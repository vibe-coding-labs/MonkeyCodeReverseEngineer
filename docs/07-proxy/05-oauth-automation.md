---
description: 代理中的 OAuth 登录自动化实现 — 百智云 6 步完整流程、Playwright 自动化代码
protocol_version: based on admin-login.ts 实现
confidence: high
last_verified: 2026-06-27
---

# OAuth 登录自动化

## 6 步自动化流程（纯 HTTP）

代理的 `admin-login.ts`（425 行）实现了纯 HTTP 的 OAuth 自动化，无需浏览器：

| 步骤 | 操作 | HTTP 端点 | 说明 |
|------|------|-----------|------|
| 1 | 获取 OAuth 跳转 URL | `GET /api/v1/users/login` → 提取 authorize URL | 从 MonkeyCode 获取百智云 OAuth authorize URL |
| 2 | 获取 SCaptcha token | `baizhi.cloud` SCaptcha API | 调用百智云验证码服务获取挑战 |
| 3 | 发送短信验证码 | `baizhi.cloud` SMS API | 发送验证码到用户手机 |
| 4 | 百智云手机号登录 | `baizhi.cloud` login API | 手机号+验证码登录百智云 |
| 5 | OAuth 授权跳转 | `baizhi.cloud` OAuth authorize | 执行 OAuth 授权：`POST /oauth/authorize` |
| 6 | MonkeyCode 回调处理 | `MonkeyCode` OAuth callback | 从回调 URL 提取 session cookie |

### 步骤 1-6 的 HTTP 请求序列

```http
### Step 1: 获取 OAuth 跳转 URL
GET /api/v1/users/login HTTP/1.1
Host: api.monkeycode-ai.com

→ 302 Location: https://oauth.baizhi.cloud/oauth/authorize?
  client_id=monkeycode-ai&
  redirect_uri=https://api.monkeycode-ai.com/api/v1/users/oauth/callback&
  response_type=code&
  scope=user+phone

### Step 2: 获取 SCaptcha token
POST /api/v1/public/captcha/challenge HTTP/1.1
Host: baizhi.cloud
Content-Type: application/x-www-form-urlencoded

→ {"code":0,"data":{"token":"sc_xxx","expires_at":1715299200}}

### Step 3: 发送短信验证码
POST /api/v1/phone/send-code HTTP/1.1
Host: baizhi.cloud

phone=13800138000&captcha_token=sc_xxx

### Step 4: 手机号登录
POST /api/v1/phone/login HTTP/1.1
Host: baizhi.cloud

phone=13800138000&code=123456

→ Set-Cookie: baizhi_session=xxx

### Step 5: OAuth 授权
POST /oauth/authorize HTTP/1.1
Host: baizhi.cloud
Cookie: baizhi_session=xxx
Content-Type: application/x-www-form-urlencoded

client_id=monkeycode-ai&
response_type=code&
scope=user+phone&
redirect_uri=https://api.monkeycode-ai.com/api/v1/users/oauth/callback

→ 302 Location: https://api.monkeycode-ai.com/api/v1/users/oauth/callback?code=oauth_code_xxx

### Step 6: 提取 Session Cookie
GET /api/v1/users/oauth/callback?code=oauth_code_xxx HTTP/1.1
Host: api.monkeycode-ai.com

→ Set-Cookie: monkeycode_ai_session=session_uuid_xxx; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax
```

## 代理暴露的端点

```typescript
// admin-login.ts — 代理暴露的 OAuth 自动化端点
router.post('/admin/login/send-code', async (req, res) => {
    // 1. 发现百智云 authorize URL
    const authorizeUrl = await discoverOAuthUrl();
    // 2. 获取 SCaptcha token
    const captchaToken = await getSCaptchaToken();
    // 3. 发送短信验证码到用户手机
    await sendSMSCode(req.body.phone, captchaToken);
    res.json({ success: true });
});

router.post('/admin/login/verify', async (req, res) => {
    // 4. 手机号+验证码登录百智云
    const baizhiSession = await loginBaizhi(req.body.phone, req.body.code);
    // 5. OAuth 授权
    const callbackUrl = await oauthAuthorize(baizhiSession);
    // 6. 提取 MonkeyCode session cookie
    const session = await extractSession(callbackUrl);
    res.json({ session });
});

router.post('/admin/login/callback', async (req, res) => {
    // 处理 MonkeyCode OAuth 回调（直接传入 code）
    const session = await handleOAuthCallback(req.body.code);
    res.json({ session });
});

router.get('/admin/discover', async (req, res) => {
    // 自动发现 image_id 和模型配置
    const config = await discoverConfig();
    res.json(config);
});
```

## 浏览器头伪装

```typescript
// browser-headers.ts — 3 种域名的 Chrome 148 头伪装
// monkeycode-ai.com 请求头
const mkHeaders = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ... Chrome/148.0.0.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Origin': 'https://monkeycode-ai.com',
    'Referer': 'https://monkeycode-ai.com/',
    'Sec-Fetch-Site': 'same-site',
};

// baizhi.cloud 请求头
const bzHeaders = {
    'User-Agent': '... Chrome/148.0.0.0',
    'Origin': 'https://oauth.baizhi.cloud',
    'Referer': 'https://oauth.baizhi.cloud/',
};

// s-captcha-r1.com 请求头（验证码服务）
const scHeaders = {
    'User-Agent': '... Chrome/148.0.0.0',
    'Origin': 'https://s-captcha-r1.baizhi.cloud',
};
```

## 纯 HTTP 方案 vs Playwright 方案

代理的 `admin-login.ts` 使用纯 HTTP 方案，而 `mvp/` 目录中的 `oauth_login.py` 提供 Playwright 浏览器自动化方案：

| 方案 | 优点 | 缺点 | 文件 |
|------|------|------|------|
| 纯 HTTP | 快速（~2s）、轻量、无浏览器依赖 | 需要处理验证码（SCaptcha reverse） | `admin-login.ts` (425行) |
| Playwright | 自动处理验证码、更稳定 | 慢（~15s）、重（~200MB 浏览器）、需 display | `oauth_login.py` (461行) |

### Playwright 方案核心代码

```python
# mvp/oauth_login.py — Playwright 自动化登录
import asyncio
from playwright.async_api import async_playwright

async def oauth_login(phone: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 1. 打开 MonkeyCode 登录页（触发 OAuth 跳转）
        await page.goto("https://monkeycode-ai.com/login")
        
        # 2. 等待跳转到百智云 OAuth 页
        await page.wait_for_url("**/oauth.baizhi.cloud/**")
        
        # 3. 输入手机号
        await page.fill("input[type='tel']", phone)
        
        # 4. 点击获取验证码
        await page.click("text=获取验证码")
        
        # 5. 等待用户输入验证码
        code = input("请输入手机验证码: ")
        await page.fill("input[placeholder='验证码']", code)
        
        # 6. 点击登录
        await page.click("text=登录")
        
        # 7. 等待 OAuth 授权完成，跳回 MonkeyCode
        await page.wait_for_url("**/monkeycode-ai.com/**")
        
        # 8. 提取 Cookie
        cookies = await context.cookies()
        session = next(c for c in cookies if c['name'] == 'monkeycode_ai_session')
        return session['value']
```

---

## 附录：逆向分析代码示例

### 附录 A: admin-login.ts 核心流程 (TypeScript)
```typescript
// proxy/src/admin-login.ts — 6 步 OAuth 自动化（简化）
class AdminLogin {
    async login(phone: string, code: string): Promise<string> {
        // 1. 发现 OAuth URL
        const loginResp = await this.http.get('/api/v1/users/login');
        const authorizeUrl = loginResp.headers['location'];
        
        // 2. 获取 SCaptcha token
        const captcha = await this.http.post(
            'https://baizhi.cloud/api/v1/public/captcha/challenge', {}
        );
        const captchaToken = captcha.data.token;
        
        // 3. 发送短信验证码
        await this.http.post(
            'https://baizhi.cloud/api/v1/phone/send-code',
            { phone, captcha_token: captchaToken }
        );
        
        // 4. 登录百智云
        const bzLogin = await this.http.post(
            'https://baizhi.cloud/api/v1/phone/login',
            { phone, code }
        );
        const bzCookie = extractCookie(bzLogin, 'baizhi_session');
        
        // 5. OAuth 授权
        const oauthResp = await this.http.post(
            authorizeUrl,
            { client_id: 'monkeycode-ai', /* ... */ },
            { Cookie: `baizhi_session=${bzCookie}` }
        );
        const callbackUrl = oauthResp.headers['location'];
        
        // 6. 提取 Session Cookie
        const callbackResp = await this.http.get(callbackUrl);
        return extractCookie(callbackResp, 'monkeycode_ai_session');
    }
}
```

### 附录 B: Cookie 提取工具函数
```typescript
function extractCookie(response: HttpResponse, cookieName: string): string {
    const setCookie = response.headers['set-cookie'];
    if (!setCookie) throw new Error(`No Set-Cookie header for ${cookieName}`);
    
    const match = setCookie.match(new RegExp(`${cookieName}=([^;]+)`));
    if (!match) throw new Error(`Cookie ${cookieName} not found in response`);
    
    return match[1];
}
```

---

## 相关章节

- [百智云 OAuth 流程](../02-auth/04-oauth-baizhi-cloud.md) — OAuth 流程图
- [浏览器头伪装](01-architecture.md) — browser-headers.ts 在代理中的位置
- [认证号池差距分析](../02-auth/08-pool-gap-analysis.md) — 账号池与自动化对比