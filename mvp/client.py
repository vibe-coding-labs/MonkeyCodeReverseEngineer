"""MonkeyCode 统一客户端 — 认证 + 模型 + 任务 + WebSocket 流式接收

整合 auth.py, models.py, chat.py 的功能为一个统一客户端 MonkeyCodeClient。

支持:
1. Session Cookie 直接设置（从浏览器提取，推荐）
2. 密码登录（需 captcha_token）
3. 模型列表获取 + 按名称匹配解析
4. 任务创建（POST /api/v1/users/tasks）
5. WebSocket 任务流连接（ACP 事件回调）
6. 自动审批 + 自动回复 Agent 提问
7. Token 用量累积

参考:
- TypeScript 实现: proxy/src/auth.ts, proxy/src/task-runner.ts
- 协议文档: docs/protocol/llm-protocol-complete.md, docs/protocol/websocket-protocol.md
"""
import json
import base64
import os
import time
import threading
import re
from typing import Optional, Callable, Any

import requests
import websocket

from config import BASE_URL, SESSION_COOKIE_NAME

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
DEFAULT_HOST_ID = "public_host"
TASK_TIMEOUT_MS = int(os.getenv("MONKEYCODE_TASK_TIMEOUT_MS", "3600000"))  # 1h
SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000  # 30 天


class MonkeyCodeClient:
    """MonkeyCode 统一客户端"""

    def __init__(
        self,
        session_cookie: str = None,
        username: str = None,
        password: str = None,
        image_id: str = None,
        host_id: str = None,
    ):
        """初始化客户端

        认证优先级(高→低):
        1. session_cookie 参数（从浏览器提取）
        2. 环境变量 MONKEYCODE_SESSION_COOKIE
        3. username + password 参数（密码登录）
        4. 环境变量 MONKEYCODE_USERNAME + MONKEYCODE_PASSWORD
        """
        self.base_url = BASE_URL
        self.session_cookie_name = SESSION_COOKIE_NAME
        self.image_id = image_id or os.getenv("MONKEYCODE_IMAGE_ID", "")
        self.host_id = host_id or os.getenv("MONKEYCODE_HOST_ID", DEFAULT_HOST_ID)

        # 认证凭据
        env_cookie = os.getenv("MONKEYCODE_SESSION_COOKIE", "")
        self._session_cookie = session_cookie or env_cookie or ""
        self._username = username or os.getenv("MONKEYCODE_USERNAME", "")
        self._password = password or os.getenv("MONKEYCODE_PASSWORD", "")
        self._captcha_token = os.getenv("MONKEYCODE_CAPTCHA_TOKEN", "")

        # 状态
        self._user_info = None
        self._models = []
        self._last_auth_time = 0

        # WebSocket 状态（流式接收时使用）
        self._ws = None
        self._ws_thread = None
        self._connected = False

    # ──────────────────────────────────────────────
    # 认证
    # ──────────────────────────────────────────────

    def set_session_cookie(self, cookie: str, cookie_name: str = None):
        """手动设置 Session Cookie（从浏览器提取）"""
        self._session_cookie = cookie
        if cookie_name:
            self.session_cookie_name = cookie_name
        self._last_auth_time = int(time.time() * 1000)

    def get_auth_cookies(self) -> dict:
        """获取认证 Cookie 字典"""
        if not self._session_cookie:
            raise RuntimeError("未认证，请先设置 Session Cookie 或调用 login_with_password()")
        return {self.session_cookie_name: self._session_cookie}

    def get_auth_headers(self) -> dict:
        """获取含 Cookie 的请求头"""
        cookies = self.get_auth_cookies()
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return {
            "Cookie": cookie_str,
            "Content-Type": "application/json",
        }

    def get_session_cookie_value(self) -> str:
        """获取当前 Session Cookie 值"""
        return self._session_cookie

    def check_status(self) -> dict:
        """检查登录状态

        GET /api/v1/users/status

        Returns:
            {"success": True/False, "user": {...} or None, "status": HTTP状态码}
        """
        url = f"{self.base_url}/api/v1/users/status"
        cookies = self.get_auth_cookies()

        resp = requests.get(url, cookies=cookies, timeout=15)

        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("code") == 0:
                    self._user_info = data.get("data", data)
                    self._last_auth_time = int(time.time() * 1000)
                    return {"success": True, "user": self._user_info, "status": 200}
            except Exception:
                pass

        return {"success": False, "status": resp.status_code}

    def login_with_password(self, email: str = None, password: str = None) -> dict:
        """普通用户密码登录

        POST /api/v1/users/password-login
        Cookie: monkeycode_ai_session

        注意: 密码登录需要 captcha_token（go-cap 验证码系统）。
        推荐使用 Session Cookie 方式（from browser）绕过验证码。

        Args:
            email: 邮箱
            password: 密码（明文，HTTPS 加密传输后后端用 bcrypt 验证）

        Returns:
            {"success": True/False, "cookie": "..." or None, ...}
        """
        email = email or self._username
        password = password or self._password
        if not email or not password:
            raise ValueError("需要提供 email 和 password")

        url = f"{self.base_url}/api/v1/users/password-login"
        payload = {
            "email": email.strip(),
            "password": password.strip(),
        }
        if self._captcha_token:
            payload["captcha_token"] = self._captcha_token

        print(f"[Auth] 普通用户登录: {email}")
        resp = requests.post(url, json=payload, allow_redirects=False, timeout=15)

        cookie = self._extract_session_cookie(resp)
        if cookie:
            self._session_cookie = cookie
            self._last_auth_time = int(time.time() * 1000)
            # 验证登录是否成功
            status = self.check_status()
            if status["success"]:
                print(f"[Auth] 登录成功: {status['user']}")
                return {"success": True, "status": resp.status_code, "cookie": cookie}
            else:
                print(f"[Auth] Cookie 获取但登录状态异常")
                return {"success": False, "status": resp.status_code, "cookie": cookie,
                        "body": resp.text[:500]}
        else:
            print(f"[Auth] 登录失败: 无法获取 Session Cookie")
            return {"success": False, "status": resp.status_code, "body": resp.text[:500]}

    def get_oauth_redirect(self) -> Optional[dict]:
        """获取百智云 OAuth 重定向 URL

        GET /api/v1/users/login → 302 → baizhi.cloud

        Returns:
            {"redirect_url": "...", "state": "...", "client_id": "...", ...} 或 None
        """
        from urllib.parse import urlparse, parse_qs

        url = f"{self.base_url}/api/v1/users/login"
        resp = requests.get(url, allow_redirects=False, timeout=15)

        if resp.status_code != 302:
            print(f"[Auth] OAuth 重定向失败: status={resp.status_code}")
            return None

        location = resp.headers.get("Location", "")
        parsed = urlparse(location)
        params = parse_qs(parsed.query)

        result = {
            "redirect_url": location,
            "state": params.get("state", [""])[0],
            "client_id": params.get("client_id", [""])[0],
            "redirect_uri": params.get("redirect_uri", [""])[0],
            "scope": params.get("scope", [""])[0],
        }
        print(f"[Auth] OAuth 重定向: client_id={result['client_id']}, state={result['state'][:12]}...")
        return result

    # ──────────────────────────────────────────────
    # 模型
    # ──────────────────────────────────────────────

    def list_models(self) -> list:
        """获取用户可用模型列表

        GET /api/v1/users/models

        Returns:
            [model_dict, ...] — 模型对象列表
        """
        url = f"{self.base_url}/api/v1/users/models"
        cookies = self.get_auth_cookies()

        resp = requests.get(url, cookies=cookies, timeout=15)

        if resp.status_code != 200:
            print(f"[Models] 获取失败: HTTP {resp.status_code}")
            return []

        try:
            data = resp.json()
            payload = data.get("data", data)
            if isinstance(payload, dict):
                self._models = payload.get("models", payload.get("list", []))
            elif isinstance(payload, list):
                self._models = payload
            else:
                self._models = []
        except Exception as e:
            print(f"[Models] 解析失败: {e}")
            self._models = []

        print(f"[Models] 获取到 {len(self._models)} 个模型")
        return self._models

    def resolve_model(self, model_id: str) -> Optional[dict]:
        """按字符串匹配解析模型

        匹配优先级:
        1. 精确匹配 monkeycode/provider/model
        2. provider/model
        3. model 名称精确匹配
        4. display_name 匹配
        5. 默认模型 (is_default=True)
        6. 第一个可用 model

        Args:
            model_id: 模型标识字符串（如 "monkeycode/OpenAI/gpt-4o"）

        Returns:
            model_dict 或 None
        """
        if not self._models:
            self.list_models()
        if not self._models:
            return None

        # 去前缀: "monkeycode/OpenAI/gpt-4o" → "OpenAI/gpt-4o"
        search = model_id
        if search.startswith("monkeycode/"):
            search = search[len("monkeycode/"):]

        # 1. 精确匹配 monkeycode/provider/model
        match = None

        # 2. 精确匹配 provider/model
        if "/" in search:
            provider_part, model_part = search.split("/", 1)
            for m in self._models:
                if (m.get("provider", "").lower() == provider_part.lower()
                        and m.get("model", "").lower() == model_part.lower()):
                    match = m
                    break

        # 3. model 名称精确匹配
        if not match:
            for m in self._models:
                if m.get("model", "").lower() == search.lower():
                    match = m
                    break

        # 4. display_name 匹配
        if not match:
            for m in self._models:
                display = m.get("display_name", "") or m.get("name", "")
                if display.lower() == search.lower():
                    match = m
                    break

        # 5. 默认模型
        if not match:
            for m in self._models:
                if m.get("is_default"):
                    match = m
                    break

        # 6. 第一个可用模型
        if not match and self._models:
            match = self._models[0]

        if match:
            print(f"[Models] 解析 '{model_id}' → {match.get('provider')}/{match.get('model')}")
        else:
            print(f"[Models] 无法解析模型: {model_id}")

        return match

    def get_public_models(self) -> list:
        """获取公开模型列表（owner.type=public）"""
        return [m for m in self._models if self._is_owner_public(m.get("owner"))]

    def get_free_models(self) -> list:
        """获取免费模型列表（is_free=True）"""
        return [m for m in self._models if m.get("is_free")]

    @staticmethod
    def _is_owner_public(owner) -> bool:
        if isinstance(owner, dict):
            return owner.get("type") == "public" or owner.get("name") == "public"
        return owner == "public"

    # ──────────────────────────────────────────────
    # 任务
    # ──────────────────────────────────────────────

    def create_task(
        self,
        model: dict,
        prompt: str,
        system_prompt: str = None,
    ) -> str:
        """创建任务

        POST /api/v1/users/tasks

        Args:
            model: 模型对象（从 resolve_model 或 list_models 获取）
            prompt: 用户提示文本
            system_prompt: 可选系统提示

        Returns:
            task_id (UUID string)

        Raises:
            ValueError: 缺少 image_id 或任务创建失败
        """
        if not self.image_id:
            raise ValueError(
                "MONKEYCODE_IMAGE_ID 是必填项。"
                "获取方式: 浏览器登录后打开 DevTools → Network → 创建一个任务 → "
                "在 POST /api/v1/users/tasks 请求中找到 image_id 字段"
            )

        # cli_name 映射: 决定 Agent 类型
        interface_type = model.get("interface_type", "")
        if interface_type == "openai_responses":
            cli_name = "codex"
        elif interface_type == "anthropic":
            cli_name = "claude"
        else:
            cli_name = "opencode"

        url = f"{self.base_url}/api/v1/users/tasks"
        headers = self.get_auth_headers()

        body = {
            "content": prompt,
            "host_id": self.host_id,
            "image_id": self.image_id,
            "model_id": model["id"],
            "cli_name": cli_name,
            "resource": {
                "core": 1,
                "memory": 1073741824,  # 1 GB
                "life": 3600,           # 1 hour
            },
            "repo": {
                "repo_url": "",
                "branch": "master",
                "repo_filename": "",
                "zip_url": "",
            },
        }

        if system_prompt:
            body["system_prompt"] = system_prompt

        print(f"[Task] 创建任务: model={model.get('model')}, cli={cli_name}, "
              f"prompt_len={len(prompt)}, sysprompt={'yes' if system_prompt else 'no'}")

        resp = requests.post(url, json=body, headers=headers, timeout=30)

        if resp.status_code != 200:
            raise RuntimeError(f"创建任务失败 (HTTP {resp.status_code}): {resp.text[:500]}")

        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"创建任务响应非 JSON: {e}, body={resp.text[:500]}")

        # 后端可能返回业务错误码 (HTTP 200 但 code != 0)
        if data.get("code") and data.get("code") != 0:
            raise RuntimeError(f"创建任务失败 (code {data['code']}): "
                              f"{data.get('message', data.get('msg', str(data)))}")

        result = data.get("data", data)
        task_id = result.get("id") or result.get("task_id") or result.get("ID")

        if not task_id:
            raise RuntimeError(f"无法从响应中提取 task_id: {resp.text[:500]}")

        print(f"[Task] 任务创建成功: {task_id}")
        return task_id

    # ──────────────────────────────────────────────
    # WebSocket 流式接收
    # ──────────────────────────────────────────────

    def connect_task_stream(
        self,
        task_id: str,
        prompt: str,
        on_acp_event: Callable[[dict], None] = None,
        on_task_ended: Callable[[dict], None] = None,
        on_task_error: Callable[[str], None] = None,
        on_connected: Callable[[], None] = None,
        auto_approve: bool = True,
        timeout: float = None,
    ) -> dict:
        """连接任务流 WebSocket 并接收 ACP 事件

        WS: /api/v1/users/tasks/stream?id={taskId}&mode=new

        流程:
        1. 建立 WS 连接（携带 Session Cookie）
        2. 发送 auto-approve（可选，默认启用）
        3. 发送 user-input（用户提示）
        4. 接收事件:
           - ping → 回复 ping（心跳保持）
           - task-started → 任务开始
           - task-running + kind=acp_event → ACP 事件（回调 on_acp_event）
           - task-running + kind=acp_ask_user_question → 自动回复
           - task-ended → 任务结束（回调 on_task_ended）
           - task-error → 任务错误（回调 on_task_error）

        Args:
            task_id: 任务 ID
            prompt: 用户提示（与 create_task 的 prompt 相同）
            on_acp_event: ACP 事件回调，接收 acp dict: {type, data, ...}
            on_task_ended: 任务结束回调，接收 usage dict
            on_task_error: 任务错误回调，接收错误消息
            on_connected: WebSocket 连接成功回调
            auto_approve: 是否自动审批（默认 True，跳过 Agent 确认）
            timeout: 超时秒数（默认 None 使用 TASK_TIMEOUT_MS）

        Returns:
            {"usage": {"input_tokens": N, "output_tokens": N, "total_tokens": N}}
        """
        ws_url = self._http_to_ws(f"{self.base_url}/api/v1/users/tasks/stream"
                                   f"?id={task_id}&mode=new")
        cookie_str = f"{self.session_cookie_name}={self._session_cookie}"

        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        result = {"usage": usage}
        done_event = threading.Event()

        def on_open(ws):
            print(f"[WS] 连接成功: task={task_id}")
            self._connected = True
            if auto_approve:
                ws.send(json.dumps({"type": "auto-approve"}))
            # 发送用户输入
            ws.send(json.dumps({"type": "user-input", "data": prompt}))
            print(f"[WS] 已发送 auto_approve={auto_approve} + user-input")
            if on_connected:
                on_connected()

        def on_message(ws, message):
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                return  # 忽略非 JSON 消息

            msg_type = msg.get("type", "")

            # 心跳
            if msg_type == "ping":
                ws.send(json.dumps({"type": "ping"}))
                return

            # 任务开始
            if msg_type == "task-started":
                print(f"[WS] 任务开始: {task_id}")
                return

            # 任务运行中
            if msg_type == "task-running":
                kind = msg.get("kind", "")
                if kind == "acp_event":
                    try:
                        acp = json.loads(msg["data"])
                        self._handle_acp_event(acp, on_acp_event, usage)
                    except (json.JSONDecodeError, KeyError):
                        pass
                elif kind == "acp_ask_user_question":
                    # 自动回复 Agent 提问
                    self._auto_reply_question(ws, msg.get("data", "{}"))
                return

            # 任务结束
            if msg_type == "task-ended":
                print(f"[WS] 任务结束: {task_id}")
                if on_task_ended:
                    on_task_ended({"usage": usage})
                done_event.set()
                return

            # 任务错误
            if msg_type == "task-error":
                error_msg = msg.get("data", "未知错误")
                print(f"[WS] 任务错误: {error_msg}")
                if on_task_error:
                    on_task_error(error_msg)
                done_event.set()
                return

        def on_error(ws, error):
            print(f"[WS] 错误: {error}")
            if on_task_error:
                on_task_error(str(error))
            done_event.set()

        def on_close(ws, close_status, close_msg):
            print(f"[WS] 关闭: code={close_status}, msg={close_msg}")
            self._connected = False
            done_event.set()

        headers = {
            "Cookie": cookie_str,
            "Origin": self.base_url,
        }

        self._ws = websocket.WebSocketApp(
            ws_url,
            header=headers,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        timeout_s = timeout or (TASK_TIMEOUT_MS / 1000)

        self._ws_thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._ws_thread.start()

        # 等待完成或超时
        done_event.wait(timeout=timeout_s)
        self.close_stream()

        return result

    def send_user_input(self, text: str):
        """向已连接的 WebSocket 发送用户输入"""
        if not self._ws or not self._connected:
            raise RuntimeError("WebSocket 未连接")

        payload = json.dumps({"content": text})
        encoded = base64.b64encode(payload.encode()).decode()

        message = json.dumps({
            "type": "user_input",
            "data": {"content": encoded},
        })
        self._ws.send(message)

    def close_stream(self):
        """关闭 WebSocket 连接"""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False

    # ──────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────

    def _http_to_ws(self, url: str) -> str:
        """将 HTTP URL 转为 WebSocket URL"""
        return url.replace("https://", "wss://").replace("http://", "ws://")

    def _extract_session_cookie(self, resp, cookie_name: str = None) -> str:
        """从响应中提取 Session Cookie"""
        name = cookie_name or self.session_cookie_name

        # 从 cookies 中提取
        if name in resp.cookies:
            return resp.cookies[name]

        # 从 Set-Cookie header 中提取
        set_cookie = resp.headers.get("Set-Cookie", "")
        if name in set_cookie:
            match = re.search(rf"{name}=([^;]+)", set_cookie)
            if match:
                return match.group(1)

        return ""

    def _handle_acp_event(self, acp: dict, callback, usage: dict):
        """处理 ACP 事件

        ACP 事件类型:
        - agent_message_chunk: Agent 输出文本流式块
        - agent_thought_chunk: Agent 内部推理流式块
        - tool_call: 工具调用开始
        - tool_call_update: 工具调用状态更新
        - usage_update: Token 使用量更新
        - plan: 执行计划
        - available_commands_update: 可用命令更新
        """
        acp_type = acp.get("type", "")

        # 累积 usage
        if acp_type == "usage_update":
            if acp.get("input_tokens"):
                usage["input_tokens"] = acp["input_tokens"]
            if acp.get("output_tokens"):
                usage["output_tokens"] = acp["output_tokens"]
            if acp.get("total_tokens"):
                usage["total_tokens"] = acp["total_tokens"]
            return

        # 回调给上层
        if callback:
            callback(acp)

    def _auto_reply_question(self, ws, question_data_str: str):
        """自动回复 Agent 的提问"""
        try:
            question_data = json.loads(question_data_str)
            request_id = question_data.get("request_id") or question_data.get("id", "")
            ws.send(json.dumps({
                "type": "reply-question",
                "data": json.dumps({
                    "request_id": request_id,
                    "answers_json": "",
                    "cancelled": False,
                }),
            }))
            print(f"[WS] 自动回复问题: {request_id}")
        except json.JSONDecodeError:
            pass

    def __del__(self):
        self.close_stream()