---
description: ACP 事件到 OpenAI SSE 格式的完整映射 — Chat Completions + Responses API 双模式
protocol_version: based on proxy/src/ TypeScript 实现
confidence: high
last_verified: 2026-06-27
---

# ACP → OpenAI 事件映射

## Chat Completions 模式

完整的 ACP → OpenAI Chat Completions SSE 映射表：

| ACP 事件 | OpenAI SSE 格式 | 完成度 |
|---------|----------------|--------|
| `task-started` | 忽略（不转换） | ✅ |
| `agent_message_chunk` | `delta.content` | ✅ |
| `agent_thought_chunk` | `delta.content` 带 `[Thinking]` 前缀 | ✅ |
| `tool_call` | `delta.content` 带 `[Tool: name]` 前缀 | ✅ |
| `tool_call_update` | 记录日志（当前不转发到 OpenAI 格式） | 🟡 |
| `usage_update` | 累积，放在最终 chunk 的 `usage` 字段 | ✅ |
| `plan` | 记录日志 | 🟡 |
| `available_commands_update` | 记录日志 | 🟡 |
| `task-ended` | `finish_reason: 'stop'` + 最终 delta | ✅ |

### 源码实现 (task-runner.ts)

```typescript
// proxy/src/task-runner.ts — ACP → Chat Completions SSE 转换
function acpToOpenAISSE(event: ACPSessionUpdate, taskId: string): string | null {
    const base = {
        id: `chatcmpl-${taskId}`,
        object: 'chat.completion.chunk' as const,
        created: Math.floor(Date.now() / 1000),
        model: this.model,
    };

    switch (event.type) {
        case 'agent_message_chunk':
            return formatSSE({
                ...base,
                choices: [{
                    index: 0,
                    delta: { content: event.text || event.content },
                    finish_reason: null,
                }],
            });

        case 'agent_thought_chunk':
            return formatSSE({
                ...base,
                choices: [{
                    index: 0,
                    delta: { content: `[Thinking] ${event.text}` },
                    finish_reason: null,
                }],
            });

        case 'tool_call':
            return formatSSE({
                ...base,
                choices: [{
                    index: 0,
                    delta: { content: `[Tool: ${event.tool_name}] ${event.tool_input || ''}` },
                    finish_reason: null,
                }],
            });

        case 'usage_update':
            return formatSSE({
                ...base,
                choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
                usage: {
                    prompt_tokens: event.input_tokens || 0,
                    completion_tokens: event.output_tokens || 0,
                    total_tokens: event.total_tokens || 0,
                },
            });

        case 'task-ended':
            return formatSSE({
                ...base,
                choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
            });

        case 'task-error':
            return formatSSE({
                ...base,
                choices: [{ index: 0, delta: {}, finish_reason: 'error' }],
            });

        default:
            return null; // 忽略其他事件
    }
}

function formatSSE(data: object): string {
    return `data: ${JSON.stringify(data)}\n\n`;
}
```

### 非流式响应

对于非流式请求，代理在后台累积所有 ACP 事件，然后一次性构造 OpenAI 格式的完整响应：

```typescript
// api-routes.ts — 非流式模式的事件累积
async function handleNonStreaming(req, res) {
    const chunks: string[] = [];
    let totalUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
    
    for await (const event of taskRunner.streamEvents(req.body)) {
        if (event.type === 'agent_message_chunk') {
            chunks.push(event.text || event.content || '');
        } else if (event.type === 'usage_update') {
            totalUsage = {
                prompt_tokens: event.input_tokens || 0,
                completion_tokens: event.output_tokens || 0,
                total_tokens: event.total_tokens || 0,
            };
        }
    }
    
    // 组装 OpenAI 格式响应
    res.json({
        id: `chatcmpl-${taskId}`,
        object: 'chat.completion',
        created: Math.floor(Date.now() / 1000),
        model: req.body.model,
        choices: [{
            index: 0,
            message: {
                role: 'assistant',
                content: chunks.join(''),
            },
            finish_reason: 'stop',
        }],
        usage: totalUsage,
    });
}
```

## Responses API 模式

Reapon API（Codex 原生 API）的 ACP → OpenAI SSE 映射：

| ACP 事件 | OpenAI Responses SSE 事件 |
|---------|--------------------------|
| `task-started` | `response.created` |
| `agent_message_chunk` | `response.output_text.delta` |
| `agent_thought_chunk` | `response.output_text.delta`（`[Thinking]` 前缀） |
| `tool_call` | `response.output_item.added` (type: function_call) |
| `tool_call_update` | `response.function_call_arguments.delta`（推测） |
| `usage_update` | 累积 → `response.completed` usage |
| `task-ended` | `response.completed` |
| `task-error` | `response.completed` {status: "failed"} |

### 完整事件序列

**纯文本响应:**
```
response.created → response.in_progress
→ response.output_item.added → response.content_part.added
→ response.output_text.delta × N
→ response.output_text.done → response.content_part.done
→ response.output_item.done → response.completed (含 usage)
```

**工具调用:**
```
response.output_item.added (type: "function_call", call_id, name)
→ response.function_call_arguments.delta × N
→ response.function_call_arguments.done (name, arguments)
→ response.output_item.done
```

**错误场景:**
```
response.created → response.in_progress
→ response.output_text.delta × N
→ response.completed {status: "failed"}
```

### Responses 模式源码

```typescript
// api-routes.ts — Responses API ACP 转换
function acpToResponsesSSE(event: ACPSessionUpdate): string {
    const base = {
        id: `resp_${taskId}`,
        type: 'response.output_text.delta',
    };
    
    switch (event.type) {
        case 'task-started':
            return formatSSE({ event: 'response.created', data: { id: base.id } });
            
        case 'agent_message_chunk':
            return formatSSE({
                event: 'response.output_text.delta',
                data: {
                    id: base.id,
                    delta: event.text || event.content || '',
                },
            });
            
        case 'tool_call':
            return [
                formatSSE({
                    event: 'response.output_item.added',
                    data: {
                        id: base.id,
                        item: {
                            id: `fcall_${Date.now()}`,
                            type: 'function_call',
                            name: event.tool_name,
                            arguments: '',
                        },
                    },
                }),
            ].join('');
        
        case 'task-ended':
            return formatSSE({
                event: 'response.completed',
                data: {
                    id: base.id,
                    status: 'completed',
                    usage: { /* 累积的 tokens */ },
                },
            });
    }
}
```

## 代理与直接 MonkeyCode WebSocket 响应对比

| 维度 | MonkeyCode 原生 WS 响应 | 代理转换后 OpenAI 格式 |
|------|------------------------|----------------------|
| 事件类型 | ACP 事件（agent_message_chunk 等） | OpenAI SSE（delta.content 等） |
| 工具调用 | `tool_call` 独立事件 | `[Tool: name]` 文本标记（Chat）/ `function_call` event（Responses）|
| 思考过程 | `agent_thought_chunk` 独立事件 | `[Thinking]` 文本标记 |
| Token 用量 | `usage_update` 多次推送 | 最终 chunk 的 `usage` 字段（累积）|
| 流格式 | 原始 WebSocket 帧 | SSE（`data: {...}\n\n`）|

---

## 附录：逆向分析代码示例

### 附录 A: Chat Completions SSE 输出示例
```json
// ACP "agent_message_chunk" → OpenAI SSE "delta.content"
data: {"id":"chatcmpl-task-xxx","object":"chat.completion.chunk",
       "choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-task-xxx","object":"chat.completion.chunk",
       "choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}

// ACP "agent_thought_chunk" → OpenAI SSE with [Thinking] prefix
data: {"id":"chatcmpl-task-xxx","object":"chat.completion.chunk",
       "choices":[{"index":0,"delta":{"content":"[Thinking] Let me analyze"},"finish_reason":null}]}

// ACP "usage_update" → 最终 chunk with usage
data: {"id":"chatcmpl-task-xxx","object":"chat.completion.chunk",
       "choices":[{"index":0,"delta":{},"finish_reason":"stop"}],
       "usage":{"prompt_tokens":150,"completion_tokens":200,"total_tokens":350}}

// 流结束
data: [DONE]
```

### 附录 B: Responses API SSE 输出示例
```json
// ACP "task-started" → response.created
event: response.created
data: {"id":"resp_task-xxx","type":"response.created"}

// ACP "agent_message_chunk" → response.output_text.delta
event: response.output_text.delta
data: {"id":"resp_task-xxx","delta":"Hello"}

// ACP "tool_call" → response.output_item.added (function_call)
event: response.output_item.added
data: {"id":"resp_task-xxx",
       "item":{"id":"fcall_1715299200","type":"function_call",
               "name":"bash","arguments":""}}

// ACP "task-ended" → response.completed
event: response.completed
data: {"id":"resp_task-xxx","status":"completed",
       "usage":{"input_tokens":150,"output_tokens":200,"total_tokens":350}}
```

---

## 相关章节

- [ACP 事件类型参考](../04-websocket/06-acp-event-reference.md) — 事件的详细格式
- [代理架构](01-architecture.md) — 事件转换在代理中的实现位置
- [Task Stream WebSocket](../04-websocket/01-task-stream.md) — ACP 事件传输通道