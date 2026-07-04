---
description: 代理架构模块间调用关系 — 基于 10 个 TS 模块源码的完整依赖分析
protocol_version: based on proxy/src/ 全部 10 文件 TypeScript 源码 (3031 行)
confidence: high
last_verified: 2026-06-28
---

# 代理架构模块间调用关系

> **源码覆盖:** `proxy/src/` 全部 10 文件, 3,031 行
> **核心发现:** 三层依赖结构 + 循环依赖避免模式 + 依赖注入架构

## 1. 模块层级依赖图

```
层级 0（入口 + 编排）
  server.ts（331行）
    │
    ├──────────────────────────────────────────────┐
    │              ├──────────┤                    │
    ▼              ▼          ▼                    ▼
层级 1（路由 + 协调器）
  api-routes.ts（545行）  conversation-manager.ts（369行）
    │              │              │
    ▼              ▼              ▼
层级 2（核心业务逻辑）
  task-runner.ts（464行）  account-pool.ts（299行）  models.ts（102行）
    │              │              │              │
    ▼              ▼              ▼              ▼
层级 3（基础服务）
  auth.ts（238行）  admin-login.ts（416行）  browser-headers.ts（87行）  types.ts（180行）
```

**依赖方向:** 高层级模块导入低层级模块，从不反向。`types.ts` 被所有模块引用但不引用任何模块（纯类型定义）。

## 2. 完整的模块间导入关系

### 2.1 server.ts 的导入

```typescript
// server.ts 导入全部 9 个模块中的 7 个
import { AuthManager } from "./auth.js"
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import { AccountPool, AccountConfig, loadAccountFromEnv, loadAccountConfigs } from "./account-pool.js"
import { ConversationManager } from "./conversation-manager.js"
import { createAPIRouter } from "./api-routes.js"
import { initiateLogin, completeLogin, verifySession, discoverImageId, discoverModels, loginWithCallbackUrl } from "./admin-login.js"
```

### 2.2 api-routes.ts 的导入

```typescript
// api-routes.ts 整合 5 个模块的 6 个类/函数
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import { AccountPool } from "./account-pool.js"
import { ConversationManager } from "./conversation-manager.js"
import { AuthManager } from "./auth.js"
import type {
  OpenAIChatCompletionRequest, OpenAIChatCompletionResponse,
  OpenAIChatCompletionChunk, OpenAIModelsResponse, OpenAIMessage,
} from "./types.js"
```

### 2.3 task-runner.ts 的导入

```typescript
// task-runner.ts 依赖 3 个模块
import WebSocket from "ws"
import { AuthManager } from "./auth.js"
import { mkHeaders, wsHeaders } from "./browser-headers.js"
import type {
  MonkeyCodeModel, TaskStreamMessage, ACPSessionUpdate, OpenAIChatCompletionChunk,
} from "./types.js"
```

### 2.4 conversation-manager.ts 的导入

```typescript
// conversation-manager.ts 依赖 3 个模块
import WebSocket from "ws"
import { AuthManager } from "./auth.js"
import { wsHeaders } from "./browser-headers.js"
import type {
  MonkeyCodeModel, OpenAIMessage, OpenAIChatCompletionChunk,
  TaskStreamMessage, ACPSessionUpdate,
} from "./types.js"
```

### 2.5 account-pool.ts 的导入

```typescript
// account-pool.ts 仅依赖 auth.ts
import { AuthManager, LoginMode } from "./auth.js"
```

### 2.6 admin-login.ts 的导入

```typescript
// admin-login.ts 仅依赖 browser-headers.ts
import { mkHeaders, bzHeaders, scHeaders, navHeaders } from "./browser-headers.js"
```

### 2.7 models.ts 的导入

```typescript
// models.ts 依赖 auth.ts + browser-headers.ts + types.ts
import { AuthManager } from "./auth.js"
import { mkHeaders } from "./browser-headers.js"
import type { MonkeyCodeModel, OpenAIModel, ModelProvider, InterfaceType } from "./types.js"
```

### 2.8 browser-headers.ts 的导入

```typescript
// browser-headers.ts — 零依赖（纯工具函数）
// 不导入任何模块
```

## 3. 依赖关系矩阵

| 模块 ↓ \ 依赖 → | types | auth | browser-headers | models | task-runner | account-pool | admin-login | conversation-mgr | api-routes | server |
|----------------|-------|------|----------------|--------|-------------|--------------|-------------|-----------------|------------|--------|
| **types.ts** | — | — | — | — | — | — | — | — | — | — |
| **browser-headers.ts** | — | — | — | — | — | — | — | — | — | — |
| **auth.ts** | — | — | — | — | — | — | — | — | — | — |
| **admin-login.ts** | — | — | ✅ | — | — | — | — | — | — | — |
| **models.ts** | ✅ | ✅ | ✅ | — | — | — | — | — | — | — |
| **account-pool.ts** | — | ✅ | — | — | — | — | — | — | — | — |
| **task-runner.ts** | ✅ | ✅ | ✅ | — | — | — | — | — | — | — |
| **conversation-manager.ts** | ✅ | ✅ | ✅ | — | — | — | — | — | — | — |
| **api-routes.ts** | ✅ | ✅ | — | ✅ | ✅ | ✅ | — | ✅ | — | — |
| **server.ts** | — | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

**模式发现:**
1. `types.ts` 是纯类型模块，零运行时依赖
2. `browser-headers.ts` 是纯工具函数，零依赖
3. `auth.ts` 是基础服务，只依赖 HTTP 内置
4. `admin-login.ts` 仅依赖 browser-headers（复用请求头生成器）
5. `account-pool.ts` 仅依赖 auth，专注账号管理
6. `task-runner.ts` 和 `conversation-manager.ts` 共享 auth + browser-headers + ws 库
7. `api-routes.ts` 是最大的依赖消费者（6 个模块）
8. `server.ts` 导入但不使用所有模块的 API

## 4. 依赖注入模式

代理架构不使用静态导入，而是通过**构造函数注入**传递依赖：

```typescript
// server.ts 中创建实例
const auth = new AuthManager()                            // 基础服务
const modelManager = new ModelManager(auth)               // auth 注入构造
const taskRunner = new TaskRunner(auth)                   // auth 注入构造
const accountPool = new AccountPool(accountConfigs)        // 无需 auth（内部创建 AuthManager）
const conversationManager = new ConversationManager()      // 独立无依赖
const router = createAPIRouter(                            // 路由创建时注入
  modelManager,    // 模型管理
  taskRunner,      // 任务执行
  accountPool,     // 可选：号池
  conversationManager  // 可选：多轮对话
)
```

**可选依赖处理：** `accountPool` 和 `conversationManager` 在函数签名中标记为可选：

```typescript
export function createAPIRouter(
  modelManager: ModelManager,
  taskRunner: TaskRunner,
  accountPool?: AccountPool,            // 可选
  conversationManager?: ConversationManager  // 可选
): Router
```

代码内部使用**安全调用**检查：
```typescript
let conversation = conversationId ? conversationManager?.get(conversationId) : undefined
let accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null
```

## 5. 调用链分析

### 5.1 Chat Completions 调用链

```
Client
  │ POST /v1/chat/completions
  ▼
api-routes.ts → handleChat()
  │ modelManager.resolveModel(modelId)            → models.ts: fetchModels() + 6层回退
  │ conversationManager?.get(conversationId)      → conversation-manager.ts: get()
  │ taskRunner.createTask(model, prompt, ...)      → task-runner.ts: createTask()
  │   auth.authHeaders()                          → auth.ts: getSessionCookie()
  │   mkHeaders()                                 → browser-headers.ts: mkHeaders()
  │ handleStreamResponse()                         → task-runner.ts: streamTask()
  │   wsHeaders()                                 → browser-headers.ts: wsHeaders()
  │ accountPool.releaseWs(auth)                   → account-pool.ts: releaseWs()
```

### 5.2 号池账号获取链

```
api-routes.ts
  │ accountPool.acquireWs()    → account-pool.ts: acquireWs()
  │   └── 过滤 ACTIVE 且 !lockedByWs 的账号
  │   └── 按 lastUsedAt 排序，取最久未用
  │   └── 锁定为 WS 独占模式
  │   └── 返回 AuthManager 实例
  │
  │ accountPool.acquireHttp()  → account-pool.ts: acquireHttp()
  │   └── 同上但不锁定
  │   └── Round-Robin 索引分散负载
  │
  │ accountPool.releaseWs()    → account-pool.ts: releaseWs()
  │   └── 清空 lockedByWs + lockedAt
```

### 5.3 OAuth 登录链

```
server.ts
  │ POST /admin/login/send-code
  ▼
  │ initiateLogin(phone)       → admin-login.ts
  │   startOAuthLogin()        → mkHeaders() → GET /api/v1/users/login
  │   getSCaptchaToken()       → scHeaders() → POST *.s-captcha-r1.com
  │   sendSmsCode(phone,token) → bzHeaders() → POST baizhi.cloud
  │
  │ POST /admin/login/verify
  ▼
  │ completeLogin(code)        → admin-login.ts
  │   baizhiPhoneLogin()       → POST baizhi.cloud (Step 4)
  │   baizhiOAuthAuthorize()   → GET baizhi.cloud (Step 5)
  │   monkeycodeCallback()     → GET monkeycode-ai.com (Step 6)
  │   discoverImageId()        → GET /api/v1/users/tasks
  │   discoverModels()         → GET /api/v1/users/models
  │   verifySession()          → GET /api/v1/users/status
```

## 6. 模块职责边界

| 模块 | 拥有的数据 | 无副作用 | 副作用 | 需要持久化 |
|------|-----------|---------|--------|-----------|
| types.ts | 全部类型定义 | ✅ | 无 | 不适用 |
| browser-headers.ts | 请求头常量 | ✅ | 无 | 不适用 |
| auth.ts | Session Cookie + 凭据 | ❌ | 写入 Cookie 缓存 | 仅内存 |
| models.ts | 模型列表缓存 | ❌ | API 调用更新缓存 | 仅内存（5min TTL）|
| task-runner.ts | WebSocket 连接 | ❌ | 创建/终止任务 | 不适用 |
| account-pool.ts | 账号状态映射 | ❌ | 定期健康检查 HTTP 调用 | 仅内存 |
| conversation-manager.ts | 对话 Map | ❌ | WS 连接管理 | 仅内存（30min TTL）|
| admin-login.ts | OAuth 会话状态 | ❌ | 短信发送/OAuth 交互 | 仅内存（10min TTL）|
| api-routes.ts | Express Router | ❌ | HTTP 响应写入 | 不适用 |
| server.ts | Express App | ❌ | 服务器监听 | 不适用 |

## 7. 关键设计模式总结

| 模式 | 体现位置 | 说明 |
|------|---------|------|
| **依赖注入** | `api-routes.ts` 函数参数 | 运行时传入依赖而非静态 import |
| **可选依赖** | `accountPool?` 和 `conversationManager?` | 不配置时功能降级 |
| **安全调用** | `?.` 操作符 | 避免可选依赖 undefined 错误 |
| **TypeScript 类型隔离** | `types.ts` 纯类型 | 类型与实现分离 |
| **短路评估** | `acquireWs() \|\| acquireHttp()` | WS 优先，回退 HTTP |
| **Promise.allSettled** | `account-pool.ts initAll()` | 并发初始化，部分失败不阻断全部 |
| **AbortController** | `api-routes.ts` 流式响应 | 客户端断开时终止任务流 |
| **try/finally** | `api-routes.ts` WS 释放 | 确保无论成功/错误都释放锁 |

---

## 相关章节

- [代理 server.ts 启动与中间件链](08-server-startup.md) — 入口编排细节
- [API 路由源码分析](../05-api/01-endpoint-catalog.md) — api-routes.ts 路由
- [AuthManager 源码](auth.ts) — Session 管理
- [账号号池源码](02-account-pool.md) — 多账号轮转
- [OAuth HTTP 自动化](09-oauth-http-automation-deep.md) — 6 步登录流程
