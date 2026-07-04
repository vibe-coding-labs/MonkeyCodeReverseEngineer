---
description: Proxy Express 中间件链和部署基础设施 — CORS、JSON 限流、健康检查、启动序列
protocol_version: based on proxy/src/server.ts (331 行)
confidence: high
last_verified: 2026-06-28
---

# 代理部署与中间件基础设施

## 1. Express 中间件链

```typescript
// proxy/src/server.ts — 完整的中间件注册顺序
const app = express()

// 1. CORS 中间件 — 允许所有来源
app.use(cors())

// 2. JSON 解析中间件 — 10MB 限制
app.use(express.json({ limit: "10mb" }))

// 3. 健康检查端点 — 最优先
app.get("/health", (_req, res) => {
  res.json({ status: "ok", uptime: process.uptime(), pool: ... })
})

// 4. OpenAI 兼容 API 路由（GET 和 POST）
app.use(createAPIRouter(modelManager, taskRunner, accountPool, conversationManager))

// 5. 管理端点
app.post("/admin/session", ...)
app.post("/admin/refresh-models", ...)
app.get("/admin/pool/status", ...)
app.post("/admin/pool/refresh", ...)
app.post("/admin/login/send-code", ...)
app.post("/admin/login/verify", ...)
app.post("/admin/login/callback", ...)
app.get("/admin/discover", ...)

// 6. 主入口 — 启动服务器
app.listen(PORT, () => { ... })
```

## 2. CORS 配置

```typescript
// 无限制 CORS（允许所有来源）
app.use(cors())
```

默认 CORS 配置允许：
- 所有 Origin（`Access-Control-Allow-Origin: *`）
- 所有方法（GET, POST, PUT, DELETE, OPTIONS）
- 默认头部（Content-Type, Authorization）

**注意：** 在生产环境需要限制 CORS：

```typescript
// 生产环境建议
app.use(cors({
  origin: [
    "http://localhost:11180",  // 本地开发
    "https://monkeycode-ai.com", // 官方前端（如果反向代理给前端用）
  ],
  methods: ["GET", "POST"],
  allowedHeaders: ["Content-Type", "Authorization"],
}))
```

## 3. JSON 请求体限制

```typescript
app.use(express.json({ limit: "10mb" }))
```

- 默认 10MB 限制
- 主要用于处理包含了 base64 编码文件内容的消息
- 如果 prompt 内容很大，可能需要增大

## 4. 健康检查端点

为运维提供：

```typescript
app.get("/health", (_req, res) => {
  const poolStats = accountPool?.getStats()
  res.json({
    status: "ok",
    uptime: process.uptime(),
    pool: poolStats || { mode: "single" },
  })
})
```

**响应示例：**
```json
{
  "status": "ok",
  "uptime": 3600.5,
  "pool": {
    "mode": "pool",
    "total": 5,
    "active": 4,
    "expired": 1,
    "invalid": 0,
    "locked": 1
  }
}
```

## 5. 启动序列

```
server.ts 启动顺序
────────────────
1. 加载环境变量
   ├── MONKEYCODE_BASE_URL
   ├── PROXY_PORT
   └── ACCOUNT_POOL_FILE

2. 初始化号池（双路径）
   ├── 从 ACCOUNT_POOL_FILE 加载多账号
   └── 从环境变量加载单账号补充
   └── 创建 AccountPool → initAll() → startHealthCheck()

3. 初始化单账号（无号池时）
   └── 创建 AuthManager → getSessionCookie()

4. 初始化模块
   ├── ModelManager(auth)
   └── TaskRunner(auth)

5. 预取模型列表（容忍失败）
   └── modelManager.fetchModels()

6. 创建 Express 应用
   ├── CORS 中间件
   ├── JSON 解析
   ├── 健康检查
   ├── API 路由
   ├── 管理端点
   └── app.listen(PORT)

7. 输出端点列表
   └── 打印所有可用端点
```

## 6. SSE 流控制

```typescript
// 所有流式响应都设置这些头
res.setHeader("Content-Type", "text/event-stream")
res.setHeader("Cache-Control", "no-cache")
res.setHeader("Connection", "keep-alive")
res.setHeader("X-Accel-Buffering", "no")  // 禁用 nginx 缓冲
```

`X-Accel-Buffering: no` 对 nginx 反向代理部署至关重要 — 如果不设置，nginx 会缓冲 SSE 数据流，导致客户端看到延迟。

## 7. 进程退出处理

```typescript
// 顶级错误处理
main().catch((err) => {
  console.error("Fatal error:", err)
  process.exit(1)
})
```

## 8. 环境变量清单

| 变量 | 用途 | 默认值 | 是否必需 |
|------|------|--------|---------|
| `MONKEYCODE_BASE_URL` | 后端 API 地址 | `https://monkeycode-ai.com` | 否 |
| `PROXY_PORT` | 代理监听端口 | `9090` | 否 |
| `REAL_PROXY_PORT` | Python 版代理端口 | `9091` | 否 |
| `ACCOUNT_POOL_FILE` | 号池配置 JSON 路径 | — | 否 |
| `MONKEYCODE_EMAIL` | 登录邮箱 | — | 条件 |
| `MONKEYCODE_PASSWORD` | 登录密码 | — | 条件 |
| `MONKEYCODE_SESSION_COOKIE` | 预提取 Session Cookie | — | 条件 |
| `MONKEYCODE_IMAGE_ID` | VM 镜像 ID | — | **是**（任务创建必需） |
| `MONKEYCODE_HOST_ID` | 宿主机 ID | `public_host` | 否 |
| `MONKEYCODE_TASK_TIMEOUT_MS` | 任务超时 | `3600000` (1h) | 否 |
| `MONKEYCODE_LOGIN_MODE` | 登录模式 | `user` | 否 |
| `MONKEYCODE_CAPTCHA_TOKEN` | 预提取验证码 Token | — | 否 |

## 9. 部署建议

### 9.1 Nginx 反向代理配置

```nginx
# /etc/nginx/sites-available/monkeycode-proxy
server {
    listen 443 ssl;
    server_name proxy.example.com;

    ssl_certificate /etc/ssl/certs/example.crt;
    ssl_certificate_key /etc/ssl/private/example.key;

    # API 端点
    location /v1/ {
        proxy_pass http://127.0.0.1:9090;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # SSE 缓冲控制
        proxy_buffering off;
        proxy_cache off;
    }

    # WebSocket 端点
    location /api/ {
        proxy_pass http://127.0.0.1:9090;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # 管理端点（限制内部访问）
    location /admin/ {
        allow 10.0.0.0/8;
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:9090;
    }
}
```

### 9.2 Systemd 服务配置

```ini
# /etc/systemd/system/monkeycode-proxy.service
[Unit]
Description=MonkeyCode Reverse Proxy
After=network.target

[Service]
Type=simple
User=monkeycode
WorkingDirectory=/opt/monkeycode-proxy
Environment=NODE_ENV=production
Environment=MONKEYCODE_BASE_URL=https://monkeycode-ai.com
Environment=MONKEYCODE_IMAGE_ID=xxx
Environment=MONKEYCODE_SESSION_COOKIE=xxx
Environment=PROXY_PORT=9090
ExecStart=/usr/bin/node dist/server.js
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 9.3 Docker 部署

```dockerfile
FROM node:20-alpine

WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY dist/ ./dist/

EXPOSE 9090

CMD ["node", "dist/server.js"]
```

---

## 相关章节

- [代理架构实现](01-architecture.md) — 完整代码结构
- [API 路由](04-acp-to-openai-mapping.md) — API 端点映射
- [附录：环境变量](../10-appendices/03-environment-variables.md) — 完整环境变量参考