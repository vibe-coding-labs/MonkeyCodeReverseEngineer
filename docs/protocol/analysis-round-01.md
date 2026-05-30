# 逆向分析轮次 01 — 全面状态评估

> **时间:** 2026-05-30 00:40 UTC+8
> **分析范围:** 项目全貌、协议完整性、代理实现差距

---

## 1. 项目当前状态总览

### 已完成的协议文档 (6 份)

| 文档 | 完成度 | 关键内容 |
|------|--------|---------|
| `auth-protocol-complete.md` | 95% | 5 种登录方式、Session 机制、验证码系统 |
| `llm-protocol-complete.md` | 90% | 3 种接口类型、模型管理、任务 API |
| `websocket-protocol.md` | 85% | 3 个 WS 通道、ACP 事件格式 |
| `api-endpoints.md` | 95% | 100 个端点映射 |
| `taskflow-vm-analysis.md` | 80% | VM 生命周期、Docker 容器架构 |
| `architecture.md` | 90% | 完整数据流和组件关系 |

### 已实现的代理 (TypeScript/Express)

| 文件 | 行数 | 功能 | 状态 |
|------|------|------|------|
| `auth.ts` | 230 | Cookie-based Session 管理 | ✅ 完整 |
| `models.ts` | 98 | 模型发现与缓存 | ✅ 完整 |
| `task-runner.ts` | 438 | 任务创建、WS 流式输出 | ✅ 完整 |
| `api-routes.ts` | 400 | OpenAI 兼容 API 路由 | ✅ 完整 |
| `account-pool.ts` | 286 | 多账号号池管理 | ✅ 完整 |
| `admin-login.ts` | 425 | OAuth 登录自动化 | ✅ 完整 |
| `server.ts` | 322 | Express 服务器入口 | ✅ 完整 |
| `types.ts` | 163 | TypeScript 类型定义 | ✅ 完整 |

**总计:** ~2362 行 TypeScript，已编译到 `proxy/dist/`

---

## 2. 协议分析差距 (Gap Analysis)

### 2.1 认证协议 — 已知 95%

| 项目 | 状态 | 说明 |
|------|------|------|
| Cookie-based Session | ✅ 已验证 | `monkeycode_ai_session` / `monkeycode_ai_team_session` |
| 密码登录 | ✅ 已验证 | 明文传输，bcrypt 验证 |
| 百智云 OAuth | ✅ 已实现 | SCaptcha → SMS → OAuth → 回调 |
| Session 过期 | ⚠️ 推测 | 文档说 30 天，未实测 |
| 验证码绕过 | ❌ 未分析 | go-cap 验证码是否有已知漏洞 |
| 多账号风控 | ❌ 未测试 | 大量账号同时登录是否触发风控 |

### 2.2 LLM 通信协议 — 已知 90%

| 项目 | 状态 | 说明 |
|------|------|------|
| 3 种接口类型 | ✅ 已验证 | `openai_chat`, `openai_responses`, `anthropic` |
| 模型管理 API | ✅ 已验证 | CRUD + 健康检查 |
| 任务创建 API | ✅ 已验证 | `POST /api/v1/users/tasks` |
| 流式输出 | ✅ 已验证 | WebSocket Task Stream |
| `system_prompt` 传递 | ✅ 已确认 | CreateTaskReq 字段，存 Redis |
| 模型切换 | ⚠️ 部分 | `switch_model` via Control WS，未实测 |
| `cli_name` 映射 | ✅ 已实现 | openai_responses→codex, anthropic→claude |

### 2.3 WebSocket 协议 — 已知 85%

| 项目 | 状态 | 说明 |
|------|------|------|
| Task Stream WS | ✅ 已验证 | `mode=new` 和 `mode=attach` |
| Task Control WS | ⚠️ 部分 | RPC 调用格式已知，未实测 |
| TaskLive WS | ⚠️ 推测 | 内部协议，基于后端源码推断 |
| 心跳机制 | ✅ 已实现 | 10s ping/pong |
| 重连机制 | ⚠️ 未实测 | 指数退避 500ms→8s，去重 |
| 历史回放 | ⚠️ 未实测 | cursor 分页，limit=2~10 |

### 2.4 ACP 事件 — 已知 82%

| 事件类型 | 状态 | 代理处理 | 说明 |
|----------|------|----------|------|
| `agent_message_chunk` | ✅ | ✅ 处理 | text/content 字段 |
| `agent_thought_chunk` | ✅ | ✅ 处理 | 前缀 [Thinking] |
| `tool_call` | ✅ | ✅ 处理 | tool_name, tool_input |
| `tool_call_update` | ❌ | ❌ 丢弃 | 字段未知，代理静默丢弃 |
| `usage_update` | ✅ | ✅ 处理 | 累积到最终 chunk |
| `plan` | ⚠️ | ❌ 未处理 | 含步骤状态，格式未文档化 |
| `available_commands_update` | ⚠️ | ❌ 未处理 | 格式未文档化 |
| `session_update` | ⚠️ | ❌ 未处理 | 独立 WS 消息类型，非 ACP |

### 2.5 代理实现差距

| 差距 | 严重度 | 说明 |
|------|--------|------|
| `tool_call_update` 丢弃 | 低 | 可能丢失工具执行进度 |
| `plan` 事件未处理 | 低 | 可能丢失执行计划信息 |
| `available_commands_update` 未处理 | 低 | 可能丢失可用命令信息 |
| `session_update` 未处理 | 低 | 独立 WS 消息，不影响主流程 |
| 双重回复风险 | 中 | `auto-approve` + `acp_ask_user_question` 自动回复可能冲突 |
| 多轮对话未实现 | 高 | 代理不保持对话上下文 |
| `tool_call` 流式参数 | 中 | Responses API 一次性发送所有参数，非流式 |

---

## 3. 代理架构分析

### 3.1 请求流

```
Codex Client
  │ POST /v1/responses (OpenAI Responses API)
  ▼
Proxy (api-routes.ts)
  │ 1. 解析 input → prompt + systemPrompt
  │ 2. 解析 model → resolveModel()
  │ 3. 获取账号 (acquireWs/acquireHttp)
  │ 4. 创建任务 (taskRunner.createTask)
  │    POST /api/v1/users/tasks
  │ 5. 流式接收 (taskRunner.streamTaskRaw)
  │    WS /api/v1/users/tasks/stream?id=X&mode=new
  │    → send auto-approve
  │    → send user-input
  │    → receive ACP events
  │ 6. 转换为 Responses API SSE 格式
  ▼
Codex Client ← SSE stream
```

### 3.2 关键映射

| ACP 事件 | Responses API 事件 |
|----------|-------------------|
| `task-started` | `response.created` |
| `agent_message_chunk` | `response.output_text.delta` |
| `agent_thought_chunk` | `response.output_text.delta` (前缀 [Thinking]) |
| `tool_call` | `response.output_item.added` (function_call) |
| `usage_update` | 累积 → `response.completed` |
| `task-ended` | `response.completed` |

### 3.3 已知 Bug

1. **双重回复**: `task-runner.ts:133` 发送 `auto-approve`，同时 `task-runner.ts:209-226` 自动回复 `acp_ask_user_question`。如果 `auto-approve` 已经让 Agent 跳过确认，自动回复可能发送多余消息。

2. **tool_call 参数非流式**: `api-routes.ts:194-203` 在收到 `tool_call` 时一次性发送 `function_call_arguments.delta` 和 `function_call_arguments.done`，而不是等待 `tool_call_update` 流式更新。

3. **非流式响应无 usage**: `api-routes.ts:380-397` 的 `handleNonStreamResponse` 返回 `usage: {0, 0, 0}`，没有从 `usage_update` 事件累积。

---

## 4. 下轮分析重点

### 优先级 P0 (影响 Codex 兼容性)

1. **验证 `auto-approve` 行为**: 确认是否自动跳过 `acp_ask_user_question`
2. **测试 `tool_call_update` 字段**: 通过实际任务触发工具调用，观察完整事件流
3. **多轮对话支持**: 分析 Conversation API 格式

### 优先级 P1 (提升代理质量)

4. **`plan` 事件格式**: 触发复杂任务，观察 plan 事件完整结构
5. **`available_commands_update` 格式**: 触发需要命令的任务
6. **Session 过期实测**: 验证 30 天过期假设

### 优先级 P2 (长期优化)

7. **重连机制**: 测试断线后 attach 模式的行为
8. **并发连接**: 测试多标签页场景
9. **风控分析**: 号池大规模使用的行为

---

## 5. 代码变更建议 (待实施)

### 5.1 修复双重回复 (P0)

```typescript
// task-runner.ts:133 — 只在需要时发送 auto-approve
// 方案 A: 移除 auto-approve，只用 acp_ask_user_question 自动回复
// 方案 B: 移除 acp_ask_user_question 自动回复，只用 auto-approve
// 建议: 方案 B (auto-approve 是官方机制)
```

### 5.2 修复非流式 usage (P1)

```typescript
// api-routes.ts:380-397 — 在 streamTask 回调中累积 usage
let accumulatedUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }
// 在 handleStreamMessage 的 usage_update 中累积
```

### 5.3 支持 tool_call_update (P1)

```typescript
// api-routes.ts — 添加 tool_call_update 处理
// 将 tool_call_update 的参数增量发送到 response.function_call_arguments.delta
```

---

## 6. 相关文件索引

| 文件 | 用途 |
|------|------|
| `proxy/src/api-routes.ts` | OpenAI 兼容 API 路由 |
| `proxy/src/task-runner.ts` | 任务创建与 WS 流式输出 |
| `proxy/src/account-pool.ts` | 多账号号池管理 |
| `proxy/src/admin-login.ts` | OAuth 登录自动化 |
| `docs/protocol/auth-protocol-complete.md` | 认证协议完整文档 |
| `docs/protocol/llm-protocol-complete.md` | LLM 协议完整文档 |
| `docs/protocol/websocket-protocol.md` | WebSocket 协议详解 |
