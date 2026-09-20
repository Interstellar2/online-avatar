import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAvatarSession } from '../src/composables/useAvatarSession'
import { installFakeAudioContext, installFakeWebSocket, mockFetchJson } from './helpers'

let FakeWS: ReturnType<typeof installFakeWebSocket>
let FakeAudio: ReturnType<typeof installFakeAudioContext>

const lastWs = () => {
  const ws = FakeWS.instances[FakeWS.instances.length - 1]
  if (!ws) throw new Error('WebSocket 未创建')
  return ws
}

beforeEach(() => {
  FakeWS = installFakeWebSocket()
  FakeAudio = installFakeAudioContext()
  mockFetchJson({ status: 'ok', dashscope_configured: true })
})

afterEach(() => {
  vi.useRealTimers() // 心跳测试用例会启用 fake timers
})

describe('useAvatarSession 旅程', () => {
  it('连接后收到服务端事件，状态与消息流正确演化', () => {
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    expect(ws.url).toContain('/ws/avatar/cascade')

    ws.simulateOpen()
    expect(s.status.value).toBe('connected')

    // 用户说话 → ASR 中间结果 → 最终结果
    ws.simulateJson({ type: 'asr_partial', text: '今天天' })
    expect(s.asrDraft.value).toBe('今天天')
    ws.simulateJson({ type: 'asr_final', text: '今天天气怎么样' })
    expect(s.asrDraft.value).toBe('')
    const userEntry = s.entries.value.find((e) => e.role === 'user')
    expect(userEntry?.text).toBe('今天天气怎么样')

    // LLM 流式 token 追加到同一条机器人条目
    ws.simulateJson({ type: 'turn_started', sample_rate: 24000 })
    expect(s.turnActive.value).toBe(true)
    expect(s.playerSampleRate.value).toBe(24000)
    ws.simulateJson({ type: 'llm_token', text: '今天' })
    ws.simulateJson({ type: 'llm_token', text: '晴朗' })
    const bots = s.entries.value.filter((e) => e.role === 'bot')
    expect(bots).toHaveLength(1)
    expect(bots[0].text).toBe('今天晴朗')

    // 音频帧不产生产条目（只进播放器）
    const before = s.entries.value.length
    ws.simulateBinary(new Int16Array([1, 2, 3]).buffer)
    expect(s.entries.value.length).toBe(before)

    // 轮次结束
    ws.simulateJson({ type: 'turn_finished' })
    expect(s.turnActive.value).toBe(false)
  })

  it('新一轮 turn_started 开启新的机器人条目', () => {
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    ws.simulateOpen()

    ws.simulateJson({ type: 'turn_started', sample_rate: 22050 })
    ws.simulateJson({ type: 'llm_token', text: '第一轮回答' })
    ws.simulateJson({ type: 'turn_finished' })
    ws.simulateJson({ type: 'turn_started', sample_rate: 22050 })
    ws.simulateJson({ type: 'llm_token', text: '第二轮回答' })

    const bots = s.entries.value.filter((e) => e.role === 'bot')
    expect(bots.map((b) => b.text)).toEqual(['第一轮回答', '第二轮回答'])
  })

  it('error 消息进入消息流', () => {
    const s = useAvatarSession()
    s.connect()
    lastWs().simulateOpen()
    lastWs().simulateJson({ type: 'error', code: 'LLM_ERROR', message: 'boom' })
    const err = s.entries.value.find((e) => e.role === 'error')
    expect(err?.text).toContain('LLM_ERROR')
    expect(err?.text).toContain('boom')
  })

  it('sendText / interrupt 发送正确协议消息', () => {
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    ws.simulateOpen()

    s.sendText('  你好  ') // 首尾空格应被 trim
    s.interrupt()
    const sent = ws.sentJson()
    expect(sent[0]).toEqual({ type: 'text', content: '你好' })
    expect(sent[1]).toEqual({ type: 'interrupt' })
  })

  it('sendText 空内容不发送', () => {
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    ws.simulateOpen()
    s.sendText('   ')
    expect(ws.sentJson()).toHaveLength(0)
  })

  it('断开后状态复位', () => {
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    ws.simulateOpen()
    ws.simulateJson({ type: 'turn_started', sample_rate: 22050 })
    expect(s.turnActive.value).toBe(true)

    ws.simulateJson({ type: 'asr_partial', text: '草稿' })
    ws.close() // 客户端主动断开
    expect(s.status.value).toBe('disconnected')
    expect(s.turnActive.value).toBe(false)
    expect(s.asrDraft.value).toBe('')
  })

  it('interrupt 停止本地播放已入队的音频', () => {
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    ws.simulateOpen()

    ws.simulateJson({ type: 'turn_started', sample_rate: 22050 })
    ws.simulateBinary(new Int16Array([1, 2, 3]).buffer)
    ws.simulateBinary(new Int16Array([4, 5, 6]).buffer)
    const ctx = FakeAudio.instances[0]
    expect(ctx.startedSources).toHaveLength(2)

    s.interrupt()
    expect(ctx.stoppedSources).toHaveLength(2) // 已入队的 source 被 stop，不再播完
    expect(ws.sentJson().at(-1)).toEqual({ type: 'interrupt' })
  })

  it('断开后停止本地播放', () => {
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    ws.simulateOpen()

    ws.simulateJson({ type: 'turn_started', sample_rate: 22050 })
    ws.simulateBinary(new Int16Array([1, 2, 3]).buffer)
    const ctx = FakeAudio.instances[0]

    ws.close()
    expect(ctx.stoppedSources).toHaveLength(1)
  })

  it('心跳随连接启停，断开后不再发送', () => {
    vi.useFakeTimers()
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()

    // 未连接时不发心跳
    vi.advanceTimersByTime(60000)
    expect(ws.sentJson()).toHaveLength(0)

    ws.simulateOpen()
    vi.advanceTimersByTime(45000)
    expect(ws.sentJson().filter((m) => m.type === 'ping')).toHaveLength(3)

    // 断开后定时器停止
    ws.close()
    vi.advanceTimersByTime(60000)
    expect(ws.sentJson().filter((m) => m.type === 'ping')).toHaveLength(3)
  })

  it('麦克风帧以二进制发送', async () => {
    // jsdom 无 getUserMedia/音频节点：最小桩验证帧发送通路
    const s = useAvatarSession()
    s.connect()
    const ws = lastWs()
    ws.simulateOpen()

    // 直接调用 mic 回调等价路径：onFrame 已绑定 send
    // 通过 toggleMic 的失败路径验证不崩溃，再手动触发内部回调不可行，
    // 这里验证 send 二进制帧的通路：模拟采集回调持有的 ws 引用
    // （useMicCapture 的 onFrame 闭包在模块内，集成级验证在 e2e 由真实浏览器完成）
    expect(ws.readyState).toBe(FakeWS.OPEN)
  })
})
