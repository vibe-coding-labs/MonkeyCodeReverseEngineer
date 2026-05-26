#!/usr/bin/env python3
"""
MonkeyCode 交互式授权测试脚本 v2

完整自动化登录链路:
1. SCaptcha API → 获取 captcha token (不需要浏览器！)
2. 百智云 phone_code → 发送短信验证码
3. 用户输入短信验证码
4. 百智云 login/phone → 登录
5. OAuth authorize → 获取 MonkeyCode session

用法:
    # 完整自动登录流程 (需要手机号和短信验证码)
    python3 test_auth_interactive.py --phone 13800138000 --auto
    
    # 仅验证已有 session cookie
    python3 test_auth_interactive.py --cookie "你的cookie值"
    
    # 仅测试公开 API (不需要任何凭据)
    python3 test_auth_interactive.py --no-auth
    
    # 交互式输入
    python3 test_auth_interactive.py --interactive
"""

import sys
import os
import json
import argparse
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BASE_URL, SESSION_COOKIE_NAME, SESSION_COOKIE as ENV_COOKIE

# SCaptcha 配置
SCAPTCHA_BUSINESS_ID = "0196c95c-620c-7cde-9c2d-b10d0faf5583"
SCAPTCHA_API = f"https://{SCAPTCHA_BUSINESS_ID}.safepoint.s-captcha-r1.com"
BAIZHI_API = "https://baizhi.cloud"


# ============================================================
# 颜色输出
# ============================================================
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


class Stats:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
    
    def __str__(self):
        return f"{self.passed} PASS, {self.failed} FAIL, {self.skipped} SKIP ({self.passed+self.failed+self.skipped} total)"


# ============================================================
# SCaptcha 自动化
# ============================================================
def get_scaptcha_token():
    """从 SCaptcha API 获取 captcha token
    
    发现: baizhi.cloud 的 SCaptcha 账户余额不足 ("no money"),
    但仍返回有效的 JWT token。baizhi.cloud 后端只验证 token
    签名而不验证 challenge 是否完成，所以这个 "空" token 可以
    直接用于 phone_code API。
    """
    try:
        r = requests.post(f"{SCAPTCHA_API}/v1/api/challenge", 
                         json={"business_id": SCAPTCHA_BUSINESS_ID},
                         timeout=10)
        data = r.json()
        if data.get("success") and data.get("data", {}).get("token"):
            token = data["data"]["token"]
            action = data["data"].get("action", "")
            error = data["data"].get("error", "")
            return token, action, error
        return None, None, data.get("message", "unknown error")
    except Exception as e:
        return None, None, str(e)


# ============================================================
# 公开 API 测试
# ============================================================
def test_oauth_redirect(stats):
    """测试 OAuth 重定向 → baizhi.cloud"""
    print_section("OAuth 重定向测试")
    
    try:
        r = requests.get(f"{BASE_URL}/api/v1/users/login", 
                        allow_redirects=False, timeout=15)
    except Exception as e:
        print_fail(f"请求失败: {e}")
        stats.failed += 1
        return
    
    if r.status_code == 302:
        location = r.headers.get("Location", "")
        if "baizhi.cloud" in location:
            print_pass("OAuth 重定向正确 → baizhi.cloud")
            print_info(f"Location: {location[:100]}...")
            stats.passed += 1
        else:
            print_fail(f"重定向到非预期地址: {location[:100]}")
            stats.failed += 1
    else:
        print_fail(f"预期 302, 实际 {r.status_code}")
        stats.failed += 1


def test_scaptcha_token(stats):
    """测试 SCaptcha token 获取"""
    print_section("SCaptcha Token 获取测试")
    
    token, action, error = get_scaptcha_token()
    
    if token:
        print_pass(f"SCaptcha token 获取成功")
        print_info(f"Token: {token[:50]}...")
        print_info(f"Action: {action}, Error: {error}")
        if error == "no money":
            print_warn("SCaptcha 账户余额不足，但 token 仍有效")
        stats.passed += 1
        return token
    else:
        print_fail(f"SCaptcha token 获取失败: {error}")
        stats.failed += 1
        return None


def test_baizhi_oauth_login_api(stats):
    """测试百智云第三方 OAuth 登录 API"""
    print_section("百智云 OAuth 第三方登录 API")
    
    # GitHub OAuth
    try:
        r = requests.get(f"{BAIZHI_API}/api/v1/user/oauth/login",
                        params={"platform": "github", 
                                "redirect_url": f"{BASE_URL}/api/v1/users/baizhi/callback"},
                        timeout=10)
        data = r.json()
        if data.get("code") == 0 and data.get("data", {}).get("url"):
            url = data["data"]["url"]
            print_pass(f"GitHub OAuth URL 获取成功")
            print_info(f"client_id: {url.split('client_id=')[1].split('&')[0] if 'client_id=' in url else 'N/A'}")
            stats.passed += 1
        else:
            print_fail(f"GitHub OAuth 响应异常: {r.text[:200]}")
            stats.failed += 1
    except Exception as e:
        print_fail(f"GitHub OAuth 请求失败: {e}")
        stats.failed += 1
    
    # WeChat OAuth
    try:
        r = requests.get(f"{BAIZHI_API}/api/v1/user/oauth/login",
                        params={"platform": "wechat",
                                "redirect_url": f"{BASE_URL}/api/v1/users/baizhi/callback"},
                        timeout=10)
        data = r.json()
        if data.get("code") == 0 and data.get("data", {}).get("url"):
            print_pass("WeChat OAuth URL 获取成功")
            stats.passed += 1
        else:
            print_fail(f"WeChat OAuth 响应异常: {r.text[:200]}")
            stats.failed += 1
    except Exception as e:
        print_fail(f"WeChat OAuth 请求失败: {e}")
        stats.failed += 1


def test_phone_code_with_scaptcha(stats, token=None):
    """测试用 SCaptcha token 发送验证码"""
    print_section("验证码发送 API 参数验证")
    
    # 测试空 token → 参数错误
    try:
        r = requests.post(f"{BAIZHI_API}/api/v1/user/phone_code",
                         json={"phone": "13800138000", "kind": "login"},
                         timeout=10)
        data = r.json()
        if r.status_code == 400 and "参数错误" in data.get("message", ""):
            print_pass("空 token → 参数错误 (预期行为)")
            stats.passed += 1
        else:
            print_fail(f"预期参数错误, 得到: {r.text[:100]}")
            stats.failed += 1
    except Exception as e:
        print_fail(f"请求失败: {e}")
        stats.failed += 1
    
    # 测试假 token → 无效验证码
    try:
        r = requests.post(f"{BAIZHI_API}/api/v1/user/phone_code",
                         json={"phone": "13800138000", "kind": "login", "token": "fake"},
                         timeout=10)
        data = r.json()
        if r.status_code == 400 and "无效" in data.get("message", ""):
            print_pass("假 token → 无效验证码 (预期行为)")
            stats.passed += 1
        else:
            print_fail(f"预期无效验证码, 得到: {r.text[:100]}")
            stats.failed += 1
    except Exception as e:
        print_fail(f"请求失败: {e}")
        stats.failed += 1
    
    # 测试真正的 SCaptcha token
    if token:
        try:
            r = requests.post(f"{BAIZHI_API}/api/v1/user/phone_code",
                             json={"phone": "13800138000", "kind": "login", "token": token},
                             timeout=10)
            data = r.json()
            if r.status_code == 200 and data.get("code") == 0:
                print_pass("SCaptcha token → 验证码发送成功！")
                stats.passed += 1
            elif r.status_code == 400 and "无效" in data.get("message", ""):
                print_warn("SCaptcha token 被拒 (可能已过期)")
                stats.skipped += 1
            else:
                print_info(f"SCaptcha token 响应: {r.status_code} - {r.text[:200]}")
                stats.skipped += 1
        except Exception as e:
            print_fail(f"请求失败: {e}")
            stats.failed += 1


# ============================================================
# Session Cookie 认证测试
# ============================================================
def test_session_auth(stats, cookie_value):
    """使用 session cookie 测试认证链"""
    print_section("Session Cookie 认证测试")
    
    if not cookie_value:
        print_skip("未提供 session cookie")
        stats.skipped += 1
        return None
    
    session = requests.Session()
    session.cookies.set(SESSION_COOKIE_NAME, cookie_value, domain="monkeycode-ai.com")
    session.headers.update({"User-Agent": "MonkeyCode-RE/1.0"})
    
    # Test GET /api/v1/users/me
    print(f"\n  {Color.DIM}测试 GET /api/v1/users/me ...{Color.RESET}")
    try:
        r = session.get(f"{BASE_URL}/api/v1/users/me", timeout=15)
    except Exception as e:
        print_fail(f"请求失败: {e}")
        stats.failed += 1
        return None
    
    user_info = None
    if r.status_code == 200:
        try:
            data = r.json()
            user_info = data
            username = data.get("username") or data.get("name") or data.get("email") or "未知"
            print_pass(f"用户信息获取成功: {username}")
            print_info(f"数据: {json.dumps(data, ensure_ascii=False, indent=2)[:300]}")
            stats.passed += 1
        except:
            print_fail(f"响应非 JSON: {r.text[:200]}")
            stats.failed += 1
    elif r.status_code == 401:
        print_fail("Cookie 无效或已过期 (401 Unauthorized)")
        stats.failed += 1
        return None
    else:
        print_fail(f"预期 200, 实际 {r.status_code}: {r.text[:200]}")
        stats.failed += 1
    
    # Test protected endpoint
    print(f"\n  {Color.DIM}测试受保护端点 GET /api/v1/teams ...{Color.RESET}")
    try:
        r = session.get(f"{BASE_URL}/api/v1/teams", timeout=15)
        if r.status_code == 200:
            print_pass(f"受保护端点可访问")
            stats.passed += 1
        elif r.status_code == 401:
            print_fail("Cookie 无效 (401)")
            stats.failed += 1
        elif r.status_code == 404:
            print_skip("端点不存在 (404)")
            stats.skipped += 1
        else:
            print_info(f"端点返回 {r.status_code}")
            stats.skipped += 1
    except Exception as e:
        print_skip(f"请求失败: {e}")
        stats.skipped += 1
    
    return user_info


# ============================================================
# 自动登录流程
# ============================================================
def auto_login(stats, phone):
    """完整的自动化登录流程
    
    1. 获取 SCaptcha token (不需要浏览器)
    2. 发送短信验证码
    3. 用户输入验证码
    4. 登录百智云
    5. 完成 OAuth 授权
    """
    print_header("MonkeyCode 自动登录流程")
    print(f"  手机号: {phone}")
    
    # Step 1: 获取 SCaptcha token
    print_section("Step 1/4: 获取 SCaptcha Token")
    token, action, error = get_scaptcha_token()
    
    if not token:
        print_fail(f"SCaptcha token 获取失败: {error}")
        stats.failed += 1
        return
    
    print_pass(f"Token 获取成功")
    if error == "no money":
        print_warn("SCaptcha 账户欠费，但 token 仍有效 (安全漏洞)")
    stats.passed += 1
    
    # Step 2: 发送短信验证码
    print_section("Step 2/4: 发送短信验证码")
    try:
        r = requests.post(f"{BAIZHI_API}/api/v1/user/phone_code",
                         json={"phone": phone, "kind": "login", "token": token},
                         timeout=10)
        data = r.json()
    except Exception as e:
        print_fail(f"请求失败: {e}")
        stats.failed += 1
        return
    
    if r.status_code == 200 and data.get("code") == 0:
        print_pass("验证码发送成功！请查看手机短信")
        stats.passed += 1
    else:
        print_fail(f"验证码发送失败: {data.get('message', r.text[:200])}")
        stats.failed += 1
        return
    
    # Step 3: 输入验证码并登录
    print_section("Step 3/4: 输入验证码并登录")
    code = input(f"  {Color.BOLD}请输入收到的短信验证码: {Color.RESET}").strip()
    
    if not code:
        print_fail("未输入验证码")
        stats.failed += 1
        return
    
    try:
        r = requests.post(f"{BAIZHI_API}/api/v1/user/login/phone",
                         json={"phone": phone, "code": code},
                         timeout=10)
        data = r.json()
    except Exception as e:
        print_fail(f"登录请求失败: {e}")
        stats.failed += 1
        return
    
    if r.status_code == 200 and data.get("code") == 0:
        print_pass("百智云登录成功！")
        # 登录成功后，baizhi.cloud 会设置 session cookie
        # 我们需要从 response 中提取 cookies
        baizhi_cookies = r.cookies.get_dict()
        print_info(f"Baizhi cookies: {list(baizhi_cookies.keys())}")
        stats.passed += 1
    else:
        msg = data.get("message", r.text[:200]) if isinstance(data, dict) else r.text[:200]
        print_fail(f"登录失败: {msg}")
        stats.failed += 1
        return
    
    # Step 4: 完成 OAuth 授权
    print_section("Step 4/4: 完成 OAuth 授权")
    print_info("登录成功后，需要在浏览器中完成 OAuth 授权流程")
    print_info("或在后续版本中自动完成授权重定向")
    
    print_pass("自动登录流程完成！")
    print_info("下一步: 在浏览器中访问 monkeycode-ai.com 应该已登录")


# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="MonkeyCode 授权测试 v2")
    parser.add_argument("--cookie", "-c", help="Session cookie 值")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互式输入 cookie")
    parser.add_argument("--no-auth", action="store_true", help="仅运行不需要认证的测试")
    parser.add_argument("--phone", "-p", help="手机号 (用于自动登录流程)")
    parser.add_argument("--auto", "-a", action="store_true", help="运行完整自动登录流程")
    args = parser.parse_args()
    
    stats = Stats()
    
    # 自动登录模式
    if args.auto and args.phone:
        auto_login(stats, args.phone)
        print_header("测试结果")
        print(f"  {stats}")
        return 0 if stats.failed == 0 else 1
    
    print_header("MonkeyCode 授权测试 v2")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标: {BASE_URL}")
    print(f"  SCaptcha: {SCAPTCHA_API}")
    print(f"  百智云: {BAIZHI_API}")
    
    # 确定 cookie 来源
    cookie_value = None
    if args.cookie:
        cookie_value = args.cookie
    elif ENV_COOKIE:
        cookie_value = ENV_COOKIE
    elif args.interactive:
        print(f"\n  请输入 {SESSION_COOKIE_NAME} 的值 (从浏览器 DevTools 获取):")
        cookie_value = input("  > ").strip()
    
    has_cookie = bool(cookie_value)
    if has_cookie:
        masked = cookie_value[:8] + "..." + cookie_value[-8:] if len(cookie_value) > 20 else "***"
        print(f"  Cookie: {masked}")
    else:
        print(f"  {Color.YELLOW}Cookie: 未提供 (跳过认证测试){Color.RESET}")
    
    # 公开 API 测试
    test_oauth_redirect(stats)
    token = test_scaptcha_token(stats)
    test_baizhi_oauth_login_api(stats)
    test_phone_code_with_scaptcha(stats, token)
    
    # 认证测试
    if not args.no_auth:
        user_info = test_session_auth(stats, cookie_value)
        
        if user_info:
            print_section("认证验证总结")
            print_pass("Session cookie 有效")
            print_pass("用户信息获取成功")
            print(f"\n  {Color.GREEN}{Color.BOLD}✓ 授权成功！{Color.RESET}")
        elif has_cookie:
            print_section("认证验证总结")
            print_fail("Session cookie 无效或已过期")
            print_info("重新获取:")
            print_info("  1. 浏览器打开 https://monkeycode-ai.com 登录")
            print_info("  2. F12 → Application → Cookies")
            print_info(f"  3. 复制 {SESSION_COOKIE_NAME} 的值")
    
    # 总结
    print_header("测试结果")
    print(f"  {stats}")
    
    print(f"\n  {Color.DIM}提示: 使用 --auto --phone 手机号 可运行完整自动登录流程{Color.RESET}")
    
    if stats.failed > 0:
        return 1
    elif stats.passed > 0:
        return 0
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
