# MonkeyCode 完整架构与数据流

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户端                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Electron 桌面 │  │  Web 浏览器  │  │  移动端 App  │          │
│  │ (main.cjs)   │  │  (Vue/React) │  │  (Flutter)   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                  │
│         └────────┬────────┘                  │                  │
│                  │                           │                  │
│         加载 https://monkeycode-ai.com       │                  │
└──────────────────┼───────────────────────────┼──────────────────┘
                   │                           │
                   ▼                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MonkeyCode 后端 (Go)                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    API Handler 层                        │   │
│  │  /api/v1/users/*  /api/v1/teams/*  /api/v1/admin/*     │   │
│  └──────────────────────┬──────────────────────────────────┘   │
│                         │                                       │
│  ┌──────────────────────┴──────────────────────────────────┐   │
│  │                   Domain UseCase 层                      │   │
│  │  TaskUsecase  ModelUsecase  UserUsecase  ...           │   │
│  └──────┬───────────────┬──────────────────┬──────────────┘   │
│         │               │                  │                    │
│  ┌──────┴──────┐  ┌────┴─────┐  ┌────────┴────────┐         │
│  │  Ent ORM   │  │  Redis   │  │  LLM Client      │         │
│  │ (PostgreSQL)│  │ (Session)│  │ (3 种接口类型)    │         │
│  └─────────────┘  └──────────┘  └────────┬────────┘         │
│                                            │                   │
│  ┌─────────────────────────────────────────┴──────────┐       │
│  │              TaskFlow Client (HTTP + WebSocket)     │       │
│  └─────────────────────────┬─────────────────────────┘       │
└────────────────────────────┼──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   TaskFlow 服务 (独立进程)                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  /internal/vm/*  /internal/task/*  /internal/ws/*      │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                              │                                  │
│  ┌──────────────────────────┴──────────────────────────────┐   │
│  │              Host Agent (远程机器上)                      │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                              │                                  │
│  ┌──────────────────────────┴──────────────────────────────┐   │
│  │            VirtualMachine (容器/VM)                      │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │   │
│  │  │   Codex     │  │   Claude    │  │  OpenCode   │    │   │
│  │  │  (Agent)    │  │  (Agent)    │  │  (Agent)    │    │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │   │
│  │         │                │                  │            │   │
│  │         └────────┬───────┴──────────────────┘            │   │
│  │                  │                                       │   │
│  │         ┌────────┴────────┐                             │   │
│  │         │   LLM Provider  │                             │   │
│  │         │  (OpenAI/Anthro-│                             │   │
│  │         │   pic/DeepSeek) │                             │   │
│  │         └─────────────────┘                             │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 核心数据流

### 任务创建与执行

```
1. 用户提交任务
   POST /api/v1/users/tasks
   Body: CreateTaskReq { content, model_id, host_id, image_id, repo, ... }

2. 后端处理
   a. 验证模型访问权限
   b. 解析模型配置 (API Key, Base URL, Interface Type)
   c. 创建 Task 记录 (status=pending)
   d. 创建 VM via TaskFlow
   e. 生成 Coding Agent 配置
   f. 存储 CreateTaskReq 到 Redis (10min TTL)

3. VM 启动
   a. TaskFlow 在 Host 上创建容器
   b. 安装 Coding Agent (Codex/Claude/OpenCode)
   c. 注入 LLM 配置 (API Key, Base URL, Model)
   d. 注入 MCP 配置
   e. VM Ready → 任务状态变为 processing

4. 任务执行
   a. Agent 使用 LLM 配置调用 Provider API
   b. Agent 输出通过 TaskLive WebSocket 流回后端
   c. 后端通过 Task Stream WebSocket 流给前端
   d. 前端解析 ACP 事件渲染 UI

5. 用户交互
   a. 继续对话: user-input via Stream WS
   b. 取消操作: user-cancel via Stream WS
   c. 文件操作: call via Control WS
   d. 切换模型: switch_model via Control WS
```

### Coding Agent 配置生成

```go
// 根据 InterfaceType 选择 NPM 包
func getNpmPackage(interfaceType InterfaceType) string {
    switch interfaceType {
    case InterfaceOpenAIChat:
        return "@ai-sdk/openai-compatible"
    case InterfaceOpenAIResponses:
        return "@ai-sdk/openai"
    case InterfaceAnthropic:
        return "@ai-sdk/anthropic"
    }
}
```

### MCP 配置

```go
// 始终包含的内置 MCP 服务器
type McpServerConfig struct {
    Name    string            `json:"name"`
    URL     string            `json:"url"`
    Headers map[string]string `json:"headers"`
}

// 内置 MCP: mcaiBuiltin
// URL: http://127.0.0.1:65510/mcp?task_id=...

// 可选 MCP: monkeycode-ai
// URL: {backend_url}/mcp
// 需要 API Key
```

## 配置系统

### 环境变量（前缀 MCAI_）

| 变量 | 对应配置 | 默认值 |
|------|---------|--------|
| MCAI_SERVER_ADDR | server.addr | :8888 |
| MCAI_SERVER_BASE_URL | server.base_url | http://localhost:8888 |
| MCAI_DATABASE_MASTER | database.master | - |
| MCAI_REDIS_HOST | redis.host | localhost |
| MCAI_REDIS_PORT | redis.port | 6379 |
| MCAI_SESSION_EXPIRE_DAY | session.expire_day | 1 |
| MCAI_LLM_API_KEY | llm.api_key | - |
| MCAI_LLM_BASE_URL | llm.base_url | - |
| MCAI_LLM_MODEL | llm.model | - |
| TASKFLOW_SERVER | taskflow server URL | - |

### VM 空闲管理

| 配置 | 默认值 | 说明 |
|------|--------|------|
| vm_idle.sleep_seconds | 900 (15min) | 空闲后休眠 |
| vm_idle.recycle_seconds | 259200 (3天) | 休眠后回收 |

## 错误处理模式

1. **LLM 错误**: 包装为中文描述错误消息
2. **ChatNoException()**: 将错误转为用户友好的内容字符串
3. **模拟模式**: `apiKey == ""` 时返回模拟响应
4. **WebSocket 重连**: 指数退避 + 去重
5. **健康检查**: 区分 HTTP 错误、API 错误、连接错误

## 关键 Hook/扩展点

| Hook | 方法 | 用途 |
|------|------|------|
| PrivilegeChecker | IsPrivileged() | 管理员权限检查 |
| ModelHook | ListPublic(), ValidateAccess() | 模型列表和访问控制扩展 |
| InternalHook | OnAgentAuth(), OnVmReady() | TaskFlow 回调扩展 |
| TaskHook | GetSystemPrompt(), OnTaskCreated() | 任务生命周期扩展 |
| ProjectHook | GenerateIssueSummary() | 项目扩展 |
| TeamHook | OnMemberAdded() | 团队成员变更回调 |
| SiteResolver | ResolveByHost() | 多租户站点解析 |
