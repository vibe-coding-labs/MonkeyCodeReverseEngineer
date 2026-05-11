# MonkeyCode 授权层级与 API 访问控制矩阵

> 基于 chaitin/MonkeyCode 开源后端源码逆向分析
> 分析日期: 2026-05-11

---

## 1. 角色体系

### 1.1 用户角色 (UserRole)

| 角色 | 常量值 | 说明 | Session Cookie |
|------|--------|------|---------------|
| 个人用户 | `individual` | 普通注册用户 | `sl-session` |
| 企业用户 | `enterprise` | 有团队的企业用户 | `sl-session` |
| 企业子账户 | `subaccount` | 企业下的子账户 | `sl-session` |
| 系统管理员 | `admin` | MonkeyCode AI 管理员，配置公共资源 | `sl-session` |
| Git 任务用户 | `gittask` | 全自动 git 任务专用用户 | 内部使用 |

### 1.2 用户状态 (UserStatus)

| 状态 | 常量值 | 说明 | 对账号池的影响 |
|------|--------|------|---------------|
| 正常 | `active` | 可正常使用 | 可用 |
| 未激活 | `inactive` | 未完成激活流程 | 不可用 |
| 被封禁 | `banded` | 被管理员封禁 | 需从池中移除 |

### 1.3 团队成员角色 (TeamMemberRole)

| 角色 | 说明 | Session Cookie |
|------|------|---------------|
| 团队管理员 | `team_admin` | 管理团队资源、成员 | `monkeycode_ai_team_session` |
| 团队成员 | `team_member` | 使用团队资源 | `monkeycode_ai_team_session` |

### 1.4 资源所有者类型 (OwnerType)

| 类型 | 常量值 | 说明 | 可见性 |
|------|--------|------|--------|
| 私有 | `private` | 用户个人创建 | 仅创建者 |
| 团队 | `team` | 团队共享 | 团队内成员 |
| 公开 | `public` | 管理员创建 | 所有认证用户 |

### 1.5 模型访问级别 (AccessLevel)

| 级别 | 说明 | 可用模型 |
|------|------|---------|
| `basic` | 基础订阅 | 免费模型 + basic 模型 |
| `pro` | 专业订阅 | basic 模型 + pro 模型 |

---

## 2. 认证中间件体系

### 2.1 中间件类型

| 中间件 | 方法 | 行为 | 使用场景 |
|--------|------|------|---------|
| `Auth()` | 强制认证 | 未登录返回 401 | 大部分用户 API |
| `Check()` | 可选认证 | 未登录继续，context 无用户 | 公开流、可选认证端点 |
| `TeamAuth()` | 强制团队认证 | 未登录或无团队返回 401 | 团队管理 API |
| `TeamAuthCheck()` | 可选团队认证 | 未登录返回 401，无团队返回 401 | 团队可选端点 |
| `TeamAdminAuth()` | 团队管理员授权 | 需 TeamAuth + admin 权限 | 团队管理操作 |

### 2.2 认证检查流程

```
请求到达
  ↓
读取 Cookie (sl-session 或 monkeycode_ai_team_session)
  ↓
Cookie 不存在 →
  Auth()    → HTTP 401 "Unauthorized"
  Check()   → 继续，context 无用户
  ↓
Cookie 存在 → session.Get() 从 Redis 读取
  ↓
  读取失败 →
  Auth()    → HTTP 401 "Unauthorized"
  Check()   → 继续，context 无用户
  ↓
  读取成功 → 注入 User/TeamUser 到 context
  ↓
TeamAuth 额外检查 → user.Team == nil → HTTP 401 "User has no team"
TeamAdminAuth 额外检查 → isAdmin() == false → HTTP 403 "Forbidden"
```

### 2.3 活跃追踪中间件 (TargetActive)

每个需要认证的请求还会经过 `TargetActive()` 中间件：
- 记录用户活跃时间到 Redis (`monkeycode_ai:user:active`)
- 记录用户活跃 IP
- 用于统计和空闲检测

---

## 3. API 访问控制矩阵

### 3.1 公开端点（无需认证）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/users/login` | 百智云 OAuth 跳转 |
| POST | `/api/v1/teams/users/login` | 团队管理员登录 |
| POST | `/api/v1/users/password-login` | 用户密码登录 |
| POST | `/api/v1/public/captcha/challenge` | 获取验证码 |
| POST | `/api/v1/public/captcha/redeem` | 兑换验证码 |
| GET | `/api/v1/users/models/providers` | 获取供应商模型列表 |
| PUT | `/api/v1/users/passwords/reset-request` | 请求重置密码 |
| GET | `/api/v1/users/passwords/accounts/{token}` | 获取重置账号信息 |
| PUT | `/api/v1/users/passwords/reset` | 重置密码 |

### 3.2 用户级端点（需要 `sl-session`）

**核心 LLM 相关：**

| Method | Path | 中间件 | 说明 |
|--------|------|--------|------|
| GET | `/api/v1/users/models` | Auth + TargetActive | 列出可用模型 |
| POST | `/api/v1/users/models` | Auth + TargetActive | 创建模型 |
| PUT | `/api/v1/users/models/{id}` | Auth + TargetActive | 更新模型 |
| DELETE | `/api/v1/users/models/{id}` | Auth + TargetActive | 删除模型 |
| GET | `/api/v1/users/models/{id}/health-check` | Auth + TargetActive | 模型健康检查 |
| POST | `/api/v1/users/models/health-check` | Auth + TargetActive | 按配置检查 |
| POST | `/api/v1/users/tasks` | Auth + TargetActive | 创建任务 |
| GET | `/api/v1/users/tasks` | Auth + TargetActive | 列出任务 |
| GET | `/api/v1/users/tasks/{id}` | Auth + TargetActive | 任务详情 |
| DELETE | `/api/v1/users/tasks/{id}` | Auth + TargetActive | 删除任务 |
| PUT | `/api/v1/users/tasks/{id}` | Auth + TargetActive | 更新任务 |
| PUT | `/api/v1/users/tasks/stop` | Auth + TargetActive | 停止任务 |
| GET | `/api/v1/users/tasks/stream` | Auth + TargetActive | 任务流 WebSocket |
| GET | `/api/v1/users/tasks/control` | Auth + TargetActive | 任务控制 WebSocket |
| GET | `/api/v1/users/tasks/rounds` | Auth + TargetActive | 历史轮次 |
| GET | `/api/v1/users/tasks/public-stream` | Check | 公开任务流 |

**用户信息：**

| Method | Path | 中间件 | 说明 |
|--------|------|--------|------|
| GET | `/api/v1/users/me` | Auth + TargetActive | 当前用户信息 |
| PUT | `/api/v1/users/profiles` | Auth + TargetActive | 更新资料 |
| GET | `/api/v1/users/settings` | Auth + TargetActive | 获取设置 |
| PUT | `/api/v1/users/settings` | Auth + TargetActive | 更新设置 |

**VM/Host：**

| Method | Path | 中间件 | 说明 |
|--------|------|--------|------|
| POST | `/api/v1/users/hosts/vms` | Auth + TargetActive | 创建 VM |
| GET | `/api/v1/users/hosts/vms` | Auth + TargetActive | 列出 VM |
| DELETE | `/api/v1/users/hosts/vms/{id}` | Auth + TargetActive | 删除 VM |

### 3.3 团队级端点（需要 `monkeycode_ai_team_session`）

| Method | Path | 中间件 | 说明 |
|--------|------|--------|------|
| GET | `/api/v1/teams/models` | TeamAuth | 列出团队模型 |
| POST | `/api/v1/teams/models` | TeamAuth | 创建团队模型 |
| GET | `/api/v1/teams/users` | TeamAuth | 列出团队成员 |
| POST | `/api/v1/teams/users` | TeamAuth + TeamAdminAuth | 添加成员 |
| PUT | `/api/v1/teams/users/{id}` | TeamAuth + TeamAdminAuth | 更新成员 |
| DELETE | `/api/v1/teams/users/{id}` | TeamAuth + TeamAdminAuth | 删除成员 |

### 3.4 管理员端点（需要 `sl-session` + admin 角色）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/auth/impersonate` | 模拟用户登录 |
| GET | `/api/v1/admin/users` | 列出所有用户 |
| GET | `/api/v1/admin/models` | 列出所有模型 |
| POST | `/api/v1/admin/models` | 创建公开模型 |

---

## 4. 资源访问控制规则

### 4.1 模型访问

```text
用户可见模型 = 用户私有模型 + 团队共享模型 + 公开模型
公开模型 API Key 被隐藏 (HideCredentials)
用户使用公开模型时，后端自动替换 public:model: 前缀为实际 Key
```

### 4.2 任务访问

```text
用户只能访问自己创建的任务
Info() 方法检查 task.UserID == user.ID
PublicStream() 方法允许其他用户查看公开任务
```

### 4.3 VM 访问

```text
用户只能操作自己的 VM
团队管理员可查看团队 VM
公共主机 (public_host) 对所有用户可用
```

---

## 5. 账号池权限边界

### 5.1 个人用户账号池

| 可访问 | 不可访问 |
|--------|---------|
| 用户模型 CRUD | 团队模型管理 |
| 任务全生命周期 | 团队成员管理 |
| VM 创建/删除 | 管理员操作 |
| 对话/消息 | Impersonate |
| 公开模型使用 | 公开模型配置 |

### 5.2 团队管理员账号池

| 可访问 | 不可访问 |
|--------|---------|
| 团队模型 CRUD | 管理员操作 |
| 团队成员管理 | Impersonate |
| 团队分组管理 | 其他团队 |
| 团队 Host/VM | |

### 5.3 推荐账号池角色

**对于 LLM 反向代理场景，推荐使用个人用户账号**：
- 需要的核心 API：模型列表 + 任务创建/流/控制
- 这些 API 全部在用户级端点下
- 团队级 API 不需要
- 管理员级 API 不需要（除非要创建公开模型）
