# MonkeyCode AI 能力逆向工程分析计划

> **类型:** Research (持续性逆向分析)
> **目标:** 完整逆向 MonkeyCode 的 AI 通信协议和认证协议，实现代理给 Codex 使用
> **分析日期:** 2026-05-28
> **执行频率:** 每 5 分钟一次持续性分析

---

## Type Detection

**Plan Type:** Research
**Scope:** Large (跨多个子系统：认证、LLM 通信、WebSocket 流式协议、VM 管理)
**Risk:** Medium (涉及线上服务逆向，需避免触发风控)
**Detection Reason:** 用户要求"逆向分析"AI 通信和认证协议，核心是信息收集和协议理解

---

## 当前逆向成果总览

### 已完成的逆向分析

| 模块 | 文档 | 完成度 | 关键发现 |
|------|------|--------|---------|
| **认证协议** | `auth-protocol-complete.md` | 95% | Cookie-based Session，5 种登录方式，验证码系统 |
| **LLM 协议** | `llm-protocol-complete.md` | 90% | 3 种接口类型，11 个 Provider，任务驱动模型 |
| **WebSocket 协议** | `websocket-protocol.md` | 85% | 3 个 WS 通道，ACP 事件格式，流式传输 |
| **API 端点** | `api-endpoints.md` | 95% | 100 个端点映射，含认证要求 |
| **TaskFlow VM** | `taskflow-vm-analysis.md` | 80% | VM 生命周期，Docker 容器架构 |
| **架构总览** | `architecture.md` | 90% | 完整数据流和组件关系 |

### 已实现的代理

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| **认证模块** | `proxy/src/auth.ts` | ✅ 已实现 | Cookie-based Session 管理，支持用户/团队登录 |
| **号池模块** | `proxy/src/account-pool.ts` | ✅ 已实现 | 多账号轮转，健康检查，错误处理 |
| **模型管理** | `proxy/src/models.ts` | ✅ 已实现 | 模型列表获取，OpenAI 格式转换 |
| **任务执行** | `proxy/src/task-runner.ts` | ✅ 已实现 | 任务创建，WebSocket 流式输出 |
| **API 路由** | `proxy/src/api-routes.ts` | ✅ 已实现 | OpenAI 兼容的 `/v1/chat/completions` |

---

## 持续分析任务清单

### 任务 1: 认证协议深度分析 (每 5 分钟检查)

**当前状态:** 基本完成，需验证线上行为

**待验证项:**
1. Session Cookie 过期时间 — 文档说 30 天，需实测确认
2. 验证码绕过可能性 — go-cap 验证码是否有已知漏洞
3. OAuth 自动化可行性 — 百智云 OAuth 流程能否程序化完成
4. 多账号号池风控 — 大量账号同时登录是否触发风控

**分析命令:**
```bash
# 检查 Session 有效性
curl -b "monkeycode_ai_session=$SESSION" https://monkeycode-ai.com/api/v1/users/status

# 检查验证码端点
curl -X POST https://monkeycode-ai.com/api/v1/public/captcha/challenge

# 检查模型列表（验证认证状态）
curl -b "monkeycode_ai_session=$SESSION" https://monkeycode-ai.com/api/v1/users/models
```

### 任务 2: LLM 通信协议深度分析 (每 5 分钟检查)

**当前状态:** 协议已逆向，需验证实际调用链

**待验证项:**
1. 三种接口类型的实际请求/响应格式验证
2. 流式响应的完整事件序列
3. Token 使用量统计的准确性
4. 模型切换（switch_model）的实际行为

**分析命令:**
```bash
# 创建任务并观察完整事件流
curl -b "monkeycode_ai_session=$SESSION" -X POST https://monkeycode-ai.com/api/v1/users/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "content": "test",
    "host_id": "public_host",
    "image_id": "$IMAGE_ID",
    "model_id": "$MODEL_ID",
    "cli_name": "claude",
    "resource": {"core": 1, "memory": 1073741824, "life": 3600},
    "repo": {"repo_url": "", "branch": "master", "repo_filename": "", "zip_url": ""}
  }'
```

### 任务 3: WebSocket 协议深度分析 (每 5 分钟检查)

**当前状态:** 协议格式已逆向，需验证边缘情况

**待验证项:**
1. 重连机制的实际行为（断线后 attach 模式）
2. 历史回放的完整性（cursor 分页）
3. 并发连接的限制（多标签页）
4. 心跳超时的实际阈值

**分析命令:**
```bash
# 使用 wscat 测试 WebSocket 连接
wscat -c "wss://monkeycode-ai.com/api/v1/users/tasks/stream?id=$TASK_ID&mode=attach" \
  -H "Cookie: monkeycode_ai_session=$SESSION"
```

### 任务 4: 代理给 Codex 的适配分析 (每 5 分钟检查)

**当前状态:** 基础代理已实现，需优化 Codex 兼容性

**待优化项:**
1. OpenAI Responses API 格式支持（Codex 原生格式）
2. 流式响应的 token 使用量报告
3. 多轮对话的上下文保持
4. 工具调用（function calling）的转发

---

## 关键协议速查表

### 认证协议

| 项目 | 值 |
|------|-----|
| Session Cookie 名 | `monkeycode_ai_session` |
| 团队 Cookie 名 | `monkeycode_ai_team_session` |
| 登录端点（用户） | `POST /api/v1/users/password-login` |
| 登录端点（团队） | `POST /api/v1/teams/users/login` |
| 状态检查 | `GET /api/v1/users/status` |
| 验证码挑战 | `POST /api/v1/public/captcha/challenge` |
| 验证码兑换 | `POST /api/v1/public/captcha/redeem` |

### LLM 通信协议

| 项目 | 值 |
|------|-----|
| 模型列表 | `GET /api/v1/users/models` |
| 创建任务 | `POST /api/v1/users/tasks` |
| 任务流 WS | `GET /api/v1/users/tasks/stream?id={taskId}&mode=new\|attach` |
| 任务控制 WS | `GET /api/v1/users/tasks/control?id={taskId}` |
| 停止任务 | `PUT /api/v1/users/tasks/stop` |

### 三种接口类型

| 类型 | 端点 | SDK |
|------|------|-----|
| `openai_chat` | `{baseURL}/chat/completions` | sashabaranov/go-openai |
| `openai_responses` | `{baseURL}/responses` | 原生 HTTP |
| `anthropic` | `{baseURL}/v1/messages` | anthropics/anthropic-sdk-go |

### ACP 事件类型

| 事件 | 说明 | 关键字段 |
|------|------|---------|
| `agent_message_chunk` | Agent 输出文本 | `text` / `content` |
| `agent_thought_chunk` | Agent 推理文本 | `text` / `content` |
| `tool_call` | 工具调用开始 | `tool_name`, `tool_input` |
| `tool_call_update` | 工具调用状态更新 | - |
| `usage_update` | Token 用量 | `input_tokens`, `output_tokens`, `total_tokens` |
| `plan` | 执行计划 | 含步骤状态 |
| `available_commands_update` | 可用命令更新 | - |
| `task-ended` | 任务结束 | 无 |

### OpenAI Responses API 流式事件序列

**文本响应**:
```
response.created → response.in_progress → response.output_item.added
→ response.content_part.added → response.output_text.delta × N
→ response.output_text.done → response.content_part.done
→ response.output_item.done → response.completed (含 usage)
```

**工具调用**:
```
response.output_item.added (type: "function_call", call_id, name)
→ response.function_call_arguments.delta × N
→ response.function_call_arguments.done (name, arguments)
→ response.output_item.done
```

**关键**: Usage 只在 `response.completed` 中报告，无增量 usage 事件。

---

## 代理实现蓝图 (14 轮分析后最终版)

### 快速修复 (P0 — ~40 行, 可立即实施)

| # | 修复 | 文件:行 | 代码量 |
|---|------|---------|--------|
| 1 | 动态 `cli_name`: openai_responses→codex, anthropic→claude, default→opencode | task-runner.ts:57 | 10 行 |
| 2 | 累积 `usage_update`: input/output/total_tokens → 最终 chunk | task-runner.ts:259-261 | 8 行 |
| 3 | 提取 `system_prompt`: messages[0].role==="system" → CreateTaskReq.system_prompt | api-routes.ts:60-66 | 5 行 |
| 4 | 发送 `auto-approve`: WS 连接后发送 `{type:"auto-approve"}` | task-runner.ts:122-131 | 2 行 |
| 5 | 处理 `acp_ask_user_question`: 自动回复 `{type:"reply-question", data:{request_id, answers_json:"", cancelled:false}}` | task-runner.ts (新增) | 15 行 |

### Responses API 端点 (P0 — ~150 行, 主要工作量)

| # | 修复 | 文件 | 代码量 |
|---|------|------|--------|
| 6 | `/v1/responses` SSE 端点 | api-routes.ts (新增) | 80 行 |
| 7 | `streamTaskRaw` 方法: 暴露原始 ACP 事件 | task-runner.ts (新增) | 50 行 |
| 8 | `tool_call` → Responses API `function_call` 映射 | task-runner.ts (新增) | 20 行 |

### ACP → Responses API 事件映射表

```
task-started           → response.created
agent_message_chunk    → response.output_text.delta
agent_thought_chunk    → response.output_text.delta (前缀 [Thinking])
tool_call              → response.output_item.added (type:function_call)
tool_call_update       → response.function_call_arguments.delta (推断)
usage_update           → 累积 → response.completed {usage}
task-ended             → response.completed
task-error             → response.completed {status:"failed"}
```

### 架构决策

- **Architecture A (直接 LLM)**: 仅私有模型可用 (公开模型 API Key 被剥离)
- **Architecture B (任务代理)**: 公开模型必需, 完整 Agent 能力
- **混合方案**: A 用于私有模型 (快速), B 用于公开模型 (Agent 执行)
- **Codex 必须用 Architecture B** (需要 Agent 工具: bash, file edit, git)

### 已解决的差距

| # | 差距 | 状态 |
|---|------|------|
| P1-8 | types.ts 注释错误 "MD5 哈希" → "明文密码" | ✅ 已修复 |

### 剩余未知 (需线上测试验证)

1. `tool_call_update` 精确字段 (当前为推断)
2. `auto-approve` 是否自动回复 `acp_ask_user_question`
3. `system_prompt` 是否实际传递给 Agent
4. Conversation API 请求/响应格式

---

## 分析日志格式

每次分析记录格式：

```markdown
## [时间戳] 分析轮次 N

### 认证状态
- Session 有效: ✅/❌
- 剩余有效期: ~Xh
- 号池状态: X/Y active

### LLM 可用性
- 可用模型数: N
- 默认模型: xxx
- 接口类型分布: openai_chat(X), anthropic(Y), openai_responses(Z)

### 任务执行
- 测试任务 ID: xxx
- 创建耗时: Xms
- 首次输出延迟: Xms
- 事件序列: task-started → agent_message_chunk(N) → task-ended

### 发现/问题
- [问题描述]
- [解决方案]

### 下轮关注
- [待验证项]
```

---

## 风险提示

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 账号被封 | 中 | 号池轮转，控制请求频率 |
| Session 过期 | 低 | 自动刷新，健康检查 |
| 验证码更新 | 中 | 监控端点变化，及时适配 |
| API 格式变更 | 低 | 版本化协议文档，差异检测 |
| 风控触发 | 中 | 分散请求，模拟正常用户行为 |

---

## 相关文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 认证协议完整文档 | `docs/protocol/auth-protocol-complete.md` | 5 种登录方式详解 |
| LLM 协议完整文档 | `docs/protocol/llm-protocol-complete.md` | 3 种接口类型 + 任务 API |
| WebSocket 协议 | `docs/protocol/websocket-protocol.md` | 流式传输 + 控制通道 |
| API 端点映射 | `docs/protocol/api-endpoints.md` | 100 个端点完整列表 |
| TaskFlow VM 分析 | `docs/protocol/taskflow-vm-analysis.md` | VM 生命周期详解 |
| 架构总览 | `docs/protocol/architecture.md` | 系统架构 + 数据流 |
| 号池协议 | `docs/protocol/account-pool-protocol.md` | 多账号管理策略 |
