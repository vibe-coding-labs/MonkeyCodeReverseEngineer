---
description: 第 7-12 轮逆向分析过程记录 — ACP 事件到号池管理
protocol_version: based on chaitin/MonkeyCode 开源后端源码 + 代理 TS 源码
confidence: high
last_verified: 2026-06-28
---

# 分析轮次 7-12 合并 — 扩增版

> **分析周期:** 2026-05-16 — 2026-05-24
> **覆盖:** ACP 事件全表 → 授权矩阵 → 百智云 OAuth → 多轮对话 → 订阅计费 → 号池管理
> **代理源码:** `proxy/src/account-pool.ts` (298L), `admin-login.ts` (416L), `conversation-manager.ts` (368L)

---

## 轮次 7: ACP 事件全表确认

**目标**: 确认 ACP 事件的完整类型和字段结构

### ACP 事件类型全表

```json
{
  "agent_message_chunk": {
    "type": "agent_message_chunk",
    "text": "Agent 输出的文本内容",
    "content": "与 text 相同或补充字段",
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "agent_thought_chunk": {
    "type": "agent_thought_chunk",
    "text": "Agent 的推理过程文本",
    "content": "推理补充内容"
  },
  "tool_call": {
    "type": "tool_call",
    "tool_name": "工具名称",
    "tool_input": "工具输入参数"
  },
  "tool_call_update": {
    "type": "tool_call_update",
    "tool_name": "工具名称",
    "tool_input": "增量参数",
    "delta": "增量更新数据",
    "status": "running / completed / done"
  },
  "usage_update": {
    "type": "usage_update",
    "input_tokens": 150,
    "output_tokens": 200,
    "total_tokens": 350
  },
  "plan": {
    "type": "plan",
    "steps": ["步骤1", "步骤2", "..."]
  },
  "available_commands_update": {
    "type": "available_commands_update",
    "commands": ["命令1", "命令2"]
  }
}
```

### 代理层 ACP 事件处理源码

```typescript
// 摘自 proxy/src/task-runner.ts — ACP 事件处理
private handleACPEvent(
  acp: ACPSessionUpdate,
  chatId: string,
  now: number,
  onChunk: (chunk: OpenAIChatCompletionChunk) => void,
  usage: { input_tokens: number; output_tokens: number; total_tokens: number }
): void {
  switch (acp.type) {
    case "agent_message_chunk": {
      const text = acp.text || acp.content || ""
      if (text) {
        onChunk({
          id: chatId,
          object: "chat.completion.chunk",
          created: now,
          model: "monkeycode",
          choices: [{ index: 0, delta: { content: text }, finish_reason: null }],
        })
      }
      break
    }

    case "agent_thought_chunk": {
      const text = acp.text || acp.content || ""
      if (text) {
        // Agent 推理内容添加 [Thinking] 前缀
        onChunk({
          id: chatId, object: "chat.completion.chunk",
          created: now, model: "monkeycode",
          choices: [{ index: 0, delta: { content: `[Thinking] ${text}` }, finish_reason: null }],
        })
      }
      break
    }

    case "usage_update":
      // 累积 token 用量
      if (acp.input_tokens) usage.input_tokens = acp.input_tokens
      if (acp.output_tokens) usage.output_tokens = acp.output_tokens
      if (acp.total_tokens) usage.total_tokens = acp.total_tokens
      break

    case "tool_call": {
      const toolName = acp.tool_name || "unknown"
      const toolInput = acp.tool_input || ""
      onChunk({
        id: chatId, object: "chat.completion.chunk",
        created: now, model: "monkeycode",
        choices: [{ index: 0, delta: { content: `[Tool: ${toolName}] ${toolInput}` }, finish_reason: null }],
      })
      break
    }

    case "tool_call_update": {
      // 记录工具调用更新（调试用）
      const updateArgs = String(acp.tool_input || acp.delta || "")
      const status = String(acp.status || "")
      console.log(`[TaskRunner] tool_call_update: status=${status}, args=${updateArgs.slice(0, 100)}`)
      break
    }

    case "plan": {
      const planData = acp.steps || acp
      console.log(`[TaskRunner] plan:`, JSON.stringify(planData).slice(0, 200))
      break
    }

    case "available_commands_update": {
      const commandsData = acp.commands || acp
      console.log(`[TaskRunner] available_commands:`, JSON.stringify(commandsData).slice(0, 200))
      break
    }
  }
}
```

---

## 轮次 8: 授权矩阵 4 级确认

**目标**: 确认 MonkeyCode 的四级权限体系

### 授权层级

| 层级 | 访问范围 | Cookie | API 前缀 |
|------|---------|--------|---------|
| public | 公开端点 | 无需 Cookie | `/api/v1/public/` |
| user | 用户级别 | `monkeycode_ai_session` | `/api/v1/users/` |
| team | 团队级别 | `monkeycode_ai_team_session` | `/api/v1/teams/` |
| admin | 管理员 | 需要 is_admin=true | `/api/v1/admin/` |

### 代理层权限检查

```typescript
// 摘自 proxy/src/auth.ts — 登录模式切换
export type LoginMode = "user" | "team"

// 根据模式选择不同的 Cookie 名和端点
async login(): Promise<void> {
  if (this.loginMode === "team") {
    await this.loginTeam()  // 团队登录
  } else {
    await this.loginUser()  // 用户登录
  }
}

// 用户状态检查
async checkStatus(): Promise<boolean> {
  const url = this.loginMode === "team"
    ? `${MONKEYCODE_BASE_URL}/api/v1/teams/users/status`
    : `${MONKEYCODE_BASE_URL}/api/v1/users/status`

  const response = await fetch(url, {
    headers: mkHeaders({
      Cookie: `${this.getSessionCookieName()}=${this.getSessionCookieSync()}`,
    }),
  })
  return response.ok
}
```

---

## 轮次 9: 百智云 OAuth 流程逆向

**目标**: 理解百智云 OAuth 的完整 6 步流程

### OAuth 6 步流程

```
Step 1: GET /api/v1/users/login → 302 Redirect to baizhi.cloud OAuth
        获取 state, client_id, redirect_uri, scope

Step 2: POST SCaptcha → 获取验证码 token
        (欠费状态 token 仍可获取，challenge 为空)

Step 3: POST baizhi.cloud/api/v1/user/phone_code → 发送短信验证码
        需要: phone + captcha_token

Step 4: POST baizhi.cloud/api/v1/user/login/phone → 手机号登录
        需要: phone + sms_code
        返回: baizhi.cloud session cookies

Step 5: GET baizhi.cloud/api/v1/oauth/authorize? → 获取 OAuth code
        需要: client_id + redirect_uri + scope + state + baizhi cookies
        返回: callback URL with code

Step 6: 访问 callback URL → 获取 monkeycode_ai_session Cookie
        OAuth code 交换 → monkeycode Session Cookie
```

### 代理层 OAuth 实现

```typescript
// 摘自 proxy/src/admin-login.ts — Step 1: 获取 OAuth 参数
export async function startOAuthLogin(): Promise<{
  oauthUrl: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
}> {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/login`, {
    headers: mkHeaders(),
    redirect: "manual",
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

### SCaptcha Token 获取

```typescript
// 摘自 proxy/src/admin-login.ts — Step 2: SCaptcha 绕过
export async function getSCaptchaToken(): Promise<string> {
  // SCaptcha 服务 TLS 证书过期，需绕过证书验证
  const originalTlsSetting = process.env.NODE_TLS_REJECT_UNAUTHORIZED
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0"

  try {
    const resp = await fetch(`${SCAPTCHA_API}/v1/api/challenge`, {
      method: "POST",
      headers: scHeaders(),
      body: JSON.stringify({ business_id: SCAPTCHA_BUSINESS_ID }),
    })

    const data = await resp.json() as any
    return data.data?.token || ""
  } finally {
    // 恢复 TLS 设置
    if (originalTlsSetting === undefined) {
      delete process.env.NODE_TLS_REJECT_UNAUTHORIZED
    } else {
      process.env.NODE_TLS_REJECT_UNAUTHORIZED = originalTlsSetting
    }
  }
}
```

---

## 轮次 10: 多轮对话设计（mode=attach）

**目标**: 设计基于 mode=attach 的多轮对话复用机制

### Conversation 数据结构

```typescript
// 摘自 proxy/src/conversation-manager.ts — Conversation 接口
export interface Conversation {
  id: string           // 格式: conv-{timestamp}-{random}
  taskId: string       // 关联的任务 ID
  model: MonkeyCodeModel  // 模型
  auth: AuthManager    // 认证
  ws: WebSocket | null // 复用的 WS 连接
  messages: OpenAIMessage[]  // 历史消息
  lastUsedAt: number   // 最后使用时间
  createdAt: number    // 创建时间
  onChunk: ((chunk: OpenAIChatCompletionChunk) => void) | null  // 回调
  resolvePromise: (() => void) | null  // Promise 解析
  rejectPromise: ((err: Error) => void) | null  // Promise 拒绝
}
```

### mode=attach 连接复用

```typescript
// 摘自 proxy/src/conversation-manager.ts — connectToTask 方法
async connectToTask(
  conversation: Conversation,
  onChunk: (chunk: OpenAIChatCompletionChunk) => void
): Promise<void> {
  // mode=attach 复用已有任务的 WebSocket
  const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${conversation.taskId}&mode=attach`

  const ws = new WebSocket(wsUrl, {
    headers: wsHeaders("monkeycode-ai.com",
      `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`),
  })

  // 与 mode=new 完全相同的 auto-approve + 心跳逻辑
  ws.on("open", () => {
    ws.send(JSON.stringify({ type: "auto-approve" }))
  })
}
```

### mode=new vs mode=attach 对比

| 特性 | mode=new | mode=attach |
|------|---------|------------|
| URL 参数 | `mode=new` | `mode=attach` |
| 创建新 VM | ✅ 是 | ❌ 复用 |
| 适用 SDK | OpenAI Chat/Responses | Conversations API |
| 代理类 | TaskRunner | ConversationManager |
| 超时 | 1h (TASK_TIMEOUT_MS) | 30min (conversationTimeoutMs) |
| 清理 | 任务结束自动销毁 | 超时自动清理 |

---

## 轮次 11: 订阅计费分析

**目标**: 理解 MonkeyCode 的订阅和计费系统

### 订阅响应结构体

```typescript
// SubscriptionResp 响应格式
interface SubscriptionResp {
  plan: string          // "basic" | "pro" | "ultra"
  source: string        // "stripe" | "open_source"
  expires_at: string    // 过期时间 ISO 格式
  auto_renew: boolean   // 是否自动续费
  is_free: boolean      // 是否免费
}

// 订阅级别对应的并发限制
const SUBSCRIPTION_LIMITS = {
  basic: { maxConcurrency: 1, maxModelsPerType: 3 },
  pro:   { maxConcurrency: 3, maxModelsPerType: 10 },
  ultra: { maxConcurrency: 10, maxModelsPerType: 50 },
}

// 开源版固定为 pro（可绕过）
const OPEN_SOURCE_SUBSCRIPTION = {
  plan: "pro",
  source: "open_source",
  is_free: true,
}
```

### 号池绕过订阅限制

```typescript
// 摘自 proxy/src/account-pool.ts — 号池多账号绕过
// 每个账号独立的订阅限制
// 号池通过多账号轮流使用绕过单账号配额限制
class AccountPool {
  // HTTP 请求: 共享模式，多个请求分发到不同账号
  acquireHttp(): AuthManager | null {
    const candidates = this.accounts
      .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
      .sort((a, b) => a.lastUsedAt - b.lastUsedAt)
    // ... Round-Robin 分配
  }

  // WebSocket: 独占模式，一个账号绑定一个 WS 流直到结束
  acquireWs(): AuthManager | null {
    const candidates = this.accounts
      .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
      .sort((a, b) => a.lastUsedAt - b.lastUsedAt)
    // 取最久未用的 ACTIVE 账号锁定
  }
}
```

---

## 轮次 12: 号池管理协议确认

**目标**: 确认 AccountPool 的完整状态机和错误处理体系

### 账号状态机

```
┌──────────┐    登录成功    ┌──────────┐
│  CREATED │──────────────▶│  ACTIVE  │
│  (创建)  │               │  (活跃)  │
└──────────┘               └──────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
              会话过期/状态检查失败       3次登录失败/
                    │                 密码错误/账号被封
                    ▼                       ▼
              ┌──────────┐           ┌──────────┐
              │  EXPIRED │           │  INVALID │
              │  (过期)  │           │  (无效)  │
              └──────────┘           └──────────┘
                    │
              自动重新登录
                    ▼
              ┌──────────┐
              │  ACTIVE  │
              │  (重新活跃)│
              └──────────┘
```

### 错误码处理策略

```typescript
// 摘自 proxy/src/account-pool.ts — 错误码分发
handleError(auth: AuthManager, errorCode: number): boolean {
  const entry = this.findByAuth(auth)
  if (!entry) return false

  switch (errorCode) {
    case 40100: // 会话无效 → 重登录
      entry.status = "EXPIRED"
      this.loginAccount(entry).catch(() => {})
      return true  // 可切换账号重试

    case 40300: // 权限不足 → 降级
      console.warn(`[AccountPool] ${entry.email}: permission denied, degrading`)
      return false

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

### 健康检查源码

```typescript
// 摘自 proxy/src/account-pool.ts — 定时健康检查
private async healthCheck(): Promise<void> {
  for (const entry of this.accounts) {
    if (entry.status !== "ACTIVE") continue

    // 清理僵尸 WS 锁
    if (entry.lockedByWs && entry.lockedAt &&
        Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
      entry.lockedByWs = false
      entry.lockedAt = null
    }

    // 检查 Cookie 年龄（30 天硬限制）
    if (entry.cookieSetAt &&
        Date.now() - entry.cookieSetAt > SESSION_MAX_AGE_MS) {
      await this.loginAccount(entry)
      continue
    }

    // 调用 /users/status 检查有效
    try {
      const ok = await entry.auth.checkStatus()
      if (!ok) {
        await this.loginAccount(entry)
      }
    } catch {
      entry.status = "EXPIRED"
    }
  }
}
```

---

## 本阶段总结

| 轮次 | 关键产出 | 后续影响 |
|------|---------|---------|
| 7 | ACP 事件全表确认 (7 种→9 种) | 完整解析 Agent 实时输出 |
| 8 | 授权矩阵 4 级 | 实现 API 权限检查 |
| 9 | 百智云 OAuth 6 步流程 | 实现纯 HTTP OAuth 自动化 |
| 10 | mode=attach 多轮对话设计 | 实现 ConversationManager |
| 11 | 订阅计费 SubscriptionResp | 号池绕过限制 |
| 12 | 号池状态机 + 5 种错误码 | 完整错误隔离体系 |

## 相关章节

- [ACP 事件参考](../../04-websocket/06-acp-event-reference.md)
- [OAuth 自动化](../../07-proxy/05-oauth-automation.md)
- [号池管理](../../07-proxy/02-account-pool.md)
- [多轮对话](../../07-proxy/03-multi-turn-conversation.md)