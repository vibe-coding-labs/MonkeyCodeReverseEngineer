---
description: MonkeyCode 逆向工程 18 轮分析过程汇总 — 关键发现时间线
protocol_version: based on complete analysis history
confidence: high
last_verified: 2026-06-27
---

# 18 轮逆向分析 — 过程总结

> **分析周期:** 2026-05-10 ~ 2026-05-30
> **总文件产生:** 35 份原始分析档案（docs/protocol/）
> **总行数:** ~12,903

---

## 分阶段时间线

### 第一阶段：发现与初探（第 1~6 轮）

目标：建立初步协议理解

| 轮次 | 日期 | 关键发现 | 衍生文档 |
|------|------|---------|---------|
| 1 | 05-10 | 识别 Electron ASAR 结构，发现 API 端点和 WebSocket 连接 | `asar-analysis.md`, `api-endpoints.md` |
| 2 | 05-10 | 验证密码登录、Session Cookie 机制（monkeycode_ai_session） | `auth-protocol-complete.md` |
| 3 | 05-11 | 建立三层架构（前端→后端→TaskFlow→LLM） | `architecture.md` |
| 4 | 05-12 | 确认 11 个模型提供商、3 种接口类型 | `llm-protocol-complete.md` |
| 5 | 05-14 | TaskFlow VM 生命周期完整分析 | `taskflow-vm-analysis.md` |
| 6 | 05-15 | WebSocket Task Stream 协议握手和消息格式 | `websocket-protocol.md` |

### 第二阶段：深入协议分析（第 7~12 轮）

目标：确认协议细节和安全性

| 轮次 | 日期 | 关键发现 | 衍生文档 |
|------|------|---------|---------|
| 7 | 05-16 | ACP 事件类型全表（7 种），agent_message/thought/tool_call 确认 | `websocket-protocol.md` |
| 8 | 05-16 | 授权矩阵（public/user/team/admin 四级） | `authorization-matrix.md` |
| 9 | 05-18 | 百智云 OAuth 流程（baizhi.cloud）| `auth-automation-analysis.md` |
| 10 | 05-20 | 多轮对话设计（mode=attach） | `multi-turn-design.md` |
| 11 | 05-22 | 订阅端点和计费结构体（SubscriptionResp） | `model-pricing-quota.md` |
| 12 | 05-24 | 号池管理协议（账号池轮转+健康检查） | `auth-protocol-pool-complete.md` |

### 第三阶段：线验证和实现（第 13~18 轮）

目标：实现反向代理并验证

| 轮次 | 日期 | 关键发现 | 衍生文档 |
|------|------|---------|---------|
| 13 | 05-25 | 代理 Mode 架构设计（Python 验证原型） | `proxy/` |
| 14 | 05-26 | ACP→OpenAI Chat/Responses 双模式映射 | `proxy/` |
| 15 | 05-28 | TypeScript 代理实现（~3031 行） | `proxy/src/` |
| 16 | 05-28 | 验证码系统逆向（CAP.js + go-cap） | `auth-automation-analysis.md` |
| 17 | 05-30 | 安全测试（SCaptcha TLS 绕过，发送短息轰炸） | `baizhi-security-report.md` |
| 18 | 05-30 | 未解决问题追踪和文档整理 | `auth-unresolved-verification.md` |

---

## 关键转折点

| 日期 | 事件 | 影响 |
|------|------|------|
| 05-10 | ASAR 解包发现第一个 API 端点 | 启动整个逆向项目 |
| 05-11 | 确认三层架构（非两层） | 修正架构理解 |
| 05-14 | TaskFlow VM 生命周期完整分析 | 理解虚拟机调度 |
| 05-16 | ACP 事件全表确认 | 能够解析 Agent 实时输出 |
| 05-18 | 百智云 OAuth 逆向 | 理解免密登录流程 |
| 05-28 | TypeScript 代理首次运行成功 | 验证全部协议理解正确 |
| 05-30 | 安全测试发现 3 个漏洞 | 发现 TLS 绕过等安全问题 |

---

## 各轮次产出规模（扩增后）

```
第 1~6 轮合并:  ──────────────────────── 541 行, 38 代码块 (扩增版 — ASAR/登录/架构/提供商/VM/WS)
第 7~12 轮合并:  ──────────────────────── 517 行, 26 代码块 (扩增版 — ACP/授权/OAuth/多轮/订阅/号池)
第 13~18 轮合并:  ──────────────────────── 380 行, 24 代码块 (扩增版 — 代理/Bug修复/TS实现/验证码/安全/审查)
```

## 最终成果

| 指标 | 数值 |
|------|------|
| 分析轮次 | 18 轮 |
| 分析时间跨度 | 20 天 |
| 原始档案 | 35 份，~12,903 行 |
| 结构化文档 | ~81 份，10 章节 |
| TypeScript 代理 | ~3,031 行（10 个模块）|
| Python 验证工具 | ~4,854 行（10 个工具）|
| 代码示例 | 300+ 代码块 |
| 分析维度 | 32/32 完整覆盖 |
| 安全漏洞发现 | 3 个（TLS 绕过、授权码重放、短信轰炸）|

---

## 相关章节

- [原始分析档案 (docs/protocol/)](../protocol/README.md) — 35 份原始分析文件
- [文档全书索引](../INDEX.md) — 结构化文档导航
- [分析完成度矩阵](../MASTER-CHECKLIST.md) — 32 维度状态