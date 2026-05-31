// MonkeyCode 认证模块 — Cookie-based Session 管理
//
// 支持的登录方式:
// 1. 普通用户密码登录 (POST /api/v1/users/password-login) → Cookie: monkeycode_ai_session
// 2. 团队管理员密码登录 (POST /api/v1/teams/users/login) → Cookie: monkeycode_ai_team_session
// 3. 手动设置 Session Cookie（从浏览器提取）
//
// 验证码说明:
// - 所有密码登录需要 captcha_token (go-cap 验证码系统)
// - 自动化场景建议直接使用浏览器提取的 Session Cookie

import { browserHeaders } from "./browser-headers.js"
const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"
const SESSION_COOKIE_NAME = "monkeycode_ai_session"
const TEAM_SESSION_COOKIE_NAME = "monkeycode_ai_team_session"

export type LoginMode = "user" | "team"

export class AuthManager {
  private sessionCookie: string = ""
  private sessionCookieName: string = SESSION_COOKIE_NAME
  private email: string = ""
  private passwordHash: string = ""
  private captchaToken: string = ""
  private lastAuthTime: number = 0
  private sessionTTL: number = 24 * 60 * 60 * 1000 // 24h
  private loginMode: LoginMode = "user"

  constructor() {
    this.email = process.env.MONKEYCODE_EMAIL || process.env.MONKEYCODE_USERNAME || ""
    this.passwordHash = process.env.MONKEYCODE_PASSWORD_HASH || ""
    this.captchaToken = process.env.MONKEYCODE_CAPTCHA_TOKEN || ""

    // 如果提供了明文密码，直接使用（API 接收明文，不是 MD5）
    const plainPassword = process.env.MONKEYCODE_PASSWORD || ""
    if (plainPassword && !this.passwordHash) {
      this.passwordHash = plainPassword.trim()
    }

    // 登录模式
    const mode = process.env.MONKEYCODE_LOGIN_MODE || "user"
    if (mode === "team") {
      this.loginMode = "team"
      this.sessionCookieName = TEAM_SESSION_COOKIE_NAME
    }

    // 如果直接提供了 Session Cookie
    const existingCookie = process.env.MONKEYCODE_SESSION_COOKIE || ""
    if (existingCookie) {
      this.sessionCookie = existingCookie
      this.lastAuthTime = Date.now()
      console.log(`[Auth] Using provided session cookie: ${existingCookie.substring(0, 20)}...`)
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

  /** 号池：设置凭据（不自动登录，由 AccountPool 控制时机） */
  setCredentials(email: string, password: string, mode: LoginMode = "user"): void {
    this.email = email
    this.passwordHash = password // 明文
    this.loginMode = mode
    this.sessionCookieName = mode === "team" ? TEAM_SESSION_COOKIE_NAME : SESSION_COOKIE_NAME
  }

  /** 获取当前账号的 email */
  getEmail(): string {
    return this.email
  }

  /** 根据登录模式执行登录 */
  async login(): Promise<void> {
    if (this.loginMode === "team") {
      await this.loginTeam()
    } else {
      await this.loginUser()
    }
  }

  /** 普通用户密码登录
   *  API: POST /api/v1/users/password-login
   *  Cookie: monkeycode_ai_session
   */
  async loginUser(): Promise<void> {
    if (!this.email || !this.passwordHash) {
      throw new Error(
        "Missing credentials. Set MONKEYCODE_EMAIL and MONKEYCODE_PASSWORD (or MONKEYCODE_PASSWORD_HASH)."
      )
    }

    const url = `${MONKEYCODE_BASE_URL}/api/v1/users/password-login`
    const body: Record<string, string> = {
      email: this.email.trim(),
      password: this.passwordHash,
    }
    if (this.captchaToken) {
      body.captcha_token = this.captchaToken
    }

    const response = await fetch(url, {
      method: "POST",
      headers: browserHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      redirect: "manual",
    })

    if (!response.ok && response.status !== 302) {
      const respBody = await response.text()
      throw new Error(`User login failed (${response.status}): ${respBody}`)
    }

    const cookie = this.extractCookie(response, SESSION_COOKIE_NAME)
    this.sessionCookie = cookie
    this.sessionCookieName = SESSION_COOKIE_NAME
    this.lastAuthTime = Date.now()
    console.log(`[Auth] User login successful, session cookie obtained`)
  }

  /** 团队管理员密码登录
   *  API: POST /api/v1/teams/users/login
   *  Cookie: monkeycode_ai_team_session
   */
  async loginTeam(): Promise<void> {
    if (!this.email || !this.passwordHash) {
      throw new Error(
        "Missing credentials. Set MONKEYCODE_EMAIL and MONKEYCODE_PASSWORD (or MONKEYCODE_PASSWORD_HASH)."
      )
    }

    const url = `${MONKEYCODE_BASE_URL}/api/v1/teams/users/login`
    const body: Record<string, string> = {
      email: this.email.trim(),
      password: this.passwordHash,
    }
    if (this.captchaToken) {
      body.captcha_token = this.captchaToken
    }

    const response = await fetch(url, {
      method: "POST",
      headers: browserHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      redirect: "manual",
    })

    if (!response.ok && response.status !== 302) {
      const respBody = await response.text()
      throw new Error(`Team login failed (${response.status}): ${respBody}`)
    }

    const cookie = this.extractCookie(response, TEAM_SESSION_COOKIE_NAME)
    this.sessionCookie = cookie
    this.sessionCookieName = TEAM_SESSION_COOKIE_NAME
    this.lastAuthTime = Date.now()
    console.log(`[Auth] Team login successful, session cookie obtained`)
  }

  /** 使用已有的 Session Cookie（从浏览器提取） */
  setSessionCookie(cookie: string, mode: LoginMode = "user"): void {
    this.sessionCookie = cookie
    this.sessionCookieName = mode === "team" ? TEAM_SESSION_COOKIE_NAME : SESSION_COOKIE_NAME
    this.loginMode = mode
    this.lastAuthTime = Date.now()
  }

  /** 同步获取当前 Session Cookie（不检查过期） */
  getSessionCookieSync(): string {
    return this.sessionCookie
  }

  /** 获取当前 Session Cookie 名称 */
  getSessionCookieName(): string {
    return this.sessionCookieName
  }

  /** 构造认证请求头 */
  async authHeaders(): Promise<Record<string, string>> {
    const cookie = await this.getSessionCookie()
    return {
      Cookie: `${this.sessionCookieName}=${cookie}`,
      "Content-Type": "application/json",
    }
  }

  /** 检查登录状态 */
  async checkStatus(): Promise<boolean> {
    const url = this.loginMode === "team"
      ? `${MONKEYCODE_BASE_URL}/api/v1/teams/users/status`
      : `${MONKEYCODE_BASE_URL}/api/v1/users/status`

    const response = await fetch(url, {
      headers: browserHeaders({
        Cookie: `${this.getSessionCookieName()}=${this.getSessionCookieSync()}`,
      }),
    })
    return response.ok
  }

  /** 登出 */
  async logout(): Promise<void> {
    if (!this.sessionCookie) return
    const logoutUrl = this.loginMode === "team"
      ? `${MONKEYCODE_BASE_URL}/api/v1/teams/users/logout`
      : `${MONKEYCODE_BASE_URL}/api/v1/users/logout`

    await fetch(logoutUrl, {
      method: "POST",
      headers: browserHeaders({
        Cookie: `${this.getSessionCookieName()}=${this.getSessionCookieSync()}`,
      }),
    })
    this.sessionCookie = ""
    this.lastAuthTime = 0
    console.log("[Auth] Logged out")
  }

  /** 从响应中提取指定名称的 Cookie */
  private extractCookie(response: Response, cookieName: string): string {
    const setCookie = response.headers.get("set-cookie")
    if (!setCookie) {
      throw new Error("No Set-Cookie header in login response")
    }

    const match = setCookie.match(new RegExp(`${cookieName}=([^;]+)`))
    if (!match) {
      throw new Error(`Cannot extract ${cookieName} from Set-Cookie: ${setCookie}`)
    }

    return match[1]
  }
}
