# MonkeyCode 代理上线与授权登录执行计划

**Goal:** 启动 MonkeyCode 代理，通过交互式 OAuth 流程完成授权登录，使代理可正常服务

**Architecture:**
- 代理运行在 `localhost:9090`
- 通过 `/admin/login/send-code` + `/admin/login/verify` 端点完成百智云 OAuth 自动化
- 用户只需提供手机号 + 短信验证码，其余由代理自动完成
- 登录后自动发现 `image_id` 和模型列表，无需任何手动配置

**Tech Stack:** Node.js (tsx), Express 4, TypeScript 5

**Risks:**
- SCaptcha 请求可能因证书问题失败 → 已内置 `NODE_TLS_REJECT_UNAUTHORIZED=0` 降级
- 手机号需是已注册 MonkeyCode 的账号
- OAuth 回调可能有延迟 → 短信码 10 分钟内有效

---

## Task 1: 启动代理服务

**Depends on:** None
**Files:**
- Create: `proxy/.env`（仅需设置基础 URL）

- [ ] **Step 1: 创建 minimal .env 配置**

```bash
# proxy/.env
MONKEYCODE_BASE_URL=https://monkeycode-ai.com
PROXY_PORT=9090
MONKEYCODE_HOST_ID=public_host
```

- [ ] **Step 2: 启动代理服务**

Run: `cd /home/cc11001100/github/vibe-coding-labs/MonkeyCode-RE/proxy && npx tsx src/server.ts`
Expected:
- Exit code: 0 (持续运行)
- Output contains: "MonkeyCode Reverse Proxy running on http://localhost:9090"
- Output contains: "POST /admin/login/send-code"
- Output contains: "POST /admin/login/verify"

- [ ] **Step 3: 验证健康检查**

Run: `curl http://localhost:9090/health`
Expected:
- Exit code: 0
- Response contains: `"status": "ok"`

---

## Task 2: 发起 OAuth 登录（需要用户配合）

**Depends on:** Task 1

本 Task 需要用户输入两步信息：
1. **手机号** — 已注册 MonkeyCode 的手机号
2. **短信验证码** — 手机收到的验证码

- [ ] **Step 1: 发送短信验证码 — 用户输入手机号**

Run: `curl -X POST http://localhost:9090/admin/login/send-code -H "Content-Type: application/json" -d '{"phone": "请用户填入手机号"}'`

Expected:
- Exit code: 0
- Response contains: `"message": "SMS code sent to ..."`

此时用户手机会收到百智云短信验证码。

- [ ] **Step 2: 用户输入短信验证码，完成登录**

Run: `curl -X POST http://localhost:9090/admin/login/verify -H "Content-Type: application/json" -d '{"code": "用户填入验证码"}'`

Expected:
- Exit code: 0
- Response contains: `"status": "ok"`、`"sessionCookie": "..."`
- Response contains: `"imageId": "..."`（自动发现）
- Response contains: `"modelCount": > 0`（自动发现）
- 代理自动注入 session cookie + image_id，立即可用

---

## Task 3: 验证代理可用性

**Depends on:** Task 2

- [ ] **Step 1: 验证模型列表可用**

Run: `curl http://localhost:9090/v1/models`
Expected:
- Exit code: 0
- Response contains: `"object": "list"`
- Response contains: `"data": [...]`（至少 1 个模型）

- [ ] **Step 2: 验证聊天 API 可用**

Run: `curl -X POST http://localhost:9090/v1/chat/completions -H "Content-Type: application/json" -d '{"model": "模型ID来自上一步", "messages": [{"role": "user", "content": "Hello"}]}'`

Expected:
- Exit code: 0
- Response contains: `"choices"` 和 `"message"`、`"content"`
- 有实际的 AI 回复内容

- [ ] **Step 3: 验证流式聊天**

Run: `curl -N -X POST http://localhost:9090/v1/chat/completions -H "Content-Type: application/json" -d '{"model": "模型ID", "messages": [{"role": "user", "content": "1+1=?"}], "stream": true}'`

Expected:
- SSE 格式输出：`data: {"id":"chatcmpl-...","object":"chat.completion.chunk",...}`
- 最终收到 `data: [DONE]`
- 能看到逐字输出

---

## 质量门禁

- [ ] 编译通过（`npx tsc --noEmit` 无错误）
- [ ] 代理正常启动并监听 9090 端口
- [ ] OAuth 登录流程完整（send-code → 用户收短信 → verify）
- [ ] `GET /v1/models` 返回模型列表
- [ ] `POST /v1/chat/completions` 返回 AI 回复（非 mock）
- [ ] 流式模式正常工作，SSE 格式正确