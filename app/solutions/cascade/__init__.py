"""方案一：ASR → LLM → TTS 级联（阿里云百炼）。"""

from app import ws_protocol as proto
from app.config import Settings
from app.core.dialogue import Dialogue
from app.core.engines import EngineError, EngineSet
from app.core.transport import Transport
from app.solutions.cascade.engines_bailian import build_engines
from app.solutions.cascade.session import CascadeSession


class CascadeSolutionBase:
    """级联方案公共装配：构建引擎 → 运行会话。

    子类只需提供引擎工厂与 system prompt 来源（配置或硬编码），
    echo 等复用级联管线的方案不再需要照抄 handle()。
    """

    name = ""

    def __init__(self, settings: Settings):
        self._settings = settings

    def _build_engines(self, settings: Settings) -> EngineSet:
        raise NotImplementedError

    def _system_prompt(self, settings: Settings) -> str:
        raise NotImplementedError

    async def handle(
        self, transport: Transport, session_id: str, codec: str = "pcm"
    ) -> None:
        try:
            engines = self._build_engines(self._settings)
        except EngineError as exc:
            await transport.send_json(proto.error("CONFIG_ERROR", str(exc)))
            return
        session = CascadeSession(
            engines.asr,
            engines.llm,
            engines.tts,
            dialogue=Dialogue(system_prompt=self._system_prompt(self._settings)),
            transport=transport,
            session_id=session_id,
            codec=codec,
            input_sample_rate=self._input_sample_rate(self._settings),
        )
        await session.run()

    def _input_sample_rate(self, settings: Settings) -> int:
        return settings.input_audio_sample_rate


class CascadeSolution(CascadeSolutionBase):
    name = "cascade"

    def _build_engines(self, settings: Settings) -> EngineSet:
        return build_engines(settings)

    def _system_prompt(self, settings: Settings) -> str:
        return settings.llm_system_prompt
