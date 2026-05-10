// OpenAI 兼容 API 路由 — 将 OpenAI 格式请求转换为 MonkeyCode 任务

import { Router, type Request, type Response } from "express"
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import type {
  OpenAIChatCompletionRequest,
  OpenAIChatCompletionResponse,
  OpenAIChatCompletionChunk,
  OpenAIModelsResponse,
  OpenAIMessage,
} from "./types.js"

export function createAPIRouter(modelManager: ModelManager, taskRunner: TaskRunner): Router {
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

      // 构造 prompt
      const prompt = messagesToPrompt(body.messages)

      // 获取或创建 VM
      let vmId = await getOrCreateVM(taskRunner)

      // 创建任务
      const taskId = await taskRunner.createTask(vmId, model, prompt)
      console.log(`[Chat] Task created: ${taskId}, model: ${model.model}`)

      if (body.stream) {
        // 流式响应
        await handleStreamResponse(res, taskRunner, taskId, model)
      } else {
        // 非流式响应
        await handleNonStreamResponse(res, taskRunner, taskId, model)
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
async function getOrCreateVM(taskRunner: TaskRunner): Promise<string> {
  const vms = await taskRunner.listVMs()
  const activeVm = vms.find((v) => v.status === "running" || v.status === "ready")
  if (activeVm) return activeVm.id

  return await taskRunner.createVM()
}

/** 流式响应处理 */
async function handleStreamResponse(
  res: Response,
  taskRunner: TaskRunner,
  taskId: string,
  model: import("./types.js").MonkeyCodeModel
): Promise<void> {
  res.setHeader("Content-Type", "text/event-stream")
  res.setHeader("Cache-Control", "no-cache")
  res.setHeader("Connection", "keep-alive")
  res.setHeader("X-Accel-Buffering", "no")

  const abortController = new AbortController()

  // 客户端断开时取消
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
      abortController.signal
    )
  } catch (err: any) {
    console.error("[Stream] Error:", err.message)
  } finally {
    sendSSE({ object: "done" })
    res.write("data: [DONE]\n\n")
    res.end()
  }
}

/** 非流式响应处理 */
async function handleNonStreamResponse(
  res: Response,
  taskRunner: TaskRunner,
  taskId: string,
  model: import("./types.js").MonkeyCodeModel
): Promise<void> {
  let fullContent = ""

  await taskRunner.streamTask(taskId, (chunk: OpenAIChatCompletionChunk) => {
    for (const choice of chunk.choices) {
      if (choice.delta?.content) {
        fullContent += choice.delta.content
      }
    }
  })

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
