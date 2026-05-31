// 浏览器伪装头 — 精确模拟 Chrome 148 请求
//
// 使用规则:
//   monkeycode-ai.com → mkHeaders()       — 调 MonkeyCode API
//   baizhi.cloud      → bzHeaders()        — 调百智云 API
//   *.s-captcha-r1.com → scHeaders()       — 调 SCaptcha
//   页面导航           → navHeaders(domain) — 模拟浏览器页面跳转

const BASE_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
const BASE_ACCEPT = "application/json, text/plain, */*"
const BASE_ACCEPT_LANG = "zh-CN,zh;q=0.9,en;q=0.8"
const BASE_SEC_CH = '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"'

/** 合并基本浏览器头与自定义头 */
function merge(domain: string, extra: Record<string, string> = {}): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    Accept: BASE_ACCEPT,
    "Accept-Language": BASE_ACCEPT_LANG,
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": BASE_SEC_CH,
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    Origin: `https://${domain}`,
    Referer: `https://${domain}/`,
    Priority: "u=1, i",
    ...extra,
  }
}

/** MonkeyCode API 请求头（Origin: https://monkeycode-ai.com） */
export function mkHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return merge("monkeycode-ai.com", extra)
}

/** 百智云 API 请求头（Origin: https://baizhi.cloud） */
export function bzHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return merge("baizhi.cloud", extra)
}

/** SCaptcha API 请求头 */
export function scHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    Accept: BASE_ACCEPT,
    "Accept-Language": BASE_ACCEPT_LANG,
    "Content-Type": "application/json",
    "Origin": "https://monkeycode-ai.com",
    "Referer": "https://monkeycode-ai.com/",
    ...extra,
  }
}

/** 页面导航请求头（模拟浏览器地址栏导航，非 XHR） */
export function navHeaders(domain: string, extra: Record<string, string> = {}): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": BASE_ACCEPT_LANG,
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": BASE_SEC_CH,
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Upgrade-Insecure-Requests": "1",
    Priority: "u=0, i",
    ...extra,
  }
}

/** WebSocket 请求头 */
export function wsHeaders(domain: string, cookie: string): Record<string, string> {
  return {
    "User-Agent": BASE_UA,
    "Accept-Language": BASE_ACCEPT_LANG,
    "Cache-Control": "no-cache",
    Pragma: "no-cache",
    Origin: `https://${domain}`,
    Cookie: cookie,
    "Sec-WebSocket-Version": "13",
  }
}