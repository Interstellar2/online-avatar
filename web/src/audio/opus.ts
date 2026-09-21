// WebCodecs Opus 编解码封装：上行 PCM16 → Opus 包，下行 Opus 包 → PCM16
// 注意：WebCodecs 在 jsdom / 旧浏览器里不存在，所有 API 引用都放在函数内部，
// 保证模块被 import 时不会因触碰 AudioEncoder 而抛错（能力检测统一走 isOpusSupported）

export interface OpusEncoderHandle {
  encode: (int16: Int16Array, sampleRate: number) => void
  close: () => void
}

export interface OpusDecoderHandle {
  decode: (packet: ArrayBuffer) => void
  close: () => void
}

// 与后端协商一致的编码参数：Opus 原生 48kHz 单声道，24kbps 语音码率足够清晰
const OPUS_SAMPLE_RATE = 48000
const OPUS_CHANNELS = 1
const OPUS_BITRATE = 24000
// opus format 用裸 'opus'（非 ogg 容器）：一个编码输出块就是一个 Opus 包，正好对应一个 WS 二进制帧
const OPUS_FORMAT = 'opus'

export async function isOpusSupported(): Promise<boolean> {
  try {
    const { supported } = await AudioEncoder.isConfigSupported({
      codec: 'opus',
      sampleRate: OPUS_SAMPLE_RATE,
      numberOfChannels: OPUS_CHANNELS,
      bitrate: OPUS_BITRATE,
      opus: { format: OPUS_FORMAT },
    })
    return !!supported
  } catch {
    // 无 WebCodecs、codec 字符串非法等一律按不支持处理，回落 pcm 透传
    return false
  }
}

export function createOpusEncoder(onPacket: (data: ArrayBuffer) => void): OpusEncoderHandle {
  let timestamp = 0 // 微秒，单调递增：WebCodecs 要求帧时间戳不回退
  const encoder = new AudioEncoder({
    output: (chunk) => {
      // 一个输出 chunk = 一个 Opus 包；拷贝出独立缓冲再回调，避免复用内部内存
      const buf = new ArrayBuffer(chunk.byteLength)
      chunk.copyTo(buf)
      onPacket(buf)
    },
    error: (e) => console.warn('opus 编码器错误', e),
  })
  encoder.configure({
    codec: 'opus',
    sampleRate: OPUS_SAMPLE_RATE,
    numberOfChannels: OPUS_CHANNELS,
    bitrate: OPUS_BITRATE,
    opus: { format: OPUS_FORMAT },
  })
  return {
    encode(int16, sampleRate) {
      // 输入可以是 16k 等任意 Opus 支持的采样率，由编码器内部重采样到 48k
      const data = new AudioData({
        format: 's16',
        sampleRate,
        numberOfFrames: int16.length, // 单声道：一帧即一个采样
        numberOfChannels: OPUS_CHANNELS,
        timestamp,
        // 拷贝一份 ArrayBuffer -backed 的视图：AudioData 可能持有传入缓冲，且 TS 要求 BufferSource
        data: new Int16Array(int16),
      })
      timestamp += (int16.length / sampleRate) * 1e6
      encoder.encode(data)
      data.close()
    },
    close() {
      encoder.close()
    },
  }
}

export function createOpusDecoder(onPcm: (int16: Int16Array, sampleRate: number) => void): OpusDecoderHandle {
  let timestamp = 0 // 每个包 20ms，只需保持单调，解码不依赖精确值
  const decoder = new AudioDecoder({
    output: (frame) => {
      // 按帧数 × 通道数分配，防止将来升级立体声时溢出
      const int16 = new Int16Array(frame.numberOfFrames * frame.numberOfChannels)
      frame.copyTo(int16, { format: 's16', planeIndex: 0 })
      // Opus 解码输出恒为 48kHz（原生率），重采样交给调用方按本轮目标率处理
      onPcm(int16, frame.sampleRate)
      frame.close()
    },
    error: (e) => console.warn('opus 解码器错误', e),
  })
  decoder.configure({ codec: 'opus', sampleRate: OPUS_SAMPLE_RATE, numberOfChannels: OPUS_CHANNELS })
  return {
    decode(packet) {
      // 一个 WS 二进制帧 = 一个 Opus 包，无需自己拆包
      decoder.decode(new EncodedAudioChunk({ type: 'key', timestamp, data: packet }))
      timestamp += 20000
    },
    close() {
      decoder.close()
    },
  }
}
