"""BailianASR 协议逻辑测试（FakeWS，不联网）。

锁定：建连 URL/鉴权头、session.update 的 VAD 参数、transcription.completed
产出最终句子、partial 走 on_partial 回调、send_audio 的 base64 编码、
未建连时报 EngineError。
"""

import base64
import json

import pytest

from app.core.engines import EngineError
from app.solutions.cascade.engines_bailian import BailianASR


class FakeWS:
    """按脚本产出消息的异步迭代器，记录 send/close。"""

    def __init__(self, script: list[str]):
        self._script = list(script)
        self.sent: list[str] = []
        self.closed = False
        self._iter = None

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._script:
            raise StopAsyncIteration
        return self._script.pop(0)


@pytest.fixture
def patch_connect(monkeypatch):
    """把 websockets.connect 替换为返回预置 FakeWS 的桩，并记录建连参数。"""
    calls: dict[str, list] = {"kwargs": []}
    holder: dict[str, FakeWS] = {}

    async def fake_connect(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return holder["ws"]

    monkeypatch.setattr(
        "app.solutions.cascade.engines_bailian.websockets.connect", fake_connect
    )
    return holder, calls


def _event(event_type: str, **extra) -> str:
    return json.dumps({"type": event_type, **extra})


def make_asr(**kwargs) -> BailianASR:
    return BailianASR(
        api_key="test-key", model="qwen3-asr", ws_url="wss://example/realtime",
        sample_rate=16000, **kwargs,
    )


async def test_connect_url_and_auth(patch_connect):
    holder, calls = patch_connect
    holder["ws"] = FakeWS([])
    asr = make_asr(ping_interval=7)
    async with asr:
        pass

    assert calls["url"] == "wss://example/realtime?model=qwen3-asr"
    headers = calls["kwargs"]["additional_headers"]
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["OpenAI-Beta"] == "realtime=v1"
    assert calls["kwargs"]["ping_interval"] == 7


async def test_session_update_parameters(patch_connect):
    holder, _ = patch_connect
    ws = FakeWS([])
    holder["ws"] = ws
    asr = make_asr(vad_threshold=0.5, vad_silence_ms=800)
    async with asr:
        pass

    update = json.loads(ws.sent[0])
    assert update["type"] == "session.update"
    session = update["session"]
    assert session["sample_rate"] == 16000
    assert session["turn_detection"] == {
        "type": "server_vad",
        "threshold": 0.5,
        "silence_duration_ms": 800,
    }


async def test_completed_event_yields_final_transcript(patch_connect):
    holder, _ = patch_connect
    holder["ws"] = FakeWS(
        [_event("conversation.item.input_audio_transcription.completed", transcript=" 你好  "),
         _event("session.finished")]
    )
    asr = make_asr()
    async with asr:
        texts = [t async for t in asr.final_transcripts()]
    assert texts == [" 你好  "]  # 是否 strip 由会话层决定，引擎原样透传


async def test_partial_event_goes_to_callback_not_final(patch_connect):
    holder, _ = patch_connect
    holder["ws"] = FakeWS(
        [_event("conversation.item.input_audio_transcription.partial", transcript="今"),
         _event("conversation.item.input_audio_transcription.completed", transcript="今天"),
         _event("session.finished")]
    )
    partials: list[str] = []
    asr = make_asr(on_partial=partials.append)
    async with asr:
        finals = [t async for t in asr.final_transcripts()]
    assert partials == ["今"]
    assert finals == ["今天"]


async def test_send_audio_base64_encodes_pcm(patch_connect):
    holder, _ = patch_connect
    ws = FakeWS([])
    holder["ws"] = ws
    asr = make_asr()
    async with asr:
        await asr.send_audio(b"\x01\x02")
        # 等 read loop（空脚本）结束不影响断言
    append = json.loads(ws.sent[1])
    assert append["type"] == "input_audio_buffer.append"
    assert base64.b64decode(append["audio"]) == b"\x01\x02"


async def test_send_audio_before_enter_raises():
    asr = make_asr()
    with pytest.raises(EngineError, match="not established"):
        await asr.send_audio(b"\x00")


async def test_exit_closes_connection(patch_connect):
    holder, _ = patch_connect
    ws = FakeWS([])
    holder["ws"] = ws
    asr = make_asr()
    async with asr:
        pass
    assert ws.closed
