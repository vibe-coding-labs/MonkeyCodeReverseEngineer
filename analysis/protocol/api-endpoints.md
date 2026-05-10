# MonkeyCode 完整 API 端点映射

> 基于 frontend/src/api/Api.ts (Swagger 自动生成) 逆向提取
> 共 100 个端点：89 个需认证 + 11 个公开

## 认证机制

- **方式**: Cookie-based Session（非 JWT）
- **Cookie 名**: `monkeycode_ai_session`
- **存储**: Redis（key: `sess:{session_id}`）
- **Session 内容**: `user_id`, `team_id`, `is_admin`, `is_team_admin`
- **过期**: 可配置的 session TTL
- **CORS**: 支持 credentials

### 认证流程

1. **OAuth 登录** (`GET /api/v1/users/login?provider=github`)
   - 重定向到 OAuth provider
   - 回调后设置 session cookie
2. **Team 登录** (`POST /api/v1/teams/users/login`)
   - Body: `{username, password}` (password 为 MD5 哈希)
   - 成功后设置 session cookie
3. **Admin Impersonate** (`GET /api/v1/auth/impersonate?user_id=xxx`)
   - 仅管理员可用
   - 切换到指定用户的 session

---

## 1. 认证端点 (Auth)

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/users/login | `api.apiUsersLogin()` | Public | OAuth 登录重定向 |
| POST | /api/v1/teams/users/login | `api.apiTeamsUsersLogin()` | Public | Team 用户登录 |
| POST | /api/v1/users/logout | `api.apiUsersLogout()` | Required | 登出 |
| GET | /api/v1/auth/impersonate | `api.apiAuthImpersonate()` | Admin | 管理员模拟用户 |
| POST | /api/v1/public/captcha/challenge | `api.apiPublicCaptchaChallenge()` | Public | 获取验证码 |

## 2. 用户端点 (User)

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/users/me | `api.apiUsersMe()` | Required | 获取当前用户信息 |
| PUT | /api/v1/users/passwords/reset | `api.apiUsersPasswordsReset()` | Required | 重置密码 |
| PUT | /api/v1/users/profiles | `api.apiUsersProfilesUpdate()` | Required | 更新用户资料 |
| GET | /api/v1/users/settings | `api.apiUsersSettingsList()` | Required | 获取用户设置 |
| PUT | /api/v1/users/settings | `api.apiUsersSettingsUpdate()` | Required | 更新用户设置 |

## 3. 模型端点 (Model) — 核心

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/users/models | `api.apiUsersModelsList()` | Required | 列出用户可用模型 |
| POST | /api/v1/users/models | `api.apiUsersModelsCreate()` | Required | 创建用户模型 |
| PUT | /api/v1/users/models/{id} | `api.apiUsersModelsUpdate()` | Required | 更新用户模型 |
| DELETE | /api/v1/users/models/{id} | `api.apiUsersModelsDelete()` | Required | 删除用户模型 |
| GET | /api/v1/users/models/{id}/health-check | `api.apiUsersModelsHealthCheck()` | Required | 模型健康检查 |
| POST | /api/v1/users/models/health-check | `api.apiUsersModelsHealthCheckByConfig()` | Required | 按配置检查健康 |
| GET | /api/v1/teams/models | `api.apiTeamsModelsList()` | Required | 列出团队模型 |
| POST | /api/v1/teams/models | `api.apiTeamsModelsCreate()` | Required | 创建团队模型 |
| PUT | /api/v1/teams/models/{id} | `api.apiTeamsModelsUpdate()` | Required | 更新团队模型 |
| DELETE | /api/v1/teams/models/{id} | `api.apiTeamsModelsDelete()` | Required | 删除团队模型 |

### 模型数据结构

```typescript
interface Model {
  id: number
  provider: ModelProvider       // siliconflow|openai|ollama|deepseek|moonshot|azure_openai|baizhicloud|hunyuan|bailian|volcengine|gemini
  api_key: string              // 加密存储，公开模型前缀 "public:model:"
  base_url: string             // 自定义 API 端点
  model: string                // 模型名称（如 gpt-4, claude-3-opus）
  temperature: number          // 0.0 - 2.0
  is_default: boolean          // 是否为默认模型
  interface_type: InterfaceType // openai_chat|openai_responses|anthropic
  is_free: boolean             // 是否免费模型
  access_level: AccessLevel    // basic|pro
  thinking_enabled: boolean    // 是否启用思考模式
  context_limit: number        // 上下文窗口限制
  output_limit: number         // 输出长度限制
  owner: OwnerType             // private|team|public
}
```

## 4. 任务/VM 端点 (Task/VM) — 核心

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| POST | /api/v1/users/hosts/vms | `api.apiUsersHostsVmsCreate()` | Required | 创建 VM |
| GET | /api/v1/users/hosts/vms | `api.apiUsersHostsVmsList()` | Required | 列出 VM |
| DELETE | /api/v1/users/hosts/vms/{id} | `api.apiUsersHostsVmsDelete()` | Required | 删除 VM |
| POST | /api/v1/users/tasks | `api.apiUsersTasksCreate()` | Required | 创建任务 |
| GET | /api/v1/users/tasks | `api.apiUsersTasksList()` | Required | 列出任务 |
| GET | /api/v1/users/tasks/{id} | `api.apiUsersTasksGet()` | Required | 获取任务详情 |
| DELETE | /api/v1/users/tasks/{id} | `api.apiUsersTasksDelete()` | Required | 删除任务 |
| POST | /api/v1/users/tasks/{id}/stop | `api.apiUsersTasksStop()` | Required | 停止任务 |
| POST | /api/v1/users/tasks/{id}/retry | `api.apiUsersTasksRetry()` | Required | 重试任务 |

### 创建任务请求

```typescript
interface CreateTaskReq {
  vm_id: string
  llm: LLMConfig                // LLM 配置
  coding_agent: CodingAgent     // 1=Codex, 2=Claude, 3=MCAIReview, 4=OpenCode
  mcp_configs: MCPConfig[]      // MCP 工具配置
  config_files: ConfigFile[]    // 配置文件
  prompt: string                // 用户提示
  working_dir: string           // 工作目录
}

interface LLMConfig {
  api_key: string
  base_url: string
  model: string
  api_type: "anthropic" | "openai"
  temperature: number
}
```

## 5. MCP 端点

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/users/mcp/upstreams | `api.apiUsersMcpUpstreamsList()` | Required | 列出 MCP 上游 |
| POST | /api/v1/users/mcp/upstreams | `api.apiUsersMcpUpstreamsCreate()` | Required | 创建 MCP 上游 |
| PUT | /api/v1/users/mcp/upstreams/{id} | `api.apiUsersMcpUpstreamsUpdate()` | Required | 更新 MCP 上游 |
| DELETE | /api/v1/users/mcp/upstreams/{id} | `api.apiUsersMcpUpstreamsDelete()` | Required | 删除 MCP 上游 |
| GET | /api/v1/users/mcp/upstreams/{id}/tools | `api.apiUsersMcpUpstreamsToolsList()` | Required | 列出 MCP 工具 |

## 6. 团队端点 (Team)

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/teams | `api.apiTeamsList()` | Required | 列出团队 |
| POST | /api/v1/teams | `api.apiTeamsCreate()` | Required | 创建团队 |
| PUT | /api/v1/teams/{id} | `api.apiTeamsTeamsUpdate()` | Required | 更新团队 |
| DELETE | /api/v1/teams/{id} | `api.apiTeamsTeamsDelete()` | Required | 删除团队 |
| GET | /api/v1/teams/users | `api.apiTeamsUsersList()` | Required | 列出团队成员 |
| POST | /api/v1/teams/users | `api.apiTeamsUsersCreate()` | Required | 添加团队成员 |
| PUT | /api/v1/teams/users/{id} | `api.apiTeamsUsersUpdate()` | Required | 更新团队成员 |
| DELETE | /api/v1/teams/users/{id} | `api.apiTeamsUsersDelete()` | Required | 删除团队成员 |

## 7. 管理员端点 (Admin)

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/admin/users | `api.apiAdminUsersList()` | Admin | 列出所有用户 |
| PUT | /api/v1/admin/users/{id} | `api.apiAdminUsersUpdate()` | Admin | 更新用户 |
| DELETE | /api/v1/admin/users/{id} | `api.apiAdminUsersDelete()` | Admin | 删除用户 |
| GET | /api/v1/admin/models | `api.apiAdminModelsList()` | Admin | 列出所有模型 |
| POST | /api/v1/admin/models | `api.apiAdminModelsCreate()` | Admin | 创建公开模型 |
| PUT | /api/v1/admin/models/{id} | `api.apiAdminModelsUpdate()` | Admin | 更新模型 |
| DELETE | /api/v1/admin/models/{id} | `api.apiAdminModelsDelete()` | Admin | 删除模型 |
| GET | /api/v1/admin/stats | `api.apiAdminStats()` | Admin | 系统统计 |

## 8. 订阅端点 (Subscription)

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/users/subscriptions | `api.apiUsersSubscriptionsList()` | Required | 列出订阅 |
| POST | /api/v1/users/subscriptions | `api.apiUsersSubscriptionsCreate()` | Required | 创建订阅 |
| GET | /api/v1/users/subscriptions/current | `api.apiUsersSubscriptionsCurrent()` | Required | 当前订阅 |
| GET | /api/v1/users/balance | `api.apiUsersBalance()` | Required | Token 余额 |

## 9. 对话端点 (Conversation)

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| GET | /api/v1/users/conversations | `api.apiUsersConversationsList()` | Required | 列出对话 |
| POST | /api/v1/users/conversations | `api.apiUsersConversationsCreate()` | Required | 创建对话 |
| GET | /api/v1/users/conversations/{id} | `api.apiUsersConversationsGet()` | Required | 获取对话 |
| DELETE | /api/v1/users/conversations/{id} | `api.apiUsersConversationsDelete()` | Required | 删除对话 |
| GET | /api/v1/users/conversations/{id}/messages | `api.apiUsersConversationsMessagesList()` | Required | 列出消息 |
| POST | /api/v1/users/conversations/{id}/messages | `api.apiUsersConversationsMessagesCreate()` | Required | 发送消息 |

## 10. 文件/上传端点

| Method | Path | Api Method | Auth | 说明 |
|--------|------|-----------|------|------|
| POST | /api/v1/uploader/presign | `api.apiUploaderPresign()` | Required | 获取预签名上传 URL |
| POST | /api/v1/uploader/upload | `api.apiUploaderUpload()` | Required | 上传文件 |

## 11. WebSocket 通道

| 通道 | 路径 | 说明 |
|------|------|------|
| Task Stream | `ws://host/ws/tasks/{id}/stream` | 任务输出流（SSE 格式） |
| Task Control | `ws://host/ws/tasks/{id}/control` | 任务控制（停止、重试） |
| TaskLive | `ws://host/ws/tasks/live` | 实时任务状态推送 |

---

## HttpClient 安全配置

```typescript
// Api.ts 中的安全配置
this.securityData = {}  // 存储 auth token
this.securityWorker = (securityData) => {
  return {
    headers: {
      // Cookie-based auth: 浏览器自动携带 session cookie
      // 对于 API 调用，需要手动设置 Cookie header
      Cookie: `monkeycode_ai_session=${securityData.sessionId}`
    }
  }
}
```

## API 调用模式

```typescript
// 前端调用模式
const api = new Api({ baseUrl: "https://monkeycode-ai.com" })
// 浏览器环境：cookie 自动携带
// Node.js 环境：需要手动设置 Cookie header
const result = await api.apiUsersModelsList()
```
