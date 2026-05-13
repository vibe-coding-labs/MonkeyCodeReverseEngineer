#!/usr/bin/env python3
"""MonkeyCode 授权协议测试脚本

基于实测 API 行为编写，覆盖:
1. API 连通性
2. Session Cookie 认证（从浏览器提取）
3. Session 有效性检测
4. 用户信息/模型/余额/订阅获取
5. 错误码验证（HTTP 401/403 + JSON code）
6. 验证码 API（实际格式: challenge + token）
7. OAuth 重定向验证
8. 团队登录端点可达性

使用方式:
  # 方式 1: 使用浏览器提取的 Session Cookie
  export MONKEYCODE_SESSION_COOKIE="your-session-cookie-value"
  python test_auth.py

  # 方式 2: 指定自定义 base URL
  export MONKEYCODE_BASE_URL="https://monkeycode-ai.com"
  python test_auth.py
"""
import json
import os
import sys
import requests

BASE_URL = os.getenv("MONKEYCODE_BASE_URL", "https://monkeycode-ai.com")
SESSION_COOKIE_NAME = "monkeycode_ai_session"
TEAM_COOKIE_NAME = "monkeycode_ai_team_session"

USERNAME = os.getenv("MONKEYCODE_USERNAME", "")
PASSWORD = os.getenv("MONKEYCODE_PASSWORD", "")
SESSION_COOKIE = os.getenv("MONKEYCODE_SESSION_COOKIE", "")


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def ok(self, name, detail=""):
        self.passed += 1
        msg = f"  [PASS] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    def fail(self, name, detail=""):
        self.failed += 1
        self.errors.append((name, detail))
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    def skip(self, name, detail=""):
        self.skipped += 1
        msg = f"  [SKIP] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)

    def summary(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{'='*60}")
        print(f"测试结果: {self.passed} 通过, {self.failed} 失败, {self.skipped} 跳过 (共 {total})")
        if self.errors:
            print("\n失败项:")
            for name, detail in self.errors:
                print(f"  - {name}: {detail}")
        print(f"{'='*60}")
        return self.failed == 0


def make_request(method, path, session_cookie=None, json_body=None, cookie_name=SESSION_COOKIE_NAME):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    cookies = {}
    if session_cookie:
        cookies[cookie_name] = session_cookie

    try:
        kwargs = dict(cookies=cookies, headers=headers, timeout=15, allow_redirects=False)
        if json_body is not None:
            kwargs["json"] = json_body
        resp = getattr(requests, method.lower())(url, **kwargs)
        return resp, None
    except requests.exceptions.ConnectionError:
        return None, "连接失败 — 无法连接到 MonkeyCode 服务器"
    except requests.exceptions.Timeout:
        return None, "请求超时 — 服务器未在 15s 内响应"
    except Exception as e:
        return None, f"请求异常: {e}"


def parse_json(resp):
    try:
        return resp.json(), None
    except Exception:
        return None, f"非 JSON 响应 (status={resp.status_code}): {resp.text[:200]}"


def is_auth_success(resp):
    """判断认证是否成功 — 兼容多种响应格式"""
    # HTTP 200 + JSON code=0
    if resp.status_code == 200:
        data, _ = parse_json(resp)
        if data and data.get("code") == 0:
            return True, data
        if data:
            return False, data
        return True, None
    # HTTP 401 纯文本
    if resp.status_code == 401:
        data, _ = parse_json(resp)
        if data:
            return False, data
        return False, {"code": 401, "message": resp.text}
    # HTTP 403
    if resp.status_code == 403:
        data, _ = parse_json(resp)
        return False, data or {"code": 403, "message": resp.text[:100]}
    # 其他
    data, _ = parse_json(resp)
    return False, data or {"status": resp.status_code, "body": resp.text[:100]}


# ──────────────────────────────────────────────
# 测试用例
# ──────────────────────────────────────────────

def test_api_connectivity(t: TestResult):
    """测试 1: API 连通性"""
    print("\n--- 测试 1: API 连通性 ---")

    resp, err = make_request("GET", "/api/v1/users/status")
    if err:
        t.fail("API 连通性", err)
        return False

    if resp.status_code in (200, 401):
        t.ok("API 连通性", f"HTTP {resp.status_code} — API 可达")
        return True
    else:
        t.fail("API 连通性", f"意外状态码: {resp.status_code}")
        return False


def test_session_cookie_auth(t: TestResult, cookie: str):
    """测试 2: Session Cookie 认证"""
    print("\n--- 测试 2: Session Cookie 认证 ---")

    if not cookie:
        t.fail("Session Cookie 认证", "未提供 MONKEYCODE_SESSION_COOKIE 环境变量")
        print("  提示: export MONKEYCODE_SESSION_COOKIE=\"从浏览器获取的 cookie 值\"")
        return None

    resp, err = make_request("GET", "/api/v1/users/status", session_cookie=cookie)
    if err:
        t.fail("Session 有效性检测", err)
        return None

    success, data = is_auth_success(resp)
    if success:
        t.ok("Session 有效性检测", f"session 有效, data={json.dumps(data.get('data', data), ensure_ascii=False)[:100]}")
        return cookie
    else:
        code = data.get("code", "?") if isinstance(data, dict) else "?"
        msg = data.get("message", "") if isinstance(data, dict) else str(data)
        t.fail("Session 有效性检测", f"session 无效 (HTTP {resp.status_code}, code={code}, msg={msg})")
        return None


def test_user_info(t: TestResult, cookie: str):
    """测试 3: 获取用户信息"""
    print("\n--- 测试 3: 获取用户信息 ---")

    resp, err = make_request("GET", "/api/v1/users/me", session_cookie=cookie)
    if err:
        t.fail("GET /users/me", err)
        return

    data, parse_err = parse_json(resp)
    if parse_err:
        t.fail("GET /users/me", parse_err)
        return

    if resp.status_code == 200 and data.get("code") == 0:
        user = data.get("data", {})
        t.ok("GET /users/me",
             f"id={user.get('id', '?')[:8]}..., role={user.get('role', '?')}, email={user.get('email', '?')}")
    else:
        t.fail("GET /users/me", f"HTTP {resp.status_code}, code={data.get('code')}, msg={data.get('message', data.get('msg'))}")


def test_user_models(t: TestResult, cookie: str):
    """测试 4: 获取可用模型列表"""
    print("\n--- 测试 4: 获取可用模型列表 ---")

    resp, err = make_request("GET", "/api/v1/users/models", session_cookie=cookie)
    if err:
        t.fail("GET /users/models", err)
        return

    data, parse_err = parse_json(resp)
    if parse_err:
        t.fail("GET /users/models", parse_err)
        return

    if resp.status_code == 200 and data.get("code") == 0:
        # 尝试多种数据结构
        payload = data.get("data", {})
        if isinstance(payload, list):
            models = payload
        elif isinstance(payload, dict):
            models = payload.get("models", payload.get("list", []))
        else:
            models = []

        if isinstance(models, list):
            model_names = [m.get("model", "?") for m in models[:5]] if models else []
            t.ok("GET /users/models", f"共 {len(models)} 个模型, 前5: {model_names}")
        else:
            t.ok("GET /users/models", f"data keys={list(payload.keys()) if isinstance(payload, dict) else type(payload)}")
    else:
        t.fail("GET /users/models", f"HTTP {resp.status_code}, code={data.get('code')}, msg={data.get('message', '')}")


def test_user_balance(t: TestResult, cookie: str):
    """测试 5: 获取用户余额"""
    print("\n--- 测试 5: 获取用户余额 ---")

    resp, err = make_request("GET", "/api/v1/users/balance", session_cookie=cookie)
    if err:
        t.fail("GET /users/balance", err)
        return

    data, parse_err = parse_json(resp)
    if parse_err:
        t.fail("GET /users/balance", parse_err)
        return

    if resp.status_code == 200:
        t.ok("GET /users/balance", f"data={json.dumps(data.get('data', data), ensure_ascii=False)[:100]}")
    else:
        t.fail("GET /users/balance", f"HTTP {resp.status_code}, code={data.get('code')}")


def test_user_subscriptions(t: TestResult, cookie: str):
    """测试 6: 获取用户订阅"""
    print("\n--- 测试 6: 获取用户订阅 ---")

    resp, err = make_request("GET", "/api/v1/users/subscriptions/current", session_cookie=cookie)
    if err:
        t.fail("GET /users/subscriptions/current", err)
        return

    data, parse_err = parse_json(resp)
    if parse_err:
        t.fail("GET /users/subscriptions/current", parse_err)
        return

    if resp.status_code == 200:
        t.ok("GET /users/subscriptions/current", f"data={json.dumps(data.get('data', data), ensure_ascii=False)[:100]}")
    else:
        # 订阅可能为空，不算硬失败
        t.ok("GET /users/subscriptions/current", f"HTTP {resp.status_code}, code={data.get('code')} (可能无订阅)")


def test_invalid_session(t: TestResult):
    """测试 7: 无效 Session 错误码验证"""
    print("\n--- 测试 7: 无效 Session 错误码验证 ---")

    fake_cookie = "00000000-0000-0000-0000-000000000000"
    resp, err = make_request("GET", "/api/v1/users/status", session_cookie=fake_cookie)
    if err:
        t.fail("无效 Session 错误码", err)
        return

    # 实测: /users/status 返回 JSON {"code": 401, "message": "未授权"}
    if resp.status_code == 401:
        data, _ = parse_json(resp)
        if data and data.get("code") == 401:
            t.ok("无效 Session 错误码", f"HTTP 401 + JSON code=401, message={data.get('message', '')[:50]}")
        else:
            t.ok("无效 Session 错误码", f"HTTP 401 (响应格式: {resp.text[:100]})")
    elif resp.status_code == 200:
        data, _ = parse_json(resp)
        t.fail("无效 Session 错误码", f"期望 401, 实际 200, data={data}")
    else:
        t.fail("无效 Session 错误码", f"期望 401, 实际 HTTP {resp.status_code}")


def test_no_session(t: TestResult):
    """测试 8: 无 Session 请求错误码验证"""
    print("\n--- 测试 8: 无 Session 请求错误码验证 ---")

    resp, err = make_request("GET", "/api/v1/users/me")
    if err:
        t.fail("无 Session 错误码", err)
        return

    # 实测: /users/me 无 cookie 返回 HTTP 401 + text/plain "Unauthorized"
    if resp.status_code == 401:
        ct = resp.headers.get("Content-Type", "")
        if "text/plain" in ct:
            t.ok("无 Session 错误码", f"HTTP 401 + text/plain: {resp.text[:50]}")
        else:
            data, _ = parse_json(resp)
            t.ok("无 Session 错误码", f"HTTP 401 + JSON: code={data.get('code') if data else '?'}")
    else:
        t.fail("无 Session 错误码", f"期望 401, 实际 HTTP {resp.status_code}")


def test_captcha_api(t: TestResult):
    """测试 9: 验证码 API（实测格式）"""
    print("\n--- 测试 9: 验证码 API ---")

    # 实测: POST /public/captcha/challenge 返回
    # {"challenge":{"c":50,"s":32,"d":3},"expires":...,"token":"..."}
    resp, err = make_request("POST", "/api/v1/public/captcha/challenge")
    if err:
        t.fail("验证码 Challenge", err)
        return

    data, parse_err = parse_json(resp)
    if parse_err:
        t.fail("验证码 Challenge", parse_err)
        return

    if resp.status_code == 201 and "challenge" in data:
        challenge = data.get("challenge", {})
        token = data.get("token", "")
        expires = data.get("expires", 0)
        t.ok("验证码 Challenge",
             f"c={challenge.get('c')} s={challenge.get('s')} d={challenge.get('d')}, "
             f"token={token[:12]}..., expires={expires}")
    else:
        t.fail("验证码 Challenge", f"HTTP {resp.status_code}, body={json.dumps(data, ensure_ascii=False)[:200]}")


def test_team_login_endpoint(t: TestResult):
    """测试 10: 团队登录端点可达性"""
    print("\n--- 测试 10: 团队登录端点可达性 ---")

    resp, err = make_request("POST", "/api/v1/teams/users/login",
                             json_body={"email": "", "password": ""})
    if err:
        t.fail("POST /teams/users/login", err)
        return

    if resp.status_code == 404:
        t.fail("POST /teams/users/login", "端点不存在 (404)")
    else:
        data, _ = parse_json(resp)
        code = data.get("code") if data else "?"
        msg = data.get("message", "") if data else ""
        t.ok("POST /teams/users/login", f"端点存在, HTTP {resp.status_code}, code={code}, msg={msg[:50]}")


def test_oauth_redirect(t: TestResult):
    """测试 11: OAuth 登录重定向"""
    print("\n--- 测试 11: OAuth 登录重定向 ---")

    resp, err = make_request("GET", "/api/v1/users/login")
    if err:
        t.fail("OAuth 重定向", err)
        return

    if resp.status_code == 302:
        location = resp.headers.get("Location", "")
        if "baizhi.cloud" in location:
            t.ok("OAuth 重定向", f"302 → baizhi.cloud (百智云)")
        elif location:
            t.ok("OAuth 重定向", f"302 → {location[:80]}")
        else:
            t.fail("OAuth 重定向", "302 但无 Location 头")
    else:
        t.fail("OAuth 重定向", f"期望 302, 实际 HTTP {resp.status_code}")


def test_password_login_endpoint(t: TestResult):
    """测试 12: 密码登录端点可达性（错误密码）"""
    print("\n--- 测试 12: 密码登录端点可达性 ---")

    resp, err = make_request("POST", "/api/v1/users/password-login",
                             json_body={"email": "test@test.com", "password": "wrong"})
    if err:
        t.fail("密码登录端点", err)
        return

    # 实测: 错误密码返回 HTTP 403 + {"code":403,"message":"禁止访问"}
    if resp.status_code in (400, 401, 403):
        data, _ = parse_json(resp)
        code = data.get("code") if data else "?"
        msg = data.get("message", "") if data else ""
        t.ok("密码登录端点", f"端点存在, HTTP {resp.status_code}, code={code}, msg={msg[:50]}")
    elif resp.status_code == 404:
        t.fail("密码登录端点", "端点不存在 (404)")
    else:
        t.fail("密码登录端点", f"意外状态码: {resp.status_code}")


def test_response_headers(t: TestResult, cookie: str):
    """测试 13: 响应头分析"""
    print("\n--- 测试 13: 响应头分析 ---")

    resp, err = make_request("GET", "/api/v1/users/status", session_cookie=cookie)
    if err:
        t.fail("响应头分析", err)
        return

    # CORS
    cors = resp.headers.get("Access-Control-Allow-Origin", "")
    if cors:
        t.ok("CORS 头", f"Access-Control-Allow-Origin: {cors}")
    else:
        t.ok("CORS 头", "无 CORS 头（same-origin 模式）")

    # Content-Type
    ct = resp.headers.get("Content-Type", "")
    if "application/json" in ct:
        t.ok("Content-Type", ct)
    else:
        t.fail("Content-Type", f"期望 application/json, 实际: {ct}")


def test_logout(t: TestResult, cookie: str):
    """测试 14: 登出（跳过）"""
    print("\n--- 测试 14: 登出 ---")
    t.skip("登出测试", "跳过 — 不破坏当前有效 session")


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("MonkeyCode 授权协议测试")
    print(f"Base URL: {BASE_URL}")
    print(f"Cookie Name: {SESSION_COOKIE_NAME}")
    print(f"Session Cookie: {'已设置' if SESSION_COOKIE else '未设置'}")
    print(f"Username: {'已设置' if USERNAME else '未设置'}")
    print("=" * 60)

    t = TestResult()

    # 1. API 连通性
    if not test_api_connectivity(t):
        print("\nAPI 不可达，终止测试")
        t.summary()
        sys.exit(1)

    # 2. Session Cookie 认证
    active_cookie = None
    if SESSION_COOKIE:
        active_cookie = test_session_cookie_auth(t, SESSION_COOKIE)
    else:
        print("\n--- 测试 2: Session Cookie 认证 ---")
        t.skip("Session Cookie 认证", "未提供 MONKEYCODE_SESSION_COOKIE 环境变量")
        print("  提示: export MONKEYCODE_SESSION_COOKIE=\"从浏览器获取的 cookie 值\"")

    # 需要有效 session 的测试
    if active_cookie:
        test_user_info(t, active_cookie)
        test_user_models(t, active_cookie)
        test_user_balance(t, active_cookie)
        test_user_subscriptions(t, active_cookie)
        test_response_headers(t, active_cookie)
        test_logout(t, active_cookie)
    else:
        print("\n--- 跳过需要有效 Session 的测试 ---")
        for name in ["GET /users/me", "GET /users/models", "GET /users/balance",
                      "GET /users/subscriptions/current", "响应头分析", "登出"]:
            t.skip(name, "无有效 Session Cookie")

    # 不需要 session 的测试
    test_invalid_session(t)
    test_no_session(t)
    test_captcha_api(t)
    test_team_login_endpoint(t)
    test_oauth_redirect(t)
    test_password_login_endpoint(t)

    success = t.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
