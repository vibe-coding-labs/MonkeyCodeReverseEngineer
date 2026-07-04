---
description: VM 生命周期分析 — 7 种状态、启动链、WS 双通道、代理层超时保护
protocol_version: based on chaitin/MonkeyCode + proxy/src/task-runner.ts + proxy/src/account-pool.ts
confidence: high
last_verified: 2026-06-28
---

# VM 生命周期（源码增强版）

## VM 状态机

```
                 POST /api/v1/users/hosts/vms
                      │
                   ┌──▼──┐
                   │pending│ ← Docker 正在拉镜像
                   └──┬──┘
                      │ 容器就绪
                   ┌──▼──┐
         ┌─────────│online│─────────┐
         │         └──┬──┘          │
         │            │              │
    ┌────▼───┐   ┌────▼───┐    ┌───▼────┐
    │hibernated│  │processing│  │ offline │
    │(15min空闲)│  │(任务执行) │  │(主动停止)│
    └────┬───┘   └─────────┘   └─────────┘
         │ 有 Control WS 连接就自动恢复
         └──────────→ online
```

### 状态说明

| 状态 | 触发条件 | 说明 |
|------|---------|------|
| `unknown` | 初始 | 刚创建，状态未知 |
| `pending` | POST VM | Docker 正在拉镜像、启动容器 |
| `online` | 容器就绪 | VM 正常运行，等待任务 |
| `processing` | 任务分配给 VM | Agent 正在执行任务 |
| `hibernated` | 15 分钟空闲 | 容器被休眠以节省资源 |
| `offline` | 主动停止/超时 | VM 已停止运行 |

## 代理层的任务超时保护

基于 `proxy/src/task-runner.ts` 的源码分析，代理层实现了双重超时保护：

```typescript
// proxy/src/task-runner.ts — 任务超时控制
const TASK_TIMEOUT_MS = parseInt(
  process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000",  // 默认 1 小时
  10
)

// 超时保护
setTimeout(() => {
  if (!resolved) {
    console.warn(`[TaskRunner] Task ${taskId} timed out after ${TASK_TIMEOUT_MS / 1000}s`)
    cleanup()
    resolve()  // 注意：超时后 resolve 而非 reject
  }
}, TASK_TIMEOUT_MS)
```

超时后行为：
- 调用 `cleanup()` 关闭 WebSocket
- 调用 `resolve()`（不 reject），确保调用方不会被挂起
- 已收集到的输出内容不会丢失

## 代理层的 WS 锁超时保护

```typescript
// proxy/src/account-pool.ts — WS 锁超时
const WS_LOCK_MAX_MS = parseInt(
  process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000", 10
) + 60_000  // 任务超时 + 1 分钟缓冲

// 健康检查中强制释放僵尸锁
if (entry.lockedByWs && entry.lockedAt &&
    Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
  console.warn(`[AccountPool] ${entry.email}: WS lock expired`)
  entry.lockedByWs = false  // 强制释放
  entry.lockedAt = null
}
```

## 启动链（含代理层细节）

代理层创建任务时构造的请求体决定了 VM 的初始参数：

```
Step 1: 代理 POST /api/v1/users/tasks
    ├── 构造 body → task-runner.ts:55-78
    │   ├── content: prompt
    │   ├── host_id: "public_host" (默认)
    │   ├── image_id: (必需，从环境变量或 OAuth 发现)
    │   ├── model_id: model.id (UUID)
    │   ├── cli_name: "codex" | "claude" | "opencode"
    │   ├── resource: { core:1, memory:1GB, life:3600s }
    │   ├── system_prompt: (可选)
    │   └── repo: { repo_url, branch, ... } (可选)
    │
Step 2: 后端验证 → 重写资源参数
    ├── resource.core → "2" (固定)
    ├── resource.memory → 8GB (固定)
    └── resource.life → 3600s (实际使用)
    │
Step 3: 后端 POST → TaskFlow → Host Agent → docker run
Step 4: 容器启动
    ├── NPM 包安装 (@ai-sdk/*)
    ├── LLM 环境变量注入
    ├── MCP 服务启动 (127.0.0.1:65510)
    └── Agent 等待 user-input
```

## 代理层的 image_id 发现流程

```typescript
// proxy/src/admin-login.ts
export async function discoverImageId(sessionCookie: string): Promise<{
  imageId: string
  imageName: string
} | null> {
  const resp = await fetch(
    `${MONKEYCODE_BASE_URL}/api/v1/users/tasks?page=1&size=5`,
    { headers: mkHeaders({
      Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}`,
    })}
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
  return null  // 当前用户没有任何任务记录
}
```

**设计意图：** 新用户第一次使用时没有已有任务，此时无法自动发现 image_id，必须手动提供。

## 任务创建的完整错误处理

```typescript
// proxy/src/task-runner.ts — 创建任务
async createTask(model, prompt, options): Promise<string> {
  // 1. 前置条件检查
  if (!imageId) {
    throw new Error("MONKEYCODE_IMAGE_ID is required.")
  }

  // 2. HTTP 请求
  const response = await fetch(url, {
    method: "POST", headers: mkHeaders(headers), body: JSON.stringify(body),
  })

  // 3. HTTP 状态码错误
  if (!response.ok) {
    throw new Error(`Failed to create task (${response.status}): ${respText}`)
  }

  // 4. 业务错误（HTTP 200 + code != 0）
  const result = await response.json()
  if (result.code && result.code !== 0) {
    throw new Error(`Failed to create task (code ${result.code}): ${result.message}`)
  }

  return data.id || data.task_id
}
```

## WebSocket 双通道设计

| 通道 | 端点 | 消息格式 | 用途 |
|------|------|---------|------|
| **Task Stream** | `.../tasks/stream?id=X&mode=new\|attach` | ACP 事件（JSON） | Agent 输出流、用户输入 |
| **Task Control** | `.../tasks/control?id=X` | call/call-response（RPC） | 管理操作、文件操作、模型切换 |

## 超时时间一览

| 超时 | 默认值 | 最大 | 触发动作 | 源码位置 |
|------|--------|------|---------|---------|
| `resource.life` | 3600s (1h) | 10800s (3h) | VM 到期销毁 | `task.go` |
| `vm_idle.sleep_seconds` | 900s (15min) | 配置 | VM 空闲 → hibernated | `team_policy.go` |
| `vm_idle.recycle_seconds` | 259200s (3天) | 配置 | hibernated → 删除 | `team_policy.go` |
| **代理任务超时** | 3600000ms (1h) | 环境变量配置 | WS cleanup + resolve | `task-runner.ts:16` |
| **代理 WS 锁超时** | task_timeout + 1min | — | 强制释放锁 | `account-pool.ts:23` |
| **代理 WS 连接超时** | 30000ms (30s) | — | resolve 防挂起 | `conversation-manager.ts:202` |

## 数据流：Agent 输出 → 用户（含代理层处理）

```
VM 内 Coding Agent
    │ Agent 输出文本
    ▼
ACP 事件 → TaskLive WS → TaskFlow
    ▼
MonkeyCode 后端 → Task Stream WS
    │ {"type":"task-running","kind":"acp_event",
    │  "data":"{\"type\":\"agent_message_chunk\",\"text\":\"...\"}"}
    ▼
代理 task-runner.ts → handleStreamMessage()
    │ ├── agent_message_chunk → SSE delta.content
    │ ├── agent_thought_chunk → SSE [Thinking] prefix
    │ ├── tool_call → SSE tool_calls / function_call
    │ ├── usage_update → 累积 usage 计数器
    │ ├── task-ended → SSE finish_reason:stop + usage
    │ └── task-error → SSE [Error] prefix
    ▼
OpenAI SDK / 用户
```

## 销毁途径

```
途径 1: 正常结束
    Task 完成 → Agent 输出 task-ended → VM → offline
    VM 可能被复用（默认不立即删除）

途径 2: 用户主动停止（代理实现）
    代理 task-runner: stopTask()
    → PUT /api/v1/users/tasks/stop {"id": "task-uuid"}

途径 3: 超时回收（自动）
    Resource life 到期（默认 1h，最大 3h）
    → TaskFlow 自动销毁容器
    代理侧超时 1h 保护: resolve + 返回已收集内容

途径 4: 用户主动删除
    DELETE /api/v1/users/hosts/vms/{id}
    → 直接删除 VM（有 task 在运行时不允许）
```

---

## 相关章节

- [TaskFlow 架构定位](01-architecture.md) — TaskFlow 在整体架构中的位置
- [核心数据流](../01-architecture/02-data-flow.md) — 完整数据流链
- [资源管理](05-resource-management.md) — 代理层的资源超时控制
- [代理错误处理](../01-architecture/04-error-handling-patterns.md) — 代理层的错误恢复策略