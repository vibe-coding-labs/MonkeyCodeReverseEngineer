---
description: 认证中间件体系分析 — 后端 Go 中间件 + 代理层 auth.ts 双视角
protocol_version: based on chaitin/MonkeyCode + proxy/src/auth.ts + proxy/src/server.ts
confidence: high
last_verified: 2026-06-28
---

# 认证中间件体系（源码增强版）

## 1. 双认证体系架构

MonkeyCode 的认证中间件有两层：**后端 Go 中间件**（真正的认证执行者）和**代理层认证管理**（Cookie 生命周期管理器）。

```
后端 Go 认证链                        代理 TypeScript 认证
────────────────                      ────────────────────
Auth() 中间件                          AuthManager 类
├── Cookie 存在？                      ├── getSessionCookie()
├── → 否: 401                         │   ├── 缓存命中？→ 返回
├── → 是: Redis GET                    │   └── 过期 → login()
│   ├── Lookup Key → user_id          ├── loginUser()
│   └── Hash Key → session data       │   └── POST password-login
├── role 检查                          ├── loginTeam()
│   └── admin? → admin 端点           │   └── POST teams/login
├── TargetActive()                     ├── checkStatus()
│   ├── Redis 写入活跃时间             │   └── GET /users/status
│   └── Redis 写入活跃 IP              ├── authHeaders()
└── Handler()                          │   └── Cookie + Content-Type
                                       └── logout()
                                           └── POST /users/logout
```

## 2. 后端 Go 中间件

### 2.1 中间件类型

| 中间件 | 方法 | 行为 | 使用场景 |
|--------|------|------|---------|
| `Auth()` | 强制认证 | 未登录返回 401 | 大部分用户 API |
| `Check()` | 可选认证 | 未登录继续，context 无用户 | 公开流、可选认证端点 |
| `TeamAuth()` | 强制团队认证 | 未登录或无团队返回 401 | 团队管理 API |
| `TeamAuthCheck()` | 可选团队认证 | 未登录返回 401，无团队返回 401 | 团队可选端点 |
| `TeamAdminAuth()` | 团队管理员授权 | 需 TeamAuth + admin 权限 | 团队管理操作 |

### 2.2 完整的中间件代码（根据源码反推）

```go
// backend/middleware/auth.go
func Auth() gin.HandlerFunc {
    return func(c *gin.Context) {
        // 1. 从 Cookie 提取 session uuid
        cookie, err := c.Cookie("monkeycode_ai_session")
        if err != nil {
            c.AbortWithStatusJSON(401, Response{Code: 40100, Msg: "Unauthorized"})
            return
        }

        // 2. Redis Lookup Key → user_id
        //    Key: lookup:{cookie_name}:{cookie_uuid}
        //    Value: user_id (UUID)
        userID, err := redis.Get(ctx, fmt.Sprintf("lookup:%s:%s", cookieName, cookie))
        if err != nil {
            c.AbortWithStatusJSON(401, Response{Code: 40100, Msg: "Session expired"})
            return
        }

        // 3. Redis Hash Key → 用户完整信息
        //    Key: {cookie_name}:{user_id}
        //    Field: {cookie_uuid}
        //    Value: {user_id, email, role, subscription_level, created_at}
        sessionData, err := redis.HGetAll(ctx, fmt.Sprintf("%s:%s", cookieName, userID))
        if err != nil {
            c.AbortWithStatusJSON(401, Response{Code: 40100, Msg: "Session not found"})
            return
        }

        // 4. 注入用户上下文
        c.Set("user_id", userID)
        c.Set("email", sessionData["email"])
        c.Set("role", sessionData["role"])
        c.Set("subscription_level", sessionData["subscription_level"])
        c.Next()
    }
}
```

### 2.3 活跃追踪中间件（TargetActive）

```go
func TargetActive() gin.HandlerFunc {
    return func(c *gin.Context) {
        user := c.Get("user").(*MonkeyCodeUser)

        // 记录用户活跃时间到 Redis（7 天 TTL）
        redis.Set(ctx,
            fmt.Sprintf("monkeycode_ai:user:active:%s", user.ID),
            time.Now().Unix(),
            7*24*time.Hour,
        )

        // 记录用户活跃 IP（7 天 TTL）
        redis.Set(ctx,
            fmt.Sprintf("monkeycode_ai:user:ip:%s", user.ID),
            c.ClientIP(),
            7*24*time.Hour,
        )
        c.Next()
    }
}
```

**TargetActive 的设计意图：**
- 用于在管理后台显示用户的最后活跃时间
- 用于空闲检测（例如：用户长时间不活跃自动注销）
- 不参与认证检查，仅做日志记录

### 2.4 端点分组与中间件映射

| 路径前缀 | 中间件链 | 说明 |
|---------|---------|------|
| `/api/v1/public/*` | 无 | 公开端点（验证码、OAuth 跳转） |
| `/api/v1/users/*` | Auth + TargetActive | 大多数用户 API |
| `/api/v1/teams/*` | TeamAuth + TargetActive | 团队 API（部分再加 TeamAdminAuth） |
| `/api/v1/admin/*` | Auth (admin role check) | 管理员 API |
| `/api/v1/auth/*` | Auth | 认证相关 |

## 3. 代理层认证实现

### 3.1 AuthManager 类设计

代理层不执行真正的认证检查——它通过持有 Cookie 来"代表"一个已经认证的后端用户：

```typescript
// proxy/src/auth.ts — AuthManager 类设计
export class AuthManager {
  private sessionCookie: string = ""       // Cookie UUID 值
  private sessionCookieName: string = "monkeycode_ai_session"
  private email: string = ""
  private passwordHash: string = ""
  private captchaToken: string = ""
  private lastAuthTime: number = 0          // 上次认证时间戳
  private sessionTTL: number = 24 * 60 * 60 * 1000  // 24 小时缓存
  private loginMode: LoginMode = "user"     // "user" | "team"
}
```

### 3.2 四种获取 Cookie 的方式

| 来源 | 优先级 | 代码位置 | 说明 |
|------|--------|---------|------|
| 环境变量 `MONKEYCODE_SESSION_COOKIE` | 最高 | `auth.ts:48-52` | 直接使用预提取 Cookie |
| 构造函数参数传入 | 高 | `auth.ts:48-52` | 从浏览器 DevTools 提取 |
| 密码登录 (`loginUser/loginTeam`) | 中 | `auth.ts:91-163` | 需要验证码 |
| OAuth 自动化登录 | 低 | `admin-login.ts` | 6 步 HTTP 流程 |

### 3.3 密码登录实现

```typescript
// proxy/src/auth.ts — 普通用户密码登录
async loginUser(): Promise<void> {
  const url = `${MONKEYCODE_BASE_URL}/api/v1/users/password-login`
  const body: Record<string, string> = {
    email: this.email.trim(),
    password: this.passwordHash,   // 明文密码
  }
  if (this.captchaToken) {
    body.captcha_token = this.captchaToken  // 验证码 token
  }

  const response = await fetch(url, {
    method: "POST",
    headers: mkHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    redirect: "manual",  // 不自动跟随 302
  })

  if (!response.ok && response.status !== 302) {
    throw new Error(`User login failed (${response.status}): ${respBody}`)
  }

  // 从 Set-Cookie header 提取 cookie UUID
  const cookie = this.extractCookie(response, SESSION_COOKIE_NAME)
  this.sessionCookie = cookie
  this.sessionCookieName = SESSION_COOKIE_NAME
  this.lastAuthTime = Date.now()
}
```

### 3.4 团队登录与普通登录的区别

| 特性 | 普通用户登录 | 团队管理员登录 |
|------|------------|---------------|
| API 端点 | `POST /api/v1/users/password-login` | `POST /api/v1/teams/users/login` |
| Cookie 名称 | `monkeycode_ai_session` | `monkeycode_ai_team_session` |
| loginMode | `"user"` | `"team"` |
| 登录后权限 | 用户级 API | 团队级 API |
| 状态检查端点 | `GET /api/v1/users/status` | `GET /api/v1/teams/users/status` |

### 3.5 Cookie 提取器实现

```typescript
private extractCookie(response: Response, cookieName: string): string {
  const setCookie = response.headers.get("set-cookie")
  if (!setCookie) {
    throw new Error("No Set-Cookie header in login response")
  }

  // 从 Set-Cookie header 中正则提取
  // Set-Cookie: monkeycode_ai_session=uuid; Path=/; Domain=.monkeycode-ai.com; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax
  const match = setCookie.match(new RegExp(`${cookieName}=([^;]+)`))
  if (!match) {
    throw new Error(`Cannot extract ${cookieName} from Set-Cookie`)
  }

  return match[1]  // 只提取 UUID 部分
}
```

### 3.6 Cookie 自动刷新机制

```typescript
// proxy/src/auth.ts
async getSessionCookie(): Promise<string> {
  // 代理侧 24 小时缓存检查
  if (this.sessionCookie && Date.now() - this.lastAuthTime < this.sessionTTL) {
    return this.sessionCookie  // 缓存命中，直接返回
  }
  await this.login()  // 缓存过期，重新登录
  return this.sessionCookie
}

// 构造认证请求头
async authHeaders(): Promise<Record<string, string>> {
  const cookie = await this.getSessionCookie()  // 自动触发刷新
  return {
    Cookie: `${this.sessionCookieName}=${cookie}`,
    "Content-Type": "application/json",
  }
}
```

## 4. 代理层 vs 后端的 Session 管理差异

| 特性 | 后端 Go | 代理 TypeScript |
|------|--------|----------------|
| Session TTL | 30 天（Redis 硬限制） | 24 小时（内存缓存） |
| 刷新方式 | 不可刷新（30 天后必须重新登录） | 过期后自动调用 login() |
| Cookie 提取 | `http.Cookie` 对象 | `Set-Cookie` 正则提取 |
| 并发管理 | Redis 负责 | `lockedByWs` 互斥锁 |
| 状态检查 | 中间件每个请求都检查 Redis | `checkStatus()` 仅在健康检查中调用 |
| 多设备支持 | Hash 多 field 设计 | 单 Cookie 单用 |

## 5. 代理管理端点的认证现状

```typescript
// proxy/src/server.ts — 管理端点均无内置认证
app.post("/admin/session", ...)          // 设置 Cookie（可劫持）
app.post("/admin/login/send-code", ...)   // 发送短信（OAuth）
app.post("/admin/login/verify", ...)      // 短信验证
app.post("/admin/login/callback", ...)    // 回调登录
app.get("/admin/pool/status", ...)        // 号池状态
app.post("/admin/pool/refresh", ...)      // 号池重登录
app.post("/admin/refresh-models", ...)    // 刷新模型缓存
```

## 6. 错误码

| HTTP 状态码 | Error Code | 含义 | 处理方式 |
|------------|-----------|------|---------|
| 401 | 40100 | Session 过期或无效 | 代理标记 EXPIRED → 重登录 |
| 403 | — | 权限不足 | 代理标记 INVALID |
| 401 | 40002 | 密码错误 | 账号永久不可用 |
| 401 | 40003 | 账号被封禁 | 账号永久不可用 |
| 401 | 40004 | 账号未激活 | 账号永久不可用 |

---

## 相关章节

- [Session 存储机制](01-session-storage.md) — Session 数据结构
- [登录方式详解](03-login-methods.md) — 各登录方式创建 Session 的流程
- [第五章：授权层级访问控制](../05-api/02-authorization-matrix.md) — 端点的访问控制规则
- [号池差距分析](08-pool-gap-analysis.md) — 多账号管理的的登录逻辑