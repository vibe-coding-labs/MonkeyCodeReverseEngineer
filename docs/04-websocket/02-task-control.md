---
description: Task Control WebSocket 协议完整分析 — 基于 proxy/src/task-runner.ts 和源码反推
protocol_version: based on chaitin/MonkeyCode 开源后端源码 + proxy/src/task-runner.ts
confidence: high
last_verified: 2026-06-28
---

# Task Control WebSocket（源码增强版）

## 1. 协议架构总览

Task Control WebSocket 是 MonkeyCode 的**任务控制通道**，独立于 Task Stream 的事件流通道。它提供 RPC 调用、文件操作、模型切换等控制功能。

```
Control WS (RPC 控制)
──────────────────
Client → Server: call (repo_file_list / switch_model / restart / ...)
               → sync-my-ip
Server → Client: call-response
               → task-event
               → ping (每 10s)

Stream WS (事件流)
──────────────────
Client → Server: user-input / user-cancel / auto-approve / ping
Server → Client: task-started / task-running(kind=acp_event) / task-ended / task-error / ping
```

## 2. 连接与生命周期

### 2.1 端点

```http
GET /api/v1/users/tasks/control?id={taskId}
Cookie: monkeycode_ai_session=xxx
```

### 2.2 关键特性

- **长连接**: 任务完成后 Control WS 仍然保持
- **一对多映射**: 一个 task 可以有多个并发 Control WS 连接（多标签页支持）
- **保活机制**: 每 60 秒刷新 VM 空闲计时器，防止 VM 进入 `hibernated` 状态
- **任务停止**: 通过 PUT `/api/v1/users/tasks/stop` HTTP 端点实现（见 task-runner.ts）

### 2.3 与 Task Stream WS 的关系

```
TASK STREAM WS                           TASK CONTROL WS
──────────────                           ────────────────
单向：后→前推送事件                      双向：RPC 请求/响应
自动审批(user-input→auto-approve)        文件操作(repo_file_list, repo_read_file)
ACP 事件流(agent_message/thought/...)    模型切换(switch_model)
任务状态变化(task-ended/task-error)       端口转发管理(port_forward_list)
心跳响应(ping/pong)                      重启任务(restart)
                                         心跳(ping, 每10s)
```

## 3. 完整消息格式

### 3.1 上行消息（Client → Server）

| type | kind | data 格式 | 说明 |
|------|------|-----------|------|
| `call` | `repo_file_list` | `{request_id, path, glob_pattern?, include_hidden}` | 列出目录文件 |
| `call` | `repo_file_diff` | `{request_id, path, unified, context_lines}` | 获取文件 diff |
| `call` | `repo_read_file` | `{request_id, path}` | 读取文件内容 |
| `call` | `repo_file_changes` | `{request_id}` | 获取变更文件列表 |
| `call` | `port_forward_list` | `{request_id}` | 获取端口转发列表 |
| `call` | `restart` | `{request_id, load_session}` | 重启任务 |
| `call` | `switch_model` | `{request_id, model_id, load_session}` | 切换模型 |
| `sync-my-ip` | — | `{ip: "..."}` | 同步客户端 IP |

### 3.2 下行消息（Server → Client）

| type | 说明 |
|------|------|
| `call-response` | RPC 响应（匹配 request_id） |
| `task-event` | 任务事件转发 |
| `ping` | 心跳（每 10s，客户端无响应不会断开） |

## 4. Call-Response 完整示例

### 4.1 读取文件（带 base64 编码）

```json
// 请求
{
  "type": "call",
  "kind": "repo_read_file",
  "data": "{\"request_id\":\"req-1\",\"path\":\"/workspace/main.go\"}"
}

// 成功响应
{
  "type": "call-response",
  "kind": "repo_read_file",
  "data": "{\"request_id\":\"req-1\",\"path\":\"/workspace/main.go\",\"content\":\"base64_encoded_content\",\"success\":true}"
}

// 失败响应
{
  "type": "call-response",
  "kind": "repo_read_file",
  "data": "{\"request_id\":\"req-1\",\"path\":\"/workspace/main.go\",\"error\":\"file not found\",\"success\":false}"
}
```

### 4.2 列出目录文件（支持 glob 模式）

```json
// 请求
{
  "type": "call",
  "kind": "repo_file_list",
  "data": "{\"request_id\":\"req-2\",\"path\":\"/workspace/src\",\"glob_pattern\":\"**/*.ts\",\"include_hidden\":false}"
}

// 响应
{
  "type": "call-response",
  "kind": "repo_file_list",
  "data": "{\"request_id\":\"req-2\",\"files\":[\"src/index.ts\",\"src/utils.ts\",\"src/types.ts\"],\"directories\":[\"src/components\"],\"success\":true}"
}
```

### 4.3 文件 Diff（带上下文行）

```json
// 请求
{
  "type": "call",
  "kind": "repo_file_diff",
  "data": "{\"request_id\":\"req-3\",\"path\":\"/workspace/main.go\",\"unified\":true,\"context_lines\":3}"
}

// 响应
{
  "type": "call-response",
  "kind": "repo_file_diff",
  "data": "{\"request_id\":\"req-3\",\"diff\":\"--- a/main.go\\n+++ b/main.go\\n@@ -10,6 +10,7 @@\\n ...\",\"success\":true}"
}
```

### 4.4 切换模型（运行时）

```json
// 请求
{
  "type": "call",
  "kind": "switch_model",
  "data": "{\"request_id\":\"req-4\",\"model_id\":\"550e8400-e29b-41d4-a716-446655440000\",\"load_session\":true}"
}

// 响应
{
  "type": "call-response",
  "kind": "switch_model",
  "data": "{\"request_id\":\"req-4\",\"model_id\":\"550e8400-e29b-41d4-a716-446655440000\",\"success\":true}"
}
```

### 4.5 重启任务

```json
// 请求
{
  "type": "call",
  "kind": "restart",
  "data": "{\"request_id\":\"req-5\",\"load_session\":true}"
}
```

## 5. 与代理层代码的关系

### 5.1 任务停止（HTTP，非 WS）

代理层通过 HTTP PUT 停止任务，而非 Control WS：

```typescript
// proxy/src/task-runner.ts
async stopTask(taskId: string, authOverride?: AuthManager): Promise<void> {
  const auth = authOverride || this.auth
  const url = `${MONKEYCODE_BASE_URL}/api/v1/users/tasks/stop`

  await fetch(url, {
    method: "PUT",
    headers: mkHeaders({
      Cookie: `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`,
      "Content-Type": "application/json",
    }),
    body: JSON.stringify({ id: taskId }),
  })
}
```

### 5.2 WS 连接参数

代理中 WebSocket 连接的请求头构造方式：

```typescript
// proxy/src/browser-headers.ts
export function wsHeaders(domain: string, cookie: string): Record<string, string> {
  return {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    Pragma: "no-cache",
    Origin: `https://${domain}`,
    Cookie: cookie,
    "Sec-WebSocket-Version": "13",
  }
}
```

## 6. 安全考虑

| 攻击面 | 风险 | 防护措施 |
|--------|------|---------|
| 未授权 Control WS 访问 | 可操作他人 VM | WS 连接需要 Cookie 认证，Auth 中间件校验 |
| WS 消息注入 | 构造恶意 RPC 调用 | 服务端验证 request_id 和参数格式 |
| 多标签页并发 | 竞争条件 | ControlConn 一对多映射，无锁访问 |
| WS 连接劫持 | Cookie 泄露后可控制 VM | WSS 加密，Cookie httpOnly+secure |

## 7. 最佳实践

1. **每 10s 处理 ping** — 保持连接活跃，避免被服务端断开
2. **使用 unique request_id** — 区分并发 RPC 请求的响应
3. **处理 call-response timeout** — 无响应时重试或报错
4. **模型切换后刷新 prompt** — 切换模型不会丢失当前会话
5. **任务停止优先用 HTTP API** — Control WS 可能已断开

---

## 相关章节

- [Task Stream WebSocket](01-task-stream.md) — ACP 事件流通道
- [VM 生命周期](../06-vm-taskflow/02-vm-lifecycle.md) — Control WS 保活机制
- [代理架构实现](../07-proxy/01-architecture.md) — 代理层的代码实现