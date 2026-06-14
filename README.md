<p align="center">
  <img src="https://img.shields.io/badge/status-active--development-blue" alt="Status">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/protocol-analysis-31%20rounds-brightgreen" alt="Protocol Analysis">
  <img src="https://img.shields.io/badge/author-CC11001100-orange" alt="Author">
</p>

# MonkeyCode Reverse Engineer

> **MonkeyCode AI 平台的全方位逆向工程与反向代理实现**
>
> 目标：将 MonkeyCode 平台内建的 AI 编码能力（覆盖 11 个模型提供商、3 种 LLM 接口协议）逆向分析 → 协议文档化 → 以 OpenAI 兼容 API（Chat Completions / Responses）暴露给 Codex 等第三方 AI 工具使用。

---

## 📋 目录

- [项目背景](#-项目背景)
- [架构总览](#-架构总览)
- [项目进度](#-项目进度)
- [仓库结构](#-仓库结构)
- [文档索引](#-文档索引)
  - [协议分析报告](#协议分析报告)
  - [认证相关](#认证相关)
  - [LLM 通信协议](#llm-通信协议)
  - [WebSocket & 通道](#websocket--通道)
  - [任务流 & VM](#任务流--vm)
  - [安全分析](#安全分析)
- [快速开始](#-快速开始)
- [Python 验证工具](#-python-验证工具)
- [代理与 Codex 集成](#-代理与-codex-集成)
- [安全说明](#-安全说明)
- [已知限制](#-已知限制)

---

## 🎯 项目背景

**MonkeyCode** ([monkeycode-ai.com](https://monkeycode-ai.com)) 是一个 AI 编码平台，后端集成了 11 个模型提供商（OpenAI、Anthropic、DeepSeek、SiliconFlow 等），通过 Docker 容器化的 TaskFlow VM 运行 AI Agent，提供代码开发、审查、文档生成等功能。

本仓库的目标是：

1. **逆向分析** MonkeyCode 平台的全套通信协议（认证、API、WebSocket 流、Agent-Client-Protocol）
2. **协议文档化** — 将分析结果整理为结构化文档
3. **实现反向代理** — 将 MonkeyCode 的能力以 OpenAI 标准 API 暴露出来，让 Codex 等工具可以直接使用
4. **Python 验证** — 编写验证脚本确认协议理解正确

### 为什么需要这个项目？

MonkeyCode 本身是一个**闭源 SaaS 平台**，没有官方的 OpenAI 兼容 API。通过逆向工程，我们可以：

- 使用 MonkeyCode 集成的公开模型（如 qwen3.5-plus、kimi-k2.6 等）来驱动 Codex
- 理解其 Agent 通信协议（ACP）的设计模式
- 验证其认证体系的安全边界

---

## 🏗 架构总览

```
┌─ Client ──────────────────────────────────────────────────┐
│  Codex / curl / OpenAI SDK                                 │
│  GET  /v1/models                                           │
│  POST /v1/chat/completions {model, messages, stream}       │
│  POST /v1/responses {model, input}         (Codex 原生)    │
└──────────────────────┬─────────────────────────────────────┘
                       │ HTTP / SSE (OpenAI 格式)
┌──────────────────────▼─────────────────────────────────────┐
│  Proxy Layer (OpenAI → MonkeyCode Bridge)                   │
│                                                             │
│  TypeScript (proxy/src/)                 Python (mvp/)     │
│  ┌─────────────────────────────┐   ┌─────────────────────┐  │
│  │ auth.ts         认证模块   │   │ client.py  统一客户端│  │
│  │ models.ts       模型管理   │   │ proxy_real.py 代理   │  │
│  │ task-runner.ts  任务+WS流  │   │ verify_full_flow.py │  │
│  │ api-routes.ts   OpenAI路由 │   │ auth.py      认证    │  │
│  │ account-pool.ts 号池轮转   │   └─────────────────────┘  │
│  │ conversation-manager.ts    │                             │
│  └─────────────────────────────┘                             │
│                                                             │
│  ACP → OpenAI 事件映射引擎:                                  │
│  agent_message_chunk  → delta.content                        │
│  agent_thought_chunk  → [Thinking] 前缀 + content            │
│  tool_call            → tool_calls / function_call           │
│  usage_update         → accumulate → task-ended 输出         │
└──────────────────────┬─────────────────────────────────────┘
                       │ MonkeyCode API + WebSocket
┌──────────────────────▼─────────────────────────────────────┐
│  MonkeyCode Backend (Go / Gin)                              │
│                                                             │
│  POST /api/v1/users/tasks     — 创建 AI 任务               │
│  GET  /api/v1/users/status    — 检查 Session 有效性         │
│  GET  /api/v1/users/models    — 获取可用模型列表             │
│  POST /api/v1/users/password-login  — 密码登录              │
│  WS   /api/v1/users/tasks/stream    — ACP 事件流             │
│  WS   /api/v1/users/tasks/control   — 任务控制通道           │
│  WS   /api/v1/users/hosts/vms/{id}/terminals — 终端通道      │
└──────────────────────┬─────────────────────────────────────┘
                       │ TaskFlow Orchestration
┌──────────────────────▼─────────────────────────────────────┐
│  VM Cluster (Docker Container, 内嵌 Agent)                   │
│                                                             │
│  Agent(Codex/Claude/OpenCode) → LLM Client (Go)            │
│    ├── openai_chat:      POST {baseURL}/chat/completions    │
│    ├── openai_responses: POST {baseURL}/responses           │
│    └── anthropic:        POST {baseURL}/v1/messages         │
│                                                             │
│  Agent 工具: bash 执行 / 文件读写 / git / MCP 协议           │
└──────────────────────┬─────────────────────────────────────┘
                       │
    ┌──────────────────┼──────────────────┐
    ▼                  ▼                  ▼
  OpenAI           Anthropic          DeepSeek
  SiliconFlow      Moonshot           Volcengine...
```

### 核心工作流

```
Browser/Codex → 创建任务 → 后端调度 VM → Agent 初始化
  → 连接 LLM Provider → Agent 开始工作
  → ACP 事件通过 WebSocket 推回 → Proxy 转换为 OpenAI SSE
  → 客户端收到标准 OpenAI 格式响应
```

---

## 📊 项目进度

### 协议分析状态（31 轮分析完成）

| 模块 | 完成度 | 关键成果 |
|------|--------|---------|
| **认证协议** | **98%** | 5 种登录方式：OAuth / 密码登录 / 团队登录 / Git OAuth / Admin Impersonate |
| **LLM 通信协议** | **95%** | 3 种接口类型（openai_chat / openai_responses / anthropic），11 个模型提供商 |
| **WebSocket 协议** | **90%** | 3 个独立通道（Stream / Control / Terminal），ACP 事件 7 种子类型 |
| **API 端点映射** | **95%** | 100 个 API 端点（89 个需认证 + 11 个公开） |
| **VM 生命周期** | **85%** | 7 种状态、2 种超时策略、VM 热复用 |
| **模型定价配额** | **90%** | 3 级订阅（basic/pro/ultra），公开/私有/团队三级模型 |
| **Conversation API** | **40%** | 6 个端点已知，完整 JSON Schema 待确认 |
| **号池管理** | **95%** | 4 种状态（CREATED/ACTIVE/EXPIRED/INVALID），LRU+轮询+互斥锁 |

### 实现状态

| 组件 | 语言 | 文件数 | 行数 | 状态 |
|------|------|--------|------|------|
| 反向代理（完整实现） | TypeScript | 10 | ~2,920 | ✅ **已编译通过** |
| 统一代理客户端 | Python | 1 | 673 | ✅ **已完成** |
| OpenAI 兼容代理 | Python | 1 | 873 | ✅ **已完成** |
| 端到端验证脚本 | Python | 1 | 471 | ✅ **已完成** |
| 认证协议验证 | Python | 1 | 323 | ✅ **已增强** |
| OAuth 自动化登录 | Python | 2 | 544 | ✅ **已完成** |
| 模型管理验证 | Python | 1 | 90 | ✅ **已完成** |
| WebSocket 聊天验证 | Python | 1 | 134 | ✅ **已完成** |

### 已知待确认项

| # | 项目 | 优先级 | 说明 |
|---|------|--------|------|
| 1 | `tool_call_update` 精确字段 | P0 | 协议文档标记为"-"，需线上验证 |
| 2 | 自动审批 + 提问交互 | P0 | `auto-approve` 与 `reply-question` 是否冲突需实测 |
| 3 | Conversation API Schema | P1 | 已知 6 端点，请求/响应 JSON 格式待确认 |
| 4 | `session_update` 事件 | P2 | 独立 WS 消息类型，非 ACP 事件 |

---

## 📁 仓库结构

```
MonkeyCodeReverseEngineer/
│
├── proxy/                            # TypeScript 反向代理（完整实现）
│   ├── .env.example                  # 环境变量模板
│   ├── src/
│   │   ├── server.ts                 # 主入口 + Express HTTP 服务器
│   │   ├── auth.ts                   # 认证模块（Cookie-based Session）
│   │   ├── account-pool.ts           # 多账号号池轮转（HTTP 共享 + WS 独占）
│   │   ├── admin-login.ts            # 百智云 OAuth 登录自动化
│   │   ├── models.ts                 # 模型列表获取与缓存
│   │   ├── task-runner.ts            # 任务创建 + WebSocket 流式接收
│   │   ├── api-routes.ts             # OpenAI 兼容 API 路由（完整实现）
│   │   ├── conversation-manager.ts   # 多轮对话管理器
│   │   ├── types.ts                  # 完整类型定义
│   │   └── browser-headers.ts        # 浏览器头欺骗（3 种域名）
│   ├── package.json
│   └── tsconfig.json
│
├── mvp/                              # Python 协议验证与代理工具
│   ├── client.py                     # 🆕 统一客户端（认证 + 模型 + 任务 + WS）
│   ├── proxy_real.py                 # 🆕 真实 OpenAI 兼容代理
│   ├── verify_full_flow.py           # 🆕 端到端链路验证脚本
│   ├── auth.py                       # ✨ 增强版认证模块
│   ├── models.py                     # 模型管理验证
│   ├── chat.py                       # WebSocket 聊天协议验证
│   ├── proxy.py                      # (旧) mock 版代理
│   ├── oauth_login.py                # Playwright OAuth 自动化
│   ├── oauth_http.py                 # HTTP OAuth 授权（含 SCaptcha）
│   ├── config.py                     # 共享配置
│   ├── test_auth.py                  # 认证协议测试（14 用例）
│   ├── test_auth_interactive.py      # 交互式认证测试
│   ├── test_protocol.py              # 端到端协议验证
│   ├── requirements.txt
│   ├── run_mvp.sh                    # 运行脚本
│   └── README.md                     # MVP 使用文档
│
├── docs/                             # 文档
│   ├── protocol/                     # 逆向分析协议文档（核心产出）
│   │   ├── analysis-summary.md       # 分析总结报告
│   │   ├── analysis-round-*.md       # 逐轮分析报告（18 轮）
│   │   ├── auth-protocol-complete.md # 认证协议完整文档
│   │   ├── llm-protocol-complete.md  # LLM 通信协议完整文档
│   │   ├── llm-integration.md        # LLM 集成协议详解
│   │   ├── websocket-protocol.md     # WebSocket 流式协议
│   │   ├── api-endpoints.md          # 完整 API 端点映射（100 个）
│   │   ├── architecture.md           # 系统架构分析
│   │   ├── authorization-matrix.md   # 授权层级与访问控制矩阵
│   │   ├── account-pool-protocol.md  # 账号号池协议
│   │   ├── taskflow-vm-analysis.md   # TaskFlow VM 生命周期分析
│   │   ├── multi-turn-design.md      # 多轮对话设计
│   │   ├── asar-analysis.md          # Electron ASAR 逆向分析
│   │   ├── auth-automation-analysis.md    # 认证自动化分析
│   │   ├── auth-pool-gap-analysis.md      # 认证号池差距分析
│   │   ├── auth-unresolved-verification.md # 认证待验证问题
│   │   └── model-pricing-quota.md    # 模型定价与配额分析
│   └── superpowers/                  # 超能力 / 功能扩展文档
│
├── analysis/                         # 逆向分析素材
│   └── asar-content/                 # Electron ASAR 解包内容
│       ├── electron/                 # Electron 主进程代码
│       └── renderer/                 # 前端渲染层代码（React）
│
├── .gitignore
└── README.md                         # 本文件
```

---

## 📚 文档索引

### 协议分析报告

| 文档 | 内容 | 完成度 |
|------|------|--------|
| [分析总结报告](docs/protocol/analysis-summary.md) | 项目全貌、关键发现、修复列表 | ✅ 完整 |
| [分析轮次 01](docs/protocol/analysis-round-01.md) | 全面状态评估与差距分析 | ✅ 完整 |
| [分析轮次 02](docs/protocol/analysis-round-02.md) | P0 深度分析 | ✅ 完整 |
| [分析轮次 03](docs/protocol/analysis-round-03.md) | 代码修复实施 | ✅ 完整 |
| [分析轮次 04](docs/protocol/analysis-round-04.md) | 多轮对话设计 | ✅ 完整 |
| [分析轮次 05](docs/protocol/analysis-round-05.md) | Phase 1 实施 | ✅ 完整 |
| [分析轮次 06](docs/protocol/analysis-round-06.md) | 代码审查 | ✅ 完整 |
| [分析轮次 07](docs/protocol/analysis-round-07.md) | 测试脚本 | ✅ 完整 |
| [分析轮次 08](docs/protocol/analysis-round-08.md) ~ [18](docs/protocol/analysis-round-18.md) | 持续深入分析 | ✅ 完整 |

### 认证相关

| 文档 | 内容 | 完成度 |
|------|------|--------|
| [认证协议完整文档](docs/protocol/auth-protocol-complete.md) | 5 种登录方式、Session 存储、Redis 结构、Cookie 属性 | 98% |
| [授权层级与访问控制矩阵](docs/protocol/authorization-matrix.md) | 角色体系、5 种中间件、API 访问权限 | 95% |
| [认证号池差距分析](docs/protocol/auth-pool-gap-analysis.md) | 多账号轮转策略、状态管理、锁机制 | 95% |
| [认证自动化分析](docs/protocol/auth-automation-analysis.md) | SCaptcha 绕过、OAuth 自动化全流程 | 90% |
| [认证待验证问题](docs/protocol/auth-unresolved-verification.md) | 线上实测发现的 5 个偏差及源码验证 | 100% |

### LLM 通信协议

| 文档 | 内容 | 完成度 |
|------|------|--------|
| [LLM 协议完整分析](docs/protocol/llm-protocol-complete.md) | 3 种接口类型、模型管理 API、健康检查、Public API Key 机制 | 95% |
| [LLM 集成协议详解](docs/protocol/llm-integration.md) | Client 架构、接口类型自动检测、11 个提供商配置 | 98% |
| [模型定价与配额](docs/protocol/model-pricing-quota.md) | 3 级订阅（basic/pro/ultra）、模型访问逻辑 | 90% |

### WebSocket & 通道

| 文档 | 内容 | 完成度 |
|------|------|--------|
| [WebSocket 流式协议](docs/protocol/websocket-protocol.md) | 3 个独立 WS 通道、ACP 事件 7 种子类型、消息格式 | 90% |
| [任务协议分析](docs/protocol/analysis-round-06.md) | 任务创建格式、TaskStreamMessage 结构 | 95% |

### 任务流 & VM

| 文档 | 内容 | 完成度 |
|------|------|--------|
| [TaskFlow VM 分析](docs/protocol/taskflow-vm-analysis.md) | VM 7 种状态、生命周期管理、资源配额 | 85% |
| [多轮对话设计](docs/protocol/multi-turn-design.md) | Conversation API、attach 模式、历史回放 | 90% |
| [完整 API 端点映射](docs/protocol/api-endpoints.md) | 100 个 API 端点（含认证要求） | 95% |

### 安全分析

| 文档 | 内容 | 完成度 |
|------|------|--------|
| [百智云安全测试报告](docs/protocol/baizhi-cloud-security-report/) | SCaptcha 漏洞发现、安全评估 | 已报告 |

---

## 🚀 快速开始

### 前置条件

- 一个 **已注册 MonkeyCode 的账号**
- Node.js 18+（TypeScript 代理）
- Python 3.8+（Python 验证工具）

### 运行 TypeScript 代理（推荐，完整实现）

```bash
cd proxy
cp .env.example .env
# 编辑 .env 填入 MONKEYCODE_SESSION_COOKIE 和 MONKEYCODE_IMAGE_ID
npm install
npm run dev
```

### 获取 Session Cookie（二选一）

**方式 A：浏览器提取（推荐，1 分钟）**

1. 浏览器打开 [monkeycode-ai.com](https://monkeycode-ai.com) 并登录
2. 按 `F12` → `Application` → `Cookies` → 找到 `monkeycode_ai_session`
3. 复制 Cookie 值
4. 设置到代理：

```bash
export MONKEYCODE_SESSION_COOKIE="你复制的session值"
```

**方式 B：密码登录**

```
export MONKEYCODE_USERNAME="your-email@example.com"
export MONKEYCODE_PASSWORD="your-password"
```

> ⚠️ 密码登录需要 `captcha_token`（go-cap 验证码），建议优先使用方式 A。

### 获取 IMAGE_ID

1. 浏览器登录 MonkeyCode 并打开 DevTools → Network
2. 创建一个任务（输入提示词后点击运行）
3. 在 Network 中找到 `POST /api/v1/users/tasks` 请求
4. 复制请求体中的 `image_id` 字段值

```bash
export MONKEYCODE_IMAGE_ID="你获取的image_id"
```

### 验证运行

```bash
# 模型列表
curl http://localhost:9090/v1/models | jq

# Chat Completions
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "monkeycode/OpenAI/gpt-4o", "messages": [{"role": "user", "content": "你好"}]}'

# 流式 Chat Completions
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "monkeycode/OpenAI/gpt-4o", "messages": [{"role": "user", "content": "你好"}], "stream": true}'

# Responses API（Codex 原生）
curl -X POST http://localhost:9090/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"model": "monkeycode/OpenAI/gpt-4o", "input": "你好"}'
```

---

## 🐍 Python 验证工具

`mvp/` 目录提供了一套完整的 Python 实现，用于**协议验证**和**完整链路测试**。

### 文件总览

```
mvp/
├── client.py             # 统一客户端（673 行）
├── proxy_real.py         # 真实代理（873 行）
├── verify_full_flow.py   # 端到端验证（471 行）
├── auth.py               # 认证模块（323 行）
├── models.py             # 模型管理
├── chat.py               # WebSocket 聊天
├── oauth_login.py        # Playwright OAuth
├── oauth_http.py         # HTTP OAuth
├── test_auth.py          # 14 个测试用例
├── test_protocol.py      # 协议验证
├── README.md             # Python 工具使用说明
└── run_mvp.sh            # 启动脚本
```

### 运行 Python 代理

```bash
cd mvp
export MONKEYCODE_SESSION_COOKIE="xxx"
export MONKEYCODE_IMAGE_ID="xxx"
python proxy_real.py
# 监听 http://0.0.0.0:9091
```

### 完整链路验证

```bash
python verify_full_flow.py       # 全流程验证（需要 IMAGE_ID）
python verify_full_flow.py --skip-task  # 仅认证+模型
```

### 认证对比

| 方式 | 难度 | 有效性 | 验证码 | 适用场景 |
|------|------|--------|--------|---------|
| Session Cookie | ⭐ 简单 | 最长 30天 | ❌ 不需要 | ✅ **推荐，自动化首选** |
| 密码登录 | ⭐⭐ 中等 | 30天（刷新） | ✅ go-cap | 批量账号 |
| OAuth 百智云 | ⭐⭐⭐ 复杂 | 30天 | ✅ SCaptcha | 手机号登录 |
| 团队密码登录 | ⭐⭐ 中等 | 30天 | ✅ go-cap | 团队管理 |

---

## 🔌 代理与 Codex 集成

### Codex CLI 集成

```bash
export OPENAI_API_KEY="any-value-works"
export OPENAI_BASE_URL="http://localhost:9090/v1"
codex
```

### OpenAI SDK 集成

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:9090/v1",
    api_key="any",  # MonkeyCode 使用 Cookie 认证，API Key 不校验
)

response = client.chat.completions.create(
    model="monkeycode/OpenAI/gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

### 支持的 OpenAI 端点

| 端点 | 方法 | 流式支持 | 说明 |
|------|------|---------|------|
| `/v1/models` | GET | — | 模型列表 |
| `/v1/chat/completions` | POST | ✅ SSE | Chat Completions |
| `/v1/responses` | POST | ✅ SSE | Responses API（Codex 原生） |
| `/health` | GET | — | 健康检查 |

### 多轮对话

在请求中添加 `conversation_id` 扩展字段即可实现多轮对话复用：

```json
{
  "model": "monkeycode/OpenAI/gpt-4o",
  "messages": [{"role": "user", "content": "继续上一步"}],
  "conversation_id": "prev-task-id"
}
```

---

## 🔒 安全说明

1. **仅供本地开发测试使用** — 所有 API 端点无外部认证保护
2. **密码明文传输** — MonkeyCode 后端使用 bcrypt 验证，传输层由 HTTPS 保护
3. **Session Cookie 管理** — Session 30 天硬限制，无法刷新，到期需重新登录
4. **SCaptcha 服务不可用** — `admin-login.ts` 因证书问题临时关闭了 TLS 验证
5. **账号池安全** — 密码明文存储在内存/配置文件中，生产环境需加密存储

---

## ⚠️ 已知限制

| 限制 | 影响 | 解决方案 |
|------|------|---------|
| SCaptcha 余额不足 | 密码登录 / OAuth 自动化不可用 | 使用浏览器提取的 Session Cookie |
| Session 30 天过期 | 需定期重新获取 Session | 设置定时任务重新登录 |
| IMAGE_ID 必须（任务创建） | 任务创建失败 | 从浏览器 DevTools 获取 |
| 单用户 WS 独占锁 | 账号池 WS 锁可能泄漏 | 健康检查自动释放（已修复） |
| conversation API schema 未知 | 多轮对话仅部分支持 | 使用 `mode=new` + 手动传 conversation_id |

---

## 🤝 贡献

欢迎 Issue 和 PR！

- 如有新的协议发现，请在 `docs/protocol/` 下创建分析报告
- TypeScript 代理代码在 `proxy/src/` 中
- Python 验证脚本在 `mvp/` 中

---

## 📜 License

MIT License

---

<p align="center">
  <sub>Built with ❤️ for research and educational purposes.</sub>
</p>
