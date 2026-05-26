// MonkeyCode Reverse Proxy — 主入口
// 将 MonkeyCode 内置 LLM 暴露为 OpenAI 兼容 API
// 支持单账号模式和号池模式

import express from "express"
import cors from "cors"
import path from "path"
import { AuthManager } from "./auth.js"
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import { AccountPool, AccountConfig, loadAccountFromEnv, loadAccountConfigs } from "./account-pool.js"
import { createAPIRouter } from "./api-routes.js"

const PORT = parseInt(process.env.PROXY_PORT || "9090", 10)

async function main() {
  console.log("=== MonkeyCode Reverse Proxy ===")
  console.log(`Target: ${process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"}`)
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

  // 健康检查
  app.get("/health", (_req, res) => {
    const poolStats = accountPool?.getStats()
    res.json({
      status: "ok",
      uptime: process.uptime(),
      pool: poolStats || { mode: "single" },
    })
  })

  // OpenAI 兼容 API（传入号池）
  app.use(createAPIRouter(modelManager, taskRunner, accountPool))

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

  // 启动服务器
  app.listen(PORT, () => {
    console.log()
    console.log(`MonkeyCode Reverse Proxy running on http://localhost:${PORT}`)
    console.log()
    console.log("Endpoints:")
    console.log(`  GET  /v1/models            - List available models`)
    console.log(`  POST /v1/chat/completions  - Chat completion (streaming supported)`)
    console.log(`  GET  /health               - Health check`)
    console.log(`  POST /admin/session        - Set session cookie manually`)
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