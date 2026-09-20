"""端到端旅程测试：真实 HTTP/WS 栈（FastAPI TestClient）× echo/cascade 方案。

旅程覆盖：
1. 文字直发完整一轮（turn_started → llm_token → 音频帧 → turn_finished）
2. 音频驱动一轮（二进制帧上行触发 ASR）
3. 打断（interrupt 中断播报）
4. 多轮连续对话
5. 心跳 ping/pong
6. 未知方案 → 错误并关闭
7. cascade 缺密钥 → CONFIG_ERROR
"""

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def connect(client: TestClient, solution: str):
    return client.websocket_connect(f"/ws/avatar/{solution}")


def recv_until_turn_finished(ws, timeout_frames: int = 5000):
    """接收一轮回答的全部帧，返回 (json_msgs, audio_bytes)。"""
    jsons, audio = [], 0
    for _ in range(timeout_frames):
        msg = ws.receive()
        if msg.get("bytes") is not None:
            audio += len(msg["bytes"])
        else:
            m = json.loads(msg["text"])
            jsons.append(m)
            if m.get("type") == "turn_finished":
                return jsons, audio
    raise AssertionError("未收到 turn_finished")


def test_journey_text_turn(client):
    with connect(client, "echo") as ws:
        ws.send_json({"type": "text", "content": "今天天气怎么样"})
        jsons, audio = recv_until_turn_finished(ws)
        types = [m["type"] for m in jsons]
        assert types[0] == "turn_started"
        assert types[-1] == "turn_finished"
        assert "llm_token" in types
        assert audio > 1000
        assert jsons[0]["sample_rate"] == 22050


def test_journey_audio_driven_turn(client):
    with connect(client, "echo") as ws:
        # 喂 1.6s 静音（EchoASR 默认 1.5s 阈值）触发一轮 mock 识别
        for _ in range(16):
            ws.send_bytes(b"\x00\x00" * 1600)
        jsons, audio = recv_until_turn_finished(ws)
        types = [m["type"] for m in jsons]
        # ASR 判停后先下发 asr_final 实时字幕，再启动轮次
        assert types[0] == "asr_final"
        assert types[1] == "turn_started"
        assert types[-1] == "turn_finished"
        assert audio > 1000


def test_journey_interrupt(client):
    with connect(client, "echo") as ws:
        ws.send_json({"type": "text", "content": "讲一个很长的故事吧"})
        ws.send_json({"type": "interrupt"})
        jsons, audio = recv_until_turn_finished(ws)
        types = [m["type"] for m in jsons]
        # 无论打断发生在哪个阶段，都必须有且仅有这一对起止标记
        assert types.count("turn_started") == 1
        assert types.count("turn_finished") == 1


def test_journey_multi_turn(client):
    with connect(client, "echo") as ws:
        finishes = 0
        ws.send_json({"type": "text", "content": "第一轮问题"})
        ws.send_json({"type": "text", "content": "第二轮问题"})
        for _ in range(10000):
            msg = ws.receive()
            if msg.get("text"):
                m = json.loads(msg["text"])
                if m.get("type") == "turn_finished":
                    finishes += 1
                    if finishes == 2:
                        break
        assert finishes == 2


def test_journey_ping_pong(client):
    with connect(client, "echo") as ws:
        ws.send_json({"type": "ping"})
        while True:
            m = json.loads(ws.receive_text())
            if m.get("type") == "pong":
                break


def test_journey_unknown_solution(client):
    with pytest.raises(WebSocketDisconnect):
        with connect(client, "nope") as ws:
            m = json.loads(ws.receive_text())
            assert m["type"] == "error"
            assert m["code"] == "UNKNOWN_SOLUTION"
            ws.receive_text()  # 服务端随后关闭连接 → WebSocketDisconnect


def test_journey_cascade_without_key(client, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(WebSocketDisconnect):
            with connect(client, "cascade") as ws:
                m = json.loads(ws.receive_text())
                assert m["type"] == "error"
                assert m["code"] == "CONFIG_ERROR"
                ws.receive_text()
    finally:
        get_settings.cache_clear()
