# 安全分析

> **所属位置:** 第五篇·研究记录 — 安全漏洞与加固分析
> **阅读目标:** 了解已发现的安全问题和加固策略

```mermaid
flowchart LR
    subgraph Found["已发现的漏洞"]
        TLS["TLS 绕过<br/>SCaptcha"]
        REPLAY["授权码重放"]
        SMS["短信轰炸"]
    end
    subgraph Risk["代理安全风险"]
        A1["管理端未鉴权"]
        A2["Cookie 日志泄露"]
    end
    Found -->|影响百智云 OAuth| BZ["百智云登录"]
    Risk -->|影响代理层| Proxy["MonkeyCode 代理"]
```

| # | 文件 | 内容 | 行数 |
|---|------|------|------|
| 1 | [百智云安全报告](baizhi-security-report.md) | SCaptcha 漏洞（TLS 绕过/授权码重放/短信轰炸） | 268L |
| 2 | [代理安全加固](02-proxy-security-analysis.md) | OWASP Top 10 自评、管理端点认证、CSRF | 354L |