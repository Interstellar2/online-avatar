// 会话核心：WebSocket 生命周期 + 消息路由 + 会话状态
// 协议与 app/ws_protocol.py 对齐；二进制帧=音频，JSON 文本帧=控制消息

import { getCurrentScope, onScopeDispose, ref, shallowRef } from 'vue'
import type { ChatEntry, ClientMessage, ServerMessage, SolutionName } from '../types'
import { createOpusDecoder, createOpusEncoder, isOpusSupported } from '../audio/opus'
import type { OpusDecoderHandle, OpusEncoderHandle } from '../audio/opus'
import { resampleInt16 } from '../audio/resample'
import { useAudioPlayer } from './useAudioPlayer'
import { useMicCapture } from './useMicCapture'

export type ConnStatus = 'disconnected' | 'connected'

// 麦克风采集固定 16k（与 useMicCapture 的 TARGET_RATE 对齐），仅作 encode 的源采样率标注
const MIC_SAMPLE_RATE = 16000

export function useAvatarSession() {
  const status = ref<ConnStatus>('disconnected')
  const solution = ref<SolutionName>('cascade')
  const entries = shallowRef<ChatEntry[]>([])
  const listening = ref(false) // 正在采集麦克风
  const turnActive = ref(false) // 服务端正在回答
  const asrDraft = ref('') // 识别中间结果
  const serverConfigured = ref<boolean | null>(null)

  let ws: WebSocket | null = null
  let entrySeq = 0
  let botEntryId: number | null = null // 正在流式追加的机器人条目
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let negotiatedCodec: 'pcm' | 'opus' = 'pcm' // 连接协商结果，决定上行是否编码
  let encoder: OpusEncoderHandle | null = null // 上行编码器，随连接生命周期创建/关闭
  let decoder: OpusDecoderHandle | null = null // 下行解码器，会话级一个、跨轮复用
  let turnCodec: 'pcm' | 'opus' = 'pcm' // 本轮下行帧编码，以 turn_started 为准
  let turnSampleRate = 22050 // 本轮下行目标采样率，解码回调里重采样要用

  const player = useAudioPlayer()
  const mic = useMicCapture((pcm) => {
    if (encoder) encoder.encode(pcm, MIC_SAMPLE_RATE) // opus：编码器输出回调里按包发送
    else sendRaw(pcm.buffer)
  })

  // 统一发送入口：未连接时静默丢弃（心跳、麦克风帧都会高频走到这里）
  const sendRaw = (data: string | ArrayBufferLike) => {
    if (ws?.readyState === WebSocket.OPEN) ws.send(data)
  }

  const startHeartbeat = () => {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => send({ type: 'ping' }), 15000)
  }

  const stopHeartbeat = () => {
    if (heartbeatTimer !== null) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  const push = (role: ChatEntry['role'], text: string) => {
    entrySeq += 1
    entries.value = [...entries.value, { id: entrySeq, role, text }]
  }

  const appendBot = (text: string) => {
    if (botEntryId === null) {
      entrySeq += 1
      botEntryId = entrySeq
      entries.value = [...entries.value, { id: botEntryId, role: 'bot', text }]
      return
    }
    entries.value = entries.value.map((e) =>
      e.id === botEntryId ? { ...e, text: e.text + text } : e,
    )
  }

  const connect = async () => {
    if (ws) disconnect()
    // 能力检测必须先于建连：结果决定 WS URL 是否带 codec 协商参数
    negotiatedCodec = (await isOpusSupported()) ? 'opus' : 'pcm'
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const codecQuery = negotiatedCodec === 'opus' ? '?codec=opus' : ''
    ws = new WebSocket(`${proto}://${location.host}/ws/avatar/${solution.value}${codecQuery}`)
    ws.binaryType = 'arraybuffer'
    if (negotiatedCodec === 'opus') {
      encoder = createOpusEncoder((data) => sendRaw(data))
    }

    ws.onopen = () => {
      status.value = 'connected'
      startHeartbeat() // 心跳跟连接生命周期绑定，避免泄漏游离定时器
      push('system', `已连接方案 ${solution.value}`)
    }
    ws.onclose = () => {
      status.value = 'disconnected'
      turnActive.value = false
      asrDraft.value = ''
      stopHeartbeat()
      player.stop() // 断开后不应继续播服务端余音
      mic.stop()
      encoder?.close()
      encoder = null
      decoder?.close()
      decoder = null
      listening.value = false
      push('system', '连接已断开')
      ws = null
    }
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        handleJson(JSON.parse(ev.data) as ServerMessage)
      } else if (turnCodec === 'opus' && decoder) {
        decoder.decode(ev.data) // opus 帧先进解码器，回调里重采样后送播放器
      } else {
        player.play(ev.data)
      }
    }
  }

  const disconnect = () => ws?.close()

  const handleJson = (msg: ServerMessage) => {
    switch (msg.type) {
      case 'pong':
        break
      case 'asr_partial':
        asrDraft.value = msg.text
        break
      case 'asr_final':
        asrDraft.value = ''
        push('user', msg.text)
        break
      case 'llm_token':
        appendBot(msg.text)
        break
      case 'turn_started': {
        player.reset(msg.sample_rate)
        turnSampleRate = msg.sample_rate
        // 以服务端 turn_started 为准（兼容协商 opus 但本轮回 pcm 的异常情况）；
        // 老版本服务端未带 codec 字段时按 pcm 透传
        turnCodec = msg.codec ?? 'pcm'
        if (turnCodec === 'opus' && !decoder) {
          // 解码器会话级一个、跨轮复用；输出恒为 48k，重采样到本轮目标采样率再播
          decoder = createOpusDecoder((pcm, srcRate) => {
            player.play(resampleInt16(pcm, srcRate, turnSampleRate).buffer)
          })
        }
        botEntryId = null // 新一轮重新开条目
        turnActive.value = true
        break
      }
      case 'turn_finished':
        turnActive.value = false
        botEntryId = null
        break
      case 'error':
        push('error', `[${msg.code}] ${msg.message}`)
        break
    }
  }

  const send = (msg: ClientMessage) => sendRaw(JSON.stringify(msg))

  const sendText = (content: string) => {
    const text = content.trim()
    if (text) send({ type: 'text', content: text })
  }

  const interrupt = () => {
    send({ type: 'interrupt' })
    player.stop() // 本地立即停播，否则已入队的音频会继续播完
    botEntryId = null
  }

  const toggleMic = async () => {
    if (mic.isCapturing.value) {
      mic.stop()
      listening.value = false
      return
    }
    try {
      await mic.start()
      listening.value = true
    } catch (e) {
      push('error', `麦克风启动失败: ${e}`)
    }
  }

  const checkHealth = async () => {
    try {
      const r = await fetch('/healthz')
      serverConfigured.value = (await r.json()).dashscope_configured
    } catch {
      serverConfigured.value = false
    }
  }

  // 心跳保活：连接期间由 startHeartbeat/stopHeartbeat 管理；
  // 组件作用域卸载时兜底清理（composable 也可能在测试等非组件环境调用，需先判断作用域存在）
  if (getCurrentScope()) onScopeDispose(stopHeartbeat)

  return {
    status,
    solution,
    entries,
    listening,
    turnActive,
    asrDraft,
    serverConfigured,
    playerSampleRate: player.sampleRate,
    connect,
    disconnect,
    sendText,
    interrupt,
    toggleMic,
    checkHealth,
  }
}
