"""MonkeyCode 认证协议验证模块

支持的登录方式:
1. 百智云 OAuth 登录 (GET /api/v1/users/login → 百智云 → 回调)
2. 普通用户密码登录 (POST /api/v1/users/password-login)
3. 团队管理员密码登录 (POST /api/v1/teams/users/login)
4. Session Cookie 直接设置（从浏览器提取）

验证码说明:
- 密码登录需要 MonkeyCode captcha_token (go-cap)
- 百智云登录需要 SCaptcha token (长亭科技) + 短信验证码
- 自动化场景推荐使用 oauth_login.py 或 oauth_http.py
"""
import re
import requests
from config import BASE_URL, SESSION_COOKIE_NAME, USERNAME, PASSWORD, SESSION_COOKIE


class MonkeyCodeAuth:
    def __init__(self):
        self.session = requests.Session()
        self.session_cookie = SESSION_COOKIE
        self.user_info = None

    def login_user_password(self, email: str = None, password: str = None,
                            captcha_token: str = None) -> dict:
        """普通用户密码登录

        API: POST /api/v1/users/password-login
        Cookie: monkeycode_ai_session
        """
        email = email or USERNAME
        password = password or PASSWORD
        if not email or not password:
            raise ValueError("需要提供 email 和 password")

        url = f"{BASE_URL}/api/v1/users/password-login"
        payload = {
            "email": email.strip(),
            "password": password.strip(),
        }
        if captcha_token:
            payload["captcha_token"] = captcha_token

        print(f"[Auth] 普通用户登录: {email}")

        resp = self.session.post(url, json=payload, allow_redirects=False)

        print(f"[Auth] 响应状态: {resp.status_code}")
        print(f"[Auth] 响应头: {dict(resp.headers)}")

        cookie = self._extract_session_cookie(resp)
        if cookie:
            self.session_cookie = cookie
            print(f"[Auth] Session Cookie 获取成功: {self.session_cookie[:20]}...")
        else:
            print(f"[Auth] 登录失败: 无法获取 Session Cookie")
            print(f"[Auth] 响应体: {resp.text[:500]}")
            return {"success": False, "status": resp.status_code, "body": resp.text[:500]}

        try:
            data = resp.json()
            self.user_info = data.get("data", data)
            print(f"[Auth] 登录成功: {self.user_info}")
        except Exception:
            pass

        return {"success": True, "status": resp.status_code, "cookie": self.session_cookie}

    def login_team_password(self, email: str = None, password: str = None,
                            captcha_token: str = None) -> dict:
        """团队管理员密码登录

        API: POST /api/v1/teams/users/login
        Cookie: monkeycode_ai_team_session
        """
        email = email or USERNAME
        password = password or PASSWORD
        if not email or not password:
            raise ValueError("需要提供 email 和 password")

        url = f"{BASE_URL}/api/v1/teams/users/login"
        payload = {
            "email": email.strip(),
            "password": password.strip(),
        }
        if captcha_token:
            payload["captcha_token"] = captcha_token

        print(f"[Auth] 团队管理员登录: {email}")

        resp = self.session.post(url, json=payload, allow_redirects=False)

        print(f"[Auth] 响应状态: {resp.status_code}")

        # 团队管理员使用不同的 cookie name
        team_cookie_name = "monkeycode_ai_team_session"
        cookie = self._extract_session_cookie(resp, cookie_name=team_cookie_name)
        if cookie:
            self.session_cookie = cookie
            print(f"[Auth] Team Session Cookie 获取成功: {self.session_cookie[:20]}...")
        else:
            print(f"[Auth] 登录失败: 无法获取 Team Session Cookie")
            print(f"[Auth] 响应体: {resp.text[:500]}")
            return {"success": False, "status": resp.status_code, "body": resp.text[:500]}

        try:
            data = resp.json()
            self.user_info = data.get("data", data)
            print(f"[Auth] 登录成功: {self.user_info}")
        except Exception:
            pass

        return {"success": True, "status": resp.status_code, "cookie": self.session_cookie}

    def oauth_login(self):
        """百智云 OAuth 登录 — 获取重定向 URL

        实际登录流程需要浏览器交互（百智云手机号+验证码+SCaptcha），
        此方法仅获取 OAuth 重定向 URL，完整流程请使用 oauth_login.py 或 oauth_http.py。

        Returns:
            dict: {"redirect_url": "https://baizhi.cloud/oauth/authorize?...", "state": "..."}
        """
        url = f"{BASE_URL}/api/v1/users/login"
        print(f"[Auth] 百智云 OAuth 登录 — 获取重定向 URL")

        resp = requests.get(url, allow_redirects=False, timeout=15)
        if resp.status_code != 302:
            print(f"[Auth] OAuth 重定向失败: status={resp.status_code}")
            return None

        location = resp.headers.get("Location", "")
        print(f"[Auth] 重定向到: {location[:80]}...")

        # 解析 OAuth 参数
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(location)
        params = parse_qs(parsed.query)

        result = {
            "redirect_url": location,
            "state": params.get("state", [""])[0],
            "client_id": params.get("client_id", [""])[0],
            "redirect_uri": params.get("redirect_uri", [""])[0],
            "scope": params.get("scope", [""])[0],
        }
        print(f"[Auth] OAuth 参数: client_id={result['client_id']}, state={result['state'][:12]}...")
        return result

    def set_session_cookie(self, cookie: str, cookie_name: str = None):
        """手动设置 Session Cookie（从浏览器提取）"""
        self.session_cookie = cookie
        name = cookie_name or SESSION_COOKIE_NAME
        self.session.cookies.set(name, cookie)
        print(f"[Auth] Session Cookie 已设置 ({name}): {cookie[:20]}...")

    def check_status(self) -> dict:
        """检查普通用户登录状态

        API: GET /api/v1/users/status
        """
        url = f"{BASE_URL}/api/v1/users/status"
        cookies = {SESSION_COOKIE_NAME: self.session_cookie}

        resp = requests.get(url, cookies=cookies)
        print(f"[Auth] 用户状态检查: {resp.status_code}")

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

    def check_team_status(self) -> dict:
        """检查团队管理员登录状态

        API: GET /api/v1/teams/users/status
        """
        url = f"{BASE_URL}/api/v1/teams/users/status"
        cookies = {"monkeycode_ai_team_session": self.session_cookie}

        resp = requests.get(url, cookies=cookies)
        print(f"[Auth] 团队状态检查: {resp.status_code}")

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
        """普通用户登出

        API: POST /api/v1/users/logout
        """
        url = f"{BASE_URL}/api/v1/users/logout"
        cookies = {SESSION_COOKIE_NAME: self.session_cookie}

        resp = requests.post(url, cookies=cookies)
        print(f"[Auth] 登出: {resp.status_code}")
        self.session_cookie = ""
        self.user_info = None
        return {"success": resp.status_code == 200}

    def logout_team(self) -> dict:
        """团队管理员登出

        API: POST /api/v1/teams/users/logout
        """
        url = f"{BASE_URL}/api/v1/teams/users/logout"
        cookies = {"monkeycode_ai_team_session": self.session_cookie}

        resp = requests.post(url, cookies=cookies)
        print(f"[Auth] 团队登出: {resp.status_code}")
        self.session_cookie = ""
        self.user_info = None
        return {"success": resp.status_code == 200}

    def get_auth_cookies(self) -> dict:
        """获取认证 Cookie 字典"""
        if not self.session_cookie:
            raise RuntimeError("未认证，请先登录或设置 Session Cookie")
        return {SESSION_COOKIE_NAME: self.session_cookie}

    def _extract_session_cookie(self, resp, cookie_name: str = None) -> str:
        """从响应中提取 Session Cookie"""
        name = cookie_name or SESSION_COOKIE_NAME

        # 尝试从 cookies 中提取
        if name in resp.cookies:
            return resp.cookies[name]

        # 尝试从 Set-Cookie header 中提取
        set_cookie = resp.headers.get("Set-Cookie", "")
        if name in set_cookie:
            match = re.search(rf"{name}=([^;]+)", set_cookie)
            if match:
                return match.group(1)

        return ""
