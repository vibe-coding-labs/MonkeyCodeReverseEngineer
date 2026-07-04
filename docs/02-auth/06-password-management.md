---
description: 密码管理接口 + bcrypt 实现源码分析 — 修改/重置/请求重置 + auth.ts 代理密码管理
protocol_version: based on chaitin/MonkeyCode pkg/crypto/bcrypt.go + proxy/src/auth.ts
confidence: high
last_verified: 2026-06-28
---

# 密码管理接口（源码增强版）

> **核心文件:** `pkg/crypto/bcrypt.go` — bcrypt 哈希实现
> **代理文件:** `proxy/src/auth.ts` — AuthManager 密码管理
> **核心发现:** 明文 HTTPS 传输 + bcrypt DefaultCost=10 存储

## 1. 端点一览

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| PUT | `/api/v1/users/passwords/reset-request` | 公开 | 请求重置密码 |
| GET | `/api/v1/users/passwords/accounts/{token}` | 公开 | 通过 token 获取账号信息 |
| PUT | `/api/v1/users/passwords/reset` | 公开 | 执行密码重置 |
| PUT | `/api/v1/users/passwords` | Auth | 修改密码 |

## 2. bcrypt 哈希实现

```go
// backend/pkg/crypto/bcrypt.go
import "golang.org/x/crypto/bcrypt"

const DefaultCost = bcrypt.DefaultCost  // = 10

func HashPassword(password string) (string, error) {
    bytes, err := bcrypt.GenerateFromPassword([]byte(password), DefaultCost)
    return string(bytes), err
}

func CheckPasswordHash(password, hash string) bool {
    err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
    return err == nil
}
```

| bcrypt 参数 | 值 |
|------------|-----|
| Cost | 10（默认，~100ms）|
| 输出 | `$2a$10$...` |
| 输入 | 明文密码（HTTPS 传输已加密）|

## 3. 修改密码

```http
PUT /api/v1/users/passwords
Cookie: monkeycode_ai_session=xxx

{"old_password": "current_password", "new_password": "new_password"}
```

### 后端处理

```go
func (h *UserHandler) ChangePassword(c web.Context) error {
    var req ChangePasswordReq; c.Bind(&req)
    user := GetCurrentUser(c)

    // 验证旧密码
    if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(req.OldPassword)); err != nil {
        return errcode.ErrPasswordIncorrect
    }

    // 生成新哈希 + 更新数据库
    newHash, _ := crypto.HashPassword(req.NewPassword)
    h.db.User.UpdateOneID(user.ID).SetPasswordHash(newHash).Save(ctx)

    return c.JSON(http.StatusOK, map[string]any{"code": 0, "msg": "Password updated"})
}
```

## 4. 密码重置流程

**Step 1: 请求重置**
```http
PUT /api/v1/users/passwords/reset-request
{"email": "user@example.com"}
→ {"code": 0, "msg": "重置邮件已发送（如邮箱存在）"}
```

```go
// 用户不存在也返回成功（防邮箱枚举）
func (h *UserHandler) ResetRequest(c web.Context) error {
    user, err := h.db.User.Query().Where(email.Equal(req.Email)).Only(ctx)
    if err != nil {
        return c.JSON(http.StatusOK, map[string]any{"code": 0, "msg": "重置邮件已发送（如邮箱存在）"})
    }
    token, _ := crypto.GenerateResetToken(user.ID, 1*time.Hour)
    h.mailer.SendPasswordResetEmail(req.Email, token)
    return c.JSON(http.StatusOK, map[string]any{"code": 0, "msg": "重置邮件已发送"})
}
```

**Step 2: 获取账号信息**
```http
GET /api/v1/users/passwords/accounts/{token}
→ {"code": 0, "data": {"name": "用户名", "email": "user@example.com"}}
```

**Step 3: 执行重置**
```http
PUT /api/v1/users/passwords/reset
{"token": "reset_token", "new_password": "new_password"}
→ {"code": 0, "msg": "密码已重置"}
```

## 5. 代理层密码管理

```typescript
// proxy/src/auth.ts — AuthManager 密码管理
export class AuthManager {
  private email: string = ""
  private passwordHash: string = ""

  constructor() {
    this.email = process.env.MONKEYCODE_EMAIL || process.env.MONKEYCODE_USERNAME || ""
    this.passwordHash = process.env.MONKEYCODE_PASSWORD_HASH || ""
    const plainPassword = process.env.MONKEYCODE_PASSWORD || ""
    if (plainPassword && !this.passwordHash) {
      this.passwordHash = plainPassword.trim()  // 明文
    }
  }

  async loginUser(): Promise<void> {
    const body = { email: this.email.trim(), password: this.passwordHash }
    const response = await fetch(`.../password-login`, {
      method: "POST", headers: mkHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify(body)
    })
    const cookie = this.extractCookie(response, SESSION_COOKIE_NAME)
    this.sessionCookie = cookie
  }
}
```

## 6. 密码安全分析

| 方面 | 评估 |
|------|------|
| 传输加密 | ✅ HTTPS |
| 存储哈希 | ✅ bcrypt cost=10 |
| 传输明文密码 | 🟡 可接受（HTTPS 保护）|
| 代理内存明文 | ⚠️ 内存可被 dump |
| 重置 token | ✅ 1 小时过期 |
| 邮箱枚举防护 | ✅ 始终返回成功 |

---

## 相关章节

- [登录方式详解](03-login-methods.md) — 五种登录方式
- [代理 AuthManager 源码](../07-proxy/auth.ts) — 认证管理
