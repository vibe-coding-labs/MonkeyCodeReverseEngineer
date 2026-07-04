---
description: MonkeyCode OAuth 纯 HTTP 自动化登录协议 — 6 步纯 HTTP 流程绕过浏览器交互
protocol_version: based on proxy/src/admin-login.ts (416 行) + proxy/src/types.ts
confidence: high
last_verified: 2026-06-28
---

# OAuth 自动化协议（源码增强版）

## 1. 协议架构

MonkeyCode 的代理层实现了 **纯 HTTP 的 OAuth 自动化登录**，不使用浏览器或 Playwright，全程通过 HTTP 请求完成百智云 OAuth 认证。

```
                 纯 HTTP OAuth 自动化登录（6 步）
                 ─────────────────────────────
  Step 1         GET /api/v1/users/login → 302
  [OAuth 启动]    获取 OAuth 参数 (client_id, state, redirect_uri)
                    │
                    ▼
  Step 2         POST *.s-captcha-r1.com/v1/api/challenge
  [SCaptcha]      获取 SCaptcha token (绕过人机验证)
                    │
                    ▼
  Step 3         POST baizhi.cloud/api/v1/user/phone_code
  [发送短信]       请求发送短信验证码到手机号
                    │
                    ▼
  Step 4         POST baizhi.cloud/api/v1/user/login/phone
  [百智云登录]     验证短信码 → 获取百智云 Session Cookie
                    │
                    ▼
  Step 5         GET baizhi.cloud/api/v1/oauth/authorize
  [OAuth Authorize] 用百智云 Cookie 授权 → 获取 redirect code
                    │
                    ▼
  Step 6         GET callback_url (MonkeyCode)
  [回调]          获取 monkeycode_ai_session Cookie
                    │
                    ▼
               ✅ 登录成功
```

## 2. 流程详解

### Step 1: 获取 OAuth 重定向 URL

```typescript
// proxy/src/admin-login.ts
export async function startOAuthLogin(): Promise<{
  oauthUrl: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
}> {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/login`, {
    headers: mkHeaders(),
    redirect: "manual",  // 不自动跟随 302
  })

  if (resp.status !== 302) {
    throw new Error(`Expected 302 redirect, got ${resp.status}`)
  }

  const location = resp.headers.get("Location") || ""
  const url = new URL(location)

  return {
    oauthUrl: location,
    state: url.searchParams.get("state") || "",
    clientId: url.searchParams.get("client_id") || "",
    redirectUri: url.searchParams.get("redirect_uri") || "",
    scope: url.searchParams.get("scope") || "",
  }
}
```

**参数提取结果示例：**
```json
{
  "oauthUrl": "https://baizhi.cloud/api/v1/oauth/authorize?client_id=monkeycode-ai&redirect_uri=https://monkeycode-ai.com/api/v1/users/login/callback&scope=openid+profile+email&state=xxx&response_type=code",
  "state": "xxx",
  "clientId": "monkeycode-ai",
  "redirectUri": "https://monkeycode-ai.com/api/v1/users/login/callback",
  "scope": "openid profile email"
}
```

### Step 2: SCaptcha token 获取

```typescript
export async function getSCaptchaToken(): Promise<string> {
  const originalTlsSetting = process.env.NODE_TLS_REJECT_UNAUTHORIZED
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0"

  let resp: Response
  try {
    resp = await fetch(`${SCAPTCHA_API}/v1/api/challenge`, {
      method: "POST",
      headers: scHeaders(),
      body: JSON.stringify({ business_id: SCAPTCHA_BUSINESS_ID }),
    })
  } finally {
    // 恢复原始的 TLS 设置
    if (originalTlsSetting === undefined) {
      delete process.env.NODE_TLS_REJECT_UNAUTHORIZED
    } else {
      process.env.NODE_TLS_REJECT_UNAUTHORIZED = originalTlsSetting
    }
  }

  const data = await resp.json()
  return data.data?.token || ""
}
```

**关键常量：**
```typescript
const SCAPTCHA_BUSINESS_ID = "0196c95c-620c-7cde-9c2d-b10d0faf5583"
const SCAPTCHA_API = `https://${SCAPTCHA_BUSINESS_ID}.safepoint.s-captcha-r1.com`
```

### Step 3: 发送短信验证码

```typescript
export async function sendSmsCode(phone: string, captchaToken: string): Promise<boolean> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/phone_code`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      phone,
      kind: "login",     // 登录类型短信
      token: captchaToken,  // SCaptcha token
    }),
  })

  const data = await resp.json()
  if (data.code !== 0) {
    throw new Error(`SMS send error: code=${data.code}, msg=${data.message}`)
  }
  return true
}
```

### Step 4: 百智云手机号登录

```typescript
async function baizhiPhoneLogin(
  phone: string,
  code: string  // 短信验证码
): Promise<{ cookies: string; data: any }> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/login/phone`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ phone, code }),
  })

  // 从 Set-Cookie 中提取百智云 cookies
  const setCookie = resp.headers.get("Set-Cookie") || ""
  const cookies: string[] = []
  for (const part of setCookie.split(",")) {
    const match = part.trim().match(/^([^=]+)=([^;]+)/)
    if (match) {
      cookies.push(`${match[1]}=${match[2]}`)
    }
  }

  return { cookies: cookies.join("; "), data: data.data }
}
```

### Step 5: OAuth 授权

```typescript
async function baizhiOAuthAuthorize(
  baizhiCookies: string,
  clientId: string,
  redirectUri: string,
  scope: string,
  state: string
): Promise<{ code: string; callbackUrl: string }> {
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    scope,
    state,
    response_type: "code",
  })

  const resp = await fetch(`${BAIZHI_URL}/api/v1/oauth/authorize?${params}`, {
    headers: {
      ...bzHeaders(),
      Cookie: baizhiCookies,
      // 这里切换到页面导航模式（处理 302 重定向）
      Accept: navHeaders("baizhi.cloud").Accept,
      "Sec-Fetch-Dest": "document",
      "Sec-Fetch-Mode": "navigate",
    },
    redirect: "manual",
  })

  // 百智云返回 302 → 带 code 参数的重定向 URL
  const location = resp.headers.get("Location") || ""
  const url = new URL(location)
  const code = url.searchParams.get("code") || ""

  return { code, callbackUrl: location }
}
```

**OAuth 请求头切换：** 第 5 步从 `bzHeaders()`（XHR 模式）切换到 `navHeaders() + Sec-Fetch-Mode: navigate`（页面导航模式），模拟浏览器地址栏跳转。

### Step 6: MonkeyCode 回调获取 Cookie

```typescript
async function monkeycodeCallback(callbackUrl: string): Promise<string> {
  // 首次请求（直接跟随 callback URL）
  const resp = await fetch(callbackUrl, {
    headers: navHeaders("monkeycode-ai.com", {
      "Sec-Fetch-Site": "cross-site",
      Referer: "https://baizhi.cloud/",
    }),
    redirect: "manual",
  })

  // 尝试从 Set-Cookie 直接提取
  const setCookie = resp.headers.get("Set-Cookie") || ""
  const match = setCookie.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
  if (match) return match[1]

  // 如果 callback 又重定向了（多段重定向），跟随到最终
  const location = resp.headers.get("Location") || ""
  if (location) {
    const resp2 = await fetch(
      location.startsWith("http") ? location : `${MONKEYCODE_BASE_URL}${location}`,
      { headers: mkHeaders(), redirect: "manual" }
    )
    const setCookie2 = resp2.headers.get("Set-Cookie") || ""
    const match2 = setCookie2.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
    if (match2) return match2[1]
  }

  throw new Error("Failed to extract session cookie from callback")
}
```

## 3. 会话状态管理

```typescript
// 全局 OAuth 会话存储 — 跨多步 API 调用保持状态
let currentOAuthSession: OAuthSession | null = null

export interface OAuthSession {
  phone: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
  baizhiCookies: string      // 百智云 session cookies
  createdAt: number           // 创建时间（用于 10 分钟超时）
}
```

**状态管理关键点：**
- 全局变量存储（不适用多实例部署）
- 10 分钟超时自动清空
- `initiateLogin()` 创建 → `completeLogin()` 消费 → 清空

## 4. 完整的 HTTP API 端点

代理通过两个端点暴露 OAuth 流程：

```typescript
// Step 1+2+3: 发送短信验证码
app.post("/admin/login/send-code", async (req, res) => {
  // 1. 获取 OAuth URL 参数
  // 2. 请求 SCaptcha token
  // 3. 发送短信验证码
  // 返回: { message, state }
})

// Step 4+5+6: 验证短信码 → 完成登录
app.post("/admin/login/verify", async (req, res) => {
  // 4. 百智云手机号登录
  // 5. OAuth 授权
  // 6. MonkeyCode 回调 → 获取 session cookie
  // 自动: 注入 AuthManager, 发现 image_id, 刷新模型缓存
  // 返回: { status, sessionCookie, imageId, modelCount, user }
})
```

## 5. 备用模式：回调 URL 直接登录

```typescript
// 手动模式: 用户从浏览器获取 OAuth 回调 URL 后直接提交
app.post("/admin/login/callback", async (req, res) => {
  const { callbackUrl } = req.body
  // 跳过步骤 1-5，直接从步骤 6 开始
  const result = await loginWithCallbackUrl(callbackUrl)
  // 自动注入 AuthManager
})
```

## 6. 各步骤头部切换总结

| 步骤 | 目标域名 | 请求头函数 | Sec-Fetch-Mode | 说明 |
|------|---------|-----------|---------------|------|
| 1 | monkeycode-ai.com | `mkHeaders()` | cors | 获取 OAuth 参数 |
| 2 | *.s-captcha-r1.com | `scHeaders()` | — | 绕过人机验证 |
| 3 | baizhi.cloud | `bzHeaders()` | cors | 发送短信 |
| 4 | baizhi.cloud | `bzHeaders()` | cors | 百智云登录 |
| 5 | baizhi.cloud | `bzHeaders()` + `navHeaders()` | **navigate** | OAuth 授权 |
| 6 | monkeycode-ai.com | `navHeaders()` | **navigate** | 回调获取 Cookie |

---

## 相关章节

- [浏览器指纹伪装](06-browser-fingerprinting.md) — 请求头生成器详解
- [百智云 OAuth](../02-auth/04-oauth-baizhi-cloud.md) — OAuth 登录背景
- [认证自动化](../02-auth/07-auth-automation.md) — Session 管理策略