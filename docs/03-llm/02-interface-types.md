---
description: 三种 LLM 接口类型的源码级对比 — Go SDK 选择 + 代理 Chat/Responses 双模式实现
protocol_version: based on chaitin/MonkeyCode + proxy/src/api-routes.ts + proxy/src/task-runner.ts
confidence: high
last_verified: 2026-06-28
---

# LLM 接口类型详解（源码增强版）

> **核心发现:** 3 种接口决定 3 种 SDK、3 种 API 格式、3 种 Agent 类型
> **代理层关键代码:** `api-routes.ts` Chat + Responses 双模式、`task-runner.ts` cli_name 映射

## 1. 接口类型全景

| 特性 | openai_chat | openai_responses | anthropic |
|------|------------|-----------------|-----------|
| **底层 SDK** | `@ai-sdk/openai-compatible` | `@ai-sdk/openai` | `@ai-sdk/anthropic` |
| **API 格式** | Chat Completions | Responses API | Messages API |
| **端点路径** | `{baseURL}/chat/completions` | `{baseURL}/responses` | `{baseURL}/v1/messages` |
| **Go SDK** | `sashabaranov/go-openai` | 原生 HTTP | `anthropics/anthropic-sdk-go` |
| **流式事件** | `chat.completion.chunk` | `response.*` events | `content_block_delta` |
| **工具调用** | `tool_calls` | `function_call` | `tool_use` |
| **Agent 类型** | `opencode` | `codex` | `claude` |
| **代理端点** | `POST /v1/chat/completions` | `POST /v1/responses` | 同 Chat（代理转换）|

## 2. Go 后端 SDK 选择

```go
// backend/pkg/taskflow/vm.go — 接口类型决定容器内 NPM 包
func getNpmPackage(interfaceType InterfaceType) string {
    switch interfaceType {
    case InterfaceOpenAIChat:
        return "@ai-sdk/openai-compatible"   // 通用 OpenAI 兼容
    case InterfaceOpenAIResponses:
        return "@ai-sdk/openai"              // OpenAI 官方 SDK
    case InterfaceAnthropic:
        return "@ai-sdk/anthropic"           // Anthropic 官方 SDK
    }
    return "@ai-sdk/openai-compatible"       // 默认回退
}
```

### Go 端统一请求结构体

```go
// pkg/llm/client.go — 三种接口共享的请求/响应格式
type ChatRequest struct {
    Messages      []Message     `json:"messages"`
    Model         string        `json:"model,omitempty"`
    MaxTokens     int           `json:"max_tokens,omitempty"`
    Temperature   float32       `json:"temperature,omitempty"`
    System        string        `json:"system,omitempty"`
    InterfaceType InterfaceType `json:"interface_type,omitempty"`
}

type ChatResponse struct {
    Content string `json:"content"`
    Usage   Usage  `json:"usage"`
}

// LLMConfig 注入到容器的 LLM 配置
type LLMConfig struct {
    APIKey  string `json:"api_key"`
    BaseURL string `json:"base_url"`
    Model   string `json:"model"`
    APIType string `json:"api_type"`    // "anthropic" | "openai"
}
```

## 3. 代理层 Chat 模式实现

### 3.1 Chat Completions 路由

```typescript
// proxy/src/api-routes.ts — POST /v1/chat/completions
router.post("/v1/chat/completions", async (req, res) => {
  try {
    const body: OpenAIChatCompletionRequest = req.body

    // 验证请求
    if (!body.messages || body.messages.length === 0) {
      res.status(400).json({ error: { message: "messages is required" } })
      return
    }

    // 解析模型
    const model = await modelManager.resolveModel(body.model || "")
    if (!model) {
      res.status(404).json({ error: { message: `Model '${body.model}' not found` } })
      return
    }

    // 检查对话复用
    const conversation = body.conversation_id
      ? conversationManager?.get(body.conversation_id) : undefined

    if (conversation) {
      // 复用已有对话 → 发送最后一条消息
      conversation.sendUserInput(body.messages[body.messages.length - 1].content)
      // 流式/非流式响应
      if (body.stream) {
        await handleConversationStreamResponse(res, conversationManager!, conversation)
      } else {
        await handleConversationNonStreamResponse(res, conversationManager!, conversation)
      }
    } else {
      // 创建新任务
      const accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null

      // 提取 system prompt 和用户消息
      const systemMsg = body.messages.find(m => m.role === "system")
      const prompt = body.messages.filter(m => m.role !== "system")
        .map(m => `[${m.role === "user" ? "User" : "Assistant"}]\n${m.content}`).join("\n\n")

      // 创建 MonkeyCode 任务
      const taskId = await taskRunner.createTask(model, prompt, {
        authOverride: accountAuth || undefined,
        systemPrompt: systemMsg?.content,
      })

      // 创建对话管理
      if (conversationManager) {
        conversation = conversationManager.create(taskId, model, accountAuth, body.messages)
      }

      // 流式/非流式响应
      if (body.stream) {
        await handleStreamResponse(res, taskRunner, taskId, model, prompt, accountPool, accountAuth)
      } else {
        await handleNonStreamResponse(res, taskRunner, taskId, model, prompt, accountPool, accountAuth)
      }
    }
  } catch (err: any) {
    if (!res.headersSent) {
      res.status(500).json({ error: { message: err.message, type: "internal_error" } })
    }
  }
})
```

### 3.2 ACP → Chat Chunk 转换

```typescript
// proxy/src/task-runner.ts — ACP 事件转 OpenAI Chat Chunk
private handleACPEvent(acp, chatId, now, onChunk, usage) {
  switch (acp.type) {
    case "agent_message_chunk":
      onChunk({ id: chatId, object: "chat.completion.chunk",
        choices: [{ delta: { content: acp.text }, finish_reason: null }] })
      break
    case "agent_thought_chunk":
      onChunk({ id: chatId, object: "chat.completion.chunk",
        choices: [{ delta: { content: `[Thinking] ${acp.text}` }, finish_reason: null }] })
      break
    case "tool_call":
      onChunk({ id: chatId, object: "chat.completion.chunk",
        choices: [{ delta: { content: `[Tool: ${acp.tool_name}] ${acp.tool_input}` }, finish_reason: null }] })
      break
    case "task-ended":
      onChunk({ id: chatId, object: "chat.completion.chunk",
        choices: [{ delta: {}, finish_reason: "stop" }],
        usage: usage.total_tokens > 0 ? usage : undefined })
      break
  }
}
```

### 3.3 三种接口对应同一 SSE 格式

```json
// 三种接口类型代理都输出此格式
// Chat: 直接 SSE 流
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"你好"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}}

data: [DONE]
```

## 4. 代理层 Responses 模式实现

### 4.1 Responses API 路由

```typescript
// proxy/src/api-routes.ts — POST /v1/responses (Codex 原生模式)
router.post("/v1/responses", async (req, res) => {
  const { model: modelId, input, max_output_tokens } = req.body

  // 解析模型 + 创建任务（同上 Chat 模式）
  const model = await modelManager.resolveModel(modelId || "")

  // 归一化 input 为 prompt
  let prompt = ""
  if (typeof input === "string") prompt = input
  else if (Array.isArray(input)) {
    // 从 messages 格式提取 system + user 消息
    prompt = input.map(m => /* ... */).join("\n\n")
  }

  const accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null
  const taskId = await taskRunner.createTask(model, prompt, { authOverride: accountAuth })

  // SSE: Responses 模式（多个事件类型）
  res.setHeader("Content-Type", "text/event-stream")

  // 发送 response.created
  sendEvent("response.created", { type: "response.created", response: { id: `resp-${taskId}`, status: "in_progress" } })

  // 接收 ACP 事件 → Responses 事件
  taskRunner.streamTaskRaw(taskId, prompt, (event) => {
    if (event.type === "acp") {
      const acp = event.data
      if (acp.type === "agent_message_chunk") {
        sendEvent("response.output_text.delta", { delta: { text: acp.text } })
      } else if (acp.type === "tool_call") {
        sendEvent("response.output_item.added", { item: { type: "function_call", name: acp.tool_name } })
      }
    }
  })
})
```

### 4.2 Responses 事件流对比

```
Chat 模式 SSE:                              Responses 模式 SSE:
─────────────────                           ─────────────────────
data: {"choices":[...]}                     event: response.created
                                            event: response.output_item.added
data: {"choices":[...]}                     event: response.output_text.delta
                                            event: response.function_call_arguments.delta
data: {"choices":[...],"usage":...}         event: response.function_call_arguments.done
                                            event: response.output_item.done
data: [DONE]                                event: response.completed
```

## 5. cli_name 映射链

```typescript
// proxy/src/task-runner.ts — 动态 Agent 选择
cli_name: model.interface_type === "openai_responses" ? "codex"
  : model.interface_type === "anthropic" ? "claude"
  : "opencode",
```

| interface_type | cli_name | Agent | NPM 包 |
|---------------|----------|-------|--------|
| `openai_chat` | `opencode` | OpenCode | `@ai-sdk/openai-compatible` |
| `openai_responses` | `codex` | Codex CLI | `@ai-sdk/openai` |
| `anthropic` | `claude` | Claude Code | `@ai-sdk/anthropic` |

## 6. 三种接口的 HTTP 请求示例

### openai_chat

```http
POST {baseURL}/chat/completions
Authorization: Bearer {apiKey}
Content-Type: application/json

{
  "model": "gpt-4o",
  "messages": [{"role": "user", "content": "Hello"}],
  "temperature": 0.7,
  "stream": true
}
```

### openai_responses

```http
POST {baseURL}/responses
Authorization: Bearer {apiKey}

{
  "model": "gpt-4o",
  "input": "Hello",
  "stream": true
}
```

### anthropic

```http
POST {baseURL}/v1/messages
x-api-key: {apiKey}
anthropic-version: 2023-06-01

{
  "model": "claude-sonnet-4-20250514",
  "messages": [{"role": "user", "content": "Hello"}],
  "max_tokens": 1000,
  "stream": true
}
```

---

## 相关章节

- [模型管理 API](01-model-management-api.md) — 模型配置中的 interface_type
- [模型提供商列表](03-provider-list.md) — 各提供商接口类型分布
- [LLM 集成协议](05-llm-integration.md) — Client 架构
- [ACP → OpenAI 映射](../07-proxy/04-acp-to-openai-mapping.md) — 事件转换逻辑
- [Coding Agent 配置](06-coding-agent-config.md) — cli_name 与 NPM 包映射
