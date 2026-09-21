"""WS 二进制帧 ↔ PCM16 的音频编解码。

设计约束：
- 编解码只发生在"传输边缘"（会话收发侧），进出 ASR/TTS 引擎的永远是 PCM16，
  引擎协议因此无需感知编码方式；
- 每种编码一个 session 级实例（编码器/解码器有状态）；
- Opus 经 PyAV(libopus) 实现：20ms 帧、内部统一 48kHz 单声道，
  输入输出侧按需重采样，PyAV 静态捆绑 ffmpeg，无系统库依赖。
"""

import av
import numpy as np

OPUS_RATE = 48000  # Opus 内部统一采样率
FRAME_MS = 20  # 每帧时长（libopus 默认帧长，延迟与压缩率的平衡点）
FRAME_SAMPLES = OPUS_RATE * FRAME_MS // 1000  # 960


def frame_bytes(sample_rate: int) -> int:
    """单帧 PCM16 单声道的字节数（编码侧输入粒度）。"""
    return sample_rate * FRAME_MS // 1000 * 2


class PCMCodec:
    """透传：WS 二进制帧即 PCM16，不做任何处理（默认，向后兼容）。"""

    name = "pcm"

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    def encode(self, pcm: bytes) -> list[bytes]:
        # TTS 分块已是完整可播放单元，原样透传
        return [pcm] if pcm else []

    def flush(self) -> list[bytes]:
        return []

    def decode(self, data: bytes) -> bytes:
        return data


class OpusCodec:
    """Opus 编解码器：encode 攒满 20ms 帧再出包，decode 一帧一包。"""

    name = "opus"

    def __init__(self, sample_rate: int, bit_rate: int = 24000):
        self.sample_rate = sample_rate
        self._enc = av.CodecContext.create("libopus", "w")
        self._enc.sample_rate = OPUS_RATE
        self._enc.layout = "mono"
        self._enc.format = "s16"
        self._enc.bit_rate = bit_rate
        self._enc.open()

        self._dec = av.CodecContext.create("libopus", "r")
        self._dec.sample_rate = OPUS_RATE
        self._dec.layout = "mono"
        self._dec.format = "s16"
        self._dec.open()

        # 编码侧：sample_rate → 48k；解码侧：48k → sample_rate
        self._res_in = av.AudioResampler(format="s16", layout="mono", rate=OPUS_RATE)
        self._res_out = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        self._pending = np.zeros((1, 0), dtype=np.int16)  # 待凑帧的 48k 采样

    # ---- 编码（下行：TTS PCM → Opus 包）----

    def encode(self, pcm: bytes) -> list[bytes]:
        out: list[bytes] = []
        if pcm:
            for frame in self._res_in.resample(self._make_frame(pcm, self.sample_rate)):
                self._pending = np.concatenate([self._pending, frame.to_ndarray()], axis=1)
        return out + self._encode_ready()

    def flush(self) -> list[bytes]:
        # 冲刷重采样器内部残留，再补零凑满最后一帧
        out: list[bytes] = []
        for frame in self._res_in.resample(None):
            self._pending = np.concatenate([self._pending, frame.to_ndarray()], axis=1)
        pad = FRAME_SAMPLES - self._pending.shape[1] % FRAME_SAMPLES
        if pad != FRAME_SAMPLES:
            zeros = np.zeros((1, pad), dtype=np.int16)
            self._pending = np.concatenate([self._pending, zeros], axis=1)
        out += self._encode_ready()
        for packet in self._enc.encode(None):  # 取出编码器内滞留的包
            out.append(bytes(packet))
        return out

    def _encode_ready(self) -> list[bytes]:
        out: list[bytes] = []
        while self._pending.shape[1] >= FRAME_SAMPLES:
            chunk = self._pending[:, :FRAME_SAMPLES]
            self._pending = self._pending[:, FRAME_SAMPLES:]
            packet_out = self._enc.encode(self._make_frame(chunk.tobytes(), OPUS_RATE))
            for packet in packet_out:
                out.append(bytes(packet))
        return out

    # ---- 解码（上行：一个 WS 帧 = 一个 Opus 包 → PCM16）----

    def decode(self, data: bytes) -> bytes:
        out = bytearray()
        for frame in self._dec.decode(av.Packet(data)):
            # 解码帧自带 pts，而重采样器按 pts 推时间戳——与按采样计数的上游混用
            # 会导致输出抖动（实测正弦波频率漂移）。剥掉 pts 让它纯按采样计数
            frame.pts = None
            for rf in self._res_out.resample(frame):
                out += rf.to_ndarray().tobytes()
        return bytes(out)

    # ---- 内部 ----

    @staticmethod
    def _make_frame(pcm: bytes, sample_rate: int) -> av.AudioFrame:
        arr = np.frombuffer(pcm, dtype=np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
        frame.sample_rate = sample_rate
        frame.pts = None  # 裸帧无时基概念，由帧序决定
        return frame


def build_codec(name: str, sample_rate: int, bit_rate: int = 24000):
    """按会话协商结果构造编解码器；未知名称一律退回 PCM 透传。"""
    if name == "opus":
        return OpusCodec(sample_rate, bit_rate)
    return PCMCodec(sample_rate)
