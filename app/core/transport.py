"""传输层抽象：方案层只面向 Transport 编程，与具体 WS 框架解耦。

一条连接上二进制帧（音频）与 JSON 文本帧（控制消息）混用。
测试时可用内存 FakeTransport 替代，实现 pipeline 的时序级单元测试。
"""

from dataclasses import dataclass
from typing import Literal, Protocol, Union

MessageKind = Literal["bytes", "text", "close"]


@dataclass
class WSMessage:
    kind: MessageKind
    # bytes 帧为原始音频；text 帧为 JSON 字符串；close 时 data 为关闭原因
    data: Union[bytes, str, None] = None


class Transport(Protocol):
    """双向消息通道。recv 在连接关闭时返回 WSMessage(kind="close")。"""

    async def recv(self) -> WSMessage: ...

    async def send_json(self, message: dict) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def close(self, reason: str = "") -> None: ...


class ConnectionClosed(Exception):
    """对端关闭连接。"""
