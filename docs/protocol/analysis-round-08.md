# 逆向分析轮次 08 — 测试分析与验证

> **时间:** 2026-05-30 02:25 UTC+8
> **聚焦:** 测试分析、验证准备

---

## 1. 测试环境状态

### 1.1 代码状态

```
$ npm run build
> tsc
✅ 编译成功，无错误
```

**Git 状态**：
- 5 个文件修改
- 2 个新文件（conversation-manager.ts, test-proxy.sh）
- 7 个分析报告文档

### 1.2 测试环境要求

| 要求 | 状态 | 说明 |
|------|------|------|
| Node.js | ✅ | 已安装 |
| TypeScript | ✅ | 已编译 |
| Session Cookie | ⏳ | 需要实际账号 |
| Image ID | ⏳ | 需要从浏览器获取 |
| 网络连接 | ✅ | 可访问 monkeycode-ai.com |

---

## 2. 测试执行计划

### 2.1 测试前准备

1. **获取 Session Cookie**：
   ```bash
   # 从浏览器 DevTools 获取
   # Application → Cookies → monkeycode_ai_session
   export MONKEYCODE_SESSION_COOKIE="your-session-cookie"
   ```

2. **获取 Image ID**：
   ```bash
   # 从浏览器 DevTools 获取
   # Network → POST /api/v1/users/tasks → image_id
   export MONKEYCODE_IMAGE_ID="your-image-id"
   ```

3. **启动代理**：
   ```bash
   cd proxy
   npm run dev
   ```

### 2.2 测试执行

```bash
# 运行测试脚本
./test-proxy.sh http://localhost:9090

# 或手动测试
curl http://localhost:9090/health
curl http://localhost:9090/v1/models
```

---

## 3. 预期测试结果

### 3.1 健康检查测试

**预期**：
```json
{
  "status": "ok",
  "uptime": 123.456,
  "pool": {"mode": "single"}
}
```

**可能问题**：
- 端口被占用
- 代理未启动

### 3.2 模型列表测试

**预期**：
```json
{
  "object": "list",
  "data": [
    {
      "id": "monkeycode/OpenAI/gpt-4o",
      "object": "model",
      "created": 1715299200,
      "owned_by": "OpenAI"
    }
  ]
}
```

**可能问题**：
- Session Cookie 无效
- 网络连接问题
- 账号无可用模型

### 3.3 Chat Completions 测试

**预期**：
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello!"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
}
```

**可能问题**：
- Image ID 无效
- 任务创建失败
- WebSocket 连接超时

### 3.4 多轮对话测试

**预期**：
1. 第一轮：返回 `X-Conversation-Id` header
2. 第二轮：Agent 保持上下文（回答 "42"）

**可能问题**：
- Conversation ID 未返回
- Agent 上下文丢失
- WebSocket 连接断开

---

## 4. 测试结果分析

### 4.1 成功场景

如果所有测试通过：
- ✅ 代理功能完整
- ✅ 多轮对话支持正常
- ✅ 错误处理正确
- ✅ 可以提交代码

### 4.2 失败场景

如果测试失败：
- ❌ 需要修复问题
- ❌ 重新运行测试
- ❌ 更新文档

---

## 5. 代码提交准备

### 5.1 待提交文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/conversation-manager.ts` | 新建 | 对话管理器 |
| `src/api-routes.ts` | 修改 | 支持 conversation_id |
| `src/server.ts` | 修改 | 初始化 ConversationManager |
| `src/task-runner.ts` | 修改 | ACP 事件处理 |
| `src/types.ts` | 修改 | 新增类型定义 |
| `test-proxy.sh` | 新建 | 测试脚本 |

### 5.2 提交信息

```
feat(proxy): add multi-turn conversation support and ACP event handling

- Add ConversationManager for managing conversation lifecycle
- Support conversation_id parameter for reusing tasks/VMs
- Handle tool_call_update, plan, and available_commands_update events
- Fix non-stream usage bug (accumulate chunk.usage)
- Add test script for verifying proxy functionality
- Update types.ts with conversation-related types

Closes #xxx
```

---

## 6. 下轮分析重点

### 优先级 P0

1. **运行测试脚本**: 验证所有功能
2. **修复测试失败**: 处理发现的问题
3. **提交代码**: 保存所有更改

### 优先级 P1

4. **性能测试**: 测量响应时间
5. **稳定性测试**: 长时间运行
6. **并发测试**: 多客户端访问

### 优先级 P2

7. **文档更新**: 更新 README
8. **部署测试**: 生产环境测试
9. **监控告警**: 添加监控

---

## 7. 产出文件

- `docs/protocol/analysis-round-08.md` — 本报告

---

## 8. 相关文件索引

| 文件 | 用途 |
|------|------|
| `proxy/test-proxy.sh` | 测试脚本 |
| `proxy/src/server.ts` | 服务器入口 |
| `proxy/src/api-routes.ts` | API 路由 |
| `proxy/src/conversation-manager.ts` | 对话管理器 |
