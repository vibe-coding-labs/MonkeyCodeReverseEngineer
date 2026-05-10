import os

BASE_URL = os.getenv("MONKEYCODE_BASE_URL", "https://monkeycode-ai.com")
SESSION_COOKIE_NAME = "sl-session"

# 认证配置（二选一）
USERNAME = os.getenv("MONKEYCODE_USERNAME", "")
PASSWORD = os.getenv("MONKEYCODE_PASSWORD", "")
SESSION_COOKIE = os.getenv("MONKEYCODE_SESSION_COOKIE", "")

# 代理配置
PROXY_PORT = int(os.getenv("PROXY_PORT", "9090"))
