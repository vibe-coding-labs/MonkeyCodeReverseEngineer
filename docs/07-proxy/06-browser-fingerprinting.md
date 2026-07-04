---
description: 代理层浏览器指纹伪装系统 — 4 域名专用请求头生成器、Chrome 148 精确模拟
protocol_version: based on proxy/src/browser-headers.ts (87 行)
confidence: high
last_verified: 2026-06-28
---

# 浏览器指纹伪装系统

## 1. 系统概述

`proxy/src/browser-headers.ts` 是代理层的一个**关键安全模块**（87 行），负责生成精确的浏览器请求头，以绕过 API 网关的机器人检测。

```
浏览器指纹伪装系统
─────────────────
                                      ┌──────────────────┐
mkHeaders(domain="monkeycode-ai.com") │ MonkeyCode API    │
──────────────────────────────────────┤ 请求头生成器       │
                                      └──────────────────┘
                                      ┌──────────────────┐
bzHeaders(domain="baizhi.cloud")      │ 百智云 API        │
──────────────────────────────────────┤ 请求头生成器       │
                                      └──────────────────┘
                                      ┌──────────────────┐
scHeaders(SCaptcha)                   │ SCaptcha 验证码   │
──────────────────────────────────────┤ 请求头生成器       │
                                      └──────────────────┘
                                      ┌──────────────────┐
navHeaders(任意 domain)               │ 页面导航（非 XHR） │
──────────────────────────────────────┤ 请求头生成器       │
                                      └──────────────────┘
                                      ┌──────────────────┐
wsHeaders(domain, cookie)             │ WebSocket         │
──────────────────────────────────────┤ 连接请求头生成器    │
                                      └──────────────────┘
```

## 2. 基础伪造头

所有变体共享的基准用户代理和 Accept 语言：

```typescript
// proxy/src/browser-headers.ts
const BASE_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/148.0.0.0 Safari/537.36"

const BASE_ACCEPT = "application/json, text/plain, */*"
const BASE_ACCEPT_LANG = "zh-CN,zh;q=0.9,en;q=0.8"
const BASE_SEC_CH =
  '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"'
```

## 3. 基础合并函数

```typescript
function merge(
  domain: string,
  extra: Record<string, string> = {}
): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    Accept: BASE_ACCEPT,
    "Accept-Language": BASE_ACCEPT_LANG,
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": BASE_SEC_CH,
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    Origin: `https://${domain}`,
    Referer: `https://${domain}/`,
    Priority: "u=1, i",
    ...extra,
  }
}
```

## 4. 四种专用生成器

### 4.1 MonkeyCode API（`mkHeaders()`）

```typescript
// 用途: 所有对 monkeycode-ai.com 的 XHR/fetch 请求
// Origin: https://monkeycode-ai.com
// Sec-Fetch-Site: same-origin
export function mkHeaders(
  extra: Record<string, string> = {}
): Record<string, string> {
  return merge("monkeycode-ai.com", extra)
}
```

✅ 特点：XHR 请求风格（`Sec-Fetch-Dest: empty`, `Sec-Fetch-Mode: cors`）

### 4.2 百智云 API（`bzHeaders()`）

```typescript
// 用途: 对 baizhi.cloud 的 XHR 请求（OAuth 登录流程）
// Origin: https://baizhi.cloud
// Sec-Fetch-Site: same-origin
export function bzHeaders(
  extra: Record<string, string> = {}
): Record<string, string> {
  return merge("baizhi.cloud", extra)
}
```

✅ 特点：与 mkHeaders 结构相同，仅域名不同

### 4.3 SCaptcha API（`scHeaders()`）

```typescript
// 用途: 对 *.s-captcha-r1.com 的 challenge 请求
// Origin: https://monkeycode-ai.com（作为 "父页面"）
// Referer: https://monkeycode-ai.com/
export function scHeaders(
  extra: Record<string, string> = {}
): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    Accept: BASE_ACCEPT,
    "Accept-Language": BASE_ACCEPT_LANG,
    "Content-Type": "application/json",   // 始终 JSON
    "Origin": "https://monkeycode-ai.com",
    "Referer": "https://monkeycode-ai.com/",
    ...extra,
  }
}
```

⚠️ 重要区别：SCaptcha 是跨域请求，其 Origin 来自 monkeycode-ai.com 页面内嵌的验证码 iframe/script，而非直接访问。`NODE_TLS_REJECT_UNAUTHORIZED = "0"` 被临时设置——这表明 SCaptcha 端点可能存在证书问题。

### 4.4 页面导航（`navHeaders()`）

```typescript
// 用途: 模拟浏览器地址栏输入/页面跳转（非 XHR）
// Accept: text/html（浏览器导航请求）
// Sec-Fetch-Mode: navigate
// Upgrade-Insecure-Requests: 1
export function navHeaders(
  domain: string,
  extra: Record<string, string> = {}
): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9," +
            "image/avif,image/webp,image/apng,*/*;q=0.8," +
            "application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": BASE_ACCEPT_LANG,
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": BASE_SEC_CH,
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",       // 页面文档
    "Sec-Fetch-Mode": "navigate",       // 导航模式
    "Sec-Fetch-Site": "cross-site",     // 跨站跳转
    "Upgrade-Insecure-Requests": "1",   // 浏览器默认
    Priority: "u=0, i",
    ...extra,
  }
}
```

⚠️ 区别：这是唯一使用 `text/html Accept` 和 `navigate` 模式的请求头，用于模拟 OAuth 回调时的页面跳转。

### 4.5 WebSocket 连接头（`wsHeaders()`）

```typescript
// 用途: WebSocket 握手请求头
// Sec-WebSocket-Version: 13
export function wsHeaders(
  domain: string,
  cookie: string
): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    "Accept-Language": BASE_ACCEPT_LANG,
    "Cache-Control": "no-cache",
    Pragma: "no-cache",
    Origin: `https://${domain}`,
    Cookie: cookie,                    // 携带 Session Cookie
    "Sec-WebSocket-Version": "13",    // WebSocket 协议版本
  }
}
```

## 5. 各 API 调用中的请求头使用

| 端点 | 使用的操作 | 请求头函数 | 域名 |
|------|-----------|-----------|------|
| 登录密码 | `auth.ts` loginUser / loginTeam | `mkHeaders()` | monkeycode-ai.com |
| 状态检查 | `auth.ts` checkStatus | `mkHeaders()` | monkeycode-ai.com |
| 模型列表 | `models.ts` fetchModels | `mkHeaders()` | monkeycode-ai.com |
| 创建任务 | `task-runner.ts` createTask | `mkHeaders()` | monkeycode-ai.com |
| 停任务 | `task-runner.ts` stopTask | `mkHeaders()` | monkeycode-ai.com |
| 发送短信码 | `admin-login.ts` sendSmsCode | `bzHeaders()` | baizhi.cloud |
| 百智云登录 | `admin-login.ts` baizhiPhoneLogin | `bzHeaders()` | baizhi.cloud |
| OAuth authorize | `admin-login.ts` baizhiOAuthAuthorize | `bzHeaders()` + `navHeaders()` | baizhi.cloud |
| MonkeyCode 回调 | `admin-login.ts` monkeycodeCallback | `navHeaders()` | monkeycode-ai.com |
| SCaptcha 挑战 | `admin-login.ts` getSCaptchaToken | `scHeaders()` | *.s-captcha-r1.com |
| WS 连接 | `task-runner.ts` streamTask | `wsHeaders()` | monkeycode-ai.com |

## 6. 安全与防检测分析

### 6.1 浏览器指纹完整度

| 指纹维度 | 设置值 | 检测用途 |
|---------|--------|---------|
| User-Agent | Chrome 148 / macOS | 操作系统 + 浏览器识别 |
| Accept-Language | zh-CN,zh;q=0.9,en;q=0.8 | 语言偏好（中文优先） |
| Sec-CH-UA | Chromium;v="148" | 浏览器品牌版本 |
| Sec-CH-UA-Platform | "macOS" | 操作系统 |
| Sec-Fetch-* | 根据场景不同 | 请求来源类型检测 |
| Origin/Referer | 自动域名匹配 | 同源策略 |
| Accept-Encoding | gzip, deflate, br | 压缩协议兼容 |

### 6.2 可能被检测的信号

| 信号 | 当前处理 | 改进建议 |
|------|---------|---------|
| 请求间隔（无人工延迟） | 立即连续发送 | 加入随机延迟（300-3000ms） |
| 无鼠标/键盘事件 | 无 | 可通过 Playwright 增加交互 |
| 固定 UA 字符串 | 所有请求共享 | 每个账号使用不同 UA |
| 无 Cookie 以外的认证 | Session Cookie 固定 | 可添加额外 HTTP 头 |
| 无 WebDriver 标志 | 无 | 使用真实浏览器或 Playwright stealth |

### 6.3 SCaptcha 证书问题

```typescript
// admin-login.ts — SCaptcha 绕过 TLS 验证
const originalTlsSetting = process.env.NODE_TLS_REJECT_UNAUTHORIZED
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0"
// ... 发起请求 ...
// 恢复原始设置
```

这表明 SCaptcha 服务可能存在 TLS 证书验证问题，或者代理环境中的证书信任链不完整。

---

## 相关章节

- [OAuth 自动化协议](05-oauth-automation.md) — 使用这些请求头的登录流程
- [认证自动化](../02-auth/07-auth-automation.md) — 自动化的具体实现
- [号池状态管理](../02-auth/08-pool-gap-analysis.md) — 多账号管理