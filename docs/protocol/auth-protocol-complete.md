# MonkeyCode 认证协议完整文档

> 基于开源后端源码 (chaitin/MonkeyCode) + 前端源码 + 线上 API 实测分析

## 概述

MonkeyCode 使用 **Cookie-based Session** 认证，Session 数据存储在 Redis 中。系统存在两种独立的 Session 类型，分别服务于普通用户和团队管理员。

### 关键发现

| 项目 | 源码常量 | 线上实际值 | 说明 |
|------|---------|-----------|------|
| 普通用户 Session Cookie | `monkeycode_ai_session` | `sl-session` | 线上部署时覆盖了源码常量 |
| 团队管理员 Session Cookie | `monkeycode_ai_team_session` | 未验证 | 源码常量，线上可能也有覆盖 |

**重要**: 反向代理实现必须使用 `sl-session` 而非源码中的 `monkeycode_ai_session`。

---

## Session 存储机制

### Redis 数据结构

```
Hash Key:    {cookie_name}:{user_uuid}
  Field:     {cookie_uuid}        → JSON session data
  Value:     {"user_id":"...","team_id":"...",...}

Lookup Key:  lookup:{cookie_name}:{cookie_uuid}  → user_uuid
```

### Session 生命周期

- **创建**: 登录成功后，后端生成 UUID 作为 cookie value，存入 Redis Hash
- **读取**: 请求携带 cookie → 通过 lookup key 反查 user_uuid → 从 Hash 中读取 session data
- **刷新**: 每次登录创建新的 session entry（同一用户可有多个 session）
- **过期**: 可配置，默认 `ExpireDay` 天（由 `config.Session.ExpireDay` 控制）
- **删除**: 登出时删除单个 session；踢人时删除用户所有 session

### Cookie 属性

```go
&http.Cookie{
    Name:     cookieName,       // "sl-session" 或 "monkeycode_ai_team_session"
    Value:    uuid,             // 随机生成的 UUID
    Path:     "/",
    MaxAge:   expireSeconds,    // 由 config.Session.ExpireDay 决定
    HttpOnly: true,
    SameSite: http.SameSiteLaxMode,
}
```

---

## 验证码系统 (CAP.js)

所有需要人机验证的接口都使用 **go-cap** 验证码系统（非 Turnstile/hCaptcha/reCaptcha）。

### 技术栈

- **前端**: `@cap.js/widget` (npm 包)
- **后端**: `github.com/ackcoder/go-cap` (Go 库)

### 验证码参数

```go
gocap.New(
    gocap.WithChallenge(50, 32, 3),    // 50x32 网格，3 个目标
    gocap.WithChallengeExpires(60*2),   // 挑战 2 分钟过期
    gocap.WithTokenExpires(60*5),       // Token 5 分钟过期
)
```

### 验证码流程

```
1. 前端创建 Cap 实例
   const cap = new Cap({ apiEndpoint: '/api/v1/public/captcha/' })

2. 前端请求挑战
   POST /api/v1/public/captcha/challenge
   ← 201 Created
     { challenge_data: ... }  // 50x32 网格图片 + 3 个目标坐标

3. 用户点击图片中的目标位置
   前端收集用户点击坐标

4. 前端提交答案兑换 Token
   POST /api/v1/public/captcha/redeem
   Body: { challenge_id, answers: [...] }
   ← 200 OK
     { success: true, token: "captcha_token_string" }

5. 前端将 token 传入登录接口的 captcha_token 字段
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

### 反向代理中的验证码处理

对于自动化场景，验证码是主要障碍。可选方案：

1. **手动获取**: 在浏览器中完成验证码，提取 `captcha_token` 用于 API 调用
2. **Cookie 复用**: 先在浏览器中登录，提取 `sl-session` cookie，直接用于后续 API 调用（跳过验证码）
3. **自动化**: 集成验证码服务或使用图像识别（不推荐，违反服务条款）

---

## 登录方式详解

### 方式 1: 百智云 OAuth 登录（推荐）

普通用户的主要登录方式，前端标注为"推荐"。

#### 流程

```
1. 用户点击"百智云登录"
   GET /api/v1/users/login?redirect=&inviter_id={inviterId}
   ← 302 重定向到百智云 OAuth 授权页面

2. 用户在百智云完成认证
   （百智云侧的认证流程，不在 MonkeyCode 控制范围内）

3. 百智云回调 MonkeyCode
   GET /api/v1/users/baizhi/callback?code=xxx&state=xxx
   ← 后端用 code 换取百智云用户信息
   ← 创建/查找 User 记录
   ← 创建 Session
   ← Set-Cookie: sl-session={uuid}
   ← 302 重定向到前端页面
```

#### 前端代码

```tsx
// login.tsx
const userLoginHref = `/api/v1/users/login?redirect=&inviter_id=${inviterId}`
// inviterId 来自 localStorage.getItem('ic')

<Button size="lg" className="w-full" asChild>
  <a href={userLoginHref} onClick={ensureTermsAccepted}>
    百智云登录 - 推荐
  </a>
</Button>
```

#### 关键说明

- **不需要验证码**: 百智云登录跳转由浏览器直接处理，无需 captcha token
- **注册也走此流程**: "快速注册"按钮同样链接到百智云 OAuth
- **回调处理不在开源代码中**: `/api/v1/users/baizhi/callback` 的处理逻辑未包含在开源后端中
- **inviter_id 参数**: 用于邀请追踪，存储在 `localStorage` 的 `ic` key 中

---

### 方式 2: 账号密码登录（普通用户）

普通用户的备选登录方式，需要验证码。

#### API 端点

```
POST /api/v1/users/password-login
```

#### 请求格式

```json
{
  "email": "user@example.com",
  "password": "e10adc3949ba59abbe56e057f20f883e",
  "captcha_token": "captcha_token_from_cap_js"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `email` | string | 用户邮箱，前端会 trim |
| `password` | string | 密码的 **MD5 哈希值**（32 位小写 hex） |
| `captcha_token` | string | CAP.js 验证码返回的 token |

#### 密码处理

```
原始密码 → MD5 哈希 → 发送到后端
```

前端代码：
```typescript
await apiRequest('v1UsersPasswordLoginCreate', {
  email: userEmail.trim(),
  password: userPassword.trim(),  // 注意：前端直接发送用户输入
  captcha_token: token,
})
```

**重要发现**: 前端代码中 `userPassword` 是用户直接输入的值，但后端 domain 定义中 `Password` 字段注释标注为 MD5。这意味着：
- 可能前端在 `apiRequest` 内部做了 MD5 转换
- 或者后端接收明文密码后自行 MD5
- 需要实测确认具体行为

#### 响应

成功时：
```
HTTP 200 OK
Set-Cookie: sl-session={uuid}; Path=/; HttpOnly; SameSite=Lax
Body: { "code": 0, ... }
```

失败时：
```
HTTP 200 OK
Body: { "code": 非0, ... }
```

#### 后端处理流程

```go
// backend/biz/user/handler/v1/auth.go
func (h *AuthHandler) PasswordLogin() {
    // 1. 验证 captcha_token
    // 2. 调用 usecase 执行登录逻辑
    // 3. 验证邮箱和密码
    // 4. 创建 Session，cookie name = consts.MonkeyCodeAISession
    //    (线上实际为 sl-session)
    // 5. 返回用户信息
}
```

#### 前端登录后处理

```typescript
if (resp.code === 0) {
  // 保存账号密码到 localStorage（注意：明文存储密码！）
  localStorage.setItem('login_user', JSON.stringify({
    email: userEmail.trim(),
    password: userPassword.trim()
  }))
  navigate('/console/')
}
```

---

### 方式 3: 团队管理员登录

团队管理员使用独立的登录接口和独立的 Session。

#### API 端点

```
POST /api/v1/teams/users/login
```

#### 请求格式

```json
{
  "email": "manager@example.com",
  "password": "e10adc3949ba59abbe56e057f20f883e",
  "captcha_token": "captcha_token_from_cap_js"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `email` | string | 管理员邮箱 |
| `password` | string | 密码的 MD5 哈希值 |
| `captcha_token` | string | CAP.js 验证码 token |

#### 响应

成功时：
```
HTTP 200 OK
Set-Cookie: monkeycode_ai_team_session={uuid}; Path=/; HttpOnly; SameSite=Lax
Body: { "code": 0, ... }
```

#### 与普通用户登录的区别

| 项目 | 普通用户 | 团队管理员 |
|------|---------|-----------|
| API 端点 | `POST /api/v1/users/password-login` | `POST /api/v1/teams/users/login` |
| Cookie 名 | `sl-session` | `monkeycode_ai_team_session` |
| 登录后跳转 | `/console/` | `/manager/` |
| 权限范围 | 用户级 API | 团队管理级 API |
| localStorage key | `login_user` | `login_manager` |

#### 后端处理流程

```go
// backend/biz/team/handler/http/v1/user.go
func (h *UserHandler) Login() {
    // 1. 验证 captcha_token
    // 2. 验证邮箱和密码
    // 3. 创建 Session，cookie name = consts.MonkeyCodeAITeamSession
    // 4. 返回 TeamUser 信息（包含 User 和 Team）
}
```

---

### 方式 4: Git OAuth 登录（身份绑定）

Gitea / Gitee / GitLab OAuth 主要用于**身份绑定**，而非独立登录入口。

#### API 端点

```
获取授权 URL:
  GET /api/v1/gitea/authorize_url   → { "url": "https://..." }
  GET /api/v1/gitee/authorize_url   → { "url": "https://..." }
  GET /api/v1/gitlab/authorize_url  → { "url": "https://..." }

OAuth 回调:
  GET /api/v1/oauth/gitea/callback?code=xxx&state=xxx
  GET /api/v1/oauth/gitee/callback?code=xxx&state=xxx
  GET /api/v1/oauth/gitlab/callback?code=xxx&state=xxx

身份绑定/解绑:
  GET  /api/v1/oauth/bind           → 查询已绑定的 OAuth 账号
  GET  /api/v1/oauth/bind-users     → 查询可绑定的用户
  DELETE /api/v1/oauth/unbind       → 解绑 OAuth 账号
```

#### 支持的平台

| 平台 | 枚举值 | 说明 |
|------|--------|------|
| 百智云 | `baizhi` | 主要登录方式 |
| GitHub | `github` | 源码中未发现独立 authorize_url |
| GitLab | `gitlab` | 有独立 OAuth 流程 |
| Gitea | `gitea` | 有独立 OAuth 流程 |
| Gitee | `gitee` | 有独立 OAuth 流程 |

#### 关键说明

- Git OAuth 的回调处理逻辑**不在开源后端代码中**
- 这些 OAuth 主要用于将 Git 平台账号与 MonkeyCode 账号绑定，便于代码仓库集成
- GitHub 没有独立的 `authorize_url` 端点，可能通过百智云统一处理

---

### 方式 5: Admin Impersonate（管理员模拟登录）

系统管理员可以模拟任意用户身份登录。

#### API 端点

```
GET /api/v1/auth/impersonate?token=xxx
```

#### 流程

```
1. 管理员在后台生成一次性 impersonate token
2. 管理员访问 GET /api/v1/auth/impersonate?token=xxx
3. 后端验证 token 有效性
4. 后端创建目标用户的 Session
5. Set-Cookie: sl-session={uuid}
6. 302 重定向到用户控制台
```

#### 关键说明

- **Impersonate 端点不在开源后端代码中**: 路由注册和 handler 实现均未找到
- 这属于闭源组件，仅通过前端 API 定义可知其存在
- Token 为一次性使用，验证后即失效

---

## 认证中间件

### 中间件类型

```go
// backend/middleware/auth.go

// Auth() — 强制认证，未登录返回 401
// 用于需要登录才能访问的端点

// Check() — 可选认证，未登录不报错
// 用于公开但登录后有额外信息的端点

// TeamAuth() — 强制团队认证，需要 monkeycode_ai_team_session
// 用于团队管理相关端点

// TeamAuthCheck() — 可选团队认证
// 用于团队相关但非强制的端点
```

### 认证检查流程

```
请求到达
  ↓
读取 Cookie (sl-session 或 monkeycode_ai_team_session)
  ↓
通过 lookup key 反查 user_uuid
  lookup:{cookie_name}:{cookie_value} → user_uuid
  ↓
从 Redis Hash 读取 session data
  {cookie_name}:{user_uuid} → {cookie_value: json_data}
  ↓
反序列化 JSON → 注入到请求 context
  ↓
继续处理请求
```

---

## 密码管理相关接口

### 修改密码

```
PUT /api/v1/users/passwords/change
Headers: Cookie: sl-session=xxx
Body: {
  "current_password": "optional_current_md5",  // 可选，取决于是否有旧密码
  "new_password": "new_md5_hash"               // 8-32 字符
}
```

### 重置密码请求

```
PUT /api/v1/users/passwords/reset-request
Body: {
  "emails": ["user@example.com"],
  "captcha_token": "xxx"
}
```

### 获取重置密码账号信息

```
GET /api/v1/users/passwords/accounts/{token}
```

### 重置密码

```
PUT /api/v1/users/passwords/reset
Body: {
  "new_password": "new_md5_hash",  // 8-32 字符
  "token": "reset_token_from_email"
}
```

### 团队管理员修改密码

```
PUT /api/v1/teams/users/passwords/change
Headers: Cookie: monkeycode_ai_team_session=xxx
Body: {
  "current_password": "current_md5",
  "new_password": "new_md5_hash"
}
```

---

## 邮箱绑定相关接口

### 发送绑定验证邮件

```
PUT /api/v1/users/email/bind-request
Headers: Cookie: sl-session=xxx
Body: {
  "email": "new@example.com",
  "captcha_token": "xxx"
}
```

### 验证绑定邮箱

```
GET /api/v1/users/email/verify?token=xxx
```

---

## 登出接口

### 普通用户登出

```
POST /api/v1/users/logout
Headers: Cookie: sl-session=xxx
← 清除该 session entry
← Set-Cookie: sl-session=; Path=/; Max-Age=-1; HttpOnly
```

### 团队管理员登出

```
POST /api/v1/teams/users/logout
Headers: Cookie: monkeycode_ai_team_session=xxx
← 清除该 team session entry
← Set-Cookie: monkeycode_ai_team_session=; Path=/; Max-Age=-1; HttpOnly
```

---

## 登录状态检查

### 普通用户状态

```
GET /api/v1/users/status
Headers: Cookie: sl-session=xxx (可选)
← 200 OK
  有 Cookie 且有效: isLoggedIn = true
  无 Cookie 或无效: isLoggedIn = false
```

### 团队管理员状态

```
GET /api/v1/teams/users/status
Headers: Cookie: monkeycode_ai_team_session=xxx (可选)
```

---

## 反向代理认证策略

### 推荐方案: Cookie 复用

最简单可靠的方式，绕过验证码：

```
1. 在浏览器中正常登录 MonkeyCode
2. 从浏览器 DevTools → Application → Cookies 中复制 sl-session 的值
3. 在反向代理配置中使用该 cookie 值
4. 所有 API 请求携带 Cookie: sl-session={value}
```

### 备选方案: 自动化登录

需要解决验证码问题：

```
1. 实现验证码挑战获取 (POST /api/v1/public/captcha/challenge)
2. [障碍] 解决 50x32 网格图片验证码
3. 兑换 token (POST /api/v1/public/captcha/redeem)
4. 调用登录 API (POST /api/v1/users/password-login)
5. 提取 Set-Cookie 中的 sl-session 值
```

### Session 保活

```
定期调用 GET /api/v1/users/status 检查 session 有效性
Session 过期后需要重新登录
```

### 请求头要求

```
所有需要认证的请求必须携带:
Cookie: sl-session={session_uuid}

推荐同时携带:
Content-Type: application/json
```

---

## 权限层级

| 角色 | Session Cookie | 可访问端点 |
|------|---------------|-----------|
| 未认证 | 无 | 公开端点（验证码、登录、密码重置） |
| 普通用户 | `sl-session` | 用户级端点（模型、任务、对话、代码仓库） |
| 团队管理员 | `monkeycode_ai_team_session` | 团队管理端点（团队模型、成员、分组） |
| 系统管理员 | `sl-session` (admin flag) | 所有端点 + impersonate |

---

## 闭源组件清单

以下认证相关端点的处理逻辑**不在开源后端代码中**，属于闭源组件：

| 端点 | 说明 |
|------|------|
| `GET /api/v1/users/login` | 百智云 OAuth 跳转 |
| `GET /api/v1/users/baizhi/callback` | 百智云 OAuth 回调 |
| `GET /api/v1/gitea/authorize_url` | Gitea OAuth URL |
| `GET /api/v1/gitee/authorize_url` | Gitee OAuth URL |
| `GET /api/v1/gitlab/authorize_url` | GitLab OAuth URL |
| `GET /api/v1/oauth/gitea/callback` | Gitea OAuth 回调 |
| `GET /api/v1/oauth/gitee/callback` | Gitee OAuth 回调 |
| `GET /api/v1/oauth/gitlab/callback` | GitLab OAuth 回调 |
| `GET /api/v1/auth/impersonate` | 管理员模拟登录 |
| `GET /api/v1/oauth/bind` | OAuth 绑定查询 |
| `GET /api/v1/oauth/bind-users` | 可绑定用户查询 |
| `DELETE /api/v1/oauth/unbind` | OAuth 解绑 |

这些端点通过 GoYoko/web 框架或独立中间件注册，不在开源的 `biz/` 目录中。
