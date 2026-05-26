# TaskFlow VM 完整分析报告

> **类型:** Research
> **目标:** 分析 MonkeyCode TaskFlow VM 的启动、运行、销毁完整生命周期
> **基于:** 开源后端 Go 源码逆向 + 协议文档 + API endpoint 分析
> **注意:** TaskFlow 本身是**闭源**的独立服务**，以下分析基于后端与 TaskFlow 的交互边界

---

## 1. 架构定位：TaskFlow 在整个系统中的角色

```
用户请求
    │ POST /api/v1/users/tasks
    ▼
┌─────────────────────────────────┐
│  MonkeyCode 后端 (Go, 开源)       │
│  - 处理用户请求、权限、模型查表             │
│  - 调用 TaskFlowClient            │
│  - 中继 WebSocket                 │
└────────────┬────────────────────┘
             │ HTTP + WebSocket (内部 API)
             ▼
┌─────────────────────────────────┐
│  TaskFlow 服务 (Go, 闭源)         │
│  - 管理远程 Host 机器             │
│  - 调度 VM 创建/销毁              │
│  - 转发 TaskLive 事件             │
└────────────┬────────────────────┘
             │ Docker API
             ▼
┌─────────────────────────────────┐
│  Host Agent (远程机器)            │
│  - 执行实际的 Docker 操作          │
│  - 监控 VM 状态                   │
└────────────┬────────────────────┘
             │ docker run / docker stop
             ▼
┌─────────────────────────────────┐
│  VirtualMachine (Docker 容器)
│  VM = Docker 容器                │
│  ├── Coding Agent (Node.js)     │   - codex | claude | opencode
│  ├── LLM Config (api_key/base)  │
│  ├── Git 仓库 (clone 注入)       │
│  ├── MCP 服务 (内置)             │
│  └── Terminal (SSH-like)        │
└─────────────────────────────────┘
             │ HTTP
             ▼
         LLM Provider (OpenAI/Anthropic/DeepSeek...)
```

**关键结论:** TaskFlow 是后端和 Docker 容器之间的中间调度层。后端不直接管理容器，全权委托给 TaskFlow。后端与 TaskFlow 之间通过 HTTP + WebSocket (TaskLive) 两条通道通信。

---

## 1.1 后端 ↔ TaskFlow 通信协议

后端和 TaskFlow 之间的通信**全都在内部网络中**（不在公网上），使用两种协议：

| 通道 | 协议 | 方向 | 用途 |
|------|------|------|------|
| **HTTP API** | HTTP/JSON | 后端 → TaskFlow | 创建/删除 VM、管理任务 |
| **TaskLive WS** | WebSocket JSON | 双向 | Agent 输出事件流、任务状态更新 |

TaskLive WebSocket 端点：
```
ws(s)://TASKFLOW_SERVER/internal/ws/task-live?id={taskID}&flush={bool}
```

这个 WS **没有读限制**（`SetReadLimit(-1)`），因为内部通信量大。

通信格式（TaskChunk）：
```go
type TaskChunk struct {
    Data      []byte `json:"data,omitempty"`   // 事件数据（ACP JSON）
    Event     string `json:"event"`            // 事件类型标识
    Kind      string `json:"kind"`             // 子类型（如 acp_event）
    Timestamp int64  `json:"timestamp,omitempty"` // 毫秒时间戳
}
```

后端收到 TaskChunk 后：
1. 原样包装成 `TaskStreamMessage`（type + kind + data + timestamp）
2. 通过 Task Stream WebSocket 推送给前端
3. 同时写入 Redis（持久化，用于 attach 模式的历史回放）

---

## 2. VM 启动过程

### 2.1 启动链条

```
Step 1: 用户 POST /api/v1/users/tasks
Step 2: 后端验证权限 + 查 model_id 对应的 LLM 配置
Step 3: 后端 POST /api/v1/users/hosts/vms → 创建 VM → 拿到 vm_id
Step 4: 后端 POST /api/v1/users/tasks → 关联 task 和 vm
Step 5: 后端通过 TaskFlowClient 发送 CreateVirtualMachineReq
Step 6: TaskFlow 调度到某个 Host → Host Agent 执行 docker run
Step 7: 容器启动，Coding Agent 初始化
Step 8: Agent 连接 LLM，等待用户输入
Step 9: 任务状态 → processing
```

### 2.2 后端 → TaskFlow 的 VM 创建请求

后端查完数据库后，这样告诉 TaskFlow 要建什么 VM：

```go
// 源码: backend/internal/taskflow/vm.go
type CreateVirtualMachineReq struct {
    UserID              string         `json:"user_id"`
    HostID              string         `json:"host_id"`       // 如 "public_host"
    HostName            string         `json:"hostname"`       // 宿主机名
    Git                 Git            `json:"git"`            // 注入 git 仓库
    ZipUrl              string         `json:"zip_url"`        // 压缩包替代 git
    ImageURL            string         `json:"image_url"`      // VM 镜像地址
    ProxyURL            string         `json:"proxy_url"`      // 代理配置
    TaskID              uuid.UUID      `json:"task_id"`        // 关联 task
    LLM                 LLMProviderReq `json:"llm"`            // LLM 配置（见下）
    Cores               string         `json:"cores`json:"cores"`          // CPU 核数
    Memory              uint64         `json:"memory"`          // 内存字节数
    InstallCodingAgents bool           `json:"install_coding_agents"` // 是否装 Agent
    Envs                []string       `json:"envs,omitempty"`  // 额外环境变量
    LogStore            string         `json:"log_store,omitempty"` // 日志存储
}
```

其中 LLM 配置是：

```go
type LLMProviderReq struct {
    Provider    LLMProvider `json:"provider"`     // 固定 "openai"（字符串常量）
    ApiKey      string      `json:"api_key"`      // 已替换为真实 key
    BaseURL     string      `json:"base_url"`     // 如 https://api.siliconflow.cn/v1
    Model       string      `json:"model"`        // 如 deepseek-chat
    Temperature *float32    `json:"temperature,omitempty"`
}
```

**关键细节:**
- `Provider` 字段**固定为 `"openai"`**，不管实际是 Claude 还是别的。实际接口类型由 VM 内的 Agent 根据模型名自动识别
- `ApiKey` 如果是 `public:model:{id}` 前缀，后端已经在查表时替换为真实 Provider 的 API Key
- `HostID` 填 `"public_host"` 就会用公共资源池，不需要自建服务器

### 2.3 前端 → 后端的 VM 创建 API

这是前端直接调用的 API（我们的反向代理也是调这个）：

```json
POST /api/v1/users/hosts/vms
{
  "host_id": "public_host",
  "name": "My VM",
  "image_id": "550e8400-...",           // 镜像 UUID
  "model_id": "660e8400-...",           // 模型配置 UUID
  "life": 3600,                         // 存活秒数（最大 10800 = 3h）
  "resource": {"cpu": 1, "memory": 1073741824},  // 1核1G
  "install_coding_agents": true,
  "repo": {                             // 代码仓库（可为空）
    "repo_url": "https://github.com/user/repo.git",
    "branch": "main"
  }
}
```

### 2.4 后端创建任务

创建完 VM 后，创建 Task 关联到 VM：

```json
POST /api/v1/users/tasks
{
  "content": "写一个快速排序",
  "host_id": "public_host",
  "image_id": "550e8400-...",
  "model_id": "660e8400-...",
  "cli_name": "claude",             // Agent 类型: codex|claude|opencode
  "resource": {"core": 1, "memory": 1073741824, "life": 3600},
  "repo": {"repo_url": "", "branch": "master", ...}
}
```

**后端在创建 Task 时做了这些事:**
1. 验证模型访问权限（用户有没有权限用这个模型）
2. 解析模型配置（API Key、Base URL、Interface Type）
3. 创建 Task 记录写入数据库（status = `pending`）
4. 通过 TaskFlow 创建 VM
5. 生成 Coding Agent 配置文件
6. 把 `CreateTaskReq` 存到 Redis（10 分钟 TTL，供 Agent 读取）

### 2.5 Agent 的 NPM 包选择

后端根据模型的 `interface_type` 决定 VM 内装什么 Agent 包：

```go
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

这些是 Vercel 的 `ai-sdk` 包，Agent 用它们调用 LLM。

---

## 3. VM 运行过程

### 3.1 VM 状态机

```
                 POST /hosts/vms
                      │
                   ┌──▼──┐
                   │pending│ ← Docker 还在拉镜像
                   └──┬──┘
                      │ 容器就绪
                   ┌──▼──┐
         ┌─────────│online│─────────┐
         │         └──┬──┘          │
         │            │              │
    ┌────▼───┐   ┌────▼───┐    ┌───▼────┐
    │hibernated│  │processing│  │ offline │
    │(15min空闲)│  │(任务执行) │  │(主动停止)│
    └────┬───┘   └─────────┘   └─────────┘
         │ 有 Control WS 连接就自动恢复
         └──────────→ online
```

| 状态 | 触发条件 | 说明 |
|------|---------|------|
| `unknown` | 初始 | 刚创建，状态未知 |
| `pending` | POST VM | Docker 正在拉镜像、启动容器 |
| `online` | 容器就绪 | VM 正常运行，等待任务 |
| `processing` | 任务分配给 VM | Agent 正在执行任务 |
| `hibernated` | 15 分钟空闲 | 容器被休眠以节省资源 |
| `offline` | 主动停止/超时 | VM 已停止运行 |

### 3.2 数据流：Agent 输出 → 用户

```
VM 内的 Coding Agent
    │ Agent 输出文本（"Hello world"）
    ▼
Agent 将输出 → 包装成 ACP 事件 → TaskLive WebSocket
    │ ws://TASKFLOW_SERVER/internal/ws/task-live?id={taskID}&flush={bool}
    ▼
TaskFlow 服务 → 转发 TaskChunk
    │ TaskChunk {data, event, kind, timestamp}
    ▼
MonkeyCode 后端
    │ 从 TaskLive WS 收到事件
    │ 包装成 TaskStreamMessage
    │ 写入 Redis 持久化（历史回放）
    ▼
用户 Task Stream WebSocket
    │ wss://monkeycode-ai.com/api/v1/users/tasks/stream?id={taskId}&mode=new}
    │ {"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_message_chunk\",\"text\":\"Hello\"}"}
    ▼
前端/反向代理 → 渲染/转发
```

**TaskLive WebSocket（内部）** 的 TaskChunk 格式：

```go
type TaskChunk struct {
    Data      []byte `json:"data,omitempty"`   // 事件数据
    Event     string `json:"event"`            // 事件类型
    Kind      string `json:"kind"`             // 子类型
    Timestamp int64  `json:"timestamp,omitempty"`
}
```

这个 WebSocket **没有读限制**（`SetReadLimit(-1)`），因为内部通信量大。

### 3.3 WebSocket 双通道设计

```
前端（或反向代理）←→ Task Stream WS ←→ 后端 ←→ TaskLive WS ←→ TaskFlow ←→ VM

前端（或反向代理）←→ Task Control WS ←→ 后端 ←→ (直接管理)
```

| 通道 | 端点 | 用途 |
|------|------|------|
| **Task Stream** | `/api/v1/users/tasks/stream?id=X&mode=new\|attach` | LLM 推理内容流（ACP 事件） |
| **Task Control** | `/api/v1/users/tasks/control?id=X` | 管理操作：重启、切换模型、文件操作、VM 保活 |
| **TaskLive** | `ws://TASKFLOW_SERVER/internal/ws/task-live?id=X` | 后端 ←→ TaskFlow 内部流（用户可见） |

**Task Control WebSocket 的特殊作用：**
- 启动 VM 保活：每 60 秒刷新 VM 空闲计时器，防止 `hibernated`
- 多标签页支持：ControlConn 是一对多映射（一个 task → 多个并发 WS）
- RPC 调用：`repo_file_list`、`repo_read_file`、`switch_model`、`restart`

### 3.4 用户输入如何发送到 VM

```
用户 → WS → 后端 → Redis(持久化) → TaskFlow → VM
```

用户输入格式（**新格式，base64 编码**）：

```json
{
  "type": "user-input",
  "data": "{\"content\":\"5L2g5aW9\",\"attachments\":[{\"url\":\"...\",\"filename\":\"a.txt\"}]}"
}
```

后端收到后：
1. 解析 `user-input` 消息
2. 存入 Redis（持久化，供历史回放）
3. 转发给 TaskFlow（通过 TaskLive WS 或其他内部通道）
4. TaskFlow 发给 VM 内的 Agent

---

## 4. VM 销毁过程

### 4.1 三种销毁途径

```
途径 1: 正常结束
    Task 完成 → Agent 输出 task-ended → 后端清理
    VM 状态: processing → offline（不会被立即删除，可能被复用）

途径 2: 用户主动停止
    PUT /api/v1/users/tasks/stop {"id": "task-uuid"}
    → 后端通知 TaskFlow → 停止 Agent → VM offline

途径 3: 超时回收（自动）
    Resource life 到期（默认 1h，最大 3h）
    → TaskFlow 自动销毁容器
    → 或 15min 空闲 → hibernated → 3 天后 recycle → 删除

    删除 VM: DELETE /api/v1/users/hosts/vms/{id}
    → 后端通知 TaskFlow → Host Agent 执行 docker rm

途径 4: 用户主动删除
    DELETE /api/v1/users/hosts/vms/{id}
    → 直接删除 VM（如果有 task 在运行，不允许删除）
```

### 4.2 超时时间一览

| 超时 | 默认值 | 最大 | 触发动作 |
|------|--------|------|---------|
| `resource.life` | 3600s (1h) | 10800s (3h) | VM 到期销毁 |
| `vm_idle.sleep_seconds` | 900s (15min) | 配置 | VM 空闲 → hibernated |
| `vm_idle.recycle_seconds` | 259200s (3天) | 配置 | hibernated → 彻底删除 |
| Redis TaskReq TTL | 600s (10min) | — | Task 创建请求过期 |

### 4.3 VM 复用机制（重要）

我们的反向代理在 `api-routes.ts:97-103` 实现了 VM 复用：

```typescript
async function getOrCreateVM(taskRunner: TaskRunner): Promise<string> {
  const vms = await taskRunner.listVMs()
  const activeVm = vms.find((v) => v.status === "running" || v.status === "ready")
  if (activeVm) return activeVm.id
  return await taskRunner.createVM()
}
```

它会检查已有 VM，有活着的就直接复用，避免每次请求都新建容器的开销。

---

## 5. 资源配置

### 5.1 默认资源

```go
// 后端源码: 如果请求中没传 resource，用这个默认
if r.Resource == nil {
    r.Resource = &VMResource{
        Core:   1,               // 1 核 CPU
        Memory: 1 << 30,         // 1 GB
        Life:   3600,            // 1 小时
    }
}
```

### 5.2 公共主机限制

```go
// 使用 public_host 时，life 不能超过 3h
const MaxLifeForPublicHost = 10800  // 3 * 3600
```

---

## 6. 与 Host / Host Agent 的关系

```
TaskFlow 服务
    │ 管理多台 Host 机器
    │ 每台 Host 上运行一个 Host Agent
    ▼
Host Agent (运行在宿主机上)
    │ 执行实际的 Docker 命令
    │ docker pull image
    │ docker run --rm -d ...
    │ docker stop / docker rm
    │ 监控容器资源使用
    ▼
Docker 容器 (VM)
    ├── Coding Agent (Node.js)
    ├── Git 仓库文件
    ├── MCP 内置服务 (http://127.0.0.1:65510/mcp)
    └── 工作目录 (/workspace)
```

**关键点：**
- `public_host` 是 MonkeyCode 官方提供的公共 Host 资源池
- 用户也可以自建 Host（需要部署 Host Agent），但 `public_host` 已经可用
- Host Agent 负责 docker pull、docker run、docker stop、docker rm
- 每台 Host 可以运行多个 VM 容器

---

## 7. 后端 Hook 扩展点（TaskFlow 回调）

后端提供了一套 Hook 接口，TaskFlow 在某些事件发生时通过它们回调后端：

```go
type InternalHook interface {
    OnAgentAuth(ctx context.Context, taskID string, auth AgentAuth) error
    OnVmReady(ctx context.Context, vmID string, taskID string) error
}
```

| Hook | 触发时机 | 用途 |
|------|---------|------|
| `OnAgentAuth` | Agent 在 VM 内启动时 | 验证 Agent 身份，传递认证信息 |
| `OnVmReady` | VM 容器就绪时 | 通知后端 VM 已可用，将任务状态从 pending → processing |

还有其他非 TaskFlow 相关 Hook：

| Hook | 用途 |
|------|------|
| `PrivilegeChecker` | 管理员权限检查 |
| `ModelHook` | 模型列表和访问控制扩展 |
| `TaskHook` | 任务生命周期（SystemPrompt、OnCreated） |
| `ProjectHook` | 项目扩展（Issue 摘要生成） |
| `TeamHook` | 团队成员变更回调 |
| `SiteResolver` | 多租户站点解析 |

---

## 8. 容器内环境详解

### 8.1 Docker 容器配置

从 `CreateVirtualMachineReq` 结构体可以推断出容器创建参数：

| 参数 | 来源 | 说明 |
|------|------|------|
| **镜像** | `ImageURL` | 后端传容器镜像地址 |
| **CPU** | `Cores` | CPU 核数（字符串） |
| **内存** | `Memory` | 内存字节数（uint64） |
| **环境变量** | `Envs` | 额外环境变量列表 |
| **网络代理** | `ProxyURL` | 容器内 HTTP 代理配置 |
| **日志** | `LogStore` | 日志存储后端（如 loki） |
| **Git** | `Git` | 注入的代码仓库 |
| **启动命令** | — | Agent 自动启动（通过 install_coding_agents） |

### 8.2 容器启动后自动启动的组件

```
容器启动
  │
  ├── Coding Agent (Node.js)
  │   ├── 通过 @ai-sdk/* 调 LLM
  │   │     @ai-sdk/openai-compatible → OpenAI Chat API
  │   │     @ai-sdk/anthropic          → Claude Messages API
  │   │     @ai-sdk/openai           → OpenAI Responses API
 原生（Codex）
  │   ├── 输出 ACP 事件 → TaskLive WS → 后端 → 用户
  │   ├── 接收用户输入 → TaskLive WS ← 后端 ← 用户
  │   └── 读取/写入工作目录 (/workspace)
  │
  ├── MCP 内置服务
  │   └── http://127.0.0.1:65510/mcp?task_id=...
  │       └── 提供文件操作、git 操作等工具
  │
  ├── SSH-like Terminal
  │   └── GET /api/v1/users/hosts/vms/{vmId}/terminals/connect
  │       └── 用户可以通过 WebSocket 直接连接到容器 shell
  │
  └── Git 仓库（已 clone 到 /workspace）
```

### 8.3 Terminal 通道（额外入口）

除了 Task Stream / Control WS 之外，用户还可以**直接连接到容器的 shell**：

```
端点: GET /api/v1/users/hosts/vms/{vmId}/terminals/connect
参数: terminal_id, col(列数), row(行数)
协议: 二进制帧（终端数据）+ 文本帧（resize 事件）
心跳: 15s ping, 5s 超时
重连: 指数退避 1s → 30s
```

这意味着 VM 容器里运行着一个 shell 进程（如 bash），用户可以通过 Terminal WS 直接交互。

### 8.4 Agent 配置注入机制

后端通过 Redis 向 VM 内的 Agent 传递配置：

```
后端
  │ 创建 Task 时把 CreateTaskReq 序列化 JSON
  │ 写入 Redis key，TTL = 10 分钟
  ▼
Redis
  │ key: task_config:{task_id}
  │ value: CreateTaskReq JSON（含 prompt、llm 配置、system_prompt、mcp_configs 等）
  │ TTL: 600s (10min)
  ▼
TaskFlow / Host Agent
  │ 容器启动后，Agent 从 Redis 读取配置
  │ 取到后立即执行
```

TTL 只有 10 分钟意味着：如果容器启动太慢（>10 分钟），Agent 可能拿不到配置。这表明容器镜像应该已经是预构建的（不包含第一次拉镜像的时间）。

### 8.5 MCP（Model Context Protocol）系统

VM 容器内始终运行一个内置 MCP 服务器：

```go
// 内置 MCP 服务
// 运行在容器内
容器内
// URL: http://127.0.0.1:65510/mcp?task_id=...
```

MCP 服务器提供工具调用能力：

```
Agent → 调 MCP 工具 → 内置 MCP 服务 → 执行文件/git 操作
                    → 可选 MCP 配置:
                    {name: "mcaiBuiltin", url: "http://127.0.0.1:65510/mcp", headers: {...}}
```

还支持可选的外部 MCP：

```
{name: "monkeycode-ai", url: "{backend_url}/mcp", headers: {Authorization: "Bearer xxx"}}
```

### 8.6 日志系统

VM 内 Agent 的输出日志可以配置存储后端：

```
LogStore = "loki"  // 使用 Grafana Loki
```

Loki 是 Grafana 的日志聚合系统。VM 内的日志可以通过 Loki 查询和检索。

---

### 8.7 并发保护机制

VM 回收操作有防重入保护：

```go
// backend/biz/host/handler/v1/internal_auth.go
// 使用 Redis SetNX 确保 VM 回收不会并发执行
// 当一个回收任务已经在进行时，不会启动第二个
```

---

## 9. TaskFlow 的完整调用链总结

从用户请求到 LLM 响应，中间的所有环节：

```
用户/反向代理
  │ 1. POST /api/v1/users/hosts/vms (创建 VM)
  │ 2. POST /api/v1/users/tasks (创建 Task)
  │ 3. WS /api/v1/users/tasks/stream (连接流)
  │ 4. WS send user-input (发送提示)
  ▼
MonkeyCode 后端 (Go)
  │ 5. 验证 session + 权限
  │ 6. 查数据库: model_id → {api_key, base_url, model}
  │ 7. public:model:{id} → 替换为真实 API Key
  │ 8. 调用 TaskFlowClient HTTP → CreateVirtualMachineReq
  │ 9. 写入 Redis → task_config:{task_id} (10min TTL)
  │ 10. 连接 TaskLive WS → 接收 TaskChunk
  │ 11. 中继 → 前端 Task Stream WS
  │ 12. 持久化 → Redis (历史回放)
  ▼
TaskFlow 服务 (Go, 闭源)
  │ 13. 接收 CreateVM 请求
  │ 14. 调度到某个 Host（调度策略未知）
  │ 15. 通知 Host Agent 执行操作
  │ 16. 连接 TaskLive WS → 转发 Agent 事件
  ▼
Host Agent
  │ 17. docker pull {ImageURL}
  │ 18. docker run --rm -d --cpus {Cores} --memory {Memory} ...
  │ 19. 等待容器就绪
  │ 20. 回调后端: OnVmReady()
  ▼
Docker 容器 (VM)
  │ 21. 容器启动，环境变量注入
  │ 22. Coding Agent (Node.js) 自动启动
  │ 23. 从 Redis 读取 task_config
  │ 24. Agent 初始化: @ai-sdk/openai-compatible 等
  │ 25. 回调后端: OnAgentAuth()
  │ 26. 等待 user-input
  ▼
  │ 收到 user-input 后:
  │ 27. Agent 构造 LLM 请求（OpenAI/Anthropic 格式）
  │ 28. HTTP 调用 LLM Provider API（SiliconFlow/OpenAI/DeepSeek...）
  │ 29. Agent 接收流式响应
  │ 30. 包装成 ACP 事件 → TaskLive WS
  ▼
LLM Provider
  │ 31. 处理请求，返回 completion
  │
  32 ACP 事件逆流而上:
  │ TaskLive WS → 后端 → Task Stream WS → 用户
```

---

## 10. 已知但不可见的闭源部分

TaskFlow 服务本身是**闭源**的，以下细节无法从源码验证：

| 问题 | 已知信息 | 信息来源 |
|------|---------|---------|
| TaskFlow 如何调度 Host？ | 存在调度逻辑，策略未知 | 推理（后端只传参数） |
| Docker 镜像如何管理？ | 有 `image_id` 和 `ImageURL` | API 字段名 |
| Host Agent 如何部署？ | 需要在宿主机安装进程 | 架构图 |
| Agent Node.js 代码？ | 使用 `@ai-sdk/*` NPM 包 | 后端 getNpmPackage() |
| 容器网络如何隔离？ | 未知（标准 Docker 网络） | 推理 |
| 多租户隔离？ | 每个用户独立 VM | 架构设计 |
| Host 的扩容缩容？ | TaskFlow 管理，策略未知 | 推理 |
| TaskFlow 的容错/重试？ | 后端有 InternalHook 回调 | 代码中的 Hook 接口 |

---

## 11. 对我们的影响

### 11.1 对反向代理的约束

| 约束 | 值 | 影响 |
|------|------|------|
| VM 创建 VM 耗时 | ~几秒到十几秒（拉镜像） | 首次请求慢；已实现 getOrCreateVM 复用 |
VM 最大存活 | 3h（public_host） | 需要保活或重建 |
空闲 15min 休眠 | 默认 | Control WS 保活防休眠 |
3 天回收 | 默认 | 长期不用的 VM 自动清理 |
Task 创建需要 VM | 必须先有 VM | 代理必须两步走：先创建 VM，再创建 Task |
不创建 VM 也能用？ | **不行** | 这是最小限制 |

### 11.2 号池场景的影响

由于每个账号的 VM 是独立的（VM 属于创建它的用户），号池场景下：
1. 每次请求从号池选一个账号
2. 用该账号创建/复用 VM
3. VM 和账号绑定

VM 创建开销（几秒）是每次切换账号的主要延迟来源。优化方向：
- 每个账号预先创建并保持 1-2 个 VM 在线
- 会话切换时复用已有 VM

---

## 附录 A: 相关 API 端点汇总

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/users/hosts/vms` | 创建 VM |
| GET | `/api/v1/users/hosts/vms` | 列出 VM |
| DELETE | `/api/v1/users/hosts/vms/{id}` | 删除 VM |
| POST | `/api/v1/users/tasks` | 创建任务 |
| GET | `/api/v1/users/tasks/stream?id=X&mode=new` | Task Stream WS |
| GET | `/api/v1/users/tasks/control?id=X` | Task Control WS |
| GET | `/api/v1/users/hosts/vms/{id}/terminals/connect` | 终端 WS |
| PUT | `/api/v1/users/tasks/stop` | 停止任务 |

## 附录 B: 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `TASKFLOW_SERVER` | TaskFlow 服务地址 | —（必填） |
| `MCAI_LLM_API_KEY` | 后端默认 LLM API Key | — |
| `MCAI_LLM_BASE_URL` | 后端默认 LLM Base URL | — |
| `MCAI_LLM_MODEL` | 后端默认模型 | — |
| 无 VM 相关变量 | VM 配置全是 API 参数传递 | — |

## 附录 C: 关键源码引用

```
backend/internal/taskflow/vm.go     — CreateVirtualMachineReq 结构体
backend/internal/taskflow/client.go  — TaskFlowClient（HTTP 调用）
backend/internal/taskflow/ws.go      — TaskLive WebSocket
backend/pkg/hosts/public.go          — public_host 限制
backend/config/config.go:216         — session.expire_day 默认值
```