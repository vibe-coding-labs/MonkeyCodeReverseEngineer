---
description: Conversation Manager 完整生命周期源码分析 — mode=attach 多轮对话复用协议
protocol_version: based on proxy/src/conversation-manager.ts (368L) + api-routes.ts + types.ts
confidence: high
last_verified: 2026-06-28
---

# Conversation Manager 完整生命周期源码分析

> **核心源码:** `proxy/src/conversation-manager.ts` (368L)
> **关联文件:** `proxy/src/api-routes.ts:61-108` (对话路由处理), `proxy/src/server.ts:115-118` (初始化)
> **类型定义:** `proxy/src/types.ts:167-174`
> **覆盖:** 创建→连接→通信→清理→销毁 完整生命周期 + mode=attach WS 帧级跟踪

---

## 1. Conversation 数据结构

### 完整接口定义

```typescript
// 摘自 proxy/src/types.ts:167-174 — Conversation 类型
export interface Conversation {
  id: string           // 格式: conv-{timestamp}-{random8}
  taskId: string       // 关联的 MonkeyCode 任务 ID
  modelId: string      // 模型 ID
  messages: OpenAIMessage[]  // 历史消息列表
  lastUsedAt: number   // 最后使用时间戳 (用于超时清理)
  createdAt: number    // 创建时间戳
}

// ——————————————————————————————————

// 摘自 proxy/src/conversation-manager.ts:26-38 — 运行时 Conversation 接口
export interface Conversation {
  id: string
  taskId: string
  model: MonkeyCodeModel       // 完整模型对象 (vs types.ts 中的 modelId)
  auth: AuthManager            // 认证管理器
  ws: WebSocket | null         // 复用的 WebSocket 连接
  messages: OpenAIMessage[]
  lastUsedAt: number
  createdAt: number
  onChunk: ((chunk: OpenAIChatCompletionChunk) => void) | null  // 流式回调
  resolvePromise: (() => void) | null    // Promise resolve
  rejectPromise: ((err: Error) => void) | null  // Promise reject
}
```

### ID 生成策略

```typescript
// 摘自 proxy/src/conversation-manager.ts:60-62 — 对话 ID 生成
const id = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
// 示例: conv-1718245799000-a1b2c3d4
// 格式: conv-{毫秒时间戳}-{6位随机字母数字}
```

### 配置项

```typescript
// 摘自 proxy/src/conversation-manager.ts:43-48 — 配置
const DEFAULT_CONVERSATION_TIMEOUT_MS = 30 * 60 * 1000  // 30 分钟
const DEFAULT_CLEANUP_INTERVAL_MS = 5 * 60 * 1000       // 5 分钟

constructor(options?: {
  conversationTimeoutMs?: number   // 对话超时 (默认 30min)
  cleanupIntervalMs?: number       // 清理间隔 (默认 5min)
}) {
  this.conversationTimeoutMs = options?.conversationTimeoutMs || DEFAULT_CONVERSATION_TIMEOUT_MS
  const cleanupInterval = options?.cleanupIntervalMs || DEFAULT_CLEANUP_INTERVAL_MS
  this.cleanupTimer = setInterval(() => this.cleanup(), cleanupInterval)
}
```

---

## 2. 完整生命周期

### 阶段 1: 创建 (create)

```typescript
// 摘自 proxy/src/conversation-manager.ts:54-76 — 创建对话
create(
  taskId: string,
  model: MonkeyCodeModel,
  auth: AuthManager,
  messages: OpenAIMessage[]
): Conversation {
  const id = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const conversation: Conversation = {
    id, taskId, model, auth,
    ws: null,                   // WS 初始未连接
    messages: [...messages],    // 深拷贝消息列表
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
```

### 阶段 2: 连接 (connectToTask)

```typescript
// 摘自 proxy/src/conversation-manager.ts:131-210 — WS 连接 (mode=attach)
async connectToTask(
  conversation: Conversation,
  onChunk: (chunk: OpenAIChatCompletionChunk) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const auth = conversation.auth
    const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)

    // 关键: mode=attach 复用已有任务的 WS 连接
    const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${conversation.taskId}&mode=attach`

    const ws = new WebSocket(wsUrl, {
      headers: wsHeaders("monkeycode-ai.com",
        `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`),
    })

    conversation.ws = ws           // 保存 WS 引用
    conversation.onChunk = onChunk  // 注册回调
    conversation.resolvePromise = resolve  // Promise 准备
    conversation.rejectPromise = reject

    ws.on("open", () => {
      ws.send(JSON.stringify({ type: "auto-approve" }))
      resolve()  // 连接成功时 resolve
    })

    // 30 秒连接超时
    setTimeout(() => {
      if (!resolved) {
        cleanup()
        resolve()
      }
    }, 30000)
  })
}
```

### 阶段 3: 通信 (sendUserInput)

```typescript
// 摘自 proxy/src/conversation-manager.ts:213-225 — 发送用户输入
sendUserInput(conversation: Conversation, content: string): void {
  if (!conversation.ws || conversation.ws.readyState !== WebSocket.OPEN) {
    throw new Error(`Conversation ${conversation.id} is not connected`)
  }

  const userMsg = {
    type: "user-input",
    data: content,           // 纯文本，与 mode=new 相同格式
  }
  conversation.ws.send(JSON.stringify(userMsg))
  conversation.lastUsedAt = Date.now()
  console.log(`[ConversationManager] Sent user-input for conversation ${conversation.id}`)
}
```

### 阶段 4: 清理 (cleanup)

```typescript
// 摘自 proxy/src/conversation-manager.ts:108-116 — 定期清理过期对话
private cleanup(): void {
  const now = Date.now()
  for (const [id, conversation] of this.conversations) {
    if (now - conversation.lastUsedAt > this.conversationTimeoutMs) {
      // 30 分钟未使用 → 清理
      console.log(`[ConversationManager] Cleaning up expired conversation ${id}`)
      this.delete(id)
    }
  }
}
```

### 阶段 5: 销毁 (destroy)

```typescript
// 摘自 proxy/src/conversation-manager.ts:119-128 — 完全销毁
destroy(): void {
  if (this.cleanupTimer) {
    clearInterval(this.cleanupTimer)
    this.cleanupTimer = null
  }
  // 关闭所有对话的 WS 连接
  for (const [id] of this.conversations) {
    this.delete(id)
  }
}

// delete 单个对话: 关闭 WS + 移除
delete(id: string): boolean {
  const conversation = this.conversations.get(id)
  if (conversation) {
    if (conversation.ws) {
      conversation.ws.close()  // 关闭 WS 连接
    }
    this.conversations.delete(id)
    return true
  }
  return false
}
```

---

## 3. mode=attach 协议细节

### ws URL 格式对比

```typescript
// mode=new (TaskRunner): 创建新任务 + 新 VM
`${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=new`

// mode=attach (ConversationManager): 复用已有任务的 WS
`${wsBaseUrl}/api/v1/users/tasks/stream?id=${conversation.taskId}&mode=attach`
```

### WS 帧级通信时序

```
mode=attach 连接后的完整帧序列:

Client → Server (连接建立后):
  Frame 1: {"type":"auto-approve"}
  — 启用自动审批模式，Agent 不再等待用户确认

Server → Client (心跳，每 ~15 秒):
  Frame 2: {"type":"ping"}
Client → Server:
  Frame 3: {"type":"ping"}

Server → Client (ACP 事件流):
  Frame 4: {"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_message_chunk\",\"text\":\"...\"}"}
  Frame 5: {"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_thought_chunk\",\"text\":\"...\"}"}
  Frame 6: {"type":"task-running","kind":"acp_event","data":"{\"type\":\"tool_call\",\"tool_name\":\"read_file\",\"tool_input\":\"...\"}"}

可能有 Server → Client 提问:
  Frame 7: {"type":"task-running","kind":"acp_ask_user_question","data":"{\"request_id\":\"...\"}"}
Client → Server:
  Frame 8: {"type":"reply-question","data":"{\"request_id\":\"...\",\"answers_json\":\"\",\"cancelled\":false}"}

Server → Client 新的用户输入:
  Frame 9: {"type":"user-input","data":"新的提示词"}
  — 注意: 此处是 Client 主动发送 user-input 到 Server

Server → Client (结束):
  Frame N: {"type":"task-ended"}
```

### attach 模式自动回复

```typescript
// 摘自 proxy/src/conversation-manager.ts:248-265 — 自动回复
if (msg.kind === "acp_ask_user_question") {
  try {
    const questionData = JSON.parse(msg.data)
    const requestId = questionData.request_id || questionData.id || ""
    conversation.ws?.send(JSON.stringify({
      type: "reply-question",
      data: JSON.stringify({
        request_id: requestId,
        answers_json: "",       // 空答案 = 默认确认
        cancelled: false,       // 不取消
      }),
    }))
  } catch {
    // ignore
  }
}
```

---

## 4. ACP 事件处理 (与 TaskRunner 对比)

### handleStreamMessage 源码

```typescript
// 摘自 proxy/src/conversation-manager.ts:228-293 — 流式消息处理
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
        const acp: ACPSessionUpdate = JSON.parse(msg.data)
        this.handleACPEvent(acp, chatId, now, onChunk, conversation)
      }
      break

    case "task-ended":
      onChunk({
        id: chatId, object: "chat.completion.chunk",
        created: now, model: "monkeycode",
        choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
      })
      // resolve 对话的 Promise
      if (conversation.resolvePromise) {
        conversation.resolvePromise()
        conversation.resolvePromise = null
        conversation.rejectPromise = null
      }
      break

    case "task-error":
      onChunk({
        id: chatId, object: "chat.completion.chunk",
        created: now, model: "monkeycode",
        choices: [{ index: 0, delta: { content: `[Error] ${msg.data}` }, finish_reason: null }],
      })
      break
  }
}
```

### TaskRunner 与 ConversationManager 差异

| 特性 | TaskRunner (mode=new) | ConversationManager (mode=attach) |
|------|----------------------|----------------------------------|
| WS 连接 | 每次调用新建 | 复用已有连接 |
| promise resolve | 在 WS close 时 | 在 task-ended 时 |
| onChunk 注册 | 函数参数 | conversation 属性 |
| WS 关闭 | resolve(无数据) | resolve + 清空 promise |
| 最终 usage 返回 | `streamTaskRaw` 返回 `usage` | 不返回 |
| 多轮 support | 不支持 | 支持 (sendUserInput) |
| WS 连接超时 | 无 (依赖 1h 任务超时) | 30 秒硬超时 |

---

## 5. 与 API 路由的集成

### 对话复用逻辑

```typescript
// 摘自 proxy/src/api-routes.ts:61-108 — 对话复用
router.post("/v1/chat/completions", async (req, res) => {
  const conversationId = body.conversation_id
  let conversation = conversationId ? conversationManager?.get(conversationId) : undefined

  if (conversation) {
    // 复用对话: 发送最后一条用户消息到已有 WS
    const lastMessage = body.messages[body.messages.length - 1]
    if (lastMessage.role === "user") {
      conversationManager?.sendUserInput(conversation, lastMessage.content)
    }
    // 返回 conversation_id 响应头
    res.setHeader("X-Conversation-Id", conversation.id)

    if (body.stream) {
      await handleConversationStreamResponse(res, conversationManager!, conversation)
    } else {
      await handleConversationNonStreamResponse(res, conversationManager!, conversation)
    }
  } else {
    // 创建新任务 + 新对话
    const taskId = await taskRunner.createTask(model, prompt, {...})
    conversation = conversationManager.create(taskId, model, auth, body.messages)
    res.setHeader("X-Conversation-Id", conversation.id)
    // 流式/非流式处理
  }
})
```

### 对话流式响应

```typescript
// 摘自 proxy/src/api-routes.ts:472-502 — 对话流式处理
async function handleConversationStreamResponse(res, conversationManager, conversation) {
  res.setHeader("Content-Type", "text/event-stream")
  res.setHeader("Cache-Control", "no-cache")
  res.setHeader("Connection", "keep-alive")

  const abortController = new AbortController()
  res.on("close", () => abortController.abort())

  const sendSSE = (data) => {
    res.write(`data: ${JSON.stringify(data)}\n\n`)
  }

  await conversationManager.connectToTask(conversation, (chunk) => {
    sendSSE(chunk)  // OpenAI SSE 格式
  })

  sendSSE({ object: "done" })
  res.write("data: [DONE]\n\n")
  res.end()
}
```

### 服务器初始化

```typescript
// 摘自 proxy/src/server.ts:115-118 — 初始化
const conversationManager = new ConversationManager({
  conversationTimeoutMs: 30 * 60 * 1000,  // 30 分钟超时
  cleanupIntervalMs: 5 * 60 * 1000,      // 5 分钟清理一次
})
console.log("[Init] ConversationManager initialized")

// 注入到 API 路由
app.use(createAPIRouter(modelManager, taskRunner, accountPool, conversationManager))
```

---

## 6. 状态总览

### Conversation 状态机

```
IDLE (创建后未连接)
  │
  ▼ connectToTask
CONNECTING (WS 握手进行中, 30s 超时)
  │
  ▼ WS open
CONNECTED (WS 连接建立)
  │
  ▼ sendUserInput
STREAMING (ACP 事件流中)
  │
  ▼ task-ended
COMPLETED (完成)
  │
  ▼ cleanup (30min 超时)
DELETED (清理)

或者:
COMPLETED → sendUserInput → STREAMING → task-ended → COMPLETED (多轮循环)
```

### ConversationManager 内部状态

```typescript
// 摘自 proxy/src/conversation-manager.ts:41 — 对话集合
private conversations: Map<string, Conversation> = new Map()

// 大小查询
size(): number {
  return this.conversations.size
}
```

---

## 相关章节

- [WebSocket 协议总览](../01-task-stream.md) — mode=new/attach 对比
- [TaskRunner 源码分析](../../07-proxy/README.md) — task-runner.ts 完整实现
- [代理 API 路由](../../07-proxy/README.md) — api-routes.ts 对话路由
- [多轮对话设计](../../07-proxy/03-multi-turn-conversation.md)