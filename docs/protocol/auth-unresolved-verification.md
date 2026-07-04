> ⚠️ **此文件为原始分析档案** — 内容已被 docs/ 下结构化章节覆盖。详见 [docs/protocol/README.md](./README.md)。

# MonkeyCode 认证协议未决问题验证报告

> 基于 chaitin/MonkeyCode 开源源码深度分析
> 分析日期: 2026-05-12
> 验证方法: 源码级代码追踪（非实测）

---

## 1. 密码传输格式（P0）— 已确认

### 结论：前端传明文，后端用 bcrypt 验证

**证据链：**

1. **前端代码** (`frontend/src/pages/login.tsx:85-88`)：
   ```tsx
   await apiRequest('v1UsersPasswordLoginCreate', {
     email: userEmail.trim(),
     password: userPassword.trim(),  // 直接传用户输入的明文
     captcha_token: token,
   })
   ```

2. **前端 apiRequest** (`frontend/src/utils/requestUtils.ts:6-12`)：
   - 无任何拦截器或中间件对 password 字段做 MD5 转换
   - 直接透传到 Swagger 生成的 API 客户端

3. **前端无 MD5 依赖**：
   - `grep -rn "md5\|MD5\|CryptoJS\|hash\|digest" frontend/src/` 结果中无任何 MD5 相关代码
   - 唯一的 `crypto` 引用是 `crypto.randomUUID()` 用于 WebSocket 连接 ID

4. **后端密码验证** (`backend/biz/user/repo/user.go:77`)：
   ```go
   err = crypto.VerifyPassword(usr.Password, req.Password)
   ```

5. **后端 VerifyPassword 实现** (`backend/pkg/crypto/bcrypt.go:22-24`)：
   ```go
   func VerifyPassword(dbPassword, password string) error {
     return bcrypt.CompareHashAndPassword([]byte(dbPassword), []byte(password))
   }
   ```
   - 数据库存储 bcrypt 哈希
   - 直接将前端传来的明文与 bcrypt 哈希比较
   - **无 MD5 中间步骤**

6. **后端 HashPassword 实现** (`backend/pkg/crypto/bcrypt.go:10-18`)：
   ```go
   func HashPassword(password string) (string, error) {
     if len(password) > 32 {
       return "", errors.New("password must be less than 32 characters")
     }
     hashedBytes, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
     return string(hashedBytes), nil
   }
   ```
   - 密码长度限制 32 字符（明文长度，非 MD5 长度）

### 注释错误说明

以下注释标注"MD5加密后的值"是**错误的/过时的**：

| 位置 | 错误注释 |
|------|---------|
| `domain/team.go:209` | `Password string // 用户密码（MD5加密后的值）` |
| `biz/team/handler/http/v1/user.go:84` | `@Description 团队用户登录，password 字段需要传 MD5 加密后的值` |
| `frontend/src/api/Api.ts:1438` | `/** 用户密码（MD5加密后的值） */` |

这些注释是从 Swagger 自动生成的，源头是 `domain/team.go` 中的错误注释。

### 对账号池的影响

| 项目 | 结论 |
|------|------|
| 账号池存储 | 存储明文密码 |
| 登录请求 | 直接传明文 |
| 安全性 | 较差（需存明文），但这是 MonkeyCode 的设计选择 |
| 无需 MD5 | 前端和后端都不做 MD5 |

---

## 2. 团队管理员 Cookie 名称（P2）— 已确认

### 结论：源码硬编码，非 `sl-session`

**源码常量** (`backend/consts/auth.go:4-5`)：
```go
const (
  MonkeyCodeAISession     = "monkeycode_ai_session"
  MonkeyCodeAITeamSession = "monkeycode_ai_team_session"
)
```

**使用位置：**

| Cookie 名称 | 使用位置 | 用途 |
|------------|---------|------|
| `monkeycode_ai_session` | `biz/user/handler/v1/auth.go:96` | 用户密码登录 Save |
| `monkeycode_ai_session` | `middleware/auth.go:93` | Auth() 中间件读取 |
| `monkeycode_ai_session` | `middleware/auth.go:116` | Check() 中间件读取 |
| `monkeycode_ai_team_session` | `biz/team/handler/http/v1/user.go:106` | 团队登录 Save |
| `monkeycode_ai_team_session` | `middleware/auth.go:139` | TeamAuth() 中间件读取 |
| `monkeycode_ai_team_session` | `middleware/auth.go:168` | TeamAuthCheck() 中间件读取 |

**关键发现：**

1. Cookie 名称是**硬编码常量**，不是从配置文件读取
2. `config.go` 中没有 `session.cookie_name` 等配置项
3. 环境变量 `MCAI_SESSION_*` 无法覆盖（因为代码直接引用 `consts.MonkeyCodeAISession`）
4. **之前文档中写的 `sl-session` 是错误的**，正确名称是 `monkeycode_ai_session`

### 对账号池的影响

| 项目 | 结论 |
|------|------|
| 用户登录 Cookie | `monkeycode_ai_session` |
| 团队登录 Cookie | `monkeycode_ai_team_session` |
| 请求头注入 | `Cookie: monkeycode_ai_session={uuid}` |
| 不可配置 | 硬编码在源码中，线上环境不会改变 |

---

## 3. Session TTL（P1）— 已确认

### 结论：默认 30 天，可配置

**配置结构** (`backend/config/config.go:167-169`)：
```go
type Session struct {
  ExpireDay int `mapstructure:"expire_day"`
}
```

**默认值** (`backend/config/config.go:216`)：
```go
v.SetDefault("session.expire_day", 30)
```

**TTL 计算** (`backend/pkg/session/session.go:36-38`)：
```go
func (s *Session) expire() time.Duration {
  return time.Duration(s.cfg.Session.ExpireDay) * 24 * time.Hour
}
```

**配置方式：**

| 方式 | 配置项 | 示例 |
|------|--------|------|
| YAML 配置文件 | `session.expire_day: 30` | `config.yaml` |
| 环境变量 | `MCAI_SESSION_EXPIRE_DAY=30` | Docker/K8s 环境变量 |
| 默认值 | 30 | 代码内置 |

**Session 保存时设置 TTL** (`backend/pkg/session/session.go:49-77`)：
```go
func (s *Session) Save(c echo.Context, name string, uid uuid.UUID, data any) (string, error) {
  expire := s.expire()  // 30 * 24 * time.Hour
  // ...
  pipe.HSet(ctx, key, cookie, string(b))
  pipe.Expire(ctx, key, expire)  // 设置 Hash key 的 TTL
  pipe.Set(ctx, lookupKey(name, cookie), uid.String(), expire)  // 设置 lookup key 的 TTL
  // ...
  c.SetCookie(&http.Cookie{
    Name:     name,
    Value:    cookie,
    MaxAge:   int(expire.Seconds()),  // Cookie 的 MaxAge 也设为 30 天
    // ...
  })
}
```

### 对账号池的影响

| 项目 | 结论 |
|------|------|
| Session 有效期 | 默认 30 天 |
| 保活间隔 | 30 天内不需要保活（但建议仍定期检查） |
| Cookie MaxAge | 与 Session TTL 一致，30 天 |
| 线上可能不同 | 需确认线上 `MCAI_SESSION_EXPIRE_DAY` 环境变量值 |

---

## 4. 并发检测（P1）— 已确认

### 结论：开源源码中无任何并发检测/限流逻辑

**搜索结果：**

1. **Rate Limiting** — `grep -rn "rate\|limit\|throttle\|abuse\|concurrent"` 结果：
   - 仅 `biz/host/handler/v1/internal_auth.go` 有 Redis SetNX 用于 VM 回收防重
   - 无 API 级别的限流中间件

2. **中间件** — `backend/middleware/` 目录仅包含：
   - `auth.go` — 认证中间件（Auth/Check/TeamAuth/TeamAdminAuth）
   - `target_active.go` — 活跃追踪（仅记录时间+IP，无限流）
   - `audit.go` — 审计日志

3. **TargetActive 中间件** (`backend/middleware/target_active.go:29-52`)：
   ```go
   func (t *TargetActiveMiddleware) TargetActive() echo.MiddlewareFunc {
     return func(next echo.HandlerFunc) echo.HandlerFunc {
       return func(c echo.Context) error {
         user := GetUser(c)
         if user != nil && t.activeRepo != nil {
           // 仅记录活跃时间和 IP，无限流逻辑
           t.activeRepo.RecordActiveRecord(ctx, consts.UserActiveKey, user.ID.String(), time.Now())
           t.activeRepo.RecordActiveIP(ctx, fmt.Sprintf("mcai:user:active:ip:%s", user.ID.String()), c.RealIP())
         }
         return next(c)
       }
     }
   }
   ```

4. **Session 并发** — `session.Get()` 不做任何并发检查，直接从 Redis 读取

### 对账号池的影响

| 项目 | 结论 |
|------|------|
| 开源代码无并发检测 | 同一 session 可并发使用，无限制 |
| 同一用户多 session | 支持（Redis Hash 多 field 设计） |
| 生产环境可能有 | 闭源组件可能添加了限流（无法确认） |
| 建议 | 保守起见，每账号限制 2 session，每 session QPS < 5 |

---

## 5. Status 端点是否刷新 TTL（P2）— 已确认

### 结论：不刷新 Redis TTL

**证据链：**

1. **Status 端点处理** (`biz/user/handler/v1/auth.go:171-192`)：
   ```go
   func (h *AuthHandler) Status(c *web.Context) error {
     user := middleware.GetUser(c)  // 从 context 获取用户
     if user == nil {
       return errcode.ErrUnauthorized
     }
     // 仅返回用户信息，不调用 session.Save()
     teamUser, err := h.usecase.GetUserWithTeams(c.Request().Context(), user.ID)
     return c.Success(teamUser)
   }
   ```
   - Status 不调用 `session.Save()`
   - 不调用任何 Redis EXPIRE 命令

2. **session.Get() 实现** (`backend/pkg/session/session.go:80-105`)：
   ```go
   func Get[T any](s *Session, c echo.Context, name string) (T, error) {
     // 通过 lookup key 反查 uid
     uid, err := s.rdb.Get(ctx, lookupKey(name, ck.Value)).Result()
     // 从 Hash 中读取 session 数据
     val, err := s.rdb.HGet(ctx, fmt.Sprintf("%s:%s", name, uid), ck.Value).Result()
     // 反序列化返回
     var t T
     json.Unmarshal([]byte(val), &t)
     return t, nil
   }
   ```
   - `rdb.Get()` — 读取 lookup key，**不刷新 TTL**
   - `rdb.HGet()` — 读取 Hash field，**不刷新 TTL**
   - Redis 的 GET 和 HGET 命令不会重置 key 的 TTL

3. **Auth 中间件** (`middleware/auth.go:88-108`)：
   ```go
   func (a *AuthMiddleware) Auth() echo.MiddlewareFunc {
     return func(next echo.HandlerFunc) echo.HandlerFunc {
       return func(c echo.Context) error {
         user, err := session.Get[*domain.User](a.Session, c, consts.MonkeyCodeAISession)
         // 仅读取，不刷新
         SetUser(c, user)
         return next(c)
       }
     }
   }
   ```

4. **TargetActive 中间件** — 仅记录活跃时间到独立 key (`monkeycode_ai:user:active`)，不影响 session TTL

### Redis TTL 行为

| Redis 命令 | 是否刷新 TTL | session.Get() 使用 |
|-----------|-------------|-------------------|
| `GET` | 否 | ✅ 读取 lookup key |
| `HGET` | 否 | ✅ 读取 Hash field |
| `HSET` | 否（除非 key 不存在） | ❌ 未使用 |
| `EXPIRE` | 是 | ❌ 未使用 |
| `TTL` | 否（仅查询） | ❌ 未使用 |

### 对账号池的影响

| 项目 | 结论 |
|------|------|
| Status 不刷新 TTL | 调用 `/api/v1/users/status` 不能延长 session 有效期 |
| 任何 API 调用都不刷新 TTL | 整个请求链中无 EXPIRE 调用 |
| Session 有效期固定 | 从 Save 时设置，30 天后过期，无法续期 |
| 保活策略无效 | 定期调用 status 只能**检测**有效性，不能**延长**有效期 |
| 唯一续期方式 | 重新登录获取新 session |

---

## 6. 修正汇总

### 6.1 Cookie 名称修正

之前所有文档中写的 `sl-session` 是**错误的**，正确名称：

| 之前（错误） | 修正后（正确） |
|------------|--------------|
| `sl-session` | `monkeycode_ai_session` |
| `monkeycode_ai_team_session` | `monkeycode_ai_team_session`（这个是对的） |

### 6.2 密码格式修正

之前文档中"密码格式未确认"的状态，现在确认：

| 之前 | 修正后 |
|------|--------|
| 可能是 MD5 或明文 | **确定是明文**，注释中的 MD5 是错误注释 |
| 建议存储明文，登录时决定 | **确定存储明文，直接传明文** |

### 6.3 保活策略修正

之前文档建议"每 5 分钟调用 status 保活"，现在确认：

| 之前 | 修正后 |
|------|--------|
| status 调用可保活/刷新 TTL | **status 不刷新 TTL**，仅检测有效性 |
| 保活可延长 session | **无法延长**，session 30 天后必定过期 |
| 保活间隔 5 分钟 | 改为**有效性检测**，间隔可延长到 1 小时 |

### 6.4 Session TTL 修正

| 之前 | 修正后 |
|------|--------|
| TTL 未知，需实测 | **默认 30 天**，可通过 `MCAI_SESSION_EXPIRE_DAY` 配置 |

---

## 7. 账号池协议更新建议

基于以上验证结果，账号池协议需要以下关键更新：

1. **Cookie 名称**：所有 `sl-session` 替换为 `monkeycode_ai_session`
2. **密码存储**：存明文，登录时直接传明文（无需 MD5）
3. **Session 有效期**：30 天，到期必须重新登录
4. **保活策略**：改为"有效性检测"而非"TTL 续期"
5. **并发安全**：开源代码无限制，但建议保守使用
6. **Session 轮换**：过期前 1-2 天主动重新登录获取新 session
