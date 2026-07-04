> ⚠️ **此文件为原始分析档案** — 内容已被 docs/ 下结构化章节覆盖。详见 [docs/protocol/README.md](./README.md)。

# MonkeyCode 逆向分析总结报告

> **分析周期:** 2026-05-30 00:40 — 02:25 UTC+8
> **分析轮次:** 8 轮
> **状态:** 实现阶段完成，待测试验证

---

## 1. 项目概述

### 1.1 目标

逆向 MonkeyCode AI 编码平台的 AI 通信协议和登录认证协议，实现代理给 Codex 使用。

### 1.2 架构

```
Codex Client
    ↓ (OpenAI API)
Proxy (TypeScript/Express)
    ↓ (MonkeyCode API)
MonkeyCode Backend (Go)
    ↓ (TaskFlow API)
VM (Docker Container)
    ↓ (LLM API)
LLM Provider (OpenAI/Anthropic/DeepSeek)
```

---

## 2. 分析成果

### 2.1 协议文档 (13 份)

| 文档 | 完成度 | 关键内容 |
|------|--------|---------|
| `auth-protocol-complete.md` | 95% | 5 种登录方式、Session 机制 |
| `llm-protocol-complete.md` | 95% | 3 种接口类型、模型管理 |
| `websocket-protocol.md` | 90% | 3 个 WS 通道、ACP 事件 |
| `api-endpoints.md` | 95% | 100 个端点映射 |
| `taskflow-vm-analysis.md` | 85% | VM 生命周期 |
| `architecture.md` | 90% | 完整数据流 |
| `multi-turn-design.md` | 90% | 多轮对话设计 |
| `analysis-round-01.md` | - | 全面状态评估 |
| `analysis-round-02.md` | - | P0 深度分析 |
| `analysis-round-03.md` | - | 代码修复实施 |
| `analysis-round-04.md` | - | 多轮对话设计 |
| `analysis-round-05.md` | - | Phase 1 实施 |
| `analysis-round-06.md` | - | 代码审查 |
| `analysis-round-07.md` | - | 测试脚本 |
| `analysis-round-08.md` | - | 测试分析 |

### 2.2 代理实现 (9 个文件, ~2920 行)

| 文件 | 行数 | 功能 | 状态 |
|------|------|------|------|
| `auth.ts` | 230 | Cookie-based Session 管理 | ✅ |
| `models.ts` | 98 | 模型发现与缓存 | ✅ |
| `task-runner.ts` | 470 | 任务创建、WS 流式输出 | ✅ |
| `api-routes.ts` | 530 | OpenAI 兼容 API 路由 | ✅ |
| `account-pool.ts` | 286 | 多账号号池管理 | ✅ |
| `admin-login.ts` | 425 | OAuth 登录自动化 | ✅ |
| `conversation-manager.ts` | 370 | 多轮对话管理器 | ✅ |
| `server.ts` | 330 | Express 服务器入口 | ✅ |
| `types.ts` | 180 | TypeScript 类型定义 | ✅ |
| **总计** | **2919** | - | **✅** |

### 2.3 测试脚本 (1 个)

| 文件 | 功能 | 状态 |
|------|------|------|
| `test-proxy.sh` | 自动化测试脚本 | ✅ |

---

## 3. 关键发现与修复

### 3.1 认证协议

| 发现 | 状态 | 说明 |
|------|------|------|
| Cookie-based Session | ✅ | `monkeycode_ai_session` / `monkeycode_ai_team_session` |
| 密码传输 | ✅ | 明文传输，bcrypt 验证 |
| 百智云 OAuth | ✅ | SCaptcha + SMS + OAuth 流程 |
| Session 过期 | ✅ | 30 天硬限制，不可刷新 |

### 3.2 LLM 通信协议

| 发现 | 状态 | 说明 |
|------|------|------|
| 3 种接口类型 | ✅ | `openai_chat`, `openai_responses`, `anthropic` |
| 任务驱动模型 | ✅ | 创建任务 → VM → Agent → LLM |
| 流式输出 | ✅ | WebSocket Task Stream |
| 多轮对话 | ✅ | 通过 `conversation_id` 复用任务 |

### 3.3 ACP 事件

| 事件类型 | 状态 | 处理方式 |
|----------|------|----------|
| `agent_message_chunk` | ✅ | 转换为 OpenAI 格式 |
| `agent_thought_chunk` | ✅ | 前缀 [Thinking] |
| `tool_call` | ✅ | 转换为 function_call |
| `tool_call_update` | ✅ | 流式更新参数 |
| `usage_update` | ✅ | 累积到最终响应 |
| `plan` | ✅ | 日志记录 |
| `available_commands_update` | ✅ | 日志记录 |

### 3.4 Bug 修复

| Bug | 状态 | 修复方式 |
|-----|------|----------|
| 非流式 usage=0 | ✅ | 累积 `chunk.usage` |
| tool_call_update 丢弃 | ✅ | 添加事件处理 |
| tool_call 参数非流式 | ✅ | 等待 update 事件 |
| task-ended 未关闭 tool_call | ✅ | 正确关闭工具调用 |

---

## 4. 架构决策

### 4.1 代理架构

**Architecture B (任务代理)** — 适用于所有场景

- **公开模型**: 必需（API Key 被剥离）
- **私有模型**: 可用（虽然 Architecture A 更快）
- **Codex**: 必需（需要 Agent 工具：bash, file edit, git）

### 4.2 多轮对话方案

**混合方案** — 兼容 OpenAI API + 低延迟

- **默认行为**: 无状态，每次创建新任务
- **扩展行为**: 支持 `conversation_id`，复用对话
- **实现复杂度**: 中等（~455 行代码）

### 4.3 auto-approve 机制

**不冲突** — `auto-approve` 和 `reply-question` 互补

- `auto-approve`: 全局设置，跳过工具执行确认
- `reply-question`: 回复 Agent 的特定问题
- 两者服务不同目的，可以共存

---

## 5. API 扩展

### 5.1 OpenAI Chat Completions API

**标准请求**：
```json
POST /v1/chat/completions
{
  "model": "monkeycode/OpenAI/gpt-4o",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": true
}
```

**扩展请求（多轮对话）**：
```json
POST /v1/chat/completions
{
  "model": "monkeycode/OpenAI/gpt-4o",
  "messages": [...],
  "conversation_id": "conv-xxx",
  "stream": true
}
```

**扩展响应**：
```
HTTP/1.1 200 OK
X-Conversation-Id: conv-xxx
```

### 5.2 OpenAI Responses API

**请求**：
```json
POST /v1/responses
{
  "model": "monkeycode/OpenAI/gpt-4o",
  "input": [{"role": "user", "content": "Hello"}],
  "stream": true
}
```

**响应**：
```
event: response.created
data: {"type":"response.created","response":{"id":"resp-xxx","status":"in_progress"},...}

event: response.output_text.delta
data: {"type":"response.output_text.delta","delta":{"text":"Hello"},...}

event: response.completed
data: {"type":"response.completed","response":{"status":"completed","usage":{...}},...}
```

---

## 6. 测试计划

### 6.1 测试覆盖范围

| 测试项 | 说明 | 预期结果 |
|--------|------|---------|
| 健康检查 | `GET /health` | 200 + `{"status":"ok"}` |
| 模型列表 | `GET /v1/models` | 200 + 模型数组 |
| Chat (非流式) | `POST /v1/chat/completions` | 200 + 完整响应 |
| Chat (流式) | `POST /v1/chat/completions` + stream | SSE 流 |
| Responses API | `POST /v1/responses` + stream | SSE 流 |
| 多轮对话 | 两轮对话测试 | conversation_id + 上下文保持 |
| 错误处理 | 无效模型、空消息 | 404、400 |

### 6.2 测试执行

```bash
# 启动代理
cd proxy
npm run dev

# 运行测试
./test-proxy.sh http://localhost:9090
```

---

## 7. 代码提交准备

### 7.1 待提交文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/conversation-manager.ts` | 新建 | 对话管理器 |
| `src/api-routes.ts` | 修改 | 支持 conversation_id |
| `src/server.ts` | 修改 | 初始化 ConversationManager |
| `src/task-runner.ts` | 修改 | ACP 事件处理 |
| `src/types.ts` | 修改 | 新增类型定义 |
| `test-proxy.sh` | 新建 | 测试脚本 |

### 7.2 提交信息

```
feat(proxy): add multi-turn conversation support and ACP event handling

- Add ConversationManager for managing conversation lifecycle
- Support conversation_id parameter for reusing tasks/VMs
- Handle tool_call_update, plan, and available_commands_update events
- Fix non-stream usage bug (accumulate chunk.usage)
- Add test script for verifying proxy functionality
- Update types.ts with conversation-related types
```

---

## 8. 下一步计划

### 8.1 短期 (1-2 天)

1. **运行测试脚本**: 验证所有功能
2. **修复测试失败**: 处理发现的问题
3. **提交代码**: 保存所有更改
4. **更新 README**: 添加使用说明

### 8.2 中期 (1-2 周)

1. **性能测试**: 测量响应时间
2. **稳定性测试**: 长时间运行
3. **并发测试**: 多客户端访问
4. **错误处理增强**: WS 断线重连

### 8.3 长期 (1-2 月)

1. **VM 预热池**: 预创建 VM
2. **负载均衡**: 多 VM 分配
3. **对话持久化**: Redis 存储
4. **监控告警**: 添加监控

---

## 9. 总结

### 9.1 已完成

- ✅ 完整的协议分析（认证、LLM、WebSocket）
- ✅ OpenAI 兼容代理实现
- ✅ 多轮对话支持（Phase 1）
- ✅ ACP 事件处理
- ✅ 号池管理
- ✅ OAuth 登录自动化
- ✅ 测试脚本

### 9.2 待完成

- ⏳ 线上实测验证
- ⏳ 性能测试和优化
- ⏳ 错误处理增强
- ⏳ 对话持久化

### 9.3 代码质量

- ✅ TypeScript 编译通过
- ✅ 类型定义完整
- ✅ 错误处理基本完整
- ✅ 日志记录详细
- ⏳ 单元测试待添加

---

## 10. 附录

### 10.1 文件索引

**代理源码**：
- `proxy/src/auth.ts` — 认证管理
- `proxy/src/models.ts` — 模型管理
- `proxy/src/task-runner.ts` — 任务执行
- `proxy/src/api-routes.ts` — API 路由
- `proxy/src/account-pool.ts` — 号池管理
- `proxy/src/admin-login.ts` — OAuth 登录
- `proxy/src/conversation-manager.ts` — 对话管理
- `proxy/src/server.ts` — 服务器入口
- `proxy/src/types.ts` — 类型定义

**测试脚本**：
- `proxy/test-proxy.sh` — 自动化测试

**协议文档**：
- `docs/protocol/` — 所有协议文档

### 10.2 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `MONKEYCODE_SESSION_COOKIE` | 是 | Session Cookie |
| `MONKEYCODE_IMAGE_ID` | 是 | VM 镜像 ID |
| `MONKEYCODE_BASE_URL` | 否 | 后端地址 (默认: https://monkeycode-ai.com) |
| `PROXY_PORT` | 否 | 代理端口 (默认: 9090) |
| `MONKEYCODE_LOGIN_MODE` | 否 | 登录模式 (默认: user) |

### 10.3 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/v1/models` | 模型列表 |
| POST | `/v1/chat/completions` | Chat Completions API |
| POST | `/v1/responses` | Responses API |
| POST | `/admin/session` | 设置 Session Cookie |
| POST | `/admin/login/send-code` | 发送短信验证码 |
| POST | `/admin/login/verify` | 验证短信码 |
| POST | `/admin/login/callback` | OAuth 回调 |
| GET | `/admin/discover` | 自动发现 |
| POST | `/admin/refresh-models` | 刷新模型缓存 |
| GET | `/admin/pool/status` | 号池状态 |
| POST | `/admin/pool/refresh` | 刷新号池 |
