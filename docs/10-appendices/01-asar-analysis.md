---
description: Electron ASAR 逆向分析 — main.cjs 完整源码、preload.cjs、Electron 安全、4 种加载模式
protocol_version: based on app.asar extracted content (version 260324.1.22)
confidence: high
last_verified: 2026-06-28
---

# Electron ASAR 逆向分析

> **ASAR 大小:** 5.8KB（极薄壳）
> **Electron 版本:** ^35.1.5
> **核心发现:** 纯 Web 容器，所有业务逻辑在远程 SPA 中

## 1. ASAR 结构

```
monkeycode-desktop.asar (5.8KB)
├── package.json                   — monkeycode-desktop v260324.1.22
├── electron/main.cjs              — Electron 主进程 (138 行)
└── electron/preload.cjs           — 预加载脚本 (3 行)
```

## 2. main.cjs 完整源码

```javascript
// electron/main.cjs — 138 行，全部业务逻辑就是加载 URL
const { app, BrowserWindow, shell, dialog, Menu } = require("electron")
const fs = require("fs")
const path = require("path")

const isDev = !app.isPackaged
const DEFAULT_PROD_URL = "https://monkeycode-ai.com"
const ERR_ABORTED = -3
const START_PATH = process.env.MONKEYCODE_DESKTOP_START_PATH || "/console/"

function createWindow() {
  const win = new BrowserWindow({
    width: 1280, height: 800,
    minWidth: 900, minHeight: 640,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,  // 非沙箱：兼容完整 Web 应用
    },
  })

  // 4 种加载模式
  if (isDev) {
    win.loadURL(desktopEntryUrl(
      process.env.VITE_DEV_SERVER_URL || "http://localhost:11180"))
    win.webContents.openDevTools({ mode: "detach" })
  } else if (process.env.MONKEYCODE_LOAD_LOCAL_DIST === "1") {
    win.loadFile(localDistIndexHtml())
  } else {
    win.loadURL(desktopEntryUrl(
      process.env.MONKEYCODE_DESKTOP_URL || DEFAULT_PROD_URL))
  }
}
```

## 3. 关键功能分析

### 3.1 单实例锁

```javascript
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()  // 只允许一个实例
} else {
  app.on("second-instance", () => {
    const w = BrowserWindow.getAllWindows()[0]
    if (w) {
      if (w.isMinimized()) w.restore()
      w.focus()
    }
  })
}
```

### 3.2 加载失败处理

```javascript
win.webContents.on("did-fail-load", (_event, code, desc, url, isMainFrame) => {
  if (!isMainFrame) return
  if (isBenignLoadFailure(code, desc)) return  // ERR_ABORTED 忽略
  if (isDev) return
  dialog.showErrorBox("MonkeyCode",
    `页面加载失败（${code}）\n${desc}\n\n${url}\n\n请检查网络或代理`)
})
```

### 3.3 启动超时保护

```javascript
function ensureWindowVisible(win, ms = 2000) {
  // 防止 ready-to-show 迟迟不触发导致窗口永远隐藏
  win.once("ready-to-show", () => win.show())
  win.webContents.once("did-finish-load", () => {
    if (!win.isDestroyed() && !win.isVisible()) win.show()
  })
  setTimeout(() => win.show(), ms)  // 2 秒强制显示
}
```

## 4. preload.cjs

```javascript
"use strict"
// Preload：若需向页面暴露安全 API，请使用 contextBridge.exposeInMainWorld。
```

> 只有 3 行注释占位代码。**未暴露任何 API** 到渲染进程。

## 5. 安全配置详解

| 配置 | 值 | 安全影响 | 风险说明 |
|------|-----|---------|---------|
| `contextIsolation` | `true` | ✅ 渲染进程不能访问 Node API | 防止 XSS 攻击升级为 RCE |
| `nodeIntegration` | `false` | ✅ 渲染进程没有 `require` | 防止恶意脚本加载原生模块 |
| `sandbox` | `false` | ⚠️ 非沙箱模式 | 加载完整 Web 应用时需要 |

```javascript
// sandbox: false 的原因（源码注释原文）:
// "加载完整 Web 应用时 sandbox 可能导致部分站点行为异常，桌面壳使用非沙箱更稳妥"
```

## 6. 4 种加载模式总结

| 模式 | 触发条件 | 加载目标 | 典型用途 |
|------|---------|---------|---------|
| 开发 | `!app.isPackaged` | `http://localhost:11180` | 前端开发 |
| 本地构建 | `MONKEYCODE_LOAD_LOCAL_DIST=1` | `file://web-dist/index.html` | 离线测试 |
| 生产在线 | 默认 | `https://monkeycode-ai.com/console/` | 用户日常使用 |
| 自定义 | `MONKEYCODE_DESKTOP_URL` | 任意 URL | 企业自定义部署 |

## 7. Electron 配置表

| 配置项 | 值 |
|--------|-----|
| appId | `com.monkeycode.desktop` |
| 版本 | `260324.1.22` |
| Electron | `^35.1.5` (devDependencies) |
| ASAR | ✅ 启用 |
| 类型 | CommonJS `"type": "commonjs"` |
| 主进程 | `electron/main.cjs` |

## 8. 逆向结论

Electron 壳是被动的 Web 容器。所有业务逻辑在远程 SPA 中运行。

**分析重点应转向：**

```bash
# 1. 后端 Go 源码（开源在 chaitin/MonkeyCode）
# 2. 代理层 TypeScript（proxy/src/ 目录，3031 行）
# 3. 网络通信协议（HTTP + WebSocket 流）
```

> 仅有的「客户端逻辑」：窗口创建配置、单实例锁、加载失败弹窗、外链打开。

---

## 相关章节

- [系统架构总览](../01-architecture/01-system-overview.md) — Electron 壳定位
- [环境变量全集](../10-appendices/03-environment-variables.md) — 桌面壳环境变量

## 9. 加载源解析函数

```javascript
// main.cjs — URL 构建逻辑
function desktopEntryUrl(base) {
  const href = (base || "").trim() || DEFAULT_PROD_URL
  // 拼接: base + START_PATH
  return new URL(
    `${START_PATH.startsWith("/") ? START_PATH : `/${START_PATH}`}`,
    href
  ).href
}

// 本地构建路径
function localDistIndexHtml() {
  if (app.isPackaged) {
    return path.join(__dirname, "..", "web-dist", "index.html")
  }
  return path.join(__dirname, "..", "..", "frontend", "dist", "index.html")
}
```

## 10. 扩展功能

```javascript
// 窗口图标（ASAR 内无法读取，需 unpack）
function windowIconPath() {
  if (app.isPackaged) {
    const unpacked = path.join(process.resourcesPath,
      "app.asar.unpacked", "electron", "icon.png")
    if (fs.existsSync(unpacked)) return unpacked
  }
  return fs.existsSync(path.join(__dirname, "icon.png"))
    ? path.join(__dirname, "icon.png") : undefined
}
```

| 功能 | 方法 | 说明 |
|------|------|------|
| URL 拼接 | `desktopEntryUrl(base)` | 将 base URL + 路径组合 |
| 本地构建 | `localDistIndexHtml()` | 开发/生产不同路径 |
| 窗口图标 | `windowIconPath()` | ASAR unpacked 模式加载图标 |
| 菜单栏 | `Menu.setApplicationMenu(null)` | Win/Linux 隐藏菜单 |
| Dock 图标 | `app.dock.setIcon(icon)` | macOS 设置 Dock 图标 |
| 外链拦截 | `setWindowOpenHandler` | 外部链接系统浏览器打开 |
| 应用退出 | `app.on("window-all-closed")` | 非 macOS 直接退出 |

## 11. package.json

```json
{
  "name": "monkeycode-desktop",
  "private": true,
  "version": "260324.1.22",
  "description": "MonkeyCode 桌面客户端（Electron）",
  "author": "MonkeyCode",
  "type": "commonjs",
  "main": "electron/main.cjs"
}
```

> 版本号 `260324.1.22` 使用日期格式：`YYMMDD.构建号.补丁号`，表示 2026 年 3 月 24 日的第 1 次构建的第 22 次补丁。

## 12. Electron 安全检查清单

| 安全项 | monkeycode-desktop | 安全实践 |
|--------|-------------------|---------|
| contextIsolation: true | ✅ | 渲染进程隔离 |
| nodeIntegration: false | ✅ | 无 Node.js API |
| preload | ✅ (3 行占位) | 预加载脚本（空壳）|
| sandbox: false | ❌ | 非沙箱（明确风险）|
| CSP Header | ❌ 无 | 远程页面自行管理 |
| session partition | ❌ 无 | 默认 session |
| navigate handler | ❌ 无 | 未限制导航目标 |

---

## 相关章节

- [系统架构总览](../01-architecture/01-system-overview.md) — Electron 壳在整体架构中的位置
- [环境变量全集](03-environment-variables.md) — 桌面壳环境变量
