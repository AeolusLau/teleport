# A 组联合真机验收记录(2026-08-16)

对象:`spec/tunnel-webapp-compat` 分支的 A 组交付(teleport + fairyland 两仓)。
环境:`fairyland-ai` VM 内 k3s 全栈 + 宿主 docker 数据面 fixture,基础域 `fairyland.ai`,
租户 `dadou`,受管 profile 由真实 OIDC 纳管流程建立(设备证书已签发,隧道已绑定)。
被测浏览器:`out/mac/arm64/dev/Teleport.app`(本分支 overlay,M151 基线)。

两份 spec 的「联合验收」节共六条,逐条结论与证据如下。**六条全部通过**,
过程中发现并修掉两个**验收装置自身**的缺陷(见 §7),它们都属于「装置会说谎」
一类——不修的话后续每次跑都会得到看似正确、实则无意义的绿。

---

## 1. `include_subdomains` 的地址,根域与子域都可达 —— 通过

只登记了**一条** origin:`subdomains.example.com:443`,`include_subdomains=true`。
子域 `app.subdomains.example.com` **在任何地方都没有登记**(seed、路由行、DNS 白名单都没有),
所以它能被打开这件事本身就是「一条 origin 扩宽了整棵子域」的证据。

诊断页(`teleport://tunnel`)生效路由表:

```
subdomains.example.com:443        含子域        —
```

浏览器实测(两次导航均落地,页面正文来自 fixture 本体):

```
https://subdomains.example.com/      → subdomains.example.com reached (the REGISTERED origin, include_subdomains=true)
https://app.subdomains.example.com/  → app.subdomains.example.com reached (NOT registered anywhere; reachable only because the parent origin says include_subdomains)
```

服务端侧同样正确归因:授权未配前,边缘对**两个名字**都记了同一条
`candidate_scope_paths: [.../app-725e4e84-...]`——即边缘把子域算到了父 origin 所属 app 的
scope 上,而不是当作未知地址。补上 app 授权后两条即通。

> 路由行是**透传**(`next_hop` 留空)。这一点是刻意的:固定下一跳会让连接器不论子域路由
> 有没有被扩宽都拨到同一个后端,该验收就恒绿。透传下连接器必须自己解析
> `app.subdomains.example.com`,被验收的行为才真的被执行到。

## 2. `certpicker.example.com`(`client_cert=false`)必须走浏览器自己的证书选择器 —— 通过

**这条不能用页面正文验收**,原因见 §7.1 与 §7.2。可靠观测点是选择路径本身:

```
SelectClientCertificate url=https://certpicker.example.com/  matching=0  nonmatching=1  web_contents=1
ShowSelector host=certpicker.example.com:443  n=1  can_show=1
```

`matching=0` 即 `AutoSelectCertificateForUrls` **没有**覆盖这个 origin(收敛生效),
随后进入 `ShowSSLClientCertificateSelector`,选择器带着那一张设备证书弹出。
对照:同一次运行里 `gate.fairyland.ai` 与 `edge.fairyland.ai` 都是 `matching=1`,静默选中——
两个隧道自身端点仍在策略里,这正是收敛后应保留的三条之二。

> 上面两行来自**临时插桩构建**(`chrome_content_browser_client.cc` /
> `ssl_client_certificate_selector.cc` 各一行 `LOG`)。插桩已回滚,检出已重新
> `apply_patches.py` 并重编为干净构建。无插桩时的等价观测是:该导航**不落地**
> (选择器把加载挂住),而 §3 的对照站点秒落地。

## 3. `clientcert.example.com`(`client_cert=true`)出示设备证书且无提示 —— 通过

```
SelectClientCertificate url=https://clientcert.example.com/  matching=1  nonmatching=0
```

页面正文(fixture 回显服务端看到的客户端证书):

```
clientcert.example.com reached (origin client_cert=true; expected: no prompt)
client_cert_subject=CN=<person_id>,O=<tenant_id>
client_cert_issuer=CN=Teleport Device CA
```

同一台 Caddy、同一套 `client_auth mode=request` 握手,唯一变量是 origin 级
`client_cert` 开关——§2 与 §3 合起来才构成完整证据。

## 4. `teleport://tunnel` 显示正确的 origin 列表、凭据到期、带 authority 的 CONNECT 结果 —— 通过

一次真实运行的页面内容(节选):

```
纳管状态 已纳管 | 证书选择策略 已下发 | 隧道编排 已启动 | 访问凭据 已持有 | 代理配置 已下发到网络栈
绑定入口(gate) gate.fairyland.ai      边缘节点(edge) edge.fairyland.ai:443
最近一次绑定成功 8:31:37   凭据到期 8:41:37(10 分钟后)   下次自动刷新 8:39:37
生效的路由地址(9)  …  subdomains.example.com:443 含子域
服务端自述陈旧 否   服务端自述截断 否   服务端丢弃条目数 1
路由表摘要 2e866811d4ea1a72906329f8637c9f93025633277e2846a76bd3c3ae17b88dfd
被跳过的条目(0)
最近的 CONNECT 结果(9)
  8:27:27  clientcert.example.com:443  403
  …
```

**CONNECT 归因是这次验收里最直接兑现的一条**:同一个站点在环境被修好的过程中
依次呈现 `403`(边缘拒绝)→ `502`(连接器会话空窗)→ 落地,每一条都带 authority 与状态码。
这正是为归因付上游 patch 想买到的东西——在此之前这些只是一个无差别的
`ERR_TUNNEL_CONNECTION_FAILED`。

## 5. `gate.<D>` 与覆盖它的通配在写路径被拒;强行入库后两侧都不路由且 bind 不自锁 —— 通过

写路径(经控制台 BFF 的真实 API,非直连 DB):

| 请求 | 结果 |
|---|---|
| origin `gate.fairyland.ai:443` | 400 `origin "gate.fairyland.ai" is a reserved host used by the tunnel itself and can never be a web app address` |
| origin `fairyland.ai:443` + `include_subdomains` | 400 `origin "fairyland.ai" covers a reserved host used by the tunnel itself (gate.fairyland.ai, edge.fairyland.ai) — a wildcard cannot carve one name back out, so this address must be narrowed` |
| origin `edge.fairyland.ai:443` | 400,同第一条 |

绕过写路径、直接把 `gate.fairyland.ai:443` INSERT 进 `web_app_origins` 后重投影:

- **bind 成功**(`最近一次绑定成功 8:59:26`,凭据已持有,代理配置已下发)——**没有自锁**;
- 生效路由地址仍为原来的 8 条,`gate.fairyland.ai` **不在其中**;
- **服务端丢弃条目数 1**——服务端投影拒绝了它,并把丢弃计数报到客户端诊断页;
- 路由表摘要未变(`8506d4cb…`),即该条目从未进入路由集合。

客户端「被跳过的条目」为 0 是**正确**的:服务端已经在投影阶段丢掉,客户端无从跳过。
两级都拒、且两级的拒绝都可见,是这条验收要的形状。

## 6. 相同内容重复 bind,`routes_digest` 不变 —— 通过

```
round 0: digest=8506d4cb…  last_success=8:59:26  origins=8
   clicked rebind
round 1: digest=8506d4cb…  last_success=8:59:26  origins=8
   clicked rebind
round 2: digest=8506d4cb…  last_success=9:01:22  origins=8
```

两次不同的成功 bind(8:59:26 → 9:01:22)摘要一致。
反向对照也成立:登记 `subdomains` 之后内容真的变了,摘要随之变为 `2e866811…`——
说明这条稳定性不是「摘要恒定」的假象。

---

## 7. 过程中修掉的两个验收装置缺陷

这两条都不是产品缺陷,但都会让验收**说谎**,所以按缺陷处理。

### 7.1 clientcert/certpicker fixture 返回可缓存的 200

`respond … 200` 没有校验器,属于启发式可缓存。于是**第二次访问会渲染第一次的正文**,
连接根本没有发生。方向恰好最坏:只要有一次合法出示过证书,之后每次都读作
「出示了证书」,无论浏览器实际做了什么。实测到一次 certpicker 显示了 subject 行,
而浏览器其实正停在选择器上、什么都没发。

修复:两个站点块都加 `Cache-Control: no-store`
(`infra/docker/testdata-clientcert/Caddyfile`),新的 subdomains fixture 一并带上。
验收脚本另外用 CDP `Network.clearBrowserCache` + `setCacheDisabled` 双保险。

### 7.2 选择器会被机器上任何一次游离鼠标点击点掉

`certpicker` 反复表现为「静默出示了设备证书」。加堆栈探针后真相是:

```
SSLClientAuthObserver::CertificateSelected
  ← CertificateSelector::Accept()
  ← views::DialogDelegate::AcceptDialog()
  ← views::ButtonController::OnMouseReleased()
  ← -[BridgedContentView mouseEvent:] ← NSApplication sendEvent:
```

——**一次真实的鼠标释放事件**。证书选择器装了全局鼠标捕获 event tap,
无人值守的 GUI 上,机器上任何一次点击都可能被路由进对话框并落在确定按钮上。

结论写进方法论,而不是改产品:**「弹没弹选择器」不能用页面正文验收**。
可靠观测是 (a) 策略匹配数 `matching`,或 (b) 无插桩时「该导航不落地」。
后续把这条纳入 Playwright e2e(独立窗口、无人干扰)时是确定性的;
手工在共用桌面上跑必须知道这个陷阱。

### 7.3(顺带)`seed-demo` 的跨租户 origin 撞名

`seed-demo.sh` 给第二个租户 `xiaodou` 覆盖了 demoapp/adminer/portal 三个 fixture 主机名,
但本次新增的 `clientcert`/`certpicker` 没有跟着覆盖,于是两个租户认领同一个 origin,
边缘按「一个 origin 被两个租户认领」fail-closed 拒绝,**第一个租户的隧道被静默打死**,
表现为一个看起来像路由或策略 bug 的 403。

脚本里原本就有一大段注释警告这个坑——注释没拦住。除了补上缺的两个覆盖,
另加了一条 SQL 断言:两个租户都 seed 完之后,若存在被多个租户认领的 primary origin
就直接失败并列出来。以后再新增 fixture 主机名忘了覆盖,是**响亮**的失败而不是静默的。

---

## 8. 未纳入本次验收的事项

- **通配 origin 覆盖另一租户精确主机**:一度以为这是 §7.3 断言的盲区(它只比对精确
  `(host, port)`)。查了 `rift/internal/authzcache` 后确认**不是盲区,是设计**:
  `admissionSetLocked` 只合并**同租户**的通配行,注释写明了理由——跨租户合并会给任何
  租户一根「在别人精确主机之上注册一个通配就能把它 fail-close 掉」的拒绝服务杠杆。
  所以边缘的冲突判据本来就只在精确 `(host, port)` 上,§7.3 的断言与它同形,**不欠一条**。
  无待办。
- **无插桩的选择器验收**:§2 目前的一等证据来自临时插桩。等价的无插桩判据
  (导航不落地)已验证可用(`localhost:18443` 对照实验中出现过 18s 不落地),
  但没有把它固化成脚本断言。
