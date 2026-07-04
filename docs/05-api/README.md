# 第五章：API 端点和授权

> **章节状态:** ✅ 所有文件已创建（Conversation 70%、订阅需线上确认）
> **最后更新:** 2026-06-25
> **覆盖范围:** 完整 API 端点目录、授权层级矩阵、Conversation API、订阅计费 API、管理后台 API

---

## 文件清单

| # | 文件 | 内容 | 完成度 |
|---|------|------|--------|
| 1 | [01-endpoint-catalog.md](01-endpoint-catalog.md) | 完整 API 端点目录（100+ 端点，含认证要求和请求格式） | ✅ 已完成 |
| 2 | [02-authorization-matrix.md](02-authorization-matrix.md) | 授权层级与访问控制矩阵（角色体系、5 种中间件、资源规则） | ✅ 已完成 |
| 3 | [03-conversation-api.md](03-conversation-api.md) | Conversation API 分析（6 个端点，JSON Schema 推导） | 🟡 70%（待线上确认）|
| 4 | [04-subscription-billing.md](04-subscription-billing.md) | 订阅与计费 API（SubscriptionResp、余额） | ✅ 已完成 |
| 5 | [05-admin-management-api.md](05-admin-management-api.md) | 管理后台 API（用户管理、模型管理、审计） | ✅ 已完成 |

---

## 核心发现

| 关键项 | 值 |
|--------|-----|
| 已知端点总数 | 100+（89 个需认证 + 11 个公开） |
| API 前缀 | `/api/v1/` |
| 统一响应格式 | `{"code": 0, "msg": "success", "data": ...}` |
| 认证缺失维度 | Conversation API（40%）、管理后台 API（0%）、订阅 API（概览） |

---

## 相关章节

- [第二章：认证协议](../02-auth/README.md) — 认证中间件细节
- [第四章：WebSocket 协议](../04-websocket/README.md) — WebSocket 端点详情