// 与后端 app/ws_protocol.py 对齐的消息协议类型

// 方案注册表当前仅提供这两个方案；未知方案由服务端 error 消息兜底提示
export type SolutionName = 'cascade' | 'echo'

// 客户端 → 服务端（文本帧）
export interface PingMessage { type: 'ping' }
export interface InterruptMessage { type: 'interrupt' }
export interface TextMessage { type: 'text'; content: string }
export type ClientMessage = PingMessage | InterruptMessage | TextMessage

// 服务端 → 客户端（文本帧）
export interface PongMessage { type: 'pong' }
export interface AsrPartialMessage { type: 'asr_partial'; text: string }
export interface AsrFinalMessage { type: 'asr_final'; text: string }
export interface LlmTokenMessage { type: 'llm_token'; text: string }
// codec 告知本轮下行二进制帧的编码（pcm=PCM16 小端，opus=每帧一个 Opus 包）
export interface TurnStartedMessage { type: 'turn_started'; sample_rate: number; codec: 'pcm' | 'opus' }
export interface TurnFinishedMessage { type: 'turn_finished' }
export interface ErrorMessage { type: 'error'; code: string; message: string }
export type ServerMessage =
  | PongMessage
  | AsrPartialMessage
  | AsrFinalMessage
  | LlmTokenMessage
  | TurnStartedMessage
  | TurnFinishedMessage
  | ErrorMessage

// 会话内展示条目
export interface ChatEntry {
  id: number
  role: 'user' | 'bot' | 'system' | 'error'
  text: string
}
