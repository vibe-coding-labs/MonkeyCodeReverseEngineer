---
description: 11 个模型提供商的完整配置 — 基于 pkg/llm/client.go 和 proxy/src/types.ts 的源码分析
protocol_version: based on chaitin/MonkeyCode + proxy/src/types.ts + proxy/src/server.ts
confidence: high
last_verified: 2026-06-28
---

# 11 个模型提供商配置（源码增强版）

## 1. 源码级类型安全

代理层对提供商类型做了完整的 TypeScript 联合类型约束：

```typescript
// proxy/src/types.ts — 类型安全的提供商枚举
export type ModelProvider =
  | "siliconflow"
  | "openai"
  | "ollama"
  | "deepseek"
  | "moonshot"
  | "azure_openai"
  | "baizhicloud"
  | "hunyuan"
  | "bailian"
  | "volcengine"
  | "gemini"
  | "other"       // 扩展占位
```

提供商列表通过 `"other"` 类型支持扩展，允许管理员添加未预定义的提供商。

## 2. 模型 ID 在代理层的完整映射

### 2.1 OpenAI 兼容 ID 格式

```typescript
// proxy/src/models.ts
toOpenAIModelId(m: MonkeyCodeModel): string {
  return `monkeycode/${m.provider}/${m.model}`
}

// 示例结果:
// "monkeycode/openai/gpt-4o"
// "monkeycode/deepseek/deepseek-chat"
// "monkeycode/volcengine/doubao-seed-1.6-250615"
```

### 2.2 模型 ID 解析回退链（6层）

代理启动时的模型加载日志：

```
[Init] Available models: 47
  - openai/gpt-4o (openai_chat, public)
  - anthropic/claude-sonnet-4-20250514 (anthropic, public)
  - deepseek/deepseek-chat (openai_chat, public)
  - moonshot/moonshot-v1-auto-8k (openai_chat, public)
  - volcengine/doubao-seed-1.6-250615 (openai_chat, public)
  ... and 42 more
```

## 3. 代理层中 Provider 的端到端使用

### 3.1 模型列表 API 的代理实现

```typescript
// proxy/src/api-routes.ts — GET /v1/models
router.get("/v1/models", async (_req: Request, res: Response) => {
  try {
    const models = await modelManager.toOpenAIModels()
    const response: OpenAIModelsResponse = {
      object: "list",
      data: models,
    }
    res.json(response)
  } catch (err: any) {
    console.error("[Models] Error:", err.message)
    res.status(500).json({
      error: { message: err.message, type: "internal_error" }
    })
  }
})
```

响应示例：
```json
{
  "object": "list",
  "data": [
    {
      "id": "monkeycode/openai/gpt-4o",
      "object": "model",
      "created": 1717000000,
      "owned_by": "openai"
    }
  ]
}
```

### 3.2 启动时的模型预载入

```typescript
// proxy/src/server.ts — 启动时的模型预载入
try {
  const models = await modelManager.fetchModels()
  console.log(`[Init] Available models: ${models.length}`)
  for (const m of models.slice(0, 5)) {
    console.log(`  - ${m.provider}/${m.model} (${m.interface_type}, ${m.owner})`)
  }
  if (models.length > 5) {
    console.log(`  ... and ${models.length - 5} more`)
  }
} catch (err: any) {
  console.warn(`[Init] Failed to fetch models: ${err.message}`)
}
```

## 4. Provider 与接口类型的运行时匹配

在任务创建时，代理层根据模型配置动态选择 Agent 类型：

```typescript
// proxy/src/task-runner.ts — cli_name 选择逻辑
cli_name: model.interface_type === "openai_responses" ? "codex"
  : model.interface_type === "anthropic" ? "claude"
  : "opencode",
```

| 提供商 | 接口类型 | Agent | 调用链 |
|--------|---------|-------|--------|
| OpenAI | `openai_chat` 或 `openai_responses` | opencode 或 codex | HTTP → GPT-4o/4o-mini |
| Anthropic | `anthropic` | claude | HTTP → Claude API |
| DeepSeek | `openai_chat` | opencode | HTTP → DeepSeek Chat/Reasoner |
| SiliconFlow | `openai_chat` | opencode | HTTP → 第三方代理转 API |
| 火山引擎(豆包) | `openai_chat` | opencode | HTTP → Doubao 系列模型 |
| 通义千问 | `openai_chat` | opencode | HTTP → Qwen 系列模型 |
| Moonshot(月之) | `openai_chat` | opencode | HTTP → Moonshot 系列 |
| 百川 | `openai_chat` | opencode | HTTP → Baichuan 系列 |
| 智谱GLM | `openai_chat` | opencode | HTTP → GLM 系列 |
| Minimax | `openai_chat` | opencode | HTTP → MiniMax 系列 |
| 阶跃星辰 | `openai_chat` | opencode | HTTP → Step 系列 |

## 5. 模型管理操作流

### 5.1 代理的模型缓存刷新

```typescript
// proxy/src/server.ts — 管理端点
app.post("/admin/refresh-models", async (_req, res) => {
  try {
    modelManager.clearCache()          // 清除 5 分钟缓存
    const models = await modelManager.fetchModels()  // 重新获取
    res.json({ status: "ok", count: models.length })
  } catch (err: any) {
    res.status(500).json({ error: err.message })
  }
})
```

### 5.2 Agent 内部模型解析流程

```
OpenAI SDK 调用
    │ POST /v1/chat/completions
    │ { model: "monkeycode/deepseek/deepseek-chat" }
    ▼
代理 api-routes.ts
    │ resolveModel("monkeycode/deepseek/deepseek-chat")
    │ → 找到对应 MonkeyCodeModel
    │ → model.interface_type = "openai_chat"
    │ → cli_name = "opencode"
    ▼
代理 task-runner.ts
    │ createTask({
    │   model_id: model.id (UUID),
    │   cli_name: "opencode",
    │   content: prompt
    │ })
    ▼
MonkeyCode 后端
    │ POST /internal/vm (TaskFlow)
    │ → 创建 Docker 容器
    │ → 注入 LLM 环境变量
    │ → 启动 Coding Agent
    ▼
VM 容器内
    │ LLM_API_KEY=sk-xxx
    │ LLM_BASE_URL=https://api.deepseek.com/v1
    │ LLM_MODEL=deepseek-chat
    │ LLM_INTERFACE_TYPE=openai_chat
    │ → Agent 调用 DeepSeek API
```

## 6. 提供商配置对代理行为的影响

### 6.1 公开模型 vs 私有模型的 Key 处理

```go
// 后端逻辑（domain/model.go）
// 公开模型: api_key 返空，运行时由后端注入实际 Key
// 私有模型: api_key 返给创建者，直接使用
```

### 6.2 模型配置的字段映射

```
Go 后端模型字段           → API 响应字段          → TypeScript 类型
─────────────────         ───────────────          ────────────────
provider                  → provider               → MonkeyCodeModel.provider
model_name                → model                  → MonkeyCodeModel.model
interface_type            → interface_type         → MonkeyCodeModel.interface_type
base_url                  → base_url               → MonkeyCodeModel.base_url
access_level              → access_level           → MonkeyCodeModel.access_level
```

---

## 相关章节

- [模型管理 API](01-model-management-api.md) — CRUD 操作细节
- [模型定价与配额](04-model-pricing-quota.md) — 订阅与配额
- [LLM 集成协议](05-llm-integration.md) — Client 架构和接口检测
- [私有模型创建](06-private-model-creation.md) — 私有模型创建流程