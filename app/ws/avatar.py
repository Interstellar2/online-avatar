"""WebSocket 入口：/ws/avatar/{solution_name}。

路由层只做协议适配（FastAPI WebSocket ↔ Transport）和方案分发，
业务编排全部在方案层。
"""

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import ws_protocol as proto
from app.config import get_settings
from app.core.transport import Transport, WSMessage
from app.solutions import get_solution
from app.solutions.registry import list_solutions

router = APIRouter()


class FastAPITransport:
    def __init__(self, ws: WebSocket):
        self._ws = ws

    async def recv(self) -> WSMessage:
        message = await self._ws.receive()
        if message.get("bytes") is not None:
            return WSMessage(kind="bytes", data=message["bytes"])
        if message.get("text") is not None:
            return WSMessage(kind="text", data=message["text"])
        return WSMessage(kind="close")  # disconnect / close 帧

    async def send_json(self, message: dict) -> None:
        await self._ws.send_text(proto.dumps(message))

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)

    async def close(self, reason: str = "") -> None:
        await self._ws.close(reason=reason)


@router.websocket("/ws/avatar/{solution_name}")
async def avatar_endpoint(websocket: WebSocket, solution_name: str) -> None:
    await websocket.accept()
    settings = get_settings()
    # 音频编码协商：?codec=opus 启用 Opus，缺省/未知值一律退回 PCM 透传
    codec = websocket.query_params.get("codec", "pcm")
    try:
        solution = get_solution(solution_name, settings)
    except KeyError:
        transport = FastAPITransport(websocket)
        available = ", ".join(list_solutions())
        await transport.send_json(
            proto.error("UNKNOWN_SOLUTION", f"未知方案 '{solution_name}'，可选: {available}")
        )
        await websocket.close()
        return
    try:
        await solution.handle(
            FastAPITransport(websocket), session_id=uuid.uuid4().hex, codec=codec
        )
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass  # 连接已关闭
