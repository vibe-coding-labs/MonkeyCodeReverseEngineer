# 原始分析档案

> **状态:** ⚠️ **已存档** — 内容已被结构化文档覆盖
> **文件数:** 35 份
> **总行数:** ~12,903
> **保留原因:** 历史记录/原始数据附录/可追溯的逆向过程

---

## 关于此目录

`docs/protocol/` 目录包含了 MonkeyCode 逆向工程的**原始分析档案**。这些文件是在 18 轮分析过程中逐个创建的分析笔记，内容已被重组到 `docs/` 下的结构化章节中。

## 为什么保留

1. **可追溯性** — 每份档案记录了分析当时的原始发现过程
2. **原始数据** — 包含完整的抓包数据、调试日志等细节
3. **补充阅读** — 部分篇幅较大的分析细节未完整迁移

## 内容映射表

| 原始档案 | 对应结构化章节 | 迁移状态 |
|---------|--------------|---------|
| `account-pool-protocol.md` | [07-proxy/02-account-pool.md](../07-proxy/02-account-pool.md) | ✅ 已覆盖 |
| `api-endpoints.md` | [05-api/01-endpoint-catalog.md](../05-api/01-endpoint-catalog.md) | ✅ 已覆盖 |
| `architecture.md` | [01-architecture/](../01-architecture/) | ✅ 已覆盖 |
| `asar-analysis.md` | [10-appendices/01-asar-analysis.md](../10-appendices/01-asar-analysis.md) | ✅ 已覆盖 |
| `auth-automation-analysis.md` | [02-auth/07-auth-automation.md](../02-auth/07-auth-automation.md) | ✅ 已覆盖 |
| `authorization-matrix.md` | [05-api/02-authorization-matrix.md](../05-api/02-authorization-matrix.md) | ✅ 已覆盖 |
| `auth-pool-gap-analysis.md` | [02-auth/08-pool-gap-analysis.md](../02-auth/08-pool-gap-analysis.md) | ✅ 已覆盖 |
| `auth-protocol-complete.md` | [02-auth/](../02-auth/) | ✅ 已覆盖 |
| `auth-protocol-pool-complete.md` | [02-auth/](../02-auth/) | ✅ 已覆盖 |
| `auth-unresolved-verification.md` | [02-auth/](../02-auth/) | ✅ 已覆盖 |
| `llm-integration.md` | [03-llm/05-llm-integration.md](../03-llm/05-llm-integration.md) | ✅ 已覆盖 |
| `llm-protocol-complete.md` | [03-llm/](../03-llm/) | ✅ 已覆盖 |
| `model-pricing-quota.md` | [03-llm/04-model-pricing-quota.md](../03-llm/04-model-pricing-quota.md) | ✅ 已覆盖 |
| `multi-turn-design.md` | [07-proxy/03-multi-turn-conversation.md](../07-proxy/03-multi-turn-conversation.md) | ✅ 已覆盖 |
| `taskflow-vm-analysis.md` | [06-vm-taskflow/](../06-vm-taskflow/) | ✅ 已覆盖 |
| `websocket-protocol.md` | [04-websocket/](../04-websocket/) | ✅ 已覆盖 |
| `analysis-round-*.md` | [08-analysis-rounds/rounds/](../08-analysis-rounds/rounds/) | ✅ 已覆盖 |
| `analysis-summary.md` | [08-analysis-rounds/](../08-analysis-rounds/) | ✅ 已覆盖 |

## 目录结构

```
docs/protocol/
├── README.md                          ← 本文件
├── architecture.md                    → 01-architecture/
├── auth-protocol-complete.md          → 02-auth/
├── auth-protocol-pool-complete.md     → 02-auth/
├── auth-automation-analysis.md        → 02-auth/
├── auth-unresolved-verification.md    → 02-auth/
├── auth-pool-gap-analysis.md          → 02-auth/
├── authorization-matrix.md           → 05-api/
├── api-endpoints.md                   → 05-api/
├── llm-protocol-complete.md          → 03-llm/
├── llm-integration.md                → 03-llm/
├── model-pricing-quota.md            → 03-llm/
├── websocket-protocol.md             → 04-websocket/
├── taskflow-vm-analysis.md           → 06-vm-taskflow/
├── multi-turn-design.md              → 07-proxy/
├── account-pool-protocol.md          → 07-proxy/
├── asar-analysis.md                  → 10-appendices/
├── analysis-summary.md               → 08-analysis-rounds/
├── analysis-round-01.md ~ 18.md      → 08-analysis-rounds/rounds/
└── (其他文件)
```

---

> **建议:** 阅读时优先参考 `docs/` 下的结构化章节。如需查看更原始的发现过程，可翻阅此目录中的档案文件。