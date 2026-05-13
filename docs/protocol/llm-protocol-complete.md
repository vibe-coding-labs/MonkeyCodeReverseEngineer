# MonkeyCode LLM API 通信协议完整分析

> 基于 chaitin/MonkeyCode 开源后端源码逆向分析
> 分析日期: 2026-05-11

---

## 1. 架构概览

MonkeyCode 的 LLM 通信采用 **任务驱动模型**：用户创建任务 → 后端调度 VM → VM 内的 Agent 通过 LLM Client 调用模型 → 结果通过 WebSocket 流式推送给前端。

```
┌──────────┐     HTTP REST      ┌──────────────┐     TaskFlow API     ┌──────────────┐
│  Frontend │ ──────────────→  │  Backend     │ ────────────────→  │  TaskFlow    │
│  (React)  │ ←────────────── │  (Go/Gin)    │ ←──────────────── │  (VM Agent)  │
└──────────┘     WebSocket      └──────────────┘     TaskLive WS      └──────────────┘
                                       │                                      │
                                       │ LLM Client                           │ LLM Provider
                                       ↓                                      ↓
                                ┌──────────────┐                     ┌──────────────┐
                                │  LLM Client  │ ────────────────→ │  OpenAI /    │
                                │  (3 接口类型) │                    │  Anthropic / │
                                └──────────────┘                     │  DeepSeek... │
                                                                     └──────────────┘
```

**关键洞察**: LLM Client 运行在 **TaskFlow VM 内部**，而非 Backend 进程中。Backend 负责：
- 模型配置管理（CRUD + 健康检查）
- 任务创建与调度
- WebSocket 流转发（Backend 是 TaskFlow → Frontend 的中继）

---

## 2. 模型管理 API

### 2.1 端点一览

| Method | Path | 认证 | 说明 |
|--------|------|------|------|
| GET | `/api/v1/users/models` | Required | 列出当前用户可用模型 |
| POST | `/api/v1/users/models` | Required | 创建用户私有模型 |
| PUT | `/api/v1/users/models/{id}` | Required | 更新模型配置 |
| DELETE | `/api/v1/users/models/{id}` | Required | 删除模型 |
| GET | `/api/v1/users/models/{id}/health-check` | Required | 模型健康检查（按 ID） |
| POST | `/api/v1/users/models/health-check` | Required | 模型健康检查（按配置） |
| GET | `/api/v1/users/models/providers` | Public | 获取供应商模型列表 |

### 2.2 列出模型

**请求**: `GET /api/v1/users/models?limit=100&cursor=xxx`

**响应**:
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "models": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "provider": "OpenAI",
        "api_key": "",
        "base_url": "",
        "model": "gpt-4o",
        "temperature": 0.7,
        "is_default": false,
        "created_at": 1715299200,
        "updated_at": 1715299200,
        "weight": 1,
        "owner": {
          "id": "admin-uuid",
          "type": "public",
          "name": "MonkeyCode AI Team"
        },
        "interface_type": "openai_chat",
        "is_free": false,
        "access_level": "pro",
        "last_check_at": 1715299200,
        "last_check_success": true,
        "last_check_error": "",
        "thinking_enabled": false,
        "context_limit": 128000,
        "output_limit": 16384
      }
    ],
    "page": {
      "next_cursor": "xxx",
      "has_more": false
    }
  }
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | uuid | 模型配置唯一标识 |
| `provider` | string | 提供商常量（见 2.5） |
| `api_key` | string | API Key（公开/团队模型返回空） |
| `base_url` | string | API 端点（公开/团队模型返回空） |
| `model` | string | 模型名称（如 `gpt-4o`, `deepseek-chat`） |
| `temperature` | float64 | 温度参数 |
| `is_default` | bool | 是否为用户默认模型 |
| `weight` | int | 权重（用于负载均衡） |
| `owner` | object | 所有者信息（private/team/public） |
| `interface_type` | string | API 接口类型（见第 3 节） |
| `is_free` | bool | 是否免费模型 |
| `access_level` | string | 访问级别（basic/pro） |
| `last_check_success` | bool | 最近健康检查结果 |
| `thinking_enabled` | bool | 是否启用思考模式 |
| `context_limit` | int | 上下文窗口 token 数 |
| `output_limit` | int | 最大输出 token 数 |

### 2.3 创建模型

**请求**: `POST /api/v1/users/models`

```json
{
  "provider": "OpenAI",
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "temperature": 0.7,
  "is_default": false,
  "interface_type": "openai_chat",
  "thinking_enabled": false,
  "context_limit": 128000,
  "output_limit": 16384
}
```

**响应**: 返回完整的 `Model` 对象（含 `id`, `created_at` 等）

**验证规则**:
- `provider`: required
- `api_key`: required
- `base_url`: required
- `model`: required
- `interface_type`: required, 枚举值 `openai_chat | openai_responses | anthropic`

### 2.4 更新模型

**请求**: `PUT /api/v1/users/models/{id}`

```json
{
  "provider": "DeepSeek",
  "api_key": "sk-xxx",
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "temperature": 0.5,
  "is_default": true,
  "interface_type": "openai_chat",
  "thinking_enabled": true,
  "context_limit": 64000,
  "output_limit": 8192
}
```

所有字段均为可选（partial update），仅传需要更新的字段。

### 2.5 模型提供商常量

| Provider 常量 | 值 | 说明 |
|---------------|-----|------|
| `ModelProviderSiliconFlow` | `SiliconFlow` | 硅基流动 |
| `ModelProviderOpenAI` | `OpenAI` | OpenAI |
| `ModelProviderOllama` | `Ollama` | Ollama 本地 |
| `ModelProviderDeepSeek` | `DeepSeek` | DeepSeek |
| `ModelProviderMoonshot` | `Moonshot` | Kimi/Moonshot |
| `ModelProviderAzureOpenAI` | `AzureOpenAI` | Azure OpenAI |
| `ModelProviderBaiZhiCloud` | `BaiZhiCloud` | 百智云 |
| `ModelProviderHunyuan` | `Hunyuan` | 腾讯混元 |
| `ModelProviderBaiLian` | `BaiLian` | 百炼 |
| `ModelProviderVolcengine` | `Volcengine` | 火山引擎 |
| `ModelProviderGoogle` | `Gemini` | Google Gemini |

### 2.6 品牌默认模型

```go
var ModelProviderBrandModelsList = map[consts.ModelProvider][]ProviderModelListItem{
    ModelProviderOpenAI:      {{Model: "gpt-4o"}},
    ModelProviderDeepSeek:    {{Model: "deepseek-reasoner"}, {Model: "deepseek-chat"}},
    ModelProviderMoonshot:    {{Model: "moonshot-v1-auto"}, {Model: "moonshot-v1-8k"}, {Model: "moonshot-v1-32k"}, {Model: "moonshot-v1-128k"}},
    ModelProviderAzureOpenAI: {{Model: "gpt-4"}, {Model: "gpt-4o"}, {Model: "gpt-4o-mini"}, {Model: "gpt-4o-nano"}, {Model: "gpt-4.1"}, {Model: "gpt-4.1-mini"}, {Model: "gpt-4.1-nano"}, {Model: "o1"}, {Model: "o1-mini"}, {Model: "o3"}, {Model: "o3-mini"}, {Model: "o4-mini"}},
    ModelProviderVolcengine:  {{Model: "doubao-seed-1.6-250615"}, {Model: "doubao-seed-1.6-flash-250615"}, {Model: "doubao-seed-1.6-thinking-250615"}, {Model: "doubao-1.5-thinking-vision-pro-250428"}, {Model: "deepseek-r1-250528"}},
}
```

### 2.7 Public Model API Key 机制

```go
const ModelApiKeyPrefix = "public:model:"

func PublicModelKey(key string) string {
    return ModelApiKeyPrefix + key
}
```

- 管理员创建公开模型时，`api_key` 设为 `public:model:{model_id}`
- 用户使用公开模型时，后端自动替换为实际 Provider API Key
- `HideCredentials()` 清空 `api_key` 和 `base_url`
- `HideSharedCredentials()` 仅对非私有模型（team/public）清空凭证

### 2.8 模型所有者层级

| OwnerType | 条件 | 说明 |
|-----------|------|------|
| `private` | 普通用户创建 | 仅创建者可见可用 |
| `team` | 企业用户创建 | 团队内共享 |
| `public` | 管理员创建 | 所有用户可见可用 |

### 2.9 健康检查

**按 ID 检查**: `GET /api/v1/users/models/{id}/health-check`

**按配置检查**: `POST /api/v1/users/models/health-check`

```json
{
  "provider": "OpenAI",
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "interface_type": "openai_chat"
}
```

**响应**:
```json
{
  "code": 0,
  "data": {
    "success": true,
    "error": ""
  }
}
```

**健康检查协议细节**:
- 超时: 30 秒
- 请求体: 最小请求 `{"model": "xxx", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}`
- 判定: HTTP 200-299 且响应无 `error` 对象
- 检查后更新数据库: `last_check_at`, `last_check_success`, `last_check_error`

---

## 3. LLM Client 三种接口类型

### 3.1 接口类型常量

```go
type InterfaceType string

const (
    InterfaceTypeOpenAIChat     InterfaceType = "openai_chat"      // OpenAI Chat Completions
    InterfaceTypeOpenAIResponse InterfaceType = "openai_responses" // OpenAI Responses (Codex)
    InterfaceTypeAnthropic      InterfaceType = "anthropic"        // Anthropic Messages
)
```

### 3.2 接口类型自动检测

当 `interface_type` 为空时，根据模型名称自动推断：

```go
func fillInterfaceType(model string, interfaceType InterfaceType) InterfaceType {
    if interfaceType != "" {
        return interfaceType  // 显式指定优先
    }
    if strings.Contains(model, "codex") {
        return InterfaceOpenAIResponses
    }
    if strings.Contains(model, "claude") {
        return InterfaceAnthropic
    }
    return InterfaceOpenAIChat  // 默认
}
```

### 3.3 OpenAI Chat (`openai_chat`)

**SDK**: `sashabaranov/go-openai`

**端点**: `{baseURL}/chat/completions`

**请求**:
```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello"}
  ],
  "max_tokens": 4096,
  "temperature": 0.7
}
```

**响应**:
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "model": "gpt-4o",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello! How can I help you?"},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 10,
    "total_tokens": 30
  }
}
```

**LLM Client 映射**:
```go
// ChatRequest → openai.ChatCompletionRequest
messages := []openai.ChatCompletionMessage{}
if req.System != "" {
    messages = append(messages, openai.ChatCompletionMessage{Role: "system", Content: req.System})
}
for _, msg := range req.Messages {
    messages = append(messages, openai.ChatCompletionMessage{Role: msg.Role, Content: msg.Content})
}
```

### 3.4 OpenAI Responses (`openai_responses`)

**SDK**: 原生 HTTP（非 SDK）

**端点**: `{baseURL}/responses`

**请求**:
```json
{
  "model": "codex-mini-latest",
  "input": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello"}
  ],
  "max_output_tokens": 4096,
  "temperature": 0.7
}
```

**响应**:
```json
{
  "id": "resp-xxx",
  "output": [{
    "type": "message",
    "content": [{
      "type": "output_text",
      "text": "Hello! How can I help you?"
    }]
  }],
  "usage": {
    "input_tokens": 20,
    "output_tokens": 10,
    "total_tokens": 30
  },
  "error": null
}
```

**LLM Client 映射**:
```go
// ChatRequest → openAIResponsesRequest
inputs := []openAIResponsesInput{}
if req.System != "" {
    inputs = append(inputs, openAIResponsesInput{Role: "system", Content: req.System})
}
for _, msg := range req.Messages {
    inputs = append(inputs, openAIResponsesInput(msg))
}
requestBody := openAIResponsesRequest{
    Model: req.Model, Input: inputs,
    MaxOutputToken: req.MaxTokens, Temperature: req.Temperature,
}
```

### 3.5 Anthropic (`anthropic`)

**SDK**: `anthropics/anthropic-sdk-go`

**端点**: `{baseURL}/v1/messages`（SDK 自动拼接 `/v1/messages`）

**Base URL 规范化**:
```go
func normalizeAnthropicBaseURL(baseURL string) string {
    baseURL = strings.TrimSuffix(baseURL, "/")
    baseURL = strings.TrimSuffix(baseURL, "/v1")
    return strings.TrimSuffix(baseURL, "/")
}
```

**请求**:
```json
{
  "model": "claude-3-opus-20240229",
  "system": [{"type": "text", "text": "You are a helpful assistant."}],
  "messages": [
    {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
  ],
  "max_tokens": 4096,
  "temperature": 0.7
}
```

**响应**:
```json
{
  "id": "msg-xxx",
  "content": [{"type": "text", "text": "Hello! How can I help you?"}],
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 20,
    "output_tokens": 10
  }
}
```

**LLM Client 映射**:
```go
// ChatRequest → anthropic.MessageNewParams
system := []anthropic.TextBlockParam{}
if req.System != "" {
    system = append(system, anthropic.TextBlockParam{Text: req.System})
}
messages := []anthropic.MessageParam{}
for _, msg := range req.Messages {
    switch msg.Role {
    case "user":
        messages = append(messages, anthropic.NewUserMessage(anthropic.NewTextBlock(msg.Content)))
    case "assistant":
        messages = append(messages, anthropic.NewAssistantMessage(anthropic.NewTextBlock(msg.Content)))
    }
}
params := anthropic.MessageNewParams{
    Model: anthropic.Model(req.Model), Messages: messages, MaxTokens: int64(req.MaxTokens),
}
if req.Temperature != 0 { params.Temperature = anthropic.Float(float64(req.Temperature)) }
if len(system) > 0 { params.System = system }
```

### 3.6 统一 ChatRequest/ChatResponse

```go
type ChatRequest struct {
    Messages      []Message     `json:"messages"`
    Model         string        `json:"model,omitempty"`
    MaxTokens     int           `json:"max_tokens,omitempty"`
    Temperature   float32       `json:"temperature,omitempty"`
    System        string        `json:"system,omitempty"`
    InterfaceType InterfaceType `json:"interface_type,omitempty"`
}

type Message struct {
    Role    string `json:"role"`
    Content string `json:"content"`
}

type ChatResponse struct {
    Content string `json:"content"`
    Usage   Usage  `json:"usage"`
}

type Usage struct {
    PromptTokens     int `json:"prompt_tokens"`
    CompletionTokens int `json:"completion_tokens"`
    TotalTokens      int `json:"total_tokens"`
}
```

### 3.7 默认值

| 参数 | 默认值 | 条件 |
|------|--------|------|
| `interface_type` | `openai_chat` | 未指定时 |
| `temperature` | `0.7` | 为 0 且非 openai_responses 时 |
| `max_tokens` | `1000` | 为 0 时 |
| `model` | Client 配置的 model | 请求中为空时 |

### 3.8 模拟模式

当 `apiKey == ""` 时，LLM Client 返回模拟响应：
```go
return &ChatResponse{
    Content: "这是一个模拟的AI响应。请设置API Key以使用真实的AI服务。",
    Usage:   Usage{},
}, nil
```

---

## 4. 任务生命周期 API

### 4.1 任务状态机

```
pending → processing → finished
                    ↘ error
```

| 状态 | 常量 | 说明 |
|------|------|------|
| `pending` | `TaskStatusPending` | 等待执行 |
| `processing` | `TaskStatusProcessing` | 正在执行 |
| `error` | `TaskStatusError` | 执行出错 |
| `finished` | `TaskStatusFinished` | 执行完成 |

### 4.2 任务类型

| 类型 | 常量 | 说明 |
|------|------|------|
| `develop` | `TaskTypeDevelop` | 开发任务 |
| `design` | `TaskTypeDesign` | 设计任务 |
| `review` | `TaskTypeReview` | 代码审查 |

### 4.3 任务子类型

| 子类型 | 常量 | 说明 |
|--------|------|------|
| `generate_docs` | `TaskSubTypeGenerateDocs` | 生成文档 |
| `generate_requirement` | `TaskSubTypeGenerateRequirement` | 生成需求 |
| `generate_design` | `TaskSubTypeGenerateDesign` | 生成设计 |
| `generate_tasklist` | `TaskSubTypeGenerateTasklist` | 生成任务列表 |
| `execute_task` | `TaskSubTypeExecuteTask` | 执行任务 |
| `pr_review` | `TaskSubTypePrReview` | PR 审查 |

### 4.4 CLI Agent 类型

| 名称 | 常量 | 说明 |
|------|------|------|
| `codex` | `CliNameCodex` | OpenAI Codex |
| `claude` | `CliNameClaude` | Anthropic Claude |
| `opencode` | `CliNameOpencode` | OpenCode |

### 4.5 创建任务

**端点**: `POST /api/v1/users/tasks`

**请求体** (`CreateTaskReq`):
```json
{
  "content": "帮我写一个 Python 快速排序算法",
  "host_id": "public_host",
  "image_id": "550e8400-e29b-41d4-a716-446655440000",
  "model_id": "660e8400-e29b-41d4-a716-446655440000",
  "git_identity_id": "770e8400-e29b-41d4-a716-446655440000",
  "repo": {
    "repo_url": "https://github.com/user/repo.git",
    "branch": "main",
    "repo_filename": "",
    "zip_url": ""
  },
  "cli_name": "claude",
  "resource": {
    "core": 1,
    "memory": 1073741824,
    "life": 3600
  },
  "extra": {
    "project_id": "880e8400-e29b-41d4-a716-446655440000",
    "issue_id": "990e8400-e29b-41d4-a716-446655440000",
    "skill_ids": ["skill-1", "skill-2"]
  },
  "system_prompt": "You are an expert Python developer.",
  "task_type": "develop",
  "sub_type": "execute_task",
  "attachments": [
    {"url": "https://bucket.oss-cn-hangzhou.aliyuncs.com/temp/a.txt", "filename": "a.txt"}
  ]
}
```

**字段说明**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | string | Yes | 用户提示内容 |
| `host_id` | string | Yes | 宿主机 ID（`public_host` 为公共主机） |
| `image_id` | uuid | Yes | VM 镜像 ID |
| `model_id` | string | Yes | 模型配置 ID |
| `git_identity_id` | uuid | No | Git 凭证 ID |
| `repo` | object | Yes | 仓库信息 |
| `cli_name` | string | No | Agent 类型（codex/claude/opencode） |
| `resource` | object | Yes | VM 资源配置 |
| `extra` | object | No | 额外配置（项目/Issue/Skill） |
| `system_prompt` | string | No | 系统提示词 |
| `task_type` | string | No | 任务类型 |
| `sub_type` | string | No | 任务子类型 |
| `attachments` | array | No | 附件列表（最多 10 个） |

**公共主机限制**: `resource.life` 最大 3 小时（10800 秒）

**默认资源**:
```go
if r.Resource == nil {
    r.Resource = &VMResource{
        Core:   1,
        Memory: 1 << 30,  // 1 GB
        Life:   3600,      // 1 小时
    }
}
```

**响应**: 返回 `ProjectTask` 对象

### 4.6 任务列表

**端点**: `GET /api/v1/users/tasks?page=1&size=20&project_id=xxx&status=processing,error`

**响应**:
```json
{
  "code": 0,
  "data": {
    "tasks": [
      {
        "id": "task-uuid",
        "model": {"id": "...", "provider": "OpenAI", "model": "gpt-4o", ...},
        "image": {"id": "...", "name": "Ubuntu 22.04", ...},
        "branch": "main",
        "cli_name": "claude",
        "repo_url": "https://github.com/user/repo.git",
        "full_name": "user/repo",
        "extra": {"project_id": "...", "issue_id": "..."},
        "id": "task-uuid",
        "user_id": "user-uuid",
        "type": "develop",
        "sub_type": "execute_task",
        "content": "帮我写一个快速排序",
        "title": "Quick Sort Implementation",
        "summary": "Implemented quick sort algorithm in Python",
        "status": "finished",
        "log_store": "loki",
        "virtualmachine": {"id": "vm-xxx", "status": "online", ...},
        "created_at": 1715299200,
        "last_active_at": 1715299800,
        "completed_at": 1715300000
      }
    ],
    "page_info": {"page": 1, "size": 20, "total": 100}
  }
}
```

### 4.7 任务详情

**端点**: `GET /api/v1/users/tasks/{id}`

**响应**: 返回完整 `Task` 对象（含 `stats`）

### 4.8 停止任务

**端点**: `PUT /api/v1/users/tasks/stop`

```json
{
  "id": "task-uuid"
}
```

### 4.9 删除任务

**端点**: `DELETE /api/v1/users/tasks/{id}`

限制: 任务处于 `pending`/`processing` 或 VM 仍在线时不允许删除。

### 4.10 更新任务

**端点**: `PUT /api/v1/users/tasks/{id}`

```json
{
  "title": "New Task Title"
}
```

### 4.11 切换任务模型

通过 Task Control WebSocket 发送：

```json
{
  "type": "call",
  "kind": "switch_model",
  "data": "{\"request_id\":\"req-1\",\"model_id\":\"new-model-uuid\",\"load_session\":true}"
}
```

响应:
```json
{
  "type": "call-response",
  "kind": "switch_model",
  "data": "{\"id\":\"switch-uuid\",\"request_id\":\"req-1\",\"success\":true,\"message\":\"\",\"session_id\":\"sess-xxx\",\"model\":{...}}"
}
```

---

## 5. WebSocket 流式协议

### 5.1 Task Stream WebSocket

**端点**: `GET /api/v1/users/tasks/stream?id={taskId}&mode={new|attach}`

**认证**: Cookie `monkeycode_ai_session={session_id}`

**协议**: `coder/websocket`（文本帧，JSON 格式）

**心跳**: 每 10 秒发送 `{"type": "ping"}`

#### 连接模式

| 模式 | 行为 |
|------|------|
| `new` | 等待客户端发送第一条 `user-input`，然后订阅实时流 |
| `attach` | 先回放最新轮次历史 → 发送 cursor → 消费实时流 |

#### 消息格式

```typescript
interface TaskStream {
  type: string       // 消息类型
  data: string       // 消息数据（JSON 字符串或原始文本）
  kind?: string      // 子类型
  timestamp?: number // 毫秒时间戳
}
```

#### 下行消息类型（Server → Client）

| type | kind | 说明 | data 格式 |
|------|------|------|-----------|
| `task-started` | - | 任务轮次开始 | 空 |
| `task-ended` | - | 任务轮次结束 | 空 |
| `task-error` | - | 任务出错 | 错误信息字符串 |
| `task-running` | `acp_event` | ACP 事件 | JSON（见 5.2） |
| `task-running` | `acp_ask_user_question` | Agent 提问 | JSON |
| `task-event` | - | 临时事件（不持久化） | JSON |
| `cursor` | - | 历史分页游标 | `{"cursor": "xxx", "has_more": true}` |
| `ping` | - | 心跳 | 无 |
| `user-input` | - | 用户输入回显（attach 模式回放） | JSON payload |

#### 上行消息类型（Client → Server）

| type | 说明 | data 格式 |
|------|------|-----------|
| `user-input` | 用户输入 | 新格式: `{"content": "base64_text", "attachments": []}` / 旧格式: 纯文本 |
| `user-stop` | 停止任务 | 无 |
| `user-cancel` | 取消当前操作 | 无 |
| `auto-approve` | 开启自动批准 | 无 |
| `disable-auto-approve` | 关闭自动批准 | 无 |
| `reply-question` | 回复 Agent 提问 | `{"request_id": "xxx", "answers_json": "...", "cancelled": false}` |

#### 用户输入格式详解

**新格式（base64 编码，推荐）**:
```json
{
  "type": "user-input",
  "data": "{\"content\":\"5L2g5aW9\",\"attachments\":[{\"url\":\"https://bucket.oss/a.txt\",\"filename\":\"a.txt\"}]}",
  "timestamp": 1715299200000
}
```
其中 `content` 为用户输入文本的 base64 编码。

**旧格式（纯文本，仍兼容）**:
```json
{
  "type": "user-input",
  "data": "你好世界"
}
```

**存储格式（统一）**:
```json
{
  "encoding": "plaintext",
  "content": "你好世界",
  "attachments": []
}
```

后端 `parseUserInputData()` 按以下优先级解析：
1. `{"encoding": "plaintext", "content": "...", "attachments": [...]}` — 存储格式
2. `{"content": [base64 bytes], "attachments": [...]}` — 新上行格式
3. 纯文本 — 旧格式兼容

#### Cursor 消息

attach 模式下，回放历史后发送：
```json
{
  "type": "cursor",
  "data": "{\"cursor\":\"next-page-cursor\",\"has_more\":true}",
  "timestamp": 1715299200000
}
```

客户端可通过 `GET /api/v1/users/tasks/rounds?id={taskId}&cursor={cursor}&limit=2` 向前翻页加载更早的轮次。

### 5.2 ACP 事件格式

当 `type: "task-running"` 且 `kind: "acp_event"` 时，`data` 字段为 ACP SessionUpdate 的 JSON 字符串。

```typescript
interface ACPSessionUpdate {
  type: string  // 事件子类型
  text?: string // 文本内容（message/thought chunk）
  content?: string // 备用文本字段
  // usage_update 特有
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  // tool_call 特有
  tool_name?: string
  tool_input?: string
  // 其他字段
  [key: string]: unknown
}
```

| ACP 事件类型 | 说明 | 关键字段 |
|-------------|------|---------|
| `agent_message_chunk` | Agent 输出文本流式块 | `text` / `content` |
| `agent_thought_chunk` | Agent 内部推理流式块 | `text` / `content` |
| `tool_call` | 工具调用开始 | `tool_name`, `tool_input` |
| `tool_call_update` | 工具调用状态更新 | - |
| `available_commands_update` | 可用命令更新 | - |
| `plan` | 执行计划 | 含步骤状态 |
| `usage_update` | Token 使用量更新 | `input_tokens`, `output_tokens`, `total_tokens` |

### 5.3 Task Control WebSocket

**端点**: `GET /api/v1/users/tasks/control?id={taskId}`

**特性**: 长连接，任务完成后仍保持，支持多标签页并发连接

**心跳**: 每 10 秒 `{"type": "ping"}`

**VM 保活**: 每 1 分钟刷新 VM 空闲计时器

#### 上行 Call 消息

| kind | 说明 | data 格式 |
|------|------|-----------|
| `repo_file_list` | 列出目录文件 | `{"request_id":"r1","path":"/workspace","glob_pattern":"*.go","include_hidden":false}` |
| `repo_file_diff` | 获取文件 diff | `{"request_id":"r1","path":"/workspace/main.go","unified":true,"context_lines":3}` |
| `repo_read_file` | 读取文件内容 | `{"request_id":"r1","path":"/workspace/main.go","offset":0,"length":1024}` |
| `repo_file_changes` | 变更文件列表 | `{"request_id":"r1"}` |
| `port_forward_list` | 端口转发列表 | `{"request_id":"r1"}` |
| `restart` | 重启任务 | `{"request_id":"r1","load_session":true}` |
| `switch_model` | 切换模型 | `{"request_id":"r1","model_id":"uuid","load_session":true}` |

#### 下行消息

| type | 说明 |
|------|------|
| `call-response` | RPC 响应（kind 与请求一致，含 `request_id` 匹配） |
| `task-event` | 任务事件转发（从 TaskLive 订阅） |
| `ping` | 心跳 |

#### Call-Response 错误格式

```json
{
  "type": "call-response",
  "kind": "repo_read_file",
  "data": "{\"request_id\":\"r1\",\"success\":false,\"error\":\"file not found\"}",
  "timestamp": 1715299200000
}
```

### 5.4 历史轮次查询

**端点**: `GET /api/v1/users/tasks/rounds?id={taskId}&cursor={cursor}&limit=2`

**响应**:
```json
{
  "code": 0,
  "data": {
    "chunks": [
      {
        "data": "{\"content\":\"5L2g5aW9\",\"attachments\":[]}",
        "event": "user-input",
        "kind": "",
        "timestamp": 1715299200000,
        "labels": null
      },
      {
        "data": "{\"type\":\"agent_message_chunk\",\"text\":\"Hello!\"}",
        "event": "task-running",
        "kind": "acp_event",
        "timestamp": 1715299201000,
        "labels": null
      }
    ],
    "next_cursor": "older-cursor",
    "has_more": true
  }
}
```

- `limit` 为轮次数（默认 2，上限 10）
- chunks 按时间倒序（最新在前）
- `user-input.data` 统一为 JSON payload 格式

---

## 6. VM 管理相关 API

### 6.1 创建 VM

**端点**: `POST /api/v1/users/hosts/vms`

**请求** (`CreateVMReq`):
```json
{
  "host_id": "public_host",
  "name": "My VM",
  "image_id": "550e8400-e29b-41d4-a716-446655440000",
  "model_id": "660e8400-e29b-41d4-a716-446655440000",
  "life": 3600,
  "resource": {"cpu": 1, "memory": 1073741824},
  "install_coding_agents": true,
  "repo": {
    "repo_url": "https://github.com/user/repo.git",
    "branch": "main",
    "repo_filename": "",
    "zip_url": ""
  },
  "git_identity_id": "770e8400-e29b-41d4-a716-446655440000"
}
```

### 6.2 VM 状态

| 状态 | 说明 |
|------|------|
| `unknown` | 未知 |
| `pending` | 创建中 |
| `online` | 运行中 |
| `offline` | 已停止 |
| `hibernated` | 休眠（Control WebSocket 连接时自动恢复） |

### 6.3 TaskFlow CreateVirtualMachineReq

Backend 向 TaskFlow 服务发送的 VM 创建请求：

```go
type CreateVirtualMachineReq struct {
    UserID              string         `json:"user_id"`
    HostID              string         `json:"host_id"`
    HostName            string         `json:"hostname"`
    Git                 Git            `json:"git"`
    ZipUrl              string         `json:"zip_url"`
    ImageURL            string         `json:"image_url"`
    ProxyURL            string         `json:"proxy_url"`
    TaskID              uuid.UUID      `json:"task_id"`
    LLM                 LLMProviderReq `json:"llm"`
    Cores               string         `json:"cores"`
    Memory              uint64         `json:"memory"`
    InstallCodingAgents bool           `json:"install_coding_agents"`
    Envs                []string       `json:"envs,omitempty"`
    LogStore            string         `json:"log_store,omitempty"`
}

type LLMProviderReq struct {
    Provider    LLMProvider `json:"provider"`     // 固定 "openai"
    ApiKey      string      `json:"api_key"`
    BaseURL     string      `json:"base_url"`
    Model       string      `json:"model"`
    Temperature *float32    `json:"temperature,omitempty"`
}
```

**注意**: TaskFlow 的 `LLMProviderReq.Provider` 固定为 `"openai"`，实际接口类型由 Agent 在 VM 内部根据模型名称自动推断。

---

## 7. WebSocket 实现细节

### 7.1 底层库

```go
import "github.com/coder/websocket"
```

### 7.2 WebsocketManager

```go
type WebsocketManager struct {
    conn   *websocket.Conn
    ip     string        // X-Real-IP header
    realIP string        // 浏览器上报的真实 IP
    mu     sync.Mutex    // 并发写保护
}
```

- 写操作通过 `mu sync.Mutex` 串行化
- 所有消息均为文本帧（JSON）
- `InsecureSkipVerify: true`（跳过 Origin 校验）

### 7.3 连接池

**TaskConn**: 一对一映射（taskID → 单个 WebSocket 连接）

**ControlConn**: 一对多映射（taskID → 多个并发连接，支持多标签页）

---

## 8. 反向代理 LLM 转发完整流程

### 8.1 非流式请求（chat/completions）

```
OpenAI Client → Proxy → MonkeyCode Backend
                       1. POST /api/v1/users/tasks (创建任务)
                       2. WS  /api/v1/users/tasks/stream?id={taskId}&mode=new
                       3. 发送 user-input
                       4. 接收 ACP 事件流
                       5. 转换为 OpenAI ChatCompletion 响应
                       6. PUT /api/v1/users/tasks/stop (停止任务)
```

### 8.2 流式请求（chat/completions with stream=true）

```
OpenAI Client ←SSE← Proxy ←WS← MonkeyCode Backend
                       1. POST /api/v1/users/tasks (创建任务)
                       2. WS  /api/v1/users/tasks/stream?id={taskId}&mode=new
                       3. 发送 user-input
                       4. 循环接收 ACP 事件:
                          - agent_message_chunk → SSE delta content
                          - agent_thought_chunk → SSE delta [Thinking] content
                          - usage_update → 记录 token 用量
                          - task-ended → SSE finish_reason: stop + usage
                          - task-error → SSE delta [Error] content
                       5. 关闭 SSE 流
```

### 8.3 ACP → OpenAI SSE 转换规则

| ACP 事件 | OpenAI SSE Chunk |
|----------|-----------------|
| `agent_message_chunk` (text) | `delta: {content: text}, finish_reason: null` |
| `agent_thought_chunk` (text) | `delta: {content: "[Thinking] " + text}, finish_reason: null` |
| `usage_update` | 记录，不单独发送 |
| `task-ended` | `delta: {}, finish_reason: "stop"` + 累积 usage |
| `task-error` | `delta: {content: "[Error] " + data}, finish_reason: null` |

### 8.4 模型 ID 映射

Proxy 使用 `monkeycode/{provider}/{model}` 格式作为 OpenAI 兼容的模型 ID：

```typescript
toOpenAIModelId(m: MonkeyCodeModel): string {
    return `monkeycode/${m.provider}/${m.model}`
}
// 例: monkeycode/OpenAI/gpt-4o, monkeycode/DeepSeek/deepseek-chat
```

解析时按优先级匹配：
1. 精确匹配 `monkeycode/provider/model`
2. 匹配 `provider/model`
3. 模糊匹配 `model` 名称
4. 匹配 `display_name`
5. 返回默认模型

---

## 9. 语音识别 API

**端点**: `POST /api/v1/users/tasks/speech-to-text`

**请求**: 二进制音频数据（`application/octet-stream`）

**响应**: Server-Sent Events 流

```
event: recognition
data: {"type":"result","text":"你好","is_final":false,"user_id":"uuid","timestamp":1715299200000}

event: recognition
data: {"type":"result","text":"你好世界","is_final":true,"user_id":"uuid","timestamp":1715299210000}

event: end
data: {"type":"end"}

event: error
data: {"type":"error","error":"识别失败"}
```

超时: 2 分钟

---

## 10. 与现有代理实现的差异分析

### 10.1 CreateTaskReq 差异

| 字段 | 代理实现 | 实际后端 |
|------|---------|---------|
| `vm_id` | 直接传 VM ID | `host_id`（宿主机 ID） |
| `llm` | `{api_key, base_url, model, api_type, temperature}` | `model_id`（模型配置 UUID） |
| `coding_agent` | 数字枚举 | `cli_name`（字符串枚举） |
| `prompt` | 用户提示 | `content`（用户提示） |
| `working_dir` | 工作目录 | 无（由 VM 决定） |
| - | 无 | `image_id`, `repo`, `resource`, `extra`, `system_prompt`, `task_type`, `sub_type`, `attachments` |

**关键差异**: 代理实现使用 `llm` 对象直接传递 API 配置，而实际后端使用 `model_id` 引用已配置的模型。后端会根据 `model_id` 查找数据库中的模型配置（含 API Key、Base URL、Interface Type 等），然后传给 TaskFlow 创建 VM。

### 10.2 认证 Cookie 名称

| 代理实现 | 实际后端 |
|---------|---------|
| `monkeycode_ai_session` | `monkeycode_ai_session` |

> 注：之前文档错误地记录为 `sl-session`，实际后端 Cookie 名称硬编码为 `monkeycode_ai_session`（见 `consts/auth.go`），线上环境不会覆盖。

### 10.3 WebSocket 认证

代理实现通过 `headers: { Cookie: "monkeycode_ai_session=xxx" }` 传递认证，实际后端通过 `coder/websocket` 的 `Accept()` 从 HTTP 请求中读取 Cookie。

---

## 11. 完整请求/响应示例

### 11.1 创建任务并获取流式输出

```bash
# 1. 登录获取 session cookie
curl -c cookies.txt -X POST https://monkeycode-ai.com/api/v1/teams/users/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"plain_password"}'

# 2. 获取可用模型
curl -b cookies.txt https://monkeycode-ai.com/api/v1/users/models | jq .

# 3. 创建任务
TASK=$(curl -b cookies.txt -X POST https://monkeycode-ai.com/api/v1/users/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Write a hello world in Python",
    "host_id": "public_host",
    "image_id": "image-uuid",
    "model_id": "model-uuid",
    "cli_name": "claude",
    "resource": {"core": 1, "memory": 1073741824, "life": 3600},
    "repo": {"repo_url": "", "branch": "master", "repo_filename": "", "zip_url": ""}
  }')
TASK_ID=$(echo $TASK | jq -r '.data.id')

# 4. 连接 WebSocket 流
wscat -c "wss://monkeycode-ai.com/api/v1/users/tasks/stream?id=$TASK_ID&mode=new" \
  -H "Cookie: monkeycode_ai_session=$(cat cookies.txt | grep monkeycode_ai_session | awk '{print $NF}')"

# 5. 发送用户输入（WebSocket 文本帧）
{"type":"user-input","data":"{\"content\":\"53687269746520612068656c6c6f20776f726c6420696e20507974686f6e\",\"attachments\":[]}"}

# 6. 接收流式输出（WebSocket 文本帧）
{"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_message_chunk\",\"text\":\"Here\"}","timestamp":1715299201000}
{"type":"task-running","kind":"acp_event","data":"{\"type\":\"agent_message_chunk\",\"text\":\" is\"}","timestamp":1715299201100}
{"type":"task-ended","data":"","timestamp":1715299300000}
```

### 11.2 通过代理的 OpenAI 兼容请求

```bash
# 非流式
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer monkeycode-session-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/OpenAI/gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "temperature": 0.7
  }'

# 流式
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer monkeycode-session-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "monkeycode/DeepSeek/deepseek-chat",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```
