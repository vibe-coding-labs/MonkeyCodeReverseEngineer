---
description: 代理中的多轮对话设计 — 方案对比、ConversationManager 实现、mode=attach 复用
protocol_version: based on proxy/src/ TypeScript 实现
confidence: high
last_verified: 2026-06-27
---

# 多轮对话设计

## 问题分析

当前代理默认是**无状态**的：
- 每个请求创建新任务（新 VM）
- 发送单个 `user-input` 消息
- 接收流式输出
- 任务结束，关闭连接

这种模式的问题：
- **高延迟**: 每次请求都需要 ~10-30s 等待 VM 启动
- **无上下文**: Agent 每次都是全新的对话环境
- **资源浪费**: 每次请求都创建+销毁 VM

## MonkeyCode 的多轮机制

MonkeyCode 通过 Task Stream WS 支持多轮对话：

```
┌─────────────────────────────────────────────────────────┐
│                      多轮对话流程                         │
│                                                         │
│  客户端          代理               MonkeyCode 后端       │
│    │              │                     │                │
│    ├── chat req ──► POST /tasks ────────► 创建任务       │
│    │              │  WS /stream ────────► 连接 WS        │
│    │              │  {user-input} ──────► 发送第一轮输入  │
│    │              │  ←── ACP stream ──── 接收 Agent 输出 │
│    │←── SSE ──────┤                     │                │
│    │              │                     │                │
│    ├── chat req ──► {user-input} ──────► 第二轮输入      │
│    │              │  ←── ACP stream ──── Agent 保持上下文 │
│    │←── SSE ──────┤                     │                │
│    │              │                     │                │
│    ├── chat req ──► {user-input} ──────► 第三轮输入      │
│    │              │  ←── ACP stream ──── 继续            │
│    │←── SSE ──────┤                     │                │
└─────────────────────────────────────────────────────────┘
```

**关键**: 同一任务/VM 可以处理多个 `user-input` 消息，Agent 保持对话上下文。

## 设计方案对比

| 方案 | 复杂度 | 延迟 | 并发 | 状态管理 | 适用场景 |
|------|--------|------|------|---------|---------|
| A: 客户端管理 | 低 | 高（每次建 VM） | 好 | 无 | 一次性请求 |
| B: 代理管理 | 高 | 低（复用 VM） | 中 | 需要 | 多轮对话 |
| **推荐: 混合方案** | **中** | **中** | **中** | **需要** | 通用 |

## 混合方案 — 推荐

- **默认行为**: 无状态，每次创建新任务（向下兼容）
- **扩展行为**: 支持 `conversation_id`，复用对话
- 请求中添加 `conversation_id` 扩展字段即可实现多轮对话

### 请求/响应格式

```json
POST /v1/chat/completions
{
  "model": "monkeycode/OpenAI/gpt-4o",
  "messages": [
    {"role": "user", "content": "写一个 Python 脚本"}
  ],
  "conversation_id": "conv-xxx",   // 可选：复用对话（第一次可不传）
  "stream": true
}
```

```http
HTTP/1.1 200 OK
X-Conversation-Id: conv-xxx  // 新对话或复用的对话 ID
```

## ConversationManager 设计

ConversationManager（`proxy/src/conversation-manager.ts`，369 行）管理对话状态的完整实现：

```typescript
// proxy/src/conversation-manager.ts
interface Conversation {
    id: string              // 对话 ID（代理生成）
    taskId: string          // 关联的 MonkeyCode Task ID
    model: ModelInfo
    auth: AuthManager
    ws: WebSocket | null    // Task Stream WS 连接
    messages: OpenAIMessage[]
    lastUsedAt: number
    createdAt: number
}

class ConversationManager {
    private conversations: Map<string, Conversation> = new Map();
    private cleanupTimer: NodeJS.Timer;
    
    constructor() {
        // 每 5 分钟清理超时对话
        this.cleanupTimer = setInterval(() => this.cleanup(), 5 * 60 * 1000);
    }
    
    // 创建新对话
    async createConversation(
        model: ModelInfo, 
        auth: AuthManager
    ): Promise<Conversation> {
        // 1. 生成对话 ID
        const id = `conv_${uuidv4().slice(0, 8)}`;
        
        // 2. 创建 MonkeyCode 任务
        const taskRunner = new TaskRunner(auth);
        const taskId = await taskRunner.createTask(model.model_id);
        
        // 3. 连接 Task Stream WS (mode=new)
        const ws = await taskRunner.connectStream(taskId, 'new');
        
        const conv: Conversation = {
            id, taskId, model, auth,
            ws, messages: [],
            lastUsedAt: Date.now(),
            createdAt: Date.now(),
        };
        
        this.conversations.set(id, conv);
        return conv;
    }
    
    // 发送消息（支持多轮）
    async sendMessage(
        convId: string, 
        message: string
    ): Promise<AsyncIterable<ACPEvent>> {
        const conv = this.conversations.get(convId);
        if (!conv) throw new Error(`Conversation ${convId} not found`);
        
        conv.lastUsedAt = Date.now();
        conv.messages.push({ role: 'user', content: message });
        
        // 通过 WS 发送 user-input ACP 消息
        return this.sendUserInput(conv.ws, message);
    }
    
    // 30 分钟超时清理
    private cleanup() {
        const now = Date.now();
        const timeout = 30 * 60 * 1000; // 30 分钟
        
        for (const [id, conv] of this.conversations) {
            if (now - conv.lastUsedAt > timeout) {
                conv.ws?.close();
                this.conversations.delete(id);
                console.log(`[Conversation] ${id} expired (task=${conv.taskId})`);
            }
        }
    }
}
```

## mode=attach 复用

`mode=attach` 允许新连接复用到已有任务的 WS 流：

```typescript
// task-runner.ts — mode=attach 复用
async function attachToExistingTask(taskId: string): Promise<WebSocket> {
    const ws = new WebSocket(
        `${WS_BASE}/api/v1/users/tasks/stream?id=${taskId}&mode=attach`
    );
    
    // 复用已有连接后，后续的 user-input 仍在同一上下文处理
    // 但需要注意: 最新的 ACP 事件不会推送到新连接的客户端
    // 客户端需要自行管理上下文
    return ws;
}
```

```
客户端 A           代理
  │  POST /v1/chat/completions
  │  {model: "...", messages: [...], conversation_id: "conv-xxx"}
  │
  ├── 1. 查找 conv-xxx
  ├── 2. 找到现有 Task WS
  ├── 3. 发送 user-input (通过已有 WS)
  ├── 4. 接收 ACP stream
  └── 5. 转换为 OpenAI SSE → 客户端

关键: 代理的 WS 连接是 client ↔ task 的唯一通道
      但是代理同时只能为一个客户端保持连接
      （E2E 加密后无法透传，需要转 webhook 或重新架构）
```

## 限制

| 问题 | 说明 | 影响 |
|------|------|------|
| 单客户端 WS 绑定 | 代理与 MonkeyCode 的 WS 连接是 1:1 的 | 无法多客户端共享同任务 |
| E2E 加密场景 | 代理无法直接解析 WS 流的传输内容 | 需要 webhook 中转 |
| 超时机制 | 30 分钟空闲自动关闭 | 长时间对话可能超时 |
| 代理重启 | 内存中的对话状态丢失 | 需客户端重建 |

---

## 附录：逆向分析代码示例

### 附录 A: 多轮对话客户端使用 (Python)
```python
# 使用代理进行多轮对话
import requests
import json

proxy_url = "http://localhost:3000/v1/chat/completions"
conv_id = None

def chat(model: str, messages: list, conversation_id: str = None):
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    
    resp = requests.post(proxy_url, json=payload, stream=True)
    
    # 获取新对话 ID
    global conv_id
    if not conv_id:
        conv_id = resp.headers.get("X-Conversation-Id")
    
    # 读取 SSE 流
    for line in resp.iter_lines():
        if line.startswith(b"data: ") and line != b"data: [DONE]":
            chunk = json.loads(line[6:])
            if chunk["choices"][0]["delta"].get("content"):
                print(chunk["choices"][0]["delta"]["content"], end="")

# 第一轮
chat("monkeycode/OpenAI/gpt-4o", 
     [{"role": "user", "content": "写一个 Python 脚本读取 CSV"}])

# 第二轮（同一对话）
chat("monkeycode/OpenAI/gpt-4o",
     [{"role": "user", "content": "添加错误处理"}],
     conversation_id=conv_id)

# 第三轮
chat("monkeycode/OpenAI/gpt-4o",
     [{"role": "user", "content": "添加命令行参数支持"}],
     conversation_id=conv_id)
```

### 附录 B: Conversation 生命周期时序图
```
时间 →  
│
├── t0: conv-xxx create
│   ├── POST /api/v1/users/tasks → taskId: t-123
│   └── WS connect /stream?id=t-123&mode=new
│
├── t1: 第一轮
│   ├── WS ← {"type":"user-input","content":"hello"}
│   └── WS → ACP events (agent_message_chunk × N)
│   └── conv.lastUsedAt = t1
│
├── t2: 第二轮 (< 30min)
│   ├── WS ← {"type":"user-input","content":"add feature"}
│   └── WS → ACP events (tool_call × N, agent_message_chunk × N)
│   └── conv.lastUsedAt = t2
│
├── t3: 空闲 (30 分钟)
│
└── t4: cleanup
    ├── conv.lastUsedAt - now > 30min
    ├── WS close
    └── Map.delete(conv-xxx)
```

---

## 相关章节

- [代理架构](01-architecture.md) — 对话管理器在代理中的位置
- [Task Stream WebSocket](../04-websocket/01-task-stream.md) — WS 连接详情
- [ACP 事件参考](../04-websocket/06-acp-event-reference.md) — user-input 消息格式