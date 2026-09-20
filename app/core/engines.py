"""引擎层统一抽象：ASR / LLM / TTS。

设计目标：
- pipeline 只面向这些协议编程，不关心背后是阿里云百炼、OpenAI 还是自部署服务；
- 引擎是异步上下文管理器，持有到上游服务的连接生命周期（三引擎统一，见 EngineSet）；
- 数据流均为 AsyncIterator，天然适配 asyncio 流水线。

注意：omni 类端到端模型不拆 ASR/TTS，应实现 solutions 层的 Solution 协议，
而不是这里的引擎协议。两层分离是为了同时兼容"级联"与"端到端"两类方案。
"""

import sys
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Protocol, runtime_checkable


class EngineError(RuntimeError):
    """引擎层统一异常：配置缺失、上游错误等。

    定义在协议层而非某个供应商实现里，方案层才能与具体供应商解耦。
    """


@runtime_checkable
class ASREngine(Protocol):
    """语音识别：上行 PCM 音频流，产出"判停后的最终句子"。

    final_transcripts() 由服务端 VAD（或引擎自身端点检测）驱动，
    每产出一条即代表用户说完了一句话，pipeline 据此启动一轮回答。
    on_partial 为可选的同步回调，用于向前端推识别中间结果（实时字幕）；
    无中间结果能力的引擎保持 None 即可。
    """

    on_partial: Callable[[str], None] | None

    async def __aenter__(self) -> "ASREngine": ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def send_audio(self, pcm: bytes) -> None:
        """喂入一帧 PCM16 单声道音频。"""
        ...

    async def finalize(self) -> None:
        """主动结束当前一路识别（可选实现，无服务端 VAD 的引擎用得到）。"""
        ...

    def final_transcripts(self) -> AsyncIterator[str]:
        """产出最终识别句子。"""
        ...


@runtime_checkable
class LLMEngine(Protocol):
    """大语言模型：流式产出增量 token。

    与 ASR/TTS 一样有连接生命周期（httpx client 等），
    会话统一通过 EngineSet 进出异步上下文，避免资源泄漏。
    """

    async def __aenter__(self) -> "LLMEngine": ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    def stream_reply(self, messages: list[dict]) -> AsyncIterator[str]: ...


@runtime_checkable
class TTSEngine(Protocol):
    """语音合成：输入完整句子，流式产出 PCM 音频分块。

    output_sample_rate 为输出 PCM 的采样率，须随 turn_started 下发给前端。
    """

    output_sample_rate: int

    async def __aenter__(self) -> "TTSEngine": ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """合成一句话，流式产出 PCM16 单声道音频分块。"""
        ...

    async def interrupt(self) -> None:
        """打断当前正在进行的合成。"""
        ...


@dataclass
class EngineSet:
    """三引擎集合：统一进出异步上下文。

    调用方只需 `async with engines:`，无需逐个管理生命周期；
    进入中途失败时回滚已建立的引擎，避免半初始化状态泄漏。
    """

    asr: ASREngine
    llm: LLMEngine
    tts: TTSEngine

    async def __aenter__(self) -> "EngineSet":
        await self.asr.__aenter__()
        try:
            await self.llm.__aenter__()
        except BaseException:
            await self.asr.__aexit__(*sys.exc_info())
            raise
        try:
            await self.tts.__aenter__()
        except BaseException:
            await self.llm.__aexit__(*sys.exc_info())
            await self.asr.__aexit__(*sys.exc_info())
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # 逆序释放：后建立的先关闭
        await self.tts.__aexit__(exc_type, exc, tb)
        await self.llm.__aexit__(exc_type, exc, tb)
        await self.asr.__aexit__(exc_type, exc, tb)
