---
description: 私有模型创建完整流程 — 基于 Go 源码和 TypeScript 代理的双视角分析
protocol_version: based on chaitin/MonkeyCode + proxy/src/models.ts + proxy/src/api-routes.ts
confidence: high
last_verified: 2026-06-28
---

# 私有模型创建（源码增强版）

## 1. 模型管理体系全景

MonkeyCode 的模型管理跨越**后端 Go 源码**和**代理 TypeScript 代码**两个系统：

```
用户/管理员
    │
    ├── POST /api/v1/users/models  ──→ Go 后端 (创建/管理模型元数据)
    │                                     │
    │                                     ├── domain/model.go: CRUD + 权限
    │                                     ├── pkg/llm/client.go: 接口类型分发
    │                                     └── ent schema: PostgreSQL 持久化
    │
    └── POST /v1/chat/completions ──→ 代理 (模型解析和路由)
                                          │
                                          ├── models.ts: 模型 ID 解析 + 缓存
                                          ├── api-routes.ts: OpenAI 兼容路由
                                          └── task-runner.ts: 任务创建
```

## 2. Go 后端模型模型结构体

### 2.1 Model 实体定义

```go
// domain/model.go
type Model struct {
    ID             string         // UUID
    Provider       string         // 提供商名：OpenAI/DeepSeek/Anthropic/...
    ModelName      string         // 模型名：gpt-4o/deepseek-chat/...
    DisplayName    string         // 显示名
    Description    string         // 描述
    InterfaceType  string         // openai_chat | openai_responses | anthropic
    BaseURL        string         // API 基础 URL
    APIKey         string         // API Key（敏感信息）
    Temperature    float64        // 默认温度
    ContextLimit   int64          // 上下文窗口限制
    OutputLimit    int64          // 输出长度限制
    IsFree         bool           // 是否免费
    AccessLevel    string         // basic | pro | ultra
    IsDefault      bool           // 是否默认选中
    ThinkingEnabled bool          // 是否启用思维链
    Owner          Owner          // 所有者信息
    CreatedAt      time.Time
    UpdatedAt      time.Time
}

type Owner struct {
    Type string    // "private" | "team" | "public"
    ID   string    // 用户 UUID（private）或团队 UUID（team）
}
```

### 2.2 模型查询的完整 SQL 逻辑

代理层 `models.ts` 的 `resolveModel()` 展示了模型 ID 解析的回退链：

```typescript
// proxy/src/models.ts — 模型 ID 解析回退链
async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
  const models = await this.fetchModels()

  // 1. 精确匹配: monkeycode/provider/model 格式
  const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
  if (exact) return exact

  // 2. 匹配 provider/model 格式
  const byProviderModel = models.find(
    (m) => `${m.provider}/${m.model}` === openaiModelId
  )
  if (byProviderModel) return byProviderModel

  // 3. 模糊匹配 model 名称
  const byModelName = models.find((m) => m.model === openaiModelId)
  if (byModelName) return byModelName

  // 4. 匹配 display_name
  const byDisplayName = models.find((m) => m.display_name === openaiModelId)
  if (byDisplayName) return byDisplayName

  // 5. 回退到默认模型
  const defaultModel = models.find((m) => m.is_default)
  if (defaultModel) return defaultModel

  // 6. 最后的回退
  return models[0] || null
}
```

完整解析链：**6层回退**，确保最大兼容性。

## 3. 私有模型创建完整流程

### 3.1 TypeScript 代理侧的模型管理

```typescript
// proxy/src/types.ts — 完整的模型接口定义
export interface MonkeyCodeModel {
  id: string             // UUID string from backend
  provider: ModelProvider  // siliconflow | openai | ollama | deepseek | ...
  api_key: string
  base_url: string
  model: string          // 模型名称
  temperature: number
  is_default: boolean
  interface_type: InterfaceType  // "openai_chat" | "openai_responses" | "anthropic"
  is_free: boolean
  access_level: AccessLevel       // "basic" | "pro" | "ultra"
  thinking_enabled: boolean
  context_limit: number
  output_limit: number
  owner: OwnerType               // "private" | "team" | "public"
  name: string
  display_name: string
  description: string
}
```

### 3.2 模型缓存策略

代理层使用 **5 分钟缓存**减少对后端的请求：

```typescript
// proxy/src/models.ts
export class ModelManager {
  private models: MonkeyCodeModel[] = []
  private lastFetch: number = 0
  private cacheTTL: number = 5 * 60 * 1000  // 5分钟缓存

  async fetchModels(): Promise<MonkeyCodeModel[]> {
    // 缓存命中直接返回
    if (this.models.length > 0 && Date.now() - this.lastFetch < this.cacheTTL) {
      return this.models
    }

    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/models`
    const response = await fetch(url, {
      headers: mkHeaders({
        Cookie: `${this.auth.getSessionCookieName()}=${this.auth.getSessionCookieSync()}`,
      }),
    })

    const result = await response.json()
    // 响应格式兼容: { code: 0, data: { models: [...] } } 或 { models: [...] }
    const data = result.data || result
    this.models = data.models || []
    this.lastFetch = Date.now()
    return this.models
  }

  // 清除缓存（管理员手动刷新）
  clearCache(): void {
    this.models = []
    this.lastFetch = 0
  }
}
```

### 3.3 OpenAI 兼容模型 ID 格式

代理层将 MonkeyCode 内部模型 ID 转换为 OpenAI 兼容格式：

```typescript
// proxy/src/models.ts
toOpenAIModelId(m: MonkeyCodeModel): string {
  // 格式: monkeycode/{provider}/{model}
  return `monkeycode/${m.provider}/${m.model}`
}
```

OpenAI SDK 使用示例：
```bash
# OpenAI Python SDK
openai = OpenAI(
    base_url="http://localhost:9090/v1",
    api_key="any-value",  # 代理不验证 API Key
)
models = openai.models.list()
# 返回: { id: "monkeycode/openai/gpt-4o", ... }
```

## 4. 模型创建与接口类型的关系

### 4.1 接口类型决定 Agent 行为

模型创建时指定的 `interface_type` 决定了 VM 内使用的 Coding Agent：

```typescript
// proxy/src/task-runner.ts — cli_name 映射
const body: Record<string, unknown> = {
  // ...
  cli_name: model.interface_type === "openai_responses" ? "codex"
    : model.interface_type === "anthropic" ? "claude"
    : "opencode",
  // ...
}
```

| interface_type | cli_name | NPM 包 | Agent 行为 |
|---------------|----------|--------|-----------|
| `openai_chat` | `opencode` | `@ai-sdk/openai-compatible` | 通用聊天 Agent |
| `openai_responses` | `codex` | `@ai-sdk/openai` | Codex 原生 Agent（工具调用） |
| `anthropic` | `claude` | `@ai-sdk/anthropic` | Claude 协议 Agent |

### 4.2 私有模型的 HTTP 验证（后端源码）

```go
// 后端创建模型时验证 API Key 可达性（逻辑伪代码）
func (uc *ModelUsecase) Create(ctx context.Context, req CreateModelReq) (*Model, error) {
    // 1. 校验参数
    if err := validateModel(req); err != nil {
        return nil, err
    }

    // 2. 验证 API Key（可选）
    if req.APIKey != "" {
        health, err := uc.llmClient.HealthCheck(ctx, HealthCheckReq{
            Provider:    req.Provider,
            BaseURL:     req.BaseURL,
            APIKey:      req.APIKey,
            Model:       req.ModelName,
        })
        if err != nil || !health.Success {
            // API Key 验证失败但模型仍被创建（只是标记为不可用）
            log.Warnf("Model created but API key validation failed: %v", err)
        }
    }

    // 3. 写入数据库
    model, err := uc.db.Model.Create().
        SetProvider(req.Provider).
        SetModelName(req.ModelName).
        SetInterfaceType(req.InterfaceType).
        SetBaseURL(req.BaseURL).
        SetAPIKey(req.APIKey).  // 注意：明文存储
        SetOwner(Owner{Type: "private", ID: ctx.UserID}).
        Save(ctx)

    return model, nil
}
```

## 5. 安全关键点

### 5.1 API Key 存储

| 考虑项 | 当前处理 | 安全建议 |
|--------|---------|---------|
| 传输加密 | HTTPS | ✅ 已满足 |
| 存储加密 | Go PostgreSQL 明文存储 | ⚠️ 建议数据库层面加密 |
| 日志脱敏 | 未特殊处理 | ⚠️ 注意避免 Key 泄露到日志 |
| 返回隐藏 | `HideCredentials` 仅对公开模型 | ⚠️ 私有模型 Key 可查看 |

### 5.2 权限边界

```typescript
// 私有模型创建后的可见性
// - owner.type = "private", owner.id = user_id
// - 仅创建者可见
// - 其他用户无法发现或使用

// team 模型
// - owner.type = "team", owner.id = team_id
// - 团队内所有成员可见

// public 模型（管理员创建）
// - owner.type = "public"
// - 所有认证用户可见
```

## 6. 模型列表的端到端流程

```
Client                         Proxy                        MonkeyCode Backend
  │                              │                              │
  │  GET /v1/models              │                              │
  ├─────────────────────────────►│                              │
  │                              │  GET /api/v1/users/models    │
  │                              ├─────────────────────────────►│
  │                              │                              │── Select * from models
  │                              │                              │  WHERE owner.type IN
  │                              │                              │  ('public', user.id, team.id)
  │                              │◄──── { code:0, data:        │
  │                              │         { models: [...] }}   │
  │                              │                              │
  │                              ├── 缓存结果 5 分钟            │
  │                              │── 转换为 OpenAI 格式        │
  │◄──── { object:"list",       │                              │
  │         data: [...] }        │                              │
  │                              │                              │
  │  POST /v1/chat/completions   │                              │
  │  { model:"monkeycode/...",   │                              │
  │    messages: [...] }         │                              │
  ├─────────────────────────────►│                              │
  │                              │── resolveModel(model_id)     │
  │                              │── model.interface_type →     │
  │                              │   cli_name 映射              │
  │                              │── createTask(...)            │
  │                              ├─────────────────────────────►│
```

---

## 相关章节

- [模型管理 API](01-model-management-api.md) — 完整的 CRUD 端点
- [模型定价与配额](04-model-pricing-quota.md) — 订阅与访问控制
- [11 个提供商配置](03-provider-list.md) — 提供商列表
- [LLM 集成协议](05-llm-integration.md) — Client 架构和接口检测