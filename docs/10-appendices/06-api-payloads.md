# 关键 API 请求/响应载荷示例

> **最后更新:** 2026-06-27
> **用途:** 记录全书各章节引用的核心 API 载荷

---

## 1. 登录认证

### 1.1 密码登录

```http
POST /api/v1/users/password-login HTTP/1.1
Host: api.monkeycode-ai.com
Content-Type: application/json

{
    "email": "user@example.com",
    "password": "MySecretPassword123!",    // 明文（HTTPS 保护）
    "captcha_token": "captcha_uuid"
}

→ HTTP/1.1 200 OK
Set-Cookie: monkeycode_ai_session=550e8400-e29b-41d4-a716-446655440000; 
            Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax

{
    "code": 0,
    "msg": "success",
    "data": {
        "user": {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "name": "username",
            "email": "user@example.com",
            "role": "individual"
        }
    }
}
```

### 1.2 OAuth 登录（百智云）

```http
### Step 1: 触发 OAuth 重定向
GET /api/v1/users/login HTTP/1.1
Host: api.monkeycode-ai.com

→ HTTP/1.1 302 Found
Location: https://oauth.baizhi.cloud/oauth/authorize?
  client_id=monkeycode-ai&
  redirect_uri=https://api.monkeycode-ai.com/api/v1/users/oauth/callback&
  response_type=code&
  scope=user+phone&
  state=random_state

### Step 2: OAuth 回调（code 兑换 session）
GET /api/v1/users/oauth/callback?code=oauth_code_xxx&state=random_state HTTP/1.1
Host: api.monkeycode-ai.com

→ HTTP/1.1 302 Found
Set-Cookie: monkeycode_ai_session=session-uuid; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax
Location: https://monkeycode-ai.com/
```

### 1.3 Session 状态检查

```http
GET /api/v1/users/status HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=550e8400-e29b-41d4-a716-446655440000

→ HTTP/1.1 200 OK
{
    "code": 0,       // 0=有效, 40100=失效
    "msg": "success",
    "data": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "username",
        "role": "individual",
        "email": "user@example.com"
    }
}
```

---

## 2. 验证码

### 2.1 获取验证码 Challenge

```http
POST /api/v1/public/captcha/challenge HTTP/1.1
Host: api.monkeycode-ai.com
Content-Type: application/json

{
    "type": "login"
}

→ HTTP/1.1 200 OK
{
    "code": 0,
    "msg": "success",
    "data": {
        "challenge": {
            "c": 50,       // 网格列数
            "s": 32,       // 网格行数
            "d": 3         // 难度系数
        },
        "token": "challenge_token_xxx",
        "expires_at": 1715299200
    }
}
```

### 2.2 兑换验证码

```http
POST /api/v1/public/captcha/redeem HTTP/1.1
Host: api.monkeycode-ai.com
Content-Type: application/json

{
    "token": "challenge_token_xxx",
    "positions": [1, 5, 12]    // 用户选择的网格位置
}

→ HTTP/1.1 200 OK
{
    "code": 0,
    "msg": "success",
    "data": {
        "captcha_token": "captcha_uuid_for_login"
    }
}
```

---

## 3. 模型管理

### 3.1 模型列表（分页）

```http
GET /api/v1/users/models?limit=100&cursor=xxx HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx

→ HTTP/1.1 200 OK
{
    "code": 0,
    "msg": "success",
    "data": {
        "models": [
            {
                "id": "model-uuid-1",
                "name": "gpt-4o",
                "provider": "OpenAI",
                "interface_type": "openai_chat",
                "allowed_plans": ["basic", "pro", "ultra"],
                "pricing": {
                    "input": 2.50,
                    "output": 10.00,
                    "currency": "CNY",
                    "unit": "1M tokens"
                }
            }
        ],
        "page": {
            "next_cursor": "next_cursor_xxx",
            "has_more": false
        }
    }
}
```

---

## 4. 任务管理

### 4.1 创建任务

```http
POST /api/v1/users/tasks HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx
Content-Type: application/json

{
    "cli_name": "opencode",
    "model_id": "model-uuid-1",
    "interface_type": "openai_chat",
    "user_input": "写一个Python脚本读取CSV文件",
    "system_prompt": "你是一个专业的Python开发者",
    "max_tokens": 4096,
    "temperature": 0.7
}

→ HTTP/1.1 200 OK
{
    "code": 0,
    "msg": "success",
    "data": {
        "task_id": "task-uuid-xxx",
        "vm_id": "vm-uuid-xxx",
        "status": "pending",
        "created_at": 1715299200
    }
}
```

### 4.2 停止任务

```http
PUT /api/v1/users/tasks/stop HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx
Content-Type: application/json

{
    "task_id": "task-uuid-xxx"
}

→ HTTP/1.1 200 OK
{
    "code": 0,
    "msg": "success"
}
```

---

## 5. 订阅

### 5.1 获取订阅信息

```http
GET /api/v1/users/subscription HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx

→ 开源版固定响应:
{
    "code": 0,
    "msg": "success",
    "data": {
        "plan": "pro",
        "auto_renew": false
    }
}
```

---

## 6. 管理（Admin）

### 6.1 列出团队成员

```http
GET /api/v1/teams/users/members?limit=20&cursor=xxx HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_team_session=xxx

→ HTTP/1.1 200 OK
{
    "code": 0,
    "data": {
        "members": [
            {
                "user_id": "uuid",
                "name": "member1",
                "role": "member",
                "joined_at": 1715299200
            }
        ]
    }
}
```

### 6.2 查看 Docker 镜像

```http
GET /api/v1/teams/users/images HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx

→ HTTP/1.1 200 OK
{
    "code": 0,
    "data": {
        "images": [
            {
                "id": "image-uuid",
                "name": "monkeycode-agent",
                "tag": "latest"
            }
        ]
    }
}
```

---

## 7. Conversation API

### 7.1 创建对话

```http
POST /api/v1/users/conversations HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx
Content-Type: application/json

{
    "title": "代码审查任务",
    "task_id": "task-uuid-xxx",
    "model_id": "model-uuid-1"
}

→ HTTP/1.1 201 Created
{
    "code": 0,
    "data": {
        "id": "conversation-uuid",
        "title": "代码审查任务",
        "task_id": "task-uuid-xxx",
        "created_at": 1715299200
    }
}
```

### 7.2 发送消息

```http
POST /api/v1/users/conversations/{id}/messages HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx
Content-Type: application/json

{
    "content": "审查这个代码文件",
    "role": "user"
}

→ HTTP/1.1 200 OK
{
    "code": 0,
    "data": {
        "id": "msg-uuid",
        "role": "user",
        "content": "审查这个代码文件",
        "created_at": 1715299200
    }
}
```

---

## 8. 密码管理

### 8.1 修改密码

```http
PUT /api/v1/users/passwords HTTP/1.1
Host: api.monkeycode-ai.com
Cookie: monkeycode_ai_session=xxx
Content-Type: application/json

{
    "old_password": "current_password",
    "new_password": "new_secure_password"
}

→ HTTP/1.1 200 OK
{
    "code": 0,
    "msg": "success"
}
```

### 8.2 重置密码请求

```http
PUT /api/v1/users/passwords/reset-request HTTP/1.1
Host: api.monkeycode-ai.com
Content-Type: application/json

{"email": "user@example.com"}

→ HTTP/1.1 200 OK
{"code": 0, "msg": "重置邮件已发送"}
```