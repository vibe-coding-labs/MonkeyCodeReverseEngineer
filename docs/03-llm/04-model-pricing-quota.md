---
description: 模型定价与配额 + 并发控制源码分析 — Go TeamPolicy 完整分析, VM 限制, 号池影响
protocol_version: based on chaitin/MonkeyCode domain/team_policy.go + config.go
confidence: high
last_verified: 2026-06-28
---

# 模型定价与配额（源码增强版）

> **核心源码:** `domain/team_policy.go` — 并发限制、空闲休眠、回收策略
> **核心文件:** `config.go` — VM 数量上限和 TTL 限制
> **核心发现:** 三级订阅模型 (basic/pro/ultra)、并发限制 3、无 API 限流

## 1. 订阅等级与模型访问

### 1.1 三级订阅结构

| AccessLevel | 说明 | 典型模型 |
|-------------|------|---------|
| `basic` | 注册用户默认 | MonkeyCode Basic (Qwen3.5-Plus) + 免费模型 |
| `pro` | 专业订阅 | MonkeyCode Pro (Kimi K2.6) + basic 全部模型 |
| `ultra` | 高级订阅 | MonkeyCode Ultra (GPT-5.5) + 所有模型 |

### 1.2 模型过滤逻辑

```go
// 用户可见模型的过滤条件（从源码推断）
func filterModelsByAccessLevel(models []Model, userLevel string) []Model {
    var allowedLevels []string
    switch userLevel {
    case "ultra":
        allowedLevels = []string{"basic", "pro", "ultra"} // 全部可见
    case "pro":
        allowedLevels = []string{"basic", "pro"}          // basic + pro
    default: // "basic"
        allowedLevels = []string{"basic"}                 // 仅 basic + is_free
    }

    return filter(models, func(m Model) bool {
        return contains(allowedLevels, m.AccessLevel) || m.IsFree
    })
}
```

### 1.3 SubscriptionResp 结构体

```go
type SubscriptionResp struct {
    Plan      string     `json:"plan"`                // "basic" | "pro" | "ultra"
    Source    string     `json:"source,omitempty"`    // "stripe" | "wechat" | "free"
    ExpiresAt *time.Time `json:"expires_at,omitempty"`// null = 永久
    AutoRenew bool       `json:"auto_renew"`          // 是否自动续费
}
```

## 2. 并发任务限制

### 2.1 TeamPolicy 完整源码分析

```go
// domain/team_policy.go — 核心限制字段
const defaultTaskConcurrencyLimit = 3

type TeamTaskVMIdlePolicy struct {
    TaskConcurrencyLimit int  `json:"task_concurrency_limit"` // 默认 3 个并发任务
    SleepSeconds         int  `json:"sleep_seconds"`          // 默认 900s (15min 空闲休眠)
    RecycleSeconds       int  `json:"recycle_seconds"`        // 默认 259200s (3天回收)
}
```

### 2.2 并发限制下达方式

```
用户 → 订阅等级 → TeamPolicy
    │
    ├── TaskConcurrencyLimit = 3（默认）
    │   └── VM 级别限制（非 API 级别）
    │
    ├── SleepSeconds = 900（15 分钟无操作进入休眠）
    │   └── VM 释放资源但保留状态
    │
    └── RecycleSeconds = 259200（3 天后彻底删除）
        └── VM 从磁盘删除
```

### 2.3 并发控制的实现

```go
// taskhook.go — 并发限制执行逻辑（从源码推断）
func (h *TaskHook) ValidateTaskConcurrency(ctx context.Context, userID string) error {
    count, err := h.db.Task.Query().
        Where(
            task.UserID(userID),
            task.StatusIn("running", "pending"),
        ).
        Count(ctx)
    if err != nil {
        return err
    }

    // 获取用户/团队的最大并发限制
    limit := h.policyRepo.GetConcurrencyLimit(ctx, userID)

    if count >= limit {
        return errcode.ErrTaskConcurrencyLimit
    }
    return nil
}
```

## 3. 资源限制全景

### 3.1 限制对比表

| 限制项 | 默认值 | 配置来源 | 在代理中的作用 |
|--------|--------|---------|--------------|
| 并发任务数 | **3** | `team_policy.go` | account-pool 需控制同时使用的账号数 |
| VM 空闲休眠 | **900s (15min)** | `team_policy.go` | 多轮对话的 mode=attach 窗口 |
| VM 回收 | **259200s (3天)** | `team_policy.go` | — |
| VM 数量上限 | 0=不限制 | `config.go:196` `CountLimit` | — |
| VM 存活 TTL | 0=不限制 | `config.go:197` `TTLLimit` | — |
| 每任务 CPU | **2 cores** | 硬编码 | 代理 task-runner 传 core:1 |
| 每任务内存 | **8GB** | 硬编码 | 代理 task-runner 传 memory:1GB |
| 每任务生命周期 | **3600s** | 代理层硬编码 | `TASK_TIMEOUT_MS = 3600000` |
| **API 频率限制** | ❌ 无 | Nginx + Go 中间件均无 | 可高频调用 |
| **验证码频率限制** | ❌ 无 | `go-cap` 闭源模块 | 无频率上限 |

### 3.2 VM 资源分配的双层模型

代理层在 `task-runner.ts createTask()` 中的资源请求：

```typescript
// task-runner.ts — 任务资源请求（可能被后端忽略）
resource: {
  core: 1,                    // 请求 1 核
  memory: 1073741824,         // 请求 1 GB
  life: 3600,                 // 请求 1 小时生命周期
}
```

后端实际分配（源代码硬编码）：

| 资源 | 前端传参 | 后端实际分配 | 说明 |
|------|---------|-------------|------|
| CPU 核数 | `core: 1` | **2 cores** | 后端忽略前端传参硬编码 |
| 内存 | `memory: 1GB` | **8GB** | 后端忽略前端传参硬编码 |
| 生命周期 | `life: 3600` | 尊重前端传参 | 后端以此计算超时 |

### 3.3 限制对号池设计的实际影响

| 考量 | 值 | 对号池的影响 |
|------|------|-------------|
| 每账号并发任务 | 3 | 号池内每个账号最多 3 个同时任务 |
| WS 独占 | 每任务 1 个 WS 连接 | 每个 WS 会话锁定一个账号 |
| HTTP 共享 | 无限制 | HTTP 请求可以从任意 ACTIVE 账号发送 |
| 无 API 限流 | 可高频 | HTTP 请求无需特殊退避（错误 500 除外） |

## 4. 确认无 Rate Limiting

### 4.1 源码层确认

所有 Go 中间件源码中无 rate limiting 相关代码：

```
中间件列表（全部已审查）:
├── middleware/auth.go         — Cookie 验证 + TargetActive（记录活跃时间）
├── middleware/team_auth.go    — 团队角色检查
├── middleware/admin.go        — Admin 角色检查
├── nginx.conf                 — 无 limit_req / limit_conn 指令
└── config.go                  — 全量配置键搜索 → 无止流相关
```

### 4.2 Nginx 配置确认

```nginx
# backend/build/nginx.conf — 搜索全部配置
# 未找到以下任何指令:
#   - limit_req
#   - limit_conn
#   - burst
#   - nodelay
#   - limit_rate
```

## 5. 未知信息

| 问题 | 状态 | 原因 |
|------|------|------|
| 订阅具体价格 | 🟡 需线上 | Stripe 后台配置 |
| Token 余额系统 | 🟡 需线上 | 闭源支付组件 |
| 模型级别 Token 价格 | 🟡 需线上 | 同上 |
| 生产环境 Nginx 限流 | 🟡 需线上 | 开源配置可能不同 |
| 免费模型限制 | 🟡 推测有限 | 可能后端另有闭源限制 |

---

## 相关章节

- [模型管理 API](01-model-management-api.md) — CRUD 端点
- [订阅计费 API](../05-api/04-subscription-billing.md) — 订阅详情
- [代理号池管理](../07-proxy/02-account-pool.md) — 并发控制影响
- [VM 资源管理](../06-vm-taskflow/05-resource-management.md) — VM 资源配置
