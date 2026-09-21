import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resampleInt16 } from '../src/audio/resample'
import { useAvatarSession } from '../src/composables/useAvatarSession'
import {
  FakeAudioContext,
  installFakeAudioContext,
  installFakeGetUserMedia,
  installFakeWebCodecs,
  installFakeWebSocket,
  makeOpusPacket,
  mockFetchJson,
  uninstallFakeWebCodecs,
} from './helpers'

let FakeWS: ReturnType<typeof installFakeWebSocket>

const lastWs = () => {
  const ws = FakeWS.instances[FakeWS.instances.length - 1]
  if (!ws) throw new Error('WebSocket 未创建')
  return ws
}

beforeEach(() => {
  FakeWS = installFakeWebSocket()
  installFakeAudioContext()
  mockFetchJson({ status: 'ok', dashscope_configured: true })
})

afterEach(() => {
  uninstallFakeWebCodecs() // 无论用例是否安装过，统一兜底还原，避免污染后续用例
})

describe('resampleInt16', () => {
  it('16k → 48k：长度为 3 倍且线性插值正确', () => {
    const out = resampleInt16(new Int16Array([0, 100, 200, 300]), 16000, 48000)
    expect(out).toHaveLength(12)
    // 插值落在源采样点上时值必须精确还原
    expect(out[0]).toBe(0)
    expect(out[3]).toBe(100)
    expect(out[6]).toBe(200)
    expect(out[9]).toBe(300)
    // 插值中间点：pos=1/3 → 33.33 → 33，pos=2/3 → 66.67 → 67
    expect(out[1]).toBe(33)
    expect(out[2]).toBe(67)
  })

  it('48k → 22.05k：长度按比例缩短，常量信号幅值保持', () => {
    const out = resampleInt16(new Int16Array(4800).fill(1000), 48000, 22050)
    expect(out).toHaveLength(2205) // 4800 * 22050 / 48000
    for (const v of out) expect(v).toBe(1000) // 常量信号插值后不应失真
  })

  it('同采样率直接返回原数组，不做无谓拷贝', () => {
    const pcm = new Int16Array([1, 2, 3])
    expect(resampleInt16(pcm, 16000, 16000)).toBe(pcm)
  })
})

describe('useAvatarSession opus 集成', () => {
  it('支持 opus 时连接 URL 带 ?codec=opus', async () => {
    installFakeWebCodecs()
    const s = useAvatarSession()
    await s.connect()
    expect(lastWs().url).toContain('/ws/avatar/cascade?codec=opus')
  })

  it('opus 模式下麦克风帧经编码后以二进制发送', async () => {
    installFakeWebCodecs()
    const s = useAvatarSession()
    await s.connect()
    const ws = lastWs()
    ws.simulateOpen()

    installFakeGetUserMedia()
    await s.toggleMic()
    expect(s.listening.value).toBe(true)

    // 驱动采集回调：48k 浮点输入被重采样为 16k 整数帧（4800 / 3 = 1600 采样）
    const ctx = FakeAudioContext.instances[0]
    ctx.createdProcessors[0].onaudioprocess!({
      inputBuffer: { getChannelData: () => new Float32Array(4800).fill(0.5) },
    })

    const bins = ws.sentBinary()
    expect(bins).toHaveLength(1)
    // 假编码器的包内嵌采样数：验证送进来的确实是重采样后的 16k 帧
    expect(new DataView(bins[0]).getInt32(0, true)).toBe(1600)
  })

  it('收到 codec:opus 的 turn_started 后，二进制帧解码并重采样送给播放器', async () => {
    installFakeWebCodecs()
    const s = useAvatarSession()
    await s.connect()
    const ws = lastWs()
    ws.simulateOpen()

    ws.simulateJson({ type: 'turn_started', sample_rate: 22050, codec: 'opus' })
    expect(s.playerSampleRate.value).toBe(22050)

    // 一个二进制帧 = 一个 Opus 包：960 个 48k 常量采样（20ms）
    ws.simulateBinary(makeOpusPacket(new Int16Array(960).fill(1000)))

    const ctx = FakeAudioContext.instances[0]
    expect(ctx.createdBuffers).toHaveLength(1)
    const buf = ctx.createdBuffers[0]
    expect(buf.channel).toHaveLength(441) // 960 * 22050 / 48000，重采样到本轮目标率
    expect(buf.channel[0]).toBeCloseTo(1000 / 32768, 5) // 播放器把 int16 归一化到 float
  })

  it('无 WebCodecs 时 URL 不带参数，pcm 路径不受影响', async () => {
    // 故意不装 WebCodecs 桩：isOpusSupported 应回落 false
    const s = useAvatarSession()
    await s.connect()
    const ws = lastWs()
    expect(ws.url).not.toContain('codec=')
    ws.simulateOpen()

    ws.simulateJson({ type: 'turn_started', sample_rate: 22050 })
    ws.simulateBinary(new Int16Array([1, 2, 3]).buffer)
    const ctx = FakeAudioContext.instances[0]
    expect(ctx.createdBuffers).toHaveLength(1)
    expect(ctx.createdBuffers[0].channel).toHaveLength(3) // pcm 帧原样进播放器
  })
})
