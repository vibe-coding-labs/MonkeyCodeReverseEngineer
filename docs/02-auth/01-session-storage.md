---
description: Session 存储机制的完整分析 — 基于 Go 源码和 proxy TypeScript 源码的双重视角
protocol_version: based on chaitin/MonkeyCode + proxy/src/auth.ts + proxy/src/account-pool.ts
confidence: high
last_verified: 2026-06-28
---

# Session 存储机制（源码增强版）

> **所属位置:** 🔌 第二篇·通讯协议 → 🔐 认证协议
> **上一步:** [认证协议总览](README.md)
> **下一步:** [验证码系统](02-captcha-system.md)
（源码增强版）

## 1. Redis 双结构

Session 数据存储在 Redis 中，使用 **Hash + Lookup Key** 双结构：

```
Hash Key:    {cookie_name}:{user_uuid}
  Field:     {cookie_uuid}        → JSON session data
  Value:     {"user_id":"...","team_id":"...","role":"...","subscription_level":"..."}

Lookup Key:  lookup:{cookie_name}:{cookie_uuid}  → user_uuid
```

### 示例

```
# 用户 UUID = a1b2c3d4-e5f6-7890-abcd-ef1234567890
# Cookie UUID = f7e6d5c4-b3a2-1098-7654-321fedcba098

Hash Key:    monkeycode_ai_session:a1b2c3d4-e5f6-7890-abcd-ef1234567890
  Field:     f7e6d5c4-b3a2-1098-7654-321fedcba098
  Value:     {"user_id":"a1b2c3d4-...","role":"user",...}

Lookup Key:  lookup:monkeycode_ai_session:f7e6d5c4-b3a2-1098-7654-321fedcba098
  Value:     a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### 设计原理

1. **Lookup Key 的目的**: Cookie 只存 UUID，不存 user_id，保护用户标识
2. **Hash 多 Field 设计**: 同一用户可以创建多个 Session（多设备/多标签页）
3. **Hash 全量删除**: `Trunc()` 遍历 Hash 所有 field 实现「踢下线所有设备」
4. **HTTP Only Cookie**: Cookie 值仅为 UUID，不包含任何用户信息

## 2. 代理层的 AuthManager 设计

代理层的认证管理是后端 Session 系统的直接客户端实现：

```typescript
// proxy/src/auth.ts
export class AuthManager {
  private sessionCookie: string = ""       // Cookie UUID 值
  private sessionCookieName: string = "monkeycode_ai_session"
  private email: string = ""
  private passwordHash: string = ""
  private captchaToken: string = ""
  private lastAuthTime: number = 0
  private sessionTTL: number = 24 * 60 * 60 * 1000  // 代理侧 24h 缓存
  private loginMode: LoginMode = "user"
}
```

**TTL 差异对比：**

| 层级 | TTL | 说明 |
|------|-----|------|
| Redis 后端 | 30 天（硬限制，不可刷新） | 由 `pkg/session/session.go` 设置 |
| 代理 AuthManager | 24 小时（仅缓存） | 代理侧减少 `login()` 调用频率 |
| 号池健康检查 | 29 天（提前 1 天刷新） | `account-pool.ts` 中 `SESSION_MAX_AGE_MS` |

### 2.1 代理的 Cookie 刷新机制

```typescript
// 获取当前 Cookie（缓存未过期则直接返回）
async getSessionCookie(): Promise<string> {
  if (this.sessionCookie && Date.now() - this.lastAuthTime < this.sessionTTL) {
    return this.sessionCookie
  }
  await this.login()  // 过期后重新登录
  return this.sessionCookie
}
```

### 2.2 两种登录方式

#### 普通用户登录（Proxy → Go 后端）

```typescript
async loginUser(): Promise<void> {
  const url = `${MONKEYCODE_BASE_URL}/api/v1/users/password-login`
  const body: Record<string, string> = {
    email: this.email.trim(),
    password: this.passwordHash,
  }
  if (this.captchaToken) {
    body.captcha_token = this.captchaToken
  }

  const response = await fetch(url, {
    method: "POST",
    headers: mkHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    redirect: "manual",
  })

  // 后端返回 302（重定向）或 200（直接返回）
  const cookie = this.extractCookie(response, SESSION_COOKIE_NAME)
  this.sessionCookie = cookie
  this.lastAuthTime = Date.now()
}
```

#### 团队管理员登录

```typescript
async loginTeam(): Promise<void> {
  const url = `${MONKEYCODE_BASE_URL}/api/v1/teams/users/login`
  // 使用不同的 Cookie name: monkeycode_ai_team_session
  const cookie = this.extractCookie(response, TEAM_SESSION_COOKIE_NAME)
}
```

### 2.3 Cookie 提取逻辑

```typescript
private extractCookie(response: Response, cookieName: string): string {
  const setCookie = response.headers.get("set-cookie")
  if (!setCookie) {
    throw new Error("No Set-Cookie header in login response")
  }

  const match = setCookie.match(new RegExp(`${cookieName}=([^;]+)`))
  if (!match) {
    throw new Error(`Cannot extract ${cookieName} from Set-Cookie`)
  }

  return match[1]  // 提取纯 UUID 值
}
```

## 3. 号池中的 Session 生命周期管理

```typescript
// proxy/src/account-pool.ts
const SESSION_MAX_AGE_MS = 29 * 24 * 60 * 60 * 1000  // 29 天提前重登录
const HEALTH_CHECK_INTERVAL_MS = 60 * 60 * 1000        // 1 小时
```

号池在健康检查中对每个账号执行三件事：

```typescript
private async healthCheck(): Promise<void> {
  for (const entry of this.accounts) {

    // 1. 清理僵尸 WS 锁（> 任务超时 + 1min）
    if (entry.lockedByWs && entry.lockedAt &&
        Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
      entry.lockedByWs = false
    }

    // 2. 检查 Cookie 年龄（提前 1 天重登录）
    if (entry.cookieSetAt &&
        Date.now() - entry.cookieSetAt > SESSION_MAX_AGE_MS) {
      await this.loginAccount(entry)
      continue
    }

    // 3. 调用 /users/status 检查有效性
    try {
      const ok = await entry.auth.checkStatus()
      if (!ok) await this.loginAccount(entry)
    } catch {
      entry.status = "EXPIRED"
    }
  }
}
```

## 4. Cookie 属性

```go
// backend/pkg/session/session.go
&http.Cookie{
    Name:     cookieName,       // "monkeycode_ai_session" 或 "monkeycode_ai_team_session"
    Value:    cookieUUID,       // 随机 UUID v4（无任何用户信息）
    Path:     "/",
    Domain:   ".monkeycode-ai.com",
    MaxAge:   86400 * 30,       // 30 天
    Secure:   true,             // 仅 HTTPS
    HttpOnly: true,             // 禁止 JS 访问
    SameSite: http.SameSiteLaxMode, // 允许 GET 方式跨站传输
}
```

| 属性 | 值 | 原因 |
|------|-----|------|
| Domain | `.monkeycode-ai.com` | 子域名共享（api.monkeycode-ai.com 等） |
| MaxAge | 30 天 | 与 Redis TTL 一致，硬限制不可刷新 |
| Secure | true | 仅 HTTPS 传输 |
| HttpOnly | true | XSS 保护 |
| SameSite | LaxMode | 允许 GET 请求跨站携带 Cookie |

## 5. 代理层 Session 操作

### 5.1 状态检查

```typescript
// proxy/src/auth.ts — 检查 Session 是否有效
async checkStatus(): Promise<boolean> {
  const url = this.loginMode === "team"
    ? `${MONKEYCODE_BASE_URL}/api/v1/teams/users/status`
    : `${MONKEYCODE_BASE_URL}/api/v1/users/status`

  const response = await fetch(url, {
    headers: mkHeaders({
      Cookie: `${this.getSessionCookieName()}=${this.getSessionCookieSync()}`,
    }),
  })
  return response.ok  // HTTP 200 = 有效，其他 = 失效
}
```

### 5.2 登出

```typescript
// proxy/src/auth.ts
async logout(): Promise<void> {
  const logoutUrl = this.loginMode === "team"
    ? `${MONKEYCODE_BASE_URL}/api/v1/teams/users/logout`
    : `${MONKEYCODE_BASE_URL}/api/v1/users/logout`

  await fetch(logoutUrl, {
    method: "POST",
    headers: mkHeaders({
      Cookie: `${this.getSessionCookieName()}=${this.getSessionCookieSync()}`,
    }),
  })
  this.sessionCookie = ""
  this.lastAuthTime = 0
}
```

### 5.3 构建认证请求头

```typescript
// proxy/src/auth.ts
async authHeaders(): Promise<Record<string, string>> {
  const cookie = await this.getSessionCookie()  // 自动刷新
  return {
    Cookie: `${this.sessionCookieName}=${cookie}`,
    "Content-Type": "application/json",
  }
}
```

## 6. 完整的 Session 生命周期时序

```
Cookie 创建                    30天 TTL                        Cookie 过期
    │                            │                                │
    ├── login() ───────────────►│                                │
    │  Set-Cookie: session=UUID  │                                │
    │  Redis: session:{UUID}     │                                │
    │  Redis: lookup:session:UUID│                                │
    │                            │                                │
    ├── API 调用 ──────────────►│─── /users/status ──────────────►│
    │  Cookie: session=UUID      │  返回 200 (有效)               │ 返回 401 (过期)
    │                            │                                │
    ├── healthCheck() ──────────►│                                │
    │  检查 Cookie 年龄           │                                │
    │  29天时触发重登录            │                                │
    │                            │                                │
    ├── 重登录 ─────────────────►│                                │
    │  获取新 Cookie              │                                │
    │  旧 Cookie 自动失效         │                                │
```

## 7. 多标签页 Session 共享

```go
// Redis Hash 支持多 field —— 一个用户可以有多个会话
// 每个标签页/设备有自己的 cookieUUID

// 查询当前所有活跃设备
Hash Key: monkeycode_ai_session:{user_uuid}
  Field 1: cookie_uuid_1 (桌面浏览器)
  Field 2: cookie_uuid_2 (手机浏览器)
  Field 3: cookie_uuid_3 (代理 API)

// "踢下线所有设备" 操作
func (s *Session) Trunc(ctx context.Context, name string, uid uuid.UUID) error {
    hashKey := fmt.Sprintf("%s:%s", name, uid)
    fields, _ := s.redis.HKeys(ctx, hashKey)  // 获取所有 field
    for _, field := range fields {
        // 删除 Hash field
        s.redis.HDel(ctx, hashKey, field)
        // 删除对应的 Lookup Key
        s.redis.Del(ctx, fmt.Sprintf("lookup:%s:%s", name, field))
    }
}
```

---

## 相关章节

- [登录方式详解](03-login-methods.md) — 创建 Session 的 5 种方式
- [认证中间件](05-auth-middleware.md) — 读取 Session 的中间件实现
- [认证自动化](07-auth-automation.md) — 自动化的具体实现