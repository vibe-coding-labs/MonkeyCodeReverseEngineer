# MonkeyCode 逆向工程分析全书 — 索引目录

> **项目:** MonkeyCode Reverse Engineer
> **版本:** 2.3（第3轮系统深入分析完成版）
> **最后更新:** 2026-07-03
> **总文档数:** 95+（正式） + 35（原始档案）
> **分析维度:** 40+ 维度完整覆盖（36 原维度 + 4 新深入分析维度）

---

## 📖 阅读指南

本书适合三种读者：

| 读者类型 | 起点 | 路径 |
|---------|------|------|
| 🧑‍💻 **代理用户**（想使用反向代理） | 第 1 章 → 第 7 章 | 快速上手代理 |
| 🔬 **安全研究者**（想理解认证体系） | 第 1 章 → 第 2 章 → 第 9 章 | 认证 + 安全 |
| 📐 **协议开发者**（想深入协议细节） | 第 5 章 → 第 2~6 章按需 | 端点 + 协议 |

---

## 文档全集

### 第一章：系统架构 (`docs/01-architecture/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-system-overview.md](01-architecture/01-system-overview.md) | **187L** | **8** | 四层架构、Electron 壳源码、4种客户端模式、代理7步启动 |
| [02-data-flow.md](01-architecture/02-data-flow.md) | **283L** | **22** | 5条数据流完整源码追踪、Chat/Responses/OAuth/账户/模型完整路径 |
| [03-component-layer.md](01-architecture/03-component-layer.md) | **716L** | **40** | types.ts 类型系统深潜、模块依赖图、跨层类型流、17 种接口 |
| [04-error-handling-patterns.md](01-architecture/04-error-handling-patterns.md) | **409L** | **38** | 错误处理树、5 种模式、源码级错误码分析 |
| [README.md](01-architecture/README.md) | 37L | 2 | 章节总览 |

### 第二章：认证协议 (`docs/02-auth/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-session-storage.md](02-auth/01-session-storage.md) | **306L** | **30** | Redis 双结构、代理层 AuthManager、Cookie TTL 三层对比 |
| [02-captcha-system.md](02-auth/02-captcha-system.md) | 205L | 18 | CAP.js、go-cap、线上实测 |
| [03-login-methods.md](02-auth/03-login-methods.md) | **208L** | **14** | 5种登录方式源码级分析、Go handler、代理 AuthManager 双视角 |
| [04-oauth-baizhi-cloud.md](02-auth/04-oauth-baizhi-cloud.md) | **275L** | **22** | 百智云 OAuth 6 步流程、代理层请求头切换策略、10 分钟超时保护 |
| [05-auth-middleware.md](02-auth/05-auth-middleware.md) | **282L** | **18** | 后端 Go 中间件 + 代理 AuthManager 双视角、Cookie 自动刷新 |
| [06-password-management.md](02-auth/06-password-management.md) | **157L** | **16** | bcrypt 实现、密码修改/重置 Go handler 源码、代理密码安全 |
| [07-auth-automation.md](02-auth/07-auth-automation.md) | **247L** | **20** | 验证码绕过、Session 保活、并发策略 |
| [08-pool-gap-analysis.md](02-auth/08-pool-gap-analysis.md) | **397L** | **32** | 号池源码完整分析、状态机、双模式获取、告警阈值 |
| [README.md](02-auth/README.md) | 39L | 0 | 章节总览 |

### 第三章：LLM 通信协议 (`docs/03-llm/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-model-management-api.md](03-llm/01-model-management-api.md) | **293L** | **16** | 模型 CRUD、Owner 权限过滤、ModelManager 6层解析、5分钟缓存 |
| [02-interface-types.md](03-llm/02-interface-types.md) | **305L** | **22** | 3种接口SDK选择+代理Chat/Responses双模式+HTTP示例+cli_name映射 |
| [03-provider-list.md](03-llm/03-provider-list.md) | **223L** | **22** | 11 个提供商配置、代理层 ModelManager 源码、模型 ID 6 层解析 |
| [04-model-pricing-quota.md](03-llm/04-model-pricing-quota.md) | **202L** | **16** | TeamPolicy 并发控制、3级订阅、VM 资源分配双层模型 |
| [05-llm-integration.md](03-llm/05-llm-integration.md) | **298L** | **18** | Client 架构、SDK 调用链、错误处理 |
| [06-coding-agent-config.md](03-llm/06-coding-agent-config.md) | **163L** | **12** | 4种 cli_name 枚举、agentpluginrepo 表设计、容器启动流程 |
| [06-private-model-creation.md](03-llm/06-private-model-creation.md) | **317L** | **22** | 私有模型创建完整流程、ModelManager 缓存策略、模型 ID 映射 |
| **[07-model-discovery-pipeline.md](03-llm/07-model-discovery-pipeline.md)** | **413L** | **30** | **新增** 模型发现 Pipeline 全景、6 层回退解析、5 分钟缓存、全链路追踪 |
| [README.md](03-llm/README.md) | 37L | 0 | 章节总览 |

### 第四章：WebSocket 协议 (`docs/04-websocket/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-task-stream.md](04-websocket/01-task-stream.md) | **279L** | **24** | Task Stream WS 代理实现、ACP→SSE 转换、6 种事件处理 |
| [02-task-control.md](04-websocket/02-task-control.md) | **237L** | **20** | 任务控制 WS 完整协议、RPC 示例、与 Stream WS 对比 |
| [03-terminal.md](04-websocket/03-terminal.md) | **290L** | **18** | TTY 协议、PTY 源码、Keepalive |
| [04-tasklive-internal.md](04-websocket/04-tasklive-internal.md) | **212L** | **18** | TaskChunk 格式、通信流、Go 源码 |
| [05-speech-to-text.md](04-websocket/05-speech-to-text.md) | **259L** | **24** | PCM S16LE 音频编码、Doubao ASR、代理层音频传输方式 |
| [06-acp-event-reference.md](04-websocket/06-acp-event-reference.md) | 201L | 16 | ACP 事件完整参考 |
| **[07-conversation-lifecycle.md](04-websocket/07-conversation-lifecycle.md)** | **465L** | **34** | **新增** Conversation Manager 生命周期、mode=attach WS 帧级跟踪 |
| [README.md](04-websocket/README.md) | 38L | 0 | 章节总览 |

### 第五章：API 端点和授权 (`docs/05-api/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-endpoint-catalog.md](05-api/01-endpoint-catalog.md) | **249L** | **16** | 100+端点 + 各端组 HTTP/curl 示例 + 代理扩展端点 + 端到端调用链 |
| [02-authorization-matrix.md](05-api/02-authorization-matrix.md) | **394L** | **22** | 双层授权体系、代理层 AuthManager、6 层模型 ID 解析回退 |
| [03-conversation-api.md](05-api/03-conversation-api.md) | **222L** | **10** | Go后端 + TS ConversationManager双实现、ACP事件处理 |
| [04-subscription-billing.md](05-api/04-subscription-billing.md) | **216L** | **18** | SubscriptionResp、开源版固定pro、号池多账号绕过、Stripe集成 |
| [05-admin-management-api.md](05-api/05-admin-management-api.md) | **299L** | **18** | 12 个 Admin 端点、代理管理端点、OAuth 自动化管理 |
| [README.md](05-api/README.md) | 34L | 0 | 章节总览 |

### 第六章：VM & TaskFlow (`docs/06-vm-taskflow/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-architecture.md](06-vm-taskflow/01-architecture.md) | **164L** | **14** | TaskFlow 架构定位、TaskChunk 格式、Go 前后端通信协议 |
| [02-vm-lifecycle.md](06-vm-taskflow/02-vm-lifecycle.md) | **246L** | **18** | VM 生命周期、代理层双重超时保护、image_id 发现流程 |
| [03-mcp-protocol.md](06-vm-taskflow/03-mcp-protocol.md) | 367L | 12 | JSON-RPC 2.0、tools/list |
| [04-agent-internals.md](06-vm-taskflow/04-agent-internals.md) | **277L** | **16** | Agent 类型、NPM 包、容器初始化 |
| [05-resource-management.md](06-vm-taskflow/05-resource-management.md) | **231L** | **28** | 资源管理、Cores=2/Memory=8GB、代理层超时控制、WS 锁超时 |
| [README.md](06-vm-taskflow/README.md) | 36L | 0 | 章节总览 |

### 第七章：代理实现 (`docs/07-proxy/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-architecture.md](07-proxy/01-architecture.md) | **277L** | **30** | 10模块依赖图、调用链分析、依赖矩阵、5种设计模式 |
| [02-account-pool.md](07-proxy/02-account-pool.md) | **394L** | **36** | 账号状态机、双模式获取、健康检查、4级错误隔离、P0/P1告警 |
| [03-multi-turn-conversation.md](07-proxy/03-multi-turn-conversation.md) | **292L** | **16** | ConversationManager、mode=attach |
| [04-acp-to-openai-mapping.md](07-proxy/04-acp-to-openai-mapping.md) | **299L** | **16** | Chat + Responses 双模式映射 |
| [05-oauth-automation.md](07-proxy/05-oauth-automation.md) | **257L** | **12** | 6 步 OAuth 自动化、Playwright |
| [06-browser-fingerprinting.md](07-proxy/06-browser-fingerprinting.md) | **248L** | **38** | 4 种域名专用请求头生成器、浏览器指纹伪装 |
| [06-oauth-automation-http.md](07-proxy/06-oauth-automation-http.md) | **294L** | **22** | 纯 HTTP OAuth 自动化、6 步协议详解 |
| [07-deployment-infrastructure.md](07-proxy/07-deployment-infrastructure.md) | **278L** | **16** | Express 中间件链、SSE 流控制、Nginx 部署 |
| [08-server-startup.md](07-proxy/08-server-startup.md) | **343L** | **24** | **新增** server.ts 7步启动、12管理端点、异常容忍分析 |
| [09-oauth-http-automation-deep.md](07-proxy/09-oauth-http-automation-deep.md) | **483L** | **34** | **新增** admin-login.ts 416行完整分析、6步OAuth时序、SCaptcha TLS绕过 |
| **[09-error-handling-deep.md](07-proxy/09-error-handling-deep.md)** | **441L** | **32** | **新增** 代理错误处理深度分析、5 种错误码、4 级隔离、超时保护 |
| [README.md](07-proxy/README.md) | 50L | 0 | 章节总览 |

### 第八章：分析轮次 (`docs/08-analysis-rounds/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [round-01-to-06（扩增版）](08-analysis-rounds/rounds/round-01-to-06.md) | **541L** | **38** | ASAR解包/密码登录/三层架构/提供商/VM/WebSocket 全源码追溯 |
| [round-07-to-12（扩增版）](08-analysis-rounds/rounds/round-07-to-12.md) | **517L** | **26** | ACP事件全表/授权矩阵/OAuth 6步/多轮对话/订阅/号池管理 |
| [round-13-to-18（扩增版）](08-analysis-rounds/rounds/round-13-to-18.md) | **380L** | **24** | ACP→OpenAI双模式映射/4个Bug修复/TS代理完成/安全测试 |
| [README.md](08-analysis-rounds/README.md) | 32L | 0 | 章节总览 |

### 第九章：安全分析 (`docs/09-security/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [baizhi-security-report.md](09-security/baizhi-security-report.md) | **268L** | **22** | SCaptcha 漏洞发现（TLS 绕过/授权码重放/短信轰炸）|
| **[02-proxy-security-analysis.md](09-security/02-proxy-security-analysis.md)** | **354L** | **22** | **新增** 代理安全加固分析（OWASP Top 10 自评/管理端点认证/CSRF 防护） |
| [README.md](09-security/README.md) | 24L | 0 | 章节总览 |

### 第十章：附录 (`docs/10-appendices/`)

| 文件 | 行数 | 代码块 | 关键内容 |
|------|------|--------|---------|
| [01-asar-analysis.md](10-appendices/01-asar-analysis.md) | **251L** | **22** | Electron ASAR 分析 |
| [02-error-codes.md](10-appendices/02-error-codes.md) | **178L** | **18** | 错误码全集、代理错误策略、启动时错误容忍、ACP 事件错误 |
| [03-environment-variables.md](10-appendices/03-environment-variables.md) | **180L** | **10** | 5 类 30+ 环境变量 + 默认值 + 源码引用 + .env 示例 |
| [04-glossary.md](10-appendices/04-glossary.md) | **134L** | **8** | 100+ 术语全覆盖、Go结构体速查、TypeScript接口速查、ACP事件速查 |
| [05-code-exhibits.md](10-appendices/05-code-exhibits.md) | 153L | 4 | 代码展品全集 |
| [06-api-payloads.md](10-appendices/06-api-payloads.md) | **391L** | **30** | API 请求/响应示例 |
| [07-websocket-frames.md](10-appendices/07-websocket-frames.md) | **321L** | **40** | WebSocket 帧数据分析 |
| [08-python-vs-ts.md](10-appendices/08-python-vs-ts.md) | **289L** | **28** | Python MVP vs TS 代理实现差异 |
| [09-mvp-python-analysis.md](10-appendices/09-mvp-python-analysis.md) | **379L** | **22** | **新增** MVP Python 13文件源码深度分析 |

### 原始分析档案 (`docs/protocol/` — 35 份文件, 12903 行)

内容已被各章节覆盖，保留作为原始分析记录。

---

## 分析维度速查表

| # | 维度 | 状态 | 置信度 | 核心源码引用 | 章节 |
|---|------|------|--------|------------|------|
| 1 | Redis Session 双结构 | ✅ 已完成 | high | `session.go` | 02-auth/01 |
| 2 | CAP.js/go-cap 验证码 | ✅ 已完成 | high | `captcha.go` | 02-auth/02 |
| 3 | 5 种登录方式 | ✅ 已完成 | high | `auth.go` | 02-auth/03 |
| 4 | 百智云 OAuth 流程 | ✅ 已完成 | high | `oauth_login.py` | 02-auth/04 |
| 5 | Auth 中间件实现 | ✅ 已完成 | high | `middleware/auth.go` | 02-auth/05 |
| 6 | bcrypt 密码管理 | ✅ 已完成 | high | `crypto/bcrypt.go` | 02-auth/06 |
| 7 | 认证自动化策略 | ✅ 已完成 | high | `auth.go` + `auth-automation.md` | 02-auth/07 |
| 8 | 模型管理 API | ✅ 已完成 | high | `model.go` | 03-llm/01 |
| 9 | 3 种 LLM 接口类型 | ✅ 已完成 | high | `interface_type.go` | 03-llm/02 |
| 10 | 11 个提供商配置 | ✅ 已完成 | high | `client.go` | 03-llm/03 |
| 11 | 模型定价与配额 | ✅ 已完成 | high | `model.go` | 03-llm/04 |
| 12 | LLM Client 集成 | ✅ 已完成 | high | `llm/client.go` | 03-llm/05 |
| 13 | Coding Agent 配置 | ✅ 已完成 | high | `vm.go` | 03-llm/06 |
| 14 | 私有模型创建 | ✅ 已完成 | high | `model.go` | 03-llm/06 |
| 15 | Task Stream WS | ✅ 已完成 | high | `task-runner.ts` | 04-websocket/01 |
| 16 | Task Control WS | ✅ 已完成 | high | — | 04-websocket/02 |
| 17 | Terminal TTY 协议 | ✅ 已完成 | high | Go PTY 源码 | 04-websocket/03 |
| 18 | TaskLive 内部通信 | ✅ 已完成 | high | `vm.go` | 04-websocket/04 |
| 19 | Doubao ASR 语音 | ✅ 已完成 | high | `doubao.go` | 04-websocket/05 |
| 20 | ACP 事件参考 | ✅ 已完成 | high | `task-runner.ts` | 04-websocket/06 |
| 21 | API 端点目录（100+） | ✅ 已完成 | high | `api-endpoints.md` | 05-api/01 |
| 22 | 授权矩阵 | ✅ 已完成 | high | — | 05-api/02 |
| 23 | Conversation API | ✅ 已完成 | medium | `user.go` | 05-api/03 |
| 24 | 订阅与计费 | ✅ 已完成 | medium | `subscription.go` | 05-api/04 |
| 25 | Admin 管理 API | ✅ 已完成 | high | — | 05-api/05 |
| 26 | VM 生命周期 | ✅ 已完成 | high | `vm.go` | 06-vm-taskflow/02 |
| 27 | MCP 协议 | ✅ 已完成 | high | JSON-RPC 2.0 规范 | 06-vm-taskflow/03 |
| 28 | Agent 内部架构 | ✅ 已完成 | medium | `vm.go` | 06-vm-taskflow/04 |
| 29 | VM 资源管理 | ✅ 已完成 | high | `team_policy.go` | 06-vm-taskflow/05 |
| 30 | 代理架构实现 | ✅ 已完成 | high | `proxy/src/*.ts` | 07-proxy/01 |
| 31 | 号池管理 | ✅ 已完成 | high | `account-pool.ts` | 07-proxy/02 |
| 32 | 多轮对话 | ✅ 已完成 | high | `conversation-manager.ts` | 07-proxy/03 |
| 33 | 浏览器指纹伪装 | ✅ 新增 | high | `proxy/src/browser-headers.ts` | 07-proxy/06 |
| 34 | OAuth HTTP 自动化 | ✅ 新增 | high | `proxy/src/admin-login.ts` (416L) | 07-proxy/06 |
| 35 | 部署与中间件 | ✅ 新增 | high | `proxy/src/server.ts` (331L) | 07-proxy/07 |
| 36 | Python vs TS 实现差异 | ✅ 新增 | medium | `mvp/*.py` vs `proxy/src/*.ts` | 10-appendices/08 |
| **37** | **模型发现 Pipeline（6 层回退）** | ✅ **新维度** | **high** | `models.ts` `resolveModel` | 03-llm/07 |
| **38** | **Conversation Manager 生命周期** | ✅ **新维度** | **high** | `conversation-manager.ts` | 04-websocket/07 |
| **39** | **代理错误处理与重试策略** | ✅ **新维度** | **high** | `account-pool.ts` `handleError` | 07-proxy/09 |
| **40** | **代理安全加固分析（OWASP）** | ✅ **新维度** | **high** | 全部 10 文件 | 09-security/02 |

### 仍缺线上确认的项

| # | 维度 | 原因 | 对分析完整性的影响 |
|---|------|------|-----------------|
| — | 订阅实际价格 | Stripe 配置不在开源代码中 | —（运营配置范畴） |
| — | 余额具体行为 | 闭源支付组件 | —（运营配置范畴） |
| — | 生产环境 Nginx 限流 | 开源版无限流，生产可能不同 | —（部署配置范畴） |

---

## 逆向代码展品索引

全书包含约 **500+ 代码块**，涵盖以下语言：

| 语言 | 代码块数 | 主要用途 |
|------|---------|---------|
| Go | ~60 | 后端源码分析（Redis 操作、PTY 管理、LLM Client 等） |
| TypeScript | ~60 | 代理实现（auth.ts、task-runner.ts、api-routes.ts 等） |
| Python | ~35 | 验证工具、抓包模拟、Playwright 自动化、MVP 深度分析 |
| HTTP | ~60 | API 请求/响应示例 |
| JSON | ~70 | ACP 事件、API 响应、SSE 数据 |
| bash | ~35 | curl 测试命令 |

---

## 修订历史

| 日期 | 版本 | 变更 |
|------|------|------|
| **2026-07-03** | **2.3** | **第 3 轮系统深入分析完成：分析轮次扩增 156L→1438L/88 代码块，code-exhibits 扩增 227L→643L/33 代码块，新增 4 个新维度（模型发现 Pipeline/Conversation 生命周期/错误处理深度分析/代理安全加固），全书达到 40+ 维度 500+ 代码块** |
| 2026-06-28 | 2.2 | 第 2 轮系统扩增完成：新增 endpoint-catalog 代码示例、data-flow 5 路径追踪、glossary/env-vars/interface-types/password-management 扩增、MVP Python 深度分析 |
| 2026-06-27 | 2.0 | 11 份文档扩增代码示例，创建全书索引目录 |
| 2026-06-25 | 1.0 | 文档重组为 10 章节书结构 |
| 2026-05-10~30 | 0.x | 18 轮逆向分析完成 |

---

<p align="center">
  <sub>Built with ❤️ for research and educational purposes.</sub>
</p>