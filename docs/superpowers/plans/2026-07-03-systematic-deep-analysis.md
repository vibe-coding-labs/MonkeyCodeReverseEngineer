# MonkeyCode 逆向工程 — 系统性深入分析计划

**Goal:** 对当前文档的薄弱和缺失维度进行系统性深入分析，每个维度输出详实的 Markdown 报告，包含实际逆向分析代码示例

**Architecture:** 按 P0→P1→P2→P3 优先级顺序执行。每个维度完成后更新 INDEX.md 和 MASTER-CHECKLIST.md

**Scope:** Large (8 个维度)
**Risk:** Low

---

### Task 1: 扩增 08-analysis-rounds 各轮次报告

**Depends on:** None
**Files:**
- Modify: `docs/08-analysis-rounds/rounds/round-01-to-06.md`
- Modify: `docs/08-analysis-rounds/rounds/round-07-to-12.md`
- Modify: `docs/08-analysis-rounds/rounds/round-13-to-18.md`
- Modify: `docs/08-analysis-rounds/summary-report.md`

将每轮从当前 41-63L/0 代码块扩增到 200+L/10+ 代码块，补充：
- 每轮的实际代码片段（Go/TS/Python 源码引用）
- 关键发现的技术细节和数据结构
- ACP 事件帧示例
- OAuth HTTP 请求/响应示例

### Task 2: 扩增 10-appendices/05-code-exhibits

**Depends on:** None
**Files:**
- Modify: `docs/10-appendices/05-code-exhibits.md`

从 153L/4 代码块扩增到 300+L/20+ 代码块，新增：
- ACP 事件处理全流程代码
- WebSocket 连接和心跳处理
- 错误处理与重试逻辑
- 模型发现 Pipeline

### Task 3: 代理层错误处理与重试策略深入分析

**Depends on:** None
**Files:**
- Create: `docs/07-proxy/09-error-handling-deep.md`

### Task 4: Conversation Manager 完整生命周期源码分析

**Depends on:** None
**Files:**
- Create: `docs/04-websocket/07-conversation-lifecycle.md`

### Task 5: MonkeyCode 代理安全加固分析

**Depends on:** None
**Files:**
- Create: `docs/09-security/02-proxy-security-analysis.md`

### Task 6: Model Discovery Pipeline 全景

**Depends on:** None
**Files:**
- Create: `docs/03-llm/07-model-discovery-pipeline.md`

### Task 7-8: 附录扩增（glossary 等）

**Depends on:** None
**Files:**
- Modify: `docs/10-appendices/04-glossary.md`
- Modify: 其他附录文件