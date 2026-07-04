# 第二章：认证协议

> **章节状态:** ✅ 所有文件已完成
> **最后更新:** 2026-06-25
> **覆盖范围:** Cookie-based Session 认证、5 种登录方式、验证码系统、认证中间件、密码管理

---

## 文件清单

| # | 文件 | 内容 | 完成度 |
|---|------|------|--------|
| 1 | [01-session-storage.md](01-session-storage.md) | Session 存储机制（Redis 数据结构、Cookie 属性、生命周期） | ✅ 已完成 |
| 2 | [02-captcha-system.md](02-captcha-system.md) | 验证码系统分析（CAP.js / go-cap 前端集成） | ✅ 已完成 |
| 3 | [03-login-methods.md](03-login-methods.md) | 5 种登录方式详解（密码/OAuth/Git/团队/Impersonate） | ✅ 已完成 |
| 4 | [04-oauth-baizhi-cloud.md](04-oauth-baizhi-cloud.md) | 百智云 OAuth 完整流程（SCaptcha + SMS + 跳转） | ✅ 已完成 |
| 5 | [05-auth-middleware.md](05-auth-middleware.md) | 认证中间件体系（Auth/Check/TeamAuth/TeamAdminAuth） | ✅ 已完成 |
| 6 | [06-password-management.md](06-password-management.md) | 密码管理接口（修改/重置/重置请求） | ✅ 已完成 |
| 7 | [07-auth-automation.md](07-auth-automation.md) | 认证自动化（SCaptcha 绕过、Playwright OAuth、HTTP 模拟） | ✅ 已完成 |
| 8 | [08-pool-gap-analysis.md](08-pool-gap-analysis.md) | 认证号池差距分析（多账号策略、状态管理、锁机制） | ✅ 已完成 |

---

## 核心发现

| 关键项 | 值 |
|--------|-----|
| Session Cookie 名 | `monkeycode_ai_session`（用户）/ `monkeycode_ai_team_session`（团队） |
| 后端框架 | Go / Gin |
| 认证方式 | Cookie-based Session |
| Session 存储 | Redis（Hash + Lookup Key 双结构） |
| Session 有效期 | 30 天硬限制，不可刷新 |
| 验证码 | CAP.js / go-cap（50x32 网格） |

---

## 相关章节

- [第一章：系统架构](../01-architecture/README.md) — 认证组件在架构中的位置
- [第七章：代理实现](../07-proxy/README.md) — 代理中的认证模块实现细节