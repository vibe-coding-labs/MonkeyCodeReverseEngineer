---
description: MVP Python 验证工具深度分析 — 基于 13 个文件 (4,854 行) 的设计模式与协议验证
protocol_version: based on mvp/*.py 全部 13 文件
confidence: high
last_verified: 2026-06-28
---

# MVP Python 验证工具深度分析

> **源码文件:** `mvp/` 目录全部 13 个 Python 文件 (4,854 行)
> **与 TypeScript 代理对比:** Python MVP 是最初的协议验证实现，TS 代理是其生产级演进
> **核心发现:** Python MVP 揭示了 8 个关键的协议验证细节，其中 3 个在 TS 代理中有不同的实现

## 1. 整体架构

```
mvp/
├── config.py            — 配置常量（BASE_URL, Cookie 名等）
├── auth.py            — MonkeyCodeAuth 类（323 行）
├── client.py          — MonkeyCodeClient 统一客户端（673 行）
├── models.py          — 模型管理（95 行）
├── chat.py            — WebSocket 聊天（133 行）
├── proxy.py           — Mock 代理（占位）
├── proxy_real.py      — 真实任务代理（873 行）
├── oauth_login.py     — Playwright OAuth 自动化（461 行）
├── oauth_http.py      — 纯 HTTP OAuth 自动化（372 行）
├── test_auth.py       — 14 个认证测试（498 行）
├── test_auth_interactive.py — 交互式认证测试
├── test_protocol.py   — 协议验证测试（268 行）
└── verify_full_flow.py — 端到端验证（471 行）
```

### 模块依赖关系

```
config.py（零依赖，纯常量）
   │
   ├── auth.py（依赖 requests）
   │     └── MonkeyCodeAuth：Session Cookie 管理 + 密码登录 + 验证码
   │
   ├── models.py（依赖 requests）
   │     └── 模型列表获取 + ID 解析
   │
   ├── client.py（集成 auth + models + chat）
   │     └── MonkeyCodeClient：统一客户端（673 行核心）
   │           ├── 认证（Session/TTL 管理）
   │           ├── 任务创建（POST /tasks）
   │           ├── WebSocket 流式接收
   │           └── 自动审批 + 自动回复
   │
   ├── chat.py → WebSocket 基础实现
   ├── proxy_real.py → OpenAI 兼容 HTTP 代理（873 行）
   │     └── HTTP Server + SSE 流 + ACP→SSE 转换
   ├── oauth_login.py → Playwright OAuth
   ├── oauth_http.py → 纯 HTTP OAuth
   └── test_auth.py → 14 个测试用例
```

## 2. MonkeyCodeClient 核心分析

### 2.1 构造函数与认证优先级

```python
class MonkeyCodeClient:
    def __init__(self, session_cookie=None, username=None, password=None,
                 image_id=None, host_id=None):
        """认证优先级（高→低）:
        1. session_cookie 参数
        2. 环境变量 MONKEYCODE_SESSION_COOKIE
        3. username + password 参数
        4. 环境变量 MONKEYCODE_USERNAME + MONKEYCODE_PASSWORD
        """
        self.base_url = BASE_URL
        self.session_cookie_name = SESSION_COOKIE_NAME  # "monkeycode_ai_session"
        self.image_id = image_id or os.getenv("MONKEYCODE_IMAGE_ID", "")
        self.host_id = host_id or os.getenv("MONKEYCODE_HOST_ID", DEFAULT_HOST_ID)

        env_cookie = os.getenv("MONKEYCODE_SESSION_COOKIE", "")
        self._session_cookie = session_cookie or env_cookie or ""
        self._username = username or os.getenv("MONKEYCODE_USERNAME", "")
        self._password = password or os.getenv("MONKEYCODE_PASSWORD", "")
        self._captcha_token = os.getenv("MONKEYCODE_CAPTCHA_TOKEN", "")
```

### 2.2 Session TTL 追踪

Python MVP 明确追踪了 30 天 TTL——这是 TS 代理中没有独立暴露的功能：

```python
# auth.py — Session TTL 管理
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 天硬限制

class MonkeyCodeAuth:
    def __init__(self):
        self._cookie_set_time = 0

    def get_session_remaining_seconds(self) -> float:
        return max(0.0, SESSION_TTL_SECONDS - self.get_session_age_seconds())

    def is_session_expired(self) -> bool:
        if not self.session_cookie:
            return True
        return self.get_session_age_seconds() >= SESSION_TTL_SECONDS

    def get_session_ttl_info(self) -> dict:
        return {
            "age_days": int(self.get_session_age_seconds() / 86400),
            "remaining_days": int(self.get_session_remaining_seconds() / 86400),
            "is_expired": self.is_session_expired(),
            "max_ttl_days": 30,
        }
```

### 2.3 任务创建（对比 TS 代理）

```python
# client.py — 任务创建（Python 使用 requests，TS 使用 fetch）
def create_task(self, content: str, model_id: str, cli_name: str = "opencode",
                host_id: str = None, image_id: str = None,
                system_prompt: str = None, repo: dict = None) -> dict:
    url = f"{self.base_url}/api/v1/users/tasks"
    body = {
        "content": content,
        "host_id": host_id or self.host_id,
        "image_id": image_id or self.image_id,
        "model_id": model_id,
        "cli_name": cli_name,
        "resource": {"core": 1, "memory": 1073741824, "life": 3600},
        "repo": repo or {"repo_url": "", "branch": "master",
                         "repo_filename": "", "zip_url": ""},
    }
    if system_prompt:
        body["system_prompt"] = system_prompt

    resp = requests.post(url, json=body, headers=self.get_auth_headers(), timeout=30)
    data = resp.json()
    return data.get("data", data)
```

### 2.4 WebSocket 流式接收

```python
# client.py — WebSocket 流（Python 使用 websocket-client）
def stream_task(self, task_id: str, prompt: str,
                on_acp_event=None, on_error=None, on_done=None,
                auto_approve=True, auto_reply=True):
    ws_url = f"wss://monkeycode-ai.com/api/v1/users/tasks/stream?id={task_id}&mode=new"
    ws = websocket.WebSocket()
    ws.connect(ws_url, header={"Cookie": f"{self.session_cookie_name}={self._session_cookie}"})

    if auto_approve:
        ws.send(json.dumps({"type": "auto-approve"}))       # 消息 1

    ws.send(json.dumps({"type": "user-input", "data": prompt}))  # 消息 2

    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    while True:
        raw = ws.recv()
        if not raw:
            break
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "ping":
            ws.send(json.dumps({"type": "ping"}))
            continue

        if msg.get("type") == "task-running" and msg.get("kind") == "acp_event":
            acp = json.loads(msg["data"])
            if acp.get("type") == "usage_update":
                usage["input_tokens"] = acp.get("input_tokens", usage["input_tokens"])
                usage["output_tokens"] = acp.get("output_tokens", usage["output_tokens"])
                usage["total_tokens"] = acp.get("total_tokens", usage["total_tokens"])
            if on_acp_event:
                on_acp_event(acp)

        elif msg.get("type") == "task-running" and msg.get("kind") == "acp_ask_user_question":
            if auto_reply:
                ws.send(json.dumps({
                    "type": "reply-question",
                    "data": json.dumps({"answers_json": "", "cancelled": False})
                }))

        elif msg.get("type") == "task-ended":
            if on_done:
                on_done(usage)
            break

        elif msg.get("type") == "task-error":
            if on_error:
                on_error(msg.get("data", ""))
            break

    ws.close()
```

## 3. proxy_real.py 分析（873 行）

### 3.1 架构概览

```
Client (curl/Codex)         proxy_real.py (port 9091)      MonkeyCode Backend
    │ POST /v1/chat/...          │                              │
    ├───────────────────────────►│                              │
    │                            │ RealProxyHandler 处理         │
    │                            ├── parse request body          │
    │                            ├── resolve model               │
    │                            ├── client.create_task()        │
    │                            ├── client.stream_task()        │
    │                            │    → ACP 事件处理器             │
    │                            ├── ACP→SSE 转换                │
    │◄── SSE stream ────────────│                              │
```

### 3.2 Chat Completions 处理（对比 TS）

```python
# proxy_real.py — Chat Completions 处理器（Python 版）
def _handle_chat_completions(self):
    content_length = int(self.headers.get("Content-Length", 0))
    body = json.loads(self.rfile.read(content_length))

    model_id = body.get("model", "")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # 模型解析
    model = resolve_model_from_cache(model_id)
    if not model:
        self._send_json(404, {"error": f"Model '{model_id}' not found"})
        return

    # 提取 system + 用户消息
    prompt = messages_to_prompt(messages)
    system_prompt = None
    for m in messages:
        if m.get("role") == "system":
            system_prompt = m.get("content", "")
            break

    # 创建 MonkeyCode 任务
    client = ProxyState.client
    task = client.create_task(prompt, model["id"], cli_name="opencode",
                               system_prompt=system_prompt)
    task_id = task.get("id") or task.get("task_id")

    if stream:
        self._handle_streaming_response(task_id, prompt, model, client)
    else:
        self._handle_non_streaming_response(task_id, prompt, model, client)
```

### 3.3 ACP → SSE 转换

```python
# proxy_real.py — ACP→Chat Completions 转换
def acp_to_chat_chunk(acp, task_id, usage):
    chat_id = f"chatcmpl-{task_id}"
    now = int(time.time())

    if acp["type"] == "agent_message_chunk":
        text = acp.get("text") or acp.get("content", "")
        if text:
            return {"id": chat_id, "object": "chat.completion.chunk",
                    "created": now, "model": "monkeycode",
                    "choices": [{"index": 0, "delta": {"content": text},
                                 "finish_reason": None}]}

    elif acp["type"] == "agent_thought_chunk":
        text = acp.get("text") or acp.get("content", "")
        if text:
            return {"id": chat_id, "object": "chat.completion.chunk",
                    "created": now, "model": "monkeycode",
                    "choices": [{"index": 0, "delta": {"content": f"[Thinking] {text}"},
                                 "finish_reason": None}]}

    elif acp["type"] == "tool_call":
        return {"id": chat_id, "object": "chat.completion.chunk",
                "created": now, "model": "monkeycode",
                "choices": [{"index": 0,
                    "delta": {"content": f"[Tool: {acp.get('tool_name')}] {acp.get('tool_input', '')}"},
                    "finish_reason": None}]}

    elif acp["type"] == "usage_update":
        usage["input_tokens"] = acp.get("input_tokens", 0)
        usage["output_tokens"] = acp.get("output_tokens", 0)
        usage["total_tokens"] = acp.get("total_tokens", 0)
        return None

    return None
```

## 4. 测试套件分析

### 4.1 14 个认证测试

```python
# test_auth.py — 关键测试用例
class TestMonkeyCodeAuth(unittest.TestCase):

    def test_get_captcha_challenge(self):          # ✅ Test 1: 验证码挑战
    def test_redeem_captcha(self):                 # ✅ Test 2: 验证码兑换
    def test_password_login(self):                 # ✅ Test 3: 密码登录
    def test_session_ttl_tracking(self):           # ✅ Test 4: TTL 追踪
    def test_get_session_ttl_info(self):            # ✅ Test 5: TTL 信息
    def test_is_session_expired(self):             # ✅ Test 6: 过期检查
    def test_logout(self):                         # ✅ Test 7: 登出
    def test_login_and_logout_cycle(self):         # ✅ Test 8: 登录登出循环
    def test_get_user_info(self):                  # ✅ Test 9: 用户信息
    def test_auth_headers(self):                   # ✅ Test 10: 认证请求头
    def test_session_persistence(self):            # ✅ Test 11: Session 持久化
    def test_team_login_and_session(self):          # ✅ Test 12: 团队登录
    def test_missing_credentials(self):            # ✅ Test 13: 缺少凭据
    def test_get_session_age_seconds(self):        # ✅ Test 14: Session 年龄
```

### 4.2 端到端验证

```python
# verify_full_flow.py — 完整流程验证（471 行）
def test_full_loop(email, password, image_id):
    """认证 → 模型 → 任务 → WS 流 → 结果"""
    client = MonkeyCodeClient(username=email, password=password)
    client.login_with_password()

    models = client.list_models()
    model = models[0]

    task = client.create_task("Hello", model["id"])
    task_id = task.get("id") or task.get("task_id")

    collected = []
    def on_acp(acp):
        if acp["type"] == "agent_message_chunk":
            collected.append(acp.get("text", ""))

    client.stream_task(task_id, "Hello", on_acp_event=on_acp)

    full_text = "".join(collected)
    assert len(full_text) > 0, "Expected non-empty response"
    print(f"Full response ({len(full_text)} chars): {full_text[:200]}...")
```

## 5. 关键差异：Python MVP vs TypeScript 代理

| 维度 | Python MVP | TypeScript 代理 | 差异说明 |
|------|-----------|----------------|---------|
| **HTTP 框架** | `http.server.HTTPServer` | Express | Python 手写路由, TS 使用成熟框架 |
| **WS 库** | `websocket-client`（同步） | `ws`（异步事件） | Python 是阻塞 while 循环 |
| **多轮对话** | 不支持 | ConversationManager 完整实现 | Python 每请求新 WS |
| **号池** | 无（单账号） | AccountPool（多账号轮转） | Python 无号池功能 |
| **模型缓存** | 全局变量 + 5 分钟 | ModelManager 类 + 5 分钟 | 逻辑相同，实现不同 |
| **用户输入编码** | base64（早期） | 纯文本字符串 | Python 最初用 base64，TS 直接发文本 |
| **错误处理** | try/except 基本 | try/catch + 号池错误隔离 | TS 更完善 |
| **浏览器头伪装** | 无 | browser-headers.ts（5 种域名） | Python 仅基本 headers |
| **构建** | 纯 Python 零依赖 | npm + TypeScript 编译 | Python 无需构建 |
| **Responses API** | 基本支持 | 完整实现（9 种 SSE 事件） | TS 更完整 |

## 6. Python MVP 的独有发现

以下协议细节在 Python MVP 中被首次确认，之后才被 TS 代理采用：

1. **验证码 201 状态码** — `get_captcha_challenge()` 发现 POST `/captcha/challenge` 返回 201 而非 200
2. **Session TTL 不可刷新** — `get_session_remaining_seconds()` 确认 30 天 TTL 且 API 不延长
3. **WebSocket ping/pong** — 心跳消息格式 `{"type": "ping"}`，回复 `{"type": "ping"}`
4. **acp_ask_user_question 自动回复** — 格式 `{"request_id": "...", "answers_json": "", "cancelled": false}`
5. **usage_update 字段** — `input_tokens`/`output_tokens`/`total_tokens` 三个字段确认
6. **任务创建并发限制** — 错误码 `10811` 对应 "已有正在执行的任务"

---

## 相关章节

- [Python vs TS 实现差异](08-python-vs-ts.md) — 8 大关键差异
- [代理架构实现](../07-proxy/01-architecture.md) — TS 代理完整分析
- [协议验证工具索引](../MASTER-CHECKLIST.md) — 验证工具列表
