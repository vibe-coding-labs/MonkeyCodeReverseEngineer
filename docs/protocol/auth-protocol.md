# MonkeyCode 认证协议详解

## 概述

MonkeyCode 使用 **Cookie-based Session** 认证（非 JWT），Session 存储在 Redis 中。

## Session 结构

```go
// 后端 Session 数据结构
type SessionData struct {
    UserID      string `json:"user_id"`
    TeamID      string `json:"team_id"`
    IsAdmin     bool   `json:"is_admin"`
    IsTeamAdmin bool   `json:"is_team_admin"`
}
```

- **Cookie 名**: `sl-session`
- **Redis Key**: `sess:{session_id}`
- **Session TTL**: 可配置（默认 24h）

## 认证流程

### 1. OAuth 登录流程

```
用户 → GET /api/v1/users/login?provider=github
     → 302 重定向到 GitHub OAuth
     → 用户授权
     → GitHub 回调 /api/v1/auth/callback?code=xxx&state=xxx
     → 后端用 code 换取 access_token
     → 后端用 access_token 获取用户信息
     → 创建/查找 User 记录
     → 创建 Session，设置 Cookie
     → 302 重定向到前端页面
```

支持的 OAuth Provider:
- `github` — GitHub OAuth
- `gitlab` — GitLab OAuth
- `gitee` — Gitee OAuth
- `gitea` — Gitea OAuth

### 2. Team 用户登录流程

```
客户端 → POST /api/v1/teams/users/login
       Body: {
         "username": "user@example.com",
         "password": "md5_hash_of_password"  // MD5 哈希
       }
       ← 200 OK
         Set-Cookie: sl-session=xxx; Path=/; HttpOnly
         Body: { "user": {...}, "team": {...} }
```

**密码处理**: 前端将密码 MD5 哈希后发送，后端存储的也是 MD5 哈希值。

### 3. Admin Impersonate

```
管理员 → GET /api/v1/auth/impersonate?user_id=xxx
       ← 创建目标用户的 Session
       ← Set-Cookie: sl-session=xxx
       ← 302 重定向到控制台
```

### 4. 登出

```
用户 → POST /api/v1/users/logout
     ← 清除 Session
     ← Set-Cookie: sl-session=; Max-Age=0
```

## 认证中间件

```go
// 后端认证中间件伪代码
func AuthMiddleware(next echo.HandlerFunc) echo.HandlerFunc {
    return func(c echo.Context) error {
        cookie, err := c.Cookie("sl-session")
        if err != nil {
            return c.JSON(401, {"error": "unauthorized"})
        }

        sessionData, err := redis.Get("sess:" + cookie.Value)
        if err != nil {
            return c.JSON(401, {"error": "invalid session"})
        }

        // 注入用户信息到 context
        c.Set("user_id", sessionData.UserID)
        c.Set("team_id", sessionData.TeamID)
        c.Set("is_admin", sessionData.IsAdmin)

        return next(c)
    }
}
```

## 权限层级

| 角色 | 权限 |
|------|------|
| 未认证 | 仅公开端点（登录、验证码） |
| 普通用户 | 用户级端点（模型、任务、对话） |
| Team 管理员 | 团队级端点（团队模型、成员管理） |
| 系统管理员 | 所有端点（用户管理、公开模型、impersonate） |

## 模型访问控制

```go
// 模型可见性规则
func (m *Model) IsAccessible(userID string, teamID string) bool {
    switch m.Owner {
    case "public":
        return true  // 公开模型，所有人可用
    case "team":
        return m.TeamID == teamID  // 团队模型，仅团队成员可用
    case "private":
        return m.UserID == userID  // 私有模型，仅创建者可用
    }
}
```

### Public Model 机制

```go
// 公开模型的 API Key 前缀
const PublicModelKeyPrefix = "public:model:"

func PublicModelKey(modelID string) string {
    return PublicModelKeyPrefix + modelID
}
```

- 管理员创建公开模型时，API Key 自动设为 `public:model:{model_id}`
- 用户使用公开模型时，系统替换为实际的 Provider API Key
- 用户无法看到实际的 Provider API Key

## 反向代理认证策略

对于反向代理，需要：

1. **获取 Session Cookie**: 通过 Team 登录或 OAuth 登录
2. **保持 Session 活跃**: 定期调用 API 刷新 Session
3. **传递 Cookie**: 所有 API 请求携带 `Cookie: sl-session=xxx`

```typescript
// 反向代理中的认证实现
async function authenticate(username: string, password: string): Promise<string> {
  const md5Password = md5(password)
  const response = await fetch('https://monkeycode-ai.com/api/v1/teams/users/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: md5Password }),
  })

  // 从 Set-Cookie header 提取 session
  const setCookie = response.headers.get('set-cookie')
  const match = setCookie?.match(/sl-session=([^;]+)/)
  return match?.[1] || ''
}
```
