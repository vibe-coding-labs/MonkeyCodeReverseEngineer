# MonkeyCode 代理多轮对话支持设计

> **日期:** 2026-05-30
> **状态:** 设计阶段

---

## 1. 问题分析

### 1.1 当前代理行为

当前代理是**无状态的**：
1. 每个请求创建新任务（新 VM）
2. 发送单个 `user-input` 消息
3. 接收流式输出
4. 任务结束，关闭连接

**问题**：
- 每次请求都要创建新 VM（~几秒延迟）
- 无法保持对话上下文
- 资源消耗大（每个请求一个 VM）

### 1.2 MonkeyCode 的多轮机制

MonkeyCode 通过 Task Stream WS 支持多轮对话：
1. 创建任务并连接 WS（`mode=new`）
2. 发送 `user-input` 消息
3. 接收 Agent 输出
4. **再次发送 `user-input` 消息**（同一 WS 连接）
5. 接收 Agent 输出（Agent 保持上下文）
6. 重复步骤 4-5

**关键**：同一任务/VM 可以处理多个 `user-input` 消息，Agent 保持对话上下文。

### 1.3 Conversation API 的作用

Conversation API 是**前端 UI 层**的抽象：
- 管理对话列表和消息历史
- 与任务（Task）关联
- 提供持久化存储

**对代理的影响**：Conversation API 是可选的，代理可以直接使用 Task Stream WS 实现多轮对话。

---

## 2. 设计方案

### 2.1 方案 A: 客户端管理多轮（简单）

**思路**：客户端发送完整对话历史，代理每次都创建新任务。

**实现**：
```typescript
// 客户端请求
POST /v1/chat/completions
{
  "model": "monkeycode/...",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"},
    {"role": "user", "content": "What is Python?"}
  ]
}

// 代理处理
const prompt = messages.map(m => `[${m.role}]\n${m.content}`).join("\n\n")
const taskId = await taskRunner.createTask(model, prompt)
// ... 流式输出
```

**优点**：
- 实现简单，无需状态管理
- 与 OpenAI API 完全兼容
- 每个请求独立，无并发问题

**缺点**：
- 每次请求创建新 VM（延迟高）
- 无法利用 Agent 的真实多轮能力
- 长对话会导致 prompt 过长

### 2.2 方案 B: 代理管理多轮（复杂）

**思路**：代理维护对话状态，复用任务/VM。

**实现**：
```typescript
// 对话管理
interface Conversation {
  id: string
  taskId: string
  ws: WebSocket
  messages: Message[]
  lastUsedAt: number
}

// 客户端请求
POST /v1/chat/completions
{
  "model": "monkeycode/...",
  "messages": [...],  // 完整历史
  "conversation_id": "conv-xxx"  // 可选：指定对话
}

// 代理处理
let conversation = getConversation(conversation_id)
if (!conversation) {
  // 创建新对话
  const taskId = await taskRunner.createTask(model, systemPrompt)
  conversation = { id: generateId(), taskId, ws: connectWS(taskId), ... }
}

// 发送最后一条用户消息
const lastUserMessage = messages[messages.length - 1]
conversation.ws.send({ type: "user-input", data: lastUserMessage.content })

// 接收输出
// ... 流式输出
```

**优点**：
- 复用 VM，延迟低
- 利用 Agent 的真实多轮能力
- 对话上下文由 Agent 管理

**缺点**：
- 实现复杂，需要状态管理
- 需要处理 WS 连接生命周期
- 需要处理并发和超时

### 2.3 方案 C: 混合方案（推荐）

**思路**：结合 A 和 B 的优点。

**规则**：
1. 如果客户端发送 `conversation_id`，复用对话
2. 如果客户端发送完整消息历史（无 `conversation_id`），创建新任务
3. 对话超时后自动清理

**实现**：
```typescript
// 客户端请求（两种方式）
// 方式 1: 新对话（完整历史）
POST /v1/chat/completions
{
  "model": "monkeycode/...",
  "messages": [...]
}

// 方式 2: 继续对话
POST /v1/chat/completions
{
  "model": "monkeycode/...",
  "messages": [...],
  "conversation_id": "conv-xxx"
}

// 代理处理
if (conversation_id && hasConversation(conversation_id)) {
  // 复用对话
  const conversation = getConversation(conversation_id)
  const lastMessage = messages[messages.length - 1]
  conversation.ws.send({ type: "user-input", data: lastMessage.content })
  // ... 流式输出
} else {
  // 创建新任务
  const prompt = messagesToPrompt(messages)
  const taskId = await taskRunner.createTask(model, prompt)
  // ... 流式输出
  // 如果客户端需要对话 ID，返回 conversation_id
}
```

---

## 3. 实现细节

### 3.1 对话管理器

```typescript
class ConversationManager {
  private conversations: Map<string, Conversation> = new Map()
  private cleanupInterval: NodeJS.Timeout

  constructor() {
    // 每 5 分钟清理过期对话
    this.cleanupInterval = setInterval(() => this.cleanup(), 5 * 60 * 1000)
  }

  create(taskId: string, ws: WebSocket): Conversation {
    const id = `conv-${Date.now()}-${Math.random().toString(36).slice(2)}`
    const conversation: Conversation = {
      id,
      taskId,
      ws,
      messages: [],
      lastUsedAt: Date.now(),
    }
    this.conversations.set(id, conversation)
    return conversation
  }

  get(id: string): Conversation | undefined {
    const conversation = this.conversations.get(id)
    if (conversation) {
      conversation.lastUsedAt = Date.now()
    }
    return conversation
  }

  cleanup() {
    const now = Date.now()
    const timeout = 30 * 60 * 1000 // 30 分钟
    for (const [id, conversation] of this.conversations) {
      if (now - conversation.lastUsedAt > timeout) {
        conversation.ws.close()
        this.conversations.delete(id)
      }
    }
  }
}
```

### 3.2 WS 连接管理

```typescript
class TaskConnection {
  private ws: WebSocket
  private taskId: string
  private onChunk: (chunk: OpenAIChatCompletionChunk) => void

  constructor(taskId: string, auth: AuthManager) {
    this.taskId = taskId
    this.connect(auth)
  }

  private connect(auth: AuthManager) {
    const wsUrl = `${httpToWs(MONKEYCODE_BASE_URL)}/api/v1/users/tasks/stream?id=${this.taskId}&mode=attach`
    this.ws = new WebSocket(wsUrl, {
      headers: { Cookie: `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}` }
    })

    this.ws.on("open", () => {
      this.ws.send(JSON.stringify({ type: "auto-approve" }))
    })

    this.ws.on("message", (raw) => {
      const msg = JSON.parse(raw.toString())
      this.handleMessage(msg)
    })
  }

  sendUserInput(content: string) {
    this.ws.send(JSON.stringify({
      type: "user-input",
      data: content
    }))
  }

  private handleMessage(msg: TaskStreamMessage) {
    // 处理 ACP 事件，转换为 OpenAI 格式
  }
}
```

### 3.3 API 路由更新

```typescript
// api-routes.ts
router.post("/v1/chat/completions", async (req, res) => {
  const { model, messages, stream, conversation_id } = req.body

  // 获取或创建对话
  let conversation: Conversation | undefined
  if (conversation_id) {
    conversation = conversationManager.get(conversation_id)
  }

  if (conversation) {
    // 复用对话
    const lastMessage = messages[messages.length - 1]
    conversation.connection.sendUserInput(lastMessage.content)
    // ... 流式输出
  } else {
    // 创建新任务
    const prompt = messagesToPrompt(messages)
    const taskId = await taskRunner.createTask(model, prompt)
    const connection = new TaskConnection(taskId, auth)
    conversation = conversationManager.create(taskId, connection)

    // 发送第一条消息
    connection.sendUserInput(prompt)
    // ... 流式输出

    // 返回 conversation_id
    res.setHeader("X-Conversation-Id", conversation.id)
  }
})
```

---

## 4. 与 OpenAI API 的兼容性

### 4.1 标准 OpenAI API

标准 OpenAI API 不支持 `conversation_id`，客户端每次发送完整消息历史。

**代理行为**：
- 每次创建新任务
- 无状态，简单可靠

### 4.2 扩展 API

为了支持多轮对话，代理可以扩展 API：

**方式 1: 自定义 header**
```
X-Conversation-Id: conv-xxx
```

**方式 2: 自定义字段**
```json
{
  "model": "monkeycode/...",
  "messages": [...],
  "conversation_id": "conv-xxx"
}
```

**方式 3: 自定义参数**
```json
{
  "model": "monkeycode/...",
  "messages": [...],
  "extra": {
    "conversation_id": "conv-xxx"
  }
}
```

**建议**：使用方式 2（自定义字段），因为：
- 与 OpenAI API 兼容（额外字段会被忽略）
- 客户端可以明确指定对话
- 实现简单

---

## 5. 实施计划

### 5.1 Phase 1: 基础多轮支持（P1）

1. 实现 `ConversationManager` 类
2. 实现 `TaskConnection` 类
3. 更新 API 路由支持 `conversation_id`
4. 添加对话超时清理

**工作量**：~200 行代码

### 5.2 Phase 2: 高级功能（P2）

1. 对话持久化（Redis/数据库）
2. 对话列表 API
3. 对话消息历史 API
4. 对话删除 API

**工作量**：~300 行代码

### 5.3 Phase 3: 优化（P3）

1. VM 预热池
2. 对话负载均衡
3. 对话迁移（VM 故障时）

**工作量**：~500 行代码

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| WS 连接泄漏 | 内存泄漏 | 定时清理超时对话 |
| VM 空闲超时 | 对话中断 | 定期发送心跳 |
| 并发访问 | 数据竞争 | 使用锁或队列 |
| 任务异常 | 对话失效 | 自动重连机制 |

---

## 7. 总结

**推荐方案**：方案 C（混合方案）

- 默认行为：无状态，每次创建新任务（兼容 OpenAI API）
- 扩展行为：支持 `conversation_id`，复用对话（低延迟）
- 实现复杂度：中等（~200 行代码）
- 兼容性：完全兼容 OpenAI API

**下一步**：实施 Phase 1，实现基础多轮支持。
