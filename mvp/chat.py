"""MonkeyCode WebSocket 聊天协议验证模块

验证:
1. WebSocket 任务流连接 (wss://monkeycode-ai.com/api/v1/ws/tasks/{task_id}/stream)
2. ACP 事件接收 (agent_message_chunk, agent_thought_chunk, tool_call, usage_update)
3. 用户输入发送 (base64 编码 JSON)
4. 任务控制 (stop)
"""
import json
import base64
import threading
import websocket
from config import BASE_URL, SESSION_COOKIE_NAME


class MonkeyCodeChat:
    def __init__(self, auth):
        self.auth = auth
        self.ws = None
        self.messages = []
        self.connected = False
        self._lock = threading.Lock()

    def connect_task_stream(self, task_id: str) -> bool:
        """连接任务流 WebSocket"""
        ws_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/api/v1/ws/tasks/{task_id}/stream"

        cookie = f"{SESSION_COOKIE_NAME}={self.auth.session_cookie}"
        headers = {
            "Cookie": cookie,
            "Origin": BASE_URL,
        }

        print(f"[Chat] 连接任务流: {ws_url}")

        self.ws = websocket.WebSocketApp(
            ws_url,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self._ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self._ws_thread.start()

        import time
        for _ in range(50):
            if self.connected:
                return True
            time.sleep(0.1)

        print("[Chat] 连接超时")
        return False

    def _on_open(self, ws):
        self.connected = True
        print("[Chat] WebSocket 连接成功")

    def _on_message(self, ws, message):
        with self._lock:
            self.messages.append(message)

        try:
            data = json.loads(message)
            event_type = data.get("type", data.get("event", "unknown"))
            print(f"[Chat] 收到事件: {event_type}")

            if event_type == "agent_message_chunk":
                content = data.get("data", {}).get("content", "")
                print(f"[Chat]   内容: {content[:100]}")
            elif event_type == "agent_thought_chunk":
                content = data.get("data", {}).get("content", "")
                print(f"[Chat]   思考: {content[:100]}")
            elif event_type == "tool_call":
                tool = data.get("data", {}).get("tool_name", "unknown")
                print(f"[Chat]   工具调用: {tool}")
            elif event_type == "usage_update":
                usage = data.get("data", {})
                print(f"[Chat]   用量: {usage}")
            elif event_type == "session_update":
                status = data.get("data", {}).get("status", "unknown")
                print(f"[Chat]   会话状态: {status}")
        except json.JSONDecodeError:
            print(f"[Chat] 非JSON消息: {message[:100]}")

    def _on_error(self, ws, error):
        print(f"[Chat] WebSocket 错误: {error}")
        self.connected = False

    def _on_close(self, ws, close_status, close_msg):
        print(f"[Chat] WebSocket 关闭: {close_status} {close_msg}")
        self.connected = False

    def send_user_input(self, text: str) -> bool:
        """发送用户输入 (base64 编码)"""
        if not self.ws or not self.connected:
            print("[Chat] 未连接，无法发送")
            return False

        payload = json.dumps({"content": text})
        encoded = base64.b64encode(payload.encode()).decode()

        message = json.dumps({
            "type": "user_input",
            "data": {"content": encoded},
        })

        print(f"[Chat] 发送用户输入: {text[:50]}")
        self.ws.send(message)
        return True

    def receive_messages(self, timeout: float = 30.0) -> list:
        """等待并返回接收到的消息"""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self.messages:
                    result = self.messages.copy()
                    self.messages.clear()
                    return result
            time.sleep(0.5)
        return []

    def close(self):
        """关闭 WebSocket 连接"""
        if self.ws:
            self.ws.close()
            self.connected = False
            print("[Chat] 连接已关闭")
