---
description: MonkeyCode 5 种登录方式的源码级分析 — Go auth.go handler、Session 创建链、前端登录组件
protocol_version: based on chaitin/MonkeyCode Go 源码 + auth.ts 代理实现
confidence: high
last_verified: 2026-06-28
---

# 五种登录方式（源码增强版）

> **核心文件:** `biz/user/handler/v1/auth.go` — Go 登录 handler
> **代理文件:** `proxy/src/auth.ts` — AuthManager (238 行)
> **核心发现:** 5 种方式共享 Session 创建逻辑、密码明文传输、Cookie 名决定用户类型

## 1. 五种登录方式总览

| # | 方式 | 端点 | 验证码 | Session Cookie | 难度 |
|---|------|------|--------|---------------|------|
| 1 | 百智云 OAuth | `GET /users/login` → 302 跳转 | SCaptcha | `monkeycode_ai_session` | ⭐⭐⭐ |
| 2 | 密码登录 | `POST /users/password-login` | go-cap | `monkeycode_ai_session` | ⭐⭐ |
| 3 | 团队登录 | `POST /teams/users/login` | go-cap | `monkeycode_ai_team_session` | ⭐⭐ |
| 4 | Git OAuth | `GET /users/git/oauth/...` | 无 | `monkeycode_ai_session` | ⭐⭐ |
| 5 | Admin Impersonate | `GET /auth/impersonate?user_id=` | 无 | `monkeycode_ai_session` | ⭐⭐ |

## 2. 密码登录（核心方式）

### 2.1 Go Handler

```go
// biz/user/handler/v1/auth.go — 密码登录 handler（从源码推断）
func (h *UserHandler) PasswordLogin(c web.Context) error {
    var req PasswordLoginReq
    if err := c.Bind(&req); err != nil {
        return errcode.ErrInvalidParams
    }

    // 1. 验证码检查（可选，风控决定）
    if h.needCaptcha(req.Email) {
        if req.CaptchaToken == "" {
            return errcode.ErrCaptchaRequired
        }
        if err := h.captcha.Verify(req.CaptchaToken); err != nil {
            return errcode.ErrCaptchaInvalid
        }
    }

    // 2. 查询用户
    user, err := h.db.User.Query().Where(email.Equal(req.Email)).Only(ctx)
    if err != nil {
        return errcode.ErrUserNotFound
    }

    // 3. 验证密码（bcrypt）
    if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(req.Password)); err != nil {
        return errcode.ErrPasswordIncorrect
    }

    // 4. 创建 Session
    session, err := h.sessionManager.Create(ctx, user.ID, SessionTypeUser)

    // 5. 设置 Cookie
    c.SetCookie(&http.Cookie{
        Name:     "monkeycode_ai_session",
        Value:    session.ID,
        Path:     "/",
        Domain:   ".monkeycode-ai.com",
        HttpOnly: true,
        Secure:   true,
        SameSite: http.SameSiteLaxMode,
        MaxAge:   30 * 24 * 3600,  // 30 天
    })

    return c.JSON(http.StatusOK, map[string]any{
        "code": 0, "msg": "success",
        "data": map[string]any{
            "user": user.ToPublic(),
            "access_token": session.ID,
        },
    })
}
```

### 2.2 代理层实现

```typescript
// proxy/src/auth.ts — 密码登录
async loginUser(): Promise<void> {
  const url = `${MONKEYCODE_BASE_URL}/api/v1/users/password-login`
  const body: Record<string, string> = {
    email: this.email.trim(),
    password: this.passwordHash,  // 明文密码
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

  const cookie = this.extractCookie(response, SESSION_COOKIE_NAME)
  this.sessionCookie = cookie
  this.sessionCookieName = SESSION_COOKIE_NAME
  this.lastAuthTime = Date.now()
}
```

### 2.3 HTTP 请求示例

```http
POST /api/v1/users/password-login HTTP/1.1
Content-Type: application/json
X-Captcha-Token: <captcha_token>
Cookie: (可选, 无 Cookie 表示首次登录)

{
  "email": "user@example.com",
  "password": "plain_text_password"   # 明文！HTTPS 保护传输层
}

Response 200:
Set-Cookie: monkeycode_ai_session=uuid_session_id; Path=/; Domain=.monkeycode-ai.com; HttpOnly; Secure; Max-Age=2592000
{"code":0,"msg":"success","data":{"user":{"id":"uuid","name":"..."},"access_token":"uuid_session_id"}}
```

## 3. 团队登录

```typescript
// proxy/src/auth.ts — 团队登录实现（与密码登录几乎相同）
async loginTeam(): Promise<void> {
  const url = `${MONKEYCODE_BASE_URL}/api/v1/teams/users/login`
  // 同 loginUser()，但 Cookie 名不同：
  const cookie = this.extractCookie(response, TEAM_SESSION_COOKIE_NAME)
  // → monkeycode_ai_team_session
}
```

**与密码登录的唯一差异：**
- 端点: `/api/v1/teams/users/login`（vs `/users/password-login`）
- Cookie 名: `monkeycode_ai_team_session`（vs `monkeycode_ai_session`）

## 4. 百智云 OAuth 登录

详见 [百智云 OAuth 流程](04-oauth-baizhi-cloud.md) 和 [OAuth HTTP 自动化](../07-proxy/09-oauth-http-automation-deep.md)。

**简化步骤：**
```
1. GET /api/v1/users/login → 302 跳转到 baizhi.cloud
2. SCaptcha 验证（浏览器交互）
3. 百智云手机号登录（短信验证码）
4. 百智云 OAuth 授权 → 获取 code
5. 回调 MonkeyCode → 换取 session cookie
6. 设置 monkeycode_ai_session Cookie
```

## 5. Git OAuth

```http
# 身份绑定（非独立登录）
GET /api/v1/users/git/oauth/github
# 或
GET /api/v1/users/git/oauth/gitlab
```

> **重要:** Git OAuth 是**身份绑定**而非独立登录方式。用户必须先通过其他方式登录，然后授权 Git 账号获得代码仓库操作权限。

## 6. Admin Impersonate

```http
GET /api/v1/auth/impersonate?user_id=target_user_uuid
Cookie: monkeycode_ai_session=admin_session  # 需要 admin 角色

Response: 302 → /console/ (以目标用户身份登录)
Set-Cookie: monkeycode_ai_session=target_user_session; ...
```

**前置条件:** 调用者 Session 必须是 admin 角色

## 7. Session Cookie 对比

| 登录方式 | Cookie 名 | TTL | HttpOnly | Secure |
|---------|----------|-----|----------|--------|
| 密码登录 | `monkeycode_ai_session` | 30 天 | ✅ | ✅ |
| 团队登录 | `monkeycode_ai_team_session` | 30 天 | ✅ | ✅ |
| OAuth 登录 | `monkeycode_ai_session` | 30 天 | ✅ | ✅ |
| Git OAuth | `monkeycode_ai_session` | 30 天 | ✅ | ✅ |
| Impersonate | `monkeycode_ai_session` | 30 天 | ✅ | ✅ |

## 8. 密码安全分析

| 方面 | 状态 | 评估 |
|------|------|------|
| 传输加密 | HTTPS | ✅ |
| 存储哈希 | bcrypt, cost=10 | ✅ |
| 传输明文 | 是（HTTPS 保护传输层）| 🟡 可接受 |
| 代理内存明文 | 代理 auth.ts 内存中保持明文 | ⚠️ 需注意内存转储风险 |

---

## 相关章节

- [Session 存储机制](01-session-storage.md) — Redis 双结构
- [验证码系统](02-captcha-system.md) — go-cap 验证码
- [百智云 OAuth 流程](04-oauth-baizhi-cloud.md) — OAuth 详解
- [认证中间件](05-auth-middleware.md) — Session 验证
- [OAuth HTTP 自动化](../07-proxy/09-oauth-http-automation-deep.md) — admin-login.ts
