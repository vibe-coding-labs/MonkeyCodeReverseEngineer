---
description: 模型管理 API CRUD 端点完整分析 — Go 后端源码 + TypeScript 代理模型管理器
protocol_version: based on chaitin/MonkeyCode Go 源码 + proxy/src/models.ts (102 行)
confidence: high
last_verified: 2026-06-28
---

# 模型管理 API（源码增强版）

> **Go 端核心文件:** `domain/model.go` — Model 实体 + Owner 权限
> **TypeScript 端核心文件:** `proxy/src/models.ts` — ModelManager (102 行)
> **核心发现:** 6 层模型 ID 解析回退链 + 5 分钟缓存 + Owner 隔离 + 与授权矩阵深度耦合

## 1. 模型管理体系架构

```
管理员/用户
    │
    ├── CRUD API (Go 后端)
    │   ├── GET    /api/v1/users/models          → 列出可见模型
    │   ├── POST   /api/v1/users/models           → 创建模型
    │   ├── GET    /api/v1/users/models/:id       → 获取详情
    │   ├── PUT    /api/v1/users/models/:id       → 更新模型
    │   └── DELETE /api/v1/users/models/:id       → 删除模型
    │
    └── 模型管理 (代理层 models.ts)
        ├── fetchModels()    → GET /users/models + 5 分钟缓存
        ├── resolveModel()   → 6 层回退解析
        ├── toOpenAIModels() → 转换为 OpenAI /v1/models 格式
        └── clearCache()     → 管理员手动刷新
```

## 2. Go 后端模型实体

```go
// domain/model.go
type Model struct {
    ID              string    // UUID
    Provider        string    // 提供商名
    ModelName       string    // 模型名
    DisplayName     string    // 显示名
    Description     string    // 描述
    InterfaceType   string    // openai_chat | openai_responses | anthropic
    BaseURL         string    // API Base URL
    APIKey          string    // API Key（⚠️ 明文存储在数据库）
    Temperature     float64   // 默认温度
    ContextLimit    int64     // 上下文窗口
    OutputLimit     int64     // 输出长度限制
    IsFree          bool      // 是否免费
    AccessLevel     string    // basic | pro | ultra
    IsDefault       bool      // 是否默认选中
    ThinkingEnabled bool      // 是否启用思维链
    Owner           Owner     // 所有者信息
    CreatedAt       time.Time
    UpdatedAt       time.Time
}

type Owner struct {
    Type string    // "private" | "team" | "public"
    ID   string    // 用户 UUID（private）或团队 UUID（team）
}
```

### 数据库表结构 (Ent ORM)

| 字段 | PostgreSQL 类型 | 约束 |
|------|----------------|------|
| id | UUID | PK |
| provider | VARCHAR(64) | NOT NULL |
| model_name | VARCHAR(128) | NOT NULL |
| display_name | VARCHAR(256) | NULLABLE |
| interface_type | VARCHAR(32) | NOT NULL |
| base_url | TEXT | NOT NULL |
| api_key | TEXT | NOT NULL（⚠️ 明文）|
| temperature | DOUBLE | DEFAULT 0.7 |
| context_limit | BIGINT | DEFAULT 0 |
| output_limit | BIGINT | DEFAULT 0 |
| is_free | BOOLEAN | DEFAULT false |
| access_level | VARCHAR(16) | DEFAULT 'basic' |
| is_default | BOOLEAN | DEFAULT false |
| owner_type | VARCHAR(16) | NOT NULL |
| owner_id | VARCHAR(128) | NOT NULL |

## 3. 模型查询的权限过滤

```go
// 可见性查询逻辑（从源码推断）
// 查询条件 OR 组合：
//   (1) owner.type == "public" AND access_level IN user.allowedLevels()
//   (2) owner.type == "private" AND owner_id == user.id
//   (3) owner.type == "team" AND owner_id IN user.teamIDs AND access_level IN user.allowedLevels()
```

| Owner Type | 谁可见 | 额外过滤 |
|-----------|--------|---------|
| `public` | 所有认证用户 | access_level ≤ 用户订阅等级 |
| `private` | 仅创建者 | 无条件 |
| `team` | 团队成员 | access_level ≤ 用户订阅等级 |

## 4. TypeScript ModelManager 完整分析

### 4.1 完整源码

```typescript
// proxy/src/models.ts
export class ModelManager {
  private auth: AuthManager
  private models: MonkeyCodeModel[] = []
  private lastFetch: number = 0
  private cacheTTL: number = 5 * 60 * 1000  // 5 分钟缓存

  constructor(auth: AuthManager) {
    this.auth = auth
  }

  /** 获取模型列表（带 5 分钟缓存） */
  async fetchModels(): Promise<MonkeyCodeModel[]> {
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
      throw new Error(`Failed to fetch models (${response.status})`)
    }

    const result = await response.json()
    // 兼容两种响应格式
    const data = result.data || result
    this.models = data.models || []
    this.lastFetch = Date.now()
    return this.models
  }

  /** 转换为 OpenAI /v1/models 格式 */
  async toOpenAIModels(): Promise<OpenAIModel[]> {
    const models = await this.fetchModels()
    return models.map((m) => ({
      id: this.toOpenAIModelId(m),
      object: "model" as const,
      created: Math.floor(Date.now() / 1000),
      owned_by: m.provider,
    }))
  }

  /** 生成 OpenAI 兼容模型 ID: monkeycode/{provider}/{model} */
  toOpenAIModelId(m: MonkeyCodeModel): string {
    return `monkeycode/${m.provider}/${m.model}`
  }

  /** 6 层模型 ID 解析回退链 */
  async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
    const models = await this.fetchModels()

    // 第 1 层：精确匹配 monkeycode/provider/model
    const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId)
    if (exact) return exact

    // 第 2 层：匹配 provider/model
    const byProviderModel = models.find(
      (m) => `${m.provider}/${m.model}` === openaiModelId
    )
    if (byProviderModel) return byProviderModel

    // 第 3 层：模糊匹配 model 名称
    const byModelName = models.find((m) => m.model === openaiModelId)
    if (byModelName) return byModelName

    // 第 4 层：匹配 display_name
    const byDisplayName = models.find((m) => m.display_name === openaiModelId)
    if (byDisplayName) return byDisplayName

    // 第 5 层：默认模型
    const defaultModel = models.find((m) => m.is_default)
    if (defaultModel) return defaultModel

    // 第 6 层：取第一个模型（最终回退）
    return models[0] || null
  }

  clearCache(): void {
    this.models = []
    this.lastFetch = 0
  }
}
```

### 4.2 6 层解析链示例

| 用户输入 | 匹配层 | 解释 |
|---------|--------|------|
| `monkeycode/siliconflow/Qwen/Qwen3.5-Plus` | 第 1 层 | 完整路径格式 |
| `siliconflow/deepseek-ai/DeepSeek-V3` | 第 2 层 | provider/model |
| `gpt-4o` | 第 3 层 | 模型名精确匹配 |
| `Kimi K2.6` | 第 4 层 | display_name |
| `""`（空串） | 第 5~6 层 | 回退到默认 |

### 4.3 响应格式兼容

```typescript
// 代理兼容两种后端响应格式：
const data = result.data || result          // { code:0, data:{models:[...]} } 或 { models:[...] }
this.models = data.models || []             // models 字段名兼容
```

## 5. 创建私有模型

### 5.1 完整请求

```http
POST /api/v1/users/models
Cookie: monkeycode_ai_session=xxx
Content-Type: application/json

{
  "provider": "openai",
  "model_name": "gpt-4o-mini",
  "display_name": "My GPT-4o Mini",
  "interface_type": "openai_chat",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "temperature": 0.7,
  "context_limit": 128000,
  "output_limit": 16384,
  "access_level": "basic",
  "is_free": false,
  "thinking_enabled": false
}
```

### 5.2 后端处理

```go
// 创建模型时的 API Key 验证（失败不阻断）
if req.APIKey != "" {
    if err := uc.llmClient.HealthCheck(req.Provider, req.BaseURL, req.APIKey, req.ModelName); err != nil {
        log.Warnf("Model created but API key validation failed: %v", err)
        // 不阻断创建
    }
}

// ⚠️ API Key 明文写入 PostgreSQL：
model = db.Model.Create().
    SetProvider(req.Provider).
    SetModelName(req.ModelName).
    SetBaseURL(req.BaseURL).
    SetAPIKey(req.APIKey).      // 明文存储
    SetOwner(Owner{Type: "private", ID: ctx.UserID}).
    Save(ctx)
```

## 6. 模型列表的端到端流程

```
Client (OpenAI SDK)          代理 (models.ts)             MonkeyCode Backend
  │                             │                             │
  │ GET /v1/models              │                             │
  ├────────────────────────────►│                             │
  │                             │ GET /api/v1/users/models    │
  │                             ├────────────────────────────►│
  │                             │                             │── 权限过滤查询
  │                             │◄── { code:0, data:{        │
  │                             │       models:[...] }}       │
  │                             │                             │
  │                             ├── 缓存 (5min TTL)           │
  │                             └── 转换为 OpenAI 格式        │
  │◄── { object:"list",        │                             │
  │       data:[{id:"monkeycode/│                             │
  │       ..."}] }              │                             │
```

## 7. 安全风险总结

| 风险 | 状态 | 影响 |
|------|------|------|
| API Key 明文存储于 PostgreSQL | ⚠️ | 数据库泄露 → 所有 Key 暴露 |
| API Key 返回体不脱敏 | ⚠️ | 私有模型创建者可查看原始 Key |
| 无模型创建频率限制 | ⚠️ | 可批量创建模型（与授权矩阵耦合） |
| 模型访问权限隔离 | ✅ | Owner 系统正确隔离 |

---

## 相关章节

- [模型 ID 类型系统](02-interface-types.md) — 3 种接口类型详解
- [模型定价与配额](04-model-pricing-quota.md) — access_level 订阅过滤
- [私有模型创建](06-private-model-creation.md) — 完整创建和私有流程
- [授权矩阵](../05-api/02-authorization-matrix.md) — Owner 权限体系
