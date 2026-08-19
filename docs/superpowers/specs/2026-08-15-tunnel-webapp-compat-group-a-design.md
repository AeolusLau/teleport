# 隧道 Web 应用兼容性 A 组 · 客户端设计

- 日期:2026-08-15(经三轮对抗评审修订,见 §9)
- 分支:`spec/tunnel-webapp-compat`(两仓成对)
- 本仓角色:**客户端**(Chromium overlay)
- 对侧 spec:`../fairyland/docs/superpowers/specs/2026-08-15-tunnel-webapp-compat-group-a-design.md`
- 判定来源:`docs/research/2026-08-14-tunnel-webapp-compat-assessment.md`(11 条问题 `C-1`…`C-11`)

---

## 0. 这份 spec 的高度(重要)

三轮对抗评审的结论很一致:**问题判定与设计决策每轮都站得住,而我写下的「具体怎么实现」每轮都被真源码推翻**——第三轮里我加的那道 host 安全校验被一条 `corp.example;.com` 直接绕过,我引来支撑「第二个唤醒信号」的文档注释被截断处正好反转了语义。

所以本文**只承载三样东西**:

1. **问题与根因**(已被三轮独立核验);
2. **决策与其理由**;
3. **跨仓契约**。

**它不承载实现机制。** 凡是「用哪个 API、判据怎么写、patch 改哪几个文件」一律**下沉到 plan**,并且在 plan 里一律写成「**先验证、再实现**」的任务对。理由是实测出来的:这类结论读代码读不对,编译器和测试一次就能给出答案。plan 里凡是引用上游行为的任务,第一步都必须是验证步。

---

## 1. A 组是什么

A 组是「**已注册的应用本应可达却不可达**」那一类。经三轮收敛,**只剩两件事**:

| # | 事项 | 吃掉 | 主责仓 |
|---|---|---|---|
| 1 | 隧道路由白名单从证书策略里独立出来,改由 bind 响应下发 | `C-2`、`C-11`、`C-5` 粒度半 | 两仓 |
| 2 | `teleport://tunnel` 诊断页 + 手动重绑 | `C-10` | 本仓 |

### 拆出去的两项

| 编号 | 原因 | 去向 |
|---|---|---|
| `C-1` 纯 HTTP 应用的 WebSocket | 看着是「放行一个方法」,实为隧道内 L7 承载的完整设计题(inner Host 规范化、gate 2 是否重跑、升级后的可见性边界、越界缓冲字节、内层 server 生命周期、隧道内归因) | `TD-TUNNEL-HTTP-ORIGIN-WEBSOCKET`(fairyland) |
| `C-7` 生命周期与超时 | 看着是「改个常量」,实为数据面容量设计题(**四条腿**不是两条、`AcceptBacklog` 是阻塞信号量、`StreamOpenTimeout` 超时会**关掉整个连接器会话**、body-idle 截止会打掉今天可用的 `wss://`、Chrome 每页开数十条流) | `TD-TUNNEL-DATAPLANE-LIFECYCLE`(fairyland) |

两条 TD 都完整收录了三轮评审挖出的设计面,立项时不必重新发现。

**拆 `C-1` 还解掉一个耦合**:它会让 http origin 的 CONNECT 恒返回 **200**、失败全挪进隧道内部,诊断页不仅看不到、还会**显示成功**——即 `C-1` 会让 `C-10` **报假**。两者必须分批。

---

## 2. 统领不变量

> **客户端路由表是「往哪送」的提示,不是「能不能访问」的判定。授权真值恒在 edge。**

由此:**过度捕获无害且必要**(客户端按 host 捕获,未注册端口被送到 edge 并产生拒绝记录,喂给 origin discovery;收窄会让漏配走 DIRECT、静默失败、不留记录);**陈旧可容忍**(多一条由 edge 实时拒,少一条等下一个刷新周期)。

**这条不变量只覆盖授权,不覆盖保密**,因此不用于论证作用域。

### 作用域:租户全量(与今天一致)

第一轮评审断言「今天的 `AutoSelectCertificateForUrls` 是 USER scope、按用户已授权的应用树编译」,我据此改成 per-subject。**第二、三轮独立核验推翻**:策略 blob 按 **tenant** 编译(`webapp_repo.go` 的 `withRecompile(ctx, tenantID, …)` → `webapp.Compile` 不收身份参数)、按 **tenant** 下发(`policy_repo.go` 的 `PoliciesFor` 把 DM token 解析到 tenant),`policy_assignments` 的唯一索引是 `(tenant_id, scope, policy_type)`——**per-person 策略在 schema 上不可表达**。`ScopeUser` 过滤的是**策略键**,不是人。

> 精确措辞(第三轮要求):该路径上**没有对策略值集的 per-person 过滤**;唯一的 per-person 读取是填 `PolicyData` 信封的 `username` / `domain`,从不触碰 `Policies`。不要写成「全程无 person id」——下一个人 grep `user_registrations` 会以为更正错了。

**决策:维持租户全量,收紧单独立项**(`TD-TUNNEL-ROUTING-TABLE-PER-SUBJECT`)。理由两条:

1. 它要修的「回退」不存在——租户全量就是今天的行为;
2. **按 `Route.ScopePath` 逐条 `authz.Check` 并不等价于 gate 4 的判定**。gate 4 判的是 `authzcache` 收敛后的候选集(**primary-only 塌缩**有意排除 auxiliary 的 grant,加同租户通配行合并,加对未知 `Kind` / 空 `Scheme` / 双 primary 的 fail-closed)。照 `ScopePath` 过滤会**新造一类**「页面显示可路由、edge 恒拒」的条目。

> 第二轮曾给出第三条理由(「只收紧 bind 一条通道拿不到该性质,因为策略通道仍在下发同一份清单」)。**第三轮证伪并删除**:默认配置下(未配浏览访问控制、未配 DevTools 策略)`URLAllowlist` 与 DevTools 键都被 `setIfNonEmpty` 整键删除,而本组又删掉 per-app AutoSelect 条目——**A 组之后 bind 响应是默认部署下的唯一载体**。这不改变结论(理由 1、2 足以支撑),但必须如实记:A 组**收敛**了暴露面,同时**新增了一个渲染好的可读页面**。该事实已写进 `TD-TUNNEL-ROUTING-TABLE-PER-SUBJECT`。

---

## 3. 决策

### 3.1 路由表来源:删除策略推导,改由 bind 响应下发

**`C-2` 的根因**(三轮核验一致):`DeriveRoutableOrigins` 用 `GURL` 解析 content-settings pattern。对 `https://[*.]corp.example:443`,URL 解析器能正常切出 host 与 port,host 是带方括号的 `[*.]corp.example`(`*` 被字符表标为 `kEsc` → `%2A`);随后 `CanonicalizeIPAddress` 因 host 首尾不是 `[`…`]` 而不进入 IPv6 解析,回落到「扫描 IPv6 专属字符」分支,扫到 `[` 即置 `CanonHostInfo::BROKEN`,`is_valid()` 为 false、条目被跳过。**通配 origin 因此从不进入白名单。**

**决策**:**删除**这条推导路径,不修 `[*.]` 解析。系统处于开发期、零真实用户,**不留向后兼容回退**。

**必须满足的性质**(具体判据由 plan 从源码推导并验证):

| # | 性质 | 已知约束 |
|---|---|---|
| P1 | **通配条目必须同时覆盖根域与子域** | 匹配是 `base::MatchPattern` glob,`*.corp.example` **匹配不到 `corp.example` 本身`**。只发一条会把「通配域整个丢失」换成「通配域的根丢失」。三轮核验一致 |
| P2 | **edge / gate 主机永不进入路由表** | 含**被通配条目覆盖**的情形。否则 bind 自己的 POST 被路由进 edge → 隧道自锁。glob 的 `*` **跨点**,故任何位于 D 之上的通配都会捕获 gate,把 gate 往深处搬不能规避 |
| P3 | **恶意/畸形条目不得转化为规则注入** | `AddRuleFromString` 是**一套语法**不是主机名:`/` → IP 段规则、`:` → 端口规则、`://` → scheme 规则、`<local>` / `<-loopback>` → 特殊语法(后者关掉全部隐式 loopback 保护)。**更关键**:`ProxyHostMatchingRules::operator=` 的实现是 `ParseFromString(rhs.ToString())`——**每次拷贝都是字符串往返**,`ToString` 用 `;` 拼、`ParseFromString` 按 `,;` 切,所以一个含 `;` 的 host 会在**首次拷贝时裂成两条规则**,前导点片段还会被提升为通配 |
| P4 | **被拒条目必须可见** | 静默丢弃正是 `C-2`。任何 skip 都要带原因进诊断页 |
| P5 | **不可路由的合法 origin 必须被发现,而不是静默丢弃** | 已知一例:IPv6 origin 经 `SplitHostPort` 剥掉方括号后上 wire,客户端多半会拒——**edge 路由得好好的,客户端永不路由**。plan 须定 IPv6 的 wire 编码,或明确不支持并计入服务端的 drop 计数 |
| P6 | **去重时 `include_subdomains` 取并集** | 两个 app 合法共享一个 host 而 flag 取值不同是受支持形态(device-manager 已有 `unionWildcardByHost` 先例);先到先得会让 digest 抖动并丢子域 |

**信任域说明(决策依据,不是实现)**:旧载体走受签名链保护的云策略,新载体是 bind 响应体,`OnTunnelToken` 只做 JSON 解析、**无签名校验**,信任仅来自 gate 的 TLS 与设备证书 mTLS。P3 是这次降级的**粗粒度补偿**,不是策略引擎;彻底解是给 bind 响应加签,登记为 `TD-TUNNEL-BIND-RESPONSE-UNSIGNED`。

**捕获粒度**:按 **host** 捕获(§2 的过度捕获论证),协议里保留 port 供诊断与将来收窄。降级只发生在一处,便于定位。

### 3.2 启动竞态:不设前置判据,让失败可被唤醒

**竞态是什么**(三轮核验一致,这是本节唯一可信的部分):bind 请求的身份**只有设备证书 mTLS**;选证走 `SelectClientCertificate`,而 bind 是浏览器进程的 `SimpleURLLoader` 请求、**没有 WebContents**。恰好一张 matching → 自动选中不弹框(今天能跑通的路径,依赖 AutoSelect 策略里那条 gate 条目);**零张 matching → 落到 picker 分支 → `web_contents == nullptr` → 直接 return 不调 delegate**(注释:*"implicitly calls to cancel the request"*)→ 握手失败 → **bind 失败**。

所以那条策略链有两个职责:当路由表来源(本组拆掉的),以及**让 bind 自己的证书能被自动出示**(拆不掉)。且证书**供给本身**是第二个异步前置条件。

**决策**:**不设前置判据**,把失败做成可被唤醒的——`Start()` 只门控在能可靠判定的条件上,失败走既有退避,并由「前置条件就绪」的信号短路重试。

**理由**:任何判据都只是代理指标(两个异步前置,判据即便精确也不充分),而唤醒模型不依赖判据正确。

**plan 必须先验证再实现的点**(第三轮证明我在这里连续错了两次):

- 第二轮我说「只留通知即可」——错:`PrefChangeRegistrar` **不对初始值触发**,今天的代码靠**读值**来补,只留通知严格更弱;
- 第三轮我说「证书供给有现成回调 `GetManagedIdentity`」——**也错**:我引的注释被截断,完整语义是「策略未启用时**同步**跑 `std::nullopt` 并返回」,此后不再触发。**它是 request/response,不是 observer**,而且恰好在它要解决的那个冷启动窗口里失效。

**所以 plan 的第一步是:枚举「bind 前置条件就绪」的可用信号并逐个验证其触发语义**(包括是否同步回调、是否可重入、测试环境下是否可获得),然后再定唤醒通道。同时必须定义 idle / in-flight / in-flight+pending 的完整状态机与自动唤醒的最小间隔——`BeginBind()` 今天**没有 in-flight 守卫**,新 loader 赋值会取消在途请求。

### 3.3 `teleport://tunnel` 诊断页

**动机**:今天派生出的 `routable_origins` 与实际推给网络栈的 config **唯一可观测性是 `VLOG(1)`**(要带 `--v=1` 重启),也没有手动重绑入口。而 **`chrome://policy` 对 `C-2` 完全没起作用**——那条策略在 `chrome://policy` 里显示为已下发、已应用、值正确,客户端却在**派生**那一步丢了它。**本页展示的一律是派生后的实际状态。**

**必须展示**(信息需求,字段形状由 plan 定):bind 状态与最近成功/失败时刻及原因;令牌到期时刻(**来自 wire 的剩余秒数,不解析 JWT**——客户端有「cnf 是不透明 bearer token」的既有不变量);下次刷新时刻;**实际生效的 origin 列表**;**被跳过的条目及原因**(P4);服务端侧的 stale / truncated / dropped 标记;config 是否已推给网络栈;最近若干次 CONNECT 的结果。

**必须提供**:手动重新绑定,带最小间隔限流(否则任意用户就有了一个清零指数退避的按钮,而 mTLS 握手是服务端最贵的操作之一)。

**已知约束(plan 须处理)**:

- **`blocked` 是服务端逐行标记,不是 edge 终判**——edge 的判定是候选集收敛后的**聚合**。页面文案须表述为「服务端标记该地址无路由行」,**不得**表述为「访问必定失败」;
- **CONNECT 结果需要按代理链过滤**:`NetworkServiceProxyDelegate` 在这条通知上**没有** `IsInProxyConfig` 门控(它的两个兄弟方法都有),不过滤就会把该 network context 上**任何**代理链的 CONNECT 当成隧道结果展示——一个以「消灭看不见的派生结果」为目的的页面,第一版就会展示无关数据;
- **WebUI 接线不能简单「沿用 enroll」**:`teleport_enroll` 的 source_set 刻意**不依赖 `//chrome/browser`**,而 `TeleportTunnelService` 是经 patch 编进 `//chrome/browser` 的——tunnel 页 handler 一旦 include 它就编不过。plan 须在两条路里选一条并说明。

### 3.4 CONNECT 归因:付一处最小上游 patch

**问题**:CONNECT 结果的通知**不带目的地**(只有代理链与链内下标),连关联 id 都拼不出来。所以状态码拿得到、**是哪个 origin 拿不到**——而 403 的排障价值几乎全在后者。

**决策**:**付这个 patch**(用户裁定:必须要有归因)。

**约束**:

1. **不得破坏其它实现者**。`net::ProxyDelegate` 侧用**非破坏性新增**(旧方法保留,新方法带默认实现转发),这样 mock / fake / test delegate 与全部上游单测调用点一个不用改——`be430f1` 就是这个形状,先例可抄;
2. **mojom 侧的破坏性改动可以接受**,但 plan 必须先枚举**全部**实现者并确认它们都在我们构建里;
3. **Cronet 与 Java 不在范围**:实测我们的 `out/mac/arm64/dev` 中 **cronet 目标文件数为零**,`cronet_common` 是独立 source_set、`chrome` 不依赖它,Java 部分整个在 `is_android` 下;
4. **每多 patch 一个上游文件,就是下次里程碑升级多一个冲突点**——M148→M151 的账刚付过。patch 面最小化本身是一条决策依据。

**plan 必须先验证**:新方法的**完整签名**(第三轮抓到我漏了异步回调参数——该接口的契约是返回 `ERR_IO_PENDING` 表示稍后回调,漏掉它默认实现就转发不出去);每个调用点是否真有目的地可传(已知一处需要从上一帧取);以及 mojom 实现者的真实清单与路径。

---

## 4. 失败模式(决策级)

| 场景 | 决策 |
|---|---|
| 服务端未下发路由表(字段缺失或 `null`) | 路由表置空、不路由;页面明示「服务端未下发」。契约要求空结果发 `[]`,故 `null` 是协议违例 |
| 路由表为**空数组** | 与上一行**区分**:页面表述为「服务端下发了空表」,**不推断原因**(冷启动与「租户确实没有应用」在 wire 上不可区分) |
| 条目未过校验 | 跳过该条、其余生效,进「被跳过」列表(P4) |
| bind / 续期失败 | 既有退避;页面显示时刻、原因、下次重试;可手动重绑 |
| 前置条件未就绪导致选证被取消 | bind 失败 → 退避;就绪信号到达即短路重试(§3.2) |
| **网络服务重启** | 重推谓词是 **`!cnf_token_.empty()`**,**不是** `have_pushed_config_`。现有代码对此有明确注释:首次 PushConfig 若在 receiver 绑定前跑过会静默 no-op 并把 `have_pushed_config_` 留为 false,旧写法因而永不重推。`have_pushed_config_` **保留**作为页面「config 是否已推」的后端,**永不**作为重推谓词 |
| 令牌过期且续期持续失败 | 新建连接 407;**已建立的连接不受影响**(edge 无状态)。现场表现是「开着的页面还活着、新开的全打不开」,页面把它显式化——这就是 `C-10` 的解 |
| 连续失败到令牌失效之后 | **推给网络栈的 config 保持不变**(清空只会把可诊断的 403/407 换成不可诊断的连不上),页面显著标注表已不受新鲜授权支撑 |

---

## 5. 跨仓契约

```
POST https://gate.<D>/tunnel/bind   (设备证书 mTLS)
200 OK
{
  "tunnel_token": "<RS256 JWT>",
  "expires_in":   600,
  "routable_origins": [
    {"host": "app.corp",     "port": 443},
    {"host": "corp.example", "port": 443,  "include_subdomains": true},
    {"host": "adminer.corp", "port": 8080, "blocked": true}
  ],
  "routes_digest": "<sha256 hex>"
}
```

- **条目是结构化对象,不是字符串**。`include_subdomains` 必须是独立字段;压进字符串等于用另一种拼写把 `[*.]` 那类约定式解析请回来;
- 字段语义由 `common/tunnelauthz.Route` **单点定义**,两侧不得各自解释;
- **全部 `omitempty` 字段缺失一律按零值**——包括 `include_subdomains`、`blocked`、`routes_stale`、`routes_truncated`、`routes_dropped`(第二轮只给前两个定了默认,漏了最常缺失的那个);
- **空结果必须发 `[]`,`null` 是协议违例**(Go nil slice marshal 成 `null`);
- 数组按 `(host, port)` **去重(`include_subdomains` 取并集)并升序**;
- `routes_digest` 的输入**必须逐字节定义**(不定义到字节就不是契约);
- **`expires_in` 由盖 `exp` 的同一字段派生**(读配置是第二真值,会与实际 `exp` 静默漂移);
- **payload 规模必须与客户端的响应体上限闭合**。当前上限是 64KB,超限**整个请求失败**(拿不到令牌 → 永久退避)。plan 须按**序列化字节预算**而非条目数定上限,并同批调整客户端常量——按条目数定的版本在长 host 下不闭合;
- `routes_stale` / `routes_truncated` / `routes_dropped` / `blocked` / `routes_digest` **均不参与路由决策**,仅供诊断展示。

**联合验收(真机,两侧都过才算完成)**:

1. `include_subdomains` 应用的**根域与子域都可达** —— `C-2`(P1);
2. 索要客户端证书的站点**正常弹 picker、不再静默出示设备证书** —— `C-11`;
3. `teleport://tunnel` 显示正确列表(含 blocked / stale / truncated / dropped 标注)、到期时刻、CONNECT 状态码**与 authority** —— `C-10`;
4. `gate.<D>` **及覆盖它的通配**注册为 origin:服务端写入面拒绝;绕过写入面直接落库时两侧都不路由它,bind 不自锁 —— P2;
5. **同内容重复 bind 的 `routes_digest` 不变**(锚住排序与逐字节定义)。

---

## 6. 交付边界

**本仓**:`teleport_tunnel_logic.{h,cc}`(删推导、加解析与校验、通配双规则)、`teleport_tunnel_service.{h,cc}`(响应解析、loader 回调形态、启动与唤醒、observer 绑定、手动重绑、状态快照、响应体上限)、CONNECT 归因的上游 patch、`teleport://tunnel` 的 WebUI 全套。

**本仓不改**:edge 数据面、device-manager 编译器、AutoSelect 的 edge/gate 两条条目(隧道必需,且 gate 那条是 bind 选证的前提)。

**纯逻辑必须放 `teleport_tunnel_logic`**,不放 service——service 经 patch 编进 `chrome/browser`,轻量 `teleport_unittests` 链不到它的符号(`TD-TUNNEL-UNITTEST-WIRING` 已付过一次学费)。

**合并纪律**:两仓同分支,联合 e2e 通过后一并回各自 main(rebase + squash + ff),**不自动 push**。

---

## 7. 已知残余

| 编号 | 残余 | 去向(全部在两仓 `docs/tech-debt.md`) |
|---|---|---|
| `C-1` | 纯 HTTP 应用的 WebSocket 必然 403;会让 `C-10` 报假成功 | `TD-TUNNEL-HTTP-ORIGIN-WEBSOCKET` |
| `C-7` | 两条数据面路径的生命周期与容量 | `TD-TUNNEL-DATAPLANE-LIFECYCLE` |
| — | 路由表 + 其余 per-origin 策略键收窄到 per-subject | `TD-TUNNEL-ROUTING-TABLE-PER-SUBJECT`(前置:先抽共享收敛包) |
| — | bind 响应未签名 | `TD-TUNNEL-BIND-RESPONSE-UNSIGNED` |
| `C-5` 覆盖度半 / `C-3` / `C-4` / `C-9` / `C-6` / `C-8` | 见 research 报告 §7 | 各自 TD |

---

## 8. 决策账本

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| 1 | 11 条问题的切分 | 按根因分 A–E 五组,依次做 | 性质差异过大 |
| 2 | 明文 HTTP 应用定位 | 长期一等公民 | 用户裁定 |
| 3 | `C-1` / `C-7` 归属 | **均移出 A 组,各自单独立 spec** | 两者都是「看着像小改动、实为完整设计题」;三轮评审在它们身上找到的 Critical 多于其余部分之和 |
| 4 | `C-2` 修法 | **删除**推导路径而非修补解析 | 迁就 content-settings 语法是在迁就不该存在的耦合 |
| 5 | 路由表载体 | bind 响应 | 云策略要占 policy id + proto 字段号(每次里程碑升级多一处撞号);PAC 会打断 cnf 注入 |
| 6 | 路由表数据源 | 同一份 `routes.<tenant>` KV;**只宣称同源,不宣称无漂移** | edge 准入还要过候选集收敛,投影是其超集 |
| 7 | 路由表作用域 | **租户全量**(与今天一致);收紧单独立项 | 「今天是 USER scope」经三轮核验为假;且 per-route `authz.Check` ≠ gate 4 判定 |
| 8 | 捕获粒度 | 维持 host 捕获 | 过度捕获是唯一的漏配发现机制 |
| 9 | 灰度回退 | 无回退,硬 fail-closed | 开发期、零真实用户 |
| 10 | per-app AutoSelect 条目 | **删除**,但**必须同批交付 origin 级 `client_cert` opt-in** | 见 §8 注 |
| 11 | 诊断页归属 | 进 A 组并吸收 `C-10` | 换载体却看不见派生结果 = 把 `C-2` 的坑搬一遍 |
| 12 | CONNECT 归因 | **付 patch**,约束见 §3.4 | 403 的价值几乎全在「是哪个 origin」 |
| 13 | 启动竞态 | **不设前置判据,失败可被唤醒** | 两个异步前置,任何判据都不充分 |
| 14 | 服务端 KV 不可读 | **无快照时 5xx**,不发空表 | 见 §8 注 |
| 15 | 残余登记载体 | 两仓既有 `docs/tech-debt.md` | 避免第二个真值 |

**注(决策 10)**:origins-model 设计的 §9.1 早已预登记这次撤销,并写死了同批交付物——**origin 级 `client_cert` 布尔(默认 false)+ AutoSelect 收缩为 edge/gate 恒定条目 + 显式 opt-in**。第二轮只做了「收缩」那一半,把 opt-in 整个删掉且没登记,后果是**真正需要出示设备证书的应用失去全部通路**,而措辞还把它写成「纯收益」。本轮更正:opt-in 是同批交付物,不是可选项。同时必须显式声明撤销该设计的 **§5.1**(AutoSelect 覆盖每一个 origin)与 **§5.2**(客户端数据源不变、observer 不动)两条不变量。

**注(决策 14)**:第二轮把「KV 不可读即 5xx」判为全租户令牌悬崖,改成「照发令牌 + 空表」。**第三轮证明方向反了**:bind 失败**不推 config**,已在工作的客户端保留现有路由表并在 1 秒后重试;而「令牌 + 空表」会**立刻清空**它的路由表(空规则 + `reverse_bypass` = 全部 DIRECT = 不可诊断的连不上),下次尝试在 **8 分钟后**。为救「没有表的人」去伤「表好好的人」,且惩罚重 480 倍——这与本文 §4 最后一行为「表已失效」写的理由**自相矛盾**。故:**有快照服务快照并标注;无快照 5xx**。

---

## 9. 修订记录

- **第一轮**:`C-1` 移出;撤销「零上游 patch」与「启动竞态结构上不可能」;新增 edge/gate 排除与 host 校验;KV 不可达改 last-known-good;wire 契约修正。
- **第二轮**:作用域据一个**假前提**改成 per-subject(我采信子代理结论未核实);唤醒信号从一个补到三个;归因 patch 改为两侧分开;新增 body-idle 与并发流上限。
- **第三轮**:
  - **作用域改回租户全量**(前提经独立核验为假),并删掉第二轮那条同样被证伪的「多载体」理由;
  - **`C-7` 移出 A 组**——它与 `C-1` 同形:看着是常量,实为四条腿的容量设计题,且触及两个比它本身更严重的既有悬崖(`AcceptBacklog` 阻塞信号量、`StreamOpenTimeout` 关整个会话);
  - **决策 14 方向反转**(冷启动改回 5xx);
  - **决策 10 补回被删掉的同批交付物**(`client_cert` opt-in);
  - **全文降到「决策 + 契约」高度**:第三轮证明我写的实现机制连续三轮被推翻(这轮是 host 校验被 `corp.example;.com` 绕过、"第二个唤醒信号"实为同步 nullopt 且此后不再触发),故一切「用哪个 API、判据怎么写、改哪几个文件」下沉到 plan,并一律成对写成「先验证、再实现」。
