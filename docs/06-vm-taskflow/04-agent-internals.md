---
description: VM 内部 Agent 架构分析 — Codex / Claude / OpenCode 三种 Agent，NPM 包选择，环境变量注入，容器启动流程
protocol_version: based on chaitin/MonkeyCode 开源后端源码 + NPM 包分析
confidence: high (Agent 类型枚举、NPM 包选择、环境变量注入完整已知；内部实现闭源)
last_verified: 2026-06-27
---

# VM 内部 Agent 分析

> **状态:** 🟡 架构层已知，Agent 内部实现闭源
> **当前已知:** 三种 Agent 类型 (codex/claude/opencode)，NPM 包选择逻辑，容器初始化流程，环境变量注入
> **不可解析:** Agent 内部的 LLM 请求构造、工具调用处理、ACP 事件生成逻辑（NPM 包闭源）

## 概述

VM 容器内运行一个 **Node.js Coding Agent**，通过 `@ai-sdk/*`（Vercel AI SDK）调用 LLM Provider，并执行代码开发任务。

## Agent 类型

Agent 类型由任务创建时的 `cli_name` 字段决定：

| cli_name | 对应 Agent | 用途 | NPM 包 |
|---------|-----------|------|--------|
| `codex` | Codex CLI | 代码生成与编辑（OpenAI 官方 Agent） | `@ai-sdk/openai` 或 `@ai-sdk/openai-compatible` |
| `claude` | Claude Code | 代码审查与开发（Anthropic 官方 Agent） | `@ai-sdk/anthropic` |
| `opencode` | OpenCode | 开源代码 Agent | `@ai-sdk/openai-compatible` |

## NPM 包选择

```go
// 源码: backend/pkg/taskflow/vm.go — 根据接口类型选择 NPM 包
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

| 接口类型 | NPM 包 | 用途 |
|---------|--------|------|
| `openai_chat` | `@ai-sdk/openai-compatible` | 兼容 OpenAI Chat Completion API 的提供商 |
| `openai_responses` | `@ai-sdk/openai` | OpenAI Responses API（Codex 专用） |
| `anthropic` | `@ai-sdk/anthropic` | Anthropic Messages API |

> **注意:** Agent 的精确 NPM 包版本号不是代码硬编码的，而是通过 `agentpluginrepo` 数据库表管理，由前端 `package.json` 和后端 Docker 构建共同决定。

## 容器初始化流程

```
容器启动
    │
    ├── 1. 安装 Coding Agent NPM 包（基于 cli_name + interface_type）
    │     ├── npm install @ai-sdk/openai-compatible@latest
    │     ├── npm install @ai-sdk/anthropic@latest
    │     └── npm install (cli_name 对应的 Agent 包)
    │
    ├── 2. 注入环境变量（task_config 中配置）
    │     ├── ANTHROPIC_API_KEY=xxx
    │     ├── OPENAI_API_KEY=xxx
    │     ├── OPENAI_BASE_URL=http://taskflow-internal:8080
    │     ├── TASK_ID=xxx
    │     └── MCP_SERVER_URL=http://127.0.0.1:65510/mcp
    │
    ├── 3. 启动内置 MCP 服务 (mcaiBuiltin)
    │     └── http://127.0.0.1:65510/mcp (task_id 参数上下文绑定)
    │
    ├── 4. 从 Redis 读取 task_config（10 分钟内）
    │     ├── user_prompt（用户输入）
    │     ├── system_prompt（系统指令）
    │     ├── MCP 上游配置
    │     └── 模型配置（model/interface_type 等）
    │
    ├── 5. 等待 user-input（通过 TaskLive WS）
    │     └── 第一个 user-input 触发 Agent 开始工作
    │
    └── 6. Agent 启动 LLM 调用循环
          ├── 构造 LLM Request（基于 @ai-sdk/*）
          ├── 调用 LLM Provider
          ├── 解析 Streaming Response
          ├── 处理 Tool Calls（MCP 工具）
          └── 生成 ACP 事件流 → TaskLive WS
```

## 环境变量注入代码

```go
// backend/pkg/taskflow/vm.go — VM 容器环境变量配置
func buildAgentEnv(task *Task, config *TaskConfig) map[string]string {
    env := map[string]string{
        // AI SDK 配置
        "TASK_ID":              task.ID.String(),
        "AGENT_TYPE":           string(task.CliName),
        "MODEL_NAME":           config.Model,
        "INTERFACE_TYPE":       string(config.InterfaceType),
        
        // LLM API Key 注入
        "ANTHROPIC_API_KEY":    config.AnthropicKey,
        "OPENAI_API_KEY":       config.OpenAIKey,
        "OPENAI_BASE_URL":      config.OpenAIBaseURL,
        
        // MCP 内置服务地址
        "MCP_SERVER_URL":       fmt.Sprintf("http://127.0.0.1:65510/mcp?task_id=%s", task.ID),
        
        // 工作目录
        "WORKSPACE_DIR":        "/workspace",
    }
    return env
}
```

## Agent 启动命令

```go
// 构建容器启动命令
func buildEntrypoint(agentType string) []string {
    switch agentType {
    case "codex":
        return []string{"npx", "codex", "--model", config.Model}
    case "claude":
        return []string{"npx", "claude", "--model", config.Model}
    case "opencode":
        return []string{"npx", "opencode", "--model", config.Model}
    default:
        return []string{"npx", "opencode"} // 默认 fallback
    }
}
```

## 容器内的 @ai-sdk/* 使用模式

Agent 在容器内通过 `@ai-sdk/*` 调用 LLM Provider 的典型结构：

```typescript
// 容器内 Agent 代码的推测结构（基于 @ai-sdk/openai-compatible 用法）
import { generateText } from 'ai';
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';

// 1. 创建 Provider 实例
const provider = createOpenAICompatible({
  baseURL: process.env.OPENAI_BASE_URL,  // 内部 LLM 代理地址
  apiKey: process.env.OPENAI_API_KEY,
  name: 'monkeycode-llm',
});

// 2. 调用 LLM
const { text, toolCalls, toolResults, usage } = await generateText({
  model: provider.chatModel(process.env.MODEL_NAME),
  messages: [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userInput }
  ],
  tools: {
    // MCP 工具通过 mcaiBuiltin 注册
    ...mcpTools,
  },
  maxSteps: 10,  // 允许工具调用多轮
  onStepFinish(result) {
    // 生成 ACP 事件并通过 TaskLive WS 发送
    sendACPUpdate({
      type: 'agent_message_chunk',
      text: result.text,
      toolCalls: result.toolCalls,
    });
  },
});
```

## Agent 包版本管理

Agent NPM 包的版本不由代码硬编码，而是由数据库的 `agentpluginrepo` 表管理：

```sql
-- agentpluginrepo 表结构（推测）
CREATE TABLE agentpluginrepo (
    id          UUID PRIMARY KEY,
    name        VARCHAR(64)    NOT NULL,  -- 包名，如 "@ai-sdk/openai-compatible"
    version     VARCHAR(32)    NOT NULL,  -- 版本号，如 "0.0.0-canary-e241dcf-20250517014852"
    config      JSON           NOT NULL,  -- 配置 JSON
    created_at  TIMESTAMP      NOT NULL,
    updated_at  TIMESTAMP      NOT NULL
);
```

这意味着：
- 前端选择 Agent 时从 `agentpluginrepo` 读取可用包列表
- 后端构建 Docker 容器时按数据库中的版本安装
- 更新 Agent NPM 包只需要改数据库记录，无需重新部署后端

## 已知但不可见的部分

| # | 问题 | 状态 | 瓶颈 |
|---|------|------|------|
| 1 | Agent 精确 NPM 包版本 | 🟡 需线上 | Docker 构建时从数据库读取 |
| 2 | Agent 如何构造 LLM 请求（prompt template） | 🟡 需线上 | Agent 包闭源 |
| 3 | Agent 如何处理工具调用结果 | 🟡 需线上 | Agent 包闭源 |
| 4 | Agent 内部状态管理 | 🟡 需线上 | Agent 包闭源 |
| 5 | Agent 对 ACP 事件的生成逻辑 | 🟡 需线上 | Agent 包闭源 |
| 6 | LLM 调用失败的重试策略 | 🟡 需线上 | Agent 包闭源 |
| 7 | Agent 是否支持多模态输入 | 🟡 推测支持 | LLM Provider 能力 |

---

## 附录：逆向分析代码示例

### 附录 A: Docker 容器启动模拟 (Python)
```python
# 模拟 MonkeyCode VM Agent 容器启动逻辑
import subprocess
import os

def build_agent_container(task_id: str, cli_name: str, model: str,
                          interface_type: str, api_key: str):
    """构造 Agent 容器的启动环境和命令"""
    
    env = os.environ.copy()
    env.update({
        "TASK_ID": task_id,
        "AGENT_TYPE": cli_name,
        "MODEL_NAME": model,
        "INTERFACE_TYPE": interface_type,
        f"{'ANTHROPIC' if interface_type == 'anthropic' else 'OPENAI'}_API_KEY": api_key,
        "MCP_SERVER_URL": f"http://127.0.0.1:65510/mcp?task_id={task_id}",
        "WORKSPACE_DIR": "/workspace",
    })
    
    # NPM 包选择
    npm_packages = {
        "openai_chat": "@ai-sdk/openai-compatible",
        "openai_responses": "@ai-sdk/openai",
        "anthropic": "@ai-sdk/anthropic",
    }
    pkg = npm_packages.get(interface_type, "@ai-sdk/openai-compatible")
    
    print(f"[Agent] Installing {pkg}...")
    subprocess.run(["npm", "install", pkg], cwd="/workspace")
    
    print(f"[Agent] Starting {cli_name} with model {model}...")
    subprocess.run(["npx", cli_name, "--model", model], cwd="/workspace")
```

### 附录 B: Go 容器配置源码模式
```go
// chaitin/MonkeyCode VM 容器配置（重构版）
type ContainerConfig struct {
    Image         string            // Docker 镜像
    Cmd           []string          // entrypoint 命令
    Env           map[string]string // 环境变量
    ResourceLimit ResourceSpec      // 资源限制（Cores=2, Memory=8GB）
    MCPPort       int               // MCP 服务端口（65510）
}

func NewAgentContainer(task *Task, config *TaskConfig) *ContainerConfig {
    return &ContainerConfig{
        Image: config.ImageURL,
        Cmd:   buildEntrypoint(string(task.CliName)),
        Env:   buildAgentEnv(task, config),
        ResourceLimit: ResourceSpec{
            Cores:  2,
            Memory: 8 * 1024 * 1024 * 1024, // 8GB
        },
        MCPPort: 65510,
    }
}
```

---

## 相关章节

- [VM 生命周期](02-vm-lifecycle.md) — Agent 在 VM 中的运行上下文
- [MCP 协议](03-mcp-protocol.md) — Agent 使用的工具调用协议
- [LLM 通信协议](../03-llm/README.md) — Agent 调用的 LLM Provider
- [Coding Agent 配置](../03-llm/06-coding-agent-config.md) — Agent 配置详情