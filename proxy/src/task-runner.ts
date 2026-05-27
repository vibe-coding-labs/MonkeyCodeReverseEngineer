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

    const body = {
      content: prompt,
      host_id: hostId,
      image_id: imageId,
      model_id: model.id,
      cli_name: "claude",
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
        // mode=new 要求客户端先发送 user-input 才开始流式输出
        // 使用旧格式（纯文本）兼容性最好
        const userMsg = {
          type: "user-input",
          data: prompt,
        }
        ws.send(JSON.stringify(userMsg))
        console.log(`[TaskRunner] Sent user-input for task ${taskId}`)
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

          this.handleStreamMessage(msg, taskId, onChunk)
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

      // 超时保护（5 分钟）
      setTimeout(() => {
        if (!resolved) {
          cleanup()
          resolve()
        }
      }, 5 * 60 * 1000)
    })
  }

  /** 处理流式消息，转换为 OpenAI 格式 */
  private handleStreamMessage(
    msg: TaskStreamMessage,
    taskId: string,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void
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
            this.handleACPEvent(acp, chatId, now, onChunk)
          } catch {
            // 忽略解析错误
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
    onChunk: (chunk: OpenAIChatCompletionChunk) => void
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
        // Token usage — recorded but not sent as separate chunk
        break
    }
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
