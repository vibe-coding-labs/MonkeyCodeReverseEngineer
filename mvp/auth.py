"""MonkeyCode 认证协议验证模块

验证:
1. Team 用户登录 (POST /api/v1/teams/users/login)
2. Session Cookie 提取
3. 登录状态检查 (GET /api/v1/users/status)
4. 登出 (POST /api/v1/users/logout)
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

    def login_with_password(self, username: str = None, password: str = None) -> dict:
        """Team 用户密码登录"""
        username = username or USERNAME
        password = password or PASSWORD
        if not username or not password:
            raise ValueError("需要提供 username 和 password")

        password_md5 = hashlib.md5(password.encode()).hexdigest()

        url = f"{BASE_URL}/api/v1/teams/users/login"
        payload = {"username": username, "password": password_md5}

        print(f"[Auth] 尝试登录: {username}")
        print(f"[Auth] 密码 MD5: {password_md5}")

        resp = self.session.post(url, json=payload, allow_redirects=False)

        print(f"[Auth] 响应状态: {resp.status_code}")
        print(f"[Auth] 响应头: {dict(resp.headers)}")

        # 提取 Session Cookie
        if SESSION_COOKIE_NAME in resp.cookies:
            self.session_cookie = resp.cookies[SESSION_COOKIE_NAME]
            print(f"[Auth] Session Cookie 获取成功: {self.session_cookie[:20]}...")
        else:
            set_cookie = resp.headers.get("Set-Cookie", "")
            if SESSION_COOKIE_NAME in set_cookie:
                match = re.search(rf"{SESSION_COOKIE_NAME}=([^;]+)", set_cookie)
                if match:
                    self.session_cookie = match.group(1)
                    print(f"[Auth] Session Cookie (从 header) 获取成功: {self.session_cookie[:20]}...")

        if not self.session_cookie:
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

    def set_session_cookie(self, cookie: str):
        """手动设置 Session Cookie"""
        self.session_cookie = cookie
        self.session.cookies.set(SESSION_COOKIE_NAME, cookie)
        print(f"[Auth] Session Cookie 已设置: {cookie[:20]}...")

    def check_status(self) -> dict:
        """检查登录状态"""
        url = f"{BASE_URL}/api/v1/users/status"
        cookies = {SESSION_COOKIE_NAME: self.session_cookie}

        resp = requests.get(url, cookies=cookies)
        print(f"[Auth] 状态检查: {resp.status_code}")

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
        """登出"""
        url = f"{BASE_URL}/api/v1/users/logout"
        cookies = {SESSION_COOKIE_NAME: self.session_cookie}

        resp = requests.post(url, cookies=cookies)
        print(f"[Auth] 登出: {resp.status_code}")
        self.session_cookie = ""
        self.user_info = None
        return {"success": resp.status_code == 200}

    def get_auth_cookies(self) -> dict:
        """获取认证 Cookie 字典"""
        if not self.session_cookie:
            raise RuntimeError("未认证，请先登录或设置 Session Cookie")
        return {SESSION_COOKIE_NAME: self.session_cookie}