# MonkeyCode 账号池认证协议完整分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** 完整分析 MonkeyCode 的认证（Authentication）和授权（Authorization）协议，识别现有文档缺口，产出账号池场景所需的完整通信协议报告。

**Architecture:** 分析现有源码和文档 → 识别缺口 → 补充分析 → 产出完整报告。数据流：GitHub 源码 + 线上 API → 逆向分析 → 协议文档 → 账号池设计建议。

**Tech Stack:** Go (Echo framework), Redis (Session), CAP.js/go-cap (验证码), Python (MVP 验证)

**Risks:**
- Task 2 密码格式需要实测确认，无法纯靠源码推断 → 缓解：设计两种格式的测试脚本
- Task 3 授权矩阵部分闭源，只能从中间件和 domain 类型推断 → 缓解：标注置信度
- Task 4 团队管理员 cookie 名线上可能被覆盖 → 缓解：设计验证脚本

---

### Task 1: 审计现有认证协议文档并识别缺口

**Depends on:** None
**Files:**
- Read: `docs/protocol/auth-protocol-complete.md`
- Read: `docs/protocol/llm-protocol-complete.md`
- Read: `docs/protocol/api-endpoints.md`
- Read: `docs/protocol/websocket-protocol.md`
- Create: `docs/protocol/auth-pool-gap-analysis.md`

- [ ] **Step 1: 读取现有认证协议文档，提取已覆盖模块清单**

读取 `docs/protocol/auth-protocol-complete.md`，列出所有已分析的协议模块和每个模块的覆盖程度评分（0-100%）。

- [ ] **Step 2: 读取 LLM 协议和 API 端点文档，提取认证相关交叉引用**

读取 `docs/protocol/llm-protocol-complete.md` 和 `docs/protocol/api-endpoints.md`，提取其中涉及认证/授权的内容（如中间件标注、权限要求）。

- [ ] **Step 3: 对比源码中间件，识别授权层级缺口**

基于已获取的 `backend/middleware/auth.go` 源码（包含 Auth/Check/TeamAuth/TeamAuthCheck/TeamAdminAuth 五种中间件）和 `backend/consts/user.go`（包含 UserRole: individual/enterprise/subaccount/admin/gittask），识别现有文档中**完全未覆盖**的授权分析。

- [ ] **Step 4: 产出缺口分析报告**

创建 `docs/protocol/auth-pool-gap-analysis.md`，包含：
- 已覆盖模块清单 + 覆盖度评分
- 未覆盖模块清单 + 优先级
- 账号池场景特需的协议缺口
- 需要实测确认的未决问题列表

---

### Task 2: 分析授权层级与 API 访问控制矩阵

**Depends on:** Task 1
**Files:**
- Read: `backend/middleware/auth.go` (已获取)
- Read: `backend/consts/user.go` (已获取)
- Read: `backend/domain/user.go` (已获取)
- Read: `backend/domain/team.go` (已获取)
- Read: `backend/domain/model.go` (已获取)
- Read: `backend/biz/task/handler/v1/task.go` (已获取)
- Read: `backend/biz/setting/handler/v1/model.go` (已获取)
- Create: `docs/protocol/authorization-matrix.md`

- [ ] **Step 1: 从源码提取完整角色体系**

基于已获取的源码，整理完整角色体系：

```text
UserRole:
  - individual: 个人用户
  - enterprise: 企业用户（有团队）
  - subaccount: 企业子账户
  - admin: MonkeyCode AI 管理员（配置公共资源）
  - gittask: 全自动 git 任务专用用户

UserStatus:
  - active: 正常
  - inactive: 未激活
  - banded: 被封禁

TeamMemberRole: (从 team.go 推断)
  - team_admin: 团队管理员
  - team_member: 团队成员
```

- [ ] **Step 2: 从路由注册提取 API 访问控制矩阵**

基于已获取的 task handler 和 model handler 源码，提取每个路由使用的中间件组合：

```text
用户级 API:
  Auth() + TargetActive() → 需要普通用户 session
  Check() → 可选认证，未登录也可访问

团队级 API:
  TeamAuth() → 需要 monkeycode_ai_team_session
  TeamAuthCheck() → 可选团队认证
  TeamAdminAuth() → 需要团队管理员权限

公开 API:
  无中间件 → 任何人可访问
```

- [ ] **Step 3: 分析资源所有者层级与访问控制**

基于已获取的 model.go 和 host.go 源码，分析 OwnerType 对资源访问的影响：

```text
OwnerType:
  private → 仅创建者可访问
  team → 团队内共享
  public → 所有认证用户可访问

AccessLevel:
  basic → 基础订阅模型
  pro → 专业订阅模型
```

- [ ] **Step 4: 产出授权矩阵文档**

创建 `docs/protocol/authorization-matrix.md`，包含：
- 完整角色体系定义
- 中间件 → 角色 → API 端点映射表
- 资源所有者层级与访问控制规则
- 账号池场景下的权限边界说明

---

### Task 3: 分析密码传输格式与验证码自动化可行性

**Depends on:** Task 1
**Files:**
- Read: `backend/domain/user.go` (已获取)
- Read: `backend/domain/team.go` (已获取)
- Create: `docs/protocol/auth-automation-analysis.md`

- [ ] **Step 1: 分析密码传输格式的不确定性**

基于源码分析，整理两种可能性：

**可能性 A — 前端 MD5：**
- 前端 `login.tsx` 中 `userPassword.trim()` 传入 `apiRequest`
- `apiRequest` 内部可能做了 MD5 转换（Swagger 生成的客户端代码通常有拦截器）
- 后端 domain 注释标注 `Password` 为 MD5
- 验证方式：发送 `md5("123456")` = `e10adc3949ba59abbe56e057f20f883e`

**可能性 B — 后端 MD5：**
- 前端直接传明文密码
- 后端收到后自行 MD5 再与数据库比较
- 验证方式：发送明文 `"123456"`

**对账号池的影响：**
- 如果是可能性 A，账号池需要存储 MD5 哈希而非明文
- 如果是可能性 B，账号池存储明文密码，登录时直接传

- [ ] **Step 2: 分析验证码自动化可行性**

基于已获取的验证码系统源码（50x32 网格，3 目标，2 分钟挑战过期，5 分钟 token 过期）：

```text
验证码参数:
  网格: 50x32
  目标数: 3
  挑战过期: 120s
  Token过期: 300s
  类型: 图片点击验证码

自动化方案评估:
  1. OCR/图像识别 — 需要识别网格中的目标位置
  2. 预设答案重放 — 不可行，每次挑战不同
  3. 人工辅助 — 可行但无法规模化
  4. Cookie 复用 — 绕过验证码，最推荐
```

- [ ] **Step 3: 分析并发 Session 策略**

基于已获取的 session.go 源码（Redis Hash 存储，同一用户可有多个 session field）：

```text
Session 并发策略:
  - 同一用户可有多个 session（Hash 多 field）
  - 每次登录创建新 session，不删除旧 session
  - 登出只删除当前 session
  - Trunc（踢人）删除用户所有 session

对账号池的影响:
  - 同一账号可同时有多个有效 session
  - 适合账号池场景：一个账号可被多个代理实例复用
  - 风险：服务端可能检测异常并发
```

- [ ] **Step 4: 产出自动化分析文档**

创建 `docs/protocol/auth-automation-analysis.md`，包含：
- 密码传输格式分析与验证方案
- 验证码自动化可行性评估
- 并发 Session 策略分析
- 账号池场景推荐方案

---

### Task 4: 设计账号池通信协议与 Session 管理

**Depends on:** Task 2, Task 3
**Files:**
- Create: `docs/protocol/account-pool-protocol.md`

- [ ] **Step 1: 设计账号池 Session 生命周期协议**

```text
Session 生命周期:
  1. 获取: 通过登录 API 或 Cookie 复用获取 session
  2. 验证: GET /api/v1/users/status 检查有效性
  3. 保活: 定期调用 status 端点刷新 TTL
  4. 轮换: session 过期前切换到新 session
  5. 失效检测: status 返回 40100 时触发重新登录
  6. 清理: 登出或 session 过期后从池中移除
```

- [ ] **Step 2: 设计账号池 API 调用协议**

```text
请求头注入:
  Cookie: sl-session={session_uuid}
  Content-Type: application/json

错误处理:
  40100 → session 失效，触发轮换
  40001 → 验证码失败，需要重新获取
  40002 → 账号密码错误，标记账号异常
  40003 → 用户被封禁，从池中移除
  403 → 权限不足，降级到低权限 API
```

- [ ] **Step 3: 设计多账号并发策略**

```text
并发模型:
  - 每个账号可持有多个 session（Redis Hash 多 field）
  - 同一 session 不应并发使用（WebSocket 互斥）
  - 不同 session 可并发使用
  - 建议每账号 2-3 个 session 轮换使用

负载均衡:
  - Round-robin: 轮询分配 session
  - Least-recently-used: 优先使用最久未用的 session
  - Health-check: 定期验证 session 有效性
```

- [ ] **Step 4: 产出账号池协议文档**

创建 `docs/protocol/account-pool-protocol.md`，包含：
- Session 生命周期管理协议
- API 调用认证注入规范
- 错误码处理与自动恢复策略
- 多账号并发与负载均衡策略
- 推荐的账号池架构设计

---

### Task 5: 整合产出完整认证协议报告

**Depends on:** Task 2, Task 3, Task 4
**Files:**
- Read: `docs/protocol/auth-pool-gap-analysis.md`
- Read: `docs/protocol/authorization-matrix.md`
- Read: `docs/protocol/auth-automation-analysis.md`
- Read: `docs/protocol/account-pool-protocol.md`
- Create: `docs/protocol/auth-protocol-pool-complete.md`

- [ ] **Step 1: 整合所有分析结果为一份完整报告**

将 Task 1-4 的产出整合为一份面向账号池场景的完整认证协议报告，结构：

```text
1. 概述与架构
2. 认证协议（5 种登录方式完整规格）
3. 授权协议（角色体系 + API 访问控制矩阵）
4. Session 管理协议（存储、生命周期、并发策略）
5. 验证码系统与自动化评估
6. 账号池通信协议（Session 池化、轮换、保活、错误恢复）
7. 未决问题与实测验证清单
8. 附录：完整请求/响应示例
```

- [ ] **Step 2: 验证报告完整性**

检查报告是否覆盖账号池所需的所有协议：
- [x] 如何获取 session（5 种方式）
- [x] 如何验证 session 有效性
- [x] 如何保活 session
- [x] 如何处理 session 失效
- [x] 如何并发使用多个 session
- [x] 如何处理验证码
- [x] 如何处理密码格式
- [x] 如何处理权限不足

- [ ] **Step 3: 提交**
Run: `git add docs/protocol/auth-pool-gap-analysis.md docs/protocol/authorization-matrix.md docs/protocol/auth-automation-analysis.md docs/protocol/account-pool-protocol.md docs/protocol/auth-protocol-pool-complete.md && git commit -m "docs: add complete auth protocol analysis for account pool scenario"`