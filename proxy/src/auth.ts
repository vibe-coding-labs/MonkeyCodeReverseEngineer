// MonkeyCode 认证模块 — Cookie-based Session 管理

import crypto from "crypto"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"
const SESSION_COOKIE_NAME = "sl-session"

export class AuthManager {
  private sessionCookie: string = ""
  private username: string = ""
  private passwordHash: string = ""
  private lastAuthTime: number = 0
  private sessionTTL: number = 24 * 60 * 60 * 1000 // 24h

  constructor() {
    this.username = process.env.MONKEYCODE_USERNAME || ""
    this.passwordHash = process.env.MONKEYCODE_PASSWORD_HASH || ""
    // 如果提供了明文密码，自动计算 MD5
    const plainPassword = process.env.MONKEYCODE_PASSWORD || ""
    if (plainPassword && !this.passwordHash) {
      this.passwordHash = md5(plainPassword)
    }
  }

  /** 获取当前有效的 Session Cookie，过期则重新认证 */
  async getSessionCookie(): Promise<string> {
    if (this.sessionCookie && Date.now() - this.lastAuthTime < this.sessionTTL) {
      return this.sessionCookie
    }
    await this.login()
    return this.sessionCookie
  }

  /** Team 用户登录 */
  async login(): Promise<void> {
    if (!this.username || !this.passwordHash) {
      throw new Error(
        "Missing credentials. Set MONKEYCODE_USERNAME and MONKEYCODE_PASSWORD (or MONKEYCODE_PASSWORD_HASH) environment variables."
      )
    }

    const url = `${MONKEYCODE_BASE_URL}/api/v1/teams/users/login`
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: this.username,
        password: this.passwordHash,
      }),
      redirect: "manual",
    })

    if (!response.ok && response.status !== 302) {
      const body = await response.text()
      throw new Error(`Login failed (${response.status}): ${body}`)
    }

    // 从 Set-Cookie 提取 session
    const setCookie = response.headers.get("set-cookie")
    if (!setCookie) {
      throw new Error("No session cookie in login response")
    }

    const match = setCookie.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
    if (!match) {
      throw new Error(`Cannot extract ${SESSION_COOKIE_NAME} from Set-Cookie: ${setCookie}`)
    }

    this.sessionCookie = match[1]
    this.lastAuthTime = Date.now()
    console.log(`[Auth] Login successful, session cookie obtained`)
  }

  /** 使用已有的 Session Cookie（手动设置） */
  setSessionCookie(cookie: string): void {
    this.sessionCookie = cookie
    this.lastAuthTime = Date.now()
  }

  /** 同步获取当前 Session Cookie（不检查过期） */
  getSessionCookieSync(): string {
    return this.sessionCookie
  }

  /** 构造认证请求头 */
  async authHeaders(): Promise<Record<string, string>> {
    const cookie = await this.getSessionCookie()
    return {
      Cookie: `${SESSION_COOKIE_NAME}=${cookie}`,
      "Content-Type": "application/json",
    }
  }

  /** 登出 */
  async logout(): Promise<void> {
    if (!this.sessionCookie) return
    const headers = await this.authHeaders()
    await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/logout`, {
      method: "POST",
      headers,
    })
    this.sessionCookie = ""
    this.lastAuthTime = 0
    console.log("[Auth] Logged out")
  }
}

/** MD5 哈希 */
export function md5(input: string): string {
  return crypto.createHash("md5").update(input).digest("hex")
}
