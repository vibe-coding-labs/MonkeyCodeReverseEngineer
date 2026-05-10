// MonkeyCode Reverse Proxy — 主入口
// 将 MonkeyCode 内置 LLM 暴露为 OpenAI 兼容 API

import express from "express"
import cors from "cors"
import { AuthManager } from "./auth.js"
import { ModelManager } from "./models.js"
import { TaskRunner } from "./task-runner.js"
import { createAPIRouter } from "./api-routes.js"

const PORT = parseInt(process.env.PROXY_PORT || "9090", 10)

async function main() {
  console.log("=== MonkeyCode Reverse Proxy ===")
  console.log(`Target: ${process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"}`)
  console.log(`Port: ${PORT}`)
  console.log()

  // 初始化模块
  const auth = new AuthManager()
  const modelManager = new ModelManager(auth)
  const taskRunner = new TaskRunner(auth)

  // 尝试登录
  try {
    await auth.getSessionCookie()
    console.log("[Init] Authentication successful")
  } catch (err: any) {
    console.warn(`[Init] Authentication failed: ${err.message}`)
    console.warn("[Init] Proxy will start but API calls will fail until authenticated")
    console.warn("[Init] Set MONKEYCODE_USERNAME and MONKEYCODE_PASSWORD env vars")
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
    res.json({ status: "ok", uptime: process.uptime() })
  })

  // OpenAI 兼容 API
  app.use(createAPIRouter(modelManager, taskRunner))

  // 手动设置 Session Cookie 的端点
  app.post("/admin/session", express.text(), (req, res) => {
    const cookie = req.body
    if (!cookie) {
      res.status(400).json({ error: "Cookie value required" })
      return
    }
    auth.setSessionCookie(cookie)
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
    console.log()
    console.log("Usage with OpenAI SDK:")
    console.log(`  OPENAI_API_KEY=any OPENAI_BASE_URL=http://localhost:${PORT}/v1`)
  })
}

main().catch((err) => {
  console.error("Fatal error:", err)
  process.exit(1)
})
