---
description: 第 1-6 轮逆向分析过程记录 — 从 ASAR 解包到 WebSocket 协议确认
protocol_version: based on chaitin/MonkeyCode 开源后端源码 + 代理 TS 源码
confidence: high
last_verified: 2026-06-28
---

# 分析轮次 1-6 合并 — 扩增版

> **分析周期:** 2026-05-10 — 2026-05-15
> **覆盖:** ASAR 解包 → API 端点发现 → 密码登录 → 架构确认 → 提供商列表 → TaskFlow VM → WebSocket
> **原始档案:** `docs/protocol/analysis-round-01.md` ~ `docs/protocol/analysis-round-06.md`
> **代理源码:** `proxy/src/` 10 个 TypeScript 文件 (~3,031 行)

---

## 轮次 1: ASAR 解包发现 API 端点

**目标**: 解包 MonkeyCode 桌面客户端 Electron ASAR 文件，发现通信协议端点

### ASAR 解包过程

```bash
# 使用 asar 工具解包 Electron 应用
npx asar extract monkeycode.asar ./extracted-asar

# 解包后目录结构:
# extracted-asar/
# ├── package.json
# ├── main.js          # Electron 主进程
# ├── renderer.js      # 渲染进程
# └── node_modules/    # 依赖模块
```

### 从 main.js 发现的 API 端点

```typescript
// 从 Electron 主进程 main.js 中提取的 API 端点模式
const API_BASE = "https://monkeycode-ai.com/api/v1"

// 认证端点
const AUTH_ENDPOINTS = {
  passwordLogin: `${API_BASE}/users/password-login`,
  teamLogin: `${API_BASE}/teams/users/login`,
  userStatus: `${API_BASE}/users/status`,
  logout: `${API_BASE}/users/logout`,
  oauthCallback: `${API_BASE}/users/oauth/callback`,
}

// 模型端点
const MODEL_ENDPOINTS = {
  listModels: `${API_BASE}/users/models?limit=100`,
  createModel: `${API_BASE}/users/models`,
  updateModel: `${API_BASE}/users/models/{id}`,
  deleteModel: `${API_BASE}/users/models/{id}`,
}

// 任务端点
const TASK_ENDPOINTS = {
  createTask: `${API_BASE}/users/tasks`,
  stopTask: `${API_BASE}/users/tasks/stop`,
  taskStream: `${API_BASE}/users/tasks/stream?id={taskId}&mode={mode}`,
  taskControl: `${API_BASE}/users/tasks/control?id={taskId}`,
  taskList: `${API_BASE}/users/tasks?page={page}&size={size}`,
}
```

### 关键发现

| 发现 | 说明 |
|------|------|
| Session Cookie 名 | `monkeycode_ai_session`（用户）/ `monkeycode_ai_team_session`（团队） |
| 基础 URL | `https://monkeycode-ai.com` |
| 通信协议 | REST + WebSocket 混合 |
| 认证方式 | Cookie-based Session，Set-Cookie 响应头 |
| 流式传输 | WebSocket (`wss://monkeycode-ai.com/api/v1/users/tasks/stream`) |

### WebSocket 连接发现

```javascript
// 从 main.js 提取的 WebSocket 连接逻辑
const wsUrl = `wss://monkeycode-ai.com/api/v1/users/tasks/stream?id=${taskId}&mode=new`
const ws = new WebSocket(wsUrl, {
  headers: {
    Cookie: "monkeycode_ai_session=xxx",
  },
})

// 连接后发送的消息格式
ws.onopen = () => {
  ws.send(JSON.stringify({ type: "auto-approve" }))
  ws.send(JSON.stringify({
    type: "user-input",
    data: "用户消息内容",
  }))
}
```

---

## 轮次 2: 密码登录 + Session Cookie 机制

**目标**: 验证密码登录流程和 Session Cookie 管理机制

### 登录请求/响应

```http
POST /api/v1/users/password-login HTTP/1.1
Host: monkeycode-ai.com
Content-Type: application/json
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)

{
  "email": "user@example.com",
  "password": "plaintext_password",
  "captcha_token": "optional_captcha_token"
}

→ HTTP/1.1 302 Found
Location: /dashboard
Set-Cookie: monkeycode_ai_session=uuid-session-id; Path=/; HttpOnly; Secure; SameSite=Lax
```

### 团队登录

```http
POST /api/v1/teams/users/login HTTP/1.1
Host: monkeycode-ai.com
Content-Type: application/json

{
  "email": "admin@company.com",
  "password": "plaintext_password",
  "captcha_token": "optional_captcha_token"
}

→ HTTP/1.1 302 Found
Set-Cookie: monkeycode_ai_team_session=uuid-session-id; Path=/; HttpOnly
```

### Session Cookie 三跳查找（代理源码实现）

```typescript
// 摘自 proxy/src/auth.ts — AuthManager 核心实现
// Cookie 提取逻辑
private extractCookie(response: Response, cookieName: string): string {
  const setCookie = response.headers.get("set-cookie")
  if (!setCookie) {
    throw new Error("No Set-Cookie header in login response")
  }

  const match = setCookie.match(new RegExp(`${cookieName}=([^;]+)`))
  if (!match) {
    throw new Error(`Cannot extract ${cookieName} from Set-Cookie: ${setCookie}`)
  }

  return match[1]
}
```

### Cookie 会话管理

```typescript
// 摘自 proxy/src/auth.ts — 会话 TTL 管理
// 环境中已有 Cookie 直接使用
const existingCookie = process.env.MONKEYCODE_SESSION_COOKIE || ""
if (existingCookie) {
  this.sessionCookie = existingCookie
  this.lastAuthTime = Date.now()
}

// 获取会话 Cookie，过期则自动重新登录
async getSessionCookie(): Promise<string> {
  if (this.sessionCookie && Date.now() - this.lastAuthTime < this.sessionTTL) {
    return this.sessionCookie  // 24h 内有效，直接返回
  }
  await this.login()  // 过期则重新登录
  return this.sessionCookie
}
```

---

## 轮次 3: 三层架构确认

**目标**: 确认 MonkeyCode 的整体系统架构

### 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     客户端层 (Client Layer)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ Electron │  │  Web UI  │  │  CLI     │  │ OpenAI SDK/Codex  │ │
│  │  Desktop │  │ (React)  │  │ (curl)   │  │ (通过代理)        │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘ │
│       │             │             │                   │          │
│       └─────────────┴─────────────┴───────────────────┘          │
│                            │ HTTP/WS                             │
├────────────────────────────┼─────────────────────────────────────┤
│                     后端层 (Backend — Go)                        │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Auth Middleware  →  Session Lookup → Redis Hash + Lookup   │ │
│  │  API Router  →  /api/v1/users/*  /api/v1/teams/*           │ │
│  │  Model Manager  →  CRUD + Provider Router                  │ │
│  │  Task Creator  →  VM 调度 + WebSocket 隧道                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                            │                                     │
├────────────────────────────┼─────────────────────────────────────┤
│                    TaskFlow VM 层 (Docker 容器)                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Agent (Codex/Claude/OpenCode)  ←  NPM 包                    │ │
│  │  MCP Server  ←  JSON-RPC 2.0 协议                            │ │
│  │  LLM Client  ←  3 种 SDK 自动选择                             │ │
│  │  PTY 终端  ←  WebSocket 二进制帧隧道                          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                            │                                     │
├────────────────────────────┼─────────────────────────────────────┤
│                    LLM 提供商层 (LLM Provider Layer)              │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  11 个提供商: OpenAI / Anthropic / DeepSeek / SiliconFlow   │ │
│  │  / Moonshot / Ollama / Azure / 百智云 / 混元 / 百炼 / 火山   │ │
│  │  3 种接口: openai_chat / openai_responses / anthropic       │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 代理层模块依赖图

```typescript
// 代理模块依赖关系
// server.ts          ← 入口，初始化所有模块
//   ├── auth.ts      ← AuthManager: Cookie 认证
//   ├── models.ts    ← ModelManager: 模型发现
//   ├── task-runner.ts ← TaskRunner: 任务创建 + WS 流
//   ├── account-pool.ts ← AccountPool: 多账号管理
//   ├── conversation-manager.ts ← ConversationManager: 多轮对话
//   ├── admin-login.ts ← OAuth 登录自动化
//   ├── browser-headers.ts ← 浏览器指纹伪装
//   ├── types.ts     ← 类型定义
//   └── api-routes.ts ← OpenAI 兼容 API 路由
```

---

## 轮次 4: 11 个提供商 + 3 种接口类型确认

**目标**: 确认 MonkeyCode 支持的 LLM 提供商和接口类型

### 提供商联合类型

```typescript
// 摘自 proxy/src/types.ts — 代理商定义的提供商类型
export type ModelProvider =
  | "siliconflow"
  | "openai"
  | "ollama"
  | "deepseek"
  | "moonshot"
  | "azure_openai"
  | "baizhicloud"
  | "hunyuan"
  | "bailian"
  | "volcengine"
  | "gemini"
  | "other"
```

### 三种接口类型

```typescript
// 摘自 proxy/src/types.ts — 接口类型枚举
export type InterfaceType = "openai_chat" | "openai_responses" | "anthropic"

// 接口类型 → SDK 映射
// openai_chat       → sashabaranov/go-openai (ChatCompletion)
// openai_responses  → 原生 HTTP (Responses API)
// anthropic         → anthropics/anthropic-sdk-go (Messages API)
```

### 模型 ID 解析策略

```typescript
// 摘自 proxy/src/models.ts — 6 层回退解析
// 格式: monkeycode/{provider}/{model}
toOpenAIModelId(m: MonkeyCodeModel): string {
  return `monkeycode/${m.provider}/${m.model}`
}

// 6 层解析回退
async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
  const models = await this.fetchModels()

  // 第 1 层: 精确匹配 monkeycode/provider/model
  const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
  if (exact) return exact

  // 第 2 层: 匹配 provider/model
  const byProviderModel = models.find((m) => `${m.provider}/${m.model}` === openaiModelId)
  if (byProviderModel) return byProviderModel

  // 第 3 层: 模糊匹配 model 名称
  const byModelName = models.find((m) => m.model === openaiModelId)
  if (byModelName) return byModelName

  // 第 4 层: 匹配 display_name
  const byDisplayName = models.find((m) => m.display_name === openaiModelId)
  if (byDisplayName) return byDisplayName

  // 第 5 层: 默认模型
  const defaultModel = models.find((m) => m.is_default)
  if (defaultModel) return defaultModel

  // 第 6 层: 返回第一个模型
  return models[0] || null
}
```

### MonkeyCodeModel 完整结构

```typescript
// 摘自 proxy/src/types.ts — 模型数据结构
export interface MonkeyCodeModel {
  id: string            // UUID
  provider: ModelProvider // 提供商
  api_key: string       // API 密钥
  base_url: string      // 基础 URL
  model: string         // 模型名称
  temperature: number   // 温度参数
  is_default: boolean   // 是否默认
  interface_type: InterfaceType // 接口类型
  is_free: boolean      // 是否免费
  access_level: AccessLevel // basic/pro/ultra
  thinking_enabled: boolean // 是否启用思考
  context_limit: number // 上下文限制
  output_limit: number  // 输出限制
  owner: OwnerType      // private/team/public
  name: string          // 名称
  display_name: string  // 显示名称
  description: string   // 描述
}
```

---

## 轮次 5: TaskFlow VM 生命周期分析

**目标**: 理解 TaskFlow VM 的完整生命周期

### VM 状态机

```
创建任务 (POST /api/v1/users/tasks)
  │
  ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ PENDING  │───▶│ STARTING │───▶│ RUNNING  │───▶│ STOPPED  │
│ (创建)   │    │ (启动)   │    │ (运行)   │    │ (停止)   │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                    │
                                    │ (超时/错误)
                                    ▼
                                ┌──────────┐
                                │  ERROR   │
                                │ (错误)   │
                                └──────────┘
```

### 任务创建请求格式

```json
{
  "content": "用户提示词",
  "host_id": "public_host",
  "image_id": "docker-image-uuid",
  "model_id": "model-uuid",
  "cli_name": "codex",
  "resource": {
    "core": 1,
    "memory": 1073741824,
    "life": 3600
  },
  "repo": {
    "repo_url": "",
    "branch": "master",
    "repo_filename": "",
    "zip_url": ""
  },
  "system_prompt": "可选的系统提示词"
}
```

### 代理层任务创建源码

```typescript
// 摘自 proxy/src/task-runner.ts — 任务创建
async createTask(
  model: MonkeyCodeModel,
  prompt: string,
  options?: {
    hostId?: string
    imageId?: string
    systemPrompt?: string
    authOverride?: AuthManager
  }
): Promise<string> {
  const auth = options?.authOverride || this.auth
  const headers = await auth.authHeaders()
  const url = `${MONKEYCODE_BASE_URL}/api/v1/users/tasks`

  const hostId = options?.hostId || DEFAULT_HOST_ID
  const imageId = process.env.MONKEYCODE_IMAGE_ID || options?.imageId || DEFAULT_IMAGE_ID

  // cli_name 根据 interface_type 动态选择
  const body: Record<string, unknown> = {
    content: prompt,
    host_id: hostId,
    image_id: imageId,
    model_id: model.id,
    cli_name: model.interface_type === "openai_responses" ? "codex"
      : model.interface_type === "anthropic" ? "claude"
      : "opencode",
    resource: { core: 1, memory: 1073741824, life: 3600 },
    repo: { repo_url: "", branch: "master", repo_filename: "", zip_url: "" },
  }

  if (options?.systemPrompt) {
    body.system_prompt = options.systemPrompt
  }

  const response = await fetch(url, {
    method: "POST",
    headers: mkHeaders(headers),
    body: JSON.stringify(body),
  })

  // 业务错误码处理（如 code=10811 已有运行任务）
  const result = await response.json()
  if (result.code && result.code !== 0) {
    throw new Error(`Failed to create task (code ${result.code}): ${result.message}`)
  }
  const data = result.data || result
  return data.id || data.task_id
}
```

---

## 轮次 6: WebSocket Task Stream 协议确认

**目标**: 确认 WebSocket 协议的握手和消息帧格式

### WebSocket 连接握手

```typescript
// 摘自 proxy/src/task-runner.ts — WebSocket 连接
// HTTP URL 转 WebSocket URL
function httpToWs(url: string): string {
  return url.replace(/^https?/, (m) => (m === "https" ? "wss" : "ws"))
}

// 建立 WebSocket 连接
const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=new`

const ws = new WebSocket(wsUrl, {
  headers: wsHeaders("monkeycode-ai.com",
    `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`),
})
```

### WebSocket 消息帧格式

```typescript
// 摘自 proxy/src/types.ts — WebSocket 消息类型
export interface TaskStreamMessage {
  type: string    // 消息类型
  data: string    // JSON 字符串或纯文本
  kind?: string   // 子类型（如 "acp_event"）
  timestamp?: number
}

export interface UserInputMessage {
  type: "user-input"
  data: string    // 用户输入内容
}

export interface UserCancelMessage {
  type: "user-cancel"
  data: string
}
```

### 消息流时序

```
Client → Server:
  { type: "auto-approve" }           ← 启用自动审批
  { type: "user-input", data: "..." } ← 发送用户输入

Server → Client (心跳):
  { type: "ping" }                    ← 服务端心跳
Client → Server:
  { type: "ping" }                    ← 客户端心跳响应

Server → Client (任务事件):
  { type: "task-started", data: "...", kind: "..." }
  { type: "task-running", data: "...", kind: "acp_event" }
  { type: "task-running", data: "...", kind: "acp_ask_user_question" }
  { type: "task-ended", data: "..." }

Server → Client (错误):
  { type: "task-error", data: "错误描述" }
```

### 两种 mode 对比

| 特性 | mode=new | mode=attach |
|------|---------|------------|
| 用途 | 创建新任务 | 复用已有任务 |
| VM 生命周期 | 创建新 VM | 复用已有 VM |
| 适用场景 | 首次对话 | 多轮对话 |
| 代理实现 | TaskRunner.streamTask | ConversationManager.connectToTask |

---

## 本阶段总结

| 轮次 | 关键产出 | 后续影响 |
|------|---------|---------|
| 1 | ASAR 解包，发现 API 端点和 WS 协议 | 启动整个逆向项目 |
| 2 | 密码登录 + Session Cookie 机制确认 | 实现 AuthManager |
| 3 | 三层架构确认 | 架构图指导后续分析 |
| 4 | 11 个提供商 + 3 种接口类型 | 实现 ModelManager |
| 5 | TaskFlow VM 生命周期 | 实现 TaskRunner |
| 6 | WebSocket 协议握手 + 消息帧 | 实现 WS 流式输出 |

## 相关章节

- [原始分析档案 (docs/protocol/)](../../protocol/README.md)
- [代理架构实现](../../07-proxy/01-architecture.md)
- [WebSocket 协议](../../04-websocket/README.md)