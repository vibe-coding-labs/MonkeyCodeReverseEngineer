---
description: VM TaskFlow 架构 — TaskRunner 源码完整追踪、任务创建、ACP→SSE、超时保护
protocol_version: based on proxy/src/task-runner.ts (464 行) + chaitin/MonkeyCode pkg/taskflow/vm.go
confidence: high
last_verified: 2026-06-28
---

# VM TaskFlow 架构（源码增强版）

> **代理文件:** `proxy/src/task-runner.ts` (464 行) + Go `pkg/taskflow/vm.go`
> **核心发现:** TaskRunner 完整端到端流：创建→WS→ACP→SSE 转换

## 1. TaskRunner 类结构

```typescript
export class TaskRunner {
  private auth: AuthManager

  async createTask(model, prompt, options?): Promise<string>
  async streamTask(taskId, prompt, onChunk, signal?, auth?): Promise<void>
  async streamTaskRaw(taskId, prompt, onEvent, signal?, auth?): Promise<Usage>
  async stopTask(taskId, auth?): Promise<void>

  private handleStreamMessage(msg, taskId, onChunk, usage, ws): void
  private handleACPEvent(acp, chatId, now, onChunk, usage): void
}
```

## 2. 任务创建

```typescript
async createTask(model, prompt, options?): Promise<string> {
  const body = {
    content: prompt,
    host_id: process.env.MONKEYCODE_HOST_ID || "public_host",
    image_id: process.env.MONKEYCODE_IMAGE_ID || options?.imageId,
    model_id: model.id,
    cli_name: model.interface_type === "openai_responses" ? "codex"
            : model.interface_type === "anthropic" ? "claude"
            : "opencode",
    resource: { core: 1, memory: 1073741824, life: 3600 },
    repo: { repo_url: "", branch: "master", repo_filename: "", zip_url: "" },
  }
  if (options?.systemPrompt) body.system_prompt = options.systemPrompt

  const response = await fetch(`${BASE_URL}/api/v1/users/tasks`, {
    method: "POST", headers, body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`Failed (${response.status})`)
  const result = await response.json()
  if (result.code && result.code !== 0) throw new Error(...)
  return result.data.id || result.data.task_id
}
```

| 字段 | 说明 |
|------|------|
| `image_id` | VM 镜像 UUID（必需，否则抛出错误）|
| `cli_name` | interface_type → Agent 自动映射 |
| `resource` | core:1 / memory:1GB / life:3600s（后端可能忽略）|

## 3. WebSocket 流

```typescript
async streamTask(taskId, prompt, onChunk, signal?, authOverride?) {
  const ws = new WebSocket(
    `wss://monkeycode-ai.com/api/v1/users/tasks/stream?id=${taskId}&mode=new`,
    { headers: wsHeaders("monkeycode-ai.com", `${auth.getSessionCookieName()}=${cookie}`) }
  )

  ws.on("open", () => {
    ws.send(JSON.stringify({ type: "auto-approve" }))
    ws.send(JSON.stringify({ type: "user-input", data: prompt }))
  })

  ws.on("message", (raw) => {
    const msg = JSON.parse(raw.toString())
    if (msg.type === "ping") { ws.send(JSON.stringify({ type: "ping" })); return }
    this.handleStreamMessage(msg, taskId, onChunk, usage, ws)
  })
}
```

## 4. ACP 事件处理

```typescript
private handleStreamMessage(msg, taskId, onChunk, usage, ws) {
  switch (msg.type) {
    case "task-started": break
    case "task-running":
      if (msg.kind === "acp_event") {
        this.handleACPEvent(JSON.parse(msg.data), chatId, now, onChunk, usage)
      } else if (msg.kind === "acp_ask_user_question") {
        // 自动回复 Agent 提问
        ws.send(JSON.stringify({
          type: "reply-question",
          data: JSON.stringify({ request_id: "xxx", answers_json: "", cancelled: false }),
        }))
      }
      break
    case "task-ended":
      onChunk({ choices: [{ delta: {}, finish_reason: "stop" }], usage })
      break
    case "task-error":
      onChunk({ choices: [{ delta: { content: `[Error] ${msg.data}` } }] })
      break
  }
}
```

## 5. ACP → SSE 映射

```typescript
private handleACPEvent(acp, chatId, now, onChunk, usage) {
  switch (acp.type) {
    case "agent_message_chunk":
      onChunk({ id: chatId, choices: [{ delta: { content: acp.text }, finish_reason: null }] })
      break
    case "agent_thought_chunk":
      onChunk({ id: chatId, choices: [{ delta: { content: `[Thinking] ${acp.text}` } }] })
      break
    case "tool_call":
      onChunk({ id: chatId, choices: [{ delta: { content: `[Tool: ${acp.tool_name}] ${acp.tool_input}` } }] })
      break
    case "usage_update":
      if (acp.input_tokens) usage.input_tokens += acp.input_tokens
      if (acp.output_tokens) usage.output_tokens += acp.output_tokens
      if (acp.total_tokens) usage.total_tokens += acp.total_tokens
      break
  }
}
```

## 6. Go 后端 VM 定义

```go
type CreateVirtualMachineReq struct {
    UserID  string    `json:"user_id"`
    HostID  string    `json:"host_id"`
    ImageURL string   `json:"image_url"`
    TaskID  uuid.UUID `json:"task_id"`
    LLM     LLMProviderReq `json:"llm"`
    Cores   string    `json:"cores"`
    Memory  uint64    `json:"memory"`
}
```

## 7. 超时保护

```typescript
const TASK_TIMEOUT_MS = parseInt(process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000", 10)

setTimeout(() => {
  if (!resolved) { ws.close(); resolve() }
}, TASK_TIMEOUT_MS)  // 默认 1 小时后优雅超时
```

---

## 相关章节

- [VM 生命周期](02-vm-lifecycle.md) — VM 启动/停止流程
- [Task Stream WS](../04-websocket/01-task-stream.md) — WS 协议
- [ACP 事件参考](../04-websocket/06-acp-event-reference.md) — 事件类型
