# MonkeyCode Reverse Proxy

将 MonkeyCode 的 AI 能力代理为 OpenAI 兼容 API，支持 Codex 原生调用。

## 功能特性

- ✅ **OpenAI Chat Completions API** — `/v1/chat/completions`
- ✅ **OpenAI Responses API** — `/v1/responses` (Codex 原生)
- ✅ **多轮对话支持** — 通过 `conversation_id` 复用任务/VM
- ✅ **流式响应** — SSE 格式
- ✅ **号池管理** — 多账号轮转
- ✅ **OAuth 登录** — 百智云自动化
- ✅ **ACP 事件处理** — 完整的 Agent 通信协议支持

## 快速开始

### 1. 安装依赖

```bash
cd proxy
npm install
```

### 2. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑配置
vim .env
```

**必需配置**：
```bash
# Session Cookie（从浏览器获取）
MONKEYCODE_SESSION_COOKIE=your-session-cookie

# VM 镜像 ID（从浏览器获取）
MONKEYCODE_IMAGE_ID=your-image-id
```

**可选配置**：
```bash
# 后端地址（默认）
MONKEYCODE_BASE_URL=https://monkeycode-ai.com

# 代理端口（默认）
PROXY_PORT=9090

# 登录模式
MONKEYCODE_LOGIN_MODE=user
```

### 3. 启动代理

```bash
# 开发模式
npm run dev

# 生产模式
npm run build
npm start
```

### 4. 测试代理

```bash
# 运行测试脚本
./test-proxy.sh http://localhost:9090

# 或手动测试
curl http://localhost:9090/health
curl http://localhost:9090/v1/models
```

## API 使用

### Chat Completions API

**标准请求**：
```bash
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

**多轮对话**：
```bash
# 第一轮
curl -D - -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "Remember the number 42"}],
    "stream": false
  }'

# 提取 conversation_id（从响应头）
# X-Conversation-Id: conv-xxx

# 第二轮（复用对话）
curl -X POST http://localhost:9090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "What number did I ask you to remember?"}],
    "conversation_id": "conv-xxx",
    "stream": false
  }'
```

### Responses API (Codex 原生)

```bash
curl -X POST http://localhost:9090/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "input": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### 模型列表

```bash
curl http://localhost:9090/v1/models
```

## 管理端点

### 健康检查

```bash
curl http://localhost:9090/health
```

### 设置 Session Cookie

```bash
curl -X POST http://localhost:9090/admin/session \
  -H "Content-Type: text/plain" \
  -d "your-session-cookie"
```

### OAuth 登录

```bash
# 发送短信验证码
curl -X POST http://localhost:9090/admin/login/send-code \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800138000"}'

# 验证短信码
curl -X POST http://localhost:9090/admin/login/verify \
  -H "Content-Type: application/json" \
  -d '{"code": "123456"}'
```

### 自动发现

```bash
curl http://localhost:9090/admin/discover
```

### 号池管理

```bash
# 查看号池状态
curl http://localhost:9090/admin/pool/status

# 刷新号池
curl -X POST http://localhost:9090/admin/pool/refresh
```

## 架构说明

### 代理架构

```
Codex Client
    ↓ (OpenAI API)
Proxy (TypeScript/Express)
    ↓ (MonkeyCode API)
MonkeyCode Backend (Go)
    ↓ (TaskFlow API)
VM (Docker Container)
    ↓ (LLM API)
LLM Provider (OpenAI/Anthropic/DeepSeek)
```

### 多轮对话机制

1. **新对话**: 创建新任务，返回 `conversation_id`
2. **继续对话**: 通过 `conversation_id` 复用任务/VM
3. **超时清理**: 30 分钟无活动自动清理

### ACP 事件处理

| 事件类型 | 处理方式 |
|----------|----------|
| `agent_message_chunk` | 转换为 OpenAI 格式 |
| `agent_thought_chunk` | 前缀 [Thinking] |
| `tool_call` | 转换为 function_call |
| `tool_call_update` | 流式更新参数 |
| `usage_update` | 累积到最终响应 |
| `plan` | 日志记录 |
| `available_commands_update` | 日志记录 |

## 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `MONKEYCODE_SESSION_COOKIE` | 是 | - | Session Cookie |
| `MONKEYCODE_IMAGE_ID` | 是 | - | VM 镜像 ID |
| `MONKEYCODE_BASE_URL` | 否 | `https://monkeycode-ai.com` | 后端地址 |
| `PROXY_PORT` | 否 | `9090` | 代理端口 |
| `MONKEYCODE_LOGIN_MODE` | 否 | `user` | 登录模式 |
| `MONKEYCODE_HOST_ID` | 否 | `public_host` | 宿主机 ID |
| `ACCOUNT_POOL_FILE` | 否 | - | 号池配置文件 |

## 测试

### 运行测试脚本

```bash
./test-proxy.sh http://localhost:9090
```

### 测试覆盖范围

| 测试项 | 说明 | 预期结果 |
|--------|------|---------|
| 健康检查 | `GET /health` | 200 + `{"status":"ok"}` |
| 模型列表 | `GET /v1/models` | 200 + 模型数组 |
| Chat (非流式) | `POST /v1/chat/completions` | 200 + 完整响应 |
| Chat (流式) | `POST /v1/chat/completions` + stream | SSE 流 |
| Responses API | `POST /v1/responses` + stream | SSE 流 |
| 多轮对话 | 两轮对话测试 | conversation_id + 上下文保持 |
| 错误处理 | 无效模型、空消息 | 404、400 |

## 故障排除

### 连接问题

**问题**：无法连接到 MonkeyCode 后端

**解决方案**：
- 检查 `MONKEYCODE_BASE_URL` 是否正确
- 检查网络连接
- 检查 Session Cookie 是否有效

### 认证问题

**问题**：401 Unauthorized

**解决方案**：
- 检查 `MONKEYCODE_SESSION_COOKIE` 是否正确
- 检查 Session 是否过期
- 重新登录获取新的 Session Cookie

### 模型问题

**问题**：找不到模型

**解决方案**：
- 检查 `MONKEYCODE_IMAGE_ID` 是否正确
- 检查账号是否有可用模型
- 使用 `/v1/models` 查看可用模型列表

### 任务创建失败

**问题**：无法创建任务

**解决方案**：
- 检查 `MONKEYCODE_IMAGE_ID` 是否正确
- 检查账号是否有权限创建任务
- 检查 VM 配额是否已满

## 开发

### 项目结构

```
proxy/
├── src/
│   ├── auth.ts                    # 认证管理
│   ├── models.ts                  # 模型管理
│   ├── task-runner.ts             # 任务执行
│   ├── api-routes.ts              # API 路由
│   ├── account-pool.ts            # 号池管理
│   ├── admin-login.ts             # OAuth 登录
│   ├── conversation-manager.ts    # 对话管理
│   ├── server.ts                  # 服务器入口
│   └── types.ts                   # 类型定义
├── test-proxy.sh                  # 测试脚本
├── package.json                   # 项目配置
├── tsconfig.json                  # TypeScript 配置
└── README.md                      # 本文件
```

### 编译

```bash
npm run build
```

### 开发模式

```bash
npm run dev
```

## 协议文档

详细的协议分析文档位于 `docs/protocol/` 目录：

- `auth-protocol-complete.md` — 认证协议
- `llm-protocol-complete.md` — LLM 协议
- `websocket-protocol.md` — WebSocket 协议
- `api-endpoints.md` — API 端点
- `taskflow-vm-analysis.md` — VM 分析
- `architecture.md` — 架构总览
- `multi-turn-design.md` — 多轮对话设计

## 许可证

MIT License
