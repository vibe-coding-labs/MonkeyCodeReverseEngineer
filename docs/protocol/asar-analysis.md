> ⚠️ **此文件为原始分析档案** — 内容已被 docs/ 下结构化章节覆盖。详见 [docs/protocol/README.md](./README.md)。

# MonkeyCode Electron 客户端 ASAR 分析

## 概述

MonkeyCode 桌面客户端是一个极薄的 Electron 壳，所有前端代码从远程加载。

## 关键发现

### Electron 配置

- **appId**: `com.monkeycode.desktop`
- **Electron 版本**: ^35.1.5
- **ASAR**: 启用（但仅 5.8KB，几乎为空壳）

### main.cjs 分析

- **默认加载 URL**: `https://monkeycode-ai.com`
- **启动路径**: `/console/`（可通过 `MONKEYCODE_DESKTOP_START_PATH` 覆盖）
- **开发模式**: 加载 `http://localhost:11180`（Vite dev server）
- **本地构建模式**: `MONKEYCODE_LOAD_LOCAL_DIST=1` 时加载 `web-dist/index.html`

### 安全配置

- `contextIsolation: true` — 上下文隔离启用
- `nodeIntegration: false` — Node 集成禁用
- `sandbox: false` — 沙箱禁用（为兼容完整 Web 应用）

### 环境变量覆盖

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `MONKEYCODE_DESKTOP_URL` | 后端地址 | `https://monkeycode-ai.com` |
| `MONKEYCODE_DESKTOP_START_PATH` | 启动路径 | `/console/` |
| `MONKEYCODE_LOAD_LOCAL_DIST` | 加载本地构建 | `0` |
| `VITE_DEV_SERVER_URL` | 开发服务器地址 | `http://localhost:11180` |

### preload.cjs

仅包含 `"use strict"` 和注释，未暴露任何 API 到渲染进程。

### 结论

Electron 客户端是纯 Web 壳，所有业务逻辑在 `monkeycode-ai.com` 上运行。逆向目标应聚焦于：
1. GitHub 源码中的后端 Go 代码
2. Swagger 生成的 `frontend/src/api/Api.ts`（170KB，6420 行）
3. 实际网络通信（HTTP + WebSocket）
