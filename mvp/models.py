"""MonkeyCode 模型管理协议验证模块

验证:
1. 获取用户模型列表 (GET /api/v1/users/models)
2. 模型数据结构验证
3. 公开模型识别 (public:model: 前缀)
4. 模型健康检查 (GET /api/v1/users/models/{id}/health-check)
"""
import requests
from config import BASE_URL, SESSION_COOKIE_NAME


class MonkeyCodeModels:
    def __init__(self, auth):
        self.auth = auth
        self.models = []

    def list_models(self) -> dict:
        """获取用户可用模型列表"""
        url = f"{BASE_URL}/api/v1/users/models"
        cookies = self.auth.get_auth_cookies()

        print(f"[Models] 获取模型列表...")
        resp = requests.get(url, cookies=cookies)
        print(f"[Models] 响应状态: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[Models] 获取失败: {resp.text[:500]}")
            return {"success": False, "status": resp.status_code}

        data = resp.json()
        result = data.get("data", data)
        self.models = result.get("models", []) if isinstance(result, dict) else result

        print(f"[Models] 获取到 {len(self.models)} 个模型")

        by_owner = {}
        by_interface = {}
        by_provider = {}
        for m in self.models:
            owner = m.get("owner", "unknown")
            iface = m.get("interface_type", "unknown")
            provider = m.get("provider", "unknown")
            by_owner[owner] = by_owner.get(owner, 0) + 1
            by_interface[iface] = by_interface.get(iface, 0) + 1
            by_provider[provider] = by_provider.get(provider, 0) + 1

        print(f"[Models] 按所有者: {by_owner}")
        print(f"[Models] 按接口类型: {by_interface}")
        print(f"[Models] 按提供商: {by_provider}")

        public_models = [m for m in self.models if m.get("owner") == "public"]
        if public_models:
            print(f"\n[Models] 公开模型详情:")
            for m in public_models:
                print(f"  - {m.get('provider')}/{m.get('model')} "
                      f"(interface={m.get('interface_type')}, "
                      f"free={m.get('is_free')}, "
                      f"access={m.get('access_level')})")
                api_key = m.get("api_key", "")
                if api_key.startswith("public:model:"):
                    print(f"    API Key: {api_key} (公开模型前缀，后端自动替换)")

        return {
            "success": True,
            "count": len(self.models),
            "by_owner": by_owner,
            "by_interface": by_interface,
            "by_provider": by_provider,
            "models": self.models,
        }

    def health_check(self, model_id: str) -> dict:
        """模型健康检查"""
        url = f"{BASE_URL}/api/v1/users/models/{model_id}/health-check"
        cookies = self.auth.get_auth_cookies()

        print(f"[Models] 健康检查模型 {model_id}...")
        resp = requests.get(url, cookies=cookies)
        print(f"[Models] 健康检查结果: {resp.status_code} {resp.text[:200]}")

        return {"success": resp.status_code == 200, "status": resp.status_code, "body": resp.text[:500]}

    def get_public_models(self) -> list:
        return [m for m in self.models if m.get("owner") == "public"]

    def get_free_models(self) -> list:
        return [m for m in self.models if m.get("is_free")]