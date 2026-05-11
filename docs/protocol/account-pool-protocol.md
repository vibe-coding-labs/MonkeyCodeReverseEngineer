# MonkeyCode 账号池通信协议

> 分析日期: 2026-05-11

---

## 1. 概述

本文档定义 MonkeyCode 账号池的完整通信协议，包括 Session 生命周期管理、API 调用认证注入、错误恢复策略和并发管理。

---

## 2. Session 生命周期管理

### 2.1 生命周期状态

```text
                    ┌──────────┐
                    │  CREATED │ ← 登录成功/Cookie 导入
                    └────┬─────┘
                         │
                    ┌────▼─────┐
               ┌──→│  ACTIVE  │←── 保活检查通过
               │    └────┬─────┘
               │         │
               │    ┌────▼─────┐
               │    │ EXPIRED  │ ← status 返回 40100
               │    └────┬─────┘
               │         │
               │    ┌────▼─────┐
               │    │ REFRESH  │ ← 自动重新登录
               │    └────┬─────┘
               │         │
               │    ┌────▼─────┐
               │    │  ACTIVE  │ ← 登录成功，新 session
               │    └──────────┘
               │
          ┌────▼─────┐
          │  INVALID │ ← 账号被封禁/密码错误
          └──────────┘
```

### 2.2 Session 获取方式

| 方式 | 自动化程度 | 说明 |
|------|-----------|------|
| 浏览器 Cookie 导入 | 手动 | 从 DevTools 复制 `monkeycode_ai_session` 值 |
| 密码登录 API | 半自动 | 需要验证码 token |
| 团队管理员登录 | 半自动 | 需要验证码 token |
| 百智云 OAuth | 手动 | 需要浏览器交互 |
| Admin Impersonate | 不可用 | 闭源 token 生成 |

**推荐：浏览器 Cookie 导入 + 自动保活**

### 2.3 Session 数据结构

```typescript
interface PoolSession {
  id: string              // cookie UUID (monkeycode_ai_session 的值)
  userId: string          // 用户 UUID
  email: string           // 用户邮箱
  role: UserRole          // 用户角色
  status: SessionStatus   // CREATED | ACTIVE | EXPIRED | INVALID
  createdAt: number       // 创建时间戳
  lastCheckedAt: number   // 最后检查时间戳
  lastUsedAt: number      // 最后使用时间戳
  failCount: number       // 连续失败次数
  metadata: {
    source: 'import' | 'login' | 'refresh'  // 来源
    ipAddress?: string     // 登录 IP
  }
}

type UserRole = 'individual' | 'enterprise' | 'subaccount' | 'admin' | 'gittask'
type SessionStatus = 'CREATED' | 'ACTIVE' | 'EXPIRED' | 'INVALID'
```

---

## 3. API 调用认证注入

### 3.1 请求头规范

```http
GET /api/v1/users/models HTTP/1.1
Host: monkeycode-ai.com
Cookie: monkeycode_ai_session={session_uuid}
Content-Type: application/json
```

### 3.2 WebSocket 认证

```http
GET /api/v1/users/tasks/stream?id={taskId}&mode=new HTTP/1.1
Host: monkeycode-ai.com
Upgrade: websocket
Connection: Upgrade
Cookie: monkeycode_ai_session={session_uuid}
```

### 3.3 认证注入流程

```text
1. 从 Session 池选择一个 ACTIVE session
2. 注入 Cookie: monkeycode_ai_session={session.id}
3. 发送请求
4. 检查响应：
   - 成功 (code: 0) → 更新 lastUsedAt
   - 认证失败 (code: 40100) → 标记 session EXPIRED，重试
   - 权限不足 (code: 40300) → 记录，降级处理
   - 其他错误 → 记录，返回错误
```

---

## 4. 错误码处理与自动恢复

### 4.1 错误码映射

| 错误码 | HTTP 状态 | 含义 | 自动恢复策略 |
|--------|----------|------|-------------|
| `0` | 200 | 成功 | 无需处理 |
| `40100` | 401 | 未授权/session 失效 | 标记 EXPIRED → 切换 session → 重试 |
| `40300` | 403 | 权限不足 | 记录 → 降级到低权限 API |
| `40001` | 400 | 验证码失败 | 重新获取验证码 |
| `40002` | 400 | 账号密码错误 | 标记账号 INVALID |
| `40003` | 400 | 用户被封禁 | 标记账号 INVALID，从池移除 |
| `40004` | 400 | 用户未激活 | 标记账号 INVALID |
| `50000` | 500 | 服务器内部错误 | 重试（指数退避） |

### 4.2 自动恢复流程

```text
请求失败
  ↓
判断错误码
  ↓
40100 (session 失效)
  → 标记当前 session EXPIRED
  → 从池中选择下一个 ACTIVE session
  → 使用新 session 重试请求
  → 无可用 session → 触发登录流程
  ↓
40002/40003/40004 (账号问题)
  → 标记账号 INVALID
  → 从池中移除
  → 通知管理员
  ↓
50000 (服务器错误)
  → 指数退避重试 (1s, 2s, 4s, 8s, max 30s)
  → 3 次重试后放弃
```

---

## 5. 多账号并发与负载均衡

### 5.1 并发模型

```text
┌──────────────────────────────────────────────────┐
│                  Session Pool                     │
│                                                   │
│  Account A ──→ [Session A1 (ACTIVE)]             │
│           └──→ [Session A2 (ACTIVE)]             │
│                                                   │
│  Account B ──→ [Session B1 (ACTIVE)]             │
│           └──→ [Session B2 (EXPIRED)]            │
│                                                   │
│  Account C ──→ [Session C1 (ACTIVE)]             │
│                                                   │
└──────────────────────────────────────────────────┘
         │
         ▼
   Load Balancer (Round-Robin / LRU)
         │
         ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐
   │ Worker 1 │  │ Worker 2 │  │ Worker 3 │
   └─────────┘  └─────────┘  └─────────┘
```

### 5.2 负载均衡策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| **Round-Robin** | 轮询分配 session | 均匀负载 |
| **Least-Recently-Used** | 优先使用最久未用的 session | 防止 session 过期 |
| **Random** | 随机选择 session | 简单实现 |
| **Weighted** | 按账号权重分配 | 不同账号有不同配额 |

**推荐：LRU + Round-Robin 混合**
- 优先使用 LRU 防止 session 过期
- 同等 LRU 时间时 Round-Robin 分配

### 5.3 并发安全规则

```text
1. 同一 session 不能同时用于两个 WebSocket 连接
2. 同一 session 可以并发用于 HTTP API 请求
3. WebSocket 连接独占一个 session，直到连接关闭
4. HTTP 请求不独占 session，用完即还
5. 每个账号最多 2 个并发 session
```

### 5.4 Session 选择算法

```python
def select_session(pool, request_type="http"):
    """从池中选择最合适的 session"""
    active_sessions = [s for s in pool if s.status == "ACTIVE"]

    if not active_sessions:
        raise NoAvailableSession()

    if request_type == "websocket":
        # WebSocket 需要独占 session
        available = [s for s in active_sessions if not s.is_exclusive]
        if not available:
            raise NoAvailableSession()
        session = min(available, key=lambda s: s.lastUsedAt)
        session.is_exclusive = True
        return session
    else:
        # HTTP 请求不独占
        return min(active_sessions, key=lambda s: s.lastUsedAt)
```

---

## 6. 保活与监控

### 6.1 有效性检测策略

> **重要**: 调用 status 端点**不会刷新** Redis TTL。Session 有效期从 Save 时固定（默认 30 天），无法续期。

```text
检测间隔: 1 小时（非保活，仅检测有效性）
检测方法: GET /api/v1/users/status

检测流程:
  1. 选择 lastCheckedAt > 1h 的 session
  2. 调用 status 端点
  3. 成功 → 更新 lastCheckedAt
  4. 失败 → 标记 EXPIRED，尝试刷新
  5. Session 过期前 1-2 天主动重新登录获取新 session
```

### 6.2 监控指标

| 指标 | 说明 | 告警阈值 |
|------|------|---------|
| 可用 session 数 | ACTIVE 状态的 session 数量 | < 总数的 50% |
| session 失效率 | 每小时 EXPIRED 的 session 数 | > 2/小时 |
| 平均响应时间 | API 调用平均延迟 | > 5s |
| 错误率 | 非成功响应比例 | > 10% |
| 账号异常数 | INVALID 状态的账号数 | > 0 |

### 6.3 告警规则

```text
1. 可用 session 数 < 2 → P0 告警
2. session 失效率 > 5/hour → P1 告警
3. 账号异常数 > 0 → P1 告警（可能有封号风险）
4. 错误率 > 20% → P2 告警
```

---

## 7. 推荐账号池架构

### 7.1 最小可用架构

```text
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ Config File  │────→│ Session Pool │────→│  MonkeyCode  │
│ (accounts)   │     │  (in-memory) │     │    API       │
└─────────────┘     └──────────────┘     └──────────────┘
                            │
                     ┌──────▼──────┐
                     │  Health     │
                     │  Checker    │
                     │  (5min)     │
                     └─────────────┘
```

### 7.2 生产级架构

```text
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ Account DB   │────→│ Session Pool │────→│  MonkeyCode  │
│ (encrypted)  │     │  (Redis)     │     │    API       │
└─────────────┘     └──────────────┘     └──────────────┘
       │                   │                     │
       │            ┌──────▼──────┐              │
       │            │  Health     │              │
       │            │  Checker    │              │
       │            │  (5min)     │              │
       │            └─────────────┘              │
       │                   │                     │
       │            ┌──────▼──────┐              │
       │            │  Metrics &  │              │
       │            │  Alerts     │              │
       │            └─────────────┘              │
       │                                         │
┌──────▼──────┐     ┌──────────────┐             │
│ Auto-Login  │────→│  Proxy       │─────────────┘
│ (captcha)   │     │  (OpenAI)    │
└─────────────┘     └──────────────┘
```

### 7.3 配置文件格式

```json
{
  "accounts": [
    {
      "email": "user1@example.com",
      "password": "plain_or_md5_password",
      "password_format": "auto",
      "role": "individual",
      "max_sessions": 2,
      "tags": ["pool-1", "gpt-4o"]
    }
  ],
  "pool": {
    "health_check_interval": 300,
    "session_timeout": 86400,
    "max_retries": 3,
    "retry_backoff": [1, 2, 4],
    "load_balance": "lru"
  },
  "proxy": {
    "base_url": "https://monkeycode-ai.com",
    "default_model": "monkeycode/OpenAI/gpt-4o"
  }
}
```
