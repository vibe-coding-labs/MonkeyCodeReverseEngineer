---
description: Task Stream WebSocket 协议完整分析 — ACP 事件流、代理实现、自动审批、重连
protocol_version: based on proxy/src/task-runner.ts + proxy/src/conversation-manager.ts
confidence: high
last_verified: 2026-06-28
---

# Task Stream WebSocket（源码增强版）

## 端点

```http
GET /api/v1/users/tasks/stream?id={taskId}&mode={new|attach}
Cookie: monkeycode_ai_session=xxx
```

## 连接模式

| 模式 | 说明 |
|------|------|
| `new` | 创建新的任务轮次，等待用户输入后开始执行 |
| `attach` | 附加到已有任务，先回放历史再接收实时数据 |

## 代理层的 WS 连接实现

### WebSocket 连接头构造

```typescript
// proxy/src/browser-headers.ts
export function wsHeaders(domain: string, cookie: string): Record<string, string> {
  return {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    Pragma: "no-cache",
    Origin: `https://${domain}`,
    Cookie: cookie,
    "Sec-WebSocket-Version": "13",
  }
}
```

### Task Stream WS 连接（代理核心实现）

```typescript
// proxy/src/task-runner.ts — streamTask 核心流程
async streamTask(
  taskId: string,
  prompt: string,
  onChunk: (chunk: OpenAIChatCompletionChunk) => void,
  signal?: AbortSignal,
  authOverride?: AuthManager
): Promise<void> {
  const auth = authOverride || this.auth
  const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=new`

  const ws = new WebSocket(wsUrl, {
    headers: wsHeaders("monkeycode-ai.com",
      `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`),
  })

  let resolved = false
  let accumulatedUsage = { input_tokens: 0, output_tokens: 0, total_tokens: 0 }

  // 连接成功后立即发送初始化消息
  ws.on("open", () => {
    // 1. 启用自动审批模式（Agent 不再等待用户确认）
    ws.send(JSON.stringify({ type: "auto-approve" }))
    // 2. 发送用户输入
    ws.send(JSON.stringify({ type: "user-input", data: prompt }))
  })

  // 接收消息
  ws.on("message", (raw) => {
    if (resolved) return
    try {
      const msg: TaskStreamMessage = JSON.parse(raw.toString())
      // 心跳响应
      if (msg.type === "ping") {
        ws.send(JSON.stringify({ type: "ping" }))
        return
      }
      this.handleStreamMessage(msg, taskId, onChunk, accumulatedUsage, ws)
    } catch {
      // 忽略非 JSON 消息
    }
  })

  // 超时保护
  setTimeout(() => {
    if (!resolved) {
      console.warn(`[TaskRunner] Task ${taskId} timed out`)
      cleanup(); resolve()
    }
  }, TASK_TIMEOUT_MS)
}
```

## 消息格式

```typescript
interface TaskStreamMessage {
  type: string      // 消息类型
  data?: string     // 消息数据（JSON 字符串）
  kind?: string     // 子类型（task-running 的 ACP 事件分类）
  timestamp?: number // 时间戳
}
```

## 下行消息类型（Server → Client）

| type | kind | data 格式 | 说明 |
|------|------|-----------|------|
| `task-started` | - | - | 任务轮次开始 |
| `task-ended` | - | `{"usage": {"input_tokens":N, "output_tokens":N}}` | 任务轮次结束 |
| `task-error` | - | `{"error":"..."}` | 任务出错 |
| `task-running` | `acp_event` | ACP SessionUpdate JSON | Agent 通信协议事件 |
| `task-running` | `acp_ask_user_question` | base64 编码的提问数据 | Agent 向用户提问 |
| `cursor` | - | `{cursor, has_more}` | 历史分页游标 |
| `ping` | - | - | 心跳（每 10s） |

## 上行消息类型（Client → Server）

| type | data 格式 | 说明 |
|------|-----------|------|
| `user-input` | 纯文本 或 `{"content": btoa(text), "attachments": [...]}` | 用户输入 |
| `user-cancel` | 无 | 取消当前操作 |
| `reply-question` | `{"request_id", "answers_json", "cancelled"}` | 回复 Agent 提问 |
| `auto-approve` | - | 自动批准工具执行 |

## ACP 事件 Handle 完整实现

```typescript
// proxy/src/task-runner.ts — 6 种 ACP 事件处理
private handleACPEvent(acp, chatId, now, onChunk, usage): void {
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
      if (acp.input_tokens) usage.input_tokens = acp.input_tokens
      if (acp.output_tokens) usage.output_tokens = acp.output_tokens
      if (acp.total_tokens) usage.total_tokens = acp.total_tokens
      break

    case "tool_call":
      onChunk({
        id: chatId,
        object: "chat.completion.chunk",
        created: now,
        model: "monkeycode",
        choices: [{ index: 0, delta: { content: `[Tool: ${acp.tool_name}] ${acp.tool_input}` }, finish_reason: null }],
      })
      break

    case "tool_call_update":
      // 仅日志记录
      console.log(`[TaskRunner] tool_call_update: status=${acp.status}, args=${acp.tool_input?.slice(0,100)}`)
      break

    case "plan":
      console.log(`[TaskRunner] plan:`, JSON.stringify(acp.steps || acp).slice(0, 200))
      break

    case "available_commands_update":
      console.log(`[TaskRunner] available_commands:`, JSON.stringify(acp.commands || acp).slice(0, 200))
      break
  }
}

// 自动回复 Agent 提问
if (msg.kind === "acp_ask_user_question") {
  const questionData = JSON.parse(msg.data)
  ws.send(JSON.stringify({
    type: "reply-question",
    data: JSON.stringify({
      request_id: questionData.request_id || questionData.id || "",
      answers_json: "",
      cancelled: false,  // 不取消，自动继续
    }),
  }))
}
```

## ACP → OpenAI SSE 转换过程

```
ACP 事件                               → OpenAI SSE 格式
─────────                                  ────────────────
agent_message_chunk {text:"Hello"}         → delta: {content: "Hello"}
agent_thought_chunk {content:"思考中..."}  → delta: {content: "[Thinking] 思考中..."}
tool_call {tool_name:"bash",               → delta: {content: "[Tool: bash] ls -la"}
          tool_input:"ls -la"}
usage_update {input_tokens:150,             → 累积到 usage 计数器
             output_tokens:450}
task-ended                                  → delta: {}, finish_reason: "stop"
                                            → usage: {prompt_tokens, completion_tokens, total_tokens}
task-error {data:"timeout"}                → delta: {content: "[Error] timeout"}
```

## task-ended 事件的 SSE 输出

```typescript
// proxy/src/task-runner.ts — task-ended 事件处理
case "task-ended":
  onChunk({
    id: chatId,
    object: "chat.completion.chunk",
    created: now,
    model: "monkeycode",
    choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
    usage: usage.total_tokens > 0 ? {
      prompt_tokens: usage.input_tokens,
      completion_tokens: usage.output_tokens,
      total_tokens: usage.total_tokens,
    } : undefined,
  })
  break
```

## 重连机制

| 参数 | 值 |
|------|-----|
| 策略 | 指数退避 |
| 初始延迟 | 500ms |
| 最大延迟 | 8s |
| 重连模式 | `attach`（回放历史 + 继续实时流） |
| 去重 | 通过 `type+kind+timestamp+data` hash 追踪已处理块 |
| 去重上限 | 2000 个块 |

## 代理的原始 ACP 事件流（供 Responses API 使用）

```typescript
// proxy/src/task-runner.ts — streamTaskRaw 原始事件流
async streamTaskRaw(taskId, prompt, onEvent, signal, authOverride): Promise<Usage> {
  // 与 streamTask 相同的 WS 连接逻辑
  // 但是 onEvent 接收原始 {type, data} 而非转换后的 OpenAI 格式
  //
  // 输出事件:
  // { type: "task-started", data: {} }
  // { type: "acp", data: acpEvent }
  // { type: "task-ended", data: {} }
  // { type: "task-error", data: errorMsg }
}
```

---

## 相关章节

- [Task Control WebSocket](02-task-control.md) — 管理通道
- [ACP 事件参考](06-acp-event-reference.md) — 事件格式完整参考
- [代理 ACP→OpenAI 映射](../07-proxy/04-acp-to-openai-mapping.md) — 完整映射表
- [多轮对话](../07-proxy/03-multi-turn-conversation.md) — mode=attach 复用