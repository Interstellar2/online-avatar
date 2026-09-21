"""前后端消息协议构造函数与解析测试。"""

from app import ws_protocol as proto


def test_roundtrip_server_messages():
    for msg in [
        proto.pong(),
        proto.asr_partial("识别中"),
        proto.asr_final("最终结果"),
        proto.llm_token("token"),
        proto.turn_started(22050),
        proto.turn_finished(),
        proto.error("E", "msg"),
    ]:
        parsed = proto.loads(proto.dumps(msg))
        assert parsed == msg


def test_turn_started_carries_sample_rate():
    assert proto.turn_started(24000)["sample_rate"] == 24000


def test_turn_started_carries_codec():
    assert proto.turn_started(22050)["codec"] == "pcm"  # 缺省向后兼容
    assert proto.turn_started(22050, codec="opus")["codec"] == "opus"


def test_loads_invalid_json():
    assert proto.loads("not-json") == {}
    assert proto.loads('["list"]') == {}
    assert proto.loads("123") == {}


def test_loads_unicode_preserved():
    msg = proto.loads(proto.dumps(proto.asr_final("你好，世界")))
    assert msg["text"] == "你好，世界"


def test_client_message_shapes():
    # 协议约定的客户端消息结构（与 web/src/types.ts 对齐）
    assert proto.loads('{"type":"ping"}') == {"type": "ping"}
    assert proto.loads('{"type":"interrupt"}') == {"type": "interrupt"}
    text = proto.loads('{"type":"text","content":"你好"}')
    assert text == {"type": "text", "content": "你好"}
