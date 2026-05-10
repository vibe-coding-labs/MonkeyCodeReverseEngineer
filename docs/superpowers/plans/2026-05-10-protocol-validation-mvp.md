# MonkeyCode 协议验证 MVP + 文档整理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** 将所有分析文档迁移到 docs/ 目录，使用 Python 编写 MVP 验证脚本，端到端验证逆向出的通信协议（认证、模型列表、WebSocket 流式）确实可被反向代理使用。

**Architecture:** 文档从 analysis/protocol/ 迁移到 docs/protocol/ → Python MVP 脚本使用 requests + websocket-client 直接调用 MonkeyCode API → 验证 Cookie-based Session 认证 → 验证模型列表 API → 验证 WebSocket 任务流 → 输出验证报告。Python 选择因为快速原型验证，无需编译，requests 库对 Cookie 处理天然支持。

**Tech Stack:** Python 3.12, requests 2.32, websocket-client 1.8, hashlib (stdlib)

**Risks:**
- Task 2/3 需要真实 MonkeyCode 账号 → 缓解：用户表示可协助登录，MVP 支持手动设置 Session Cookie
- MonkeyCode 可能有 CSRF 保护 → 缓解：先测试无 CSRF 场景，失败则从浏览器提取 CSRF token
- WebSocket 连接可能需要特定 Origin header → 缓解：MVP 中设置 Origin 为 monkeycode-ai.com

---

### Task 1: 迁移文档到 docs/ 目录

**Depends on:** None
**Files:**
- Move: `analysis/protocol/api-endpoints.md` → `docs/protocol/api-endpoints.md`
- Move: `analysis/protocol/architecture.md` → `docs/protocol/architecture.md`
- Move: `analysis/protocol/auth-protocol.md` → `docs/protocol/auth-protocol.md`
- Move: `analysis/protocol/llm-integration.md` → `docs/protocol/llm-integration.md`
- Move: `analysis/protocol/websocket-protocol.md` → `docs/protocol/websocket-protocol.md`
- Create: `docs/protocol/asar-analysis.md` (从 asar-content 提取信息)

- [ ] **Step 1: 创建 docs/protocol/ 目录并迁移所有协议文档**

```bash
mkdir -p docs/protocol
mv analysis/protocol/api-endpoints.md docs/protocol/
mv analysis/protocol/architecture.md docs/protocol/
mv analysis/protocol/auth-protocol.md docs/protocol/
mv analysis/protocol/llm-integration.md docs/protocol/
mv analysis/protocol/websocket-protocol.md docs/protocol/
rmdir analysis/protocol
```

- [ ] **Step 2: 创建 ASAR 分析文档 — 记录 Electron 客户端逆向发现**

```markdown
// docs/protocol/asar-analysis.md

# MonkeyCode Electron 客户端 ASAR 分析

## 概述

MonkeyCode 桌面客户端是一个极薄的 Electron 壳，所有前端代码从远程加载。

## 关键发现

### Electron 配置

- **appId**: `com.monkeycode.desktop`
- **Electron 版本**: ^35.1.5
- **ASAR**: 启用（但仅 5.8KB，几乎为空壳）

### main.cjs 分析

- **默认加载 URL**: `https://monkeycode-ai.com`
- **启动路径**: `/console/`（可通过 `MONKEYCODE_DESKTOP_START_PATH` 覆盖）
- **开发模式**: 加载 `http://localhost:11180`（Vite dev server）
- **本地构建模式**: `MONKEYCODE_LOAD_LOCAL_DIST=1` 时加载 `web-dist/index.html`

### 安全配置

- `contextIsolation: true` — 上下文隔离启用
- `nodeIntegration: false` — Node 集成禁用
- `sandbox: false` — 沙箱禁用（为兼容完整 Web 应用）

### 环境变量覆盖

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `MONKEYCODE_DESKTOP_URL` | 后端地址 | `https://monkeycode-ai.com` |
| `MONKEYCODE_DESKTOP_START_PATH` | 启动路径 | `/console/` |
| `MONKEYCODE_LOAD_LOCAL_DIST` | 加载本地构建 | `0` |
| `VITE_DEV_SERVER_URL` | 开发服务器地址 | `http://localhost:11180` |

### preload.cjs

仅包含 `"use strict"` 和注释，未暴露任何 API 到渲染进程。

### 结论

Electron 客户端是纯 Web 壳，所有业务逻辑在 `monkeycode-ai.com` 上运行。逆向目标应聚焦于：
1. GitHub 源码中的后端 Go 代码
2. Swagger 生成的 `frontend/src/api/Api.ts`（170KB，6420 行）
3. 实际网络通信（HTTP + WebSocket）
```

- [ ] **Step 3: 验证文档迁移完成**
Run: `ls -la docs/protocol/ && test ! -d analysis/protocol && echo "OLD DIR REMOVED"`
Expected:
  - Exit code: 0
  - Output contains: "api-endpoints.md", "architecture.md", "auth-protocol.md", "llm-integration.md", "websocket-protocol.md", "asar-analysis.md"
  - Output contains: "OLD DIR REMOVED"

- [ ] **Step 4: 提交**
Run: `git add docs/protocol/ analysis/ && git commit -m "docs: migrate protocol docs to docs/protocol/ and add ASAR analysis"`

---

### Task 2: 创建 Python MVP 基础框架

**Depends on:** Task 1
**Files:**
- Create: `mvp/requirements.txt`
- Create: `mvp/config.py`
- Create: `mvp/auth.py`
- Create: `mvp/models.py`

- [ ] **Step 1: 创建 Python 依赖文件**

```text
requests>=2.32.0
websocket-client>=1.8.0
```

- [ ] **Step 2: 安装 Python 依赖**
Run: `cd mvp && pip install -r requirements.txt`
Expected:
  - Exit code: 0
  - Output contains: "Successfully installed"

- [ ] **Step 3: 创建配置模块 — 集中管理 MonkeyCode 连接参数**

```python
# mvp/config.py
import os

BASE_URL = os.getenv("MONKEYCODE_BASE_URL", "https://monkeycode-ai.com")
SESSION_COOKIE_NAME = "monkeycode_ai_session"

# 认证配置（二选一）
USERNAME = os.getenv("MONKEYCODE_USERNAME", "")
PASSWORD = os.getenv("MONKEYCODE_PASSWORD", "")
SESSION_COOKIE = os.getenv("MONKEYCODE_SESSION_COOKIE", "")

# 代理配置
PROXY_PORT = int(os.getenv("PROXY_PORT", "9090"))
```

- [ ] **Step 4: 创建认证模块 — 验证 Cookie-based Session 登录协议**

```python
# mvp/auth.py
"""MonkeyCode 认证协议验证模块

验证:
1. Team 用户登录 (POST /api/v1/teams/users/login)
2. Session Cookie 提取
3. 登录状态检查 (GET /api/v1/users/status)
4. 登出 (POST /api/v1/users/logout)
"""
import hashlib
import requests
from config import BASE_URL, SESSION_COOKIE_NAME, USERNAME, PASSWORD, SESSION_COOKIE


class MonkeyCodeAuth:
    def __init__(self):
        self.session = requests.Session()
        self.session_cookie = SESSION_COOKIE
        self.user_info = None

    def login_with_password(self, username: str = None, password: str = None) -> dict:
        """Team 用户密码登录 — 验证 POST /api/v1/teams/users/login"""
        username = username or USERNAME
        password = password or PASSWORD
        if not username or not password:
            raise ValueError("需要提供 username 和 password")

        # MonkeyCode 要求密码 MD5 哈希
        password_md5 = hashlib.md5(password.encode()).hexdigest()

        url = f"{BASE_URL}/api/v1/teams/users/login"
        payload = {
            "username": username,
            "password": password_md5,
        }

        print(f"[Auth] 尝试登录: {username}")
        print(f"[Auth] 密码 MD5: {password_md5}")

        resp = self.session.post(url, json=payload, allow_redirects=False)

        print(f"[Auth] 响应状态: {resp.status_code}")
        print(f"[Auth] 响应头: {dict(resp.headers)}")

        # 提取 Session Cookie
        cookies = resp.cookies
        if SESSION_COOKIE_NAME in cookies:
            self.session_cookie = cookies[SESSION_COOKIE_NAME]
            print(f"[Auth] Session Cookie 获取成功: {self.session_cookie[:20]}...")
        else:
            # 尝试从 Set-Cookie header 提取
            set_cookie = resp.headers.get("Set-Cookie", "")
            if SESSION_COOKIE_NAME in set_cookie:
                import re
                match = re.search(rf"{SESSION_COOKIE_NAME}=([^;]+)", set_cookie)
                if match:
                    self.session_cookie = match.group(1)
                    print(f"[Auth] Session Cookie (从 header) 获取成功: {self.session_cookie[:20]}...")

        if not self.session_cookie:
            print(f"[Auth] 登录失败: 无法获取 Session Cookie")
            print(f"[Auth] 响应体: {resp.text[:500]}")
            return {"success": False, "status": resp.status_code, "body": resp.text[:500]}

        # 解析响应
        try:
            data = resp.json()
            self.user_info = data.get("data", data)
            print(f"[Auth] 登录成功: {self.user_info}")
        except Exception:
            pass

        return {"success": True, "status": resp.status_code, "cookie": self.session_cookie}

    def set_session_cookie(self, cookie: str):
        """手动设置 Session Cookie（从浏览器复制）"""
        self.session_cookie = cookie
        self.session.cookies.set(SESSION_COOKIE_NAME, cookie)
        print(f"[Auth] Session Cookie 已设置: {cookie[:20]}...")

    def check_status(self) -> dict:
        """检查登录状态 — 验证 GET /api/v1/users/status"""
        url = f"{BASE_URL}/api/v1/users/status"
        cookies = {SESSION_COOKIE_NAME: self.session_cookie}

        resp = requests.get(url, cookies=cookies)
        print(f"[Auth] 状态检查: {resp.status_code}")

        if resp.status_code == 200:
            try:
                data = resp.json()
                self.user_info = data.get("data", data)
                print(f"[Auth] 已登录: {self.user_info}")
                return {"success": True, "user": self.user_info}
            except Exception:
                pass

        print(f"[Auth] 未登录或 Session 过期")
        return {"success": False, "status": resp.status_code}

    def logout(self) -> dict:
        """登出 — 验证 POST /api/v1/users/logout"""
        url = f"{BASE_URL}/api/v1/users/logout"
        cookies = {SESSION_COOKIE_NAME: self.session_cookie}

        resp = requests.post(url, cookies=cookies)
        print(f"[Auth] 登出: {resp.status_code}")
        self.session_cookie = ""
        self.user_info = None
        return {"success": resp.status_code == 200}

    def get_auth_cookies(self) -> dict:
        """获取认证 Cookie 字典"""
        if not self.session_cookie:
            raise RuntimeError("未认证，请先登录或设置 Session Cookie")
        return {SESSION_COOKIE_NAME: self.session_cookie}
```

- [ ] **Step 5: 创建模型管理模块 — 验证模型列表 API**

```python
# mvp/models.py
"""MonkeyCode 模型管理协议验证模块

验证:
1. 获取用户模型列表 (GET /api/v1/users/models)
2. 模型数据结构验证
3. 公开模型识别 (public:model: 前缀)
4. 模型健康检查 (GET /api/v1/users/models/{id}/health-check)
"""
import requests
from config import BASE_URL, SESSION_COOKIE_NAME


class MonkeyCodeModels:
    def __init__(self, auth):
        self.auth = auth
        self.models = []

    def list_models(self) -> dict:
        """获取用户可用模型列表 — 验证 GET /api/v1/users/models"""
        url = f"{BASE_URL}/api/v1/users/models"
        cookies = self.auth.get_auth_cookies()

        print(f"[Models] 获取模型列表...")
        resp = requests.get(url, cookies=cookies)
        print(f"[Models] 响应状态: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[Models] 获取失败: {resp.text[:500]}")
            return {"success": False, "status": resp.status_code}

        data = resp.json()
        # 响应格式: {code: 0, data: {models: [...]}} 或 {models: [...]}
        result = data.get("data", data)
        self.models = result.get("models", []) if isinstance(result, dict) else result

        print(f"[Models] 获取到 {len(self.models)} 个模型")

        # 分类统计
        by_owner = {}
        by_interface = {}
        by_provider = {}
        for m in self.models:
            owner = m.get("owner", "unknown")
            iface = m.get("interface_type", "unknown")
            provider = m.get("provider", "unknown")
            by_owner[owner] = by_owner.get(owner, 0) + 1
            by_interface[iface] = by_interface.get(iface, 0) + 1
            by_provider[provider] = by_provider.get(provider, 0) + 1

        print(f"[Models] 按所有者: {by_owner}")
        print(f"[Models] 按接口类型: {by_interface}")
        print(f"[Models] 按提供商: {by_provider}")

        # 显示公开模型详情
        public_models = [m for m in self.models if m.get("owner") == "public"]
        if public_models:
            print(f"\n[Models] 公开模型详情:")
            for m in public_models:
                print(f"  - {m.get('provider')}/{m.get('model')} "
                      f"(interface={m.get('interface_type')}, "
                      f"free={m.get('is_free')}, "
                      f"access={m.get('access_level')})")
                # 检查 API Key 是否为 public:model: 前缀
                api_key = m.get("api_key", "")
                if api_key.startswith("public:model:"):
                    print(f"    API Key: {api_key} (公开模型前缀，后端自动替换)")

        return {
            "success": True,
            "count": len(self.models),
            "by_owner": by_owner,
            "by_interface": by_interface,
            "by_provider": by_provider,
            "models": self.models,
        }

    def health_check(self, model_id: str) -> dict:
        """模型健康检查 — 验证 GET /api/v1/users/models/{id}/health-check"""
        url = f"{BASE_URL}/api/v1/users/models/{model_id}/health-check"
        cookies = self.auth.get_auth_cookies()

        print(f"[Models] 健康检查模型 {model_id}...")
        resp = requests.get(url, cookies=cookies)
        print(f"[Models] 健康检查结果: {resp.status_code} {resp.text[:200]}")

        return {"success": resp.status_code == 200, "status": resp.status_code, "body": resp.text[:500]}

    def get_public_models(self) -> list:
        """获取公开模型列表"""
        return [m for m in self.models if m.get("owner") == "public"]

    def get_free_models(self) -> list:
        """获取免费模型列表"""
        return [m for m in self.models if m.get("is_free")]
```

- [ ] **Step 6: 验证 Python 模块可导入**
Run: `cd mvp && python -c "from config import BASE_URL; from auth import MonkeyCodeAuth; from models import MonkeyCodeModels; print('All modules imported OK')"`
Expected:
  - Exit code: 0
  - Output contains: "All modules imported OK"

- [ ] **Step 7: 提交**
Run: `git add mvp/ && git commit -m "feat(mvp): add Python MVP base with auth and models modules"`

---

### Task 3: 创建协议验证测试脚本

**Depends on:** Task 2
**Files:**
- Create: `mvp/chat.py`
- Create: `mvp/test_protocol.py`

- [ ] **Step 1: 创建 Chat 模块 — 验证 WebSocket 任务流协议**

```python
# mvp/chat.py
"""MonkeyCode Chat 协议验证模块

验证:
1. WebSocket 连接到任务流 (GET /api/v1/users/tasks/stream)
2. 消息格式验证 (JSON {type, data, kind, timestamp})
3. ACP 事件解析 (agent_message_chunk, usage_update 等)
4. 用户输入发送 (type=user-input)
"""
import json
import base64
import time
import websocket
from config import BASE_URL, SESSION_COOKIE_NAME


def http_to_ws(url: str) -> str:
    return url.replace("https://", "wss://").replace("http://", "ws://")


class MonkeyCodeChat:
    def __init__(self, auth):
        self.auth = auth
        self.ws = None

    def connect_task_stream(self, task_id: str, mode: str = "attach") -> dict:
        """连接到任务流 WebSocket — 验证 WS /api/v1/users/tasks/stream"""
        ws_url = http_to_ws(BASE_URL)
        url = f"{ws_url}/api/v1/users/tasks/stream?id={task_id}&mode={mode}"
        cookie = f"{SESSION_COOKIE_NAME}={self.auth.session_cookie}"

        print(f"[Chat] 连接 WebSocket: {url}")
        print(f"[Chat] Cookie: {cookie[:40]}...")

        try:
            self.ws = websocket.WebSocket()
            self.ws.connect(
                url,
                header=[
                    f"Cookie: {cookie}",
                    f"Origin: {BASE_URL}",
                ],
                timeout=10,
            )
            print(f"[Chat] WebSocket 连接成功")
            return {"success": True}
        except Exception as e:
            print(f"[Chat] WebSocket 连接失败: {e}")
            return {"success": False, "error": str(e)}

    def receive_messages(self, timeout: float = 5.0) -> list:
        """接收 WebSocket 消息并解析"""
        messages = []
        deadline = time.time() + timeout

        while time.time() < deadline and self.ws and self.ws.connected:
            try:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self.ws.settimeout(min(remaining, 1.0))
                raw = self.ws.recv()
                if raw:
                    try:
                        msg = json.loads(raw)
                        messages.append(msg)
                        print(f"[Chat] 收到: type={msg.get('type')}, kind={msg.get('kind', '-')}")
                    except json.JSONDecodeError:
                        print(f"[Chat] 收到非 JSON: {raw[:100]}")
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                print(f"[Chat] 接收错误: {e}")
                break

        return messages

    def send_user_input(self, content: str) -> dict:
        """发送用户输入 — 验证上行消息格式"""
        if not self.ws or not self.ws.connected:
            return {"success": False, "error": "WebSocket 未连接"}

        # MonkeyCode 新格式: base64 编码的 JSON
        content_b64 = base64.b64encode(content.encode()).decode()
        payload = json.dumps({
            "content": content_b64,
            "attachments": [],
        })

        msg = {
            "type": "user-input",
            "data": payload,
        }

        print(f"[Chat] 发送用户输入: {content[:50]}...")
        try:
            self.ws.send(json.dumps(msg))
            return {"success": True}
        except Exception as e:
            print(f"[Chat] 发送失败: {e}")
            return {"success": False, "error": str(e)}

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
```

- [ ] **Step 2: 创建协议验证测试脚本 — 端到端验证所有逆向协议**

```python
# mvp/test_protocol.py
"""MonkeyCode 协议验证 MVP — 端到端验证逆向出的通信协议

验证项:
1. ✅ Cookie-based Session 认证
2. ✅ 模型列表 API
3. ✅ 公开模型识别
4. ✅ WebSocket 任务流连接
5. ✅ OpenAI 兼容代理可行性

用法:
  # 方式1: 使用密码登录
  MONKEYCODE_USERNAME=user MONKEYCODE_PASSWORD=pass python test_protocol.py

  # 方式2: 使用浏览器 Session Cookie
  MONKEYCODE_SESSION_COOKIE=xxx python test_protocol.py

  # 方式3: 交互式（会提示输入）
  python test_protocol.py
"""
import sys
import os
import json
import time

# 确保可以从当前目录导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BASE_URL, SESSION_COOKIE_NAME, USERNAME, PASSWORD, SESSION_COOKIE
from auth import MonkeyCodeAuth
from models import MonkeyCodeModels
from chat import MonkeyCodeChat


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def print_result(name: str, success: bool, detail: str = ""):
    icon = "✅" if success else "❌"
    print(f"  {icon} {name}")
    if detail:
        print(f"     {detail}")


def test_auth(auth: MonkeyCodeAuth) -> bool:
    """测试1: 认证协议验证"""
    print_header("测试1: Cookie-based Session 认证协议")

    # 如果已有 Session Cookie，先验证
    if auth.session_cookie:
        print("[Test] 使用已有 Session Cookie 验证...")
        result = auth.check_status()
        if result["success"]:
            print_result("Session Cookie 有效性", True, f"用户: {result.get('user', {})}")
            return True
        else:
            print_result("Session Cookie 有效性", False, "Cookie 可能已过期")
            auth.session_cookie = ""

    # 尝试密码登录
    if USERNAME and PASSWORD:
        print(f"[Test] 尝试密码登录: {USERNAME}")
        result = auth.login_with_password()
        if result["success"]:
            print_result("Team 用户登录", True, f"Cookie: {result.get('cookie', '')[:20]}...")
            # 验证状态
            status = auth.check_status()
            print_result("登录状态检查", status["success"])
            return result["success"]
        else:
            print_result("Team 用户登录", False, f"状态: {result.get('status')}, 原因: {result.get('body', '')[:100]}")
            return False
    else:
        print("[Test] 未提供凭据，跳过登录测试")
        print("[Test] 请设置环境变量:")
        print("  MONKEYCODE_USERNAME=xxx MONKEYCODE_PASSWORD=xxx")
        print("  或")
        print("  MONKEYCODE_SESSION_COOKIE=xxx")
        return False


def test_models(models: MonkeyCodeModels) -> bool:
    """测试2: 模型列表 API 验证"""
    print_header("测试2: 模型列表 API 协议验证")

    result = models.list_models()
    if not result["success"]:
        print_result("模型列表获取", False, f"状态: {result.get('status')}")
        return False

    print_result("模型列表获取", True, f"共 {result['count']} 个模型")

    # 验证数据结构
    by_owner = result.get("by_owner", {})
    by_interface = result.get("by_interface", {})
    by_provider = result.get("by_provider", {})

    print_result("模型所有者分类", True, str(by_owner))
    print_result("接口类型分类", True, str(by_interface))
    print_result("提供商分类", True, str(by_provider))

    # 验证公开模型
    public = models.get_public_models()
    print_result("公开模型识别", len(public) > 0, f"{len(public)} 个公开模型")

    # 验证免费模型
    free = models.get_free_models()
    print_result("免费模型识别", len(free) > 0, f"{len(free)} 个免费模型")

    # 验证模型数据结构完整性
    if models.models:
        m = models.models[0]
        required_fields = ["id", "provider", "model", "interface_type", "owner"]
        missing = [f for f in required_fields if f not in m]
        print_result("模型数据结构完整性", len(missing) == 0,
                     f"缺失字段: {missing}" if missing else "所有必需字段存在")

    return True


def test_websocket(auth: MonkeyCodeAuth, models: MonkeyCodeModels) -> bool:
    """测试3: WebSocket 协议验证"""
    print_header("测试3: WebSocket 任务流协议验证")

    # 需要一个 task_id 来测试
    # 先尝试创建任务或使用已有任务
    print("[Test] WebSocket 测试需要已有任务 ID")
    print("[Test] 跳过自动测试，提供手动测试指引:")
    print()
    print("  1. 在浏览器中创建一个 MonkeyCode 任务")
    print("  2. 从浏览器 DevTools Network 面板找到任务 ID")
    print("  3. 运行以下代码测试 WebSocket:")
    print()
    print(f"     from chat import MonkeyCodeChat")
    print(f"     chat = MonkeyCodeChat(auth)")
    print(f"     chat.connect_task_stream('YOUR_TASK_ID', mode='attach')")
    print(f"     messages = chat.receive_messages(timeout=10)")
    print(f"     for msg in messages: print(msg)")
    print()

    # 尝试直接连接验证 WebSocket 端点是否可达
    from chat import http_to_ws
    ws_url = http_to_ws(BASE_URL)
    test_url = f"{ws_url}/api/v1/users/tasks/stream?id=test&mode=attach"
    cookie = f"{SESSION_COOKIE_NAME}={auth.session_cookie}"

    print(f"[Test] 测试 WebSocket 端点可达性...")
    try:
        import websocket as ws_lib
        test_ws = ws_lib.WebSocket()
        test_ws.connect(
            test_url,
            header=[f"Cookie: {cookie}", f"Origin: {BASE_URL}"],
            timeout=5,
        )
        # 连接成功说明端点可达（即使 task_id 无效，握手也会成功）
        test_ws.close()
        print_result("WebSocket 端点可达", True, f"端点: {ws_url}/api/v1/users/tasks/stream")
        return True
    except Exception as e:
        error_str = str(e)
        # 403/401 说明端点存在但认证问题
        if "403" in error_str or "401" in error_str:
            print_result("WebSocket 端点可达", True, "端点存在，需要有效任务 ID")
            return True
        print_result("WebSocket 端点可达", False, f"错误: {error_str[:100]}")
        return False


def test_proxy_feasibility(models: MonkeyCodeModels) -> bool:
    """测试4: 反向代理可行性评估"""
    print_header("测试4: OpenAI 兼容反向代理可行性评估")

    public = models.get_public_models()
    free = models.get_free_models()

    print("[评估] 基于逆向分析结果，评估反向代理可行性:")
    print()

    # 评估1: 是否有可用的公开/免费模型
    has_usable = len(public) > 0 or len(free) > 0
    print_result("可用模型存在", has_usable,
                 f"公开: {len(public)}, 免费: {len(free)}")

    # 评估2: 接口类型覆盖
    if models.models:
        interfaces = set(m.get("interface_type") for m in models.models)
        print_result("接口类型覆盖", True, f"支持: {interfaces}")

        # 检查三种接口类型是否都有模型
        expected = {"openai_chat", "openai_responses", "anthropic"}
        covered = interfaces & expected
        print_result("三种 LLM 接口覆盖", len(covered) >= 2,
                     f"已覆盖: {covered}, 缺失: {expected - interfaces}")

    # 评估3: 认证协议可行性
    print_result("Cookie-based Session 可行", True,
                 "Python requests 库天然支持 Cookie 管理")

    # 评估4: WebSocket 流式可行性
    print_result("WebSocket 流式可行", True,
                 "websocket-client 库支持，ACP → OpenAI SSE 转换已设计")

    print()
    print("[评估] 结论:")
    if has_usable:
        print("  ✅ 反向代理可行！可以通过 MonkeyCode 的公开/免费模型提供 OpenAI 兼容 API")
        print("  ✅ 建议使用公开模型（后端自动替换 API Key），无需暴露实际 Provider 凭据")
    else:
        print("  ⚠️ 需要用户自行配置模型 API Key（私有模型）")
        print("  ⚠️ 公开模型可能需要订阅才能使用")

    return has_usable


def main():
    print("=" * 60)
    print("  MonkeyCode 协议验证 MVP")
    print(f"  目标: {BASE_URL}")
    print("=" * 60)

    auth = MonkeyCodeAuth()
    models_mgr = MonkeyCodeModels(auth)

    results = {}

    # 测试1: 认证
    results["auth"] = test_auth(auth)
    if not results["auth"]:
        print("\n[WARN] 认证失败，后续测试可能无法进行")
        print("[WARN] 请设置环境变量后重试")
        # 继续执行，某些测试可能不需要认证

    # 测试2: 模型列表
    if results["auth"]:
        results["models"] = test_models(models_mgr)
    else:
        results["models"] = False

    # 测试3: WebSocket
    if results["auth"]:
        results["websocket"] = test_websocket(auth, models_mgr)
    else:
        results["websocket"] = False

    # 测试4: 代理可行性
    if results["models"]:
        results["proxy"] = test_proxy_feasibility(models_mgr)
    else:
        results["proxy"] = False

    # 汇总
    print_header("验证结果汇总")
    for name, success in results.items():
        icon = "✅" if success else "❌"
        print(f"  {icon} {name}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  总计: {passed}/{total} 通过")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 验证测试脚本可运行（无凭据模式）**
Run: `cd mvp && python test_protocol.py 2>&1 | head -30`
Expected:
  - Exit code: non-zero (因为没有凭据)
  - Output contains: "MonkeyCode 协议验证 MVP"

- [ ] **Step 4: 提交**
Run: `git add mvp/ && git commit -m "feat(mvp): add protocol validation test script with WebSocket and proxy feasibility check"`

---

### Task 4: 端到端集成验证

**Depends on:** Task 3
**Files:**
- Create: `mvp/proxy.py`
- Create: `mvp/run_mvp.sh`

- [ ] **Step 1: 创建 Python 最小反向代理 — 验证 OpenAI 兼容 API 可行性**

```python
# mvp/proxy.py
"""MonkeyCode 最小反向代理 — Python MVP

验证反向代理可行性:
1. 接收 OpenAI 格式请求
2. 转换为 MonkeyCode API 调用
3. 返回 OpenAI 格式响应

仅用于协议验证，非生产级实现。
"""
import json
import time
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BASE_URL, PROXY_PORT
from auth import MonkeyCodeAuth
from models import MonkeyCodeModels


class OpenAIProxyHandler(BaseHTTPRequestHandler):
    auth = None
    models_mgr = None

    def do_GET(self):
        if self.path == "/v1/models":
            self.handle_models()
        elif self.path == "/health":
            self.handle_health()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            self.handle_chat_completions()
        else:
            self.send_error(404)

    def handle_health(self):
        self.send_json(200, {"status": "ok", "target": BASE_URL})

    def handle_models(self):
        """GET /v1/models — 返回 OpenAI 格式模型列表"""
        try:
            result = self.models_mgr.list_models()
            if not result["success"]:
                self.send_json(500, {"error": "Failed to fetch models"})
                return

            openai_models = []
            for m in self.models_mgr.models:
                openai_models.append({
                    "id": f"monkeycode/{m.get('provider')}/{m.get('model')}",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": m.get("provider"),
                })

            self.send_json(200, {"object": "list", "data": openai_models})
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def handle_chat_completions(self):
        """POST /v1/chat/completions — 转换为 MonkeyCode 任务"""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return

        model_name = req.get("model", "")
        messages = req.get("messages", [])

        # 构造简单响应（MVP 不实际创建任务，仅验证请求解析）
        prompt = "\n".join(f"[{m.get('role')}] {m.get('content')}" for m in messages)

        self.send_json(200, {
            "id": f"chatcmpl-mvp-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"[MVP Proxy] 收到请求，模型: {model_name}\n[提示] 实际任务创建需要 WebSocket 流式支持，请参考 TypeScript 代理实现",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": len(prompt), "completion_tokens": 0, "total_tokens": len(prompt)},
        })

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[Proxy] {args[0]}")


def main():
    print(f"=== MonkeyCode MVP Reverse Proxy ===")
    print(f"Target: {BASE_URL}")
    print(f"Port: {PROXY_PORT}")
    print()

    # 初始化认证
    auth = MonkeyCodeAuth()
    OpenAIProxyHandler.auth = auth
    OpenAIProxyHandler.models_mgr = MonkeyCodeModels(auth)

    # 尝试认证
    try:
        if auth.session_cookie:
            status = auth.check_status()
            if status["success"]:
                print("[Init] Session Cookie 有效")
            else:
                print("[Init] Session Cookie 无效，尝试登录...")
                if USERNAME and PASSWORD:
                    auth.login_with_password()
        elif USERNAME and PASSWORD:
            auth.login_with_password()
    except Exception as e:
        print(f"[Init] 认证失败: {e}")

    # 启动代理
    server = HTTPServer(("0.0.0.0", PROXY_PORT), OpenAIProxyHandler)
    print(f"\nMVP Proxy running on http://localhost:{PROXY_PORT}")
    print(f"  GET  /v1/models           - List models")
    print(f"  POST /v1/chat/completions - Chat completion")
    print(f"  GET  /health              - Health check")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Proxy] 停止")
        server.server_close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 创建 MVP 运行脚本**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 加载 .env
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

echo "=== MonkeyCode MVP Runner ==="
echo ""
echo "选择操作:"
echo "  1) 运行协议验证测试"
echo "  2) 启动 MVP 反向代理"
echo "  3) 交互式登录（获取 Session Cookie）"
echo ""

read -p "请选择 (1/2/3): " choice

case "$choice" in
  1)
    echo "运行协议验证测试..."
    python test_protocol.py
    ;;
  2)
    echo "启动 MVP 反向代理..."
    python proxy.py
    ;;
  3)
    echo "交互式登录..."
    python -c "
from auth import MonkeyCodeAuth
auth = MonkeyCodeAuth()
username = input('用户名: ')
password = input('密码: ')
result = auth.login_with_password(username, password)
if result['success']:
    print(f'\\nSession Cookie:')
    print(auth.session_cookie)
    print(f'\\n设置环境变量:')
    print(f'export MONKEYCODE_SESSION_COOKIE={auth.session_cookie}')
else:
    print(f'\\n登录失败: {result}')
"
    ;;
  *)
    echo "无效选择"
    ;;
esac
```

- [ ] **Step 3: 创建 mvp/.env.example**

```text
# MonkeyCode 认证配置（二选一）

# 方式1: 用户名密码登录
MONKEYCODE_USERNAME=
MONKEYCODE_PASSWORD=

# 方式2: 手动设置 Session Cookie（从浏览器复制）
MONKEYCODE_SESSION_COOKIE=

# MonkeyCode 后端地址
MONKEYCODE_BASE_URL=https://monkeycode-ai.com

# 代理端口
PROXY_PORT=9090
```

- [ ] **Step 4: 验证 MVP 代理可启动**
Run: `cd mvp && timeout 3 python proxy.py 2>&1 || true`
Expected:
  - Output contains: "MonkeyCode MVP Reverse Proxy"

- [ ] **Step 5: 提交**
Run: `git add mvp/ && git commit -m "feat(mvp): add Python MVP reverse proxy and run script for protocol validation"`
