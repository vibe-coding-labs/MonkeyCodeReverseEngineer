---
description: 代理号池管理源码全解析 — account-pool.ts (299 行) 账号状态机、双模式获取、错误隔离、健康检查、告警系统
protocol_version: based on proxy/src/account-pool.ts (299 行)
confidence: high
last_verified: 2026-06-28
---

# 代理号池管理源码全解析

> **源码文件:** `proxy/src/account-pool.ts` — 299 行
> **核心类:** `AccountPool` — 多账号管理与轮转
> **核心发现:** 4 种账号状态、HTTP 共享/WS 独占双模式、4 级错误隔离、P0/P1 告警

## 1. 架构总览

```
账号配置 (JSON / ENV)
    │
    ▼
AccountPool
    ├── 账号生命状态机
    │   CREATED → ACTIVE → EXPIRED → REFRESH → ACTIVE / INVALID
    │
    ├── 获取模式
    │   ├── acquireHttp()  — HTTP 共享模式（Round-Robin）
    │   └── acquireWs()    — WS 独占模式（锁定账号）
    │
    ├── 生命周期管理
    │   ├── initAll()       — 初始化全部 CREATED 账号
    │   ├── startHealthCheck() — 每小时健康检查
    │   └── healthCheck()   — Cookie 过期检查 + WS 锁清理 + 状态验证
    │
    ├── 错误处理
    │   ├── handleError()   — 根据错误码分级处理
    │   └── loginAccount()  — 重登录（最多 3 次）
    │
    └── 告警系统
        ├── P0: 可用 < 50%
        ├── P1: 可用 < 70%
        └── P2: 错误率 > 20%
```

## 2. 账号状态机

### 2.1 状态定义

```typescript
export type AccountStatus = "CREATED" | "ACTIVE" | "EXPIRED" | "INVALID"
```

```
        提供 cookie         health check 失败
CREATED ──────────► ACTIVE ────────────────► EXPIRED
  │                   │                          │
  │  initAll()        │ 重登录成功                │ 重登录成功
  └──► ACTIVE         └──► ACTIVE ◄──────────────┘
                      │
                      │ 3 次重登录失败 / 错误码 40002/3/4
                      └──► INVALID
```

### 2.2 账号条目数据结构

```typescript
interface AccountEntry {
  email: string              // 邮箱
  password: string           // 密码（明文）
  mode: LoginMode            // "user" | "team"
  status: AccountStatus      // 当前状态
  auth: AuthManager          // 认证管理器（持有 Session Cookie）
  cookieSetAt: number | null // Cookie 获取时间
  cookieTTLReached: boolean  // 是否到达 29 天 TTL
  lastUsedAt: number         // 上次使用时间
  errorCount: number         // 连续错误计数
  lockedByWs: boolean        // WS 是否锁定
  lockedAt: number | null    // WS 锁定时间
}
```

## 3. 初始化

### 3.1 配置来源

```typescript
// 从 JSON 文件加载多个账号
export interface AccountConfig {
  email: string
  password: string         // 明文密码
  mode?: LoginMode         // "user" | "team"
  cookie?: string          // 预提取的 session cookie（推荐）
  cookieName?: string      // 可覆盖 cookie 名
}

// 从环境变量加载单账号（向后兼容）
const envAccount = loadAccountFromEnv()
// MONKEYCODE_EMAIL + MONKEYCODE_PASSWORD + (可选) MONKEYCODE_SESSION_COOKIE
```

### 3.2 并发初始化

```typescript
async initAll(): Promise<void> {
  const created = this.accounts.filter((a) => a.status === "CREATED")
  // Promise.allSettled：部分失败不阻断全部
  const results = await Promise.allSettled(created.map((a) => this.loginAccount(a)))
  const ok = results.filter((r) => r.status === "fulfilled").length
  console.log(`[AccountPool] Init complete: ${ok}/${created.length} succeeded`)
}
```

## 4. 双模式获取

### 4.1 HTTP 共享模式 (acquireHttp)

```typescript
/** HTTP 共享模式：取最久未用的 ACTIVE 账号，Round-Robin 分散负载 */
acquireHttp(): AuthManager | null {
  const candidates = this.accounts
    .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
    .sort((a, b) => a.lastUsedAt - b.lastUsedAt)

  if (candidates.length === 0) return null

  const idx = this.roundRobinIndex % candidates.length
  this.roundRobinIndex++
  const chosen = candidates[idx]
  chosen.lastUsedAt = Date.now()
  return chosen.auth
}
```

**特征：**
- 只从 ACTIVE 且未被 WS 锁定的账号中选取
- 按 `lastUsedAt` 排序 → 优先使用最久未用的
- `roundRobinIndex` 在不同请求间分散负载
- 不锁定账号，其他 HTTP 请求也可同时使用

### 4.2 WS 独占模式 (acquireWs)

```typescript
/** WebSocket 独占模式：锁定一个账号直到流结束 */
acquireWs(): AuthManager | null {
  const candidates = this.accounts
    .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
    .sort((a, b) => a.lastUsedAt - b.lastUsedAt)

  if (candidates.length === 0) return null

  const chosen = candidates[0]
  chosen.lockedByWs = true
  chosen.lockedAt = Date.now()
  chosen.lastUsedAt = Date.now()
  return chosen.auth
}

/** 释放 WS 独占锁 */
releaseWs(auth: AuthManager): void {
  const entry = this.findByAuth(auth)
  if (entry) {
    entry.lockedByWs = false
    entry.lockedAt = null
  }
}
```

**特征：**
- 锁定账号直到 `releaseWs()` 被调用
- WS 流期间账号不能被其他 WS 或 HTTP 请求使用
- 在 `api-routes.ts` 的 `finally` 块中确保释放

### 4.3 获取优先级

```typescript
// api-routes.ts 中的实际调用模式
let accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null
```

| 优先级 | 获取方式 | 效果 |
|--------|---------|------|
| 1 | `acquireWs()` | WS 独占（用于流式请求） |
| 2 | `acquireHttp()` | HTTP 共享（回退） |
| 3 | `null` | 无可用账号 |

## 5. 健康检查系统

### 5.1 定时检查

```typescript
const HEALTH_CHECK_INTERVAL_MS = 60 * 60 * 1000 // 1 小时

startHealthCheck(): void {
  this.healthTimer = setInterval(() => this.healthCheck(), HEALTH_CHECK_INTERVAL_MS)
}
```

### 5.2 每次检查的内容

```typescript
private async healthCheck(): Promise<void> {
  for (const entry of this.accounts) {
    if (entry.status !== "ACTIVE") continue

    // 1. 清理僵尸 WS 锁（超时未释放）
    if (entry.lockedByWs && entry.lockedAt &&
        Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
      console.warn(`[AccountPool] ${entry.email}: WS lock expired, force releasing`)
      entry.lockedByWs = false
      entry.lockedAt = null
    }

    // 2. Cookie 年龄检查（29 天提前重登录）
    if (entry.cookieSetAt &&
        Date.now() - entry.cookieSetAt > SESSION_MAX_AGE_MS) {
      await this.loginAccount(entry)
      continue
    }

    // 3. 调用 /users/status 检查有效
    const ok = await entry.auth.checkStatus()
    if (!ok) {
      entry.status = "EXPIRED"
      await this.loginAccount(entry)
    }
  }
}
```

**三项检查：**

| 检查 | 条件 | 动作 |
|------|------|------|
| 僵尸 WS 锁 | 锁定时间 > `TASK_TIMEOUT + 60s` | 强制释放 |
| Cookie 年龄 | 设置时间 > **29 天** | 提前重登录 |
| 状态有效性 | `GET /users/status` 返回非 200 | 标记 EXPIRED → 重登录 |

## 6. 错误隔离与重试系统

### 6.1 错误码处理

```typescript
handleError(auth: AuthManager, errorCode: number): boolean {
  const entry = this.findByAuth(auth)
  if (!entry) return false

  switch (errorCode) {
    case 40100: // 会话无效
      entry.status = "EXPIRED"
      this.loginAccount(entry)
      return true   // 可重试（切换账号）

    case 40300: // 权限不足
      return false  // 不可重试

    case 40002: case 40003: case 40004:
      // 密码错误 / 账号被封 / 账号未激活
      entry.status = "INVALID"
      return false

    case 50000: // 服务器错误
      return true   // 可重试（指数退避）
  }
}
```

### 6.2 重登录逻辑

```typescript
private async loginAccount(entry: AccountEntry): Promise<void> {
  try {
    await entry.auth.login()
    entry.status = "ACTIVE"
    entry.cookieSetAt = Date.now()
    entry.cookieTTLReached = false
    entry.errorCount = 0
  } catch (err: any) {
    entry.errorCount++
    if (entry.errorCount >= 3) {
      entry.status = "INVALID"       // 3 次失败 → 永久无效
    }
  }
}
```

### 6.3 错误处理汇总

| 错误码 | 含义 | 动作 | 可重试 |
|--------|------|------|--------|
| 40100 | 会话无效 | 重登录 + 切换账号 | ✅ |
| 40300 | 权限不足 | 仅降级 | ❌ |
| 40002 | 密码错误 | 标记 INVALID | ❌ |
| 40003 | 账号被封 | 标记 INVALID | ❌ |
| 40004 | 账号未激活 | 标记 INVALID | ❌ |
| 50000 | 服务端错误 | 返回可重试 | ✅（应指数退避）|

## 7. 告警阈值

```typescript
private checkAlerts(): void {
  const { total, active } = this.getStats()
  const activeRatio = total > 0 ? active / total : 0

  if (activeRatio < 0.5) {
    console.error(`[AccountPool] P0 ALERT: available accounts < 50% (${active}/${total})`)
  } else if (activeRatio < 0.7) {
    console.warn(`[AccountPool] P1 WARN: available accounts < 70% (${active}/${total})`)
  }
}
```

| 级别 | 阈值 | 行为 |
|------|------|------|
| **P0** | 可用账号 < 50% | `console.error` 日志输出 |
| **P1** | 可用账号 < 70% | `console.warn` 日志输出 |
| **P2** | 错误率 > 20% | 通过 errorCount 追踪 |

## 8. 配置加载

### 8.1 JSON 文件格式

```json
// accounts.json
[
  {
    "email": "user1@example.com",
    "password": "password1",
    "mode": "user",
    "cookie": "pre_extracted_session_cookie_1"
  },
  {
    "email": "admin@company.com",
    "password": "admin_pass",
    "mode": "team"
  }
]
```

### 8.2 环境变量加载

```typescript
export function loadAccountFromEnv(): AccountConfig | null {
  const email = process.env.MONKEYCODE_EMAIL || process.env.MONKEYCODE_USERNAME || ""
  const password = process.env.MONKEYCODE_PASSWORD || ""
  if (!email || !password) return null

  return {
    email,
    password,
    mode: (process.env.MONKEYCODE_LOGIN_MODE as LoginMode) || "user",
    cookie: process.env.MONKEYCODE_SESSION_COOKIE || undefined,
  }
}
```

## 9. 统计接口

```typescript
getStats(): { total: number; active: number; expired: number; invalid: number; locked: number } {
  // 返回号池完整状态，用于 /admin/pool/status 端点
}
```

**输出示例：**
```json
{
  "mode": "pool",
  "total": 5,
  "active": 4,
  "expired": 0,
  "invalid": 1,
  "locked": 2
}
```

## 10. 设计模式总结

| 模式 | 实现 | 说明 |
|------|------|------|
| **状态机** | 4 种状态 + 9 条转换边 | 清晰定义账号生命周期 |
| **双模式获取** | acquireHttp / acquireWs | 共享与独占分离 |
| **Round-Robin** | roundRobinIndex 计数器 | HTTP 模式分散负载 |
| **Promise.allSettled** | initAll 并发初始化 | 部分失败不阻断全部 |
| **try/finally** | releaseWs | 确保锁释放 |
| **僵尸锁检测** | healthCheck WS_LOCK_MAX_MS | 防止死锁 |
| **指数退避暗示** | 50000 错误重试 | 错误码驱动的退避 |
| **告警阈值** | 50%/70% | P0/P1 分级告警 |

---

## 相关章节

- [代理架构设计](01-architecture.md) — 模块依赖关系
- [server.ts 启动分析](08-server-startup.md) — 号池初始化
- [多轮对话](03-multi-turn-conversation.md) — WS 锁与对话关联
- [订阅计费绕过](../05-api/04-subscription-billing.md) — 号池绕过策略
