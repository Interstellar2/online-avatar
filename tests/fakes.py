"""测试共享假件与助手：内存 Transport + 会话驱动工具。

FakeTransport 是实现 core.transport.Transport 协议的内存假件，
方案级测试（pipeline 时序、未来的 omni 方案）都可复用。
"""

import asyncio
import json

from app import ws_protocol as proto
from app.core.transport import WSMessage


class FakeTransport:
    """内存 Transport：incoming 由测试喂入，outgoing 记录所有发出的帧。"""

    def __init__(self):
        self.incoming: asyncio.Queue[WSMessage] = asyncio.Queue()
        self.outgoing: list[WSMessage] = []

    async def recv(self) -> WSMessage:
        return await self.incoming.get()

    async def send_json(self, message: dict) -> None:
        self.outgoing.append(WSMessage(kind="text", data=json.dumps(message, ensure_ascii=False)))

    async def send_bytes(self, data: bytes) -> None:
        self.outgoing.append(WSMessage(kind="bytes", data=data))

    async def close(self, reason: str = "") -> None:
        await self.incoming.put(WSMessage(kind="close"))

    # ---- 测试辅助 ----

    def send_client_json(self, message: dict) -> None:
        self.incoming.put_nowait(WSMessage(kind="text", data=json.dumps(message, ensure_ascii=False)))

    def send_client_bytes(self, data: bytes) -> None:
        self.incoming.put_nowait(WSMessage(kind="bytes", data=data))

    def json_frames(self) -> list[dict]:
        return [json.loads(m.data) for m in self.outgoing if m.kind == "text"]

    def audio_frames(self) -> list[bytes]:
        return [m.data for m in self.outgoing if m.kind == "bytes"]

    def count_type(self, msg_type: str) -> int:
        return sum(1 for m in self.json_frames() if m.get("type") == msg_type)


async def run_session_until_finished(
    transport: FakeTransport, session, *, count: int = 1, timeout: float = 2
) -> None:
    """驱动一次会话直到收到 count 条 turn_finished：起 runner → 等待 → 关闭 → 回收。

    会话收尾的统一样板（此前在多个用例里重复手写）。
    """
    runner = asyncio.create_task(session.run())
    try:
        async with asyncio.timeout(timeout):
            while transport.count_type(proto.TURN_FINISHED) < count:
                await asyncio.sleep(0.005)
    finally:
        await transport.close()
        await asyncio.wait_for(runner, timeout=timeout)
