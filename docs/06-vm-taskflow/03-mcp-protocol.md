---
description: MCP (Model Context Protocol) 协议分析 — 完整 JSON-RPC 2.0 规范解析
protocol_version: MCP 2025-06-18 规范
confidence: high (完整规范已知，具体工具列表需线上)
last_verified: 2026-06-25
---

# MCP 协议分析

> **状态:** ✅ MCP 开放协议规范已完整确认，具体工具集需线上
> **协议版本:** MCP specification 2025-06-18

## 概述

MCP（Model Context Protocol）是 VM 容器内运行的**工具调用服务**，采用 **JSON-RPC 2.0** over HTTP 协议。Agent 通过标准化 RPC 接口发现和调用工具。

除了 VM 内部的内置 MCP 服务外，MonkeyCode 后端还提供了独立的 **MCP REST API**（用户管理 MCP 上游配置的接口）。

## MCP 规范完整细节（已从公开协议标准确认）

### 协议版本

| 项目 | 值 |
|------|-----|
| **协议** | JSON-RPC 2.0 |
| **MCP 版本** | 2025-06-18 |
| **传输** | HTTP POST (JSON-RPC) |
| **Capabilities** | `tools` 声明 `listChanged: true/false` |

### tools/list — 发现工具

```json
// Request
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {
    "cursor": "optional-cursor-value-for-pagination"
  }
}

// Response
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "get_weather",
        "description": "Get current weather information for a location",
        "inputSchema": {
          "type": "object",
          "properties": {
            "location": { "type": "string", "description": "City name or zip code" }
          },
          "required": ["location"]
        }
      }
    ],
    "nextCursor": "next-page-cursor"
  }
}
```

**Tool 定义字段:**

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 工具唯一标识符 |
| `description` | string | ❌ | 工具功能描述 |
| `inputSchema` | object (JSON Schema) | ❌ | 预期的参数 JSON Schema |
| `outputSchema` | object (JSON Schema) | ❌ | 预期的输出结构 |
| `annotations` | object | ❌ | 描述工具行为的元属性 |

### tools/call — 调用工具

```json
// Request
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_weather",
    "arguments": {
      "location": "New York"
    }
  }
}

// Response (成功)
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Current temperature: 72°F"
      }
    ],
    "isError": false
  }
}

// Response (执行错误)
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Failed to fetch weather data: API rate limit exceeded"
      }
    ],
    "isError": true
  }
}

// JSON-RPC 协议错误
{
  "jsonrpc": "2.0",
  "id": 4,
  "error": {
    "code": -32602,
    "message": "Unknown tool: invalid_tool_name"
  }
}
```

**Content 类型:**

| type | 附加字段 | 说明 |
|------|---------|------|
| `text` | `text: string` | 纯文本结果 |
| `image` | `data: base64, mimeType: string` | 图片结果 |
| `audio` | `data: base64, mimeType: string` | 音频结果 |
| `resource` | `resource: {uri, mimeType, text}` | 嵌入资源 |
| `resource_link` | `uri: string` | 资源链接 |

### 变更通知

当工具列表变化时，MCP 服务可以推送通知：

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/tools/list_changed"
}
```

### 通信流程总结

```
Client → Server:
  tools/list                              → 发现可用工具（分页支持）
  tools/call {"name":"bash","arguments":...} → 调用 bash 执行命令
  tools/call {"name":"read_file","arguments":...} → 读取文件内容
  
Server → Client:
  tools/list result                       → 返回工具列表（含 inputSchema）
  tools/call result                       → 返回工具执行结果
  notifications/tools/list_changed        → 通知工具列表变化
```

## MCP 部署配置

### 内置 MCP (`mcaiBuiltin`)

| 配置 | 值 |
|------|-----|
| URL | `http://127.0.0.1:65510/mcp?task_id=...` |
| 协议 | JSON-RPC 2.0 over HTTP |
| 范围 | 容器内本地通信 |

### 可选 MCP (`monkeycode-ai`)

| 配置 | 值 |
|------|-----|
| URL | `{backend_url}/mcp` |
| 认证 | Authorization: Bearer {API Key} |
| 范围 | 后端 API 管理操作 |

### 后端 MCP REST API（管理接口）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/users/mcp/upstreams` | 列出 MCP 上游 |
| POST | `/api/v1/users/mcp/upstreams` | 创建 MCP 上游 |
| GET | `/api/v1/users/mcp/upstreams/{id}/tools` | 查询上游工具列表 |

> 这层 REST API 是 MonkeyCode 的用户 MCP 管理接口，与 Agent VM 内部的 mcaiBuiltin MCP 是**不同层次**的概念。

## 完整的消息流

```
Agent (在 VM 内)
  │
  ├── tools/list → mcaiBuiltin MCP (127.0.0.1:65510)
  │   └── 返回: [{name:"bash", inputSchema:{...}}, {name:"read_file",...}, ...]
  │
  ├── tools/call {name:"bash", arguments:{command:"ls -la"}} → mcaiBuiltin
  │   └── 返回: {content:[{type:"text", text:"file1.txt\nfile2.txt"}], isError:false}
  │
  └── tools/call {name:"read_file", arguments:{path:"/workspace/main.go"}} → mcaiBuiltin
      └── 返回: {content:[{type:"text", text:"package main\n..."}], isError:false}
```

## 仍然未知（需线上确认）

| 项目 | 状态 | 原因 |
|------|------|------|
| `mcaiBuiltin` 具体工具列表的**完整精确副本** | 🟡 高度推测（见下方推理） | Docker 镜像定义的实际 tools/list 返回值 |
| 每个工具的具体 `inputSchema` 精确 JSON | 🟡 高度推测 | 同上 |

### `mcaiBuiltin` 工具列表推理（基于 OpenCode 内置工具）

MonkeyCode 的 VM Agent 基于 OpenCode（opencode）/ Codex / Claude Code。它们的工具需求高度相似。根据 OpenCode 的 12 个内置工具，`mcaiBuiltin` 的 MCP `tools/list` 返回值大概率包含：

```json
[
  {
    "name": "bash",
    "description": "Run a shell command",
    "inputSchema": {
      "type": "object",
      "properties": {
        "command": {"type": "string", "description": "The shell command to execute"},
        "timeout": {"type": "number", "description": "Timeout in milliseconds"}
      },
      "required": ["command"]
    }
  },
  {
    "name": "view",
    "description": "View file contents with pagination",
    "inputSchema": {
      "type": "object",
      "properties": {
        "file_path": {"type": "string"},
        "offset": {"type": "number"},
        "limit": {"type": "number"}
      },
      "required": ["file_path"]
    }
  },
  {
    "name": "write",
    "description": "Write content to a file",
    "inputSchema": {
      "type": "object",
      "properties": {
        "file_path": {"type": "string"},
        "content": {"type": "string"}
      },
      "required": ["file_path", "content"]
    }
  },
  {
    "name": "edit",
    "description": "Edit a file with changes",
    "inputSchema": {
      "type": "object",
      "properties": {
        "file_path": {"type": "string"},
        "old_string": {"type": "string"},
        "new_string": {"type": "string"}
      },
      "required": ["file_path"]
    }
  },
  {
    "name": "glob",
    "description": "Find files matching a pattern",
    "inputSchema": {
      "type": "object",
      "properties": {
        "pattern": {"type": "string"},
        "path": {"type": "string"}
      },
      "required": ["pattern"]
    }
  },
  {
    "name": "grep",
    "description": "Search file content with regex",
    "inputSchema": {
      "type": "object",
      "properties": {
        "pattern": {"type": "string"},
        "path": {"type": "string"},
        "include": {"type": "string"}
      },
      "required": ["pattern"]
    }
  },
  {
    "name": "ls",
    "description": "List directory contents",
    "inputSchema": {
      "type": "object",
      "properties": {
        "path": {"type": "string", "default": "."},
        "ignore": {"type": "array", "items": {"type": "string"}}
      }
    }
  },
  {
    "name": "patch",
    "description": "Apply a diff/patch to a file",
    "inputSchema": {
      "type": "object",
      "properties": {
        "file_path": {"type": "string"},
        "diff": {"type": "string", "description": "Unified diff format"}
      },
      "required": ["file_path", "diff"]
    }
  },
  {
    "name": "diagnostics",
    "description": "Get file diagnostics/errors",
    "inputSchema": {
      "type": "object",
      "properties": {
        "file_path": {"type": "string"}
      }
    }
  },
  {
    "name": "agent",
    "description": "Delegate to a sub-agent",
    "inputSchema": {
      "type": "object",
      "properties": {
        "prompt": {"type": "string"}
      },
      "required": ["prompt"]
    }
  },
  {
    "name": "fetch",
    "description": "Make an HTTP request",
    "inputSchema": {
      "type": "object",
      "properties": {
        "url": {"type": "string"},
        "format": {"type": "string", "enum": ["text", "json", "base64"]},
        "timeout": {"type": "number"}
      },
      "required": ["url", "format"]
    }
  }
]
```

> 以上 tools/list 返回值为**基于 OpenCode 内置工具的高度推理**（来源：OpenCode CLI 文档）。实际 `mcaiBuiltin` 返回的工具列表可能略有不同（如添加/移除某些工具），但格式和工具类型一致。具体差异需要连接线上 VM 后通过 `tools/list` 或 `GET /mcp/upstreams/{id}/tools` 确认。

---

## 相关章节

- [VM 生命周期](02-vm-lifecycle.md) — MCP 服务在 VM 中的运行环境
- [核心数据流](../01-architecture/02-data-flow.md) — MCP 在数据流中的位置
- [完整 API 端点目录](../05-api/01-endpoint-catalog.md) — MCP REST API 端点
