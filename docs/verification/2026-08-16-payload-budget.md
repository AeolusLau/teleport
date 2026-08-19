# bind 响应体字节预算(Task 12 Step 1)

**结论:`kMaxBindBodyBytes` 维持 64 KiB,不提到 512 KB。计划初稿的「提到 512KB」这一步作废。**

理由不是「够用就行」,而是:**提高它需要同批改服务端,而这条耦合没有编译期保护;一条不去创造的耦合,就是一条不会漂移的耦合。** 算术表明 48 KiB / 64 KiB 这一对对现实部署已经闭合,提高只增加漂移面,不增加能力。

---

## 1. 两个数从哪来

| 侧 | 常量 | 值 | 位置 |
|---|---|---|---|
| 客户端 | `kMaxBindBodyBytes` | 64 KiB = 65536 | `src/browser/enterprise/teleport_tunnel_logic.h`(本任务从 `teleport_tunnel_service.cc` 的匿名 namespace 移出,为的是能被测试钉住) |
| 服务端(镜像) | `clientBindBodyCapBytes` | 64 KiB | `../fairyland/products/teleport/gateway/internal/tunnelroutes/store.go:83` |
| 服务端 | `defaultMaxBytes` | 48 KiB = 49152 | 同上 `store.go:91` |
| 客户端(镜像) | `kServerRoutesBudgetBytes` | 48 KiB | 本任务新增,仅供闭合断言,不参与任何客户端行为 |

客户端的 64 KiB 直接喂给 `network::SimpleURLLoader::DownloadToString`。**超限不是截断**:
`services/network/public/cpp/simple_url_loader.h:223-227` —— 「If `max_body_size` is exceeded, the request will fail with `net::ERR_INSUFFICIENT_RESOURCES`」。
即**整个 bind 失败 ⇒ 拿不到令牌 ⇒ 进退避**。这是服务端绝不能计划越过这条线的原因。

上游自己的上限:`simple_url_loader.h:110` —— `kMaxBoundedStringDownloadSize = 5 * 1024 * 1024`。64 KiB 与假想的 512 KB 都合法,所以上游不是约束方。

## 2. 最坏单条与现实最坏

服务端 wire 结构(`project.go:32-37`,两个 bool 带 `omitempty`):

```
{"host":"H","port":P}                                       19 + |H| + |P|
+ ,"include_subdomains":true                                +26
+ ,"blocked":true                                           +15
```

- **绝对最坏**:host 取客户端的 `kMaxHostLength = 253`(`teleport_tunnel_logic.cc:36`,RFC1034 上限),port 5 位,两个 flag 都在 ⇒ **318 字节 + 1 逗号 = 319**。
  `(49152 − 2) / 319 ≈ 154` 条。**这是病理值**:253 字符的 FQDN 现实中不存在。
- **现实悲观值**:40 字符 FQDN(比典型内网名长)、4 位端口、**两个 flag 都在**(即 `omitempty` 一点便宜都不占)⇒ **104 字节 + 1 逗号**。
  实测 **468 条**(见 `TeleportTunnelPayloadBudgetTest.ServerBudgetHoldsARealTenantAndStillFits`,按服务端 `truncateToBudget` 的同一套记账重算,`project.go:237-254`)。
- **典型值**(无 flag,`omitempty` 生效,40 字符 host、443):`19+40+3 = 62` + 逗号 ⇒ 约 **780 条**。

## 3. 「现实最坏」是不是够

路由表的一条 = 一个 **(host, port) 地址**,不是一个应用。服务端在 `Project` 里先按 (host, port) 去重(`project.go:145-152`),所以一个声明了多个 origin 的应用只按其**不同地址数**计入。

对照:

- 服务端对 origin 数量**没有**其它上限——`ValidateOriginSet`(`device-manager/internal/policy/webapp/origin.go:96`)只要求根节点至少有一个 primary origin,不限个数。**字节预算是唯一的界**,而它有 `routes_truncated` 标志与 `routes_dropped` 计数把越界暴露出来,不是静默的。
- 同一仓库里可比的上游上限是 `maxURLFiltersPerPolicy = 1500`(`compiler.go:53`),那是 URL 过滤列表的条目上限,数量级参考。

一家大型企业内网发布的 Web 应用数量在**几十到低三位数**;468 个不同地址(悲观形状)覆盖到"数百个应用、每个应用平均两个不同地址"。**48 KiB 已经闭合。**

## 4. 提高它会买到什么(答案:什么也没有)

- **只提客户端**:服务端仍按 48 KiB 截断。表面全绿,实际静默丢路由。**这是计划原步骤会造成的确切后果。**
- **只提服务端**:客户端整个 bind 失败(`ERR_INSUFFICIENT_RESOURCES`),没有令牌,永久退避。比丢路由更响,但同样是故障。
- **两边同批提**:能力上多出一个现实中还没出现过的量级,代价是把一条已经闭合、写在两侧注释与两侧测试里的耦合变成一条**活的**耦合——每次改动都要跨仓对表。

安全面上还有一点:64 KiB 是一个紧的内存界,对着一个**未签名**的响应体(`TD-TUNNEL-BIND-RESPONSE-UNSIGNED`)缓冲。512 KB 会把被攻陷 gate 能让每个客户端每 8 分钟缓冲的量放大 8 倍。收益为零的情况下这不是划算的交换。

**决定:两个数都不动。** 若将来真要动,必须**同批**给出新的一对:客户端 `kMaxBindBodyBytes` 与服务端 `clientBindBodyCapBytes` 相等,`defaultMaxBytes` 至少低 8 KiB(服务端 `TestStore_DefaultBudgetLeavesHeadroomUnderTheClientBodyCap` 钉住这条 headroom 规则)。

## 5. 零值 / 未初始化路径的检查(服务端那个坑在客户端有没有对应物)

服务端发现:`Config.MaxBytes` 原本无默认值,而 **0 的语义是「全部截断」** ⇒「有效令牌 + 空表」,设计里最坏的状态,一个零值配置直达。现已由 `store.go:159-160` 的 `if cfg.MaxBytes <= 0 { cfg.MaxBytes = defaultMaxBytes }` 与 `TestStore_ZeroMaxBytesFallsBackToTheDefaultBudget` 封住。

**客户端对应物:不存在,而且是结构性不存在。**

- `kMaxBindBodyBytes` 是 `inline constexpr size_t`,**不是**配置字段、不是 pref、不来自策略、没有 setter,只有一个使用点(`teleport_tunnel_service.cc` 的 `DownloadToString`)。没有可以是零的载体。
- 假设性地,如果它**是** 0:每次响应都超限 ⇒ `response_body` 为空 ⇒ `OnTunnelToken` 走 `OnBindFailed` ⇒ **拿不到令牌**。也就是说客户端的零值失败模式是 **fail-closed 且吵**(诊断页显示 bind 失败 + 退避),不是服务端那种 **fail-open 且静**(有效令牌 + 空表)。两侧的零值风险本就不对称。
- 因此这里**刻意不做成可配置**。加一个旋钮就要加一个默认值,也就凭空造出服务端刚封上的那个洞。这条理由已写进 `teleport_tunnel_logic.h` 的常量注释,免得后人"顺手"把它变成 pref。

## 6. 客户端这侧新增的防护

以前客户端**没有任何**测试钉住这个常量(服务端有,但服务端钉的是它自己那份镜像——客户端改了、没人改服务端时,服务端测试照样绿。这个洞只能从客户端这侧堵)。

新增 `TeleportTunnelPayloadBudgetTest`(2 个测试,`teleport_tunnel_logic_unittest.cc`):

1. `WholeBodyCapIsTheNumberTheServerMirrors` —— 钉 64 KiB 与 48 KiB,并断言不超上游 5 MiB。改常量的人必须改这一行,而这一行的注释就是告诉他服务端要同批动的那段文字。
2. `ServerBudgetHoldsARealTenantAndStillFits` —— 按服务端记账填满 48 KiB,断言条数 ≥ 450(实测 468)、整包 ≤ 64 KiB、且 `ParseRoutableOrigins` 全部解析成功、`skipped` 为空。**已做变异验证**:把条数断言改成 `EXPECT_EQ(entries, 0u)` 会红并打印实测的 468,证明它确实在算而不是空过。

为此把 `kMaxBindBodyBytes` 从 `teleport_tunnel_service.cc` 的匿名 namespace 移进 `teleport_tunnel_logic.h`——service 编在 `chrome/browser` 里,轻量 `teleport_unittests` 链不到它的符号(`TD-TUNNEL-UNITTEST-WIRING`),常量留在那儿就永远钉不住。
