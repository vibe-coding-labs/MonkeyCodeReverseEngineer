---
description: MonkeyCode 100+ API 端点的完整目录 + HTTP 请求/响应示例 + 代理扩展端点
protocol_version: based on chaitin/MonkeyCode Go 源码 + proxy/src/server.ts 代理端点
confidence: high
last_verified: 2026-06-28
---

# 完整 API 端点目录（源码增强版）

> **覆盖范围:** Go 后端 100+ 端点 + 代理层 12 个管理端点
> **新增:** 每个端点组添加实际 HTTP 请求/响应示例 + curl 命令

## 统一响应格式

```json
{
  "code": 0,
  "msg": "success",
  "data": { ... }
}

// 错误响应：
{"code": 401, "message": "未授权 [trace_id:xxx]"}
{"code": 403, "message": "禁止访问 [trace_id:xxx]"}
```

## 1. 公开端点（无需认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/public/captcha/challenge` | 创建验证码挑战 |
| POST | `/api/v1/public/captcha/redeem` | 兑换验证码 |
| GET | `/api/v1/users/login` | OAuth 登录跳转（302） |

```http
# 创建验证码挑战
curl -s -X POST https://monkeycode-ai.com/api/v1/public/captcha/challenge \
  -H "Content-Type: application/json" -d '{}'
# → {"challenge":{"c":50,"s":32,"d":3},"expires":...,"token":"ab6768a297..."}
```

## 2. 认证端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/v1/users/password-login` | 公开 | 密码登录（用户）|
| POST | `/api/v1/teams/users/login` | 公开 | 密码登录（团队）|
| POST | `/api/v1/users/logout` | Auth | 登出 |
| POST | `/api/v1/teams/users/logout` | Auth | 团队登出 |
| GET | `/api/v1/users/status` | Auth | 登录状态检查 |
| GET | `/api/v1/teams/users/status` | Auth | 团队状态检查 |
| GET | `/api/v1/users/baizhi/callback?code=xxx&state=yyy` | 公开 | OAuth 回调 |
| GET | `/api/v1/auth/impersonate?user_id=xxx` | Admin | 模拟登录 |

```http
# 密码登录
curl -s -X POST https://monkeycode-ai.com/api/v1/users/password-login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"mypassword"}'
# ← Set-Cookie: monkeycode_ai_session=uuid; Max-Age=2592000; HttpOnly; Secure
# → {"code":0,"msg":"success","data":{"user":{"id":"uuid","name":"用户"}}}

# 状态检查
curl -s https://monkeycode-ai.com/api/v1/users/status \
  -H "Cookie: monkeycode_ai_session=uuid"
# → {"code":0,"data":{"user":{"id":"uuid","subscription_level":"pro"}}}
```

## 3. 模型管理端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v1/users/models` | Auth | 列出可见模型 |
| POST | `/api/v1/users/models` | Auth | 创建模型 |
| GET | `/api/v1/users/models/:id` | Auth | 获取模型详情 |
| PUT | `/api/v1/users/models/:id` | Auth | 更新模型 |
| DELETE | `/api/v1/users/models/:id` | Auth | 删除模型 |

```http
# 模型列表
curl -s https://monkeycode-ai.com/api/v1/users/models \
  -H "Cookie: monkeycode_ai_session=uuid"
# → {"code":0,"data":{"models":[
#   {"id":"uuid","provider":"siliconflow","model":"Qwen/Qwen3.5-Plus","interface_type":"openai_chat","access_level":"basic"},
#   {"id":"uuid","provider":"openai","model":"gpt-4o","interface_type":"openai_chat","access_level":"ultra"}
# ]}}

# 创建私有模型
curl -s -X POST https://monkeycode-ai.com/api/v1/users/models \
  -H "Cookie: monkeycode_ai_session=uuid" -H "Content-Type: application/json" \
  -d '{"provider":"openai","model_name":"gpt-4o-mini","interface_type":"openai_chat","base_url":"https://api.openai.com/v1","api_key":"sk-..."}'
```

## 4. 任务端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/v1/users/tasks` | Auth | 创建任务 |
| GET | `/api/v1/users/tasks` | Auth | 列出任务 |
| GET | `/api/v1/users/tasks/:id` | Auth | 获取任务详情 |
| PUT | `/api/v1/users/tasks/stop` | Auth | 停止任务 |
| DELETE | `/api/v1/users/tasks/:id` | Auth | 删除任务 |
| GET | `/api/v1/users/tasks/stream?id=x&mode=new` | Auth+WS | WS 任务流 |
| GET | `/api/v1/users/tasks/stream?id=x&mode=attach` | Auth+WS | WS 对话复用 |
| POST | `/api/v1/users/tasks/speech-to-text` | Auth | 语音识别 |

```http
# 创建任务
curl -s -X POST https://monkeycode-ai.com/api/v1/users/tasks \
  -H "Cookie: monkeycode_ai_session=uuid" -H "Content-Type: application/json" \
  -d '{
    "content": "Write a Python hello world",
    "host_id": "public_host",
    "image_id": "uuid_image",
    "model_id": "uuid_model",
    "cli_name": "opencode",
    "resource": {"core": 1, "memory": 1073741824, "life": 3600}
  }'
# → {"code":0,"data":{"id":"task-uuid"}}

# WebSocket 连接
# wss://monkeycode-ai.com/api/v1/users/tasks/stream?id=task-uuid&mode=new
# → {"type":"auto-approve"}
# → {"type":"user-input","data":"Write a Python hello world"}
# ← {"type":"task-started"}
# ← {"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_message_chunk\",\"text\":\"Hello\"}"}
# ← {"type":"task-ended"}
```

## 5. 对话端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v1/users/conversations` | Auth | 对话列表 |
| POST | `/api/v1/users/conversations` | Auth | 创建对话 |
| GET | `/api/v1/users/conversations/:id` | Auth | 对话详情 |
| PUT | `/api/v1/users/conversations/:id` | Auth | 更新对话 |
| DELETE | `/api/v1/users/conversations/:id` | Auth | 删除对话 |
| GET | `/api/v1/users/conversations/:id/messages` | Auth | 对话消息 |

## 6. 订阅端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v1/users/subscriptions` | Auth | 订阅列表 |
| POST | `/api/v1/users/subscriptions` | Auth | 创建订阅（Stripe 跳转）|
| GET | `/api/v1/users/subscriptions/current` | Auth | 当前订阅 |
| PUT | `/api/v1/users/subscriptions/:id` | Auth | 更新订阅 |

```http
# 当前订阅（开源版固定返回 pro）
curl -s https://monkeycode-ai.com/api/v1/users/subscriptions/current \
  -H "Cookie: monkeycode_ai_session=uuid"
# → {"plan":"pro","source":"free","expires_at":null,"auto_renew":true}
```

## 7. 管理端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v1/admin/users` | Admin | 用户列表 |
| GET | `/api/v1/admin/users/:id` | Admin | 用户详情 |
| GET | `/api/v1/admin/teams` | Admin | 团队列表 |
| GET | `/api/v1/admin/teams/:id` | Admin | 团队详情 |
| GET | `/api/v1/admin/subscriptions` | Admin | 订阅管理 |
| PUT | `/api/v1/admin/users/:id/ban` | Admin | 封禁用户 |
| PUT | `/api/v1/admin/users/:id/unban` | Admin | 解禁用户 |
| GET | `/api/v1/admin/stats` | Admin | 平台统计 |
| GET | `/api/v1/admin/logs` | Admin | 操作日志 |
| GET | `/api/v1/admin/tasks` | Admin | 任务管理 |
| GET | `/api/v1/admin/models` | Admin | 模型管理 |
| PUT | `/api/v1/admin/models/:id` | Admin | 更新模型权限 |

## 8. 代理层扩展端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | OpenAI 兼容模型列表 |
| POST | `/v1/chat/completions` | OpenAI Chat Completions API |
| POST | `/v1/responses` | OpenAI Responses API |
| GET | `/health` | 代理健康检查 |
| POST | `/admin/session` | 手动设置 Session Cookie |
| POST | `/admin/login/send-code` | 发送 OAuth 短信验证码 |
| POST | `/admin/login/verify` | 验证短信码完成登录 |
| POST | `/admin/login/callback` | 通过回调 URL 登录 |
| GET | `/admin/discover` | 自动发现 image_id + 模型 |
| POST | `/admin/refresh-models` | 刷新模型缓存 |
| GET | `/admin/pool/status` | 号池状态 |
| POST | `/admin/pool/refresh` | 重新登录号池所有账号 |

```http
# Chat Completions（通过代理）
curl -s -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello"}],"stream":true}'

# 号池状态
curl -s http://localhost:9090/admin/pool/status
# → {"mode":"pool","total":5,"active":4,"expired":1,"invalid":0,"locked":2}
```

## 9. 密码管理端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| PUT | `/api/v1/users/passwords` | Auth | 修改密码 |
| PUT | `/api/v1/users/passwords/reset-request` | 公开 | 请求重置 |
| GET | `/api/v1/users/passwords/accounts/:token` | 公开 | 获取账号信息 |
| PUT | `/api/v1/users/passwords/reset` | 公开 | 执行重置 |

## 10. 团队端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v1/teams` | TeamAuth | 团队信息 |
| POST | `/api/v1/teams` | Auth | 创建团队 |
| GET | `/api/v1/teams/members` | TeamAuth | 团队成员 |
| POST | `/api/v1/teams/members` | TeamAdminAuth | 添加成员 |
| DELETE | `/api/v1/teams/members/:id` | TeamAdminAuth | 移除成员 |
| GET | `/api/v1/teams/policies` | TeamAuth | 团队策略 |
| PUT | `/api/v1/teams/policies` | TeamAdminAuth | 更新策略 |

## 附录：端到端调用示例

```bash
# 1. 登录获取 Session
SESSION=$(curl -s -X POST https://monkeycode-ai.com/api/v1/users/password-login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass"}' \
  -c - | grep monkeycode_ai_session | awk '{print $NF}')

# 2. 获取模型列表
curl -s https://monkeycode-ai.com/api/v1/users/models \
  -H "Cookie: monkeycode_ai_session=$SESSION"

# 3. 创建任务
TASK_ID=$(curl -s -X POST https://monkeycode-ai.com/api/v1/users/tasks \
  -H "Cookie: monkeycode_ai_session=$SESSION" -H "Content-Type: application/json" \
  -d '{"content":"Hello","host_id":"public_host","image_id":"...","model_id":"...","cli_name":"opencode","resource":{"core":1,"memory":1073741824,"life":3600}}' \
  | jq -r '.data.id')
```

---

## 相关章节

- [认证协议详解](../02-auth/README.md) — 认证端点详情
- [模型管理 API](../03-llm/01-model-management-api.md) — 模型 CRUD
- [代理管理端点](../07-proxy/05-admin-management-api.md) — 代理扩展端点
- [授权矩阵](02-authorization-matrix.md) — 端点权限要求