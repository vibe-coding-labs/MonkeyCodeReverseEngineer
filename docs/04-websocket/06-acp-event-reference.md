---
description: ACP (Agent-Client-Protocol) 事件类型完整参考 — 格式、字段、示例
protocol_version: based on chaitin/MonkeyCode 开源源码 + 代理逆向
confidence: high
last_verified: 2026-06-25
---

# ACP 事件类型参考

## 事件一览

| 事件 | 方向 | 说明 | 完成度 |
|------|------|------|--------|
| `agent_message_chunk` | Agent → 用户 | Agent 输出文本块 | ✅ 完整 |
| `agent_thought_chunk` | Agent → 用户 | Agent 推理文本块 | ✅ 完整 |
| `tool_call` | Agent → 用户 | 工具调用开始 | ✅ 完整 |
| `tool_call_update` | Agent → 用户 | 工具调用状态更新 | ✅ 已确认 |
| `usage_update` | Agent → 用户 | Token 使用量更新 | ✅ 完整 |
| `plan` | Agent → 用户 | 执行计划（含步骤状态） | 🟡 日志级 |
| `available_commands_update` | Agent → 用户 | 可用命令更新 | 🟡 日志级 |
| `task-ended` | Agent → 用户 | 任务结束 | ✅ 完整 |

## agent_message_chunk

Agent 输出的文本流式块，逐 token 推送给前端。

```json
{
  "type": "agent_message_chunk",
  "text": "Hello ",
  "content": "Hello "
}
```

| 字段 | 类型 | 说明 | 已知示例值 |
|------|------|------|-----------|
| `type` | string | 事件类型 | `"agent_message_chunk"` |
| `text` | string | 文本内容 | 任意文本 |
| `content` | string | 内容代理 | 与 text 相同 |

## agent_thought_chunk

Agent 内部推理的文本流式块。与 `agent_message_chunk` 区别在于来源——非最终输出，而是推理中间过程。

```json
{
  "type": "agent_thought_chunk",
  "text": "用户要求实现一个快速排序算法，我需要先设计数据结构...",
  "content": "用户要求实现一个快速排序算法，我需要先设计数据结构..."
}
```

## tool_call

Agent 调用工具的开始信号。

```json
{
  "type": "tool_call",
  "tool_name": "bash",
  "tool_input": "ls -la /workspace"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | `"tool_call"` |
| `tool_name` | string | 工具名（bash / file_read / file_write / git 等） |
| `tool_input` | string | 工具参数（JSON 序列化的字符串） |

## tool_call_update

工具调用的状态更新。

**已从代理源码确认字段:**

```json
{
  "type": "tool_call_update",
  "tool_name": "bash",
  "tool_input": "...",          // 工具参数的增量更新
  "delta": "...",               // 工具参数的增量文本（与 tool_input 等价）
  "status": "running"           // 工具状态: running | success | error
}
```

**字段说明:**

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `type` | string | 固定 `"tool_call_update"` | proxy/src/task-runner.ts:317 |
| `tool_name` | string | 工具名称（bash / file_read 等） | 代理从 `acp.tool_name` 读取 |
| `tool_input` | string | 工具参数的增量更新 | proxy/src/task-runner.ts:319 |
| `delta` | string | 与 `tool_input` 等价的增量文本 | proxy/src/task-runner.ts:319 `acp.tool_input || acp.delta` |
| `status` | string | 工具状态: `"running"` / `"success"` / `"error"` / `"completed"` / `"done"` | proxy/src/task-runner.ts:320 + api-routes.ts:245 |

Proxy 中的 `api-routes.ts` 还在 Responses API 处理中检查 `status === "completed" || status === "done"` 作为工具调用完成标志（api-routes.ts:245），这确认了 `tool_call_update` 可以有多种状态值。

**代理中的处理逻辑（proxy/src/task-runner.ts:317-323）:**

```typescript
case "tool_call_update": {
  const updateArgs = String(acp.tool_input || acp.delta || "")
  const status = String(acp.status || "")
  console.log(`[TaskRunner] tool_call_update: status=${status}, args=${updateArgs.slice(0, 100)}`)
  break
}
```

> **注意:** 当前代理仅记录 `tool_call_update` 的日志，未将其转换为 OpenAI SSE 格式。如果要实现 tool call streaming，`tool_input` 的增量更新应该拼接成完整的函数调用参数，在最终 `tool_call` 结束时一次性发出。

## usage_update

Token 使用量更新，在任务执行过程中多次发送（增量）。

```json
{
  "type": "usage_update",
  "input_tokens": 150,
  "output_tokens": 450,
  "total_tokens": 600
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | `"usage_update"` |
| `input_tokens` | int | 输入 Token 数 |
| `output_tokens` | int | 输出 Token 数 |
| `total_tokens` | int | 总 Token 数 |

> **注意:** `usage_update` 可能是增量值（需在代理中累积），也可能是累计值（直接可用）。当前代理实现将其作为累计值处理。

## plan

Agent 的执行计划，包含步骤列表和状态。代理将其作为日志记录。

```json
{
  "type": "plan",
  "steps": [
    {"id": "1", "title": "分析需求", "status": "completed"},
    {"id": "2", "title": "编写代码", "status": "running"},
    {"id": "3", "title": "测试验证", "status": "pending"}
  ]
}
```

| 字段 | 类型 | 说明 | 证据 |
|------|------|------|------|
| `type` | string | `"plan"` | `acp.steps \|\| acp` (proxy/src/task-runner.ts:327) |
| `steps` | array | 包含 `id`、`title`、`status` 的步骤数组 | 推断，源自 docs/protocol/websocket-protocol.md |

> **注意:** `steps` 结构是基于文档和代理代码的推断，具体字段名可能略有不同。

## available_commands_update

Agent 的可用命令更新。代理将其作为日志记录。

```json
{
  "type": "available_commands_update",
  "commands": ["bash", "file_read", "file_write", "git"]
}
```

| 字段 | 类型 | 说明 | 证据 |
|------|------|------|------|
| `type` | string | `"available_commands_update"` | proxy/src/task-runner.ts:332 |
| `commands` | string[] | 可用命令列表 | `acp.commands \|\| acp` (proxy/src/task-runner.ts:334)

> **注意:** `commands` 数组中的具体命令名称为推断值。

## ACP → OpenAI 事件映射

### Chat Completions 模式

| ACP 事件 | OpenAI 格式 |
|---------|------------|
| `agent_message_chunk` | `delta.content` |
| `agent_thought_chunk` | `delta.content`（带 `[Thinking]` 前缀） |
| `tool_call` | `delta.content`（带 `[Tool: name]` 前缀） |
| `task-ended` + `usage_update` | 最终 `choices[0].finish_reason='stop'` + `usage` |

### Responses API 模式

| ACP 事件 | OpenAI Responses 格式 |
|---------|---------------------|
| `task-started` | `response.created` |
| `agent_message_chunk` | `response.output_text.delta` |
| `agent_thought_chunk` | `response.output_text.delta`（`[Thinking]` 前缀） |
| `tool_call` | `response.output_item.added`（type: function_call） |
| `tool_call_update` | `response.function_call_arguments.delta`（推测） |
| `usage_update` | 累积 → `response.completed` 中的 usage |
| `task-ended` | `response.completed` |

---

## 相关章节

- [Task Stream WebSocket](01-task-stream.md) — ACP 事件的传输通道
- [第七章：ACP→OpenAI 映射](../07-proxy/04-acp-to-openai-mapping.md) — 代理中的事件转换实现