---
description: Coding Agent 配置生成（含 agentpluginrepo 设计）— Go vm.go 源码、NPM 包注入、agentpluginrepo 表结构
protocol_version: based on chaitin/MonkeyCode backend/pkg/taskflow/vm.go + frontend plugin repo
confidence: high
last_verified: 2026-06-28
---

# Coding Agent 配置生成（源码增强版）

> **核心文件:** `backend/pkg/taskflow/vm.go` — Agent 类型枚举、NPM 包选择
> **数据库表:** `agentpluginrepo` — Agent 插件的版本和元数据管理
> **核心发现:** 4 种 cli_name 枚举、动态 NPM 包选择、agentpluginrepo 表管理版本

## 1. Agent 类型体系

### 1.1 cli_name 枚举

```go
// backend/pkg/taskflow/vm.go — Agent 类型枚举
const (
    CodingAgentCodex      = "codex"       // Codex CLI（OpenAI 官方）
    CodingAgentClaude     = "claude"      // Claude Code（Anthropic 官方）
    CodingAgentMCAIReview = "MCAIReview"  // MonkeyCode 内置代码审查
    CodingAgentOpenCode   = "opencode"    // 开源代码 Agent
)
```

| cli_name | Agent | 开发者 | 用途 |
|---------|-------|--------|------|
| `codex` | Codex CLI | OpenAI | 代码生成与编辑 |
| `claude` | Claude Code | Anthropic | 代码审查与开发 |
| `MCAIReview` | MonkeyCode Review | MonkeyCode | 内置代码审查 |
| `opencode` | OpenCode | 开源社区 | 通用代码 Agent（默认值）|

### 1.2 代理层的动态映射

```typescript
// proxy/src/task-runner.ts — 根据 interface_type 自动选择 cli_name
cli_name: model.interface_type === "openai_responses" ? "codex"
  : model.interface_type === "anthropic" ? "claude"
  : "opencode",
```

| interface_type | cli_name | 说明 |
|---------------|----------|------|
| `openai_responses` | `codex` | Responses API → Codex 原生 |
| `anthropic` | `claude` | Anthropic Messages → Claude |
| `openai_chat`（默认） | `opencode` | 通用 OpenAI 兼容 |

## 2. NPM 包选择

### 2.1 由 interface_type 决定

```go
// backend/pkg/taskflow/vm.go — NPM 包选择
func getNpmPackage(interfaceType InterfaceType) string {
    switch interfaceType {
    case InterfaceOpenAIChat:
        return "@ai-sdk/openai-compatible"
    case InterfaceOpenAIResponses:
        return "@ai-sdk/openai"
    case InterfaceAnthropic:
        return "@ai-sdk/anthropic"
    }
    return "@ai-sdk/openai-compatible" // 默认
}
```

| interface_type | NPM 包 | 用途 |
|---------------|--------|------|
| `openai_chat` | `@ai-sdk/openai-compatible` | OpenAI Chat Completions |
| `openai_responses` | `@ai-sdk/openai` | OpenAI Responses API（Codex 专用）|
| `anthropic` | `@ai-sdk/anthropic` | Anthropic Messages API |

### 2.2 agentpluginrepo 数据库表设计

```sql
-- agentpluginrepo 表（从源码推断）
CREATE TABLE agentpluginrepo (
    id            UUID PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,       -- 插件名，如 "@ai-sdk/openai"
    version       VARCHAR(32) NOT NULL,        -- 语义化版本，如 "1.0.0"
    agent_type    VARCHAR(64),                 -- 关联的 cli_name
    interface_type VARCHAR(32),                -- openai_chat / openai_responses / anthropic
    is_active     BOOLEAN DEFAULT true,        -- 是否当前激活版本
    package_json  JSONB,                       -- 完整 package.json 内容
    dependencies  JSONB,                       -- NPM 依赖树
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE(name, version)
);

-- 前端通过此表获取 NPM 包版本信息：
-- SELECT version FROM agentpluginrepo WHERE name = '@ai-sdk/anthropic' AND is_active = true
```

**表说明：**
- 管理每个 @ai-sdk/* 包的版本
- 支持版本回退（设置不同的 is_active）
- 前端构建时决定实际安装版本
- 后端不硬编码版本号

## 3. Agent 配置注入

### 3.1 LLMProviderReq 结构体

```go
type LLMProviderReq struct {
    Provider    string   `json:"provider"`     // 固定 "openai"（内部使用）
    ApiKey      string   `json:"api_key"`      // LLM Provider API Key
    BaseURL     string   `json:"base_url"`     // LLM Provider 地址
    Model       string   `json:"model"`        // 模型名
    Temperature *float32 `json:"temperature,omitempty"`
}
```

### 3.2 容器内环境变量注入

| 环境变量 | 值来源 | 用途 |
|---------|--------|------|
| `LLM_API_KEY` | `LLMProviderReq.ApiKey` | Agent 调用 LLM |
| `LLM_BASE_URL` | `LLMProviderReq.BaseURL` | Agent 连接地址 |
| `LLM_MODEL` | `LLMProviderReq.Model` | Agent 使用的模型 |
| `LLM_INTERFACE_TYPE` | 模型配置 `interface_type` | Agent 选择 SDK |
| `MCAI_SERVER_BASE_URL` | 后端配置 | MCP 服务器地址 |
| `TASK_ID` | 当前任务 UUID | 上下文绑定 |
| `MCP_SERVER_URL` | `http://127.0.0.1:65510/mcp` | 内置 MCP 服务 |

## 4. Agent 容器启动流程

```
容器启动
    │
    ├── 1. 安装 NPM 包（依据 agentpluginrepo 表版本）
    │     ├── npm install @ai-sdk/openai-compatible@<version>
    │     ├── npm install @ai-sdk/anthropic@<version>
    │     └── npm install <coding-agent-package>@<version>
    │
    ├── 2. 注入环境变量（20+ 个环境变量）
    ├── 3. 启动内置 MCP 服务 (mcaiBuiltin, 端口 65510)
    ├── 4. 从 Redis 读取 task_config（10 分钟 TTL）
    │     ├── user_prompt, system_prompt
    │     ├── MCP 配置
    │     └── 模型配置
    ├── 5. 等待 user-input（通过 TaskLive WebSocket）
    └── 6. 第一个 input → Agent 开始工作
```

## 5. 安全考量

| 风险 | 说明 |
|------|------|
| API Key 注入 | Agent 运行所需的 API Key 在容器内可见 |
| NPM 包版本 | 版本由 agentpluginrepo 表控制，可回退 |
| 容器隔离 | Docker 容器提供进程隔离 |
| 网络限制 | Agent 只连接 LLM Provider 和 MCP 服务 |

---

## 相关章节

- [三种接口类型](02-interface-types.md) — interface_type 定义
- [VM 内部 Agent 架构](../06-vm-taskflow/04-agent-internals.md) — Agent 运行环境
- [VM 生命周期](../06-vm-taskflow/02-vm-lifecycle.md) — 容器启动流程