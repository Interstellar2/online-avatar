"""前后端 WebSocket 消息协议。

帧类型：
- 二进制帧：音频（上行 PCM16 单声道 16kHz；下行 PCM16 单声道，采样率由 turn_started 下发）
- JSON 文本帧：控制消息，见下方构造函数
"""

import json
from typing import Any

# ---- 消息类型 ----
PING = "ping"
PONG = "pong"
INTERRUPT = "interrupt"
TEXT = "text"  # 客户端文字直发（跳过 ASR，调试用）
ASR_PARTIAL = "asr_partial"
ASR_FINAL = "asr_final"
LLM_TOKEN = "llm_token"
TURN_STARTED = "turn_started"
TURN_FINISHED = "turn_finished"
ERROR = "error"


def dumps(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False)


def loads(data: str) -> dict[str, Any]:
    """解析客户端文本帧；返回 {"type": ...}；非法 JSON 返回 {}。"""
    try:
        msg = json.loads(data)
        return msg if isinstance(msg, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ---- 服务端 → 客户端 ----
def pong() -> dict:
    return {"type": PONG}


def asr_partial(text: str) -> dict:
    return {"type": ASR_PARTIAL, "text": text}


def asr_final(text: str) -> dict:
    return {"type": ASR_FINAL, "text": text}


def llm_token(text: str) -> dict:
    return {"type": LLM_TOKEN, "text": text}


def turn_started(sample_rate: int) -> dict:
    return {"type": TURN_STARTED, "sample_rate": sample_rate}


def turn_finished() -> dict:
    return {"type": TURN_FINISHED}


def error(code: str, message: str) -> dict:
    return {"type": ERROR, "code": code, "message": message}
