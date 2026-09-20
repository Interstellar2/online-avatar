"""会话通知器：把协议消息的构造与发送从方案编排中收拢到一处。

方案层只面向本模块编程，协议字段变化只需改这里（与 ws_protocol 同步）。
"""

from app import ws_protocol as proto
from app.core.transport import Transport


class SessionNotifier:
    """包装 Transport，提供语义化的会话通知方法。"""

    def __init__(self, transport: Transport):
        self._transport = transport

    async def pong(self) -> None:
        await self._transport.send_json(proto.pong())

    async def asr_partial(self, text: str) -> None:
        await self._transport.send_json(proto.asr_partial(text))

    async def asr_final(self, text: str) -> None:
        await self._transport.send_json(proto.asr_final(text))

    async def turn_started(self, sample_rate: int) -> None:
        await self._transport.send_json(proto.turn_started(sample_rate))

    async def llm_token(self, token: str) -> None:
        await self._transport.send_json(proto.llm_token(token))

    async def turn_finished(self) -> None:
        await self._transport.send_json(proto.turn_finished())

    async def error(self, code: str, message: str) -> None:
        await self._transport.send_json(proto.error(code, message))

    async def send_bytes(self, data: bytes) -> None:
        """音频等原始二进制帧不走协议构造，直接透传传输层。"""
        await self._transport.send_bytes(data)
