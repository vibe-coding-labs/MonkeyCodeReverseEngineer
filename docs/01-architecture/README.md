# 第一章：系统架构

> **章节状态:** ✅ 所有文件已完成
> **最后更新:** 2026-06-25
> **覆盖范围:** MonkeyCode 整体系统架构、数据流、组件层级、错误处理模式

---

## 文件清单

| # | 文件 | 内容 | 完成度 |
|---|------|------|--------|
| 1 | [01-system-overview.md](01-system-overview.md) | 系统架构总览（三层架构、组件关系） | ✅ 已完成 |
| 2 | [02-data-flow.md](02-data-flow.md) | 核心数据流（任务创建→执行→返回） | ✅ 已完成 |
| 3 | [03-component-layer.md](03-component-layer.md) | 组件层级分析（前端、后端、TaskFlow、VM） | ✅ 已完成 |
| 4 | [04-error-handling-patterns.md](04-error-handling-patterns.md) | 错误处理模式（LLM 错误、WS 重连、模拟模式） | ✅ 已完成 |

---

## 关键图表引用

系统架构图、数据流图在本章各文件中。核心依赖关系：

```
第三方1 [Electron Client] --> [Proxy Layer]
第三方2 [Codex/OpenAI SDK] --> [Proxy Layer]
Proxy Layer --> [MonkeyCode Backend]
MonkeyCode Backend --> [TaskFlow Service]
TaskFlow Service --> [Docker VM Cluster]
VM Cluster --> [LLM Providers]
```

---

## 相关章节

- [第二章：认证协议](../02-auth/README.md) — 本架构中的认证组件
- [第六章：VM & TaskFlow](../06-vm-taskflow/README.md) — TaskFlow 服务和 VM 生命周期细节