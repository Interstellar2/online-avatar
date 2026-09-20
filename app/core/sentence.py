"""流式切句器：把 LLM 增量 token 切成可送 TTS 的完整句子。

沿用旧方案（total-product-microservices）的思路：LLM 每切出一个完整句子
即开始合成，不等整段回答生成完毕，实现 LLM 与 TTS 的并行流水。
"""

# 句末终止标点
_TERMINATORS = "。！？；!?;\n"
# 终止标点后可跟随的闭合符号（引号、括号等），归入同一句
_CLOSERS = "」』”’\"')]}）】》"

# 兜底：单句过长时强制切分，避免 TTS 输入过大
MAX_SENTENCE_LEN = 200


class SentenceSplitter:
    def __init__(self, max_len: int = MAX_SENTENCE_LEN):
        self._buf = ""
        self._max_len = max_len

    def feed(self, text: str) -> list[str]:
        """喂入增量文本，返回本批切出的完整句子（可能为空列表）。"""
        self._buf += text
        return self._drain(force=False)

    def flush(self) -> str | None:
        """流结束时把缓冲剩余文本作为最后半句取出（无终止标点的情况）。"""
        sentences = self._drain(force=True)
        return sentences[0] if sentences else None

    def _drain(self, force: bool) -> list[str]:
        sentences: list[str] = []
        while self._buf:
            cut = self._find_cut()
            if cut is not None:
                sentence, self._buf = self._buf[:cut], self._buf[cut:]
                sentences.append(sentence)
            elif not force and len(self._buf) >= self._max_len:
                sentence, self._buf = self._buf[: self._max_len], self._buf[self._max_len :]
                sentences.append(sentence)
            elif force:
                sentences.append(self._buf)
                self._buf = ""
            else:
                break
        return sentences

    def _find_cut(self) -> int | None:
        """返回第一个切分点（终止标点 + 可选闭合符号之后）的下标；无则 None。"""
        positions = [self._buf.find(p) for p in _TERMINATORS if p in self._buf]
        if not positions:
            return None
        idx = min(positions) + 1
        while idx < len(self._buf) and self._buf[idx] in _CLOSERS:
            idx += 1
        return idx
