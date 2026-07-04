---
description: MonkeyCode 各层错误处理模式 — 基于 proxy 层 TypeScript 源码和 Go 后端的完整错误处理分析
protocol_version: based on chaitin/MonkeyCode + proxy/src/ 全部 10 文件源码
confidence: high
last_verified: 2026-06-28
---

# 错误处理模式（源码增强版）

## 1. 代理层的错误处理全景

MonkeyCode 的代理层（TypeScript 3031 行）实现了 5 种主要的错误处理模式：

| 模式 | 源码位置 | 触发场景 |
|------|---------|---------|
| 号池自动重试 | `account-pool.ts` handleError | HTTP API 调用失败 |
| WS 自动重连 | `task-runner.ts` streamTask | WebSocket 断开 |
| 超时保护 | `task-runner.ts` setTimeout | 任务超过 1h 无响应 |
| 优雅降级 | `api-routes.ts` try/catch 链 | 后端 API 错误 |
| 僵尸恢复 | `account-pool.ts` healthCheck | WS 锁未释放 |

## 2. 代理 HTTP 调用错误处理

### 2.1 创建任务的错误处理

```typescript
// proxy/src/task-runner.ts
async createTask(...): Promise<string> {
  // 1. 检查 Image ID
  if (!imageId) {
    throw new Error("MONKEYCODE_IMAGE_ID is required.")
  }

  // 2. 发送请求
  const response = await fetch(url, {
    method: "POST",
    headers: mkHeaders(headers),
    body: JSON.stringify(body),
  })

  // 3. HTTP 状态码错误
  if (!response.ok) {
    const respText = await response.text()
    throw new Error(`Failed to create task (${response.status}): ${respText}`)
  }

  // 4. 业务错误（HTTP 200 + code != 0）
  if (result.code && result.code !== 0) {
    throw new Error(
      `Failed to create task (code ${result.code}): ${result.message || JSON.stringify(result)}`
    )
  }

  return data.id || data.task_id
}
```

**注意：** 后端即使业务失败也返回 HTTP 200，通过 `code` 字段区分成功/失败。

### 2.2 模型加载的错误处理

```typescript
// proxy/src/api-routes.ts — POST /v1/chat/completions
router.post("/v1/chat/completions", async (req, res) => {
  try {
    // 验证请求体
    if (!body.messages || body.messages.length === 0) {
      res.status(400).json({
        error: { message: "messages is required", type: "invalid_request_error" }
      })
      return
    }

    // 模型解析失败
    const model = await modelManager.resolveModel(body.model || "")
    if (!model) {
      res.status(404).json({
        error: { message: `Model '${body.model}' not found`, type: "invalid_request_error" }
      })
      return
    }

    // 主逻辑
    // ...

    // 顶层 catch — 所有未捕获错误的最后防线
  } catch (err: any) {
    console.error("[Chat] Error:", err.message)
    if (!res.headersSent) {
      res.status(500).json({
        error: { message: err.message, type: "internal_error" }
      })
    }
  }
})
```

**保护头：** `if (!res.headersSent)` 防止多次写入响应。

### 2.3 模型列表错误

```typescript
// proxy/src/api-routes.ts — GET /v1/models
router.get("/v1/models", async (_req: Request, res: Response) => {
  try {
    const models = await modelManager.toOpenAIModels()
    res.json({ object: "list", data: models })
  } catch (err: any) {
    console.error("[Models] Error:", err.message)
    res.status(500).json({
      error: { message: err.message, type: "internal_error" }
    })
  }
})
```

## 3. WebSocket 错误处理

### 3.1 WS 连接失败

```typescript
// proxy/src/task-runner.ts — WS 连接错误处理
ws.on("error", (err) => {
  if (!resolved) {
    resolved = true
    reject(err)  // 只有首次错误会 reject
  }
})

// 超时保护（30s 连接超时）
setTimeout(() => {
  if (!resolved) {
    console.warn(`[ConversationManager] WebSocket connection timed out...`)
    cleanup()
    resolve()  // 超时 resolve 而不是 reject，确保不挂起
  }
}, 30000)
```

### 3.2 WS 消息解析错误

```typescript
// proxy/src/task-runner.ts — 消息解析错误静默忽略
ws.on("message", (raw: WebSocket.Data) => {
  if (resolved) return
  try {
    const msg: TaskStreamMessage = JSON.parse(raw.toString())
    // 处理消息
  } catch {
    // 忽略非 JSON 消息（如二进制帧、文本格式异常等）
  }
})
```

### 3.3 WS 异常关闭

```typescript
// proxy/src/task-runner.ts — WS 关闭处理
ws.on("close", () => {
  if (!resolved) {
    resolved = true
    resolve()  // 关闭也算正常结束
  }
})
```

### 3.4 WS 心跳保活

```typescript
// WS ping/pong 处理
if (msg.type === "ping") {
  ws.send(JSON.stringify({ type: "ping" }))
  return
}
```

## 4. 号池错误处理与恢复

### 4.1 错误码处理矩阵

```typescript
// proxy/src/account-pool.ts handleError
handleError(auth: AuthManager, errorCode: number): boolean {
  const entry = this.findByAuth(auth)
  if (!entry) return false

  switch (errorCode) {
    case 40100:  // 会话无效
      entry.status = "EXPIRED"
      this.loginAccount(entry).catch(() => {})
      return true  // 可重试（换账号）

    case 40300:  // 权限不足
      console.warn(`[AccountPool] ${entry.email}: permission denied`)
      return false  // 不可重试

    case 40002:  // 密码错误
    case 40003:  // 账号被封
    case 40004:  // 账号未激活
      entry.status = "INVALID"
      console.error(`[AccountPool] ${entry.email}: marked INVALID`)
      return false  // 不可重试

    case 50000:  // 服务端内部错误
      return true  // 可重试（指数退避）

    default:
      return false
  }
}
```

### 4.2 号池初始化容错

```typescript
// proxy/src/account-pool.ts — 批量登录容忍失败
async initAll(): Promise<void> {
  const results = await Promise.allSettled(
    created.map((a) => this.loginAccount(a))
  )
  const ok = results.filter((r) => r.status === "fulfilled").length
  console.log(`[AccountPool] Init complete: ${ok}/${created.length} succeeded`)
  // 部分失败不影响其他账号
}
```

### 4.3 登录失败重试

```typescript
// proxy/src/account-pool.ts — 登录重试
private async loginAccount(entry: AccountEntry): Promise<void> {
  try {
    await entry.auth.login()
    entry.status = "ACTIVE"
    entry.errorCount = 0
  } catch (err: any) {
    entry.errorCount++
    if (entry.errorCount >= 3) {
      entry.status = "INVALID"  // 连续 3 次失败标记为不可用
    }
  }
}
```

### 4.4 告警阈值

```typescript
private checkAlerts(): void {
  const activeRatio = active / total

  if (activeRatio < 0.5) {
    // P0: 可用账号低于 50%
    console.error(`P0 ALERT: available accounts < 50% (${active}/${total})`)
  } else if (activeRatio < 0.7) {
    // P1: 可用账号低于 70%
    console.warn(`P1 WARN: available accounts < 70% (${active}/${total})`)
  }
}
```

## 5. 后端 Go 错误处理模式

### 5.1 统一响应格式

```go
// backend/pkg/response/response.go
func Success(c *gin.Context, data interface{}) {
    c.JSON(http.StatusOK, Response{
        Code: 0,
        Msg:  "success",
        Data: data,
    })
}

func Fail(c *gin.Context, code int, msg string) {
    c.JSON(http.StatusOK, Response{  // 注意: 200 OK + 非零 code
        Code: code,
        Msg:  msg,
        Data: nil,
    })
}
```

**关键：** 即使业务失败也返回 HTTP 200，通过 `code` 字段区分成功/失败。前端通过检查 `code === 0` 判断成功。

### 5.2 模拟模式（开发环境）

```go
// backend/pkg/llm/client.go
func (c *Client) ChatCompletion(ctx context.Context, req ChatReq) (*ChatResp, error) {
    if req.ApiKey == "" {
        return mockChatCompletion(ctx, req)  // 无 API Key 时返回模拟响应
    }
    // 真实调用
}
```

### 5.3 错误消息包装

```go
// ChatNoException 将 LLM 错误转为用户友好的内容字符串
func ChatNoException(err error) string {
    return fmt.Sprintf("模型调用失败: %v", err)
}
```

### 5.4 健康检查错误处理

```go
type HealthCheckResult struct {
    Error string `json:"error,omitempty"`
}

// 错误处理逻辑
// - HTTP 连接错误 → last_check_success = false
// - API 返回错误 → last_check_success = false + 保存错误信息
// - 超时 → last_check_success = false
// - 连接成功 → last_check_success = true
```

## 6. 启动时的错误容忍

### 6.1 模型加载失败

```typescript
// proxy/src/server.ts — 模型加载失败不影响启动
try {
  const models = await modelManager.fetchModels()
  console.log(`[Init] Available models: ${models.length}`)
} catch (err: any) {
  console.warn(`[Init] Failed to fetch models: ${err.message}`)
  // 代理仍然启动，API 调用会在运行时失败
}
```

### 6.2 号池配置文件加载失败

```typescript
// proxy/src/server.ts — 号池文件加载失败回退
if (poolFile) {
  try {
    accounts = await loadAccountConfigs(resolved)
  } catch (err: any) {
    console.warn(`[Init] Failed to load account pool file '${poolFile}': ${err.message}`)
    // 回退到单账号模式
  }
}
```

### 6.3 单账号认证失败

```typescript
// proxy/src/server.ts — 认证失败不影响启动
if (!accountPool && singleAuth) {
  try {
    await singleAuth.getSessionCookie()
    console.log("[Init] Authentication successful")
  } catch (err: any) {
    console.warn(`[Init] Authentication failed: ${err.message}`)
    console.warn("[Init] Proxy will start but API calls will fail until authenticated")
    // 代理仍然启动，调用会 401
  }
}
```

## 7. 错误处理层次图

```
                        代理层错误处理树
                    ┌────────────────────┐
                    │   server.ts 启动    │
                    │   尝试初始化所有模块 │
                    │   容忍部分失败      │
                    └────────┬───────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ HTTP API 调用 │ │ WS 连接/流   │ │ 号池管理     │
    │ (api-routes)  │ │ (task-runner) │ │ (account-pool)│
    ├──────────────┤ ├──────────────┤ ├──────────────┤
    │ try/catch 链 │ │ on('error')  │ │ handleError  │
    │ 模型不存在→404 │ │ JSON 解析失败→ │ │ 40100→重试   │
    │ 消息为空→400  │ │ 静默忽略     │ │ 40003→标记   │
    │ 其他→500     │ │ 超时→resolve │ │ 50000→指数   │
    │ headersSent  │ │ 关闭→resolve │ │ 退避         │
    │ 保护         │ │              │ │             │
    └──────────────┘ └──────────────┘ └──────────────┘
```

## 8. 错误恢复策略对比

| 策略 | 触发条件 | 处理方式 | 恢复时间 |
|------|---------|---------|---------|
| **号池切换** | 当前账号 40100 | 标记 EXPIRED → 重登录 → 换其他账号 | 1s~几秒 |
| **WS 重连** | WS 意外断开 | mode=attach 回放历史 + 继续 | 500ms~8s |
| **超时** | 任务超过 1h | resolve() 返回已收集的内容 | 不重试 |
| **僵尸 WS 锁** | 健康检查发现 | 强制释放 + 账号重新可用 | 1h（下个周期） |
| **连续失败** | 登录失败 3 次 | 标记 INVALID → 移除号池 | 手动恢复 |
| **status 检查** | 健康检查发现 | 重新登录 | 1h（下个周期） |
| **JSON 解析失败** | WS 收到非 JSON | 静默跳过 | N/A |

---

## 相关章节

- [第一章：系统架构](01-system-overview.md) — 整体架构
- [第二章：认证协议](../02-auth/README.md) — 认证错误处理
- [第四章：WebSocket 协议](../04-websocket/README.md) — WS 重连细节
- [第七章：代理实现](../07-proxy/README.md) — 代理中的错误处理代码