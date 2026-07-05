---
description: Python MVP oauth_login.py Playwright 自动化深度分析 — 461行浏览器自动化的完整逆向工程
protocol_version: based on mvp/oauth_login.py (461 行)
confidence: high
last_verified: 2026-07-05
---

# Python MVP OAuth 登录自动化深度分析

> **所属分类:** 新维度 #31 — Python MVP oauth_login.py Playwright 自动化
> **关键发现:** Playwright 浏览器自动化 vs 纯 HTTP 实现的双轨设计，8 步登录流程，3 种运行模式

## 1. 架构全景

```mermaid
flowchart TB
    subgraph Entry["入口 — main()"]
        ARGS["参数解析<br/>--phone --sms-api<br/>--headless --extract-only --verify"]
        MODE{"运行模式"}
    end

    subgraph Mode1["模式1: 完整 OAuth 登录<br/>oauth_login()"]
        S1["Step1: 打开 MonkeyCode 登录页<br/>page.goto(/api/v1/users/login)"]
        S2["Step2: 等待百智云重定向<br/>wait_for_url(**/sign-in**)"]
        S3["Step3: 输入手机号 + SCaptcha<br/>7种selector兜底"]
        S4["Step4: 点击发送验证码<br/>7种selector兜底"]
        S5["Step5: 输入短信验证码<br/>sms_api 自动 / 手动"]
        S6["Step6: 点击登录<br/>5种selector兜底"]
        S7["Step7: OAuth 授权确认<br/>点击确认授权"]
        S8["Step8: 等待回调 + 提取 Cookie<br/>extract_session_from_browser()"]
    end

    subgraph Mode2["模式2: 交互式登录<br/>interactive_login()"]
        I1["打开页面<br/>page.goto(/api/v1/users/login)"]
        I2["用户手动操作<br/>input() 等待"]
        I3["提取 Cookie"]
    end

    subgraph Mode3["模式3: 验证已有 Session<br/>--verify 参数"]
        V1["verify_session()<br/>GET /api/v1/users/status"]
        V2["get_user_info()<br/>GET /api/v1/users/me"]
        V3["get_user_models()<br/>GET /api/v1/users/models"]
    end

    subgraph Output["输出"]
        O1["打印 Session Cookie"]
        O2["保存到 .session 文件"]
        O3["验证结果输出"]
    end

    ARGS --> MODE
    MODE -->|--phone 或 --sms-api| Mode1
    MODE -->|--extract-only| Mode2
    MODE -->|--verify| Mode3
    Mode1 --> O1 --> O2 --> O3
    Mode2 --> O1
    Mode3 --> O3
```

## 2. 双轨架构：Playwright 浏览器 vs 纯 HTTP

| 维度 | Playwright 实现 (oauth_login.py) | 纯 HTTP 实现 (admin-login.ts) |
|------|--------------------------------|------------------------------|
| **原理** | 真实浏览器 + Playwright 控制 | Node.js fetch + 请求头伪装 |
| **验证码** | 人工在浏览器里点 SCaptcha | TLS 绕过 + 自动获取 captcha token |
| **发短信** | Playwright 点击按钮 | HTTP POST 直接调百智云 API |
| **稳定性** | 依赖 DOM 选择器（脆弱） | 依赖 API 响应（稳定） |
| **速度** | 慢（需要浏览器启动 + 页面加载） | 快（纯网络请求） |
| **适用场景** | 开发调试、手动登录 | 自动化、账号池 |

## 3. DOM 选择器兜底策略

```python
# mvp/oauth_login.py:122-134 — 手机号输入框的 6 种兜底选择器
phone_input = None
for selector in [
    "input[type='tel']",
    "input[name='phone']",
    "input[placeholder*='手机']",
    "input[placeholder*='phone']",
    "input[id*='phone']",
]:
    phone_input = page.locator(selector).first
    if phone_input.is_visible(timeout=3000):
        break
```

**所有 DOM 操作都使用了类似的兜底策略（6-7 种选择器）：**

| 目标元素 | 兜底选择器数 | 脆弱性 |
|---------|------------|--------|
| 手机号输入框 | 6 种 | 🟡 百智云页面改版后可能全部失效 |
| 验证码按钮 | 7 种 | 🟡 同上 |
| 发送验证码按钮 | 6 种 | 🟡 同上 |
| 验证码输入框 | 4 种 | 🟡 同上 |
| 登录按钮 | 4 种 | 🟡 同上 |
| 授权确认按钮 | 4 种 | 🟡 同上 |

## 4. 短信验证码获取流程

```mermaid
flowchart TB
    subgraph Manual["手动模式"]
        MAN_ASK["input('请输入短信验证码: ')"]
        MAN_INPUT["code_input.fill(code)"]
    end

    subgraph Auto["自动模式 (--sms-api)"]
        RETRY["10 次重试<br/>每次间隔 3 秒"]
        FETCH["requests.get(sms_api)"]
        CHECK{"code 存在<br/>且 >= 4位?"}
    end

    CALL_SEND["点击发送验证码按钮"] -->|等待 SMS| MAN_ASK
    CALL_SEND -->|sms_api 参数| RETRY
    RETRY --> FETCH
    FETCH --> CHECK
    CHECK -->|否| RETRY
    CHECK -->|是| MAN_INPUT

    MAN_ASK --> MAN_INPUT
    MAN_INPUT --> SUBMIT["点击登录按钮"]
```

## 5. 与纯 HTTP 实现的双轨架构

```mermaid
flowchart LR
    subgraph Python["Python MVP 工具集"]
        OAUTH["oauth_login.py<br/>Playwright 浏览器"]
        HTTP_OAUTH["oauth_http.py<br/>纯 HTTP 请求"]
        AUTH["auth.py<br/>基础认证模块"]
    end

    subgraph TS["TypeScript 代理层"]
        ADMIN["admin-login.ts<br/>纯 HTTP + 请求头伪装"]
    end

    OAUTH -->|人工点验证码| MC["monkeycode-ai.com"]
    HTTP_OAUTH -->|HTTP 请求| MC
    ADMIN -->|HTTP + 指纹| MC
    MC -->|HTTP 请求| BZ["baizhi.cloud"]

    OAUTH -.->|双轨设计<br/>同一流程两种实现| ADMIN
```

## 6. 关键发现

| 发现 | 详情 | 影响 |
|------|------|------|
| **3 种运行模式** | 完整 OAuth / 交互式提取 / Session 验证 | 覆盖所有使用场景 |
| **DOM 兜底策略** | 4-7 种选择器兜底每个元素 | 百智云改版可能全失效 |
| **sms_api 接口约定** | 期望返回 `{code: "123456"}` 或纯文本 | 无标准格式文档 |
| **无 headless + 手动验证码路径** | headless 模式要求 sms_api | 无人工介入时无法使用 |
| **Session 持久化** | 自动保存到 `.session` 文件 | 持久化方便后续使用 |
| **无重试机制** | 登录失败不重试 | 网络抖动可能失败 |
| **无超时配置** | 10 次 3s 的重试硬编码 | 不可配置 |

---

**更新状态:** ✅ 新维度已分析完成
**更新索引:** docs/08-analysis-rounds/unknown-gaps-index.md