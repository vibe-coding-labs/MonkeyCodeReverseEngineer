> ⚠️ **此文件为原始分析档案** — 内容已被 docs/ 下结构化章节覆盖。详见 [docs/protocol/README.md](./README.md)。

# MonkeyCode 账号池认证协议完整报告

> 基于 chaitin/MonkeyCode 开源后端源码逆向分析
> 分析日期: 2026-05-11 | 更新日期: 2026-05-12（未决问题已全部确认）

---

## 1. 概述与架构

### 1.1 目标

为 MonkeyCode 账号池提供完整的认证和授权协议参考，覆盖：
- 如何获取、验证、保活、轮换 Session
- 不同角色账号的权限边界
- 并发使用策略
- 错误恢复机制

### 1.2 认证架构

```
┌─────────────────────────────────────────────────────────────┐
│                    MonkeyCode 认证体系                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  认证方式 (Authentication)          授权层级 (Authorization)  │
│  ┌──────────────────────┐          ┌──────────────────────┐ │
│  │ 1. 密码登录           │          │ UserRole:            │ │
│  │    POST /password-login│         │  individual          │ │
│  │    → monkeycode_ai_session       │          │  enterprise          │ │
│  │                       │          │  subaccount          │ │
│  │ 2. 百智云 OAuth       │          │  admin               │ │
│  │    GET /login → 回调   │          │  gittask             │ │
│  │    → monkeycode_ai_session       │          │                      │ │
│  │                       │          │ OwnerType:           │ │
│  │ 3. 团队管理员登录      │          │  private             │ │
│  │    POST /teams/login   │         │  team                │ │
│  │    → team_session     │          │  public              │ │
│  │                       │          │                      │ │
│  │ 4. Git OAuth 绑定     │          │ AccessLevel:         │ │
│  │    GET /git/auth      │          │  basic               │ │
│  │    → monkeycode_ai_session       │          │  pro                 │ │
│  │                       │          └──────────────────────┘ │
│  │ 5. Admin Impersonate  │                                   │
│  │    GET /impersonate   │                                   │
│  │    → monkeycode_ai_session       │                                   │
│  └──────────────────────┘                                   │
│                                                             │
│  Session 存储: Redis Hash                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Key:   {cookie_name}:{user_uuid}                    │    │
│  │ Field: {cookie_uuid}                                │    │
│  │ Value: JSON session data                            │    │
│  │ Lookup: lookup:{cookie_name}:{cookie_uuid} → user_uuid│  │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 认证协议

### 2.1 用户密码登录

**端点**: `POST /api/v1/users/password-login`

**请求**:
```json
{
  "email": "user@example.com",
  "password": "e10adc3949ba59abbe56e057f20f883e",
  "captcha_token": "captcha-redeem-token"
}
```

**响应**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "User Name",
    "email": "user@example.com",
    "role": "individual",
    "status": "active",
    "team": null,
    "default_configs": {}
  }
}
```

**Set-Cookie**: `monkeycode_ai_session={uuid}; Path=/; HttpOnly; SameSite=Lax`

**密码格式**: 前端传明文，后端用 bcrypt 验证。注释中标注 MD5 是**错误注释**，实际不经过 MD5（详见 §6.1）。

**验证码前置**:
1. `POST /api/v1/public/captcha/challenge` → 获取挑战 ID + 图片
2. 用户点击 3 个目标 → `POST /api/v1/public/captcha/redeem` → 获取 `captcha_token`
3. 使用 `captcha_token` 调用登录 API

### 2.2 团队管理员登录

**端点**: `POST /api/v1/teams/users/login`

**请求**:
```json
{
  "email": "admin@company.com",
  "password": "plain_password",
  "captcha_token": "captcha-redeem-token"
}
```

**Set-Cookie**: `monkeycode_ai_team_session={uuid}; Path=/; HttpOnly; SameSite=Lax`

**注意**: 线上环境可能通过配置覆盖 cookie 名称，需实测确认。

### 2.3 百智云 OAuth

**流程**:
1. `GET /api/v1/users/login` → 302 重定向到百智云
2. 用户在百智云完成认证
3. 百智云回调 MonkeyCode → 创建/关联用户 → 设置 `monkeycode_ai_session`

**闭源部分**: 回调处理逻辑在闭源组件中，无法从开源代码获取。

### 2.4 Git OAuth 绑定

**端点**: `GET /api/v1/users/git/{provider}/auth`

**支持的 Provider**: `github`, `gitlab`

**流程**: 重定向到 Git 平台 → 用户授权 → 回调 → 绑定到用户账号

### 2.5 Admin Impersonate

**端点**: `GET /api/v1/auth/impersonate?user_id={uuid}`

**前置条件**: 当前用户必须是 `admin` 角色

**流程**: 生成临时 token → 重定向到前端 → 前端用 token 换取 `monkeycode_ai_session`

**闭源**: token 生成逻辑完全闭源。

---

## 3. 授权协议

### 3.1 角色体系

| 角色 | 常量 | Session Cookie | 权限范围 |
|------|------|---------------|---------|
| 个人用户 | `individual` | `monkeycode_ai_session` | 私有模型 + 任务 + VM |
| 企业用户 | `enterprise` | `monkeycode_ai_session` | 私有 + 团队模型/任务 |
| 企业子账户 | `subaccount` | `monkeycode_ai_session` | 团队分配的资源 |
| 系统管理员 | `admin` | `monkeycode_ai_session` | 所有用户资源 + 公开模型管理 |
| Git 任务 | `gittask` | 内部 | 自动化 git 任务 |

### 3.2 中间件 → API 映射

| 中间件 | 认证要求 | 适用 API |
|--------|---------|---------|
| `Auth()` | 必须有 `monkeycode_ai_session` | 大部分用户 API |
| `Check()` | 可选认证 | 公开流、公开端点 |
| `TeamAuth()` | 必须有 `monkeycode_ai_team_session` | 团队管理 API |
| `TeamAdminAuth()` | TeamAuth + 管理员权限 | 团队成员管理 |

### 3.3 账号池所需 API 权限

对于 LLM 反向代理场景，**个人用户**即可满足需求：

| API | 中间件 | 个人用户可用 |
|-----|--------|------------|
| `GET /api/v1/users/models` | Auth | ✅ |
| `POST /api/v1/users/tasks` | Auth | ✅ |
| `GET /api/v1/users/tasks/stream` | Auth | ✅ |
| `GET /api/v1/users/tasks/control` | Auth | ✅ |
| `POST /api/v1/users/hosts/vms` | Auth | ✅ |
| `GET /api/v1/users/status` | Check | ✅ |

---

## 4. Session 管理协议

### 4.1 存储结构

```text
Redis:
  Hash Key: monkeycode_ai_session:{user_uuid}
    Field: {cookie_uuid_1} → {"user_id":"...","role":"individual",...}
    Field: {cookie_uuid_2} → {"user_id":"...","role":"individual",...}

  Lookup Key: lookup:monkeycode_ai_session:{cookie_uuid} → {user_uuid}
```

### 4.2 关键特性

| 特性 | 行为 | 对账号池的影响 |
|------|------|---------------|
| 多 Session 共存 | 同一用户可有多个 session | ✅ 可并发使用 |
| 登录不踢人 | 新登录不删除旧 session | ✅ 安全轮换 |
| 单独删除 | `Del()` 只删一个 session | ✅ 精细管理 |
| 全部踢出 | `Trunc()` 删除所有 session | ⚠️ 管理员操作 |
| TTL 过期 | 由 `config.Session.ExpireDay` 控制 | ⚠️ 需要保活 |

### 4.3 Session 生命周期

```text
获取 → CREATED
  ↓
首次验证成功 → ACTIVE
  ↓
定期保活 (5min) → ACTIVE
  ↓
status 返回 40100 → EXPIRED
  ↓
自动重新登录 → ACTIVE (新 session)
  或
账号被封禁 → INVALID (永久移除)
```

### 4.4 有效性检测协议

> **重要**: 调用 status 端点**不会刷新** Redis TTL。Session 有效期从 Save 时固定（默认 30 天），无法通过任何 API 调用续期。

```bash
# 定期检测 session 有效性（建议每 1 小时）
GET /api/v1/users/status
Cookie: monkeycode_ai_session={uuid}

# 成功响应
{"code": 0, "data": {"status": "active"}}

# 失败响应
{"code": 40100, "msg": "Unauthorized"}
```

**Session 轮换策略**: 在 session 过期前 1-2 天主动重新登录获取新 session。

---

## 5. 验证码系统

### 5.1 完整流程

```text
1. POST /api/v1/public/captcha/challenge
   请求: {"captcha_id": "auto-generated-uuid"}
   响应: {"id": "challenge-uuid", "image": "base64-png", "targets": 3}

2. 用户识别图片中 3 个目标位置
   点击坐标: [(x1,y1), (x2,y2), (x3,y3)]

3. POST /api/v1/public/captcha/redeem
   请求: {"id": "challenge-uuid", "positions": [[x1,y1],[x2,y2],[x3,y3]]}
   响应: {"token": "captcha-token-string"}

4. 使用 captcha_token 调用登录 API
```

### 5.2 参数

| 参数 | 值 |
|------|-----|
| 网格大小 | 50x32 |
| 目标数量 | 3 |
| 挑战过期 | 120s |
| Token 过期 | 300s |
| Proof-of-Work | go-cap |

### 5.3 自动化评估

| 方案 | 推荐度 | 说明 |
|------|--------|------|
| Cookie 复用 | ★★★★★ | 完全绕过验证码 |
| 多模态 LLM 识别 | ★★★☆☆ | 可行但有成本 |
| 第三方打码服务 | ★★★☆☆ | 可行但有成本 |
| 人工辅助 | ★★★★☆ | 可行但无法规模化 |

---

## 6. 未决问题验证结果（全部已确认）

> 详细证据链见 `docs/protocol/auth-unresolved-verification.md`

### 6.1 密码传输格式（P0）— 已确认：明文

**结论**: 前端传明文，后端用 bcrypt 验证。注释中"MD5加密后的值"是错误注释，实际不经过 MD5。

**证据**: 前端 `login.tsx:85-88` 直接传 `userPassword.trim()`；后端 `pkg/crypto/bcrypt.go:22-24` 使用 `bcrypt.CompareHashAndPassword()`；前端无任何 MD5 依赖。

**账号池存储**: 存储明文密码，登录时直接传明文。

### 6.2 团队管理员 Cookie 名称（P2）— 已确认：硬编码

**结论**: Cookie 名称硬编码在 `consts/auth.go`，线上环境不会改变。

- 用户登录 Cookie: `monkeycode_ai_session`
- 团队登录 Cookie: `monkeycode_ai_team_session`

**注意**: 之前文档中写的 `sl-session` 是错误的，正确名称是 `monkeycode_ai_session`。

### 6.3 Session TTL（P1）— 已确认：默认 30 天

**结论**: Session 默认有效期 30 天，可通过环境变量 `MCAI_SESSION_EXPIRE_DAY` 配置。

**源码** (`config/config.go:216`): `v.SetDefault("session.expire_day", 30)`

### 6.4 并发检测（P1）— 已确认：开源代码无检测

**结论**: 开源源码中无任何 API 级别的并发检测或限流逻辑。TargetActive 中间件仅记录活跃时间和 IP，无限流。

**建议**: 保守起见，每账号限制 2 session，每 session QPS < 5。

### 6.5 Status 端点是否刷新 TTL（P2）— 已确认：不刷新

**结论**: 调用 `/api/v1/users/status` **不刷新** Redis TTL。Session 有效期从 Save 时固定，30 天后必定过期，无法通过任何 API 调用续期。

**证据**: Status handler 仅返回用户信息；`session.Get()` 使用 `rdb.Get()` + `rdb.HGet()`，这两个 Redis 命令不刷新 TTL。

---

## 7. 账号池通信协议

### 7.1 请求头注入

```http
Cookie: monkeycode_ai_session={session_uuid}
Content-Type: application/json
```

### 7.2 错误码处理

| 错误码 | 含义 | 自动恢复 |
|--------|------|---------|
| `0` | 成功 | 无 |
| `40100` | Session 失效 | 切换 session → 重试 |
| `40300` | 权限不足 | 记录 → 降级 |
| `40002` | 密码错误 | 标记账号 INVALID |
| `40003` | 账号被封 | 标记账号 INVALID → 移除 |
| `50000` | 服务器错误 | 指数退避重试 |

### 7.3 并发策略

- 每账号 1 主 session + 1 备用 session
- HTTP 请求不独占 session
- WebSocket 连接独占 session
- LRU + Round-Robin 混合负载均衡

### 7.4 保活策略

- 定期（每 1 小时）检查 session 有效性
- 失效时自动切换到备用 session
- 备用也失效时触发重新登录
- 登录失败标记账号异常
- Session 无法续期，过期前 1-2 天主动重新登录

---

## 8. 完整请求/响应示例

### 8.1 账号池初始化流程

```bash
# 1. 导入 Cookie（从浏览器获取）
SESSION_ID="550e8400-e29b-41d4-a716-446655440000"

# 2. 验证 Session 有效性
curl -s https://monkeycode-ai.com/api/v1/users/status \
  -H "Cookie: monkeycode_ai_session=$SESSION_ID" | jq .
# 期望: {"code": 0, "data": {"status": "active"}}

# 3. 获取用户信息
curl -s https://monkeycode-ai.com/api/v1/users/me \
  -H "Cookie: monkeycode_ai_session=$SESSION_ID" | jq .
# 期望: {"code": 0, "data": {"id": "...", "role": "individual", ...}}

# 4. 获取可用模型
curl -s https://monkeycode-ai.com/api/v1/users/models \
  -H "Cookie: monkeycode_ai_session=$SESSION_ID" | jq '.data.models[] | {id, model, provider, owner: .owner.type}'
# 期望: 模型列表

# 5. 创建任务（LLM 调用）
curl -s -X POST https://monkeycode-ai.com/api/v1/users/tasks \
  -H "Cookie: monkeycode_ai_session=$SESSION_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Hello, write a hello world in Python",
    "host_id": "public_host",
    "image_id": "image-uuid",
    "model_id": "model-uuid",
    "cli_name": "claude",
    "resource": {"core": 1, "memory": 1073741824, "life": 3600},
    "repo": {"repo_url": "", "branch": "master", "repo_filename": "", "zip_url": ""}
  }' | jq '.data.id'
# 期望: task-uuid
```

### 8.2 Session 失效自动恢复流程

```bash
# 1. 请求失败，检测到 40100
RESPONSE=$(curl -s https://monkeycode-ai.com/api/v1/users/models \
  -H "Cookie: monkeycode_ai_session=$EXPIRED_SESSION")
echo $RESPONSE | jq '.code'
# 输出: 40100

# 2. 切换到备用 session
SESSION_ID=$BACKUP_SESSION

# 3. 重试请求
curl -s https://monkeycode-ai.com/api/v1/users/models \
  -H "Cookie: monkeycode_ai_session=$SESSION_ID" | jq '.code'
# 期望: 0

# 4. 如果备用也失效，触发重新登录
# (需要验证码 token，可能需要人工干预)
```

---

## 9. 附录：相关文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 认证协议完整版 | `docs/protocol/auth-protocol-complete.md` | 5 种登录方式完整规格 |
| LLM 协议完整版 | `docs/protocol/llm-protocol-complete.md` | 任务/模型/流式协议 |
| 授权矩阵 | `docs/protocol/authorization-matrix.md` | 角色/权限/API 映射 |
| 自动化分析 | `docs/protocol/auth-automation-analysis.md` | 密码格式/验证码/并发 |
| 账号池协议 | `docs/protocol/account-pool-protocol.md` | Session 池化/轮换/保活 |
| 缺口分析 | `docs/protocol/auth-pool-gap-analysis.md` | 文档覆盖度评估 |
| 未决问题验证 | `docs/protocol/auth-unresolved-verification.md` | 5 个未决问题的源码级验证结果 |
