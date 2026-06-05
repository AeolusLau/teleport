# Teleport 企业账号体系设计

- 状态:已评审(设计)
- 日期:2026-06-03
- 范围:跨 `teleport`(客户端 overlay)与 `fairyland`(服务端 monorepo)两仓
- 权威归属:本 spec 为**设计权威**(在 teleport);协议契约权威在 `fairyland/proto/teleport/v1`

> 本文是设计权威。客户端实现 plan 在 teleport `docs/superpowers/plans/`;服务端实现 plan 在 fairyland `docs/superpowers/plans/`;fairyland `docs/superpowers/specs/` 放一页指针回链本文。

## 1. 目标与核心思想

基于 Chromium 源码自研的企业安全浏览器 Teleport,要具备 Chrome 企业版的账号体系能力:登录 UI、账号联邦、设备纳管、账号相关策略控制,以及"基于客户 IdP 登录后搭车进客户自有 Web 应用"。本轮聚焦**账号体系 + 设备纳管的"管道与绑定"**,把具体安全策略目录(DLP、零信任等)留到未来轮。

**核心思想:复用 Chromium 已有的企业身份/策略管道,把端点指向 fairyland,绝不重写 GAIA。** 客户端几乎全是"配置 + 极少 patch",真正的新建工程在服务端的 device-manager。

技术依据(已在 M148 检出与权威文档核实):

- **CBCM / DMServer 策略面**是复用 ROI 最高项:DM 协议是开源 protobuf(`device_management_backend.proto`),服务端 URL 可经 `--device-management-url` 覆盖。
- **GAIA 登录栈虽开源但与 Google 深度耦合**,直接对接我们的 OIDC IdP ≈ 重写,不走。
- **M148 已含"通用 OIDC → 受管 profile enrollment"流程**(Google 为"用 Entra ID 登录 Chrome"所建),且**未被 `is_chrome_branded` 门控**,编进我们非品牌构建、默认开启。可经"1 个 patch + 强开一个 feature + DM url"重指向我们的 Keystone。

> **子设计指针(拆两份,按仓库归属)**:OIDC 受管 profile 纳管的细化设计拆为——**客户端**(本仓)`docs/superpowers/specs/2026-06-04-enterprise-oidc-client-design.md`(Chromium throttle 契约 + 端点/根钥 buildflag);**服务端**(fairyland 仓)`docs/superpowers/specs/2026-06-04-enterprise-oidc-server-design.md`(Keystone IdP:集中认证中心 `accounts.<BASE_DOMAIN>` + per-tenant 域名 OP `<slug>.<BASE_DOMAIN>`、全局手机号认证、多账号会话、slug 租户解析、enroll-landing + HPKE header 注入、device-manager header 路径)。两份互相引用、各自生成 plan。

## 2. 两层身份/SSO 平面(全程不混淆)

### Layer 1 · Teleport 账号(我们建)
两种纳管,经同一 `CloudPolicyClient` / `--device-management-url` 拉签名策略:

- **设备纳管(无用户、登录前)**:`enrollment token → register → 机器 DMToken → 浏览器级策略`。
- **用户登录(登录后)**:`Keystone OIDC 登录 → id_token → register → 用户 DMToken + 受管 profile → 用户级策略`。

### Layer 2 · 搭车进客户 Web 应用(macOS 上基本继承)
macOS OS 层 Apple Platform SSO / Kerberos / Apple Extensible SSO 持客户目录身份,Chrome 透明 SSO 进客户 Entra/Okta/Kerberos Web 应用。我们只:① 经策略面下发 `AuthServerAllowlist` 等;② 验证相关代码路径未被品牌 buildflag 关掉;③ 文档化客户侧 MDM 配置。

技术核实结论(macOS,M148):

- **Kerberos / Negotiate(GSSAPI)**:多年支持、纯上游 `//net`、零代码,只需 `AuthServerAllowlist` 策略 + ccache 里有 TGT(Apple Kerberos SSO 扩展 / Jamf Connect 等)。
- **Apple Extensible SSO(Entra/Okta 重定向型)**:**Chrome 135+ 原生支持**(M148 已含),零代码;客户 MDM 需把**我们的** bundle id(`com.beansec.Teleport*`)加进 IdP 的 SSO 扩展白名单。"Chrome 用自有网络栈所以用不了 Apple SSO 扩展"的旧说法在 135 后已不成立。

## 3. 关键统一点:Keystone 作为浏览器唯一对话的 OIDC OP

浏览器登录只面向 **Keystone 的租户级 OIDC OP**(Keystone 现有 Phase 5 能力:`EnableTenantOP`/`RegisterOauthClient`);Keystone 在背后 fan-out:

- **客户 IdP 联邦租户** → Keystone 走其现有入站 OIDC 联邦到客户 IdP;
- **Keystone 自有账号租户** → Keystone 走密码/MFA。

无论哪种,浏览器拿到的都是 **Keystone 签发的 id_token**,device-manager 只需信任 Keystone 一个 issuer/JWKS。浏览器在 Keystone tenant-OP 里注册为一个 OAuth client。**双模身份("客户 IdP 联邦 / Keystone 自有",按租户配置)对客户端透明,复杂度收在 Keystone 内。**

## 4. 组件全景

| 层 | 组件 | 状态 | 本轮职责 |
|---|---|---|---|
| 客户端 | teleport overlay(`//teleport`) | 已有骨架 | 4 个 patch + `teleport_enterprise_urls` 常量件 + 强开 generic-OIDC feature + 机器 enrollment token 品牌路径 + 经策略面暴露 ride-along 策略 |
| 服务端 | **device-manager(新服务,`fairyland/products/teleport/device-manager`)** | **新建,本轮核心** | 实现 Chromium DM 协议:设备 register(enrollment token)+ 用户 register(OIDC id_token)+ 签名策略下发 + unregister/status |
| 服务端 | Keystone(identity/tenant/sso/tenant-OP) | 已有且完整 | 复用:浏览器登录的 OIDC OP、客户 IdP 联邦、租户/授权 |
| 服务端 | teleport-gateway + 控制台 | 已有骨架 | 本轮最小:生成 per-tenant enrollment token、把浏览器登记为 tenant-OP 的 OAuth client、配置 1~2 样例策略 |
| OS/MDM | 客户侧 MDM | 客户负责 | 下发 enrollment token、Apple SSO 扩展 payload(白名单我们的 bundle id)、Kerberos 配置 |

## 5. 服务端:device-manager 设计

### 5.1 DM 协议端点
线上格式 = vendor Chromium 的 `device_management_backend.proto`。HTTP POST、`request_type` 走 query 参数,`DeviceManagementRequest` 信封包子请求。**Content-Type:请求 = `application/protobuf`(Chrome 的 `kPostContentType`),响应 = `application/x-protobuffer`**(二者不同,服务端两边都要按此处理):

| request_type | 用途 | 入参/鉴权 | 出参 |
|---|---|---|---|
| `register`(浏览器/CBCM) | 设备纳管(无用户) | `DeviceRegisterRequest{type=TYPE_BROWSER}` + `Authorization: GoogleEnrollmentToken token=<per-tenant>` | `DeviceRegisterResponse{device_management_token}`=机器 DMToken |
| `register`(OIDC 变体) | 用户纳管 | `RegisterWithOidcResponse` → 携 Keystone `id_token`(`DMAuth::kOidc`) | 用户 DMToken + `third_party_identity_type` |
| `policy` | 拉策略 | `DevicePolicyRequest{PolicyFetchRequest[policy_type]}` + DMToken | `PolicyFetchResponse{policy_data, policy_data_signature, new_public_key}` |
| `unregister` / `status` | 解绑 / 回执 | DMToken | 最小实现 |

### 5.2 三个服务端关键活儿
1. **OIDC 校验**:用 Keystone issuer/JWKS 验 `id_token`(签名/issuer/aud)→ 经 tenant 服务解析租户+成员+授权(`GetMember`/`ResolveAuthz`,product="teleport")→ 签发用户 DMToken。
2. **enrollment token 校验**:per-tenant token(由 Teleport 控制台/Keystone 生成)→ 解析租户 → 签发机器 DMToken。
3. **策略签名(两层密钥,见 §10.1)**:每租户**独立签名钥**签该租户的 `PolicyData`;**根钥**只在租户 onboarding 时签该租户签名钥的 `new_public_key_verification_data`(带 `domain`,实现 per-tenant 真隔离 + username/域绑定)。**device-manager 运行时只持(解密后的)per-tenant 签名钥,永不持根钥。** 客户端 patch 内置验签根公钥(dev/release 两把,编译期 buildflag 二选一,见 §6.1)。

### 5.3 存储与集成
- Postgres(fairyland pgx 约定):设备/用户注册表、DMToken、租户映射、策略指派。
- 复用 Keystone:租户解析、授权、product 入口校验(`GetTenantProducts` 含 "teleport")、tenant-OP(浏览器注册为其 OAuth client)。
- 端口:沿用 fairyland 端口表为 device-manager 分配 HTTP 端口,接入现有 gateway 体系。

### 5.4 proto 归属(别混)
- **DM 线协议**:vendor Chromium 的 `device_management_backend.proto`(服务端说这套线格式,客户端原生就懂)。
- **`proto/teleport/v1`**:放我们自己的控制面 API(enrollment token 增删查、fleet 列表、策略配置),给控制台/teleport-gateway 用,与 DM 线协议无关。

## 6. 客户端:teleport overlay 设计

延续仓库现有风格——patch 尽量薄,把可变常量收进 `//teleport` 源码,patch 只引用 `teleport::` 常量。

### 6.1 客户端 patch 集(一文件一 patch,镜像 chromium/src 路径;行号基于 M148 检出已核实)

> **关键核实结论**:`--device-management-url` 与 OIDC header 额外 URL 在 STABLE/BETA 渠道被 `IsCommandLineSwitchSupported()` 静默忽略;policy 验签根公钥的 `--policy-verification-key` 覆盖带 `CHECK_IS_TEST()` 仅测试可用。故下列项**一律 patch 内置常量,不靠 switch**,跨渠道稳健。

**阶段一(用户 OIDC 登录 → 受管 profile,走 stub,不依赖 DMServer):**

| patch 目标文件 | 改动 | 为什么 |
|---|---|---|
| `chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc` | 替换常量 `kEnrollmentFallbackUrl`(:41)、`kEnterpriseOidcRegisterUrl`(:53)、`kEntraLoginHost`/`kEntraMcasHost`(:46/:48)为 Keystone 回跳/host | 让 Keystone 回跳触发受管 profile 拦截器(landing URL `IsEnrollmentUrl` 是承重点) |
| `chrome/browser/enterprise/profile_management/profile_management_features.cc` | `kEnableGenericOidcAuthProfileManagement`(:23-24)默认 `FEATURE_ENABLED_BY_DEFAULT` | 跳过 Entra 信任链校验、并启用读 `state` 参数;免每次 `--enable-features` |

stub 通道用运行期 feature params(无需 patch):`--enable-features=OidcAuthProfileManagement:dm_token/<t>/client_id/<id>/user_name/<n>/user_email/<e>/is_dasher_based/false`(全挂在已默认开启的 `kOidcAuthProfileManagement` 上)。

**阶段二(连真 device-manager + 设备纳管 + 签名策略):**

| patch 目标文件 | 改动 | 为什么 |
|---|---|---|
| `components/policy/core/common/cloud/cloud_policy_constants.cc` | 内嵌 **dev + release 两把根公钥 DER + 两个 hash**,`GetPolicyVerificationKey()`/hash 按 `BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` **编译期二选一** | 用户级策略 `new_public_key` 验签必须信我们的根;dev/release 信任锚分离(命令行覆盖仅测试)。**【已实现】** |
| `components/policy/.../BUILD.gn`(编译 cloud_policy_constants.cc 的 target) | 加 dep `//teleport:teleport_policy_buildflags` | 引入上面 buildflag 头;buildflag_header 是叶子目标,**不会经 //content 成依赖环**。**【已实现】** |

> per-channel 根钥说明:canary/beta/stable **共用一把 release 根公钥**(都从 `release.mac.gn` 构建)、dev 用另一把。dev/release 是不同二进制,故**编译期** buildflag 选 key 即可,无需运行时按 channel 选、也无 layering 注入。`//teleport` 出 `buildflag_header("teleport_policy_buildflags")` 由 GN arg `teleport_use_release_endpoints` 驱动(`dev.mac.gn`=false / `release.mac.gn`=true)。**注意:`teleport_use_release_endpoints` 这一个开关同时统管 dev/release 的端点(DM URL + enroll/register-handler URL)与 bake 的验签根钥,不只是策略根钥。** release 私钥在生产 KMS、dev 私钥在 dev root-signer;两把**公钥**入库到 patch。
| `components/policy/core/browser/browser_policy_connector.cc` | `kDefaultDeviceManagementServerUrl`(:37-38)→ fairyland | switch 在 STABLE/BETA 被忽略,必须改默认。**【已实现】** |
| `components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc` | `IsEnabled()`(:98-106)非品牌分支返回 true | 否则非品牌构建机器纳管整段关闭(原 spec "零 patch" 假设有误)。**【未实现 — 机器/CBCM 纳管为后续 phase;设计保留,本分支未落地】** |
| `chrome/browser/policy/browser_dm_token_storage_mac.mm` | `kBundleId`(:62,硬编码 `com.google.Chrome`)→ 读运行时主 bundle id(适配 per-channel `com.beansec.Teleport*`);三处硬编码路径(:46/:50/:56)`/Library/Google/Chrome/…` → 我们的路径 | enrollment token 受管偏好域/缓存路径当前全锁死 Google,必须改。**【未实现 — 机器/CBCM 纳管为后续 phase;设计保留,本分支未落地】** |

> **阶段二落地状态(本分支)**:上表四项中,前两项(`cloud_policy_constants.cc` 验签根钥 + 其 `BUILD.gn` dep)与 DM URL 默认值(`browser_policy_connector.cc` + 其 `BUILD.gn`)**均已实现并构建验证**;后两项(CBCM `IsEnabled` + macOS `browser_dm_token_storage_mac.mm`)属**机器/CBCM 设备纳管**,本分支聚焦用户 OIDC 登录纳管,设备纳管延后到后续 phase——这两个 patch **尚未实现**,仅作设计保留。

### 6.x 已核实可"零 patch"项
- **Apple Extensible SSO**:`kEnableExtensibleEnterpriseSSO` 默认开、`chrome/browser/enterprise/platform_auth/` 在 `if(is_mac)` 下、无任何品牌门控 → 非品牌构建直接可用,仅靠 `ExtensibleEnterpriseSSOBlocklist` 策略 + MDM 控制。
- **policy_type 字符串**:机器级 `"google/chrome/machine-level-user"`;用户级 `"google/chrome/user"`(`GetChromeUserPolicyType()`)。

### 6.2 新增 `//teleport` 源码(走 TDD + gtest)
- `common/teleport_enterprise_urls.{h,cc,_unittest.cc}`:集中暴露 Keystone enrollment/回跳 URL、DM server 默认 URL,供上述 patch 引用,把"可变配置"从 patch 抽出。(验签根公钥**不**放这里——它走 `cloud_policy_constants.cc` patch 内的双数组 + buildflag,见 §6.1。)
- `BUILD.gn` 增 `buildflag_header("teleport_policy_buildflags")`,由 GN arg `teleport_use_release_endpoints` 驱动(供 `components/policy` patch include)。该 GN arg 一处同时选 dev/release 的端点(DM URL + enroll/register-handler URL)与 bake 的验签根钥。

### 6.3 设备纳管(机器级 CBCM)——需 2 个 patch(已核实,非"零 patch")【后续 phase,本分支未实现】
> **落地状态**:本分支聚焦用户 OIDC 登录纳管,机器级 CBCM 设备纳管延后到后续 phase。下述两个 patch **均尚未实现**,本节为后续设计保留。
- 标准 Chrome 走 `ChromeBrowserCloudManagementController` 启动时读 enrollment token 向 device-manager register。但核实发现两处硬编码必须 patch(见 §6.1 阶段二):① `IsEnabled()` 非品牌分支默认返回 false(需 `--enable-chrome-browser-cloud-management` 或 patch 返回 true);② macOS 读取把 bundle id 硬编码 `com.google.Chrome`、文件路径硬编码 `/Library/Google/Chrome/…`。
- 客户侧:经 MDM Configuration Profile 把 per-tenant `CloudManagementEnrollmentToken`(及 `CloudManagementEnrollmentMandatory`)推到我们 patch 后读取的受管偏好域。
- 注:per-channel bundle id(`com.beansec.Teleport` / `.canary` / `.beta`)意味着 `browser_dm_token_storage_mac.mm` 最好 patch 成读“运行时主 bundle id”而非写死单一 id。

### 6.4 搭车 SSO(Layer 2)——客户端侧仅"验证 + 文档"
- `AuthServerAllowlist`/`AuthNegotiateDelegateAllowlist`/`ExtensibleEnterpriseSSOBlocklist` 都是标准 Chrome 策略,由 device-manager 当策略下发,客户端无新代码。
- 验证项:grep 确认 Apple Extensible SSO(`ASAuthorization`/`ExtensibleEnterpriseSSO`)代码路径未被品牌 buildflag 关掉。
- 文档项:客户 MDM 需把我们的 bundle id 加进 Entra/Okta SSO 扩展白名单、部署 Kerberos 扩展。

### 6.5 GN args / 构建
- `release.mac.gn`/`dev.mac.gn` 增:强开 generic-OIDC 所需 flag、确认 CBCM/enterprise 相关 build flag 打开;dev 可指向本地 device-manager。

## 7. 关键数据流

### ① 设备纳管(登录前,无用户)
```
启动 → ChromeBrowserCloudManagementController 读受管偏好(MDM 推的 enrollment token,我们 bundle id 域)
     → register(type=TYPE_BROWSER, Authorization: GoogleEnrollmentToken) → device-manager
     → 校验 token → 解析租户 → 签发机器 DMToken
     → CloudPolicyClient 拉浏览器级签名策略 → 应用(如 AuthServerAllowlist)——此刻尚无用户
```

### ② 用户登录/纳管(双模 fan-out 收在 Keystone 内)
```
触发登录 → 浏览器开 Keystone tenant-OP /authorize(OIDC Code+PKCE,浏览器=注册的 OAuth client)
   Keystone 内部分流:  联邦租户 → 入站 OIDC 到客户 IdP(若 OS Platform SSO 在场则 PRT 静默放行)
                        自有租户 → 密码/MFA
   → Keystone 签发 id_token,回跳我们 patch 过的 register-handler URL
   → OidcAuthResponseCaptureNavigationThrottle 拦截 → OidcAuthenticationSigninInterceptor
   → RegisterWithOidcResponse(id_token, DMAuth::kOidc) → device-manager
   → 用 Keystone JWKS 验 id_token → 解析租户/成员 → 签发用户 DMToken
   → ManagedProfileCreator 建/绑受管 profile → UserPolicyOidcSigninService 拉用户级签名策略
```

### ③ 搭车 SSO(Layer 2,客户端透明)
```
机器策略已下发 AuthServerAllowlist + OS 持客户目录身份(Kerberos/Platform SSO)
   → Chrome 对名单内客户 Web 应用透明 Negotiate / Apple Extensible SSO → 免二次登录
```

## 8. 分阶段计划(映射到两仓 plan)

| 阶段 | 仓库 | 内容 | 可见成果 |
|---|---|---|---|
| **一** | teleport | 2 个 patch(redirect 拦截重指 Keystone + 强开 generic-OIDC)+ `teleport_enterprise_urls`(先放 Keystone URL)+ stub 通道 + Keystone OP 接 OAuth client | 客户 IdP 登录 → 受管 profile 闭环点亮(无需 DMServer) |
| **二** | fairyland + teleport | fairyland:device-manager DM 协议(设备/用户 register + **两层密钥签名**)+ **per-tenant 签名钥(DB 信封加密)+ RootVerificationSigner + dev root-signer 组件 + onboarding 生成&背书** + Keystone 集成 + 1~2 样例策略。teleport:去 stub,补 patch(验签根公钥 **buildflag 双钥** + `components/policy` BUILD.gn 加 buildflag dep + DM url 默认值【以上已实现】;CBCM `IsEnabled` + macOS dm_token 存储【机器/CBCM 纳管,后续 phase,本分支未实现】)、指真服务 | 用户级:登录后用户级策略端到端(per-tenant 隔离)【本分支目标】。机器纳管(登录前下发策略)随 CBCM patch 延后到后续 phase |

接缝:`proto/teleport/v1` 契约先谈定 + vendor DM 线协议,之后两仓可半独立推进。

**阶段一 stub 通道**:`kOidcAuthProfileManagement` 的 feature params `kOidcAuthStubDmToken`/`kOidcAuthStubClientId`/`kOidcAuthStubUserName`/`kOidcAuthStubUserEmail` → 绕过 DMServer,仅凭 Keystone 登录就建受管 profile;阶段二去 stub、指真 device-manager。

## 9. 样例策略(打通"下发"闭环,各取一)
- **`AuthServerAllowlist`(浏览器级,登录前下发)**:直接点亮 Layer 2 搭车,把整条故事串起。
- **`HomepageLocation` 或 `ManagedBookmarks`(用户级,登录后下发)**:肉眼可见,验证用户级通道。

## 10. 安全 / 密钥 / 测试

### 10.1 密钥架构(两层 + 双根)

设计目标:**device-manager 运行时永不持有根钥;per-tenant 真隔离;dev/release 信任锚分离;容器可跑。**

- **根验签钥(2 把,长期):**
  - `release`(canary/beta/stable **共用一把**)+ `dev`(另一把,throwaway)。私钥:release 在**生产 KMS**(如阿里云 KMS),dev 在 **dev root-signer**(compose 组件)。**绝不入库、绝不进 device-manager 运行时。**
  - 仅在**租户 onboarding** 时被调用一次:签该租户签名钥的 `PublicKeyVerificationData{new_public_key, domain=租户域}`。
  - 抽象为 **`RootVerificationSigner` 接口**(我们自己的 Go 接口,**非 KMS 厂商线协议**):prod 实现 = 阿里云 KMS SDK;dev 实现 = compose 里的极简 root-signer 服务(只持根钥、只暴露 `SignVerificationData`)。切换 = 换实现,不换协议。
  - **公钥**入库(安全),编译期 buildflag 二选一 bake 进客户端(见 §6.1)。
- **per-tenant 签名钥(N 把,onboarding 动态生成):**
  - 对标 **Keystone `tenant_op_keys`**:onboarding 时生成 RSA 钥 → 用 **KEK 信封加密**存 device-manager DB(`tenant_signing_keys(tenant_id, public_key, private_key_enc, ...)`)→ 运行时解密到内存本地签 `policy_data`。**不逐租户进 KMS**(成本/延迟)。KEK:prod 用 KMS(一把 master)、dev 用 env(类比 `OP_KEY_ENCRYPTION_KEY`)。
  - 真隔离:每租户独立签名钥 + 根背书到其域 → Chrome 的 `CheckDomainInPublicKeyVerificationData`(domain==username 域)此时才有隔离意义;攻破某租户签名钥仅伤该租户、可轮换。
- **onboarding 两步**(创建租户时,容器内即可):① 生成 per-tenant 签名钥 → KEK 加密入库;② 取其 `verification_data` → 调 `RootVerificationSigner`(KMS/dev root-signer)签 → 连同根签名入库。
- **runtime**:device-manager 按 dm_token→tenant 取 {解密签名钥, verification_data, 根签名},本地签 policy_data;**不调 KMS、不持根钥**。
- 其余机密(延续"私钥绝不入库 + 离线备份"传统):enrollment token 机密;Keystone tenant-OP 的 OAuth client secret;KEK / KMS 凭据按环境管理。

### 10.2 传输 / 令牌 / 测试
- **传输**:浏览器↔device-manager 走 HTTPS;fairyland 服务间沿用现有 mTLS。
- **令牌校验**:id_token 经 Keystone JWKS 验 issuer/签名/aud;enrollment token 服务端校验绑租户。
- **测试**:`//teleport` 新件走 gtest(TDD);fairyland Go 侧走仓库约定的红-绿-重构 + 80% 覆盖;另加 DM 协议一致性测试(对着 vendor proto 验 register/policy 往返与签名)。

## 11. 跨仓库工作流

- **spec(权威)**:teleport `docs/superpowers/specs/2026-06-03-enterprise-account-system-design.md`(本文)。
- **契约(权威)**:fairyland `proto/teleport/v1/`(+ vendor 的 Chromium DM 线协议说明)。
- **客户端 plan**:teleport `docs/superpowers/plans/2026-06-04-enterprise-oidc-client-plan.md`。
- **服务端 plan**:fairyland `docs/superpowers/plans/2026-06-04-enterprise-oidc-server-plan.md`。
- **指针文档**:fairyland `docs/superpowers/specs/` 一页,回链本文路径 + commit。
- **worktree**:各仓库在 `<repo>/.claude/worktrees/` 下开新分支,spec/plan/实现各提交到对应分支。
- **执行**:协议契约先定;之后客户端(阶段一,不依赖服务端)与服务端(阶段二)可半独立推进。

## 12. 明确不在本轮(范围边界)

- Windows / Linux / 国产 OS;GCPW 式 OS 凭据提供器。
- 完整安全策略目录、DLP 事件上报、零信任(留未来轮;本轮只 1~2 样例策略验管道)。
- 富 fleet 控制台 UI(本轮仅最小 API:生成 enrollment token、登记 OAuth client、配样例策略)。
- 不支持现代 SSO 的遗留应用的凭据代填/注入(搭车仅覆盖联邦/Kerberos 应用)。
- 密钥轮换运维自动化(本轮仅协议层支持 `new_public_key`,不做全套运维)。

## 13. 检出核实结论与遗留项

已核实(见 §6.1/§6.x,行号基于当前 M148 检出):
- 验签根公钥 = `cloud_policy_constants.cc` 的 `kPolicyVerificationKey`(:159-184)+ `kPolicyVerificationKeyHash`(:186);命令行覆盖仅 `CHECK_IS_TEST()`。
- CBCM 机器纳管:`ChromeBrowserCloudManagementController::IsEnabled()`(:98-106)非品牌分支默认 false;macOS 读取硬编码 `com.google.Chrome` + `/Library/Google/Chrome/…`(`browser_dm_token_storage_mac.mm`)。**需 patch,但属机器/CBCM 纳管后续 phase,本分支未实现。**
- Apple Extensible SSO:无品牌门控,默认开,**零 patch**。
- policy_type:机器级 `"google/chrome/machine-level-user"`、用户级 `"google/chrome/user"`。
- OIDC register 链路确认:interceptor → `StartRegistrationWithOidcTokens` → `RegisterWithOidcResponse` → `DMAuth::FromOidcResponse`(`DMAuthTokenType::kOidc=5`)。
- 渠道陷阱:`--device-management-url` / OIDC 额外 header URL 在 STABLE/BETA 经 `IsCommandLineSwitchSupported()`(`chrome_browser_policy_connector.cc:241-249`)被忽略 → 全部改走 patch 内置常量。

遗留(plan/实现阶段处理):各样例策略到 `CloudPolicySettings` 的精确 proto 字段编码(从 vendor `cloud_policy.proto` / `dm_protocol.h` 取)。
