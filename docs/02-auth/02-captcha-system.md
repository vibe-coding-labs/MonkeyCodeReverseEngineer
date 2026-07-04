---
description: 验证码系统分析 - CAP.js 前端集成与 go-cap 后端配置（线上实测确认）
protocol_version: 2026-06-27 线上实测
confidence: high
last_verified: 2026-06-27
---

# 验证码系统 (CAP.js / go-cap)

## 概述

MonkeyCode 使用 **go-cap** 验证码系统（前端组件为 CAP.js），配置为 **50x32 网格**的图像点击验证码。

**架构**: 
- 后端: `go-cap` 闭源二进制模块
- 前端: `CAP.js` 闭源 JavaScript 组件（50x32 网格点击）
- 验证码类型: 图像网格点击（选择包含特定物体的图片）

## API 端点

### 创建验证码挑战

```http
POST /api/v1/public/captcha/challenge
Content-Type: application/json
```

**请求体**: 不需要发送请求体（`{}` 即可）

**线上实测返回** (HTTP 201):
```json
{
  "challenge": {
    "c": 50,
    "s": 32,
    "d": 3
  },
  "expires": 1782557516440,
  "token": "ab6768a297ba96ee8443a9494"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `challenge.c` | int | 网格列数（50） |
| `challenge.s` | int | 网格行数（32） |
| `challenge.d` | int | 需要点击的目标数量（3） |
| `expires` | int | 挑战过期时间戳（毫秒） |
| `token` | string | 挑战 token，用于后续 redeem |

> **注意:** 此格式和 `auth-protocol-complete.md` 中的 `{"code":0,"data":{...}}` 格式**不同**。Go 后端 `h.captcha.Create()` 的返回值直接作为 `c.JSON(http.StatusCreated, challenge)` 的响应体，没有经过统一响应包装。**线上实测确认**（2026-06-27）。

### 兑换验证码

```http
POST /api/v1/public/captcha/redeem
Content-Type: application/json
```

**请求体**:

```json
{
  "id": "challenge-token-from-create",
  "answers": [
    {"x": 12, "y": 8},
    {"x": 35, "y": 20},
    {"x": 42, "y": 5}
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 挑战 token（从 challenge 响应的 `token` 字段获取） |
| `answers` | array | 用户点击的坐标数组 |
| `answers[].x` | int | X 坐标（0-49） |
| `answers[].y` | int | Y 坐标（0-31） |

**响应体** (成功):
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": true,
    "token": "captcha_token_string_xxxxxxxxxxxx"
  }
}
```

**响应体** (失败):
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": false,
    "token": ""
  }
}
```

> 注意：redeem 响应遵循标准 `{"code":0,"data":...}` 包装格式。

**后端实现:**

```go
// backend/biz/public/handler/http/v1/captcha.go
func (h *CaptchaHandler) RedeemCaptcha() web.HandlerFunc {
    return func(c web.Context) error {
        var req RedeemCaptchaReq
        if err := c.Bind(&req); err != nil {
            return err
        }
        result, err := h.captcha.Redeem(req.ID, req.Answers)
        if err != nil {
            return errcode.ErrCreateCaptcha
        }
        return c.JSON(http.StatusOK, result)
    }
}
```

### 前端实现

```typescript
// frontend/src/utils/common.tsx
export async function captchaChallenge(): Promise<string | null> {
  try {
    const cap = new Cap({
      apiEndpoint: '/api/v1/public/captcha/'
    })
    const data = await cap.solve()
    if (data.success) {
      return data.token
    }
    return null
  } catch (err) {
    return null
  }
}
```

## 验证码使用场景

| 登录方式 | 需要验证码 | 验证码类型 |
|---------|-----------|-----------|
| 百智云 OAuth | ✅ SCaptcha（第三方） | 滑块/点击验证码，business_id=`0196c95c-620c-7cde-9c2d-b10d0faf5583` |
| 密码登录 | ✅ go-cap | 50x32 网格点击 |
| 团队密码登录 | ✅ go-cap | 50x32 网格点击 |
| Git OAuth | ❌ | 不需要 |
| Admin Impersonate | ❌ | 不需要 |

## go-cap 配置（线上实测 + 源码确认）

| 配置 | 线上实测值 | 说明 |
|------|-----------|------|
| 网格列数 (c) | `50` | 50 列 |
| 网格行数 (s) | `32` | 32 行 |
| 目标数量 (d) | `3` | 需要点击 3 个目标 |
| 挑战过期 | ~120s | 从 expires 时间戳计算 |
| 类型 | 图像点击（选择包含特定物体的图片） | go-cap Proof-of-Work |

> **已知问题:** `go-cap` 是闭源二进制模块，无法直接获取其内部的验证码验证逻辑。

## 线上错误码格式确认

| 场景 | HTTP 状态码 | 响应体 | 说明 |
|------|------------|--------|------|
| /users/me 无 Cookie | 401 | `Unauthorized` (text/plain) | 旧端点，纯文本 |
| /users/status 无 Cookie | 401 | `{"code":401,"message":"未授权 [trace_id:xxx]"}` | JSON 格式 |
| /users/status 无效 Cookie | 401 | `{"code":401,"message":"未授权 [trace_id:xxx]"}` | JSON 格式 |
| /password-login 错误密码 | 403 | `{"code":403,"message":"禁止访问 [trace_id:xxx]"}` | JSON 格式 |
| /teams/users/login 错误密码 | 403 | `{"code":403,"message":"禁止访问 [trace_id:xxx]"}` | JSON 格式 |

> 所有错误响应中都包含 `trace_id` 字段，用于服务器端追踪。

## OAuth 跳转参数（线上实测确认）

```http
GET /api/v1/users/login
→ 302 Location: https://baizhi.cloud/oauth/authorize
    ?client_id=monkeycode-ai
    &redirect_uri=https://monkeycode-ai.com/api/v1/users/baizhi/callback
    &response_type=code
    &scope=user+phone
    &state=<random-uuid>
```

| 参数 | 线上值 | 说明 |
|------|--------|------|
| `client_id` | `monkeycode-ai` | 百智云 OAuth 客户端 ID |
| `redirect_uri` | `https://monkeycode-ai.com/api/v1/users/baizhi/callback` | OAuth 回调路径 |
| `response_type` | `code` | 授权码模式 |
| `scope` | `user phone` | 授权范围：用户信息和手机号 |
| `state` | 随机 UUID | CSRF 防护 |

---

## 相关章节

- [登录方式详解](03-login-methods.md) — 各登录方式如何使用验证码
- [百智云 OAuth 流程](04-oauth-baizhi-cloud.md) — SCaptcha 集成
- [认证自动化](07-auth-automation.md) — 验证码绕过分析
