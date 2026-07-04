---
description: 语音识别 SSE 协议 — Doubao 流式 ASR 2.0 完整分析、双向 WS 协议、PCM 音频处理链
protocol_version: based on chaitin/MonkeyCode + 火山引擎开放文档
confidence: high
last_verified: 2026-06-28
---

# 语音转文字（源码增强版）

> **后端引擎:** 火山引擎豆包流式语音识别 2.0（SAUC bigmodel）
> **WebSocket 端点:** `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`
> **HTTP 端点:** `POST /api/v1/users/tasks/speech-to-text`
> **核心发现:** PCM S16LE 16kHz mono → Doubao WS 双向流 → SSE 识别结果

## 1. 音频编码格式

```go
// backend/pkg/doubao/type.go — 双向流式 ASR 音频元数据
type audioMeta struct {
    Format  string `json:"format,omitempty"`  // "pcm"
    Codec   string `json:"codec,omitempty"`   // "raw"
    Rate    int    `json:"rate,omitempty"`    // 16000
    Bits    int    `json:"bits,omitempty"`    // 16
    Channel int    `json:"channel,omitempty"` // 1
}
```

| 属性 | 值 | 说明 |
|------|-----|------|
| Format | `"pcm"` | 线性 PCM 编码 |
| Codec | `"raw"` | 无压缩原始数据 |
| Rate | `16000` | 16kHz 采样率 |
| Bits | `16` | 16-bit signed little-endian |
| Channel | `1` | 单声道 |

> **编码总结:** PCM S16LE, 16kHz, 单声道
> **数据速率:** 16000 Hz × 16 bits × 1 channel = 256 kbps = 32 KB/s

## 2. HTTP 端点

```http
POST /api/v1/users/tasks/speech-to-text
Cookie: monkeycode_ai_session=xxx
Content-Type: application/octet-stream

<raw PCM S16LE 16kHz mono audio data>
```

### Python 客户端示例

```python
import requests

def speech_to_text(audio_bytes: bytes, session_cookie: str) -> str:
    """将 PCM 音频发送到 MonkeyCode STT 端点"""
    resp = requests.post(
        "https://monkeycode-ai.com/api/v1/users/tasks/speech-to-text",
        data=audio_bytes,
        headers={
            "Content-Type": "application/octet-stream",
            "Cookie": f"monkeycode_ai_session={session_cookie}",
        },
        stream=True,
    )
    result = ""
    for line in resp.iter_lines():
        if line.startswith(b"data: "):
            data = json.loads(line[6:])
            if data.get("type") == "result" and data.get("is_final"):
                result += data.get("text", "")
    return result
```

## 3. SSE 响应格式

```
event: recognition
data: {"type":"result","text":"你","is_final":false,"user_id":"uuid"}

event: recognition  
data: {"type":"result","text":"你好","is_final":false,"user_id":"uuid"}

event: recognition
data: {"type":"result","text":"你好世界","is_final":true,"user_id":"uuid"}

event: end
data: {"type":"end"}

event: error
data: {"type":"error","error":"识别失败","code":40001}
```

| 事件 | is_final | 说明 |
|------|----------|------|
| `recognition` | false | 部分识别结果（随时间越来越完整）|
| `recognition` | true | 最终识别结果 |
| `end` | — | 识别完成（无更多数据）|
| `error` | — | 识别失败，含 code 字段 |

## 4. 内部 Doubao 双向 WS 协议

```go
// pkg/doubao/doubao.go — Doubao ASR 客户端
type FullClientRequest struct {
    App    appIdentifier `json:"app"`
    Audio  audioMeta     `json:"audio"`
    // 后续帧为二进制 PCM 数据
}

type appIdentifier struct {
    AppID  string `json:"appid"`   // MonkeyCode 在火山引擎的 appid
    Token  string `json:"token"`   // 访问令牌
    UserID string `json:"user_id"` // 当前登录用户 UUID
}
```

```
后端收到前端 HTTP POST (含 PCM 二进制数据)
    │
    ├── 1. 解析音频数据（application/octet-stream）
    │
    ├── 2. 封装第一个 WS 帧: JSON 帧 (sequence=1)
    │     FullClientRequest{App{}, Audio{Format:"pcm", Rate:16000}}
    │
    ├── 3. 发送后续音频帧: 二进制帧 (sequence=2,3,4...)
    │     raw PCM S16LE 数据分片
    │
    ├── 4. 目标: wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
    │
    └── 5. 接收识别结果 → 转换 SSE → 流回前端
```

### 音频分片流程

```go
// 伪代码 — 音频分片与传输
func streamAudioToDoubao(wsConn *websocket.Conn, audioData []byte, chunkSize int) {
    // 帧 1: JSON 元数据
    wsConn.WriteJSON(FullClientRequest{
        App: appIdentifier{AppID: "monkeycode", Token: "xxx"},
        Audio: audioMeta{Format: "pcm", Codec: "raw", Rate: 16000, Bits: 16, Channel: 1},
    })

    // 帧 2-N: 二进制 PCM 数据（分片发送）
    for i := 0; i < len(audioData); i += chunkSize {
        end := i + chunkSize
        if end > len(audioData) {
            end = len(audioData)
        }
        wsConn.WriteMessage(websocket.BinaryMessage, audioData[i:end])
        time.Sleep(20 * time.Millisecond) // 模拟实时流
    }
}
```

## 5. 音频处理参数

### 编码转换

```bash
# 从 MP3/WAV 转为 PCM S16LE 16kHz mono
ffmpeg -i input.mp3 -acodec pcm_s16le -ar 16000 -ac 1 -f s16le output.pcm

# 从麦克风录制（Linux）
arecord -f S16_LE -r 16000 -c 1 -d 5 audio.pcm

# 验证 PCM 文件
ffprobe -f s16le -sample_rate 16000 -channels 1 -show_streams audio.pcm
```

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| 采样率 | 16000 Hz | 16kHz 标准语音采样率 |
| 位深 | 16-bit | S16LE（小端有符号）|
| 声道 | 1（单声道）| 多声道会被混音 |
| 数据速率 | 32 KB/s | 每秒钟 32KB 原始 PCM 数据 |
| 音频格式 | WAV / PCM | 需先解码为 PCM |
| 分片大小 | 640 bytes | 20ms 音频帧（常见语音引擎分片大小）|

### curl 发送示例

```bash
# 从文件发送 PCM 音频
curl -X POST https://monkeycode-ai.com/api/v1/users/tasks/speech-to-text \
  -H "Content-Type: application/octet-stream" \
  -H "Cookie: monkeycode_ai_session=xxx" \
  --data-binary @audio.pcm \
  --no-buffer

# 通过代理转发
curl -X POST http://localhost:9090/api/v1/users/tasks/speech-to-text \
  -H "Content-Type: application/octet-stream" \
  --data-binary @audio.pcm
```

## 6. 代理层传输

```typescript
// server.ts — Express 中间件支持 10MB 请求体
app.use(express.json({ limit: "10mb" }))
```

代理层直接转发二进制数据，不做音频转码或格式转换。

## 7. 完整请求/响应示例

```python
# 端到端语音识别调用
import requests, json, struct

def record_and_transcribe(duration_sec=5) -> str:
    """模拟录音并转写"""
    import pyaudio
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                    input=True, frames_per_buffer=1024)
    frames = []
    for _ in range(0, int(16000 / 1024 * duration_sec)):
        frames.append(stream.read(1024))
    audio_bytes = b''.join(frames)

    resp = requests.post(
        "https://monkeycode-ai.com/api/v1/users/tasks/speech-to-text",
        data=audio_bytes,
        headers={"Content-Type": "application/octet-stream",
                 "Cookie": "monkeycode_ai_session=xxx"},
        stream=True,
    )
    result = ""
    for line in resp.iter_lines():
        if line and line.startswith(b"data: "):
            data = json.loads(line[6:])
            if data.get("type") == "end":
                break
            if data.get("type") == "result" and data.get("is_final"):
                result = data.get("text", "")
    return result
```

## 8. WebSocket 帧分析

```json
// WS → 后端: FullClientRequest (JSON 帧)
{"app":{"appid":"monkeycode","token":"xxx"},"audio":{"format":"pcm","rate":16000,"bits":16,"channel":1}}

// WS → 后端: 后续帧（二进制 PCM 分片）
<binary: PCM S16LE 16kHz mono chunk>

// 后端 → WS: 识别结果（JSON 帧）
{"type":"result","text":"你好世界","is_final":true}
```

---

## 相关章节

- [ACP 事件参考](06-acp-event-reference.md) — 全部事件类型
- [VM 内部 Agent](../06-vm-taskflow/04-agent-internals.md) — Agent 运行环境
- [认证自动化](../02-auth/07-auth-automation.md) — Session Cookie 管理
