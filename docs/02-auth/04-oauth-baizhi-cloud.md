---
description: 百智云 OAuth 完整流程 — 代理层 6 步纯 HTTP 自动化 + 请求头切换 + SCaptcha
protocol_version: based on proxy/src/admin-login.ts (416 行) + proxy/src/browser-headers.ts
confidence: high
last_verified: 2026-06-28
---

# 百智云 OAuth 完整流程（源码增强版）

## 流程概览

```
用户                     Proxy 代理层           MonkeyCode 后端          百智云平台
 │                          │                       │                      │
 │  1. POST /admin/         │                       │                      │
 │     login/send-code      │                       │                      │
 │─────────────────────────►│                       │                      │
 │                          │  2. GET /api/v1/      │                      │
 │                          │     users/login        │                      │
 │                          ├──────────────────────►│                      │
 │                          │                       │  3. 302 → baizhi     │
 │                          │◄──────────────────────│                      │
 │                          │  4. POST *.s-captcha  │                      │
 │                          │     /v1/api/challenge  │                      │
 │                          ├─────────────────────────────────────────────►│
 │                          │◄─ captcha_token ──────┤                      │
 │                          │  5. POST baizhi/      │                      │
 │                          │     user/phone_code   │                      │
 │                          ├─────────────────────────────────────────────►│
 │                          │◄── SMS sent ──────────┤                      │
 │◄── { message,           │                       │                      │
 │      state } ───────────┤                       │                      │
 │                          │                       │                      │
 │  用户收到短信验证码       │                       │                      │
 │                          │                       │                      │
 │  6. POST /admin/         │                       │                      │
 │     login/verify         │                       │                      │
 │─────────────────────────►│  7. POST baizhi/      │                      │
 │                          │     user/login/phone  │                      │
 │                          ├─────────────────────────────────────────────►│
 │                          │◄── 百智云 Cookie ─────┤                      │
 │                          │  8. GET baizhi/       │                      │
 │                          │     oauth/authorize   │                      │
 │                          ├─────────────────────────────────────────────►│
 │                          │◄── 302 + code ────────┤                      │
 │                          │  9. GET callback URL  │                      │
 │                          ├──────────────────────►│                      │
 │                          │◄── session cookie ────┤                      │
 │                          │ 10. 自动注入:         │                      │
 │                          │     - image_id 发现   │                      │
 │                          │     - 模型缓存刷新    │                      │
 │                          │     - session 注入    │                      │
 │◄── { sessionCookie,     │                       │                      │
 │      imageId, user } ───┤                       │                      │
```

## OAuth 跳转参数（线上实测 + 源码确认）

```http
GET /api/v1/users/login
→ 302 Location: https://baizhi.cloud/oauth/authorize
    ?client_id=monkeycode-ai
    &redirect_uri=https://monkeycode-ai.com/api/v1/users/baizhi/callback
    &response_type=code
    &scope=user+phone
    &state=8abbf170-a3fa-496f-b8c6-63b94f9d2aa0
```

| 参数 | 线上值 | 源码中使用的值 | 说明 |
|------|--------|---------------|------|
| `client_id` | `monkeycode-ai` | `oauth.clientId` | 百智云 OAuth 客户端 ID |
| `redirect_uri` | `https://monkeycode-ai.com/api/v1/users/baizhi/callback` | `oauth.redirectUri` | OAuth 回调路径 |
| `response_type` | `code` | `"code"` | 授权码模式 |
| `scope` | `user phone` | `oauth.scope || "openid profile email"` | 授权范围（源码回退值不同） |
| `state` | 随机 UUID | `oauth.state` | CSRF 防护 |

> **线上与源码差异：** 线上实测 scope=`user phone`，但 admin-login.ts 回退值为 `"openid profile email"`。说明线上配置可能与源码中的默认值不同。

## 代理中的完整自动化（6 步）

TypeScript 代理的 `admin-login.ts`（416 行）实现了完整的 HTTP 自动化流程：

### Step 1: 获取 OAuth 跳转 URL

```typescript
export async function startOAuthLogin(): Promise<{
  oauthUrl: string, state: string, clientId: string, redirectUri: string, scope: string
}> {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/login`, {
    headers: mkHeaders(),         // ← XHR 模式请求头
    redirect: "manual",
  })

  const location = resp.headers.get("Location") || ""
  const url = new URL(location)

  return {
    oauthUrl: location,
    state: url.searchParams.get("state") || "",
    clientId: url.searchParams.get("client_id") || "monkeycode-ai",
    redirectUri: url.searchParams.get("redirect_uri") || "",
    scope: url.searchParams.get("scope") || "openid profile email",
  }
}
```

### Step 2: SCaptcha 验证码

```typescript
const SCAPTCHA_BUSINESS_ID = "0196c95c-620c-7cde-9c2d-b10d0faf5583"
const SCAPTCHA_API = `https://${SCAPTCHA_BUSINESS_ID}.safepoint.s-captcha-r1.com`

export async function getSCaptchaToken(): Promise<string> {
  const resp = await fetch(`${SCAPTCHA_API}/v1/api/challenge`, {
    method: "POST",
    headers: scHeaders(),   // ← 独立验证码请求头
    body: JSON.stringify({ business_id: SCAPTCHA_BUSINESS_ID }),
  })
  const data = await resp.json()
  return data.data?.token || ""
}
```

### Step 3: 发送短信验证码

```typescript
export async function sendSmsCode(phone: string, captchaToken: string): Promise<boolean> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/phone_code`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),  // ← 百智云 API 头
    body: JSON.stringify({ phone, kind: "login", token: captchaToken }),
  })
  return true
}
```

### Step 4: 百智云手机号登录

```typescript
async function baizhiPhoneLogin(phone: string, code: string): Promise<{ cookies: string; data: any }> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/login/phone`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ phone, code }),
  })

  // 从 Set-Cookie 提取百智云 Cookies
  const setCookie = resp.headers.get("Set-Cookie") || ""
  const cookies: string[] = []
  for (const part of setCookie.split(",")) {
    const match = part.trim().match(/^([^=]+)=([^;]+)/)
    if (match) cookies.push(`${match[1]}=${match[2]}`)
  }
  return { cookies: cookies.join("; "), data: data.data }
}
```

### Step 5: OAuth 授权（❗ 请求头切换关键点）

```typescript
async function baizhiOAuthAuthorize(
  baizhiCookies: string, clientId: string, redirectUri: string,
  scope: string, state: string
): Promise<{ code: string; callbackUrl: string }> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/oauth/authorize?${params}`, {
    headers: {
      ...bzHeaders(),
      Cookie: baizhiCookies,
      // ❗ 切换到页面导航模式！不再是 XHR
      Accept: navHeaders("baizhi.cloud").Accept,  // text/html
      "Sec-Fetch-Dest": "document",
      "Sec-Fetch-Mode": "navigate",
      "Upgrade-Insecure-Requests": "1",
    },
    redirect: "manual",
  })

  const location = resp.headers.get("Location") || ""
  const url = new URL(location)
  const code = url.searchParams.get("code") || ""
  return { code, callbackUrl: location }
}
```

### Step 6: MonkeyCode 回调

```typescript
async function monkeycodeCallback(callbackUrl: string): Promise<string> {
  const resp = await fetch(callbackUrl, {
    headers: navHeaders("monkeycode-ai.com", {
      "Sec-Fetch-Site": "cross-site",  // ← 跨站点跳转
      Referer: "https://baizhi.cloud/",
    }),
    redirect: "manual",
  })

  // 方法 1: 直接提取 Cookie
  const match = resp.headers.get("Set-Cookie")
    ?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
  if (match) return match[1]

  // 方法 2: 跟随额外重定向后再提取
  const location = resp.headers.get("Location") || ""
  if (location) {
    const resp2 = await fetch(
      location.startsWith("http") ? location : `${MONKEYCODE_BASE_URL}${location}`,
      { headers: mkHeaders(), redirect: "manual" }
    )
    const match2 = resp2.headers.get("Set-Cookie")
      ?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
    if (match2) return match2[1]
  }
  throw new Error("Failed to extract session cookie")
}
```

## 请求头切换策略

每一步使用不同的浏览器指纹伪装，模拟真实用户的浏览器行为：

| Step | 目标域名 | 请求头函数 | Sec-Fetch-Mode | 模拟行为 |
|------|---------|-----------|---------------|---------|
| 1 | monkeycode-ai.com | `mkHeaders()` | cors | XHR 获取 OAuth 参数 |
| 2 | *.s-captcha-r1.com | `scHeaders()` | — | 内置验证码 iframe 请求 |
| 3 | baizhi.cloud | `bzHeaders()` | cors | XHR 发送短信 |
| 4 | baizhi.cloud | `bzHeaders()` | cors | XHR 登录 |
| 5 | baizhi.cloud | `bzHeaders()` + `navHeaders()` | **navigate** | **页面跳转授权** |
| 6 | monkeycode-ai.com | `navHeaders()` | **navigate** | **回调页面** |

## OAuth 会话管理

```typescript
// 全局 OAuth 会话状态
let currentOAuthSession: OAuthSession | null = null

export interface OAuthSession {
  phone: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
  baizhiCookies: string    // 百智云登录态 cookies
  createdAt: number        // 创建时间（10 分钟超时）
}
```

## 备用方式：手动回调 URL 登录

```typescript
// 适用于用户从浏览器复制 OAuth 回调 URL
app.post("/admin/login/callback", async (req, res) => {
  const { callbackUrl } = req.body
  // 直接从 step 6 开始
  const result = await loginWithCallbackUrl(callbackUrl)
  singleAuth?.setSessionCookie(result.sessionCookie)
})
```

## 安全敏感点

| 项目 | 说明 | 风险 | 建议 |
|------|------|------|------|
| SCaptcha TLS 禁用 | `NODE_TLS_REJECT_UNAUTHORIZED="0"` | 🟡 中 | 修复证书链，移除该配置 |
| 全局 OAuth 状态 | `currentOAuthSession` 内存变量 | 🟡 多实例不支持 | 改为 Redis 共享存储 |
| 10 分钟超时 | OAuth 会话自动失效 | ✅ 安全 | 保持 |
| 管理端点无认证 | `/admin/login/*` 无需 Cookie | 🔴 高 | 绑定 localhost 或加密码 |
| scope 值差异 | 源码默认值 ≠ 线上实际值 | 🟡 低 | 以线上实测为准 |

---

## 相关章节

- [OAuth HTTP 自动化](../07-proxy/06-oauth-automation-http.md) — 纯 HTTP 自动化实现
- [浏览器指纹伪装](../07-proxy/06-browser-fingerprinting.md) — 请求头生成器
- [认证自动化](07-auth-automation.md) — Session 管理策略
- [安全测试报告](../09-security/baizhi-security-report.md) — SCaptcha 漏洞