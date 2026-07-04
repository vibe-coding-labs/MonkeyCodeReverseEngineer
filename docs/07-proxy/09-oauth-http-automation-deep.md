---
description: admin-login.ts OAuth HTTP 自动化完整分析——SCaptcha 绕过、百智云登录、OAuth 授权、Session 获取、6 步全流程源码级详解
protocol_version: based on proxy/src/admin-login.ts (416 行, 代理层最大模块)
confidence: high
last_verified: 2026-06-28
---

# OAuth HTTP 自动化（admin-login.ts 源码完整分析）

> **源码文件:** `proxy/src/admin-login.ts` — 416 行
> **分析覆盖:** 100%（所有函数全部覆盖）
> **核心发现:** 6 步纯 HTTP 自动化流程、SCaptcha TLS 绕过、10 分钟会话超时、自动 image_id 发现

## 1. 模块概述

`admin-login.ts` 是代理层**最大的模块**（416 行），实现了完整的 **百智云 OAuth 纯 HTTP 自动化**。它不依赖任何浏览器自动化工具（如 Playwright/Puppeteer），通过模拟 HTTP 请求完成从短信验证到 Session Cookie 获取的全流程。

### 暴露的 6 个公共函数

| 函数 | 行数 | 用途 | 调用的私有函数 |
|------|------|------|---------------|
| `startOAuthLogin()` | 11 | Step 1: 获取 OAuth 跳转参数 | — |
| `getSCaptchaToken()` | 35 | Step 2: 获取 SCaptcha token | — |
| `sendSmsCode(phone, token)` | 23 | Step 3: 发送短信验证码 | — |
| `initiateLogin(phone)` | 24 | 组合 Step 1~3，创建 OAuth 会话 | `startOAuthLogin`, `getSCaptchaToken`, `sendSmsCode` |
| `completeLogin(code)` | 65 | Step 4~6: 验证码→Session Cookie | `baizhiPhoneLogin`, `baizhiOAuthAuthorize`, `monkeycodeCallback` + `discoverImageId`, `discoverModels`, `verifySession` |
| `loginWithCallbackUrl(url)` | 20 | 备用：直接由回调 URL 登录 | `monkeycodeCallback`, `discoverImageId` |

### 内部辅助函数

| 函数 | 行数 | 用途 |
|------|------|------|
| `baizhiPhoneLogin(phone, code)` | 30 | Step 4: 百智云手机号登录 |
| `baizhiOAuthAuthorize(...)` | 37 | Step 5: OAuth 授权 |
| `monkeycodeCallback(callbackUrl)` | 34 | Step 6: MonkeyCode 回调换 Session |
| `verifySession(cookie)` | 15 | 验证 Session Cookie 是否有效 |
| `discoverImageId(cookie)` | 30 | 从任务列表发现 image_id |
| `discoverModels(cookie)` | 13 | 获取模型列表 |

## 2. 6 步骤 OAuth 自动化详解

### 2.1 Step 1: 获取 OAuth 参数

```typescript
// 1. 请求 GET /api/v1/users/login
// 响应 302 → Location: https://baizhi.cloud/oauth/authorize?client_id=monkeycode-ai&...
export async function startOAuthLogin(): Promise<{
  oauthUrl: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
}> {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/login`, {
    headers: mkHeaders(),
    redirect: "manual",  // ← 关键：不自动跟随 302
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

**请求/响应示例：**

```http
GET /api/v1/users/login HTTP/1.1
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...
Accept: application/json, text/plain, */*
Sec-Fetch-Site: same-origin
Origin: https://monkeycode-ai.com

← HTTP/1.1 302 Found
Location: https://baizhi.cloud/oauth/authorize
  ?client_id=monkeycode-ai
  &redirect_uri=https://monkeycode-ai.com/api/v1/users/baizhi/callback
  &response_type=code
  &scope=user+phone
  &state=550e8400-e29b-41d4-a716-446655440000
```

### 2.2 Step 2: 获取 SCaptcha Token（含 TLS 绕过）

```typescript
// 2. 获取 SCaptcha 验证码 token
export async function getSCaptchaToken(): Promise<string> {
  // ⚠️ 安全风险：临时禁用 TLS 证书验证
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
    // 恢复原始 TLS 设置
    if (originalTlsSetting === undefined) {
      delete process.env.NODE_TLS_REJECT_UNAUTHORIZED
    } else {
      process.env.NODE_TLS_REJECT_UNAUTHORIZED = originalTlsSetting
    }
  }

  const data = await resp.json() as any
  if (!data.success) {
    throw new Error(`SCaptcha failed: ${JSON.stringify(data)}`)
  }
  return data.data?.token || ""
}
```

**SCaptcha 请求/响应：**

```http
POST /v1/api/challenge HTTP/1.1
Host: 0196c95c-620c-7cde-9c2d-b10d0faf5583.safepoint.s-captcha-r1.com
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...
Content-Type: application/json

{"business_id": "0196c95c-620c-7cde-9c2d-b10d0faf5583"}

← HTTP/1.1 200 OK
{"success": true, "data": {"token": "sc_captcha_token_xxx"}}
```

### 2.3 Step 3: 发送短信验证码

```typescript
// 3. 向百智云发送短信验证码
export async function sendSmsCode(phone: string, captchaToken: string): Promise<boolean> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/phone_code`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      phone,
      kind: "login",
      token: captchaToken,
    }),
  })

  const data = await resp.json() as any
  if (data.code !== 0) {
    throw new Error(`SMS send error: code=${data.code}, msg=${data.message}`)
  }
  return true
}
```

**请求示例：**

```http
POST /api/v1/user/phone_code HTTP/1.1
Host: baizhi.cloud
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...
Origin: https://baizhi.cloud
Sec-Fetch-Site: same-origin
Content-Type: application/json

{"phone": "138xxxx8888", "kind": "login", "token": "sc_captcha_token_xxx"}

← HTTP/1.1 200 OK
{"code": 0, "message": "success"}
```

### 2.4 Step 4: 百智云手机号登录

```typescript
// 4. 用短信验证码登录百智云，获取百智云 Session Cookie
async function baizhiPhoneLogin(
  phone: string, code: string
): Promise<{ cookies: string; data: any }> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/login/phone`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ phone, code }),
  })

  if (!resp.ok) throw new Error(`百智云 login failed: ${resp.status}`)

  const data = await resp.json() as any
  if (data.code !== 0) {
    throw new Error(`百智云 login error: code=${data.code}, msg=${data.message}`)
  }

  // 从 Set-Cookie 中提取所有 Cookie
  const setCookie = resp.headers.get("Set-Cookie") || ""
  const cookies: string[] = []
  for (const part of setCookie.split(",")) {
    const match = part.trim().match(/^([^=]+)=([^;]+)/)
    if (match) cookies.push(`${match[1]}=${match[2]}`)
  }

  return { cookies: cookies.join("; "), data: data.data }
}
```

### 2.5 Step 5: OAuth 授权

```typescript
// 5. 用百智云 Session 请求 OAuth 授权 → 获取 authorization code
async function baizhiOAuthAuthorize(
  baizhiCookies: string,
  clientId: string, redirectUri: string,
  scope: string, state: string
): Promise<{ code: string; callbackUrl: string }> {
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    scope, state,
    response_type: "code",
  })

  const resp = await fetch(`${BAIZHI_URL}/api/v1/oauth/authorize?${params}`, {
    headers: {
      ...bzHeaders(),
      Cookie: baizhiCookies,
      Accept: navHeaders("baizhi.cloud").Accept,
      "Sec-Fetch-Dest": "document",
      "Sec-Fetch-Mode": "navigate",
      "Upgrade-Insecure-Requests": "1",
    },
    redirect: "manual",
  })

  // 百智云返回 302 → Location 中携带 code
  const location = resp.headers.get("Location") || ""
  const url = new URL(location)
  const code = url.searchParams.get("code") || ""
  if (!code) {
    const error = url.searchParams.get("error") || "unknown"
    throw new Error(`OAuth authorize failed: error=${error}`)
  }

  return { code, callbackUrl: location }
}
```

**关键请求头转换：** Step 5 中使用了 `navHeaders()` 的 `Accept` 和 `Sec-Fetch-*` 值，这是因为 OAuth 授权请求模拟的是**浏览器页面跳转**行为（而非 XHR 请求）：

| 请求头 | XHR 请求（bzHeaders） | 导航请求（navHeaders） |
|--------|---------------------|---------------------|
| Accept | `application/json` | `text/html,application/xhtml+xml,...` |
| Sec-Fetch-Dest | `empty` | `document` |
| Sec-Fetch-Mode | `cors` | `navigate` |

### 2.6 Step 6: MonkeyCode 回调 → Session Cookie

```typescript
// 6. 用 OAuth code 换取 MonkeyCode Session Cookie
async function monkeycodeCallback(callbackUrl: string): Promise<string> {
  const resp = await fetch(callbackUrl, {
    headers: navHeaders("monkeycode-ai.com", {
      "Sec-Fetch-Site": "cross-site",
      Referer: "https://baizhi.cloud/",     // ← Referer 指向百智云（跨站跳转来源）
    }),
    redirect: "manual",
  })

  // 尝试从 Set-Cookie 直接提取
  const setCookie = resp.headers.get("Set-Cookie") || ""
  const match = setCookie.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
  if (match) return match[1]

  // 如果回调返回重定向（302），跟随重定向后查找 Cookie
  const location = resp.headers.get("Location") || ""
  if (location) {
    const resp2 = await fetch(
      location.startsWith("http") ? location : `${MONKEYCODE_BASE_URL}${location}`,
      { headers: mkHeaders(), redirect: "manual" }
    )
    const match2 = resp2.headers.get("Set-Cookie") || ""
      .match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
    if (match2) return match2[1]
  }

  throw new Error("Failed to extract session cookie from callback")
}
```

**回调流程的双重策略：**

```
OAuth 回调 URL（形如 https://monkeycode-ai.com/api/v1/users/baizhi/callback?code=xxx&state=yyy）
  │
  ├── 方案 A：直接提取 Set-Cookie（最终响应包含 Cookie）
  │   └── 成功 → 返回 session cookie
  │
  └── 方案 B：响应是 302 → 跟随重定向 → 提取最终 Cookie
      └── 成功 → 返回 session cookie
      └── 失败 → 抛出异常
```

## 3. OAuth 会话状态管理

### 3.1 会话结构

```typescript
export interface OAuthSession {
  phone: string           // 手机号
  state: string           // CSRF 保护 state 参数
  clientId: string        // OAuth client_id
  redirectUri: string     // OAuth 回调 URL
  scope: string           // 授权范围
  baizhiCookies: string   // 百智云会话 Cookie
  createdAt: number       // 创建时间戳（用于超时判断）
}

// 全局单例会话（一次只能有一个进行中的登录流程）
let currentOAuthSession: OAuthSession | null = null
```

### 3.2 10 分钟超时保护

```typescript
// completeLogin() 中的超时检查
export async function completeLogin(smsCode: string): Promise<{...}> {
  if (!currentOAuthSession) {
    throw new Error("No pending login session. Call send-code first.")
  }

  if (Date.now() - currentOAuthSession.createdAt > 10 * 60 * 1000) {
    currentOAuthSession = null                          // 清除过期会话
    throw new Error("Login session expired. Request new SMS code.")
  }

  // ... 执行登录流程 ...
  currentOAuthSession = null                            // 成功后清除
}
```

## 4. 辅助功能：登录后的自动发现

### 4.1 Image ID 自动发现

```typescript
export async function discoverImageId(sessionCookie: string): Promise<{...} | null> {
  // 从最近的 5 个任务中查找 image_id
  const resp = await fetch(
    `${MONKEYCODE_BASE_URL}/api/v1/users/tasks?page=1&size=5`,
    { headers: mkHeaders({ Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}` }) }
  )

  const data = await resp.json() as any
  const tasks = data.data?.tasks || []

  for (const task of tasks) {
    if (task.image?.id) {
      return { imageId: task.image.id, imageName: task.image.name || "unknown" }
    }
  }
  return null
}
```

### 4.2 验证复用

```typescript
// verifySession 和 discoverModels 被 completeLogin 串联调用：
return {
  sessionCookie,          // 必须
  imageId,                // 可选（来自任务列表）
  imageName,              // 可选
  models,                 // 可选（模型列表）
  user,                   // 可选（用户信息）
}
```

## 5. 完整的 6 步时序图

```
代理 (admin-login.ts)               MonkeyCode API                  百智云 API                 SCaptcha
  │                                    │                              │                         │
  │  initiateLogin(phone)               │                              │                         │
  │────────────────────────────────────►│                              │                         │
  │  GET /api/v1/users/login             │                              │                         │
  │◄──────── 302 + Location ──────────│                              │                         │
  │                                    │                              │                         │
  │                                    │                              │                         │
  │                                    │              POST /v1/api/challenge                   │
  │                                    │────────────────────────────────────────────────────────►│
  │                                    │                              │                  ◄── token │
  │                                    │                              │                         │
  │                                    │     POST /api/v1/user/phone_code                       │
  │                                    │─────────────────────────────►│                         │
  │                                    │◄────────── { code:0 } ─────│                         │
  │◄──────── { state, msg } ──────────│                              │                         │
  │                                    │                              │                         │
  │  completeLogin(code)                │                              │                         │
  │                                    │                              │                         │
  │                                    │     POST /api/v1/user/login/phone                      │
  │                                    │─────────────────────────────►│                         │
  │                                    │◄── { code:0 } + baizhi Cookie                         │
  │                                    │                              │                         │
  │                                    │     GET /api/v1/oauth/authorize?code=...               │
  │                                    │─────────────────────────────►│                         │
  │                                    │◄── 302 + Location(callback)◄                          │
  │                                    │                              │                         │
  │  GET callback?code=xxx&state=yyy    │                              │                         │
  │────────────────────────────────────►│                              │                         │
  │◄── Set-Cookie: monkeycode_ai_session│                              │                         │
  │                                    │                              │                         │
  │  discoverImageId(cookie)            │                              │                         │
  │────────────────────────────────────►│                              │                         │
  │◄── { imageId: "...", ... } ───────│                              │                         │
  │                                    │                              │                         │
  │  discoverModels(cookie)             │                              │                         │
  │────────────────────────────────────►│                              │                         │
  │◄── [{ model, provider, ... }] ────│                              │                         │
```

## 6. 安全分析

### 6.1 SCaptcha Token 的安全风险

```typescript
// ⚠️ TLS 绕过：请求 SCaptcha 时禁用证书验证
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0"
```

| 问题 | 影响 | 根本原因 |
|------|------|---------|
| TLS 证书验证被禁用 | MITM 攻击可拦截 SCaptcha 流量 | SCaptcha 端点证书链可能不完整 |
| `NODE_TLS_REJECT_UNAUTHORIZED` 修改是全局的 | 可能影响其他并发请求 | 使用了 `process.env` 而非 request-level 的 `rejectUnauthorized` |
| 错误恢复实现正确 | 有 `try/finally` 确保恢复 | 正确使用了原始值保存+恢复模式 |

### 6.2 OAuth 会话安全

| 安全方面 | 当前状态 | 评估 |
|---------|---------|------|
| state 参数（CSRF 防护） | 使用随机 UUID | ✅ 有效 |
| 10 分钟会话超时 | 硬编码在 `completeLogin` | ✅ 有限窗口 |
| Session Cookie 内存存储 | 仅内存，不落盘 | ✅ 不持久化 |
| 短信验证码使用限制 | 依赖后端限流 | 🟡 后端检测 |
| 授权码（code）一次性 | 依赖 OAuth 协议保证 | ✅ OAuth 标准 |
| Referer 头伪造 | `navHeaders` 正确设置跨站 Referer | ✅ |

### 6.3 潜在攻击面

```
攻击向量: 短信轰炸
  场景: 反复调用 initiateLogin() 触发发送短信
  影响: 手机号收到大量短信
  缓解: 应用层需限制 SMS 发送频率

攻击向量: 会话固定
  场景: state 参数虽然随机，但 OAuth 会话存储在全局变量中
  影响: 如果多个登录流程并发，会互相覆盖
  缓解: 当前为顺序设计，不支持并发登录
```

## 7. 与 Playwright 方案的对比

| 维度 | HTTP 自动化（admin-login.ts） | Playwright 方案（oauth_login.py） |
|------|---------------------------|--------------------------------|
| 依赖 | 零额外依赖（纯 fetch） | 需要 Playwright + Chromium |
| 速度 | 快（毫秒级 HTTP 请求） | 慢（需要启动浏览器 + 页面渲染） |
| 浏览器指纹 | 手动构造请求头 | 真实浏览器指纹 |
| 验证码处理 | SCaptcha token 直接获取 | 需用户手动干预 |
| 稳定性 | 高（纯协议交互） | 中（依赖页面元素选择器） |
| 适用场景 | 无头服务器、自动化脚本 | 需要人工交互的复杂流程 |

---

## 相关章节

- [代理 server.ts 启动与中间件链](08-server-startup.md) — 如何调用 admin-login.ts 的端点
- [OAuth 自动化协议](05-oauth-automation.md) — Playwright 方案
- [浏览器指纹伪装](06-browser-fingerprinting.md) — 请求头生成器
- [认证自动化](../02-auth/07-auth-automation.md) — 后端认证策略
