"""Echo mock 引擎：不依赖任何外部服务，用于验证架构与全链路时序。

- EchoASR：累计收到 N 秒音频后吐一句预设"识别结果"
- EchoLLM：围绕用户最后一条输入回一句模拟回答，逐字流式
- EchoTTS：把每个字合成一段正弦波 beep（可真实播放，验证音频通路）
"""

import asyncio
import math
import struct
from typing import AsyncIterator

BYTES_PER_SECOND_16K = 16000 * 2  # PCM16 单声道


class EchoASR:
    def __init__(self, trigger_seconds: float = 1.5, canned_texts: list[str] | None = None):
        self._trigger_bytes = int(trigger_seconds * BYTES_PER_SECOND_16K)
        self._canned = canned_texts or ["你好，请介绍一下你自己。"]
        self._idx = 0
        self._buf = bytearray()
        self._q: asyncio.Queue[str | None] = asyncio.Queue()
        self.on_partial = None  # mock 引擎无中间结果能力

    async def __aenter__(self) -> "EchoASR":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._q.put(None)

    async def send_audio(self, pcm: bytes) -> None:
        self._buf.extend(pcm)
        while len(self._buf) >= self._trigger_bytes:
            del self._buf[: self._trigger_bytes]
            text = self._canned[self._idx % len(self._canned)]
            self._idx += 1
            await self._q.put(text)

    async def finalize(self) -> None:
        return None

    async def final_transcripts(self) -> AsyncIterator[str]:
        while True:
            item = await self._q.get()
            if item is None:
                return
            yield item


class EchoLLM:
    def __init__(self, token_delay: float = 0.02):
        self._token_delay = token_delay

    async def __aenter__(self) -> "EchoLLM":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def stream_reply(self, messages: list[dict]) -> AsyncIterator[str]:
        return self._stream(messages)

    async def _stream(self, messages: list[dict]) -> AsyncIterator[str]:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        reply = f"收到，你说的是：{last_user}。这是回声方案的模拟回答，用于验证级联链路。"
        for ch in reply:
            yield ch
            await asyncio.sleep(self._token_delay)


class EchoTTS:
    """每 0.08 秒一个 beep，按句子总时长生成可播放的 PCM。"""

    output_sample_rate = 22050

    def __init__(self, seconds_per_char: float = 0.08, freq: float = 440.0):
        self._seconds_per_char = seconds_per_char
        self._freq = freq
        self._interrupted = False

    async def __aenter__(self) -> "EchoTTS":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        return self._synthesize(text)

    async def interrupt(self) -> None:
        self._interrupted = True

    async def _synthesize(self, text: str) -> AsyncIterator[bytes]:
        self._interrupted = False
        sr = self.output_sample_rate
        for ch in text:
            if self._interrupted:
                return
            duration = self._seconds_per_char * (1.5 if ch in "。！？!?" else 1.0)
            n = int(sr * duration)
            pcm = bytearray()
            for i in range(n):
                sample = 0.3 * math.sin(2 * math.pi * self._freq * i / sr)
                pcm += struct.pack("<h", int(sample * 32767))
            yield bytes(pcm)
            await asyncio.sleep(0)
