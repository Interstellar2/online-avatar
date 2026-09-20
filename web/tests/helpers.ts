// 测试公共工具：FakeWebSocket / FakeAudioContext / fetch mock

export class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []

  url: string
  readyState = 0
  binaryType = 'arraybuffer'
  sent: (string | ArrayBuffer)[] = []
  closed = false

  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((ev: { data: string | ArrayBuffer }) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data)
  }

  close() {
    this.closed = true
    this.readyState = 3
    this.onclose?.()
  }

  // ---- 模拟服务端 ----
  simulateOpen() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }

  simulateJson(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) })
  }

  simulateBinary(data: ArrayBuffer) {
    this.onmessage?.({ data })
  }

  sentJson(): Record<string, unknown>[] {
    return this.sent.filter((s): s is string => typeof s === 'string').map((s) => JSON.parse(s))
  }

  sentBinary(): ArrayBuffer[] {
    return this.sent.filter((s): s is ArrayBuffer => typeof s !== 'string')
  }
}

export function installFakeWebSocket() {
  FakeWebSocket.instances = []
  ;(globalThis as Record<string, unknown>).WebSocket = FakeWebSocket
  return FakeWebSocket
}

export interface FakeAudioBuffer {
  duration: number
  channel: Float32Array
  getChannelData: (ch: number) => Float32Array
}

export interface FakeAudioBufferSource {
  buffer: FakeAudioBuffer | null
  stopped: boolean
  ended: boolean
  onended: (() => void) | null
  connect: () => void
  start: (at: number) => void
  stop: () => void
  // 模拟自然播完，触发 onended（播放器依赖它回收活跃 source）
  simulateEnded: () => void
}

export class FakeAudioContext {
  static instances: FakeAudioContext[] = []
  currentTime = 0
  destination = {}
  createdBuffers: FakeAudioBuffer[] = []
  startedSources: { buffer: FakeAudioBuffer; at: number; source: FakeAudioBufferSource }[] = []
  stoppedSources: FakeAudioBufferSource[] = []

  constructor() {
    FakeAudioContext.instances.push(this)
  }

  createBuffer(_channels: number, length: number, sampleRate: number): FakeAudioBuffer {
    const channel = new Float32Array(length)
    const buf: FakeAudioBuffer = {
      duration: length / sampleRate,
      channel,
      getChannelData: () => channel,
    }
    this.createdBuffers.push(buf)
    return buf
  }

  createBufferSource(): FakeAudioBufferSource {
    const ctx = this
    const source: FakeAudioBufferSource = {
      buffer: null,
      stopped: false,
      ended: false,
      onended: null,
      connect() {},
      start(at: number) {
        if (source.buffer) ctx.startedSources.push({ buffer: source.buffer, at, source })
      },
      stop() {
        source.stopped = true
        ctx.stoppedSources.push(source)
      },
      simulateEnded() {
        source.ended = true
        source.onended?.()
      },
    }
    return source
  }
}

export function installFakeAudioContext() {
  FakeAudioContext.instances = []
  ;(globalThis as Record<string, unknown>).AudioContext = FakeAudioContext
  return FakeAudioContext
}

export function mockFetchJson(body: unknown) {
  const fn = vi.fn().mockResolvedValue({ json: () => Promise.resolve(body) })
  ;(globalThis as Record<string, unknown>).fetch = fn
  return fn
}
