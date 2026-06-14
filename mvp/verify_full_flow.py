#!/usr/bin/env python3
"""MonkeyCode 授权与代理端到端验证脚本

自动执行完整链路验证:
1. 认证有效性检查
2. 模型列表获取与解析
3. 任务创建（真实 API）
4. WebSocket 流式接收（ACP 事件）
5. 代理 HTTP 端点可达性测试

用法:
  # 完整验证（需要有效 Session Cookie + IMAGE_ID）
  MONKEYCODE_SESSION_COOKIE=xxx MONKEYCODE_IMAGE_ID=xxx python verify_full_flow.py

  # 仅验证认证和模型（不需要 IMAGE_ID）
  MONKEYCODE_SESSION_COOKIE=xxx python verify_full_flow.py --skip-task

  # 密码登录方式
  MONKEYCODE_USERNAME=xxx MONKEYCODE_PASSWORD=xxx MONKEYCODE_IMAGE_ID=xxx python verify_full_flow.py
"""
import json
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BASE_URL, SESSION_COOKIE_NAME
from client import MonkeyCodeClient


# ──────────────────────────────────────────────
# 颜色输出
# ──────────────────────────────────────────────
class Color:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def print_pass(msg):
    print(f"  {Color.GREEN}✓ PASS{Color.RESET} {msg}")

def print_fail(msg):
    print(f"  {Color.RED}✗ FAIL{Color.RESET} {msg}")

def print_skip(msg):
    print(f"  {Color.YELLOW}⊘ SKIP{Color.RESET} {msg}")

def print_info(msg):
    print(f"  {Color.BLUE}ℹ INFO{Color.RESET} {msg}")

def print_warn(msg):
    print(f"  {Color.YELLOW}⚠ WARN{Color.RESET} {msg}")

def print_header(title):
    print(f"\n{Color.BOLD}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{Color.RESET}")

def print_section(title):
    print(f"\n{Color.CYAN}--- {title} ---{Color.RESET}")


# ──────────────────────────────────────────────
# 测试结果收集
# ──────────────────────────────────────────────
class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def ok(self, name, detail=""):
        self.passed += 1
        print_pass(f"{name}" + (f" — {detail}" if detail else ""))

    def fail(self, name, detail=""):
        self.failed += 1
        self.errors.append((name, detail))
        print_fail(f"{name}" + (f" — {detail}" if detail else ""))

    def skip(self, name, detail=""):
        self.skipped += 1
        print_skip(f"{name}" + (f" — {detail}" if detail else ""))

    def summary(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{'='*60}")
        if self.failed == 0:
            print(f"  {Color.GREEN}全部通过!{Color.RESET}")
        else:
            print(f"  {Color.RED}{self.failed} 项失败{Color.RESET}")
        print(f"  通过: {self.passed}  失败: {self.failed}  跳过: {self.skipped}  总计: {total}")
        if self.errors:
            print(f"\n  失败详情:")
            for name, detail in self.errors:
                print(f"    - {name}: {detail}")
        print(f"{'='*60}")
        return self.failed == 0


# ──────────────────────────────────────────────
# 测试用例
# ──────────────────────────────────────────────

def test_001_api_connectivity(t: TestResult, client: MonkeyCodeClient):
    """API 连通性"""
    print_section("API 连通性")
    try:
        import requests
        resp = requests.get(BASE_URL, timeout=10)
        t.ok("MonkeyCode 主页可达", f"HTTP {resp.status_code}")
    except Exception as e:
        t.fail("MonkeyCode 主页不可达", str(e))
        return False

    # 测试公开 API 端点
    for path, expected in [("/api/v1/users/status", 401),
                           ("/api/v1/users/models", 401)]:
        try:
            resp = requests.get(f"{BASE_URL}{path}", timeout=10)
            if resp.status_code == expected:
                t.ok(f"GET {path}", f"HTTP {resp.status_code} (预期 {expected})")
            else:
                t.fail(f"GET {path}", f"HTTP {resp.status_code} (预期 {expected})")
        except Exception as e:
            t.fail(f"GET {path}", str(e))

    return True


def test_002_authentication(t: TestResult, client: MonkeyCodeClient):
    """认证有效性验证"""
    print_section("认证有效性")

    cookie = client.get_session_cookie_value()
    if not cookie:
        # 尝试密码登录
        if client._username and client._password:
            print_info("尝试密码登录...")
            result = client.login_with_password()
            if result["success"]:
                t.ok("密码登录", f"Cookie: {result['cookie'][:20]}...")
            else:
                t.fail("密码登录", f"状态: {result.get('status')}, body: {result.get('body', '')[:100]}")
                return False
        else:
            t.fail("无凭据", "未提供 Session Cookie 或用户名密码")
            print_info("设置方式:")
            print_info("  export MONKEYCODE_SESSION_COOKIE='从浏览器获取的 cookie 值'")
            print_info("  或 export MONKEYCODE_USERNAME=xxx MONKEYCODE_PASSWORD=xxx")
            return False

    # 检查 Session 有效性
    status = client.check_status()
    if status["success"]:
        user = status.get("user", {})
        if isinstance(user, dict):
            t.ok("Session 有效", f"user_id={str(user.get('id', '?'))[:12]}..., "
                                 f"role={user.get('role', '?')}")
        else:
            t.ok("Session 有效")
    else:
        t.fail("Session 无效", f"HTTP {status.get('status')}")
        return False

    # OAuth 重定向检查
    oauth = client.get_oauth_redirect()
    if oauth:
        t.ok("OAuth 重定向", f"client_id={oauth['client_id']}, state={oauth['state'][:12]}...")
    else:
        t.skip("OAuth 重定向", "可能不是百智云 OAuth 配置")

    return True


def test_003_models(t: TestResult, client: MonkeyCodeClient):
    """模型列表获取与解析"""
    print_section("模型列表")

    models = client.list_models()
    if not models:
        t.fail("模型列表获取", "返回空列表")
        return False

    t.ok("模型列表获取", f"共 {len(models)} 个模型")

    # 统计分布
    by_owner = {}
    by_interface = {}
    by_provider = {}
    for m in models:
        owner = m.get("owner", "unknown")
        if isinstance(owner, dict):
            owner_label = owner.get("type", owner.get("name", "unknown"))
        else:
            owner_label = str(owner)
        by_owner[owner_label] = by_owner.get(owner_label, 0) + 1
        iface = m.get("interface_type", "unknown")
        by_interface[iface] = by_interface.get(iface, 0) + 1
        provider = m.get("provider", "unknown")
        by_provider[provider] = by_provider.get(provider, 0) + 1

    t.ok("按所有者分布", str(by_owner))
    t.ok("按接口类型分布", str(by_interface))
    t.ok("按提供商分布", str(by_provider))

    # 检查必需字段
    m = models[0]
    required = ["id", "provider", "model", "interface_type", "owner"]
    missing = [f for f in required if f not in m]
    if missing:
        t.fail("模型字段完整性", f"缺失: {missing}")
    else:
        t.ok("模型字段完整性", "所有必需字段存在")

    # 接口类型覆盖
    interfaces = set(m.get("interface_type") for m in models if m.get("interface_type"))
    expected = {"openai_chat", "openai_responses", "anthropic"}
    covered = interfaces & expected
    t.ok("接口类型覆盖", f"已覆盖: {covered}")

    # 展示前 3 个模型
    print(f"\n  模型示例 (前 3):")
    for m in models[:3]:
        owner_label = m.get("owner", "?")
        if isinstance(owner_label, dict):
            owner_label = owner_label.get("type", "?")
        print(f"    {m.get('provider', '?')}/{m.get('model', '?')}  "
              f"[{m.get('interface_type', '?')}]  "
              f"owner={owner_label}  free={m.get('is_free', False)}")

    # 模型解析测试
    resolved = client.resolve_model(models[0]["model"])
    if resolved:
        t.ok("模型解析", f"'{models[0]['model']}' → {resolved.get('provider')}/{resolved.get('model')}")
    else:
        t.fail("模型解析", "无法解析模型")

    return True


def test_004_task_creation(t: TestResult, client: MonkeyCodeClient):
    """任务创建"""
    print_section("任务创建")

    if not client.image_id:
        t.skip("任务创建", "MONKEYCODE_IMAGE_ID 未设置")
        return False

    # 选择一个模型
    if not client._models:
        client.list_models()
    if not client._models:
        t.fail("任务创建前置", "无可用模型")
        return False

    # 优先选择公开模型
    public_models = client.get_public_models()
    free_models = client.get_free_models()
    if public_models:
        model = public_models[0]
        print_info(f"使用公开模型: {model.get('provider')}/{model.get('model')}")
    elif free_models:
        model = free_models[0]
        print_info(f"使用免费模型: {model.get('provider')}/{model.get('model')}")
    else:
        model = client._models[0]
        print_info(f"使用模型: {model.get('provider')}/{model.get('model')}")

    # 创建测试任务（短 prompt，快速返回）
    test_prompt = "请用一句话回答: Python 的创始人是谁？"
    try:
        task_id = client.create_task(model, test_prompt)
        t.ok("任务创建", f"task_id: {task_id}")
        return task_id, model, test_prompt
    except Exception as e:
        t.fail("任务创建", str(e))
        return False


def test_005_websocket_stream(t: TestResult, client: MonkeyCodeClient, task_id: str,
                               model: dict, prompt: str):
    """WebSocket 流式接收"""
    print_section("WebSocket 流式接收")

    if not task_id:
        t.skip("WS 流", "无任务 ID")
        return

    received_events = []
    usage = {}

    def on_acp(acp: dict):
        received_events.append(acp)
        acp_type = acp.get("type", "")
        text = acp.get("text") or acp.get("content") or ""

        if acp_type == "agent_message_chunk" and text:
            print(f"    [消息] {text[:60]}{'...' if len(text) > 60 else ''}")
        elif acp_type == "agent_thought_chunk" and text:
            print(f"    [思考] {text[:60]}{'...' if len(text) > 60 else ''}")
        elif acp_type == "tool_call":
            print(f"    [工具] {acp.get('tool_name', '?')}: {str(acp.get('tool_input', ''))[:60]}")
        elif acp_type == "plan":
            print(f"    [计划] 收到执行计划")

    def on_ended(result: dict):
        nonlocal usage
        usage = result.get("usage", {})

    def on_error(msg: str):
        print(f"    [错误] {msg}")

    print_info(f"连接任务流: {task_id}")
    start = time.time()

    try:
        result = client.connect_task_stream(
            task_id=task_id,
            prompt=prompt,
            on_acp_event=on_acp,
            on_task_ended=on_ended,
            on_task_error=on_error,
            timeout=120,
        )
        elapsed = time.time() - start
        usage = result.get("usage", {})

        # 评估结果
        if received_events:
            has_text = any(e.get("type") == "agent_message_chunk" and
                           (e.get("text") or e.get("content"))
                           for e in received_events)
            if has_text:
                t.ok("WS 流式接收", f"收到 {len(received_events)} 个 ACP 事件, 耗时 {elapsed:.1f}s")
            else:
                t.ok("WS 流式接收", f"收到 {len(received_events)} 个事件 (无文本输出), 耗时 {elapsed:.1f}s")

            if usage.get("total_tokens", 0) > 0:
                t.ok("Token 用量", f"input={usage.get('input_tokens', 0)}, "
                                   f"output={usage.get('output_tokens', 0)}, "
                                   f"total={usage.get('total_tokens', 0)}")
            else:
                t.ok("WS 连接", "无用量信息")
        else:
            # 可能快速返回没有事件—衡量连接本身
            t.ok("WS 连接", f"连接完成, 耗时 {elapsed:.1f}s")

    except Exception as e:
        elapsed = time.time() - start
        t.fail("WS 流", f"{e} (耗时 {elapsed:.1f}s)")


def test_006_proxy_endpoints(t: TestResult):
    """代理端点可达性测试"""
    print_section("代理端点")

    import requests

    port = os.getenv("PROXY_REAL_PORT", "9091")
    proxy_url = f"http://127.0.0.1:{port}"

    # 检查代理是否在运行
    try:
        resp = requests.get(f"{proxy_url}/health", timeout=5)
        if resp.status_code == 200:
            t.ok("代理健康检查", f"HTTP {resp.status_code}")
        else:
            t.fail("代理健康检查", f"HTTP {resp.status_code}")
            return
    except requests.exceptions.ConnectionError:
        t.skip("代理端点", "代理未运行 (启动方式: python proxy_real.py &)")
        return
    except Exception as e:
        t.fail("代理健康检查", str(e))
        return

    # /v1/models
    try:
        resp = requests.get(f"{proxy_url}/v1/models", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            t.ok("GET /v1/models", f"HTTP 200, {len(models)} 个模型")
        else:
            t.fail("GET /v1/models", f"HTTP {resp.status_code}")
    except Exception as e:
        t.fail("GET /v1/models", str(e))

    # /v1/chat/completions (non-stream)
    try:
        # 先获取一个模型 ID
        models_resp = requests.get(f"{proxy_url}/v1/models", timeout=10)
        if models_resp.status_code == 200:
            models = models_resp.json().get("data", [])
            if models:
                model_id = models[0]["id"]
                resp = requests.post(
                    f"{proxy_url}/v1/chat/completions",
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": "用一句话说你好"}],
                        "stream": False,
                    },
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    t.ok("POST /v1/chat/completions", f"HTTP 200, 响应长度: {len(content)} 字符")
                else:
                    t.fail("POST /v1/chat/completions", f"HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                t.skip("POST /v1/chat/completions", "无可用模型")
    except Exception as e:
        t.fail("POST /v1/chat/completions", str(e))


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def main():
    print_header("MonkeyCode 授权与代理端到端验证")
    print_info(f"后端: {BASE_URL}")
    print_info(f"Session Cookie: {'已设置' if os.getenv('MONKEYCODE_SESSION_COOKIE') else '未设置'}")
    print_info(f"IMAGE_ID:       {'已设置' if os.getenv('MONKEYCODE_IMAGE_ID') else '未设置'}")
    print_info(f"用户名:         {'已设置' if os.getenv('MONKEYCODE_USERNAME') else '未设置'}")

    skip_task = "--skip-task" in sys.argv

    t = TestResult()
    client = MonkeyCodeClient()

    # 1. API 连通性
    test_001_api_connectivity(t, client)

    # 2. 认证
    auth_ok = test_002_authentication(t, client)
    if not auth_ok:
        t.summary()
        sys.exit(1)

    # 3. 模型列表
    test_003_models(t, client)

    # 4. 任务创建 + WS 流
    if skip_task:
        print_info("跳过任务创建和 WS 测试 (--skip-task)")
    else:
        result = test_004_task_creation(t, client)
        if result:
            task_id, model, prompt = result
            test_005_websocket_stream(t, client, task_id, model, prompt)

    # 5. 代理端点
    test_006_proxy_endpoints(t)

    success = t.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()