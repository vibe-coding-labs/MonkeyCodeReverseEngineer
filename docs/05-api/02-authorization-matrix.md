---
description: MonkeyCode 授权层级与 API 访问控制矩阵 — 基于 proxy/src/api-routes.ts + proxy/src/auth.ts + Go 源码
protocol_version: based on chaitin/MonkeyCode 开源后端源码 + proxy 源码
confidence: high
last_verified: 2026-06-28
---

# 授权层级与访问控制矩阵（源码增强版）

## 1. 双层的授权体系

MonkeyCode 存在**两套平行的授权体系**：后端层（Go）和代理层（TypeScript）。

### 1.1 后端 Go 授权体系

后端是真正的授权执行者，基于 **Cookie Session** + **中间件链**：

```
请求进入
    │
    ▼
Auth() 中间件
    │ Cookie → Redis Lookup Key → Redis Hash Key
    │ 提取 user_id, email, role
    │ 检查 session 是否过期
    │ 401 失败则返回（不继续）
    ▼
Role 检查（admin 端点额外检查 role === "admin"）
    │ 403 失败则返回
    ▼
TargetActive 中间件
    │ 检查用户 status === "active"
    │ "inactive" 或 "banded" 用户 403
    ▼
Handler（执行业务逻辑）
```

### 1.2 代理 TypeScript 授权体系

代理层有自己的**简化授权**，由于所有代理请求都通过同一个后端账号转发：

```
请求进入代理
    │
    ▼
模型检查（models.ts: resolveModel）
    │ 所有通过代理的请求共享同一个后端 Session
    │ 无用户级鉴权（代理不区分用户）
    ▼
任务创建（task-runner.ts: createTask）
    │ 使用号池中获取的 AuthManager
    │ 自动处理 Session 过期和重登录
    ▼
MonkeyCode 后端（真正的授权执行者）
```

## 2. 后端 Go 授权角色（5 种）

| 角色（role） | 中间件检查 | API 访问范围 | 典型用户 |
|-------------|-----------|-------------|---------|
| `individual` | Auth | /api/v1/users/* | 个人用户 |
| `enterprise` | Auth | /api/v1/users/* | 企业用户 |
| `subaccount` | Auth + 主账号校验 | /api/v1/users/*（受限） | 子账号 |
| `admin` | Auth + admin 角色 | /api/v1/admin/* | 管理员 |
| `gittask` | Auth + 特殊校验 | /api/v1/users/tasks/* | Git 任务机器人 |

### 2.1 用户状态（3 种）

| 状态（status） | 说明 | API 访问 |
|---------------|------|---------|
| `active` | 正常 | ✅ 允许 |
| `inactive` | 未激活/被禁用 | ❌ 拒绝（TargetActive 中间件） |
| `banded` | 被封禁 | ❌ 拒绝（TargetActive 中间件） |

### 2.2 团队成员角色（TeamMemberRole）

| 角色 | 说明 | Session Cookie |
|------|------|---------------|
| 团队管理员（`team_admin`） | 管理团队资源、成员 | `monkeycode_ai_team_session` |
| 团队成员（`team_member`） | 使用团队资源 | `monkeycode_ai_team_session` |

## 3. 代理层的实际权限模式

代理层通过不同的 AuthManager 实现两种访问模式：

### 3.1 单账号模式（开发/个人使用）

```typescript
// proxy/src/auth.ts
export class AuthManager {
  private sessionCookie: string = ""
  private sessionCookieName: string = "monkeycode_ai_session"
  private email: string = ""
  private passwordHash: string = ""
  private captchaToken: string = ""
  private lastAuthTime: number = 0
  private sessionTTL: number = 24 * 60 * 60 * 1000  // 代理侧的 24h Session TTL
  private loginMode: LoginMode = "user"

  constructor() {
    this.email = process.env.MONKEYCODE_EMAIL || process.env.MONKEYCODE_USERNAME || ""
    this.passwordHash = process.env.MONKEYCODE_PASSWORD_HASH || ""
    this.captchaToken = process.env.MONKEYCODE_CAPTCHA_TOKEN || ""

    // 明文密码支持
    const plainPassword = process.env.MONKEYCODE_PASSWORD || ""
    if (plainPassword && !this.passwordHash) {
      this.passwordHash = plainPassword.trim()
    }

    // Cookie 直接注入
    const existingCookie = process.env.MONKEYCODE_SESSION_COOKIE || ""
    if (existingCookie) {
      this.sessionCookie = existingCookie
      this.lastAuthTime = Date.now()
    }
  }

  // 获取当前 Cookie（过期自动重登录）
  async getSessionCookie(): Promise<string> {
    if (this.sessionCookie && Date.now() - this.lastAuthTime < this.sessionTTL) {
      return this.sessionCookie
    }
    await this.login()
    return this.sessionCookie
  }
}
```

**关键配置差异：**
- 后端 Session TTL：**30 天**（Redis 端硬限制，不可刷新）
- 代理 Session TTL：**24 小时**（仅代理侧缓存，实际 TTL 仍由后端控制）

### 3.2 号池模式（多用户/生产使用）

```typescript
// proxy/src/account-pool.ts
// HTTP 共享模式：取最久未用的活跃账号
acquireHttp(): AuthManager | null {
  const candidates = this.accounts
    .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
    .sort((a, b) => a.lastUsedAt - b.lastUsedAt)

  const idx = this.roundRobinIndex % candidates.length
  this.roundRobinIndex++
  const chosen = candidates[idx]
  chosen.lastUsedAt = Date.now()
  return chosen.auth
}

// WS 独占模式：锁定一个账号直到流结束
acquireWs(): AuthManager | null {
  const candidates = this.accounts
    .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
    .sort((a, b) => a.lastUsedAt - b.lastUsedAt)

  const chosen = candidates[0]
  chosen.lockedByWs = true   // 标记为 WS 独占
  chosen.lockedAt = Date.now()
  chosen.lastUsedAt = Date.now()
  return chosen.auth
}

// 释放 WS 独占锁
releaseWs(auth: AuthManager): void {
  const entry = this.findByAuth(auth)
  if (entry) {
    entry.lockedByWs = false
    entry.lockedAt = null
  }
}
```

## 4. 代理管理端点的权限现状

代理包含了**无内置认证的管理端点**，这对安全性有重要影响：

```typescript
// proxy/src/server.ts — 管理端点定义

// 设置 Session Cookie（可覆盖当前认证状态）
app.post("/admin/session", express.text(), (req, res) => {
  const cookie = req.body
  if (!cookie) {
    res.status(400).json({ error: "Cookie value required" })
    return
  }
  singleAuth?.setSessionCookie(cookie)
  res.json({ status: "ok", message: "Session cookie set" })
})

// OAuth 登录管理
app.post("/admin/login/send-code", async (req, res) => { ... })  // 发送短信验证码
app.post("/admin/login/verify", async (req, res) => { ... })     // 验证码登录
app.post("/admin/login/callback", async (req, res) => { ... })    // 回调登录

// 号池管理
app.get("/admin/pool/status", (_req, res) => { ... })             // 号池状态
app.post("/admin/pool/refresh", async (_req, res) => { ... })     // 刷新号池

// 模型管理
app.post("/admin/refresh-models", async (_req, res) => { ... })   // 刷新模型缓存
app.get("/admin/discover", async (_req, res) => { ... })          // 自动发现 image_id
```

**注意：** 以上端点均无认证检查。任何能访问代理端口的人都可以：
- 替换 Session Cookie（劫持会话）
- 读取号池状态（了解账号健康状况）
- 重新登录号池账号

## 5. AI SDK 的模型 ID 解析授权

代理层中 `modelManager.resolveModel()` 实现了 6 层回退解析：

```typescript
async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
  const models = await this.fetchModels()

  // 1. 精确匹配 monkeycode/provider/model
  const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
  if (exact) return exact

  // 2. provider/model 格式
  const byProviderModel = models.find(
    (m) => `${m.provider}/${m.model}` === openaiModelId
  )
  if (byProviderModel) return byProviderModel

  // 3. 模糊匹配 model 名称
  const byModelName = models.find((m) => m.model === openaiModelId)
  if (byModelName) return byModelName

  // 4. 匹配 display_name
  const byDisplayName = models.find((m) => m.display_name === openaiModelId)
  if (byDisplayName) return byDisplayName

  // 5. 回退到默认模型
  const defaultModel = models.find((m) => m.is_default)
  if (defaultModel) return defaultModel

  // 6. 最后的回退
  return models[0] || null
}
```

这意味着如果传递的 model_id 完全不存在，代理仍会返回模型列表中的第一个模型，而不是拒绝请求。

## 6. 实体级权限（Owner 机制）

### 6.1 模型所有权

| 类型 | 源码常量 | 说明 | 可见性 |
|------|---------|------|--------|
| 私有 | `private` | 用户个人创建 | 仅创建者 |
| 团队 | `team` | 团队共享 | 团队内成员 |
| 公开 | `public` | 管理员创建 | 所有认证用户 |

```typescript
// proxy/src/types.ts
export type OwnerType = "private" | "team" | "public"

// 模型的 API Key 可见性
// - public: API Key 被隐藏（只返回空字符串）
// - private: API Key 对创建者可见
// - team: API Key 对管理员可见
```

### 6.2 模型访问级别

```typescript
export type AccessLevel = "basic" | "pro" | "ultra"
```

| 级别 | 说明 | 可用模型 |
|------|------|---------|
| `basic` | 基础订阅 | 免费模型 + basic 模型 |
| `pro` | 专业订阅 | basic 模型 + pro 模型 |
| `ultra` | 高级订阅 | 所有模型 |

## 7. 中间件链代码级分析

### 7.1 Auth 中间件（Cookie → Redis 三跳查找）

```go
// middleware/auth.go（基于源码反推）
func Auth() gin.HandlerFunc {
    return func(c *gin.Context) {
        // 1. 从 Cookie 提取 session uuid
        cookie, err := c.Cookie("monkeycode_ai_session")
        if err != nil {
            c.AbortWithStatusJSON(401, Response{Code: 40100, Msg: "unauthorized"})
            return
        }

        // 2. Redis Lookup Key → user_id
        //    Key: session_lookup:{uuid}
        //    Value: user_id
        userID, err := redis.Get(fmt.Sprintf("session_lookup:%s", cookie))
        if err != nil {
            c.AbortWithStatusJSON(401, Response{Code: 40100, Msg: "session expired"})
            return
        }

        // 3. Redis Hash Key → 用户完整信息
        //    Key: session:{uuid}
        //    Fields: user_id, email, role, created_at, expires_at
        sessionData, err := redis.HGetAll(fmt.Sprintf("session:%s", cookie))
        if err != nil {
            c.AbortWithStatusJSON(401, Response{Code: 40100, Msg: "session not found"})
            return
        }

        // 4. 注入上下文
        c.Set("user_id", userID)
        c.Set("email", sessionData["email"])
        c.Set("role", sessionData["role"])
        c.Set("session_uuid", cookie)

        c.Next()
    }
}
```

### 7.2 admin 角色检查

```go
func AdminRequired() gin.HandlerFunc {
    return func(c *gin.Context) {
        role := c.GetString("role")
        if role != "admin" {
            c.AbortWithStatusJSON(403, Response{Code: 40300, Msg: "forbidden"})
            return
        }
        c.Next()
    }
}
```

### 7.3 代理层的自动回复（代替用户授权）

在多轮对话和任务执行中，代理层自动回复 Agent 的用户确认请求，实现**完全自动化**：

```typescript
// proxy/src/task-runner.ts — 自动回复用户问题
ws.on("open", () => {
  // 启用自动审批模式
  ws.send(JSON.stringify({ type: "auto-approve" }))
  // 发送用户输入
  ws.send(JSON.stringify({ type: "user-input", data: prompt }))
})

// 处理 Agent 的用户确认请求
if (msg.kind === "acp_ask_user_question") {
  const questionData = JSON.parse(msg.data)
  ws.send(JSON.stringify({
    type: "reply-question",
    data: JSON.stringify({
      request_id: questionData.request_id,
      answers_json: "",
      cancelled: false,  // 不取消，自动继续
    }),
  }))
}
```

## 8. 授权推荐与安全建议

### 8.1 反向代理场景的账号选择

**对于 LLM 反向代理场景，推荐使用个人用户账号**：
- 需要的核心 API：模型列表 + 任务创建/流/控制
- 这些 API 全部在用户级端点下，不需要团队或管理员权限
- 团队级 API 不需要（如团队管理、批量邀请）
- 管理员 API 不需要（除非要在代理中创建公开模型）

### 8.2 安全加固建议

| 风险 | 建议措施 |
|------|---------|
| 代理管理端点无认证 | 设置 Express trust proxy，仅允许内部 IP |
| | 或添加自定义认证中间件 |
| 共享 Session 泄露 | 代理绑定到 127.0.0.1 |
| | 使用 iptables 限制访问来源 |
| 号池文件明文密码 | `chmod 600 accounts.json` |
| | 或使用环境变量注入配置 |
| WebSocket 未加密 | 使用 WSS（通过 nginx 反向代理） |

---

## 相关章节

- [认证中间件](../02-auth/05-auth-middleware.md) — Auth() 中间件 Go 源码
- [完整 API 端点目录](01-endpoint-catalog.md) — 所有端点概览
- [Admin 管理 API](05-admin-management-api.md) — Admin 端点的 CRUD 操作
- [代理架构实现](../07-proxy/01-architecture.md) — 代理层代码结构