---
description: 代码展品全集 — 全书 60+ 代码示例统一索引，含 Go/TS/Python/HTTP/WS 五类
protocol_version: general
confidence: high
last_verified: 2026-06-28
---

# 代码展品全集

> **覆盖范围:** 全书逆向分析代码示例统一索引
> **格式:** `Exhibit-ID` — 文件 — 行号 — 说明

## Go 源码展品 (G-1 ~ G-19)

| ID | 文件 | 说明 |
|----|------|------|
| G-1 | `pkg/session/session.go:55-70` | Session Save — Redis Hash + Lookup Key 双结构 |
| G-2 | `pkg/session/session.go:85-95` | Cookie 属性 — Secure/HttpOnly/SameSite/MaxAge 30 天 |
| G-3 | `middleware/auth.go:25-45` | Auth 中间件 — Cookie→Lookup→Hash 三跳查找 |
| G-4 | `pkg/crypto/bcrypt.go:22-24` | bcrypt 密码验证 — CompareHashAndPassword |
| G-5 | `domain/user.go:85-95` | User 结构体 — 无 Balance 字段 |
| G-6 | `domain/user.go:103-108` | SubscriptionResp — 订阅响应结构体 |
| G-7 | `subscription/handler/v1/subscription.go:38-47` | 订阅端点 — 固定返回 pro 计划 |
| G-8 | `captcha.go:30-50` | 验证码创建 — CAP.js 验证逻辑 |
| G-9 | `pkg/llm/client.go:15-30` | LLM Client — 3 种 SDK 选择逻辑 |
| G-10 | `domain/model.go:55-65` | 模型定义 — AllowedPlans 访问控制 |
| G-11 | `pkg/taskflow/vm.go:40-60` | NPM 包选择 — interface_type 映射 |
| G-12 | `pkg/taskflow/vm.go:70-85` | VM 环境变量注入 — API Key、MCP_URL |
| G-13 | `internal/taskflow/vm.go:20-35` | CreateVirtualMachineReq — 12 字段请求体 |
| G-14 | `domain/team_policy.go:15-25` | TeamPolicy — 并发限制 3 + Cores=2/Memory=8GB |
| G-15 | `pkg/doubao/doubao.go:57-65` | 音频元数据 — PCM S16LE 16kHz mono |
| G-16 | `pkg/doubao/type.go:5-12` | audioMeta 结构体 — 音频编码参数 |
| G-17 | `pkg/taskflow/vm.go:90-105` | TaskChunk — TaskLive 通信数据单元 |
| G-18 | `pkg/taskflow/vm.go` | cli_name 枚举 — codex/claude/MCAIReview/opencode |
| G-19 | `domain/team_policy.go:12` | defaultTaskConcurrencyLimit = 3 |

## TypeScript 展品 (TS-1 ~ TS-15)

| ID | 文件 | 说明 |
|----|------|------|
| TS-1 | `server.ts:1-55` | Express 服务器初始化 — 中间件链 |
| TS-2 | `api-routes.ts:1-30` | OpenAI 兼容路由 — chat/responses/models |
| TS-3 | `api-routes.ts:60-100` | 非流式 Chat — ACP 事件累积组装 |
| TS-4 | `api-routes.ts:110-160` | Responses API ACP 转换 — SSE event mapping |
| TS-5 | `task-runner.ts:40-90` | ACP→Chat SSE 转换 — delta.content |
| TS-6 | `task-runner.ts:120-160` | mode=attach 复用 — 已有任务 WS 流 |
| TS-7 | `conversation-manager.ts:15-80` | Conversation 接口 — 状态管理/30min 超时 |
| TS-8 | `conversation-manager.ts:90-130` | createConversation — 任务+WS 连接 |
| TS-9 | `auth.ts:20-60` | 3 种登录模式 — Cookie Session 管理 |
| TS-10 | `models.ts:15-40` | 模型 ID 解析 — monkeycode/Provider/Model |
| TS-11 | `account-pool.ts:30-70` | 账号轮转 — 健康检查 + 错误隔离 |
| TS-12 | `admin-login.ts:10-50` | 6 步 OAuth 自动化 — 百智云登录 |
| TS-13 | `admin-login.ts:100-140` | 代理暴露的管理端点 |
| TS-14 | `browser-headers.ts:1-30` | 3 组 Chrome 148 头伪装函数 |
| TS-15 | `types.ts:1-40` | 类型定义 — 全部 TS 接口 |

## Python 验证展品 (PY-1 ~ PY-13)

| ID | 文件 | 说明 |
|----|------|------|
| PY-1 | `mvp/auth.py:160` | 登录流程 — password-login + captcha |
| PY-2 | `mvp/auth.py:240` | Session 保活检测 — Status 端点 |
| PY-3 | `mvp/chat.py:1-134` | WebSocket 聊天 — ACP 事件接收 |
| PY-4 | `mvp/client.py:45` | 统一客户端 — API 调用封装 |
| PY-5 | `mvp/models.py:1-95` | 模型列表获取 + 缓存 |
| PY-6 | `mvp/proxy_real.py:1-873` | 真实代理 — OpenAI 兼容端点 |
| PY-7 | `mvp/test_auth.py:1-498` | 14 个认证测试用例 |
| PY-8 | `mvp/test_protocol.py:1-268` | 协议验证 — WS/ACP 事件 |
| PY-9 | `mvp/verify_full_flow.py:1-471` | 端到端验证 — 登录→任务→输出 |
| PY-10 | `mvp/oauth_login.py:120-180` | Playwright OAuth 自动化 |
| PY-11 | `mvp/oauth_http.py:1-372` | HTTP OAuth 授权流程 |
| PY-12 | `mvp/client.py:300-350` | WebSocket 流 — 自动审批 + 自动回复 |
| PY-13 | `mvp/client.py:400-450` | Task 创建 — resource/repo/cli_name |

## HTTP 请求/响应展品 (H-1 ~ H-17)

| ID | 端点 | 说明 |
|----|------|------|
| H-1 | `POST /users/password-login` | 密码登录 |
| H-2 | `GET /users/login` | OAuth 跳转 302 |
| H-3 | `POST /users/session` | 设置 Session Cookie |
| H-4 | `GET /users/status` | Session 有效性检查 |
| H-5 | `POST /public/captcha/challenge` | 验证码 challenge |
| H-6 | `POST /public/captcha/redeem` | 验证码兑换 |
| H-7 | `POST /users/tasks` | 创建任务 |
| H-8 | `WS /users/tasks/stream?mode=new` | Task Stream |
| H-9 | `WS /users/tasks/control` | Task Control |
| H-10 | `PUT /users/tasks/stop` | 停止任务 |
| H-11 | `GET /users/models` | 模型列表 |
| H-12 | `GET /users/subscription` | 当前订阅 |
| H-13 | `GET/POST /users/conversations` | 对话 CRUD |
| H-14 | `WS /hosts/vms/{vmId}/terminals/connect` | Terminal WS |
| H-15 | `POST /users/tasks/speech-to-text` | 语音转文字 |
| H-16 | `PUT /users/passwords` | 修改密码 |
| H-17 | `PUT /users/passwords/reset` | 重置密码 |

## WebSocket 帧展品 (W-1 ~ W-13)

```json
// W-1: agent_message_chunk — Agent 输出文本
{"type":"agent_message_chunk","text":"Hello World"}

// W-2: agent_thought_chunk — 思考过程
{"type":"agent_thought_chunk","text":"思考中..."}

// W-3: tool_call — 工具调用开始
{"type":"tool_call","tool_name":"read_file","tool_input":"/etc/passwd"}

// W-4: tool_call_update — 工具调用状态
{"type":"tool_call_update","status":"running","delta":"partial_result"}

// W-5: usage_update — Token 用量
{"type":"usage_update","input_tokens":100,"output_tokens":50}

// W-6: plan — 执行计划
{"type":"plan","steps":[{"action":"analyze","status":"completed"}]}

// W-7: task-ended — 任务完成
{"type":"task-ended"}

// W-8: task-error — 任务错误
{"type":"task-error","data":"Error message"}

// W-9: user-input — 用户输入
{"type":"user-input","data":"请帮我写代码"}

// W-10: ping/pong — 心跳
{"type":"ping"}  // 回复 {"type":"ping"}

// W-11: auto-approve — 自动审批
{"type":"auto-approve"}

// W-12: reply-question — 自动回复提问
{"type":"reply-question","data":"{\"request_id\":\"xxx\",\"answers_json\":\"\",\"cancelled\":false}"}

// W-13: Terminal binary — PTY 数据帧（二进制 UTF-8）
```

---

## 展品交叉引用关系

```
Go 源码 (G-1~19) ←── 后端架构层
    ↓
TypeScript 代理 (TS-1~15) ←── 代理网关层
    ↓ 验证
Python MVP (PY-1~13) ←── 协议验证层
    ↓ 展示
HTTP 请求/响应 (H-1~17) ←── 网络协议层
    ↓ 帧级核对
WebSocket 帧 (W-1~13) ←── 实时通信层
```

## 精选代码示例

### Go: Redis Session 双结构

```go
// G-1: session.go — Session Save
func (s *SessionStore) Save(ctx context.Context, session *Session) error {
    pipe := s.redis.Pipeline()
    // Lookup Key: session_id → user_id
    pipe.Set(ctx, "session_lookup:"+session.ID, session.UserID, session.TTL)
    // Hash Key: user_id → session data
    pipe.HSet(ctx, "session_hash:"+session.UserID, session.ID, session.Data)
    pipe.Expire(ctx, "session_hash:"+session.UserID, session.TTL)
    _, err := pipe.Exec(ctx)
    return err
}
```

### TypeScript: 模型 6 层解析

```typescript
// TS-10: models.ts — 6 层回退解析
async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
  const models = await this.fetchModels()
  // 第1层: 精确匹配 monkeycode/provider/model
  const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
  if (exact) return exact
  // 第2-5层: provider/model → model → display_name → default
  // 第6层: 回退 models[0]
  return models[0] || null
}
```

### Python: WebSocket 流接收

```python
# PY-3: chat.py — ACP 事件接收循环
def stream_task(self, task_id, prompt):
    ws = websocket.WebSocket()
    ws.connect(f"wss://api/{task_id}?mode=new")
    ws.send(json.dumps({"type": "auto-approve"}))
    ws.send(json.dumps({"type": "user-input", "data": prompt}))
    while True:
        msg = json.loads(ws.recv())
        if msg["type"] == "task-ended": break
        if msg["type"] == "task-running" and msg.get("kind") == "acp_event":
            yield json.loads(msg["data"])
```

### HTTP: Chat Completion 请求

```http
# H-7: POST /api/v1/users/tasks
POST /api/v1/users/tasks HTTP/1.1
Cookie: monkeycode_ai_session=uuid
Content-Type: application/json

{"content":"Hello","host_id":"public_host","image_id":"uuid",
 "model_id":"uuid","cli_name":"opencode",
 "resource":{"core":1,"memory":1073741824,"life":3600}}
```

### WS: ACP 事件完整流

```json
// W-1~W-7: 完整 ACP 事件序列
← {"type":"task-started"}
← {"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_thought_chunk\",\"text\":\"思考中...\"}"}
← {"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_message_chunk\",\"text\":\"你好\"}"}
← {"type":"task-running","kind":"acp_event","data":"{\"type\":\"tool_call\",\"tool_name\":\"bash\"}"}
← {"type":"task-running","kind":"acp_event","data":"{\"type\":\"usage_update\",\"total_tokens\":150}"}
← {"type":"task-ended"}
```

---

## 代码展品详解

### Go: Auth 中间件 — Cookie → Lookup → Hash 三跳查找

```go
// G-3: middleware/auth.go — 认证中间件核心逻辑
func AuthMiddleware(c *gin.Context) {
    cookie, err := c.Cookie("monkeycode_ai_session")
    if err != nil {
        c.AbortWithStatusJSON(401, gin.H{"error": "no session cookie"})
        return
    }

    // 第一跳: Cookie → session_id (直接从请求头提取)
    sessionID := cookie

    // 第二跳: session_lookup:{sessionID} → userID (Redis Lookup Key)
    userID, err := redis.Get(ctx, "session_lookup:"+sessionID).Result()
    if err != nil {
        c.AbortWithStatusJSON(401, gin.H{"error": "session not found"})
        return
    }

    // 第三跳: session_hash:{userID} → session data (Redis Hash Key)
    sessionData, err := redis.HGet(ctx, "session_hash:"+userID, sessionID).Result()
    if err != nil {
        c.AbortWithStatusJSON(401, gin.H{"error": "session data not found"})
        return
    }

    c.Set("user_id", userID)
    c.Set("session_data", sessionData)
    c.Next()
}
```

### TypeScript: WebSocket 流式连接 — 完整实现

```typescript
// TS-5: task-runner.ts — WebSocket 流式连接完整逻辑
async streamTask(
  taskId: string,
  prompt: string,
  onChunk: (chunk: OpenAIChatCompletionChunk) => void,
  signal?: AbortSignal,
  authOverride?: AuthManager
): Promise<void> {
  const auth = authOverride || this.auth
  return new Promise((resolve, reject) => {
    const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
    const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${taskId}&mode=new`

    const ws = new WebSocket(wsUrl, {
      headers: wsHeaders("monkeycode-ai.com",
        `${auth.getSessionCookieName()}=${auth.getSessionCookieSync()}`),
    })

    let resolved = false
    let accumulatedUsage = { input_tokens: 0, output_tokens: 0, total_tokens: 0 }

    ws.on("open", () => {
      ws.send(JSON.stringify({ type: "auto-approve" }))
      ws.send(JSON.stringify({ type: "user-input", data: prompt }))
    })

    ws.on("message", (raw: WebSocket.Data) => {
      const msg: TaskStreamMessage = JSON.parse(raw.toString())
      if (msg.type === "ping") {
        ws.send(JSON.stringify({ type: "ping" }))
        return
      }
      this.handleStreamMessage(msg, taskId, onChunk, accumulatedUsage, ws)
    })

    ws.on("close", () => { if (!resolved) { resolved = true; resolve() } })
    ws.on("error", (err) => { if (!resolved) { resolved = true; reject(err) } })

    // 1 小时超时保护
    setTimeout(() => {
      if (!resolved) { cleanup(); resolve() }
    }, TASK_TIMEOUT_MS)
  })
}
```

### TypeScript: 账号池错误隔离 — 5 种错误码处理

```typescript
// TS-11: account-pool.ts — 错误码分发 + 账号状态管理
// 账号状态机: CREATED → ACTIVE → EXPIRED/INVALID
type AccountStatus = "CREATED" | "ACTIVE" | "EXPIRED" | "INVALID"

interface AccountEntry {
  email: string
  status: AccountStatus
  auth: AuthManager
  errorCount: number
  lockedByWs: boolean
  lockedAt: number | null
}

// 5 种错误码处理
handleError(auth: AuthManager, errorCode: number): boolean {
  switch (errorCode) {
    case 40100: // 会话无效 → 可重试（切换账号）
      entry.status = "EXPIRED"
      this.loginAccount(entry).catch(() => {})
      return true
    case 40300: // 权限不足 → 不可重试
      return false
    case 40002: case 40003: case 40004:
      // 密码错误 / 封号 / 未激活 → 标记 INVALID
      entry.status = "INVALID"
      return false
    case 50000: // 服务端错误 → 可重试
      return true
    default:
      return false
  }
}

// 3 次登录失败 → 永久锁定
private async loginAccount(entry: AccountEntry): Promise<void> {
  try {
    await entry.auth.login()
    entry.status = "ACTIVE"
    entry.errorCount = 0
  } catch {
    entry.errorCount++
    if (entry.errorCount >= 3) {
      entry.status = "INVALID"
    }
  }
}
```

### TypeScript: OAuth HTTP 6 步自动化 — 完整流程

```typescript
// TS-12: admin-login.ts — 6 步 OAuth 自动化
// Step 1: 获取 OAuth 参数 (state/clientId/redirectUri)
export async function startOAuthLogin() {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/login`, {
    headers: mkHeaders(), redirect: "manual",
  })
  const location = resp.headers.get("Location") || ""
  const url = new URL(location)
  return {
    state: url.searchParams.get("state") || "",
    clientId: url.searchParams.get("client_id") || "",
    redirectUri: url.searchParams.get("redirect_uri") || "",
  }
}

// Step 2: 获取 SCaptcha 验证码 Token
export async function getSCaptchaToken(): Promise<string> {
  const resp = await fetch(`${SCAPTCHA_API}/v1/api/challenge`, {
    method: "POST",
    headers: scHeaders(),
    body: JSON.stringify({ business_id: SCAPTCHA_BUSINESS_ID }),
  })
  const data = await resp.json()
  return data.data?.token || ""
}

// Step 3-6: 完整登录（调用方视角）
export async function completeLogin(smsCode: string) {
  // Step 3: 百智云手机号登录
  const loginResult = await baizhiPhoneLogin(session.phone, smsCode)
  // Step 4: OAuth authorize → code
  const { callbackUrl } = await baizhiOAuthAuthorize(...)
  // Step 5: 回调 → session cookie
  const sessionCookie = await monkeycodeCallback(callbackUrl)
  // Step 6: 自动发现 image_id + 模型列表
  const imageResult = await discoverImageId(sessionCookie)
  return { sessionCookie, imageId: imageResult?.imageId }
}
```

### TypeScript: Conversation Manager 多轮对话

```typescript
// TS-7/8: conversation-manager.ts — 多轮对话核心逻辑
class ConversationManager {
  private conversations: Map<string, Conversation> = new Map()

  // 创建对话 (关联到已有任务)
  create(taskId: string, model: MonkeyCodeModel, auth: AuthManager, messages: OpenAIMessage[]) {
    const id = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const conversation: Conversation = {
      id, taskId, model, auth, ws: null,
      messages: [...messages],
      lastUsedAt: Date.now(), createdAt: Date.now(),
      onChunk: null, resolvePromise: null, rejectPromise: null,
    }
    this.conversations.set(id, conversation)
    return conversation
  }

  // 连接模式=attach 复用 WebSocket
  async connectToTask(conversation: Conversation, onChunk) {
    const wsBaseUrl = httpToWs(MONKEYCODE_BASE_URL)
    const wsUrl = `${wsBaseUrl}/api/v1/users/tasks/stream?id=${conversation.taskId}&mode=attach`

    const ws = new WebSocket(wsUrl, {
      headers: wsHeaders("monkeycode-ai.com",
        `${conversation.auth.getSessionCookieName()}=${conversation.auth.getSessionCookieSync()}`),
    })

    // 30 秒连接超时
    setTimeout(() => cleanup(), 30000)
  }

  // 发送新用户输入到已有 WS 连接
  sendUserInput(conversation: Conversation, content: string): void {
    conversation.ws?.send(JSON.stringify({ type: "user-input", data: content }))
    conversation.lastUsedAt = Date.now()
  }

  // 定期清理 30 分钟不活跃的对话
  private cleanup(): void {
    for (const [id, conv] of this.conversations) {
      if (Date.now() - conv.lastUsedAt > this.conversationTimeoutMs) {
        this.delete(id)
      }
    }
  }
}
```

### TypeScript: 浏览器指纹伪装 — 5 种请求头

```typescript
// TS-14: browser-headers.ts — Chrome 148 精确模拟
const BASE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

function merge(domain: string, extra = {}) {
  return {
    "User-Agent": BASE_UA,
    "Sec-Ch-Ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Origin": `https://${domain}`,
    "Referer": `https://${domain}/`,
    ...extra,
  }
}

// MonkeyCode API
export function mkHeaders(extra = {}) { return merge("monkeycode-ai.com", extra) }
// 百智云 API
export function bzHeaders(extra = {}) { return merge("baizhi.cloud", extra) }
// SCaptcha 验证码
export function scHeaders(extra = {}) {
  return { "User-Agent": BASE_UA, "Origin": "https://monkeycode-ai.com", "Referer": "https://monkeycode-ai.com/", ...extra }
}
// 页面导航（模拟浏览器跳转）
export function navHeaders(domain: string, extra = {}) {
  return { "User-Agent": BASE_UA, "Accept": "text/html,...", "Sec-Fetch-Mode": "navigate", ...extra }
}
// WebSocket
export function wsHeaders(domain: string, cookie: string) {
  return { "User-Agent": BASE_UA, "Origin": `https://${domain}`, "Cookie": cookie, "Sec-WebSocket-Version": "13" }
}
```

### Python: 统一客户端 — 登录 + 模型 + 任务 + WS 流

```python
# PY-4: client.py — MonkeyCode 统一客户端
class MonkeyCodeClient:
    def __init__(self, session_cookie=None, username=None, password=None, image_id=None):
        self.session_cookie = session_cookie
        self.image_id = image_id
        self.base_url = "https://monkeycode-ai.com"

    # 密码登录
    def login(self, captcha_token=None):
        body = {"email": self.username, "password": self.password}
        if captcha_token:
            body["captcha_token"] = captcha_token
        resp = requests.post(f"{self.base_url}/api/v1/users/password-login",
                           json=body, allow_redirects=False)
        cookie = resp.headers.get("Set-Cookie", "")
        self.session_cookie = re.search(r"monkeycode_ai_session=([^;]+)", cookie).group(1)

    # 创建任务
    def create_task(self, model_id, prompt, image_id=None):
        resp = requests.post(f"{self.base_url}/api/v1/users/tasks",
            headers={"Cookie": f"monkeycode_ai_session={self.session_cookie}"},
            json={
                "content": prompt,
                "image_id": image_id or self.image_id,
                "model_id": model_id,
                "host_id": "public_host",
                "cli_name": "opencode",
                "resource": {"core": 1, "memory": 1073741824, "life": 3600},
            })
        return resp.json()["data"]["id"]

    # WebSocket 流式接收 ACP 事件
    def stream_task(self, task_id, prompt):
        ws = websocket.WebSocket()
        ws.connect(f"wss://monkeycode-ai.com/api/v1/users/tasks/stream?id={task_id}&mode=new",
                   header={"Cookie": f"monkeycode_ai_session={self.session_cookie}"})
        ws.send(json.dumps({"type": "auto-approve"}))
        ws.send(json.dumps({"type": "user-input", "data": prompt}))
        while True:
            msg = json.loads(ws.recv())
            if msg["type"] == "ping":
                ws.send(json.dumps({"type": "ping"}))
                continue
            if msg["type"] == "task-ended":
                break
            if msg["type"] == "task-running" and msg.get("kind") == "acp_event":
                yield json.loads(msg["data"])
```

### HTTP: Chat Completion 请求/响应完整示例

```http
# 请求: POST /v1/chat/completions (通过代理)
POST /v1/chat/completions HTTP/1.1
Host: localhost:9090
Content-Type: application/json
Authorization: Bearer any-key-works

{
  "model": "monkeycode/openai/gpt-4o",
  "messages": [
    {"role": "system", "content": "你是一个编程助手"},
    {"role": "user", "content": "用 Python 写一个二分查找"}
  ],
  "stream": true,
  "conversation_id": "conv-1718245800000-a1b2c3d4"
}

# 流式响应 (SSE)
data: {"id":"chatcmpl-task-uuid","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"我来帮你写"},"finish_reason":null}]}
data: {"id":"chatcmpl-task-uuid","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"二分查找"},"finish_reason":null}]}
data: {"id":"chatcmpl-task-uuid","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":200,"total_tokens":300}}
data: [DONE]

# 非流式响应
{
  "id": "chatcmpl-task-uuid",
  "object": "chat.completion",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "二分查找代码如下..."}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}
}
```

### HTTP: Responses API 流式响应

```http
POST /v1/responses HTTP/1.1
Host: localhost:9090
Content-Type: application/json

{
  "model": "monkeycode/anthropic/claude-3-opus-20240229",
  "input": "解释递归的工作原理",
  "max_output_tokens": 1000
}

# SSE 流式 (Responses API 格式)
event: response.created
data: {"type":"response.created","response":{"id":"resp-task-uuid","status":"in_progress"}}

event: response.output_item.added
data: {"type":"response.output_item.added","output_index":0,"item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":""}]}}

event: response.output_text.delta
data: {"type":"response.output_text.delta","delta":{"type":"output_text.delta","text":"递归是一种..."}}

event: response.output_text.delta
data: {"type":"response.output_text.delta","delta":{"type":"output_text.delta","text":"编程技巧..."}}

event: response.completed
data: {"type":"response.completed","response":{"id":"resp-task-uuid","status":"completed","usage":{"input_tokens":50,"output_tokens":150,"total_tokens":200}}}
```

### HTTP: 管理端点使用示例

```bash
# 健康检查
curl http://localhost:9090/health
# {"status":"ok","uptime":1234.56,"pool":{"mode":"single"}}

# 设置 Session Cookie (手动从浏览器提取)
curl -X POST http://localhost:9090/admin/session \
  -H "Content-Type: text/plain" \
  -d "your-session-cookie-value"

# 查看号池状态
curl http://localhost:9090/admin/pool/status
# {"mode":"pool","total":5,"active":4,"expired":1,"invalid":0,"locked":1}

# OAuth 自动化: 发送短信
curl -X POST http://localhost:9090/admin/login/send-code \
  -H "Content-Type: application/json" \
  -d '{"phone":"13800138000"}'

# OAuth 自动化: 验证码
curl -X POST http://localhost:9090/admin/login/verify \
  -H "Content-Type: application/json" \
  -d '{"code":"123456"}'

# 自动发现 image_id 和模型
curl http://localhost:9090/admin/discover

# 刷新模型缓存
curl -X POST http://localhost:9090/admin/refresh-models
