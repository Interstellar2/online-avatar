"""Echo mock 引擎行为测试。"""

import asyncio
import struct

from app.solutions.echo.engines_mock import EchoASR, EchoLLM, EchoTTS


async def test_echo_asr_triggers_by_audio_volume():
    asr = EchoASR(trigger_seconds=0.5)  # 0.5s × 32000 字节/秒 = 16000 字节阈值
    async with asr:
        await asr.send_audio(b"\x00" * 15999)  # 阈值差 1 字节，不触发
        assert asr._q.empty()
        await asr.send_audio(b"\x00")  # 累计达到阈值，触发一次识别
        assert await asyncio.wait_for(asr._q.get(), 1) == "你好，请介绍一下你自己。"


async def test_echo_asr_cycles_canned_texts():
    texts = ["问题一", "问题二"]
    asr = EchoASR(trigger_seconds=0.1, canned_texts=texts)
    async with asr:
        frame = b"\x00\x00" * 1600
        for i in range(2):
            await asr.send_audio(frame)
            assert await asr.final_transcripts().__anext__() == texts[i]


async def test_echo_llm_streams_chars_of_reply():
    llm = EchoLLM(token_delay=0)
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "今天天气如何"},
    ]
    chunks = [t async for t in llm.stream_reply(messages)]
    full = "".join(chunks)
    assert "今天天气如何" in full
    assert len(chunks) == len(full)  # 逐字流式


async def test_echo_llm_without_user_message():
    llm = EchoLLM(token_delay=0)
    full = "".join([t async for t in llm.stream_reply([{"role": "system", "content": "s"}])])
    assert "收到" in full


async def test_echo_tts_generates_valid_pcm():
    tts = EchoTTS(seconds_per_char=0.01)
    async with tts:
        audio = b"".join([c async for c in tts.synthesize("你好")])
    assert len(audio) > 0
    assert len(audio) % 2 == 0  # PCM16 对齐
    sample = struct.unpack("<h", audio[:2])[0]
    assert -32768 <= sample <= 32767


async def test_echo_tts_interrupt_stops_generation():
    tts = EchoTTS(seconds_per_char=0.05)
    async with tts:
        gen = tts.synthesize("很长的一句话用来测试打断")
        chunks = []
        async for c in gen:
            chunks.append(c)
            await tts.interrupt()  # 第一帧后立即打断
            break
        rest = b"".join([c async for c in gen])
        # 打断后续部分应显著短于完整生成
        full = b"".join([c async for c in tts.synthesize("很长的一句话用来测试打断")])
    assert len(rest) < len(full) * 0.9
