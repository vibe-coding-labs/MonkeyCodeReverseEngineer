---
description: Admin 管理 API 完整分析 — 基于代理源码 server.ts 和 Go 后端的完整端点和权限分析
protocol_version: based on chaitin/MonkeyCode + proxy/src/server.ts + api-endpoints.md
confidence: high
last_verified: 2026-06-28
---

# 管理后台 API

## 1. 两套管理系统

MonkeyCode 存在**两套平行的管理端点**：后端 Go Admin API 和代理层管理端点。

```
后端 Admin API (Go)
──────────────────
需要管理员角色 + Cookie 认证
管理真实资源：用户、模型、VM、Host

代理管理端点 (TypeScript)
────────────────────
无内置认证
管理代理层状态：Session、号池、模型缓存
```

## 2. 后端 Admin API（Go）

### 2.1 Admin 端点完整列表

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v1/auth/impersonate?user_id=xxx` | Admin | 模拟用户登录 |
| GET | `/api/v1/admin/users?limit=20&cursor=xxx` | Admin | 列出所有用户 |
| GET | `/api/v1/admin/users/{id}` | Admin | 用户详情 |
| PUT | `/api/v1/admin/users/{id}` | Admin | 更新用户信息 |
| DELETE | `/api/v1/admin/users/{id}` | Admin | 删除用户 |
| GET | `/api/v1/admin/models` | Admin | 列出所有模型 |
| POST | `/api/v1/admin/models` | Admin | 创建公开模型 |
| PUT | `/api/v1/admin/models/{id}` | Admin | 更新公开模型 |
| DELETE | `/api/v1/admin/models/{id}` | Admin | 删除公开模型 |
| GET | `/api/v1/admin/vms` | Admin | 列出所有 VM |
| GET | `/api/v1/admin/hosts` | Admin | 列出所有主机 |
| GET | `/api/v1/admin/stats` | Admin | 系统统计 |

### 2.2 Impersonate 模拟机制

允许管理员以目标用户身份查看系统，用于排查问题：

```http
GET /api/v1/auth/impersonate?user_id=target-user-uuid
Cookie: monkeycode_ai_session=admin-session

Response: 302 → /console/
Set-Cookie: monkeycode_ai_session=target-user-session; ...
```

**工作原理：**
1. 验证当前用户是否为 admin 角色
2. 查找 target user 的最新 session UUID
3. 制作一个指向该 session 的 Cookie 返回
4. 管理员浏览器变成了目标用户的会话

### 2.3 公开模型创建

```http
POST /api/v1/admin/models
Content-Type: application/json

{
  "provider": "OpenAI",
  "model": "gpt-4o",
  "interface_type": "openai_chat",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-xxx",
  "access_level": "pro",
  "is_free": false,
  "temperature": 0.7,
  "context_limit": 128000,
  "output_limit": 16384
}
```

## 3. 代理管理端点（TypeScript）

### 3.1 端点完整列表

```typescript
// proxy/src/server.ts — 管理端点定义

// === Session / Cookie 管理 ===

// 手动设置 Session Cookie
app.post("/admin/session", express.text(), (req, res) => {
  // 不检查现有认证，直接覆盖
  singleAuth?.setSessionCookie(req.body)
  res.json({ status: "ok" })
})

// === OAuth 登录管理 ===

// Step 1: 发送短信验证码
app.post("/admin/login/send-code", async (req, res) => {
  const { phone } = req.body
  // 触发百智云 OAuth 登录流程
})

// Step 2: 验证短信码 + 完成 OAuth
app.post("/admin/login/verify", async (req, res) => {
  const { code } = req.body
  // 完成 OAuth 流程，获取 session cookie
  // 自动注入到 AuthManager
  // 自动发现 image_id
  // 自动刷新模型缓存
})

// Step 3: 直接用回调 URL 登录（手动模式）
app.post("/admin/login/callback", async (req, res) => {
  const { callbackUrl } = req.body
})

// 自动发现 image_id（用已有 session）
app.get("/admin/discover", async (_req, res) => {
  // 从已有任务列表中发现 image_id
  // 获取可用模型列表
})

// === 号池管理 ===

// 号池状态查询
app.get("/admin/pool/status", (_req, res) => {
  if (!accountPool) { res.json({ mode: "single" }); return }
  res.json({ mode: "pool", ...accountPool.getStats() })
})

// 号池刷新（所有账号重登录）
app.post("/admin/pool/refresh", async (_req, res) => {
  accountPool.stopHealthCheck()
  await accountPool.initAll()
  accountPool.startHealthCheck()
  res.json({ status: "ok", ...accountPool.getStats() })
})

// === 模型管理 ===

// 刷新模型缓存
app.post("/admin/refresh-models", async (_req, res) => {
  modelManager.clearCache()
  const models = await modelManager.fetchModels()
  res.json({ status: "ok", count: models.length })
})
```

### 3.2 OAuth 登录流程的代理自动化

代理层的 `/admin/login/send-code` + `/admin/login/verify` 实现完整的 OAuth 自动化：

```typescript
// proxy/src/admin-login.ts — 全局会话状态管理
let currentOAuthSession: OAuthSession | null = null

export interface OAuthSession {
  phone: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
  baizhiCookies: string
  createdAt: number
}
```

**登录流程的状态管理：**
1. `initiateLogin(phone)` — 保存 `OAuthSession` 到全局变量
2. `completeLogin(code)` — 读取 `OAuthSession`，完成 6 步流程
3. 会话 **10 分钟过期** — `createdAt + 10min` 后自动清空

### 3.3 OAuth 会话的 10 分钟超时保护

```typescript
// proxy/src/admin-login.ts
export async function completeLogin(smsCode: string): Promise<{
  sessionCookie: string
  imageId?: string
  imageName?: string
  models?: any[]
  user?: any
}> {
  if (!currentOAuthSession) {
    throw new Error("No pending login session. Call POST /admin/login/send-code first.")
  }

  // 10 分钟超时
  if (Date.now() - currentOAuthSession.createdAt > 10 * 60 * 1000) {
    currentOAuthSession = null
    throw new Error("Login session expired. Please request a new SMS code.")
  }
  // ...
}
```

## 4. 权限模型对比

| 特性 | 后端 Admin API | 代理管理端点 |
|------|---------------|-------------|
| 认证方式 | Cookie Session | 无认证 |
| 角色检查 | `role === "admin"` | 无 |
| 资源范围 | 所有用户/模型/VM | 代理本地状态 |
| 网络隔离 | 无（需从外部访问） | 建议绑定 127.0.0.1 |
| 风险等级 | 中（有认证保护） | 高（无保护，需运维控制） |

## 5. 代理管理端点的 AuthManager 状态管理

```typescript
// proxy/src/server.ts — 手动设置 Cookie 端点
app.post("/admin/session", express.text(), (req, res) => {
  const cookie = req.body
  if (!cookie) {
    res.status(400).json({ error: "Cookie value required" })
    return
  }
  singleAuth?.setSessionCookie(cookie)
  res.json({ status: "ok", message: "Session cookie set" })
})

// OAuth 登录后自动注入
app.post("/admin/login/verify", async (req, res) => {
  // ...
  if (singleAuth) {
    singleAuth.setSessionCookie(result.sessionCookie)
  }
  // 自动设置 image_id
  if (result.imageId) {
    process.env.MONKEYCODE_IMAGE_ID = result.imageId
  }
  // 自动刷新模型缓存
  modelManager.clearCache()
  await modelManager.fetchModels()
})
```

## 6. 运维建议

### 6.1 代理管理端点保护

```bash
# 方案 1：只绑定 localhost（推荐）
PROXY_PORT=9090
# 使用 nginx 反向代理，只暴露 API 端点

# 方案 2：iptables 限制管理端点
iptables -A INPUT -p tcp --dport 9090 -s 127.0.0.1 -j ACCEPT
iptables -A INPUT -p tcp --dport 9090 -j DROP
```

### 6.2 使用 curl 管理代理

```bash
# 手动设置 Session Cookie
curl -X POST http://localhost:9090/admin/session \
  -H "Content-Type: text/plain" \
  -d "your-session-cookie-value"

# 检查号池状态
curl http://localhost:9090/admin/pool/status

# 刷新模型缓存
curl -X POST http://localhost:9090/admin/refresh-models

# 刷新号池
curl -X POST http://localhost:9090/admin/pool/refresh

# 自动发现 image_id
curl http://localhost:9090/admin/discover?session_cookie=xxx

# OAuth 登录
curl -X POST http://localhost:9090/admin/login/send-code \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800138000"}'
# 收到短信后：
curl -X POST http://localhost:9090/admin/login/verify \
  -H "Content-Type: application/json" \
  -d '{"code": "123456"}'
```

### 6.3 安全建议总结

| 风险 | 严重程度 | 建议 |
|------|---------|------|
| 管理端点无认证 | 🔴 高 | 绑定 127.0.0.1 + nginx 反向代理 |
| Session Cookie 可覆盖 | 🔴 高 | /admin/session 端点应禁用或加密码 |
| 号池文件明文密码 | 🟡 中 | chmod 600 + 环境变量 |
| OAuth 全局状态 | 🟡 中 | 多实例部署需改为共享存储 |

---

## 相关章节

- [授权层级与访问控制矩阵](02-authorization-matrix.md) — Admin 角色的权限细节
- [完整 API 端点目录](01-endpoint-catalog.md) — 所有端点概览
- [认证中间件](../02-auth/05-auth-middleware.md) — Auth() 中间件实现