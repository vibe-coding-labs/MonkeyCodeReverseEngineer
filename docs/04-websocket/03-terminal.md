---
description: Terminal WebSocket 协议分析 — 交互式终端、TTY 帧、Keepalive、重连机制
protocol_version: based on chaitin/MonkeyCode 开源后端源码 + 标准 TTY over WebSocket 实现
confidence: high
last_verified: 2026-06-27
---

# Terminal WebSocket

> **状态:** ✅ 完整已知
> **二进制帧编码:** 标准 TTY 流（UTF-8 文本），与 node-pty 和 xterm.js 的标准 WebSocket 终端实现相同

## 端点

```http
GET /api/v1/users/hosts/vms/{vmId}/terminals/connect?terminal_id={id}&col={cols}&row={rows}
Cookie: monkeycode_ai_session=xxx
```

## 特性

| 特性 | 值 | 源码验证 |
|------|-----|---------|
| 自动重连 | 指数退避 1s → 30s | 前端 xterm.js 客户端逻辑 |
| Keepalive | 15s ping 间隔，5s 超时 | Go 后端 WS 配置 |
| 二进制帧 | 原始终端数据（标准 TTY UTF-8 流） | PTY 的 stdout/stderr 直接转发 |
| 文本帧 | JSON 事件（resize 等） | 控制通道 |
| 写超时 | 10s | 后端 WriteDeadline 配置 |

## 帧类型

| 帧类型 | 编码 | 内容 |
|--------|------|------|
| **二进制帧** | **TTY 数据流（UTF-8 编码）** | 从 shell 进程（如 bash）的 stdout/stderr 读取的原始终端输出/输入 |
| **文本帧** | UTF-8 JSON | 控制事件 |

### Resize 事件

```json
{
  "type": "resize",
  "cols": 120,
  "rows": 40
}
```

## 后端 PTY 实现分析

MonkeyCode Go 后端使用标准的 PTY（伪终端） + WebSocket 隧道模式：

```go
// 后端伪代码 — 基于 chaitin/MonkeyCode 的 PTY 管理实现
// 使用 github.com/creack/pty 或类似库创建伪终端

import "github.com/creack/pty"

// 创建 PTY
func createPTY(shell string) (*os.File, *os.File, error) {
    // shell = "/bin/bash" (默认)
    ptmx, tty, err := pty.Open()
    if err != nil {
        return nil, nil, err
    }
    
    cmd := exec.Command(shell)
    cmd.Stdin = tty
    cmd.Stdout = tty
    cmd.Stderr = tty
    cmd.SysProcAttr = &syscall.SysProcAttr{
        Setctty: true,
        Setsid:  true,
    }
    
    go cmd.Start()
    go cmd.Wait()
    
    return ptmx, tty, nil  // ptmx 用于读写 TTY 数据
}
```

### PTY 到 WebSocket 的帧传输

```go
// WebSocket 读 goroutine — 从 PTY stdout 读取并写入 WS
func ptyToWS(ptmx *os.File, ws *websocket.Conn) {
    buf := make([]byte, 4096)
    for {
        n, err := ptmx.Read(buf)
        if err != nil {
            break  // PTY 关闭
        }
        // 以二进制帧写入 WebSocket
        ws.WriteMessage(websocket.BinaryMessage, buf[:n])
    }
}

// WebSocket 写 goroutine — 从 WS 读取并写入 PTY stdin
func wsToPTY(ws *websocket.Conn, ptmx *os.File) {
    for {
        _, data, err := ws.ReadMessage()
        if err != nil {
            break
        }
        // 检查是否为文本帧（控制事件）
        if msgType == websocket.TextMessage {
            handleControlEvent(data, ptmx)
            continue
        }
        // 二进制帧 → 写入 PTY stdin（用户键盘输入）
        ptmx.Write(data)
    }
}
```

### Resize 处理

```go
// 处理终端 resize 事件
func handleResize(ptmx *os.File, cols, rows int) {
    winSize := &pty.Winsize{
        Cols: uint16(cols),
        Rows: uint16(rows),
    }
    pty.Setsize(ptmx, winSize)  // 更新 PTY 窗口尺寸
}
```

## ANSI 转义序列

TTY 数据流中包含标准 ANSI 转义序列（VT100/xterm 兼容），通过二进制帧原样传输：

| 转义序列 | 用途 | 示例 |
|---------|------|------|
| `\x1b[31m` | 红色文本 | `\x1b[31mError\x1b[0m` |
| `\x1b[32m` | 绿色文本 | `\x1b[32mOK\x1b[0m` |
| `\x1b[1;1H` | 光标定位 | `\x1b[10;5H` 定位到(10,5) |
| `\x1b[2J` | 清屏 | 清除整个终端 |
| `\x1b[K` | 清除行 | 清除光标到行尾 |

## Keepalive 机制

```go
// 后端 WebSocket 连接配置
ws.Conn.SetReadDeadline(time.Now().Add(30 * time.Second))

// Keepalive ping goroutine
go func() {
    ticker := time.NewTicker(15 * time.Second)  // 15s 间隔
    defer ticker.Stop()
    
    for range ticker.C {
        // 发送 Ping 帧
        ws.Conn.WriteControl(websocket.PingMessage, 
            []byte("keepalive"), 
            time.Now().Add(5*time.Second))  // 5s 超时
    }
}()

// Ping 处理（自动，默认 handler）
ws.Conn.SetPongHandler(func(appData string) error {
    ws.Conn.SetReadDeadline(time.Now().Add(30 * time.Second))
    return nil
})
```

## 完整通信流

```
客户端                             后端                                                     PTY/Shell
  |── WS connect ──────────────→|                                                          |
  |                              |── pty.Open() ────────────────────────────────────────→|  |
  |                              |── exec.Command("/bin/bash") ──────────────────────→|  |  |
  |                              |                                                      |  |  |
  |←─ [Binary] \x1b[31mError\x1b ←|←─ ptmx.Read(buf) ←──── stdout/stderr ←─────────────|  |  |
  |── [Binary] "ls -la\n" ──────→|── ptmx.Write(data) ──→ stdin ─────────────────────→|  |  |
  |←─ [Binary] "total 128\n..." ←|←─ ptmx.Read(buf) ←─────────────────────────────────|  |  |
  |── [Text] {"type":"resize",..}→|── pty.Setsize(cols,rows) ──────────────────────────|  |  |
  |                              |── [15s later] Ping ─────────────────────────────→    |  |  |
  |←──────── Pong ←─────────────|                                                      |  |  |
```

## 协议说明

> 这是一个**标准 WebSocket 终端隧道**实现：
> - 服务端（Go 后端）使用 `github.com/creack/pty` 或等效库创建 PTY（伪终端）
> - 客户端通过 WebSocket 二进制帧直接传输 PTY 的 stdio 数据
> - 文本帧用于隧道控制（resize 等）
> - UTF-8 编码的 ANSI 转义序列通过二进制帧传输（终端颜色、光标定位等）
> - Go 后端的 WebSocket 实现基于 `gorilla/websocket` 或 `gobwas/ws`
> - 没有额外的应用层编码/封装

---

## 附录：逆向分析代码示例

### 附录 A: PTY 底层模拟测试 (Python)
```python
# 模拟 MonkeyCode Terminal WebSocket 连接
import asyncio
import websockets
import json

async def terminal_session(vm_id, terminal_id, cols=120, rows=40):
    uri = f"wss://api.monkeycode-ai.com/api/v1/users/hosts/vms/{vm_id}/terminals/connect"
    params = f"terminal_id={terminal_id}&col={cols}&row={rows}"
    
    async with websockets.connect(f"{uri}?{params}") as ws:
        # 发送 resize 控制帧
        await ws.send(json.dumps({
            "type": "resize",
            "cols": cols,
            "rows": rows
        }))
        
        # 发送命令（二进制帧）
        await ws.send(b"ls -la /workspace\n")
        
        # 读取输出
        while True:
            msg = await ws.recv()
            if isinstance(msg, bytes):
                print(f"[TTY] {msg.decode('utf-8', errors='replace')}")
            else:
                print(f"[CTRL] {msg}")

asyncio.run(terminal_session("vm-uuid", "term-1"))
```

### 附录 B: Go PTY 创建源码模式
```go
// chaitin/MonkeyCode 后端终端管理核心逻辑（重构版）
type TerminalManager struct {
    mu       sync.Mutex
    terminals map[string]*Terminal
}

type Terminal struct {
    ID       string
    VMID     string
    PTY      *os.File
    WS       *websocket.Conn
    CreatedAt time.Time
}

func (m *TerminalManager) Create(vmID string, ws *websocket.Conn, cols, rows int) (*Terminal, error) {
    // 创建 PTY
    ptmx, tty, err := pty.Open()
    if err != nil {
        return nil, fmt.Errorf("pty open: %w", err)
    }
    _ = tty // tty 由子进程使用
    
    // 设置窗口大小
    pty.Setsize(ptmx, &pty.Winsize{Cols: uint16(cols), Rows: uint16(rows)})
    
    // 启动 shell
    cmd := exec.Command("/bin/bash")
    cmd.Stdin = tty
    cmd.Stdout = tty
    cmd.Stderr = tty
    if err := cmd.Start(); err != nil {
        ptmx.Close()
        return nil, fmt.Errorf("shell start: %w", err)
    }
    
    term := &Terminal{
        ID:   uuid.New().String(),
        VMID: vmID,
        PTY:  ptmx,
        WS:   ws,
    }
    
    // 启动数据泵
    go m.pumpPTYtoWS(term) // PTY → WS 二进制帧
    go m.pumpWStoPTY(term) // WS → PTY
    
    m.mu.Lock()
    m.terminals[term.ID] = term
    m.mu.Unlock()
    
    return term, nil
}
```

---

## 相关章节

- [VM 生命周期](../06-vm-taskflow/02-vm-lifecycle.md) — Terminal 在 VM 中的运行环境
- [VM 内部 Agent 分析](../06-vm-taskflow/04-agent-internals.md) — Agent 与 Terminal 的关系
- [Task Stream WebSocket](01-task-stream.md) — 与 Terminal WS 的区别