---
description: 环境变量全集 — 代理/后端/Electron 所有配置变量含默认值和源码引用
protocol_version: based on proxy/src/ 全部 10 文件 + Electron main.cjs
confidence: high
last_verified: 2026-06-28
---

# 环境变量全集

> **覆盖范围:** TypeScript 代理（10 文件） + Electron 桌面壳 + Python MVP
> **总计:** 30+ 个环境变量，5 个分类

## 1. 代理配置 (proxy/src/)

| 变量 | 必需 | 默认值 | 使用文件 | 说明 |
|------|------|--------|---------|------|
| `MONKEYCODE_BASE_URL` | 否 | `https://monkeycode-ai.com` | `auth.ts`, `task-runner.ts`, `server.ts` | 后端地址 |
| `PROXY_PORT` | 否 | `9090` | `server.ts:24` | 代理监听端口 |
| `ACCOUNT_POOL_FILE` | 否 | — | `server.ts:37` | 号池 JSON 文件路径 |

### 代码示例: 代理环境变量如何加载

```typescript
// server.ts: 环境变量解析
const PORT = parseInt(process.env.PROXY_PORT || "9090", 10)
const poolFile = process.env.ACCOUNT_POOL_FILE || ""

// task-runner.ts: 任务默认配置
const TASK_TIMEOUT_MS = parseInt(process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000", 10)
const DEFAULT_HOST_ID = process.env.MONKEYCODE_HOST_ID || "public_host"
const DEFAULT_IMAGE_ID = process.env.MONKEYCODE_IMAGE_ID || ""
```

## 2. 认证变量 (proxy/src/auth.ts)

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `MONKEYCODE_EMAIL` | 条件 | — | 登录邮箱（与 PASSWORD 配对）|
| `MONKEYCODE_USERNAME` | 否 | — | `EMAIL` 的别名 |
| `MONKEYCODE_PASSWORD` | 条件 | — | 明文密码 |
| `MONKEYCODE_PASSWORD_HASH` | 否 | — | 密码哈希值（备用）|
| `MONKEYCODE_CAPTCHA_TOKEN` | 否 | — | go-cap 验证码 token |
| `MONKEYCODE_LOGIN_MODE` | 否 | `"user"` | 登录模式: `"user"` / `"team"` |
| `MONKEYCODE_SESSION_COOKIE` | 条件 | — | 从浏览器提取的 Session Cookie |

### 认证优先级链

```typescript
// auth.ts 构造函数 — 5 层回退
constructor() {
  // 1. 构造函数参数（最高优先级）
  // 2. ENV: MONKEYCODE_SESSION_COOKIE
  // 3. ENV: MONKEYCODE_EMAIL + MONKEYCODE_PASSWORD
  // 4. ENV: MONKEYCODE_USERNAME + MONKEYCODE_PASSWORD_HASH
  // 5. 报错（无凭据）
  this.email = process.env.MONKEYCODE_EMAIL || process.env.MONKEYCODE_USERNAME || ""
  this.passwordHash = process.env.MONKEYCODE_PASSWORD_HASH || ""
  this.captchaToken = process.env.MONKEYCODE_CAPTCHA_TOKEN || ""
  const plainPassword = process.env.MONKEYCODE_PASSWORD || ""
  if (plainPassword && !this.passwordHash) {
    this.passwordHash = plainPassword.trim()
  }
  const existingCookie = process.env.MONKEYCODE_SESSION_COOKIE || ""
  if (existingCookie) {
    this.sessionCookie = existingCookie
    this.lastAuthTime = Date.now()
  }
}
```

## 3. 任务与 VM 变量 (proxy/src/task-runner.ts)

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `MONKEYCODE_IMAGE_ID` | **是** | — | VM 镜像 UUID（任务创建必需）|
| `MONKEYCODE_HOST_ID` | 否 | `public_host` | VM 宿主机 ID |
| `MONKEYCODE_TASK_TIMEOUT_MS` | 否 | `3600000` (1h) | 任务最大运行时间(ms)|

### IMAGE_ID 发现流程

```typescript
// admin-login.ts — 自动从已有任务中发现 image_id
export async function discoverImageId(sessionCookie: string) {
  const resp = await fetch(
    `${BASE_URL}/api/v1/users/tasks?page=1&size=5`,
    { headers: { Cookie: `monkeycode_ai_session=${sessionCookie}` } }
  )
  const data = await resp.json()
  for (const task of data.data?.tasks || []) {
    if (task.image?.id) {
      return { imageId: task.image.id, imageName: task.image.name }
    }
  }
  return null
}
```

## 4. Electron 桌面壳变量

| 变量 | 默认值 | 使用位置 | 说明 |
|------|--------|---------|------|
| `MONKEYCODE_DESKTOP_URL` | `https://monkeycode-ai.com` | `main.cjs:102` | 桌面壳加载地址 |
| `MONKEYCODE_DESKTOP_START_PATH` | `/console/` | `main.cjs:9` | 登录后的默认路径 |
| `MONKEYCODE_LOAD_LOCAL_DIST` | — | `main.cjs:90` | 加载本地前端构建 |
| `VITE_DEV_SERVER_URL` | `http://localhost:11180` | `main.cjs:87` | 开发模式 Vite 地址 |

```javascript
// Electron main.cjs — 4 种加载模式
// 1. 开发模式
if (isDev) {
  win.loadURL(desktopEntryUrl(process.env.VITE_DEV_SERVER_URL || "http://localhost:11180"))
}
// 2. 本地构建
else if (process.env.MONKEYCODE_LOAD_LOCAL_DIST === "1") {
  win.loadFile(localDistIndexHtml())
}
// 3. 生产模式（默认）
else {
  win.loadURL(desktopEntryUrl(process.env.MONKEYCODE_DESKTOP_URL))
}
// 4. 自定义路径
const START_PATH = process.env.MONKEYCODE_DESKTOP_START_PATH || "/console/"
```

## 5. Go 后端变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MONKEYCODE_REDIS_ADDR` | `localhost:6379` | Redis 地址 |
| `MONKEYCODE_REDIS_PASSWORD` | — | Redis 密码 |
| `MONKEYCODE_DB_DSN` | — | PostgreSQL 连接串 |
| `MONKEYCODE_SERVER_PORT` | `8080` | 后端监听端口 |
| `MONKEYCODE_STRIPE_KEY` | — | Stripe API Key（生产版）|
| `MONKEYCODE_WECHAT_*` | — | 微信支付配置（生产版）|

## 6. Python MVP 变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MONKEYCODE_BASE_URL` | `https://monkeycode-ai.com` | 同 TS 代理 |
| `MONKEYCODE_SESSION_COOKIE` | — | 同 TS 代理 |
| `MONKEYCODE_USERNAME` | — | 同 TS 代理 |
| `MONKEYCODE_PASSWORD` | — | 同 TS 代理 |
| `MONKEYCODE_IMAGE_ID` | — | 同 TS 代理 |
| `PROXY_REAL_PORT` | `9091` | Python 代理端口（与 TS 代理 9090 区分）|
| `MONKEYCODE_TASK_TIMEOUT_MS` | `3600000` | 任务超时(ms)|

## 7. 完整 .env 示例

```bash
# === MonkeyCode 代理配置 ===
MONKEYCODE_BASE_URL=https://monkeycode-ai.com
PROXY_PORT=9090

# === 认证（二选一） ===
# 方式 1: Session Cookie（推荐）
MONKEYCODE_SESSION_COOKIE=your_session_cookie_here

# 方式 2: 密码登录
# MONKEYCODE_EMAIL=user@example.com
# MONKEYCODE_PASSWORD=your_password

# === 号池（可选）===
ACCOUNT_POOL_FILE=./accounts.json

# === 任务配置 ===
MONKEYCODE_IMAGE_ID=uuid_from_discover
MONKEYCODE_HOST_ID=public_host
MONKEYCODE_TASK_TIMEOUT_MS=3600000

# === 调试 ===
# NODE_TLS_REJECT_UNAUTHORIZED=0  # ⚠️ 仅测试用
```

---

## 相关章节

- [术语表](04-glossary.md) — 环境变量速查表
- [代理 server.ts 启动](../07-proxy/08-server-startup.md) — 启动环境变量解析
- [AuthManager 源码](../07-proxy/auth.ts) — 认证优先级