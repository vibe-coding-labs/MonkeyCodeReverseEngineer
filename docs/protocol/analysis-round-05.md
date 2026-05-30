# 逆向分析轮次 05 — Phase 1 多轮对话实施

> **时间:** 2026-05-30 01:40 UTC+8
> **聚焦:** 实施 Phase 1 多轮对话支持

---

## 1. 实施的功能

### 1.1 ConversationManager 类 ✅

**文件**: `proxy/src/conversation-manager.ts` (新建)

**功能**:
- 管理对话生命周期
- 连接到任务的 WebSocket
- 发送用户输入
- 处理流式消息
- 自动清理过期对话

**核心方法**:
```typescript
class ConversationManager {
  create(taskId, model, auth, messages): Conversation
  get(id): Conversation | undefined
  delete(id): boolean
  connectToTask(conversation, onChunk): Promise<void>
  sendUserInput(conversation, content): void
  destroy(): void
}
```

### 1.2 类型定义更新 ✅

**文件**: `proxy/src/types.ts`

**新增类型**:
```typescript
export interface OpenAIChatCompletionRequest {
  // ... 现有字段 ...
  conversation_id?: string // 扩展字段：支持多轮对话
}

export interface Conversation {
  id: string
  taskId: string
  model: MonkeyCodeModel
  auth: AuthManager
  ws: WebSocket | null
  messages: OpenAIMessage[]
  lastUsedAt: number
  createdAt: number
}
```

### 1.3 API 路由更新 ✅

**文件**: `proxy/src/api-routes.ts`

**新增功能**:
- 支持 `conversation_id` 参数
- 复用对话：发送最后一条用户消息
- 创建新对话：返回 `X-Conversation-Id` header

**API 扩展**:
```json
// 继续对话
POST /v1/chat/completions
{
  "model": "monkeycode/...",
  "messages": [...],
  "conversation_id": "conv-xxx"
}

// 响应包含 conversation_id
HTTP/1.1 200 OK
X-Conversation-Id: conv-xxx
```

### 1.4 服务器更新 ✅

**文件**: `proxy/src/server.ts`

**新增功能**:
- 初始化 ConversationManager
- 传递给 API 路由器

---

## 2. 编译验证

```
$ npm run build
> tsc
✅ 编译成功，无错误
```

---

## 3. 代码变更统计

| 文件 | 状态 | 新增行 | 说明 |
|------|------|--------|------|
| `conversation-manager.ts` | 新建 | +350 | 对话管理器 |
| `types.ts` | 修改 | +15 | 新增类型定义 |
| `api-routes.ts` | 修改 | +80 | 支持 conversation_id |
| `server.ts` | 修改 | +10 | 初始化 ConversationManager |
| **总计** | - | +455 | Phase 1 完成 |

---

## 4. 使用示例

### 4.1 新对话

```bash
# 创建新对话
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [
      {"role": "user", "content": "Hello, what is Python?"}
    ],
    "stream": true
  }'

# 响应包含 conversation_id
# X-Conversation-Id: conv-1715299200-abc123
```

### 4.2 继续对话

```bash
# 继续对话
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [
      {"role": "user", "content": "Hello, what is Python?"},
      {"role": "assistant", "content": "Python is a programming language..."},
      {"role": "user", "content": "Can you give me an example?"}
    ],
    "conversation_id": "conv-1715299200-abc123",
    "stream": true
  }'
```

---

## 5. 下轮分析重点

### 优先级 P0 (影响 Codex 兼容性)

1. **测试多轮对话**: 验证 Agent 上下文保持
2. **性能测试**: 测量 VM 复用的延迟改善
3. **错误处理**: 处理 WS 连接断开和 VM 故障

### 优先级 P1 (提升代理质量)

4. **对话持久化**: 实现对话列表和历史
5. **并发测试**: 测试多客户端同时访问
6. **对话迁移**: VM 故障时迁移对话

### 优先级 P2 (长期优化)

7. **VM 预热池**: 预创建 VM 减少延迟
8. **负载均衡**: 在多个 VM 之间分配对话
9. **对话恢复**: 断线后自动重连

---

## 6. 相关文件索引

| 文件 | 用途 |
|------|------|
| `proxy/src/conversation-manager.ts` | 对话管理器 (新建) |
| `proxy/src/types.ts` | 类型定义 (已修改) |
| `proxy/src/api-routes.ts` | API 路由 (已修改) |
| `proxy/src/server.ts` | 服务器入口 (已修改) |
| `docs/protocol/multi-turn-design.md` | 多轮对话设计文档 |
