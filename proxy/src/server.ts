// MonkeyCode Reverse Proxy — 主入口
// 将 MonkeyCode 内置 LLM 暴露为 OpenAI 兼容 API
// 支持单账号模式和号池模式
// 支持多轮对话：通过 conversation_id 复用任务/VM

import express from "express"
import cors from "cors"
import path from "path"
import { fileURLToPath } from "url"
import { AuthManager } from "./auth.js"
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import { AccountPool, AccountConfig, loadAccountFromEnv, loadAccountConfigs } from "./account-pool.js"
import { ConversationManager } from "./conversation-manager.js"
import { createAPIRouter } from "./api-routes.js"
import {
  initiateLogin,
  completeLogin,
  verifySession,
  discoverImageId,
  discoverModels,
  loginWithCallbackUrl,
} from "./admin-login.js"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"

const PORT = parseInt(process.env.PROXY_PORT || "9090", 10)

async function main() {
  console.log("=== MonkeyCode Reverse Proxy ===")
  console.log(`Target: ${MONKEYCODE_BASE_URL}`)
  console.log(`Port: ${PORT}`)
  console.log()

  // ========== 初始化号池或单账号 ==========
  let accountPool: AccountPool | undefined
  let singleAuth: AuthManager | undefined

  // 尝试从 ACCOUNT_POOL_FILE 加载号池配置
  const poolFile = process.env.ACCOUNT_POOL_FILE || ""
  let accounts: import("./account-pool.js").AccountConfig[] = []

  if (poolFile) {
    try {
      const resolved = path.resolve(poolFile)
      accounts = await loadAccountConfigs(resolved)
      console.log(`[Init] Loaded ${accounts.length} accounts from ${resolved}`)
    } catch (err: any) {
      console.warn(`[Init] Failed to load account pool file '${poolFile}': ${err.message}`)
    }
  }

  // 从环境变量加载单个账号（作为号池补充或独立使用）
  const envAccount = loadAccountFromEnv()
  if (envAccount) {
    accounts.push(envAccount)
    console.log(`[Init] Added account from env: ${envAccount.email}`)
  }

  if (accounts.length > 0) {
    accountPool = new AccountPool(accounts)
    await accountPool.initAll()
    accountPool.startHealthCheck()
    // 号池模式下 ModelManager 使用第一个账号作为 ModelManager 的认证
    singleAuth = accountPool.acquireHttp() ?? undefined
  } else {
    // 纯单账号模式（向后兼容）
    singleAuth = new AuthManager()
  }

  // 初始化模块
  const modelManager = new ModelManager(singleAuth ?? new AuthManager())
  const taskRunner = new TaskRunner(singleAuth ?? new AuthManager())

  // 非号池模式：尝试登录
  if (!accountPool && singleAuth) {
    try {
      await singleAuth.getSessionCookie()
      console.log("[Init] Authentication successful")
    } catch (err: any) {
      console.warn(`[Init] Authentication failed: ${err.message}`)
      console.warn("[Init] Proxy will start but API calls will fail until authenticated")
      console.warn("[Init] Set MONKEYCODE_EMAIL and MONKEYCODE_PASSWORD env vars")
    }
  }

  // 尝试获取模型列表
  try {
    const models = await modelManager.fetchModels()
    console.log(`[Init] Available models: ${models.length}`)
    for (const m of models.slice(0, 5)) {
      console.log(`  - ${m.provider}/${m.model} (${m.interface_type}, ${m.owner})`)
    }
    if (models.length > 5) {
      console.log(`  ... and ${models.length - 5} more`)
    }
  } catch (err: any) {
    console.warn(`[Init] Failed to fetch models: ${err.message}`)
  }

  // 创建 Express 应用
  const app = express()

  app.use(cors())
  app.use(express.json({ limit: "10mb" }))

  // 静态文件 — 中转站前端页面
  const __dirname = path.dirname(fileURLToPath(import.meta.url))
  app.use(express.static(path.join(__dirname, "../public")))

  // 健康检查
  app.get("/health", (_req, res) => {
    const poolStats = accountPool?.getStats()
    res.json({
      status: "ok",
      uptime: process.uptime(),
      pool: poolStats || { mode: "single" },
    })
  })

  // 初始化对话管理器
  const conversationManager = new ConversationManager({
    conversationTimeoutMs: 30 * 60 * 1000, // 30 分钟超时
    cleanupIntervalMs: 5 * 60 * 1000, // 5 分钟清理一次
  })
  console.log("[Init] ConversationManager initialized")

  // OpenAI 兼容 API（传入号池和对话管理器）
  app.use(createAPIRouter(modelManager, taskRunner, accountPool, conversationManager))

  // 手动设置 Session Cookie 的端点
  app.post("/admin/session", express.text(), (req, res) => {
    const cookie = req.body
    if (!cookie) {
      res.status(400).json({ error: "Cookie value required" })
      return
    }
    singleAuth?.setSessionCookie(cookie)
    res.json({ status: "ok", message: "Session cookie set" })
  })

  // 刷新模型缓存
  app.post("/admin/refresh-models", async (_req, res) => {
    try {
      modelManager.clearCache()
      const models = await modelManager.fetchModels()
      res.json({ status: "ok", count: models.length })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // 钱包/余额查询
  app.get("/admin/wallet", async (_req, res) => {
    try {
      const auth = singleAuth
      if (!auth) {
        res.status(400).json({ error: "No auth configured" })
        return
      }
      const cookie = auth.getSessionCookieSync()
      if (!cookie) {
        res.status(400).json({ error: "No session cookie" })
        return
      }
      const response = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/wallet`, {
        headers: {
          Cookie: `${auth.getSessionCookieName()}=${cookie}`,
          "User-Agent": "Mozilla/5.0",
          "Content-Type": "application/json",
        },
      })
      const data = await response.json()
      res.json(data)
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // Session 状态（前端用）
  app.get("/admin/session-status", async (_req, res) => {
    try {
      const auth = singleAuth
      if (!auth) {
        res.json({ code: 0, data: { user: { name: "未配置", role: "-", status: "inactive" } } })
        return
      }
      const cookie = auth.getSessionCookieSync()
      if (!cookie) {
        res.json({ code: 0, data: { user: { name: "未登录", role: "-", status: "inactive" } } })
        return
      }
      const response = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/status`, {
        headers: { Cookie: `${auth.getSessionCookieName()}=${cookie}`, "User-Agent": "Mozilla/5.0" },
      })
      const data = await response.json()
      res.json(data)
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // 订阅信息（前端用，可能返回 404）
  app.get("/admin/subscription", async (_req, res) => {
    try {
      const auth = singleAuth
      if (!auth) { res.json({ plan: "未配置" }); return }
      const cookie = auth.getSessionCookieSync()
      if (!cookie) { res.json({ plan: "未登录" }); return }
      const response = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/subscriptions/current`, {
        headers: { Cookie: `${auth.getSessionCookieName()}=${cookie}`, "User-Agent": "Mozilla/5.0" },
      })
      if (!response.ok) { res.json({ plan: "未订阅" }); return }
      const data = await response.json()
      res.json(data.data || { plan: "未订阅" })
    } catch { res.json({ plan: "未订阅" }) }
  })

  // 号池管理端点
  app.get("/admin/pool/status", (_req, res) => {
    if (!accountPool) {
      res.json({ mode: "single" })
      return
    }
    const stats = accountPool.getStats()
    res.json({ mode: "pool", ...stats })
  })

  app.post("/admin/pool/refresh", async (_req, res) => {
    if (!accountPool) {
      res.status(400).json({ error: "No account pool configured" })
      return
    }
    try {
      accountPool.stopHealthCheck()
      await accountPool.initAll()
      accountPool.startHealthCheck()
      res.json({ status: "ok", ...accountPool.getStats() })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // ========== OAuth 登录端点 ==========

  // Step 1: 发送短信验证码（百智云 OAuth 流程）
  app.post("/admin/login/send-code", async (req, res) => {
    try {
      const { phone } = req.body
      if (!phone) {
        res.status(400).json({ error: "phone is required" })
        return
      }
      const result = await initiateLogin(phone)
      res.json(result)
    } catch (err: any) {
      console.error("[Login] Send code error:", err.message)
      res.status(500).json({ error: err.message })
    }
  })

  // Step 2: 验证短信码 + 完成 OAuth 登录 → 获取 session cookie + 自动发现 image_id
  app.post("/admin/login/verify", async (req, res) => {
    try {
      const { code } = req.body
      if (!code) {
        res.status(400).json({ error: "SMS code is required" })
        return
      }
      const result = await completeLogin(code)

      // 自动注入到当前 AuthManager
      if (singleAuth) {
        singleAuth.setSessionCookie(result.sessionCookie)
      }

      // 如果发现了 image_id，自动设置到环境变量
      if (result.imageId) {
        process.env.MONKEYCODE_IMAGE_ID = result.imageId
        console.log(`[Login] Auto-discovered image_id: ${result.imageId} (${result.imageName})`)
      }

      // 尝试刷新模型缓存
      try {
        modelManager.clearCache()
        await modelManager.fetchModels()
      } catch {
        // ignore
      }

      res.json({
        status: "ok",
        message: "Login successful",
        sessionCookie: result.sessionCookie,
        imageId: result.imageId,
        imageName: result.imageName,
        modelCount: result.models?.length || 0,
        user: result.user ? {
          id: result.user.id,
          name: result.user.name,
          email: result.user.email,
          role: result.user.role,
        } : undefined,
      })
    } catch (err: any) {
      console.error("[Login] Verify error:", err.message)
      res.status(500).json({ error: err.message })
    }
  })

  // 手动模式: 直接用 OAuth 回调 URL 登录
  app.post("/admin/login/callback", async (req, res) => {
    try {
      const { callbackUrl } = req.body
      if (!callbackUrl) {
        res.status(400).json({ error: "callbackUrl is required" })
        return
      }
      const result = await loginWithCallbackUrl(callbackUrl)

      if (singleAuth) {
        singleAuth.setSessionCookie(result.sessionCookie)
      }

      if (result.imageId) {
        process.env.MONKEYCODE_IMAGE_ID = result.imageId
      }

      res.json({
        status: "ok",
        sessionCookie: result.sessionCookie,
        imageId: result.imageId,
        imageName: result.imageName,
      })
    } catch (err: any) {
      console.error("[Login] Callback error:", err.message)
      res.status(500).json({ error: err.message })
    }
  })

  // 自动发现 image_id（用已有 session）
  app.get("/admin/discover", async (_req, res) => {
    try {
      const cookie = singleAuth?.getSessionCookieSync()
      if (!cookie) {
        res.status(400).json({ error: "No session cookie. Login first." })
        return
      }

      const [imageResult, models] = await Promise.all([
        discoverImageId(cookie),
        discoverModels(cookie),
      ])

      if (imageResult) {
        process.env.MONKEYCODE_IMAGE_ID = imageResult.imageId
      }

      res.json({
        imageId: imageResult?.imageId || null,
        imageName: imageResult?.imageName || null,
        models: models.map((m: any) => ({
          id: m.id,
          model: m.model,
          provider: m.provider,
          display_name: m.display_name,
          is_free: m.is_free,
        })),
      })
    } catch (err: any) {
      res.status(500).json({ error: err.message })
    }
  })

  // 启动服务器
  app.listen(PORT, () => {
    console.log()
    console.log(`MonkeyCode Reverse Proxy running on http://localhost:${PORT}`)
    console.log()
    console.log("Endpoints:")
    console.log(`  GET  /v1/models            - List available models`)
    console.log(`  POST /v1/chat/completions  - Chat completion (streaming supported)`)
    console.log(`  POST /v1/responses         - Responses API (Codex native, streaming)`)
    console.log(`  GET  /health               - Health check`)
    console.log(`  GET  /admin/wallet           - Query wallet balance`)
    console.log(`  POST /admin/session        - Set session cookie manually`)
    console.log(`  POST /admin/login/send-code  - Send SMS code (百智云 OAuth)`)
    console.log(`  POST /admin/login/verify     - Verify SMS code + login`)
    console.log(`  POST /admin/login/callback   - Login with OAuth callback URL`)
    console.log(`  GET  /admin/discover         - Auto-discover image_id & models`)
    console.log(`  POST /admin/refresh-models - Refresh model cache`)
    const poolStats = accountPool?.getStats()
    if (poolStats) {
      console.log(`  GET  /admin/pool/status    - Account pool status`)
      console.log(`  POST /admin/pool/refresh   - Re-login all pool accounts`)
    }
    console.log()
    console.log("Usage with OpenAI SDK:")
    console.log(`  OPENAI_API_KEY=any OPENAI_BASE_URL=http://localhost:${PORT}/v1`)
  })
}

main().catch((err) => {
  console.error("Fatal error:", err)
  process.exit(1)
})