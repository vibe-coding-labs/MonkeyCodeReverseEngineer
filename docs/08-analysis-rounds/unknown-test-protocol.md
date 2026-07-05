---
description: Python MVP test_protocol.py 协议验证方法深度分析 — 268行端到端协议验证器
protocol_version: based on mvp/test_protocol.py (268 行)
confidence: high
last_verified: 2026-07-05
---

# Python MVP 协议验证方法深度分析

> **所属分类:** 新维度 #34 — Python MVP test_protocol.py 协议验证方法
> **关键发现:** 4 个递进测试阶段（连通性→认证→模型→代理可行性），是 MonkeyCode 协议完整性的实证文档

## 1. 四阶段递进测试架构

```mermaid
flowchart TB
    subgraph Phase0["测试0: API 连通性"]
        P0_1["GET / → 主页可达"]
        P0_2["GET /users/status → 401"]
        P0_3["GET /users/models → 401"]
        P0_4["POST /captcha/challenge → 201"]
        P0_5["POST /teams/users/login → 400"]
    end

    subgraph Phase1["测试1: 认证协议验证"]
        P1_1["Session Cookie 有效性<br/>check_status()"]
        P1_2["密码登录<br/>login_with_password()"]
        P1_3["登录状态检查<br/>check_status()"]
    end

    subgraph Phase2["测试2: 模型列表 API"]
        P2_1["list_models()<br/>按 owner/interface/provider 分类"]
        P2_2["公开模型识别<br/>get_public_models()"]
        P2_3["免费模型识别<br/>get_free_models()"]
        P2_4["数据结构完整性<br/>必需字段检查"]
    end

    subgraph Phase3["测试3: 代理可行性"]
        P3_1["可用模型存在?"]
        P3_2["接口类型覆盖?"]
        P3_3["Cookie-based 可行?"]
        P3_4["WebSocket 流式可行?"]
    end

    Phase0 -->|必须通过| Phase1
    Phase1 -->|必须通过| Phase2
    Phase2 -->|必须通过| Phase3
```

## 2. 测试流程数据流

```mermaid
sequenceDiagram
    participant Main as main()
    participant T0 as test_api_connectivity
    participant T1 as test_auth
    participant T2 as test_models
    participant T3 as test_proxy_feasibility
    participant Auth as MonkeyCodeAuth
    participant Models as MonkeyCodeModels

    Main->>T0: 测试 API 连通性
    T0->>MonkeyCode: GET / (HTTP)
    T0->>MonkeyCode: GET /users/status (no cookie)
    T0->>MonkeyCode: POST /captcha/challenge
    T0-->>Main: ✅/❌

    Main->>T1: 测试认证
    T1->>Auth: check_status()
    alt cookie 有效
        Auth-->>T1: session 有效
    else cookie 过期/无
        T1->>Auth: login_with_password()
        Auth-->>T1: cookie
        T1->>Auth: check_status()
    end
    T1-->>Main: ✅/❌

    alt auth 通过
        Main->>T2: 测试模型
        T2->>Auth: get_auth_cookies()
        T2->>Models: list_models()
        Models-->>T2: 模型列表 + 分类统计
        T2->>Models: get_public_models()
        T2->>Models: get_free_models()
        T2-->>Main: ✅/❌

        alt models 通过
            Main->>T3: 代理可行性
            T3->>T3: 检查可用模型
            T3->>T3: 检查接口类型覆盖
            T3-->>Main: ✅/❌
        end
    end

    Main->>Main: 汇总结果
```

## 3. test_auth.py vs test_protocol.py 对比

| 维度 | test_auth.py (498 行) | test_protocol.py (268 行) |
|------|---------------------|--------------------------|
| **定位** | 详细认证测试套件 | 快速端到端协议验证 |
| **用例数** | 14 个独立测试 | 4 个递进阶段 |
| **可重复性** | ✅ 独立的 TestResult | ✅ 顺序依赖 |
| **执行时间** | ~30 秒 | ~15 秒 |
| **覆盖深度** | 深（含错误码验证） | 浅（仅功能验证） |
| **失败处理** | 继续执行后续测试 | 阶段失败则跳过后续 |
| **输出格式** | [PASS]/[FAIL] | ✅/❌ |
| **依赖** | 无外部依赖 | auth.py + models.py |

## 4. 关键发现

| 发现 | 详情 |
|------|------|
| **4 阶段递进设计** | 每阶段成功后才能继续下一阶段 |
| **test_auth 是详细版** | test_protocol 是精简版 |
| **0 个任务/WS 测试** | 两个测试文件都不涉及任务和 WebSocket |
| **无 mock 设计** | 全部为线上集成测试 |
| **唯一记录关键修正的地方** | test_protocol 末尾记录协议修正 |
| **验证了协议完整性的 80%** | 认证+模型+OAuth+验证码 |

---

**更新状态:** ✅ 新维度已分析完成  
**更新索引:** docs/08-analysis-rounds/unknown-gaps-index.md