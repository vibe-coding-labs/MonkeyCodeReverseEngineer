// OpenAI 兼容 API 路由 — 将 OpenAI 格式请求转换为 MonkeyCode 任务
// 支持号池轮转：每个请求从 AccountPool 获取账号
// 支持多轮对话：通过 conversation_id 复用任务/VM

import { Router, type Request, type Response } from "express"
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import { AccountPool } from "./account-pool.js"
import { ConversationManager } from "./conversation-manager.js"
import { AuthManager } from "./auth.js"
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
  accountPool?: AccountPool,
  conversationManager?: ConversationManager
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

      // 检查是否复用对话
      const conversationId = body.conversation_id
      let conversation = conversationId ? conversationManager?.get(conversationId) : undefined

      if (conversation) {
        // 复用对话：发送最后一条用户消息
        console.log(`[Chat] Reusing conversation ${conversationId}`)
        const lastMessage = body.messages[body.messages.length - 1]
        if (lastMessage.role === "user") {
          conversationManager?.sendUserInput(conversation, lastMessage.content)
        }

        // 返回 conversation_id
        res.setHeader("X-Conversation-Id", conversation.id)

        if (body.stream) {
          await handleConversationStreamResponse(res, conversationManager!, conversation)
        } else {
          await handleConversationNonStreamResponse(res, conversationManager!, conversation)
        }
      } else {
        // 创建新任务
        let accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null
        const usePool = !!accountAuth

        // 构造 prompt — 提取 system message 作为 system_prompt
        const systemMsg = body.messages.find((m) => m.role === "system")
        const nonSystemMessages = body.messages.filter((m) => m.role !== "system")
        const prompt = messagesToPrompt(nonSystemMessages)

        // 创建任务（不需要 VM 管理，task API 自动处理）
        const taskId = await taskRunner.createTask(model, prompt, {
          authOverride: accountAuth || undefined,
          systemPrompt: systemMsg?.content,
        })
        console.log(`[Chat] Task created: ${taskId}, model: ${model.model}${usePool ? " (pooled)" : ""}`)

        // 如果有 conversationManager，创建对话
        if (conversationManager) {
          conversation = conversationManager.create(taskId, model, accountAuth || new AuthManager(), body.messages)
          res.setHeader("X-Conversation-Id", conversation.id)
        }

        if (body.stream) {
          await handleStreamResponse(res, taskRunner, taskId, model, prompt, accountPool, accountAuth)
        } else {
          await handleNonStreamResponse(res, taskRunner, taskId, model, prompt, accountPool, accountAuth)
        }
      }
    } catch (err: any) {
      console.error("[Chat] Error:", err.message)
      if (!res.headersSent) {
        res.status(500).json({ error: { message: err.message, type: "internal_error" } })
      }
    }
  })

  // ========== POST /v1/responses — OpenAI Responses API (Codex native) ==========
  router.post("/v1/responses", async (req: Request, res: Response) => {
    try {
      const { model: modelId, input, max_output_tokens } = req.body

      if (!input) {
        res.status(400).json({ error: { message: "input is required", type: "invalid_request_error" } })
        return
      }

      const model = await modelManager.resolveModel(modelId || "")
      if (!model) {
        res.status(404).json({ error: { message: `Model '${modelId}' not found`, type: "invalid_request_error" } })
        return
      }

      // Normalize input to prompt string + system prompt
      let prompt = ""
      let systemPrompt: string | undefined
      if (typeof input === "string") {
        prompt = input
      } else if (Array.isArray(input)) {
        const sysMsg = input.find((m: any) => m.role === "system")
        if (sysMsg) systemPrompt = typeof sysMsg.content === "string" ? sysMsg.content : ""
        const userMsgs = input.filter((m: any) => m.role !== "system")
        prompt = userMsgs.map((m: any) => {
          if (typeof m.content === "string") return m.content
          if (Array.isArray(m.content)) return m.content.filter((c: any) => c.type === "input_text").map((c: any) => c.text).join("")
          return ""
        }).join("\n\n")
      }

      let accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null

      const taskId = await taskRunner.createTask(model, prompt, {
        authOverride: accountAuth || undefined,
        systemPrompt,
      })

      const responseId = `resp-${taskId}`
      let seq = 0

      res.setHeader("Content-Type", "text/event-stream")
      res.setHeader("Cache-Control", "no-cache")
      res.setHeader("Connection", "keep-alive")
      res.setHeader("X-Accel-Buffering", "no")

      const abortController = new AbortController()
      res.on("close", () => abortController.abort())

      const sendEvent = (name: string, data: object) => {
        if (res.writableEnded) return
        res.write(`event: ${name}\ndata: ${JSON.stringify({ ...data, sequence_number: seq++ })}\n\n`)
      }

      // Emit response.created
      sendEvent("response.created", {
        type: "response.created",
        response: { id: responseId, object: "response", status: "in_progress", model: model.model, output: [] },
      })

      let currentOutputIndex = 0
      let currentCallId = ""
      let currentToolName = ""

      try {
        const usage = await taskRunner.streamTaskRaw(
          taskId,
          prompt,
          (event) => {
            if (event.type === "acp") {
              const acp = event.data

              if (acp.type === "agent_message_chunk" || acp.type === "agent_thought_chunk") {
                const text = acp.text || acp.content || ""
                if (!text) return

                // If first text output, emit output_item.added + content_part.added
                if (currentOutputIndex === 0) {
                  sendEvent("response.output_item.added", {
                    type: "response.output_item.added",
                    output_index: 0,
                    item: { type: "message", id: `msg-${taskId}`, role: "assistant", content: [{ type: "output_text", text: "" }] },
                  })
                  sendEvent("response.content_part.added", {
                    type: "response.content_part.added",
                    output_index: 0,
                    content_index: 0,
                    part: { type: "output_text", text: "" },
                  })
                  currentOutputIndex = 1
                }

                const prefix = acp.type === "agent_thought_chunk" ? "[Thinking] " : ""
                sendEvent("response.output_text.delta", {
                  type: "response.output_text.delta",
                  output_index: 0,
                  content_index: 0,
                  delta: { type: "output_text.delta", text: prefix + text },
                })
              } else if (acp.type === "tool_call") {
                currentCallId = `call_${acp.tool_name || "unknown"}_${Date.now()}`
                currentToolName = acp.tool_name || "unknown"
                const args = acp.tool_input || ""
                sendEvent("response.output_item.added", {
                  type: "response.output_item.added",
                  output_index: currentOutputIndex,
                  item: { type: "function_call", id: currentCallId, call_id: currentCallId, name: currentToolName, arguments: "" },
                })
                // Send initial arguments (may be updated by tool_call_update)
                if (args) {
                  sendEvent("response.function_call_arguments.delta", {
                    type: "response.function_call_arguments.delta",
                    output_index: currentOutputIndex,
                    delta: { type: "function_call_arguments.delta", arguments: args },
                  })
                }
              } else if (acp.type === "tool_call_update") {
                // Stream tool call argument updates
                const updateArgs = acp.tool_input || acp.delta || ""
                if (updateArgs && currentCallId) {
                  sendEvent("response.function_call_arguments.delta", {
                    type: "response.function_call_arguments.delta",
                    output_index: currentOutputIndex,
                    delta: { type: "function_call_arguments.delta", arguments: updateArgs },
                  })
                }
                // If tool call is complete, finalize it
                if (acp.status === "completed" || acp.status === "done") {
                  const finalArgs = acp.tool_input || ""
                  sendEvent("response.function_call_arguments.done", {
                    type: "response.function_call_arguments.done",
                    output_index: currentOutputIndex,
                    arguments: finalArgs,
                  })
                  sendEvent("response.output_item.done", {
                    type: "response.output_item.done",
                    output_index: currentOutputIndex,
                    item: { type: "function_call", id: currentCallId, call_id: currentCallId, name: currentToolName, arguments: finalArgs },
                  })
                  currentOutputIndex++
                  currentCallId = ""
                  currentToolName = ""
                }
              }
            } else if (event.type === "task-ended") {
              // Close any open tool call
              if (currentCallId) {
                sendEvent("response.function_call_arguments.done", {
                  type: "response.function_call_arguments.done",
                  output_index: currentOutputIndex,
                  arguments: "",
                })
                sendEvent("response.output_item.done", {
                  type: "response.output_item.done",
                  output_index: currentOutputIndex,
                  item: { type: "function_call", id: currentCallId, call_id: currentCallId, name: currentToolName, arguments: "" },
                })
              }
              // Close any open text content part
              if (currentOutputIndex === 1 && !currentCallId) {
                // Text output was started but never closed
                sendEvent("response.content_part.done", {
                  type: "response.content_part.done",
                  output_index: 0,
                  content_index: 0,
                })
                sendEvent("response.output_item.done", {
                  type: "response.output_item.done",
                  output_index: 0,
                  item: { type: "message", id: `msg-${taskId}`, role: "assistant", content: [{ type: "output_text", text: "" }] },
                })
              } else if (currentOutputIndex === 0) {
                // No output at all — emit empty message
                sendEvent("response.output_item.added", {
                  type: "response.output_item.added",
                  output_index: 0,
                  item: { type: "message", id: `msg-${taskId}`, role: "assistant", content: [{ type: "output_text", text: "" }] },
                })
                sendEvent("response.content_part.added", {
                  type: "response.content_part.added",
                  output_index: 0,
                  content_index: 0,
                  part: { type: "output_text", text: "" },
                })
                sendEvent("response.content_part.done", {
                  type: "response.content_part.done",
                  output_index: 0,
                  content_index: 0,
                })
                sendEvent("response.output_item.done", {
                  type: "response.output_item.done",
                  output_index: 0,
                  item: { type: "message", id: `msg-${taskId}`, role: "assistant", content: [{ type: "output_text", text: "" }] },
                })
              }
              // If currentOutputIndex > 1, text was already closed when tool_call started
            }
          },
          abortController.signal,
          accountAuth || undefined
        )

        // Final response.completed
        sendEvent("response.completed", {
          type: "response.completed",
          response: {
            id: responseId,
            object: "response",
            status: "completed",
            model: model.model,
            usage: { input_tokens: usage.input_tokens, output_tokens: usage.output_tokens, total_tokens: usage.total_tokens },
          },
        })
      } catch (err: any) {
        console.error("[Responses] Stream error:", err.message)
        sendEvent("response.completed", {
          type: "response.completed",
          response: { id: responseId, object: "response", status: "failed", model: model.model },
        })
      } finally {
        res.end()
        if (accountAuth && accountPool) {
          accountPool.releaseWs(accountAuth)
        }
      }
    } catch (err: any) {
      console.error("[Responses] Error:", err.message)
      if (!res.headersSent) {
        res.status(500).json({ error: { message: err.message, type: "internal_error" } })
      }
    }
  })

  return router
}

/** 将消息列表转换为 prompt（system 消息已由调用方提取） */
function messagesToPrompt(messages: OpenAIMessage[]): string {
  return messages
    .map((m) => {
      switch (m.role) {
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
  let accumulatedUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }

  try {
    await taskRunner.streamTask(taskId, prompt, (chunk: OpenAIChatCompletionChunk) => {
      for (const choice of chunk.choices) {
        if (choice.delta?.content) {
          fullContent += choice.delta.content
        }
      }
      // 累积 usage
      if (chunk.usage) {
        accumulatedUsage = chunk.usage
      }
    }, undefined, auth || undefined)
  } finally {
    if (auth && pool) {
      pool.releaseWs(auth)
    }
  }

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
    usage: accumulatedUsage.total_tokens > 0 ? accumulatedUsage : {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    },
  }

  res.json(response)
}

/** 对话流式响应处理 */
async function handleConversationStreamResponse(
  res: Response,
  conversationManager: ConversationManager,
  conversation: import("./conversation-manager.js").Conversation
): Promise<void> {
  res.setHeader("Content-Type", "text/event-stream")
  res.setHeader("Cache-Control", "no-cache")
  res.setHeader("Connection", "keep-alive")
  res.setHeader("X-Accel-Buffering", "no")

  const abortController = new AbortController()
  res.on("close", () => abortController.abort())

  const sendSSE = (data: object) => {
    if (res.writableEnded) return
    res.write(`data: ${JSON.stringify(data)}\n\n`)
  }

  try {
    // 连接到对话的 WebSocket
    await conversationManager.connectToTask(conversation, (chunk: OpenAIChatCompletionChunk) => {
      sendSSE(chunk)
    })
  } catch (err: any) {
    console.error("[ConversationStream] Error:", err.message)
  } finally {
    sendSSE({ object: "done" })
    res.write("data: [DONE]\n\n")
    res.end()
  }
}

/** 对话非流式响应处理 */
async function handleConversationNonStreamResponse(
  res: Response,
  conversationManager: ConversationManager,
  conversation: import("./conversation-manager.js").Conversation
): Promise<void> {
  let fullContent = ""

  try {
    // 连接到对话的 WebSocket
    await conversationManager.connectToTask(conversation, (chunk: OpenAIChatCompletionChunk) => {
      for (const choice of chunk.choices) {
        if (choice.delta?.content) {
          fullContent += choice.delta.content
        }
      }
    })
  } catch (err: any) {
    console.error("[ConversationNonStream] Error:", err.message)
  }

  const response: OpenAIChatCompletionResponse = {
    id: `chatcmpl-${conversation.taskId}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: conversation.model.model,
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
