---
description: VM 资源管理与配额 — 基于 task-runner.ts、account-pool.ts 和 Go 源码的双层详解
protocol_version: based on chaitin/MonkeyCode + proxy/src/task-runner.ts + proxy/src/account-pool.ts
confidence: high
last_verified: 2026-06-28
---

# 资源管理与配额（源码增强版）

## 1. 两层资源分配模型

MonkeyCode 的 VM 资源有两层含义，通过源码可以完整还原：

```
代理层 (TypeScript)              后端层 (Go)                     TaskFlow (Go 闭源)
────────────────               ──────────                     ────────────────
task-runner.ts                  task.go 解析请求                docker run
├─ resource.core: 1             ├─ Cores: "2" (固定)            ├─ --cpus=2
├─ resource.memory: 1GB         ├─ Memory: 8GB (固定)           ├─ --memory=8g
├─ resource.life: 3600s         ├─ Life: 3600s (实际使用)       └─ --stop-timeout=3600
└─ 请求中携带                   └─ 有并发限制

account-pool.ts                 domain/team_policy.go
├─ 多账号并发                   ├─ defaultTaskConcurrencyLimit=3
├─ SESSION_MAX_AGE_MS: 29天     └─ 每团队并发任务上限
└─ WS_LOCK_MAX_MS: 任务+1min
```

### 代理层默认值

```typescript
// proxy/src/task-runner.ts — 任务创建时的资源参数
const body: Record<string, unknown> = {
  // ...
  resource: {
    core: 1,                     // CPU 核心数（请求值，被后端忽略）
    memory: 1073741824,          // 1 GB（请求值，被后端忽略）
    life: 3600,                  // 1 hour（实际使用）
  },
  // ...
}
```

### Go 后端实际分配

```go
// backend/biz/task/usecase/task.go — 创建 VM 时的实际参数
Cores:    "2",          // 2 核 CPU（字符串格式）
Memory:   8 << 30,      // 8 GB
```

**核心差异：** 后端忽略前端传的 `resource.core` 和 `resource.memory`，始终固定分配 2 核 8GB。只有 `resource.life` 被实际使用。

## 2. 代理层的任务超时控制

```typescript
// proxy/src/task-runner.ts — 任务超时（可配置）
const TASK_TIMEOUT_MS = parseInt(
  process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000",  // 默认 1h
  10
)
```

任务超时机制：
- 代理侧超时默认 1 小时，匹配 `resource.life`
- 超过超时自动 `cleanup()` 并 `resolve()`（不 reject）
- 超时可通 `MONKEYCODE_TASK_TIMEOUT_MS` 环境变量配置

```typescript
// 超时保护 — 代理侧
setTimeout(() => {
  if (!resolved) {
    console.warn(`[TaskRunner] Task ${taskId} timed out after ${TASK_TIMEOUT_MS / 1000}s`)
    cleanup()
    resolve()  // 不 reject，确保调用方不被挂起
  }
}, TASK_TIMEOUT_MS)
```

## 3. 号池模式的 WS 锁超时

```typescript
// proxy/src/account-pool.ts — WS 锁超时
const WS_LOCK_MAX_MS = parseInt(
  process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000", 10
) + 60_000  // 任务超时 + 1 分钟缓冲
```

健康检查中会强制释放超时的 WS 锁：

```typescript
// 健康检查 — 清理僵尸 WS 锁
if (entry.lockedByWs && entry.lockedAt &&
    Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
  console.warn(`[AccountPool] ${entry.email}: WS lock expired`)
  entry.lockedByWs = false  // 强制释放
  entry.lockedAt = null
}
```

## 4. 并发限制

### 4.1 团队策略默认值

```go
// backend/domain/team_policy.go
const defaultTaskConcurrencyLimit = 3
```

| 限制项 | 默认值 | 说明 |
|--------|--------|------|
| 并发任务数 | **3** | 每团队同时最多 3 个运行中任务 |
| VM 空闲休眠 | **900s (15min)** | 无操作后进入 hibernated 状态 |
| VM 回收 | **259200s (3天)** | 休眠后彻底删除 |

### 4.2 代理层的并发处理

代理层不限制并发——因为它使用号池模式，多账号可以同时发起任务：

```typescript
// 代理不限制并发
// 每个账号可以有独立的 WS 连接和 HTTP 请求
// 但后端 TeamPolicy 会限制最多 3 个并发任务

// 号池中的账号分配
// - HTTP 共享模式：多个请求可以同时使用不同账号
// - WebSocket 独占模式：一个账号同一时间只能有一个 WS 连接
```

## 5. 代理层的资源管理实践

### 5.1 Host ID 配置

```typescript
// proxy/src/task-runner.ts
const DEFAULT_HOST_ID = process.env.MONKEYCODE_HOST_ID || "public_host"
```

所有任务使用 `public_host`（MonkeyCode 官方公共资源池）。私有部署时可配置私有的 host_id。

### 5.2 Image ID 的必要性

```typescript
// 创建任务时必须提供 Image ID
if (!imageId) {
  throw new Error(
    "MONKEYCODE_IMAGE_ID is required. Set it in .env or pass imageId option."
  )
}
```

Image ID 可以从已有任务中发现：

```typescript
// proxy/src/admin-login.ts — 从已有任务中发现 image_id
export async function discoverImageId(sessionCookie: string): Promise<{
  imageId: string
  imageName: string
} | null> {
  const resp = await fetch(
    `${MONKEYCODE_BASE_URL}/api/v1/users/tasks?page=1&size=5`,
    { headers: mkHeaders({ Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}` }) }
  )

  if (!resp.ok) return null

  const data = await resp.json()
  const tasks = data.data?.tasks || []
  for (const task of tasks) {
    if (task.image?.id) {
      return {
        imageId: task.image.id,
        imageName: task.image.name || "unknown",
      }
    }
  }
  return null
}
```

### 5.3 Agent NPM 包版本管理

@ai-sdk 包版本不是硬编码的——通过数据库的 `agentskillversion` 表管理：

```go
// 数据库 schema: agentskillversion 表中有 npm_version_spec 字段
// 版本在部署时通过数据库种子数据/管理后台设置，不是代码中硬编码
```

代理端根据接口类型选择包，版本由后端控制：

```go
// pkg/taskflow/vm.go
func getNpmPackage(interfaceType InterfaceType) string {
    switch interfaceType {
    case InterfaceOpenAIChat:
        return "@ai-sdk/openai-compatible"
    case InterfaceOpenAIResponses:
        return "@ai-sdk/openai"
    case InterfaceAnthropic:
        return "@ai-sdk/anthropic"
    }
}
```

## 6. 资源对比速查表

### 6.1 请求 vs 实际

| 场景 | 请求 Core | 实际 Core | 请求 Memory | 实际 Memory | Life |
|------|----------|----------|------------|------------|------|
| 默认（不传 resource） | 1 | 2 | 1GB | 8GB | 1h |
| 传 Core=2/Memory=4GB | 2 | 2 | 4GB | 8GB | 1h |
| 最大 | — | 2 | — | 8GB | 3h |

> **注意:** 后端固定用 `Cores="2"` 和 `Memory=8GB`，前端传的 resource.core 和 resource.memory 被**忽略**。只有 `life` 字段被实际使用。

### 6.2 号池场景的资源影响

| 因素 | 影响 |
|------|------|
| VM 创建耗时 | ~几秒到十几秒（拉镜像） |
| 账号与 VM 绑定 | VM 属于创建它的用户，切换账号需新 VM |
| 优化方向 | 每个账号预创建 1-2 个 VM 并保持在线 |

---

## 相关章节

- [VM 生命周期](02-vm-lifecycle.md) — VM 状态和超时细节
- [第七章：代理实现](../07-proxy/02-account-pool.md) — 代理中的号池实现
- [代理架构](../07-proxy/01-architecture.md) — 代理层的完整代码结构