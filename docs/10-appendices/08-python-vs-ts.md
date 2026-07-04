---
description: MonkeyCode Python MVP 与 TypeScript 代理的实现差异分析 — 双实现对比
protocol_version: based on mvp/*.py (4,854 行) vs proxy/src/*.ts (3,031 行)
confidence: high
last_verified: 2026-06-28
---

# Python MVP vs TypeScript 代理实现差异分析

## 1. 项目定位差异

| 维度 | Python MVP | TypeScript Proxy |
|------|-----------|-----------------|
| 定位 | 协议验证工具 | 生产级反向代理 |
| 语言 | Python 3 | TypeScript 5 |
| HTTP 框架 | `http.server.HTTPServer` | Express 4 |
| WS 库 | `websocket-client` (thread-based) | `ws` (async event-based) |
| 典型部署 | 测试环境 `python3 proxy_real.py` | 生产环境 `node dist/server.js` |
| 启动依赖 | `MonkeyCodeClient` 单例 | `AuthManager` + 号池全功能 |

## 2. 服务器架构对比

### Python MVP — 基于线程的 http.server

```python
# mvp/proxy_real.py — HTTP 服务器
class RealProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 每次请求独立线程处理
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        req = json.loads(body)

        if path == "/v1/chat/completions":
            self._handle_chat_completions(req)

    def _handle_stream_response(self, task_id, prompt, model, chat_id, client):
        # 线程内用回调函数处理 ACP 事件
        def on_acp_event(acp: dict):
            text = acp.get("text") or acp.get("content") or ""
            self._send_sse({
                "id": chat_id,
                "choices": [{"delta": {"content": text}}],
            })

        client.connect_task_stream(task_id, prompt,
            on_acp_event=on_acp_event,
            on_task_ended=on_task_ended)
```

### TypeScript Proxy — 基于 Express 中间件

```typescript
// proxy/src/server.ts — Express 服务器
const app = express()
app.use(cors())  // 全局 CORS
app.use(express.json({ limit: "10mb" }))  // JSON 解析中间件
app.use(createAPIRouter(modelManager, taskRunner, accountPool, conversationManager))

// proxy/src/api-routes.ts — Express 路由
router.post("/v1/chat/completions", async (req, res) => {
  try {
    const model = await modelManager.resolveModel(body.model)
    const taskId = await taskRunner.createTask(model, prompt, { systemPrompt })
    // 流式或非流式处理
    await handleStreamResponse(res, taskRunner, taskId, model, prompt, pool, auth)
  } catch (err: any) {
    if (!res.headersSent) {
      res.status(500).json({ error: { message: err.message, type: "internal_error" } })
    }
  }
})
```

**架构差异：**
- Python: `BaseHTTPRequestHandler` 是同步的，多请求靠线程池
- TypeScript: Express 是异步事件驱动的，一个进程处理所有请求
- Python 的 `send_header` 和 `end_headers` 需要手动管理
- TypeScript 的 `res.json()` / `res.status()` 自动处理

## 3. WebSocket 连接模型对比

### Python — 线程阻塞模型

```python
# mvp/client.py — WS 连接
def connect_task_stream(self, task_id, prompt, ...):
    self._ws = websocket.WebSocketApp(ws_url, ...)

    self._ws_thread = threading.Thread(
        target=self._ws.run_forever, daemon=True
    )
    self._ws_thread.start()

    # 主线程阻塞等待完成
    done_event.wait(timeout=timeout_s)
    self.close_stream()
    return result  # 同步阻塞直到任务完成
```

### TypeScript — 异步事件模型

```typescript
// proxy/src/task-runner.ts — WS 连接
async streamTask(taskId, prompt, onChunk, signal, authOverride): Promise<void> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl, { headers })

    ws.on("open", () => {
      ws.send(JSON.stringify({ type: "auto-approve" }))
      ws.send(JSON.stringify({ type: "user-input", data: prompt }))
    })

    ws.on("message", (raw) => {
      this.handleStreamMessage(msg, taskId, onChunk, accumulatedUsage, ws)
    })

    ws.on("close", () => { if (!resolved) { resolved = true; resolve() } })
    ws.on("error", (err) => { if (!resolved) { resolved = true; reject(err) } })
  })
}
```

| 特性 | Python | TypeScript |
|------|--------|-----------|
| WS 事件循环 | `run_forever()` 在独立线程 | 主事件循环异步 |
| 阻塞 | `done_event.wait()` 阻塞 | `await streamTask()` 非阻塞 |
| 超时 | `wait(timeout=X)` | `setTimeout(→resolve)` |
| 连接关闭 | `close_stream()` 手动 | `ws.close()` 自动 |
| 多连接 | 多线程管理 | 单线程事件驱动 |

## 4. 用户输入编码差异

### Python — base64 编码用户输入

```python
# mvp/client.py:579-591
def send_user_input(self, text: str):
    payload = json.dumps({"content": text})
    encoded = base64.b64encode(payload.encode()).decode()

    message = json.dumps({
        "type": "user_input",
        "data": {"content": encoded},
    })
    self._ws.send(message)
```

### TypeScript — 直接发送纯文本

```typescript
// proxy/src/task-runner.ts:139-143
const userMsg = {
  type: "user-input",
  data: prompt,  // 纯文本，无 base64 编码
}
ws.send(JSON.stringify(userMsg))
```

**重要差异：** Python MVP 使用了 base64 编码的 `user_input`（带下划线!）消息格式，而 TypeScript 代理使用纯文本的 `user-input`（连字符!）格式。这可能是后端 API 版本兼容问题。

## 5. 模型管理对比

### Python — 每次请求重新获取

```python
# mvp/proxy_real.py:81-103
def fetch_models(client):
    """全局缓存"""
    now = time.time()
    if ProxyState.models_cache and (now - ProxyState.models_cache_time) < 300:
        return ProxyState.models_cache
    # ... 刷新缓存
```

### TypeScript — 按需刷新 + 6 层回退

```typescript
// proxy/src/models.ts:64-90
async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
  const models = await this.fetchModels()  // 自动管理 5 分钟缓存

  // 6 层回退解析
  const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
  if (exact) return exact                    // 1. 精确匹配
  const byProviderModel = models.find(...)   // 2. provider/model
  const byModelName = models.find(...)       // 3. model 名称
  const byDisplayName = models.find(...)     // 4. display_name
  const defaultModel = models.find(...)      // 5. 默认模型
  return models[0] || null                   // 6. 最后回退
}
```

## 6. ACP 事件处理对比

### Python — 回调函数模型

```python
# mvp/proxy_real.py:558-650
def on_acp_event(acp: dict):
    acp_type = acp.get("type", "")

    if acp_type in ("agent_message_chunk", "agent_thought_chunk"):
        text = acp.get("text") or acp.get("content") or ""
        if text:
            # 首次文本时需要发送 output_item.added
            if not text_opened:
                self._send_sse_event("response.output_item.added", ...)
                text_opened = True

            prefix = "[Thinking] " if acp_type == "agent_thought_chunk" else ""
            self._send_sse_event("response.output_text.delta", {
                "delta": {"text": prefix + text},
            })
```

### TypeScript — 类方法模型

```typescript
// proxy/src/task-runner.ts:262-339
private handleACPEvent(acp, chatId, now, onChunk, usage): void {
  switch (acp.type) {
    case "agent_message_chunk": {
      const text = acp.text || acp.content || ""
      if (text) {
        onChunk({
          id: chatId, choices: [{ delta: { content: text } }]
        })
      }
      break
    }
    // ...
  }
}
```

## 7. 错误处理对比

| 场景 | Python | TypeScript |
|------|--------|-----------|
| WS 消息解析失败 | `try/except json.JSONDecodeError: pass` | `catch { }` |
| WS 超时 | `done_event.wait(timeout=X)` | `setTimeout(→resolve)` |
| WS 连接错误 | `on_error → done_event.set()` | `ws.on("error") → reject` |
| HTTP 500 | `self._send_json(500, ...)` | `res.status(500).json(...)` |
| SSE 流结束 | `self._send_sse({"choices": []})` | `sendSSE({object: "done"})` |
| 响应头已发送 | 未检查 | `if (!res.headersSent)` |

## 8. Responses API 实现差异

| ACP → SSE 事件 | Python MVP | TypeScript Proxy |
|---------------|-----------|-----------------|
| `agent_message_chunk` → 首次 | 发送 `output_item.added` + `content_part.added` | 发送 `output_item.added` + `content_part.added` |
| `agent_message_chunk` → delta | `response.output_text.delta` | `response.output_text.delta` |
| `tool_call` | `function_call` 输出项 | `function_call` 输出项 |
| `tool_call_update` → 完成 | `function_call_arguments.done` + `output_item.done` | `function_call_arguments.done` + `output_item.done` |
| 无输出时 | 发送空 message | 发送空 message |
| 错误时 | `response.completed{status:"failed"}` | `response.completed{status:"failed"}` |

**完全一致的映射逻辑** — 说明 Responses API 的事件映射受到同一个协议规范的约束。

## 9. 各自特有的功能

### Python MVP 特有

```python
# 模型分类查询
def get_public_models(self) -> list: ...
def get_free_models(self) -> list: ...
def _is_owner_public(owner) -> bool: ...
```

### TypeScript Proxy 特有

```typescript
// 号池功能
// proxy/src/account-pool.ts
acquireHttp(): AuthManager | null {}  // HTTP 共享模式
acquireWs(): AuthManager | null {}    // WS 独占模式

// 多轮对话
// proxy/src/conversation-manager.ts
create(): Conversation {}  // 创建对话
connectToTask(): void {}   // mode=attach 复用

// 浏览器头伪装
// proxy/src/browser-headers.ts
mkHeaders()     // MonkeyCode API
bzHeaders()     // 百智云 API
navHeaders()    // 页面导航
wsHeaders()     // WebSocket
```

---

## 相关章节

- [代理架构实现](../07-proxy/01-architecture.md) — TypeScript 代理架构
- [代理 ACP→OpenAI 映射](../07-proxy/04-acp-to-openai-mapping.md) — ACP 事件映射
- [错误处理模式](../01-architecture/04-error-handling-patterns.md) — 错误处理差异