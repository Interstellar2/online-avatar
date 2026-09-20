"""Echo 方案：用 mock 引擎复用级联管线，验证架构可插拔性（无需 API key）。"""

from app.config import Settings
from app.core.engines import EngineSet
from app.solutions.cascade import CascadeSolutionBase
from app.solutions.echo.engines_mock import EchoASR, EchoLLM, EchoTTS


class EchoSolution(CascadeSolutionBase):
    name = "echo"

    def _build_engines(self, settings: Settings) -> EngineSet:
        return EngineSet(asr=EchoASR(), llm=EchoLLM(), tts=EchoTTS())

    def _system_prompt(self, settings: Settings) -> str:
        return "你是回声测试助手。"
