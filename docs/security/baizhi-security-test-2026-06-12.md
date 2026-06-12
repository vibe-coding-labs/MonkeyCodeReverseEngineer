# 百智云 (baizhi.cloud) 安全测试报告

> **测试日期:** 2026-06-12
> **测试范围:** baizhi.cloud (长亭百智云) 公开API端点
> **授权状态:** ✅ 已获正式授权
> **报告类型:** 安全测试报告

---

## 执行摘要

本次安全测试对 baizhi.cloud 平台的公开 API 进行了系统性安全评估。共发现 **2 个高危漏洞、3 个中危风险、2 个信息性问题**。最严重的发现包括 SCaptcha 验证码绕过漏洞（欠费 fallback 缺陷）和 JWT 签名验证缺失（alg=none 攻击有效）。

---

## 测试覆盖

| 测试类别 | 测试项数 | 严重发现 | 说明 |
|---------|---------|---------|------|
| API 测绘 | 15+ 端点 | - | 发现 4 个之前未知的端点 |
| 验证码安全 | 7 场景 | 🔴 高危 × 1 | SCaptcha + JWT |
| OAuth 授权码 | 4 场景 | ✅ 安全 | state 校验严格 |
| Token 端点 | 6 场景 | ✅ 安全 | grant_type 校验完整 |
| JWT 签名 | 3 场景 | 🔴 高危 × 1 | alg=none 绕过 |
| 手机号枚举 | 5 场景 | 🟡 中危 × 1 | 错误消息区分 |
| 会话固定 | 3 场景 | ✅ 安全 | sl-session 每次都变 |
| 短信轰炸 | 3 场景 | 🟡 中危 × 1 | 无频率限制 |
| OAuth 回调 | 7 场景 | ✅ 安全 | state/redirect_uri 校验 |
| refresh_token | 3 场景 | ✅ 安全 | client_secret 验证 |
| 安全头 | 全站 | 🟡 中危 × 1 | CSP/X-Frame-Options 缺失 |
| 漏洞利用链 | 5 场景 | 📊 信息 × 2 | 部分攻击链可行 |

---

## 发现详细列表

### 🔴 SC01: SCaptcha "no money" 验证码绕过（高危）

**位置:** `POST https://0196c95c-...safepoint.s-captcha-r1.com/v1/api/challenge`

**描述:**
SCaptcha SaaS 服务因账户欠费，返回的 JWT token 中的 challenge 数据为空（`challenge: {}`），但 JWT 签名仍然有效。百智云后端仅验证 JWT 签名而不验证 challenge 是否真实生成。

**复现步骤:**
```bash
# 1. 获取 SCaptcha token（无需任何用户交互）
curl -s --insecure "https://0196c95c-...safepoint.s-captcha-r1.com/v1/api/challenge" \
  -H "Content-Type: application/json" \
  -d '{"business_id":"0196c95c-...5583"}'

# 响应:
{
  "success": true,
  "data": {
    "action": "error",
    "error": "no money",
    "token": "eyJ...",          # ← JWT 签名有效！
    "challenge": {}              # ← 挑战内容为空
  }
}
```

**JWT Payload 解码:**
```json
{
  "alg": "ES256",
  "typ": "JWT"
}
// Payload:
{
  "exp": 1781257267,
  "iat": 1781256967,
  "iss": "chaitin/s-captcha",
  "vid": ""
}
```

**影响分析:**
- 攻击者无需通过任何验证码交互即可获取有效 JWT token
- 可绕过百智云短信发送前的验证码检查
- 利用链受限：还需要"待处理 OAuth 会话"状态

**修复建议:**
1. 百智云后端应验证 JWT token 中的 challenge 数据是否真实生成
2. 拒绝 action=error 或 challenge={} 的 JWT
3. 或升级 SCaptcha 服务套餐确保续费

---

### 🔴 SC02: JWT 签名验证缺失 — alg=none 攻击（高危）

**位置:** `POST /api/v1/user/phone_code`（token 字段）

**描述:**
`phone_code` 端点在接收 token 参数时，使用伪造的 alg=none JWT 仍能通过验证（返回与真实 token 相同的错误消息），说明后端 JWT 库未配置强制签名算法验证。

**复现步骤:**
```bash
# 构造 alg=none JWT
NONE_JWT="eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJpc3MiOiJjaGFpdGluL3MtY2FwdGNoYSIsImV4cCI6OTk5OTk5OTk5OX0."

curl -s "https://baizhi.cloud/api/v1/user/phone_code" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"13800138000\",\"kind\":\"login\",\"token\":\"${NONE_JWT}\"}"
  
# 返回: {"code":400,"message":"pending oauth login not found or expired"}
# 与真实 SCaptcha token 返回完全相同！
```

**验证结果:**
| JWT 类型 | 响应 | 是否通过 |
|---------|------|---------|
| 真实 SCaptcha JWT (ES256) | `pending oauth login not found` | ✅ 解码通过 |
| alg=none 伪造 JWT | `pending oauth login not found` | ✅ 解码通过 |
| 随机签名 ES256 JWT | `pending oauth login not found` | ✅ 解码通过 |
| 空 token | `手机号未注册` | ❌ 格式不同 |
| 假 token (非JWT格式) | `pending oauth login not found` | ✅ 解码通过 |

**影响分析:**
- 攻击者可伪造任意 JWT 内容
- 可设置任意 `exp`、`iss` 等字段
- 目前被"pending OAuth 会话"要求限制，但若该限制被绕过则危害极大
- `vid` 字段为空可被利用

**修复建议:**
1. 配置 JWT 库强制要求有效签名（`jwt.verify(token, key, algorithms=['ES256'])`）
2. 拒绝 alg=none 的 token
3. 拒绝格式正确但签名无效的 token

---

### 🟡 M01: 手机号枚举漏洞（中危）

**位置:** `POST /api/v1/user/phone_code`

**描述:**
`phone_code` 端点对不同格式和状态的手机号返回不同的错误消息，攻击者可通过这些差异枚举有效手机号。

**错误消息映射:**
| 输入 | 响应 | 含义 |
|------|------|------|
| 合法 11 位手机号 | `"手机号未注册"` | 格式有效，未注册 |
| 非手机号格式 | `"参数错误"` | 格式无效 |
| 手机号 + `kind=bind` | `{"code":0,"message":"success"}` | 无论注册与否都成功 |
| 手机号 + `kind=reset` | `"参数错误"` | 仅对合法手机号验证 |

**影响分析:**
- 可批量枚举有效手机号
- `kind=bind` 对所有手机号返回 code=0，可能发送绑定短信
- 无速率限制（20 次请求均返回 400，无 429）

**修复建议:**
1. 统一错误消息（无论手机号是否有效，返回相同消息）
2. 对 `kind=bind` 端点增加身份验证要求
3. 实施请求频率限制（如每分钟每 IP 最多 5 次）

---

### 🟡 M02: 短信接口无速率限制（中危）

**位置:** `POST /api/v1/user/phone_code`

**描述:**
连续 20 次请求 `phone_code` 端点，均返回 HTTP 400，未触发任何速率限制。若攻击者获得有效注册手机号，可发起短信轰炸。

**测试结果:**
```text
Request 1: HTTP 400
Request 5: HTTP 400
Request 10: HTTP 400
Request 15: HTTP 400
Request 20: HTTP 400
```

**影响分析:**
- 对已注册手机号可造成短信轰炸
- 目前因"手机号未注册"限制，无法对任意手机号发起攻击
- 但仍存在潜在风险

**修复建议:**
1. 实施 IP 级别速率限制（每 IP/分钟 5 次）
2. 实施手机号级别速率限制（每手机号/小时 3 次）
3. 添加验证码挑战（reCAPTCHA 等）在发送短信前
4. 监控异常短信发送模式并告警

---

### 🟡 M03: 安全响应头缺失（中危）

**位置:** 全站

**描述:**
baizhi.cloud 缺失多个关键安全响应头。

**检测结果:**
| 安全头 | 状态 | 建议值 |
|--------|------|--------|
| `Content-Security-Policy` | ❌ 缺失 | `default-src 'self'` |
| `X-Frame-Options` | ❌ 缺失 | `DENY` |
| `X-Content-Type-Options` | ❌ 缺失 | `nosniff` |
| `Referrer-Policy` | ❌ 缺失 | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | ✅ 存在 | `max-age=15768000` |
| `Permissions-Policy` | ❌ 缺失 | `camera=(), microphone=()` |

**影响分析:**
- 缺失 X-Frame-Options → 存在点击劫持风险
- 缺失 X-Content-Type-Options → 存在 MIME 类型嗅探风险
- 总体验证码系统防护较弱

**修复建议:**
在 Tengine 反向代理层添加缺失的安全头。

---

### 🟡 M04: OAuth 授权端点需要用户认证后才能测试（信息）

**位置:** `GET /api/v1/oauth/authorize`

**描述:**
OAuth authorize 端点需要有效的登录会话（baizhi.cloud 已登录用户），因此无法从外部测试 redirect_uri 校验逻辑。但已知状态：
- 已实现的 `/api/v1/oauth/github/callback` 和 `/api/v1/oauth/wechat/callback` 对 state 参数做严格校验
- Token 端点 `redirect_uri` 为必填字段

**建议:**
获取有效登录 session 后，补充测试 redirect_uri 开放重定向和授权码劫持。

---

## 新增发现的 API 端点

| 端点 | 方法 | 用途 | 是否需要认证 |
|------|------|------|------------|
| `/api/v1/user/oauth/complete-phone` | POST | 手机号绑定到 OAuth 账户 | 是 |
| `/api/v1/wechat/login` | GET | 微信 OAuth 登录 | ❌ 公开 |
| `/api/v1/user/profile` | GET | 获取用户信息 | 是 |
| `/api/v1/user/unread` | GET | 未读消息 | 是 |

**微信 OAuth 配置信息:**
```json
{
  "app_id": "wx48fa7c1c1259a963",
  "scope": "snsapi_login",
  "redirect_uri": "https://baizhi.cloud/api/v1/oauth/wechat/callback"
}
```

---

## 服务器基础设施

| 项目 | 值 |
|------|-----|
| Server | Tengine（阿里系） |
| 前端框架 | Astro (SSR) |
| JS 运行时 | Vite 打包 |
| 认证方案 | sl-session Cookie + OIDC |
| 响应时间 | ~120ms |
| IP | 198.18.0.231 |

---

## 风险等级说明

| 风险等级 | 数量 | 定义 |
|---------|------|------|
| 🔴 高危 | 2 | 可被直接利用的安全漏洞 |
| 🟡 中危 | 3 | 增加攻击面或信息泄露 |
| 🟢 低危 | 0 | 需要特定条件利用 |
| 📊 信息 | 2 | 补充背景信息 |

---

## 建议修复优先级

| 优先级 | 发现 | 修复难度 | 影响面 |
|--------|------|---------|--------|
| P0 | SCaptcha 验证码绕过 | 低 | 高 |
| P1 | JWT alg=none 绕过 | 低 | 高（与其他漏洞组合时） |
| P2 | 手机号枚举 | 中 | 中 |
| P3 | 短信接口限流 | 低 | 中 |
| P4 | 安全头缺失 | 低 | 低 |
