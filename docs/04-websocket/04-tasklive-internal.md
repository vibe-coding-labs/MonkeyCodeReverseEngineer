---
description: TaskLive 内部 WebSocket 协议 — Backend 与 TaskFlow 之间的通信、TaskChunk 格式
protocol_version: based on chaitin/MonkeyCode 开源后端源码
confidence: high (后端到 TaskFlow 通信层已知；TaskFlow 内部闭源)
last_verified: 2026-06-27
---

# TaskLive 内部 WebSocket

> **状态:** ✅ 通信层完整已知
> **角色:** 后端与 TaskFlow 之间的内部 WebSocket 通道

## 端点

```
ws(s)://TASKFLOW_SERVER/internal/ws/task-live?id={taskID}&flush={bool}
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 任务 ID |
| `flush` | bool | 是否强制刷新缓冲区（`true`=立即推送） |

## 特性

- **无读限制**: `ws.SetReadLimit(-1)` — 内部通信数据量大，不限帧大小
- **后端 ↔ TaskFlow**: 后端从 TaskLive WS 接收 Agent 事件，转发给前端
- **每任务一个连接**: 每个 Task 对应一个 TaskLive WS 连接

## TaskChunk 结构体

```go
// backend/pkg/taskflow/vm.go — TaskFlow 通信数据单元
type TaskChunk struct {
    Data      []byte `json:"data,omitempty"`   // 事件数据（ACP JSON 序列化）
    Event     string `json:"event"`            // 事件类型标识
    Kind      string `json:"kind"`             // 子类型（如 "acp_event", "status", "error"）
    Timestamp int64  `json:"timestamp,omitempty"` // 毫秒时间戳
}
```

### 事件类型

| Event | Kind | 说明 |
|-------|------|------|
| `live` | `acp_event` | ACP 事件（agent_message_chunk 等） |
| `status` | `status` | 任务状态变更 |
| `error` | `error` | 任务执行错误 |
| `heartbeat` | — | 连接保活 |

## 通信流

```
VM Agent → ACP 事件流
  → TaskLive WS (内部)
    → 后端接收 TaskChunk
      → 包装为 TaskStreamMessage
        → 推送至前端 Task Stream WS
        → 写入 Redis（历史回放）
```

### 后端接收处理代码

```go
// backend/pkg/taskflow/vm.go — 解析 TaskLive 数据
func (v *VM) handleTaskLive(ctx context.Context, conn *websocket.Conn) error {
    conn.SetReadLimit(-1) // 内部通信，不限大小
    
    for {
        _, data, err := conn.ReadMessage()
        if err != nil {
            return fmt.Errorf("tasklive read: %w", err)
        }
        
        var chunk TaskChunk
        if err := json.Unmarshal(data, &chunk); err != nil {
            continue // 跳过无法解析的帧
        }
        
        switch chunk.Kind {
        case "acp_event":
            // 解析 ACP 事件
            var event ACPEvent
            json.Unmarshal(chunk.Data, &event)
            
            // 推送到前端 Task Stream WS
            v.pushToFrontend(event)
            
            // 写入 Redis（用于历史回放）
            v.saveToRedis(chunk)
            
        case "status":
            v.handleStatusChange(chunk.Event, chunk.Data)
            
        case "error":
            v.handleTaskError(chunk.Data)
        }
    }
}
```

### TaskStreamMessage 格式（前端接收）

```go
// 后端转发给前端的包装格式
type TaskStreamMessage struct {
    Event     string          `json:"event"`     // 与 TaskChunk.Event 一致
    Data      json.RawMessage `json:"data"`      // 原始 ACP JSON 数据（Base64 或原始 JSON）
    Kind      string          `json:"kind"`      // "acp_event"
    Timestamp int64           `json:"timestamp"` // 毫秒时间戳
}
```

## TaskLive 与其他 WS 的关系

```
┌─────────────┐    TaskLive WS     ┌──────────────┐
│  TaskFlow   │◄──────────────────►│    Backend    │
│  (VM Agent) │    Internal        │    (Go)       │
└─────────────┘                    └──────┬───────┘
                                          │
                             ┌────────────┼────────────┐
                             │            │            │
                      Task Stream WS   Terminal WS   Control WS
                             │            │            │
                        ┌────▼────┐  ┌───▼────┐  ┌───▼────┐
                        │ 前端    │  │ 前端   │  │ 前端   │
                        └─────────┘  └────────┘  └────────┘
```

## 与直接 ACP 信号的关系

后端内部有一个信号中继机制，在 TaskFlow 不可用时直接捕获 ACP 事件：

```
┌───────────────┐   ACP event    ┌────────────┐   TaskChunk    ┌──────────────┐
│  TaskFlow VM  │ ──────────────►│    Hub     │───────────────►│   Backend    │
│  (Agent)      │                │ (signal)   │                │  (Go)        │
└───────────────┘                └────────────┘                └──────┬───────┘
                                                                      │
                                                                 前端 WS
```

---

## 附录：逆向分析代码示例

### 附录 A: TaskLive 连接测试 (Python)
```python
# 模拟后端接收 TaskLive 事件
import asyncio
import websockets
import json

TASKFLOW_WS = "wss://taskflow.internal/monkeycode-ai/internal/ws/task-live"

async def dump_tasklive_events(task_id: str):
    """连接到 TaskLive WS 并输出所有事件"""
    uri = f"{TASKFLOW_WS}?id={task_id}&flush=true"
    
    async with websockets.connect(uri) as ws:
        print(f"[TaskLive] Connected to {task_id}")
        while True:
            raw = await ws.recv()
            chunk = json.loads(raw)
            
            print(f"[{chunk.get('kind','?')}] " +
                  f"event={chunk.get('event','?')} " +
                  f"ts={chunk.get('timestamp','?')}")
            
            if chunk.get("kind") == "acp_event":
                data = json.loads(chunk["data"])
                print(f"  ACP: {data.get('type', '?')}")

asyncio.run(dump_tasklive_events("task-uuid-here"))
```

### 附录 B: Go TaskChunk 到前端消息的转换
```go
// 后端推送逻辑 — TaskChunk → TaskStreamMessage
func (v *VM) pushToFrontend(chunk TaskChunk) {
    msg := &TaskStreamMessage{
        Event:     chunk.Event,
        Data:      chunk.Data,
        Kind:      chunk.Kind,
        Timestamp: chunk.Timestamp,
    }
    
    // 序列化
    payload, _ := json.Marshal(msg)
    
    // 推送到前端 WS
    select {
    case v.frontendChan <- payload:
        // 成功
    default:
        // 前端通道满，丢弃
        log.Warn("frontend channel full, dropping event")
    }
    
    // 写入 Redis（TTL = 任务最大时长 + 1h）
    redis.Set(f"task:{v.taskID}:events:{chunk.Timestamp}", 
              payload, 4*time.Hour)
}
```

---

## 相关章节

- [TaskFlow 架构定位](../06-vm-taskflow/01-architecture.md) — TaskLive 在架构中的位置
- [Task Stream WebSocket](01-task-stream.md) — 用户端的流式通道
- [VM 生命周期](../06-vm-taskflow/02-vm-lifecycle.md) — TaskLive 在 VM 生命周期中的角色