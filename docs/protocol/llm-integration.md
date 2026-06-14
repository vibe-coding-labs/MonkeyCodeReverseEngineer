# MonkeyCode LLM 集成协议详解

## 概述

MonkeyCode 后端通过统一的 LLM Client 支持 3 种 API 接口类型，11 个模型提供商。

## LLM Client 架构

```go
// backend/pkg/llm/client.go
type Client struct {
    openaiClient    *openai.Client          // sashabaranov/go-openai SDK
    anthropicClient *anthropic.Client       // anthropics/anthropic-sdk-go SDK
    httpClient      *http.Client            // raw HTTP for OpenAI Responses
    baseURL         string
    apiKey          string
    model           string
    interfaceType   InterfaceType
}
```

## 三种接口类型

### 1. OpenAI Chat (`openai_chat`)

**协议**: OpenAI Chat Completions API

**端点**: `{baseURL}/chat/completions`

**请求格式**:
```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "max_tokens": 4096,
  "temperature": 0.7,
  "stream": false
}
```

**响应格式**:
```json
{
  "id": "chatcmpl-xxx",
  "choices": [{
    "message": {"role": "assistant", "content": "..."},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150
  }
}
```

**流式响应**: `stream: true` 时返回 SSE 格式

### 2. OpenAI Responses (`openai_responses`)

**协议**: OpenAI Responses API（Codex 风格）

**端点**: `{baseURL}/responses`

**请求格式**:
```json
{
  "model": "codex-mini-latest",
  "input": [
    {"role": "user", "content": "..."}
  ],
  "max_output_tokens": 4096,
  "temperature": 0.7
}
```

**响应格式**:
```json
{
  "output": [{
    "type": "message",
    "content": [{
      "type": "output_text",
      "text": "..."
    }]
  }],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50,
    "total_tokens": 150
  }
}
```

### 3. Anthropic (`anthropic`)

**协议**: Anthropic Messages API

**端点**: `{baseURL}/v1/messages`（注意：baseURL 不含 `/v1`）

**请求格式**:
```json
{
  "model": "claude-3-opus-20240229",
  "system": "system prompt here",
  "messages": [
    {"role": "user", "content": "..."}
  ],
  "max_tokens": 4096,
  "temperature": 0.7
}
```

**响应格式**:
```json
{
  "content": [{
    "type": "text",
    "text": "..."
  }],
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50
  }
}
```

**Base URL 规范化**: 自动去除尾部 `/`、`/v1`、`/`

## 接口类型自动检测

```go
func fillInterfaceType(model string) InterfaceType {
    if strings.Contains(model, "codex") {
        return InterfaceOpenAIResponses
    }
    if strings.Contains(model, "claude") {
        return InterfaceAnthropic
    }
    return InterfaceOpenAIChat
}
```

## 模型提供商

| Provider | 常量值 | 默认 Base URL |
|----------|--------|---------------|
| SiliconFlow | `SiliconFlow` | https://api.siliconflow.cn/v1 |
| OpenAI | `OpenAI` | https://api.openai.com/v1 |
| Ollama | `Ollama` | http://localhost:11434/v1 |
| DeepSeek | `DeepSeek` | https://api.deepseek.com/v1 |
| Moonshot | `Moonshot` | https://api.moonshot.cn/v1 |
| AzureOpenAI | `AzureOpenAI` | {azure_endpoint}/openai |
| BaiZhiCloud | `BaiZhiCloud` | https://api.baizhicloud.com/v1 |
| Hunyuan | `Hunyuan` | https://api.hunyuan.tencent.com/v1 |
| BaiLian | `BaiLian` | https://api.bailian.com/v1 |
| Volcengine | `Volcengine` | https://api.volcengine.com/v1 |
| Gemini | `Gemini` | https://generativelanguage.googleapis.com/v1beta |
| Other | `Other` | 用户自定义 |

## 健康检查协议

```go
func HealthCheck(ctx context.Context, cfg Config) error {
    // 30s timeout
    // 发送最小请求 ("hi", max_tokens: 1)
    // 验证 HTTP 200-299 且无 error 对象
}
```

- OpenAI Chat: POST `{baseURL}/chat/completions`
- OpenAI Responses: POST `{baseURL}/responses`
- Anthropic: 使用 SDK `Messages.New()`

## 模型访问层级

| AccessLevel | 说明 | 可用模型 |
|-------------|------|---------|
| `basic` | 基础订阅（默认注册用户） | monkeycode-basic (`qwen3.5-plus`) + 免费模型 (is_free=true) |
| `pro` | 专业订阅 | monkeycode-pro (`kimi-k2.6`) + basic 模型 |
| `ultra` | 高级订阅 | monkeycode-ultra (`gpt-5.5`) + 所有模型 |

## SubscriptionResp 结构体（从 `backend/domain/user.go` 源码确认）

```go
type SubscriptionResp struct {
    Plan      string     `json:"plan"`
    Source    string     `json:"source,omitempty"`
    ExpiresAt *time.Time `json:"expires_at,omitempty"`
    AutoRenew bool       `json:"auto_renew"`
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `plan` | string | 订阅套餐名称（`basic`/`pro`/`ultra`） |
| `source` | string | 订阅来源（`stripe`/`wechat`/`free`） |
| `expires_at` | *time.Time | 到期时间，null=永久 |
| `auto_renew` | bool | 是否自动续费 |

> **注意:** `User` 实体不包含 `subscription_level` 或 `balance` 字段。订阅信息通过独立 API 获取。 |

## Public Model API Key 机制

```go
const PublicModelKeyPrefix = "public:model:"

func PublicModelKey(modelID string) string {
    return PublicModelKeyPrefix + modelID
}
```

- 管理员创建公开模型时 API Key 设为 `public:model:{model_id}`
- 用户使用公开模型时，后端自动替换为实际 Provider API Key
- `HideSharedCredentials()` 方法隐藏非私有模型的 API Key

## 模拟模式

当 `apiKey == ""` 时，LLM Client 返回模拟响应：
``"This is a simulated AI response. Please set API Key to use real AI service."``

## 反向代理 LLM 转发策略

反向代理需要处理两种场景：

### 场景 A: 直接使用 Public Model（通过 MonkeyCode 后端）

1. 获取 Public Model 列表
2. 使用 MonkeyCode Session Cookie 调用后端 API
3. 后端自动替换 `public:model:` API Key 为实际 Key
4. 后端转发请求到 LLM Provider

### 场景 B: 直接调用 LLM Provider（获取实际 API Key）

1. 通过某种方式获取实际 API Key（需要管理员权限或抓包）
2. 直接调用 LLM Provider 的 API
3. 无需经过 MonkeyCode 后端

**推荐方案**: 场景 A，通过 MonkeyCode 后端转发，利用 Public Model 机制。