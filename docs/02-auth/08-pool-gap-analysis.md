---
description: 认证号池差距分析 — 基于 proxy/src/account-pool.ts 源码的完整账号池实现分析
protocol_version: based on chaitin/MonkeyCode + proxy/src/account-pool.ts 源码
confidence: high
last_verified: 2026-06-28
---

# 认证号池差距分析（源码增强版）

## 1. 号池架构总览

MonkeyCode 的号池（AccountPool）模块是一个完整的**多账号管理与轮转系统**，位于 `proxy/src/account-pool.ts`，约 299 行源码。号池在代理层运行，通过轮转多个 MonkeyCode 账号来提供高可用性。

```
┌────────────────────────────────────────────────────────┐
│                    AccountPool                          │
│                                                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ 账号 #1   │  │ 账号 #2   │  │ 账号 #N   │  │  ...   │ │
│  │ ACTIVE   │  │ ACTIVE   │  │ EXPIRED  │  │        │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘ │
│       │              │              │                   │
│       ▼              ▼              ▼                   │
│  ┌────────────────────────────────────────────────┐    │
│  │  状态机: CREATED → ACTIVE → EXPIRED → REFRESH  │    │
│  │           → ACTIVE / INVALID                    │    │
│  └────────────────────────────────────────────────┘    │
│       │              │              │                   │
│       ▼              ▼              ▼                   │
│  ┌────────────────────────────────────────────────┐    │
│  │  获取策略: HTTP 共享模式 / WebSocket 独占模式    │    │
│  └────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────┘
```

## 2. 完整源码架构（account-pool.ts）

### 2.1 账号状态机

```typescript
// proxy/src/account-pool.ts
export type AccountStatus = "CREATED" | "ACTIVE" | "EXPIRED" | "INVALID"

interface AccountEntry {
  email: string
  password: string
  mode: LoginMode          // "user" | "team"
  status: AccountStatus    // 当前状态
  auth: AuthManager        // 关联的认证管理器
  cookieSetAt: number | null  // Cookie 设置时间戳
  cookieTTLReached: boolean   // 是否触发 30 天 TTL
  lastUsedAt: number          // 最后使用时间
  errorCount: number          // 连续失败计数
  lockedByWs: boolean         // WebSocket 独占锁
  lockedAt: number | null     // WS 锁定时间戳
}
```

**状态转换规则：**

```
CREATED ──── initAll() 登录成功 ────→ ACTIVE
ACTIVE ──── 30 天过期或 status 检查失败 ────→ EXPIRED
EXPIRED ──── loginAccount() 重登录成功 ────→ ACTIVE
ACTIVE ──── 连续 3 次登录失败 ────→ INVALID
EXPIRED ──── 连续 3 次登录失败 ────→ INVALID
INVALID ──── (终态) 无法恢复，需手动干预
```

### 2.2 双模式获取策略

号池设计区分了 **HTTP 共享模式** 和 **WebSocket 独占模式**，这是关键设计决策：

#### HTTP 共享模式（`acquireHttp()`）

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

特点：
- **无锁** — 多个 HTTP 请求可以同时使用不同账号
- **Least-Recently-Used 排序** — 优先使用最久未用的账号，分散负载
- **Round-Robin 索引** — 在候选列表中做轮转

#### WebSocket 独占模式（`acquireWs()`）

```typescript
/** WebSocket 独占模式：锁定一个账号直到释放 */
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
```

关键区别：WebSocket 分配后，该账号被标记为 `lockedByWs=true`，直到调用 `releaseWs()` 才释放。这是因为 WebSocket 连接期间（可能长达数分钟甚至数小时）不能共享认证凭据。

### 2.3 账号初始化

```typescript
/** 初始化所有 CREATED 账号的登录 */
async initAll(): Promise<void> {
  const created = this.accounts.filter((a) => a.status === "CREATED")
  const results = await Promise.allSettled(
    created.map((a) => this.loginAccount(a))
  )
  const ok = results.filter((r) => r.status === "fulfilled").length
  console.log(`[AccountPool] Init complete: ${ok}/${created.length} succeeded`)
}
```

- **批量并行登录** — 使用 `Promise.allSettled` 并发登录所有账号
- **部分容忍** — 部分账号登录失败不影响其他账号
- **预置 Cookie 跳过** — 如果 `AccountConfig.cookie` 已有值，状态直接设为 `ACTIVE`

### 2.4 定时健康检查

```typescript
private async healthCheck(): Promise<void> {
  for (const entry of this.accounts) {
    if (entry.status !== "ACTIVE") continue

    // 1. 清理僵尸 WS 锁
    if (entry.lockedByWs && entry.lockedAt &&
        Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
      entry.lockedByWs = false  // 强制释放
    }

    // 2. 检查 Cookie 年龄（30天硬限制）
    if (entry.cookieSetAt &&
        Date.now() - entry.cookieSetAt > SESSION_MAX_AGE_MS) {
      await this.loginAccount(entry)
      continue
    }

    // 3. 调用 /users/status 检查有效性
    try {
      const ok = await entry.auth.checkStatus()
      if (!ok) await this.loginAccount(entry)
    } catch {
      entry.status = "EXPIRED"
    }
  }
}
```

健康检查周期：**1 小时**（`HEALTH_CHECK_INTERVAL_MS = 60 * 60 * 1000`）

检查三件事：
1. **僵尸锁清理** — 超过 `WS_LOCK_MAX_MS`（约 `TASK_TIMEOUT_MS + 1min`）未释放的 WS 锁自动释放
2. **Session 提前刷新** — 在硬过期前 **1 天** 主动重登录（`SESSION_MAX_AGE_MS = 29天`，30 天硬限制）
3. **状态端点验证** — 调用 `/users/status` 确认服务端 session 仍有效

## 3. 错误处理与告警

### 3.1 错误码处理矩阵

```typescript
handleError(auth: AuthManager, errorCode: number): boolean {
  switch (errorCode) {
    case 40100:  // 会话无效
      entry.status = "EXPIRED"
      this.loginAccount(entry).catch(() => {})
      return true  // 调用方可以切换账号重试

    case 40300:  // 权限不足
      return false  // 不可重试

    case 40002:  // 密码错误
    case 40003:  // 账号被封禁
    case 40004:  // 账号未激活
      entry.status = "INVALID"  // 终态，永久不可用
      return false

    case 50000:  // 服务端内部错误
      return true  // 可重试

    default:
      return false
  }
}
```

### 3.2 告警阈值

```typescript
private checkAlerts(): void {
  const activeRatio = active / total

  if (activeRatio < 0.5) {
    // P0 告警: 可用账号低于 50%
    console.error(`P0 ALERT: available accounts < 50% (${active}/${total})`)
  } else if (activeRatio < 0.7) {
    // P1 告警: 可用账号低于 70%
    console.warn(`P1 WARN: available accounts < 70% (${active}/${total})`)
  }
}
```

| 级别 | 触发条件 | 响应要求 |
|------|---------|---------|
| P0 | 可用账号 < 50% | 立即检查账号状态，可能需要补充新账号 |
| P1 | 可用账号 < 70% | 准备替换过期账号 |
| P2 | 错误率 > 20% / 过期率 > 5/h | 检查后端是否在线，调整号池配置 |

## 4. 配置加载方式

### 4.1 JSON 文件配置

```typescript
// 配置文件示例: accounts.json
[
  {
    "email": "user1@example.com",
    "password": "password123",
    "mode": "user",
    "cookie": "...",  // 可选：预提取的 session cookie
    "cookieName": "monkeycode_ai_session"  // 可选：覆盖 cookie 名
  },
  {
    "email": "admin@example.com",
    "password": "admin456",
    "mode": "team",  // 团队管理员登录
    "cookie": "..."
  }
]
```

```typescript
// 从 JSON 文件加载
export async function loadAccountConfigs(filePath: string): Promise<AccountConfig[]> {
  const fs = await import("fs")
  const content = fs.readFileSync(filePath, "utf-8")
  return JSON.parse(content) as AccountConfig[]
}
```

### 4.2 环境变量配置（单账号模式）

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

### 4.3 启动时初始化

```typescript
// server.ts 中的初始化逻辑
// 1. 尝试从 ACCOUNT_POOL_FILE 加载号池配置
const poolFile = process.env.ACCOUNT_POOL_FILE || ""
if (poolFile) {
  accounts = await loadAccountConfigs(resolved)
}

// 2. 从环境变量加载单个账号（作为号池补充）
const envAccount = loadAccountFromEnv()
if (envAccount) accounts.push(envAccount)

// 3. 创建号池并初始化
if (accounts.length > 0) {
  accountPool = new AccountPool(accounts)
  await accountPool.initAll()
  accountPool.startHealthCheck()
}
```

## 5. 生产环境建议配置

### 5.1 最少账号数

| 场景 | 最少账号数 | 推荐账号数 | 说明 |
|------|-----------|-----------|------|
| 个人开发/测试 | 1 | 2 | 1主1备 |
| 小团队使用（<10人） | 2 | 3-5 | 支持并发 WS |
| 公开代理服务 | 5 | 10+ | 需要冗余和负载均衡 |

### 5.2 关键配置参数

```bash
# 号池配置文件路径
ACCOUNT_POOL_FILE=/path/to/accounts.json

# 单个账号凭据（号池补充）
MONKEYCODE_EMAIL=user@example.com
MONKEYCODE_PASSWORD=password
MONKEYCODE_LOGIN_MODE=user    # user | team

# 预提取 Session Cookie（绕过验证码）
MONKEYCODE_SESSION_COOKIE=xxx

# 健康检查间隔（默认 1h）
# (硬编码参数，可在 account-pool.ts 中调整)
# HEALTH_CHECK_INTERVAL_MS = 60 * 60 * 1000
# SESSION_MAX_AGE_MS = 29 * 24 * 60 * 60 * 1000  # 29 天

# 任务超时（影响 WS 锁释放判断）
MONKEYCODE_TASK_TIMEOUT_MS=3600000  # 1h
```

### 5.3 监控与巡检

```bash
# 检查号池状态
curl http://localhost:9090/admin/pool/status

# 输出示例
{
  "mode": "pool",
  "total": 5,
  "active": 4,
  "expired": 1,
  "invalid": 0,
  "locked": 1  // 一个账号被 WebSocket 独占
}

# 刷新所有过期账号
curl -X POST http://localhost:9090/admin/pool/refresh
```

## 6. 与后端 Session 系统的关系

```
后端 (Go)                   代理 (TypeScript)
─────────                   ────────────────
Redis 存储 Session          AccountPool 管理多个账号
├─ Hash Key: session:{uuid} ├─ 每个账号一个 AuthManager
│  - user_id, email, role   │  - 持有 Cookie
│  - created_at, expires_at  │  - 管理 TTL 29天硬限制
└─ Lookup Key: session      └─ 健康检查 1h 轮询
   - user_id → uuid
   
后端不感知号池            代理层在外部实现号池逻辑
(TTL 30天不刷新)           (对应 30 天硬限制策略)
```

## 7. 差距分析与改进建议

### 已覆盖的功能

| 功能 | 源码位置 | 状态 |
|------|---------|------|
| 多账号轮转 | `account-pool.ts` acquireHttp/acquireWs | ✅ 完整实现 |
| Session 有效性检测 | `auth.ts` checkStatus | ✅ 完整实现 |
| 30 天 TTL 管理 | `account-pool.ts` 健康检查 | ✅ 完整实现 |
| 错误码处理 | `account-pool.ts` handleError | ✅ 完整实现 |
| 僵尸 WS 锁清理 | `account-pool.ts` 健康检查 | ✅ 完整实现 |
| 并发安全 | `account-pool.ts` lockedByWs | ✅ 完整实现 |
| 批量配置加载 | `account-pool.ts` loadAccountConfigs | ✅ 完整实现 |

### 已知未覆盖功能

| 功能 | 缺失原因 | 影响 | 建议实现方式 |
|------|---------|------|------------|
| 动态添加/移除账号 | 号池初始化后固定 | 运维不便 | 添加 addAccount/removeAccount API |
| IP 代理轮换 | 未实现 | 高频请求可能被风控 | 每个账号绑定不同出口 IP |
| 账号质量评分 | 未实现 | 无法区分慢速/不稳定账号 | 添加响应时间、成功率等指标 |
| 自动注册新账号 | 未实现 | 人工补充账号 | 集成注册流程自动化 |
| 用量配额跟踪 | 未实现 | 可能超限 | 跟踪每个账号的 API 调用次数 |
| 浏览器指纹池 | 在 `browser-headers.ts` 中 | 只生成固定指纹 | 每个账号使用不同的 UA/IP/指纹组合 |

---

## 相关章节

- [Session 存储](01-session-storage.md) — Redis 数据结构
- [认证自动化](07-auth-automation.md) — 自动化的具体实现
- [浏览器头伪装](../07-proxy/05-oauth-automation.md) — 浏览器指纹生成