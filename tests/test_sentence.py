from app.core.sentence import SentenceSplitter


def test_no_split_until_terminator():
    s = SentenceSplitter()
    assert s.feed("你好") == []
    assert s.feed("世界") == []
    assert s.flush() == "你好世界"


def test_split_on_terminator():
    s = SentenceSplitter()
    assert s.feed("第一句。第二句") == ["第一句。"]
    assert s.feed("还没完") == []
    assert s.flush() == "第二句还没完"


def test_multiple_sentences_in_one_feed():
    s = SentenceSplitter()
    assert s.feed("甲。乙！丙？尾巴") == ["甲。", "乙！", "丙？"]
    assert s.flush() == "尾巴"


def test_closing_quote_belongs_to_sentence():
    s = SentenceSplitter()
    assert s.feed('他说"你好。"然后走了') == ['他说"你好。"']


def test_flush_returns_none_when_empty():
    s = SentenceSplitter()
    s.feed("已经结束了。")
    assert s.flush() is None


def test_max_length_force_split():
    s = SentenceSplitter(max_len=10)
    result = s.feed("一二三四五六七八九十十一十二")
    assert result == ["一二三四五六七八九十"]  # 达到 max_len 强制切，余量留缓冲
    assert s.flush() == "十一十二"


def test_newline_is_terminator():
    s = SentenceSplitter()
    assert s.feed("第一行\n第二行") == ["第一行\n"]
