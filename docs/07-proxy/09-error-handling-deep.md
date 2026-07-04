---
description: 代理层错误处理与重试策略深度分析 — 错误码分类、隔离体系、超时保护、告警机制
protocol_version: based on proxy/src/account-pool.ts + auth.ts + task-runner.ts + server.ts
confidence: high
last_verified: 2026-06-28
---

# 代理层错误处理与重试策略深度分析

> **核心源码:** `proxy/src/account-pool.ts` (298L), `auth.ts` (237L), `task-runner.ts` (463L), `server.ts` (331L)
> **覆盖:** 5 种错误码处理分支、4 级错误隔离、3 阶重试策略、4 层超时保护、P0/P1/P2 告警

---

## 1. 错误码分类体系

### 完整错误码映射表

```typescript
// 摘自 proxy/src/account-pool.ts:214-242 — 错误码分发逻辑
handleError(auth: AuthManager, errorCode: number): boolean {
  const entry = this.findByAuth(auth)
  if (!entry) return false

  switch (errorCode) {
    case 40100: // 会话无效 → 进入过期状态并重登录
      entry.status = "EXPIRED"
      this.loginAccount(entry).catch(() => {})
      return true   // 调用方可切换账号重试

    case 40300: // 权限不足 → 降级处理
      console.warn(`[AccountPool] ${entry.email}: permission denied, degrading`)
      return false  // 不可重试

    case 40002: // 密码错误
    case 40003: // 账号被封
    case 40004: // 账号未激活
      entry.status = "INVALID"
      console.error(`[AccountPool] ${entry.email}: marked INVALID (code ${errorCode})`)
      return false

    case 50000: // 服务端错误 → 可重试
      return true

    default:
      return false
  }
}
```

### 业务错误码 (code 非零但 HTTP 200)

```typescript
// 摘自 proxy/src/task-runner.ts:93-97 — 业务错误码处理
// 后端在任务创建时可能返回业务错误（HTTP 200 + code ≠ 0）
const result = await response.json()
if (result.code && result.code !== 0) {
  // 已知业务错误码: 10811 = 已有运行任务
  throw new Error(
    `Failed to create task (code ${result.code}): ${result.message || JSON.stringify(result)}`
  )
}
```

### HTTP 层错误处理

```typescript
// 摘自 proxy/src/task-runner.ts:86-88 — HTTP 错误
if (!response.ok) {
  const respText = await response.text()
  throw new Error(`Failed to create task (${response.status}): ${respText}`)
}

// 摘自 proxy/src/auth.ts:114-115 — 登录 HTTP 错误
if (!response.ok && response.status !== 302) {
  const respBody = await response.text()
  throw new Error(`User login failed (${response.status}): ${respBody}`)
}
```

---

## 2. 错误隔离策略

### 4 级账号状态机

```typescript
// 摘自 proxy/src/account-pool.ts — 账号状态定义
export type AccountStatus = "CREATED" | "ACTIVE" | "EXPIRED" | "INVALID"

// 状态转换图:
//
// ┌──────────┐    登录成功    ┌──────────┐
// │  CREATED │──────────────▶│  ACTIVE  │
// │  (创建)  │               │  (活跃)  │
// └──────────┘               └────┬─────┘
//                                 │
//                     ┌───────────┴───────────┐
//                     │                       │
//              会话过期/40100           3次失败/40002/
//                     │                40003/40004
//                     ▼                       ▼
//               ┌──────────┐           ┌──────────┐
//               │  EXPIRED │           │  INVALID │
//               │  (过期)  │           │  (无效)  │
//               └────┬─────┘           └──────────┘
//                    │
//              自动重登录
//                    ▼
//               ┌──────────┐
//               │  ACTIVE  │
//               └──────────┘
```

### 双模式获取隔离

```typescript
// 摘自 proxy/src/account-pool.ts — HTTP 共享模式
// 多个 HTTP 请求共享账号池，Round-Robin 分散负载
acquireHttp(): AuthManager | null {
  const candidates = this.accounts
    .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)  // 过滤掉 WS 锁定的
    .sort((a, b) => a.lastUsedAt - b.lastUsedAt)             // 最久未用优先

  const idx = this.roundRobinIndex % candidates.length
  this.roundRobinIndex++
  return candidates[idx]?.auth || null
}

// ——————————————————————————————————

// WebSocket 独占模式：锁住一个账号直到流结束
acquireWs(): AuthManager | null {
  const candidates = this.accounts
    .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)   // 未被锁定的
    .sort((a, b) => a.lastUsedAt - b.lastUsedAt)

  const chosen = candidates[0]
  if (chosen) {
    chosen.lockedByWs = true
    chosen.lockedAt = Date.now()
    chosen.lastUsedAt = Date.now()
  }
  return chosen?.auth || null
}

// 释放 WS 锁
releaseWs(auth: AuthManager): void {
  const entry = this.findByAuth(auth)
  if (entry) {
    entry.lockedByWs = false
    entry.lockedAt = null
  }
}
```

### 错误计数隔离

```typescript
// 摘自 proxy/src/account-pool.ts — 3 次失败锁定
interface AccountEntry {
  // ...
  errorCount: number     // 连续失败计数
  // ...
}

private async loginAccount(entry: AccountEntry): Promise<void> {
  try {
    await entry.auth.login()
    entry.status = "ACTIVE"
    entry.cookieSetAt = Date.now()
    entry.cookieTTLReached = false
    entry.errorCount = 0  // 成功重置计数
  } catch (err: any) {
    entry.errorCount++
    if (entry.errorCount >= 3) {
      entry.status = "INVALID"  // 3 次失败永久锁定
    }
  }
}
```

---

## 3. 重试策略

### HTTP 重试

```typescript
// 摘自 proxy/src/account-pool.ts — HTTP 重试常量
const HTTP_RETRY_MAX = 3  // 最多重试 3 次
```

### 号池切换重试

```typescript
// handleError 返回 true → 调用方切换账号重试
// 流程:
// 1. 请求使用 AuthA → 收到 40100
// 2. AuthA 标记 EXPIRED → 触发自动重登录
// 3. 调用方获取下一个 ACTIVE 账号 AuthB
// 4. 用 AuthB 重发请求
```

### 启动时错误容忍

```typescript
// 摘自 proxy/src/server.ts:73-83 — 启动错误容忍
// 非号池模式：登录失败不阻止代理启动
if (!accountPool && singleAuth) {
  try {
    await singleAuth.getSessionCookie()
    console.log("[Init] Authentication successful")
  } catch (err: any) {
    // 登录失败也继续启动，后续请求会失败
    console.warn(`[Init] Authentication failed: ${err.message}`)
  }
}

// 号池模式：部分账号失败也不阻塞
const results = await Promise.allSettled(created.map((a) => this.loginAccount(a)))
const ok = results.filter((r) => r.status === "fulfilled").length
console.log(`[AccountPool] Init complete: ${ok}/${created.length} succeeded`)
```

### WebSocket 错误处理

```typescript
// 摘自 proxy/src/task-runner.ts:172-177 — WS 错误
ws.on("close", () => {
  if (!resolved) {
    resolved = true
    resolve()  // 连接关闭视为正常结束
  }
})

ws.on("error", (err) => {
  if (!resolved) {
    resolved = true
    reject(err)  // 连接错误才拒绝
  }
})

// task-error 事件：发送错误内容到流
case "task-error":
  onChunk({
    id: chatId, object: "chat.completion.chunk",
    created: now, model: "monkeycode",
    choices: [{ index: 0, delta: { content: `[Error] ${msg.data}` }, finish_reason: null }],
  })
  break
```

---

## 4. 超时保护体系

### 4 层超时保护

```typescript
// 摘自各文件 — 超时常量定义
// 第 1 层: 任务执行超时 (TaskRunner)
const TASK_TIMEOUT_MS = 3600000  // 1 小时，匹配 resource.life

// 第 2 层: WS 锁超时 (AccountPool)
const WS_LOCK_MAX_MS = TASK_TIMEOUT_MS + 60000  // 1h + 1min buffer

// 第 3 层: Conversation 连接超时 (ConversationManager)
const CONVERSATION_TIMEOUT_MS = 30 * 60 * 1000     // 30 分钟
const CONVERSATION_CONNECT_TIMEOUT_MS = 30000       // 30 秒 WS 连接超时

// 第 4 层: Session TTL (AuthManager + AccountPool)
const SESSION_TTL_MS = 24 * 60 * 60 * 1000          // 24h (AuthManager)
const SESSION_MAX_AGE_MS = 29 * 24 * 60 * 60 * 1000 // 29 天提前重登录 (AccountPool)
```

### 超时触发源码

```typescript
// 摘自 proxy/src/task-runner.ts:180-186 — 任务超时保护
setTimeout(() => {
  if (!resolved) {
    console.warn(`[TaskRunner] Task ${taskId} timed out after ${TASK_TIMEOUT_MS / 1000}s`)
    cleanup()  // 关闭 WS 连接
    resolve()  // 正常结束（不是 reject）
  }
}, TASK_TIMEOUT_MS)

// 摘自 proxy/src/account-pool.ts:162-166 — 僵尸 WS 锁清理
if (entry.lockedByWs && entry.lockedAt &&
    Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
  console.warn(`[AccountPool] ${entry.email}: WS lock expired, force releasing`)
  entry.lockedByWs = false
  entry.lockedAt = null
}
```

### 健康检查体系

```typescript
// 摘自 proxy/src/account-pool.ts — 定时健康检查
const HEALTH_CHECK_INTERVAL_MS = 60 * 60 * 1000  // 1 小时

startHealthCheck(): void {
  this.healthTimer = setInterval(() => this.healthCheck(), HEALTH_CHECK_INTERVAL_MS)
}

private async healthCheck(): Promise<void> {
  for (const entry of this.accounts) {
    if (entry.status !== "ACTIVE") continue

    // 3 项健康检查:
    // 1. WS 锁超时清理
    // 2. Cookie 年龄（30 天硬限制）
    if (entry.cookieSetAt && Date.now() - entry.cookieSetAt > SESSION_MAX_AGE_MS) {
      entry.cookieTTLReached = true
      await this.loginAccount(entry)
      continue
    }
    // 3. /users/status API 检查
    try {
      const ok = await entry.auth.checkStatus()
      if (!ok) await this.loginAccount(entry)
    } catch {
      entry.status = "EXPIRED"
    }
  }
}
```

---

## 5. 告警与监控

### 告警阈值

```typescript
// 摘自 proxy/src/account-pool.ts — 告警检查
private checkAlerts(): void {
  const { total, active } = this.getStats()
  const activeRatio = total > 0 ? active / total : 0

  // P0: 可用账号 < 50%
  if (activeRatio < 0.5) {
    console.error(`[AccountPool] P0 ALERT: available accounts < 50% (${active}/${total})`)
  }
  // P1: 可用账号 < 70%
  else if (activeRatio < 0.7) {
    console.warn(`[AccountPool] P1 WARN: available accounts < 70% (${active}/${total})`)
  }
}
```

### 告警分级

| 级别 | 触发条件 | 日志级别 | 处理动作 |
|------|---------|---------|---------|
| **P0** | 可用账号 < 50% | `console.error` | 紧急告警，需要人工介入 |
| **P1** | 可用账号 < 70% | `console.warn` | 预警，监控趋势 |
| **P1** | 过期率 > 5/h | — | 频繁过期说明 Cookie 策略有问题 |
| **P1** | 账号异常 > 0 | — | INVALID 账号需要移除或更换凭据 |
| **P2** | 错误率 > 20% | — | 整体健康度下降 |

### 统计监控

```typescript
// 摘自 proxy/src/account-pool.ts — 账号统计
getStats(): { total: number; active: number; expired: number; invalid: number; locked: number } {
  return {
    total: this.accounts.length,
    active: this.accounts.filter((a) => a.status === "ACTIVE").length,
    expired: this.accounts.filter((a) => a.status === "EXPIRED").length,
    invalid: this.accounts.filter((a) => a.status === "INVALID").length,
    locked: this.accounts.filter((a) => a.lockedByWs).length,
  }
}

// 状态日志
logStatus(): void {
  const stats = this.getStats()
  console.log(`[AccountPool] Status: ${stats.active}/${stats.total} active, ` +
    `${stats.expired} expired, ${stats.invalid} invalid, ${stats.locked} ws-locked`)
}
```

---

## 6. 错误处理模式总结

### 5 种错误处理模式

| 模式 | 描述 | 源码位置 | 示例 |
|------|------|---------|------|
| **切换重试** | 错误码返回 true，调用方切换资源 | account-pool.ts:handleError + acquireHttp | 40100 切换账号 |
| **状态锁定** | 错误后将资源标记 INVALID，不再使用 | account-pool.ts:loginAccount | 3 次登录失败锁定 |
| **超时兜底** | 超过时限后自动清理资源 | task-runner.ts:180 行 setTimeout | 1h 任务超时 |
| **错误容忍** | 非致命错误不阻塞启动流程 | server.ts:73-83 | 登录失败继续启动 |
| **自动恢复** | EXPIRED 状态 + 后台重登录 | account-pool.ts:healthCheck | Session 过期自动恢复 |

### 错误处理架构图

```
请求进入
  │
  ▼
┌─────────────────────────────────────────────────────┐
│ API 路由层 (api-routes.ts)                           │
│ 全局 try-catch → 500 JSON 错误响应                   │
│ 流式错误 → error SSE event                           │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 任务执行层 (task-runner.ts)                          │
│ HTTP 错误 → throw Error                             │
│ 业务错误码 → throw Error (code=10811 等)            │
│ WS 错误 → reject Promise                            │
│ WS 关闭 → resolve Promise (正常结束)                 │
│ task-error 事件 → 流式发送 [Error] 内容              │
│ 1h 超时 → resolve Promise (超时不报错)               │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 号池管理 (account-pool.ts)                           │
│ 40100 → EXPIRED + 后台重登录 + true (可重试)         │
│ 40002/3/4 → INVALID (不可重试)                      │
│ 40300 → 降级处理 (不可重试)                          │
│ 50000 → true (可重试)                               │
│ 3 次登录失败 → INVALID                              │
│ 健康检查 1h × 3 维度                                │
└─────────────────────────────────────────────────────┘
```

---

## 相关章节

- [号池管理](../07-proxy/02-account-pool.md) — 号池状态机和双模式获取
- [代理架构](../07-proxy/01-architecture.md) — 10 模块依赖关系
- [附录: 错误码全集](../../10-appendices/02-error-codes.md) — 错误码详细参考
- [部署与中间件](../07-proxy/07-deployment-infrastructure.md) — Express 错误中间件