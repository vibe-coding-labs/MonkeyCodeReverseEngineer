// MonkeyCode OAuth 登录流程 — 纯 HTTP 实现
// 流程: SCaptcha → 百智云短信验证码 → 百智云手机号登录 → OAuth authorize → MonkeyCode 回调

import { mkHeaders, bzHeaders, scHeaders, navHeaders } from "./browser-headers.js"

const MONKEYCODE_BASE_URL = process.env.MONKEYCODE_BASE_URL || "https://monkeycode-ai.com"
const BAIZHI_URL = "https://baizhi.cloud"
const SESSION_COOKIE_NAME = "monkeycode_ai_session"
const SCAPTCHA_BUSINESS_ID = "0196c95c-620c-7cde-9c2d-b10d0faf5583"
const SCAPTCHA_API = `https://${SCAPTCHA_BUSINESS_ID}.safepoint.s-captcha-r1.com`

/** OAuth 会话状态 — 跨多步 API 调用保持状态 */
export interface OAuthSession {
  phone: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
  baizhiCookies: string
  createdAt: number
}

/** 全局 OAuth 会话存储 */
let currentOAuthSession: OAuthSession | null = null

/** Step 1: 获取 OAuth 重定向 URL + 解析参数 */
export async function startOAuthLogin(): Promise<{
  oauthUrl: string
  state: string
  clientId: string
  redirectUri: string
  scope: string
}> {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/login`, {
    headers: mkHeaders(),
    redirect: "manual",
  })

  if (resp.status !== 302) {
    throw new Error(`Expected 302 redirect, got ${resp.status}`)
  }

  const location = resp.headers.get("Location") || ""
  if (!location) {
    throw new Error("No Location header in redirect response")
  }

  const url = new URL(location)
  const state = url.searchParams.get("state") || ""
  const clientId = url.searchParams.get("client_id") || ""
  const redirectUri = url.searchParams.get("redirect_uri") || ""
  const scope = url.searchParams.get("scope") || ""

  return { oauthUrl: location, state, clientId, redirectUri, scope }
}

/** Step 2: 获取 SCaptcha 验证码 token */
export async function getSCaptchaToken(): Promise<string> {
  const originalTlsSetting = process.env.NODE_TLS_REJECT_UNAUTHORIZED
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0"

  let resp: Response
  try {
    resp = await fetch(`${SCAPTCHA_API}/v1/api/challenge`, {
      method: "POST",
      headers: scHeaders(),
      body: JSON.stringify({ business_id: SCAPTCHA_BUSINESS_ID }),
    })
  } finally {
    if (originalTlsSetting === undefined) {
      delete process.env.NODE_TLS_REJECT_UNAUTHORIZED
    } else {
      process.env.NODE_TLS_REJECT_UNAUTHORIZED = originalTlsSetting
    }
  }

  if (!resp.ok) {
    throw new Error(`SCaptcha request failed: ${resp.status}`)
  }

  const data = await resp.json() as any
  if (!data.success) {
    throw new Error(`SCaptcha failed: ${JSON.stringify(data)}`)
  }

  const token = data.data?.token || ""
  if (!token) {
    throw new Error("SCaptcha returned no token")
  }

  return token
}

/** Step 3: 发送短信验证码到百智云 */
export async function sendSmsCode(phone: string, captchaToken: string): Promise<boolean> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/phone_code`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      phone,
      kind: "login",
      token: captchaToken,
    }),
  })

  if (!resp.ok) {
    const body = await resp.text().catch(() => "")
    throw new Error(`SMS send failed: ${resp.status} ${body.slice(0, 200)}`)
  }

  const data = await resp.json() as any
  if (data.code !== 0) {
    throw new Error(`SMS send error: code=${data.code}, msg=${data.message}`)
  }

  return true
}

/** 发起登录流程: 获取 OAuth 参数 + SCaptcha + 发送短信 */
export async function initiateLogin(phone: string): Promise<{
  message: string
  state: string
}> {
  const oauth = await startOAuthLogin()
  const captchaToken = await getSCaptchaToken()
  await sendSmsCode(phone, captchaToken)

  currentOAuthSession = {
    phone,
    state: oauth.state,
    clientId: oauth.clientId,
    redirectUri: oauth.redirectUri,
    scope: oauth.scope || "openid profile email",
    baizhiCookies: "",
    createdAt: Date.now(),
  }

  return {
    message: `SMS code sent to ${phone}. Use POST /admin/login/verify with the code to complete login.`,
    state: oauth.state,
  }
}

/** Step 4: 百智云手机号登录 */
async function baizhiPhoneLogin(
  phone: string,
  code: string
): Promise<{ cookies: string; data: any }> {
  const resp = await fetch(`${BAIZHI_URL}/api/v1/user/login/phone`, {
    method: "POST",
    headers: bzHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ phone, code }),
  })

  if (!resp.ok) {
    throw new Error(`百智云 login failed: ${resp.status}`)
  }

  const data = await resp.json() as any
  if (data.code !== 0) {
    throw new Error(`百智云 login error: code=${data.code}, msg=${data.message}`)
  }

  const setCookie = resp.headers.get("Set-Cookie") || ""
  const cookies: string[] = []
  for (const part of setCookie.split(",")) {
    const match = part.trim().match(/^([^=]+)=([^;]+)/)
    if (match) {
      cookies.push(`${match[1]}=${match[2]}`)
    }
  }

  return { cookies: cookies.join("; "), data: data.data }
}

/** Step 5: OAuth authorize — 用百智云 session 获取 code */
async function baizhiOAuthAuthorize(
  baizhiCookies: string,
  clientId: string,
  redirectUri: string,
  scope: string,
  state: string
): Promise<{ code: string; callbackUrl: string }> {
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    scope,
    state,
    response_type: "code",
  })

  const resp = await fetch(`${BAIZHI_URL}/api/v1/oauth/authorize?${params}`, {
    headers: {
      ...bzHeaders(),
      Cookie: baizhiCookies,
      Accept: navHeaders("baizhi.cloud").Accept, // 页面导航用 text/html
      "Sec-Fetch-Dest": "document",
      "Sec-Fetch-Mode": "navigate",
      "Upgrade-Insecure-Requests": "1",
    },
    redirect: "manual",
  })

  if (resp.status !== 302) {
    const body = await resp.text()
    throw new Error(`OAuth authorize expected 302, got ${resp.status}: ${body.slice(0, 200)}`)
  }

  const location = resp.headers.get("Location") || ""
  if (!location) {
    throw new Error("OAuth authorize: no Location header")
  }

  const url = new URL(location)
  const code = url.searchParams.get("code") || ""
  if (!code) {
    const error = url.searchParams.get("error") || "unknown"
    throw new Error(`OAuth authorize failed: error=${error}, location=${location.slice(0, 100)}`)
  }

  return { code, callbackUrl: location }
}

/** Step 6: MonkeyCode 回调 — 用 OAuth code 换取 session cookie */
async function monkeycodeCallback(callbackUrl: string): Promise<string> {
  const resp = await fetch(callbackUrl, {
    headers: navHeaders("monkeycode-ai.com", {
      "Sec-Fetch-Site": "cross-site",
      Referer: "https://baizhi.cloud/",
    }),
    redirect: "manual",
  })

  const setCookie = resp.headers.get("Set-Cookie") || ""
  const match = setCookie.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
  if (match) {
    return match[1]
  }

  const location = resp.headers.get("Location") || ""
  if (location) {
    const resp2 = await fetch(
      location.startsWith("http") ? location : `${MONKEYCODE_BASE_URL}${location}`,
      {
        headers: mkHeaders(),
        redirect: "manual",
      }
    )
    const setCookie2 = resp2.headers.get("Set-Cookie") || ""
    const match2 = setCookie2.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))
    if (match2) {
      return match2[1]
    }
  }

  throw new Error(
    `Failed to extract session cookie from callback. Status: ${resp.status}, Set-Cookie: ${setCookie.slice(0, 200)}`
  )
}

/** 验证 session cookie 是否有效 */
export async function verifySession(sessionCookie: string): Promise<{
  valid: boolean
  user?: any
}> {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/status`, {
    headers: mkHeaders({
      Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}`,
    }),
  })

  if (resp.ok) {
    const data = await resp.json() as any
    if (data.code === 0) {
      return { valid: true, user: data.data }
    }
  }

  return { valid: false }
}

/** 从已有任务列表中发现 image_id */
export async function discoverImageId(sessionCookie: string): Promise<{
  imageId: string
  imageName: string
} | null> {
  const resp = await fetch(
    `${MONKEYCODE_BASE_URL}/api/v1/users/tasks?page=1&size=5`,
    {
      headers: mkHeaders({
        Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}`,
      }),
    }
  )

  if (!resp.ok) {
    return null
  }

  const data = await resp.json() as any
  const tasks = data.data?.tasks || []

  for (const task of tasks) {
    if (task.image?.id) {
      return {
        imageId: task.image.id,
        imageName: task.image.name || "unknown",
      }
    }
  }

  return null
}

/** 获取可用模型列表 */
export async function discoverModels(sessionCookie: string): Promise<any[]> {
  const resp = await fetch(`${MONKEYCODE_BASE_URL}/api/v1/users/models`, {
    headers: mkHeaders({
      Cookie: `${SESSION_COOKIE_NAME}=${sessionCookie}`,
    }),
  })

  if (!resp.ok) {
    return []
  }

  const data = await resp.json() as any
  return data.data?.models || data.data?.list || []
}

/** 完成登录: 验证 SMS code → OAuth → 回调 → 获取 session cookie */
export async function completeLogin(smsCode: string): Promise<{
  sessionCookie: string
  imageId?: string
  imageName?: string
  models?: any[]
  user?: any
}> {
  if (!currentOAuthSession) {
    throw new Error("No pending login session. Call POST /admin/login/send-code first.")
  }

  if (Date.now() - currentOAuthSession.createdAt > 10 * 60 * 1000) {
    currentOAuthSession = null
    throw new Error("Login session expired. Please request a new SMS code.")
  }

  const session = currentOAuthSession

  const loginResult = await baizhiPhoneLogin(session.phone, smsCode)
  const baizhiCookies = loginResult.cookies

  const { callbackUrl } = await baizhiOAuthAuthorize(
    baizhiCookies,
    session.clientId,
    session.redirectUri,
    session.scope,
    session.state
  )

  const sessionCookie = await monkeycodeCallback(callbackUrl)

  currentOAuthSession = null

  let imageResult: { imageId: string; imageName: string } | null = null
  let models: any[] = []
  let user: any = null

  try {
    imageResult = await discoverImageId(sessionCookie)
  } catch {
    // ignore
  }

  try {
    models = await discoverModels(sessionCookie)
  } catch {
    // ignore
  }

  try {
    const result = await verifySession(sessionCookie)
    user = result.user
  } catch {
    // ignore
  }

  return {
    sessionCookie,
    imageId: imageResult?.imageId,
    imageName: imageResult?.imageName,
    models: models.length > 0 ? models : undefined,
    user,
  }
}

/** 直接用已有的 OAuth 回调 URL 完成登录（手动模式） */
export async function loginWithCallbackUrl(callbackUrl: string): Promise<{
  sessionCookie: string
  imageId?: string
  imageName?: string
}> {
  const sessionCookie = await monkeycodeCallback(callbackUrl)

  let imageResult: { imageId: string; imageName: string } | null = null
  try {
    imageResult = await discoverImageId(sessionCookie)
  } catch {
    // ignore
  }

  return {
    sessionCookie,
    imageId: imageResult?.imageId,
    imageName: imageResult?.imageName,
  }
}