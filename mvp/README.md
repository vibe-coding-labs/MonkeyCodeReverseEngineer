# MonkeyCode Python 授权与代理 MVP

> **目标**: 通过 Python 脚本模拟 MonkeyCode 平台的认证授权流程，验证反向代理给 Codex 等工具使用的可行性。

## 架构

```
Codex / curl / OpenAI SDK
  │
  │ OpenAI API (HTTP/SSE)
  ▼
proxy_real.py (端口 9091)
  │
  │ MonkeyCode API + WebSocket
  ▼
MonkeyCode Backend (monkeycode-ai.com)
  │
  │ TaskFlow → VM → LLM Client
  ▼
LLM Provider (OpenAI / Anthropic / DeepSeek ...)
```

## 文件说明

| 文件 | 说明 | 状态 |
|------|------|------|
| `client.py` | 统一客户端（认证 + 模型 + 任务 + WS 流） | ✅ |
| `proxy_real.py` | OpenAI 兼容代理（真实任务执行） | ✅ |
| `verify_full_flow.py` | 端到端验证脚本 | ✅ |
| `auth.py` | 认证协议（密码登录、Session 管理） | ✅ 增强 |
| `models.py` | 模型管理（列表、公开模型识别） | ✅ |
| `chat.py` | WebSocket 聊天协议 | ✅ |
| `oauth_login.py` | Playwright OAuth 自动登录 | ✅ |
| `oauth_http.py` | HTTP OAuth 授权 | ✅ |
| `test_auth.py` | 授权协议测试（14 个测试用例） | ✅ |
| `test_protocol.py` | 端到端协议验证测试 | ✅ |
| `proxy.py` | OpenAI 兼容代理（mock 版，旧版） | ⚠️ 遗留 |

## 快速开始

### 前置条件

```bash
pip install -r requirements.txt
```

### 方式 1: 使用 Session Cookie（推荐，绕过验证码）

1. 在浏览器中打开 [MonkeyCode](https://monkeycode-ai.com) 并登录
2. 打开 DevTools → Application → Cookies → 找到 `monkeycode_ai_session`
3. 复制 Cookie 值

```bash
export MONKEYCODE_SESSION_COOKIE="粘贴你的 session cookie 值"
export MONKEYCODE_IMAGE_ID="从浏览器 DevTools 中获取的 image_id"
```

### 方式 2: 密码登录

```bash
export MONKEYCODE_USERNAME="your-email@example.com"
export MONKEYCODE_PASSWORD="your-password"
export MONKEYCODE_IMAGE_ID="从浏览器 DevTools 中获取的 image_id"
```

> **注意**: 密码登录需要 `captcha_token`（go-cap 验证码），首次登录建议使用方式 1。

### 获取 IMAGE_ID

1. 浏览器中登录 MonkeyCode 并打开 DevTools → Network
2. 创建一个任务（输入提示词后点击运行）
3. 在 Network 中找到 `POST /api/v1/users/tasks` 请求
4. 在请求体中查找 `image_id` 字段
5. 设置为环境变量 `MONKEYCODE_IMAGE_ID`

### 运行

```bash
# 完整链路验证（认证 → 模型 → 任务 → WS 流）
python verify_full_flow.py

# 启动 OpenAI 兼容代理
python proxy_real.py

# 仅测试认证和模型（不需要 IMAGE_ID）
python verify_full_flow.py --skip-task
```

## API 端点

启动代理后：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/models` | GET | 模型列表 |
| `/v1/chat/completions` | POST | Chat Completions（支持 stream） |
| `/v1/responses` | POST | Responses API（Codex 原生） |
| `/health` | GET | 健康检查 |

### curl 测试

```bash
# 模型列表
curl http://localhost:9091/v1/models | jq

# Chat Completions（非流式）
curl -X POST http://localhost:9091/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "你好"}]
  }'

# Chat Completions（流式）
curl -X POST http://localhost:9091/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'

# Responses API
curl -X POST http://localhost:9091/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "input": "你好"
  }'
```

## 认证方式对比

| 方式 | 难度 | 持久性 | 是否需要验证码 | 适用场景 |
|------|------|--------|---------------|---------|
| Session Cookie | ⭐ 简单 | 最长 30 天 | ❌ 不需要 | ✅ **推荐，自动化首选** |
| 密码登录 | ⭐⭐ 中等 | 30 天（每次登录刷新） | ✅ 需要 captcha | 首次设置、批量账号 |
| 团队密码登录 | ⭐⭐ 中等 | 30 天 | ✅ 需要 captcha | 团队账号管理 |
| OAuth 百智云 | ⭐⭐⭐ 复杂 | 30 天 | ✅ 需要 SCaptcha | 手机号登录场景 |

## Session TTL 说明

- MonkeyCode 的 Session 有 **30 天硬限制**（Redis TTL）
- 没有 refresh API，过期后需要重新登录
- 同一个用户可以创建多个并行 Session
- 建议 HTTP 和 WebSocket 使用不同的 Session（避免争用）

## 建议

1. **推荐使用 Session Cookie 方式** — 从浏览器提取，绕过验证码，最简单稳定
2. **不建议频繁密码登录** — 可能触发速率限制或验证码要求
3. **先跑 verify_full_flow.py --skip-task** 确认认证和模型列表正常
4. **IMPORTANT**: MonkeyCode 平台可能随时更新 API，如果遇到问题请查看 DevTools 调试
