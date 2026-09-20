import { beforeEach, describe, expect, it } from 'vitest'
import { useAudioPlayer } from '../src/composables/useAudioPlayer'
import { installFakeAudioContext } from './helpers'

const CTX = () => FakeAudioContextRef.instances[0]

let FakeAudioContextRef: ReturnType<typeof installFakeAudioContext>

function makePcmBuffer(sampleCount: number): ArrayBuffer {
  return new Int16Array(sampleCount).buffer
}

beforeEach(() => {
  FakeAudioContextRef = installFakeAudioContext()
})

describe('useAudioPlayer', () => {
  it('reset 更新采样率', () => {
    const p = useAudioPlayer()
    p.reset(24000)
    expect(p.sampleRate.value).toBe(24000)
  })

  it('PCM 帧被包装为 AudioBuffer 并调度播放', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205)) // 0.1s
    const ctx = CTX()
    expect(ctx.createdBuffers).toHaveLength(1)
    expect(ctx.createdBuffers[0].duration).toBeCloseTo(0.1, 5)
    expect(ctx.startedSources).toHaveLength(1)
  })

  it('连续帧顺序调度，后一帧接前一帧末尾', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205)) // 0.1s，从 now+0.05 起播
    p.play(makePcmBuffer(2205))
    const [s1, s2] = CTX().startedSources
    expect(s2.at).toBeCloseTo(s1.at + s1.buffer.duration, 5)
  })

  it('播放游标落后当前时间时重新对齐（防大段静音）', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205)) // 先建 AudioContext 并排第一帧
    const ctx = CTX()
    ctx.currentTime = 100 // 模拟长时间无音频后时钟已远
    p.play(makePcmBuffer(2205))
    const [, s2] = ctx.startedSources
    expect(s2.at).toBeCloseTo(100 + 0.05, 5)
  })

  it('reset 后从头调度', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205))
    const firstAt = CTX().startedSources[0].at
    CTX().currentTime = firstAt + 10
    p.reset(22050)
    p.play(makePcmBuffer(2205))
    const [, s2] = CTX().startedSources
    expect(s2.at).toBeCloseTo(firstAt + 10 + 0.05, 5)
  })

  it('stop 停止所有已调度 source 并重置游标', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205))
    p.play(makePcmBuffer(2205))
    const ctx = CTX()
    expect(ctx.startedSources).toHaveLength(2)

    p.stop()
    expect(ctx.stoppedSources).toHaveLength(2)
    // 打断后新帧从头调度，不接在旧游标后面
    ctx.currentTime = 5
    p.play(makePcmBuffer(2205))
    expect(ctx.startedSources).toHaveLength(3)
    expect(ctx.startedSources[2].at).toBeCloseTo(5 + 0.05, 5)
  })

  it('自然播完的 source 会被回收，stop 不再重复停止', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205))
    const ctx = CTX()
    ctx.startedSources[0].source.simulateEnded()

    p.stop()
    expect(ctx.stoppedSources).toHaveLength(0)
  })

  it('reset 停止上一轮未播完的声音', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205))
    const ctx = CTX()
    p.reset(22050)
    expect(ctx.stoppedSources).toHaveLength(1)
  })

  it('游标轻微落后时保持时间线连续，不跳过已缓冲音频', () => {
    const p = useAudioPlayer()
    p.reset(22050)
    p.play(makePcmBuffer(2205)) // 排至 now+0.05
    const ctx = CTX()
    ctx.currentTime = 0.1 // 仅落后 0.05s（< 1s 阈值）
    p.play(makePcmBuffer(2205))
    const [, s2] = ctx.startedSources
    expect(s2.at).toBeCloseTo(0.05 + 0.1, 5) // 接在第一帧末尾，而非跳到 now+0.05
  })

  it('int16 样本正确转换为 float [-1,1]', () => {
    const p = useAudioPlayer()
    p.reset(16000)
    const pcm = new Int16Array([0, 16384, -16384, 32767, -32768])
    p.play(pcm.buffer)
    const ch = CTX().createdBuffers[0].channel
    expect(ch[0]).toBe(0)
    expect(ch[1]).toBeCloseTo(0.5, 3)
    expect(ch[2]).toBeCloseTo(-0.5, 3)
    expect(ch[3]).toBeCloseTo(32767 / 32768, 5)
    expect(ch[4]).toBe(-1)
  })
})
