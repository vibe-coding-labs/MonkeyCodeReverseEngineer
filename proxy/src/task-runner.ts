// MonkeyCode 任务流 — 通过 WebSocket 创建任务并接收流式输出

import WebSocket from "ws"
import { AuthManager } from "./auth.js"
import type {
  MonkeyCodeModel,
  TaskStreamMessage,
  ACPSessionUpdate,
  OpenAIChatCompletionChunk,
  OpenAIChatCompletionRequest,
  OpenAIMessage,
} from "./types.js"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"

/** 将 HTTP URL 转换为 WebSocket URL */
function httpToWs(url: string): string {
  return url.replace(/^https?/, (m) => (m === "https" ? "wss" : "ws"))
}

export class TaskRunner {
  private auth: AuthManager

  constructor(auth: AuthManager) {
    this.auth = auth
  }

  /** 创建 VM */
  async createVM(): Promise<string> {
    const headers = await this.auth.authHeaders()
    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/hosts/vms`

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({}),
    })

    if (!response.ok) {
      throw new Error(`Failed to create VM (${response.status}): ${await response.text()}`)
    }

    const result = await response.json()
    const data = result.data || result
    return data.id || data.vm_id
  }

  /** 列出已有 VM */
  async listVMs(): Promise<{ id: string; status: string }[]> {
    const headers = await this.auth.authHeaders()
    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/hosts/vms`

    const response = await fetch(url, { headers })
    if (!response.ok) {
      throw new Error(`Failed to list VMs (${response.status}): ${await response.text()}`)
    }

    const result = await response.json()
    const data = result.data || result
    return data.vms || data || []
  }

  /** 创建任务 */
  async createTask(vmId: string, model: MonkeyCodeModel, prompt: string): Promise<string> {
    const headers = await this.auth.authHeaders()
    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/tasks`

    const apiType = model.interface_type === "anthropic" ? "anthropic" : "openai"

    const body = {
      vm_id: vmId,
      llm: {
        api_key: model.api_key,
        base_url: model.base_url,
        model: model.model,
        api_type: apiType,
        temperature: model.temperature,
      },
      coding_agent: 2, // Claude agent
      prompt,
      working_dir: "/workspace",
    }

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      throw new Error(`Failed to create task (${response.status}): ${await response.text()}`)
    }

    const result = await response.json()
    const data = result.data || result
    return data.id || data.task_id
  }

  /** 通过 WebSocket 连接任务流并收集输出 */
  async streamTask(
    taskId: string,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void,
    signal?: AbortSignal
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
      const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=new`

      const ws = new WebSocket(wsUrl, {
        headers: {
          Cookie: `${this.auth.getSessionCookieSync()}`,
        },
      })

      let resolved = false
      let fullContent = ""

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
      })

      ws.on("message", (raw: WebSocket.Data) => {
        if (resolved) return

        try {
          const msg: TaskStreamMessage = JSON.parse(raw.toString())
          this.handleStreamMessage(msg, taskId, onChunk, (content) => {
            fullContent = content
          })
        } catch (e) {
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
    onChunk: (chunk: OpenAIChatCompletionChunk) => void,
    onContent: (content: string) => void
  ): void {
    const chatId = `chatcmpl-${taskId}`
    const now = Math.floor(Date.now() / 1000)

    switch (msg.type) {
      case "task-running":
        if (msg.kind === "acp_event") {
          try {
            const acp: ACPSessionUpdate = JSON.parse(msg.data)
            this.handleACPEvent(acp, chatId, now, onChunk, onContent)
          } catch {
            // 忽略解析错误
          }
        }
        break

      case "task-ended":
        // 发送结束 chunk
        onChunk({
          id: chatId,
          object: "chat.completion.chunk",
          created: now,
          model: "monkeycode",
          choices: [
            {
              index: 0,
              delta: {},
              finish_reason: "stop",
            },
          ],
        })
        break

      case "task-error":
        // 将错误作为内容发送
        onChunk({
          id: chatId,
          object: "chat.completion.chunk",
          created: now,
          model: "monkeycode",
          choices: [
            {
              index: 0,
              delta: { content: `[Error] ${msg.data}` },
              finish_reason: null,
            },
          ],
        })
        break

      // 忽略 ping, cursor, task-started 等
    }
  }

  /** 处理 ACP 事件 */
  private handleACPEvent(
    acp: ACPSessionUpdate,
    chatId: string,
    now: number,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void,
    onContent: (content: string) => void
  ): void {
    switch (acp.type) {
      case "agent_message_chunk": {
        const text = acp.text || acp.content || ""
        onChunk({
          id: chatId,
          object: "chat.completion.chunk",
          created: now,
          model: "monkeycode",
          choices: [
            {
              index: 0,
              delta: { content: text },
              finish_reason: null,
            },
          ],
        })
        break
      }

      case "agent_thought_chunk": {
        // 思考内容，可以作为 reasoning_content 或跳过
        const text = acp.text || acp.content || ""
        if (text) {
          onChunk({
            id: chatId,
            object: "chat.completion.chunk",
            created: now,
            model: "monkeycode",
            choices: [
              {
                index: 0,
                delta: { content: `[Thinking] ${text}` },
                finish_reason: null,
              },
            ],
          })
        }
        break
      }

      case "usage_update": {
        // Token 使用量，在最后 chunk 中附带
        // 不单独发送，等 task-ended 时处理
        break
      }

      // 忽略其他 ACP 事件
    }
  }

  /** 发送用户输入到任务流 */
  async sendUserInput(taskId: string, content: string): Promise<void> {
    const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
    const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=attach`

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(wsUrl, {
        headers: {
          Cookie: `${this.auth.getSessionCookieSync()}`,
        },
      })

      ws.on("open", () => {
        const msg = {
          type: "user-input",
          data: JSON.stringify({
            content: Buffer.from(content).toString("base64"),
            attachments: [],
          }),
        }
        ws.send(JSON.stringify(msg))
        setTimeout(() => {
          ws.close()
          resolve()
        }, 1000)
      })

      ws.on("error", reject)
    })
  }

  /** 停止任务 */
  async stopTask(taskId: string): Promise<void> {
    const headers = await this.auth.authHeaders()
    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/tasks/${taskId}/stop`

    await fetch(url, { method: "POST", headers })
  }
}
