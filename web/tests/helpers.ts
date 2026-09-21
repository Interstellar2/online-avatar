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

export interface FakeScriptProcessorNode {
  onaudioprocess: ((e: { inputBuffer: { getChannelData: (ch: number) => Float32Array } }) => void) | null
  connect: () => void
  disconnect: () => void
}

export class FakeAudioContext {
  static instances: FakeAudioContext[] = []
  currentTime = 0
  sampleRate = 48000 // 与真实浏览器常见的 48k 对齐，让麦克风重采样路径可测
  destination = {}
  createdBuffers: FakeAudioBuffer[] = []
  startedSources: { buffer: FakeAudioBuffer; at: number; source: FakeAudioBufferSource }[] = []
  stoppedSources: FakeAudioBufferSource[] = []
  createdProcessors: FakeScriptProcessorNode[] = [] // 供测试驱动 onaudioprocess 模拟采集回调

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

  createMediaStreamSource(_stream: unknown) {
    return { connect() {}, disconnect() {} }
  }

  createScriptProcessor(_bufferSize: number, _inputChannels: number, _outputChannels: number): FakeScriptProcessorNode {
    const node: FakeScriptProcessorNode = { onaudioprocess: null, connect() {}, disconnect() {} }
    this.createdProcessors.push(node)
    return node
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

// ---- WebCodecs 桩 ----
// 假编码器把输入采样可逆地打进包里（帧数 + 原始 s16 数据），假解码器原样还原，
// 目的是测试集成流（协商/编码发送/解码播放）而非真实 codec；输出回调同步触发，便于断言

// 包格式：4 字节小端采样数 + 原始 Int16 采样
export function makeOpusPacket(samples: Int16Array): ArrayBuffer {
  const buf = new ArrayBuffer(4 + samples.length * 2)
  new DataView(buf).setInt32(0, samples.length, true)
  new Int16Array(buf, 4).set(samples)
  return buf
}

export function parseOpusPacket(packet: ArrayBuffer): Int16Array {
  const count = new DataView(packet).getInt32(0, true)
  return new Int16Array(packet, 4, count)
}

export class FakeAudioData {
  format: string
  sampleRate: number
  numberOfFrames: number
  numberOfChannels: number
  timestamp: number
  samples: Int16Array // 假编码器从这里读输入采样

  constructor(init: {
    format: string
    sampleRate: number
    numberOfFrames: number
    numberOfChannels: number
    timestamp: number
    data: ArrayBuffer | Int16Array
  }) {
    this.format = init.format
    this.sampleRate = init.sampleRate
    this.numberOfFrames = init.numberOfFrames
    this.numberOfChannels = init.numberOfChannels
    this.timestamp = init.timestamp
    this.samples = init.data instanceof Int16Array ? init.data : new Int16Array(init.data)
  }

  close() {}
}

export class FakeEncodedAudioChunk {
  type: string
  timestamp: number
  data: ArrayBuffer
  byteLength: number

  constructor(init: { type: string; timestamp: number; data: ArrayBuffer }) {
    this.type = init.type
    this.timestamp = init.timestamp
    this.data = init.data
    this.byteLength = init.data.byteLength
  }

  copyTo(dst: ArrayBuffer) {
    new Uint8Array(dst).set(new Uint8Array(this.data))
  }

  close() {}
}

export class FakeAudioEncoder {
  static instances: FakeAudioEncoder[] = []

  static async isConfigSupported(config: unknown) {
    return { supported: true, config }
  }

  config: unknown = null
  closed = false
  encodedInputs: Int16Array[] = []
  private onOutput: (chunk: FakeEncodedAudioChunk) => void

  constructor(init: { output: (chunk: FakeEncodedAudioChunk) => void; error: (e: unknown) => void }) {
    this.onOutput = init.output
    FakeAudioEncoder.instances.push(this)
  }

  configure(config: unknown) {
    this.config = config
  }

  encode(data: FakeAudioData) {
    this.encodedInputs.push(data.samples)
    const packet = makeOpusPacket(data.samples)
    this.onOutput(new FakeEncodedAudioChunk({ type: 'key', timestamp: data.timestamp, data: packet }))
  }

  close() {
    this.closed = true
  }
}

export interface FakeAudioFrame {
  format: string
  sampleRate: number
  numberOfFrames: number
  numberOfChannels: number
  timestamp: number
  copyTo: (dst: Int16Array, options?: { format?: string }) => void
  close: () => void
}

export class FakeAudioDecoder {
  static instances: FakeAudioDecoder[] = []

  config: unknown = null
  closed = false
  private onOutput: (frame: FakeAudioFrame) => void

  constructor(init: { output: (frame: FakeAudioFrame) => void; error: (e: unknown) => void }) {
    this.onOutput = init.output
    FakeAudioDecoder.instances.push(this)
  }

  configure(config: unknown) {
    this.config = config
  }

  decode(chunk: FakeEncodedAudioChunk) {
    // 还原编码侧的采样，输出 Opus 原生 48k 帧，行为对齐真实解码器
    const samples = parseOpusPacket(chunk.data)
    this.onOutput({
      format: 's16',
      sampleRate: 48000,
      numberOfFrames: samples.length,
      numberOfChannels: 1,
      timestamp: chunk.timestamp,
      copyTo: (dst) => dst.set(samples),
      close: () => {},
    })
  }

  close() {
    this.closed = true
  }
}

const WEBCODECS_GLOBALS = ['AudioEncoder', 'AudioDecoder', 'AudioData', 'EncodedAudioChunk'] as const
let savedWebCodecs: Record<string, unknown> = {}

export function installFakeWebCodecs() {
  FakeAudioEncoder.instances = []
  FakeAudioDecoder.instances = []
  const g = globalThis as Record<string, unknown>
  savedWebCodecs = Object.fromEntries(WEBCODECS_GLOBALS.map((k) => [k, g[k]]))
  g.AudioEncoder = FakeAudioEncoder
  g.AudioDecoder = FakeAudioDecoder
  g.AudioData = FakeAudioData
  g.EncodedAudioChunk = FakeEncodedAudioChunk
}

export function uninstallFakeWebCodecs() {
  const g = globalThis as Record<string, unknown>
  for (const k of WEBCODECS_GLOBALS) {
    if (savedWebCodecs[k] === undefined) delete g[k]
    else g[k] = savedWebCodecs[k]
  }
}

// jsdom 无 getUserMedia：最小桩让 toggleMic 的采集链路可测
export function installFakeGetUserMedia() {
  const stream = { getTracks: () => [{ stop() {} }] }
  const fn = vi.fn().mockResolvedValue(stream)
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    value: { getUserMedia: fn },
    configurable: true,
  })
  return fn
}

export function mockFetchJson(body: unknown) {
  const fn = vi.fn().mockResolvedValue({ json: () => Promise.resolve(body) })
  ;(globalThis as Record<string, unknown>).fetch = fn
  return fn
}
