"""阿里云百炼引擎实现（原始 WebSocket 协议，asyncio 原生）。

- ASR: qwen3-asr-flash-realtime（/api-ws/v1/realtime，OpenAI realtime 风格事件，
  服务端 VAD 自动判停，产出最终句子）
- LLM: qwen-plus（OpenAI 兼容 HTTP，SSE 流式）
- TTS: cosyvoice-v3-flash（/api-ws/v1/inference，run-task/continue-task/finish-task
  协议，二进制帧收 PCM，每句独立连接实现打断）

文档：
- https://help.aliyun.com/zh/model-studio/asr-model （实时语音识别原始协议）
- https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide （CosyVoice 原始协议）
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
import websockets

from app.config import Settings
from app.core.engines import EngineError, EngineSet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ASR
# ---------------------------------------------------------------------------
class BailianASR:
    """qwen3-asr-flash-realtime：上行 base64 PCM 帧，服务端 VAD 判停后回最终句子。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        ws_url: str,
        sample_rate: int = 16000,
        vad_threshold: float = 0.2,
        vad_silence_ms: int = 400,
        ping_interval: int = 20,
        on_partial=None,
    ):
        self._api_key = api_key
        self._model = model
        self._ws_url = ws_url
        self._sample_rate = sample_rate
        self._vad_threshold = vad_threshold
        self._vad_silence_ms = vad_silence_ms
        self._ping_interval = ping_interval
        self.on_partial = on_partial  # 可选同步回调: (text) -> None，会话层注入
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._final_q: asyncio.Queue[str | None] = asyncio.Queue()
        # 事件分发表：事件类型 → 处理器（替代 if/elif 链）
        self._event_handlers = {
            "conversation.item.input_audio_transcription.completed": self._on_transcription_completed,
            "conversation.item.input_audio_transcription.partial": self._on_transcription_partial,
            "session.finished": self._on_session_finished,
            "error": self._on_session_finished,
        }

    async def __aenter__(self) -> "BailianASR":
        url = f"{self._ws_url}?model={self._model}"
        self._ws = await websockets.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
            ping_interval=self._ping_interval,
        )
        self._reader = asyncio.create_task(self._read_loop())
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "input_audio_format": "pcm",
                    "sample_rate": self._sample_rate,
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": self._vad_threshold,
                        "silence_duration_ms": self._vad_silence_ms,
                    },
                },
            }
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._reader is not None:
            self._reader.cancel()
        if self._ws is not None:
            await self._ws.close()
        await self._final_q.put(None)

    async def send_audio(self, pcm: bytes) -> None:
        if self._ws is None:
            raise EngineError("ASR connection not established")
        await self._send(
            {
                "event_id": f"event_{uuid.uuid4().hex}",
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode(),
            }
        )

    async def finalize(self) -> None:
        await self._send({"type": "session.finish"})

    async def final_transcripts(self) -> AsyncIterator[str]:
        while True:
            item = await self._final_q.get()
            if item is None:
                return
            yield item

    async def _send(self, message: dict) -> None:
        await self._ws.send(json.dumps(message))

    # ---- ASR 事件处理器 ----

    async def _on_transcription_completed(self, event: dict) -> None:
        transcript = event.get("transcript") or ""
        if transcript.strip():
            await self._final_q.put(transcript)

    async def _on_transcription_partial(self, event: dict) -> None:
        if self.on_partial is not None:
            self.on_partial(event.get("transcript") or "")

    async def _on_session_finished(self, _event: dict) -> None:
        await self._final_q.put(None)

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                handler = self._event_handlers.get(event.get("type", ""))
                if handler is not None:
                    await handler(event)
        except websockets.ConnectionClosed:
            pass
        finally:
            await self._final_q.put(None)


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
class BailianLLM:
    """qwen-plus：OpenAI 兼容 chat/completions，SSE 流式增量 token。"""

    def __init__(self, api_key: str, model: str, base_url: str):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        # client 延迟到 __aenter__ 创建、__aexit__ 释放：
        # 生命周期绑定会话，避免每条连接泄漏一个 client + 连接池
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BailianLLM":
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def stream_reply(self, messages: list[dict]) -> AsyncIterator[str]:
        return self._stream(messages)

    async def _stream(self, messages: list[dict]) -> AsyncIterator[str]:
        if self._client is None:
            raise EngineError("LLM client 未初始化：须在 async with 内使用")
        payload = {"model": self._model, "messages": messages, "stream": True}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with self._client.stream(
            "POST", f"{self._base_url}/chat/completions", json=payload, headers=headers
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise EngineError(f"LLM HTTP {resp.status_code}: {body[:200]!r}")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices", []):
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield delta


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
class BailianTTS:
    """cosyvoice-v3-flash：每句一条 WebSocket 连接（run-task 协议）。

    每句独立连接换来简单的打断语义（interrupt = 关闭当前连接），
    代价是每句多一次建连耗时；首句延迟受 pipeline 并行流水掩盖。
    后续优化方向：单连接复用 + finish-task(cancel)。
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        voice: str,
        ws_url: str,
        output_sample_rate: int = 22050,
        volume: int = 50,
        rate: float = 1.0,
        pitch: float = 1.0,
        ping_interval: int = 20,
    ):
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._ws_url = ws_url
        self.output_sample_rate = output_sample_rate
        self._volume = volume
        self._rate = rate
        self._pitch = pitch
        self._ping_interval = ping_interval
        self._current_ws: websockets.ClientConnection | None = None

    async def __aenter__(self) -> "BailianTTS":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.interrupt()

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        return self._synthesize(text)

    async def interrupt(self) -> None:
        ws, self._current_ws = self._current_ws, None
        if ws is not None:
            await ws.close()

    # ---- TTS 事件处理器（由 _TTS_EVENT_HANDLERS 注册表分发）----
    # 返回 True 表示任务终结，合成循环应退出。

    async def _ev_task_started(self, state: "_SynthState", _header: dict) -> bool:
        state.started = True
        state.t_started = time.monotonic()
        await state.ws.send(
            json.dumps(
                {
                    "header": {
                        "action": "continue-task",
                        "task_id": state.task_id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {"text": state.text}},
                }
            )
        )
        await state.ws.send(
            json.dumps(
                {
                    "header": {
                        "action": "finish-task",
                        "task_id": state.task_id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {}},
                }
            )
        )
        return False

    async def _ev_task_finished(self, state: "_SynthState", _header: dict) -> bool:
        logger.info(
            "[TTS-LATENCY] text_len=%d total=%.0fms (任务完成)",
            len(state.text),
            (time.monotonic() - state.t0) * 1000,
        )
        return True

    async def _ev_task_failed(self, _state: "_SynthState", header: dict) -> bool:
        raise EngineError(f"TTS task failed: {header.get('error_message')}")

    def _log_first_frame(self, state: "_SynthState") -> None:
        if state.t_first_frame is not None:
            return
        state.t_first_frame = time.monotonic()
        logger.info(
            "[TTS-LATENCY] text_len=%d connect=%.0fms started=%.0fms "
            "first_frame=%.0fms (首音频帧已到达)",
            len(state.text),
            (state.t_connected - state.t0) * 1000,
            (state.t_started - state.t_connected) * 1000 if state.t_started else -1,
            (state.t_first_frame - state.t_connected) * 1000,
        )

    async def _synthesize(self, text: str) -> AsyncIterator[bytes]:
        # 延迟埋点：连接建立 / task-started / 首音频帧 / 任务结束
        t0 = time.monotonic()
        task_id = uuid.uuid4().hex
        ws = await websockets.connect(
            self._ws_url,
            additional_headers={
                "Authorization": f"bearer {self._api_key}",
                # 合规数据检查头，属固定行为而非调参，故不进 Settings
                "X-DashScope-DataInspection": "enable",
            },
            ping_interval=self._ping_interval,
        )
        self._current_ws = ws
        try:
            await ws.send(
                json.dumps(
                    {
                        "header": {
                            "action": "run-task",
                            "task_id": task_id,
                            "streaming": "duplex",
                        },
                        "payload": {
                            "task_group": "audio",
                            "task": "tts",
                            "function": "SpeechSynthesizer",
                            "model": self._model,
                            "parameters": {
                                "text_type": "PlainText",
                                "voice": self._voice,
                                "format": "pcm",
                                "sample_rate": self.output_sample_rate,
                                "volume": self._volume,
                                "rate": self._rate,
                                "pitch": self._pitch,
                            },
                            "input": {},
                        },
                    }
                )
            )
            state = _SynthState(
                ws=ws, task_id=task_id, text=text,
                t0=t0, t_connected=time.monotonic(),
            )
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    self._log_first_frame(state)
                    yield bytes(raw)
                    continue
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                header = event.get("header") or {}
                name = header.get("event") or header.get("event_name") or ""
                handler = _TTS_EVENT_HANDLERS.get(name)
                if handler is not None and await handler(self, state, header):
                    return  # 处理器返回 True = 任务终结（finished/failed）
            if not state.started:
                raise EngineError("TTS connection closed before task-started")
        finally:
            if self._current_ws is ws:
                self._current_ws = None
            await ws.close()


@dataclass
class _SynthState:
    """单次合成任务的循环内状态，事件处理器共享。"""

    ws: websockets.ClientConnection
    task_id: str
    text: str
    t0: float  # 开始建连时间
    t_connected: float
    started: bool = False
    t_started: float | None = None
    t_first_frame: float | None = None


# TTS 事件分发表：事件名 → 处理器（替代 if/elif 链）
_TTS_EVENT_HANDLERS = {
    "task-started": BailianTTS._ev_task_started,
    "task-finished": BailianTTS._ev_task_finished,
    "task-failed": BailianTTS._ev_task_failed,
}


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------
def build_engines(settings: Settings) -> EngineSet:
    """按配置构造三引擎（仅构造，连接在会话内经 EngineSet 异步上下文建立）。"""
    if not settings.dashscope_api_key:
        raise EngineError("DASHSCOPE_API_KEY 未配置")
    return EngineSet(
        asr=BailianASR(
            api_key=settings.dashscope_api_key,
            model=settings.asr_model,
            ws_url=settings.asr_ws_url,
            sample_rate=settings.input_audio_sample_rate,
            vad_threshold=settings.asr_vad_threshold,
            vad_silence_ms=settings.asr_vad_silence_ms,
            ping_interval=settings.upstream_ping_interval,
        ),
        llm=BailianLLM(
            api_key=settings.dashscope_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        ),
        tts=BailianTTS(
            api_key=settings.dashscope_api_key,
            model=settings.tts_model,
            voice=settings.tts_voice,
            ws_url=settings.tts_ws_url,
            output_sample_rate=settings.tts_sample_rate,
            volume=settings.tts_volume,
            rate=settings.tts_rate,
            pitch=settings.tts_pitch,
            ping_interval=settings.upstream_ping_interval,
        ),
    )
