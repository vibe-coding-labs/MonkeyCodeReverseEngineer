"""MonkeyCode OpenAI 兼容代理 — 真实任务执行版

替换 mvp/proxy.py 的 mock 实现，通过 MonkeyCode API 创建真实任务，将 ACP 事件
映射为 OpenAI 兼容的 SSE 流式响应。

支持的 OpenAI 端点:
1. GET /v1/models — 真实模型列表（来自 MonkeyCode API）
2. POST /v1/chat/completions — Chat Completions API（流式+非流式）
3. POST /v1/responses — Responses API（Codex 原生，SSE 流式）

架构:
```
Client (Codex/curl)
    ↓ OpenAI API 格式
Proxy (proxy_real.py, port 9091)
    ↓ MonkeyCode API + WS
MonkeyCode Backend (monkeycode-ai.com)
    ↓ TaskFlow VM → LLM Client
LLM Provider
```

ACP → OpenAI 事件映射:
- agent_message_chunk  → delta.content (Chat) / output_text.delta (Responses)
- agent_thought_chunk  → [Thinking] prefix + content
- tool_call            → tool_calls delta / function_call (Responses)
- usage_update         → 累积 → task-ended 时输出
- task-ended           → finish_reason: stop + usage

参考: proxy/src/api-routes.ts
"""
import json
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BASE_URL, SESSION_COOKIE_NAME, PROXY_PORT
from client import MonkeyCodeClient

# 代理端口（与 mock proxy.py 区分，使用 9091）
PROXY_REAL_PORT = int(os.getenv("PROXY_REAL_PORT", "9091"))


class ProxyState:
    """代理全局状态"""
    client: Optional[MonkeyCodeClient] = None
    models_cache: list = []
    models_cache_time: float = 0
    models_cache_ttl: float = 300  # 5 分钟缓存


# ──────────────────────────────────────────────
# OpenAI 兼容请求/响应构建
# ──────────────────────────────────────────────

def messages_to_prompt(messages: list) -> str:
    """将 OpenAI messages 列表转为 prompt 文本"""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # 多模态消息: 提取 text 部分
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            content = "\n".join(texts)
        if role == "system":
            parts.append(f"[System]\n{content}")
        elif role == "user":
            parts.append(f"[User]\n{content}")
        elif role == "assistant":
            parts.append(f"[Assistant]\n{content}")
        else:
            parts.append(content)
    return "\n\n".join(parts)


def fetch_models(client: MonkeyCodeClient) -> list:
    """从 MonkeyCode API 获取并缓存模型列表"""
    now = time.time()
    if ProxyState.models_cache and (now - ProxyState.models_cache_time) < ProxyState.models_cache_ttl:
        return ProxyState.models_cache

    models = client.list_models()
    openai_models = []
    for m in models:
        provider = m.get("provider", "unknown")
        model_name = m.get("model", "unknown")
        openai_models.append({
            "id": f"monkeycode/{provider}/{model_name}",
            "object": "model",
            "created": int(time.time()),
            "owned_by": m.get("owner", "monkeycode"),
            "permission": [],
        })

    ProxyState.models_cache = openai_models
    ProxyState.models_cache_time = now
    print(f"[Proxy] 模型列表已刷新: {len(openai_models)} 个模型")
    return openai_models


def resolve_model_from_cache(model_id: str) -> Optional[dict]:
    """从缓存中按 ID 查找模型（返回原始 MonkeyCode 模型对象）"""
    client = ProxyState.client
    if not client:
        return None
    return client.resolve_model(model_id)


# ──────────────────────────────────────────────
# HTTP 处理器
# ──────────────────────────────────────────────

class RealProxyHandler(BaseHTTPRequestHandler):
    """OpenAI 兼容代理 HTTP 请求处理器"""

    def log_message(self, format, *args):
        print(f"[Proxy] {format % args}")

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _send_sse(self, data: dict):
        """发送 SSE data 行"""
        chunk = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            self.wfile.write(chunk.encode())
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def _send_sse_event(self, event: str, data: dict, seq: int = 0):
        """发送命名 SSE 事件（用于 Responses API）"""
        payload = json.dumps({**data, "sequence_number": seq}, ensure_ascii=False)
        try:
            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def do_OPTIONS(self):
        """CORS 预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/v1/models":
            self._handle_models()
        elif path == "/health" or path == "/":
            self._send_json(200, {
                "status": "ok",
                "service": "MonkeyCode OpenAI Proxy",
                "version": "1.0.0",
                "base_url": BASE_URL,
            })
        else:
            self._send_json(404, {"error": {"message": "Not Found", "type": "not_found"}})

    def do_POST(self):
        path = urlparse(self.path).path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}})
            return

        if path == "/v1/chat/completions":
            self._handle_chat_completions(req)
        elif path == "/v1/responses":
            self._handle_responses(req)
        else:
            self._send_json(404, {"error": {"message": "Not Found", "type": "not_found"}})

    # ──────────────────────────────────────────────
    # GET /v1/models
    # ──────────────────────────────────────────────

    def _handle_models(self):
        client = ProxyState.client
        if not client:
            self._send_json(502, {"error": {"message": "客户端未初始化", "type": "internal_error"}})
            return

        try:
            models = fetch_models(client)
            self._send_json(200, {
                "object": "list",
                "data": models,
            })
        except Exception as e:
            self._send_json(502, {"error": {"message": str(e), "type": "upstream_error"}})

    # ──────────────────────────────────────────────
    # POST /v1/chat/completions
    # ──────────────────────────────────────────────

    def _handle_chat_completions(self, req: dict):
        client = ProxyState.client
        if not client:
            self._send_json(502, {"error": {"message": "客户端未初始化", "type": "internal_error"}})
            return

        model_id = req.get("model", "")
        messages = req.get("messages", [])
        stream = req.get("stream", False)
        max_tokens = req.get("max_tokens", 4096)

        if not messages:
            self._send_json(400, {"error": {"message": "messages is required", "type": "invalid_request_error"}})
            return

        # 解析模型
        model = resolve_model_from_cache(model_id)
        if not model:
            self._send_json(404, {"error": {"message": f"Model '{model_id}' not found", "type": "invalid_request_error"}})
            return

        # 提取 system_prompt
        system_msg = None
        non_system = []
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "")
            else:
                non_system.append(m)

        prompt = messages_to_prompt(non_system)
        chat_id = f"chatcmpl-{int(time.time())}"

        try:
            # 创建任务
            task_id = client.create_task(model, prompt, system_prompt=system_msg)
            print(f"[Chat] 任务创建成功: {task_id}, model={model.get('model')}")

            if stream:
                self._handle_stream_response(task_id, prompt, model, chat_id, client)
            else:
                self._handle_non_stream_response(task_id, prompt, model, chat_id, client)
        except Exception as e:
            print(f"[Chat] 错误: {e}")
            if not self.wfile.closed:
                self._send_json(500, {"error": {"message": str(e), "type": "internal_error"}})

    def _handle_stream_response(self, task_id: str, prompt: str, model: dict, chat_id: str, client: MonkeyCodeClient):
        """流式响应处理"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        now = int(time.time())
        model_name = model.get("model", "monkeycode")
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def on_acp_event(acp: dict):
            nonlocal usage
            acp_type = acp.get("type", "")

            if acp_type == "agent_message_chunk":
                text = acp.get("text") or acp.get("content") or ""
                if text:
                    self._send_sse({
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": now,
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None,
                        }],
                    })

            elif acp_type == "agent_thought_chunk":
                text = acp.get("text") or acp.get("content") or ""
                if text:
                    self._send_sse({
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": now,
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": f"[Thinking] {text}"},
                            "finish_reason": None,
                        }],
                    })

            elif acp_type == "tool_call":
                tool_name = acp.get("tool_name", "unknown")
                tool_input = acp.get("tool_input", "")
                self._send_sse({
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": now,
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": f"\n[Tool: {tool_name}] {tool_input}\n"},
                        "finish_reason": None,
                    }],
                })

        def on_task_ended(result: dict):
            final_usage = result.get("usage", {})
            usage["prompt_tokens"] = final_usage.get("input_tokens", 0)
            usage["completion_tokens"] = final_usage.get("output_tokens", 0)
            usage["total_tokens"] = final_usage.get("total_tokens", 0)

            # 发送完成事件
            self._send_sse({
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            })

            # 发送用法（非标准，给客户端提供参考）
            if usage["total_tokens"] > 0:
                self._send_sse({
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": now,
                    "model": model_name,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": usage["prompt_tokens"],
                        "completion_tokens": usage["completion_tokens"],
                        "total_tokens": usage["total_tokens"],
                    },
                })

            # 结束
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except BrokenPipeError:
                pass

        def on_task_error(error_msg: str):
            self._send_sse({
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {"content": f"\n[Error] {error_msg}"},
                    "finish_reason": None,
                }],
            })
            self._send_sse({
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            })
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except BrokenPipeError:
                pass

        # 连接 WebSocket 流
        try:
            client.connect_task_stream(
                task_id=task_id,
                prompt=prompt,
                on_acp_event=on_acp_event,
                on_task_ended=on_task_ended,
                on_task_error=on_task_error,
            )
        except Exception as e:
            print(f"[Stream] 流式接收错误: {e}")

    def _handle_non_stream_response(self, task_id: str, prompt: str, model: dict, chat_id: str, client: MonkeyCodeClient):
        """非流式响应处理 — 收集完整输出后一次性返回"""
        full_content = ""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        done_event = threading.Event()

        def on_acp_event(acp: dict):
            nonlocal full_content
            acp_type = acp.get("type", "")
            if acp_type == "agent_message_chunk":
                text = acp.get("text") or acp.get("content") or ""
                full_content += text
            elif acp_type == "agent_thought_chunk":
                text = acp.get("text") or acp.get("content") or ""
                full_content += f"\n[Thinking] {text}\n"
            elif acp_type == "tool_call":
                tool_name = acp.get("tool_name", "unknown")
                tool_input = acp.get("tool_input", "")
                full_content += f"\n[Tool: {tool_name}] {tool_input}\n"

        def on_task_ended(result: dict):
            nonlocal usage
            final_usage = result.get("usage", {})
            usage["prompt_tokens"] = final_usage.get("input_tokens", 0)
            usage["completion_tokens"] = final_usage.get("output_tokens", 0)
            usage["total_tokens"] = final_usage.get("total_tokens", 0)
            done_event.set()

        def on_task_error(error_msg: str):
            nonlocal full_content
            full_content += f"\n[Error] {error_msg}"
            done_event.set()

        try:
            client.connect_task_stream(
                task_id=task_id,
                prompt=prompt,
                on_acp_event=on_acp_event,
                on_task_ended=on_task_ended,
                on_task_error=on_task_error,
            )
            # 等待任务完成
            done_event.wait(timeout=120)
        except Exception as e:
            print(f"[NonStream] 错误: {e}")

        model_name = model.get("model", "monkeycode")
        response = {
            "id": chat_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_content},
                "finish_reason": "stop",
            }],
            "usage": usage if usage["total_tokens"] > 0 else {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

        self._send_json(200, response)

    # ──────────────────────────────────────────────
    # POST /v1/responses — OpenAI Responses API
    # ──────────────────────────────────────────────

    def _handle_responses(self, req: dict):
        """OpenAI Responses API（Codex 原生协议）

        SSE 事件流:
        - response.created
        - response.output_item.added (message / function_call)
        - response.content_part.added
        - response.output_text.delta
        - response.function_call_arguments.delta (tool_call)
        - response.content_part.done
        - response.output_item.done
        - response.completed
        """
        client = ProxyState.client
        if not client:
            self._send_json(502, {"error": {"message": "客户端未初始化", "type": "internal_error"}})
            return

        model_id = req.get("model", "")
        input_data = req.get("input", "")

        if not input_data:
            self._send_json(400, {"error": {"message": "input is required", "type": "invalid_request_error"}})
            return

        model = resolve_model_from_cache(model_id)
        if not model:
            self._send_json(404, {"error": {"message": f"Model '{model_id}' not found", "type": "invalid_request_error"}})
            return

        # 归一化 input → prompt + system_prompt
        prompt = ""
        system_prompt = None
        if isinstance(input_data, str):
            prompt = input_data
        elif isinstance(input_data, list):
            for m in input_data:
                if m.get("role") == "system":
                    system_prompt = m.get("content", "")
            user_msgs = [m for m in input_data if m.get("role") != "system"]
            prompt = messages_to_prompt(user_msgs)
        elif isinstance(input_data, dict):
            prompt = input_data.get("content", "")

        response_id = f"resp-{int(time.time())}"

        try:
            task_id = client.create_task(model, prompt, system_prompt=system_prompt)
            print(f"[Responses] 任务创建成功: {task_id}")
        except Exception as e:
            self._send_json(500, {"error": {"message": str(e), "type": "internal_error"}})
            return

        # SSE 流式响应
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        seq = 0
        model_name = model.get("model", "monkeycode")
        current_output_index = 0
        current_call_id = ""
        current_tool_name = ""
        text_opened = False

        # response.created
        self._send_sse_event("response.created", {
            "type": "response.created",
            "response": {
                "id": response_id,
                "object": "response",
                "status": "in_progress",
                "model": model_name,
                "output": [],
            },
        }, seq := seq + 1)

        def on_acp_event(acp: dict):
            nonlocal seq, current_output_index, current_call_id, current_tool_name, text_opened
            acp_type = acp.get("type", "")

            if acp_type in ("agent_message_chunk", "agent_thought_chunk"):
                text = acp.get("text") or acp.get("content") or ""
                if not text:
                    return

                # 首次文本输出时发送 output_item.added + content_part.added
                if not text_opened:
                    self._send_sse_event("response.output_item.added", {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {
                            "type": "message",
                            "id": f"msg-{task_id}",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": ""}],
                        },
                    }, seq := seq + 1)
                    self._send_sse_event("response.content_part.added", {
                        "type": "response.content_part.added",
                        "output_index": 0,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": ""},
                    }, seq := seq + 1)
                    text_opened = True
                    current_output_index = 1

                prefix = "[Thinking] " if acp_type == "agent_thought_chunk" else ""
                self._send_sse_event("response.output_text.delta", {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": {"type": "output_text.delta", "text": prefix + text},
                }, seq := seq + 1)

            elif acp_type == "tool_call":
                current_call_id = f"call_{acp.get('tool_name', 'unknown')}_{int(time.time())}"
                current_tool_name = acp.get("tool_name", "unknown")
                args = acp.get("tool_input", "")

                self._send_sse_event("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": current_output_index,
                    "item": {
                        "type": "function_call",
                        "id": current_call_id,
                        "call_id": current_call_id,
                        "name": current_tool_name,
                        "arguments": "",
                    },
                }, seq := seq + 1)

                if args:
                    self._send_sse_event("response.function_call_arguments.delta", {
                        "type": "response.function_call_arguments.delta",
                        "output_index": current_output_index,
                        "delta": {"type": "function_call_arguments.delta", "arguments": args},
                    }, seq := seq + 1)

            elif acp_type == "tool_call_update":
                update_args = acp.get("tool_input") or acp.get("delta") or ""
                if update_args and current_call_id:
                    self._send_sse_event("response.function_call_arguments.delta", {
                        "type": "response.function_call_arguments.delta",
                        "output_index": current_output_index,
                        "delta": {"type": "function_call_arguments.delta", "arguments": update_args},
                    }, seq := seq + 1)

                if acp.get("status") in ("completed", "done"):
                    final_args = acp.get("tool_input", "")
                    self._send_sse_event("response.function_call_arguments.done", {
                        "type": "response.function_call_arguments.done",
                        "output_index": current_output_index,
                        "arguments": final_args,
                    }, seq := seq + 1)
                    self._send_sse_event("response.output_item.done", {
                        "type": "response.output_item.done",
                        "output_index": current_output_index,
                        "item": {
                            "type": "function_call",
                            "id": current_call_id,
                            "call_id": current_call_id,
                            "name": current_tool_name,
                            "arguments": final_args,
                        },
                    }, seq := seq + 1)
                    current_output_index += 1
                    current_call_id = ""
                    current_tool_name = ""

        def on_task_ended(result: dict):
            nonlocal seq, text_opened, current_output_index, current_call_id, current_tool_name
            usage = result.get("usage", {})

            # 关闭未完成的 tool_call
            if current_call_id:
                self._send_sse_event("response.function_call_arguments.done", {
                    "type": "response.function_call_arguments.done",
                    "output_index": current_output_index,
                    "arguments": "",
                }, seq := seq + 1)
                self._send_sse_event("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": current_output_index,
                    "item": {
                        "type": "function_call",
                        "id": current_call_id,
                        "call_id": current_call_id,
                        "name": current_tool_name,
                        "arguments": "",
                    },
                }, seq := seq + 1)

            # 关闭文本输出
            if text_opened:
                self._send_sse_event("response.content_part.done", {
                    "type": "response.content_part.done",
                    "output_index": 0,
                    "content_index": 0,
                }, seq := seq + 1)
                self._send_sse_event("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "type": "message",
                        "id": f"msg-{task_id}",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": ""}],
                    },
                }, seq := seq + 1)

            # 无输出时发送空消息
            if not text_opened and not current_call_id:
                self._send_sse_event("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "message",
                        "id": f"msg-{task_id}",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": ""}],
                    },
                }, seq := seq + 1)
                self._send_sse_event("response.content_part.added", {
                    "type": "response.content_part.added",
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": ""},
                }, seq := seq + 1)
                self._send_sse_event("response.content_part.done", {
                    "type": "response.content_part.done",
                    "output_index": 0,
                    "content_index": 0,
                }, seq := seq + 1)
                self._send_sse_event("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "type": "message",
                        "id": f"msg-{task_id}",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": ""}],
                    },
                }, seq := seq + 1)

            # response.completed
            self._send_sse_event("response.completed", {
                "type": "response.completed",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "status": "completed",
                    "model": model_name,
                    "usage": {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                },
            }, seq := seq + 1)

            try:
                self.wfile.write(b"\n")
                self.wfile.flush()
            except BrokenPipeError:
                pass

        def on_task_error(error_msg: str):
            self._send_sse_event("response.completed", {
                "type": "response.completed",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "status": "failed",
                    "model": model_name,
                    "error": {"message": error_msg},
                },
            }, seq := seq + 1)

            try:
                self.wfile.write(b"\n")
                self.wfile.flush()
            except BrokenPipeError:
                pass

        try:
            client.connect_task_stream(
                task_id=task_id,
                prompt=prompt,
                on_acp_event=on_acp_event,
                on_task_ended=on_task_ended,
                on_task_error=on_task_error,
            )
        except Exception as e:
            print(f"[Responses] 流错误: {e}")


# ──────────────────────────────────────────────
# 服务器
# ──────────────────────────────────────────────

def create_proxy_server(host="0.0.0.0", port=None):
    """创建代理 HTTP 服务器

    Args:
        host: 监听地址
        port: 端口（默认 PROXY_REAL_PORT = 9091）
    """
    port = port or PROXY_REAL_PORT

    # 检查依赖
    try:
        import websocket
    except ImportError:
        print("错误: 需要安装 websocket-client 库")
        print("  pip install websocket-client")
        sys.exit(1)

    # 初始化客户端
    client = MonkeyCodeClient()

    # 检查认证状态
    if client.get_session_cookie_value():
        status = client.check_status()
        if status["success"]:
            print(f"[Proxy] Session Cookie 有效")
        else:
            print(f"[Proxy] ⚠️ Session Cookie 可能已过期")
            if client._username and client._password:
                print("[Proxy] 尝试密码登录...")
                result = client.login_with_password()
                if not result["success"]:
                    print(f"[Proxy] ⚠️ 密码登录失败，代理仅返回缓存数据")
            else:
                print("[Proxy] ⚠️ 未设置凭据。请设置:")
                print("  MONKEYCODE_SESSION_COOKIE=xxx")
                print("  或 MONKEYCODE_USERNAME=xxx + MONKEYCODE_PASSWORD=xxx")
    else:
        if client._username and client._password:
            print("[Proxy] 尝试密码登录...")
            result = client.login_with_password()
            if not result["success"]:
                print(f"[Proxy] ⚠️ 密码登录失败")
        else:
            print("[Proxy] ⚠️ 未认证。请设置 MONKEYCODE_SESSION_COOKIE")

    # 验证 IMAGE_ID
    if not client.image_id:
        print("[Proxy] ⚠️ MONKEYCODE_IMAGE_ID 未设置!")
        print("  任务创建将失败。从浏览器 DevTools 中获取 image_id。")

    ProxyState.client = client

    # 预取模型列表
    try:
        print("[Proxy] 预取模型列表...")
        fetch_models(client)
    except Exception as e:
        print(f"[Proxy] 模型预取失败: {e}")

    server = HTTPServer((host, port), RealProxyHandler)
    print(f"\n{'='*60}")
    print(f"  MonkeyCode OpenAI 兼容代理 (真实任务版)")
    print(f"  {'='*60}")
    print(f"  监听: http://{host}:{port}")
    print(f"  端点:")
    print(f"    GET  /v1/models               — 模型列表")
    print(f"    POST /v1/chat/completions      — Chat Completions API")
    print(f"    POST /v1/responses             — Responses API (Codex)")
    print(f"    GET  /health                   — 健康检查")
    print(f"  后端: {BASE_URL}")
    print(f"  {'='*60}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Proxy] 代理已停止")
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MonkeyCode OpenAI 兼容代理 (真实版)")
    parser.add_argument("--port", type=int, default=PROXY_REAL_PORT, help=f"监听端口 (默认 {PROXY_REAL_PORT})")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")

    args = parser.parse_args()

    # 打印配置摘要
    print(f"[Config] BASE_URL={BASE_URL}")
    print(f"[Config] SESSION_COOKIE={'已设置' if os.getenv('MONKEYCODE_SESSION_COOKIE') else '未设置'}")
    print(f"[Config] IMAGE_ID={'已设置' if os.getenv('MONKEYCODE_IMAGE_ID') else '⚠️ 未设置'}")

    create_proxy_server(host=args.host, port=args.port)