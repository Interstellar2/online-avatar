"""CascadeSession：一条 WS 连接的生命周期（级联方案）。

组合三个职责单一的组件：
- SessionShell：接收前端消息（音频帧喂 ASR；ping/interrupt/text 分发）
- TurnRunner：单轮内部的 LLM/TTS 并行流水线
- SessionNotifier：协议消息构造与发送

并发模型：
- shell.serve()：接收循环
- _asr_producer：消费 ASR 最终句子，发 asr_final 并入轮次队列
- _turn_consumer：从轮次队列逐轮执行 TurnRunner，
  并保证 turn_started/turn_finished 起止标记成对
"""

import asyncio
import logging

from app.core.codecs import build_codec
from app.core.dialogue import Dialogue
from app.core.engines import ASREngine, EngineSet, LLMEngine, TTSEngine
from app.core.transport import Transport
from app.solutions.cascade.notifier import SessionNotifier
from app.solutions.cascade.shell import SessionShell
from app.solutions.cascade.turn import AudioSink, TurnRunner

logger = logging.getLogger(__name__)


class _TransportAudioSink:
    """把 TTS 的 PCM 分块经编码器成帧后发到传输层（帧式编码的 send/flush 适配）。"""

    def __init__(self, codec, transport: Transport):
        self._codec = codec
        self._transport = transport

    async def send(self, chunk: bytes) -> None:
        for packet in self._codec.encode(chunk):
            await self._transport.send_bytes(packet)

    async def flush(self) -> None:
        for packet in self._codec.flush():
            await self._transport.send_bytes(packet)


class CascadeSession:
    # 背压上限：客户端狂发 text / ASR 高频判停时轮次队列内存有界，
    # 生产者阻塞等待消费（慢于上游推送属异常场景，宁可反压不可膨胀）
    MAX_QUEUED_TURNS = 32

    def __init__(
        self,
        asr: ASREngine,
        llm: LLMEngine,
        tts: TTSEngine,
        dialogue: Dialogue,
        transport: Transport,
        session_id: str = "",
        codec: str = "pcm",
        input_sample_rate: int = 16000,
    ):
        self._asr = asr
        self._llm = llm
        self._tts = tts
        self._dialogue = dialogue
        self._transport = transport
        self._session_id = session_id
        # 编解码只发生在传输边缘：上行帧解码回 PCM 再喂 ASR，下行 PCM 编码后发出。
        # 两侧采样率不同（麦克风 16k / TTS 22.05k），故各持一个实例
        self._uplink_codec = build_codec(codec, input_sample_rate)
        self._downlink_codec = build_codec(codec, tts.output_sample_rate)
        self._notifier = SessionNotifier(transport, codec=codec)
        self._turn_runner = TurnRunner(
            llm,
            tts,
            dialogue,
            self._notifier,
            _TransportAudioSink(self._downlink_codec, transport),
        )
        self._turn_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.MAX_QUEUED_TURNS)
        self._current_turn: asyncio.Task | None = None
        # ASR 中间结果（实时字幕）的异步发送任务引用，防止被 GC 回收
        self._bg_tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        # 三引擎统一进出异步上下文：连接在此建立/释放，杜绝生命周期遗漏
        async with EngineSet(self._asr, self._llm, self._tts):
            # 引擎建立后即可注入识别中间结果回调（同步回调转异步发送）
            self._asr.on_partial = self._on_asr_partial
            shell = SessionShell(
                self._transport,
                self._notifier,
                on_bytes=self._on_audio_frame,
                on_text=self._enqueue_turn,
                on_interrupt=self._handle_interrupt,
            )
            tasks = [
                asyncio.create_task(shell.serve()),
                asyncio.create_task(self._asr_producer()),
                asyncio.create_task(self._turn_consumer()),
            ]
            try:
                done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.cancelled():
                        continue
                    exc = t.exception()
                    if exc is not None:
                        raise exc
                # ASR 流先于连接结束 = 上游断流而非用户挂断（静默退出会让前端
                # 无法区分两者），这里显式告知
                if tasks[1] in done and tasks[0] not in done:
                    await self._notifier.error("ASR_ERROR", "语音识别上游连接已断开")
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    # ---------- 生产者 ----------

    async def _on_audio_frame(self, data: bytes) -> None:
        pcm = self._uplink_codec.decode(data)
        if pcm:
            await self._asr.send_audio(pcm)

    async def _asr_producer(self) -> None:
        async for text in self._asr.final_transcripts():
            text = text.strip()
            if text:
                await self._notifier.asr_final(text)
                await self._turn_queue.put(text)

    def _on_asr_partial(self, text: str) -> None:
        # ASR 的 on_partial 是同步回调，这里转交给事件循环异步发送
        task = asyncio.create_task(self._notifier.asr_partial(text))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _enqueue_turn(self, text: str) -> None:
        await self._turn_queue.put(text)

    # ---------- 轮次执行 ----------

    async def _turn_consumer(self) -> None:
        while True:
            user_text = await self._turn_queue.get()
            turn = asyncio.create_task(self._turn_runner.run(user_text))
            # 赋值与 create_task 之间存在极窄的竞争窗口：期间到达的 interrupt 会
            # cancel 到上一轮的 task 引用——那一定是已结束或已取消的，无害
            self._current_turn = turn
            try:
                await turn
            except asyncio.CancelledError:
                # 区分两种取消（asyncio.Task.cancelling() 只统计对本任务
                # 调用 cancel() 的次数，是 3.11 起的判定依据）：
                # - 会话整体关闭：本任务自身被取消（cancelling() > 0）→ 退出；
                # - 本轮被 interrupt：cancel 落在内部 turn 任务上，本任务只是
                #   await 到 CancelledError（cancelling() == 0）→ 吞掉，继续下一轮
                if asyncio.current_task().cancelling():
                    raise
            finally:
                # 起止标记成对由消费者保证：无论正常完成还是被 interrupt 取消，
                # 都恰好补一条 turn_finished。本 finally 只包住已启动的 turn——
                # 阻塞在 queue.get() 时被取消不会走到这里，不会多发尾帧
                try:
                    await self._notifier.turn_finished()
                except Exception:  # noqa: BLE001 - 连接可能正在关闭，起止标记尽力而为
                    logger.debug("turn_finished 发送失败（连接可能已关闭）", exc_info=True)

    async def _handle_interrupt(self) -> None:
        await self._tts.interrupt()
        # 打断语义 = 停止当前播报，且丢弃排队中的输入——用户不想要堆积的回答
        while True:
            try:
                self._turn_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._current_turn is not None and not self._current_turn.done():
            self._current_turn.cancel()
