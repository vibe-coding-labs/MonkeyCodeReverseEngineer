# MonkeyCode 逆向工程 — 分析完成度矩阵

> **最后更新:** 2026-07-03
> **总维度:** 40/40 ✅ 全部搞清楚（36 原维度 + 4 新增深入分析维度）
> **源码增强轮:** 第 3 轮系统深入分析完成（3 轮次报告扩增 1438L/88 代码块 + code-exhibits 扩增 + 4 新维度报告）
> **不可覆盖项:** 3 项（运营配置范畴，非逆向可及）
> **代理源码扫描:** 全部 10 文件 (3,031 行 TypeScript) + MVP 全部 13 文件 (4,854 行 Python) 已覆盖
> **源码覆盖率:** 代理层 10 文件 100% 行级覆盖，Go 后端关键源码文件覆盖

---

## 全部完成维度 (36/36)

### 1-7: 认证协议

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| 1 | Session Redis 双结构 | ✅ | Hash Key + Lookup Key。Cookie 只存 UUID。代理层 AuthManager 24h 缓存 | `pkg/session/session.go` + `proxy/src/auth.ts` | `test_auth.py` |
| 2 | CAP.js/go-cap 验证码 | ✅ | 50x32 网格，cap.go Go 实现，challenge+redeem 线上确认 | `biz/public/handler/http/v1/captcha.go` | 线上 curl 测试 |
| 3 | 5 种登录方式 | ✅ | password-login、oauth/callback、email、team、mfa | `biz/user/handler/v1/auth.go` | — |
| 4 | 百智云 OAuth | ✅ | client_id=monkeycode-ai, scope=user+phone, 3 个 callback URL | `oauth_login.py` | 线上实测参数 |
| 5 | Auth 中间件 | ✅ | Cookie → Lookup → Hash 三跳查找。TTL 不刷新。代理自动回复 `acp_ask_user_question` | `middleware/auth.go` + `proxy/src/task-runner.ts` | — |
| 6 | 密码 bcrypt hash | ✅ | 明文 HTTPS 传输，bcrypt DefaultCost=10，MD5 注释是错误 | `pkg/crypto/bcrypt.go` | — |
| 7 | 认证自动化策略 | ✅ | Status 端点不刷新 TTL。30 天硬过期。号池 29 天提前重登录。P0/P1 告警 | `biz/user/handler/v1/auth.go` + `proxy/src/account-pool.ts` | `test_auth.py` |

### 8-14: LLM 通信

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| 8 | 模型管理 API | ✅ | CRUD + 分页 cursor，Go + @ai-sdk 双查询 | `domain/model.go` | `models.ts` |
| 9 | 3 种接口类型 | ✅ | openai_chat/openai_responses/anthropic，代理自动选择 cli_name | `domain/model.go` + `proxy/src/task-runner.ts` | — |
| 10 | 11 个提供商 | ✅ | 代理层 ModelProvider 联合类型 12 种。模型 ID 6 层回退解析 | `pkg/llm/client.go` + `proxy/src/models.ts` | — |
| 11 | 模型定价配额 | ✅ | 基本+pro+ultra 三级，最大并发 3，无 rate limiting | `domain/model.go` | 源码 grep 确认无限流 |
| 12 | LLM Client 集成 | ✅ | 3 种 SDK（go-openai/go-openai 新版/anthropic-sdk-go）自动选择 | `pkg/llm/client.go` | — |
| 13 | Coding Agent 配置 | ✅ | cli_name 枚举 (codex/claude/opencode)，NPM 包按 interface_type 映射 | `pkg/taskflow/vm.go` | — |
| 14 | 私有模型创建 | ✅ | Owner=platform/team/user 三级。ModelManager.resolveModel 6 层解析 | `domain/model.go` + `proxy/src/models.ts` | — |

### 15-20: WebSocket 协议

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| 15 | Task Stream WS | ✅ | mode=new/attach，ACP 事件流。代理自动 auto-approve + reply-question | `task-runner.ts` + `proxy/src/task-runner.ts` | `chat.py` |
| 16 | Task Control WS | ✅ | 完整 RPC 消息格式（repo_file_list/switch_model/restart 等 7 种） | `proxy/src/task-runner.ts` + `proxy/src/conversation-manager.ts` | — |
| 17 | Terminal 协议 | ✅ | PTY → WS 二进制帧隧道，TTY UTF-8 + ANSI，15s ping | Go PTY 源码 | Python 模拟 |
| 18 | TaskLive 内部 | ✅ | TaskChunk{Data,Event,Kind,Timestamp}，SetReadLimit(-1) | `pkg/taskflow/vm.go` | — |
| 19 | 语音转文字 | ✅ | PCM S16LE 16kHz mono，Doubao 流式 ASR 2.0，SSE 流 | `pkg/doubao/doubao.go` | — |
| 20 | ACP 事件参考 | ✅ | 9 种事件完整字段。代理 6 种 ACP 事件处理 | `task-runner.ts` + `proxy/src/task-runner.ts` handleACPEvent | `test_protocol.py` |

### 21-25: API 端点和授权

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| 21 | API 端点 | ✅ | 100+ 端点 + 代理管理端点 12 个。两套管理系统对比 + 各端组 HTTP 示例 | `api-endpoints.md` + `proxy/src/server.ts` | curl 测试 |
| 22 | 授权矩阵 | ✅ | public/user/team/admin 四级 + 代理层无认证管理端点安全分析 | Go 中间件 + `proxy/src/server.ts` | — |
| 23 | Conversation API | ✅ | 6 端点，前端 UI 层抽象，代理独立实现 | `user.go` | — |
| 24 | 订阅计费 | ✅ | SubscriptionResp{plan,source,expires_at,auto_renew}，开源版固定 pro。号池多账号可绕过 | `subscription/handler/v1/subscription.go` + `proxy/src/account-pool.ts` | — |
| 25 | Admin 管理 API | ✅ | 12 端点 + 代理管理 8 端点。OAuth 会话 10 分钟超时 | Go 源码 + `proxy/src/server.ts` | — |

### 26-32: VM, TaskFlow, 代理

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| 26 | VM 生命周期 | ✅ | 创建→启动→就绪→运行→销毁。代理层任务超时 1h 保护 + WS 锁超时 | `internal/taskflow/vm.go` + `proxy/src/task-runner.ts` | — |
| 27 | MCP 协议 | ✅ | JSON-RPC 2.0 over HTTP，tools/list+call，mcaiBuiltin 在 65510 | MCP 2025-06-18 规范 | — |
| 28 | Agent 内部 | ✅ | 3 种 Agent (codex/claude/opencode)。cli_name 映射：openai_responses→codex, anthropic→claude, 其他→opencode | `pkg/taskflow/vm.go` + `proxy/src/task-runner.ts` | — |
| 29 | VM 资源管理 | ✅ | Cores=2, Memory=8GB（硬编码，忽略前端传参），默认 3 并发。代理 WS_LOCK_MAX_MS 锁超时 | `domain/team_policy.go` + `proxy/src/account-pool.ts` | — |
| 30 | 代理架构 | ✅ | 10 模块 ~3031 行 TypeScript，Chat+Responses 双模式。5 种错误处理模式 | `proxy/src/` 全部 10 文件 | — |
| 31 | 号池管理 | ✅ | 多账号轮转（HTTP 共享/WS 独占）+ 健康检查 1h + 错误隔离 + 29 天 TTL + P0/P1 告警 | `account-pool.ts` | — |
| 32 | 多轮对话 | ✅ | ConversationManager + mode=attach，30 分钟超时清理 | `conversation-manager.ts` | — |

### 33-35: 代理层新增维度

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| 33 | 浏览器指纹伪装 | ✅ | 5 种域名专用请求头（mk/bz/sc/nav/wsHeaders），Chrome 148 精确模拟 | `proxy/src/browser-headers.ts` (87L) | — |
| 34 | OAuth HTTP 自动化 | ✅ | 6 步纯 HTTP OAuth 流程（无浏览器），10 分钟会话超时，备用回调URL模式 | `proxy/src/admin-login.ts` (416L) | `oauth_http.py` |
| 35 | 部署与中间件 | ✅ | Express 中间件链（CORS/JSON/SSE），5 种错误处理模式，启动序列 7 步 | `proxy/src/server.ts` (331L) | — |

### 36: 实现对比分析

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| 36 | Python MVP vs TS Proxy | ✅ | 8 大差异：架构(HTTPServer vs Express)、WS 模型(线程 vs 事件)、用户输入编码(base64 vs 纯文本)、模型管理(cache vs 6层回退) 等 | `mvp/*.py` (4,854L) vs `proxy/src/*.ts` (3,031L) | — |

### 37-40: 第 3 轮新增维度

| # | 维度 | 搞清楚了吗 | 关键结论 | 源码证据 | 验证工具 |
|---|------|-----------|---------|---------|---------|
| **37** | **模型发现 Pipeline** | ✅ | 6 层回退（精确→provider/model→model→display_name→default→首项），5 分钟缓存，monkeycode/provider/model 格式 | `proxy/src/models.ts` `resolveModel` | `GET /v1/models` |
| **38** | **Conversation Manager 生命周期** | ✅ | mode=attach 复用已有 WS，30 分钟超时清理，5 分钟定时扫描，30 秒连接超时，Promise 模式 resolve | `proxy/src/conversation-manager.ts` (368L) | — |
| **39** | **代理错误处理与重试策略** | ✅ | 5 种错误码（40100/40002/40003/40300/50000）、4 级隔离（CREATED/ACTIVE/EXPIRED/INVALID）、4 层超时保护、P0/P1/P2 告警 | `proxy/src/account-pool.ts` `handleError` | — |
| **40** | **代理安全加固分析** | ✅ | OWASP Top10 自评（7/10 项需关注）、管理端点无认证风险、CORS 全开、错误泄露风险 | 全部 10 个 TS 文件 | — |

---

## 不可覆盖项 (3 项)

以下 3 项属于**线上运营配置**范畴，非逆向分析可及：

| # | 维度 | 原因 | 建议获取方式 |
|---|------|------|------------|
| 1 | 订阅具体价格 | Stripe 后台配置，不在开源代码中 | 注册账号查看定价页面 |
| 2 | 余额具体行为 | 闭源支付组件，开源版也无 balance handler | 线上测试余额 API |
| 3 | 生产环境 Nginx 限流 | 开源版无限流配置，生产环境可能不同 | 生产环境渗透测试 |

---

## 验证状态总览

| 验证方式 | 完成数 |
|---------|-------|
| Go 源码确认 | 26 |
| TypeScript 代理源码确认 | **40** |
| Python 验证工具 | **10** (含独立深度分析报告) |
| 线上 HTTP 测试 | 4 |
| 公开协议规范 | 2 |

---

## 附录：验证工具索引

| 工具 | 位置 | 用途 | 行数 |
|------|------|------|------|
| `auth.py` | `mvp/auth.py` | 认证模块 | 323 |
| `chat.py` | `mvp/chat.py` | WebSocket 聊天 | 133 |
| `client.py` | `mvp/client.py` | 统一客户端 | **673** |
| `models.py` | `mvp/models.py` | 模型管理 | 95 |
| `proxy_real.py` | `mvp/proxy_real.py` | 真实代理 | **873** |
| `test_auth.py` | `mvp/test_auth.py` | 14 个认证测试 | 498 |
| `test_protocol.py` | `mvp/test_protocol.py` | 协议验证 | 268 |
| `verify_full_flow.py` | `mvp/verify_full_flow.py` | 端到端验证 | 471 |
| `oauth_login.py` | `mvp/oauth_login.py` | Playwright OAuth | 461 |
| `oauth_http.py` | `mvp/oauth_http.py` | HTTP OAuth | 372 |
| **`09-mvp-python-analysis.md`** | `docs/10-appendices/` | **新增** MVP 源码深度分析 | **379** |