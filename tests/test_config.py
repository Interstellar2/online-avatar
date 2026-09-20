"""配置加载测试：环境变量优先，默认值兜底。"""

import importlib

import app.config as config_module
from app.config import Settings


def test_defaults():
    s = Settings()
    assert s.asr_model == "qwen3-asr-flash-realtime"
    assert s.llm_model == "qwen-plus"
    assert s.tts_model == "cosyvoice-v3-flash"
    assert s.tts_sample_rate == 22050
    assert s.input_audio_sample_rate == 16000
    assert s.default_solution == "cascade"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-123")
    monkeypatch.setenv("LLM_MODEL", "qwen-turbo")
    monkeypatch.setenv("TTS_VOICE", "longxiaochun_v2")
    monkeypatch.setenv("ASR_VAD_SILENCE_MS", "600")
    s = Settings()
    assert s.dashscope_api_key == "sk-test-123"
    assert s.llm_model == "qwen-turbo"
    assert s.tts_voice == "longxiaochun_v2"
    assert s.asr_vad_silence_ms == 600


def test_env_file_resolved_from_project_root():
    """.env 路径应与 CWD 无关（绝对化到项目根）。"""
    import pathlib

    env_file = Settings.model_config["env_file"]
    assert pathlib.Path(env_file).is_absolute()
    assert env_file.name == ".env"


def test_get_settings_cached(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    config_module.get_settings.cache_clear()
    s1 = config_module.get_settings()
    s2 = config_module.get_settings()
    assert s1 is s2
    config_module.get_settings.cache_clear()
