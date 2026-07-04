# WebSocket 帧数据示例

> **最后更新:** 2026-06-27
> **用途:** 记录 MonkeyCode 各 WebSocket 通道的完整帧格式

---

## 1. Task Stream WS — ACP 事件

### 1.1 agent_message_chunk

```json
// 方向: Server → Client
// Agent 输出文本内容
{
    "type": "agent_message_chunk",
    "text": "我来分析这个代码文件。首先，让我看看文件内容。",
    "content": "我来分析这个代码文件。首先，让我看看文件内容。"
}
```

### 1.2 agent_thought_chunk

```json
// 方向: Server → Client
// Agent 的推理/思考过程
{
    "type": "agent_thought_chunk",
    "text": "用户要求我审查一个Python脚本。我需要检查代码质量、潜在bug和最佳实践。"
}
```

### 1.3 tool_call

```json
// 方向: Server → Client
// Agent 开始调用工具
{
    "type": "tool_call",
    "tool_name": "view",
    "tool_input": "{\"file_path\": \"/workspace/main.py\", \"offset\": 0, \"limit\": 100}",
    "tool_id": "call_abc123"
}
```

### 1.4 tool_call_update

```json
// 方向: Server → Client
// 工具调用状态更新（5 字段完整确认）
{
    "type": "tool_call_update",
    "tool_name": "bash",
    "tool_input": "python3 test.py",
    "delta": "...",
    "status": "running"   // running | success | error | completed | done
}

// 工具执行成功
{
    "type": "tool_call_update",
    "tool_name": "bash",
    "status": "success",
    "tool_input": "python3 test.py",
    "extra": {
        "exit_code": 0,
        "stdout": "All tests passed!",
        "stderr": ""
    }
}
```

### 1.5 usage_update

```json
// 方向: Server → Client
// Token 用量更新（全局或累积）
{
    "type": "usage_update",
    "input_tokens": 150,
    "output_tokens": 42,
    "total_tokens": 192
}
```

### 1.6 plan

```json
// 方向: Server → Client
// 执行计划
{
    "type": "plan",
    "steps": [
        {"title": "读取文件", "status": "completed"},
        {"title": "分析代码", "status": "in_progress"},
        {"title": "生成报告", "status": "pending"}
    ]
}
```

### 1.7 available_commands_update

```json
// 方向: Server → Client
// 当前可用的命令列表
{
    "type": "available_commands_update",
    "commands": ["bash", "view", "write", "edit", "grep", "glob", "ls"]
}
```

### 1.8 task-ended

```json
// 方向: Server → Client
// 任务正常结束
{
    "type": "task-ended"
}
```

### 1.9 task-error

```json
// 方向: Server → Client
// 任务执行出错
{
    "type": "task-error",
    "error": "模型调用失败: rate limit exceeded",
    "code": "rate_limit_error"
}
```

---

## 2. Task Control WS — 控制事件

### 2.1 前端发送控制命令

```json
// 方向: Client → Server
// 停止任务
{
    "type": "stop",
    "task_id": "task-uuid-xxx"
}

// 获取任务信息
{
    "type": "task_info",
    "task_id": "task-uuid-xxx"
}

// 重置任务
{
    "type": "reset",
    "task_id": "task-uuid-xxx"
}

// 心跳
{
    "type": "heartbeat",
    "task_id": "task-uuid-xxx"
}
```

### 2.2 后端响应

```json
// 方向: Server → Client
// 任务已停止
{
    "type": "stopped",
    "task_id": "task-uuid-xxx",
    "stopped_at": 1715299200
}

// 任务信息
{
    "type": "task_info_response",
    "data": {
        "task_id": "task-uuid-xxx",
        "status": "running",
        "vm_id": "vm-uuid-xxx",
        "started_at": 1715299200,
        "elapsed_seconds": 120
    }
}

// 心跳回复
{
    "type": "pong",
    "timestamp": 1715299200
}
```

---

## 3. Terminal WS — TTY 帧

### 3.1 二进制帧（TTY 数据）

```
// 方向: Server ↔ Client（双向）
// TTY 数据流（UTF-8 编码 + ANSI 转义序列）

// Shell 输出（带颜色）— 二进制帧
\x1b[32m~\x1b[0m \x1b[1m$\x1b[0m ls -la\n
total 128\ndrwxr-xr-x 2 root root  4096 Jun  1 12:00 .\n
-rw-r--r-- 1 root root 10240 Jun  1 12:00 main.py\n

// 用户键盘输入 — 二进制帧
ls -la /workspace\n

// 程序输出（带 ANSI 清屏）
\x1b[2J\x1b[1;1H[INFO] Starting build...\n
[INFO] Compilation successful!\n
```

### 3.2 文本帧（控制事件）

```json
// 方向: Client → Server
// 终端 resize
{
    "type": "resize",
    "cols": 120,
    "rows": 40
}

// 方向: Client → Server
// 终端关闭
{
    "type": "close"
}
```

### 3.3 Keepalive 帧

```
// 方向: Server → Client
// WebSocket Ping 帧 (15s 间隔)
Ping: "keepalive"

// 方向: Client → Server
// WebSocket Pong 帧（自动回复）
Pong: ""
```

---

## 4. TaskLive 内部 WS — TaskChunk

### 4.1 ACP 事件转发

```json
// 方向: TaskFlow → Backend
// ACP 事件通过 TaskLive WS 传输
{
    "data": "eyJ0eXBlIjoiYWdlbnRfbWVzc2FnZV9jaHVuayIsInRleHQiOiLmiJHomL/lr7zlkb3kuo7ov5nkuKrkuK3mlofml6DvvIwifQ==",
    "event": "live",
    "kind": "acp_event",
    "timestamp": 1715299200123
}
// 注: data 字段是 Base64 编码的 ACP JSON
```

### 4.2 任务状态变更

```json
{
    "data": "{\"status\":\"running\",\"elapsed\":15}",
    "event": "status",
    "kind": "status",
    "timestamp": 1715299200150
}
```

### 4.3 错误通知

```json
{
    "data": "{\"code\":\"vm_error\",\"msg\":\"VM creation failed: insufficient resources\"}",
    "event": "error",
    "kind": "error",
    "timestamp": 1715299200200
}
```

---

## 5. 语音识别 SSE

### 5.1 部分识别结果

```
// 方向: Server → Client
// SSE 流（不是 WebSocket，但类似实时推送格式）

event: recognition
data: {"type":"result","text":"你好","is_final":false,"user_id":"uuid","timestamp":1715299200000}

event: recognition
data: {"type":"result","text":"你好世界","is_final":false,"user_id":"uuid","timestamp":1715299210000}
```

### 5.2 最终结果

```
event: recognition
data: {"type":"result","text":"你好世界，今天天气不错","is_final":true,"user_id":"uuid","timestamp":1715299220000}

event: end
data: {"type":"end"}
```

### 5.3 识别错误

```
event: error
data: {"type":"error","error":"识别失败: 音频格式不支持"}
```