---
description: MonkeyCode 代理安全加固分析 — 认证安全、会话管理、错误隔离、请求伪造防护、部署安全
protocol_version: based on proxy/src/ 10 个 TS 文件 + server.ts 中间件链
confidence: high
last_verified: 2026-06-28
---

# MonkeyCode 代理安全加固分析

> **分析范围:** `proxy/src/` 全部 10 个 TypeScript 文件 (~3,031 行)
> **覆盖:** 认证安全、会话管理、错误隔离、请求伪造防护、部署安全、OWASP Top 10 自评
> **关联报告:** [百智云安全测试报告](baizhi-security-report.md) (baizhi.cloud 外部平台)

---

## 1. 认证安全分析

### Session Cookie 管理

```typescript
// 摘自 proxy/src/auth.ts — 会话管理安全分析

// ✅ 安全措施:
// 1. Cookie 使用 HttpOnly（后端设置，JS 不可读）
// 2. Cookie 使用 Secure（仅 HTTPS 传输）
// 3. Cookie 使用 SameSite=Lax（防 CSRF）

// ⚠️ 潜在风险:
// 1. 环境变量中存储的 Cookie 可能被泄露
const existingCookie = process.env.MONKEYCODE_SESSION_COOKIE || ""
if (existingCookie) {
  this.sessionCookie = existingCookie  // 明文内存中
}

// 2. 密码明文在内存和 env 中
this.passwordHash = process.env.MONKEYCODE_PASSWORD || ""

// 3. 24h 无刷新 TTL（后端不刷新，24h 后自动重登录）
private sessionTTL: number = 24 * 60 * 60 * 1000
```

### ⚠️ 安全风险及修复建议

| 风险 | 严重程度 | 描述 | 修复建议 |
|------|---------|------|---------|
| **明文密码在 env** | 🟡 中危 | 密码以明文方式存储在环境变量和运行时内存中 | 使用密码管理器或 KMS 加密存储 |
| **Session Cookie 在 env** | 🟡 中危 | 预提取的 Cookie 以明文存储 | 加密存储或使用密钥管理服务 |
| **无登录失败限流** | 🟡 中危 | login() 方法没有重试限制 | 添加指数退避，限制 5 次/分钟 |
| **无 MFA 支持** | 🟢 低危 | 不支持多因素认证 | 代理层不涉及，后端安全问题 |

---

## 2. 会话安全分析

### Session TTL 管理

```typescript
// 摘自 proxy/src/account-pool.ts — 会话 TTL 配置

// ✅ 合理的 TTL 策略
const SESSION_MAX_AGE_MS = 29 * 24 * 60 * 60 * 1000  // 29 天提前重登录
// 后端 Session 固定 30 天过期，代理在 29 天时提前重登录
// 避免 Session 在请求中过期导致失败

// ⚠️ 风险: 29 天的长 TTL 意味着泄露后长期可用
// 缓解: 代理仅用于可信环境

// ✅ 健康检查自动续期
const HEALTH_CHECK_INTERVAL_MS = 60 * 60 * 1000  // 1 小时一次
// 定期检查 /users/status 端点，自动续期
```

### 会话泄露预防

```typescript
// ✅ 最小化 Cookie 使用范围
// 只在必要的 API 请求中携带 Cookie
async authHeaders(): Promise<Record<string, string>> {
  const cookie = await this.getSessionCookie()
  return {
    Cookie: `${this.sessionCookieName}=${cookie}`,
    "Content-Type": "application/json",
    // 没有额外泄露风险
  }
}

// ✅ 登出时清除会话
async logout(): Promise<void> {
  await fetch(logoutUrl, { method: "POST", headers: {...} })
  this.sessionCookie = ""   // 清空内存中的 Cookie
  this.lastAuthTime = 0
}
```

---

## 3. 错误隔离安全分析

### 错误泄露预防

```typescript
// 摘自 proxy/src/api-routes.ts — 错误信息泄露

// ⚠️ 风险: 错误消息可能包含敏感信息
router.post("/v1/chat/completions", async (req, res) => {
  try {
    // ...
  } catch (err: any) {
    console.error("[Chat] Error:", err.message)
    if (!res.headersSent) {
      res.status(500).json({
        error: { message: err.message, type: "internal_error" }
        // ⚠️ err.message 可能包含 API URL、账号信息等敏感内容
      })
    }
  }
})
```

### 账号隔离安全

```typescript
// 摘自 proxy/src/account-pool.ts

// ✅ 账号级隔离：每个账号独立 AuthManager
for (const cfg of configs) {
  const auth = new AuthManager()  // 每个账号独立的认证实例
  auth.setCredentials(cfg.email, cfg.password, cfg.mode || "user")
  // ...
}

// ✅ 错误隔离：INVALID 账号彻底移出池
case 40002: // 密码错误
case 40003: // 账号被封
case 40004: // 账号未激活
  entry.status = "INVALID"  // 不再使用

// ⚠️ 风险: 账号文件 JSON 明文存储密码
export interface AccountConfig {
  email: string
  password: string     // 明文密码
  // ...
}
```

---

## 4. 请求伪造防护（CSRF/Replay）

### 浏览器头伪装

```typescript
// 摘自 proxy/src/browser-headers.ts — 反指纹识别

// ✅ 精确模拟 Chrome 148 请求头
const BASE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

// ✅ 4 种域名专用请求头
export function mkHeaders(extra = {}) {
  return merge("monkeycode-ai.com", extra)  // 正确的 Referer/Origin
}
export function bzHeaders(extra = {}) {
  return merge("baizhi.cloud", extra)       // 百智云专用
}
export function scHeaders(extra = {}) {
  return { UserAgent, Accept, ..., Origin: "https://monkeycode-ai.com" }  // SCaptcha 专用
}
export function navHeaders(domain, extra = {}) {
  return { Accept: "text/html,...", "Sec-Fetch-Mode": "navigate", ... }  // 页面导航
}

// ✅ WS 专用请求头
export function wsHeaders(domain: string, cookie: string) {
  return {
    "User-Agent": BASE_UA,
    "Origin": `https://${domain}`,  // 正确 Origin
    "Cookie": cookie,               // 必要认证
  }
}
```

### ⚠️ 风险分析

| 风险 | 严重程度 | 分析 |
|------|---------|------|
| **CSRF 令牌** | 🟢 无 | 使用 Cookie-based auth，后端依赖 Cookie 的 SameSite 属性防护，未使用 CSRF token |
| **请求重放** | 🟡 低危 | OAuth code 回调可能被重放（见安全报告），但 API 请求的时效性通过 Session TTL 控制 |
| **Origin 伪造** | 🟢 低危 | 代理端伪造了 Origin/Referer 头，如果被 MITM 可能被利用进行 CSRF |

---

## 5. 部署安全分析

### 中间件链安全

```typescript
// 摘自 proxy/src/server.ts — Express 中间件
const app = express()

// ✅ 安全中间件
app.use(cors())                    // CORS 防护
app.use(express.json({ limit: "10mb" }))  // 请求体大小限制

// ⚠️ 风险: CORS 默认允许所有来源
// app.use(cors()) 等价于 Access-Control-Allow-Origin: *

// ✅ 管理端点需要认证? 不 — 安全风险！
app.post("/admin/session", ...)   // ❌ 无认证 — 任何人都可以设置 Cookie
app.post("/admin/refresh-models", ...)  // ❌ 无认证
app.get("/admin/pool/status", ...)      // ❌ 无认证
app.post("/admin/logout", ...)          // ❌ 无认证
```

### ⚠️ 管理端点安全风险

```typescript
// 摘自 proxy/src/server.ts — 管理端点

// 高风险端点:
// POST /admin/session — 设置 Session Cookie（无认证）
app.post("/admin/session", express.text(), (req, res) => {
  const cookie = req.body       // 接受任意 Cookie
  singleAuth?.setSessionCookie(cookie)  // 立即生效
  res.json({ status: "ok" })
})

// 中风险端点:
// POST /admin/login/send-code — 发送 OAuth 短信
// POST /admin/login/verify — 验证短信码
// 攻击者可以触发短信轰炸

// 低风险端点:
// GET /admin/pool/status — 查看号池状态（信息泄露）
// POST /admin/pool/refresh — 刷新号池
```

### 安全加固建议

```typescript
// ✅ 建议: 为管理端点添加认证
// 方案 1: API Key
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || ""
app.use("/admin", (req, res, next) => {
  const apiKey = req.headers["x-admin-key"]
  if (!ADMIN_API_KEY || apiKey !== ADMIN_API_KEY) {
    return res.status(403).json({ error: "Forbidden" })
  }
  next()
})

// 方案 2: 仅本地监听
app.listen(PORT, "127.0.0.1", () => {  // 仅本地可访问
  console.log(`Proxy listening on 127.0.0.1:${PORT}`)
})

// 方案 3: 基本认证
app.use("/admin", basicAuth({
  users: { admin: process.env.ADMIN_PASSWORD || "changeme" }
}))
```

### 其他部署安全

```typescript
// 摘自 proxy/src/server.ts — 安全配置

// ⚠️ 风险: 请求体限制 10MB（可能过大）
app.use(express.json({ limit: "10mb" }))

// ✅ 建议: 添加安全头
app.use((req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff")
  res.setHeader("X-Frame-Options", "DENY")
  res.setHeader("X-XSS-Protection", "1; mode=block")
  next()
})
```

---

## 6. OAuth 自动化安全分析

### OAuth 流程中的安全风险

```typescript
// 摘自 proxy/src/admin-login.ts — OAuth 安全

// ⚠️ 风险 1: SCaptcha TLS 绕过（依赖外部服务）
export async function getSCaptchaToken(): Promise<string> {
  // SCaptcha 服务证书存在问题 → 使用 --insecure
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0"
  // 如果 MITM 攻击，可以伪造 SCaptcha 响应
}

// ⚠️ 风险 2: OAuth session 仅 10 分钟超时
const OAUTH_SESSION_TIMEOUT = 10 * 60 * 1000  // 10 分钟
if (Date.now() - currentOAuthSession.createdAt > OAUTH_SESSION_TIMEOUT) {
  currentOAuthSession = null
  throw new Error("Login session expired.")
}

// ✅ 合理的超时设计
// 10 分钟对于短信验证码收发足够了
// 过期后清除状态，防止重放
```

---

## 7. OWASP Top 10 自评

| OWASP | 风险 | 代理层状态 | 说明 |
|-------|------|-----------|------|
| A01 | 访问控制失效 | ⚠️ 管理端点无认证 | `/admin/*` 端点需要 API Key 或本地绑定 |
| A02 | 加密失效 | ⚠️ 密码明文存储 | 环境变量中明文密码 |
| A03 | 注入 | ✅ 低风险 | 使用 fetch/WebSocket API，非 SQL 操作 |
| A04 | 不安全设计 | ⚠️ `NODE_TLS_REJECT_UNAUTHORIZED=0` | 仅在 SCaptcha 中使用，但风险较高 |
| A05 | 安全配置错误 | ⚠️ CORS 全开 | `app.use(cors())` 未配置 allowed origins |
| A06 | 敏感信息泄露 | ⚠️ 错误消息可能泄露 | `err.message` 包含 API URL |
| A07 | 认证失效 | ⚠️ 管理端点无认证 | `/admin/session` 可被任意设置 |
| A08 | 数据完整性 | ✅ 低风险 | 使用 HTTPS 传输 |
| A09 | 日志监控不足 | ⚠️ 仅有 console.log | 缺少结构化日志和安全事件告警 |
| A10 | SSRF | 🟢 不适用 | 代理不处理用户提供的 URL |

---

## 8. 安全加固检查清单

### 立即修复（P0）

- [ ] 管理端点添加认证（API Key 或本地绑定 `127.0.0.1`）
- [ ] 环境变量密码加密存储（使用 KMS 或加密工具）

### 建议修复（P1）

- [ ] 配置 CORS 白名单，不使用通配符
- [ ] 错误消息不包含敏感信息（API URL，内部路径）
- [ ] 添加请求频率限制（登录端点 5 次/分钟）
- [ ] 添加安全响应头（X-Content-Type-Options, X-Frame-Options）

### 提升加固（P2）

- [ ] 添加结构化日志（JSON 格式，含 requestId 和 timestamp）
- [ ] 添加安全告警（异常登录模式、大量 401 错误）
- [ ] 添加 Health Check 端点的安全信息（版本号、账号池健康度）
- [ ] 减少请求体限制（10MB → 1MB 或根据实际需求调整）

---

## 相关章节

- [百智云安全测试报告](baizhi-security-report.md) — 外部平台安全测试
- [原始安全测试报告](../../security/baizhi-security-test-2026-06-12.md) — 完整安全测试过程
- [认证协议](../../02-auth/README.md) — 认证安全边界
- [部署与中间件](../../07-proxy/07-deployment-infrastructure.md) — Express 中间件链