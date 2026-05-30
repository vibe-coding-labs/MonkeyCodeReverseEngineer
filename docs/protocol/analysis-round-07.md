# 逆向分析轮次 07 — 测试验证

> **时间:** 2026-05-30 02:10 UTC+8
> **聚焦:** 测试脚本、验证准备

---

## 1. 测试脚本创建

### 1.1 测试覆盖范围

创建了 `proxy/test-proxy.sh` 测试脚本，覆盖以下功能：

| 测试项 | 说明 | 预期结果 |
|--------|------|---------|
| 健康检查 | `GET /health` | 200 + `{"status":"ok"}` |
| 模型列表 | `GET /v1/models` | 200 + 模型数组 |
| Chat (非流式) | `POST /v1/chat/completions` | 200 + 完整响应 |
| Chat (流式) | `POST /v1/chat/completions` + stream | SSE 流 |
| Responses API | `POST /v1/responses` + stream | SSE 流 |
| 多轮对话 | 两轮对话测试 | conversation_id + 上下文保持 |
| 错误处理 | 无效模型、空消息 | 404、400 |

### 1.2 测试脚本功能

```bash
# 运行测试
./test-proxy.sh [BASE_URL]

# 示例
./test-proxy.sh http://localhost:9090
```

**特性**：
- 彩色输出（绿色通过，红色失败）
- 详细错误信息
- 自动统计通过/失败数
- 退出码（0=全部通过，1=有失败）

---

## 2. 测试项详解

### 2.1 健康检查测试

```bash
curl -s http://localhost:9090/health
```

**预期响应**：
```json
{
  "status": "ok",
  "uptime": 123.456,
  "pool": {"mode": "single"}
}
```

### 2.2 模型列表测试

```bash
curl -s http://localhost:9090/v1/models
```

**预期响应**：
```json
{
  "object": "list",
  "data": [
    {
      "id": "monkeycode/OpenAI/gpt-4o",
      "object": "model",
      "created": 1715299200,
      "owned_by": "OpenAI"
    }
  ]
}
```

### 2.3 Chat Completions 测试

**非流式**：
```bash
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "Say hello"}],
    "stream": false
  }'
```

**预期响应**：
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello!"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
}
```

**流式**：
```bash
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "Say hello"}],
    "stream": true
  }'
```

**预期响应**：
```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### 2.4 Responses API 测试

```bash
curl -X POST http://localhost:9090/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "input": [{"role": "user", "content": "Say hello"}],
    "stream": true
  }'
```

**预期响应**：
```
event: response.created
data: {"type":"response.created","response":{"id":"resp-xxx","status":"in_progress"},...}

event: response.output_text.delta
data: {"type":"response.output_text.delta","delta":{"text":"Hello"},...}

event: response.completed
data: {"type":"response.completed","response":{"status":"completed","usage":{...}},...}
```

### 2.5 多轮对话测试

**第一轮**：
```bash
curl -D - -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "Remember the number 42"}],
    "stream": false
  }'
```

**预期**：响应头包含 `X-Conversation-Id: conv-xxx`

**第二轮**：
```bash
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "What number did I ask you to remember?"}],
    "conversation_id": "conv-xxx",
    "stream": false
  }'
```

**预期**：响应包含 "42"（Agent 保持上下文）

---

## 3. 测试环境准备

### 3.1 启动代理

```bash
# 开发模式
cd proxy
npm run dev

# 生产模式
npm run build
npm start
```

### 3.2 环境变量

```bash
# 必需
export MONKEYCODE_SESSION_COOKIE="your-session-cookie"
export MONKEYCODE_IMAGE_ID="your-image-id"

# 可选
export MONKEYCODE_BASE_URL="https://monkeycode-ai.com"
export PROXY_PORT=9090
export MONKEYCODE_LOGIN_MODE="user"
```

### 3.3 运行测试

```bash
# 运行测试脚本
./test-proxy.sh http://localhost:9090

# 或手动测试
curl http://localhost:9090/health
curl http://localhost:9090/v1/models
```

---

## 4. 预期问题与解决方案

### 4.1 连接问题

**问题**：无法连接到 MonkeyCode 后端

**解决方案**：
- 检查 `MONKEYCODE_BASE_URL` 是否正确
- 检查网络连接
- 检查 Session Cookie 是否有效

### 4.2 认证问题

**问题**：401 Unauthorized

**解决方案**：
- 检查 `MONKEYCODE_SESSION_COOKIE` 是否正确
- 检查 Session 是否过期
- 重新登录获取新的 Session Cookie

### 4.3 模型问题

**问题**：找不到模型

**解决方案**：
- 检查 `MONKEYCODE_IMAGE_ID` 是否正确
- 检查账号是否有可用模型
- 使用 `/v1/models` 查看可用模型列表

### 4.4 任务创建失败

**问题**：无法创建任务

**解决方案**：
- 检查 `MONKEYCODE_IMAGE_ID` 是否正确
- 检查账号是否有权限创建任务
- 检查 VM 配额是否已满

---

## 5. 下轮分析重点

### 优先级 P0

1. **运行测试脚本**: 验证所有功能
2. **修复测试失败**: 处理发现的问题
3. **性能测试**: 测量响应时间

### 优先级 P1

4. **多轮对话验证**: 确认 Agent 上下文保持
5. **错误处理测试**: 测试各种异常情况
6. **并发测试**: 测试多客户端同时访问

### 优先级 P2

7. **压力测试**: 高并发场景
8. **稳定性测试**: 长时间运行
9. **内存泄漏检查**: 监控内存使用

---

## 6. 产出文件

- `proxy/test-proxy.sh` — 测试脚本 (新建)
- `docs/protocol/analysis-round-07.md` — 本报告

---

## 7. 相关文件索引

| 文件 | 用途 |
|------|------|
| `proxy/test-proxy.sh` | 测试脚本 |
| `proxy/src/server.ts` | 服务器入口 |
| `proxy/src/api-routes.ts` | API 路由 |
| `proxy/src/conversation-manager.ts` | 对话管理器 |
