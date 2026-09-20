import { describe, expect, it } from 'vitest'
import { downsampleToInt16 } from '../src/composables/useMicCapture'

describe('downsampleToInt16', () => {
  it('48k → 16k 长度变为 1/3', () => {
    const src = new Float32Array(4800) // 0.1s @48k
    const out = downsampleToInt16(src, 48000)
    expect(out.length).toBe(1600)
  })

  it('静音输出全零', () => {
    const out = downsampleToInt16(new Float32Array(4800), 48000)
    expect(Array.from(out.slice(0, 10))).toEqual(new Array(10).fill(0))
  })

  it('满幅正弦峰值在 int16 范围内', () => {
    const src = new Float32Array(4800)
    for (let i = 0; i < src.length; i++) src[i] = Math.sin((i / 48000) * 2 * Math.PI * 440)
    const out = downsampleToInt16(src, 48000)
    const peak = Math.max(...Array.from(out).map(Math.abs))
    expect(peak).toBeGreaterThan(10000)
    expect(peak).toBeLessThanOrEqual(32767)
  })

  it('超幅信号被钳制到 int16 边界', () => {
    const src = new Float32Array([2.0, -2.0, 0.5]) // 2.0 超出 [-1,1]
    const out = downsampleToInt16(src, 16000) // 同采样率，1:1
    expect(out[0]).toBe(32767)
    expect(out[1]).toBe(-32768)
    expect(out[2]).toBe(Math.round(0.5 * 32767))
  })

  it('同采样率时逐样本直通（线性插值 pos 整数）', () => {
    const src = new Float32Array([0, 0.5, -0.5, 1])
    const out = downsampleToInt16(src, 16000)
    expect(out.length).toBe(4)
    expect(out[1]).toBe(Math.round(0.5 * 32767))
  })
})
