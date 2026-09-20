from app.core.dialogue import Dialogue


def test_messages_include_system_prompt():
    d = Dialogue(system_prompt="你是助手")
    d.add_user("你好")
    d.add_assistant("你好！")
    msgs = d.messages
    assert msgs[0] == {"role": "system", "content": "你是助手"}
    assert msgs[1:] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
    ]


def test_no_system_prompt():
    d = Dialogue()
    d.add_user("hi")
    assert d.messages == [{"role": "user", "content": "hi"}]


def test_truncation_keeps_pairs():
    d = Dialogue(max_messages=4)
    for i in range(6):  # 3 轮对话
        d.add_user(f"q{i}")
        d.add_assistant(f"a{i}")
    msgs = d.messages
    assert len(msgs) == 4
    # 保留最近 4 条，且不拆散 user/assistant 对
    assert [m["content"] for m in msgs] == ["q4", "a4", "q5", "a5"]


def test_odd_max_messages_keeps_pairs():
    # max_messages 为奇数时也应保持 user/assistant 成对
    d = Dialogue(max_messages=5)
    for i in range(4):  # 4 轮 = 8 条消息
        d.add_user(f"q{i}")
        d.add_assistant(f"a{i}")
    msgs = d._messages
    assert len(msgs) % 2 == 0
    assert [m["content"] for m in msgs] == ["q2", "a2", "q3", "a3"]


def test_turn_count():
    d = Dialogue()
    assert d.turn_count == 0
    d.add_user("q")
    d.add_assistant("a")
    assert d.turn_count == 1
