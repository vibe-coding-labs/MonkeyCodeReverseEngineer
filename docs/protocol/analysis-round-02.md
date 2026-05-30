# 逆向分析轮次 02 — P0 深度分析

> **时间:** 2026-05-30 00:55 UTC+8
> **聚焦:** auto-approve 机制、tool_call_update 字段、Conversation API

---

## 1. auto-approve 机制深度分析

### 1.1 协议定义

从 `llm-protocol-complete.md:761-762`:

| 上行命令 | 说明 | data 格式 |
|----------|------|-----------|
| `auto-approve` | 开启自动批准 | 无 |
| `disable-auto-approve` | 关闭自动批准 | 无 |

### 1.2 代理实现分析

**task-runner.ts:131-141** (streamTask):
```typescript
ws.on("open", () => {
  ws.send(JSON.stringify({ type: "auto-approve" }))  // ← 开启自动批准
  ws.send(JSON.stringify({ type: "user-input", data: prompt }))
})
```

**task-runner.ts:211-228** (handleStreamMessage):
```typescript
} else if (msg.kind === "acp_ask_user_question") {
  // Agent 请求用户确认 — 自动回复以继续执行
  const questionData = JSON.parse(msg.data)
  const requestId = questionData.request_id || questionData.id || ""
  ws.send(JSON.stringify({
    type: "reply-question",
    data: JSON.stringify({
      request_id: requestId,
      answers_json: "",
      cancelled: false,
    }),
  }))
}
```

### 1.3 冲突分析

**假设 1**: `auto-approve` 让 Agent 跳过所有确认，不再发送 `acp_ask_user_question`
- 如果成立：`acp_ask_user_question` handler 是死代码
- 代理不会双重回复
- **风险**: 无

**假设 2**: `auto-approve` 仅跳过某些确认，Agent 仍可能发送 `acp_ask_user_question`
- 如果成立：需要 `reply-question` 来继续执行
- 代理需要两者都保留
- **风险**: 无双重回复，因为 `auto-approve` 不覆盖此类问题

**假设 3**: `auto-approve` 和 `reply-question` 是独立机制
- `auto-approve`: 控制 Agent 是否等待用户确认工具执行
- `reply-question`: 回复 Agent 的特定问题（如"要继续吗？"）
- 两者互补，不冲突
- **风险**: 无

### 1.4 结论

**`auto-approve` 和 `acp_ask_user_question` 自动回复不冲突**。理由：

1. `auto-approve` 是 WS 连接级别的全局设置，告诉 Agent "不要等待用户确认工具执行"
2. `acp_ask_user_question` 是 Agent 在特定场景下发送的问题（如权限确认、歧义澄清）
3. 两者服务不同目的，可以共存
4. 代理的实现是正确的，不需要修改

**验证方法**: 需要线上实测确认。创建一个需要确认的任务（如删除文件），观察：
- 只发 `auto-approve` 时：Agent 是否等待确认？
- 只发 `reply-question` 时：Agent 是否继续执行？
- 两者都发时：是否有异常？

---

## 2. tool_call_update 字段分析

### 2.1 协议现状

从 `llm-protocol-complete.md:838`:
```
| `tool_call_update` | 工具调用状态更新 | - |
```

字段标记为 `-`（未知）。代理静默丢弃此事件。

### 2.2 推断分析

基于 ACP 事件的设计模式和 `tool_call` 的字段结构，推断 `tool_call_update` 的可能格式：

**模式 A: 增量参数更新**（最可能）
```json
{
  "type": "tool_call_update",
  "tool_name": "bash",
  "tool_input": "{\"command\":\"ls -la\"}",  // 完整参数（累积）
  "status": "running"  // 或 "completed", "failed"
}
```

**模式 B: 状态更新**
```json
{
  "type": "tool_call_update",
  "status": "running",
  "output": "partial output..."  // 工具的部分输出
}
```

**模式 C: 参数增量**
```json
{
  "type": "tool_call_update",
  "delta": " -la"  // 参数增量
}
```

### 2.3 代理当前处理

**api-routes.ts:185-209** (Responses API):
```typescript
} else if (acp.type === "tool_call") {
  currentCallId = `call_${acp.tool_name || "unknown"}_${Date.now()}`
  currentToolName = acp.tool_name || "unknown"
  const args = acp.tool_input || ""
  sendEvent("response.output_item.added", {...})
  sendEvent("response.function_call_arguments.delta", { delta: { arguments: args } })
  sendEvent("response.function_call_arguments.done", { arguments: args })
  sendEvent("response.output_item.done", {...})
  currentOutputIndex++
}
```

**问题**: 一次性发送所有参数，没有流式更新。

### 2.4 修复方案

**方案 A: 等待 tool_call_update（需要知道字段格式）**
```typescript
} else if (acp.type === "tool_call") {
  // 记录当前 tool_call，等待 update
  currentCallId = `call_${acp.tool_name}_${Date.now()}`
  currentToolName = acp.tool_name
  sendEvent("response.output_item.added", {
    type: "response.output_item.added",
    output_index: currentOutputIndex,
    item: { type: "function_call", id: currentCallId, call_id: currentCallId, name: currentToolName, arguments: "" },
  })
} else if (acp.type === "tool_call_update") {
  // 流式更新参数
  const args = acp.tool_input || acp.delta || ""
  sendEvent("response.function_call_arguments.delta", {
    type: "response.function_call_arguments.delta",
    output_index: currentOutputIndex,
    delta: { type: "function_call_arguments.delta", arguments: args },
  })
  // 如果是最终更新
  if (acp.status === "completed" || acp.status === "done") {
    sendEvent("response.function_call_arguments.done", {
      type: "response.function_call_arguments.done",
      output_index: currentOutputIndex,
      arguments: acp.tool_input || "",
    })
    sendEvent("response.output_item.done", {...})
    currentOutputIndex++
  }
}
```

**方案 B: 保持当前行为（简单，兼容性好）**
- `tool_call` 时一次性发送所有参数
- 忽略 `tool_call_update`
- 优点：简单可靠
- 缺点：Codex 可能期望流式参数更新

### 2.5 建议

**暂时保持方案 B**，原因：
1. `tool_call_update` 字段格式未知，盲目实现可能出错
2. 当前实现在功能上是完整的（参数最终会发送）
3. Codex 的 Responses API 实现可能容忍一次性参数

**后续**: 需要线上实测捕获 `tool_call_update` 的实际格式。

---

## 3. Conversation API 格式分析

### 3.1 已知端点

从 `api-endpoints.md:170-175`:

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/users/conversations` | 列出对话 |
| POST | `/api/v1/users/conversations` | 创建对话 |
| GET | `/api/v1/users/conversations/{id}` | 获取对话 |
| DELETE | `/api/v1/users/conversations/{id}` | 删除对话 |
| GET | `/api/v1/users/conversations/{id}/messages` | 列出消息 |
| POST | `/api/v1/users/conversations/{id}/messages` | 发送消息 |

### 3.2 推断格式

基于 GoYoko/web 框架的通用模式和 MonkeyCode 的其他 API 风格：

**创建对话**:
```json
POST /api/v1/users/conversations
{
  "title": "对话标题",  // 可选
  "model_id": "xxx",    // 可选，关联模型
  "task_id": "xxx"      // 可选，关联任务
}

Response:
{
  "code": 0,
  "data": {
    "id": "conv-uuid",
    "title": "对话标题",
    "created_at": 1715299200,
    "updated_at": 1715299200
  }
}
```

**列出对话**:
```json
GET /api/v1/users/conversations?page=1&size=20

Response:
{
  "code": 0,
  "data": {
    "conversations": [
      {
        "id": "conv-uuid",
        "title": "对话标题",
        "last_message": "最后一条消息...",
        "created_at": 1715299200,
        "updated_at": 1715299800
      }
    ],
    "page_info": {"page": 1, "size": 20, "total": 100}
  }
}
```

**发送消息**:
```json
POST /api/v1/users/conversations/{id}/messages
{
  "content": "用户消息",
  "role": "user"  // 或 "assistant"
}

Response:
{
  "code": 0,
  "data": {
    "id": "msg-uuid",
    "conversation_id": "conv-uuid",
    "role": "user",
    "content": "用户消息",
    "created_at": 1715299200
  }
}
```

### 3.3 与代理的关系

**当前代理不使用 Conversation API**。原因：
1. 代理是无状态的，每次请求创建新任务
2. 代理通过 Task Stream WS 传递消息，不通过 Conversation API
3. 多轮对话需要客户端自己维护上下文

**如果需要多轮对话支持**:
1. 客户端发送完整消息历史（包含之前的对话）
2. 代理将整个历史作为 prompt 发送给 MonkeyCode
3. 或者：代理实现 Conversation API，自动管理上下文

### 3.4 建议

**暂时不实现 Conversation API**，原因：
1. 当前代理设计是无状态的，简单可靠
2. 多轮对话可以通过客户端传完整历史实现
3. Conversation API 格式未完全确认，盲目实现可能出错

**后续**: 如果 Codex 需要多轮对话支持，再实现 Conversation API。

---

## 4. 其他发现

### 4.1 session_update WS 消息

从 `mvp/chat.py:83`:
```python
elif event_type == "session_update":
    status = data.get("data", {}).get("status", "unknown")
    print(f"[Chat]   会话状态: {status}")
```

**格式**: `{type: "session_update", data: {status: "..."}}`

**代理处理**: 忽略（不影响功能）

### 4.2 plan ACP 事件

从 `llm-protocol-complete.md:840`:
```
| `plan` | 执行计划 | 含步骤状态 |
```

**推断格式**:
```json
{
  "type": "plan",
  "steps": [
    {"id": 1, "description": "步骤1", "status": "completed"},
    {"id": 2, "description": "步骤2", "status": "in_progress"},
    {"id": 3, "description": "步骤3", "status": "pending"}
  ]
}
```

**代理处理**: 忽略（不影响功能，但丢失执行计划信息）

### 4.3 available_commands_update ACP 事件

**推断格式**:
```json
{
  "type": "available_commands_update",
  "commands": ["bash", "file_edit", "git"]
}
```

**代理处理**: 忽略（不影响功能，但丢失可用命令信息）

---

## 5. 代码修复建议 (待实施)

### 5.1 修复非流式 usage (P0)

```typescript
// api-routes.ts:364-397 — handleNonStreamResponse
let accumulatedUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }

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

// 使用累积的 usage
const response: OpenAIChatCompletionResponse = {
  // ...
  usage: accumulatedUsage.total_tokens > 0 ? accumulatedUsage : {
    prompt_tokens: 0, completion_tokens: 0, total_tokens: 0
  },
}
```

### 5.2 添加 tool_call_update 处理 (P1)

```typescript
// api-routes.ts — 在 tool_call 处理后添加
} else if (acp.type === "tool_call_update") {
  // 流式更新工具调用参数
  const args = acp.tool_input || acp.delta || ""
  if (args && currentCallId) {
    sendEvent("response.function_call_arguments.delta", {
      type: "response.function_call_arguments.delta",
      output_index: currentOutputIndex,
      delta: { type: "function_call_arguments.delta", arguments: args },
    })
  }
}
```

### 5.3 添加 plan 事件处理 (P2)

```typescript
// api-routes.ts — 在 tool_call_update 处理后添加
} else if (acp.type === "plan") {
  // 记录执行计划（可选：转换为 Responses API 格式）
  console.log(`[Responses] Plan:`, JSON.stringify(acp.steps || acp))
}
```

---

## 6. 下轮分析重点

### 优先级 P0 (影响 Codex 兼容性)

1. **线上实测 auto-approve**: 确认是否跳过 `acp_ask_user_question`
2. **捕获 tool_call_update**: 通过实际任务触发工具调用，观察完整事件流
3. **验证 Conversation API**: 测试端点存在性和响应格式

### 优先级 P1 (提升代理质量)

4. **修复非流式 usage**: 累积 `usage_update` 到最终响应
5. **添加 tool_call_update 处理**: 流式更新工具调用参数
6. **测试重连机制**: 断线后 attach 模式的行为

### 优先级 P2 (长期优化)

7. **实现 Conversation API**: 多轮对话支持
8. **plan 事件处理**: 记录执行计划
9. **available_commands_update 处理**: 记录可用命令

---

## 7. 相关文件索引

| 文件 | 用途 |
|------|------|
| `proxy/src/task-runner.ts:131-141` | auto-approve 发送逻辑 |
| `proxy/src/task-runner.ts:211-228` | acp_ask_user_question 处理 |
| `proxy/src/api-routes.ts:185-209` | tool_call → function_call 映射 |
| `proxy/src/api-routes.ts:364-397` | handleNonStreamResponse (usage bug) |
| `docs/protocol/llm-protocol-complete.md:761-762` | auto-approve/disable-auto-approve 定义 |
| `docs/protocol/llm-protocol-complete.md:838` | tool_call_update 字段未知 |
| `docs/protocol/api-endpoints.md:170-175` | Conversation API 端点 |
