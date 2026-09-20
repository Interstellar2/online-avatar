// 会话核心：WebSocket 生命周期 + 消息路由 + 会话状态
// 协议与 app/ws_protocol.py 对齐；二进制帧=音频，JSON 文本帧=控制消息

import { getCurrentScope, onScopeDispose, ref, shallowRef } from 'vue'
import type { ChatEntry, ClientMessage, ServerMessage, SolutionName } from '../types'
import { useAudioPlayer } from './useAudioPlayer'
import { useMicCapture } from './useMicCapture'

export type ConnStatus = 'disconnected' | 'connected'

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

  const player = useAudioPlayer()
  const mic = useMicCapture((pcm) => sendRaw(pcm.buffer))

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

  const connect = () => {
    if (ws) disconnect()
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws/avatar/${solution.value}`)
    ws.binaryType = 'arraybuffer'

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
      listening.value = false
      push('system', '连接已断开')
      ws = null
    }
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        handleJson(JSON.parse(ev.data) as ServerMessage)
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
      case 'turn_started':
        player.reset(msg.sample_rate)
        botEntryId = null // 新一轮重新开条目
        turnActive.value = true
        break
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
