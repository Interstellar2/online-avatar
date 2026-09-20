// 音频播放：服务端二进制 PCM 帧 → AudioBuffer 顺序调度播放
// sampleRate 由 turn_started 消息下发，新一轮时 reset()

import { ref } from 'vue'

export function useAudioPlayer() {
  const sampleRate = ref(22050)

  let ctx: AudioContext | null = null
  let nextPlayTime = 0
  // 已调度未结束的 source：打断时必须显式 stop，否则已入队的缓冲仍会播完
  const activeSources = new Set<AudioBufferSourceNode>()

  const stop = () => {
    for (const src of activeSources) src.stop()
    activeSources.clear()
    nextPlayTime = 0
  }

  const reset = (rate: number) => {
    if (rate) sampleRate.value = rate
    stop() // 新一轮从头调度，上一轮未播完的声音按打断语义丢弃
  }

  const play = (buffer: ArrayBuffer) => {
    if (!ctx) ctx = new AudioContext()
    const int16 = new Int16Array(buffer)
    const audioBuf = ctx.createBuffer(1, int16.length, sampleRate.value)
    const ch = audioBuf.getChannelData(0)
    for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / 32768
    const src = ctx.createBufferSource()
    src.buffer = audioBuf
    src.connect(ctx.destination)
    const now = ctx.currentTime
    if (nextPlayTime === 0) {
      nextPlayTime = now + 0.05 // 新一轮首帧：留 50ms 缓冲防断音
    } else if (nextPlayTime < now - 1) {
      // 游标落后超过 1s 说明积压了过多未播缓冲，丢弃并追赶，防止延迟无限累积
      nextPlayTime = now + 0.05
    }
    // 轻微落后（<1s）：保持原时间线起播（浏览器把已过去的时间当作立即开始），保证声音连续
    src.start(nextPlayTime)
    nextPlayTime += audioBuf.duration
    activeSources.add(src)
    src.onended = () => activeSources.delete(src)
  }

  return { sampleRate, reset, play, stop }
}
