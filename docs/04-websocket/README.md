# 第四章：WebSocket 协议

> **章节状态:** ✅ 所有文件已创建
> **最后更新:** 2026-06-25
> **覆盖范围:** 3 个 WebSocket 通道（Stream/Control/Terminal）、内部 TaskLive 通信、语音识别 SSE、ACP 事件参考

---

## 文件清单

| # | 文件 | 内容 | 完成度 |
|---|------|------|--------|
| 1 | [01-task-stream.md](01-task-stream.md) | Task Stream WebSocket（ACP 事件流、用户输入、重连机制） | ✅ 已完成 |
| 2 | [02-task-control.md](02-task-control.md) | Task Control WebSocket（RPC 调用：文件操作、重启、切换模型） | ✅ 已完成 |
| 3 | [03-terminal.md](03-terminal.md) | Terminal WebSocket（交互式终端、二进制帧、Keepalive） | 🟡 待扩充 |
| 4 | [04-tasklive-internal.md](04-tasklive-internal.md) | TaskLive 内部 WebSocket（Backend ↔ TaskFlow 通信） | ✅ 已完成 |
| 5 | [05-speech-to-text.md](05-speech-to-text.md) | 语音识别 SSE 流式输出 | 🟡 待扩充（需线上测试）|
| 6 | [06-acp-event-reference.md](06-acp-event-reference.md) | ACP 事件类型完整参考（格式、字段、示例） | ✅ 已完成 |
| 7 | **[07-conversation-lifecycle.md](07-conversation-lifecycle.md)** | **新增** Conversation Manager 生命周期（mode=attach 协议） | ✅ **新维度** |

---

## 核心发现

| 关键项 | 值 |
|--------|-----|
| Stream WS 端点 | `GET /api/v1/users/tasks/stream?id={taskId}&mode=new\|attach` |
| Control WS 端点 | `GET /api/v1/users/tasks/control?id={taskId}` |
| Terminal WS 端点 | `GET /api/v1/users/hosts/vms/{vmId}/terminals/connect` |
| ACP 事件类型 | agent_message_chunk / agent_thought_chunk / tool_call / tool_call_update / usage_update / plan / available_commands_update |
| 心跳间隔 | 10s（服务器端 ping） |
| 重连策略 | 指数退避 500ms → 1s → 2s → 4s → 8s |

---

## 相关章节

- [第三章：LLM 通信协议](../03-llm/README.md) — ACP 事件中的 LLM 输出内容
- [第六章：VM & TaskFlow](../06-vm-taskflow/README.md) — TaskLive 内部通信的上游
- [第七章：代理实现](../07-proxy/README.md) — 代理中的 ACP → OpenAI 事件映射