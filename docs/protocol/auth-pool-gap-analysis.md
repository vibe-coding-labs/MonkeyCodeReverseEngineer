# MonkeyCode 认证协议缺口分析（账号池视角）

> 分析日期: 2026-05-11

---

## 1. 已覆盖模块清单

| 模块 | 文档位置 | 覆盖度 | 说明 |
|------|---------|--------|------|
| Session 存储机制 | auth-protocol-complete.md §1 | 90% | Redis Hash 结构完整，缺 session data JSON schema |
| 验证码系统 | auth-protocol-complete.md §2 | 85% | API 规格完整，缺自动化破解评估 |
| 百智云 OAuth | auth-protocol-complete.md §3 | 70% | 流程完整，回调处理闭源 |
| 用户密码登录 | auth-protocol-complete.md §4 | 80% | API 规格完整，**密码格式未确认** |
| 团队管理员登录 | auth-protocol-complete.md §5 | 85% | API 规格完整，cookie 线上名称未验证 |
| Git OAuth 绑定 | auth-protocol-complete.md §6 | 75% | API 端点完整，回调闭源 |
| Admin Impersonate | auth-protocol-complete.md §7 | 60% | 仅流程描述，token 生成完全闭源 |
| 认证中间件 | auth-protocol-complete.md §8 | 95% | 源码已完整获取 |
| 密码管理接口 | auth-protocol-complete.md §9 | 90% | 完整规格 |
| 闭源组件清单 | auth-protocol-complete.md §10 | 100% | 完整 |
| 反向代理策略 | auth-protocol-complete.md §11 | 70% | 仅 Cookie 复用和自动登录，缺池化设计 |

---

## 2. 未覆盖模块清单（按优先级）

| 优先级 | 模块 | 说明 | 对账号池的影响 |
|--------|------|------|---------------|
| **P0** | 授权/权限层级 | 角色体系、API 访问控制矩阵完全缺失 | 账号池需要知道每个账号能调用哪些 API |
| **P0** | 密码传输格式 | MD5 还是明文未确认 | 影响账号池存储格式和登录自动化 |
| **P1** | 并发 Session 策略 | 多 session 共存还是互踢未分析 | 影响账号池并发设计 |
| **P1** | Session 保活/轮换 | 仅提到 status 检查，缺完整保活协议 | 影响账号池长期运行稳定性 |
| **P2** | 验证码自动化评估 | 仅描述协议，缺可行性评估 | 影响自动登录方案选择 |
| **P2** | 团队管理员 cookie 线上名称 | 源码是 `monkeycode_ai_team_session`，线上可能被覆盖 | 影响团队账号池 |
| **P3** | Session data JSON schema | Redis 中存储的完整 JSON 结构未文档化 | 影响深度调试 |

---

## 3. 账号池场景特需的协议缺口

### 3.1 账号池核心问题

账号池需要解决以下核心问题，现有文档均未覆盖：

1. **Session 获取自动化** — 如何批量获取有效 session？
2. **Session 有效性检测** — 如何快速判断 session 是否过期？
3. **Session 保活** — 如何延长 session 有效期？
4. **Session 轮换** — 如何在 session 过期前平滑切换？
5. **并发安全** — 同一 session 是否可以并发使用？
6. **错误恢复** — 各种错误码对应的自动恢复策略？
7. **权限边界** — 不同角色账号能访问哪些 API？

### 3.2 关键未决问题

| 问题 | 现状 | 验证方法 | 影响 |
|------|------|---------|------|
| 密码是 MD5 还是明文？ | 源码注释 MD5，前端代码传明文 | 实测两种格式 | 账号池存储格式 |
| 团队 cookie 线上名称？ | 源码 `monkeycode_ai_team_session` | 抓包或实测 | 团队账号池 |
| 同一用户多 session 并发？ | 源码支持多 session | 实测并发调用 | 并发设计 |
| Session 过期时间？ | 由 `config.Session.ExpireDay` 控制 | 实测观察 | 保活策略 |
| 是否有异常并发检测？ | 源码无显式检测 | 实测高频调用 | 风控规避 |

---

## 4. 建议的补充分析顺序

1. **授权矩阵** → 确定账号池需要哪些角色
2. **密码格式确认** → 确定账号池存储格式
3. **并发 Session 分析** → 确定并发策略
4. **账号池协议设计** → 综合所有分析产出最终方案