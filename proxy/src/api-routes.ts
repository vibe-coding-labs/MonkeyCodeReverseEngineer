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

      // 获取或创建 VM
      let vmId = await getOrCreateVM(taskRunner, accountAuth || undefined)
      const creatingAuth = accountAuth || undefined

      // 创建任务
      const taskId = await taskRunner.createTask(vmId, model, prompt, creatingAuth)
      console.log(`[Chat] Task created: ${taskId}, model: ${model.model}${usePool ? " (pooled)" : ""}`)

      if (body.stream) {
        // 流式响应 — WS 独占该账号直到结束
        await handleStreamResponse(res, taskRunner, taskId, model, accountPool, accountAuth)
      } else {
        // 非流式响应
        await handleNonStreamResponse(res, taskRunner, taskId, model, accountPool, accountAuth)
      }

      // 非 WS 模式释放账号（WS 模式在流结束后由 handleStreamResponse 释放）
      if (!body.stream && accountAuth && accountPool) {
        // 如果是 WS 锁定的，需要释放；但 HTTP 获取的是非锁的，不需要主动释放
        accountPool
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

/** 获取或创建 VM */
async function getOrCreateVM(taskRunner: TaskRunner, auth?: import("./auth.js").AuthManager): Promise<string> {
  const vms = await taskRunner.listVMs(auth)
  const activeVm = vms.find((v) => v.status === "running" || v.status === "ready")
  if (activeVm) return activeVm.id

  return await taskRunner.createVM(auth)
}

/** 流式响应处理 */
async function handleStreamResponse(
  res: Response,
  taskRunner: TaskRunner,
  taskId: string,
  model: import("./types.js").MonkeyCodeModel,
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
    // WS 结束后释放账号
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
  pool?: AccountPool,
  auth?: import("./auth.js").AuthManager | null
): Promise<void> {
  let fullContent = ""

  await taskRunner.streamTask(taskId, (chunk: OpenAIChatCompletionChunk) => {
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