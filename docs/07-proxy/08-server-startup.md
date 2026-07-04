---
description: 代理层 server.ts 启动序列、中间件链、管理端点、OAuth 路由——基于完整源码分析
protocol_version: based on proxy/src/server.ts (331 行)
confidence: high
last_verified: 2026-06-28
---

# 代理启动与中间件链（server.ts 源码分析）

> **源码文件:** `proxy/src/server.ts` — 331 行
> **分析覆盖:** 100%（完整覆盖）
> **核心发现:** 7 步启动序列、12 个端点注册、3 层中间件链、号池/单账号双模式初始化、OAuth 登录端点组

## 1. 架构概述

`server.ts` 是整个 TypeScript 代理的**入口和编排器**。它不负责具体业务逻辑，而是完成以下职责：

1. **初始化** — 号池或单账号认证、ModelManager、TaskRunner、ConversationManager
2. **路由注册** — 将所有 OpenAI 兼容端点和 Admin 管理端点注册到 Express
3. **中间件链** — 配置 CORS、JSON 解析、错误处理
4. **启动服务器** — 绑定端口并输出使用信息

### 依赖图谱

```
server.ts（主入口）
  ├── auth.ts          → AuthManager（Session 管理）
  ├── models.ts        → ModelManager（模型缓存与解析）
  ├── task-runner.ts   → TaskRunner（任务创建与 WS 流）
  ├── account-pool.ts  → AccountPool（多账号轮转）
  ├── conversation-manager.ts → ConversationManager（多轮对话）
  ├── api-routes.ts    → createAPIRouter（OpenAI 兼容路由）
  ├── admin-login.ts   → 6 个 OAuth 自动化函数
  └── types.ts         → 全部类型定义
```

## 2. 完整启动序列（7 步）

```
server.ts main()
  │
  ├── 第 1 步：解析环境变量（PORT, MONKEYCODE_BASE_URL, ACCOUNT_POOL_FILE 等）
  │
  ├── 第 2 步：初始化号池或单账号
  │     ├── ACCOUNT_POOL_FILE 存在？→ 加载账号配置 JSON
  │     ├── 环境变量 MONKEYCODE_EMAIL+PASSWORD 存在？→ 添加单账号
  │     ├── 是号池模式？→ new AccountPool(accounts), await initAll(), startHealthCheck()
  │     └── 纯单账号模式？→ new AuthManager()
  │
  ├── 第 3 步：创建核心模块实例
  │     ├── new ModelManager(auth) — 模型管理
  │     └── new TaskRunner(auth) — 任务执行
  │
  ├── 第 4 步：尝试登录 + 获取模型列表
  │     ├── 单账号模式 → await auth.getSessionCookie()
  │     └── 获取模型 → await modelManager.fetchModels()
  │
  ├── 第 5 步：配置 Express 中间件链
  │     ├── cors() — 跨域
  │     ├── express.json({ limit: "10mb" }) — JSON body 解析
  │     └── 路由注册 → createAPIRouter(...)
  │
  ├── 第 6 步：注册管理端点（12 个）
  │     ├── /admin/session, /admin/refresh-models
  │     ├── /admin/pool/status, /admin/pool/refresh
  │     ├── /admin/login/send-code, /admin/login/verify, /admin/login/callback
  │     └── /admin/discover
  │
  └── 第 7 步：监听端口 → 输出使用说明
```

### 第 2 步详析：号池 vs 单账号的初始化代码

```typescript
// proxy/src/server.ts — 启动序列第 2 步
async function main() {
  // 1. 尝试从 ACCOUNT_POOL_FILE 文件加载号池
  const poolFile = process.env.ACCOUNT_POOL_FILE || ""
  let accounts: AccountConfig[] = []

  if (poolFile) {
    const resolved = path.resolve(poolFile)
    accounts = await loadAccountConfigs(resolved)
    console.log(`[Init] Loaded ${accounts.length} accounts from ${resolved}`)
  }

  // 2. 从环境变量加载单个账号（放入同一数组）
  const envAccount = loadAccountFromEnv()
  if (envAccount) {
    accounts.push(envAccount)
  }

  // 3. 决策：号池模式 vs 单账号模式
  if (accounts.length > 0) {
    accountPool = new AccountPool(accounts)
    await accountPool.initAll()
    accountPool.startHealthCheck()
    singleAuth = accountPool.acquireHttp() ?? undefined // 取第一个用于模型查询
  } else {
    singleAuth = new AuthManager() // 纯单账号
  }
}
```

**关键设计决策：** 即使配置了号池，代理也会使用号池的第一个账号作为 `ModelManager` 的认证源。号池和单账号并非互斥模式——文件账号和环境变量账号被合并到同一数组。

### 第 5 步详析：中间件链

```typescript
// Express 中间件链
const app = express()
app.use(cors())                            // 第一层：允许所有来源跨域
app.use(express.json({ limit: "10mb" }))   // 第二层：JSON body 解析（10MB 限制）
app.use(createAPIRouter(...))               // 第三层：路由（内含 try/catch 错误处理）
```

| 中间件 | 用途 | 安全考量 |
|--------|------|---------|
| `cors()` | 允许任意来源跨域 | ⚠️ 生产环境应限制来源 |
| `express.json({ limit: "10mb" })` | 解析 JSON 请求体 | ✅ 10MB 限制防止大 payload 攻击 |
| API 路由内的 try/catch | 统一错误响应 | ✅ 防止未捕获异常导致进程退出 |

> **注意:** 与常规 Express 应用不同，server.ts **没有**全局错误处理中间件。每个路由处理函数内部自己捕获错误。`res.headersSent` 保护防止重复写入。

## 3. 完整的 12 个管理端点

### 3.1 Session 管理

```typescript
// POST /admin/session — 手动设置 Session Cookie
// 用途：从浏览器复制 Cookie 直接注入代理
app.post("/admin/session", express.text(), (req, res) => {
  const cookie = req.body
  if (!cookie) {
    res.status(400).json({ error: "Cookie value required" })
    return
  }
  singleAuth?.setSessionCookie(cookie)   // 设置到单账号 AuthManager
  res.json({ status: "ok", message: "Session cookie set" })
})
```

### 3.2 模型缓存管理

```typescript
// POST /admin/refresh-models — 刷新模型缓存
// 用途：管理员在后台添加模型后手动刷新
app.post("/admin/refresh-models", async (_req, res) => {
  modelManager.clearCache()              // 清除 5 分钟缓存
  const models = await modelManager.fetchModels()
  res.json({ status: "ok", count: models.length })
})
```

### 3.3 号池管理

```typescript
// GET /admin/pool/status — 查看号池状态
// 返回：{ total: N, active: N, expired: N, invalid: N, locked: N }
app.get("/admin/pool/status", (_req, res) => {
  if (!accountPool) {
    res.json({ mode: "single" })
    return
  }
  const stats = accountPool.getStats()
  res.json({ mode: "pool", ...stats })
})

// POST /admin/pool/refresh — 重新登录所有号池账号
// 用途：批量刷新过期 Session
app.post("/admin/pool/refresh", async (_req, res) => {
  accountPool.stopHealthCheck()
  await accountPool.initAll()
  accountPool.startHealthCheck()
  res.json({ status: "ok", ...accountPool.getStats() })
})
```

### 3.4 OAuth 登录端点组（3 个）

| 端点 | 功能 | admin-login.ts 函数 | 请求体 |
|------|------|-------------------|--------|
| `POST /admin/login/send-code` | 发送短信验证码 | `initiateLogin(phone)` | `{"phone": "138..."}` |
| `POST /admin/login/verify` | 验证短信码 | `completeLogin(code)` | `{"code": "123456"}` |
| `POST /admin/login/callback` | 使用回调 URL | `loginWithCallbackUrl(url)` | `{"callbackUrl": "..."}` |

**自动发现链（/admin/login/verify 成功后的回写机制）：**

```typescript
app.post("/admin/login/verify", async (req, res) => {
  const result = await completeLogin(code)

  // 1. 自动注入 Session Cookie
  if (singleAuth) {
    singleAuth.setSessionCookie(result.sessionCookie)
  }

  // 2. 自动设置 image_id 到环境变量（持久化！）
  if (result.imageId) {
    process.env.MONKEYCODE_IMAGE_ID = result.imageId
    console.log(`[Login] Auto-discovered image_id: ${result.imageId}`)
  }

  // 3. 自动刷新模型缓存
  modelManager.clearCache()
  await modelManager.fetchModels()

  // 4. 返回完整登录结果
  res.json({
    sessionCookie: result.sessionCookie,
    imageId: result.imageId,
    imageName: result.imageName,
    modelCount: result.models?.length || 0,
    user: { id, name, email, role },
  })
})
```

### 3.5 自动发现端点

```typescript
// GET /admin/discover — 用已有 Session 自动发现配置
// 并行调用两个发现函数
app.get("/admin/discover", async (_req, res) => {
  const cookie = singleAuth?.getSessionCookieSync()
  if (!cookie) {
    res.status(400).json({ error: "No session cookie. Login first." })
    return
  }

  const [imageResult, models] = await Promise.all([
    discoverImageId(cookie),    // 发现 image_id
    discoverModels(cookie),     // 发现模型列表
  ])

  if (imageResult) {
    process.env.MONKEYCODE_IMAGE_ID = imageResult.imageId
  }

  res.json({
    imageId: imageResult?.imageId || null,
    imageName: imageResult?.imageName || null,
    models: models.map(m => ({
      id: m.id, model: m.model, provider: m.provider,
      display_name: m.display_name, is_free: m.is_free,
    })),
  })
})
```

## 4. OpenAI 兼容路由注册

通过 `createAPIRouter()` 注册到 Express：

```typescript
// 路由由 api-routes.ts 管理，传入所有依赖
app.use(createAPIRouter(modelManager, taskRunner, accountPool, conversationManager))
```

函数签名：
```typescript
export function createAPIRouter(
  modelManager: ModelManager,
  taskRunner: TaskRunner,
  accountPool?: AccountPool,
  conversationManager?: ConversationManager
): Router
```

`accountPool` 和 `conversationManager` 是**可选的**（`?`），这意味着代理可以在没有号池和多轮对话能力的情况下运行。

## 5. 完整的启动输出

```text
=== MonkeyCode Reverse Proxy ===
Target: https://monkeycode-ai.com
Port: 9090

[Init] Loaded 5 accounts from accounts.json
[Init] Added account from env: user@example.com
[Init] Init complete: 5/5 succeeded
[AccountPool] Status: 5/5 active, 0 expired, 0 invalid, 0 ws-locked
[AccountPool] Health check started (interval: 60min)
[Init] Available models: 23
  - siliconflow/Qwen/Qwen3.5-Plus (openai_chat, public)
  - siliconflow/Pro/deepseek-ai/DeepSeek-V3-0324 (openai_chat, public)
  - openai/gpt-4o (openai_chat, public)
  - deepseek/deepseek-chat (openai_chat, public)
  - anthropic/claude-sonnet-4-20250514 (anthropic, public)
  ... and 18 more
[Init] ConversationManager initialized

MonkeyCode Reverse Proxy running on http://localhost:9090

Endpoints:
  GET  /v1/models            - List available models
  POST /v1/chat/completions  - Chat completion (streaming supported)
  POST /v1/responses         - Responses API (Codex native, streaming)
  GET  /health               - Health check
  POST /admin/session        - Set session cookie manually
  POST /admin/login/send-code  - Send SMS code (百智云 OAuth)
  POST /admin/login/verify     - Verify SMS code + login
  POST /admin/login/callback   - Login with OAuth callback URL
  GET  /admin/discover         - Auto-discover image_id & models
  POST /admin/refresh-models - Refresh model cache
  GET  /admin/pool/status    - Account pool status
  POST /admin/pool/refresh   - Re-login all pool accounts

Usage with OpenAI SDK:
  OPENAI_API_KEY=any OPENAI_BASE_URL=http://localhost:9090/v1
```

## 6. 异常情况分析

| 情景 | 行为 | 日志输出 |
|------|------|---------|
| 无 ACCOUNT_POOL_FILE、无 ENV 账号 | 空号池 → 单账号模式 → 启动时自动登录 | `[Init] Authentication successful/failed` |
| ACCOUNT_POOL_FILE 加载失败 | 仅 warning，不退出进程 | `[Init] Failed to load account pool file...` |
| 单账号登录失败 | warning，服务继续运行 | `[Init] Authentication failed... Proxy will start...` |
| 模型列表获取失败 | warning，服务继续运行 | `[Init] Failed to fetch models...` |
| fatal 顶层错误 | 进程退出 | `Fatal error: ...` |

这种"**启动时宽容**"设计确保代理即使部分初始化失败也能启动，方便运维人员后续通过管理端点修复。

## 7. 安全分析

| 安全问题 | 现状 | 建议 |
|---------|------|------|
| CORS 全开放 | `cors()` 无配置 → 允许所有来源 | 生产环境应 `cors({ origin: "..." })` |
| API Key 验证 | 代理不验证 API Key（接受任意值） | 设计如此（透明代理） |
| 管理端点无认证 | 所有 `/admin/*` 路径无任何认证 | 应添加 IP 白名单或简单 Token |
| image_id 写入 env | `process.env` 变更影响进程全局 | 仅影响当前进程，可接受 |
| 错误信息泄露 | 错误信息直接返回给客户端 | 生产环境应限制详细程度 |

---

## 相关章节

- [代理架构设计](01-architecture.md) — 10 个模块的职责与调用关系
- [API 路由源码分析](../05-api/01-endpoint-catalog.md) — api-routes.ts 完整路由
- [AuthManager 源码](auth.ts) — Session 管理
- [号池管理源码](02-account-pool.md) — 多账号轮转
- [OAuth HTTP 自动化](06-oauth-automation-http.md) — 6 步登录流程
