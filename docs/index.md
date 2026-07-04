# MonkeyCode 逆向工程分析全书

> **项目:** MonkeyCode Reverse Engineer
> **版本:** 2.3
> **最后更新:** 2026-07-03
> **总文档数:** 119+ 份
> **分析维度:** 40+ 维度全覆盖

[![Chapters](https://img.shields.io/badge/总章节-10章-blue)](https://vibe-coding-labs.github.io/MonkeyCodeReverseEngineer/)
[![Docs](https://img.shields.io/badge/文档数-119份-green)]()
[![Status](https://img.shields.io/badge/状态-持续更新-yellow)]()
[![License](https://img.shields.io/badge/许可证-MIT-orange)](https://github.com/vibe-coding-labs/MonkeyCodeReverseEngineer/blob/main/LICENSE)

---

本项目是对 [MonkeyCode AI](https://monkeycode-ai.com) 平台的全面逆向工程文档，覆盖认证协议、LLM 通信、WebSocket 流式协议、API 端点、VM 生命周期、代理实现等 10 个维度、40+ 分析维度。

## 系统架构全景图

```mermaid
graph TB
    subgraph Client["客户端层"]
        Electron["🖥️ Electron 桌面壳<br/>analysis/asar-content/electron/"]
        Codex["🤖 Codex CLI"]
        OpenAI["🔌 OpenAI SDK"]
    end

    subgraph Proxy["代理层 · proxy/src/"]
        Server["server.ts<br/>Express 入口"]
        Auth["auth.ts<br/>Session 管理"]
        Pool["account-pool.ts<br/>账号轮转"]
        Model["models.ts<br/>模型解析"]
        Runner["task-runner.ts<br/>WebSocket 流"]
        Conv["conversation-manager.ts<br/>多轮对话"]
    end

    subgraph Remote["MonkeyCode 后端 · api.monkeycode-ai.com"]
        Login["POST /api/v1/users/login<br/>OAuth/密码登录"]
        Task["POST /api/v1/users/tasks<br/>任务创建"]
        WS["WS /api/v1/users/tasks/stream<br/>ACP 事件流"]
        ModelAPI["GET /api/v1/users/models<br/>模型列表"]
    end

    subgraph VM["TaskFlow VM · Docker 容器"]
        Agent["Codex/Claude/OpenCode Agent"]
        LLM["LLM Client · client.go<br/>OpenAI / Anthropic SDK"]
    end

    Client -->|HTTP/WSS| Proxy
    Proxy -->|Session Cookie| Remote
    Remote -->|创建 Docker 容器| VM
    VM -->|ACP 事件 via WS| Proxy
    Proxy -->|SSE 流| Client
```

## 认证流程全景图

```mermaid
sequenceDiagram
    participant U as 用户
    participant P as 代理 server.ts
    participant A as auth.ts
    participant MC as monkeycode-ai.com
    participant BZ as 百智云 OAuth

    U->>P: OpenAI API 请求
    P->>A: 获取 Session Cookie
    alt 已有 Cookie
        A-->>P: 返回有效 Cookie
    else Cookie 过期
        A->>MC: POST /api/v1/users/password-login
        MC-->>A: Set-Cookie: monkeycode_ai_session
        A-->>P: 返回新 Cookie
    end
    P->>MC: 请求 + Cookie
    MC-->>P: 响应
    P-->>U: OpenAI 格式响应
```

## 快速导航

| 章节 | 内容 | 文件数 |
|------|------|--------|
| [📐 第一章：系统架构](01-architecture/README.md) | 四层架构、数据流、组件层级、错误处理 | 4 |
| [🔐 第二章：认证协议](02-auth/README.md) | Session 存储、验证码、5 种登录方式 | 8 |
| [🤖 第三章：LLM 通信协议](03-llm/README.md) | 3 种接口类型、11 个提供商、模型定价 | 7 |
| [🔌 第四章：WebSocket 协议](04-websocket/README.md) | Stream/Control/Terminal/ACP 事件 | 7 |
| [🌐 第五章：API 端点和授权](05-api/README.md) | 100+ 端点、授权矩阵、订阅计费 | 5 |
| [🖥️ 第六章：VM & TaskFlow](06-vm-taskflow/README.md) | TaskFlow 架构、VM 生命周期、MCP | 5 |
| [⚡ 第七章：代理实现](07-proxy/README.md) | 号池、多轮对话、ACP 映射、OAuth | 11 |
| [📊 第八章：分析轮次](08-analysis-rounds/README.md) | 18 轮逆向分析全记录 | 3 |
| [🛡️ 第九章：安全分析](09-security/README.md) | SCaptcha 漏洞、代理安全加固 | 2 |
| [📎 第十章：附录](10-appendices/README.md) | 错误码、环境变量、术语表、代码展品 | 9 |

## 阅读路径

本书按**学习路径**组织为六篇，每篇都以前一篇为基础：

```mermaid
flowchart TB
    P1["🚀 第一篇·基础入门<br/>这是什么？怎么构成的？"]
    P2["🔌 第二篇·通讯协议<br/>前后端怎么通信？"]
    P3["⚙️ 第三篇·运行原理<br/>AI 在哪跑？怎么调用？"]
    P4["🛠️ 第四篇·工程实现<br/>代码怎么写的？"]
    P5["📖 第五篇·研究记录<br/>怎么逆向出来的？"]
    P6["📚 第六篇·参考与附录<br/>需要查什么？"]

    P1 --> P2 --> P3 --> P4
    P1 --> P5
    P1 -.-> P6
    P2 -.-> P6
    P3 -.-> P6
    P4 -.-> P6
```

| 篇 | 名称 | 内容 | 文件数 | 适合 |
|----|------|------|--------|------|
| 🚀 | **第一篇·基础入门** | 系统架构、数据流、组件层级 | 4 | 所有读者起点 |
| 🔌 | **第二篇·通讯协议** | 认证协议 / API 层 / WebSocket 通信 | 20 | 协议开发者 |
| ⚙️ | **第三篇·运行原理** | LLM 调用链路 / VM 执行引擎 | 13 | 架构理解者 |
| 🛠️ | **第四篇·工程实现** | 反向代理完整实现 | 11 | 想用代理的人 |
| 📖 | **第五篇·研究记录** | 18 轮分析过程 / 安全漏洞 | 6 | 安全研究者 |
| 📚 | **第六篇·参考与附录** | 错误码 / 术语 / 环境变量 / 原始档案 | 44 | 所有人查阅 |

## 快速入口

| 你的角色 | 最短路径 |
|---------|---------|
| 🧑‍💻 **只想用代理** | 基础入门 → 工程实现 |
| 🔬 **安全研究** | 基础入门 → 通讯协议(认证) → 研究记录(安全) |
| 📐 **协议开发** | 基础入门 → 通讯协议 → 运行原理 |
| 🏃 **快速查阅** | 直接跳参考与附录

---

<p align="center">
  <sub>Built with ❤️ for research and educational purposes.</sub>
  <br>
  <sub>作者: <a href="https://github.com/CC11001100">CC11001100</a></sub>
  <br>
  <sub>
    Powered by <a href="https://squidfunk.github.io/mkdocs-material/">MkDocs Material</a>
  </sub>
</p>