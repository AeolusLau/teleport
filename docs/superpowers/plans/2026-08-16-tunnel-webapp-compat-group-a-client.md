# 隧道 Web 应用兼容性 A 组 · 客户端实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把隧道路由白名单从 `AutoSelectCertificateForUrls` 策略搬到 bind 响应,并新建 `teleport://tunnel` 诊断页,让派生后的实际状态第一次变得可见。

**Architecture:** 纯逻辑(解析 / 校验 / 排除 / 去重 / 规则产出)全部落在独立可测的 `teleport_tunnel_logic` source_set;`TeleportTunnelService`(编在 `chrome/browser`)只做编排;诊断页沿用 `teleport://enroll` 的 MojoWebUIController 形态;CONNECT 归因经一处**非破坏性**上游 patch 取得目的地。

**Tech Stack:** C++17 / Chromium M151 overlay / GN + Siso / gtest(`teleport_unittests` 与上游 `unit_tests`)/ Mojo / TypeScript + Lit(WebUI)

## ⚠️ 一条贯穿全计划的纪律:**绿色输出不是证据,数量才是**

本会话已经出现**三次**假绿,三次都是「命令返回成功、实际什么都没验」:

1. 服务端 Task 9 的 `go build ./...` 在仓库根**从来跑不起来**,而它被写成了终局验收门;
2. `go test ./...` 对带 `//go:build integration` 的包打绿灯,**藏掉 105/110 个测试**(我第一次修这条时还把症状写成了「跑零个」——实际跑 5 个,而这个差别正好让「有没有测试跑」这个探测器失效);
3. **`net_unittests` 的代理套件是参数化的**(`HttpProxyType/HttpProxyConnectJobTest.*` 等)。用不带前缀的名字过滤会匹配到 **0 个测试**,而 runner **照样打印 `SUCCESS: all tests passed.`** —— Task 8 的第一次取证运行就是这样,靠数执行条数才发现。

**所以:任何「验证某套件通过」的步骤,必须断言执行条数,不得只看 SUCCESS 行。** 任何跨模块 / 跨 tag 的测试命令,必须先确认它真的编译并运行了目标包。

## Global Constraints

- 上游基线 `CHROMIUM_VERSION` = **151.0.7922.76**;检出在 `$TELEPORT_CHROMIUM_ROOT/151.0.7922`(默认 `~/workspace/chromium/151.0.7922`)。**每个新 shell 先 `unset TELEPORT_CHROMIUM_DIR`**。
- **纯逻辑必须放 `src/browser/enterprise/teleport_tunnel_logic.{h,cc}`**,不得放 `teleport_tunnel_service.cc`——后者经 `patches/chrome/browser/BUILD.gn.patch` 编进 `chrome/browser`,轻量 `teleport_unittests` 链不到它的符号(`TD-TUNNEL-UNITTEST-WIRING`)。
- **修改已有 patch 的唯一工作流**:`apply_patches.py` 全应用 → 直接编辑 `chromium/src/<file>` → `git -C chromium/src diff -- <path> > patches/<path>.patch` 重生成 → 再跑 `apply_patches.py` 验幂等。**禁止手改 hunk。**
- 产物语言:代码 / 注释 / commit message 一律 **English**;本计划与 spec 为中文。
- 提交遵 Conventional Commits;**不自动 push**,不自动合并。
- **跨仓契约(与 fairyland 计划逐字段一致,任何一侧改动须同批改另一侧)**:

```
POST https://gate.<D>/tunnel/bind   200 OK
{
  "tunnel_token": "<RS256 JWT>",
  "expires_in":   600,
  "routes_stale":     false,   // omitempty
  "routes_truncated": false,   // omitempty
  "routes_dropped":   0,       // omitempty
  "routable_origins": [ {"host":"h","port":443,"include_subdomains":false,"blocked":false} ],
  "routes_digest": "<sha256 hex, lowercase>"
}
```
  - 全部 `omitempty` 字段缺失按零值;空结果发 `[]`,`null` 是协议违例;
  - 数组按 `(host, port)` 去重(`include_subdomains` 取并集)并升序;
  - `routes_stale` / `routes_truncated` / `routes_dropped` / `blocked` / `routes_digest` **不参与路由决策**。

---

## 验证阶段结论(2026-08-16 完成)与本计划的勘误

四份结论在 `docs/verification/`。**下面每一条都推翻了本计划初稿的一个具体断言**,执行时以此为准。

| # | 初稿写的 | 实际 | 影响 |
|---|---|---|---|
| 1 | Task 2 用 `bypass_rules.Matches(url, /*reverse=*/true)` 断言「命中」,并注释「漏传 reverse 会静默测反」 | **极性全反**:`Matches()` 答的是「是否 bypass 代理」,命中 ⇒ `false`。而且**漏传 reverse 才会让错断言变绿** | 四条断言照抄会全红;已改用 `ProxyRules::Apply()` 断言「走不走隧道」 |
| 2 | spec P3「**每次拷贝**都是字符串往返,所以 `corp.example;.com` 会裂」 | `operator=` 确实是往返,**但当前 mojo 边界是 `array<string>` 逐条 `AddRuleFromString`,推送路径全程无拷贝** ⇒ 今天不会裂 | 判据**不变**,但拒绝理由改写为「**潜伏**:任何一次拷贝 / Clone / 重构即触发」。上游那道 `DCHECK` 查的是子串 `",;"`,单分隔符拦不住 |
| 3 | 「GURL 往返逐字节相同」能干掉尾点 | **干不掉**。去尾点只发生在 IP 字面量路径;`;`、`,`、前导 `.` 同样过 | 尾点、分隔符、前导点各需**独立判据** |
| 4 | `include_subdomains` 两标签规则挡公共后缀 | 无效。`github.io` / `s3.amazonaws.com` 是 **private** 标志,默认 `EXCLUDE_PRIVATE` 漏掉;且 `co.uk` 与 `corp.example` 同为两标签而后者必须放行 | 必须用 `GetDomainAndRegistry(..., INCLUDE_PRIVATE_REGISTRIES)` |
| 5 | (未提) | **`HostIsRegistryIdentifier()` 带三个 `CHECK`(非 DCHECK)**,空串 / 非规范 / IP 输入**直接崩进程**;而输入是未签名的服务端字符串 | **调用顺序是承重的**:注册域判定必须排在全部形状校验**之后** |
| 6 | 用 `IsLoopback() \|\| IsLinkLocal() \|\| IsZero()` | 盖不住 RFC1918;`localhost` 这种**名字**形态 `AssignFromIPLiteral` 根本命中不了 | 名字形态用 `net::HostStringIsLocalhost()`;**`IsHostnameNonUnique()` 是陷阱**,会误杀 `app.corp` 这类合法内网名 |
| 7 | (未提) | 纯 ASCII host 上游**零长度限制**(`kMaxHostLength` 只用于 IDN 缓冲) | 长度上限必须我们自己加 |
| 8 | Task 7「三个信号」 | **证书就绪不可观测**(见下) | 唤醒只覆盖策略那一半 |
| 9 | Task 8「**一处**非破坏性上游 patch」 | **10 个 patch 文件**;mojom 侧 3 个是**被强制的破坏性改动** | spec §3.4 本身是对的,是本计划的摘要压缩错了 |
| 10 | Task 10「6 个 patch」 | **7 个**,漏的两个只在真机炸 | 见 Task 10 |

### Task 1–5 执行后的追加勘误(2026-08-16)

| # | 计划写的 | 实际 |
|---|---|---|
| a | Task 1 测试代码用 `base::Value::List` + `TakeList()` | **那是 M148 API,M151 已无**。实为 `base::ListValue` / `base::DictValue` + `JSONReader::ReadList(json, options)`。后续任何测试代码不得再照 M148 记忆写 |
| b | (未提)`RejectHost()` 骨架的 IP 分支提前 `return` | **我那条 RFC1918 放行的决定给它开了一个欺骗面**:被放行的 IP 字面量因此**永不经过 GURL 往返规范性检查**。`010.0.0.5` 是八进制的 **8.0.0.5** —— 规则会按规范化后的地址构建,而诊断页显示的是原始字符串。已补 `if (ip.ToString() != host) return "non-canonical IP literal";` 与用例。**这是我的决定的二阶后果,验证阶段和我都没看出来** |
| c | 结论 Q7「长度上限必须我们自己加」 | **只对一半**:规则侧确实无限制,但同一份文档定为第 2 步的 `IsCanonicalizedHostCompliant()` **已经**拒掉 ≥254(非尾点 host)。显式长度检查是**构造上冗余**,不是新增覆盖。保留作 Task 12 的预算锚点,注释须如实说明,不得冒充补洞 |
| d | Task 4 未提排序 | **gate 必须先于 edge 检查**:通配覆盖 `D` 时 `gate.tp.D` 与 `edge.tp.D` **都**被覆盖,但只能报一个原因,而计划的测试断言原因含 `"gate"`。顺序是承重的 |
| e | Task 1 Step 5「最小改动让树可编」 | 低估了范围。`teleport_tunnel_service_unittest.cc`(经 `patches/chrome/test/BUILD.gn.patch` 接进 `unit_tests`)里有 `RoutableOriginsResyncWhenPolicyLandsAfterStart`,**钉的正是被删掉的策略推导行为**——会编译通过然后失败。另需给 `RoutableOrigin` 加 `operator==`、改 `routable_origins_` 类型、修一处流式输出该结构的 `VLOG` |
| f | Task 4 Step 5「更新 service 的调用点」 | **moot**:Task 1 之后 service 里已无 `ParseRoutableOrigins` 调用,Task 6 才引入 |
| g | (未提)共享检出的 overlay 符号链接 | 执行时 `chromium/src/teleport` 指向的是**另一个 worktree**(`aliyun-first-deploy`),其 8 个 patch 已应用、`chrome/VERSION` 是那条分支的版本。已重新指向本 worktree 并重跑 `apply_patches.py`。**代价:一次全量重建;且回到那条分支的人必须先重跑 `apply_patches.py`** |

**遗留给 Task 13 Step 3**:`docs/tech-debt.md` 的 `TD-TUNNEL-BIND-RESPONSE-UNSIGNED` 现已**陈旧**——它仍写着 `include_subdomains` 门控在「至少两个标签」(已被证伪:`co.uk` 与 `corp.example` 同为两标签),且列的元字符集比实际落地的窄。RFC1918 的理由目前只存在于代码注释与提交信息里,须一并同步进该条目。

### Task 6–7 执行后的追加勘误与一处决定反转(2026-08-16)

| # | 计划 / 结论写的 | 实际 |
|---|---|---|
| h | 验证结论 §7 要求「自动唤醒设最小间隔」,理由是「抖动饿死」 | **该理由已不成立**:它预设唤醒会**取消**在途 bind。一旦唤醒永不中断在途请求,一次飞行期间的 N 次唤醒**塌成一个 pending 位**,没有可饿死的东西。限流只属于手动重绑(Task 11)。已由 `RepeatedWakeUpsCollapseIntoOneRetry` 钉住 |
| i | (计划与结论都没预见) | **把启动与唤醒合并成一个信号入口会让构造期的延迟读值门变成一次伪唤醒**。注册器的直接 `Start()` 是同步的,在首次纳管时**必然**赢过构造函数 post 出去的任务;那个任务随后看到 `started_ == true`、把门读成开,于是**每次纳管都多发一次 bind**。两个 Task-7 测试在 `ASSERT` 设置行上就红了。已拆出独立的初始读值门,已启动即早退 |
| j | Task 6 只说「解析完整响应体」,`expires_in` 无消费者 | 只拿它显示等于:客户端按固定 8 分钟重铸,却同时展示一个**它明知已经跑过头**的服务端到期时刻(`expires_in: 100` ⇒ 令牌死了 6m20s 才刷新)。**已接进刷新环**:TTL×0.8、下限 30s、字段缺失时回落固定 8 分钟。**副作用:`expires_in` 从「仅供展示」变成承重字段**,服务端必须如实给(Task 3 已让 `Mint` 返回真实 TTL,对齐) |
| k | 验证结论 §8「勿破坏 `OnManagedAutoSelectPrefChanged` 的 post-Start 重推角色」 | **moot**:该角色在 Task 1 就随 `DeriveRoutableOrigins` 一起死了 |
| l | Task 6/7 的测试草稿引用了一整套 fixture | **那套 fixture 不存在**,既有 5 个测试各自手搭 service + interceptor。已在不改写既有测试的前提下新建 harness |

**`AutoSelectCertificateForUrls` 仍留在读值门里**——它不再供给路由表,但它是让网络栈在 gate 的 mTLS 握手上愿意出示设备证书的那个条件。代码里已注明,别当残留删掉。

### 一处决定反转:协议违例时**不清空**已有路由表

执行代理选择了「后来的 bind 若不带表,就清掉先前那份好表」,理由是「无回退就是无回退」,并明确请我复核。**我改成:区分两种情形。**

- `routable_origins: []`(**显式空数组**)⇒ 服务端在说「你没有应用」⇒ **清空,正确**;
- **字段缺失或 `null`** ⇒ 这是**协议违例**,服务端坏了 ⇒ **保留现有表 + 置 hard-stale + 诊断页显著标注**。

理由与我在服务端把冷启动改回 5xx 的那条**完全同源**:§2 的不变量说客户端路由表只是提示、授权真值恒在 edge,所以陈旧的表**不产生安全风险**;而清空会把**可诊断的 403/407 换成不可诊断的连不上**,并且一次性打掉全部应用。两处是同一个失败面,不能一处 fail-stale、另一处 fail-closed。

本文 §4 最后一行早就为「表已失效」写了这条理由,当时只覆盖了「持续 bind 失败」;现在把「bind 成功但响应违例」一并纳入。**Task 8 的执行者顺带改这一条并补测试。**

### Task 8–9 执行后的追加勘误(2026-08-16)

| # | 计划 / 结论写的 | 实际 |
|---|---|---|
| m | 验证结论 §7:默认体可内联写在头里,故 `proxy_delegate.cc` 不必进 patch 清单 | **那样写编译不过**:Chromium 的 clang plugin 禁止**非空**的内联虚函数体(`virtual methods with non-empty bodies shouldn't be declared inline`)。`be430f1` 能内联只因为它的体是空的 `{}`;我们的默认体要转发,非空 ⇒ **必须落 `.cc`**。**patch 是 11 个文件不是 10 个,新碰的上游文件是 6 个不是 5 个**——比成本估计多一个里程碑冲突点 |
| n | (未提)`ProxyList::First()` 的返回类型 | 是 `const ProxyChain&`,不是 `std::optional<ProxyServer>`。config 里的 edge hop 本来就是一条链 |
| o | (未提)本 worktree 没有 `chromium/` 符号链接 | 计划里的 `git -C chromium/src diff` **在这里跑不通**,Task 10+ 必须用检出的绝对路径 |

**几处值得保留的判断**(执行代理的偏离,均有理由):默认体所需的 include **显式写出**而不依赖传递包含——传递包含一旦被上游改成前置声明,会在 rebase 时以一个离病因很远的症状炸掉;MASQUE 那条调用点**保留旧 override 并上报空 authority**,而不是丢掉通知,行为与改动前完全一致、只是没有归因;两个重载共用一个私有非虚 helper,**避免「哪个体在跑」取决于虚分发**。

**协议违例保留表那处修正的实现细节值得记**:整份表快照(origins + skipped + 元数据)**一起保留**——若把一个没带表的响应里的标志位采纳进来、再配上保留的旧表,`routes_digest` 就会描述一个不存在的东西。hard-stale 用独立字段而非塞进 skipped 列表,因为「显著可见」正是保留之所以安全的前提。`routes_unavailable_` 的语义也随之从「上一次响应没带表」改成「从未采纳过一份良构的表」。

**两个回归锚做了变异验证**,不是只跑绿:把重推谓词改回 `have_pushed_config_`、以及单独删掉代理链过滤,各自都能让对应测试变红,然后再恢复重建。这才是锚。

### Task 10–11 执行后的追加勘误(2026-08-16)

| # | 计划 / 结论写的 | 实际 |
|---|---|---|
| p | 「本树 `gn check` 是开着的,所以坏的依赖边会被它抓住」 | **半假,而且本树根本过不了 `gn check`**。`.gn` 里没有 `check_targets` 只意味着「check 跑起来时全部在范围内」——而 **`gn gen` 并不跑 check**。实测 `gn gen --check` 今天就失败,原因是一处**既有的 overlay 违规**:`oidc_auth_response_capture_navigation_throttle.cc.patch` 从一个编进 `//chrome/browser/enterprise:impl` 的文件里 include 了三个属于 `//chrome/browser:core` 的 teleport 头。**结论仍然成立,但理由必须换**:加那条依赖会让**普通 `gn gen`** 直接报 Dependency cycle,与 check 无关(已实测) |
| q | 预测的环路径 `core → configs → tunnel → core` | GN 实际报的是另一条(经 `browser_public_dependencies → browser_generated_files → teleport_tunnel → core → app_shim → …`)。两条都是真环,判定不变 |
| r | (计划与结论都没提)mojom 字段命名 | **必须 snake_case**。`has_token` 在 mojom 里会同时产出 C++ 的 `state->has_token` 与 TS 的 `state.hasToken`;写成 `hasToken` 生成器会静默照抄,然后 handler 编译失败。enroll 的 `can_unbind`/`canUnbind` 是先例,但文件清单从没写出这条规则 |
| s | (未提)WebUI 的两条 eslint 硬规则 | enroll 页碰不到(它的模板没有循环也没有局部变量):`lit-element-template-structure` **禁止 `*.html.ts` 里出现任何 `const`/`let`**,而随后 `no-unnecessary-type-assertion` 又禁掉 `this.state_!.x`(TS 在 else 分支已收窄)。**唯一能过的写法是长的 `this.state_.x`**,两种简写都不行 |
| t | Task 10 Step 2「页面先只渲染一个静态标题」 | **那样验不出任何东西**——静态页在有没有 Mojo binder 的情况下**加载得一模一样**,恰好证明不了那个「只在真机炸」的 patch。已改为页面加载即调 `GetState()` 并渲染真快照,这才让「永远 loading」这个失败模式可检测。**这是本会话第四个「验证什么都没验」的形状** |
| u | Task 11 的测试草稿 | **按原样跑不通**:`EXPECT_FALSE(service()->Rebind())` 是第一条语句,而 `service()` 在 `CreateService()` 之前是空的;`RebindIsRateLimited` 从没设 AutoSelect 策略,所以读值门是关的、`Rebind()` **正确地**返回 false——**草稿断言的正好和 Task 7 确立的行为相反** |
| v | (未提)截图验证路线 | **此处走不通**(Task 13 的冒烟要注意):`--headless=new --screenshot=<f> <url>` **会忽略 URL 去截 NTP**,而 `screencapture` 需要本会话没有的屏幕录制权限。可行路线是手写 CDP 客户端 |

**一处值得学的自我防御**:防令牌泄漏那个测试的强度**完全取决于序列化器覆盖了哪些字段**——所以执行代理在两个头文件里显式写明了这一点,加了 `CoversEveryStringBearingField` 作提醒,还加了一条 `HasSubstr` 正向断言,**使一个返回 `{}` 的空序列化器无法蒙混过关**。考虑到本会话已有的假绿史,这个习惯应当成为默认。

### Task 12–13 执行后的追加勘误(2026-08-16)

| # | 计划 / 结论写的 | 实际 |
|---|---|---|
| w | Task 12 Step 3–4「提高常量」+ commit message「raise the bind response body cap」 | **该步骤作废,两个数都不动**。算术:服务端 48 KiB 预算按**悲观**条目形状(40 字符 FQDN、4 位端口、两个 flag 都在,`omitempty` 一点便宜不占,每条 104 字节)容 **468 个地址**;整包配 5 倍余量的 4 KiB JWT 仍远在 64 KiB 之下。数百个内网应用的大型租户已闭合。**提高只增加漂移面,不增加能力**:只提客户端 ⇒ 服务端仍按旧预算静默截断;只提服务端 ⇒ 客户端整个 bind 失败。详见 `docs/verification/2026-08-16-payload-budget.md` |
| x | (未提)常量该放在哪 | 计划默认「就地改 `teleport_tunnel_service.cc` 里那个常量」。**那样永远钉不住**——它在匿名 namespace 里,而 service 编在 `chrome/browser`,轻量套件链不到。已移进 `teleport_tunnel_logic.h`。**客户端此前没有任何测试钉这个数**;服务端钉的是它自己那份镜像,客户端改了而没人改服务端时**服务端测试照样绿**,这个洞只能从客户端这侧堵 |
| y | Task 12 关于零值路径的追问 | 客户端**结构性无对应物**:`inline constexpr`,无 pref / 无策略 / 无 setter / 单一使用点。且假设性的零值在客户端是 **fail-closed 且吵**(每次 bind 超限 ⇒ 无令牌 ⇒ 诊断页显示失败),不是服务端那种 **fail-open 且静**(有效令牌 + 空表)。理由已写进常量注释,防止后人把它变成旋钮而复刻刚封上的洞 |
| z | Task 10–11 勘误 (p):`gn gen --check` 失败,原因是**一处**既有 overlay 违规(`oidc_auth_response_capture_navigation_throttle.cc`) | **规模差了一个量级**:实测 **28 个 ERROR / 19 个文件**(`gn check out/… --error-limit=500`),含**我们自己的两个 overlay 源文件**。(p) 只看到一个文件,是因为**默认 error-limit 在 10 条就截断**并打印「Too many errors」;而 `--error-limit=0` **不是「不限」,它会抑制全部输出**。已登记 `TD-OVERLAY-GN-CHECK-VIOLATIONS`。**隧道相关文件一个都不在错误列表里** |
| aa | (本计划已在 (p) 里更正过,但代码没跟着改) | 「gn check is on in this tree」这句**被证伪的断言仍然出现在两处已提交的产物里**:`teleport_tunnel_logic.h` 的 seam 注释与 `patches/chrome/browser/ui/webui/BUILD.gn.patch` 里注入的 BUILD.gn 注释。**把勘误折进计划,不会追溯修好照着错误信念写出来的代码**——两处已改正,理由换成「那条依赖边会让普通 `gn gen` 直接报环」(结论不变,依据换掉) |
| bb | Task 13 的冒烟(承 (v) 的手写 CDP 路线) | 路线成立,但有**三个额外的坑**:① **DevTools 端口在启动后约 30 秒才起来**——本机存在 CBCM enrollment token,启动期注册请求要等满 `ERR_TIMED_OUT`,而超时**不会**打印任何拒绝原因,等 8~12 秒会得到「远程调试被禁用」的假象(顺带确认:上游 default-user-data-dir 限制对**非品牌构建不生效**,不是它);② `/json/new` 现在要 **PUT**,GET 返回 405;③ WebSocket 握手默认 **403**,要 `suppress_origin=True`(优于 `--remote-allow-origins=*`)。另:自定义元素名是 **`tunnel-app`**,且必须穿透 shadow root 才读得到内容 |
| cc | Task 13 Step 1 的验收只写「全绿」 | 按本计划自己的纪律改为**断言执行条数**:`teleport_unittests` **159/159**、`unit_tests --gtest_filter='TeleportTunnel*'` **37/37**(跑前先 `--gtest_list_tests` 确认过非零)、`uv run pytest` **314 passed / 0 skipped**、`apply_patches.py` 幂等 |

**Task 12 的 IPv6 一问已由服务端定案**(选 (b) 不支持),客户端**无需改动且已一致**——现有 host 校验第 2 步的 `IsCanonicalizedHostCompliant` 拒掉一切含 `:` 的形态。主动找过的三条潜在不一致(IPv4-mapped 被 RFC1918 分支捞回 / 被当成静默丢弃 / 存在绕过校验的第二个消费者)**都不成立**。新增的回归测试**断言拒绝原因而非只数条数**,因为「拒绝发生在哪一步」正是这条一致性的全部内容。见 `docs/verification/2026-08-16-ipv6-origins.md`。

### 一个需要产品拍板的点,我在此决定并说明理由

**RFC1918 地址(`10.0.0.5` 这类)必须放行,不能用 `IsPubliclyRoutable()` 一刀切。**

验证结论建议用 `IsPubliclyRoutable()` 覆盖全部保留段,那会把 RFC1918 一并拒掉——**而内网应用跑在 RFC1918 上正是本产品的目标场景**,按 IP 注册 origin 是合理形态。

这道检查要防的是「把**全部**流量导进 edge」(`*`、`0.0.0.0/0` 这类规则注入)和「把**本机**服务导出去」(loopback / link-local / unspecified),**不是**「够到一个内网 IP」——后者是产品的全部意义。而且按 §2 的不变量,路由不等于授权,edge 才是真值。

**所以:拒 loopback / link-local / unspecified,放行其余 IP 字面量**,并在 `TD-TUNNEL-BIND-RESPONSE-UNSIGNED` 里记明这条边界的理由。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `src/browser/enterprise/teleport_tunnel_logic.h/.cc` | **纯逻辑**:`RoutableOrigin`、`SkippedEntry`、`ParseRoutableOrigins`、`BuildTunnelProxyConfig`。零 chrome/content 依赖 |
| `src/browser/enterprise/teleport_tunnel_logic_unittest.cc` | 上者的全部单测(接 `teleport_unittests`) |
| `src/browser/enterprise/teleport_tunnel_service.h/.cc` | 编排:bind、解析调用、推 config、启动与唤醒、observer、`Rebind`、状态快照 |
| `src/browser/webui/tunnel.mojom` | 诊断页 Mojo 接口 |
| `src/browser/webui/teleport_tunnel_ui.h/.cc` | `WebUIConfig` + `MojoWebUIController` + `PageHandler` |
| `src/browser/resources/tunnel/*` | 页面 TS/HTML/CSS + `BUILD.gn` |
| `patches/net/base/proxy_delegate.h.patch` 等 | CONNECT 归因的非破坏性新增 |
| `docs/verification/2026-08-16-*.md` | **验证任务的产出**(引用 file:line 的结论,供后续任务与评审复核) |

---

## Task 0: 建立验证产出目录与工作环境

**Files:**
- Create: `docs/verification/README.md`

**Interfaces:**
- Produces: `docs/verification/` 目录,后续每个验证任务在此落一份带 `file:line` 的结论文档。

- [ ] **Step 1: 确认环境**

```bash
unset TELEPORT_CHROMIUM_DIR
export TELEPORT_CHROMIUM_ROOT="${TELEPORT_CHROMIUM_ROOT:-$HOME/workspace/chromium}"
ls "$TELEPORT_CHROMIUM_ROOT/151.0.7922/src/net/base/proxy_delegate.h"
```
Expected: 文件存在。不存在则停止,先按 `docs/chromium-upgrade-runbook.md` 建检出。

- [ ] **Step 2: 建目录与说明**

```bash
mkdir -p docs/verification
cat > docs/verification/README.md <<'MD'
# 验证结论

A 组计划要求:凡引用上游或跨仓行为的实现任务,第一步必须是验证步,结论落在本目录。

原因见 spec §0 —— 三轮对抗评审证明这类结论读代码读不对,而编译器与测试一次就能给出答案。

每份文档必须:
- 给出 `file:line` 级证据,不接受"我记得"或"通常是";
- 明确写出结论**推翻**了哪条先前假设(如果有);
- 结论直接决定后续任务的判据,不得只写"看起来没问题"。
MD
```

- [ ] **Step 3: 提交**

```bash
git add docs/verification/README.md
git commit -m "docs(plan): add verification-findings directory for group A"
```

---

## Task 1: 删除策略推导路径,建立 `RoutableOrigin` 与解析骨架

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_logic.h`
- Modify: `src/browser/enterprise/teleport_tunnel_logic.cc`
- Test: `src/browser/enterprise/teleport_tunnel_logic_unittest.cc`

**Interfaces:**
- Produces:
  - `struct teleport::tunnel_internal::RoutableOrigin { std::string host; uint16_t port; bool include_subdomains; bool blocked; }`
  - `struct teleport::tunnel_internal::SkippedEntry { std::string raw; std::string reason; }`
  - `std::vector<RoutableOrigin> ParseRoutableOrigins(const base::Value::List& entries, std::vector<SkippedEntry>* skipped)` —— **本任务只做形状解析,不含校验/排除/去重**(分别在 Task 3/4/5 加)。
- Consumes: 无。

- [ ] **Step 1: 写失败测试**

在 `teleport_tunnel_logic_unittest.cc` 追加:

```cpp
namespace teleport::tunnel_internal {
namespace {

base::Value::List MakeEntries(std::string_view json) {
  std::optional<base::Value> v = base::JSONReader::Read(json);
  CHECK(v && v->is_list());
  return std::move(*v).TakeList();
}

TEST(TeleportRoutableOriginParseTest, ParsesWellFormedEntries) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"app.corp","port":443},
        {"host":"corp.example","port":443,"include_subdomains":true},
        {"host":"adminer.corp","port":8080,"blocked":true}
      ])"),
      &skipped);

  ASSERT_EQ(out.size(), 3u);
  EXPECT_EQ(out[0].host, "app.corp");
  EXPECT_EQ(out[0].port, 443);
  EXPECT_FALSE(out[0].include_subdomains);
  EXPECT_FALSE(out[0].blocked);
  EXPECT_TRUE(out[1].include_subdomains);
  EXPECT_TRUE(out[2].blocked);
  EXPECT_EQ(out[2].port, 8080);
  EXPECT_TRUE(skipped.empty());
}

TEST(TeleportRoutableOriginParseTest, SkipsMalformedAndReportsReason) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"ok.corp","port":443},
        "not-an-object",
        {"port":443},
        {"host":"","port":443},
        {"host":"noport.corp"},
        {"host":"badport.corp","port":0},
        {"host":"badport2.corp","port":70000}
      ])"),
      &skipped);

  ASSERT_EQ(out.size(), 1u);
  EXPECT_EQ(out[0].host, "ok.corp");
  EXPECT_EQ(skipped.size(), 6u);
  for (const auto& s : skipped) {
    EXPECT_FALSE(s.raw.empty());
    EXPECT_FALSE(s.reason.empty());
  }
}

TEST(TeleportRoutableOriginParseTest, EmptyListYieldsEmptyResult) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(MakeEntries("[]"), &skipped);
  EXPECT_TRUE(out.empty());
  EXPECT_TRUE(skipped.empty());
}

}  // namespace
}  // namespace teleport::tunnel_internal
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd "$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
autoninja -C out/mac/arm64/dev teleport_unittests
```
Expected: 编译失败,`ParseRoutableOrigins` / `RoutableOrigin` / `SkippedEntry` 未声明。

- [ ] **Step 3: 实现**

`teleport_tunnel_logic.h` —— **删除** `DeriveRoutableOrigins` 声明及其注释块,加入:

```cpp
// One entry of the server-supplied routing table (see the group-A spec §5).
// `include_subdomains` is a STRUCTURED field, never a string convention —
// that is the whole point of moving off the content-settings `[*.]` pattern
// whose GURL parse failure silently dropped every wildcard origin (C-2).
// `blocked` is DIAGNOSTICS ONLY: the server marks the address as having no
// route row of its own; the edge's own verdict is computed over a collapsed
// claimant set, so this flag must never be presented as "will certainly fail".
struct RoutableOrigin {
  std::string host;
  uint16_t port = 0;
  bool include_subdomains = false;
  bool blocked = false;
};

// An entry that did not survive parsing/validation, kept so the diagnostics
// page can show it. Silently dropping entries is exactly the C-2 defect this
// whole change replaces, so every rejection must be reportable.
struct SkippedEntry {
  std::string raw;
  std::string reason;
};

// Parses the bind response's `routable_origins` array. Malformed entries are
// skipped and reported through `skipped` rather than failing the whole table:
// one bad row must not cost a tenant its entire routing table. Callers MUST
// surface `skipped`.
std::vector<RoutableOrigin> ParseRoutableOrigins(
    const base::Value::List& entries,
    std::vector<SkippedEntry>* skipped);
```

`teleport_tunnel_logic.cc` —— **删除** `DeriveRoutableOrigins` 定义,加入:

```cpp
namespace {

std::string EntryToRaw(const base::Value& entry) {
  std::string json;
  base::JSONWriter::Write(entry, &json);
  return json;
}

}  // namespace

std::vector<RoutableOrigin> ParseRoutableOrigins(
    const base::Value::List& entries,
    std::vector<SkippedEntry>* skipped) {
  CHECK(skipped);
  std::vector<RoutableOrigin> out;
  for (const base::Value& entry : entries) {
    const base::Value::Dict* dict = entry.GetIfDict();
    if (!dict) {
      skipped->push_back({EntryToRaw(entry), "entry is not an object"});
      continue;
    }
    const std::string* host = dict->FindString("host");
    if (!host || host->empty()) {
      skipped->push_back({EntryToRaw(entry), "missing or empty host"});
      continue;
    }
    std::optional<int> port = dict->FindInt("port");
    if (!port) {
      skipped->push_back({EntryToRaw(entry), "missing port"});
      continue;
    }
    if (*port < 1 || *port > 65535) {
      skipped->push_back({EntryToRaw(entry), "port out of range"});
      continue;
    }
    RoutableOrigin origin;
    origin.host = *host;
    origin.port = static_cast<uint16_t>(*port);
    origin.include_subdomains =
        dict->FindBool("include_subdomains").value_or(false);
    origin.blocked = dict->FindBool("blocked").value_or(false);
    out.push_back(std::move(origin));
  }
  return out;
}
```

同时删除 `teleport_tunnel_logic.cc` 中已不再需要的 include(`base/json/json_reader.h` 若无其它用途、`url/gurl.h` 若 Task 3 尚未加回)。

- [ ] **Step 4: 跑测试确认通过**

```bash
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportRoutableOriginParse*'
```
Expected: 3 tests PASS。

- [ ] **Step 5: 修复 `DeriveRoutableOrigins` 的既有调用方与测试**

`teleport_tunnel_service.cc` 里 `TeleportTunnelService::DeriveRoutableOrigins()` 及其调用点会编译失败;本步只做**最小改动让树可编**——把 `routable_origins_` 暂时置空并加 `// TODO(task-6): fed from the bind response`。Task 6 会真正接上。
同时删除 `teleport_tunnel_logic_unittest.cc` 中原有的两个 `TeleportTunnelRoutesDeriverTest`。

```bash
autoninja -C out/mac/arm64/dev teleport_unittests chrome
```
Expected: 全部编译通过。

- [ ] **Step 6: 提交**

```bash
git add src/browser/enterprise/teleport_tunnel_logic.h \
        src/browser/enterprise/teleport_tunnel_logic.cc \
        src/browser/enterprise/teleport_tunnel_logic_unittest.cc \
        src/browser/enterprise/teleport_tunnel_service.cc
git commit -m "feat(tunnel): parse the routing table from the bind response

Deletes DeriveRoutableOrigins, whose GURL parse of the content-settings
'[*.]host' pattern failed on the bracket and silently dropped every wildcard
origin (C-2). The replacement takes structured entries, so that class of
failure cannot recur in another spelling."
```

---

## Task 2: 通配条目产出两条规则(性质 P1)

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_logic.h/.cc`
- Test: `src/browser/enterprise/teleport_tunnel_logic_unittest.cc`

**Interfaces:**
- Consumes: `RoutableOrigin`(Task 1)
- Produces: `BuildTunnelProxyConfig(std::string_view edge_host, uint16_t edge_port, const std::vector<RoutableOrigin>&, std::string_view cnf_token)`(签名从 `std::vector<std::string>` 改来)

- [ ] **Step 1: 验证匹配语义(先验证,再实现)**

```bash
CR="$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
grep -n -A6 "SchemeHostPortMatcherHostnamePatternRule::Evaluate" "$CR/net/base/scheme_host_port_matcher_rule.cc"
grep -n -B4 -A12 "bool ProxyHostMatchingRules::Matches" "$CR/net/proxy_resolution/proxy_host_matching_rules.cc"
grep -n "Matches(" "$CR/net/proxy_resolution/proxy_host_matching_rules.h"
```

把结论写入 `docs/verification/2026-08-16-wildcard-matching.md`,必须回答:
1. 匹配函数是不是 `base::MatchPattern(url.GetHost(), hostname_pattern_)`?
2. `*.corp.example` 是否匹配 `corp.example` 本身?(预期:**否**,故必须发两条)
3. `ProxyHostMatchingRules::Matches(url, reverse)` 的 `reverse` 默认值是什么?(预期 **false** —— 测试若忘了显式传 `true`,测的是反向语义却照样绿)

- [ ] **Step 2: 写失败测试**

> **不要用 `bypass_rules.Matches()` 写断言。** 它回答的是「该 URL 是否**绕过**代理」,不是「是否命中规则」:
> `Matches()` 在 `kInclude` 时 `return !reverse`、无命中时 `return reverse`,而 `ProxyRules::Apply()` 拿它当
> `if (Matches(...)) UseDirectWithBypassedProxy()`。于是 `reverse_bypass=true` 下**命中规则 ⇒ `false`(走 edge)、未命中 ⇒ `true`(DIRECT)**。
> 直接断言 `Matches()` 极性极易写反,而且**漏传 `reverse` 反而会让错误的断言变绿**(本计划初稿的注释把这条说反了)。
> 改为断言我们真正关心的语义:**这个 URL 到底走不走隧道**。

```cpp
// Asserts the semantics we actually care about, via the same entry point the
// network stack uses: does this URL end up on the edge proxy, or DIRECT?
::testing::AssertionResult GoesThroughTunnel(
    const network::mojom::CustomProxyConfigPtr& config, std::string_view url) {
  net::ProxyInfo info;
  config->rules.Apply(GURL(std::string(url)), &info);
  return info.is_direct()
             ? ::testing::AssertionFailure() << url << " went DIRECT"
             : ::testing::AssertionSuccess();
}

TEST(TeleportTunnelProxyConfigTest, WildcardCoversBothRootAndSubdomain) {
  std::vector<RoutableOrigin> origins;
  origins.push_back({"corp.example", 443, /*include_subdomains=*/true, false});
  auto config = BuildTunnelProxyConfig("edge.d", 443, origins, "tok");

  EXPECT_TRUE(GoesThroughTunnel(config, "https://a.corp.example/"));
  EXPECT_TRUE(GoesThroughTunnel(config, "https://corp.example/"));   // the root
  EXPECT_FALSE(GoesThroughTunnel(config, "https://evilcorp.example/"));
}

TEST(TeleportTunnelProxyConfigTest, NonWildcardEmitsHostOnlyRule) {
  std::vector<RoutableOrigin> origins;
  origins.push_back({"app.corp", 8443, /*include_subdomains=*/false, false});
  auto config = BuildTunnelProxyConfig("edge.d", 443, origins, "tok");

  // Capture is by host, port-agnostic (design §3.1): an unregistered port must
  // still reach the edge so it produces a denial record that origin discovery
  // can surface. Narrowing here would make misconfiguration silent.
  EXPECT_TRUE(GoesThroughTunnel(config, "https://app.corp:8443/"));
  EXPECT_TRUE(GoesThroughTunnel(config, "https://app.corp:9443/"));
  EXPECT_FALSE(GoesThroughTunnel(config, "https://sub.app.corp/"));
}

TEST(TeleportTunnelProxyConfigTest, UnlistedHostsGoDirect) {
  std::vector<RoutableOrigin> origins;
  origins.push_back({"app.corp", 443, false, false});
  auto config = BuildTunnelProxyConfig("edge.d", 443, origins, "tok");

  EXPECT_FALSE(GoesThroughTunnel(config, "https://www.example.com/"));
}
```

- [ ] **Step 3: 跑测试确认失败**

```bash
autoninja -C out/mac/arm64/dev teleport_unittests
```
Expected: 编译失败(签名不匹配)。

- [ ] **Step 4: 实现**

```cpp
network::mojom::CustomProxyConfigPtr BuildTunnelProxyConfig(
    std::string_view edge_host,
    uint16_t edge_port,
    const std::vector<RoutableOrigin>& routable_origins,
    std::string_view cnf_token) {
  // …(single_proxies / reverse_bypass / headers 段保持原样)…
  for (const RoutableOrigin& origin : routable_origins) {
    if (origin.include_subdomains) {
      // BOTH rules are required, not belt-and-braces: matching is
      // base::MatchPattern glob, and "*.corp.example" demands a literal dot
      // before the suffix, so it does NOT match "corp.example" itself.
      // Emitting only the wildcard trades "the whole wildcard domain is lost"
      // for "the wildcard domain's root is lost" — the same C-2 defect, quieter.
      rules.bypass_rules.AddRuleFromString(base::StrCat({"*.", origin.host}));
    }
    rules.bypass_rules.AddRuleFromString(origin.host);
  }
  // …
}
```

- [ ] **Step 5: 跑测试确认通过**

```bash
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportTunnelProxyConfig*'
```
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add docs/verification/2026-08-16-wildcard-matching.md \
        src/browser/enterprise/teleport_tunnel_logic.h \
        src/browser/enterprise/teleport_tunnel_logic.cc \
        src/browser/enterprise/teleport_tunnel_logic_unittest.cc
git commit -m "feat(tunnel): emit both wildcard and root rules for include_subdomains

base::MatchPattern requires a literal dot before the suffix, so '*.corp.example'
never matches 'corp.example'. One rule would lose the wildcard domain's root."
```

---

## Task 3: host 校验(性质 P3)

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_logic.cc`
- Test: `src/browser/enterprise/teleport_tunnel_logic_unittest.cc`
- Create: `docs/verification/2026-08-16-rule-grammar.md`

**Interfaces:**
- Consumes: `ParseRoutableOrigins`(Task 1)
- Produces: 校验并入 `ParseRoutableOrigins`,被拒条目进 `skipped`。

- [ ] **Step 1: 验证规则语法(承重验证步)**

```bash
CR="$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
sed -n '100,130p' "$CR/net/proxy_resolution/proxy_host_matching_rules.cc"   # ParseRule
sed -n '25,105p' "$CR/net/base/scheme_host_port_matcher_rule.cc"           # FromUntrimmedRawString
sed -n '138,152p' "$CR/net/proxy_resolution/proxy_host_matching_rules.cc"  # operator=
grep -n "kPrintRuleListDelimiter\|kParseRuleListDelimiterList" "$CR/net/base/scheme_host_port_matcher.h"
sed -n '25,45p' "$CR/url/url_canon_host.cc"                                # kHostCharLookup
grep -n -A10 "bool IPAddress::AssignFromIPLiteral" "$CR/net/base/ip_address.cc"
grep -n -A10 "IsPubliclyRoutable\|bool IPAddress::IsLoopback" "$CR/net/base/ip_address.cc"
grep -n -A8 "IsLocalHostname" "$CR/net/base/url_util.cc"
```

写入 `docs/verification/2026-08-16-rule-grammar.md`,必须逐条回答:
1. `AddRuleFromString` 实际调用链是什么?`ParseRule` 是否是 `FromUntrimmedRawString` 的**超集**(含 `<local>` / `<-loopback>`)?
2. 哪些字符会把一条 host 变成**另一种规则**?(至少覆盖 `/` → IP 段、`:` → 端口限定、`://` → scheme 限定、`<`/`>` → 特殊语法)
3. **`ProxyHostMatchingRules::operator=` 是否是 `ParseFromString(rhs.ToString())`?** `ToString` 用什么分隔、`ParseFromString` 按什么切?⇒ 含 `;` 或 `,` 的 host 在**首次拷贝**时会发生什么?前导点片段会被映射成什么?
4. `GURL("https://"+host)` 往返后与输入逐字节比较,能否拒掉 IDN / 大写 / **尾点** / 非规范 IP 拼法?**尾点单独确认**——GURL 只对 IP 字面量去尾点,普通域名保留。
5. `IsLoopback()` / `IsLinkLocal()` / `IsZero()` 的覆盖面;`IsPubliclyRoutable()` 是否更合适;`localhost` 这类**名字**能否被 `AssignFromIPLiteral` 命中(预期:否)。
6. 公共后缀:两标签规则能否挡住 `co.uk` / `github.io` / `s3.amazonaws.com`(预期:**不能**)。

**结论直接决定 Step 2 的负例清单与 Step 4 的判据。若与本任务预期不符,以验证结论为准并在文档中注明。**

- [ ] **Step 2: 写失败测试**

```cpp
TEST(TeleportRoutableOriginValidationTest, RejectsRuleGrammarInjection) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"corp.example;.com","port":443},
        {"host":"a,b.com","port":443},
        {"host":"0.0.0.0/0","port":443},
        {"host":"corp.example:8080","port":443},
        {"host":"https://x","port":443},
        {"host":"<local>","port":443},
        {"host":"<-loopback>","port":443},
        {"host":"*","port":443},
        {"host":".corp.example","port":443}
      ])"),
      &skipped);

  EXPECT_TRUE(out.empty());
  EXPECT_EQ(skipped.size(), 9u);
}

TEST(TeleportRoutableOriginValidationTest, RejectsNonCanonicalAndLocalHosts) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"Corp.Example","port":443},
        {"host":"corp.example.","port":443},
        {"host":"内网.example","port":443},
        {"host":"127.1","port":443},
        {"host":"0x7f.0.0.1","port":443},
        {"host":"2130706433","port":443},
        {"host":"localhost","port":8080},
        {"host":"sub.localhost","port":8080},
        {"host":"10.0.0.5","port":8080},
        {"host":"169.254.1.1","port":80}
      ])"),
      &skipped);

  EXPECT_TRUE(out.empty());
  EXPECT_EQ(skipped.size(), 10u);
}

TEST(TeleportRoutableOriginValidationTest, RejectsPublicSuffixWildcards) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"com","port":443,"include_subdomains":true},
        {"host":"co.uk","port":443,"include_subdomains":true},
        {"host":"github.io","port":443,"include_subdomains":true}
      ])"),
      &skipped);

  EXPECT_TRUE(out.empty());
  EXPECT_EQ(skipped.size(), 3u);
}

TEST(TeleportRoutableOriginValidationTest, AcceptsLegitimateIntranetHosts) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"app.corp.example","port":443},
        {"host":"corp.example","port":443,"include_subdomains":true},
        {"host":"adminer.corp.example","port":8080}
      ])"),
      &skipped);

  EXPECT_EQ(out.size(), 3u);
  EXPECT_TRUE(skipped.empty());
}
```

> 若 Step 1 的结论表明某条负例实际**不会**被对应判据拦住(例如公共后缀需要 registry 判定而非标签计数),按结论调整判据而非删测试。

- [ ] **Step 3: 跑测试确认失败**

```bash
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportRoutableOriginValidation*'
```
Expected: FAIL(条目被放行)。

- [ ] **Step 4: 实现校验**

在 `ParseRoutableOrigins` 的 host 取出之后、写入 `out` 之前插入,判据以 Step 1 结论为准,骨架:

```cpp
// This check is the compensation for a deliberate trust-domain downgrade: the
// routing table used to ride the signature-anchored policy channel and now
// rides an unsigned JSON body (see TD-TUNNEL-BIND-RESPONSE-UNSIGNED). It is a
// coarse fail-safe, not a policy engine.
//
// AddRuleFromString is a GRAMMAR, not a hostname setter — and worse,
// ProxyHostMatchingRules::operator= round-trips through
// ParseFromString(ToString()), so a host carrying a list delimiter splits into
// two rules on the first copy and a leading-dot fragment is promoted to a
// wildcard. Reject the grammar's metacharacters outright.
std::optional<std::string> RejectHost(const std::string& host,
                                      bool include_subdomains);
```

`RejectHost` 返回拒绝原因(`std::nullopt` = 通过),按 Step 1 结论实现,至少覆盖:分隔符与元字符集合、GURL 往返逐字节相等、尾点、IP 字面量的可路由性判定、基于名字的 localhost 族、以及 `include_subdomains` 的注册域判定。

- [ ] **Step 5: 跑全部逻辑测试确认通过**

```bash
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportRoutableOrigin*:TeleportTunnelProxyConfig*'
```
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add docs/verification/2026-08-16-rule-grammar.md \
        src/browser/enterprise/teleport_tunnel_logic.cc \
        src/browser/enterprise/teleport_tunnel_logic_unittest.cc
git commit -m "feat(tunnel): reject rule-grammar injection in routing table entries

AddRuleFromString parses a grammar, and ProxyHostMatchingRules::operator= runs
ParseFromString(ToString()), so a host containing a list delimiter splits into
two rules on first copy with a leading-dot fragment promoted to a wildcard."
```

---

## Task 4: edge / gate 排除(性质 P2)

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_logic.h/.cc`
- Test: `src/browser/enterprise/teleport_tunnel_logic_unittest.cc`
- Create: `docs/verification/2026-08-16-edge-gate-coverage.md`

**Interfaces:**
- Produces: `ParseRoutableOrigins` 增加 `std::string_view edge_host, std::string_view gate_host` 两个参数(**host-only,不带端口**)。

- [ ] **Step 1: 验证覆盖语义**

```bash
CR="$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
sed -n '10,30p' "$CR/base/strings/pattern.h"
grep -n -A20 "bool MatchPattern" "$CR/base/strings/pattern.cc"
```

在 `docs/verification/2026-08-16-edge-gate-coverage.md` 回答:
1. `base::MatchPattern` 的 `*` 是否**跨点**?`?` 与 `\` 的语义?
2. 给定条目 host `H` 与 `include_subdomains`,产出规则 `*.H` 与 `H`;**当 gate 为 `gate.tp.D`、H 为 `D` 时,`*.D` 是否匹配 `gate.tp.D`?**(预期:**是**——所以判据不能是「直接子域」)
3. 结论:排除判据的正确形式是什么?(预期等价于 `MatchPattern(gate_host, "*." + H)`,而非标签计数)

- [ ] **Step 2: 写失败测试**

```cpp
TEST(TeleportRoutableOriginExclusionTest, ExcludesEdgeAndGateExactly) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"gate.d.example","port":443},
        {"host":"edge.d.example","port":443},
        {"host":"GATE.D.EXAMPLE","port":443},
        {"host":"app.d.example","port":443}
      ])"),
      "edge.d.example", "gate.d.example", &skipped);

  ASSERT_EQ(out.size(), 1u);
  EXPECT_EQ(out[0].host, "app.d.example");
  EXPECT_EQ(skipped.size(), 3u);
}

// The self-lock vector: a wildcard over the deployment domain covers the gate,
// so bind's own POST would be routed into the edge — which needs a cnf token
// bind has not obtained yet. Host equality cannot see this; coverage can.
TEST(TeleportRoutableOriginExclusionTest, ExcludesWildcardCoveringGate) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"d.example","port":443,"include_subdomains":true}
      ])"),
      "edge.tp.d.example", "gate.tp.d.example", &skipped);

  EXPECT_TRUE(out.empty());
  ASSERT_EQ(skipped.size(), 1u);
  EXPECT_NE(skipped[0].reason.find("gate"), std::string::npos);
}
```

- [ ] **Step 3: 跑测试确认失败**

Expected: 编译失败(参数不匹配)。

- [ ] **Step 4: 实现**

```cpp
// Routing either the edge or the gate through the tunnel self-locks the client.
// Equality is not enough: matching is glob and '*' crosses dots, so ANY wildcard
// at or above the deployment domain captures the gate — moving the gate deeper
// does not help. Compare on coverage, after normalising both sides to host-only,
// ASCII-lowercased, trailing-dot-stripped.
//
// KNOWN COST: hitting the coverage branch drops the ENTIRE wildcard entry, so
// every app under that domain loses routing. Chromium's rule syntax has no
// negation, so "route *.D except gate/edge" is inexpressible. The primary
// defence is therefore the server's write path refusing such registrations;
// this is the fail-safe half.
bool CoversReservedHost(const RoutableOrigin& origin, std::string_view reserved);
```

- [ ] **Step 5: 跑测试确认通过 + 更新全部既有调用方**

签名从 2 参变 4 参,以下**全部**要改,漏一处即编译失败:
- `teleport_tunnel_service.cc` 的调用点 —— 用既有的 `DomainHostOnlyFor(EdgeHost())` / `DomainHostOnlyFor(GateHost())`(**注意去端口**,这两个 helper 已经做了);
- Task 1 的三个 `TeleportRoutableOriginParseTest`;
- Task 3 的四个 `TeleportRoutableOriginValidationTest`;
- Task 5 的两个 `TeleportRoutableOriginDedupTest`(若已落地)。

统一传测试常量 `kTestEdgeHost = "edge.d.example"` / `kTestGateHost = "gate.d.example"`,在测试文件顶部定义一次。

```bash
autoninja -C out/mac/arm64/dev teleport_unittests chrome && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportRoutableOrigin*'
```
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git commit -am "feat(tunnel): exclude edge/gate hosts by coverage, not equality

A wildcard at or above the deployment domain matches the gate under glob
semantics, which would route bind's own request into the edge and permanently
self-lock the tunnel."
```

---

## Task 5: 去重与 `include_subdomains` 并集(性质 P6)

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_logic.cc`
- Test: `src/browser/enterprise/teleport_tunnel_logic_unittest.cc`

- [ ] **Step 1: 写失败测试**

```cpp
TEST(TeleportRoutableOriginDedupTest, DeduplicatesAndUnionsWildcardFlag) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"sso.corp.example","port":443},
        {"host":"sso.corp.example","port":443,"include_subdomains":true},
        {"host":"sso.corp.example","port":443}
      ])"),
      "edge.d.example", "gate.d.example", &skipped);

  ASSERT_EQ(out.size(), 1u);
  // Two apps may legitimately share a host while disagreeing on the flag —
  // nothing pins it the way scheme consistency is pinned. First-wins would
  // silently strand the wildcard app's subdomains, so the flag is unioned.
  EXPECT_TRUE(out[0].include_subdomains);
  EXPECT_TRUE(skipped.empty());
}

TEST(TeleportRoutableOriginDedupTest, DistinctPortsAreDistinctEntries) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"app.corp.example","port":443},
        {"host":"app.corp.example","port":8443}
      ])"),
      "edge.d.example", "gate.d.example", &skipped);
  EXPECT_EQ(out.size(), 2u);
}
```

- [ ] **Step 2: 跑测试确认失败**

Expected: 第一个 FAIL(得到 3 条)。

- [ ] **Step 3: 实现** —— 用 `base::flat_map<std::pair<std::string, uint16_t>, size_t>` 记录首次出现下标,重复时 `include_subdomains |= …`、`blocked |= …`,顺序保留。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git commit -am "feat(tunnel): dedupe routing entries and union include_subdomains"
```

---

## Task 6: `TeleportTunnelService` 接入 bind 响应

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_service.h/.cc`
- Test: `chrome/test/BUILD.gn` 侧的既有 `TeleportTunnelBindClientTest`(经 `patches/chrome/test/BUILD.gn.patch`)

**Interfaces:**
- Consumes: `ParseRoutableOrigins`(Task 1–5)
- Produces: `routable_origins_` 由响应填充;`skipped_entries_`、`routes_stale_`、`routes_truncated_`、`routes_dropped_`、`routes_digest_`、`token_expires_at_` 成员供 Task 11 的诊断页读取。

- [ ] **Step 1: 写失败测试**(加进既有 fixture 文件)

```cpp
TEST_F(TeleportTunnelBindClientTest, UsesRoutingTableFromBindResponse) {
  SetBindResponse(R"({
    "tunnel_token":"tok",
    "expires_in":600,
    "routable_origins":[{"host":"app.corp.example","port":443}],
    "routes_digest":"abc"
  })");
  StartAndRunUntilIdle();

  EXPECT_THAT(service()->GetRoutableOriginsForTesting(),
              ElementsAre(FieldsAre("app.corp.example", 443, false, false)));
}

TEST_F(TeleportTunnelBindClientTest, MissingRoutingTableYieldsEmptyNoFallback) {
  SetBindResponse(R"({"tunnel_token":"tok","expires_in":600})");
  StartAndRunUntilIdle();

  EXPECT_TRUE(service()->GetRoutableOriginsForTesting().empty());
  // No fallback path exists: the pre-existing policy-derived derivation was
  // deleted outright (development phase, zero real users).
  EXPECT_TRUE(service()->RoutesUnavailableForTesting());
}

TEST_F(TeleportTunnelBindClientTest, NullRoutingTableIsAProtocolViolation) {
  SetBindResponse(R"({"tunnel_token":"tok","expires_in":600,"routable_origins":null})");
  StartAndRunUntilIdle();
  EXPECT_TRUE(service()->RoutesUnavailableForTesting());
}

TEST_F(TeleportTunnelBindClientTest, EmptyArrayIsDistinctFromMissing) {
  SetBindResponse(R"({"tunnel_token":"tok","expires_in":600,"routable_origins":[],"routes_digest":"z"})");
  StartAndRunUntilIdle();
  EXPECT_TRUE(service()->GetRoutableOriginsForTesting().empty());
  EXPECT_FALSE(service()->RoutesUnavailableForTesting());
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
autoninja -C out/mac/arm64/dev unit_tests && \
  ./out/mac/arm64/dev/unit_tests --gtest_filter='TeleportTunnelBindClientTest.*'
```

- [ ] **Step 3: 实现** —— `OnTunnelToken` 改为解析完整响应体(`tunnel_token` / `expires_in` / `routable_origins` / `routes_digest` / 三个标志),调用 `ParseRoutableOrigins`,填充成员后 `PushConfig()`。**保留 `null` 与缺字段同处理、空数组单独记号**的区分。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git commit -am "feat(tunnel): populate the routing table from the bind response"
```

---

## Task 7: 启动与唤醒

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_service.h/.cc`
- Create: `docs/verification/2026-08-16-bind-preconditions.md`

- [x] **Step 1: 验证可用信号(承重验证步)—— 已完成,结论见 `docs/verification/2026-08-16-bind-preconditions.md`**

> **本步的原始命令清单里有一条路径是错的**(`components/enterprise/.../certificate_provisioning_service_factory.cc` 不存在,真实路径在 `chrome/browser/` 下)。因为没有 `set -e`,照抄会**静默跳过最关键的那份证据**——与「引了半句被截断的注释」是同一种失败模式。
>
> **今后所有验证步的命令块一律以 `set -euo pipefail` 开头。**

**结论要点:**

| 问题 | 结论 |
|---|---|
| `PrefChangeRegistrar::Add` 对初始值触发? | **否**,纯注册。而本 service 是从 `ConfigureNetworkContextParamsInternal` 里**懒创建**的,完全可能生在策略落地**之后** ⇒ **读值门是必需的** |
| `GetManagedIdentity` 的完整语义 | 三句话,第二句反转第一句:*"Otherwise, run it with `std::nullopt`."* 策略未启用时**同步**跑 nullopt 并返回,**此后永不再触发** |
| 回调内重调安全吗? | **不安全(新发现)**。`OnFinishedProvisioning` 对成员 `pending_callbacks_` range-for 遍历后无条件 `clear()`;在「策略已开但拿不到 identity」这个**恰好会让人重试**的场合重调会 `push_back` 进正在遍历的容器(概率性 UAF),且新回调会被那次 `clear()` 静默丢弃 |
| 单测能拿到实例吗? | **不能**,factory 的 `ServiceIsNULLWhileTesting()` 为 true |
| 有没有别的「证书就绪」信号? | **没有(关键负面结论)**。`CertDatabase::OnClientCertStoreChanged` 在这条供给路径上从不触发(且 macOS 侧忽略同进程事件,身份存在 LevelDB 而非 Keychain);identity 字典 pref **在本构建里没有写入方**(特性默认关闭,又被我们的 `disable_fieldtrial_testing_config = true` 钉死);provisioning service 上**没有** observer 接口 |

**因此设计要接受一个诚实边界:「证书就绪」不可观测,只能由退避兜底。** 唤醒信号只能覆盖**策略**这一半。这必须写进实现注释,否则下一个人会重复这轮的搜索。

**两条与现存代码有关的发现,本任务顺带修:**

1. **`BeginBind()` 重新赋值 `loader_` 会静默取消在途请求。** `simple_url_loader.h` 原文:*"Deleting the SimpleURLLoader before the callback is invoked will result in cancelling the request, and **the callback will not be called**."* ⇒ `OnTunnelToken` / `OnBindFailed` 都不会跑 ⇒ **退避不被告知、刷新环不重新武装**,隧道就此静止。今天不出事只是因为三个调用点碰巧不重叠——**本任务引入唤醒信号后就会重叠**,必须加 in-flight 守卫。
2. **读值门读两个 pref,却只观察一个。** `kManagedAutoSelectCertificateForUrls` 与 `kPolicyRecoveryToken` 都被读,但只有前者进了 `pref_change_registrar_`。首次纳管路径由注册器显式调 `Start()` 兜住,所以缺口窄;但既然本任务在重建这套状态机,**两个都观察**是更便宜且更正确的做法。

**另有一处代码注释是错的**(本任务顺带改):`teleport_oidc_inplace_registrar.cc` 与 `teleport_tunnel_service.h` 都断言此刻设备证书「已供给」。实际供给要等策略 pref 落地后再走一次 DMServer 往返,`Start()` 严格早于证书可用。

**唤醒组合(实现按此)**:读值门 = 状态机 idle **且** AutoSelect 非空 **且** `kPolicyRecoveryToken` 非空;观察者 = 这两个 pref;**不设证书判据**(不可观测);三态机 + pending 位;进入 in-flight 时**显式停掉** `retry_timer_`(否则已武装的定时器会在稍后杀掉唤醒发出的请求);自动唤醒设最小间隔。

一条有利的负面结论:无 WebContents 的取消路径**不会**往 `SSLClientAuthCache` 写「不发证书」的记录,所以退避重试不会被毒化。

- [ ] **Step 2: 写失败测试**

```cpp
TEST_F(TeleportTunnelBindClientTest, DoesNotAutoStartBeforePreconditionsReady) {
  SetAutoSelectPolicy({});          // managed store, empty
  MarkProfileEnrolled();
  CreateService();
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 0);
}

TEST_F(TeleportTunnelBindClientTest, WakeUpShortCircuitsBackoff) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  FailNextBind();
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  // A pending backoff must not delay a retry once a precondition lands.
  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 2);
}

// Reassigning loader_ destroys the in-flight SimpleURLLoader, and per its
// header "the callback will not be called" — so OnTunnelToken/OnBindFailed
// never run, the backoff is never informed, and the refresh loop is never
// re-armed. Today nothing overlaps by luck; adding wake-ups makes it overlap.
TEST_F(TeleportTunnelBindClientTest, WakeUpDoesNotCancelInFlightBind) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  StallNextBind();
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 1);   // still one: the in-flight bind was not aborted

  CompleteStalledBindWithFailure();
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 2);   // pending wake-up fires immediately after
}

// The read-gate reads two prefs but the registrar observed only one. The
// enrollment registrar's explicit Start() covers the common path, so the gap is
// narrow — but observing both is cheaper than reasoning about when it isn't.
TEST_F(TeleportTunnelBindClientTest, EnrollmentTokenLandingAlsoWakesUp) {
  SetAutoSelectPolicy({kGateEntry});   // policy first
  CreateService();
  RunUntilIdle();
  ASSERT_EQ(bind_attempts(), 0);       // not enrolled yet

  MarkProfileEnrolled();               // DM token pref lands second
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 1);
}

// Entering in-flight must stop an armed retry timer, or it fires later and
// cancels the request the wake-up just issued.
TEST_F(TeleportTunnelBindClientTest, EnteringInFlightStopsTheRetryTimer) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  FailNextBind();
  StartAndRunUntilIdle();
  ASSERT_TRUE(RetryTimerIsRunning());

  StallNextBind();
  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});   // wake-up
  RunUntilIdle();
  EXPECT_FALSE(RetryTimerIsRunning());
}
```

> 注:策略 pref 必须经 **managed store** 写入(`GetTestingPrefService()->SetManagedPref`),用户 store 会触发上游 `content_settings::PolicyProvider` 的 DCHECK 崩溃——既有用例踩过一次。

- [ ] **Step 3: 跑测试确认失败**

- [ ] **Step 4: 实现** —— 按 Step 1 结论接线:读值门 + 可用唤醒源;状态机三态(idle / in-flight / in-flight+pending);自动唤醒设最小间隔;`BeginBind()` 加 in-flight 守卫(今天没有,新 loader 赋值会取消在途请求)。

- [ ] **Step 5: 跑测试确认通过**

- [ ] **Step 6: 提交**

```bash
git commit -am "feat(tunnel): gate startup on read preconditions, wake retries on readiness"
```

---

## Task 8: CONNECT 归因的上游 patch

**Files:**
- Create/Modify: `patches/net/base/proxy_delegate.h.patch` 等(清单由 Step 1 产出)
- Create: `docs/verification/2026-08-16-connect-attribution-patch.md`

- [ ] **Step 1: 验证签名与实现者清单(承重验证步)**

```bash
CR="$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
sed -n '100,120p' "$CR/net/base/proxy_delegate.h"
grep -rn "OnTunnelHeadersReceived" "$CR/net" "$CR/services/network" "$CR/content" "$CR/components" --include=*.h --include=*.cc --include=*.mojom
git -C "$CR" show --stat be430f1 2>/dev/null || git log --oneline -1 --all --grep="forward-proxy header injection"
find out/mac/arm64/dev/obj -name "*prefetch_proxy_configurator*" -o -name "*cronet*" | head
```

在 `docs/verification/2026-08-16-connect-attribution-patch.md` 回答:
1. 现有虚函数的**完整签名**(**参数个数、是否带异步回调、返回类型**)。上一轮把回调参数漏掉了,默认实现就转发不出去;
2. 全部调用点及各自**是否真有目的地可取**;
3. 全部实现者清单及它们**是否在我们的构建里**(用 `out/` 里的 `.o` 判定,不靠猜);
4. mojom 侧接口的全部实现者;
5. `be430f1` 的实际 patch 文件清单(作为非破坏性新增的形状参照)。

- [ ] **Step 2: 应用 overlay 并改上游**

```bash
cd /Users/liulichao/workspace/teleport/.worktrees/tunnel-webapp-compat
python scripts/apply_patches.py
```
按 Step 1 结论直接编辑 `chromium/src/` 下对应文件:`net::ProxyDelegate` **加一个非破坏性新虚函数**(带默认实现转发给旧的,旧的保留为纯虚);调用点改调新的;`NetworkServiceProxyDelegate` 与 mojom 跟进。

- [ ] **Step 3: 构建验证**

```bash
set -euo pipefail
cd "$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
autoninja -C out/mac/arm64/dev chrome services_unittests net_unittests teleport_unittests
```

> **只构建 `chrome` 证不出「未触及 mock/fake」**(初稿的验收标准是无效的):那些 target 根本不在 `chrome` 的依赖里,编译 `chrome` 绿了也说明不了它们没被破坏。必须把 `services_unittests`(mojom 实现者)、`net_unittests`(`test_proxy_delegate` / `fake_proxy_delegate` / 全部调用点单测)一并构建。

Expected: 四个 target 全部编译通过。这才是「`ProxyDelegate` 侧非破坏」的真实验收——**9 个实现者里 8 个在我们构建里,非破坏形状下应当一个都不用改**(唯一在外的是 cronet,`obj/` 里零文件、`gn refs` 亦无命中)。

- [ ] **Step 4: 重生成 patch 并验幂等**

```bash
set -euo pipefail
cd /Users/liulichao/workspace/teleport/.worktrees/tunnel-webapp-compat
for f in net/base/proxy_delegate.h \
         net/http/http_proxy_client_socket.cc \
         net/spdy/spdy_proxy_client_socket.cc \
         net/quic/quic_proxy_client_socket.cc \
         services/network/network_service_proxy_delegate.h \
         services/network/network_service_proxy_delegate.cc \
         services/network/public/mojom/network_context.mojom \
         content/browser/preloading/prefetch/prefetch_proxy_configurator.h \
         content/browser/preloading/prefetch/prefetch_proxy_configurator.cc \
         services/network/network_service_proxy_delegate_unittest.cc; do
  git -C chromium/src diff -- "$f" > "patches/$f.patch"
done
python scripts/apply_patches.py
```
Expected: 幂等,无冲突。

**清单相对初稿的三处修正**(验证结论):

- 初稿漏了 `prefetch_proxy_configurator.{h,cc}` 与 `network_service_proxy_delegate_unittest.cc` —— mojom 侧改方法签名是**强制破坏性**的,这两个实现者必须同批改;
- `prefetch_proxy_configurator` 的真实路径含 **`preloading/`** 这一层(`content/browser/preloading/prefetch/`),不是 `chrome/browser/prefetch/`;
- **第 4 个调用点 `quic_proxy_datagram_client_socket.cc` 不动**:它没有 `HostPortPair`,真目的地在上一帧 `quic_session_pool.cc` 的 `key.server_id()`,只编码在 `url_` 路径段里。MASQUE 不在隧道路径上,改它是自造风险。

**另一处必须知道的先例更正**:`be430f1` 的 mojom 改动是**给 struct 加字段**,不是改 interface 方法签名——**它不能作为 mojom 侧的先例**。它只对 `ProxyDelegate` 侧的非破坏性形状有参考价值。

- [ ] **Step 5: 提交**

```bash
git add docs/verification/2026-08-16-connect-attribution-patch.md patches/
git commit -m "feat(tunnel): carry the CONNECT endpoint to the proxy delegate

Non-breaking: the existing pure virtual stays and the new overload's default
body forwards to it, so no other implementer moves."
```

---

## Task 9: observer 绑定与按代理链过滤

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_service.h/.cc`

- [ ] **Step 1: 验证 observer 是否有 IsInProxyConfig 门控**

```bash
CR="$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
sed -n '155,200p' "$CR/services/network/network_service_proxy_delegate.cc"
```
Expected 结论:`OnTunnelHeadersReceived` 的转发**没有** `IsInProxyConfig` 门控(它的两个兄弟方法有)⇒ **客户端必须自己按代理链过滤**,否则会把该 network context 上任何代理的 CONNECT 当成隧道结果展示。写入 Task 8 的验证文档。

- [ ] **Step 2: 写失败测试**

```cpp
TEST_F(TeleportTunnelBindClientTest, RecentConnectsIgnoreOtherProxyChains) {
  StartAndRunUntilIdle();
  service()->OnTunnelHeadersReceivedForTesting(OtherProxyChain(), Endpoint("x.corp"), 403);
  service()->OnTunnelHeadersReceivedForTesting(EdgeProxyChain(), Endpoint("app.corp"), 403);

  auto recents = service()->GetRecentConnectsForTesting();
  ASSERT_EQ(recents.size(), 1u);
  EXPECT_EQ(recents[0].authority, "app.corp");
}
```

- [ ] **Step 3–5:** 跑测试确认失败 → 实现(`BindProxyConfigClient` 同处 stamp observer receiver;收到通知先比对代理链,再入固定长度环形缓冲)→ 跑测试确认通过。

- [ ] **Step 6: 加重推谓词的回归锚**

`BindProxyConfigClient` 是 observer 与 config client **同处** stamp 的地方,本任务正在改它——顺手把重推谓词钉住,防止未来一次「清理无用字段」把已修的 bug 装回去。

```cpp
// Regression anchor: the re-push predicate must stay `!cnf_token_.empty()`.
// have_pushed_config_ is NOT usable here — if the first PushConfig ran before
// any receiver was bound it silently no-op'd and left the flag false, so the
// old guard never re-pushed and tunnel routing was never applied. The flag
// survives only as the backing store for the diagnostics page's "config
// pushed" row.
TEST_F(TeleportTunnelBindClientTest, NetworkServiceRestartRepushesOnTokenPresence) {
  StartAndRunUntilIdle();
  ASSERT_TRUE(HasToken());
  SimulateFirstPushBeforeReceiverBound();   // leaves have_pushed_config_ false
  ResetPushCount();

  SimulateNetworkServiceRestart();
  RunUntilIdle();
  EXPECT_EQ(push_count(), 1);               // re-pushed despite the false flag
}
```

跑测试确认通过。

- [ ] **Step 7: 提交**

```bash
git commit -am "feat(tunnel): record CONNECT results, filtered to our edge proxy chain

Also pins the network-service re-push predicate to !cnf_token_.empty() with a
regression test; have_pushed_config_ remains only as the diagnostics backing."
```

---

## Task 10: `teleport://tunnel` WebUI 骨架

**Files:**
- Create: `src/browser/webui/tunnel.mojom`、`teleport_tunnel_ui.{h,cc}`、`src/browser/resources/tunnel/*`
- Modify: 多个 `patches/`
- Create: `docs/verification/2026-08-16-webui-wiring.md`

- [x] **Step 1: 验证接线清单(承重验证步)—— 已完成,结论见 `docs/verification/2026-08-16-webui-wiring.md`**

> **本步的原始命令清单是错的,已修正。** 它只 grep 了 5 个 patch,漏掉两个**只在真机炸、编译全绿**的:
> - `patches/chrome/browser/ui/webui/chrome_web_ui_configs.cc.patch`(注册 `WebUIConfig`)—— 漏 = `teleport://tunnel` **404**;
> - `patches/chrome/browser/chrome_browser_interface_binders_webui_parts_desktop.cc.patch`(绑 Mojo `PageHandlerFactory`)—— 漏 = 页面**永远停在 loading**。
>
> 正确的枚举方式不是列举已知文件,而是:`grep -rln "enroll\|Enroll" patches/` 全量捞。

**结论要点(实现时以验证文档的 20 项 checklist 为准):**

| 项 | 结论 |
|---|---|
| patch 总数 | **7 个**,不是 6 个 |
| lit patch | 改 `ts_library("build_ts")` 的 **`visibility`** 列表;该 target **没有** `extra_deps` 变量 |
| `webui/BUILD.gn.patch` | **3 处**编辑:新增 `import(mojom.gni)`、`mojom()`+`source_set()`、以及把页面 target 插进 `source_set("configs")` 的 deps |
| `chrome/browser/BUILD.gn.patch` | **有** `group("browser_generated_files")` 编辑;存在理由是 interface binder 编在 `//chrome/browser/ui`,只能经 `browser_public_dependencies` 拿 mojom 头 |
| `resources/*/BUILD.gn` | 9 个变量;用 `ts_files`(手写 `*_app.html.ts`)**非** `web_component_files`;`ts_composite=true` 是 lit visibility 白名单生效的前提 |
| grit id | **不是**「任意未用 id」——fake id 编码顺序结构,必须严格落在前后邻居的**开区间**内(enroll 占 `11800`,新页建议 `11900`);`META.sizes` 超限是硬失败 |
| `chrome_paks.gni.patch` | 碰 **2 个列表**(`sources` 与 `deps`),成对出现 |
| `src/BUILD.gn` | **不需要**改动;`teleport://` 重写与 `teleport-urls` 列表都是通用机制 |

**承重题的解法:走 `//teleport` 回调 seam(方案 A)。**

不能给 WebUI target 加 `//chrome/browser` 依赖——`//chrome/browser:core` 已 dep `webui:configs`,`configs` 又 dep 每个页面 target,加边即闭环,而本树 `gn check` 是开着的。

**本仓 enroll 页自己就是这么解的同一个问题**,直接照抄:`src/common/teleport_enroll_logic.h` 里三个 seam 的注释原文写着「the enroll handler lives in the //chrome/browser/ui/webui [target] ... so the WebUI target never reaches [into chrome/browser]」,注册点在 `src/browser/teleport_deployment_level4.cc`,调用点在 `teleport_enroll_ui.cc`。

零新增 GN 边,且能把 `TunnelStateSnapshot` 留在 `teleport_tunnel_logic` 里被 `teleport_unittests` 直接单测——正合本计划的 `TD-TUNNEL-UNITTEST-WIRING` 约束。

**seam 签名必须带 `content::BrowserContext*`**:`TeleportTunnelService` 是 per-profile,而 seam 是进程级全局。

- [ ] **Step 2: 按结论建文件并接线**,页面先只渲染一个静态标题。**接线以验证文档的 20 项 checklist 逐项打勾**,尤其那两个只在真机炸的 patch。

- [ ] **Step 3: 构建**

```bash
cd "$TELEPORT_CHROMIUM_ROOT/151.0.7922/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: 编译通过。

- [ ] **Step 4: 手动验证**

```bash
/Users/liulichao/workspace/teleport/build/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport &
```
访问 `teleport://tunnel`,确认页面加载且出现在 `teleport://teleport-urls` 列表里。

- [ ] **Step 5: 提交**

```bash
git add docs/verification/2026-08-16-webui-wiring.md src/browser/webui/ src/browser/resources/tunnel/ patches/
git commit -m "feat(tunnel): scaffold the teleport://tunnel diagnostics page"
```

---

## Task 11: 诊断页内容与手动重绑

**Files:**
- Modify: `src/browser/webui/tunnel.mojom`、`teleport_tunnel_ui.cc`、`src/browser/resources/tunnel/*`、`teleport_tunnel_service.{h,cc}`

- [ ] **Step 1: 写失败测试**

```cpp
TEST_F(TeleportTunnelBindClientTest, StateSnapshotNeverCarriesTheToken) {
  StartAndRunUntilIdle();
  const std::string json = service()->DebugStateAsJsonForTesting();
  EXPECT_EQ(json.find(kTestCnfToken), std::string::npos);
}

TEST_F(TeleportTunnelBindClientTest, RebindIsRejectedWhenNotEnrolledOrInFlight) {
  EXPECT_FALSE(service()->Rebind());          // not enrolled
  MarkProfileEnrolled();
  StallNextBind();
  StartAndRunUntilIdle();
  EXPECT_FALSE(service()->Rebind());          // in flight
}

TEST_F(TeleportTunnelBindClientTest, RebindIsRateLimited) {
  MarkProfileEnrolled();
  StartAndRunUntilIdle();
  ASSERT_TRUE(service()->Rebind());
  EXPECT_FALSE(service()->Rebind());          // within the minimum interval
  AdvanceClock(kRebindMinInterval);
  EXPECT_TRUE(service()->Rebind());
}
```

- [ ] **Step 2–4:** 跑测试确认失败 → 实现 `TunnelState` 全字段(bind 状态、时刻、原因、到期、下次刷新、生效列表、被跳过条目、服务端三标志、config 是否已推、最近 CONNECT 结果)+ `Rebind()` → 跑测试确认通过。

页面文案硬性要求:
- `blocked` 表述为「服务端标记该地址无路由行」,**不得**写「访问必定失败」;
- 空数组与「未下发」用**不同文案**,且空数组**不推断原因**。

- [ ] **Step 5: 真机验证**

按 `scripts/smoke_check.md` 起 dev 包,访问 `teleport://tunnel`,确认列表、跳过项、到期倒计时、CONNECT 状态码与 authority 显示正确;点「重新绑定」后时间戳更新。

- [ ] **Step 6: 提交**

```bash
git commit -am "feat(tunnel): show derived tunnel state and allow a manual rebind"
```

---

## Task 12: 响应体上限、IPv6 归宿与跨仓契约收口

**Files:**
- Modify: `src/browser/enterprise/teleport_tunnel_service.cc`
- Modify: `src/browser/enterprise/teleport_tunnel_logic.cc`(IPv6 判定)

- [ ] **Step 0: 决定 IPv6 origin 的归宿(spec 性质 P5)**

这是一条**已知会静默失配**的路径:服务端 `Route.Origin` 对 IPv6 主机形如 `[::1]:443`,投影用 `SplitHostPort` 拆开后 `host` 变成**不带方括号**的 `::1`;而 Task 3 的判据会因为它含 `:` 而拒掉 ⇒ **edge 路由得好好的,客户端永不路由**,正是本次改动宣称要关闭的那类漂移。

```bash
grep -n "JoinHostPort" ../fairyland/products/teleport/warden/internal/materializer/transform.go
grep -n -A6 "func NormalizeOrigin" ../fairyland/common/tunnelauthz/scope.go
grep -n "Origin.*host or host:port" ../fairyland/common/tunnelauthz/kv.go
```

二选一并写进 `docs/verification/2026-08-16-ipv6-origins.md`,**与 fairyland 计划对表**:
- **(a) 支持**:契约规定 IPv6 的 `host` 在 wire 上**带方括号**,客户端判据放行方括号形式并按 `AssignFromIPLiteral` 判可路由性;
- **(b) 不支持**:服务端投影侧**显式拒绝**并计入 drop 计数,客户端不必特判——关键是**服务端可见**,而不是两侧各自静默丢弃。

选 (b) 时须在 `docs/tech-debt.md` 记一条产品约束。

> ### ⚠️ 跨仓耦合:动这个常量前必须同批动服务端
>
> 服务端的 `Config.MaxBytes` 默认 **48 KiB**,是从**当前**的 `kMaxBindBodyBytes = 64 * 1024` 倒推的(留 JWT 余量),两边各由测试钉住。
>
> **把客户端上限提到 512KB 之前,必须同批把服务端的 `defaultMaxBytes` 一起提**,否则服务端会按一个早已过时的预算截断——表面上一切正常,实际是静默丢路由。这条耦合没有编译期保护,只有这段文字和两侧的测试。
>
> 服务端侧还发现:该配置原本**没有默认值**,而 **0 的语义是「全部截断」**——即「有效令牌 + 空表」,正是整个设计要避免的最坏状态,**一个零值配置就能直达**。客户端这侧改常量时,记得问同一个问题:新值有没有一个零值/未初始化路径能绕过去。

- [ ] **Step 1: 验证上限与闭合性**

```bash
grep -n "kMaxBindBodyBytes" src/browser/enterprise/teleport_tunnel_service.cc
grep -n "kMaxBoundedStringDownloadSize" "$TELEPORT_CHROMIUM_ROOT/151.0.7922/src/services/network/public/cpp/simple_url_loader.h"
```
计算最坏单条 JSON 字节数(host 上限 × 两个 flag × 5 位 port)× 服务端条目上限,确认**小于**客户端上限。结论写进 `docs/verification/2026-08-16-payload-budget.md`,并与 fairyland 计划的对应任务**对表**。

- [ ] **Step 2: 写失败测试** —— 构造一份刚好超过旧上限的响应,断言解析成功(而非整个请求失败)。

- [ ] **Step 3–4:** 提高常量 → 跑测试确认通过。

- [ ] **Step 5: 提交**

```bash
git commit -am "feat(tunnel): raise the bind response body cap to close the payload budget"
```

---

## Task 13: 全量回归与文档同步

- [ ] **Step 1: 跑全部测试**

```bash
cd "$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
autoninja -C out/mac/arm64/dev teleport_unittests unit_tests && \
  ./out/mac/arm64/dev/teleport_unittests && \
  ./out/mac/arm64/dev/unit_tests --gtest_filter='TeleportTunnel*'
cd /Users/liulichao/workspace/teleport/.worktrees/tunnel-webapp-compat && uv run pytest
```
Expected: 全绿。**任何跳过或失败都表示本计划未完成。**

- [ ] **Step 2: 更新 `CLAUDE.md`**

在「关键 gotcha」补一条:隧道路由表来自 bind 响应而非 `AutoSelectCertificateForUrls`;诊断页在 `teleport://tunnel`;纯逻辑必须留在 `teleport_tunnel_logic`。

- [ ] **Step 3: 更新 `docs/tech-debt.md`** —— 把 `TD-TUNNEL-BIND-RESPONSE-UNSIGNED` 的「当前补偿」段落对齐 Task 3 的**实际**判据。

- [ ] **Step 4: 提交**

```bash
git commit -am "docs: sync CLAUDE.md and tech-debt with the group-A client changes"
```

---

## 联合验收(与 fairyland 计划共同完成,不在本计划内单独打勾)

1. `include_subdomains` 应用的**根域与子域都可达**;
2. 索要客户端证书的站点**正常弹 picker**;
3. `client_cert = true` 的应用**仍能出示设备证书**;
4. `teleport://tunnel` 显示正确列表与标注、到期时刻、CONNECT 状态码**与 authority**;
5. `gate.<D>` 及覆盖它的通配在写入面被拒,绕过后两侧都不路由,bind 不自锁;
6. 同内容重复 bind 的 `routes_digest` 不变。
