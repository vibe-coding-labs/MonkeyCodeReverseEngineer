// OpenAI 兼容 API 路由 — 将 OpenAI 格式请求转换为 MonkeyCode 任务
// 支持号池轮转：每个请求从 AccountPool 获取账号

import { Router, type Request, type Response } from "express"
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import { AccountPool } from "./account-pool.js"
import type {
  OpenAIChatCompletionRequest,
  OpenAIChatCompletionResponse,
  OpenAIChatCompletionChunk,
  OpenAIModelsResponse,
  OpenAIMessage,
} from "./types.js"

export function createAPIRouter(
  modelManager: ModelManager,
  taskRunner: TaskRunner,
  accountPool?: AccountPool
): Router {
  const router = Router()

  // ========== GET /v1/models ==========
  router.get("/v1/models", async (_req: Request, res: Response) => {
    try {
      const models = await modelManager.toOpenAIModels()
      const response: OpenAIModelsResponse = {
        object: "list",
        data: models,
      }
      res.json(response)
    } catch (err: any) {
      console.error("[Models] Error:", err.message)
      res.status(500).json({ error: { message: err.message, type: "internal_error" } })
    }
  })

  // ========== POST /v1/chat/completions ==========
  router.post("/v1/chat/completions", async (req: Request, res: Response) => {
    try {
      const body: OpenAIChatCompletionRequest = req.body

      // 验证请求
      if (!body.messages || body.messages.length === 0) {
        res.status(400).json({ error: { message: "messages is required", type: "invalid_request_error" } })
        return
      }

      // 解析模型
      const model = await modelManager.resolveModel(body.model || "")
      if (!model) {
        res.status(404).json({ error: { message: `Model '${body.model}' not found`, type: "invalid_request_error" } })
        return
      }

      // 获取账号（号池模式优先）
      let accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null
      const usePool = !!accountAuth

      // 构造 prompt
      const prompt = messagesToPrompt(body.messages)

      // 创建任务（不需要 VM 管理，task API 自动处理）
      const taskId = await taskRunner.createTask(model, prompt, {
        authOverride: accountAuth || undefined,
      })
      console.log(`[Chat] Task created: ${taskId}, model: ${model.model}${usePool ? " (pooled)" : ""}`)

      if (body.stream) {
        await handleStreamResponse(res, taskRunner, taskId, model, prompt, accountPool, accountAuth)
      } else {
        await handleNonStreamResponse(res, taskRunner, taskId, model, prompt, accountPool, accountAuth)
      }
    } catch (err: any) {
      console.error("[Chat] Error:", err.message)
      if (!res.headersSent) {
        res.status(500).json({ error: { message: err.message, type: "internal_error" } })
      }
    }
  })

  return router
}

/** 将消息列表转换为 prompt */
function messagesToPrompt(messages: OpenAIMessage[]): string {
  return messages
    .map((m) => {
      switch (m.role) {
        case "system":
          return `[System]\n${m.content}`
        case "user":
          return `[User]\n${m.content}`
        case "assistant":
          return `[Assistant]\n${m.content}`
        default:
          return m.content
      }
    })
    .join("\n\n")
}

/** 流式响应处理 */
async function handleStreamResponse(
  res: Response,
  taskRunner: TaskRunner,
  taskId: string,
  model: import("./types.js").MonkeyCodeModel,
  prompt: string,
  pool?: AccountPool,
  auth?: import("./auth.js").AuthManager | null
): Promise<void> {
  res.setHeader("Content-Type", "text/event-stream")
  res.setHeader("Cache-Control", "no-cache")
  res.setHeader("Connection", "keep-alive")
  res.setHeader("X-Accel-Buffering", "no")

  const abortController = new AbortController()

  res.on("close", () => {
    abortController.abort()
  })

  const sendSSE = (data: object) => {
    if (res.writableEnded) return
    res.write(`data: ${JSON.stringify(data)}\n\n`)
  }

  try {
    await taskRunner.streamTask(
      taskId,
      prompt,
      (chunk: OpenAIChatCompletionChunk) => {
        sendSSE(chunk)
      },
      abortController.signal,
      auth || undefined
    )
  } catch (err: any) {
    console.error("[Stream] Error:", err.message)
  } finally {
    sendSSE({ object: "done" })
    res.write("data: [DONE]\n\n")
    res.end()
    if (auth && pool) {
      pool.releaseWs(auth)
    }
  }
}

/** 非流式响应处理 */
async function handleNonStreamResponse(
  res: Response,
  taskRunner: TaskRunner,
  taskId: string,
  model: import("./types.js").MonkeyCodeModel,
  prompt: string,
  pool?: AccountPool,
  auth?: import("./auth.js").AuthManager | null
): Promise<void> {
  let fullContent = ""

  await taskRunner.streamTask(taskId, prompt, (chunk: OpenAIChatCompletionChunk) => {
    for (const choice of chunk.choices) {
      if (choice.delta?.content) {
        fullContent += choice.delta.content
      }
    }
  }, undefined, auth || undefined)

  const response: OpenAIChatCompletionResponse = {
    id: `chatcmpl-${taskId}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: model.model,
    choices: [
      {
        index: 0,
        message: { role: "assistant", content: fullContent },
        finish_reason: "stop",
      },
    ],
    usage: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    },
  }

  res.json(response)
}
