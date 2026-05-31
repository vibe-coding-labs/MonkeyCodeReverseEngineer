// 伪装成 Chrome 浏览器的请求头 — 避免触发 MonkeyCode WAF
// 从真实的浏览器请求中抓取的完整头信息

export const BROWSER_HEADERS: Record<string, string> = {
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
  Accept: "application/json, text/plain, */*",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
  "Accept-Encoding": "gzip, deflate, br",
  "Sec-Ch-Ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
  "Sec-Ch-Ua-Mobile": "?0",
  "Sec-Ch-Ua-Platform": '"macOS"',
  "Sec-Fetch-Dest": "empty",
  "Sec-Fetch-Mode": "cors",
  "Sec-Fetch-Site": "same-origin",
  Origin: "https://monkeycode-ai.com",
  Referer: "https://monkeycode-ai.com/",
  Priority: "u=1, i",
}

/** 合并 auth headers（Cookie）与浏览器头 */
export function browserHeaders(
  extra: Record<string, string> = {}
): Record<string, string> {
  return {
    ...BROWSER_HEADERS,
    ...extra, // 外部可覆盖（如 Content-Type, Cookie）
  }
}

/** OAuth 流程专用：模拟页面导航的请求头 */
export const BROWSER_NAVIGATION_HEADERS: Record<string, string> = {
  ...BROWSER_HEADERS,
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Upgrade-Insecure-Requests": "1",
}
