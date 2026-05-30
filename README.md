# MonkeyCode Reverse Proxy

MonkeyCode AI 平台的反向代理，将其内置 LLM 能力暴露为 OpenAI 兼容 API（Chat Completions / Responses API），供 Codex 等客户端使用。

## 项目结构

```
.
├── proxy/                     # TypeScript 反向代理
│   └── src/
│       ├── server.ts          # 主入口 + Express 路由
│       ├── auth.ts            # 认证模块（Cookie-based Session）
│       ├── account-pool.ts    # 多账号号池轮转
│       ├── admin-login.ts     # 百智云 OAuth 登录自动化
│       ├── models.ts          # 模型列表管理
│       ├── task-runner.ts     # 任务创建 + WebSocket 流
│       ├── api-routes.ts      # OpenAI 兼容 API 路由
│       ├── conversation-manager.ts  # 多轮对话管理器
│       └── types.ts           # 类型定义
├── mvp/                       # Python 原型验证
│   └── *.py                   # 认证/协议/代理验证
└── docs/protocol/             # 逆向分析文档
    ├── llm-protocol-complete.md
    ├── auth-protocol-complete.md
    ├── websocket-protocol.md
    └── ...
```

## 逆向成果

| 模块 | 完成度 | 说明 |
|------|--------|------|
| 认证协议 | 98% | 5 种登录方式，Cookie-based Session |
| LLM 通信协议 | 95% | 3 种接口类型（openai_chat / openai_responses / anthropic） |
| WebSocket 协议 | 90% | 3 个 WS 通道，ACP 事件流 |
| 代理实现 | 95% | `/v1/chat/completions` + `/v1/responses` 均已实现 |
| 号池管理 | 95% | 多账号轮转 + 健康检查 + 错误处理 |

## 快速开始

### 前提条件

需要一个 **已注册 MonkeyCode 的账号**（支持手机号 / 邮箱注册）。

### 启动代理

```bash
cd proxy
npm install
npm run dev
```

### 获取 Session（二选一）

**方式 A：浏览器提取 Cookie（推荐，1 分钟）**

1. 浏览器打开 [monkeycode-ai.com](https://monkeycode-ai.com) 并登录
2. 按 F12 → Application → Cookies → 找到 `monkeycode_ai_session`
3. 复制值，设置到代理：

```bash
curl -X POST http://localhost:9090/admin/session \
  -H "Content-Type: text/plain" \
  -d "你的session_cookie值"
```

**方式 B：手动 OAuth 回调**

如果你在浏览器中完成了 OAuth 登录，把浏览器跳转回的完整 URL 传给代理：

```bash
curl -X POST http://localhost:9090/admin/login/callback \
  -H "Content-Type: application/json" \
  -d '{"callbackUrl": "https://monkeycode-ai.com/api/v1/users/baizhi/callback?code=xxx&state=xxx"}'
```

### 验证可用

```bash
# 列出模型
curl http://localhost:9090/v1/models

# 聊天
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "monkeycode/OpenAI/gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}'
```

### 与 Codex 集成

```bash
OPENAI_API_KEY=any \
OPENAI_BASE_URL=http://localhost:9090/v1 \
  codex
```

## 已知限制

### SCaptcha 验证码服务不可用

MonkeyCode 依赖 [chaitin/s-captcha](https://github.com/chaitin/s-captcha) 的 SaaS 版本作为验证码服务。当前该服务返回：

```json
{
  "success": true,
  "data": {
    "action": "error",
    "error": "no money"
  }
}
```

即服务商账户余额不足，导致 **以下自动化路径不可用**：

- ❌ `POST /api/v1/users/password-login`（密码登录需要验证码 token）
- ❌ 百智云 OAuth 自动化 `POST /admin/login/send-code`（发短信也需要验证码）

**当前可行的替代方案：**

- ✅ 手动从浏览器提取 Session Cookie（方式 A，最快）
- ✅ 手动完成 OAuth 授权后将回调 URL 传给代理（方式 B）
- ⚠️ 密码登录 — 需要自行解决 CAP.js 验证码（如手动获取 token 后填入 `captcha_token` 参数）

### 其他

- Session Cookie 有效期 30 天，过期需重新获取
- 公开模型（`public:model:` 前缀）的 API Key 在创建任务时由后端自动注入
- WebSocket 独占锁无超时机制（僵尸锁问题，见 `account-pool.ts:100-111`）

## 安全说明

- 所有 API 端点无认证保护（仅供本地开发使用，不应用于生产环境）
- `admin-login.ts:60` 处因 SCaptcha 证书问题临时关闭了 TLS 验证
- 密码以明文形式在内存中传递（后端用 bcrypt 验证，传输层由 HTTPS 保护）

## 相关文档

- [认证协议完整文档](docs/protocol/auth-protocol-complete.md)
- [LLM 通信协议完整文档](docs/protocol/llm-protocol-complete.md)
- [WebSocket 流式协议](docs/protocol/websocket-protocol.md)
- [API 端点映射](docs/protocol/api-endpoints.md)
