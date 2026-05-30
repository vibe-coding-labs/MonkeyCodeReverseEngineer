// MonkeyCode 任务流 — 通过正确的 API 格式创建任务并接收流式输出

import WebSocket from "ws"
import { AuthManager } from "./auth.js"
import type {
  MonkeyCodeModel,
  TaskStreamMessage,
  ACPSessionUpdate,
  OpenAIChatCompletionChunk,
} from "./types.js"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"
const DEFAULT_HOST_ID = process.env.MONKEYCODE_HOST_ID || "public_host"
const DEFAULT_IMAGE_ID = process.env.MONKEYCODE_IMAGE_ID || ""
const TASK_TIMEOUT_MS = parseInt(process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000", 10) // 1h default, matches resource.life

/** 将 HTTP URL 转换为 WebSocket URL */
function httpToWs(url: string): string {
  return url.replace(/^https?/, (m) => (m === "https" ? "wss" : "ws"))
}

export class TaskRunner {
  private auth: AuthManager

  constructor(auth: AuthManager) {
    this.auth = auth
  }

  /** 创建任务 — 使用实际后端 API 格式 (llm-protocol-complete.md §4.5) */
  async createTask(
    model: MonkeyCodeModel,
    prompt: string,
    options?: {
      hostId?: string
      imageId?: string
      systemPrompt?: string
      authOverride?: AuthManager
    }
  ): Promise<string> {
    const auth = options?.authOverride || this.auth
    const headers = await auth.authHeaders()
    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/tasks`

    const hostId = options?.hostId || DEFAULT_HOST_ID
    const imageId = options?.imageId || DEFAULT_IMAGE_ID

    if (!imageId) {
      throw new Error(
        "MONKEYCODE_IMAGE_ID is required. Set it in .env or pass imageId option. " +
        "Get it from browser DevTools → Network → POST /api/v1/users/tasks → image_id field."
      )
    }

    const body: Record<string, unknown> = {
      content: prompt,
      host_id: hostId,
      image_id: imageId,
      model_id: model.id,
      cli_name: model.interface_type === "openai_responses" ? "codex"
        : model.interface_type === "anthropic" ? "claude"
        : "opencode",
      resource: {
        core: 1,
        memory: 1073741824,  // 1 GB
        life: 3600,           // 1 hour
      },
      repo: {
        repo_url: "",
        branch: "master",
        repo_filename: "",
        zip_url: "",
      },
    }

    if (options?.systemPrompt) {
      body.system_prompt = options.systemPrompt
    }

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const respText = await response.text()
      throw new Error(`Failed to create task (${response.status}): ${respText}`)
    }

    const result = await response.json()
    const data = result.data || result
    return data.id || data.task_id
  }

  /** 通过 WebSocket 连接任务流并收集输出 */
  async streamTask(
    taskId: string,
    prompt: string,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void,
    signal?: AbortSignal,
    authOverride?: AuthManager
  ): Promise<void> {
    const auth = authOverride || this.auth
    return new Promise((resolve, reject) => {
      const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
      const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=new`

      const ws = new WebSocket(wsUrl, {
        headers: {
          Cookie: `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`,
        },
      })

      let resolved = false
      let accumulatedUsage = { input_tokens: 0, output_tokens: 0, total_tokens: 0 }

      const cleanup = () => {
        resolved = true
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close()
        }
      }

      if (signal) {
        signal.addEventListener("abort", () => {
          cleanup()
          resolve()
        })
      }

      ws.on("open", () => {
        console.log(`[TaskRunner] WebSocket connected for task ${taskId}`)
        // 启用自动审批模式 — Agent 不再等待用户确认
        ws.send(JSON.stringify({ type: "auto-approve" }))
        // mode=new 要求客户端先发送 user-input 才开始流式输出
        const userMsg = {
          type: "user-input",
          data: prompt,
        }
        ws.send(JSON.stringify(userMsg))
        console.log(`[TaskRunner] Sent auto-approve + user-input for task ${taskId}`)
      })

      ws.on("message", (raw: WebSocket.Data) => {
        if (resolved) return

        try {
          const msg: TaskStreamMessage = JSON.parse(raw.toString())

          // 心跳响应
          if (msg.type === "ping") {
            ws.send(JSON.stringify({ type: "ping" }))
            return
          }

          this.handleStreamMessage(msg, taskId, onChunk, accumulatedUsage, ws)
        } catch {
          // 忽略非 JSON 消息
        }
      })

      ws.on("close", () => {
        if (!resolved) {
          resolved = true
          resolve()
        }
      })

      ws.on("error", (err) => {
        if (!resolved) {
          resolved = true
          reject(err)
        }
      })

      // 超时保护 — 默认 1 小时，匹配 resource.life，可通过 MONKEYCODE_TASK_TIMEOUT_MS 配置
      setTimeout(() => {
        if (!resolved) {
          console.warn(`[TaskRunner] Task ${taskId} timed out after ${TASK_TIMEOUT_MS / 1000}s`)
          cleanup()
          resolve()
        }
      }, TASK_TIMEOUT_MS)
    })
  }

  /** 处理流式消息，转换为 OpenAI 格式 */
  private handleStreamMessage(
    msg: TaskStreamMessage,
    taskId: string,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void,
    usage: { input_tokens: number; output_tokens: number; total_tokens: number },
    ws: WebSocket
  ): void {
    const chatId = `chatcmpl-${taskId}`
    const now = Math.floor(Date.now() / 1000)

    switch (msg.type) {
      case "task-started":
        console.log(`[TaskRunner] Task ${taskId} started`)
        break

      case "task-running":
        if (msg.kind === "acp_event") {
          try {
            const acp: ACPSessionUpdate = JSON.parse(msg.data)
            this.handleACPEvent(acp, chatId, now, onChunk, usage)
          } catch {
            // 忽略解析错误
          }
        } else if (msg.kind === "acp_ask_user_question") {
          // Agent 请求用户确认 — 自动回复以继续执行
          try {
            const questionData = JSON.parse(msg.data)
            const requestId = questionData.request_id || questionData.id || ""
            console.log(`[TaskRunner] Auto-answering question for task ${taskId}: ${requestId}`)
            ws.send(JSON.stringify({
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
          usage: usage.total_tokens > 0 ? {
            prompt_tokens: usage.input_tokens,
            completion_tokens: usage.output_tokens,
            total_tokens: usage.total_tokens,
          } : undefined,
        })
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
    usage: { input_tokens: number; output_tokens: number; total_tokens: number }
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
        if (acp.input_tokens) usage.input_tokens = acp.input_tokens
        if (acp.output_tokens) usage.output_tokens = acp.output_tokens
        if (acp.total_tokens) usage.total_tokens = acp.total_tokens
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
        // Log tool call updates for debugging
        const updateArgs = String(acp.tool_input || acp.delta || "")
        const status = String(acp.status || "")
        console.log(`[TaskRunner] tool_call_update: status=${status}, args=${updateArgs.slice(0, 100)}`)
        break
      }

      case "plan": {
        // Log execution plan for debugging
        const planData = acp.steps || acp
        console.log(`[TaskRunner] plan:`, JSON.stringify(planData).slice(0, 200))
        break
      }

      case "available_commands_update": {
        // Log available commands for debugging
        const commandsData = acp.commands || acp
        console.log(`[TaskRunner] available_commands:`, JSON.stringify(commandsData).slice(0, 200))
        break
      }
    }
  }

  /** 原始 ACP 事件流 — 供 Responses API 使用 */
  async streamTaskRaw(
    taskId: string,
    prompt: string,
    onEvent: (event: { type: string; data: any }) => void,
    signal?: AbortSignal,
    authOverride?: AuthManager
  ): Promise<{ input_tokens: number; output_tokens: number; total_tokens: number }> {
    const auth = authOverride || this.auth
    return new Promise((resolve, reject) => {
      const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
      const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=new`

      const ws = new WebSocket(wsUrl, {
        headers: {
          Cookie: `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`,
        },
      })

      let resolved = false
      const usage = { input_tokens: 0, output_tokens: 0, total_tokens: 0 }

      const cleanup = () => {
        resolved = true
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close()
        }
      }

      if (signal) {
        signal.addEventListener("abort", () => {
          cleanup()
          resolve(usage)
        })
      }

      ws.on("open", () => {
        ws.send(JSON.stringify({ type: "auto-approve" }))
        ws.send(JSON.stringify({ type: "user-input", data: prompt }))
      })

      ws.on("message", (raw: WebSocket.Data) => {
        if (resolved) return
        try {
          const msg: TaskStreamMessage = JSON.parse(raw.toString())

          if (msg.type === "ping") {
            ws.send(JSON.stringify({ type: "ping" }))
            return
          }

          if (msg.type === "task-started") {
            onEvent({ type: "task-started", data: {} })
          } else if (msg.type === "task-running" && msg.kind === "acp_event") {
            const acp: ACPSessionUpdate = JSON.parse(msg.data)
            if (acp.type === "usage_update") {
              if (acp.input_tokens) usage.input_tokens = acp.input_tokens
              if (acp.output_tokens) usage.output_tokens = acp.output_tokens
              if (acp.total_tokens) usage.total_tokens = acp.total_tokens
            }
            onEvent({ type: "acp", data: acp })
          } else if (msg.type === "task-running" && msg.kind === "acp_ask_user_question") {
            const questionData = JSON.parse(msg.data)
            ws.send(JSON.stringify({
              type: "reply-question",
              data: JSON.stringify({
                request_id: questionData.request_id || questionData.id || "",
                answers_json: "",
                cancelled: false,
              }),
            }))
          } else if (msg.type === "task-ended") {
            onEvent({ type: "task-ended", data: {} })
            cleanup()
            resolve(usage)
          } else if (msg.type === "task-error") {
            onEvent({ type: "task-error", data: msg.data })
            cleanup()
            resolve(usage)
          }
        } catch {
          // ignore parse errors
        }
      })

      ws.on("close", () => {
        if (!resolved) {
          resolved = true
          resolve(usage)
        }
      })

      ws.on("error", (err) => {
        if (!resolved) {
          resolved = true
          reject(err)
        }
      })

      // 超时保护 — 默认 1 小时，匹配 resource.life
      setTimeout(() => {
        if (!resolved) {
          console.warn(`[TaskRunner] Task ${taskId} timed out after ${TASK_TIMEOUT_MS / 1000}s`)
          cleanup()
          resolve(usage)
        }
      }, TASK_TIMEOUT_MS)
    })
  }

  /** 停止任务 */
  async stopTask(taskId: string, authOverride?: AuthManager): Promise<void> {
    const auth = authOverride || this.auth
    const headers = await auth.authHeaders()
    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/tasks/stop`

    await fetch(url, {
      method: "PUT",
      headers,
      body: JSON.stringify({ id: taskId }),
    })
  }
}
