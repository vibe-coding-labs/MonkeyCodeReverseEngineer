# 逆向分析轮次 04 — 多轮对话设计

> **时间:** 2026-05-30 01:25 UTC+8
> **聚焦:** 多轮对话支持设计

---

## 1. 关键发现

### 1.1 MonkeyCode 的多轮机制

MonkeyCode 通过 Task Stream WS 支持多轮对话：
1. 创建任务并连接 WS（`mode=new`）
2. 发送 `user-input` 消息
3. 接收 Agent 输出
4. **再次发送 `user-input` 消息**（同一 WS 连接）
5. 接收 Agent 输出（Agent 保持上下文）

**关键**：同一任务/VM 可以处理多个 `user-input` 消息，Agent 保持对话上下文。

### 1.2 Conversation API 的作用

Conversation API 是**前端 UI 层**的抽象：
- 管理对话列表和消息历史
- 与任务（Task）关联
- 提供持久化存储

**对代理的影响**：Conversation API 是可选的，代理可以直接使用 Task Stream WS 实现多轮对话。

### 1.3 当前代理的限制

当前代理是**无状态的**：
- 每个请求创建新任务（新 VM）
- 无法保持对话上下文
- 资源消耗大（每个请求一个 VM）

---

## 2. 设计方案

### 2.1 方案 A: 客户端管理多轮（简单）

- 客户端发送完整对话历史
- 代理每次都创建新任务
- 优点：简单，兼容 OpenAI API
- 缺点：延迟高，无法利用 Agent 真实多轮能力

### 2.2 方案 B: 代理管理多轮（复杂）

- 代理维护对话状态
- 复用任务/VM
- 优点：延迟低，利用 Agent 真实多轮能力
- 缺点：实现复杂，需要状态管理

### 2.3 方案 C: 混合方案（推荐）

**规则**：
1. 如果客户端发送 `conversation_id`，复用对话
2. 如果客户端发送完整消息历史（无 `conversation_id`），创建新任务
3. 对话超时后自动清理

**优点**：
- 兼容 OpenAI API（默认行为）
- 支持低延迟多轮对话（扩展行为）
- 实现简单（~200 行代码）

---

## 3. 实现细节

### 3.1 核心组件

1. **ConversationManager**: 管理对话生命周期
2. **TaskConnection**: 封装 WS 连接和消息处理
3. **API 路由更新**: 支持 `conversation_id` 参数

### 3.2 API 扩展

```json
// 新对话（标准 OpenAI API）
POST /v1/chat/completions
{
  "model": "monkeycode/...",
  "messages": [...]
}

// 继续对话（扩展 API）
POST /v1/chat/completions
{
  "model": "monkeycode/...",
  "messages": [...],
  "conversation_id": "conv-xxx"
}
```

### 3.3 响应扩展

```json
// 响应包含 conversation_id
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "conversation_id": "conv-xxx",  // 新增字段
  "choices": [...],
  "usage": {...}
}
```

---

## 4. 实施计划

### Phase 1: 基础多轮支持（P1）

1. 实现 `ConversationManager` 类
2. 实现 `TaskConnection` 类
3. 更新 API 路由支持 `conversation_id`
4. 添加对话超时清理

**工作量**：~200 行代码

### Phase 2: 高级功能（P2）

1. 对话持久化（Redis/数据库）
2. 对话列表 API
3. 对话消息历史 API

**工作量**：~300 行代码

---

## 5. 下轮分析重点

### 优先级 P0 (影响 Codex 兼容性)

1. **实施 Phase 1**: 实现基础多轮支持
2. **测试多轮对话**: 验证 Agent 上下文保持
3. **性能测试**: 测量 VM 复用的延迟改善

### 优先级 P1 (提升代理质量)

4. **对话持久化**: 实现对话列表和历史
5. **错误处理**: 处理 WS 连接断开和 VM 故障
6. **并发测试**: 测试多客户端同时访问

### 优先级 P2 (长期优化)

7. **VM 预热池**: 预创建 VM 减少延迟
8. **负载均衡**: 在多个 VM 之间分配对话
9. **对话迁移**: VM 故障时迁移对话

---

## 6. 产出文件

- `docs/protocol/multi-turn-design.md` — 多轮对话设计文档
- `docs/protocol/analysis-round-04.md` — 本分析报告

---

## 7. 相关文件索引

| 文件 | 用途 |
|------|------|
| `proxy/src/task-runner.ts` | 任务创建与 WS 流式输出 |
| `proxy/src/api-routes.ts` | OpenAI 兼容 API 路由 |
| `docs/protocol/websocket-protocol.md` | WebSocket 协议详解 |
| `docs/protocol/llm-protocol-complete.md` | LLM 协议完整文档 |
