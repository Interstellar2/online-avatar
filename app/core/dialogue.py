"""多轮对话上下文管理。"""

DEFAULT_MAX_MESSAGES = 20  # 保留的消息条数（user/assistant 各算一条）


class Dialogue:
    def __init__(self, system_prompt: str = "", max_messages: int = DEFAULT_MAX_MESSAGES):
        self._system_prompt = system_prompt
        self._max_messages = max_messages
        self._messages: list[dict] = []

    def add_user(self, text: str) -> None:
        self._append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self._append({"role": "assistant", "content": text})

    @property
    def messages(self) -> list[dict]:
        """OpenAI chat 兼容格式的完整消息列表（含 system）。"""
        if self._system_prompt:
            return [{"role": "system", "content": self._system_prompt}, *self._messages]
        return list(self._messages)

    @property
    def turn_count(self) -> int:
        return len(self._messages) // 2

    def _append(self, message: dict) -> None:
        self._messages.append(message)
        if len(self._messages) > self._max_messages:
            # 截掉最早的若干条，保持偶数对齐（不拆散 user/assistant 对）
            overflow = len(self._messages) - self._max_messages
            overflow += overflow % 2
            del self._messages[:overflow]
