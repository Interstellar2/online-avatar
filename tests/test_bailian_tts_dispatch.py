"""BailianTTS 事件分发逻辑测试（FakeWS，不联网）。

锁定重构后的行为：run-task → task-started 后自动发 continue-task/finish-task，
task-finished 终止循环，task-failed 抛错，未知事件被忽略。
"""

import json

import pytest

from app.core.engines import EngineError
from app.solutions.cascade.engines_bailian import BailianTTS


class FakeWS:
    """记录发送、按脚本产出消息的异步迭代器。"""

    def __init__(self, script: list[bytes | str]):
        self._script = list(script)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._script:
            raise StopAsyncIteration
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _event(name: str, **header_extra) -> str:
    header = {"event": name, **header_extra}
    return json.dumps({"header": header, "payload": {}})


@pytest.fixture
def patch_connect(monkeypatch):
    """把 websockets.connect 替换为返回预置 FakeWS 的桩。"""
    holder: dict[str, FakeWS] = {}

    async def fake_connect(_url, **_kwargs):
        return holder["ws"]

    monkeypatch.setattr(
        "app.solutions.cascade.engines_bailian.websockets.connect", fake_connect
    )
    return holder


def make_tts() -> BailianTTS:
    return BailianTTS(
        api_key="k", model="cosyvoice-v3-flash", voice="longanyang",
        ws_url="wss://example", output_sample_rate=22050,
    )


def make_running_tts(patch_connect, script):
    ws = FakeWS(script)
    patch_connect["ws"] = ws
    return make_tts(), ws


async def test_task_started_sends_continue_and_finish(patch_connect):
    tts, ws = make_running_tts(patch_connect, [_event("task-started"), b"\x01\x02", _event("task-finished")])
    audio = b"".join([c async for c in tts._synthesize("你好")])

    actions = [json.loads(s)["header"]["action"] for s in ws.sent]
    assert actions == ["run-task", "continue-task", "finish-task"]
    assert json.loads(ws.sent[1])["payload"]["input"]["text"] == "你好"
    assert audio == b"\x01\x02"
    assert ws.closed


async def test_task_failed_raises(patch_connect):
    tts, ws = make_running_tts(patch_connect, [_event("task-started"), _event("task-failed", error_message="boom")])
    with pytest.raises(EngineError, match="boom"):
        async for _ in tts._synthesize("你好"):
            pass


async def test_unknown_event_ignored(patch_connect):
    tts, ws = make_running_tts(
        patch_connect, [_event("result-generated"), _event("task-started"), _event("task-finished")]
    )
    async for _ in tts._synthesize("你好"):
        pass  # 不抛错即可


async def test_event_name_fallback_key(patch_connect):
    # 部分事件用 event_name 字段
    tts, ws = make_running_tts(
        patch_connect,
        [json.dumps({"header": {"event_name": "task-started"}}), _event("task-finished")],
    )
    async for _ in tts._synthesize("你好"):
        pass
    assert len(ws.sent) == 3  # run-task + continue-task + finish-task


async def test_close_before_task_started_raises(patch_connect):
    tts, ws = make_running_tts(patch_connect, [])  # 立即结束
    with pytest.raises(EngineError, match="before task-started"):
        async for _ in tts._synthesize("你好"):
            pass
