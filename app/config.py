"""全局配置：全部敏感信息与模型选择走环境变量 / .env。

配置分区：
- 服务级：host/port/default_solution；
- 上行音频：前端麦克风的采样率；
- 级联方案级：asr_/llm_/tts_ 前缀项，对应同名环境变量（如 ASR_MODEL）。

说明：曾考虑按方案嵌套分组（Settings.cascade = CascadeSettings），但 pydantic-settings
嵌套会改变环境变量名（需 CASCADE__ASR_MODEL 形式），对外部部署不友好，故保持平铺 + 前缀。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 绝对路径：与启动时的 CWD 无关（systemd / docker 场景下 CWD 不一定在项目根）
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # ---- 服务 ----
    host: str = "0.0.0.0"
    port: int = 8000
    default_solution: str = "cascade"

    # ---- 上行音频（前端麦克风 PCM16 单声道；区别于 tts_sample_rate 的下行输出）----
    input_audio_sample_rate: int = 16000

    # ---- 级联方案：阿里云百炼 ----
    dashscope_api_key: str = ""

    # ASR（实时语音识别，服务端 VAD）
    asr_model: str = "qwen3-asr-flash-realtime"
    asr_ws_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    asr_vad_threshold: float = 0.2  # 服务端 VAD 触发阈值
    asr_vad_silence_ms: int = 400  # 判停静音时长

    # LLM（OpenAI 兼容）
    llm_model: str = "qwen-plus"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_system_prompt: str = "你是一个友好的数字人助手，回答请简洁口语化，适合语音播报。"

    # TTS（CosyVoice 实时合成，输出 PCM16 单声道）
    tts_model: str = "cosyvoice-v3-flash"
    tts_voice: str = "longanyang"
    tts_ws_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    tts_sample_rate: int = 22050
    tts_volume: int = 50
    tts_rate: float = 1.0
    tts_pitch: float = 1.0

    # 上游 WS 保活间隔（秒），对 ASR/TTS 一致
    upstream_ping_interval: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
