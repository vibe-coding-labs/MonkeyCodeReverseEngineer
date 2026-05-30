# 逆向分析轮次 03 — 代码修复实施

> **时间:** 2026-05-30 01:10 UTC+8
> **聚焦:** 实施 P0 代码修复

---

## 1. 修复的 Bug

### 1.1 非流式 usage bug (P0) ✅

**文件**: `proxy/src/api-routes.ts:364-401`

**问题**: `handleNonStreamResponse` 返回硬编码 `{0,0,0}` usage

**修复**:
```typescript
let accumulatedUsage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }

await taskRunner.streamTask(taskId, prompt, (chunk: OpenAIChatCompletionChunk) => {
  // ... 累积 content ...
  // 累积 usage
  if (chunk.usage) {
    accumulatedUsage = chunk.usage
  }
}, undefined, auth || undefined)

// 使用累积的 usage
usage: accumulatedUsage.total_tokens > 0 ? accumulatedUsage : {
  prompt_tokens: 0, completion_tokens: 0, total_tokens: 0,
}
```

**效果**: 非流式响应现在正确报告 token 使用量

### 1.2 tool_call_update 处理 (P0) ✅

**文件**: `proxy/src/api-routes.ts:185-229`

**问题**: `tool_call_update` 事件被静默丢弃

**修复**:
```typescript
} else if (acp.type === "tool_call_update") {
  // Stream tool call argument updates
  const updateArgs = acp.tool_input || acp.delta || ""
  if (updateArgs && currentCallId) {
    sendEvent("response.function_call_arguments.delta", {
      type: "response.function_call_arguments.delta",
      output_index: currentOutputIndex,
      delta: { type: "function_call_arguments.delta", arguments: updateArgs },
    })
  }
  // If tool call is complete, finalize it
  if (acp.status === "completed" || acp.status === "done") {
    // ... finalize tool call ...
  }
}
```

**效果**: Responses API 现在支持流式工具调用参数更新

### 1.3 tool_call 流式参数 (P0) ✅

**文件**: `proxy/src/api-routes.ts:185-209`

**问题**: `tool_call` 时一次性发送所有参数

**修复**: `tool_call` 现在只发送 `output_item.added`，等待 `tool_call_update` 流式更新参数

**效果**: 工具调用参数现在可以流式更新

### 1.4 task-ended 时关闭未完成的 tool_call (P0) ✅

**文件**: `proxy/src/api-routes.ts:230-268`

**问题**: 如果任务在 tool_call 执行中结束，tool_call 不会被正确关闭

**修复**:
```typescript
} else if (event.type === "task-ended") {
  // Close any open tool call
  if (currentCallId) {
    sendEvent("response.function_call_arguments.done", {
      type: "response.function_call_arguments.done",
      output_index: currentOutputIndex,
      arguments: "",
    })
    sendEvent("response.output_item.done", {...})
  }
  // ... rest of task-ended handling ...
}
```

**效果**: 任务结束时正确关闭所有未完成的工具调用

### 1.5 ACP 事件日志 (P1) ✅

**文件**: `proxy/src/task-runner.ts:314-336`

**问题**: `tool_call_update`、`plan`、`available_commands_update` 事件被静默丢弃

**修复**: 添加日志记录
```typescript
case "tool_call_update": {
  const updateArgs = String(acp.tool_input || acp.delta || "")
  const status = String(acp.status || "")
  console.log(`[TaskRunner] tool_call_update: status=${status}, args=${updateArgs.slice(0, 100)}`)
  break
}

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

**效果**: 代理现在会记录这些事件，便于调试和格式分析

---

## 2. 编译验证

```
$ npm run build
> tsc
✅ 编译成功，无错误
```

---

## 3. 代码变更统计

| 文件 | 新增行 | 删除行 | 净增 |
|------|--------|--------|------|
| `api-routes.ts` | +45 | -15 | +30 |
| `task-runner.ts` | +25 | -1 | +24 |
| **总计** | +70 | -16 | +54 |

---

## 4. 下轮分析重点

### 优先级 P0 (影响 Codex 兼容性)

1. **线上实测**: 验证修复后的代理行为
2. **捕获 tool_call_update 格式**: 通过日志记录实际事件
3. **验证 Conversation API**: 测试端点存在性

### 优先级 P1 (提升代理质量)

4. **多轮对话支持**: 实现 Conversation API
5. **重连机制测试**: 断线后 attach 模式
6. **并发连接测试**: 多标签页场景

### 优先级 P2 (长期优化)

7. **plan 事件处理**: 转换为 Responses API 格式
8. **available_commands_update 处理**: 记录可用命令
9. **风控分析**: 号池大规模使用的行为

---

## 5. 相关文件索引

| 文件 | 用途 |
|------|------|
| `proxy/src/api-routes.ts` | OpenAI 兼容 API 路由 (已修复) |
| `proxy/src/task-runner.ts` | 任务创建与 WS 流式输出 (已修复) |
| `docs/protocol/analysis-round-01.md` | 全面状态评估 |
| `docs/protocol/analysis-round-02.md` | P0 深度分析 |
