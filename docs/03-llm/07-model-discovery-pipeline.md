---
description: Model Discovery Pipeline 全景分析 — 6 层回退解析、5 分钟缓存、monkeycode/provider/model 格式设计
protocol_version: based on proxy/src/models.ts (102L) + types.ts + task-runner.ts
confidence: high
last_verified: 2026-06-28
---

# Model Discovery Pipeline 全景

> **核心源码:** `proxy/src/models.ts` (102L)
> **关联文件:** `proxy/src/types.ts` (MonkeyCodeModel 类型), `proxy/src/task-runner.ts` (cli_name 选择)
> **覆盖:** 模型发现 → 缓存 → 6 层解析 → 接口类型映射 → 全链路追踪

---

## 1. ModelManager 架构总览

### 类设计

```typescript
// 摘自 proxy/src/models.ts — ModelManager 完整类
export class ModelManager {
  private auth: AuthManager      // 认证管理器
  private models: MonkeyCodeModel[] = []  // 模型缓存
  private lastFetch: number = 0  // 上次获取时间
  private cacheTTL: number = 5 * 60 * 1000  // 5 分钟缓存

  constructor(auth: AuthManager) {
    this.auth = auth
  }
}
```

### 数据流全链路

```
用户请求 (OpenAI SDK/curl)
  │
  ▼ POST /v1/chat/completions { model: "gpt-4" }
  │
  ▼ api-routes.ts: resolveModel("gpt-4")
  │
  ┌─────────────────────────────────────────────────────┐
  │  ModelManager.resolveModel()                        │
  │                                                     │
  │  第 1 层: 精确匹配 monkeycode/provider/model 格式    │
  │  第 2 层: 匹配 provider/model 格式                   │
  │  第 3 层: 匹配 model 名称                             │
  │  第 4 层: 匹配 display_name                           │
  │  第 5 层: 返回 is_default 模型                        │
  │  第 6 层: 返回 models[0] (兜底)                      │
  └─────────────────────┬───────────────────────────────┘
                        │
                        ▼ MonkeyCodeModel { id, provider, model, interface_type, ... }
                        │
                        ▼ task-runner.ts: createTask()
                        │
                        ▼ POST /api/v1/users/tasks { model_id: model.id, cli_name: ... }
```

---

## 2. 模型发现 (fetchModels)

### API 调用

```typescript
// 摘自 proxy/src/models.ts:20-42 — 获取模型列表
async fetchModels(): Promise<MonkeyCodeModel[]> {
  // 缓存命中: 直接返回
  if (this.models.length > 0 && Date.now() - this.lastFetch < this.cacheTTL) {
    return this.models
  }

  const url = `${MONKEYCODE_BASE_URL}/api/v1/users/models`

  const response = await fetch(url, {
    headers: mkHeaders({
      Cookie: `${this.auth.getSessionCookieName()}=${this.auth.getSessionCookieSync()}`,
    }),
  })
  if (!response.ok) {
    throw new Error(`Failed to fetch models (${response.status}): ${await response.text()}`)
  }

  const result = await response.json()
  // 兼容两种响应格式:
  // 格式 A: { code: 0, data: { models: [...] } }
  // 格式 B: { models: [...] }
  const data = result.data || result
  this.models = data.models || []
  this.lastFetch = Date.now()

  console.log(`[Models] Fetched ${this.models.length} models`)
  return this.models
}
```

### 响应格式示例

```json
// 格式 A (code + data 包装)
{
  "code": 0,
  "data": {
    "models": [
      {
        "id": "uuid-xxx",
        "provider": "openai",
        "model": "gpt-4o",
        "display_name": "GPT-4o",
        "interface_type": "openai_chat",
        "is_default": true,
        "is_free": false,
        "access_level": "pro",
        "thinking_enabled": false,
        "context_limit": 128000,
        "output_limit": 4096,
        "owner": "public",
        "name": "GPT-4o",
        "description": "OpenAI GPT-4o",
        "api_key": "sk-...",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.7
      }
    ]
  }
}

// 格式 B (直接 models 数组)
{
  "models": [...]
}
```

---

## 3. 6 层模型解析回退

### 核心解析方法

```typescript
// 摘自 proxy/src/models.ts:64-88 — 6 层回退解析
async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
  const models = await this.fetchModels()

  // 第 1 层: 精确匹配 monkeycode/provider/model 格式
  // 示例: "monkeycode/openai/gpt-4o"
  const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
  if (exact) return exact

  // 第 2 层: 匹配 provider/model 格式
  // 示例: "openai/gpt-4o"
  const byProviderModel = models.find(
    (m) => `${m.provider}/${m.model}` === openaiModelId
  )
  if (byProviderModel) return byProviderModel

  // 第 3 层: 模糊匹配 model 名称
  // 示例: "gpt-4o" (不区分 provider)
  const byModelName = models.find((m) => m.model === openaiModelId)
  if (byModelName) return byModelName

  // 第 4 层: 匹配 display_name
  // 示例: "GPT-4o" (用户友好的显示名称)
  const byDisplayName = models.find((m) => m.display_name === openaiModelId)
  if (byDisplayName) return byDisplayName

  // 第 5 层: 默认模型
  // 返回 is_default=true 的模型
  const defaultModel = models.find((m) => m.is_default)
  if (defaultModel) return defaultModel

  // 第 6 层: 兜底 — 返回第一个可用模型
  return models[0] || null
}
```

### 解析层对比

| 层 | 输入格式 | 匹配方式 | 用途 | 示例 |
|---|---------|---------|------|------|
| 1 | `monkeycode/{provider}/{model}` | 精确字符串 | OpenAI SDK 标准格式 | `monkeycode/openai/gpt-4o` |
| 2 | `{provider}/{model}` | 精确字符串 | 简洁格式 | `openai/gpt-4o` |
| 3 | `{model}` | 精确字符串 | 不关心 provider | `gpt-4o` |
| 4 | `{display_name}` | 精确字符串 | 用户友好名称 | `GPT-4o` |
| 5 | — | `is_default` 标志 | 默认模型 | 平台配置的默认值 |
| 6 | — | 数组第一个 | 兜底 | 任何可用模型 |

### 模型 ID 生成

```typescript
// 摘自 proxy/src/models.ts:58-59 — OpenAI 兼容模型 ID 格式
toOpenAIModelId(m: MonkeyCodeModel): string {
  // 格式: monkeycode/{provider}/{model}
  // 示例: monkeycode/openai/gpt-4o
  //        monkeycode/anthropic/claude-3-opus-20240229
  //        monkeycode/deepseek/deepseek-coder
  return `monkeycode/${m.provider}/${m.model}`
}
```

---

## 4. 缓存策略

### 5 分钟缓存

```typescript
// 摘自 proxy/src/models.ts — 缓存
private models: MonkeyCodeModel[] = []
private lastFetch: number = 0
private cacheTTL: number = 5 * 60 * 1000  // 5 分钟

async fetchModels(): Promise<MonkeyCodeModel[]> {
  // 缓存有效期内直接返回
  if (this.models.length > 0 && Date.now() - this.lastFetch < this.cacheTTL) {
    return this.models
  }
  // 缓存过期 → 重新获取
  // ...
}

// 清除缓存
clearCache(): void {
  this.models = []
  this.lastFetch = 0
}
```

### 缓存刷新方式

```typescript
// 方式 1: 自动过期（5 分钟 TTL）
// 每次 fetchModels() 自动检查

// 方式 2: 手动刷新（管理端点）
// 摘自 proxy/src/server.ts:136-143
app.post("/admin/refresh-models", async (_req, res) => {
  try {
    modelManager.clearCache()       // 清除缓存
    const models = await modelManager.fetchModels()  // 重新获取
    res.json({ status: "ok", count: models.length })
  } catch (err: any) {
    res.status(500).json({ error: err.message })
  }
})

// 方式 3: OAuth 登录成功后自动刷新
// 摘自 proxy/src/server.ts:211-215
app.post("/admin/login/verify", async (req, res) => {
  // 登录成功后清除缓存 + 重新获取
  modelManager.clearCache()
  await modelManager.fetchModels()
})
```

---

## 5. 接口类型映射

### interface_type → cli_name 映射

```typescript
// 摘自 proxy/src/task-runner.ts:62-63 — cli_name 选择
cli_name: model.interface_type === "openai_responses" ? "codex"
  : model.interface_type === "anthropic" ? "claude"
  : "opencode",
```

### 接口类型 → SDK 映射

```typescript
// Go 后端 SDK 选择逻辑（基于 interface_type）
interface InterfaceTypeSDKMapping = {
  "openai_chat": {
    sdk: "sashabaranov/go-openai",
    endpoint: "{baseURL}/chat/completions",
    format: "completion"  // 标准 ChatCompletion
  },
  "openai_responses": {
    sdk: "原生 HTTP",
    endpoint: "{baseURL}/responses",
    format: "streaming"  // Responses API 流式
  },
  "anthropic": {
    sdk: "anthropics/anthropic-sdk-go",
    endpoint: "{baseURL}/v1/messages",
    format: "messages"  // Anthropic Messages API
  }
}
```

### 代理接口类型获取

```typescript
// 摘自 proxy/src/models.ts:93-94 — 获取接口类型
getInterfaceType(model: MonkeyCodeModel): InterfaceType {
  return model.interface_type
}
```

---

## 6. OpenAI 模型列表转换

### toOpenAIModels 方法

```typescript
// 摘自 proxy/src/models.ts:47-53 — 转换为 OpenAI 格式
async toOpenAIModels(): Promise<OpenAIModel[]> {
  const models = await this.fetchModels()
  return models.map((m) => ({
    id: this.toOpenAIModelId(m),      // monkeycode/{provider}/{model}
    object: "model" as const,
    created: Math.floor(Date.now() / 1000),
    owned_by: m.provider,             // 提供商名称
  }))
}
```

### OpenAI 响应格式

```json
// GET /v1/models 响应
{
  "object": "list",
  "data": [
    {
      "id": "monkeycode/openai/gpt-4o",
      "object": "model",
      "created": 1718245800,
      "owned_by": "openai"
    },
    {
      "id": "monkeycode/anthropic/claude-3-opus-20240229",
      "object": "model",
      "created": 1718245800,
      "owned_by": "anthropic"
    }
  ]
}
```

---

## 7. 全链路追踪

### 从请求到 LLM 调用

```
用户请求: POST /v1/chat/completions { model: "gpt-4o", messages: [...] }
  │
  ▼
① api-routes.ts: resolveModel("gpt-4o")
  ├── fetchModels() → 缓存检查 → 5 分钟有效
  ├── resolveModel("gpt-4o")
  │   ├── 第 1 层: "monkeycode/openai/gpt-4o" === "gpt-4o" → ❌
  │   ├── 第 2 层: "openai/gpt-4o" === "gpt-4o" → ❌
  │   ├── 第 3 层: "gpt-4o" === "gpt-4o" → ✅ 找到!
  │   └── 返回 MonkeyCodeModel { id: "uuid-xxx", provider: "openai", ... }
  │
  ▼
② task-runner.ts: createTask(model, prompt)
  ├── model.id → POST /api/v1/users/tasks { model_id: "uuid-xxx" }
  ├── model.interface_type → "openai_chat"
  └── cli_name → "opencode" (因为 interface_type 是 openai_chat)
  │
  ▼
③ Backend: TaskFlow VM 创建
  ├── image_id → Docker 镜像
  ├── model_id → 后端模型选择
  └── cli_name → Agent 包选择 (opencode NPM 包)
  │
  ▼
④ LLM Client: 根据 interface_type 选择 SDK
  ├── openai_chat → go-openai SDK → POST {baseURL}/chat/completions
  └── 最终调用 LLM 提供商
```

---

## 8. 配置项总览

### 环境变量

```typescript
// 影响模型发现的配置
const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"
// 模型缓存 TTL 不可配置（硬编码 5 分钟）

// 影响任务创建的配置
const DEFAULT_HOST_ID = process.env.MONKEYCODE_HOST_ID || "public_host"
const DEFAULT_IMAGE_ID = process.env.MONKEYCODE_IMAGE_ID || ""
```

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| API 端点 | `/api/v1/users/models` | 模型列表 API |
| 缓存 TTL | 5 分钟 | 硬编码，不支持配置 |
| 模型 ID 格式 | `monkeycode/{provider}/{model}` | OpenAI 兼容格式 |
| 默认 host_id | `public_host` | 可通过 MONKEYCODE_HOST_ID 配置 |
| 模型解析层级 | 6 层 | 从精确匹配到兜底 |

---

## 相关章节

- [模型管理 API](../../03-llm/01-model-management-api.md) — 后端模型 CRUD API
- [接口类型](../../03-llm/02-interface-types.md) — 3 种接口类型详解
- [提供商列表](../../03-llm/03-provider-list.md) — 11 个提供商配置
- [私有模型创建](../../03-llm/06-private-model-creation.md) — 私有模型创建流程