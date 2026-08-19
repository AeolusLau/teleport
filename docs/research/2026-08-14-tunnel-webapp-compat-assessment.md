# Web 应用经隧道访问的兼容性判定报告

- 日期:2026-08-14
- 输入:`docs/research/inputs/2026-08-14-webapp-proxy-publish-compat-checklist.md`(同事整理的对抗性问题清单)
- 判定基线:teleport `d5b3133`(Chromium M151)/ fairyland `01fbb10`(rift edge · per-origin 路由)
- 分支:`spec/tunnel-webapp-compat`(两仓成对)

---

## 1. 这份报告在回答什么

同事从对抗视角整理了一份《企业浏览器访问内网 Web 应用兼容性问题清单》,列了 25 类典型问题 + Top 10 + POC 验证清单。
本报告对其**逐项判定**:在我们**已经落地**的链路形态下,哪些问题结构上不可能发生、哪些一定会发生、哪些取决于环境需要验证。

判定不依据通用 ZTNA 经验,而是回溯到两仓的实际代码路径、Chromium M151 检出的网络栈实现,以及已有的真机实测记录。
凡结论为「一定会」的,均给出可复核的 `file:line` 或实测记录编号;凡结论为「有风险」的,表示结论取决于站点形态或客户环境,**不作断言**,留给 POC 逐项验证。

---

## 2. 判定的唯一分水岭:清单是按反向代理写的,我们不是

清单 25 条里有 14 条的根因是同一件事——**应用被改写了域名 / 路径 / 协议,或响应体被中间层动过**。
那是「反向代理式应用发布」(clientless portal)的固有代价,也是国内 SDP/ZTNA 厂商「应用发布」形态的标准问题集。

我们的形态完全不同:

| | 清单预设的形态(反向代理) | 我们的实际形态(正向代理隧道) |
|---|---|---|
| 用户访问的地址 | 网关分配的外部域名 | **应用真实主机名**,零映射 |
| 路径 | 网关按发布规则改写回源 | **零改写**,path/query 原样透传 |
| TLS | 网关终结,可见并可改写明文 | https 应用**端到端**,edge 只读 CONNECT 目标后裸字节中继 |
| 响应体 | 常需 URL/域名替换 | **从不触碰** |
| 客户端 | 普通浏览器,适配压力全在网关规则 | 受管浏览器,按 origin 选择性路由,其余 DIRECT |
| 准入 | 网关规则 | 设备证书 mTLS + cnf 令牌 + origin 白名单 + PDP 四道门 |

**结论**:那 14 条不是「我们做得好」,而是**在架构上不存在**——没有改写层,就没有改写错的失败模式。

代价对称地摆在另一侧,必须同样诚实地记下来:

1. **我们没有任何补救层**。反向代理能靠改写 Location、重签证书、放宽 CORS 把不兼容的应用「掰通」;我们不改写,凡是需要中间层修一下才能通的,只能拒绝或原样失败。
2. **失败的根因整体转移**。从「网关规则配得对不对」变成「**origin 注册全不全**」。我们全部真实兼容性问题的共同根都在这里,而不是在协议适配上。

---

## 3. 结论速览

| 判定 | 条数 | 含义 |
|---|---|---|
| 结构上进不去 | 14 | 根因(改写 / 终结 / 换域)在我们链路里不存在,无需适配工作 |
| 一定会掉进去 | 5 | 已由代码路径或真机实测坐实。其中 2 条是可修的实现缺陷,3 条是架构必然代价 |
| 有风险 | 6 | 取决于站点形态与客户环境,须在 POC 阶段逐项验证 |

外加 **6 条清单未覆盖、但我们因为用了客户端隧道而一定会碰到**的问题(§6)。

合并后需要后续处理的问题共 **11 条**,编号 `C-1` … `C-11`,见 §7。

---

## 4. 逐项判定表(对应清单第二章总表)

| 清单条目 | 判定 | 在我们链路里的实际情况 | 证据 |
|---|---|---|---|
| URL / Path 重写 | 不会 | 全链路零路径改写。edge 只解析 authority,path/query 原样透传;正向代理路径仅重写 scheme+host 到已鉴定的 authority | `rift/internal/proxy/forward.go` `Rewrite` |
| 绝对地址(写死内网域名/IP) | 不会 | 写死的内网域名甚至内网 IP **照样可用**——浏览器本来就在访问真实地址。根因转移为「该 host:port 是否已注册」 | 总纲决策 ⑦ 主机名模型 |
| 302 / Location 重定向 | 不会 | Location 里的内网地址正是浏览器可直接消费的地址。裸域 `http→301→https` 完整跳转链已真机跑通(forward-proxy 首跳 × CONNECT 终页串联) | `TD-HTTP-BACKEND-REAL-SITES-VERIFIED` |
| Cookie Domain / Path | 不会 | 域名与路径均未变,Cookie 作用域与内网直连逐字节等价;链路上无任何一处读写 `Set-Cookie` | `proxy/server.go` `splice()` |
| Cookie Secure / SameSite | 不会 | TLS 不在中间终结,https 页面对浏览器依旧是 https;跨站上下文判定基准未变 | 盲模式 app-TLS 端到端 |
| CORS / OPTIONS 预检 | 不会 | 所有 Origin 保持真实,跨域关系与直连完全相同。非幂等方法已显式放行进隧道 | `allow_non_idempotent_methods=true` |
| iframe 嵌入 | 不会 | `X-Frame-Options` / `frame-ancestors` 判定的是真实 origin。前提:被嵌子系统所在 host 也已注册(见多域名行) | 响应头零改写 |
| HTTP / HTTPS 混用 | 不会 | 不做协议升降级,不会人为制造 Mixed Content | scheme×method 门保持声明 scheme |
| **WebSocket 代理** | **一定会** | `wss://` + https 应用完全透明;**`ws://` + http 应用必然 403**。详见 `C-1` | `http_stream_factory_job.cc:992`;`proxy/server.go` `schemeMethodAllowed` |
| SSE / 长轮询 | 有风险 | CONNECT 路径无任何超时(splice 不设 deadline,edge 未设 `WriteTimeout`),https 站点安全。正向代理路径 `ResponseHeaderTimeout=30s`:SSE 因 Go 对 `text/event-stream` 自动即时 flush 而安全,**但挂起超过 30s 才出响应头的长轮询会 504**。详见 `C-7` | `forward.go` `Transport` |
| 前后端分离路径 | 不会 | 无 base path 概念,SPA 二级路由刷新与 API Base URL 与直连一致 | 零路径改写 |
| **多域名应用** | **一定会** | 非通配多域名是「必须逐个注册」的配置负担(有 origin discovery 兜底);**通配域是确定性缺陷**。详见 `C-2` | `teleport_tunnel_logic.cc:44`;`compiler.go:1192` |
| 静态资源缓存 | 不会 | 缓存键即真实 origin,链路上无 CDN、无中间缓存、无 ETag 改写 | 无缓存层 |
| **Header 透传** | **一定会** | 不是透传不对,而是**刻意不透传**:XFF 三件套被主动删除且不重建。详见 `C-3` | `forward.go` `Del("X-Forwarded-For")` 等 |
| 认证回调(OAuth/OIDC/SAML) | 不会 | Redirect URI 就是真实内网地址,IdP 侧无需为我们改配置。前提:IdP 若在内网须作为 auxiliary origin 注册(共享 auxiliary 已由 per-origin 重键支持) | per-origin-nexthop 设计 §1.2 ① |
| CSRF 校验 | 不会 | Origin / Referer 保持真实,同源校验与 CSRF Token 流程无感知 | 请求头零改写 |
| 文件上传 | 有风险 | CONNECT 路径纯字节无限制;正向代理路径未设 body 上限与写超时,大文件上传本身安全。**但后端「收完 body 后同步处理超过 30s 才回响应头」会 504**(病毒扫描、转码类接口易中)。归入 `C-7` | `ResponseHeaderTimeout=30s` |
| 文件下载 | 不会 | `Content-Disposition` / `Content-Type` 不被改写,文件名编码与预览行为与直连一致 | 响应头零改写 |
| Range / 视频流 | 有风险 | 正确性无问题(Range 与 206 原样透传)。风险在性能:正向代理路径 `DisableKeepAlives=true`,每请求一条独立连接器流,拖动进度、分片密集加载时开销放大。归入 `C-7` | `forward.go` `Transport` |
| 压缩编码 | 不会 | 结构上不可能:任何路径都不解压、不重压、不改写响应体 | 无 body 处理 |
| 响应内容替换副作用 | 不会 | 结构上不可能:从不做响应体 URL/域名替换,无「规则过宽误改业务脚本」这一失败模式 | 无 body 处理 |
| **特殊端口** | **一定会** | 客户端按 host 路由(全端口)、服务端按 host:port 授权的粒度不对称。详见 `C-5` | `scheme_host_port_matcher_rule`;`cache.Lookup(host:port)` |
| 第三方依赖 | 有风险 | 此处我们**明显优于反向代理**:公网第三方(地图、验证码、字体、CDN)走 DIRECT,行为与普通浏览器完全一致,不需纳入发布范围。风险只剩内网第三方组件须注册为 auxiliary origin。归入 `C-5` | `reverse_bypass` 白名单语义 |
| 浏览器兼容 | 有风险 | Web 平台是**未改动的 stock Chromium M151**——109 个 patch 中零个触碰渲染 / JS / Cookie / TLS 语义(唯一的 media patch 只是补一个 `<array>` include)。UA 与 UA-CH 恒等于引擎版本 `Chrome/151.x`,站点探测到的就是标准 Chrome。**真实风险不在内核,在覆盖面**:目前仅 macOS ARM 有构建,企业以 Windows 为主 | `patches/` 全量核对;`user_agent_utils.cc.patch` |
| **证书链** | **一定会** | 盲模式端到端握手,我方不出示、不重签、不补链,内网自签 / 私有 CA / 链不全一律照常拦截。详见 `C-4` | 总纲决策 ⑦ / §4.3 盲模式 |
| HSTS / CSP | 有风险 | CSP 保持原样,天然安全。HSTS 是风险源:**http-only 应用若命中 HSTS**(preload TLD 如 `.dev`/`.app`,或历史上发过 STS 头)会被强制升 https → CONNECT :443 → 无 route → 403。叠加 Chrome 的 HTTPS-Upgrades / omnibox HTTPS-First,输裸域会先试 https。归入 `C-5` | `TD-TUNNEL-HTTPS-ONLY-BARE-DOMAIN-301` |

---

## 5. 五条「一定会掉进去」的详细判定

### 5.1 `C-1` 纯 HTTP 应用上的 WebSocket 必然 403(可修缺陷)

Chromium 对配置了代理的连接**恒用 CONNECT 承载 WebSocket**,包括明文 `ws://`。
上游注释原文(`net/http/http_stream_factory_job.cc:992`):

> WebSocket is not supported over a fresh HTTP/2 connection. …
> **For proxies, WebSockets are always tunneled.**

而 edge 的 scheme×method 门规定 `http` origin **只能**走正向代理、不得走 CONNECT
(`rift/internal/proxy/server.go` `schemeMethodAllowed`):

```go
case "https": return isConnect
case "http":  return !isConnect
```

两者相撞:

```
http 应用页面 → new WebSocket("ws://app:8080/…")
  → 浏览器发 CONNECT app:8080
  → schemeMethodAllowed("http", isConnect=true) = false
  → 403 scheme mismatch
```

**影响面**:内网监控大屏、OA 消息推送、在线协作这类最依赖 WebSocket 的系统,恰恰又最常年跑明文 HTTP。
`wss://` + https 应用不受影响(盲 splice 全透明,总纲 §6.4「盲模式全免费」成立)。

**方向**:服务端处理——对 http origin 放行 CONNECT,或在 edge 侧把该 CONNECT 降级为正向代理的 Upgrade 转发。
注意 scheme×method 门是**有意的安全约束**(「客户端不能挑一个目标从未声明的传输」),放宽须重新论证其不变量,不能简单删掉。

### 5.2 `C-2` 通配 origin(include_subdomains)被客户端静默丢弃(可修缺陷)

服务端把通配 origin 当一等公民(路由行、通配并集取宽、edge `MatchesHost` 匹配全部支持),
device-manager 也据此发出 `[*.]` 前缀的 AutoSelect 条目(`device-manager/internal/policy/webapp/compiler.go:1192`):

```go
host := o.Host
if o.IncludeSubdomains { host = "[*.]" + host }
addEntry(fmt.Sprintf("%s://%s:%d", o.Scheme, host, o.Port))
```

但客户端推导路由时用 `GURL` 解析这个 pattern(`src/browser/enterprise/teleport_tunnel_logic.cc:44`):

```cpp
GURL url(*pattern);
if (!url.is_valid() || !url.has_host()) continue;
```

`https://[*.]corp.example:443` 的 host 部分以 `[` 开头,URL 规范化把它当 IPv6 字面量:
`DoSimpleHost` 放行 `[`(字符表允许),随后 `CanonicalizeIPAddress` → `DoCanonicalizeIPv6Address` 解析失败,
扫到 IPv6 专属字符 `[` 即标记 `CanonHostInfo::BROKEN`(`url/url_canon_ip.cc:93`),
于是 `is_valid()` 返回 false,该条目被 `continue` 跳过。

```
device-manager 发 "[*.]corp.example"
  → DeriveRoutableOrigins: GURL 无效 → 跳过
  → bypass_rules 里没有该域 → 流量走 DIRECT
  → 后端只经隧道可达 → 不可达
```

**这是一条跨仓静默失配**:服务端配得进去、控制台显示正常、edge 也认,唯独客户端不路由。
现场表现为「配了但打不开」,且没有任何日志指向真因。

**方向**:客户端处理——识别 `[*.]host` 前缀,产出 `*.host` + `host` 两条 bypass 规则
(Chromium 代理 bypass 原生支持 `*.` 通配)。当前 `teleport_tunnel_logic_unittest.cc` 零通配用例,须一并补。

### 5.3 `C-3` 后端拿不到真实客户端 IP(架构代价)

正向代理路径上 edge **刻意**不调 `SetXForwarded()`,并主动删除客户端自带的三件套
(`rift/internal/proxy/forward.go`):

```go
// Do NOT call pr.SetXForwarded(): the edge is a pure relay and must not
// reveal the client's egress IP to the backend (symmetric with the CONNECT
// blind-splice path).
pr.Out.Header.Del("X-Forwarded-For")
pr.Out.Header.Del("X-Forwarded-Host")
pr.Out.Header.Del("X-Forwarded-Proto")
```

CONNECT 路径更彻底:后端看到的源 IP 是连接器的。

这是清单「Header 透传问题」那一行的**反向版本**:不是透传得不对,而是刻意不透传。
任何依赖来源 IP 的能力都会失效——IP 白名单准入、按 IP 的风控与限流、审计日志里的用户 IP、部分国产中间件的会话绑定。

**方向**:这是数据主权设计的直接后果,不是 bug。需要决定的是产品姿态:
是否提供一个**按 app 可选**的「注入经签名的身份/来源断言头」能力(总纲 §5.6 已有 L7 注入头 delete-then-set + 后端验签的设计),
还是明确写进产品限制并进售前采集表。

### 5.4 `C-4` 内网自签证书照常拦截(架构代价)

盲模式的卖点就是「我方不持证书、不出示证书」(总纲决策 ⑦):后端用它自己的真证书与浏览器**端到端**握手。
所以内网常见的自签证书、私有 CA、链不全、证书域名与访问域名不符,浏览器**一如直连时那样拦截**——
反向代理方案里那种「网关重签一张干净证书」的补救在我们这里不存在,也不应存在。

目前产品侧还缺一条配套链路:把客户内网根 CA 经策略下发到端。Chromium 有对应策略面,但我们尚未产品化。
在补上之前,凡是内网证书不规范的客户,POC 第一天就会看到满屏「不安全」。

**方向**:客户端 + 服务端——内网根 CA 的策略下发通道(与既有 machine/user 策略编译器同批),
以及交付流程上把「内网证书规范性」列为前置问题。

### 5.5 `C-5` 端口未逐个注册时,劫持了却过不去(架构代价)

客户端与服务端的粒度不对称:

- **客户端按 host 路由,scheme 与 port 无关**。`BuildTunnelProxyConfig` 用 `bypass_rules.AddRuleFromString(origin)`,
  origin 是裸 host 串;Chromium 的 `SchemeHostPortMatcherRule` 对裸主机名匹配**任意 scheme / 任意端口**。
- **服务端按 host:port 授权**。gate-3 `cache.Lookup(host:port)`,未注册端口 fail-closed 403。

```
注册 app.corp:443
  → 客户端 bypass 规则 "app.corp"(全端口)
  → 访问 app.corp:9443 → 路由进 edge
  → Lookup(app.corp:9443) miss → 403
```

比「不劫持」更糟:未注册端口本来至少还有走 DIRECT 撞运气的可能,现在被确定性地掐死。

同一根因下还有两个相邻表现,归入本条一并处理:
- **内网第三方组件 / 内网 IdP / 被嵌子系统**未注册 → 同样 403。
- **https-only 站点输裸域**:Chrome HTTPS-Upgrades / omnibox HTTPS-First 先试 https 或反过来先试 http,
  未注册的那一腿 403(服务端已登记 `TD-TUNNEL-HTTPS-ONLY-BARE-DOMAIN-301`,产品级宽修待议)。
- **HSTS**:http-only 应用若命中 HSTS(preload TLD 或历史 STS 头)被强制升 https → :443 无 route → 403。

**方向**:双侧——应用发布前信息采集表逐 host / 逐端口 / 逐依赖域名收集;
服务端补 `TD-TUNNEL-HTTPS-ONLY-BARE-DOMAIN-301` 的产品级宽修;
客户端考虑是否把路由粒度收窄到 host:port 以消除不对称(须权衡:收窄后未注册端口会走 DIRECT,可能泄漏探测面)。

---

## 6. 清单未覆盖、但我们一定会碰到的六条

这几条在反向代理形态下不存在或不突出,恰恰因为我们用了**客户端隧道**才出现。
原清单没有对应行,但现场杀伤力不低于表内任何一条。

### `C-6` 端点上的透明代理 / SASE 客户端共存(最高优先)

Clash TUN、深信服 / 奇安信 VPN 客户端、Zscaler 这类工具工作在 Chrome **之下**,我们的 `CustomProxyConfig` 压不过它们。
fairyland 技术债 `TD-HTTP-BACKEND-REAL-SITES-VERIFIED` 里已有真机记录:

> 受管 Chromium / 普通浏览器访问 `*.example.com` 需把 `example.com` 加进 macOS 系统代理 bypass
> (否则落 Clash 系统代理:http 502 / https RESET,请求根本不到 edge)。

中国企业终端上装着这类客户端是常态。这是最容易在客户现场炸、且最难归因的一条。

> **待澄清**:代码层面 `EligibleForProxy` 在 `should_override_existing_config=true` 时应当压过系统代理配置
> (`services/network/network_service_proxy_delegate.cc:226`),与上述实测记录表面相左。
> 可能解释:该记录混述了「普通浏览器」的情形,或 Clash 工作在 TUN 模式(网络层劫持,Chrome 无从感知)。
> **须真机复核**,不能当已知结论用。

### `C-7` 正向代理路径的长连接与超时约束

`forward.go` 的 `Transport` 只设了 `ResponseHeaderTimeout: 30 * time.Second`,且 `DisableKeepAlives: true`。三个后果:

1. **长轮询**:挂起超过 30s 才出响应头 → 504。
2. **慢接口 / 大上传后同步处理**:body 写完后 30s 内不出响应头 → 504(病毒扫描、转码、报表生成类)。
3. **性能**:每请求一条独立连接器流,Range 拖动、分片上传、静态资源密集页面的开销被放大。

CONNECT 路径无此约束(`splice()` 不设 deadline,edge `http.Server` 未设 `ReadTimeout`/`WriteTimeout`/`IdleTimeout`),
所以 **https 应用安全、http 应用受限**。SSE 本身安全(Go `ReverseProxy` 对 `text/event-stream` 与 `ContentLength == -1` 自动即时 flush)。

### `C-8` 客户强制出网代理下建不起隧道

Chromium 不支持代理链(`network_service_proxy_delegate.cc` 明文 `TODO(crbug.com/40284947): Support nested proxies`),
浏览器必须能**直连** `edge:443`。客户若强制所有出网流量经他们自己的代理、禁止直连,隧道根本建不起来。

好消息是共存方向没问题:非注册 origin 不匹配我们的 rules,`ApplyProxyConfigToProxyInfo` 返回 false,
`result` 不被触碰,客户既有系统代理配置**得以保留**,不会被我们劫成 DIRECT。

### `C-9` WebRTC / UDP 类应用

CONNECT 隧道搬不了 UDP。内网视频会议、在线客服音视频、Web 版远程桌面会降级到 TCP TURN 或直接失败。
原清单的「第三方依赖」行没有覆盖这一类。

### `C-10` cnf 令牌续期失败即新连接全断

令牌约 10 分钟寿命、在 TTL×0.8 处续期(`TeleportTunnelService::ScheduleRefresh`)。
续期失败时新建连接一律 407,而 Chrome 无 Bearer 代理鉴权处理器,直接报 `ERR_PROXY_AUTH_UNSUPPORTED` 整页失败。
已建立的连接因 edge 无状态、不查会话而不受影响。

现场表现因此是「**开着的页面还活着,新开的全打不开**」——很容易被误判成应用故障或网络抖动。
需要的是可观测性与用户可见的失败语义,而不只是退避重试。

### `C-11` AutoSelect 被征用为路由来源的耦合

客户端的隧道路由白名单是从 `AutoSelectCertificateForUrls` 策略推导出来的
(`DeriveRoutableOrigins`,排除 edge / gate 两个 host 之后的全部 pattern host)。

如果管理员为某个「要求客户端证书、但不该走隧道」的应用加一条 AutoSelect,
该 host 会**同时**被拉进隧道白名单,随即被 edge 403。
这个耦合目前只存在于代码注释里,产品文档上没有任何说明。

---

## 7. 待处理问题清单(后续 spec 逐条引用)

| 编号 | 问题 | 性质 | 主要落点 |
|---|---|---|---|
| `C-1` | 纯 HTTP 应用上的 WebSocket 必然 403 | 可修缺陷 | 服务端(edge scheme×method 门) |
| `C-2` | 通配 origin 被客户端静默丢弃 | 可修缺陷 | 客户端(路由推导 + 单测) |
| `C-3` | 后端拿不到真实客户端 IP | 架构代价 / 产品决策 | 双侧(或仅交付文档) |
| `C-4` | 内网自签证书照常拦截,无根 CA 下发链路 | 能力缺口 | 双侧(策略下发通道) |
| `C-5` | 端口 / 依赖域名注册覆盖不全即确定性 403 | 架构代价 / 流程 | 双侧 + 交付流程 |
| `C-6` | 端点透明代理 / SASE 客户端共存 | 待复核 + 兼容性 | 客户端 + 现场流程 |
| `C-7` | 正向代理路径长连接与超时约束 | 可修缺陷 | 服务端(edge transport) |
| `C-8` | 客户强制出网代理下建不起隧道 | 能力缺口 | 待定(代理链 / 部署形态) |
| `C-9` | WebRTC / UDP 类应用不可达 | 架构限制 | 待定(明确边界或另辟通道) |
| `C-10` | cnf 续期失败即新连接全断 | 可观测性缺口 | 客户端 |
| `C-11` | AutoSelect 被征用为路由来源的耦合 | 产品说明 / 解耦 | 客户端 + 文档 |

处理顺序、每条的取舍与是否立项,在后续 spec 中逐条讨论,不在本报告预设结论。

---

## 8. 证据索引

**客户端(teleport `d5b3133` / Chromium M151 检出)**

- `src/browser/enterprise/teleport_tunnel_logic.{h,cc}` — `DeriveRoutableOrigins` / `BuildTunnelProxyConfig`
- `src/browser/enterprise/teleport_tunnel_service.{h,cc}` — bind / 续期 / 推 config
- `src/browser/enterprise/teleport_tunnel_logic_unittest.cc` — 现有 3 个用例,零通配覆盖
- `services/network/network_service_proxy_delegate.cc` — `EligibleForProxy` / `IsInProxyConfig` / `ApplyProxyConfigToProxyInfo`
- `net/http/http_stream_factory_job.cc:992` — "For proxies, WebSockets are always tunneled"
- `url/url_canon_host.cc` / `url/url_canon_ip.cc:93` — `[` 触发 IPv6 判定 → `BROKEN`
- `patches/` 全量 109 个 patch — 零个触碰渲染 / JS / Cookie / TLS 语义
- `patches/components/embedder_support/user_agent_utils.cc.patch` — UA/UA-CH 恒为引擎版本

**服务端(fairyland `01fbb10`)**

- `products/teleport/rift/internal/proxy/server.go` — 四道门 + `schemeMethodAllowed` + `splice`
- `products/teleport/rift/internal/proxy/forward.go` — 正向代理路径、XFF 剥离、`Transport` 超时
- `products/teleport/rift/cmd/edge/main.go` — `http.Server` 未设超时
- `products/teleport/device-manager/internal/policy/webapp/compiler.go:1189-1196` — AutoSelect 条目产出
- `docs/superpowers/specs/2026-07-12-teleport-access-gateway-design.md` — 总纲(决策 ⑦ 主机名模型、§4.3 盲/L7、§6.4)
- `docs/superpowers/specs/2026-07-25-teleport-access-p1c-minimal-tunnel-design.md` — 三过门契约
- `docs/superpowers/specs/2026-08-05-teleport-connector-per-origin-nexthop-design.md` — origin 一等公民化路由
- `docs/tech-debt.md` — `TD-HTTP-BACKEND-REAL-SITES-VERIFIED`、`TD-TUNNEL-HTTPS-ONLY-BARE-DOMAIN-301`
