"""MonkeyCode OpenAI 兼容反向代理 MVP

最小化实现，验证 MonkeyCode → OpenAI 协议转换可行性。
仅支持 /v1/models 和 /v1/chat/completions（流式）。
"""
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from config import PROXY_PORT
from auth import MonkeyCodeAuth
from models import MonkeyCodeModels


class OpenAIProxyHandler(BaseHTTPRequestHandler):
    auth = None
    models_mgr = None

    def log_message(self, format, *args):
        print(f"[Proxy] {format % args}")

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _send_sse(self, data: dict):
        chunk = f"data: {json.dumps(data)}\n\n"
        self.wfile.write(chunk.encode())
        self.wfile.flush()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/v1/models":
            self._handle_models()
        elif path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/v1/chat/completions":
            self._handle_chat_completions()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_models(self):
        """GET /v1/models — 返回 OpenAI 兼容模型列表"""
        if not self.models_mgr.models:
            result = self.models_mgr.list_models()
            if not result["success"]:
                self._send_json(502, {"error": "failed to fetch models", "detail": result})
                return

        openai_models = []
        for m in self.models_mgr.models:
            openai_models.append({
                "id": f"monkeycode/{m.get('provider', 'unknown')}/{m.get('model', 'unknown')}",
                "object": "model",
                "created": int(time.time()),
                "owned_by": m.get("owner", "unknown"),
            })

        self._send_json(200, {
            "object": "list",
            "data": openai_models,
        })

    def _handle_chat_completions(self):
        """POST /v1/chat/completions — OpenAI 兼容聊天接口 (MVP: 返回 mock 响应)"""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        model = req.get("model", "unknown")
        messages = req.get("messages", [])
        stream = req.get("stream", False)

        prompt = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)

        print(f"[Proxy] Chat request: model={model}, messages={len(messages)}, stream={stream}")

        if stream:
            self._handle_stream_response(model, prompt)
        else:
            self._handle_non_stream_response(model, prompt)

    def _handle_stream_response(self, model: str, prompt: str):
        """流式响应 (MVP: mock)"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        mock_text = f"[MVP Mock] 收到请求，模型: {model}。实际实现将创建 MonkeyCode 任务并通过 WebSocket 流式返回。"

        for char in mock_text:
            self._send_sse({
                "id": "chatcmpl-mvp",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": char},
                    "finish_reason": None,
                }],
            })

        self._send_sse({
            "id": "chatcmpl-mvp",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
        })
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _handle_non_stream_response(self, model: str, prompt: str):
        """非流式响应 (MVP: mock)"""
        self._send_json(200, {
            "id": "chatcmpl-mvp",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"[MVP Mock] 收到请求，模型: {model}。实际实现将创建 MonkeyCode 任务并返回结果。",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


def run_proxy():
    auth = MonkeyCodeAuth()
    models_mgr = MonkeyCodeModels(auth)

    OpenAIProxyHandler.auth = auth
    OpenAIProxyHandler.models_mgr = models_mgr

    server = HTTPServer(("0.0.0.0", PROXY_PORT), OpenAIProxyHandler)
    print(f"[Proxy] OpenAI 兼容代理启动: http://localhost:{PROXY_PORT}")
    print(f"[Proxy] 端点: /v1/models, /v1/chat/completions, /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Proxy] 代理已停止")
        server.server_close()


if __name__ == "__main__":
    run_proxy()
