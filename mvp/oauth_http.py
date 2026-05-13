#!/usr/bin/env python3
"""MonkeyCode OAuth 授权协议纯 HTTP 模拟

完整流程（纯 HTTP，无需浏览器）:
1. 获取 OAuth 重定向 URL（百智云）
2. 用户在浏览器中手动登录百智云
3. 用户复制回调 URL（含 code 参数）
4. 脚本用 code 完成授权，获取 session cookie

或者使用百智云手机号登录 API:
1. 获取 SCaptcha 验证码 token
2. 发送短信验证码 (POST /api/v1/user/phone_code)
3. 用户输入短信验证码
4. 手机号登录 (POST /api/v1/user/login/phone)
5. 获取百智云 session
6. 调用百智云 OAuth authorize 获取 code
7. 用 code 回调 MonkeyCode 获取 session cookie

使用方式:
  # 方式 1: 手机号登录（推荐）
  python oauth_http.py --phone 13800138000

  # 方式 2: 手动回调
  python oauth_http.py --callback-url "https://monkeycode-ai.com/api/v1/users/baizhi/callback?code=xxx&state=xxx"

  # 方式 3: 验证已有 session
  python oauth_http.py --verify "your-session-cookie"
"""
import argparse
import json
import os
import sys
import time
import requests
from urllib.parse import urlparse, parse_qs

BASE_URL = os.getenv("MONKEYCODE_BASE_URL", "https://monkeycode-ai.com")
BAIZHI_URL = "https://baizhi.cloud"
SESSION_COOKIE_NAME = "monkeycode_ai_session"
SCAPTCHA_BUSINESS_ID = "0196c95c-620c-7cde-9c2d-b10d0faf5583"
SCAPTCHA_API = f"https://{SCAPTCHA_BUSINESS_ID}.safepoint.s-captcha-r1.com"


def get_oauth_redirect_url():
    """Step 1: 获取 OAuth 重定向 URL"""
    print("[Step 1] 获取 OAuth 重定向 URL...")
    resp = requests.get(f"{BASE_URL}/api/v1/users/login", allow_redirects=False, timeout=15)
    if resp.status_code != 302:
        print(f"[错误] 期望 302 重定向, 实际 {resp.status_code}")
        return None, None

    location = resp.headers.get("Location", "")
    print(f"[Step 1] 重定向到: {location[:80]}...")

    # 解析 OAuth 参数
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    state = params.get("state", [""])[0]
    print(f"[Step 1] state: {state}")
    return location, state


def get_scaptcha_token():
    """获取 SCaptcha 验证码 token"""
    print("[SCaptcha] 获取验证码 token...")
    resp = requests.post(f"{SCAPTCHA_API}/v1/api/challenge", json={
        "business_id": SCAPTCHA_BUSINESS_ID
    }, timeout=15)

    if resp.status_code != 200:
        print(f"[SCaptcha] 错误: {resp.status_code}, {resp.text[:200]}")
        return None

    data = resp.json()
    if not data.get("success"):
        print(f"[SCaptcha] 失败: {data}")
        return None

    token = data.get("data", {}).get("token", "")
    challenge = data.get("data", {}).get("challenge", {})
    action = data.get("data", {}).get("action", "")

    if action == "error":
        error = data.get("data", {}).get("error", "")
        print(f"[SCaptcha] 验证码错误: {error}")
        # 即使返回 "no money" 错误，token 仍然有效
        if token:
            print(f"[SCaptcha] token 仍然有效: {token[:20]}...")
            return token
        return None

    print(f"[SCaptcha] token: {token[:20]}..., challenge type: {challenge.get('type', 'unknown')}")
    return token


def send_sms_code(phone, captcha_token):
    """Step 2: 发送短信验证码"""
    print(f"[Step 2] 发送短信验证码到 {phone}...")
    resp = requests.post(f"{BAIZHI_URL}/api/v1/user/phone_code", json={
        "phone": phone,
        "kind": "login",
        "token": captcha_token
    }, timeout=15)

    if resp.status_code != 200:
        print(f"[Step 2] 错误: {resp.status_code}, {resp.text[:200]}")
        return False

    data = resp.json()
    if data.get("code") == 0:
        print(f"[Step 2] 短信验证码发送成功!")
        return True
    else:
        print(f"[Step 2] 发送失败: code={data.get('code')}, msg={data.get('message')}")
        return False


def login_with_phone(phone, code):
    """Step 3: 手机号登录百智云"""
    print(f"[Step 3] 手机号登录百智云...")
    resp = requests.post(f"{BAIZHI_URL}/api/v1/user/login/phone", json={
        "phone": phone,
        "code": code
    }, timeout=15)

    if resp.status_code != 200:
        print(f"[Step 3] 错误: {resp.status_code}, {resp.text[:200]}")
        return None

    data = resp.json()
    if data.get("code") == 0:
        print(f"[Step 3] 登录成功!")
        # 百智云登录后设置 cookie
        return data.get("data", {})
    else:
        print(f"[Step 3] 登录失败: code={data.get('code')}, msg={data.get('message')}")
        return None


def oauth_authorize(session_cookies, client_id, redirect_uri, scope, state):
    """Step 4: 调用百智云 OAuth authorize 获取 code"""
    print(f"[Step 4] OAuth 授权...")
    resp = requests.get(f"{BAIZHI_URL}/api/v1/oauth/authorize", params={
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "response_type": "code"
    }, cookies=session_cookies, allow_redirects=False, timeout=15)

    if resp.status_code == 302:
        location = resp.headers.get("Location", "")
        print(f"[Step 4] 授权重定向: {location[:80]}...")
        # 解析 code
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        if code:
            print(f"[Step 4] OAuth code: {code[:20]}...")
            return code, location
        else:
            error = params.get("error", [""])[0]
            print(f"[Step 4] 授权失败: error={error}")
            return None, location
    else:
        print(f"[Step 4] 意外状态码: {resp.status_code}")
        print(f"[Step 4] Body: {resp.text[:300]}")
        return None, None


def monkeycode_callback(callback_url):
    """Step 5: 用 OAuth code 回调 MonkeyCode 获取 session cookie"""
    print(f"[Step 5] MonkeyCode 回调...")
    resp = requests.get(callback_url, allow_redirects=False, timeout=15)

    print(f"[Step 5] 状态码: {resp.status_code}")
    print(f"[Step 5] 重定向: {resp.headers.get('Location', '无')}")

    # 提取 session cookie
    cookies = resp.cookies
    if SESSION_COOKIE_NAME in cookies:
        session_cookie = cookies[SESSION_COOKIE_NAME]
        print(f"[Step 5] Session Cookie: {session_cookie[:20]}...")
        return session_cookie

    # 尝试从 Set-Cookie header 提取
    set_cookie = resp.headers.get("Set-Cookie", "")
    if SESSION_COOKIE_NAME in set_cookie:
        import re
        match = re.search(rf"{SESSION_COOKIE_NAME}=([^;]+)", set_cookie)
        if match:
            session_cookie = match.group(1)
            print(f"[Step 5] Session Cookie (from header): {session_cookie[:20]}...")
            return session_cookie

    print(f"[Step 5] 未获取到 Session Cookie")
    print(f"[Step 5] Cookies: {dict(cookies)}")
    return None


def verify_session(session_cookie):
    """验证 session cookie"""
    print(f"\n[验证] 验证 Session Cookie...")
    url = f"{BASE_URL}/api/v1/users/status"
    resp = requests.get(url, cookies={SESSION_COOKIE_NAME: session_cookie}, timeout=15)

    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 0:
            print(f"[验证] Session 有效!")
            return True, data

    print(f"[验证] Session 无效: status={resp.status_code}")
    return False, None


def get_user_info(session_cookie):
    """获取用户信息"""
    url = f"{BASE_URL}/api/v1/users/me"
    resp = requests.get(url, cookies={SESSION_COOKIE_NAME: session_cookie}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
    return None


def phone_login_flow(phone):
    """完整的手机号登录流程"""
    # Step 1: 获取 OAuth 重定向 URL
    oauth_url, state = get_oauth_redirect_url()
    if not oauth_url:
        return None

    # 解析 OAuth 参数
    parsed = urlparse(oauth_url)
    params = parse_qs(parsed.query)
    client_id = params.get("client_id", [""])[0]
    redirect_uri = params.get("redirect_uri", [""])[0]
    scope = params.get("scope", [""])[0]

    # Step 2: 获取 SCaptcha token
    captcha_token = get_scaptcha_token()
    if not captcha_token:
        print("[错误] 无法获取 SCaptcha token")
        return None

    # Step 3: 发送短信验证码
    if not send_sms_code(phone, captcha_token):
        print("[错误] 短信验证码发送失败")
        return None

    # Step 4: 用户输入验证码
    code = input("[Step 4] 请输入收到的短信验证码: ")

    # Step 5: 手机号登录百智云
    login_result = login_with_phone(phone, code)
    if not login_result:
        print("[错误] 百智云登录失败")
        return None

    # Step 6: OAuth 授权
    # 注意：百智云登录后的 session cookie 需要从 login API 响应中获取
    # 由于百智云使用 cookie-based session，我们需要跟踪 cookies
    # 这里使用 requests.Session 来自动管理 cookies
    session = requests.Session()

    # 重新登录以获取 cookie
    resp = session.post(f"{BAIZHI_URL}/api/v1/user/login/phone", json={
        "phone": phone,
        "code": code
    }, timeout=15)

    print(f"[Step 6] 百智云 cookies: {dict(session.cookies)}")

    # 检查是否已登录
    resp = session.get(f"{BAIZHI_URL}/api/v1/user/is_logged_in", timeout=15)
    print(f"[Step 6] is_logged_in: {resp.status_code}, {resp.text[:200]}")

    # OAuth 授权
    oauth_code, callback_url = oauth_authorize(
        dict(session.cookies), client_id, redirect_uri, scope, state
    )

    if not oauth_code:
        print("[错误] OAuth 授权失败")
        print("[提示] 可能需要先在浏览器中完成百智云登录")
        return None

    # Step 7: MonkeyCode 回调
    session_cookie = monkeycode_callback(callback_url)
    return session_cookie


def callback_flow(callback_url):
    """使用已有的回调 URL 获取 session"""
    print(f"[回调] 使用回调 URL: {callback_url[:80]}...")
    session_cookie = monkeycode_callback(callback_url)
    return session_cookie


def main():
    parser = argparse.ArgumentParser(description="MonkeyCode OAuth HTTP 授权")
    parser.add_argument("--phone", default=os.getenv("MONKEYCODE_PHONE", ""),
                        help="手机号")
    parser.add_argument("--callback-url", default="",
                        help="OAuth 回调 URL (含 code 和 state)")
    parser.add_argument("--verify", default="",
                        help="验证已有的 session cookie")
    args = parser.parse_args()

    print("=" * 60)
    print("MonkeyCode OAuth HTTP 授权工具")
    print(f"Base URL: {BASE_URL}")
    print(f"Cookie Name: {SESSION_COOKIE_NAME}")
    print(f"百智云: {BAIZHI_URL}")
    print("=" * 60)

    # 验证已有 session
    if args.verify:
        success, data = verify_session(args.verify)
        if success:
            user_info = get_user_info(args.verify)
            if user_info:
                print(f"[验证] 用户: id={user_info.get('id', '?')[:8]}..., "
                      f"role={user_info.get('role', '?')}, "
                      f"email={user_info.get('email', '?')}")
        sys.exit(0 if success else 1)

    # 回调模式
    if args.callback_url:
        session_cookie = callback_flow(args.callback_url)
    elif args.phone:
        # 手机号登录模式
        session_cookie = phone_login_flow(args.phone)
    else:
        print("\n请指定登录方式:")
        print("  --phone 13800138000    手机号登录")
        print("  --callback-url URL     使用 OAuth 回调 URL")
        print("  --verify COOKIE        验证已有 session")
        sys.exit(1)

    if session_cookie:
        print(f"\n{'='*60}")
        print(f"登录成功!")
        print(f"Session Cookie: {session_cookie}")
        print(f"\n使用方式:")
        print(f"  export MONKEYCODE_SESSION_COOKIE=\"{session_cookie}\"")
        print(f"  python test_auth.py")
        print(f"  python oauth_http.py --verify \"{session_cookie}\"")
        print(f"{'='*60}")

        # 验证
        success, data = verify_session(session_cookie)
        if success:
            user_info = get_user_info(session_cookie)
            if user_info:
                print(f"[验证] 用户: id={user_info.get('id', '?')[:8]}..., "
                      f"role={user_info.get('role', '?')}, "
                      f"email={user_info.get('email', '?')}")

        # 保存
        with open(os.path.join(os.path.dirname(__file__), ".session"), "w") as f:
            f.write(session_cookie)
        print(f"[保存] Session 已保存到 mvp/.session")
        sys.exit(0)
    else:
        print("\n登录失败 — 未获取到 Session Cookie")
        sys.exit(1)


if __name__ == "__main__":
    main()