---
description: LLM 集成协议详解 — Client 架构、接口类型自动检测、SDK 调用链
protocol_version: based on chaitin/MonkeyCode 开源后端源码
confidence: high
last_verified: 2026-06-27
---

# LLM 集成协议详解

> **状态:** ✅ 集成协议完整已知

## Client 架构

MonkeyCode 的 LLM Client 是一个 Go SDK（`backend/pkg/llm/client.go`），支持三种接口类型，根据模型配置自动选择。

```go
// backend/pkg/llm/client.go — 核心 Client 结构体
type Client struct {
    provider    LLMProvider      // 提供商枚举
    apiKey      string           // API Key
    baseURL     string           // API 地址
    model       string           // 模型名称
    httpClient  *http.Client     // HTTP 客户端（可配置超时）
}

// 支持的提供商枚举
type LLMProvider string
const (
    ProviderOpenAI      LLMProvider = "openai"
    ProviderAnthropic   LLMProvider = "anthropic"
    ProviderDeepSeek    LLMProvider = "deepseek"
    ProviderSiliconFlow LLMProvider = "siliconflow"
    // ... 共 11 个
)

// 三种调用方法 — 根据接口类型自动选择
func (c *Client) ChatCompletion(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
    // 用于 openai_chat 类型
    // 调用 openai SDK: github.com/sashabaranov/go-openai
}

func (c *Client) Responses(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
    // 用于 openai_responses 类型
    // 原生 HTTP 调用 OpenAI Responses API
}

func (c *Client) Messages(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
    // 用于 anthropic 类型
    // 调用 anthropic SDK: github.com/anthropics/anthropic-sdk-go
}
```

## SDK 选择

```go
// backend/pkg/llm/client.go — SDK 选择逻辑
import (
    openai "github.com/sashabaranov/go-openai"           // OpenAI SDK
    anthropic "github.com/anthropics/anthropic-sdk-go"   // Anthropic SDK
)

func NewClient(config *LLMConfig) *Client {
    switch config.InterfaceType {
    case InterfaceOpenAIChat:
        // 使用 go-openai SDK
        c := openai.NewClient(config.APIKey)
        if config.BaseURL != "" {
            c.BaseURL = config.BaseURL
        }
        return &Client{provider: ProviderOpenAI, ...}
        
    case InterfaceAnthropic:
        // 使用 anthropic-sdk-go
        c := anthropic.NewClient(config.APIKey)
        return &Client{provider: ProviderAnthropic, ...}
    }
}
```

### 接口类型自动检测

```go
type InterfaceType string
const (
    InterfaceOpenAIChat      InterfaceType = "openai_chat"
    InterfaceOpenAIResponses InterfaceType = "openai_responses"
    InterfaceAnthropic       InterfaceType = "anthropic"
)
```

接口类型存储在模型配置的 `interface_type` 字段中，Agent 根据此字段选择对应的调用接口。

### ChatRequest 统一格式

```go
// 统一请求格式，适配三种接口类型
type ChatRequest struct {
    Messages      []Message     `json:"messages"`
    Model         string        `json:"model,omitempty"`
    MaxTokens     int           `json:"max_tokens,omitempty"`
    Temperature   float32       `json:"temperature,omitempty"`
    System        string        `json:"system,omitempty"`
    InterfaceType InterfaceType `json:"interface_type,omitempty"`
}

type Message struct {
    Role    string `json:"role"`    // "system" | "user" | "assistant"
    Content string `json:"content"` // 消息内容
}

type ChatResponse struct {
    Content string `json:"content"` // 响应文本
    Usage   Usage  `json:"usage"`   // Token 用量
}
```

### 实际调用链

```
Agent (VM 内)
  │
  ├── @ai-sdk/openai-compatible.generateText()
  │     │
  │     └── HTTP POST → MonkeyCode 后端的 LLM Proxy
  │           │
  │           ├── backend/pkg/llm/client.go
  │           │     ├── Detect InterfaceType (从模型配置)
  │           │     ├── NewClient(config) → 选择 SDK
  │           │     └── client.ChatCompletion(ctx, req)
  │           │           │
  │           │           └── go-openai SDK → Provider API
  │           │                 ├── OpenAI: api.openai.com
  │           │                 ├── DeepSeek: api.deepseek.com
  │           │                 └── 等等
  │           │
  │           └── 流式响应返回 SSE → Agent
  │
  └── ACP 事件 → TaskLive WS → Task Stream WS → 前端
```

## 错误处理

所有 LLM 错误被包装为中文描述：

```go
// backend/pkg/llm/client.go — 错误包装
func ChatNoException(err error) string {
    return fmt.Sprintf("模型调用失败: %v", err)
}

// 实际的错误处理链
func (c *Client) ChatCompletion(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
    resp, err := c.openaiClient.CreateChatCompletion(ctx, openaiReq)
    if err != nil {
        // 包装错误，返回友好消息
        return nil, fmt.Errorf("模型调用失败: %w", err)
    }
    return &ChatResponse{
        Content: resp.Choices[0].Message.Content,
        Usage:   Usage{
            PromptTokens:     resp.Usage.PromptTokens,
            CompletionTokens: resp.Usage.CompletionTokens,
            TotalTokens:      resp.Usage.TotalTokens,
        },
    }, nil
}
```

## 模拟模式

当 `apiKey == ""` 时返回模拟响应，用于开发/测试环境：

```go
func (c *Client) ChatCompletion(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
    // 模拟模式：没有 API Key 时返回 mock 数据
    if c.apiKey == "" {
        return &ChatResponse{
            Content: "这是模拟响应（没有配置 API Key）",
            Usage:   Usage{PromptTokens: 0, CompletionTokens: 0, TotalTokens: 0},
        }, nil
    }
    // 正常调用
}
```

---

## 附录：逆向分析代码示例

### 附录 A: Go SDK 调用测试 (Python 模拟)
```python
# 模拟 MonkeyCode 后端的 LLM Client 调用逻辑
import httpx
from typing import Literal

InterfaceType = Literal["openai_chat", "openai_responses", "anthropic"]

class LLMClient:
    """模拟 chaitin/MonkeyCode 的 LLM Client"""
    
    def __init__(self, provider: str, api_key: str, base_url: str, model: str):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
    
    def chat_completion(self, messages: list, interface_type: InterfaceType):
        """根据接口类型自动选择调用方式"""
        if interface_type == "openai_chat":
            return self._call_openai_chat(messages)
        elif interface_type == "openai_responses":
            return self._call_openai_responses(messages)
        elif interface_type == "anthropic":
            return self._call_anthropic(messages)
    
    def _call_openai_chat(self, messages: list):
        """调用 OpenAI Chat Completion API"""
        import openai
        client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return resp.choices[0].message.content

# 使用示例
client = LLMClient(
    provider="deepseek",
    api_key="sk-xxx",
    base_url="https://api.deepseek.com",
    model="deepseek-chat"
)
result = client.chat_completion(
    messages=[{"role": "user", "content": "Hello"}],
    interface_type="openai_chat"
)
```

### 附录 B: Go 源码 client.go 核心逻辑
```go
// chaitin/MonkeyCode — backend/pkg/llm/client.go
// 完整 Client 调用链（基于源码重构）

func (c *Client) ChatCompletion(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
    openaiReq := openai.ChatCompletionRequest{
        Model: c.model,
        Messages: convertMessages(req.Messages),
        MaxTokens: req.MaxTokens,
        Temperature: req.Temperature,
    }
    
    if req.System != "" {
        openaiReq.Messages = append(
            []openai.ChatCompletionMessage{
                {Role: "system", Content: req.System},
            },
            openaiReq.Messages...,
        )
    }
    
    resp, err := c.openaiClient.CreateChatCompletionStreaming(ctx, openaiReq)
    if err != nil {
        return nil, ChatNoException(err)
    }
    defer resp.Close()
    
    // 累积流式响应
    var fullContent strings.Builder
    var usage Usage
    
    for {
        chunk, err := resp.Recv()
        if err != nil {
            break
        }
        fullContent.WriteString(chunk.Choices[0].Delta.Content)
        if chunk.Usage != nil {
            usage = Usage{
                PromptTokens:     chunk.Usage.PromptTokens,
                CompletionTokens: chunk.Usage.CompletionTokens,
                TotalTokens:      chunk.Usage.TotalTokens,
            }
        }
    }
    
    return &ChatResponse{
        Content: fullContent.String(),
        Usage:   usage,
    }, nil
}
```

---

## 相关章节

- [11 个模型提供商配置](03-provider-list.md) — 各提供商配置
- [模型管理 API](01-model-management-api.md) — 模型 CRUD
- [LLM 接口类型](02-interface-types.md) — 三种接口的详细对比