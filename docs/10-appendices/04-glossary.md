---
description: 术语表（源码增强版）— 100+ 术语, ACP 事件速查, 环境变量速查, Go/TS 结构体索引
protocol_version: general
confidence: high
last_verified: 2026-06-28
---

# 术语表（源码增强版）

> **覆盖范围:** 全部 Go + TypeScript 源码中的关键术语

## 首字母缩略词

| 缩写 | 全称 | 说明 |
|------|------|------|
| **ACP** | Agent-Client-Protocol | Agent↔客户端通信协议，9 种事件类型 |
| **ASAR** | Atom Shell Archive | Electron 打包格式 |
| **MCP** | Model Context Protocol | Agent 工具调用协议（JSON-RPC 2.0, port 65510）|
| **SCaptcha** | Security Captcha | 长亭科技验证码服务 |
| **SSE** | Server-Sent Events | HTTP 长连接单向数据流（`data: {...}\n\n`）|
| **STT** | Speech-To-Text | 语音识别（Doubao ASR 2.0）|
| **TTL** | Time-To-Live | Redis/Cookie 过期时间 |
| **VM** | Virtual Machine | Docker 容器（AI Agent 运行环境）|

## MonkeyCode 特有术语

| 术语 | 说明 |
|------|------|
| **access_level** | 模型访问等级: `basic` / `pro` / `ultra` |
| **AccountPool** | 多账号管理类，HTTP 共享 + WS 独占双模式 |
| **AuthManager** | 认证管理器，负责 Session Cookie 获取、缓存、刷新 |
| **cli_name** | Agent 类型标识: `codex` / `claude` / `MCAIReview` / `opencode` |
| **ConversationManager** | 对话管理器，30 分钟 TTL + 5 分钟清理循环 |
| **go-cap** | 后端闭源验证码模块，50×32 网格图像点击 |
| **image_id** | VM 容器镜像 UUID（任务创建必需参数）|
| **interface_type** | LLM 接口类型: `openai_chat` / `openai_responses` / `anthropic` |
| **mcaiBuiltin** | 容器内 MCP 服务端口 65510 |
| **ModelManager** | 模型管理类（5 分钟缓存 + 6 层模型 ID 回退）|
| **P0/P1 告警** | 号池告警阈值: P0(<50%), P1(<70%), P2(错误率>20%) |
| **TaskRunner** | 任务执行器（创建→WS→ACP→SSE）|
| **TeamPolicy** | 团队策略: 并发 3 / 休眠 900s / 回收 3 天 |

## 环境变量速查

```bash
# 认证（二选一）
MONKEYCODE_SESSION_COOKIE=xxx     # Session Cookie（推荐）
MONKEYCODE_EMAIL=xxx              # 密码登录（需 + PASSWORD）
MONKEYCODE_PASSWORD=xxx

# 代理
MONKEYCODE_BASE_URL=https://monkeycode-ai.com
PROXY_PORT=9090
ACCOUNT_POOL_FILE=./accounts.json

# 任务
MONKEYCODE_IMAGE_ID=uuid          # 必需
MONKEYCODE_TASK_TIMEOUT_MS=3600000
```

## ACP 事件速查

```json
// Agent 输出文本
{"type":"agent_message_chunk","text":"Hello"}        → delta.content

// Agent 思考过程
{"type":"agent_thought_chunk","text":"思考中..."}     → delta.content = "[Thinking] 思考中..."

// 工具调用
{"type":"tool_call","tool_name":"read_file","tool_input":"/etc/passwd"} → delta.content

// 用量
{"type":"usage_update","input_tokens":100,"output_tokens":50,"total_tokens":150}

// 任务结束
{"type":"task-ended"} → finish_reason:"stop"
```

## Go 结构体索引

```go
// Model — 模型实体
type Model struct {
    ID, Provider, ModelName, InterfaceType, BaseURL, APIKey string
    AccessLevel string // basic | pro | ultra
    Owner Owner       // private | team | public
}

// SubscriptionResp — 订阅响应
type SubscriptionResp struct {
    Plan      string     // basic | pro | ultra
    Source    string     // stripe | wechat | free
    ExpiresAt *time.Time
    AutoRenew bool
}

// TeamPolicy — 团队并发策略
type TeamPolicy struct {
    TaskConcurrencyLimit int // 默认 3
    SleepSeconds         int // 默认 900s
    RecycleSeconds       int // 默认 259200s (3天)
}
```

## TypeScript 接口索引

```typescript
// 核心模型接口
interface MonkeyCodeModel {
  id: string; provider: ModelProvider; model: string;
  interface_type: InterfaceType; access_level: AccessLevel;
  owner: OwnerType; is_free: boolean; is_default: boolean;
}

// 12 种提供商联合类型
type ModelProvider = "siliconflow" | "openai" | "ollama" | "deepseek"
  | "moonshot" | "azure_openai" | "baizhicloud" | "hunyuan"
  | "bailian" | "volcengine" | "gemini" | "other";

// ACP 事件通用格式
interface ACPSessionUpdate {
  type: string; text?: string; content?: string;
  input_tokens?: number; output_tokens?: number; total_tokens?: number;
}
```

---

## 相关章节

- [环境变量全集](03-environment-variables.md) — 完整变量表
- [ACP 事件参考](../04-websocket/06-acp-event-reference.md) — 事件格式详解
- [错误码全集](02-error-codes.md) — 错误码速查
