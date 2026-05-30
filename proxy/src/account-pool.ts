// MonkeyCode 号池模块 — 多账号管理与轮转
//
// 核心设计:
// - 账号状态: CREATED → ACTIVE → EXPIRED → REFRESH → ACTIVE / INVALID
// - HTTP 请求: 共享模式，取最久未用的 ACTIVE 账号
// - WebSocket: 独占模式，锁定一个账号直到流结束
// - 会话保活: 每小时检查 `/api/v1/users/status`，过期前 2 天主动重登录
// - 错误处理: 40100 换账号重试，40002/40003 标记 INVALID，50000 指数退避
//
// 监控告警阈值:
//   P0: 可用账号 < 50%
//   P1: 过期率 > 5/h | 账号异常 > 0
//   P2: 错误率 > 20%

import { AuthManager, LoginMode } from "./auth.js"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"

// 会话固定 30 天过期（API 不刷新 TTL）
const SESSION_MAX_AGE_MS = 29 * 24 * 60 * 60 * 1000 // 29 天提前重登录
const HEALTH_CHECK_INTERVAL_MS = 60 * 60 * 1000 // 1 小时
const HTTP_RETRY_MAX = 3
const WS_LOCK_MAX_MS = parseInt(process.env.MONKEYCODE_TASK_TIMEOUT_MS || "3600000", 10) + 60_000 // task timeout + 1min buffer

export type AccountStatus = "CREATED" | "ACTIVE" | "EXPIRED" | "INVALID"

export interface AccountConfig {
  email: string
  password: string     // 明文密码
  mode?: LoginMode     // "user" | "team"
  cookie?: string      // 预提取的 session cookie（推荐，绕过验证码）
  cookieName?: string  // 可覆盖 cookie 名
}

interface AccountEntry {
  email: string
  password: string
  mode: LoginMode
  status: AccountStatus
  auth: AuthManager
  cookieSetAt: number | null
  cookieTTLReached: boolean
  lastUsedAt: number
  errorCount: number
  lockedByWs: boolean
  lockedAt: number | null
}

export class AccountPool {
  private accounts: AccountEntry[] = []
  private roundRobinIndex = 0
  private healthTimer: ReturnType<typeof setInterval> | null = null

  constructor(configs: AccountConfig[]) {
    if (configs.length === 0) {
      console.warn("[AccountPool] No accounts configured, pool is empty")
    }

    for (const cfg of configs) {
      const auth = new AuthManager()
      auth.setCredentials(cfg.email, cfg.password, cfg.mode || "user")
      if (cfg.cookie) {
        auth.setSessionCookie(cfg.cookie, cfg.mode || "user")
      }
      this.accounts.push({
        email: cfg.email,
        password: cfg.password,
        mode: cfg.mode || "user",
        status: cfg.cookie ? "ACTIVE" : "CREATED",
        auth,
        cookieSetAt: cfg.cookie ? Date.now() : null,
        cookieTTLReached: false,
        lastUsedAt: 0,
        errorCount: 0,
        lockedByWs: false,
        lockedAt: null,
      })
    }

    this.logStatus()
  }

  // ========== 账号获取 ==========

  /** HTTP 共享模式：取最久未用的 ACTIVE 账号，Round-Robin 分散负载 */
  acquireHttp(): AuthManager | null {
    const candidates = this.accounts
      .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
      .sort((a, b) => a.lastUsedAt - b.lastUsedAt)

    if (candidates.length === 0) return null

    const idx = this.roundRobinIndex % candidates.length
    this.roundRobinIndex++
    const chosen = candidates[idx]
    chosen.lastUsedAt = Date.now()
    return chosen.auth
  }

  /** WebSocket 独占模式：锁定一个账号直到释放 */
  acquireWs(): AuthManager | null {
    const candidates = this.accounts
      .filter((a) => a.status === "ACTIVE" && !a.lockedByWs)
      .sort((a, b) => a.lastUsedAt - b.lastUsedAt)

    if (candidates.length === 0) return null

    const chosen = candidates[0]
    chosen.lockedByWs = true
    chosen.lockedAt = Date.now()
    chosen.lastUsedAt = Date.now()
    return chosen.auth
  }

  /** 释放 WS 独占锁 */
  releaseWs(auth: AuthManager): void {
    const entry = this.findByAuth(auth)
    if (entry) {
      entry.lockedByWs = false
      entry.lockedAt = null
    }
  }

  // ========== 生命周期管理 ==========

  /** 初始化所有 CREATED 账号的登录 */
  async initAll(): Promise<void> {
    const created = this.accounts.filter((a) => a.status === "CREATED")
    if (created.length === 0) {
      console.log("[AccountPool] All accounts already ACTIVE")
      return
    }
    console.log(`[AccountPool] Initializing ${created.length} accounts...`)
    const results = await Promise.allSettled(created.map((a) => this.loginAccount(a)))
    const ok = results.filter((r) => r.status === "fulfilled").length
    console.log(`[AccountPool] Init complete: ${ok}/${created.length} succeeded`)
    this.logStatus()
  }

  /** 启动定时健康检查 */
  startHealthCheck(): void {
    if (this.healthTimer) return
    this.healthTimer = setInterval(() => this.healthCheck(), HEALTH_CHECK_INTERVAL_MS)
    console.log(`[AccountPool] Health check started (interval: ${HEALTH_CHECK_INTERVAL_MS / 60000}min)`)
  }

  /** 停止健康检查 */
  stopHealthCheck(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer)
      this.healthTimer = null
    }
  }

  /** 单次健康检查：检测过期、清理僵尸 WS 锁、标记异常 */
  private async healthCheck(): Promise<void> {
    console.log("[AccountPool] Running health check...")
    for (const entry of this.accounts) {
      if (entry.status !== "ACTIVE") continue

      // 清理僵尸 WS 锁（超时未释放的锁）
      if (entry.lockedByWs && entry.lockedAt && Date.now() - entry.lockedAt > WS_LOCK_MAX_MS) {
        console.warn(`[AccountPool] ${entry.email}: WS lock expired after ${Math.round((Date.now() - entry.lockedAt) / 1000)}s, force releasing`)
        entry.lockedByWs = false
        entry.lockedAt = null
      }

      // 检查 Cookie 年龄（30天硬限制）
      if (entry.cookieSetAt && Date.now() - entry.cookieSetAt > SESSION_MAX_AGE_MS) {
        console.log(`[AccountPool] ${entry.email}: session expired, re-logging...`)
        entry.cookieTTLReached = true
        await this.loginAccount(entry)
        continue
      }

      // 调用 /users/status 检查有效
      try {
        const ok = await entry.auth.checkStatus()
        if (!ok) {
          console.warn(`[AccountPool] ${entry.email}: status check failed, re-logging...`)
          await this.loginAccount(entry)
        }
      } catch {
        console.warn(`[AccountPool] ${entry.email}: status check error, marking EXPIRED`)
        entry.status = "EXPIRED"
      }
    }
    this.logStatus()
    this.checkAlerts()
  }

  /** 登录一个账号 */
  private async loginAccount(entry: AccountEntry): Promise<void> {
    try {
      await entry.auth.login()
      entry.status = "ACTIVE"
      entry.cookieSetAt = Date.now()
      entry.cookieTTLReached = false
      entry.errorCount = 0
      console.log(`[AccountPool] ${entry.email}: login successful`)
    } catch (err: any) {
      entry.errorCount++
      console.error(`[AccountPool] ${entry.email}: login failed (attempt ${entry.errorCount}): ${err.message}`)
      if (entry.errorCount >= 3) {
        entry.status = "INVALID"
        console.error(`[AccountPool] ${entry.email}: marked INVALID after ${entry.errorCount} failed attempts`)
      }
    }
  }

  // ========== 错误处理 ==========

  /** 处理 API 错误码, 返回 true 表示可重试 */
  handleError(auth: AuthManager, errorCode: number): boolean {
    const entry = this.findByAuth(auth)
    if (!entry) return false

    switch (errorCode) {
      case 40100: // 会话无效
        entry.status = "EXPIRED"
        // 尝试重新登录
        this.loginAccount(entry).catch(() => {})
        return true // 调用方可切换账号重试

      case 40300: // 权限不足
        console.warn(`[AccountPool] ${entry.email}: permission denied, degrading`)
        return false

      case 40002: // 密码错误
      case 40003: // 账号被封
      case 40004: // 账号未激活
        entry.status = "INVALID"
        console.error(`[AccountPool] ${entry.email}: marked INVALID (code ${errorCode})`)
        return false

      case 50000: // 服务端错误
        return true // 可重试

      default:
        return false
    }
  }

  // ========== 统计与状态 ==========

  /** 获取统计信息 */
  getStats(): { total: number; active: number; expired: number; invalid: number; locked: number } {
    const total = this.accounts.length
    const active = this.accounts.filter((a) => a.status === "ACTIVE").length
    const expired = this.accounts.filter((a) => a.status === "EXPIRED").length
    const invalid = this.accounts.filter((a) => a.status === "INVALID").length
    const locked = this.accounts.filter((a) => a.lockedByWs).length
    return { total, active, expired, invalid, locked }
  }

  /** 告警检查 */
  private checkAlerts(): void {
    const { total, active } = this.getStats()
    const activeRatio = total > 0 ? active / total : 0

    if (activeRatio < 0.5) {
      console.error(`[AccountPool] P0 ALERT: available accounts < 50% (${active}/${total})`)
    } else if (activeRatio < 0.7) {
      console.warn(`[AccountPool] P1 WARN: available accounts < 70% (${active}/${total})`)
    }
  }

  /** 打印状态 */
  logStatus(): void {
    const stats = this.getStats()
    console.log(`[AccountPool] Status: ${stats.active}/${stats.total} active, ${stats.expired} expired, ${stats.invalid} invalid, ${stats.locked} ws-locked`)
  }

  private findByAuth(auth: AuthManager): AccountEntry | undefined {
    return this.accounts.find((a) => a.auth === auth)
  }
}

// ========== 配置加载 ==========

/** 从 JSON 文件路径加载账号配置 */
export async function loadAccountConfigs(filePath: string): Promise<AccountConfig[]> {
  const fs = await import("fs")
  const content = fs.readFileSync(filePath, "utf-8")
  return JSON.parse(content) as AccountConfig[]
}

/** 从环境变量加载单个账号（向后兼容） */
export function loadAccountFromEnv(): AccountConfig | null {
  const email = process.env.MONKEYCODE_EMAIL || process.env.MONKEYCODE_USERNAME || ""
  const password = process.env.MONKEYCODE_PASSWORD || ""
  if (!email || !password) return null

  return {
    email,
    password,
    mode: (process.env.MONKEYCODE_LOGIN_MODE as LoginMode) || "user",
    cookie: process.env.MONKEYCODE_SESSION_COOKIE || undefined,
  }
}