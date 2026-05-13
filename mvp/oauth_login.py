#!/usr/bin/env python3
"""MonkeyCode 百智云 OAuth 自动登录脚本

使用 Playwright 模拟浏览器完成 OAuth 授权流程:
1. 打开 MonkeyCode → 重定向到百智云登录页面
2. 在百智云输入手机号 + 短信验证码
3. 通过 SCaptcha 验证码（长亭科技验证码）
4. 授权后百智云回调 MonkeyCode → 获取 session cookie

使用方式:
  # 方式 1: 交互式（需要手动输入验证码）
  python oauth_login.py

  # 方式 2: 指定手机号
  python oauth_login.py --phone 13800138000

  # 方式 3: 自动模式（需要短信 API）
  python oauth_login.py --phone 13800138000 --sms-api http://your-sms-api/get-code

  # 方式 4: 仅获取 session（从浏览器提取）
  python oauth_login.py --extract-only

环境变量:
  MONKEYCODE_BASE_URL — MonkeyCode 服务地址 (默认 https://monkeycode-ai.com)
  MONKEYCODE_PHONE — 手机号
  MONKEYCODE_SMS_API — 短信验证码获取 API
"""
import argparse
import json
import os
import sys
import time
import requests

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("需要安装 playwright: pip install playwright && python -m playwright install chromium")
    sys.exit(1)

BASE_URL = os.getenv("MONKEYCODE_BASE_URL", "https://monkeycode-ai.com")
SESSION_COOKIE_NAME = "monkeycode_ai_session"


def extract_session_from_browser(context, cookie_name=SESSION_COOKIE_NAME):
    """从浏览器上下文中提取 session cookie"""
    cookies = context.cookies()
    for cookie in cookies:
        if cookie["name"] == cookie_name:
            return cookie["value"]
    return None


def verify_session(session_cookie, base_url=BASE_URL):
    """验证 session cookie 是否有效"""
    url = f"{base_url}/api/v1/users/status"
    resp = requests.get(url, cookies={SESSION_COOKIE_NAME: session_cookie}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 0:
            return True, data
    return False, {"status": resp.status_code, "body": resp.text[:200]}


def get_user_info(session_cookie, base_url=BASE_URL):
    """获取用户信息"""
    url = f"{base_url}/api/v1/users/me"
    resp = requests.get(url, cookies={SESSION_COOKIE_NAME: session_cookie}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
    return None


def get_user_models(session_cookie, base_url=BASE_URL):
    """获取可用模型列表"""
    url = f"{base_url}/api/v1/users/models"
    resp = requests.get(url, cookies={SESSION_COOKIE_NAME: session_cookie}, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
    return None


def oauth_login(phone=None, sms_api=None, headless=False):
    """使用 Playwright 完成 OAuth 登录流程"""
    session_cookie = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Step 1: 打开 MonkeyCode 登录页面
        print("[OAuth] 打开 MonkeyCode 登录页面...")
        page.goto(f"{BASE_URL}/api/v1/users/login", wait_until="networkidle", timeout=30000)

        # 等待重定向到百智云
        current_url = page.url
        print(f"[OAuth] 当前页面: {current_url}")

        # 检查是否在百智云登录页面
        if "baizhi.cloud" not in current_url:
            # 可能已经重定向到百智云登录页面
            page.wait_for_url("**/sign-in**", timeout=15000)
            current_url = page.url
            print(f"[OAuth] 重定向到: {current_url}")

        # Step 2: 在百智云登录页面输入手机号
        print("[OAuth] 在百智云登录页面...")

        # 等待登录表单加载
        page.wait_for_load_state("networkidle", timeout=15000)

        # 查找手机号输入框
        phone_input = None
        for selector in [
            "input[type='tel']",
            "input[name='phone']",
            "input[placeholder*='手机']",
            "input[placeholder*='phone']",
            "input[id*='phone']",
        ]:
            try:
                phone_input = page.locator(selector).first
                if phone_input.is_visible(timeout=3000):
                    break
            except PlaywrightTimeout:
                continue

        if phone_input:
            # 输入手机号
            if not phone:
                phone = input("[OAuth] 请输入手机号: ")
            phone_input.fill(phone)
            print(f"[OAuth] 手机号已输入: {phone}")
        else:
            print("[OAuth] 未找到手机号输入框，请手动输入")
            if not headless:
                print("[OAuth] 请在浏览器中手动输入手机号")

        # Step 3: 点击发送验证码按钮
        print("[OAuth] 点击发送验证码按钮...")

        # 先需要通过 SCaptcha 验证码
        # SCaptcha 是长亭科技的验证码，需要点击验证按钮
        captcha_btn = None
        for selector in [
            "button[class*='captcha']",
            "div[class*='captcha']",
            "#captcha-btn",
            "[data-testid*='captcha']",
            "button:has-text('验证')",
            "button:has-text('点击验证')",
        ]:
            try:
                captcha_btn = page.locator(selector).first
                if captcha_btn.is_visible(timeout=3000):
                    break
            except PlaywrightTimeout:
                continue

        if captcha_btn:
            print("[OAuth] 找到验证码按钮，点击...")
            captcha_btn.click()
            # SCaptcha 验证码可能需要交互式完成
            # 等待验证码完成
            print("[OAuth] 请在浏览器中完成验证码验证")
            print("[OAuth] 等待验证码验证完成...")
            # 等待发送验证码按钮变为可点击状态
            time.sleep(5)
        else:
            print("[OAuth] 未找到验证码按钮（可能自动完成或不需要）")

        # 点击发送验证码按钮
        send_code_btn = None
        for selector in [
            "button:has-text('发送验证码')",
            "button:has-text('获取验证码')",
            "button:has-text('发送')",
            "button:has-text('获取')",
            "button[class*='send']",
            "button[class*='code']",
        ]:
            try:
                send_code_btn = page.locator(selector).first
                if send_code_btn.is_visible(timeout=3000):
                    break
            except PlaywrightTimeout:
                continue

        if send_code_btn:
            print("[OAuth] 点击发送验证码...")
            send_code_btn.click()
            time.sleep(2)
        elif not headless:
            print("[OAuth] 未找到发送验证码按钮，请手动点击")

        # Step 4: 输入短信验证码
        print("[OAuth] 输入短信验证码...")

        if sms_api:
            # 自动获取验证码
            print(f"[OAuth] 从短信 API 获取验证码: {sms_api}")
            for attempt in range(10):
                try:
                    resp = requests.get(sms_api, timeout=10)
                    code = resp.json().get("code", resp.text.strip())
                    if code and len(code) >= 4:
                        break
                except Exception:
                    pass
                time.sleep(3)
        else:
            # 手动输入验证码
            if headless:
                print("[OAuth] 无头模式下无法手动输入验证码，需要 sms_api")
                browser.close()
                return None
            code = input("[OAuth] 请输入短信验证码: ")

        # 查找验证码输入框
        code_input = None
        for selector in [
            "input[name='code']",
            "input[placeholder*='验证码']",
            "input[placeholder*='code']",
            "input[type='text']:near(button:has-text('登录'))",
        ]:
            try:
                code_input = page.locator(selector).first
                if code_input.is_visible(timeout=3000):
                    break
            except PlaywrightTimeout:
                continue

        if code_input and code:
            code_input.fill(code)
            print(f"[OAuth] 验证码已输入: {code}")
        elif not headless:
            print("[OAuth] 请在浏览器中手动输入验证码")

        # Step 5: 点击登录按钮
        print("[OAuth] 点击登录按钮...")

        login_btn = None
        for selector in [
            "button:has-text('登录')",
            "button:has-text('Login')",
            "button[type='submit']",
            "button[class*='login']",
        ]:
            try:
                login_btn = page.locator(selector).first
                if login_btn.is_visible(timeout=3000):
                    break
            except PlaywrightTimeout:
                continue

        if login_btn:
            login_btn.click()
            print("[OAuth] 已点击登录按钮")
        elif not headless:
            print("[OAuth] 请手动点击登录按钮")

        # Step 6: 等待 OAuth 授权确认页面
        print("[OAuth] 等待授权确认页面...")

        # 可能出现授权确认页面
        try:
            page.wait_for_url("**/oauth/authorize**", timeout=10000)
            print(f"[OAuth] 授权确认页面: {page.url}")

            # 点击"确认授权"按钮
            authorize_btn = None
            for selector in [
                "button:has-text('确认授权')",
                "button:has-text('授权')",
                "button:has-text('Authorize')",
                "button[class*='authorize']",
                "button[class*='confirm']",
            ]:
                try:
                    authorize_btn = page.locator(selector).first
                    if authorize_btn.is_visible(timeout=3000):
                        break
                except PlaywrightTimeout:
                    continue

            if authorize_btn:
                authorize_btn.click()
                print("[OAuth] 已点击确认授权")
            elif not headless:
                print("[OAuth] 请手动点击确认授权按钮")
        except PlaywrightTimeout:
            print("[OAuth] 可能已自动授权，继续等待回调...")

        # Step 7: 等待回调到 MonkeyCode
        print("[OAuth] 等待回调到 MonkeyCode...")

        try:
            page.wait_for_url(f"{BASE_URL}/**", timeout=30000)
            print(f"[OAuth] 回调完成: {page.url}")
        except PlaywrightTimeout:
            print("[OAuth] 回调超时，检查当前页面...")
            print(f"[OAuth] 当前 URL: {page.url}")

        # 等待页面加载完成
        time.sleep(3)

        # Step 8: 提取 session cookie
        session_cookie = extract_session_from_browser(context)
        if session_cookie:
            print(f"[OAuth] Session Cookie 获取成功: {session_cookie[:20]}...")
        else:
            print("[OAuth] 未获取到 Session Cookie")
            # 尝试等待更长时间
            time.sleep(5)
            session_cookie = extract_session_from_browser(context)
            if session_cookie:
                print(f"[OAuth] Session Cookie 获取成功（延迟）: {session_cookie[:20]}...")
            else:
                print("[OAuth] 最终未获取到 Session Cookie")

        browser.close()

    return session_cookie


def interactive_login(headless=False):
    """交互式登录流程 — 用户在浏览器中操作，脚本提取 cookie"""
    session_cookie = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()

        print("[OAuth] 打开 MonkeyCode 登录页面...")
        page.goto(f"{BASE_URL}/api/v1/users/login", wait_until="domcontentloaded", timeout=30000)

        print("[OAuth] 请在浏览器中完成登录流程")
        print("[OAuth] 登录完成后，脚本将自动提取 session cookie")
        print("[OAuth] 按 Enter 键提取 cookie...")

        if headless:
            # 无头模式下等待回调
            try:
                page.wait_for_url(f"{BASE_URL}/**", timeout=120000)
                time.sleep(5)
            except PlaywrightTimeout:
                print("[OAuth] 等待超时")
        else:
            # 有头模式下等待用户操作
            input()  # 等待用户按 Enter

        session_cookie = extract_session_from_browser(context)
        if session_cookie:
            print(f"[OAuth] Session Cookie: {session_cookie[:20]}...")
        else:
            print("[OAuth] 未找到 Session Cookie")

        browser.close()

    return session_cookie


def main():
    parser = argparse.ArgumentParser(description="MonkeyCode 百智云 OAuth 自动登录")
    parser.add_argument("--phone", default=os.getenv("MONKEYCODE_PHONE", ""),
                        help="手机号")
    parser.add_argument("--sms-api", default=os.getenv("MONKEYCODE_SMS_API", ""),
                        help="短信验证码获取 API URL")
    parser.add_argument("--headless", action="store_true",
                        help="无头模式（需要 sms-api）")
    parser.add_argument("--extract-only", action="store_true",
                        help="仅提取 session（交互式浏览器登录）")
    parser.add_argument("--verify", default="",
                        help="验证已有的 session cookie")
    args = parser.parse_args()

    print("=" * 60)
    print("MonkeyCode 百智云 OAuth 登录工具")
    print(f"Base URL: {BASE_URL}")
    print(f"Cookie Name: {SESSION_COOKIE_NAME}")
    print("=" * 60)

    # 验证已有 session
    if args.verify:
        print(f"\n验证 Session Cookie: {args.verify[:20]}...")
        success, data = verify_session(args.verify)
        if success:
            print(f"[验证] Session 有效!")
            user_info = get_user_info(args.verify)
            if user_info:
                print(f"[验证] 用户: id={user_info.get('id', '?')[:8]}..., "
                      f"role={user_info.get('role', '?')}, "
                      f"email={user_info.get('email', '?')}")
            models = get_user_models(args.verify)
            if models:
                model_list = models.get("models", models.get("list", []))
                if isinstance(model_list, list):
                    print(f"[验证] 可用模型: {len(model_list)} 个")
                    for m in model_list[:5]:
                        print(f"  - {m.get('model', '?')} ({m.get('provider', '?')})")
        else:
            print(f"[验证] Session 无效: {data}")
        sys.exit(0 if success else 1)

    # 提取模式
    if args.extract_only:
        session_cookie = interactive_login(headless=args.headless)
    else:
        # OAuth 登录模式
        session_cookie = oauth_login(
            phone=args.phone,
            sms_api=args.sms_api,
            headless=args.headless
        )

    if session_cookie:
        print(f"\n{'='*60}")
        print(f"登录成功!")
        print(f"Session Cookie: {session_cookie}")
        print(f"\n使用方式:")
        print(f"  export MONKEYCODE_SESSION_COOKIE=\"{session_cookie}\"")
        print(f"  python test_auth.py")
        print(f"  python oauth_login.py --verify \"{session_cookie}\"")
        print(f"{'='*60}")

        # 验证 session
        success, data = verify_session(session_cookie)
        if success:
            print(f"\n[验证] Session 有效!")
            user_info = get_user_info(session_cookie)
            if user_info:
                print(f"[验证] 用户: id={user_info.get('id', '?')[:8]}..., "
                      f"role={user_info.get('role', '?')}, "
                      f"email={user_info.get('email', '?')}")
        else:
            print(f"\n[验证] Session 可能无效: {data}")

        # 保存到文件
        with open(os.path.join(os.path.dirname(__file__), ".session"), "w") as f:
            f.write(session_cookie)
        print(f"\n[保存] Session 已保存到 mvp/.session")

        sys.exit(0)
    else:
        print("\n登录失败 — 未获取到 Session Cookie")
        sys.exit(1)


if __name__ == "__main__":
    main()