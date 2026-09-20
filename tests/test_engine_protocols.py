"""引擎 Protocol 结构检查（纯 isinstance，不联网、不验证行为）。"""

from app.core.engines import ASREngine, LLMEngine, TTSEngine
from app.solutions.cascade.engines_bailian import BailianASR, BailianLLM, BailianTTS
from app.solutions.echo.engines_mock import EchoASR, EchoLLM, EchoTTS


def test_engines_satisfy_protocols():
    """所有引擎实现必须符合 Protocol（三引擎统一有异步上下文生命周期）。"""
    assert isinstance(EchoASR(), ASREngine)
    assert isinstance(EchoLLM(), LLMEngine)
    assert isinstance(EchoTTS(), TTSEngine)
    assert isinstance(BailianASR("k", "m", "w"), ASREngine)
    assert isinstance(BailianLLM("k", "m", "u"), LLMEngine)
    assert isinstance(BailianTTS("k", "m", "v", "w"), TTSEngine)
