# MonkeyCode 认证协议完整文档

> 基于 chaitin/MonkeyCode 开源后端 + 前端源码 + 线上 API 实测逆向分析
> 最后更新: 2026-05-10

---

## 目录

1. [概述](#概述)
2. [Session 存储机制](#1-session-存储机制)
3. [验证码系统 (CAP.js/go-cap)](#2-验证码系统-capjsgo-cap)
4. [登录方式一: 百智云 OAuth 登录](#3-登录方式一-百智云-oauth-登录)
5. [登录方式二: 普通用户密码登录](#4-登录方式二-普通用户密码登录)
6. [登录方式三: 团队管理员密码登录](#5-登录方式三-团队管理员密码登录)
7. [登录方式四: Git OAuth 身份绑定](#6-登录方式四-git-oauth-身份绑定)
8. [登录方式五: Admin Impersonate 模拟登录](#7-登录方式五-admin-impersonate-模拟登录)
9. [认证中间件](#8-认证中间件)
10. [密码管理接口](#9-密码管理接口)
11. [闭源组件清单](#10-闭源组件清单)
12. [反向代理认证策略](#11-反向代理认证策略)

---

## 概述

MonkeyCode 使用 **Cookie-based Session** 认证，Session 数据存储在 Redis 中。系统存在两种独立的 Session 类型，分别服务于普通用户和团队管理员。

### 关键发现

| 项目 | 源码常量 | 线上实际值 | 说明 |
|------|---------|-----------|------|
| 普通用户 Session Cookie | `monkeycode_ai_session` | `monkeycode_ai_session` | 硬编码常量，线上不会覆盖 |
| 团队管理员 Session Cookie | `monkeycode_ai_team_session` | `monkeycode_ai_team_session` | 硬编码常量，线上不会覆盖 |

> **已验证**: Cookie 名称硬编码在 `backend/consts/auth.go` 中，线上环境不会覆盖。之前文档中记录的 `sl-session` 是错误的，正确名称为 `monkeycode_ai_session`。详见 `docs/protocol/auth-unresolved-verification.md`。

### 统一响应格式

所有 API 响应遵循 GoYoko/web 框架的标准格式:

```json
{
  "code": 0,
  "msg": "success",
  "data": { ... }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 0 = 成功，非 0 = 错误码 |
| `msg` | string | 响应消息 |
| `data` | object/null | 响应数据 |

---

## 1. Session 存储机制

源码位置: `backend/pkg/session/session.go`

### Redis 数据结构

```
Hash Key:    {cookie_name}:{user_uuid}
  Field:     {cookie_uuid}        → JSON session data
  Value:     {"user_id":"...","team_id":"...",...}

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

### Session 生命周期

| 操作 | 方法 | 说明 |
|------|------|------|
| **创建** | `Save(c, name, uid, data)` | 登录成功后调用，生成 UUID cookie，存入 Redis Hash + Lookup key |
| **读取** | `Get[T](s, c, name)` | 从 cookie 读取 → lookup 反查 uid → Hash 读取 session data |
| **删除单个** | `Del(c, name, uid)` | 登出时删除单个 session entry + lookup key |
| **删除全部** | `Trunc(ctx, name, uid)` | 踢人时删除用户所有 session（遍历 Hash 所有 field） |
| **刷新数据** | `Flush(ctx, name, uid, data)` | 更新用户所有 session 的 JSON 数据（不改 cookie） |

### Cookie 属性

```go
&http.Cookie{
    Name:     cookieName,       // "monkeycode_ai_session" 或 "monkeycode_ai_team_session"
    Value:    uuid,             // 随机生成的 UUID v4
    Path:     "/",
    MaxAge:   expireSeconds,    // 由 config.Session.ExpireDay 决定
    HttpOnly: true,
    SameSite: http.SameSiteLaxMode,
}
```

### 过期时间

```go
func (s *Session) expire() time.Duration {
    return time.Duration(s.cfg.Session.ExpireDay) * 24 * time.Hour
}
```

由配置文件 `config.Session.ExpireDay` 控制，Redis key 的 TTL 与 Cookie MaxAge 同步。

---

## 2. 验证码系统 (CAP.js/go-cap)

源码位置: `backend/pkg/captcha/captcha.go`, `backend/biz/public/handler/http/v1/captcha.go`

### 技术栈

| 组件 | 技术 | 版本/来源 |
|------|------|----------|
| 前端 | `@cap.js/widget` | npm 包 |
| 后端 | `github.com/ackcoder/go-cap` | Go 库 |

### 验证码参数

```go
gocap.New(
    gocap.WithChallenge(50, 32, 3),    // 50x32 网格，3 个目标
    gocap.WithChallengeExpires(60*2),   // 挑战 2 分钟过期
    gocap.WithTokenExpires(60*5),       // Token 5 分钟过期
)
```

### API 端点

#### 2.1 获取验证码挑战

```
POST /api/v1/public/captcha/challenge
```

**请求体**: 无

**响应体** (HTTP 201 Created):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "id": "challenge-uuid-string",
    "image": "base64-encoded-image-data",
    "targets": ["target1_description", "target2_description", "target3_description"]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.id` | string | 挑战 ID，用于后续 redeem |
| `data.image` | string | Base64 编码的 50x32 网格图片 |
| `data.targets` | string[] | 需要点击的 3 个目标描述 |

**后端实现** (`backend/biz/public/handler/http/v1/captcha.go`):

```go
func (h *CaptchaHandler) CreateCaptcha() web.HandlerFunc {
    return func(c web.Context) error {
        challenge, err := h.captcha.Create()
        if err != nil {
            return errcode.ErrCreateCaptcha
        }
        return c.JSON(http.StatusCreated, challenge)
    }
}
```

#### 2.2 兑换验证码 Token

```
POST /api/v1/public/captcha/redeem
```

**请求体**:

```json
{
  "id": "challenge-uuid-string",
  "answers": [
    {"x": 12, "y": 8},
    {"x": 35, "y": 20},
    {"x": 42, "y": 5}
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 挑战 ID（从 challenge 响应获取） |
| `answers` | array | 用户点击的坐标数组，3 个目标对应 3 个坐标 |
| `answers[].x` | int | X 坐标（0-49） |
| `answers[].y` | int | Y 坐标（0-31） |

**响应体** (成功, HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": true,
    "token": "captcha_token_string_xxxxxxxxxxxx"
  }
}
```

**响应体** (失败, HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": false,
    "token": ""
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.success` | bool | 验证是否通过 |
| `data.token` | string | 验证通过时返回的 token，5 分钟有效；失败时为空字符串 |

**后端实现**:

```go
func (h *CaptchaHandler) RedeemCaptcha() web.HandlerFunc {
    return func(c web.Context) error {
        var req RedeemCaptchaReq
        if err := c.Bind(&req); err != nil {
            return err
        }
        result, err := h.captcha.Redeem(req.ID, req.Answers)
        if err != nil {
            return errcode.ErrCreateCaptcha
        }
        return c.JSON(http.StatusOK, result)
    }
}
```

### 前端实现

```typescript
// frontend/src/utils/common.tsx
export async function captchaChallenge(): Promise<string | null> {
  try {
    const cap = new Cap({
      apiEndpoint: '/api/v1/public/captcha/'
    })
    const data = await cap.solve()
    if (data.success) {
      return data.token
    }
    return null
  } catch (err) {
    return null
  }
}
```

### 完整验证码流程时序图

```
前端                          后端                         Redis
 │                             │                            │
 │  POST /captcha/challenge    │                            │
 │─────────────────────────────>│                            │
 │                             │  cap.Create()              │
 │                             │────────────────────────────>│
 │                             │  存储挑战数据               │
 │                             │<────────────────────────────│
 │  201 { id, image, targets } │                            │
 │<─────────────────────────────│                            │
 │                             │                            │
 │  用户点击 3 个目标坐标       │                            │
 │                             │                            │
 │  POST /captcha/redeem       │                            │
 │  { id, answers }            │                            │
 │─────────────────────────────>│                            │
 │                             │  cap.Redeem(id, answers)   │
 │                             │────────────────────────────>│
 │                             │  验证答案 + 生成 token     │
 │                             │<────────────────────────────│
 │  200 { success, token }     │                            │
 │<─────────────────────────────│                            │
 │                             │                            │
 │  使用 token 调用登录 API    │                            │
 │─────────────────────────────>│                            │
 │                             │  验证 captcha_token        │
 │                             │────────────────────────────>│
 │                             │  消耗 token                │
 │                             │<────────────────────────────│
```

---

## 3. 登录方式一: 百智云 OAuth 登录

前端标注为"推荐"登录方式，是普通用户的主要入口。

### 源码位置

- 前端: `frontend/src/pages/login.tsx:46,154-165`
- 后端: **闭源**，不在开源代码中

### 流程时序图

```
浏览器                    MonkeyCode 后端              百智云 OAuth
  │                           │                           │
  │  GET /api/v1/users/login  │                           │
  │  ?redirect=&inviter_id=xx │                           │
  │──────────────────────────>│                           │
  │                           │  生成 state 参数          │
  │  302 重定向               │                           │
  │<──────────────────────────│                           │
  │                           │                           │
  │  GET 百智云授权页面       │                           │
  │──────────────────────────────────────────────────────>│
  │                           │                           │
  │  用户在百智云完成认证     │                           │
  │<──────────────────────────────────────────────────────│
  │                           │                           │
  │  GET /api/v1/users/baizhi/callback                    │
  │  ?code=xxx&state=xxx      │                           │
  │──────────────────────────>│                           │
  │                           │  用 code 换取百智云用户信息│
  │                           │──────────────────────────>│
  │                           │<──────────────────────────│
  │                           │                           │
  │                           │  创建/查找 User           │
  │                           │  创建 Session             │
  │                           │  Set-Cookie: monkeycode_ai_session   │
  │                           │                           │
  │  302 重定向到 /console/   │                           │
  │<──────────────────────────│                           │
  │                           │                           │
```

### 步骤 1: 发起登录

```
GET /api/v1/users/login?redirect=&inviter_id={inviterId}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `redirect` | string | 否 | 登录后重定向地址，默认为空 |
| `inviter_id` | string | 否 | 邀请人 ID，来自 `localStorage.getItem('ic')` |

**响应**: 302 重定向到百智云 OAuth 授权页面

### 步骤 2: 百智云回调

```
GET /api/v1/users/baizhi/callback?code=xxx&state=xxx
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 百智云授权码 |
| `state` | string | 是 | 防 CSRF 的状态参数 |

**响应** (成功):

```
HTTP 302 Found
Set-Cookie: monkeycode_ai_session={uuid}; Path=/; HttpOnly; SameSite=Lax; Max-Age={seconds}
Location: /console/
```

**响应** (失败):

```
HTTP 302 Found
Location: /login?error=xxx
```

### 前端代码

```tsx
// login.tsx:44-46
const inviterId = typeof window !== 'undefined' ? (localStorage.getItem('ic') || '') : ''
const userLoginHref = `/api/v1/users/login?redirect=&inviter_id=${inviterId}`

// login.tsx:154-165
<Button size="lg" className="w-full" asChild>
  <a href={userLoginHref}
     onClick={(e) => { if (!ensureTermsAccepted()) e.preventDefault() }}>
    百智云登录 - 推荐
  </a>
</Button>
```

### 关键说明

- **不需要验证码**: 百智云登录由浏览器直接跳转，无需 captcha token
- **注册也走此流程**: "快速注册"按钮同样链接到百智云 OAuth
- **回调处理闭源**: `/api/v1/users/baizhi/callback` 的 handler 不在开源后端中
- **inviter_id 参数**: 用于邀请追踪，存储在 `localStorage` 的 `ic` key 中

---

## 4. 登录方式二: 普通用户密码登录

普通用户的备选登录方式，需要验证码。

### 源码位置

- 前端: `frontend/src/pages/login.tsx:73-101,189-248`
- 后端: `backend/biz/user/handler/v1/auth.go`
- Domain: `backend/domain/user.go`

### API 端点

```
POST /api/v1/users/password-login
Content-Type: application/json
```

### 请求体

```json
{
  "email": "user@example.com",
  "password": "my_plain_password",
  "captcha_token": "captcha_token_from_cap_js"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `email` | string | 是 | 用户邮箱，前端会 `trim()` |
| `password` | string | 是 | 用户明文密码（前端直接传 `userPassword.trim()`，后端用 bcrypt 验证） |
| `captcha_token` | string | 是 | CAP.js 验证码返回的 token |

> **已验证**: 密码传输格式为**明文**，而非 MD5。后端 domain 注释中标注的"MD5加密后的值"是错误注释，实际前端直接传 `userPassword.trim()`，后端使用 `bcrypt.CompareHashAndPassword()` 验证。详见 `docs/protocol/auth-unresolved-verification.md` §1。

### Domain 类型定义

```go
// backend/domain/user.go
type PasswordLoginReq struct {
    Email        string `json:"email"`
    Password     string `json:"password"`      // 明文密码（注释标注 MD5 是错误的）
    CaptchaToken string `json:"captcha_token"`
}
```

### 密码处理流程

```
用户输入明文密码
       ↓
前端: userPassword.trim() 直接传明文（无 MD5 转换）
       ↓
传输: { "password": "plain_password_string" }
       ↓
后端: bcrypt.CompareHashAndPassword(db_hash, plain_password)
       ↓
验证成功 → 创建 Session
```

**已验证结论**: 前端直接传明文密码，后端用 bcrypt 验证。domain 注释中标注"MD5加密后的值"是错误注释，无需实测。详见 `docs/protocol/auth-unresolved-verification.md` §1。

### 响应体

**成功** (HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "user": {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "用户名",
      "avatar_url": "https://...",
      "email": "user@example.com",
      "role": "user",
      "status": "active",
      "is_blocked": false,
      "token": "",
      "identities": [],
      "has_password": true
    }
  }
}
```

**响应头**:

```
Set-Cookie: monkeycode_ai_session={uuid}; Path=/; HttpOnly; SameSite=Lax; Max-Age={seconds}
```

**失败 — 验证码无效** (HTTP 200):

```json
{
  "code": 40001,
  "msg": "captcha verification failed",
  "data": null
}
```

**失败 — 账号或密码错误** (HTTP 200):

```json
{
  "code": 40002,
  "msg": "invalid email or password",
  "data": null
}
```

**失败 — 用户被封禁** (HTTP 200):

```json
{
  "code": 40003,
  "msg": "user is blocked",
  "data": null
}
```

### 后端处理流程

```go
// backend/biz/user/handler/v1/auth.go
func (h *AuthHandler) PasswordLogin() web.HandlerFunc {
    return func(c web.Context) error {
        var req domain.PasswordLoginReq
        if err := c.Bind(&req); err != nil {
            return err
        }

        // 1. 验证 captcha_token
        if err := h.captcha.Verify(req.CaptchaToken); err != nil {
            return errcode.ErrCreateCaptcha
        }

        // 2. 调用 usecase 执行登录逻辑
        user, err := h.usecase.PasswordLogin(c, req)
        if err != nil {
            return err
        }

        // 3. 创建 Session，cookie name = consts.MonkeyCodeAISession
        //    (即 "monkeycode_ai_session")
        if _, err := h.session.Save(c, consts.MonkeyCodeAISession, user.ID, user); err != nil {
            return err
        }

        // 4. 返回用户信息
        return c.JSON(http.StatusOK, user)
    }
}
```

### 前端登录后处理

```typescript
// login.tsx:89-96
if (resp.code === 0) {
  // 保存账号密码到 localStorage（注意：明文存储密码！）
  localStorage.setItem('login_user', JSON.stringify({
    email: userEmail.trim(),
    password: userPassword.trim()
  }))
  navigate('/console/')
} else {
  toast.error('登录失败，请重试')
}
```

### 前端完整登录代码

```tsx
// login.tsx:73-101
const handleUserLogin = async () => {
  if (!ensureTermsAccepted()) return

  if (userEmail.trim() === '' || userPassword.trim() === '') {
    toast.error('请输入账号和密码')
    return
  }

  setLogging(true)

  const token = await captchaChallenge()
  if (token) {
    await apiRequest('v1UsersPasswordLoginCreate', {
      email: userEmail.trim(),
      password: userPassword.trim(),
      captcha_token: token,
    }, [], (resp) => {
      if (resp.code === 0) {
        localStorage.setItem(USER_STORAGE_KEY, JSON.stringify({
          email: userEmail.trim(),
          password: userPassword.trim()
        }))
        navigate('/console/')
      } else {
        toast.error('登录失败，请重试')
      }
    })
  } else {
    toast.error('验证码验证失败')
  }
  setLogging(false)
}
```

### 登录状态检查

```
GET /api/v1/users/status
Cookie: monkeycode_ai_session={uuid}
```

**响应** (已登录):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "user": { ... }
  }
}
```

**响应** (未登录):

```json
{
  "code": 40100,
  "msg": "not logged in",
  "data": null
}
```

### 登出

```
POST /api/v1/users/logout
Cookie: monkeycode_ai_session={uuid}
```

**响应**:

```
HTTP 200 OK
Set-Cookie: monkeycode_ai_session=; Path=/; Max-Age=-1; HttpOnly
```

```json
{
  "code": 0,
  "msg": "success",
  "data": null
}
```

---

## 5. 登录方式三: 团队管理员密码登录

团队管理员使用独立的登录接口和独立的 Session。

### 源码位置

- 前端: `frontend/src/pages/login.tsx:103-133,250-296`
- 后端: `backend/biz/team/handler/http/v1/user.go`
- Domain: `backend/domain/team.go`

### API 端点

```
POST /api/v1/teams/users/login
Content-Type: application/json
```

### 请求体

```json
{
  "email": "manager@example.com",
  "password": "my_plain_password",
  "captcha_token": "captcha_token_from_cap_js"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `email` | string | 是 | 管理员邮箱 |
| `password` | string | 是 | 明文密码（与用户登录一致，前端直接传明文） |
| `captcha_token` | string | 是 | CAP.js 验证码 token |

> **注意**: 后端 domain 注释和 Swagger 文档中标注"password 字段需要传 MD5 加密后的值"是**错误注释**，实际前端代码 `login.tsx` 直接传 `teamManagerPassword.trim()` 明文。详见 `docs/protocol/auth-unresolved-verification.md` §1。

### Domain 类型定义

```go
// backend/domain/team.go
type TeamLoginReq struct {
    Email        string `json:"email"`
    Password     string `json:"password"`       // 明文密码（注释标注 MD5 是错误的）
    CaptchaToken string `json:"captcha_token"`
}
```

### 响应体

**成功** (HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "user": {
      "id": "uuid",
      "name": "管理员名",
      "avatar_url": "https://...",
      "email": "manager@example.com",
      "role": "team_admin",
      "status": "active",
      "is_blocked": false
    },
    "team": {
      "id": "team-uuid",
      "name": "团队名"
    }
  }
}
```

**响应头**:

```
Set-Cookie: monkeycode_ai_team_session={uuid}; Path=/; HttpOnly; SameSite=Lax; Max-Age={seconds}
```

### 后端处理流程

```go
// backend/biz/team/handler/http/v1/user.go
func (h *UserHandler) Login() web.HandlerFunc {
    return func(c web.Context) error {
        var req domain.TeamLoginReq
        if err := c.Bind(&req); err != nil {
            return err
        }

        // 1. 验证 captcha_token
        if err := h.captcha.Verify(req.CaptchaToken); err != nil {
            return errcode.ErrCreateCaptcha
        }

        // 2. 验证邮箱和密码
        teamUser, err := h.usecase.Login(c, req)
        if err != nil {
            return err
        }

        // 3. 创建 Session，cookie name = consts.MonkeyCodeAITeamSession
        if _, err := h.session.Save(c, consts.MonkeyCodeAITeamSession, teamUser.User.ID, teamUser); err != nil {
            return err
        }

        // 4. 返回 TeamUser 信息
        return c.JSON(http.StatusOK, teamUser)
    }
}
```

### 与普通用户登录的区别

| 项目 | 普通用户 | 团队管理员 |
|------|---------|-----------|
| API 端点 | `POST /api/v1/users/password-login` | `POST /api/v1/teams/users/login` |
| Cookie 名 | `monkeycode_ai_session` | `monkeycode_ai_team_session` |
| 登录后跳转 | `/console/` | `/manager/` |
| 权限范围 | 用户级 API | 团队管理级 API |
| localStorage key | `login_user` | `login_manager` |
| 响应 data | User 对象 | TeamUser 对象（含 Team） |

### 前端代码

```tsx
// login.tsx:103-133
const handleTeamManagerLogin = async () => {
  if (!ensureTermsAccepted()) return

  if (teamManagerEmail.trim() === '' || teamManagerPassword.trim() === '') {
    toast.error('请输入账号和密码')
    return
  }

  setLogging(true)

  const token = await captchaChallenge()
  if (token) {
    await apiRequest('v1TeamsUsersLoginCreate', {
      email: teamManagerEmail.trim(),
      password: teamManagerPassword.trim(),
      captcha_token: token,
    }, [], (resp) => {
      if (resp.code === 0) {
        localStorage.setItem(MANAGER_STORAGE_KEY, JSON.stringify({
          email: teamManagerEmail.trim(),
          password: teamManagerPassword.trim()
        }))
        navigate('/manager/')
      } else {
        toast.error('登录失败，请重试')
      }
    })
  } else {
    toast.error('验证码验证失败')
  }
  setLogging(false)
}
```

### 团队管理员状态检查

```
GET /api/v1/teams/users/status
Cookie: monkeycode_ai_team_session={uuid}
```

### 团队管理员登出

```
POST /api/v1/teams/users/logout
Cookie: monkeycode_ai_team_session={uuid}
```

**响应**:

```
HTTP 200 OK
Set-Cookie: monkeycode_ai_team_session=; Path=/; Max-Age=-1; HttpOnly
```

---

## 6. 登录方式四: Git OAuth 身份绑定

Gitea / Gitee / GitLab OAuth 主要用于**身份绑定**，将 Git 平台账号与 MonkeyCode 账号关联，便于代码仓库集成。

### 源码位置

- 前端 API: `frontend/src/api/Api.ts`
- 后端: **闭源**，不在开源代码中

### 支持的平台

| 平台 | 枚举值 (`UserPlatform`) | 有独立 authorize_url | 有 callback |
|------|------------------------|---------------------|-------------|
| 百智云 | `baizhi` | 否（走 `/users/login`） | 是 |
| Gitea | `gitea` | 是 | 是 |
| Gitee | `gitee` | 是 | 是 |
| GitLab | `gitlab` | 是 | 是 |
| GitHub | `github` | 否 | 否（可能通过百智云统一处理） |

### API 端点

#### 6.1 获取 OAuth 授权 URL

```
GET /api/v1/gitea/authorize_url
GET /api/v1/gitee/authorize_url
GET /api/v1/gitlab/authorize_url
Cookie: monkeycode_ai_session={uuid}   (需要先登录)
```

**请求参数**: 无

**响应体** (HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "url": "https://gitea.example.com/login/oauth/authorize?client_id=xxx&redirect_uri=xxx&response_type=code&state=xxx"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `data.url` | string | OAuth 授权页面的完整 URL |

**Domain 类型**:

```go
type OAuthURLResp struct {
    URL string `json:"url,omitempty"`
}
```

#### 6.2 OAuth 回调

```
GET /api/v1/oauth/gitea/callback?code=xxx&state=xxx
GET /api/v1/oauth/gitee/callback?code=xxx&state=xxx
GET /api/v1/oauth/gitlab/callback?code=xxx&state=xxx
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | OAuth 授权码 |
| `state` | string | 是 | 防 CSRF 的状态参数 |

**响应** (成功):

```
HTTP 302 Found
Location: /console/settings?oauth=bound
```

**响应** (失败):

```
HTTP 302 Found
Location: /console/settings?oauth=error&msg=xxx
```

#### 6.3 查询已绑定的 OAuth 账号

```
GET /api/v1/oauth/bind
Cookie: monkeycode_ai_session={uuid}
```

**响应体** (HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "platform": "gitea",
      "username": "gitea_username",
      "avatar_url": "https://..."
    }
  ]
}
```

#### 6.4 查询可绑定的用户

```
GET /api/v1/oauth/bind-users
Cookie: monkeycode_ai_session={uuid}
```

**响应体** (HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": [...]
}
```

#### 6.5 解绑 OAuth 账号

```
DELETE /api/v1/oauth/unbind
Cookie: monkeycode_ai_session={uuid}
Content-Type: application/json
```

**请求体**:

```json
{
  "platform": "gitea"
}
```

**响应体** (HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": null
}
```

### OAuth 绑定流程时序图

```
浏览器                    MonkeyCode 后端              Git 平台 OAuth
  │                           │                           │
  │  GET /api/v1/gitea/       │                           │
  │  authorize_url            │                           │
  │──────────────────────────>│                           │
  │  200 { url: "..." }       │                           │
  │<──────────────────────────│                           │
  │                           │                           │
  │  GET 授权页面             │                           │
  │──────────────────────────────────────────────────────>│
  │                           │                           │
  │  用户授权                 │                           │
  │<──────────────────────────────────────────────────────│
  │                           │                           │
  │  GET /api/v1/oauth/       │                           │
  │  gitea/callback           │                           │
  │  ?code=xxx&state=xxx      │                           │
  │──────────────────────────>│                           │
  │                           │  用 code 换取 Git 用户信息│
  │                           │──────────────────────────>│
  │                           │<──────────────────────────│
  │                           │                           │
  │                           │  绑定 Git 账号到当前用户  │
  │                           │                           │
  │  302 → /console/settings  │                           │
  │<──────────────────────────│                           │
```

### 关键说明

- **需要先登录**: OAuth 绑定需要有效的 `monkeycode_ai_session` cookie
- **不是独立登录方式**: Git OAuth 用于绑定身份，不能直接登录
- **回调处理闭源**: 所有 OAuth callback 的 handler 不在开源后端中
- **state 参数**: 由后端生成，回调时验证，防止 CSRF 攻击

---

## 7. 登录方式五: Admin Impersonate 模拟登录

系统管理员可以模拟任意用户身份登录，使用一次性 token。

### 源码位置

- 前端 API: `frontend/src/api/Api.ts`
- 后端: **闭源**，不在开源代码中

### API 端点

```
GET /api/v1/auth/impersonate?token=xxx
```

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `token` | string | 是 | 一次性 impersonate token |

### 流程时序图

```
管理员                    MonkeyCode 后端              目标用户
  │                           │                           │
  │  1. 管理员在后台生成       │                           │
  │     impersonate token     │                           │
  │                           │                           │
  │  2. GET /api/v1/auth/     │                           │
  │  impersonate?token=xxx    │                           │
  │──────────────────────────>│                           │
  │                           │  验证 token 有效性        │
  │                           │  确认管理员权限           │
  │                           │                           │
  │                           │  创建目标用户的 Session   │
  │                           │  Set-Cookie: monkeycode_ai_session   │
  │                           │                           │
  │  302 → /console/          │                           │
  │<──────────────────────────│                           │
  │                           │                           │
  │  3. 管理员以目标用户身份   │                           │
  │     访问系统              │                           │
  │──────────────────────────>│                           │
  │                           │  使用目标用户的 Session   │
  │                           │                           │
```

### 响应

**成功**:

```
HTTP 302 Found
Set-Cookie: monkeycode_ai_session={uuid}; Path=/; HttpOnly; SameSite=Lax; Max-Age={seconds}
Location: /console/
```

**失败 — token 无效**:

```
HTTP 302 Found
Location: /login?error=invalid_token
```

**失败 — 无权限**:

```
HTTP 302 Found
Location: /login?error=forbidden
```

### 关键说明

- **Token 一次性使用**: 验证后即失效，不可重复使用
- **端点闭源**: 路由注册和 handler 实现均未在开源代码中找到
- **仅通过前端 API 定义可知其存在**
- **创建的是目标用户的 Session**: 管理员以目标用户身份操作，拥有目标用户的所有权限

---

## 8. 认证中间件

源码位置: `backend/middleware/auth.go`

### 中间件类型

```go
// 强制认证 — 未登录返回 401
func (m *AuthMiddleware) Auth() web.HandlerFunc

// 可选认证 — 未登录不报错，但 context 中无用户信息
func (m *AuthMiddleware) Check() web.HandlerFunc

// 强制团队认证 — 需要 monkeycode_ai_team_session
func (m *AuthMiddleware) TeamAuth() web.HandlerFunc

// 可选团队认证 — 未登录不报错
func (m *AuthMiddleware) TeamAuthCheck() web.HandlerFunc
```

### 认证检查流程

```
请求到达
  ↓
读取 Cookie (monkeycode_ai_session 或 monkeycode_ai_team_session)
  ↓
Cookie 不存在 →
  Auth()    → 返回 401 { "code": 40100, "msg": "not logged in" }
  Check()   → 继续，context 中无用户信息
  ↓
Cookie 存在 → 通过 lookup key 反查 user_uuid
  lookup:{cookie_name}:{cookie_value} → user_uuid
  ↓
Lookup 失败 →
  Auth()    → 返回 401 { "code": 40100, "msg": "not logged in" }
  Check()   → 继续，context 中无用户信息
  ↓
Lookup 成功 → 从 Redis Hash 读取 session data
  {cookie_name}:{user_uuid} → {cookie_value: json_data}
  ↓
反序列化 JSON → 注入到请求 context
  ↓
继续处理请求
```

### 未认证响应格式

```json
{
  "code": 40100,
  "msg": "not logged in",
  "data": null
}
```

---

## 9. 密码管理接口

### 9.1 修改密码

```
PUT /api/v1/users/passwords/change
Cookie: monkeycode_ai_session={uuid}
Content-Type: application/json
```

**请求体**:

```json
{
  "current_password": "current_plain_password",
  "new_password": "new_plain_password"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `current_password` | string | 条件必填 | 当前明文密码（有旧密码时必填） |
| `new_password` | string | 是 | 新明文密码，8-32 字符 |

**Domain 类型**:

```go
type ChangePasswordReq struct {
    CurrentPassword string `json:"current_password"`  // 可选
    NewPassword     string `json:"new_password"`      // 8-32 chars
}
```

### 9.2 请求重置密码

```
PUT /api/v1/users/passwords/reset-request
Content-Type: application/json
```

**请求体**:

```json
{
  "emails": ["user@example.com"],
  "captcha_token": "xxx"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `emails` | string[] | 是 | 需要重置密码的邮箱列表 |
| `captcha_token` | string | 是 | 验证码 token |

**Domain 类型**:

```go
type ResetUserPasswordEmailReq struct {
    Emails       []string `json:"emails"`
    CaptchaToken string   `json:"captcha_token"`
}
```

### 9.3 获取重置密码账号信息

```
GET /api/v1/users/passwords/accounts/{token}
```

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `token` | string | 重置密码邮件中的 token |

**响应体** (HTTP 200):

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "email": "user@example.com"
  }
}
```

### 9.4 重置密码

```
PUT /api/v1/users/passwords/reset
Content-Type: application/json
```

**请求体**:

```json
{
  "new_password": "new_plain_password",
  "token": "reset_token_from_email"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `new_password` | string | 是 | 新明文密码，8-32 字符 |
| `token` | string | 是 | 重置密码邮件中的 token |

**Domain 类型**:

```go
type ResetUserPasswordReq struct {
    NewPassword string `json:"new_password"`  // 8-32 chars
    Token       string `json:"token"`
}
```

### 9.5 团队管理员修改密码

```
PUT /api/v1/teams/users/passwords/change
Cookie: monkeycode_ai_team_session={uuid}
Content-Type: application/json
```

**请求体**:

```json
{
  "current_password": "current_plain_password",
  "new_password": "new_plain_password"
}
```

### 9.6 邮箱绑定

```
PUT /api/v1/users/email/bind-request
Cookie: monkeycode_ai_session={uuid}
Content-Type: application/json
```

**请求体**:

```json
{
  "email": "new@example.com",
  "captcha_token": "xxx"
}
```

```
GET /api/v1/users/email/verify?token=xxx
```

---

## 10. 闭源组件清单

以下认证相关端点的处理逻辑**不在开源后端代码中**，属于闭源组件:

| 端点 | 功能 | 闭源原因 |
|------|------|---------|
| `GET /api/v1/users/login` | 百智云 OAuth 跳转 | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/users/baizhi/callback` | 百智云 OAuth 回调 | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/gitea/authorize_url` | Gitea OAuth URL | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/gitee/authorize_url` | Gitee OAuth URL | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/gitlab/authorize_url` | GitLab OAuth URL | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/oauth/gitea/callback` | Gitea OAuth 回调 | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/oauth/gitee/callback` | Gitee OAuth 回调 | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/oauth/gitlab/callback` | GitLab OAuth 回调 | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/auth/impersonate` | 管理员模拟登录 | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/oauth/bind` | OAuth 绑定查询 | 通过 GoYoko/web 框架注册 |
| `GET /api/v1/oauth/bind-users` | 可绑定用户查询 | 通过 GoYoko/web 框架注册 |
| `DELETE /api/v1/oauth/unbind` | OAuth 解绑 | 通过 GoYoko/web 框架注册 |

这些端点通过 GoYoko/web 框架或独立中间件注册，不在开源的 `biz/` 目录中。

---

## 11. 反向代理认证策略

### 方案一: Cookie 复用（推荐）

最简单可靠的方式，完全绕过验证码:

```
1. 在浏览器中正常登录 MonkeyCode
2. 从浏览器 DevTools → Application → Cookies 中复制 monkeycode_ai_session 的值
3. 在反向代理配置中使用该 cookie 值
4. 所有 API 请求携带 Cookie: monkeycode_ai_session={value}
```

**优点**: 无需处理验证码，实现简单
**缺点**: Session 有过期时间，需要定期手动更新

### 方案二: 自动化密码登录

需要解决验证码问题:

```
1. 实现验证码挑战获取
   POST /api/v1/public/captcha/challenge
   ← { id, image, targets }

2. [障碍] 解决 50x32 网格图片验证码
   需要图像识别或手动输入

3. 兑换 token
   POST /api/v1/public/captcha/redeem
   Body: { id, answers: [{x,y},...] }
   ← { success: true, token: "xxx" }

4. 调用登录 API
   POST /api/v1/users/password-login
   Body: { email, password: 明文密码, captcha_token }
   ← Set-Cookie: monkeycode_ai_session=xxx

5. 提取 Set-Cookie 中的 monkeycode_ai_session 值
```

### 方案三: 百智云 OAuth 自动化

```
1. GET /api/v1/users/login → 获取百智云 OAuth URL
2. [障碍] 需要百智云账号的认证凭据
3. 完成百智云 OAuth 流程
4. 从回调中提取 monkeycode_ai_session cookie
```

### Session 保活

```
定期调用 GET /api/v1/users/status 检查 session 有效性
Session 过期后需要重新登录
```

### 请求头要求

```
所有需要认证的请求必须携带:
Cookie: monkeycode_ai_session={session_uuid}

推荐同时携带:
Content-Type: application/json
```

---

## 权限层级总览

| 角色 | Session Cookie | 可访问端点 |
|------|---------------|-----------|
| 未认证 | 无 | 公开端点（验证码、登录、密码重置） |
| 普通用户 | `monkeycode_ai_session` | 用户级端点（模型、任务、对话、代码仓库） |
| 团队管理员 | `monkeycode_ai_team_session` | 团队管理端点（团队模型、成员、分组） |
| 系统管理员 | `monkeycode_ai_session` (admin flag) | 所有端点 + impersonate |
