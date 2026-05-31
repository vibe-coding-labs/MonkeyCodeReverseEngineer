// MonkeyCode 多轮对话管理器
//
// 管理对话生命周期，支持复用任务/VM 实现多轮对话。
// 设计文档: docs/protocol/multi-turn-design.md

import WebSocket from "ws"
import { AuthManager } from "./auth.js"
import { wsHeaders } from "./browser-headers.js"
import type {
  MonkeyCodeModel,
  OpenAIMessage,
  OpenAIChatCompletionChunk,
  TaskStreamMessage,
  ACPSessionUpdate,
} from "./types.js"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"
const DEFAULT_CONVERSATION_TIMEOUT_MS = 30 * 60 * 1000 // 30 分钟
const DEFAULT_CLEANUP_INTERVAL_MS = 5 * 60 * 1000 // 5 分钟

/** 将 HTTP URL 转换为 WebSocket URL */
function httpToWs(url: string): string {
  return url.replace(/^https?/, (m) => (m === "https" ? "wss" : "ws"))
}

export interface Conversation {
  id: string
  taskId: string
  model: MonkeyCodeModel
  auth: AuthManager
  ws: WebSocket | null
  messages: OpenAIMessage[]
  lastUsedAt: number
  createdAt: number
  onChunk: ((chunk: OpenAIChatCompletionChunk) => void) | null
  resolvePromise: (() => void) | null
  rejectPromise: ((err: Error) => void) | null
}

export class ConversationManager {
  private conversations: Map<string, Conversation> = new Map()
  private cleanupTimer: ReturnType<typeof setInterval> | null = null
  private conversationTimeoutMs: number

  constructor(options?: { conversationTimeoutMs?: number; cleanupIntervalMs?: number }) {
    this.conversationTimeoutMs = options?.conversationTimeoutMs || DEFAULT_CONVERSATION_TIMEOUT_MS

    // 启动定时清理
    const cleanupInterval = options?.cleanupIntervalMs || DEFAULT_CLEANUP_INTERVAL_MS
    this.cleanupTimer = setInterval(() => this.cleanup(), cleanupInterval)
  }

  /** 创建新对话 */
  create(
    taskId: string,
    model: MonkeyCodeModel,
    auth: AuthManager,
    messages: OpenAIMessage[]
  ): Conversation {
    const id = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const conversation: Conversation = {
      id,
      taskId,
      model,
      auth,
      ws: null,
      messages: [...messages],
      lastUsedAt: Date.now(),
      createdAt: Date.now(),
      onChunk: null,
      resolvePromise: null,
      rejectPromise: null,
    }
    this.conversations.set(id, conversation)
    console.log(`[ConversationManager] Created conversation ${id} for task ${taskId}`)
    return conversation
  }

  /** 获取对话 */
  get(id: string): Conversation | undefined {
    const conversation = this.conversations.get(id)
    if (conversation) {
      conversation.lastUsedAt = Date.now()
    }
    return conversation
  }

  /** 删除对话 */
  delete(id: string): boolean {
    const conversation = this.conversations.get(id)
    if (conversation) {
      if (conversation.ws) {
        conversation.ws.close()
      }
      this.conversations.delete(id)
      console.log(`[ConversationManager] Deleted conversation ${id}`)
      return true
    }
    return false
  }

  /** 获取对话数量 */
  size(): number {
    return this.conversations.size
  }

  /** 清理过期对话 */
  private cleanup(): void {
    const now = Date.now()
    for (const [id, conversation] of this.conversations) {
      if (now - conversation.lastUsedAt > this.conversationTimeoutMs) {
        console.log(`[ConversationManager] Cleaning up expired conversation ${id}`)
        this.delete(id)
      }
    }
  }

  /** 停止清理定时器 */
  destroy(): void {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer)
      this.cleanupTimer = null
    }
    // 关闭所有对话
    for (const [id] of this.conversations) {
      this.delete(id)
    }
  }

  /** 连接到任务的 WebSocket */
  async connectToTask(
    conversation: Conversation,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const auth = conversation.auth
      const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
      const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${conversation.taskId}&mode=attach`

      const ws = new WebSocket(wsUrl, {
        headers: wsHeaders("monkeycode-ai.com", `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`),
      })

      conversation.ws = ws
      conversation.onChunk = onChunk
      conversation.resolvePromise = resolve
      conversation.rejectPromise = reject

      let resolved = false

      const cleanup = () => {
        resolved = true
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close()
        }
        conversation.ws = null
      }

      ws.on("open", () => {
        console.log(`[ConversationManager] WebSocket connected for conversation ${conversation.id}`)
        // 启用自动审批模式
        ws.send(JSON.stringify({ type: "auto-approve" }))
        if (!resolved) {
          resolved = true
          resolve()
        }
      })

      ws.on("message", (raw: WebSocket.Data) => {
        try {
          const msg: TaskStreamMessage = JSON.parse(raw.toString())

          // 心跳响应
          if (msg.type === "ping") {
            ws.send(JSON.stringify({ type: "ping" }))
            return
          }

          this.handleStreamMessage(msg, conversation)
        } catch {
          // 忽略解析错误
        }
      })

      ws.on("close", () => {
        if (!resolved) {
          resolved = true
          resolve()
        }
        conversation.ws = null
      })

      ws.on("error", (err) => {
        if (!resolved) {
          resolved = true
          reject(err)
        }
        conversation.ws = null
      })

      // 超时保护
      setTimeout(() => {
        if (!resolved) {
          console.warn(`[ConversationManager] WebSocket connection timed out for conversation ${conversation.id}`)
          cleanup()
          resolve()
        }
      }, 30000) // 30 秒连接超时
    })
  }

  /** 发送用户输入 */
  sendUserInput(conversation: Conversation, content: string): void {
    if (!conversation.ws || conversation.ws.readyState !== WebSocket.OPEN) {
      throw new Error(`Conversation ${conversation.id} is not connected`)
    }

    const userMsg = {
      type: "user-input",
      data: content,
    }
    conversation.ws.send(JSON.stringify(userMsg))
    conversation.lastUsedAt = Date.now()
    console.log(`[ConversationManager] Sent user-input for conversation ${conversation.id}`)
  }

  /** 处理流式消息 */
  private handleStreamMessage(msg: TaskStreamMessage, conversation: Conversation): void {
    const chatId = `chatcmpl-${conversation.taskId}`
    const now = Math.floor(Date.now() / 1000)
    const onChunk = conversation.onChunk

    if (!onChunk) return

    switch (msg.type) {
      case "task-started":
        console.log(`[ConversationManager] Task started for conversation ${conversation.id}`)
        break

      case "task-running":
        if (msg.kind === "acp_event") {
          try {
            const acp: ACPSessionUpdate = JSON.parse(msg.data)
            this.handleACPEvent(acp, chatId, now, onChunk, conversation)
          } catch {
            // 忽略解析错误
          }
        } else if (msg.kind === "acp_ask_user_question") {
          // 自动回复
          try {
            const questionData = JSON.parse(msg.data)
            const requestId = questionData.request_id || questionData.id || ""
            console.log(`[ConversationManager] Auto-answering question for conversation ${conversation.id}`)
            conversation.ws?.send(JSON.stringify({
              type: "reply-question",
              data: JSON.stringify({
                request_id: requestId,
                answers_json: "",
                cancelled: false,
              }),
            }))
          } catch {
            // ignore parse errors
          }
        }
        break

      case "task-ended":
        onChunk({
          id: chatId,
          object: "chat.completion.chunk",
          created: now,
          model: "monkeycode",
          choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
        })
        if (conversation.resolvePromise) {
          conversation.resolvePromise()
          conversation.resolvePromise = null
          conversation.rejectPromise = null
        }
        break

      case "task-error":
        onChunk({
          id: chatId,
          object: "chat.completion.chunk",
          created: now,
          model: "monkeycode",
          choices: [{ index: 0, delta: { content: `[Error] ${msg.data}` }, finish_reason: null }],
        })
        break
    }
  }

  /** 处理 ACP 事件 */
  private handleACPEvent(
    acp: ACPSessionUpdate,
    chatId: string,
    now: number,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void,
    conversation: Conversation
  ): void {
    switch (acp.type) {
      case "agent_message_chunk": {
        const text = acp.text || acp.content || ""
        if (text) {
          onChunk({
            id: chatId,
            object: "chat.completion.chunk",
            created: now,
            model: "monkeycode",
            choices: [{ index: 0, delta: { content: text }, finish_reason: null }],
          })
        }
        break
      }

      case "agent_thought_chunk": {
        const text = acp.text || acp.content || ""
        if (text) {
          onChunk({
            id: chatId,
            object: "chat.completion.chunk",
            created: now,
            model: "monkeycode",
            choices: [{ index: 0, delta: { content: `[Thinking] ${text}` }, finish_reason: null }],
          })
        }
        break
      }

      case "usage_update":
        // 记录 usage（在最终 chunk 中返回）
        break

      case "tool_call": {
        const toolName = acp.tool_name || "unknown"
        const toolInput = acp.tool_input || ""
        onChunk({
          id: chatId,
          object: "chat.completion.chunk",
          created: now,
          model: "monkeycode",
          choices: [{ index: 0, delta: { content: `[Tool: ${toolName}] ${toolInput}` }, finish_reason: null }],
        })
        break
      }

      case "tool_call_update": {
        const updateArgs = String(acp.tool_input || acp.delta || "")
        const status = String(acp.status || "")
        console.log(`[ConversationManager] tool_call_update: status=${status}, args=${updateArgs.slice(0, 100)}`)
        break
      }

      case "plan": {
        const planData = acp.steps || acp
        console.log(`[ConversationManager] plan:`, JSON.stringify(planData).slice(0, 200))
        break
      }

      case "available_commands_update": {
        const commandsData = acp.commands || acp
        console.log(`[ConversationManager] available_commands:`, JSON.stringify(commandsData).slice(0, 200))
        break
      }
    }
  }
}
