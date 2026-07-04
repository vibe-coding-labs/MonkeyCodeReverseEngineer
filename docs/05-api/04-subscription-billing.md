---
description: 订阅与计费 API + 号池绕过策略 — Go handler 源码、SubscriptionResp、开源版固定 pro、多账号绕过
protocol_version: based on chaitin/MonkeyCode + proxy/src/account-pool.ts
confidence: high (Go 源码已知), medium (线上付费配置)
last_verified: 2026-06-28
---

# 订阅与计费 API（源码增强版）

> **核心文件:** `subscription/handler/v1/subscription.go` — Go handler
> **绕过方案:** `proxy/src/account-pool.ts` — 多账号轮转
> **核心发现:** 开源版固定返回 pro 计划、号池多账号可绕过订阅限制

## 1. Subscription API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/users/subscriptions` | 列出用户的订阅 |
| POST | `/api/v1/users/subscriptions` | 创建订阅（Stripe Checkout 重定向） |
| GET | `/api/v1/users/subscriptions/current` | 获取当前生效订阅 |
| PUT | `/api/v1/users/subscriptions/:id` | 更新订阅 |
| GET | `/api/v1/users/subscriptions/preview` | 预览订阅价格 |

### 订阅端点关键路径

```
GET /api/v1/users/subscriptions/current
  │
  ├── 开源版 → 固定返回 pro（见 2.1）
  │
  └── 生产版 → 从 Stripe/数据库查询订阅状态
```

## 2. SubscriptionResp 结构体

```go
type SubscriptionResp struct {
    Plan      string     `json:"plan"`                // "basic" / "pro" / "ultra"
    Source    string     `json:"source,omitempty"`    // "stripe" / "wechat" / "free"
    ExpiresAt *time.Time `json:"expires_at,omitempty"`// null = 永久（开源版）
    AutoRenew bool       `json:"auto_renew"`          // 默认 true
}
```

### 2.1 开源版固定返回 pro

```go
// subscription/handler/v1/subscription.go — 开源版简化实现
// 关键发现：开源后端始终返回 pro 计划
func (h *SubscriptionHandler) GetCurrentSubscription(c web.Context) error {
    // 没有实际数据库查询，直接返回硬编码 pro
    return c.JSON(http.StatusOK, SubscriptionResp{
        Plan:      "pro",        // 固定 pro
        Source:    "free",       // 免费来源
        ExpiresAt: nil,          // 永不过期
        AutoRenew: true,
    })
}
```

### 2.2 生产版行为

生产环境的闭源支付组件会有更复杂的逻辑：

```json
// 生产版预期响应体
{
  "plan": "ultra",
  "source": "stripe",
  "expires_at": "2026-07-28T00:00:00Z",
  "auto_renew": true,
  "features": {
    "max_concurrent_tasks": 10,
    "max_team_members": 20,
    "allowed_providers": ["openai", "anthropic", "deepseek"],
    "speech_to_text": true,
    "custom_models": true
  }
}
```

## 3. 号池绕过订阅限制的策略

### 3.1 绕过原理

```
订阅限制模型：
   用户 A（basic） → 只能访问 basic 级别模型
   ↓
号池绕过策略：
   账号 1（pro） → 访问 pro 模型
   账号 2（pro） → 访问 pro 模型
   账号 3（basic）→ 仅 basic 模型
   ↓
   代理根据请求路由到对应账号
```

### 3.2 关键代码

```typescript
// account-pool.ts — 多账号轮转的关键逻辑
// 一个账号 = 一个 AuthManager = 一个独立的 session = 独立的订阅等级

// 创建多个账号配置：
const configs: AccountConfig[] = [
  { email: "pro1@example.com", password: "xxx", cookie: "pro_session_1" },
  { email: "pro2@example.com", password: "xxx", cookie: "pro_session_2" },
  { email: "basic@example.com", password: "xxx", cookie: "basic_session" },
]

// 代理随机/轮转分配请求：
// HTTP 共享模式：取最久未用 ACTIVE 账号
const auth = accountPool.acquireHttp()
// auth → 可能对应 pro 账号 → 可用所有 pro+ 模型
```

### 3.3 限制绕过效果

| 场景 | 单账号效果 | 号池效果 |
|------|-----------|---------|
| 并发任务限制 | 最多 3 个 | N 个账号 × 3 |
| 模型访问限制 | 受订阅等级限制 | 多等级账号覆盖全部模型 |
| Session 过期 | 30 天需重登录 | 每个账号独立管理 |
| 错误隔离 | 单点故障 | 一个账号出问题不影响其他 |

## 4. 支付集成

### 4.1 Stripe Checkout 集成

```go
// Stripe 支付集成（闭源组件，结构从 API 推断）
type PaymentHandler struct {
    stripeClient *stripe.Client  // 生产版使用
}

// POST /api/v1/users/subscriptions → Stripe Checkout 重定向
func (h *SubscriptionHandler) CreateSubscription(c web.Context) error {
    plan := c.Query("plan") // "pro" | "ultra"

    session, err := h.stripeClient.Checkout.Sessions.Create(&stripe.CheckoutSessionParams{
        Mode:       stripe.String("subscription"),
        LineItems:  []*stripe.CheckoutSessionLineItemParams{
            {Price: stripe.String(planPriceID[plan]), Quantity: stripe.Int64(1)},
        },
        SuccessURL: stripe.String("https://monkeycode-ai.com/console/settings"),
        CancelURL:  stripe.String("https://monkeycode-ai.com/pricing"),
    })

    return c.Redirect(http.StatusSeeOther, session.URL)
}
```

### 4.2 微信支付集成

```go
// 微信支付也受支持（source: "wechat"），但实现方式类似
```

## 5. Token 余额系统

### 5.1 已知信息

| 方面 | 状态 | 说明 |
|------|------|------|
| Token 计费 | 🟡 闭源 | 开源版无 balance handler |
| 计费端点 | 🟡 推测 | 可能 `/api/v1/users/balance` |
| 免费额度 | 🟡 推测 | 注册可能赠送额度 |
| 超额处理 | 🟡 推测 | 可能返回 HTTP 402 Payment Required |

### 5.2 开源版行为

开源版 Go 源码中**没有任何 balance/token/credit 相关的 handler**，表明：

1. Token 计费完全在闭源组件中实现
2. 开源版 = 功能受限但免费使用
3. 生产版在开源基础上叠加闭源支付层

## 6. 号池绕过方案分析

### 6.1 可行性

| 维度 | 评估 |
|------|------|
| 模型访问 | ✅ 不同订阅等级账号覆盖不同模型集 |
| 并发任务 | ✅ 每账号 3 并发，N 账号 = 3N 并发 |
| 会话管理 | ✅ 每个账号独立 30 天过期 |
| 免费模型 | ✅ 可单独配置免费账号路由免费请求 |

### 6.2 风险

| 风险 | 级别 | 说明 |
|------|------|------|
| 账号被封 | 🟡 中 | 多账号被检测为异常 |
| 服务条款 | 🟡 中 | 代理使用违反 TOS |
| 功能受限 | 🟢 低 | 闭源功能不可用 |
| 模型选择 | 🟢 低 | 无法精细控制每个请求的账号 |

### 6.3 对抗检测

代理层的指纹伪装系统 (`browser-headers.ts`) 有助于降低检测风险：

```typescript
// 每个账号的请求使用逼真的浏览器请求头
headers: mkHeaders({
  Cookie: `${cookieName}=${cookie}`,
  "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/148.0.0.0",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})
```

---

## 相关章节

- [模型定价与配额](../03-llm/04-model-pricing-quota.md) — access_level 过滤
- [代理号池管理](../07-proxy/02-account-pool.md) — 多账号轮转实现
- [浏览器指纹伪装](../07-proxy/06-browser-fingerprinting.md) — 防止检测