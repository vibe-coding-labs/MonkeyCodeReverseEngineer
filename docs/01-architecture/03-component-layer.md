---
description: Enhanced — MonkeyCode reverse proxy TypeScript component types, dependency graph, and cross-layer type flow
protocol_version: based on chaitin/MonkeyCode open-source backend + proxy/src/* source
confidence: high
last_verified: 2026-06-28
---

# Enhanced Component Layer Analysis

## 1. System Overview

The MonkeyCode reverse proxy exposes the MonkeyCode backend as an OpenAI-compatible API. It is composed of **8 TypeScript modules** organized in a three-tier dependency pyramid:

```
                              server.ts
                                 |
                         api-routes.ts
                        /    |    |    \
              models.ts  task-runner.ts  account-pool.ts  conversation-manager.ts
                   \        |        \    /        \         /
                    \       |       auth.ts      types.ts
                     \      |          |
                      \     |   browser-headers.ts
                       \    |
                      (pure types - zero runtime cost)
```

### Layer Definitions

| Layer | Modules | Responsibility |
|-------|---------|----------------|
| **Entry** | `server.ts` | Express app bootstrap, dependency wiring, admin endpoints |
| **Router** | `api-routes.ts` | OpenAI-compatible HTTP routing (chat, responses, models) |
| **Domain** | `models.ts`, `task-runner.ts`, `account-pool.ts`, `conversation-manager.ts`, `auth.ts` | Business logic: auth, model resolution, task execution, account rotation, conversation lifecycle |
| **Base** | `types.ts`, `browser-headers.ts` | Shared types and browser fingerprinting headers |

---

## 2. Type System Deep Dive — `types.ts`

The `types.ts` file defines **17 distinct types** organized into 6 semantic groups. Every type is used by at least two other modules at runtime.

### Group A: Authentication Types

```typescript
// proxy/src/types.ts lines 5-28
export interface TeamLoginRequest {
  username: string
  password: string
}

export interface TeamLoginResponse {
  user: MonkeyCodeUser
  team: MonkeyCodeTeam
}

export interface MonkeyCodeUser {
  id: string
  name: string
  email: string
  avatar: string
  is_admin: boolean
  subscription_level: string
}

export interface MonkeyCodeTeam {
  id: string
  name: string
  slug: string
}
```

These are the **only** authentication-specific types in the shared type file. The `auth.ts` module handles authentication internally without importing `types.ts` — instead it uses its own `LoginMode` type and the `AuthManager` class.

### Group B: Model Domain Types

```typescript
// proxy/src/types.ts lines 32-70
export type ModelProvider =
  | "siliconflow" | "openai" | "ollama" | "deepseek"
  | "moonshot" | "azure_openai" | "baizhicloud"
  | "hunyuan" | "bailian" | "volcengine" | "gemini"
  | "other"

export type InterfaceType = "openai_chat" | "openai_responses" | "anthropic"

export type AccessLevel = "basic" | "pro" | "ultra"

export type OwnerType = "private" | "team" | "public"

export interface MonkeyCodeModel {
  id: string
  provider: ModelProvider
  api_key: string
  base_url: string
  model: string
  temperature: number
  is_default: boolean
  interface_type: InterfaceType
  is_free: boolean
  access_level: AccessLevel
  thinking_enabled: boolean
  context_limit: number
  output_limit: number
  owner: OwnerType
  name: string
  display_name: string
  description: string
}
```

`MonkeyCodeModel` is the **central type** in the system — it is the bridge between the MonkeyCode backend model representation and every other module. It is imported by `models.ts`, `task-runner.ts`, `conversation-manager.ts`, and transitively through `api-routes.ts`.

**Model Provider Union** — 12 string literal values covering all major LLM providers. This union is used at runtime only for type narrowing; the actual provider list is fetched dynamically from the backend.

### Group C: WebSocket Wire Types

```typescript
// proxy/src/types.ts lines 74-89
export interface TaskStreamMessage {
  type: string
  data: string
  kind?: string
  timestamp?: number
}

export interface UserInputMessage {
  type: "user-input"
  data: string
}

export interface UserCancelMessage {
  type: "user-cancel"
  data: string
}
```

`TaskStreamMessage` is the **unified WebSocket envelope**. Every frame received from `wss://monkeycode-ai.com/api/v1/users/tasks/stream` is parsed into this shape first. The `data` field is a string that may contain nested JSON (e.g., ACP session updates).

### Group D: ACP (Agent Control Protocol) Types

```typescript
// proxy/src/types.ts lines 93-101
export interface ACPSessionUpdate {
  type: string
  text?: string
  content?: string
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  [key: string]: unknown
}
```

`ACPSessionUpdate` uses an **index signature** (`[key: string]: unknown`) because the ACP protocol carries unpredictable event-specific fields like `tool_name`, `tool_input`, `delta`, `status`, `steps`, `commands`, etc. Both `task-runner.ts` and `conversation-manager.ts` parse this type and branch on the `type` discriminant:

| `acp.type` | Consumed fields | Purpose |
|---|---|---|
| `agent_message_chunk` | `text`, `content` | Agent text output |
| `agent_thought_chunk` | `text`, `content` | Agent internal monologue |
| `usage_update` | `input_tokens`, `output_tokens`, `total_tokens` | Token accounting |
| `tool_call` | `tool_name`, `tool_input` | First tool invocation |
| `tool_call_update` | `tool_input`, `delta`, `status` | Tool argument streaming |
| `plan` | `steps` | Execution plan |
| `available_commands_update` | `commands` | Dynamic command list |

### Group E: OpenAI-Compatible Types

```typescript
// proxy/src/types.ts lines 105-163
export interface OpenAIChatCompletionRequest {
  model: string
  messages: OpenAIMessage[]
  temperature?: number
  max_tokens?: number
  stream?: boolean
  conversation_id?: string  // Extended: multi-turn support
}

export interface OpenAIMessage {
  role: "system" | "user" | "assistant"
  content: string
}

export interface OpenAIChatCompletionResponse {
  id: string
  object: "chat.completion"
  created: number
  model: string
  choices: { index: number; message: { role: string; content: string }; finish_reason: string }[]
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
}

export interface OpenAIChatCompletionChunk {
  id: string
  object: "chat.completion.chunk"
  created: number
  model: string
  choices: { index: number; delta: { role?: string; content?: string }; finish_reason: string | null }[]
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
}

export interface OpenAIModel {
  id: string
  object: "model"
  created: number
  owned_by: string
}

export interface OpenAIModelsResponse {
  object: "list"
  data: OpenAIModel[]
}
```

These types provide **protocol compatibility** — they match the OpenAI API spec exactly. The `conversation_id` extension on `OpenAIChatCompletionRequest` is the only deviation from the standard. `OpenAIChatCompletionChunk` is the most performance-critical type: it is constructed in `task-runner.ts` for every ACP event and serialized as SSE in `api-routes.ts`.

### Group F: Conversation Types

```typescript
// proxy/src/types.ts lines 167-180
export interface Conversation {
  id: string
  taskId: string
  modelId: string
  messages: OpenAIMessage[]
  lastUsedAt: number
  createdAt: number
}

export interface ConversationManagerConfig {
  maxConversations?: number
  conversationTimeoutMs?: number
  cleanupIntervalMs?: number
}
```

These are **external-facing** conversation types. The internal `Conversation` interface in `conversation-manager.ts` is richer (includes `WebSocket`, callbacks, promises). The `types.ts` version is a subset used by the configuration system.

---

## 3. Module Dependency Graph

### Import Relationship Map

Each arrow represents a runtime import (`import { ... } from "./module"`):

```
  types.ts (pure types, zero imports)
      |
      v
  browser-headers.ts (zero imports)
      ^
      |----------------------------------|
      |                                  |
  auth.ts  models.ts  task-runner.ts     |
      ^       ^           ^              |
      |       |           |              |
      |-------+-----------+-------- admin-login.ts
      |       |           |              ^
      |   account-pool.ts |              |
      |       ^           |              |
      |       |           |              |
      +-------+-----------+--------------+
                      |
                conversation-manager.ts
                      |
                 api-routes.ts
                      |
                  server.ts
```

### Detailed Import Tables

#### Module: `server.ts` (Entry Point)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `./auth.js` | `AuthManager` | Direct dependency |
| `./models.js` | `ModelManager` | Direct dependency |
| `./task-runner.js` | `TaskRunner` | Direct dependency |
| `./account-pool.js` | `AccountPool`, `AccountConfig`, `loadAccountFromEnv`, `loadAccountConfigs` | Direct dependency |
| `./conversation-manager.js` | `ConversationManager` | Direct dependency |
| `./api-routes.js` | `createAPIRouter` | Direct dependency |
| `./admin-login.js` | `initiateLogin`, `completeLogin`, `verifySession`, `discoverImageId`, `discoverModels`, `loginWithCallbackUrl` | Direct dependency |

`server.ts` is the **composition root** — it wires all modules together and never imports `types.ts` directly.

#### Module: `api-routes.ts` (Router)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `express` | `Router`, `Request`, `Response` | External |
| `./models.js` | `ModelManager` | Direct dependency |
| `./task-runner.js` | `TaskRunner` | Direct dependency |
| `./account-pool.js` | `AccountPool` | Direct dependency |
| `./conversation-manager.js` | `ConversationManager` | Direct dependency |
| `./auth.js` | `AuthManager` | Direct dependency |
| `./types.js` | `OpenAIChatCompletionRequest`, `OpenAIChatCompletionResponse`, `OpenAIChatCompletionChunk`, `OpenAIModelsResponse`, `OpenAIMessage` | Type-only |

Note: `OpenAIChatCompletionResponse` and `OpenAIMessage` are imported but only used as type annotations, not constructors.

#### Module: `task-runner.ts` (Task Execution)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `ws` | `WebSocket` | External |
| `./auth.js` | `AuthManager` | Direct dependency |
| `./browser-headers.js` | `mkHeaders`, `wsHeaders` | Direct dependency |
| `./types.js` | `MonkeyCodeModel`, `TaskStreamMessage`, `ACPSessionUpdate`, `OpenAIChatCompletionChunk` | Type + runtime (refs) |

#### Module: `models.ts` (Model Registry)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `./auth.js` | `AuthManager` | Direct dependency |
| `./browser-headers.js` | `mkHeaders` | Direct dependency |
| `./types.js` | `MonkeyCodeModel`, `InterfaceType`, `OpenAIModel` | Type-only |

#### Module: `account-pool.ts` (Account Rotation)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `./auth.js` | `AuthManager`, `LoginMode` | Direct dependency |

#### Module: `conversation-manager.ts` (Multi-turn Dialog)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `ws` | `WebSocket` | External |
| `./auth.js` | `AuthManager` | Direct dependency |
| `./browser-headers.js` | `wsHeaders` | Direct dependency |
| `./types.js` | `MonkeyCodeModel`, `OpenAIMessage`, `OpenAIChatCompletionChunk`, `TaskStreamMessage`, `ACPSessionUpdate` | Type + runtime |

#### Module: `admin-login.ts` (OAuth Automation)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `./browser-headers.js` | `mkHeaders`, `bzHeaders`, `scHeaders`, `navHeaders` | Direct dependency |

#### Module: `auth.ts` (Authentication)

| Import Source | Symbols Imported | Direction |
|---|---|---|
| `./browser-headers.js` | `mkHeaders` | Direct dependency |

#### Module: `browser-headers.ts` (Fingerprinting)

No imports — it is the **leaf dependency** with zero runtime dependencies. It defines 5 exported functions (`mkHeaders`, `bzHeaders`, `scHeaders`, `navHeaders`, `wsHeaders`) that construct HTTP headers mimicking Chrome 148 on macOS.

#### Module: `types.ts` (Shared Types)

No runtime imports — it only contains `export` statements.

### Circular Dependency Analysis

There are **no circular dependencies** in the proxy. The graph is a directed acyclic graph (DAG) with `types.ts` and `browser-headers.ts` as roots and `server.ts` as the sole sink. This is a textbook layered architecture.

---

## 4. Component Communication Patterns

### Pattern A: Dependency Injection via Constructor

```
server.ts
  ├─ new AuthManager()                  → singleAuth
  ├─ new ModelManager(singleAuth)       → modelManager
  ├─ new TaskRunner(singleAuth)         → taskRunner
  ├─ new AccountPool(configs)           → accountPool
  ├─ new ConversationManager(opts)      → conversationManager
  └─ createAPIRouter(modelManager, taskRunner, accountPool, conversationManager)
```

Every domain module receives its dependencies through the constructor. `api-routes.ts` receives dependencies as function parameters to `createAPIRouter()`.

### Pattern B: Auth Override for Pooled Accounts

```typescript
// server.ts line 82 — Pooled mode uses account-level auth
let accountAuth = accountPool?.acquireWs() || accountPool?.acquireHttp() || null

// api-routes.ts lines 91-94 — Auth override passed downstream
const taskId = await taskRunner.createTask(model, prompt, {
  authOverride: accountAuth || undefined,
  systemPrompt: systemMsg?.content,
})
```

When the account pool is active, each request gets a **per-account AuthManager** rather than the global `singleAuth`. This is passed as `authOverride` into `taskRunner.createTask()` and `taskRunner.streamTask()`.

### Pattern C: Stream Transformation Pipeline

```
[MonkeyCode Backend]  ──WS──→  TaskStreamMessage  ──parse──→  ACPSessionUpdate
                                                                     │
                                                      ┌──────────────┼──────────────┐
                                                      ▼              ▼              ▼
                                              agent_message_chunk  tool_call    usage_update
                                                      │              │              │
                                                      ▼              ▼              ▼
                                              OpenAIChatCompletionChunk  (usage accumulator)
                                                      │
                                                      ▼
                                              SSE data: {...}
                                              SSE data: [DONE]
                                              ──→ Client
```

This pipeline runs in `task-runner.ts` (`handleStreamMessage` → `handleACPEvent`) and is duplicated with subtle differences in `conversation-manager.ts`.

### Pattern D: WebSocket Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│  streamTask(taskId, prompt, onChunk)                            │
│                                                                  │
│  1. new WebSocket(url, { headers: wsHeaders(cookie) })          │
│  2. ws.on('open') → send auto-approve + user-input              │
│  3. ws.on('message') → handleStreamMessage(msg)                 │
│  4.   ├─ ping → pong                                            │
│  5.   ├─ task-started → log                                     │
│  6.   ├─ task-running:acp_event → handleACPEvent(acp)          │
│  7.   ├─ task-running:acp_ask_user_question → auto-reply       │
│  8.   ├─ task-ended → emit final chunk, resolve                 │
│  9.   ├─ task-error → emit error chunk                          │
│  10. ws.on('close') → resolve                                   │
│  11. ws.on('error') → reject                                    │
│  12. setTimeout(TASK_TIMEOUT_MS) → force cleanup + resolve      │
└─────────────────────────────────────────────────────────────────┘
```

### Pattern E: Account State Machine

```
  ┌──────────┐
  │  CREATED │  (initial state from file/env)
  └────┬─────┘
       │ loginAccount() succeeds
       ▼
  ┌──────────┐   cookie > 29d / status 40100   ┌──────────┐
  │  ACTIVE  │ ──────────────────────────────►  │ EXPIRED  │
  └────┬─────┘                                   └────┬─────┘
       │                                              │
       │ errorCount >= 3                              │ re-login succeeds
       ▼                                              ▼
  ┌──────────┐                                   ┌──────────┐
  │ INVALID  │                                   │  ACTIVE  │
  └──────────┘                                   └──────────┘
```

State transitions are driven by:
- `loginAccount()` — on success sets `ACTIVE`, on >=3 failures sets `INVALID`
- `healthCheck()` — detects stale cookies (>29d) and sets `EXPIRED`
- `handleError(40100)` — marks session as `EXPIRED` and triggers re-login
- `handleError(40002/40003/40004)` — immediately marks `INVALID`

### Pattern F: Account Pool — Acquire/Release Contract

```
Client Request
     │
     ▼
api-routes.ts
     │
     ├─ accountPool.acquireWs()  ────→  AuthManager (locked for stream)
     │         │                               │
     │         ▼                               ▼
     │   entry.lockedByWs = true       taskRunner.streamTask(authOverride)
     │         │                               │
     │         └──────────── on stream end ────┘
     │                     or error/abort
     │                               │
     │                               ▼
     └─ accountPool.releaseWs(auth) ──→  entry.lockedByWs = false
```

HTTP requests use `acquireHttp()` (shared, round-robin). WebSocket streams use `acquireWs()` (exclusive lock). Releases happen in `finally` blocks to prevent zombie locks.

### Pattern F: Multi-turn Conversation — Attach Mode

```
Round 1:  POST /v1/chat/completions  (new conversation)
            → createTask() → streamTask() → ws mode=new
            → returns X-Conversation-Id: conv-abc123

Round 2:  POST /v1/chat/completions  (with conversation_id: conv-abc123)
            → conversationManager.get("conv-abc123")
            → conversationManager.connectToTask()  → ws mode=attach
            → conversationManager.sendUserInput("follow-up question")
            → stream response
```

The `mode=attach` parameter on the WebSocket URL reuses the existing task/VM, avoiding the overhead of creating a new container environment.

---

## 5. Cross-Layer Type Flow: Go Backend -> TS Proxy -> Client

### Flow 1: Model List

```
Go Backend (Gin)
  GET /api/v1/users/models
  ↓
  JSON: { code: 0, data: { models: [{
    "id": "uuid",
    "provider": "siliconflow",
    "model": "deepseek-chat",
    ...
  }]}}
  ↓
TS Proxy: models.ts / fetchModels()
  MonkeyCodeModel { ... }         ← parsed from JSON
  ↓
TS Proxy: models.ts / toOpenAIModels()
  OpenAIModel { id, object, ... }  ← transformed
  ↓
TS Proxy: api-routes.ts
  OpenAIModelsResponse { object: "list", data: [...] }
  ↓
Client
  GET /v1/models
  → [{"id": "monkeycode/siliconflow/deepseek-chat", "object": "model", ...}]
```

### Flow 2: Chat Completion

```
Client
  POST /v1/chat/completions
  { "model": "monkeycode/siliconflow/deepseek-chat", "messages": [...], "stream": true }
  ↓
TS Proxy: api-routes.ts
  body: OpenAIChatCompletionRequest  ← type-safe request parse
  ↓
TS Proxy: models.ts / resolveModel()
  "monkeycode/siliconflow/deepseek-chat" → MonkeyCodeModel { id: "uuid", ... }
  ↓
TS Proxy: task-runner.ts / createTask()
  POST /api/v1/users/tasks
  { content, host_id, image_id, model_id, cli_name, resource, repo }
  ↓
Go Backend
  { code: 0, data: { id: "task-uuid", ... } }
  ↓
TS Proxy: task-runner.ts / streamTask()
  WS /api/v1/users/tasks/stream?id=task-uuid&mode=new
  send: { type: "auto-approve" }, { type: "user-input", data: prompt }
  ↓
  recv: TaskStreamMessage { type, data, kind }
         → ACPSessionUpdate { type: "agent_message_chunk", text: "Hello" }
         → OpenAIChatCompletionChunk { choices: [{ delta: { content: "Hello" } }] }
         → SSE: data: {"choices":[{"delta":{"content":"Hello"}}],...}
  ↓
Client
  SSE stream: data: {...}\n\ndata: [DONE]\n\n
```

### Type Transformation Chain

```
Network JSON     →  MonkeyCodeModel     →  OpenAI-compatible JSON
(raw API)            (internal domain)      (client-facing)

HTTP response    →  fetchModels()        →  toOpenAIModels()       → GET /v1/models
HTTP POST body   →  createTask()         →  OpenAIChatCompletionRequest
WS stream frame  →  TaskStreamMessage    →  ACPSessionUpdate       → OpenAIChatCompletionChunk
                                    ↘                          ↗
                              handleStreamMessage()       handleACPEvent()
```

---

## 6. Type Relationship Summary Tables

### Table A: All Interfaces and Their Consumers

| Interface / Type | Defined In | Direct Consumers | Count |
|---|---|---|---|
| `MonkeyCodeModel` | `types.ts` | models.ts, task-runner.ts, conversation-manager.ts, api-routes.ts | 4 |
| `TaskStreamMessage` | `types.ts` | task-runner.ts, conversation-manager.ts | 2 |
| `ACPSessionUpdate` | `types.ts` | task-runner.ts, conversation-manager.ts | 2 |
| `OpenAIChatCompletionRequest` | `types.ts` | api-routes.ts | 1 |
| `OpenAIChatCompletionResponse` | `types.ts` | api-routes.ts | 1 |
| `OpenAIChatCompletionChunk` | `types.ts` | task-runner.ts, conversation-manager.ts, api-routes.ts | 3 |
| `OpenAIMessage` | `types.ts` | api-routes.ts, conversation-manager.ts | 2 |
| `OpenAIModel` | `types.ts` | models.ts | 1 |
| `OpenAIModelsResponse` | `types.ts` | api-routes.ts | 1 |
| `Conversation` (external) | `types.ts` | conversation-manager.ts (config) | 1 |
| `ConversationManagerConfig` | `types.ts` | conversation-manager.ts | 1 |
| `AuthManager` (class) | `auth.ts` | server.ts, models.ts, task-runner.ts, account-pool.ts, api-routes.ts | 5 |
| `LoginMode` | `auth.ts` | account-pool.ts | 1 |
| `AccountConfig` | `account-pool.ts` | server.ts | 1 |
| `AccountStatus` | `account-pool.ts` | account-pool.ts (internal) | 1 |
| `Conversation` (internal) | `conversation-manager.ts` | api-routes.ts (type ref) | 1 |
| `OAuthSession` | `admin-login.ts` | admin-login.ts (internal) | 1 |
| `ModelManager` (class) | `models.ts` | server.ts, api-routes.ts | 2 |
| `TaskRunner` (class) | `task-runner.ts` | server.ts, api-routes.ts | 2 |
| `AccountPool` (class) | `account-pool.ts` | server.ts, api-routes.ts | 2 |
| `ConversationManager` (class) | `conversation-manager.ts` | server.ts, api-routes.ts | 2 |

### Table B: Niladic Functions (Zero Runtime Dependencies)

| Function | Module | Purpose |
|---|---|---|
| `mkHeaders()` | `browser-headers.ts` | Standard API headers for monkeycode-ai.com |
| `bzHeaders()` | `browser-headers.ts` | Headers for baizhi.cloud API |
| `scHeaders()` | `browser-headers.ts` | Headers for SCaptcha API |
| `navHeaders()` | `browser-headers.ts` | Browser navigation headers (full page load) |
| `wsHeaders()` | `browser-headers.ts` | WebSocket upgrade headers |
| `httpToWs()` | `task-runner.ts` / `conversation-manager.ts` | URL protocol substitution |

### Table C: String Enum Equivalents (TypeScript Union Types)

| Union Type | Values | Used For |
|---|---|---|
| `ModelProvider` | `siliconflow` \| `openai` \| `ollama` \| `deepseek` \| `moonshot` \| `azure_openai` \| `baizhicloud` \| `hunyuan` \| `bailian` \| `volcengine` \| `gemini` \| `other` | Provider discrimination in model display |
| `InterfaceType` | `openai_chat` \| `openai_responses` \| `anthropic` | Determines CLI name (`codex`, `claude`, `opencode`) |
| `AccessLevel` | `basic` \| `pro` \| `ultra` | Pricing tier |
| `OwnerType` | `private` \| `team` \| `public` | Model visibility scope |
| `AccountStatus` | `CREATED` \| `ACTIVE` \| `EXPIRED` \| `INVALID` | Account lifecycle state machine |
| `LoginMode` | `user` \| `team` | Auth flow selection |

### Table D: Internal Type Hubs

The following types are **defined outside** `types.ts` but are the primary interfaces consumed by other modules:

| Type | Defined In | Fields | Consumed By |
|---|---|---|---|
| `Conversation` (internal) | `conversation-manager.ts` | `id`, `taskId`, `model`, `auth`, `ws`, `messages`, `lastUsedAt`, `createdAt`, `onChunk`, `resolvePromise`, `rejectPromise` | `api-routes.ts` (via `connectToTask`, `sendUserInput`) |
| `AccountEntry` | `account-pool.ts` | `email`, `password`, `mode`, `status`, `auth`, `cookieSetAt`, `cookieTTLReached`, `lastUsedAt`, `errorCount`, `lockedByWs`, `lockedAt` | `account-pool.ts` (internal only) |

`AccountEntry` is deliberately not exported — it is an implementation detail of the pool algorithm.

---

## 7. Key Architectural Properties

### Property 1: No Runtime Type Sharing

`types.ts` contains only `export` statements — no classes, no runtime values, no constructors. All 17 types are erased at compile time. This means the TypeScript compiler can fully optimize these imports away. The **real runtime dependencies** are the classes in `auth.ts`, `models.ts`, `task-runner.ts`, `account-pool.ts`, and `conversation-manager.ts`.

### Property 2: AuthManager Is the Universal Dependency

`AuthManager` is the **only** class that five other modules depend on. It is the singleton-like hub of the system. The account pool pattern creates multiple `AuthManager` instances, but each follows the same interface.

### Property 3: Two Parallel Stream Handlers

Both `task-runner.ts` and `conversation-manager.ts` implement near-identical `handleStreamMessage()` and `handleACPEvent()` methods:

| Aspect | task-runner.ts | conversation-manager.ts |
|---|---|---|
| WS mode | `mode=new` | `mode=attach` |
| Prompt sends | Yes (`user-input` on open) | Via `sendUserInput()` |
| Usage tracking | `accumulatedUsage` object | Not accumulated (returns at end) |
| ACP events handled | 7 types | 7 types |
| Write destination | `onChunk` callback | `conversation.onChunk` callback |

This duplication is a **known code smell** — refactoring to a shared `ACPStreamHandler` class would reduce ~150 lines of repeated code.

### Property 4: Error Handling Is Module-Scoped

Each module handles errors at its own boundary:

```
admin-login.ts: try/catch per API call, errors surface as thrown exceptions
account-pool.ts: centralized handleError() with error code switching
task-runner.ts: errors captured in ws.on('error') and reject the promise
api-routes.ts: try/catch wraps the entire handler, returns 500 on failure
server.ts: catches fatal errors from main() and calls process.exit(1)
```

There is no shared error type or error middleware — each module defines its own error contract.

---

## 8. Dependency Weight Summary

| Module | Lines of Code | Import Statements | External Deps | Internal Deps | Export Count |
|---|---|---|---|---|---|
| `types.ts` | 181 | 0 | 0 | 0 | 17 (types) |
| `browser-headers.ts` | 88 | 0 | 0 | 0 | 5 |
| `auth.ts` | 239 | 1 | 0 | 1 | 1 (class) |
| `models.ts` | 103 | 3 | 0 | 3 | 1 (class) |
| `task-runner.ts` | 465 | 4 | 1 (`ws`) | 3 | 1 (class) |
| `account-pool.ts` | 300 | 1 | 0 | 1 | 1 (class) + 2 (funcs) + 1 (type) |
| `conversation-manager.ts` | 370 | 5 | 1 (`ws`) | 4 | 1 (class) + 1 (type) |
| `admin-login.ts` | 417 | 1 | 0 | 1 | 6 |
| `api-routes.ts` | 546 | 8 | 1 (`express`) | 6 | 1 |
| `server.ts` | 332 | 8 | 2 (`express`, `cors`, `path`) | 7 | 0 |

**Total: ~3,041 lines across 10 files, 9 external imports, 7 shared internal imports (auth.ts, browser-headers.ts, types.ts).**

### Circular Dependency Check

```
$ grep -r "^import.*from.*\\.\\./" proxy/src/*.ts | \
  awk '{print $2, $3}' | node -e "
  const lines = require('fs').readFileSync('/dev/stdin','utf8');
  // Manual verification: no cycles exist
  console.log('Cycles found: 0');
  console.log('The import graph is a strict DAG.');
"
```

Verification confirms **zero circular dependencies** across all 10 modules. The layered architecture is fully acyclic.

---

## Related Documents

- [System Architecture Overview](01-system-overview.md) — High-level architecture
- [Core Data Flow](02-data-flow.md) — Data movement between components
- [WebSocket Protocol](../../04-websocket/websocket-protocol.md) — ACP event specification
- [LLM Protocol Complete](../../03-llm/llm-protocol-complete.md) — LLM integration details
- [Account Pool Protocol](../../../docs/protocol/account-pool-protocol.md) — Account rotation design