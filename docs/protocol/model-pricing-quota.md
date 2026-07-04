> ⚠️ **此文件为原始分析档案** — 内容已被 docs/ 下结构化章节覆盖。详见 [docs/protocol/README.md](./README.md)。

# MonkeyCode 模型清单与额度限制分析报告

> **分析日期:** 2026-06-13
> **依据:** 后端 Go 源码 + 前端 Swagger API 定义 + Electron ASAR + 已有逆向文档
> **状态:** 待线上 API 实测确认

---

## 1. 支持的模型提供商 (11 个)

从 `backend/pkg/llm/client.go` 导出：

| # | Provider | 常量值 | 默认 Base URL | 默认模型 |
|---|----------|--------|---------------|---------|
| 1 | SiliconFlow | `SiliconFlow` | https://api.siliconflow.cn/v1 | - |
| 2 | OpenAI | `OpenAI` | https://api.openai.com/v1 | `gpt-4o` |
| 3 | Ollama | `Ollama` | http://localhost:11434/v1 | - |
| 4 | DeepSeek | `DeepSeek` | https://api.deepseek.com/v1 | `deepseek-reasoner`, `deepseek-chat` |
| 5 | Moonshot | `Moonshot` | https://api.moonshot.cn/v1 | `moonshot-v1-auto/8k/32k/128k` |
| 6 | Azure OpenAI | `AzureOpenAI` | {azure_endpoint}/openai | `gpt-4/4o/4o-mini/4o-nano/4.1/4.1-mini/4.1-nano/o1/o1-mini/o3/o3-mini/o4-mini` |
| 7 | 百智云 | `BaiZhiCloud` | https://api.baizhicloud.com/v1 | - |
| 8 | 腾讯混元 | `Hunyuan` | https://api.hunyuan.tencent.com/v1 | - |
| 9 | 百炼 | `BaiLian` | https://api.bailian.com/v1 | - |
| 10 | 火山引擎 | `Volcengine` | https://api.volcengine.com/v1 | `doubao-seed-1.6-250615`, `doubao-seed-1.6-flash-250615`, `doubao-seed-1.6-thinking-250615`, `doubao-1.5-thinking-vision-pro-250428`, `deepseek-r1-250528` |
| 11 | Google Gemini | `Gemini` | https://generativelanguage.googleapis.com/v1beta | - |

> **注意:** 上面列出的是**品牌默认模型**（源码中 `ModelProviderBrandModelsList` 静态映射），实际线上可用模型由管理员配置，需要通过 `GET /api/v1/users/models` 获取实时列表。

---

## 2. 模型字段结构

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "provider": "OpenAI",
  "api_key": "",
  "base_url": "",
  "model": "gpt-4o",
  "temperature": 0.7,
  "is_default": false,
  "created_at": 1715299200,
  "updated_at": 1715299200,
  "weight": 1,
  "owner": {
    "id": "admin-uuid",
    "type": "public",
    "name": "MonkeyCode AI Team"
  },
  "interface_type": "openai_chat",
  "is_free": false,
  "access_level": "pro",
  "last_check_at": 1715299200,
  "last_check_success": true,
  "last_check_error": "",
  "thinking_enabled": false,
  "context_limit": 128000,
  "output_limit": 16384
}
```

---

## 3. 模型访问级别 (订阅等级)

| AccessLevel | 说明 | 可用模型 |
|-------------|------|---------|
| `basic` | 基础订阅（默认注册用户） | monkeycode-basic (`qwen3.5-plus`) + 免费模型 (is_free=true) |
| `pro` | 专业订阅 | monkeycode-pro (`kimi-k2.6`) + basic 模型 |
| `ultra` | 高级订阅 | monkeycode-ultra (`gpt-5.5`) + 所有模型（含 pro、basic） |

其中 `monkeycode-basic` / `monkeycode-pro` / `monkeycode-ultra` 是 MonkeyCode 平台自建的**代理模型标识**，它们映射到实际的第三方模型：
- `monkeycode-basic` → qwen3.5-plus（通义千问）
- `monkeycode-pro`  → kimi-k2.6（月之暗面）
- `monkeycode-ultra` → gpt-5.5（OpenAI）

### 模型访问逻辑

```go
// 后端代码逻辑:
// 1. 用户通过 session 获取其 subscription_level
// 2. 模型列表根据用户 subscription_level 过滤返回
// 3. basic 用户只能看到 access_level=basic 或 is_free=true 的模型
// 4. pro 用户能看到 basic + pro 的模型
// 5. ultra 用户能看到所有模型
```

---

## 4. 模型所有者层级

| OwnerType | 说明 | 可见性 |
|-----------|------|--------|
| `private` | 普通用户自行创建 | 仅创建者可见 |
| `team`   | 企业用户创建，团队内共享 | 团队内所有成员 |
| `public` | 管理员创建，全平台公开 | 所有认证用户 |

---

## 5. 用户角色体系

| 角色 | 常量值 | 说明 | Session Cookie |
|------|--------|------|---------------|
| 个人用户 | `individual` | 普通注册用户 | `monkeycode_ai_session` |
| 企业用户 | `enterprise` | 有团队的企业用户 | `monkeycode_ai_session` |
| 企业子账户 | `subaccount` | 企业下的子账户 | `monkeycode_ai_session` |
| 系统管理员 | `admin` | 平台管理员，配置公共资源 | `monkeycode_ai_session` |
| Git 任务 | `gittask` | 全自动 git 任务专用 | 内部使用 |

---

## 6. 订阅与余额 API

### 6.1 订阅 API

| 方法 | 路径 | 说明 | 已知格式 |
|------|------|------|---------|
| GET | `/api/v1/users/subscriptions` | 列出订阅 | 未知 |
| POST | `/api/v1/users/subscriptions` | 创建订阅 | 未知 |
| GET | `/api/v1/users/subscriptions/current` | 当前订阅 | 返回 `{"code":0,"data":{...}}`，非 Pro 用户返回非 200 |

### 6.2 `SubscriptionResp` 结构体（从 Go 源码确认）

```go
type SubscriptionResp struct {
    Plan      string     `json:"plan"`
    Source    string     `json:"source,omitempty"`
    ExpiresAt *time.Time `json:"expires_at,omitempty"`
    AutoRenew bool       `json:"auto_renew"`
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `plan` | string | 订阅套餐名称（可能是 `"basic"` / `"pro"` / `"ultra"`） |
| `source` | string | 订阅来源（如 `"stripe"` / `"wechat"` / `"free"`） |
| `expires_at` | *time.Time | 到期时间，null 表示永久/无期限 |
| `auto_renew` | bool | 是否自动续费 |

> **注意:** `SubscriptionResp` 与 `User` 实体在 Go 源码中是 **分离的**——订阅不是 `User` 结构体的字段，而是独立查询的。这意味着订阅信息可能在 `GET /api/v1/users/subscriptions/current` 中返回。

### 6.3 用户实体中的 `subscription_level`

Go 源码中 `User` 结构体并没有 `subscription_level` 字段。但 `MonkeyCodeUser` 接口（在 proxy `types.ts` 中定义）包含了 `subscription_level: string`。可能此信息来自：
1. Redis Session 中的数据中包含了 `subscription_level`
2. 或 `GET /api/v1/users/subscriptions/current` 返回的订阅信息

### 6.4 用户 `Role` 字段

从 Go 源码 `User` 实体确认：
```go
type User struct {
    ID            uuid.UUID    `json:"id"`
    Name          string       `json:"name"`
    AvatarURL     string       `json:"avatar_url"`
    Email         string       `json:"email"`
    Role          UserRole     `json:"role"`     // individual | enterprise | subaccount | admin | gittask
    Status        UserStatus   `json:"status"`   // active | inactive | banded
    // ... 其他字段
}
```

> **注意:** 用户 **没有** `Balance`/`Credits`/`Token` 余额字段。Go 源码中 `domain/user.go` 的 `User` 结构体不含任何与余额/积分相关的字段。

### 6.5 用户状态

| 状态 | 值 | 说明 |
|------|-----|------|
| `active` | `"active"` | 正常 |
| `inactive` | `"inactive"` | 未激活 |
| `banded` | `"banded"` | 被封禁（注意：源码拼写为 `"banded"` 而非 `"banned"`） |

### 6.6 余额 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/users/balance` | Token 余额（已废弃，测试确认 `/api/v1/users/status` 可替代） |

---

## 7. 额度限制 (Rate Limiting) 分析

### 7.1 开源代码结论: **无任何限流**

基于 `chaitin/MonkeyCode` 开源后端源码完整审查：

| 组件 | 限流实现 | 证据 |
|------|---------|------|
| 认证中间件 | ❌ 无 | `middleware/auth.go` 仅做认证检查 |
| API 中间件 | ❌ 无 | 仅有 TargetActive（记录活跃时间）和 Audit（审计日志） |
| 验证码 | ❌ 无 | go-cap 配置 50x32 网格，无频率控制 |
| Session | ❌ 无 | `session.Get()` 直接从 Redis 读取，无并发检查 |
| VM 创建 | ❌ 无 | 无创建频率限制 |

### 7.2 生产环境可能有限流

虽然开源代码无限制，但生产环境闭源组件可能添加：

| 限流类型 | 可能性 | 推测限制 |
|---------|--------|---------|
| API 级别限流 (RPM) | 低-中 | 可能通过反向代理层（如 Nginx）限制 60-120 req/min |
| 并发任务限制 | 中 | 每账号可能限制 3-5 个并发任务 |
| 每天请求限制 | 中 | 可能基于订阅等级（basic 每日 100 次, pro 每日 1000 次） |
| VM 创建频率 | 中 | 可能限制每分钟创建 VM 数 |
| Token 使用限制 | 高 | balance 端点暗示有 Token 配额系统 |

### 7.3 对账号池的设计影响

| 建议 | 理由 |
|------|------|
| 每个账号最多 2 个并发 session | Redis Hash 多 field 设计支持，保守使用 |
| 每个 session 同时最多 1 个 WS 连接 | WebSocket 独占模式需要 |
| HTTP QPS < 5/账号 | 保守估算，避免触发未知限流 |
| 账号池大小: 5-20 个账号 | 根据 Codex 并行度决定 |

---

## 8. 模型使用费用模型

**当前未知信息（需要线上测试确认）:**

| 问题 | 状态 |
|------|------|
| 免费模型 (is_free=true) 是否有使用量限制？ | 🔴 未知 |
| Pro 订阅的价格是多少？ | 🔴 未知 |
| Token 余额系统如何工作？ | 🔴 未知 |
| 用户创建私有模型需要付费吗？ | 🟡 推测免费，自行提供 API Key |
| 任务创建是否需要消耗积分/Token？ | 🔴 未知 |
| 不同模型的 Token 价格是否不同？ | 🔴 未知 |

**已知线索:**
- `is_free: true` 的模型可能是完全免费的
- `access_level: basic` 的模型需要 basic 及以上订阅
- balance API 暗示存在 Token 余额/积分系统
- 订阅 API 暗示有付费等级（basic 免费, pro/ultra 付费）

---

## 9. 待线上实测确认项

| # | 测试项 | 测试方法 | 预期数据 |
|---|--------|---------|---------|
| 1 | 用户模型清单 | `GET /api/v1/users/models` 带有效 session | 完整模型列表（provider, model, is_free, access_level, context_limit, output_limit） |
| 2 | 公开模型 | 查看模型中 owner.type=public 的条目 | 免费的公开模型列表 |
| 3 | 当前订阅 | `GET /api/v1/users/subscriptions/current` | subscription_level, 过期时间等 |
| 4 | 用户余额 | `GET /api/v1/users/balance` 或 `/status` | token 余额、已用量 |
| 5 | 并发限制 | 同时创建 3 个以上任务 | 是否报错、最大并发数 |
| 6 | 创建私有模型 | `POST /api/v1/users/models` 自己填 API Key | 确认是否可以绕过订阅限制 |
| 7 | 创建任务消耗 | 观察创建任务前后 balance 变化 | 每次任务消耗多少 token |
| 8 | Session 30 天验证 | 创建 session 后等待 30 天 | 确认 40100 |
| 9 | 公共模型 API Key | 抓包观察创建任务时的 LLMProviderReq | 后端是否自动注入真实 API Key |
| 10 | 品牌默认模型 | 比较 admin 配置的公开模型 vs 源码默认列表 | 哪些模型被管理员实际启用了 |

---

## 10. 已知协议文档清单

### 已完成 (13 份)

| 文档 | 大小 | 完成度 | 说明 |
|------|------|--------|------|
| `auth-protocol-complete.md` | ~40KB | 98% | 5 种登录方式、Session 机制、验证码系统 |
| `llm-protocol-complete.md` | ~36KB | 95% | 3 种接口类型、任务周期、模型管理 |
| `websocket-protocol.md` | ~7KB | 90% | 3 个 WS 通道、ACP 事件 |
| `api-endpoints.md` | ~10KB | 95% | 100+ 端点映射 |
| `taskflow-vm-analysis.md` | ~25KB | 85% | VM 生命周期、Docker 容器架构 |
| `architecture.md` | ~11KB | 90% | 完整数据流和组件关系 |
| `multi-turn-design.md` | ~10KB | 90% | 多轮对话设计 |
| `account-pool-protocol.md` | ~12KB | 95% | 账号池通信协议 |
| `auth-protocol-pool-complete.md` | ~16KB | 95% | 账号池认证协议 |
| `auth-automation-analysis.md` | ~8KB | 90% | 认证自动化分析 |
| `authorization-matrix.md` | ~8KB | 90% | 授权层级矩阵 |
| `auth-unresolved-verification.md` | ~12KB | 100% | 未决问题验证 |
| `llm-integration.md` | ~5KB | 85% | LLM 集成协议 |

### 待补充

| 文档 | 优先级 | 内容 |
|------|--------|------|
| `model-pricing-quota.md` | P0 | ⁠本文 — 模型清单、定价、额度限制 |
| `conversation-api.md` | P1 | Conversation API 请求/响应格式 |
| `production-test-report.md` | P0 | 线上 API 实测结果 |