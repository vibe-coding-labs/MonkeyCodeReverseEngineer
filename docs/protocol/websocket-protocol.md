# MonkeyCode WebSocket 流式协议详解

## 概述

MonkeyCode 使用三个独立的 WebSocket 通道实现任务执行期间的实时通信。

## 1. Task Stream WebSocket

**端点**: `GET /api/v1/users/tasks/stream?id={taskId}&mode={new|attach}`

**认证**: Cookie-based Session（`monkeycode_ai_session`）

**用途**: 任务执行数据的双向流式传输

### 连接模式

| 模式 | 说明 |
|------|------|
| `new` | 创建新的任务轮次，等待用户输入后开始执行 |
| `attach` | 附加到已有任务，先回放历史再接收实时数据 |

### 消息格式

```typescript
interface TaskStreamMessage {
  type: string      // 消息类型
  data: string      // 消息数据（可能是 JSON 字符串或 base64 编码）
  kind?: string     // 子类型（用于 task-running 的 ACP 事件分类）
  timestamp?: number // 时间戳
}
```

### 下行消息类型（Server → Client）

| type | kind | 说明 |
|------|------|------|
| `task-started` | - | 任务轮次开始 |
| `task-ended` | - | 任务轮次结束 |
| `task-error` | - | 任务出错 |
| `task-running` | `acp_event` | Agent 通信协议事件（消息块、思考块、工具调用等） |
| `task-running` | `acp_ask_user_question` | Agent 向用户提问 |
| `cursor` | - | 历史分页游标 `{cursor, has_more}` |
| `ping` | - | 心跳（每 10s） |

### ACP 事件子类型（task-running + kind=acp_event）

```typescript
// data 字段为 JSON 字符串，解析后为 ACP SessionUpdate
interface ACPSessionUpdate {
  type: string  // 事件子类型
  // ... 各子类型特有字段
}
```

| ACP 事件类型 | 说明 |
|-------------|------|
| `agent_message_chunk` | Agent 输出文本流式块 |
| `agent_thought_chunk` | Agent 内部推理流式块 |
| `tool_call` | 工具调用开始 |
| `tool_call_update` | 工具调用状态更新 |
| `available_commands_update` | 可用命令更新 |
| `plan` | 执行计划（含步骤状态） |
| `usage_update` | Token 使用量更新 |

### 上行消息类型（Client → Server）

| type | 说明 | data 格式 |
|------|------|-----------|
| `user-input` | 用户输入 | `{content: base64(text), attachments: [...]}` |
| `user-cancel` | 取消当前操作 | 无 |
| `reply-question` | 回复 Agent 提问 | `{request_id, answers_json, cancelled}` |

### 用户输入格式

```typescript
// 新格式（base64 编码）
{
  type: "user-input",
  data: JSON.stringify({
    content: btoa("用户输入的文本"),
    attachments: [{ url: "https://...", filename: "file.txt" }]
  })
}

// 旧格式（纯文本，仍支持）
{
  type: "user-input",
  data: "用户输入的文本"
}
```

### 重连机制

- 指数退避：500ms → 1s → 2s → 4s → 8s
- 去重：通过 type+kind+timestamp+data hash 追踪已处理块
- 最多追踪 2000 个块

---

## 2. Task Control WebSocket

**端点**: `GET /api/v1/users/tasks/control?id={taskId}`

**认证**: Cookie-based Session

**用途**: 同步 RPC 调用（文件操作、重启、模型切换）

**特性**: 长连接，任务完成后仍保持，支持多标签页并发连接

### 上行消息类型

| type | kind | 说明 | data 格式 |
|------|------|------|-----------|
| `call` | `repo_file_list` | 列出目录文件 | `{request_id, path, glob_pattern?, include_hidden}` |
| `call` | `repo_file_diff` | 获取文件 diff | `{request_id, path, unified, context_lines}` |
| `call` | `repo_read_file` | 读取文件内容 | `{request_id, path}` |
| `call` | `repo_file_changes` | 获取变更文件列表 | `{request_id}` |
| `call` | `port_forward_list` | 获取端口转发列表 | `{request_id}` |
| `call` | `restart` | 重启任务 | `{request_id, load_session}` |
| `call` | `switch_model` | 切换模型 | `{request_id, model_id, load_session}` |
| `sync-my-ip` | - | 同步客户端 IP | `{ip: "..."}` |

### 下行消息类型

| type | 说明 |
|------|------|
| `call-response` | RPC 响应（匹配 request_id） |
| `task-event` | 任务事件转发 |
| `ping` | 心跳（每 10s） |

### Call-Response 示例

```typescript
// 请求：读取文件
send({
  type: "call",
  kind: "repo_read_file",
  data: JSON.stringify({ request_id: "req-1", path: "/workspace/main.go" })
})

// 响应
receive({
  type: "call-response",
  kind: "repo_read_file",
  data: JSON.stringify({
    request_id: "req-1",
    path: "/workspace/main.go",
    content: "base64_encoded_file_content",
    success: true
  })
})
```

---

## 3. TaskLive WebSocket（内部）

**端点**: `ws(s)://TASKFLOW_SERVER/internal/ws/task-live?id={taskID}&flush={bool}`

**用途**: Backend 与 TaskFlow 服务之间的实时事件流

**特性**: 无读取限制（`SetReadLimit(-1)`）

### TaskChunk 格式

```go
type TaskChunk struct {
    Data      []byte `json:"data,omitempty"`
    Event     string `json:"event"`
    Kind      string `json:"kind"`
    Timestamp int64  `json:"timestamp,omitempty"`
}
```

---

## 4. Terminal WebSocket

**端点**: `GET /api/v1/users/hosts/vms/{vmId}/terminals/connect?terminal_id={id}&col={cols}&row={rows}`

**用途**: VM 交互式终端

**特性**:
- 自动重连（指数退避 1s → 30s）
- Keepalive ping（15s 间隔，5s 超时）
- 二进制帧：原始终端数据
- 文本帧：JSON 事件（resize 等）
- 写超时：10s

---

## 5. Speech-to-Text SSE

**端点**: `POST /api/v1/users/tasks/speech-to-text`

**用途**: 语音识别流式输出

**格式**: Server-Sent Events

```
event: recognition
data: {"type":"result","text":"部分识别结果","is_final":false}

event: recognition
data: {"type":"result","text":"完整识别结果","is_final":true}

event: end
data: {"type":"end"}

event: error
data: {"type":"error","error":"错误信息"}
```

---

## 反向代理流式转发策略

对于 OpenAI 兼容的反向代理，需要：

1. **接收 OpenAI 格式请求** → 转换为 MonkeyCode 任务创建
2. **连接 Task Stream WebSocket** → 接收 ACP 事件流
3. **转换 ACP 事件为 OpenAI SSE 格式** → 流式返回给客户端

```typescript
// ACP → OpenAI SSE 转换示例
function acpToOpenAISSE(event: ACPSessionUpdate): string {
  switch (event.type) {
    case 'agent_message_chunk':
      return `data: ${JSON.stringify({
        id: `chatcmpl-${taskId}`,
        object: 'chat.completion.chunk',
        choices: [{
          index: 0,
          delta: { content: event.text },
          finish_reason: null
        }]
      })}\n\n`

    case 'usage_update':
      // 在最后一个 chunk 中包含 usage
      return `data: ${JSON.stringify({
        id: `chatcmpl-${taskId}`,
        object: 'chat.completion.chunk',
        choices: [{
          index: 0,
          delta: {},
          finish_reason: 'stop'
        }],
        usage: {
          prompt_tokens: event.input_tokens,
          completion_tokens: event.output_tokens,
          total_tokens: event.total_tokens
        }
      })}\n\n`

    default:
      return ''  // 忽略其他事件
  }
}
```
