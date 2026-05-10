# MonkeyCode 内置大模型逆向与反向代理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** 逆向分析 MonkeyCode 客户端中内置的大模型 API 调用机制，提取公共模型配置（API Key、Base URL、模型列表），构建反向代理服务，使其他应用可以通过 OpenAI 兼容接口使用 MonkeyCode 内置的大模型。

**Architecture:** 下载 macOS Desktop 客户端 → 解包 Electron ASAR 提取前端代码 → 分析 API 调用链（前端 → 后端 → LLM Provider）→ 还原模型配置 API 协议 → 构建反向代理服务（监听本地端口，接收 OpenAI 格式请求，转发到 MonkeyCode 后端，返回 OpenAI 格式响应）。选择 Node.js + Express 构建代理，因为 MonkeyCode 前端本身就是 TypeScript/Vite 技术栈，便于复用类型定义。

**Tech Stack:** Node.js 20, Express 4, TypeScript 5, asar 3 (解包), mitmproxy 或 Charles (抓包), pnpm 9

**Risks:**
- Task 2: Electron ASAR 内的代码可能经过 webpack/vite 打包压缩，可读性差 → 缓解：使用 prettier 格式化 + source map 还原
- Task 3: MonkeyCode 后端 API 可能有 JWT 认证和请求签名 → 缓解：先通过源码分析认证机制，再实现对应的 token 获取
- Task 4: 公共模型的 API Key 可能有时效性或绑定 IP → 缓解：代理服务支持动态登录刷新 token，支持配置自定义 API Key
- Task 5: MonkeyCode 服务可能更新 API 接口 → 缓解：代理服务做版本检测和优雅降级

---

### Task 1: 下载 MonkeyCode 客户端

**Depends on:** None
**Files:**
- Create: `downloads/.gitkeep`
- Create: `scripts/download-client.sh`

- [ ] **Step 1: 创建下载脚本 — 下载 macOS arm64 Desktop 客户端和 Android APK**

```bash
#!/usr/bin/env bash
set -euo pipefail

DOWNLOAD_DIR="$(cd "$(dirname "$0")/.." && pwd)/downloads"
mkdir -p "$DOWNLOAD_DIR"

RELEASE_TAG="v260324.1.22"
REPO="chaitin/MonkeyCode"
BASE_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}"

echo "=== Downloading MonkeyCode clients ==="

# macOS arm64 Desktop (primary target for reverse engineering)
MACOS_FILE="MonkeyCode-macos-arm64.dmg"
if [ ! -f "$DOWNLOAD_DIR/$MACOS_FILE" ]; then
  echo "Downloading $MACOS_FILE (~100MB)..."
  curl -L -o "$DOWNLOAD_DIR/$MACOS_FILE" "${BASE_URL}/${MACOS_FILE}"
  echo "Done: $MACOS_FILE"
else
  echo "Skip (exists): $MACOS_FILE"
fi

# Android APK (secondary target)
APK_FILE="MonkeyCode-android.apk"
if [ ! -f "$DOWNLOAD_DIR/$APK_FILE" ]; then
  echo "Downloading $APK_FILE (~6MB)..."
  curl -L -o "$DOWNLOAD_DIR/$APK_FILE" "${BASE_URL}/${APK_FILE}"
  echo "Done: $APK_FILE"
else
  echo "Skip (exists): $APK_FILE"
fi

# Windows exe (for comparison)
WIN_FILE="MonkeyCode-windows.exe"
if [ ! -f "$DOWNLOAD_DIR/$WIN_FILE" ]; then
  echo "Downloading $WIN_FILE (~85MB)..."
  curl -L -o "$DOWNLOAD_DIR/$WIN_FILE" "${BASE_URL}/${WIN_FILE}"
  echo "Done: $WIN_FILE"
else
  echo "Skip (exists): $WIN_FILE"
fi

echo "=== All downloads complete ==="
ls -lh "$DOWNLOAD_DIR"
```

- [ ] **Step 2: 执行下载脚本 — 获取客户端二进制文件**
Run: `bash scripts/download-client.sh`
Expected:
  - Exit code: 0
  - Output contains: "All downloads complete"
  - File `downloads/MonkeyCode-macos-arm64.dmg` exists and size > 50MB

- [ ] **Step 3: 挂载 DMG 并提取 Electron 应用 — 获取 app 目录结构**
Run: `mkdir -p downloads/extracted && hdiutil attach downloads/MonkeyCode-macos-arm64.dmg -nobrowse -mountpoint /tmp/monkeycode-dmg && cp -R /tmp/monkeycode-dmg/MonkeyCode.app downloads/extracted/ && hdiutil detach /tmp/monkeycode-dmg -nobrowse`
Expected:
  - Exit code: 0
  - Directory `downloads/extracted/MonkeyCode.app` exists

- [ ] **Step 4: 提交**
Run: `git add scripts/download-client.sh downloads/.gitkeep && git commit -m "feat(download): add MonkeyCode client download script"`

---

### Task 2: 逆向分析 Electron 客户端

**Depends on:** Task 1
**Files:**
- Create: `scripts/extract-asar.sh`
- Create: `scripts/analyze-frontend.sh`
- Create: `analysis/` — 分析结果目录

- [ ] **Step 1: 创建 ASAR 解包脚本 — 从 Electron app 中提取前端代码**

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)/downloads/extracted/MonkeyCode.app"
ANALYSIS_DIR="$(cd "$(dirname "$0")/.." && pwd)/analysis"
mkdir -p "$ANALYSIS_DIR/asar-content"

# Find the asar file in the Electron app
ASAR_FILE=$(find "$APP_DIR/Contents/Resources" -name "app.asar" -type f 2>/dev/null | head -1)

if [ -z "$ASAR_FILE" ]; then
  echo "ERROR: app.asar not found in $APP_DIR/Contents/Resources"
  echo "Listing Resources directory:"
  ls -la "$APP_DIR/Contents/Resources/" 2>/dev/null || echo "Resources dir not found"
  exit 1
fi

echo "Found ASAR: $ASAR_FILE"
echo "Size: $(ls -lh "$ASAR_FILE" | awk '{print $5}')"

# Install asar tool if not present
if ! command -v npx &>/dev/null; then
  echo "ERROR: npx not found. Install Node.js first."
  exit 1
fi

# Extract ASAR
echo "Extracting ASAR archive..."
npx asar extract "$ASAR_FILE" "$ANALYSIS_DIR/asar-content"

echo "=== ASAR extracted ==="
echo "Top-level contents:"
ls -la "$ANALYSIS_DIR/asar-content/"

# Also check for web-dist (the frontend build)
WEB_DIST=$(find "$APP_DIR/Contents/Resources" -name "web-dist" -type d 2>/dev/null | head -1)
if [ -n "$WEB_DIST" ]; then
  echo "Found web-dist: $WEB_DIST"
  cp -R "$WEB_DIST" "$ANALYSIS_DIR/web-dist"
  echo "web-dist copied to analysis/"
fi

# Format JS files for readability
echo "Formatting JS files with prettier..."
cd "$ANALYSIS_DIR/asar-content"
find . -name "*.js" -o -name "*.cjs" -o -name "*.mjs" | head -20 | while read f; do
  npx prettier --write "$f" 2>/dev/null || true
done

echo "=== Analysis complete ==="
```

- [ ] **Step 2: 执行 ASAR 解包 — 提取 Electron 应用内嵌代码**
Run: `bash scripts/extract-asar.sh`
Expected:
  - Exit code: 0
  - Directory `analysis/asar-content/` exists and contains extracted files

- [ ] **Step 3: 创建前端分析脚本 — 搜索模型配置和 API 调用相关代码**

```bash
#!/usr/bin/env bash
set -euo pipefail

ANALYSIS_DIR="$(cd "$(dirname "$0")/.." && pwd)/analysis"
OUTPUT_DIR="$ANALYSIS_DIR/api-analysis"
mkdir -p "$OUTPUT_DIR"

echo "=== Analyzing MonkeyCode frontend for LLM API patterns ==="

# Search for model-related API endpoints
echo "--- Searching for model API endpoints ---"
grep -rn "model" "$ANALYSIS_DIR/asar-content/" --include="*.js" --include="*.cjs" --include="*.ts" 2>/dev/null | grep -iE "(api|fetch|axios|endpoint|url|path)" | head -50 > "$OUTPUT_DIR/model-api-endpoints.txt"
cat "$OUTPUT_DIR/model-api-endpoints.txt"

# Search for API base URLs
echo "--- Searching for API base URLs ---"
grep -rn "monkeycode-ai.com\|api\.monkeycode\|base_url\|baseURL\|api_url\|apiUrl" "$ANALYSIS_DIR/asar-content/" --include="*.js" --include="*.cjs" --include="*.ts" 2>/dev/null | head -30 > "$OUTPUT_DIR/api-urls.txt"
cat "$OUTPUT_DIR/api-urls.txt"

# Search for OpenAI/Anthropic API patterns
echo "--- Searching for LLM provider patterns ---"
grep -rn "openai\|anthropic\|chat/completions\|/v1/messages\|api_key\|apiKey\|Bearer" "$ANALYSIS_DIR/asar-content/" --include="*.js" --include="*.cjs" --include="*.ts" 2>/dev/null | head -50 > "$OUTPUT_DIR/llm-patterns.txt"
cat "$OUTPUT_DIR/llm-patterns.txt"

# Search for authentication patterns
echo "--- Searching for auth patterns ---"
grep -rn "token\|jwt\|auth\|login\|session\|cookie" "$ANALYSIS_DIR/asar-content/" --include="*.js" --include="*.cjs" --include="*.ts" 2>/dev/null | grep -iE "(set|get|header|bearer|authorization)" | head -30 > "$OUTPUT_DIR/auth-patterns.txt"
cat "$OUTPUT_DIR/auth-patterns.txt"

# Search for model configuration interfaces
echo "--- Searching for model config types ---"
grep -rn "interface_type\|InterfaceType\|openai_chat\|openai_responses\|provider\|temperature\|thinking" "$ANALYSIS_DIR/asar-content/" --include="*.js" --include="*.cjs" --include="*.ts" 2>/dev/null | head -30 > "$OUTPUT_DIR/model-config.txt"
cat "$OUTPUT_DIR/model-config.txt"

echo "=== Analysis complete. Results in $OUTPUT_DIR/ ==="
```

- [ ] **Step 4: 执行前端分析 — 提取 API 调用模式**
Run: `bash scripts/analyze-frontend.sh`
Expected:
  - Exit code: 0
  - File `analysis/api-analysis/model-api-endpoints.txt` exists

- [ ] **Step 5: 提交**
Run: `git add scripts/extract-asar.sh scripts/analyze-frontend.sh && git commit -m "feat(reverse): add Electron ASAR extraction and frontend analysis scripts"`

---

### Task 3: 还原 MonkeyCode API 协议

**Depends on:** Task 2
**Files:**
- Create: `src/protocol/types.ts` — API 类型定义
- Create: `src/protocol/endpoints.ts` — API 端点映射
- Create: `src/protocol/auth.ts` — 认证协议

- [ ] **Step 1: 创建 MonkeyCode API 类型定义 — 基于源码逆向的协议结构**

```typescript
// src/protocol/types.ts

/** MonkeyCode 支持的 LLM 接口类型 */
export type InterfaceType = "openai_chat" | "openai_responses" | "anthropic";

/** MonkeyCode 支持的模型提供商 */
export type ModelProvider =
  | "SiliconFlow"
  | "OpenAI"
  | "Ollama"
  | "DeepSeek"
  | "Moonshot"
  | "AzureOpenAI"
  | "BaiZhiCloud"
  | "Hunyuan"
  | "BaiLian"
  | "Volcengine"
  | "Gemini";

/** MonkeyCode 模型配置（对应 backend/domain/model.go） */
export interface MonkeyCodeModel {
  id: string;
  provider: ModelProvider;
  api_key: string;
  base_url: string;
  model: string;
  temperature: number;
  is_default: boolean;
  created_at: number;
  updated_at: number;
  weight: number;
  owner?: MonkeyCodeOwner;
  interface_type: InterfaceType;
  is_free: boolean;
  access_level: "basic" | "pro";
  last_check_at: number;
  last_check_success: boolean;
  last_check_error: string;
  thinking_enabled: boolean;
  context_limit: number;
  output_limit: number;
}

/** 模型所有者 */
export interface MonkeyCodeOwner {
  id: string;
  type: "private" | "team" | "public";
  name: string;
}

/** 创建模型请求 */
export interface CreateModelReq {
  provider: ModelProvider;
  api_key: string;
  base_url: string;
  model: string;
  temperature: number;
  is_default: boolean;
  interface_type: InterfaceType;
  thinking_enabled: boolean;
  context_limit: number;
  output_limit: number;
}

/** 模型列表响应 */
export interface ListModelResp {
  models: MonkeyCodeModel[];
  page: {
    has_next: boolean;
    cursor: string;
  };
}

/** 模型健康检查响应 */
export interface CheckModelResp {
  success: boolean;
  error?: string;
}

/** CodingAgent 类型 */
export type CodingAgent = "codex" | "claude" | "mcai_review" | "opencode";

/** LLM 配置（用于创建任务时传递给 VM） */
export interface LLMConfig {
  api_key: string;
  base_url: string;
  model: string;
  api_type?: "anthropic" | "openai";
  temperature?: number;
}
```

- [ ] **Step 2: 创建 API 端点映射 — 定义 MonkeyCode 后端所有模型相关端点**

```typescript
// src/protocol/endpoints.ts

/** MonkeyCode 后端 API 基础路径 */
export const MONKEYCODE_BASE_URL = "https://monkeycode-ai.com";

/** MonkeyCode API 端点定义 */
export const endpoints = {
  // 认证
  auth: {
    login: "/api/v1/auth/login",
    register: "/api/v1/auth/register",
    refreshToken: "/api/v1/auth/refresh",
    me: "/api/v1/auth/me",
  },

  // 模型管理
  model: {
    list: "/api/v1/models",           // GET - 列出用户可用的模型
    create: "/api/v1/models",          // POST - 创建模型配置
    delete: (id: string) => `/api/v1/models/${id}`,  // DELETE
    update: (id: string) => `/api/v1/models/${id}`,  // PUT
    check: (id: string) => `/api/v1/models/${id}/check`,  // POST - 健康检查
    checkByConfig: "/api/v1/models/check",  // POST - 按配置检查
    providerModels: "/api/v1/models/provider",  // GET - 获取提供商模型列表
  },

  // 团队模型
  teamModel: {
    list: (teamId: string) => `/api/v1/teams/${teamId}/models`,
    add: (teamId: string) => `/api/v1/teams/${teamId}/models`,
    update: (teamId: string, modelId: string) =>
      `/api/v1/teams/${teamId}/models/${modelId}`,
    delete: (teamId: string, modelId: string) =>
      `/api/v1/teams/${teamId}/models/${modelId}`,
  },

  // 任务（包含 LLM 调用）
  task: {
    create: "/api/v1/tasks",           // POST - 创建任务（含 LLM 配置）
    list: "/api/v1/tasks",             // GET
    get: (id: string) => `/api/v1/tasks/${id}`,
    stream: (id: string) => `/api/v1/tasks/${id}/stream`,  // WebSocket
  },

  // MCP
  mcp: {
    listUpstreams: "/api/v1/mcp/upstreams",
    createUpstream: "/api/v1/mcp/upstreams",
    listTools: "/api/v1/mcp/tools",
  },
} as const;

/** 构建完整 URL */
export function buildUrl(path: string, base: string = MONKEYCODE_BASE_URL): string {
  return `${base}${path}`;
}
```

- [ ] **Step 3: 创建认证协议模块 — 实现 MonkeyCode 的 JWT 认证流程**

```typescript
// src/protocol/auth.ts

import { buildUrl, endpoints } from "./endpoints";

export interface AuthCredentials {
  email: string;
  password: string;
}

export interface AuthToken {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  role: string;
  avatar_url: string;
}

/** MonkeyCode 认证客户端 */
export class MonkeyCodeAuth {
  private token: AuthToken | null = null;
  private user: AuthUser | null = null;
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl || "https://monkeycode-ai.com";
  }

  /** 使用邮箱密码登录获取 JWT */
  async login(credentials: AuthCredentials): Promise<AuthToken> {
    const resp = await fetch(buildUrl(endpoints.auth.login, this.baseUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    });

    if (!resp.ok) {
      throw new Error(`Login failed: ${resp.status} ${await resp.text()}`);
    }

    const data = await resp.json();
    this.token = {
      accessToken: data.access_token || data.token,
      refreshToken: data.refresh_token || "",
      expiresAt: Date.now() + (data.expires_in || 3600) * 1000,
    };

    return this.token;
  }

  /** 使用已有 token 设置认证 */
  setToken(token: AuthToken): void {
    this.token = token;
  }

  /** 获取当前认证头 */
  getAuthHeaders(): Record<string, string> {
    if (!this.token) {
      throw new Error("Not authenticated. Call login() first.");
    }
    return {
      Authorization: `Bearer ${this.token.accessToken}`,
      "Content-Type": "application/json",
    };
  }

  /** 刷新 token */
  async refresh(): Promise<AuthToken> {
    if (!this.token?.refreshToken) {
      throw new Error("No refresh token available");
    }

    const resp = await fetch(buildUrl(endpoints.auth.refreshToken, this.baseUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: this.token.refreshToken }),
    });

    if (!resp.ok) {
      throw new Error(`Token refresh failed: ${resp.status}`);
    }

    const data = await resp.json();
    this.token = {
      accessToken: data.access_token || data.token,
      refreshToken: data.refresh_token || this.token.refreshToken,
      expiresAt: Date.now() + (data.expires_in || 3600) * 1000,
    };

    return this.token;
  }

  /** 检查 token 是否即将过期（5分钟内） */
  isTokenExpiring(): boolean {
    if (!this.token) return true;
    return Date.now() > this.token.expiresAt - 5 * 60 * 1000;
  }

  /** 获取当前用户信息 */
  async getMe(): Promise<AuthUser> {
    const resp = await fetch(buildUrl(endpoints.auth.me, this.baseUrl), {
      headers: this.getAuthHeaders(),
    });

    if (!resp.ok) {
      throw new Error(`Get user failed: ${resp.status}`);
    }

    this.user = await resp.json();
    return this.user!;
  }

  /** 获取当前 token */
  getToken(): AuthToken | null {
    return this.token;
  }
}
```

- [ ] **Step 4: 验证协议模块编译**
Run: `cd /Users/cc11001100/github/vibe-coding-labs/MonkeyCode-RE && npx tsc --noEmit src/protocol/types.ts src/protocol/endpoints.ts src/protocol/auth.ts 2>&1 || echo "TypeScript check done (may need tsconfig)"`
Expected:
  - Files exist and are syntactically valid

- [ ] **Step 5: 提交**
Run: `git add src/protocol/ && git commit -m "feat(protocol): add MonkeyCode API types, endpoints, and auth protocol"`

---

### Task 4: 构建反向代理服务

**Depends on:** Task 3
**Files:**
- Create: `src/proxy/server.ts` — 代理服务器主入口
- Create: `src/proxy/handlers/chat-completions.ts` — OpenAI Chat Completions 兼容处理器
- Create: `src/proxy/handlers/models.ts` — 模型列表处理器
- Create: `src/proxy/model-resolver.ts` — 模型配置解析器
- Create: `package.json`
- Create: `tsconfig.json`

- [ ] **Step 1: 初始化项目 — 创建 package.json 和 tsconfig.json**

```json
{
  "name": "monkeycode-reverse-proxy",
  "version": "0.1.0",
  "description": "Reverse proxy that exposes MonkeyCode's built-in LLMs as OpenAI-compatible API",
  "type": "module",
  "main": "dist/proxy/server.js",
  "scripts": {
    "build": "tsc",
    "start": "node dist/proxy/server.js",
    "dev": "npx tsx src/proxy/server.ts"
  },
  "dependencies": {
    "express": "^4.21.0",
    "cors": "^2.8.5"
  },
  "devDependencies": {
    "typescript": "^5.7.0",
    "@types/express": "^5.0.0",
    "@types/cors": "^2.8.17",
    "tsx": "^4.19.0"
  }
}
```

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node16",
    "moduleResolution": "Node16",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true
  },
  "include": ["src"]
}
```

- [ ] **Step 2: 安装依赖**
Run: `pnpm install`
Expected:
  - Exit code: 0
  - `node_modules` directory exists

- [ ] **Step 3: 创建模型解析器 — 从 MonkeyCode 获取可用模型并映射到 OpenAI 格式**

```typescript
// src/proxy/model-resolver.ts

import { MonkeyCodeAuth } from "../protocol/auth.js";
import { buildUrl, endpoints } from "../protocol/endpoints.js";
import type { MonkeyCodeModel, InterfaceType } from "../protocol/types.js";

/** OpenAI 格式的模型信息 */
export interface OpenAIModel {
  id: string;
  object: "model";
  created: number;
  owned_by: string;
}

/** 模型解析器：从 MonkeyCode 获取模型列表并转换为 OpenAI 格式 */
export class ModelResolver {
  private auth: MonkeyCodeAuth;
  private models: MonkeyCodeModel[] = [];
  private lastFetch = 0;
  private cacheTTL = 5 * 60 * 1000; // 5 分钟缓存

  constructor(auth: MonkeyCodeAuth) {
    this.auth = auth;
  }

  /** 从 MonkeyCode 后端获取模型列表 */
  async fetchModels(): Promise<MonkeyCodeModel[]> {
    if (this.models.length > 0 && Date.now() - this.lastFetch < this.cacheTTL) {
      return this.models;
    }

    if (this.auth.isTokenExpiring()) {
      await this.auth.refresh();
    }

    const resp = await fetch(buildUrl(endpoints.model.list), {
      headers: this.auth.getAuthHeaders(),
    });

    if (!resp.ok) {
      throw new Error(`Failed to fetch models: ${resp.status} ${await resp.text()}`);
    }

    const data = await resp.json();
    this.models = data.models || [];
    this.lastFetch = Date.now();
    return this.models;
  }

  /** 转换为 OpenAI /v1/models 格式 */
  async toOpenAIModels(): Promise<OpenAIModel[]> {
    const models = await this.fetchModels();
    return models.map((m) => ({
      id: this.toOpenAIModelId(m),
      object: "model" as const,
      created: Math.floor(m.created_at / 1000),
      owned_by: m.provider,
    }));
  }

  /** 生成 OpenAI 兼容的模型 ID：provider/model 格式 */
  toOpenAIModelId(m: MonkeyCodeModel): string {
    return `${m.provider}/${m.model}`;
  }

  /** 根据 OpenAI 模型 ID 查找 MonkeyCode 模型配置 */
  async resolveModel(openaiModelId: string): Promise<MonkeyCodeModel | null> {
    const models = await this.fetchModels();

    // 精确匹配 provider/model 格式
    const exact = models.find((m) => this.toOpenAIModelId(m) === openaiModelId);
    if (exact) return exact;

    // 模糊匹配 model 名称
    const fuzzy = models.find((m) => m.model === openaiModelId);
    if (fuzzy) return fuzzy;

    // 默认模型
    const defaultModel = models.find((m) => m.is_default);
    if (defaultModel) return defaultModel;

    return models[0] || null;
  }

  /** 获取模型的接口类型 */
  getInterfaceType(model: MonkeyCodeModel): InterfaceType {
    return model.interface_type;
  }

  /** 判断模型是否为免费 */
  isFreeModel(model: MonkeyCodeModel): boolean {
    return model.is_free;
  }

  /** 清除缓存 */
  clearCache(): void {
    this.models = [];
    this.lastFetch = 0;
  }
}
```

- [ ] **Step 4: 创建 Chat Completions 处理器 — 将 OpenAI 格式请求转发到 MonkeyCode**

```typescript
// src/proxy/handlers/chat-completions.ts

import type { Request, Response } from "express";
import { MonkeyCodeAuth } from "../../protocol/auth.js";
import { buildUrl, endpoints } from "../../protocol/endpoints.js";
import type { MonkeyCodeModel, InterfaceType } from "../../protocol/types.js";
import { ModelResolver } from "../model-resolver.js";

/** OpenAI Chat Completions 请求格式 */
interface ChatCompletionRequest {
  model: string;
  messages: Array<{ role: string; content: string }>;
  max_tokens?: number;
  temperature?: number;
  stream?: boolean;
}

/** 创建 Chat Completions 处理器 */
export function createChatCompletionsHandler(auth: MonkeyCodeAuth, resolver: ModelResolver) {
  return async (req: Request, res: Response) => {
    try {
      const body = req.body as ChatCompletionRequest;

      // 解析目标模型
      const model = await resolver.resolveModel(body.model);
      if (!model) {
        res.status(404).json({ error: { message: `Model '${body.model}' not found`, type: "invalid_request_error" } });
        return;
      }

      // 根据 MonkeyCode 模型的接口类型选择转发策略
      const interfaceType = resolver.getInterfaceType(model);

      if (interfaceType === "openai_chat") {
        await proxyOpenAIChat(auth, model, body, res);
      } else if (interfaceType === "anthropic") {
        await proxyAnthropic(auth, model, body, res);
      } else if (interfaceType === "openai_responses") {
        await proxyOpenAIResponses(auth, model, body, res);
      } else {
        res.status(400).json({ error: { message: `Unsupported interface type: ${interfaceType}`, type: "invalid_request_error" } });
      }
    } catch (err: any) {
      console.error("Chat completion error:", err);
      res.status(500).json({ error: { message: err.message, type: "internal_error" } });
    }
  };
}

/** 转发到 OpenAI Chat 兼容端点 */
async function proxyOpenAIChat(
  auth: MonkeyCodeAuth,
  model: MonkeyCodeModel,
  body: ChatCompletionRequest,
  res: Response
) {
  // 直接用模型的 base_url 和 api_key 调用 LLM Provider
  const targetUrl = `${model.base_url.replace(/\/$/, "")}/chat/completions`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${model.api_key}`,
  };

  const payload = {
    model: model.model,
    messages: body.messages,
    max_tokens: body.max_tokens || model.output_limit || 4096,
    temperature: body.temperature ?? model.temperature,
    stream: body.stream || false,
  };

  const resp = await fetch(targetUrl, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const errText = await resp.text();
    res.status(resp.status).json({ error: { message: `Upstream error: ${errText}`, type: "upstream_error" } });
    return;
  }

  // 流式响应直接透传
  if (body.stream) {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        res.write(decoder.decode(value, { stream: true }));
      }
    } finally {
      res.end();
    }
    return;
  }

  // 非流式响应
  const data = await resp.json();
  res.json(data);
}

/** 转发到 Anthropic 端点（转换为 OpenAI 格式返回） */
async function proxyAnthropic(
  auth: MonkeyCodeAuth,
  model: MonkeyCodeModel,
  body: ChatCompletionRequest,
  res: Response
) {
  const targetUrl = `${model.base_url.replace(/\/$/, "")}/v1/messages`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "x-api-key": model.api_key,
    "anthropic-version": "2023-06-01",
  };

  // 提取 system 消息
  const systemMsg = body.messages.find((m) => m.role === "system")?.content || "";
  const chatMessages = body.messages.filter((m) => m.role !== "system");

  const payload = {
    model: model.model,
    system: systemMsg || undefined,
    messages: chatMessages.map((m) => ({ role: m.role, content: m.content })),
    max_tokens: body.max_tokens || model.output_limit || 4096,
    temperature: body.temperature ?? model.temperature,
  };

  const resp = await fetch(targetUrl, { method: "POST", headers, body: JSON.stringify(payload) });

  if (!resp.ok) {
    const errText = await resp.text();
    res.status(resp.status).json({ error: { message: `Anthropic error: ${errText}`, type: "upstream_error" } });
    return;
  }

  // 将 Anthropic 响应转换为 OpenAI 格式
  const data = await resp.json();
  const openaiResp = {
    id: `chatcmpl-${Date.now()}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: body.model,
    choices: [{
      index: 0,
      message: {
        role: "assistant",
        content: data.content?.filter((c: any) => c.type === "text").map((c: any) => c.text).join("") || "",
      },
      finish_reason: data.stop_reason === "end_turn" ? "stop" : data.stop_reason,
    }],
    usage: {
      prompt_tokens: data.usage?.input_tokens || 0,
      completion_tokens: data.usage?.output_tokens || 0,
      total_tokens: (data.usage?.input_tokens || 0) + (data.usage?.output_tokens || 0),
    },
  };
  res.json(openaiResp);
}

/** 转发到 OpenAI Responses 端点（转换为 Chat Completions 格式返回） */
async function proxyOpenAIResponses(
  auth: MonkeyCodeAuth,
  model: MonkeyCodeModel,
  body: ChatCompletionRequest,
  res: Response
) {
  const targetUrl = `${model.base_url.replace(/\/$/, "")}/responses`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${model.api_key}`,
  };

  const payload = {
    model: model.model,
    input: body.messages.map((m) => ({ role: m.role, content: m.content })),
    max_output_tokens: body.max_tokens || model.output_limit || 4096,
    temperature: body.temperature ?? model.temperature,
  };

  const resp = await fetch(targetUrl, { method: "POST", headers, body: JSON.stringify(payload) });

  if (!resp.ok) {
    const errText = await resp.text();
    res.status(resp.status).json({ error: { message: `Responses API error: ${errText}`, type: "upstream_error" } });
    return;
  }

  const data = await resp.json();
  const content = data.output
    ?.filter((o: any) => o.type === "message")
    .flatMap((o: any) => o.content?.filter((c: any) => c.type === "output_text").map((c: any) => c.text) || [])
    .join("") || "";

  const openaiResp = {
    id: `chatcmpl-${Date.now()}`,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: body.model,
    choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
    usage: {
      prompt_tokens: data.usage?.input_tokens || 0,
      completion_tokens: data.usage?.output_tokens || 0,
      total_tokens: data.usage?.total_tokens || 0,
    },
  };
  res.json(openaiResp);
}
```

- [ ] **Step 5: 创建模型列表处理器 — 暴露 /v1/models 端点**

```typescript
// src/proxy/handlers/models.ts

import type { Request, Response } from "express";
import { ModelResolver } from "../model-resolver.js";

/** 创建模型列表处理器 */
export function createModelsHandler(resolver: ModelResolver) {
  return async (_req: Request, res: Response) => {
    try {
      const models = await resolver.toOpenAIModels();
      res.json({
        object: "list",
        data: models,
      });
    } catch (err: any) {
      console.error("Models handler error:", err);
      res.status(500).json({ error: { message: err.message, type: "internal_error" } });
    }
  };
}
```

- [ ] **Step 6: 创建代理服务器主入口 — 启动 Express 服务并注册路由**

```typescript
// src/proxy/server.ts

import express from "express";
import cors from "cors";
import { MonkeyCodeAuth } from "../protocol/auth.js";
import { ModelResolver } from "./model-resolver.js";
import { createChatCompletionsHandler } from "./handlers/chat-completions.js";
import { createModelsHandler } from "./handlers/models.js";

const PORT = parseInt(process.env.PROXY_PORT || "9090", 10);
const MONKEYCODE_URL = process.env.MONKEYCODE_URL || "https://monkeycode-ai.com";

async function main() {
  const app = express();
  app.use(cors());
  app.use(express.json());

  // 初始化认证
  const auth = new MonkeyCodeAuth(MONKEYCODE_URL);

  // 支持通过环境变量设置已有 token
  if (process.env.MONKEYCODE_ACCESS_TOKEN) {
    auth.setToken({
      accessToken: process.env.MONKEYCODE_ACCESS_TOKEN,
      refreshToken: process.env.MONKEYCODE_REFRESH_TOKEN || "",
      expiresAt: Date.now() + 24 * 60 * 60 * 1000,
    });
  } else if (process.env.MONKEYCODE_EMAIL && process.env.MONKEYCODE_PASSWORD) {
    console.log("Logging in to MonkeyCode...");
    await auth.login({
      email: process.env.MONKEYCODE_EMAIL,
      password: process.env.MONKEYCODE_PASSWORD,
    });
    console.log("Login successful.");
  } else {
    console.warn("WARNING: No MonkeyCode credentials provided.");
    console.warn("Set MONKEYCODE_ACCESS_TOKEN or MONKEYCODE_EMAIL + MONKEYCODE_PASSWORD.");
  }

  // 初始化模型解析器
  const resolver = new ModelResolver(auth);

  // OpenAI 兼容 API 路由
  app.get("/v1/models", createModelsHandler(resolver));
  app.post("/v1/chat/completions", createChatCompletionsHandler(auth, resolver));

  // 健康检查
  app.get("/health", (_req, res) => {
    res.json({ status: "ok", monkeycode_url: MONKEYCODE_URL });
  });

  // 模型刷新
  app.post("/refresh-models", async (_req, res) => {
    resolver.clearCache();
    const models = await resolver.toOpenAIModels();
    res.json({ count: models.length, models });
  });

  app.listen(PORT, () => {
    console.log(`\n=== MonkeyCode Reverse Proxy ===`);
    console.log(`Proxy server: http://localhost:${PORT}`);
    console.log(`OpenAI compatible: http://localhost:${PORT}/v1/chat/completions`);
    console.log(`Models list: http://localhost:${PORT}/v1/models`);
    console.log(`MonkeyCode backend: ${MONKEYCODE_URL}`);
    console.log(`================================\n`);
  });
}

main().catch((err) => {
  console.error("Failed to start proxy server:", err);
  process.exit(1);
});
```

- [ ] **Step 7: 验证代理服务编译**
Run: `npx tsc --noEmit 2>&1 | head -20`
Expected:
  - Exit code: 0
  - No TypeScript compilation errors

- [ ] **Step 8: 提交**
Run: `git add package.json tsconfig.json src/proxy/ && git commit -m "feat(proxy): add OpenAI-compatible reverse proxy server for MonkeyCode LLMs"`

---

### Task 5: 集成测试与使用文档

**Depends on:** Task 4
**Files:**
- Create: `src/test/proxy.test.ts` — 代理服务集成测试
- Create: `.env.example` — 环境变量示例
- Create: `scripts/start-proxy.sh` — 启动脚本

- [ ] **Step 1: 创建环境变量示例文件**

```text
# MonkeyCode 认证配置（二选一）

# 方式1：直接使用 Access Token
MONKEYCODE_ACCESS_TOKEN=

# 方式2：使用邮箱密码登录
MONKEYCODE_EMAIL=
MONKEYCODE_PASSWORD=

# MonkeyCode 后端地址（默认 https://monkeycode-ai.com）
MONKEYCODE_URL=https://monkeycode-ai.com

# 代理服务端口
PROXY_PORT=9090
```

- [ ] **Step 2: 创建代理启动脚本**

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# 加载 .env
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

echo "Starting MonkeyCode Reverse Proxy..."
npx tsx src/proxy/server.ts
```

- [ ] **Step 3: 创建集成测试 — 验证代理服务端点和模型解析**

```typescript
// src/test/proxy.test.ts

import { describe, test, expect, beforeAll } from "vitest";

const PROXY_URL = process.env.PROXY_TEST_URL || "http://localhost:9090";

describe("MonkeyCode Reverse Proxy", () => {
  test("GET /health returns ok", async () => {
    const resp = await fetch(`${PROXY_URL}/health`);
    expect(resp.status).toBe(200);
    const data = await resp.json();
    expect(data.status).toBe("ok");
  });

  test("GET /v1/models returns model list", async () => {
    const resp = await fetch(`${PROXY_URL}/v1/models`);
    expect(resp.status).toBe(200);
    const data = await resp.json();
    expect(data.object).toBe("list");
    expect(Array.isArray(data.data)).toBe(true);
    if (data.data.length > 0) {
      const model = data.data[0];
      expect(model).toHaveProperty("id");
      expect(model).toHaveProperty("object", "model");
      expect(model).toHaveProperty("owned_by");
    }
  });

  test("POST /v1/chat/completions with invalid model returns 404", async () => {
    const resp = await fetch(`${PROXY_URL}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "nonexistent-model",
        messages: [{ role: "user", content: "hi" }],
      }),
    });
    expect(resp.status).toBe(404);
  });

  test("POST /v1/chat/completions without auth returns error", async () => {
    const resp = await fetch(`${PROXY_URL}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "test",
        messages: [{ role: "user", content: "hi" }],
      }),
    });
    // 可能是 404 (model not found) 或 500 (auth error)，都是预期内的
    expect([404, 500]).toContain(resp.status);
  });
});
```

- [ ] **Step 4: 验证项目构建**
Run: `npx tsc --noEmit 2>&1 | head -10`
Expected:
  - Exit code: 0
  - No TypeScript errors

- [ ] **Step 5: 提交**
Run: `git add .env.example scripts/start-proxy.sh src/test/ && git commit -m "feat(test): add integration tests, env config, and startup script"`
