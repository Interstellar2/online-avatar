"""单轮执行：LLM worker + TTS worker 并行流水线。

LLM 还在生成后续内容时，前几个句子已在合成播放（沿用旧项目并行切句思路）。
本模块只负责一轮内部的流水线；turn_started/turn_finished 的成对发送由
轮次消费者（CascadeSession._turn_consumer）保证，以免 turn 被 interrupt 取消时
finally 里的发送被二次取消打断导致起止标记不成对。
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from app.core.dialogue import Dialogue
from app.core.engines import LLMEngine, TTSEngine
from app.core.sentence import SentenceSplitter
from app.solutions.cascade.notifier import SessionNotifier

logger = logging.getLogger(__name__)


@dataclass
class TurnState:
    """一轮的内部状态（埋点 + 回复收集）。

    由单次 TurnRunner.run 独占，避免散落在会话级成员上——
    会话级可变状态的"正确性依赖 turn 严格串行"是隐式契约，显式化后由对象边界保证。
    """

    start_ts: float = 0.0
    first_audio_logged: bool = False
    reply: str = ""


class TurnRunner:
    """执行一轮问答：流式收 LLM token 并按句喂给 TTS。"""

    def __init__(
        self,
        llm: LLMEngine,
        tts: TTSEngine,
        dialogue: Dialogue,
        notifier: SessionNotifier,
    ):
        self._llm = llm
        self._tts = tts
        self._dialogue = dialogue
        self._notifier = notifier

    async def run(self, user_text: str) -> None:
        state = TurnState(start_ts=time.monotonic())
        self._dialogue.add_user(user_text)
        await self._notifier.turn_started(self._tts.output_sample_rate)
        sentence_q: asyncio.Queue[str | None] = asyncio.Queue()
        splitter = SentenceSplitter()
        llm_task = asyncio.create_task(self._llm_worker(sentence_q, splitter, state))
        tts_task = asyncio.create_task(self._tts_worker(sentence_q, state))
        try:
            await asyncio.gather(llm_task, tts_task)
        finally:
            for t in (llm_task, tts_task):
                if not t.done():
                    t.cancel()
            await asyncio.gather(llm_task, tts_task, return_exceptions=True)
            # 出错/打断导致回复不完整时，已流式下发给前端的部分也入库，
            # 保持对话历史与前端展示一致
            if state.reply:
                self._dialogue.add_assistant(state.reply)

    async def _llm_worker(
        self,
        sentence_q: asyncio.Queue[str | None],
        splitter: SentenceSplitter,
        state: TurnState,
    ) -> None:
        try:
            async for token in self._llm.stream_reply(self._dialogue.messages):
                state.reply += token
                await self._notifier.llm_token(token)
                for sentence in splitter.feed(token):
                    await sentence_q.put(sentence)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 错误透传给前端
            await self._notifier.error("LLM_ERROR", str(exc))
        finally:
            tail = splitter.flush()
            if tail:
                await sentence_q.put(tail)
            await sentence_q.put(None)

    async def _tts_worker(
        self, sentence_q: asyncio.Queue[str | None], state: TurnState
    ) -> None:
        try:
            while True:
                sentence = await sentence_q.get()
                if sentence is None:
                    return
                async for chunk in self._tts.synthesize(sentence):
                    if not state.first_audio_logged:
                        state.first_audio_logged = True
                        logger.info(
                            "[TURN-LATENCY] 判停/输入 → 首音频帧已下发: %.0fms",
                            (time.monotonic() - state.start_ts) * 1000,
                        )
                    await self._notifier.send_bytes(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 错误透传给前端
            await self._notifier.error("TTS_ERROR", str(exc))
