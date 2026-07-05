# MonkeyCode 待分析缺口清单

> 生成时间: 2026-07-05
> 目标: 所有未搞清楚的点的优先级排序和跟踪

> ⏱️ **状态更新:** 2026-07-05 — 全部 30 项源码级分析维度已完成 ✅
> **剩余的 P1(8项) 需线上环境实测, P2(8项) 需闭源信息/抓包**

## 优先级 P0（源码级可分析，不需要线上环境）— ✅ 全部完成

| # | 缺口 | 现有线索 | 优先级 | 分析方式 |
|---|------|---------|--------|---------|
| 1 | Agent 如何构造 LLM 请求（prompt template） | task-runner.ts 中 prompt 构造 + cli_name 映射 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-agent-llm-request.md) |
| 2 | Agent 如何处理工具调用结果 | task-runner.ts handleStreamMessage ACP 事件处理 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-agent-tool-call.md) |
| 3 | Agent 对 ACP 事件的生成逻辑 | task-runner.ts handleACPEvent 的 7 种事件 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-acp-event-generation.md) |
| 4 | LLM 调用失败的重试策略 | account-pool.ts handleError 4 级错误隔离 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-retry-strategy.md) |
| 5 | `tool_call_update` 未映射到 OpenAI 格式 | task-runner.ts 仅 log 不转发 | P0 | 代码增强 | ✅ 已完成 → [报告](unknown-tool-call-mapping.md) |
| 6 | `plan` / `available_commands_update` 未映射 | task-runner.ts 仅 log | P0 | 代码增强 | ✅ 已完成 → [报告](unknown-plan-commands-mapping.md) |
| 7 | Agent 是否支持多模态输入 | model 配置 support_image 字段 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-multimodal-support.md) |

## 优先级 P1（需线上环境确认）

| # | 缺口 | 现有线索 | 优先级 | 分析方式 |
|---|------|---------|--------|---------|
| 8 | 生产环境 Nginx 限流 | 开源版无限流，Nginx 1.29.4 | P1 | curl 压测 |
| 9 | 免费模型限制 | is_free 字段，basic access_level | P1 | 线上实测 |
| 10 | 订阅具体价格 | SubscriptionResp 结构体已知 | P1 | 线上实测 |
| 11 | Token 余额系统 | balance 端点已废弃 | P1 | 线上实测 |
| 12 | 计费端点 | 推测 `/api/v1/users/balance` | P1 | 线上实测 |
| 13 | 免费额度 | 注册可能赠送额度 | P1 | 线上实测 |
| 14 | 超额处理 | 可能 HTTP 402 | P1 | 线上实测 |
| 15 | 模型级别 Token 价格 | 闭源 Stripe 配置 | P1 | 线上实测 |

## 优先级 P2（闭源或需抓包）

| # | 缺口 | 现有线索 | 优先级 | 分析方式 |
|---|------|---------|--------|---------|
| 16 | Agent 精确 NPM 包版本 | agentpluginrepo 表结构已知 | P2 | 需线上 |
| 17 | mcaiBuiltin 具体工具列表 | JSON-RPC 2.0 规范已知 | P2 | 需线上 |
| 18 | 每个工具的 inputSchema | 同上 | P2 | 需线上 |
| 19 | Agent 内部状态管理 | Agent 包闭源 | P2 | 需线上 |
| 20 | 账号被封检测 | 40003 错误码 | P2 | 线上实测 |
| 21 | 服务条款限制 | 代理使用违反 TOS | P2 | 需确认 |
| 22 | 明文密码安全隐患 | 环境变量存储 | P2 | 安全加固 |
| 23 | 无登录失败限流 | login() 无重试限制 | P2 | 安全加固 |
| 24 | 浏览器指纹伪装策略 | browser-headers.ts 4 域名专用生成器 | 新维度 | 源码分析 | ✅ 已完成 → [报告](unknown-browser-fingerprint.md) |
| 25 | Conversation Manager 清理与超时机制 | conversation-manager.ts 369 行 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-conversation-cleanup.md) |
| 26 | Express 中间件链与 SSE 流控制 | server.ts 331 行 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-express-sse.md) |
| 27 | 任务创建 resource 参数的实际影响 | task-runner.ts resource: {core, memory, life} | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-resource-params.md) |
| 28 | model_id 6 层解析回退的精确行为 | models.ts resolveModel() | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-model-resolution.md) |
| 29 | admin-login.ts OAuth 6 步超时保护 | 10 分钟 session TTL + 状态清理 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-oauth-timeout.md) |
| 30 | types.ts 类型系统的设计演进 | 180 行完整类型定义 | P0 | 源码分析 | ✅ 已完成 → [报告](unknown-types-system.md) |
