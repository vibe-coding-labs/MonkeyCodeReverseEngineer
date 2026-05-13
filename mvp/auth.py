"""MonkeyCode 认证协议验证模块

支持的登录方式:
1. 普通用户密码登录 (POST /api/v1/users/password-login)
2. 团队管理员密码登录 (POST /api/v1/teams/users/login)
3. Session Cookie 直接设置（从浏览器提取）

验证码说明:
- 所有密码登录需要 captcha_token
- 验证码系统为 go-cap (50x32 网格，3 目标)
- 自动化场景建议直接使用浏览器提取的 Session Cookie
"""
import hashlib
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

        password_md5 = hashlib.md5(password.encode()).hexdigest()

        url = f"{BASE_URL}/api/v1/users/password-login"
        payload = {
            "email": email.strip(),
            "password": password_md5,
        }
        if captcha_token:
            payload["captcha_token"] = captcha_token

        print(f"[Auth] 普通用户登录: {email}")
        print(f"[Auth] 密码 MD5: {password_md5}")

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

        password_md5 = hashlib.md5(password.encode()).hexdigest()

        url = f"{BASE_URL}/api/v1/teams/users/login"
        payload = {
            "email": email.strip(),
            "password": password_md5,
        }
        if captcha_token:
            payload["captcha_token"] = captcha_token

        print(f"[Auth] 团队管理员登录: {email}")
        print(f"[Auth] 密码 MD5: {password_md5}")

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
