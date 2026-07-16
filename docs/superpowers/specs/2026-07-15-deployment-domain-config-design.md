# 部署域名配置(deployment-domain-config)设计

- 日期:2026-07-15
- 状态:已评审定稿(brainstorming 四节逐节确认)
- 配对仓库:`fairyland`(同名分支/worktree;fairyland 侧 spec 见 `../fairyland/docs/superpowers/specs/2026-07-15-teleport-server-identity-design.md`,协议契约以本文 §2.1 为准源)

## 1. 背景与问题

当前所有企业端点域名硬编码在二进制里,由单一 GN 开关 `teleport_use_release_endpoints` 选择 dev(`fairyland.io`)/ release(`douan.cn`)两套值。存在两个问题:

1. **开发环境多栈并行**:并行开发导致同时存在多个服务端栈(`fairyland.io`、`fairyland.test`、…),dev 包只能访问烘焙的 `fairyland.io`,切栈必须重编。
2. **生产环境私有化/气隙部署**:SaaS 之外还要支持私有化与气隙交付,enrollment 域名由客户提供,浏览器必须有机制指向客户自己的纳管域名。

### 1.1 被替换的硬编码盘点(blast radius)

| 端点 | 现位置 |
|---|---|
| DM 服务器 `teleport.<域名>/dm/devicemanagement/data/api` | `patches/components/policy/core/browser/browser_policy_connector.cc.patch` |
| 加密上报 `/dm/v1/record`、实时上报 `/dm/v1/events` | 同上 |
| enroll 起始 `/enroll/start`、register-handler | `src/common/teleport_enterprise_urls.cc` |
| 信任重定向主机(现 dev=`dadou.fairyland.io`,release=`id.douan.cn`) | 同上 |
| gate 放行主机(现后缀 `.fairyland.io` / `.douan.cn`) | 同上 |

策略验签根公钥(`cloud_policy_constants.cc` patch,dev/release 两把)**不在**本设计范围内——它是信任锚,永远烘焙。

**显式出局的两处占位链接**:`settings_localized_strings_provider.cc.patch` 的 `aboutTermsURL` 与 `about_page.ts.patch` 的隐私链接现值均为 `https://teleport.example.com/{terms,privacy}`——它们是 ToS/隐私**法律页占位符**(非浏览器要访问的企业端点、非 douan/fairyland 真域),不随 D 推导,保持独立;本设计不改动它们(其真值化属品牌/法务议题)。全量 grep 已确认 `src/` + `patches/` 无其它被漏掉的 douan/fairyland 端点。

## 2. 核心决策记录(brainstorming 结论)

| # | 决策 | 理由摘要 |
|---|---|---|
| D1 | 设计**统一「部署配置」机制**,本期只消费 enrollment/DM 域名字段;Sparkle feed 等字段在 schema 预留 | 避免将来每个端点各造一套配置通道 |
| D2 | **单一基础域名 D 推导全部端点**,固定主机布局(`teleport.D/{dm,enroll}`)写入私有化交付规范 | 配置面最小、最难配错;与现有推导结构一致 |
| D3 | **域名是数据,信任是代码**:验签根公钥不可配置;私有化/气隙走「统一根签发」模型(根密钥在 OpenBao transit(dev)/ 阿里云 KMS(prod),经 `RootVerificationSigner` 背书,私钥绝不入进程) | 恶意域名的上限是 fail-closed 的可用性损失,不是策略接管 |
| D4 | 投递通道:**平台管控策略 + 机器配置文件双通道**(admin 通道),另有 dev-only 命令行开关与经验证的用户交互输入 | 覆盖有/无 MDM 的客户;与 enrollment token 的双通道模式对齐 |
| D5 | 命令行开关**仅 dev 构建编入**(buildflag 门控),release 二进制中不存在 | 消除原方案 d 的安全顾虑,保留其合理内核 |
| D6 | **客户端配置不含租户字段**:机器链路租户由 enrollment token 服务端 DB 绑定,profile 链路由登录账号(id_token tenant claim + 成员资格校验)决定;slug 只活在服务端 enroll 页 | 两条链路的租户发现均已在服务端解决(实现核实见 §8.1) |
| D7 | **私有化/气隙 + BYOD 自装本期支持**,载体为 `teleport://enroll` WebUI(支持 `?domain=` 深链接);不做定制 pkg,不把 IT 脚本交给终端用户(自助场景的反模式:需 sudo、Gatekeeper 敌意、静默失败、绕过身份验证) | BYOD 上无 admin 通道可用;WebUI 是唯一健全的自助载体 |
| D8 | **交互输入的域名必须先通过服务端身份验证**(根签名,§2.1 协议)才能落盘;admin 通道免验(有可问责主体,启动期不可阻塞网络) | 把 BYOD 钓鱼入口掐断在落盘前 |
| D9 | 客户端**移除 `accounts.D` 等一切服务端拓扑细节**:客户端知识收敛为 D + `teleport.D` 上的固定路径 + gate 精确主机白名单(§3.4a,含 `teleport.D` 与拦截页动态注入的 OP host) | `accounts.D` 在客户端无承重消费点;不编码自己不消费的拓扑 |
| D10 | 中央租户目录(slug→域名,原方案 b)、每客户二进制(原方案 a)**否决** | 气隙够不着中央服务;单一制品原则 |
| D11 | BYOD 设备**只做 profile 纳管,不做机器纳管**——机器纳管以「能种 enrollment token = 组织管理此机器」为前提 | 与 Chrome 两层模型一致(公司设备 CBCM + profile;BYOD 仅 profile) |
| D12 | 系统级 OP 拓扑调整(enrollment 走 `accounts.D` 直发 token、登录后选租户)**记为 fairyland 侧独立议题**,非本设计依赖 | 当前 slug-first/per-tenant-OP 流程在任何 D 下端到端成立 |
| D13 | admin 通道(第 2/3 级)必须验证**来源不可伪造**:第 2 级强制 `CFPreferencesAppValueIsForced`(仅 MDM 强制值,非任意用户可写偏好);第 3 级校验文件属主 uid==0 且非 group/world 可写 | 否则本地非特权用户可注入未验证域名并压过第 4 级,击穿 D8。照抄现有 token 读取的同款检查(评审 BLOCKER 1/2) |
| D14 | 身份声明**装进带类型标签的 proto**(方案 ①),复用 root-signer 现有 `/sign` 的 proto-only 硬化路径签名,不放宽守卫、不新开签名口子;`not_after` 是该 proto 的字段 | 根密钥恒只签结构化带类型标记消息,保持信任链域分离;规避「crown-jewel 签任意字节」预言机(评审 MAJOR 5 / 运维 BLOCKER 1) |
| D15 | 身份 blob **有过期**(`not_after`),交付/续订时重签,resolver 离线重验时校期 | 把「祝福过的部署被弃/被攻陷 → 经 enroll 页招募任意外部受害者」的永久武器降级为有时限窗口(评审 MAJOR 4) |
| D16 | gate 放行从「`.D` 后缀」收敛为**精确主机白名单**(`teleport.D` + enroll-landing 在拦截页动态给出的 per-tenant OP host) | D 可为客户主内网域时,`.D` 后缀等于放开 `*.D` 全部内网站点给未纳管浏览器,瓦解「先 enroll 才能上网」(评审 MAJOR 3) |
| D17 | 域名设置页命名为 **`teleport://enroll`(→ `chrome://enroll`)**(原 `connect`) | 从用户心智看是「把浏览器纳入组织」的入口(设域是纳管第一步);与服务端 `enroll/start` OIDC 端点是不同层的东西,文档注明 |
| D18 | **受管设备锁定 enroll 页**(禁止用户自助换域),谓词 `IsDomainChangeLocked()` = 第 1/2/3 级来源 **或** 专用锁策略 `RestrictDeploymentDomainChange`(强制 managed pref);SaaS 受管采**专用布尔锁策略**而非钉官方域(与域名值解耦、抗官方域轮换、admin 一个开关)。锁定按**管理员显式声明**判定;「机器 CBCM 已纳管自动锁」评估后**否决**(冗余 + 隐式机器态脆弱,§4.5 兜住僵尸态) | 「可自助换域」仅对 BYOD 成立;公司设备(私有化/SaaS)靠显式策略锁。详见 §4.6 |

## 3. 架构设计(第 1 节定稿)

### 3.1 总览

新增部署配置子系统,核心 `src/common/teleport_deployment_config.{h,cc}` + `_mac.mm`(读管控偏好)。启动早期解析出**一个基础域名 D**,进程生命周期内不可变(变更需重启)。`teleport_enterprise_urls.cc` 与 `browser_policy_connector.cc.patch` 中的全部域名常量改为从 D 推导的函数调用。

### 3.2 配置来源与优先级(高 → 低)

| 级 | 来源 | 载体 | 场景 |
|---|---|---|---|
| 1 | 命令行开关 `--teleport-deployment-domain=<D>` | 进程参数;**`#if !BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` 门控,release 不编入** | dev 多栈切换 |
| 2 | 平台管控策略键 `DeploymentDomain` | macOS 管控偏好,`cn.douan.Teleport` 域;`CFPreferencesCopyAppValue` **且** `CFPreferencesAppValueIsForced` 同时为真才采信(**逐字同构于现有 token 读取** `browser_dm_token_storage_mac.mm.patch`——区分 MDM 强制值与任意用户可写的 `~/Library/Preferences` plist);**不进 Chrome 策略 schema**(引导配置须先于策略系统可用) | 私有化/气隙 + MDM |
| 3 | 机器配置文件 `/Library/Teleport/DeploymentConfig.json` | JSON(schema 见 §3.3);读取前 `stat` 校验**属主 uid==0 且非 group/world 可写**(`!(mode & (S_IWGRP\|S_IWOTH))`),不满足即跳过 + 记 ERROR | 私有化/气隙 + 无 MDM(IT 脚本/装机流程写入) |
| 4 | 用户接受值(enroll 页验证通过后写入) | Local State 存**自认证条目** `{domain, identity, signature}`,启动期离线重验(§5.0) | 私有化/气隙 BYOD 自装 |
| 5 | 烘焙默认值 | buildflag:dev=`fairyland.io`,release=`douan.cn` | SaaS(零配置) |

### 3.3 机器配置文件 schema

```json
{
  "domain": "acme.internal",
  "update_feed_url": "(预留字段,本期不消费;气隙升级分发另行设计)"
}
```

交付规范约束 `/Library/Teleport` 创建为 `root:wheel 0755`(该目录已是 enrollment token 文件的既有信任位置)。**顺带复核**:现有 enrollment token 文件回退(`kEnrollmentTokenFilePath`)读取时是否也做了同款属主/权限校验;若无,作为同类加固一并补上(记入实现工作项,勿在本设计静默假定其已安全)。

### 3.4 端点推导(输入:基础域名 D)

| 端点 | 推导规则 |
|---|---|
| DM 服务器 | `https://teleport.D/dm/devicemanagement/data/api` |
| 加密上报 / 实时上报 | `https://teleport.D/dm/v1/record`、`https://teleport.D/dm/v1/events` |
| enroll 起始 / register-handler | `https://teleport.D/enroll/start`、`https://teleport.D/enroll/profile-enrollment/register-handler` |
| 信任重定向主机(throttle 兜底) | `{https://teleport.D}`(见 §3.5) |
| gate 放行主机白名单 | `{teleport.D}` ∪ enroll-landing 在拦截页动态下发的 per-tenant OP host(见 §3.4a) |

主机布局 `teleport.D/{dm,enroll}` 是私有化交付规范的硬约定(fairyland 侧文档化)。

### 3.4a gate 放行:精确主机白名单(替代 `.D` 后缀,评审 MAJOR 3)

**问题**:原设计 gate 放行 `.D` 后缀。SaaS 下 `.douan.cn` 是厂商自有域无妨,但 D 可配置后,私有化客户的 D 往往就是其主内网域(如 `acme.internal`),`.D` 后缀会把 `*.acme.internal` 下**全部内网站点**对未纳管浏览器放行,直接瓦解「先 enroll 才能上网」这一核心管控。

**改为精确主机白名单**:gate 只放行 enrollment 流真正需要的固定主机——
- `teleport.D`(enroll-landing / register-handler / DM,全在此单主机);
- per-tenant OP host 与 `accounts.D` 登录跳板:这些是登录链路中间跳转,**由服务端在 gate 拦截页动态注入**(拦截页由客户端渲染,可携带本次 enrollment 允许的额外放行主机列表),而非客户端静态编码或后缀通配。

`IsEnrollmentFlowUrl` 从「后缀匹配」改为「精确 host 集合成员判定」(host 相等,`https` only)。gate 逻辑改动需相应重写单测(§6)。**跨仓影响**:拦截页动态放行主机的下发格式,记入 Phase 2 客户端拦截页工作项;在 fairyland OP 拓扑未变期间,per-tenant OP host 形如 `<slug>.D`,由服务端登录重定向前置知晓并注入。

**端口语义**:D 允许携带端口(dev/内网场景,`host[:port]`)。端口**参与 URL 构造**(如 `https://teleport.acme.internal:8443/dm/...`)与 gate 白名单主机的 host:port 相等判定;身份验证的 `payload.domain` 比对针对含端口的完整规范化 D(§4.2 规范化契约,mint 侧与客户端共用同一 canonical 形式,见 §4.1)。规范化统一走硬化 URL 解析(§4.2),不做裸字符串切分。

### 3.5 信任重定向兜底列表的说明(dadou 技术债清偿)

`EnterpriseTrustedRedirectHosts()` 喂给上游 OIDC 捕获 throttle 的重定向链检查,该检查在我们的架构中**双重不可达**:① shipped 配置开启 generic-OIDC,链检查被跳过;② 我们的 token 交付走 register-handler 的 header 拦截路径,不走该 URL-fragment 捕获路径。列表纯为保持上游函数契约完整。推导规则选 `{https://teleport.D}`(客户端唯一有业务往来的主机),替换两个无法泛化的具体 OP 主机占位符——dev 的 `dadou.fairyland.io`(测试租户 slug)与 release 的 `id.douan.cn`(身份/OP 主机)。此为「给防御性死代码换推导正确的默认值」,非行为变更。

### 3.6 时序约束

DM URL 在 `BrowserPolicyConnector` 初始化时即被消费,解析须在启动极早期同步完成(一次 CFPreferences 调用 + 一次数十字节文件读,与上游同步读 token 文件先例一致)。

## 4. 服务端身份验证与 enroll 页(第 2 节定稿)

### 4.1 server-identity 协议(跨仓契约,本文为准源)

```
GET https://teleport.<D>/dm/server-identity        (禁重定向跟随,超时 10s,仅 https)

200 OK  application/octet-stream          响应头:Cache-Control: no-store
<body> = 一段自描述容器:{ signed_bytes, signature }
  signed_bytes = 序列化的 ServerIdentityData proto(带类型标签,见下)
  signature    = 根密钥对 signed_bytes 的 RSA-PKCS1v1.5-SHA256 签名

ServerIdentityData(带类型标签的 proto,方案 ① / D14):
  message_type = "TeleportServerIdentity"   // 域分离标签,验签后必校
  version      = 1
  domain       = "<canonical D>"            // §4.2 规范化契约的 canonical 形式
  not_after    = <Unix 秒>                   // 过期时间(D15)
```

- **签名密钥 = 验签根**(dev = OpenBao transit 根 / release = 阿里云 KMS 根,与策略链**同一信任锚、同一 two-root-key buildflag 选择**);算法 = RSA-PKCS1v1.5-SHA256(root-signer 现算法),不引入新原语。
- **域分离(D14,评审 MAJOR 5)**:根密钥恒只签**带 `message_type` 类型标签的结构化 proto**。身份声明因此**复用 root-signer 现有 `/sign` 的 proto-only 硬化路径**——不放宽守卫、不新开裸字节签名口子。客户端验签后**必须校 `message_type == "TeleportServerIdentity"`**,拒绝把策略验签 blob(`PublicKeyVerificationData`)当身份 blob 用,反之亦然。是否复用 `PublicKeyVerificationData` 承载还是新增 proto,由 fairyland 侧决定并在其 spec 定型(准源只约束:带类型标签、经现有硬化路径、算法不变)。
- **`domain` 在签名内**,客户端校验 `payload.domain == 候选域名`(防跨部署重放)。TLS 管传输完整性,根签名管部署真实性,正交互补。
- **过期(D15,评审 MAJOR 4)**:`not_after` 在签名内。resolver 离线重验第 4 级、enroll 页验证新输入时**均校当前时间 < not_after**;过期即拒。私有化给较长有效期(建议默认 1 年),交付/续订时重签。这把「被弃/被攻陷的祝福部署经 enroll 页招募任意外部新受害者」的**永久武器降级为有时限窗口**。策略验签链本身的吊销/版本单调另立技术债跟踪(见 §8.4)。
- **外层容器不可信**:验签算法**固定**(不可协商),客户端只信 `signed_bytes` 内(已签)的 `version`/`message_type`/`domain`/`not_after`;任何未签的外层字段仅作非安全的解析路由提示,不参与安全决策。
- **静态产物,运行时不碰根私钥**:blob 交付/续订时由 device-manager 经 `RootVerificationSigner`(→ transit/KMS)签好并落配置,运行时原样对外(气隙下 device-manager 够不着 KMS,故**必须**是预签静态产物——见 §7 气隙前置依赖)。

**规范化一致(评审 MINOR 11 / 运维 MINOR 7)**:`domain` 的 canonical 形式由 §4.2 单一定义(小写 ASCII punycode host + 可选 `:port`、无 trailing dot);fairyland 铸造侧与客户端**共用同一规范化契约**,比对为 canonical 字节精确相等——避免大小写/尾点/IDN 差异造成「合法 blob 永远匹配失败」或「过松匹配放行错域」。

**验证适用边界**:根签名验证只把关**交互式输入**(第 4 级)。第 2/3 级 admin 通道免接受前验证——非交互场景不可在启动期阻塞网络,且有可问责运维主体(其来源不可伪造性由 D13 保证);配错/恶意的兜底是策略验签 fail-closed。

### 4.2 enroll 页(`teleport://enroll`)

- **载体**:WebUI 内部页,挂现有 `teleport://` 方案别名(复用 `teleport_url_scheme` 主机重写,query 保留)。
- **入口**:地址栏粘贴(用户主路径;web 内容无法导航到特权 scheme,文档必须写「复制粘贴到地址栏」而非「点击」)、OS 外部协议唤起、gate 拦截体验中的客户端渲染链接(挂点实现期定,约束:未 enroll 时必须可达)。SaaS 用户全程不会遇到此页。
- **深链接**:`teleport://enroll?domain=acme.internal` 预填域名并立即发起验证;不带参数 = 空输入框。一个页面两个形态。
- **必须保留一次显式确认点击**(导航不得变更安全敏感状态——否则等于自设 CSRF):

```
粘贴 teleport://enroll?domain=acme.internal 回车
→ 预填 + 后台发起 server-identity 验证
→ 通过:展示「连接到组织服务器 acme.internal?」+ [连接]
→ 点击 → 落盘条目 → done 视图:「已连接,重启后生效」+ [重启 Teleport]
   (失败:原地展示错误分类,输入框可编辑重试)
```

- **输入规范化(硬化 URL 解析,评审 MINOR 8)**:统一走 `GURL("https://" + input)` 解析,取 canonical `host()` + `EffectiveIntPort()`;**拒绝**含 userinfo(`@`)、路径、query、fragment、多冒号、非法字符的输入(防 `acme.internal:8443@evil.com`、IPv6 混淆等 URL parsing confusion)。canonical 形式 = 小写 ASCII punycode host + 可选 `:port`、无 trailing dot;`teleport.D` 用解析后的 host/port **重组**而非裸拼接。此 canonical 契约即 §4.1 的比对基准,mint 侧共用。
- **IDN 同形字防护(评审 MAJOR 6)**:确认对话框与 done 视图**一律以 punycode(ASCII)形式展示域名**(或套用 Chromium IDN 显示防欺骗降级规则),杜绝 `аpple.internal`(西里尔 а)在唯一人工确认点冒充 `apple.internal`。域名一律经 `textContent` 渲染,杜绝 `?domain=` 注入 HTML。
- **可改性判定(统一走 §4.6 锁定谓词,不看是否已 enroll)**:页面在**加载时**经 Mojo `GetState()` 取 `{domain, source, locked, canUnbind}` 决定视图。`locked` 由 §4.6 的 `IsDomainChangeLocked()` 统一给出——命中即**受管**:只读展示当前域名与来源(「由你的组织管理」样式),**隐藏输入框与验证按钮**并给不可更改文案。未锁定时(纯 BYOD:仅第 4/5 级来源、非受管设备)可写:已绑定则展示当前绑定 + 更改表单 + **解除绑定**入口(`canUnbind`),未绑定则纯表单。第 4/5 级恒**不因「已 enroll」而拒改**——BYOD 纳管后再换指新部署域是**合法自助换域**,落盘后重启由 §4.5 迁移(重上锁 + 清 DM token + 按新 D 重纳管)收口。
- **Mojo 面(browser ↔ enroll 页)**:`GetState() → {domain, source, locked, canUnbind}`(加载态);`Verify(domain) → VerifyResult`(fetch + 根验签;受管时防御性再拒);`Confirm() → bool`(落盘第 4 级条目);`Unbind()`(清第 4 级条目,回落烘焙默认;已 enroll 则重启后经 §4.5 迁移);`Relaunch()`。
- **实现形态(撞既有跨 target gotcha)**:enroll 页是 WebUI,其 controller/资源注册**必须进 chrome target**(与 About 页同理,不得进 `//teleport` source_set,否则 GN 依赖环)——故页面大头落在 `patches/`(一文件一 patch,涉 resources/BUILD.gn/webui_config 等多个上游文件)。§6 的「handler 状态机 gtest 单测」**要求把纯逻辑(规范化→验签→落盘决策)抽成 `src/common` 纯函数**(gate_logic 既有模式)才可单测;WebUI 壳走冒烟。实现工作项须显式包含此切分。

### 4.3 私有化 BYOD 全链路数据流

```
装通用包 → 启动,resolver 取烘焙默认(douan.cn)→ gate 拦截
→ 按 IT 文档粘贴 teleport://enroll?domain=acme.internal
→ GET teleport.acme.internal/dm/server-identity → 根验签 + 域名匹配 ✓
→ [连接] → 写 Local State 条目 → [重启]
→ resolver 离线重验条目(验签+类型标签+域名+未过期)✓ → D=acme.internal
→ gate 跳 teleport.acme.internal/enroll/start(slug 在服务端页输入)
→ OIDC 登录 → profile enroll → 放行
```

### 4.4 场景覆盖矩阵

| 场景 | 域名来源 | 需要 UI | enroll 页可改性(§4.6) |
|---|---|---|---|
| SaaS + BYOD | 烘焙默认,零配置 | 否 | 可改(纯 BYOD) |
| SaaS + 受管设备 | 烘焙默认 + `RestrictDeploymentDomainChange` 锁策略 | 否 | **锁定**(只读) |
| 私有化/气隙 + 受管设备 | 管控偏好 / 机器配置文件 | 否 | **锁定**(来源即锁) |
| 私有化/气隙 + BYOD 自装 | enroll 页(深链接) | 是(仅此格) | 可改(纯 BYOD) |
| dev 多栈 | 命令行开关 | 否 | **锁定**(来源即锁) |

### 4.5 已 enroll 浏览器换域(admin 通道推送 / BYOD 经 enroll 页 自助)的定义行为(评审 MAJOR / 运维 MAJOR 3)

存在「已 enroll 浏览器,启动解析出的 D ≠ enroll 时的 D」的情形,有两条来路:① 第 2/3 级 admin 通道无条件「下次启动生效」(MDM 推错值 / 管理域迁移);② BYOD 用户经 enroll 页(第 4 级)主动换指新部署域(合法自助换域,§4.2)。原设计未定义该行为,会落入「gate 放行但策略拉取全线失败」的半受管僵尸态(旧域签发的 DM token 对新 server 是 DEVICE_NOT_FOUND;旧 enrollment token 在新部署 DB 中也不存在,重注册亦失败)。

**定义行为**:
1. **持久化 enroll 时的域名**(enroll 成功时随管理状态存下 `enrolled_domain`)。
2. 启动时若 `resolved_D ≠ enrolled_domain`:视为**管理域迁移信号**,进入显式「需重新纳管」态——清除缓存的机器 DM token + 重置 profile enroll 状态、**重新上锁 gate**,按新 D 走全新 enrollment;**不**静默半受管运行。
3. **可见 + 可诊断**:记 ERROR;`chrome://version` 标注 `Deployment domain changed: <old> → <new> (re-enrollment required)`。
4. **支持 runbook**:交付文档需含「管理域迁移」条目(何时会触发、终端用户会看到什么、IT 侧应如何协调 token/域名切换),不把它当边角留白——MDM 推错值在私有化舰队是高概率事故。

此行为把非目标 §8.2「已 enroll 后换域属支持流程」落地为**统一的受控重纳管 + 告警**:无论换域来自第 2/3 级 admin 通道(从「静默照做」收紧)还是第 4 级 BYOD 自助换指,都走同一条迁移路径;仅当更高优先级来源已锁定 D 时 enroll 页才只读拒改。二者共同构成完整、无僵尸态的语义。

### 4.6 受管设备锁定 enroll 页(禁止用户自助换域,评审衍生)

**问题**:enroll 页的「可自助换域」是为 **BYOD** 设计的。**公司设备**(无论私有化还是 SaaS)不应让终端用户改域。锁定按**管理员显式声明**判定(不做隐式设备态推断):

| 设备形态 | 信号 | 现状 |
|---|---|---|
| 私有化/气隙受管 | D 经第 1/2/3 级 admin 通道下发(命令行 / 管控偏好 / 机器文件) | 已能检测(来源即锁) |
| SaaS 受管(D=官方默认,无 platform 域名策略) | **专用锁定策略** `RestrictDeploymentDomainChange`(MDM 下发的强制 managed pref) | 本节新增 |
| 纯 BYOD | 以上皆无 | 可写 |

**锁定谓词**(客户端):
```
IsDomainChangeLocked() =
    (DeploymentDomainSourceLevel() ∈ {kCommandLine, kManagedPref, kMachineFile})   // 第 1/2/3 级
 || (RestrictDeploymentDomainChange 强制 managed pref == true)                       // 专用锁策略
```

**决策:SaaS 用专用锁策略而非「用域名策略钉住官方域」**(评估两方案):
- **专用布尔锁策略(采纳)**:`RestrictDeploymentDomainChange` 强制=true 即锁,与**域名值解耦**。D 仍走第 5 级烘焙默认,故**官方域名轮换自动跟随、不断裂**;admin 只需一个开关,不必手填官方域名。
- 「域名策略钉官方域」(否决为唯一手段):把「哪个域」与「谁拥有」混淆;钉死的值在官方域名轮换时**断掉每个租户**;且要求 admin 手填官方域名(多此一举)。但它作为**私有化/SaaS-偏好钉值**路径**自然保留**——admin 一旦设第 2/3 级域名策略即命中谓词首项,无需额外配锁。

**「机器级 CBCM 已纳管」不作为锁信号(评估后否决)**:曾考虑「机器 DM token 有效即自动锁」。否决理由:① **冗余**——正常公司流程里能 CBCM 纳管即已走 MDM,同一通道可直接配锁策略或域名策略,几乎不新增覆盖;② **反直觉且脆弱**——机器 token 生命周期长、跨 profile、难排查,把 UX 锁绑在隐式机器态上(实测:一台曾 CBCM 纳管的 dev 机器,纯净 profile 也被误锁);③ **兜底仍在**——即便 CBCM 设备用户改域,§4.5 迁移保证无僵尸态。代价(管理员漏配锁策略时,CBCM-默认域设备可被用户改域→脱管)由**交付规范要求受管客户必须显式配锁策略/域名策略**兜住(§7 / 交付清单)。

**纯客户端**:两个信号全在客户端读取(锁策略是 MDM/管控偏好下发的 managed pref,纳管前即可读,**不走云策略**——云策略需先 enroll,存在鸡生蛋)。谓词纯函数 `IsDomainChangeLocked(source, restrict_forced)` 走 gtest;两个环境读取(source 级别 / `CFPreferencesAppValueIsForced` 锁 pref)在调用点完成、注入谓词(gate_logic 既有注入模式)。

**边界(Q3:重装抢先设域 → 域策略后到)**:优先级压制不变量(§5.1 不变量 4)保证第 2/3 级恒高于第 4 级——域策略同步到位后,下次启动 D 直接解析为公司域,用户那条第 4 级条目被永久压制;若用户已 enroll 到自选野域,§4.5 迁移强制向公司域重纳管。窗口期无安全洞(受保护应用仅经公司网关可达,野域够不到)。**自动收敛,无需额外机制。**

## 5. 安全模型(第 3 节定稿)

### 5.0 第 4 级的自认证设计

Local State 是用户权限可写文件(核实:该 build 的 Local State **不接 tracked-pref 哈希保护**,profile 侧哈希种子亦 `#if GOOGLE_CHROME_BRANDING` 门控、非品牌构建为空——明文用户可写),若只存裸域名,用户态 malware 可绕过 enroll 页直写 pref,身份验证形同虚设。故第 4 级存**完整条目 `{domain, identity, signature}`**,resolver **每次启动离线重验**(烘焙根公钥验签 + `message_type` 类型标签校验 + 域名匹配 + `not_after` 未过期,零网络);任一不过 → 丢弃该级、记日志、下探。malware 伪造不出链到根的签名;搬运其它真部署的合法 blob 只能指向那个真部署,且受 `not_after` 时限约束(有界,同深链接场景,§5.2 残余风险①)。

### 5.1 安全不变量

1. **信任锚不可配置**。任何通道注入任何域名,攻击上限 =「指向一个无法出示合法签名策略的服务器」→ enrollment 失败、gate 持续拦截。**错误配置的终态是 fail-closed 的可用性损失,永远不是静默接管。**
2. **release 无后门**:开关代码 release 不编入(非「存在但禁用」)。
3. **交互输入必经根签名验证**;admin 通道免验但有可问责主体 + 策略验签兜底。
4. **用户级压不过机器级**:受管设备上 malware 种的用户 pref 被 admin 通道按优先级覆盖。

### 5.2 逐通道威胁分析

| 通道 | 攻击者需要 | 能达成 | 兜底 |
|---|---|---|---|
| 命令行开关 | dev 构建 + 本地执行权 | 任意域名 | release 不编入(buildflag);dev 用 dev 根,与生产信任链隔离;**运维约束:dev 构建绝不对外分发**(dev 私钥有意入 fairyland 仓,dev 构建=可随意改域+仓内有私钥可签合法策略;构建/分发管线须护栏保证只有 release 配置可签名公证) |
| 管控偏好(MDM) | **控制 MDM(令 `IsForced` 为真)/ root** | 任意域名 | D13:仅采信 `CFPreferencesAppValueIsForced` 的强制值,普通用户写 `~/Library/Preferences` plist **不生效**;已拥有整机者可换整个 .app,非新增面;策略验签 fail-closed |
| 机器配置文件 | **root 写权限**(uid==0,非 group/world) | 任意域名 | D13:读前 `stat` 校验属主+权限,非 root-owned/组或全局可写即跳过;策略验签 fail-closed |
| Local State（种入） | 用户态写权限 | 仅能种「其它真部署」的合法凭证,且受 `not_after` 时限 | 启动期离线重验(§5.0);机器通道优先级压制 |
| Local State（删除降级，评审 MINOR 7） | 用户态写权限 | 删条目 → 静默回落第 5 级烘焙默认(私有化 BYOD 上=改指厂商 SaaS `douan.cn`) | 终态仍 fail-closed(非接管),但属**隐私信标 + 可用性**:`chrome://version` 域名+来源行使回落可见;曾 enroll 过则走 §4.5 重纳管告警而非静默 |
| 深链接 `?domain=` | 诱导用户粘贴 + 点确认 | 指向某个**真**部署 | 根签名挡掉一切非祝福域名;显式确认以 punycode 展示目标(§4.2 IDN 防护) |
| 网络 MITM | 路径中间人 | 阻断(DoS) | 全链 https、身份获取禁重定向;签名使伪造不可能 |

**已接受的残余风险**:① **被祝福的真部署被弃/被攻陷/内鬼**(其密钥仍有效),可站起 `teleport.<其域>` 回放身份 blob + 用手中仍有效的租户密钥签合法策略,经 enroll 页把**与该部署无关的外部新受害者**钓入完整纳管——不同于「SaaS 租户在自有范围作恶」,enroll 页把 self-harm **放大为招募外部受害者**。本设计以 `not_after`(D15)把它从**永久武器降级为有时限窗口**;彻底止血需策略验签链的版本单调 + 吊销,登记为技术债(§8.4),Phase 2 私有化交付前作 go/no-go 复核。② `kRequireEnrollmentToBrowse` 的防篡改是 enrollment-gate 既有独立议题,本设计不改变其现状。

### 5.3 错误处理

**启动期解析原则:单级失效即跳过、记 ERROR 日志、继续下探**;烘焙默认永远存在,浏览器永远能启动。错误配置表现为「enroll 到错误服务器失败」——可见、可诊断,而非浏览器拒启。

| 故障 | 处理 |
|---|---|
| 开关/管控偏好/文件值非法(非域名、乱码) | 跳过该级 + 日志 |
| 配置文件缺失 / JSON 损坏 | 同上 |
| Local State 条目验签失败 / 类型标签不符 / 域名不匹配 / 已过期(not_after) | 丢弃 + 日志 + 下探 |
| 各级域名规范化 | 统一走硬化 URL 解析(§4.2):`GURL` canonical host + port,拒 userinfo/路径/query/多冒号,punycode |
| 运行中配置变更(MDM 推送/文件被改) | 下次启动生效(进程内不可变);若换域且已 enroll 走 §4.5 重纳管 |

**enroll 页错误分类**(中文提示,可重试):无法连接 / TLS 错误 / 非 200(不是 Teleport 服务器)/ 响应格式错误 / 类型标签不符 / 签名无效 / 域名不匹配 / 身份已过期。**受管锁定**(§4.6 `IsDomainChangeLocked()` 命中)不属「验证错误」,而是加载态经 `GetState()` 直接渲染只读视图(无输入框/验证按钮 + 「由你的组织管理」文案),不进验证流。

**可诊断性**:`chrome://version` 增加一行,展示生效域名及来源级别,如 `Deployment domain: acme.internal (source: machine config file)`。

## 6. 测试策略(第 4 节定稿)

**客户端(//teleport,TDD/gtest):**

| 对象 | 覆盖 |
|---|---|
| DeploymentConfig resolver | 五级优先级全排列;**第 2 级非 forced 值被忽略**、**第 3 级非 root-owned/组写文件被忽略**(D13);单级非法跳过下探;硬化规范化(userinfo/多冒号/IPv6/路径注入拒绝);条目离线重验(通过/验签失败/类型标签不符/域名不匹配/not_after 过期);烘焙兜底 |
| 端点推导 | D → 四组 URL + gate 白名单(`teleport_enterprise_urls_unittest` 从断言常量重写为断言推导) |
| 身份验证库 | 根密钥验签、类型标签校验、域名绑定、not_after 过期、外层字段不可信、base64/proto 畸形 |
| enrollment gate | 从后缀匹配改为**精确主机白名单**(§3.4a);`teleport.D` 命中、`evil.acme.internal` 类子域**不再命中**、动态注入主机命中 |
| enroll 页纯逻辑 | 规范化→验签→落盘决策抽为 `src/common` 纯函数单测(§4.2 切分);IDN 输入→展示 punycode;mock fetcher 驱动状态机;WebUI 壳走冒烟 |

**服务端(fairyland,Go)**:`/server-identity` handler 单测;身份 blob 铸造工具单测(带类型标签 proto 编码、经现有 `/sign` 硬化路径、not_after);dev 根签发↔客户端验签往返测试(篡改 domain/字节/类型标签/过期 → 验签失败)。

**联合 e2e(进 `scripts/smoke_check.md`)**:① `--teleport-deployment-domain=fairyland.test` 实际 enroll 到测试栈;② 文件通道生效;③ 管控偏好通道(root 写 Managed Preferences 模拟);④ 深链接全链路(粘贴→验证→确认→重启→enroll);⑤ `chrome://version` 域名+来源行;⑥ **优先级压制**:第 4 级条目存在时被第 2/3 级覆盖(验安全不变量 4);⑦ **更高优先级来源(第 1/2/3 级)生效 → enroll 页只读拒改**(注:已 enroll 但仅第 4/5 级来源时**不**拒改,见 ⑧);⑧ **已 enroll + 换域 → §4.5 重纳管**,覆盖两来路:admin 通道推新 D、及 BYOD 经 enroll 页 自助换指新 D(重上锁 + 清 DM token + 按新 D 重纳管);⑨ **升级保持配置**:Sparkle 原地升级后第 4 级条目/`/Library` 文件/生效域名不变;⑩ **负向真栈**:server 返回错误域名/过期 blob → enroll 页拒绝并正确分类;⑪ **受管锁定(§4.6)**:(a) `RestrictDeploymentDomainChange` 强制=true → enroll 页只读、无输入框/验证按钮;(b) BYOD 未锁定 + 已绑定 → 显示当前绑定 + 解除绑定入口,`Unbind()` 清条目回落默认;⑫ **加载态**:`GetState()` 正确返回 `{domain, source, locked, canUnbind}`,三视图(只读 / 已绑定可改 / 未绑定)按之渲染。

## 7. 实施分期与跨仓配对

- **Phase 1 — 纯客户端,零 fairyland 代码改动**:resolver + 第 1/2/3/5 级(含 D13 来源校验)+ 端点推导重构 + gate 精确白名单(§3.4a)+ §4.5 换域重纳管 + `chrome://version` 诊断行 + 全部单测。**交付:dev 多栈、SaaS 的客户端机制就绪;私有化受管设备的客户端机制就绪**(注:「私有化受管设备」真正可用还需 fairyland 侧存在私有化部署形态——见 Phase 2 工作项 P2-F1,当前 Caddyfile 仅 dev、硬编码 `teleport.fairyland.io`,无 `teleport.<D>` 模板;故 Phase 1 只交付**客户端就绪**,非端到端私有化)。
- **Phase 2 — 双仓配对**:
  - fairyland:`/server-identity` 路由(chi 平铺注册,`/healthz` 已是公开 GET 先例);身份 blob 铸造(带类型标签 proto,经现有 `/sign` 硬化路径,**非新 CLI 子命令、非放宽守卫**;dev 照抄 `root-key-seed` 一次性 job 直读 PEM 模式在 compose 启动预生成);Caddy 路由**核实(预期 no-op**——`handle /dm/*` + `strip_prefix /dm` 已覆盖,device-manager 内部路由为 `/server-identity`);**P2-F1 私有化交付规范 v1**(主机布局硬约定 + Caddy/网关 `teleport.<D>` 模板 + `DeploymentConfig.json`/MDM key 的客户 IT 文档 + blob 落位路径 + §4.5 管理域迁移 runbook)。
  - 客户端:验证库(带类型标签 proto + not_after)+ 第 4 级条目 + enroll 页(patches + 纯逻辑切分,§4.2)+ 深链接 + gate 拦截页动态放行主机注入。
  - 联合 e2e(§6 ①–⑩)后双仓背靠背合并。**交付:私有化/气隙 BYOD 自装**。

**气隙/release 前置依赖(评审 MAJOR 2/4,两 spec 显式登记)**:Phase 2 的 release/气隙链路依赖两块**尚未立项/未执行**的工作,**不得默认其存在**:① **生产根仪式执行**(阿里云 KMS 根 + `teleport_release_policy_key_is_real` 翻真,当前 `KMSSigner` 为 stub、fail-closed);② **气隙离线租户背书机制**——现状租户密钥背书是「首次拉策略在线懒式」完成(`policy/onboard.go`),气隙下 device-manager 够不着 KMS,该在线路径走不通,需离线预签租户验证工件 + 导入机制。**决策(默认)**:在两 spec 显式登记①②为 Phase 2 气隙交付前置;**气隙端到端从 Phase 2 交付承诺降级为 dev/canary 验证**,真实气隙交付待①②立项完成后再排期。此项若需调整由后续决策点确认。

跨仓规则:两仓同名分支/worktree(`deployment-domain-config`),fairyland 侧独立 spec 引用本文 §4.1 为协议准源,联合验证通过才允许合并。

## 8. 附录

### 8.1 租户发现链路核实(D6 依据,fairyland 代码证据)

- 机器链路:enrollment token 由控制面 `CreateEnrollmentToken(tenant_id, label)` 租户维度签发(`device-manager/internal/grpcserver/server.go`),DB 存 `(token_hash, tenant_id)`;token 为租户级共享引导凭证(可多发、按 label 吊销),设备注册时 `Resolve(token)→tenantID`,每设备换发独立 DM token(`internal/register/device.go`);机器级租户策略登录前即下发(`internal/repo/policy_repo.go`:DM token→tenant→machine-scope assignment,租户密钥签名)。
- profile 链路:用户在 enroll 页输 slug(`enroll-landing/internal/tenant/resolver.go` 调 keystone-iam `GetTenantBySlug`)→ per-tenant OP(issuer `https://<label>.<后缀>`)→ id_token 带 tenant claim → device-manager 验签 + 成员资格校验(`internal/register/oidc_user.go`)。
- 结论:两条链路的租户发现均在服务端,客户端配置只需域名。

### 8.2 非目标(显式出局)

1. Sparkle feed URL 覆盖(schema 已预留字段;气隙升级分发独立设计)。
2. Windows/Linux 通道实现(模型可移植:注册表/GPO ↔ 管控偏好,`ProgramData`/`/etc` ↔ `/Library`;随平台 phase)。
3. 中央租户目录(slug→域名)——否决。
4. 每客户二进制 / 定制 pkg——否决。
5. 系统级 OP 拓扑调整——fairyland 独立议题(D12)。
6. 已 enroll 后更换部署域名(管理域迁移)——统一走 §4.5 受控重纳管 + 告警(**非静默照做**),覆盖第 2/3 级 admin 通道推新 D 与第 4 级 BYOD 经 enroll 页 自助换指两条来路;仅当更高优先级来源(第 1/2/3 级)已锁定 D 时,enroll 页对该来源只读拒改。
7. 身份 blob **主动吊销**(区别于过期)——v1 有 `not_after` 过期(§4.1、D15),但无「即时吊销一个未过期 blob」机制;与策略验签链吊销一并登记 §8.4。
8. 部署域名 per-profile 化——域名为浏览器全局;多租户用户在同一部署内开多 profile;跨部署并行可用渠道并存包旁路,不正式支持。
9. gate pref(`kRequireEnrollmentToBrowse`)防篡改加固——enrollment-gate 既有议题。

### 8.4 登记的技术债(评审衍生)

- **TD-DDC-1 策略验签链的版本单调 + 吊销**:当前 per-tenant 验签数据(`policy/onboard.go` 的 `EnsureVerification`)只写 `NewPublicKeyVersion=1`、无 not_before、无吊销;身份 blob 亦无主动吊销。这使「被弃/被攻陷的祝福部署」在 blob `not_after` 窗口内仍可招募外部受害者(§5.2 残余风险①)。彻底止血需:客户端拒绝低于已知 `new_public_key_version` 的密钥 + 支持根签名的吊销声明。**Phase 2 私有化交付前作 go/no-go 复核**。
- **TD-DDC-2 生产根仪式 + 气隙离线租户背书**:见 §7「气隙/release 前置依赖」①②。
- **TD-DDC-3 `/server-identity` 可观测性**:该端点是私有化 BYOD 接入第一跳,应纳入健康检查;舰队域名收敛(MDM 推新域后重启才生效)对支持侧不可见,可扩展 fairyland 现有设备状态上报,携带「生效域名 + 来源级别」。

### 8.3 参考

- `src/common/teleport_enterprise_urls.{h,cc}`、`src/teleport.gni`、`patches/components/policy/core/browser/browser_policy_connector.cc.patch`
- `docs/enterprise-device-enrollment.md`(实现后需更新)
- fairyland:`products/teleport/device-manager/`、`products/teleport/enroll-landing/`、`keystone/sso/gateway/`
