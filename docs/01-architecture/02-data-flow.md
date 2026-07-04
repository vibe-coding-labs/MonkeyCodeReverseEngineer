---
description: 核心数据流完整源码跟踪 — Chat/Responses/OAuth/账户/模型 5 条关键路径
protocol_version: based on proxy/src/ 全部 10 文件 + Go 后端源码
confidence: high
last_verified: 2026-06-28
---

# 核心数据流（源码增强版）

> **覆盖范围:** 5 条关键数据路径，每条含实际源码追踪
> **新增:** 账户获取流、模型解析流、OAuth 登录流

## 1. Chat Completions 请求生命周期

```
Client (OpenAI SDK)        代理 api-routes.ts       代理 task-runner.ts          MonkeyCode 后端
  │                           │                        │                           │
  │ POST /v1/chat/completions │                        │                           │
  ├─────────────────────────►│                        │                           │
  │                           │                        │                           │
  │                           │ 1. 验证：messages 非空 │                           │
  │                           │ 2. 模型解析（6 层回退） │                           │
  │                           │   modelManager.resolveModel(modelId)               │
  │                           ├──────────────────────────────────────────────────►│
  │                           │◄──── { models: [...] } ──────────────────────────│
  │                           │                        │                           │
  │                           │ 3. 检查对话复用        │                           │
  │                           │   conversationManager?.get(conversationId)         │
  │                           │                        │                           │
  │                           │ 4. 获取账号（号池模式）│                           │
  │                           │   accountPool?.acquireWs()                         │
  │                           │   accountPool?.acquireHttp()   ← 回退              │
  │                           │                        │                           │
  │                           │ 5. 转换 prompt 格式     │                           │
  │                           │   messagesToPrompt()   │                           │
  │                           │                        │                           │
  │                           │ 6. 创建任务             │                           │
  │                           ├──────────────────────►│                           │
  │                           │   createTask()         │ POST /api/v1/users/tasks  │
  │                           │                        ├─────────────────────────►│
  │                           │                        │◄── { task_id } ─────────│
  │                           │◄── taskId ────────────│                           │
  │                           │                        │                           │
  │                           │ 7. 流式接收             │                           │
  │                           ├──────────────────────►│                           │
  │                           │   streamTask()         │ WS connect                │
  │                           │                        ├─────────────────────────►│
  │                           │                        │◄── opened ──────────────│
  │                           │                        │                           │
  │                           │                        │ send: auto-approve        │
  │                           │                        │ send: user-input          │
  │                           │                        │                           │
  │                           │ 8. ACP → SSE           │◄── task-started ─────────│
  │ ◄── SSE: chunk ─────────│◄── 事件转换 ───────────│◄── agent_message_chunk ──│
  │ ◄── SSE: chunk ─────────│◄── 事件转换 ───────────│◄── agent_thought_chunk ──│
  │ ◄── SSE: chunk ─────────│◄── 事件转换 ───────────│◄── tool_call ────────────│
  │                           │                        │◄── usage_update ─────────│
  │ ◄── SSE: [DONE] ────────│◄── task-ended ─────────│◄── task-ended ───────────│
  │                           │                        │                           │
  │                           │ 9. 释放账号（号池模式）│                           │
  │                           │   accountPool?.releaseWs(auth)                     │
```

### 数据流关键代码（1→6 步）

```typescript
// api-routes.ts — 第 2~6 步
const model = await modelManager.resolveModel(body.model || "")

let accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null

const systemMsg = body.messages.find((m) => m.role === "system")
const prompt = body.messages.filter((m) => m.role !== "system")
  .map((m) => `[${m.role === "user" ? "User" : "Assistant"}]\n${m.content}`).join("\n\n")

const taskId = await taskRunner.createTask(model, prompt, {
  authOverride: accountAuth || undefined,
  systemPrompt: systemMsg?.content,
})
```

### 数据流关键代码（7→9 步）

```typescript
// api-routes.ts — 第 7~9 步（流式分支）
const sendSSE = (data: object) => {
  if (res.writableEnded) return
  res.write(`data: ${JSON.stringify(data)}\n\n`)
}

await taskRunner.streamTask(taskId, prompt, (chunk) => {
  sendSSE(chunk)                            // ACP→SSE 分块转发
}, abortController.signal, auth || undefined)

sendSSE({ object: "done" })
res.write("data: [DONE]\n\n")
res.end()
pool?.releaseWs(auth)                       // 释放 WS 锁
```

## 2. Responses API 数据流

```
Client                          代理 api-routes.ts               MonkeyCode 后端
  │ POST /v1/responses              │                               │
  ├───────────────────────────────►│                               │
  │                                │ 1. 模型解析 + 任务创建（同 Chat） │
  │                                │                               │
  │                                │ 2. Responses SSE 模式          │
  │                                │ sendEvent("response.created") │
  │◄── event: response.created ──│                               │
  │                                │                               │
  │                                │ 3. streamTaskRaw() 接收 ACP    │
  │                                │   agent_message_chunk →        │
  │◄── event: response.output_text.delta ──│                     │
  │                                │   tool_call →                  │
  │◄── event: response.output_item.added ──│                    │
  │                                │   tool_call_update →           │
  │◄── event: response.function_call_arguments.delta ──│        │
  │                                │                               │
  │                                │ 4. task-ended → 完成           │
  │◄── event: response.completed ─│                               │
```

## 3. 账户获取流（号池模式）

```
api-routes.ts                      account-pool.ts
  │                                   │
  │ acquireWs() / acquireHttp()       │
  ├─────────────────────────────────►│
  │                                   │ 1. 过滤 ACTIVE 且 !lockedByWs
  │                                   │ 2. 按 lastUsedAt 升序排序
  │                                   │ 3. 取最久未用的账号
  │                                   │    └── acquireWs: 设置 lockedByWs=true, lockedAt=Date.now()
  │                                   │    └── acquireHttp: roundRobinIndex++
  │                                   │ 4. 返回 AuthManager 实例
  │◄──── auth ──────────────────────│
  │                                   │
  │ 使用 auth 创建任务 + WS 流        │
  │                                   │
  │ finally: releaseWs(auth)          │
  ├─────────────────────────────────►│
  │                                   │ lockedByWs=false, lockedAt=null
```

```typescript
// account-pool.ts — acquireWs 源码
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

## 4. 会话认证流

```
AuthManager                    MonkeyCode 后端              Redis
  │                               │                         │
  │ getSessionCookie()            │                         │
  ├─ 检查缓存: Date.now() - TTL?  │                         │
  ├─ 过期？→ login()              │                         │
  │      │                        │                         │
  │      │ POST /password-login   │                         │
  │      ├──────────────────────►│                         │
  │      │ 验证密码 bcrypt        │                         │
  │      │ 创建 Session          │── SET Lookup Key ──────►│
  │      │                       │── SET Hash Key ────────►│
  │      │◄── Set-Cookie + 200 ─│                         │
  │      │                        │                         │
  │ 缓存 Cookie + 更新时间戳      │                         │
  │                              │                         │
  │ return Cookie                │                         │
  │                              │                         │
  │ authHeaders()                │                         │
  ├─ getSessionCookie()          │                         │
  ├─ 构造 {Cookie, Content-Type} │                         │
  │ return headers               │                         │
```

```typescript
// auth.ts — Session 缓存与刷新
async getSessionCookie(): Promise<string> {
  if (this.sessionCookie && Date.now() - this.lastAuthTime < this.sessionTTL) {
    return this.sessionCookie            // 24h 缓存命中
  }
  await this.login()                      // 过期→重新登录
  return this.sessionCookie
}

async authHeaders(): Promise<Record<string, string>> {
  const cookie = await this.getSessionCookie()
  return {
    Cookie: `${this.sessionCookieName}=${cookie}`,
    "Content-Type": "application/json",
  }
}
```

## 5. 模型解析流（6 层回退）

```
modelManager.resolveModel(modeId)
  │
  │ await fetchModels()
  │   └─ 缓存命中？→返回
  │   └─ 未命中？→ GET /api/v1/users/models → 缓存 5 分钟
  │
  │ 6 层回退匹配：
  ├── 第 1 层：精确匹配 "monkeycode/{provider}/{model}"
  ├── 第 2 层：匹配 "{provider}/{model}" 格式
  ├── 第 3 层：匹配 model 名称
  ├── 第 4 层：匹配 display_name
  ├── 第 5 层：回退到 is_default 模型
  └── 第 6 层：回退到 models[0]
```

```typescript
// 用户输入解析示例
// 用户输入 "gpt-4o"
// 第 3 层命中 → model === "gpt-4o"
// 返回 MonkeyCodeModel { provider: "openai", model: "gpt-4o", interface_type: "openai_chat" }

// 用户输入 "monkeycode/siliconflow/Qwen/Qwen3.5-Plus"
// 第 1 层命中 → 精确匹配完整路径
```

## 6. OAuth 登录流（6 步）

```
server.ts                    admin-login.ts                 百智云/MonkeyCode
  │                              │                              │
  │ POST /admin/login/send-code   │                              │
  ├────────────────────────────►│                              │
  │                              │ 1. startOAuthLogin()         │
  │                              │   GET /api/v1/users/login    │
  │                              ├─────────────────────────────►│
  │                              │◄── 302 + state/clientId ───│
  │                              │                              │
  │                              │ 2. getSCaptchaToken()        │
  │                              │   POST *.s-captcha-r1.com    │
  │                              │◄── { token: "sc_xxx" } ────│
  │                              │                              │
  │                              │ 3. sendSmsCode(phone, token) │
  │                              │   POST baizhi.cloud/phone_code
  │                              ├─────────────────────────────►│
  │                              │◄── { code: 0 } ────────────│
  │◄── { state, msg } ─────────│                              │
  │                              │                              │
  │ POST /admin/login/verify     │                              │
  ├────────────────────────────►│                              │
  │                              │ 4. baizhiPhoneLogin(code)    │
  │                              │   POST baizhi.cloud/login/phone
  │                              ├─────────────────────────────►│
  │                              │◄── baizhi cookies + user   │
  │                              │                              │
  │                              │ 5. baizhiOAuthAuthorize()    │
  │                              │   GET baizhi.cloud/oauth/authorize
  │                              ├─────────────────────────────►│
  │                              │◄── 302 + code ─────────────│
  │                              │                              │
  │                              │ 6. monkeycodeCallback()      │
  │                              │   GET callback?code=xxx      │
  │                              ├─────────────────────────────►│
  │                              │◄── Set-Cookie: session ────│
  │                              │                              │
  │◄── { sessionCookie,        │                              │
  │       imageId, models }     │                              │
```

---

## 相关章节

- [系统架构总览](01-system-overview.md) — 四层架构
- [组件层级分析](03-component-layer.md) — 完整类型系统
- [代理架构调用图](../07-proxy/01-architecture.md) — 模块依赖关系