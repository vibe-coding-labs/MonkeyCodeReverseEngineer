---
description: 错误码速查表 — API 错误码、HTTP 状态码、ACP 事件错误、账号池错误处理、代理错误
protocol_version: based on chaitin/MonkeyCode + proxy/src/ 全部 10 文件
confidence: high
last_verified: 2026-06-28
---

# 错误码速查表（源码增强版）

## 通用 API 错误码

所有 MonkeyCode API 响应遵循统一格式：

```json
{
  "code": 0,       // 0 = 成功，非 0 = 错误
  "msg": "success",
  "data": { ... }
}
```

## 错误码全集

| 错误码 | 含义 | 说明 | 处理方式 | 源码位置 |
|--------|------|------|---------|---------|
| `40100` | Session 过期/无效 | Cookie 过期、被删除、或被踢下线 | 代理标记 EXPIRED → 调用 loginAccount() | `middleware/auth.go`, `account-pool.ts:218` |
| `40300` | 权限不足 | 账号无权访问该资源 | 代理标记 INVALID，不可重试 | `account-pool.ts:225` |
| `40002` | 密码错误 | 登录密码错误 | 代理标记 INVALID，移除号池 | `account-pool.ts:229` |
| `40003` | 账号被封禁 | 用户状态为 `banded` | 代理标记 INVALID，移除号池 | `account-pool.ts:230` |
| `40004` | 账号未激活 | 用户处于 `inactive` 状态 | 代理标记 INVALID，移除号池 | `account-pool.ts:231` |
| `50000` | 服务端错误 | MonkeyCode 后端内部错误 | 代理标记可重试 | `account-pool.ts:236` |
| `10811` | 任务已在运行 | 同一 task 已经有正在执行的轮次 | 代理抛出 Error | `task-runner.ts:93` |

### 错误码的号池处理策略

```typescript
// proxy/src/account-pool.ts — 完整的错误码策略
handleError(auth: AuthManager, errorCode: number): boolean {
  const entry = this.findByAuth(auth)
  if (!entry) return false

  switch (errorCode) {
    case 40100:  // 会话无效 → 重登录后可切换账号重试
      entry.status = "EXPIRED"
      this.loginAccount(entry).catch(() => {})
      return true  // 可重试

    case 40300:  // 权限不足
      console.warn(`[AccountPool] ${entry.email}: permission denied`)
      return false  // 不可重试

    case 40002:  // 密码错误
    case 40003:  // 账号被封
    case 40004:  // 账号未激活
      entry.status = "INVALID"  // 终态
      console.error(`[AccountPool] ${entry.email}: marked INVALID (code ${errorCode})`)
      return false  // 不可重试

    case 50000:  // 服务端内部错误
      return true  // 可重试

    default:
      return false
  }
}
```

## HTTP 状态码

| HTTP 状态码 | 场景 | 说明 |
|------------|------|------|
| 200 | 请求成功 | 即使业务逻辑失败也返回 200，通过 `code` 区分 |
| 201 | 创建成功 | 验证码创建返回 |
| 302 | 登录/OAuth 跳转 | 密码登录成功或 OAuth 重定向（`redirect: "manual"` 必需） |
| 400 | 请求参数错误 | JSON 解析失败、缺少必填字段 |
| 401 | 未认证 | `Auth()` 中间件拒绝（无 Cookie 或 Cookie 无效） |
| 403 | 权限不足 | `TeamAdminAuth()` 检查失败（非 admin 尝试管理操作） |
| 404 | 资源不存在 | 模型/任务/VM 不存在 |
| 500 | 服务器内部错误 | 后端未捕获的异常 |
| 502 | 代理错误 | 代理连接后端失败或后端返回错误 |

## 代理错误响应（OpenAI 兼容格式）

```json
// HTTP 400 — 请求参数错误
{
  "error": { "message": "messages is required", "type": "invalid_request_error" }
}

// HTTP 400 — 缺少 input
{
  "error": { "message": "input is required", "type": "invalid_request_error" }
}

// HTTP 404 — 模型不存在
{
  "error": { "message": "Model 'xxx' not found", "type": "invalid_request_error" }
}

// HTTP 500 — 代理或后端内部错误
{
  "error": { "message": "Error details...", "type": "internal_error" }
}

// HTTP 502 — 后端不可达
{
  "error": { "message": "客户端未初始化", "type": "upstream_error" }
}
```

## ACP 事件错误

| ACP 事件 | 错误含义 | 代理处理 | 代理代码 |
|---------|---------|---------|---------|
| `task-error` | 任务执行出错 | 输出 `[Error] ${msg.data}` chunk 到 SSE 流 | `task-runner.ts:249-257` |
| `acp_ask_user_question` | Agent 向用户提问 | 自动回复 `{answers_json: "", cancelled: false}` | `task-runner.ts:214-231` |
| WS 连接错误 | WebSocket 握手失败 | reject Promise（首次错误） | `task-runner.ts:172-177` |
| WS 连接超时 | 30 秒无响应 | 记录日志并 resolve（不 reject） | `conversation-manager.ts:202-208` |
| WS 消息解析错误 | JSON 解析失败 | `catch { /* 静默忽略 */ }` | `task-runner.ts:160-163` |
| 任务超时 | 超过 1h（可配置） | `cleanup()` + `resolve()` 返回已收集内容 | `task-runner.ts:180-186` |
| Stream 错误 | 流式处理异常 | `catch {}` 静默处理，不中断响应 | `task-runner.ts:406-407` |
| 模型列表错误 | 后端 API 失败 | 记录错误日志，返回 500 | `api-routes.ts:36-39` |

## 代理内部错误

### 请求验证错误（api-routes.ts）

| 错误场景 | 错误对象 | HTTP 状态码 | 错误类型 |
|---------|---------|------------|---------|
| 缺少消息 | `messages is required` | 400 | `invalid_request_error` |
| 模型不存在 | `Model 'xxx' not found` | 404 | `invalid_request_error` |
| 缺少 input（Responses API） | `input is required` | 400 | `invalid_request_error` |

### 认证错误（auth.ts）

| 错误场景 | 错误对象 | 说明 |
|---------|---------|------|
| 凭据缺失 | `Error("Missing credentials. Set MONKEYCODE_EMAIL and MONKEYCODE_PASSWORD")` | 未设置 email/password |
| 登录 API 错误 | `Error("User login failed (status): body")` | 登录 API 返回非 200 且非 302 |
| Cookie 提取失败 | `Error("Cannot extract X from Set-Cookie")` | Set-Cookie 头格式异常或缺失 |

### 号池错误（account-pool.ts）

| 错误场景 | 错误对象 | 说明 |
|---------|---------|------|
| TS 号码源错误 | `No accounts configured, pool is empty` | 空号池警报 |
| 登录失败 | `login failed (attempt N): message` | 重试日志 |
| 超过重试次数 | `marked INVALID after N failed attempts` | 登录失败 3 次后标记永久不可用 |
| 僵尸 WS 锁 | `WS lock expired after Ns, force releasing` | 超时未释放的锁 |

### 任务创建错误（task-runner.ts）

| 错误场景 | 错误对象 | 说明 |
|---------|---------|------|
| 缺少 IMAGE_ID | `Error("MONKEYCODE_IMAGE_ID is required...")` | 必需配置缺失 |
| HTTP 错误 | `Error("Failed to create task (status): text")` | 后端 API 返回非 200 |
| 业务错误 | `Error("Failed to create task (code X): message")` | API 返回 code != 0 |

### SSE 流式响应错误

```typescript
// proxy/src/api-routes.ts — 流式响应错误处理
// 错误时发送 [DONE] 结束标记
} finally {
  sendSSE({ object: "done" })
  res.write("data: [DONE]\n\n")
  res.end()
  if (auth && pool) {
    pool.releaseWs(auth)  // 释放 WS 独占锁
  }
}
```

## 启动时错误容忍

代理启动期间多个组件出错不会阻止启动：

```typescript
// server.ts — 号池文件加载失败
try { accounts = await loadAccountConfigs(resolved) }
catch { console.warn(`Failed to load account pool file`) }
// → 回退到单账号模式

// server.ts — 模型预取失败
try { await modelManager.fetchModels() }
catch { console.warn(`Failed to fetch models`) }
// → 代理仍然启动，调用时失败

// server.ts — 单账号认证失败
try { await singleAuth.getSessionCookie() }
catch { console.warn(`Authentication failed`) }
// → 代理仍然启动，直到手动设置 Cookie
```

## 错误处理最佳实践

| 策略 | 适用场景 | 实现位置 |
|------|---------|---------|
| 静默忽略 | WS 消息解析错误、plan/commands 日志事件 | `task-runner.ts catch { }` |
| 重试 + 指数退避 | 网络错误、5xx | `account-pool.ts handleError(50000)` |
| 切换账号 | 40100 session 过期 | `account-pool.ts handleError(40100) → 'retry'` |
| 移除账号 | 40002/40003/40004 账号不可用 | `account-pool.ts → 'invalid'` |
| 自动回复 | Agent 询问确认 | `task-runner.ts reply-question` |
| 超时 resolve | WS 连接/任务超时 | `task-runner.ts setTimeout → resolve()` |
| `!headersSent` | 防止多次写入响应 | `api-routes.ts catch → if (!res.headersSent)` |
| `sseEnded` 检查 | SSE 流已结束忽略 | `api-routes.ts sendSSE → if (res.writableEnded) return` |

---

## 相关章节

- [错误处理模式](../01-architecture/04-error-handling-patterns.md) — 完整错误处理分析
- [号池差距分析](../02-auth/08-pool-gap-analysis.md) — 号池错误恢复策略
- [代理错误处理](../07-proxy/04-acp-to-openai-mapping.md) — ACP→SSE 映射中的错误处理