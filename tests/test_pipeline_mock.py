"""用 mock 引擎 + 内存 Transport 验证级联时序，无需外部服务。"""

import asyncio

from app import ws_protocol as proto
from app.core.dialogue import Dialogue
from app.solutions.cascade.session import CascadeSession
from app.solutions.echo.engines_mock import EchoASR, EchoLLM, EchoTTS
from tests.fakes import FakeTransport, run_session_until_finished


def make_session(transport: FakeTransport, **echo_kwargs) -> CascadeSession:
    llm_opts = {"token_delay": 0.001, **echo_kwargs.pop("llm", {})}
    return CascadeSession(
        asr=EchoASR(**echo_kwargs.pop("asr", {})),
        llm=EchoLLM(**llm_opts),
        tts=EchoTTS(**echo_kwargs.pop("tts", {})),
        dialogue=Dialogue(system_prompt="测试"),
        transport=transport,
    )


async def test_text_turn_full_order():
    transport = FakeTransport()
    session = make_session(transport)

    transport.send_client_json({"type": proto.TEXT, "content": "测试问题"})
    await run_session_until_finished(transport, session)

    jsons = transport.json_frames()
    types = [m["type"] for m in jsons]
    assert types[0] == proto.TURN_STARTED
    assert types[-1] == proto.TURN_FINISHED
    assert proto.LLM_TOKEN in types
    assert transport.audio_frames(), "应有音频二进制帧"
    # 音频帧出现在 turn_finished 之前（流式下发）
    first_audio_idx = next(i for i, m in enumerate(transport.outgoing) if m.kind == "bytes")
    last_json_idx = max(
        i
        for i, m in enumerate(transport.outgoing)
        if m.kind == "text" and proto.loads(m.data).get("type") == proto.TURN_FINISHED
    )
    assert first_audio_idx < last_json_idx


async def test_audio_turn_via_mock_asr():
    transport = FakeTransport()
    session = make_session(transport, asr={"trigger_seconds": 0.1})

    # 喂 0.3 秒静音音频，应触发一次 mock ASR 识别 → asr_final → 一轮回答
    silence = b"\x00\x00" * 1600  # 0.1s @16k
    for _ in range(3):
        transport.send_client_bytes(silence)
    await run_session_until_finished(transport, session)

    jsons = transport.json_frames()
    types = [m["type"] for m in jsons]
    # 每句判停先下发 asr_final（实时字幕），再启动对应轮次
    assert types[0] == proto.ASR_FINAL
    assert jsons[0]["text"]
    assert types.index(proto.TURN_STARTED) == transport.count_type(proto.ASR_FINAL)
    assert transport.audio_frames()


async def test_ping_pong():
    transport = FakeTransport()
    session = make_session(transport)

    transport.send_client_json({"type": proto.PING})
    runner = asyncio.create_task(session.run())
    try:
        async with asyncio.timeout(2):
            while transport.count_type(proto.PONG) < 1:
                await asyncio.sleep(0.005)
    finally:
        await transport.close()
        await asyncio.wait_for(runner, timeout=2)


async def test_interrupt_cancels_turn():
    transport = FakeTransport()
    session = make_session(transport, llm={"token_delay": 0.05})

    runner = asyncio.create_task(session.run())
    try:
        transport.send_client_json({"type": proto.TEXT, "content": "这个问题"})
        await asyncio.sleep(0.1)  # 让 LLM 开始输出
        transport.send_client_json({"type": proto.INTERRUPT})
        async with asyncio.timeout(2):
            while transport.count_type(proto.TURN_FINISHED) < 1:
                await asyncio.sleep(0.005)
    finally:
        await transport.close()
        await asyncio.wait_for(runner, timeout=2)

    # 打断后仍能收到恰好一轮 turn_finished，会话不挂死
    assert transport.count_type(proto.TURN_FINISHED) == 1
    assert transport.json_frames()[0]["type"] == proto.TURN_STARTED


class RecordingLLM:
    """记录每次调用的完整 messages，验证多轮上下文是否传入。"""

    def __init__(self, reply_delay: float = 0.0):
        self.queries: list[list[dict]] = []
        self._reply_delay = reply_delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def stream_reply(self, messages: list[dict]):
        return self._stream(messages)

    async def _stream(self, messages: list[dict]):
        self.queries.append([dict(m) for m in messages])
        if self._reply_delay:
            await asyncio.sleep(self._reply_delay)
        yield "收到。"


async def test_multi_turn_context_passed_to_llm():
    transport = FakeTransport()
    llm = RecordingLLM()
    session = CascadeSession(
        asr=EchoASR(),
        llm=llm,
        tts=EchoTTS(seconds_per_char=0.001),
        dialogue=Dialogue(system_prompt="系统设定"),
        transport=transport,
    )

    transport.send_client_json({"type": proto.TEXT, "content": "第一问"})
    transport.send_client_json({"type": proto.TEXT, "content": "第二问"})
    await run_session_until_finished(transport, session, count=2)

    assert len(llm.queries) == 2
    second = llm.queries[1]
    assert second[0] == {"role": "system", "content": "系统设定"}
    roles = [m["role"] for m in second]
    # 第二轮调用应携带完整历史：user/assistant 成对且不拆散
    assert roles == ["system", "user", "assistant", "user"]
    assert [m["content"] for m in second if m["role"] == "user"] == ["第一问", "第二问"]


async def test_unknown_message_ignored():
    transport = FakeTransport()
    session = make_session(transport)
    runner = asyncio.create_task(session.run())
    try:
        transport.send_client_json({"type": "nonsense", "foo": 1})
        await asyncio.sleep(0.05)
    finally:
        await transport.close()
        await asyncio.wait_for(runner, timeout=2)


class _LifecycleSpy:
    """包一层引擎记录生命周期调用（Generic 包装保持原引擎行为）。"""

    def __init__(self, engine):
        self._engine = engine
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        await self._engine.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True
        return await self._engine.__aexit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self._engine, name)


async def test_session_manages_engine_lifecycle():
    """回归测试：会话必须进出所有引擎的异步上下文（连接在那里建立）。"""
    transport = FakeTransport()
    spies = {
        name: _LifecycleSpy(engine)
        for name, engine in [("asr", EchoASR()), ("llm", EchoLLM()), ("tts", EchoTTS())]
    }
    session = CascadeSession(
        asr=spies["asr"],
        llm=spies["llm"],
        tts=spies["tts"],
        dialogue=Dialogue(system_prompt="测试"),
        transport=transport,
    )
    transport.send_client_json({"type": proto.TEXT, "content": "hi"})
    await run_session_until_finished(transport, session)
    for spy in spies.values():
        assert spy.entered, "引擎 __aenter__ 未被调用（连接未建立）"
        assert spy.exited, "引擎 __aexit__ 未被调用（资源泄漏）"


async def test_interrupt_drops_queued_turns():
    """打断语义：丢弃排队中的输入，只有被 interrupt 的那一轮补 turn_finished。"""
    transport = FakeTransport()
    # reply_delay 保证第一轮在 interrupt 到达时仍在执行（否则排队语义测不准）
    llm = RecordingLLM(reply_delay=0.2)
    session = CascadeSession(
        asr=EchoASR(),
        llm=llm,
        tts=EchoTTS(seconds_per_char=0.001),
        dialogue=Dialogue(system_prompt="测试"),
        transport=transport,
    )
    runner = asyncio.create_task(session.run())
    try:
        transport.send_client_json({"type": proto.TEXT, "content": "第一问"})
        await asyncio.sleep(0.05)  # 第一轮进入执行
        transport.send_client_json({"type": proto.TEXT, "content": "排队的问题"})
        await asyncio.sleep(0.02)  # 入队但尚未消费
        transport.send_client_json({"type": proto.INTERRUPT})
        await asyncio.sleep(0.1)
    finally:
        await transport.close()
        await asyncio.wait_for(runner, timeout=2)

    assert transport.count_type(proto.TURN_FINISHED) == 1
    assert len(llm.queries) == 1  # 排队输入被丢弃，不产生第二轮


class _SilentASR(EchoASR):
    """final_transcripts 立即结束的 ASR：模拟上游断流。"""

    async def final_transcripts(self):
        if False:
            yield ""  # 标记为异步生成器


async def test_asr_upstream_disconnect_notified():
    """ASR 流在连接仍存活时结束 = 上游断流，前端应收到 ASR_ERROR 而非静默断开。"""

    transport = FakeTransport()
    session = CascadeSession(
        asr=_SilentASR(),
        llm=EchoLLM(),
        tts=EchoTTS(),
        dialogue=Dialogue(system_prompt="测试"),
        transport=transport,
    )
    runner = asyncio.create_task(session.run())
    try:
        async with asyncio.timeout(2):
            while transport.count_type(proto.ERROR) < 1:
                await asyncio.sleep(0.005)
    finally:
        await transport.close()
        await asyncio.wait_for(runner, timeout=2)

    errors = [m for m in transport.json_frames() if m.get("type") == proto.ERROR]
    assert errors[0]["code"] == "ASR_ERROR"
