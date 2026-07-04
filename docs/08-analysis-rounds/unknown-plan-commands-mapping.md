---
description: plan 与 available_commands_update 事件映射分析 — 从当前丢弃到映射方案
protocol_version: based on proxy/src/task-runner.ts, proxy/src/api-routes.ts
confidence: high
last_verified: 2026-07-05
---

# plan 与 available_commands_update 映射分析

> **所属分类:** P0 缺口 #6 — plan / available_commands_update 未映射
> **当前行为:** 两个事件在 Chat API 和 Responses API 中均被丢弃（仅 console.log）
> **目标:** 评估是否需要映射，给出映射方案

## 1. 当前行为

```typescript
// proxy/src/task-runner.ts:325-337
case "plan": {
  const planData = acp.steps || acp
  console.log(`[TaskRunner] plan:`, JSON.stringify(planData).slice(0, 200))
  break
}

case "available_commands_update": {
  const commandsData = acp.commands || acp
  console.log(`[TaskRunner] available_commands:`, JSON.stringify(commandsData).slice(0, 200))
  break
}
```

在 Responses API (`api-routes.ts`) 中也同样被忽略——`streamTaskRaw` 透传所有 ACP 事件，但 `api-routes.ts` 的 `onEvent` 回调只处理了 `agent_message_chunk`、`agent_thought_chunk`、`tool_call`、`tool_call_update` 四种。

## 2. plan 事件

### 2.1 预期数据结构

```json
{
  "type": "plan",
  "steps": [
    {"step": 1, "action": "read_file", "target": "src/index.ts", "status": "pending"},
    {"step": 2, "action": "analyze", "target": "code structure", "status": "pending"},
    {"step": 3, "action": "write_file", "target": "src/new.ts", "status": "pending"}
  ]
}
```

### 2.2 建议映射

```typescript
case "plan": {
  const planData = acp.steps || acp
  let planText = ""
  if (Array.isArray(planData)) {
    planText = planData.map((s: any) =>
      `  ${s.status === "completed" ? "✅" : s.status === "running" ? "🔄" : "⏳"} ${s.action}: ${s.target || ""}`
    ).join("\n")
    planText = `[计划]\n${planText}`
  } else {
    planText = `[计划] ${JSON.stringify(planData).slice(0, 100)}`
  }

  onChunk({
    id: chatId,
    object: "chat.completion.chunk",
    created: now,
    model: "monkeycode",
    choices: [{ index: 0, delta: { content: `\n${planText}\n` }, finish_reason: null }],
  })
  break
}
```

**映射理由:** 执行计划对用户可见有价值——让用户知道 Agent 接下来要做什么。当前 Chat API 把 tool_call 编为文本，plan 作为上下文同样可以。

## 3. available_commands_update 事件

### 3.1 预期数据结构

```json
{
  "type": "available_commands_update",
  "commands": [
    {"name": "read", "description": "读取文件内容", "enabled": true},
    {"name": "write", "description": "写入文件", "enabled": true},
    {"name": "run", "description": "运行命令", "enabled": false}
  ]
}
```

### 3.2 建议映射

**Chat API:** 仅当有命令状态变化时可选择映射，但通常对最终用户无直接价值。

```typescript
case "available_commands_update": {
  // 低价值事件，保持 console.log 日志级别即可
  // 仅在 DEBUG 模式下映射到 SSE
  if (process.env.DEBUG_ACP) {
    onChunk({
      id: chatId,
      object: "chat.completion.chunk",
      created: now,
      model: "monkeycode",
      choices: [{ index: 0, delta: { content: `[可用命令] ${JSON.stringify(acp.commands)}` }, finish_reason: null }],
    })
  }
  break
}
```

**映射理由:** 可用命令列表主要是 Agent 内部状态，对最终用户无直接价值。仅在 DEBUG 模式下输出。

## 4. 价值评估矩阵

| 事件 | Chat API 映射价值 | Responses API 映射价值 | 建议 |
|------|------------------|----------------------|------|
| `plan` | 🟡 中 — 用户可见执行计划 | 🟡 中 — 同上 | 作为文本注入 delta.content |
| `available_commands_update` | 🔴 低 — Agent 内部状态 | 🔴 低 — 同上 | 仅 DEBUG 模式 |
| `tool_call_update` | 🟢 高 — 工具执行进度 | 🟢 高 — 已部分支持 | 标准 tool_calls 格式 |

## 5. 改进建议

1. **plan 事件 → 文本映射** — 用 emoji + action + target 格式转为可读文本，注入 Chat API 的 delta.content
2. **available_commands_update → 仅日志** — 保持当前 console.log 策略，加 DEBUG 环境变量控制
3. **Responses API 同样可以透传 plan** — 作为自定义事件发送（如 `response.plan_updated`）

## 6. 总结

| 发现 | 详情 |
|------|------|
| **plan 事件值得映射** | 用户可见 Agent 执行计划，体验提升 |
| **available_commands_update 不值得映射** | Agent 内部状态，对用户无直接价值 |
| **两个事件在 Responses API 也被忽略** | 可在自定义事件中透传 |

---

**更新状态:** ✅ 已分析完成
**更新文件:** docs/08-analysis-rounds/unknown-gaps-index.md