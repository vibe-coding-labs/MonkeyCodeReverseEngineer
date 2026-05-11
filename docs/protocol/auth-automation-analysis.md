# MonkeyCode 认证自动化与密码格式分析

> 分析日期: 2026-05-11

---

## 1. 密码传输格式分析

### 1.1 源码证据

**后端 Domain 注释（支持 MD5）：**

```go
// backend/domain/team.go
type TeamLoginReq struct {
    Email        string `json:"email" validate:"required"`
    Password     string `json:"password" validate:"required"` // 用户密码（MD5加密后的值）
    CaptchaToken string `json:"captcha_token"`
}

// backend/domain/user.go (PasswordLoginReq 同样注释)
```

**前端代码（传明文）：**

```tsx
// login.tsx:73-101
await apiRequest('v1UsersPasswordLoginCreate', {
    email: userEmail.trim(),
    password: userPassword.trim(),  // 直接传用户输入的值
    captcha_token: token,
})
```

**前端 localStorage（存明文）：**

```tsx
localStorage.setItem('login_user', JSON.stringify({
    email: userEmail.trim(),
    password: userPassword.trim()  // 明文存储！
}))
```

### 1.2 两种可能性分析

#### 可能性 A：前端在 apiRequest 内部做 MD5

**证据：**
- 后端 domain 注释明确标注 MD5
- `apiRequest` 是 Swagger 生成的客户端封装，可能有拦截器
- 密码长度验证 `8-32 chars` 对 MD5 输出（32 hex chars）合理

**验证方法：**
```bash
# 发送 MD5 哈希
curl -X POST https://monkeycode-ai.com/api/v1/users/password-login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"e10adc3949ba59abbe56e057f20f883e","captcha_token":"xxx"}'
```

#### 可能性 B：前端直接传明文，后端做 MD5

**证据：**
- 前端代码直接 `userPassword.trim()` 传入
- localStorage 存储明文密码
- 前端没有显式 MD5 调用

**验证方法：**
```bash
# 发送明文密码
curl -X POST https://monkeycode-ai.com/api/v1/users/password-login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"123456","captcha_token":"xxx"}'
```

### 1.3 对账号池的影响

| 场景 | 可能性 A (前端 MD5) | 可能性 B (后端 MD5) |
|------|---------------------|---------------------|
| 账号池存储 | 存储 MD5 哈希 | 存储明文密码 |
| 登录请求 | 直接传 MD5 | 直接传明文 |
| 安全性 | 较好（不存明文） | 较差（需存明文） |
| 兼容方案 | 存储明文，登录时 MD5 | 存储明文，直接传 |

**推荐方案：** 账号池存储明文密码，登录时根据实测结果决定是否 MD5。这样两种情况都兼容。

### 1.4 自动验证脚本设计

```python
import hashlib
import requests

def verify_password_format(email, plain_password, captcha_token):
    """测试两种密码格式，确定哪种能成功登录"""
    md5_password = hashlib.md5(plain_password.encode()).hexdigest()

    base_url = "https://monkeycode-ai.com"

    # 测试 MD5 格式
    resp_md5 = requests.post(f"{base_url}/api/v1/users/password-login", json={
        "email": email,
        "password": md5_password,
        "captcha_token": captcha_token,
    })

    # 测试明文格式
    resp_plain = requests.post(f"{base_url}/api/v1/users/password-login", json={
        "email": email,
        "password": plain_password,
        "captcha_token": captcha_token,
    })

    if resp_md5.json().get("code") == 0:
        return "MD5"
    elif resp_plain.json().get("code") == 0:
        return "PLAINTEXT"
    else:
        return "UNKNOWN"
```

---

## 2. 验证码自动化可行性评估

### 2.1 验证码参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 网格大小 | 50x32 | 1600 个格子 |
| 目标数量 | 3 | 需要点击 3 个目标 |
| 挑战过期 | 120s | 2 分钟 |
| Token 过期 | 300s | 5 分钟 |
| 类型 | 图片点击验证码 | go-cap Proof-of-Work |

### 2.2 自动化方案评估

| 方案 | 可行性 | 成本 | 说明 |
|------|--------|------|------|
| **Cookie 复用** | ★★★★★ | 极低 | 浏览器登录后复制 session，完全绕过验证码 |
| **OCR/图像识别** | ★★★☆☆ | 中等 | 需要识别 50x32 网格中的目标，可用多模态 LLM |
| **预设答案重放** | ★☆☆☆☆ | - | 不可行，每次挑战不同 |
| **人工辅助** | ★★★★☆ | 高 | 人工解决验证码，无法规模化 |
| **验证码服务** | ★★★☆☆ | 中等 | 使用第三方验证码识别服务 |

### 2.3 推荐方案

**对于账号池场景，推荐 Cookie 复用方案：**

1. 在浏览器中正常登录 MonkeyCode
2. 从 DevTools → Application → Cookies 复制 `monkeycode_ai_session` 值
3. 配置到账号池中
4. 定期检查 session 有效性，过期后重新登录

**如果需要全自动登录（无人工干预）：**

1. 使用多模态 LLM（如 GPT-4V）识别验证码图片
2. 或使用第三方验证码识别服务
3. 获取 captcha_token 后调用登录 API

---

## 3. 并发 Session 策略分析

### 3.1 Session 存储结构

```text
Redis Hash: {cookie_name}:{user_uuid}
  Field: {cookie_uuid} → JSON session data

Lookup: lookup:{cookie_name}:{cookie_uuid} → user_uuid
```

### 3.2 关键发现

**同一用户可以有多个并发 Session：**

- `Save()` 方法在 Hash 中添加新 field，不删除旧 field
- 每次登录创建新的 cookie UUID，存为 Hash 的新 field
- `Del()` 只删除单个 session entry
- `Trunc()` 删除用户所有 session（踢人）

**这意味着：**
- 同一账号可以同时持有多个有效 session
- 不同 session 可以并发使用不同 API
- 同一 session 不应并发使用同一 WebSocket（互斥）

### 3.3 对账号池的影响

| 策略 | 说明 | 风险 |
|------|------|------|
| **单 session** | 每账号一个 session，串行使用 | 低风险，但吞吐量低 |
| **多 session** | 每账号多个 session，并发使用 | 中风险，可能触发风控 |
| **session 池** | 预创建多个 session，按需分配 | 中风险，需监控异常 |

### 3.4 推荐并发策略

```text
1. 每个账号持有 1 个主 session + 1 个备用 session
2. 主 session 用于正常 API 调用
3. 备用 session 在主 session 失效时立即切换
4. WebSocket 连接使用独占 session（不与其他 HTTP 请求共享）
5. 定期（每 5 分钟）检查 session 有效性
6. Session 失效时自动触发重新登录
```

### 3.5 潜在风控检测

虽然源码中没有显式的并发检测逻辑，但生产环境可能存在：

| 检测方式 | 可能性 | 规避策略 |
|---------|--------|---------|
| 单 session 并发调用检测 | 中 | 不同 session 分担请求 |
| 同一用户多 session 检测 | 低 | 限制每账号 session 数 |
| 异常 IP 检测 | 中 | 使用代理 IP |
| 异常调用频率检测 | 高 | 限制 QPS |

---

## 4. Session 保活协议

### 4.1 有效性检测

```bash
GET /api/v1/users/status
Cookie: monkeycode_ai_session={uuid}
```

**响应判断：**
- `code: 0` → session 有效
- `code: 40100` → session 失效，需要重新登录

### 4.2 保活策略

```text
定期（每 5 分钟）调用 status 端点：
  - 成功 → session 有效，更新最后检查时间
  - 失败 → session 失效，触发重新登录

注意：仅调用 status 可能不足以刷新 Redis TTL
      Session TTL 由 config.Session.ExpireDay 控制
      需要实测确认 status 调用是否刷新 TTL
```

### 4.3 Session 过期处理

```text
检测到 session 失效后：
  1. 从可用池中移除该 session
  2. 检查是否有备用 session
  3. 有备用 → 切换到备用 session
  4. 无备用 → 触发重新登录
  5. 登录失败 → 标记账号异常，从池中移除
```
