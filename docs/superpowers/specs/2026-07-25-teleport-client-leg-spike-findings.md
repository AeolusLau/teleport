# Teleport Access P1c 客户端腿 Chromium spike — findings(静态阅读半)

> 本文件 = P1c 计划 Task 9 的**静态阅读半**产出(在 teleport `spec/teleport-access-gateway`
> worktree 完成)。它逐项给出对 spec §3.2/§3.3 客户端腿三项未知 + 代理路由形态 + M148 代理
> 策略字段号的**代码级(file:line)结论**,并把需要真浏览器 + net-export 才能定论的部分**明确
> 隔离**到「PENDING 用户真机实证」章。
>
> **实证半(跑真 Chromium + net-export 抓握手)由用户驱动,不在本轮范围**;对应项本文给出**可直接
> 照跑的验证配方**并标注 `PENDING`。
>
> 依据:
> - 计划 `docs/superpowers/plans/2026-07-25-teleport-access-p1c-edge-datapath.md`(fairyland 仓)Task 9。
> - 设计 spec `docs/superpowers/specs/2026-07-25-teleport-access-p1c-minimal-tunnel-design.md`(fairyland 仓)§3.2/§3.3/§4.2。
> - 代码基:`chromium/src`(只读静态分析;`chromium/src` 是共享 ~30GB checkout 的 gitignored 符号链,不可重建)。所引 `out/mac/arm64/release/gen/.../cloud_policy.proto` 为该 checkout 已生成的策略 proto,用作字段号的**地面真值**。

---

## 结论速览

| # | 项 | 静态结论 | patch 面 |
|---|---|---|---|
| 1 | CONNECT 头注入落点 + Bearer 冲突 | 落点 = `ProxyDelegate::OnBeforeTunnelRequest`(H1/H2/H3 三路共用);Chrome 自有代理鉴权对 Bearer **不构成写覆盖冲突**(无原生 Bearer scheme → `authorization_headers_` 为空)。**现成机制** `NetworkServiceProxyDelegate` + `CustomProxyConfig.connect_tunnel_headers` 已能注入任意 CONNECT 头 | **可能零 C++ 内核 patch**(走现成 mojo);否则单点小 patch |
| 2 | per-profile token store → 网络栈读取 | 现成 per-NetworkContext 通道:`CustomProxyConfigClient.OnCustomProxyConfigUpdated`(mojo,可热更)把 token 送进正是 CONNECT 时刻运行的 delegate。浏览器侧新增 per-Profile keyed service(跑 bind + 推 mojo)+ `ProfileNetworkContextService` 挂 receiver | 中等(浏览器进程侧,非网络栈) |
| 3 | AutoSelect 覆盖代理连接 | **静态强指向:AutoSelect 对代理握手匹配的是代理端点 URL(`https://edge.<域>:8444`)**,非 origin——proxy hop 的 `SSLClientSocket` 携带代理 `host_and_port`,直灌 `SSLCertRequestInfo::host_and_port` → `GetRequestingUrl` → AutoSelect。**定论需实证**代理 client-cert 请求确实走到 `SelectClientCertificate` 路径 | config-only(策略 URL pattern 覆盖 edge)——若实证证伪则退路 patch |
| 4 | M148 代理策略字段号 | `ProxySettings` = **field 118**(top-level in `CloudPolicySettings`,`StringPolicyProto`,dict 编码为 JSON 串);`ProxyMode`=23 / `ProxyServerMode`=24 / `ProxyServer`=25 / `ProxyPacUrl`=26 / `ProxyBypassList`=27。**均非嵌套**于 `CloudPolicySubProtoN` | proto 加字段(device-manager 侧) |
| 5 | 现有 teleport patches 上下文 | 无与代理/CONNECT/client-cert/AutoSelect 重叠的 patch;`chrome_content_browser_client.cc.patch` 与 `generate_policy_source.py.patch` 均不碰相关代码 → 后续 patch **无碰撞** | — |

---

## 项 1:CONNECT 头注入落点 + `Proxy-Authorization: Bearer` 冲突评估

### 1.1 CONNECT 头如何构建(H1 路径)

`net/http/http_proxy_client_socket.cc`:

- `DoCalculateHeaders()`(**:356–385**)组两组头:
  - `authorization_headers_`:仅当 `auth_->HaveAuth()` 为真时,`auth_->AddAuthorizationHeader(&authorization_headers_)`(**:366–368**)——这是 Chrome **自有代理鉴权状态机**(`HttpAuthController`)出的头。
  - `proxy_delegate_headers_`:`proxy_delegate_->OnBeforeTunnelRequest(proxy_chain_, proxy_chain_index_, …)`(**:370–384**)——`ProxyDelegate` 给 embedder 的 CONNECT 加头钩子。
- `DoSendRequest()`(**:414–442**)合并二者后建 CONNECT:

  ```
  HttpRequestHeaders extra_headers;
  extra_headers.MergeFrom(authorization_headers_);      // 先并 auth
  extra_headers.MergeFrom(proxy_delegate_headers_);     // 后并 delegate → 覆盖 auth
  BuildTunnelRequest(endpoint_, extra_headers, user_agent_, &request_line_, &request_headers_);
  ```
  (**:422–427**)

- `ProxyClientSocket::BuildTunnelRequest`(`net/http/proxy_client_socket.cc:25`)写 `CONNECT host:port HTTP/1.1` + `Host` + `Proxy-Connection: keep-alive` + `User-Agent`,最后 `request_headers->MergeFrom(extra_headers)`。`HttpRequestHeaders::MergeFrom` 语义 = 对每个头调 `SetHeader`(覆盖同名)(`net/http/http_request_headers.h:185–186`)。

**H1 路径注入落点确定:`proxy_delegate_headers_` 在 auth 头之后合并 → delegate 注入的 `Proxy-Authorization` 覆盖 auth 头(胜出)。**

### 1.2 三路(H1 / H2 / H3)统一走 ProxyDelegate

代理 CONNECT 有三个 socket 实现,**均**调 `proxy_delegate_->OnBeforeTunnelRequest`:

- H1:`net/http/http_proxy_client_socket.cc:370`。
- H2/SPDY:`net/spdy/spdy_proxy_client_socket.cc:413`(auth 于 :410,delegate 于 :413,`MergeFrom(proxy_delegate_headers_)` 于 :437,`BuildTunnelRequest(…, authorization_headers_, …)` 于 :445–446)。
- H3/QUIC:`net/quic/quic_proxy_client_socket.cc:363`(auth)/ `:366–369`(delegate)。

→ **经 `ProxyDelegate::OnBeforeTunnelRequest` 注入是传输无关的**(TCP CONNECT / h2 / h3 一处覆盖全部),契合 spec §6「首切片仅 h2/TCP CONNECT」并向 h3 平滑。这是**最强单一注入候选**。

> 合并次序细节:SPDY/QUIC 路径把 `authorization_headers_` 经 `BuildTunnelRequest` **后并**(与 H1 的 delegate-last 相反)。但对本设计**无实质影响**:Bearer 不是原生代理 auth scheme,`HaveAuth()` 恒 false → `authorization_headers_` 恒空 → 无论并序,注入的 `Proxy-Authorization` 都不会被空集覆盖。**结论:无写覆盖冲突。**

### 1.3 现成注入机制:`NetworkServiceProxyDelegate.connect_tunnel_headers`(关键)

网络服务里 `ProxyDelegate` 的落地实现 `services/network/network_service_proxy_delegate.cc`:

```
NetworkServiceProxyDelegate::OnBeforeTunnelRequest(...) {
  net::HttpRequestHeaders extra_headers;
  if (IsInProxyConfig(proxy_chain)) {
    MergeRequestHeaders(&extra_headers, proxy_config_->connect_tunnel_headers);  // :167
  }
  return extra_headers;
}
```
(**:161–170**)

`connect_tunnel_headers` 源自 mojo `CustomProxyConfig`:

```
// services/network/public/mojom/network_context.mojom
struct CustomProxyConfig {
  ProxyRules rules;                              // 路由规则
  ...
  // For tunneled requests (https://, ws://, wss://), these headers are added
  // to the CONNECT request. Headers here will overwrite matching headers on
  // the CONNECT request if a custom proxy is used.
  HttpRequestHeaders connect_tunnel_headers;     // :126
};
```

**即:Chrome 已内建「向 CONNECT 注入任意头、且覆盖同名头」的机制**。把 `Proxy-Authorization: Bearer <cnf>` 放进 `connect_tunnel_headers` 即注入到发往 edge 的 CONNECT。

### 1.4 冲突评估结论(承 spec §3.3 项3 风险)

- **出站 CONNECT 上无冲突**:Bearer 无原生 scheme → auth 头空;delegate/`connect_tunnel_headers` 注入的头必达且(H1)覆盖。
- **407 回挑战路径需实证**:edge 无 token 时回 `407 + Proxy-Authenticate: Bearer`,Chrome 进 `HandleProxyAuthChallenge`(`http_proxy_client_socket.cc:520–521`)。Chrome **无 Bearer auth handler** → 该挑战大概率 unhandled(`ERR_UNSUPPORTED_AUTH_SCHEME` 类),**不会**进凭据缓存/无限重试。设计上 407 只用于「bind 未完成」暂态,客户端应**主动**在首个 CONNECT 即带 token 拿 200,绕开挑战机。**该 407 状态机行为 = 实证项**(见 PENDING E-3)。
- **放弃阈值(spec §3.3 逃生舱)未触及**:注入是「单点最小面 / 甚至 config-only」,未与内核鉴权状态机纠缠 → **无需**切自定义头 `X-Teleport-Tunnel-Token` 或 MASQUE。逃生舱保留但当前不取用。

**patch 面估计:**
- **方案 A(推荐先评估,可能零 C++ 内核 patch)**:浏览器进程侧 per-Profile 组件跑 bind 腿,经 mojo `SetCustomProxyConfig`/`OnCustomProxyConfigUpdated` 下发 `CustomProxyConfig{ rules, connect_tunnel_headers:{Proxy-Authorization:Bearer …} }`。注入 + 路由同一通道,**网络栈零 patch**。
- **方案 B(与 §4.2 cloud-policy 路由对齐)**:路由走 cloud-policy `ProxySettings`(见项4),另 patch 一个「常挂在受管 NetworkContext 上的 Teleport ProxyDelegate + per-profile token holder」注入头。patch 面中等(见项2 的耦合讨论)。

---

## 项 2:per-profile token store → 网络栈读取路径

### 2.1 delegate 无按请求上下文 → token 必须落在 delegate 实例上

`ProxyDelegate::OnBeforeTunnelRequest(const ProxyChain&, size_t proxy_index, callback)`(`net/base/proxy_delegate.h:91–94`)**只带代理身份,不带 `URLRequest`/profile 上下文**。故 per-profile cnf token 不能「按请求取」,只能**存在 delegate 实例(= per-NetworkContext / per-URLRequestContext)自身**,或其引用的 token holder 上。

### 2.2 现成的 per-NetworkContext + 可热更通道

- delegate 按 NetworkContext 建:`services/network/network_context.cc:2820–2826`——当 `NetworkContextParams.initial_custom_proxy_config` **或** `custom_proxy_config_client_receiver` 存在时,`builder.set_proxy_delegate(std::make_unique<NetworkServiceProxyDelegate>(...))`。
- delegate 持 `mojom::CustomProxyConfigPtr proxy_config_`(`network_service_proxy_delegate.h:86`)。
- **热更通道**(token 轮换):`interface CustomProxyConfigClient { OnCustomProxyConfigUpdated(CustomProxyConfig) => (); }`(`network_context.mojom:168`)。token 到期换发时,浏览器侧推新 `CustomProxyConfig`(含新 `connect_tunnel_headers`)即可,无需重建 context。

### 2.3 读取路径 + patch 面

**读取路径(已存在,零改)**:`OnCustomProxyConfigUpdated`(mojo) → `NetworkServiceProxyDelegate.proxy_config_` → CONNECT 时 `OnBeforeTunnelRequest` 读 `proxy_config_->connect_tunnel_headers`。

**需新增(浏览器进程侧,非网络栈)**:
1. per-Profile keyed service(Teleport 自有):受管 profile 登录后跑 P1b bind 序列(mint 短寿票据 → mTLS+票据打 `gate.<域>/tunnel/bind` → 拿 cnf → 按 profile 存 + 退避重试,承 spec §3.2/§5.7.4)。
2. 经 `ProfileNetworkContextService` 在 `NetworkContextParams` 里挂 `custom_proxy_config_client_receiver`(令 delegate 被实例化),并在拿到/轮换 token 时 `OnCustomProxyConfigUpdated` 下发。

**耦合警示(承项1 方案 B):`IsInProxyConfig` 把注入与路由绑死。**
`NetworkServiceProxyDelegate::IsInProxyConfig`(**:同文件**)仅当 `RulesContainsProxy(proxy_config_->rules, proxy_chain.First())` 为真才返回 true —— 即 `connect_tunnel_headers` **只对 `CustomProxyConfig.rules` 里的代理**生效。推论:
- 若路由走 **`CustomProxyConfig.rules`**(方案 A)→ 注入天然生效,**一条 mojo 通道搞定路由+注入**。
- 若路由走 **cloud-policy `ProxySettings`**(方案 B,§4.2 本意)→ 该 edge 代理**不在** `CustomProxyConfig.rules` 里,`IsInProxyConfig` 为 false,`connect_tunnel_headers` **不注入** → 必须 patch:要么放宽注入判定,要么把同一 edge 也塞进 `CustomProxyConfig.rules`(路由/注入双写),要么自建 Teleport delegate 绕过该判定。

→ **这是后续客户端 patch 计划必须先定的岔路**:路由通道(cloud-policy `ProxySettings` vs `CustomProxyConfig` mojo)决定注入是否需要内核 patch。**本 spike 建议:优先评估方案 A(单 mojo 通道、网络栈零 patch),仅当「机器级策略一致性(与 AutoSelect 同一 machine policy 下发)」硬约束压倒时才取方案 B。**

---

## 项 3:`AutoSelectCertificateForUrls` 覆盖代理连接(静态读)

### 3.1 匹配 URL 来自 `SSLCertRequestInfo::host_and_port`

`chrome/browser/chrome_content_browser_client.cc` `SelectClientCertificate`(**:4224**):

```
GURL requesting_url =
    enterprise_util::GetRequestingUrl(cert_request_info->host_and_port);   // :4285–4286
enterprise_util::AutoSelectCertificates(profile, requesting_url,           // :4290–4292
    std::move(client_certs), &matching_certificates, &nonmatching_certificates);
```

`chrome/browser/enterprise/util/managed_browser_utils.cc`:
- `GetRequestingUrl(host_port_pair)` = `GURL("https://" + host_port_pair.ToString())`(**:265–267**)。
- `GetCertAutoSelectionFilters(profile, requesting_url)`(**:86–105**)拿 `AUTO_SELECT_CERTIFICATE` content setting(源自 `AutoSelectCertificateForUrls` 策略),对每条过滤器做 `ISSUER`/`SUBJECT` 主体模式匹配(`CertificatePrincipalPattern::Matches`,**:123–131**)。

**匹配键 = `cert_request_info->host_and_port`。**

### 3.2 代理握手时该 host_and_port = 代理端点(edge),非 origin

- `net/socket/ssl_client_socket_impl.cc:545`:`cert_request_info->host_and_port = host_and_port_;`(client-cert 请求用本 SSL socket 的 `host_and_port_`)。同文件 **:826** 客户端证书缓存 `context->GetClientCertificate(host_and_port_, …)` 亦以 `host_and_port_` 为键。
- `host_and_port_` = 构造参数(`:288`)。
- `net/socket/ssl_connect_job.cc:469–470`:`client_socket_factory()->CreateSSLClientSocket(…, params_->host_and_port(), …)`。**对 proxy hop,`params_->host_and_port()` = 代理服务器 host:port**(HTTPS 代理的 SSLConnectJob 以代理端点建 SSL socket)。

→ **静态强指向:browser→edge 代理 TLS 握手上 edge 索要 client cert 时,`cert_request_info->host_and_port = edge.<域>:8444`,AutoSelect 匹配的 `requesting_url = https://edge.<域>:8444`(代理端点),而非 origin(`demoapp.<域>:443`)。**

### 3.3 推论 + 定论所需实证

**代码蕴含的策略写法**:要让 device 证书在代理连接上自动出示,`AutoSelectCertificateForUrls` 的 URL pattern 必须**覆盖 edge 代理端点**(如 `https://edge.<域>:8444` 或含之的通配),配合 filter 的 `ISSUER.CN = device-CA CN`。**这与「仅给 origin 配 AutoSelect」不同——须显式给代理端点配。**

**须实证定论(spec §3.3 项1,标 PENDING)**:静态代码只证明「若代理 client-cert 请求走到 `SelectClientCertificate` 路径,则以代理端点为匹配键」。但**代理 CONNECT 的 client-cert 请求是否确实上浮到该浏览器进程路径**(而非在网络服务里被静默处理/失败),须真机 + net-export 核实。历史上代理 client-cert 的 UI/自动选择路径有过特例。→ E-1。

**patch 面估计**:若实证为「走到路径 + 以代理端点匹配」→ **config-only**(策略配 edge 端点 URL pattern,零 patch)。若证伪(代理请求不走 AutoSelect)→ 退路 = spec §3.3 项1 所述「patch 里显式为 edge 代理连接选 device 证书」,仍最小原生面(单点)。

### 3.4 项2'(machine-scope AutoSelect 选中 per-profile 证书)

`GetCertAutoSelectionFilters` 的匹配只看 `ISSUER`/`SUBJECT` 主体模式(§3.1),**不区分 machine/profile 作用域**;`SelectClientCertificate`(`chrome_content_browser_client.cc:4294–4312`)在**恰好一张**匹配时自动选中(多张且未开 prompt 时取第一张)。故**单受管 profile 库内、只有一张 device-CA 签发的设备证书**时,静态逻辑**确定性选中它**(候选集只有一张 → 命中「size()==1」自动选)。**跨 profile 隔离不在最小切片**(承 spec §7.2、总纲 §5.5 天花板)。确定性 = 实证 E-2 复核。

---

## 项 4:代理路由策略 — 真实 Chromium M148 字段号(**wire 契约**)

### 4.1 字段号地面真值(生成 proto)

策略 id 登记:`components/policy/resources/templates/policies.yaml`:

```
21: ProxyMode
22: ProxyServerMode
23: ProxyServer
24: ProxyPacUrl
25: ProxyBypassList
116: ProxySettings
```

生成器 `components/policy/tools/generate_policy_source.py` 的字段号规则:
- `_FieldNumber`(**:1596–1601**):top-level 策略的 proto 字段号 = `policy_id + RESERVED_IDS`。
- 常量:`RESERVED_IDS = 2`(**:1550**)、`_LAST_TOP_LEVEL_POLICY_ID = 1040`(**:1556**)、`_CHUNK_SIZE = 800`(**:1561**)。
- `_ChunkNumber`(**:1587–1593**):`policy_id <= 1040` → chunk 0(top-level,直接进 `CloudPolicySettings`);否则嵌套进 `CloudPolicySubProtoN`。

上述所有代理 id(21–25、116)**≤ 1040 → 全 top-level(chunk 0)**,字段号 = `id + 2`。

**对照已生成 `out/mac/arm64/release/gen/components/policy/proto/cloud_policy.proto`(地面真值)**:

```
optional StringPolicyProto  ProxySettings   = 118;   // :452
optional StringPolicyProto  ProxyMode       = 23;    // :530
optional IntegerPolicyProto ProxyServerMode = 24;    // :533
optional StringPolicyProto  ProxyServer     = 25;    // :532
optional StringPolicyProto  ProxyPacUrl     = 26;    // :531
optional StringPolicyProto  ProxyBypassList = 27;    // :529
```

### 4.2 结论(供改 `proto/teleport/upstream/chromium/cloud_policy.proto`,fairyland device-manager 侧)

- **`ProxySettings` = field `118`**,**top-level 于 `CloudPolicySettings`**(**不**嵌套于任何 `CloudPolicySubProtoN`),类型 `StringPolicyProto`——`dict` 策略被编码为 **JSON 字符串**放进 `StringPolicyProto.value`(`StringPolicyProto{ policy_options=1; value=2 }`,`components/policy/proto/policy_common_definitions.proto:42`)。
- 若走「单个策略」路线:`ProxyMode=23` / `ProxyServerMode=24` / `ProxyServer=25` / `ProxyPacUrl=26` / `ProxyBypassList=27`,均 top-level、`StringPolicyProto`(`ProxyServerMode` 为 `IntegerPolicyProto`)。
- **`ProxySettings` 元数据**(`components/policy/resources/templates/policy_definitions/Miscellaneous/ProxySettings.yaml`):`per_profile: true`、`dynamic_refresh: true`;dict schema 字段 = `ProxyMode` / `ProxyServer` / `ProxyPacUrl` / `ProxyPacMandatory` / `ProxyBypassList`(+ 弃用 `ProxyServerMode`)。`ProxyMode` 枚举:`direct` / `auto_detect` / `pac_script` / `fixed_servers` / `system`。

> **wire 契约警示(计划 §4.2 已点名)**:字段号写错 = 客户端**静默丢弃**。device-manager 的手工裁剪 proto 必须用 **118**(及需要时 23–27),且置于 `CloudPolicySettings` 顶层。teleport **客户端**用的是上游**完整**生成 `cloud_policy.proto`(已含 118),故客户端侧无需改 proto——契约缺口只在**服务端裁剪子集**。

### 4.3 路由形态(PAC vs fixed+bypass)—— 语义分析 + 实证定夺

- **`fixed_servers` + `ProxyBypassList` 语义是反的**:`fixed_servers` 把**全部**流量经 `ProxyServer`,`ProxyBypassList` 里的 host **走 DIRECT**。本需求要「**多数 DIRECT、仅注册 origin → edge**」——与 bypass 语义相反(除非注册集≈全网)。故 fixed+bypass **不干净表达**本需求。
- **`pac_script`(PAC)干净表达**:`FindProxyForURL` 对注册 origin 返 `HTTPS edge.<域>:8444`、其余返 `DIRECT`,正是「注册→edge,其余直连」。PAC 可用 `data:` URL 内联(`ProxyPacUrl` 接受 data URL,见 §4.2 desc)。
- **建议**:路由用 **PAC**(经 `ProxySettings{ ProxyMode: pac_script, ProxyPacUrl: <data: PAC> }`,或方案 A 下经 `CustomProxyConfig.rules` 等价表达)。**「Chrome 是否接受该形态并正确解析路由」= 实证 E-4**(PAC data URL 被接受、net-export 显示注册 origin 命中 edge、其余 DIRECT)。

---

## 项 5:现有 teleport patches 上下文(无碰撞)

`patches/`(89 个 patch)中与代理/CONNECT/client-cert/AutoSelect **无重叠**;两个「文件名相关」的 patch 经核实不碰相关代码:

- `patches/chrome/browser/chrome_content_browser_client.cc.patch`:hunk 仅在 `@@ -753` 与 `@@ -5064`(`BrowserURLHandlerCreated` / chrome:// URL 处理区),**不碰** `SelectClientCertificate`(:4224)。→ 后续 client-cert / AutoSelect patch **无冲突**。
- `patches/components/policy/tools/generate_policy_source.py.patch`:仅改产品版本号处理(`MAJOR=0` 的 `is None` 辨析),**不碰**字段号/chunk/代理策略生成。→ 项4 的字段号结论不受既有 patch 影响。
- `patches/.../device_management_service_configuration.cc.patch` 等策略/DM patch 属 deployment-domain / CBCM 既有工作(见 memory「deployment-domain startup race」),与代理注入正交。

→ 后续「客户端 patch 计划」的 bind 腿 + cnf 注入 + 代理策略 patch **可在现有 patch 之上干净落地,无需先解冲突**。

---

## PENDING 用户真机实证(照跑配方 — 不在本轮执行)

> 以下需真 Chromium(受管 profile)+ net-export(`chrome://net-export/`;注意 custom Teleport 构建对 `--log-net-log` 报"unsupported flag" banner,用 net-export UI 更稳),并在 edge 侧看握手 peer cert 指纹。

> ## ✅ 实证结果(LIVE 验证 2026-07-25,fairyland-ai 栈,受管 Teleport 浏览器)
>
> **E-1 / E-3 / E-4 三项已实证通过,均为最优结果;E-2 高置信待闭环。Design A(网络栈零 C++ patch)被强验证。**
>
> **E-1 ✅ 设备证书能在 browser→edge 代理握手出示、edge 接受**:用 `--proxy-pac-url` 的 PAC **只**导 `demoapp→edge`、其余 DIRECT(必须选择性路由——全局 `--proxy-server` 把 device-manager/证书供给也导向 edge → 供给死锁、证书从 `chrome://certificate-manager` **消失**;PAC 下证书**保住**)。经代理访问 demoapp → **弹出证书选择框**(= 代理 client-cert 请求确实上浮到浏览器进程 `SelectClientCertificate`,历史特例风险排除)→ 选 `Teleport Device CA` 证书 → 得 **407**(非握手失败;edge 侧无握手错误日志 = 握手过了 gate 1)。**config-only 成立。硬需求:`AutoSelectCertificateForUrls` 的 URL pattern 必须覆盖 edge 端点 `https://edge.<域>:8444`(非 origin/gate)——后续 device-manager 侧要 emit 这条。**
>
> **E-3(407 半边)✅ Chrome 对 407+Bearer 干净失败、不死循环/不污染凭据缓存**:无 token → edge 回 `407 + Proxy-Authenticate: Bearer` → Chrome 报 **`ERR_PROXY_AUTH_UNSUPPORTED`**(正是 §1.4 预测:无 Bearer auth handler → unhandled 干净失败)。设计里 407 仅"bind 未完成"暂态、客户端主动带 token 拿 200 绕开 = 成立。(**200-正路**:注入 Bearer 存活→200,仍需 Design A mojo 注入 patch 才能验,归客户端 patch 计划。)
>
> **E-4 ✅ PAC 被 Chrome 接受、路由正确**:`data:application/x-ns-proxy-autoconfig,...` 经 `--proxy-pac-url` 被接受;demoapp→`HTTPS edge.<域>:8444`、其余 DIRECT(DM 直连=证书保住,即 E-1 的证据)。**PAC 为选定路由形态;`fixed_servers` 全局代理语义反、且破坏证书供给(E-1 反证),弃。**
>
> **E-2 高置信待闭环**:E-1 用手动弹框已证证书上浮;加一条覆盖 edge 端点的 `AutoSelectCertificateForUrls`(`ISSUER.CN=Teleport Device CA`)后应**无弹框自动选中**(§3.4 静态:单库单证 `size()==1` 确定性自动选)。真机"无弹框"闭环归客户端 patch 计划(device-manager emit edge AutoSelect 条目时顺验)。

### E-1 `PENDING`:AutoSelect 是否在 browser→edge **代理** TLS 握手出示 device 证书(承 §3.3 项1 / 本文 §3.3)

配方:
1. 起 Rift edge(`RequireAndVerifyClientCert`,信任池 = device-CA)于 `edge.<域>:8444`。
2. 受管 profile 下发策略:
   - 路由:`ProxySettings` = `{"ProxyMode":"fixed_servers","ProxyServer":"https://edge.<域>:8444"}`(或临时 `--proxy-server=https://edge.<域>:8444`)。
   - `AutoSelectCertificateForUrls` = `["{\"pattern\":\"https://edge.<域>:8444\",\"filter\":{\"ISSUER\":{\"CN\":\"<device-CA CN>\"}}}"]`。
3. 浏览 `https://demoapp.<域>`,抓 net-export。
4. **判据**:net-log 里代理 socket 的 `SSL_HANDSHAKE_MESSAGE_SENT`(type=Certificate,非空)/ `SSL_CLIENT_CERT_PROVIDED`,**且** edge 日志记到 peer cert 指纹前缀。看到 = AutoSelect 覆盖代理连接(config-only 成立);看不到(edge 握手因无 client cert 失败)= 证伪 → 走 §3.3 退路 patch(显式为 edge 连接选 device 证书)。

### E-2 `PENDING`:machine-scope AutoSelect 在单-profile 库确定性选中 per-profile device 证书(承 §3.3 项2 / 本文 §3.4)

配方:单受管 profile 库仅装一张 device-CA 签发的设备证书;沿用 E-1 策略。**判据**:net-log 显示**无** client-cert 选择弹窗、恰好一张证书被 provided;重复 5 次结果稳定。

### E-3 `PENDING`:注入的 `Proxy-Authorization: Bearer` 是否被 Chrome 代理鉴权状态机吞(承 §3.3 项3 / 本文 §1.4)

配方:
1. 经 `CustomProxyConfig.connect_tunnel_headers`(mojo `SetCustomProxyConfig`,或临时探针)注入 `Proxy-Authorization: Bearer <有效 cnf>`。
2. **正路**:net-log `HTTP_TRANSACTION_SEND_TUNNEL_HEADERS` 事件里 CONNECT 头**含**该 `Proxy-Authorization`,edge 回 **200**(未被吞)。
3. **407 路**:令 edge 对无/坏 token 回 `407 + Proxy-Authenticate: Bearer`,观察 Chrome:期望 `ERR_UNSUPPORTED_AUTH_SCHEME`/`ERR_PROXY_AUTH_UNSUPPORTED` 类**干净失败**,**无**凭据缓存污染/无限重试循环(net-log 无反复 `HTTP_TRANSACTION_RESTART_AFTER_ERROR` 打向同代理)。
4. **判据**:正路 200 且头存活 → Bearer 注入可行、方案 A 成立;若 407 路进死循环/头被后续重试剥离 → 取 §3.3 逃生舱①自定义头 `X-Teleport-Tunnel-Token`。

### E-4 `PENDING`:PAC vs fixed+bypass 哪个被 Chrome 接受并正确路由「注册→edge,其余 DIRECT」(承 §3.3 / 本文 §4.3)

配方:下发 `ProxySettings` = `{"ProxyMode":"pac_script","ProxyPacUrl":"data:application/x-ns-proxy-autoconfig,function FindProxyForURL(u,h){ if (h=='demoapp.<域>') return 'HTTPS edge.<域>:8444'; return 'DIRECT'; }"}`;分别访问 `https://demoapp.<域>`(应经 edge)与任一其它站(应 DIRECT)。**判据**:net-log `PROXY_RESOLUTION_SERVICE` / `PROXY_CONFIG_CHANGED` 显示 PAC 被接受、注册 origin 解析到 `HTTPS edge.<域>:8444`、其余 `DIRECT`。对照 `fixed_servers`+`ProxyBypassList`(预期语义反,不满足需求),确认 PAC 为选定形态。

---

## 「seeds 后续计划」总结(客户端 patch 计划的输入)

1. **注入方案候选(按 patch 面升序)**:
   - **A(首选评估)**:浏览器进程 per-Profile service + mojo `CustomProxyConfig`(`rules` 路由 + `connect_tunnel_headers` 注入),经 `CustomProxyConfigClient.OnCustomProxyConfigUpdated` 热更 token。**网络栈零 C++ patch**(注入落点 = 现成 `NetworkServiceProxyDelegate::OnBeforeTunnelRequest`,`services/network/network_service_proxy_delegate.cc:161–170`)。
   - **B(策略一致性硬约束时)**:cloud-policy `ProxySettings` 路由 + 自建/放宽 Teleport ProxyDelegate 注入(须解 `IsInProxyConfig` 把注入绑死路由的耦合,本文 §2.3)。
   - 逃生舱(证伪时,承 §3.3):①自定义头 `X-Teleport-Tunnel-Token`;②MASQUE(总纲 §13.2)。当前静态分析**未触及放弃阈值**。
2. **代理策略 proto 字段(device-manager 侧 `proto/teleport/upstream/chromium/cloud_policy.proto`)**:加 **`optional StringPolicyProto ProxySettings = 118;`** 于 `CloudPolicySettings` **顶层**(非 SubProto);dict 值 = JSON 串。路由形态选 **PAC**(`ProxyMode: pac_script` + `ProxyPacUrl: data:` PAC),`fixed_servers`+bypass 语义反、不用。方案 A 下此 proto 字段**非路由必需**(路由改走 mojo),仅方案 B 需要——**字段号先探明备用**。
3. **per-profile token store 读取路径**:`OnCustomProxyConfigUpdated`(mojo)→ `NetworkServiceProxyDelegate.proxy_config_.connect_tunnel_headers`(CONNECT 时读),浏览器侧经 `ProfileNetworkContextService` 挂 `NetworkContextParams.custom_proxy_config_client_receiver`(`services/network/network_context.cc:2820–2826`)令 delegate 实例化。新增件全在**浏览器进程**,网络栈只读现成通道。
4. **AutoSelect**:策略 URL pattern **必须覆盖 edge 代理端点**(`https://edge.<域>:8444`),非 origin(本文 §3.3 静态定论);config-only 可行性 gate 于 E-1。
5. **无 patch 碰撞**:现有 89 个 patch 均不碰代理/CONNECT/client-cert/AutoSelect(本文 §5),后续 patch 干净落地。

**gate**:E-1/E-2/E-3/E-4 任一证伪 → 按对应退路/逃生舱重定;全过 → 方案 A(或 B)展开为「客户端 patch 计划」。本文档 = 该计划的输入。
