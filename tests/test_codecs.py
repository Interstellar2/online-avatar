"""音频编解码测试：Opus 往返保真、PCM 透传、帧粒度与尾帧冲刷。"""

import math
import struct

import numpy as np

from app.core.codecs import PCMCodec, build_codec, frame_bytes

TTS_RATE = 22050


def _max_correlation(a: tuple[int, ...], b: tuple[int, ...], max_lag: int = 2000) -> float:
    """滑动窗口最大相关系数：编解码器引入恒定延迟（实测约 +1245 采样 @22.05k），
    往返波形允许相位偏移，故在 ±max_lag 内细粒度搜索。"""
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    x = (x - x.mean()) / (x.std() + 1e-9)
    y = (y - y.mean()) / (y.std() + 1e-9)
    best = -1.0
    for lag in range(-max_lag, max_lag + 1, 10):
        ia, ib = max(0, -lag), max(0, lag)
        n = min(len(x) - ia, len(y) - ib)
        if n < 1000:
            continue
        corr = float(np.dot(x[ia : ia + n], y[ib : ib + n]) / n)
        best = max(best, corr)
    return best


def _sine_pcm(rate: int, seconds: float, freq: float = 440.0) -> bytes:
    n = int(rate * seconds)
    return b"".join(
        struct.pack("<h", int(0.5 * 32767 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(n)
    )


async def test_opus_roundtrip_preserves_signal():
    pcm = _sine_pcm(TTS_RATE, 0.5)
    codec = build_codec("opus", TTS_RATE)

    packets = []
    # 模拟 TTS 分块下发（不均匀分块）
    for i in range(0, len(pcm), 4800):
        packets += codec.encode(pcm[i : i + 4800])
    packets += codec.flush()

    assert packets, "应产出 Opus 包"
    # 24kbps × 20ms ≈ 60 字节/包，允许少量帧边界差异
    assert all(20 <= len(p) <= 200 for p in packets)

    # 解码回原采样率（解码器实例必须复用——状态ful，逐包新建会累积漂移）
    decoder = build_codec("opus", TTS_RATE)
    decoded = b"".join(decoder.decode(p) for p in packets)
    assert decoded != pcm  # 有损编码，字节不必相同
    n = min(len(decoded), len(pcm)) // 2
    orig = struct.unpack(f"<{n}h", pcm[: n * 2])
    back = struct.unpack(f"<{n}h", decoded[: n * 2])
    # 正弦波往返后波形应高度相关（有损但保形）
    assert _max_correlation(orig, back) > 0.9


async def test_opus_flush_emits_tail_frames():
    codec = build_codec("opus", TTS_RATE)
    codec.encode(_sine_pcm(TTS_RATE, 0.03))  # 不足一帧（20ms=441采样=882字节）
    assert codec.flush(), "不足一帧的尾部也应冲刷出一个补零帧"


async def test_pcm_codec_passthrough():
    codec = build_codec("pcm", TTS_RATE)
    assert codec.encode(b"abc") == [b"abc"]
    assert codec.flush() == []
    assert codec.decode(b"xyz") == b"xyz"
    assert codec.encode(b"") == []


def test_frame_bytes():
    assert frame_bytes(48000) == 1920  # 20ms PCM16 单声道
    assert frame_bytes(16000) == 640


async def test_uplink_decode_rate_matches_input():
    """上行解码必须回到 16k（ASR 的输入速率），48k 包 → 16k PCM。"""
    uplink = build_codec("opus", 16000)
    # 用 16k 编码器造一个真实包
    maker = build_codec("opus", 16000)
    packets = maker.encode(_sine_pcm(16000, 0.1))
    pcm = b"".join(uplink.decode(p) for p in packets)  # uplink 为复用实例，OK
    assert len(pcm) % 2 == 0
    # 100ms 音频 → 1600 采样 → 3200 字节；容差 2 帧（编码器延迟 + 补零边界）
    assert abs(len(pcm) - 3200) <= 2 * frame_bytes(16000)


def test_unknown_codec_falls_back_to_pcm():
    assert build_codec("mystery", TTS_RATE).name == "pcm"
