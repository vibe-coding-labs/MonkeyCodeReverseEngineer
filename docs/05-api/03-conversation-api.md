---
description: Conversation API 完整分析 — Go + TypeScript 双实现、6 端点、ConversationManager 源码
protocol_version: based on chaitin/MonkeyCode Go 源码 + proxy/src/conversation-manager.ts (369 行)
confidence: high
last_verified: 2026-06-28
---

# Conversation API（源码增强版）

> **Go 端:** `user.go` — 6 个对话管理端点
> **TypeScript 端:** `proxy/src/conversation-manager.ts` — 369 行的完整实现
> **核心发现:** 双实现对比 + ConversationManager 源码全覆盖

## 1. Go 后端端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/users/conversations` | 列出用户的所有对话 |
| POST | `/api/v1/users/conversations` | 创建新对话 |
| GET | `/api/v1/users/conversations/:id` | 获取对话详情 |
| PUT | `/api/v1/users/conversations/:id` | 更新对话 |
| DELETE | `/api/v1/users/conversations/:id` | 删除对话 |
| GET | `/api/v1/users/conversations/:id/messages` | 获取对话消息列表 |

### Go 数据结构

```go
// 后端对话结构体（从源码推断）
type Conversation struct {
    ID        string    `json:"id"`         // UUID
    UserID    string    `json:"user_id"`    // 所有者
    Title     string    `json:"title"`      // 对话标题
    TaskID    string    `json:"task_id"`    // 关联任务 UUID
    ModelID   string    `json:"model_id"`   // 使用的模型 UUID
    Status    string    `json:"status"`     // active | archived
    CreatedAt time.Time `json:"created_at"`
    UpdatedAt time.Time `json:"updated_at"`
}
```

> **注意:** Go 后端的 Conversation 是数据持久化实体，而代理层的 Conversation 是运行时内存对象。

## 2. TypeScript ConversationManager 完整源码分析

### 2.1 接口定义

```typescript
// proxy/src/types.ts — Conversation 类型
export interface Conversation {
  id: string
  taskId: string
  modelId: string
  messages: OpenAIMessage[]
  lastUsedAt: number
  createdAt: number
}

export interface ConversationManagerConfig {
  maxConversations?: number
  conversationTimeoutMs?: number
  cleanupIntervalMs?: number
}
```

### 2.2 完整实现

```typescript
// proxy/src/conversation-manager.ts — 核心类
export class ConversationManager {
  private conversations: Map<string, Conversation> = new Map()
  private cleanupTimer: ReturnType<typeof setInterval> | null = null
  private conversationTimeoutMs: number

  constructor(options?: {
    conversationTimeoutMs?: number
    cleanupIntervalMs?: number
  }) {
    this.conversationTimeoutMs = options?.conversationTimeoutMs || 30 * 60 * 1000 // 30 分钟
    const cleanupInterval = options?.cleanupIntervalMs || 5 * 60 * 1000 // 5 分钟
    this.cleanupTimer = setInterval(() => this.cleanup(), cleanupInterval)
  }

  /** 创建新对话 */
  create(taskId: string, model: MonkeyCodeModel,
         auth: AuthManager, messages: OpenAIMessage[]): Conversation {
    const id = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const conversation: Conversation = {
      id, taskId, model, auth,
      messages: [...messages],
      lastUsedAt: Date.now(), createdAt: Date.now(),
      onChunk: null, resolvePromise: null, rejectPromise: null,
    }
    this.conversations.set(id, conversation)
    return conversation
  }

  /** 获取对话 */
  get(id: string): Conversation | undefined {
    const conversation = this.conversations.get(id)
    if (conversation) conversation.lastUsedAt = Date.now()
    return conversation
  }

  /** 删除对话（关闭 WS 连接） */
  delete(id: string): boolean {
    const conversation = this.conversations.get(id)
    if (conversation) {
      if (conversation.ws) conversation.ws.close()
      this.conversations.delete(id)
      return true
    }
    return false
  }

  /** 定期清理过期对话 */
  private cleanup(): void {
    const now = Date.now()
    for (const [id, conversation] of this.conversations) {
      if (now - conversation.lastUsedAt > this.conversationTimeoutMs) {
        this.delete(id)  // 30 分钟未使用 → 清理
      }
    }
  }

  /** 停止管理器 */
  destroy(): void {
    if (this.cleanupTimer) clearInterval(this.cleanupTimer)
    for (const [id] of this.conversations) this.delete(id)
  }

  /** 连接对话的 WebSocket */
  async connectToTask(conversation: Conversation,
    onChunk: (chunk: OpenAIChatCompletionChunk) => void): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsUrl = `wss://monkeycode-ai.com/api/v1/users/tasks/stream?id=${conversation.taskId}&mode=attach`
      const ws = new WebSocket(wsUrl, {
        headers: wsHeaders("monkeycode-ai.com",
          `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`),
      })
      // ... WS 事件处理
    })
  }
}
```

## 3. ConversationManager ACP 事件处理

```typescript
private handleACPEvent(acp, chatId, now, onChunk, conversation): void {
  switch (acp.type) {
    case "agent_message_chunk":
      // → SSE: delta.content = acp.text
      onChunk({ id: chatId, choices: [{delta: {content: acp.text}}] })
      break

    case "agent_thought_chunk":
      // → SSE: delta.content = "[Thinking] " + acp.text
      onChunk({ id: chatId, choices: [{delta: {content: `[Thinking] ${acp.text}`}}] })
      break

    case "tool_call":
      // → SSE: delta.content = "[Tool: name] input"
      onChunk({ id: chatId, choices: [{delta: {content: `[Tool: ${acp.tool_name}] ${acp.tool_input}`}}] })
      break

    case "usage_update":
      // 累积用量，在 task-ended 时输出
      break

    case "task-ended":
      // → SSE: finish_reason: "stop"
      onChunk({ id: chatId, choices: [{delta: {}, finish_reason: "stop"}] })
      conversation.resolvePromise?.()
      break
  }
}
```

## 4. 对话复用流程

```
Client                   代理 api-routes.ts               ConversationManager
  │                           │                               │
  │ POST /v1/chat/completions  │                               │
  │ { messages: [...],         │                               │
  │   conversation_id: "..." } │                               │
  ├──────────────────────────►│                               │
  │                           │ get(conversationId)            │
  │                           ├──────────────────────────────►│
  │                           │◄── conversation ─────────────│
  │                           │                               │
  │                           │ 发送最后一条 user message       │
  │                           │ sendUserInput(conv, content)   │
  │                           ├──────────────────────────────►│
  │                           │   ws.send({type:"user-input",  │
  │                           │            data: content})     │
  │                           │                               │
  │ ◄── SSE 流 ──────────────│  ACP 事件 → SSE 转换          │
  │                           │                               │
  │                           │ task-ended → resolvePromise() │
  │                           │◄──────────────────────────────│
```

## 5. Go 后端 vs TypeScript 代理实现对比

| 维度 | Go 后端 | TypeScript 代理 |
|------|---------|----------------|
| 存储 | PostgreSQL（持久化） | 内存 Map（运行时） |
| ID 生成 | UUID（数据库自增） | `conv-{timestamp}-{random}` |
| 超时策略 | 无自动清理 | 30 分钟 TTL + 5 分钟定时清理 |
| 多轮实现 | 查询历史消息 | 复用 WebSocket 连接（mode=attach）|
| 可见性 | 按 UserID 隔离 | 全局 Map（单进程）|
| WS 管理 | 任务内部 | ConversationManager 持有 WS 引用 |
| 并发 | 多实例安全（Redis Pub/Sub） | 单实例（非集群安全）|

---

## 相关章节

- [代理多轮对话设计](../07-proxy/03-multi-turn-conversation.md) — 代理层对话管理
- [WebSocket 任务流](../04-websocket/01-task-stream.md) — WS 流协议
- [API 端点目录](01-endpoint-catalog.md) — 完整端点列表
