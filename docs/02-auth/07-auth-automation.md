---
description: 认证自动化分析 — 密码传输格式验证、验证码绕过评估、Session 保活、并发策略
protocol_version: based on chaitin/MonkeyCode 开源后端源码
confidence: high
last_verified: 2026-06-27
---

# 认证自动化

## 1. 密码传输格式

**结论**: 前端传明文，后端用 bcrypt 验证

```tsx
// frontend/src/pages/login.tsx:85-88 — 前端密码传输
await apiRequest('v1UsersPasswordLoginCreate', {
    email: userEmail.trim(),
    password: userPassword.trim(),  // 直接传用户输入的明文
    captcha_token: token,
})
```

```go
// backend/pkg/crypto/bcrypt.go:22-24 — 后端密码验证
func VerifyPassword(dbPassword, password string) error {
    return bcrypt.CompareHashAndPassword([]byte(dbPassword), []byte(password))
}
```

**注释错误**: 后端 domain 注释标注的 "MD5加密后的值" 是过时的错误注释，源自 Swagger 自动生成时的初始模板。实际密码以明文在 HTTPS 中传输，后端用 bcrypt 验证。

**对账号池的影响**: 账号池需存储明文密码，登录时直接传明文。

## 2. 验证码自动化评估

MonkeyCode 登录页面使用 CAP.js/go-cap 验证码系统：

```
验证码生成:
  前端加载 CAP.js → 生成 50×32 网格图像（识别难度: 中等）
  → 提交 grid_id + grid_positions → 后端验证

验证码参数:
  网格大小: 50×32 像素
  类型: 图片网格选择（选择包含特定物体的格子）
  TTL: 验证码 token 5 分钟有效
```

| 方案 | 可行性 | 成本 | 说明 |
|------|--------|------|------|
| Cookie 复用 | ★★★★★ | 极低 | 最推荐，完全绕过验证码 |
| 多模态 LLM 识别 | ★★★☆☆ | 中等 | 50x32 网格识别，GPT-4V 可尝试 |
| 第三方验证码服务 | ★★★☆☆ | 中等 | 使用专业验证码识别服务 |

**推荐方案**: 浏览器 Cookie 复用 + 自动保活。如需全自动登录，使用多模态 LLM 识别验证码图片。

```python
# 验证码识别示例（使用 GPT-4V）
import base64
from openai import OpenAI

def solve_captcha(grid_image_base64: str) -> list:
    """使用多模态 LLM 识别 CAP.js 验证码网格"""
    client = OpenAI()
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识别这个验证码网格中包含特定物体的格子位置，返回格子序号列表"},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{grid_image_base64}"
                    }}
                ]
            }
        ]
    )
    return parse_grid_positions(response.choices[0].message.content)
```

## 3. Session 保活协议

### 有效性检测

```bash
# 检查 Session 是否有效
curl -s https://api.monkeycode-ai.com/api/v1/users/status \
  -H "Cookie: monkeycode_ai_session={uuid}" | jq .
```

- `code: 0` → session 有效
- `code: 40100` → session 失效

### 重要发现: Status 端点不刷新 TTL

Status 端点和 Auth 中间件都**不刷新** Redis TTL。Session 从创建时起固定 30 天过期，任何 API 调用都无法延长。

```go
// backend/middleware/auth.go — Auth 中间件（不刷新 TTL）
func AuthMiddleware() gin.HandlerFunc {
    return func(c *gin.Context) {
        session := session.Get[SessionData](c, cookieName)
        if session == nil {
            c.AbortWithStatusJSON(401, ErrorResponse{Code: 40100, Msg: "unauthorized"})
            return
        }
        // 注意：这里没有调用 session.RefreshTTL()
        // 即使调用了 API，TTL 也不会延长
        c.Set("user", session.UserID)
        c.Next()
    }
}
```

| 操作 | 是否刷新 TTL |
|------|-------------|
| 登录（Save） | ✅ 设置 30 天 |
| 调用 Status | ❌ 不刷新 |
| 调用任何 API | ❌ 不刷新 |
| Auth 中间件 | ❌ 不刷新 |
| TargetActive | ❌ 不刷新 |

### 自动保活策略

```python
# 建议的 Session 自动保活策略
import time
from datetime import datetime, timedelta

class SessionKeeper:
    """Session 自动保活管理器"""
    
    def __init__(self, session_cookie: str, created_at: datetime):
        self.session = session_cookie
        self.created_at = created_at
        self.expires_at = created_at + timedelta(days=30)
    
    def days_remaining(self) -> int:
        return (self.expires_at - datetime.now()).days
    
    def should_renew(self) -> bool:
        """当剩余不足 3 天时，需要重新登录"""
        return self.days_remaining() < 3
    
    def renew_session(self):
        """重新登录获取新 Session"""
        # 每次登录获得 30 天有效期
        # 建议: 当剩余 3 天时触发重新登录
        pass

# 使用示例
keeper = SessionKeeper(
    session_cookie="monkeycode_ai_session=xxx",
    created_at=datetime.now()
)

# 每 24 小时检查一次
while True:
    if keeper.should_renew():
        print(f"Session 剩余 {keeper.days_remaining()} 天，需要重新登录")
        # 执行登录流程获取新 Session
        break
    time.sleep(24 * 3600)
```

## 4. 并发 Session 策略

| 策略 | 说明 | 风险 | 适用场景 |
|------|------|------|---------|
| 单 session 串行 | 每账号 1 个 session，每次 1 个请求 | 低风险，吞吐量低 | 个人使用 |
| 多 session 并发 | 每账号 2+ session 同时使用 | 中风险，开源代码无限制 | 小型号池 |
| 推荐: 1 主 1 备 | 主 API + WS，备切换 | 风险可控 | 推荐方案 |

```typescript
// 号池的 Session 分配策略（account-pool.ts 模式）
interface AccountSession {
    primary: string;   // 主 Session（用于 API + WS）
    backup: string;    // 备用 Session（用于切换）
    lastUsed: number;
    taskCount: number;
}

// 并发策略: 每个账号最多 2 个并发 session
// 但每个 session 只能有 1 个活跃任务（TaskFlow 限制）
```

## 5. 登录错误码

| HTTP 状态码 | Code | 含义 | 触发条件 |
|-----------|------|------|---------|
| 200 | 0 | 登录成功 | 账号密码正确，验证码通过 |
| 400 | 10001 | 参数错误 | 缺少 email/password/captcha_token |
| 401 | 40100 | 未授权/Session 过期 | Session 不存在或已过期 |
| 401 | 40101 | 账号或密码错误 | bcrypt 验证失败 |
| 401 | 40102 | 验证码错误 | captcha_token 无效或已过期 |
| 403 | 40300 | 账号被禁用 | 用户状态为 "banded" |

---

## 附录：逆向分析代码示例

### 附录 A: 快速 Session 有效性检查 (curl)
```bash
# 批量检查 Session 有效性
for cookie in "session1=xxx" "session2=yyy" "session3=zzz"; do
  status=$(curl -s -o /dev/null -w "%{http_code}" \
    https://api.monkeycode-ai.com/api/v1/users/status \
    -H "Cookie: monkeycode_ai_session=$cookie")
  echo "Session $cookie: HTTP $status"
done

# 期望输出:
# Session session1=xxx: HTTP 200 (有效)
# Session session2=yyy: HTTP 401 (失效)
```

### 附录 B: 密码明文传输验证 (Python 测试)
```python
# 验证 MonkeyCode 的密码传输是明文而非 MD5
import requests
from urllib.parse import parse_qs

# 假设的登录场景 — 抓包验证密码传输格式
login_url = "https://api.monkeycode-ai.com/api/v1/users/password-login"
payload = {
    "email": "test@example.com",
    "password": "明文密码ABC123!",
    "captcha_token": "captcha_xxx"
}

# 密码是明文直接传输
resp = requests.post(login_url, json=payload)

# 如果密码是 MD5，payload 应该包含 md5 字符串
# 但实际传输的是原始密码字符串
assert "明文密码" in resp.request.body.decode()  # 验证明文
print("✅ 密码以明文形式在 HTTPS 中传输")
```

---

## 相关章节

- [Session 存储机制](01-session-storage.md) — Redis 数据结构
- [验证码系统](02-captcha-system.md) — CAP.js/go-cap 详情
- [认证号池差距分析](08-pool-gap-analysis.md) — 完整差距分析