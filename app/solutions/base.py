"""方案层抽象。

一套"方案"= 一种数字人对话实现方式（级联 / omni 端到端 / GPT-Live / 推流版等）。
方案接管整条 WebSocket 连接的生命周期；新增方案只需实现本协议并注册进 registry，
即可通过 /ws/avatar/{solution_name} 并存对比。
"""

from typing import Protocol, runtime_checkable

from app.core.transport import Transport


@runtime_checkable
class Solution(Protocol):
    name: str

    async def handle(self, transport: Transport, session_id: str) -> None:
        """接管一条 WS 连接直到关闭，内部完成 ASR/LLM/TTS 的全部编排。"""
        ...
