"""会话外壳：WS 接收循环与客户端消息分发。

与具体方案无关的通用脚手架（recv 循环、ping/pong、消息分发表），
方案层以回调接入音频帧 / 文字 / 打断三类事件；
将来 omni 方案可直接复用，不再重写 ping/interrupt/recv 样板。
"""

from collections.abc import Awaitable, Callable

from app import ws_protocol as proto
from app.core.transport import Transport, WSMessage
from app.solutions.cascade.notifier import SessionNotifier

# 方案层回调签名：音频帧异步处理；文字入队即可（同步）；打断需异步清理
OnBytes = Callable[[bytes], Awaitable[None]]
OnText = Callable[[str], Awaitable[None]]
OnInterrupt = Callable[[], Awaitable[None]]


class SessionShell:
    """托管一条连接的接收侧：recv 循环 + 客户端消息分发表。"""

    def __init__(
        self,
        transport: Transport,
        notifier: SessionNotifier,
        on_bytes: OnBytes | None = None,
        on_text: OnText | None = None,
        on_interrupt: OnInterrupt | None = None,
    ):
        self._transport = transport
        self._notifier = notifier
        self._on_bytes = on_bytes
        self._on_text = on_text
        self._on_interrupt = on_interrupt
        # 客户端消息分发表：消息类型 → 处理器（替代 if/elif 链）
        self._client_handlers = {
            proto.PING: self._on_ping,
            proto.INTERRUPT: self._on_interrupt_msg,
            proto.TEXT: self._on_text_message,
        }

    async def serve(self) -> None:
        """接收循环：收到 close 帧正常返回；二进制帧与 JSON 文本帧按类型分发。"""
        while True:
            msg: WSMessage = await self._transport.recv()
            if msg.kind == "close":
                return
            if msg.kind == "bytes":
                if self._on_bytes is not None:
                    await self._on_bytes(msg.data)
                continue
            client = proto.loads(msg.data if isinstance(msg.data, str) else "")
            handler = self._client_handlers.get(client.get("type"))
            if handler is not None:
                await handler(client)

    # ---- 内置处理器（ping/pong 与所有方案语义一致，由外壳统一应答）----

    async def _on_ping(self, _msg: dict) -> None:
        await self._notifier.pong()

    async def _on_interrupt_msg(self, _msg: dict) -> None:
        if self._on_interrupt is not None:
            await self._on_interrupt()

    async def _on_text_message(self, msg: dict) -> None:
        if self._on_text is not None:
            content = (msg.get("content") or "").strip()
            if content:
                await self._on_text(content)
