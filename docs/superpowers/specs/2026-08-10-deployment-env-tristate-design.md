# 客户端部署环境三态化设计(dev / staging / release,分环境信任锚)

- 日期:2026-08-10
- 状态:**v2**(v1 经四路对抗性评审后重写;评审发现与决策记录见 `2026-08-10-deployment-env-tristate-review-decisions.md`)
- 关联仓库:`teleport`(本仓库,客户端)+ `fairyland`(服务端,分支 `spec/aliyun-first-deploy`)
- 对应服务端轨道:**T6a**(`fairyland/docs/superpowers/specs/2026-07-29-aliyun-first-deploy-master-design.md` §2.5 / §2.6 / T5 / T6a-T6b / §7-F5 / §7-F6)
- 分支对齐:两仓同名分支 `spec/aliyun-first-deploy`、同名 worktree `.worktrees/aliyun-first-deploy`

## 1. 背景与问题

fairyland 服务端将同时存在 **staging** 与 **prod** 两套环境。服务端已裁定(F6,2026-08-06)采用**分环境根**:两者各持独立的 `teleport-root` KMS 密钥,住在各自的 per-env KMS 实例中。安全边界是:staging(故意更弱——ciMock / mock IdP / e2e 持 token)失陷**无法**铸造 prod 客户端信任的策略或 server-identity blob。

客户端当前只有 **dev / release 两态**(GN arg `teleport_use_release_endpoints`,布尔),因此无法产出"指向 staging 且只信 staging 根"的正式形态客户端,服务端 T11 的 Aliyun-staging 全链路验证缺少前置。

**立论的准确边界(v1 在此过度承诺,v2 修正)**:F6 的隔离只覆盖**策略信任链**。客户端还有第二条独立信任链——**Sparkle 升级签名(EdDSA)**,它此前跨渠道共用一把密钥(`2026-05-26-macos-canary-channel-design.md:149`)。若不一并分环境,staging 发布机失陷即可签发 prod 客户端接受的更新,而升级链投递的是任意代码,后果重于策略。故本设计**同时**覆盖两条信任链;§1 的隔离主张仅在两者都分环境后才完整。

## 2. 上游 Chromium 的对照(M151 检出实证)

本节记录调研结论,供将来基线升级时重新核对注入点。

### 2.1 上游只烤一把验签根,不分环境、不分渠道

`components/policy/core/common/cloud/cloud_policy_constants.cc` 中仅有一个 `kPolicyVerificationKey` 与一个 `kPolicyVerificationKeyHash`(上游值 `"1:356l7w"`)。

### 2.2 多密钥并存的复杂度,上游全部压在服务端

`cloud_policy_client.cc:797` 将 `kPolicyVerificationKeyHash` 写入 `PolicyFetchRequest.verification_key_hash`。`device_management_backend.proto:1080-1087` 的注释说明 DMServer 按客户端声明的 hash 精确挑选私钥,找不到即返回错误。设计意图是 key rotation(新旧版本客户端并存),而非环境隔离。

### 2.3 环境切换靠 URL 覆盖,而非换信任锚

`--device-management-url` 经 `BrowserPolicyConnector::GetUrlOverride` 生效,门控在 `ChromeBrowserPolicyConnector::IsCommandLineSwitchSupported()`(`chrome_browser_policy_connector.cc:249`):`channel != STABLE && channel != BETA`。**只换 URL,验签根不变**。

### 2.4 需要按环境分凭据时,上游走构建期烘焙 + 运行时按渠道选

`google_apis/google_api_keys.cc:77-80` 的 `GetAPIKey(version_info::Channel)` 在 STABLE 与 non-stable 两套 key 间二选一;key 由 GN args 构建期注入,环境变量覆盖在 official build 中被禁用。

### 2.5 结论:我们的约束严格强于上游

上游从不用换信任锚区分环境。F6 的"分环境根"是主动选择的更强隔离档位。既然要求"staging 根泄露对 prod 零影响",**只有"release 二进制中根本不含 staging 材料"能兑现那个'零'**——任何运行时选择都只能做到"更难利用"。故环境必须是编译期常量。

这与本 overlay 的既有安全范式一致:level-1 命令行域名覆盖在 release 构建中是**被编译掉**而非被禁用(`src/common/teleport_deployment_config_mac.mm:29-32`)。

**但"零"的范围必须精确**:它指的是**密钥材料**。环境隔离还有非密钥面(共享 MDM 读取域、same-site 域结构),见 §4.7——那些不在"零"的覆盖范围内。

### 2.6 v1 的一处误判(已裁决推翻,保留记录)

v1 §2.6 曾断言"已分发的 canary release 包接受 `--device-management-url`"。**该判断错误**:`patches/chrome/browser/policy/chrome_browser_policy_connector.cc.patch:26-28` 把 `DeviceManagementServiceConfiguration` 的三个 URL 构造参数改成 `std::string()`,而 `patches/chrome/browser/policy/device_management_service_configuration.cc.patch` 让三个 getter 在空值时回落到 `teleport::Deployment*Url()`。因此含 `GetUrlOverride` 的 `BrowserPolicyConnector::GetDeviceManagementUrl()` **在桌面 DM 路径上不再被调用**,该 switch 对端点无效(其余消费者 `GetFileStorageServerUploadUrl` 在 M151 仅 ChromeOS 编译)。

误判成因:只验证门控函数返回 true,未验证门后调用链是否仍连通。**推论**:真正的端点控制面是 deployment domain 的 level 2/3/4,它们在 release 下全部保留且属本设计非目标。§4.4 的编译期消除因此是**防御性冗余**,不是缺陷修复。

## 3. 目标与非目标

**目标**

1. 客户端部署环境三态化(dev / staging / release),环境为编译期常量,每个二进制只含本环境的信任材料。
2. 策略验签信任锚从单把公钥升为每环境的**公钥集合**,承载 release 的"主根 + 休眠恢复根"双根拓扑。
3. **Sparkle EdDSA 升级签名密钥分环境**,补全 §1 立论的第二条信任链。
4. staging 变体走与 release **逐字相同**的 official / PGO / 签名 / 公证 / dmg / Sparkle 流水线,仅数据常量不同。
5. 打包发布链路支持 staging 渠道,产物身份与 release 完全隔离。
6. 实现推进到"**差一把公钥**":各档根值保持占位,由 fail-closed 断言挡住;真实 KMS 公钥到位后只需替换常量。

**非目标**

- 不执行任何密钥仪式(staging / release 的 KMS 根均由 fairyland T5 产出)。
- 不实现 Windows 构建(F5 已裁定 Windows 进首发,属客户端构建专项轨;本设计只在命名与渠道建模上预留位置)。
- 不实现 release 休眠恢复根的**取值**(只实现承载它的集合机制)。
- 不改动 deployment domain 五级解析逻辑本身。
- **不承诺根切换的无缝性**(见 §4.3-D1)。

## 4. 设计

### 4.1 环境轴:编译期三态

`teleport_use_release_endpoints`(bool)替换为 `teleport_deployment_env`(string,枚举校验)。第三态字面值取 **`release`**(而非 `prod`),与既有的 `release.mac.gn`、`out/mac/arm64/release` 及服务端 master design:76 的用词一致。

| | dev | staging | release |
|---|---|---|---|
| 默认域(`kBakedDefaultDomain`) | `fairyland.io` | `staging.douan.cn` | `douan.cn` |
| 策略根来源 | 入库 dev PEM | staging KMS `teleport-root` | release KMS `teleport-root` |
| 策略根数量 | 1 | 1 | **2**(主 + 休眠恢复根) |
| Sparkle EdDSA | 不适用(无 updater) | **独立密钥对** | 独立密钥对 |
| level-1 命令行域覆盖 | 编译进 | 编译进 | 编译掉 |
| official / PGO / Sparkle / 签名 | ✗ | ✓ | ✓ |
| fail-closed 断言 | 无 | `teleport_staging_policy_key_is_real` | `teleport_release_policy_key_is_real` |

**staging 不做双根**:恢复根的价值是"泄露当天服务不中断";staging 直接重发客户端即可。但承载它的集合机制必须存在。

**`teleport_is_release_form` 不引入**。评审证实 official / PGO / Sparkle / 签名全部在 args 模板中独立显式设置(`src/gn/args/release.mac.gn:9,21,25,35`),该派生量既无 C++ 消费者也无 GN 消费者,引入只会让一个无用 flag 挂在 `//components/policy` 依赖的头里、每次翻动触发全 policy 组件重编。v1 称两个派生量"正交"亦属错误——它们都是同一个 env 字符串的函数。

**buildflag 展开为三个布尔**(dev = 两个 env 布尔皆 false):

```
TELEPORT_ENV_IS_RELEASE
TELEPORT_ENV_IS_STAGING
TELEPORT_ALLOWS_DOMAIN_OVERRIDE
```

用布尔而非字符串,原因是 **`#if` 无法对字符串求值**(`buildflag_header` 本身支持字符串值,见 `build/buildflag_header.gni:38`——v1 关于"只支持布尔/整数"的说法有误)。另注:GN 的 `${}` 插值不支持表达式,派生布尔必须先在 `.gni` 中命名为变量。

**墓碑 arg(必备)**:GN 对未声明的 build arg **只告警、退出码 0**(已实测)。直接重命名会让 `docs/chromium-upgrade-runbook.md:303`、`docs/tech-debt.md:270-273`、CI 与肌肉记忆中的 `teleport_use_release_endpoints=<x>` 静默失效并回落 dev 档。故保留旧名的 `declare_args()` 声明,并紧跟:

```gn
assert(!teleport_use_release_endpoints,
       "teleport_use_release_endpoints was renamed to teleport_deployment_env")
```

**args 模板用链式 import**:`staging.mac.gn` 应写作 `import("//teleport/gn/args/release.mac.gn")` 再覆盖 `teleport_deployment_env = "staging"` 与 EdDSA 相关项,而非复制 release 模板的 60 行——否则 §3 目标 4 的"逐字相同"只靠复制粘贴维持,必然漂移。(已实测该形式的覆盖语义正确。)

### 4.2 策略验签:从单 key 到 key 集合

新增 `GetPolicyVerificationKeys()` → `std::vector<std::string>`;`GetPolicyVerificationKey()` 保留返回**主根**(`kPolicyVerificationKeyHash` 由它推导)。两者均需 `POLICY_EXPORT`,且需新增 `cloud_policy_constants.h.patch` 声明。

**必须改造的验签点(v1 只列了 3 个中的 1 个,以下为完整清单)**:

| 位置 | 用途 | 漏改后果 |
|---|---|---|
| `cloud_policy_validator.cc:452-455` `CheckNewPublicKeyVerificationSignature()` | 验首次下发的新公钥 | 恢复根签名被拒 |
| `cloud_policy_validator.cc:631-670` `CheckCachedKey()` | **每次启动**验磁盘缓存的 key(经 `user_cloud_policy_store.cc:326`) | **重启即丢策略**——恰好摧毁双根存在的理由 |
| `user_cloud_policy_store.cc:110`、`machine_level_user_cloud_policy_store.cc:238` | 把根写进磁盘 `PolicySigningKey.verification_key` | 记录与事实不符 |
| `user_cloud_policy_store.cc:262-264` | `verification_key() != GetPolicyVerificationKey()` 触发 key rotation | 升级后全网策略拉取风暴,或缓存密钥永不轮换 |
| `src/browser/teleport_deployment_level4.cc:63-67` | 验 level-4 自认证 server-identity | 恢复根签的 blob 被拒 |
| `src/browser/webui/teleport_enroll_ui.cc:223-226` → `src/common/teleport_enroll_logic.cc:78` | 验 enroll 页拉取的 server-identity | 同上 |

磁盘 `PolicySigningKey.verification_key` 应记录**实际验过的那把**根,而非恒记主根。

**验证库的既有接口不变,但新增一个集合重载**(实现期调整,已落地):`VerifyServerIdentity` / `VerifyServerIdentityDetailed` 继续接受**单把**根密钥;新增 `VerifyAgainstRootSet(..., const std::vector<std::string>& root_keys_der, ...)` 与之并列。

v1 曾写"集合遍历放在调用点、不下沉进库",但该结论的依据是"库不得依赖 `//components/policy`"——而根 DER 作参数注入即可满足,新增纯函数不引入任何依赖。放在调用点反而要把同一段遍历连同 verdict 优先级规则重复两次,两份副本一旦分歧就是静默的诊断退化。故改为下沉,依赖约束不变(Phase 2a 的注入式设计原样保留)。

**verdict 聚合语义(必须定义,否则退化诊断)**:`VerifyServerIdentityDetailed` 返回分档 verdict(`kBadSignature` / `kDomainMismatch` / `kExpired` …),经 `teleport_enroll_logic` 直接喂给 enroll 页的用户可见状态。遍历规则:

1. 任一把根返回 `kValid` → 返回 `kValid`;
2. 否则,若存在**签名通过但字段失败**的 verdict(`kDomainMismatch` / `kExpired` …)→ 返回该 verdict;
3. 全部签名失败 → 返回 `kBadSignature`。

朴素实现("取最后一次 verdict")会把"恢复根签名正确但已过期"误报为签名错误,给出错误排障方向——而验签失败的历史表现正是静默卡死(2026-07-04 "Completing enrollment…" 事故)。

### 4.3 跨仓接口契约(必须与 fairyland 对齐)

**D0 · 签名算法必须是 PKCS#1 v1.5,不得使用 PSS。** 客户端两条验签路径只接受它:`src/common/teleport_server_identity.cc:47`(`RSA_PKCS1_SHA256`,无算法协商)、`cloud_policy_validator.cc:268-280`(`switch` 只有 SHA1_RSA / SHA256_RSA,`default` 直接 `return false`,proto 层无 PSS 表示)。服务端已有正例:`common/signer/vault.go:55` 的 `"signature_algorithm": "pkcs1v15"`,契约写在 `internal/rootsigner/signer.go:17-23`(byte-equivalent to `rsa.SignPKCS1v15`)。**新增的 Aliyun KMS 后端必须沿用**——阿里云对 RSA_2048 同时提供 `RSA_PSS_SHA_256`,选错则验签静默返回 false。

**D1 · 不承诺无缝切换(v1 在此过度承诺,已下调)。**

v1 曾要求服务端"按 hash 定位客户端信任集合、用当前活跃根签名",并据此宣称"存量客户端无感切换"。该契约有两处错误:

- **论证前提错**:存量客户端的信任集合中本就有两把根,服务端直接用活跃根签名即可通过验证,**根本不需要改 hash 语义**。而 v1 的改法反而把 `verification_key_hash`(一个未经认证的客户端输入,`cloud_policy_client.cc:797`)变成**客户端可控的根选择器**——持泄露主根私钥者恒发主根 hash,服务端按该契约继续用主根签,轮换被单方面降级。
- **事实前提错**:服务端 `internal/policy/onboard.go:124-153` 的 `EnsureVerification` 是**幂等缓存**(命中 `tenant_policy_verifications` 即原样返回,仅 `ErrVerificationNotFound` 才重签),而该表(`migrations/002_tenant_signing_keys.up.sql:18-25`)**无根标识列**。改 `ROOT_KEY_ID` 后存量租户永远拿到主根签的旧背书,切换对存量**完全不生效**。

**v2 的契约**:服务端恒用**当前活跃根**签名,`verification_key_hash` 仅作跨环境串线诊断,**不得**用于选择签名密钥;主根一旦标记失陷,必须在 KMS 侧撤销其签名能力,而非依赖客户端发什么 hash。

**根切换是有损操作,写入事故 runbook(§11)**:必须强制重签存量背书(仓库现有手段只有 dev-only 的 `mint-dev-policy-root.sh:37` `DELETE FROM tenant_policy_verifications;`)。其代价是:**把 KMS 从"仅新租户 onboard 时需要"的软依赖,临时变成全租户硬依赖**,持续至重签完成;期间任何 KMS/root-signer 故障将中断全部租户的策略下发。背书是纯派生物,清除不丢租户密钥、不丢策略。

**双根买到的准确边界(必须写进交付文档)**:客户端对集合中两把根**一视同仁**,切换恢复根**不撤销主根**——持泄露主根私钥者能力丝毫未减(配合 level-4 可完整接管 BYOD 客户端,见 §8-R3)。要真正让主根失效,唯一手段是发布移除主根的新客户端。双根买到的是:**泄露当天服务不中断,有从容分批推更新的时间,而非被迫停服**。

**D2 · hash 门为服务端待实现项,不得宣称既成。** device-manager 当前对 `verification_key_hash` **零行读取**,且 `internal/keygen/keygen.go:179-185` 的注释明写该值 "ADVISORY only / NOT load-bearing / Neither side validates"。服务端需新增:①读取该字段;②与本环境信任集合比对,不在集合内 fail-closed 拒绝;③订正该注释。

**D3 · "串环境立刻在握手层报错"不成立(v1 的空头承诺,已删除)。** `internal/httpserver/server_identity_handler.go:5-20` 的 `/server-identity` 是**无参 GET**,不携带 hash;而 hash 仅存在于 policy fetch,时序上排在 server-identity 验签之后。串环境的最先失败点是客户端本地验签,服务端全程无感。诊断收益应改落到客户端:`ServerIdentityVerdict::kBadSignature` 必须 **fail-loud** 呈现到 enroll 页(枚举已存在,只需接线),列入 §7。

> 本节全部条目需在 fairyland 侧 spec 中镜像记录,含枚举字面值 `dev|staging|release`。

### 4.4 后门与编译期消除

- level-1 命令行域名覆盖 gate 由 `!TELEPORT_USE_RELEASE_ENDPOINTS` 改为 `TELEPORT_ALLOWS_DOMAIN_OVERRIDE`(dev + staging 编译进,release 编译掉)。
- **修法改到根因层**:v1 提议在 `GetUrlOverride` 内消除,但该函数是泛型的(`const char* flag`),关不掉单个 switch;且同一个 `IsCommandLineSwitchSupported()` 另有三个消费者(`binary_upload_request.cc:438`、`user_cloud_signin_restriction_policy_fetcher.cc:252`、`chrome_enterprise_url_lookup_service_factory.cc:129`)。改为在**已存在**的 `patches/chrome/browser/policy/chrome_browser_policy_connector.cc.patch` 中让 `IsCommandLineSwitchSupported()` 在 release 档 `return false`——单点、根因、覆盖全部同源开关。
- 性质是**防御性冗余**而非缺陷修复(见 §2.6)。
- 盘点其余策略信任相关 switch:`--policy-verification-key`(`cloud_policy_validator.cc:322-329`,前置 `CHECK_IS_TEST()`,出货二进制中 `g_this_is_a_test` 恒 false ⇒ 传入即 `CHECK` 失败崩溃,是一行命令的本地 DoS)——release 档一并编译掉。

### 4.5 打包与发布接线

- `scripts/_build.py`:新增 `CHANNELS["staging"]`(out `out/mac/arm64/staging`,模板 `staging.mac.gn`,distributable)。
- **`src/common/teleport_channel.cc` 必须同步**:`ChannelFromName` 目前只认 `canary`/`beta`/`stable`,其余落 `version_info::Channel::UNKNOWN`。新增 `"staging"` → **`CANARY`**。不加会产出 `is_official_build=true` + `Channel::UNKNOWN` 这个前所未有的组合,使上游一批 `channel != STABLE` 的门在 staging 下与 release 的任何渠道都不同,且既有 channel-alignment 特性(修升级角标时序)在 staging 上失效——而升级角标正是 staging 要演练的 Sparkle 链路的可见终点。
- **守卫判定轴必须改**:现有 `assert_release_endpoints_consistent`(`scripts/_build.py:116-118`)按文本正则匹配赋值行,而正常 `gn gen` 生成的 args.gn 只有一行 `import(...)` ⇒ `actual is None` 早退、零保护。改为**查询生效值**:`gn args <out> --list=teleport_deployment_env --short`(已实测),与目标 channel 的期望比对;并覆盖 `teleport_*_policy_key_is_real` 与 `teleport_policy_key_placeholder_ack` 这一族覆盖。
- `scripts/_package.py`:`TELEPORT_SIGN_CHANNEL=staging` 驱动 `cn.douan.Teleport.staging` / 显示名 `闪现 Staging` / 数据目录 `Teleport Staging`。评审确认 `chromium_config.py.patch` 的 `fragment = channel.capitalize()`、`stage_channel_icons`、`_find_signed_app`、`dmg_names` 全部泛型派生,**零新机制、无需新图标资产**。
- **tag 命名空间化,staging 照常打 tag**(v1 的"staging 不打 tag"已推翻):`assert_not_published`(`scripts/_publish.py:62-74`)的 docstring 明写前提 "we always tag on publish",不打 tag 会使重复发布护栏归零;而 `fetch_live_appcast`(`:15-20`)对**任何**异常返回 `None`、`assert_publishable`(`_release.py:61-66`)随即 no-op,两道闸可同时失效,叠加 `ossutil cp -f --cache-control immutable`(`:102-112`)将造成不可恢复的覆盖。改为:release 渠道用 `v<四段>`,staging 用 `staging/v<四段>`;`tag_exists` 按渠道命名空间查询。附带修复:`fetch_live_appcast` 必须区分 404(首发)与其它异常,后者硬失败。
- **版本序列共用 `TELEPORT_VERSION`**,可区分性由 Info.plist 烙环境标识解决(`assert_baked_version` 只校验版本串,不校验环境配置)。

  **版本号语义(完整规则;实现散落在 tag 命名空间、每渠道 feed、`assert_not_published` 三处,此处为单一出处)**:版本号标识**源码版本**,不标识产物;产物身份 = **(版本号 × 环境)**。由此三条:
  1. **跨渠道可以同号**,且同号**应当**意味着同一份源码——这正是"staging 上验过的那份源码就是 release 要发的那份"的可追溯性来源。`_publish.tag_name` 的命名空间与每渠道独立 feed 保证两者互不冲突;Sparkle 也不跨 bundle id 升级。
  2. **同一渠道内严格单调**,由 `assert_not_published`(渠道命名空间 tag + 该渠道 feed 的 max version)双查强制。
  3. **同一个版本号必须对应同一份源码** —— 这才是真正的约束,不是"跨渠道不能重复"。若下次发布的源码已不是当初那个 commit,就必须换号,哪怕换到另一个渠道。

  v1 曾把 A4 的理由写成"先在 staging 演练**同一个包**、再原样发 release"——**措辞错误**:staging 与 release 是两个不同的二进制(不同 env、不同根、不同域),永远不可能是同一个包。准确说法是**同一份源码的两个变体**。

  **演练会真实消耗版本号**(§6-c 实测:`0.2.0.1` 已绑定 commit `2505419`,并在 Apple 留下公证记录)。这是刻意的:`--rehearse` 跳过的是 **tag**(声明"这是正式发布"),不是"假装什么都没发生"。若演练能把版本号退回去,它就在版本管理这一环走了捷径——而"不走捷径"正是演练存在的意义。
- `scripts/package.py`:`assert_on_main`(`:184`)与 `tag_and_push`(`:229`)在此文件而非 `_publish.py`。staging 放宽 `assert_on_main`,但 **`assert_clean_tree` 必须保留**,并把 `git rev-parse HEAD` 写进 Info.plist 或 `_package_state` 台账——否则从特性分支发出的 staging 包零 provenance。
- **渠道配置自洽校验(新增)**:`_config.py:29-33` 的 `merged = {**shared, **channels[channel]}` 允许把 `feed_url` 写在顶层套到所有渠道;而 `_publish.py:85-87` 会先清空 updates_dir 再 `cp -f`,一个漏改的 `oss_upload_target` 就能把 staging 的 appcast 覆盖到 release 前缀。`load_channel_config` 后须断言:`feed_url` / `download_base_url` / `oss_upload_target` 均含渠道名、前缀彼此一致、且**不得出现在 shared 区**。
- `scripts/_config.py` / `release_config.local.toml.example`:新增 `[channel.staging]` 段,含独立 EdDSA(§4.6)。
- **`package.py --rehearse`(演练模式)**:对渠道配置的**真实端点**跑完整发布链(构建→签名→公证→dmg→appcast→上传),只省略 **tag** 一步。**所有守卫保持发布级强度**(含传给 `assert_release_endpoints_consistent` 的 `distributing=True`)——放松任何一条,演练验证的就是一条发布不会走的路径,而那正是它必须避免的。与 `--distribute` 互斥。

  做成一个**模式**而非手工跑同样的命令序列:手工版会与真实路径静默漂移,而漂移恰恰是演练要发现的东西。同理,`--dry-run` 的计划文本必须描述**本次调用**的真实行为——它曾在演练下仍打印 `git tag`、且把 tag 名写死为 `v<ver>` 而非渠道命名空间;一个会误导人的 dry-run 比没有更糟。
- `scripts/_publish.py` 的 `upload_to_oss`:**凭据、endpoint、region 全部显式传给 ossutil**,不留给它自行推断。两条实测得来的约束:
  1. **ossutil 的 `~/.ossutilconfig` 优先于环境变量**。在任何发布过其它渠道的机器上,`export ALIBABA_CLOUD_ACCESS_KEY_*` 会被**静默忽略**,请求以错误的 RAM 用户发出。其表现是针对目标桶的 `AccessDenied … the bucket you access does not belong to you`——**读起来完全像是对方的授权配错了**。本项目已因此误报过一次跨仓 BLOCKER 并撤回。故凭据缺失时必须**硬失败**,而不是回落到用户级配置。
  2. **ossutil 2.x 用 SigV4 签名**,只给 `-e` 会让签名 region 仍取自配置文件,请求被拒为 `Invalid signing region in Authorization header`。两个分发桶已跨 region(canary 在 beijing、staging 演练桶在 hangzhou),故 `oss_endpoint` / `oss_region` 均为**每渠道必需键**,不可有默认值。

**分发面**:staging 的 dmg 与 appcast 走 **OSS 独立前缀**,不经 staging 集群,`teleport.staging.douan.cn/download` 不作分发入口。注:v1 称此点"经 fairyland 侧确认"有误——服务端仓库对访问模型与 IP 白名单**零书面依据、零 IaC**,staging 的 OSS 分发桶亦不存在(`modules/oss/main.tf:3-5` 只有 app/backup/geoip)。已降级为 §9 的待办。

**建模取舍(硬性前置,非可登记取舍)**:staging 在打包层被建模为 channel 名、在编译层是 env 值,成立前提是"staging 只需一个渠道"。**将来 staging 需要多渠道时,必须先拆开这两个轴**,否则与 `CLAUDE.md`「channel 名是 bundle id 后缀与 `TeleportChannel` 键的单一事实源」冲突。

### 4.6 密钥治理

**策略根**
- `keys/staging-policy-root.pub.pem`、`keys/release-policy-root.pub.pem`、`keys/release-policy-recovery-root.pub.pem`(本轮均为占位);私钥在各自 KMS 内,永不入库。
- `scripts/gen_policy_verification_key.py` 由单 key 参数化为多 key(`--env dev|staging|release`)。两处必须重做:①`patch_dev_key():66` 的 hash 定位靠"key 块之后第一个 hash"的**位置启发式**,release 变成两把 key + 一个 hash 后必然错位 → 改为显式 key↔符号映射表;②`run_check()` 只做三方一致性比对,**对占位值同样返回绿色** → 新增占位根 SHA-256 指纹清单 + `--require-real <env>`,命中即硬失败,并接进 `package.py --distribute` 前置(而非只接在 `apply_patches.py`)。

**Sparkle EdDSA(新增,A2 决策)**
staging 必须持**独立**的 EdDSA 密钥对。当前 `_publish.py:88-93` 的 `generate_appcast` 不传 `--account` / `--ed-key-file`,恒用 keychain 中唯一一把;`_config.py:16` 的 `SPARKLE_KEYS` 只有公钥、无私钥选择位。改动:`SPARKLE_KEYS` 增私钥选择键、`generate_appcast` 传参、`_config` 断言各渠道 `public_ed_key` 互不重复(fail-closed)。Developer ID 仍共用并登记为残余风险。CLAUDE.md「绝不同时换 Developer ID 和 EdDSA」的轮换纪律需按两把密钥重新表述。

### 4.7 环境隔离的非密钥面(新增)

§2.5 的"零"只覆盖密钥材料。以下两条不在其覆盖内,登记为已知风险:

- **MDM 平台策略读取域跨环境共用**:`chrome_browser_policy_connector.cc.patch` 把读取域钉死为 `cn.douan.Teleport`(`teleport_deployment_config_mac.mm:25`),服务端 master design 将此写为特性(一份 payload 配全变体)。后果:QA 机并排安装 release + staging 时,一条 forced `DeploymentDomain=staging.douan.cn` 会**同时命中 release 客户端**(level 2 优先于 level 4/5),且 `CloudManagementEnrollmentToken` 只有一个槽位,两环境纳管 token 无法共存。**裁定:保持共用,明令禁止并排安装**,写进 §11 与 QA 手册。
- **`staging.douan.cn` 与 `douan.cn` same-site**:`cn` 是 TLD、`douan.cn` 可注册 ⇒ 失陷的 staging 可设 `Domain=.douan.cn` cookie、可作 SameSite=Lax/None 同站来源、可命中 `*.douan.cn` 形式的 CORS/重定向白名单。**裁定:保持域结构(服务端已部署、T4 证书已签),登记残余风险,并请服务端在 cookie/CORS 层加硬隔离。**

## 5. 改动清单

**GN**
`src/teleport.gni`(三态 arg + 墓碑 arg + 枚举断言 + 两条 fail-closed 断言 + `teleport_policy_key_placeholder_ack`)、`src/BUILD.gn`(buildflag 展开为 3 个)、`src/gn/args/staging.mac.gn`(新增,链式 import)、`src/gn/args/{dev,release}.mac.gn`

**C++ / patch**
- 扩档:`patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch`
- **新增 patch**:`cloud_policy_constants.h.patch`(声明 `GetPolicyVerificationKeys()`)、`cloud_policy_validator.cc.patch`(两处集合验签)、`user_cloud_policy_store.cc.patch`、`machine_level_user_cloud_policy_store.cc.patch`;若集合下沉为 validator 成员还需 `cloud_policy_validator.h.patch`
- 扩档:`patches/chrome/browser/policy/chrome_browser_policy_connector.cc.patch`(`IsCommandLineSwitchSupported()` release 档 `return false`)
- overlay:`src/common/teleport_deployment_config.cc`、`src/common/teleport_deployment_config_mac.mm`、`src/common/teleport_channel.cc`、`src/browser/teleport_deployment_level4.cc`、`src/browser/webui/teleport_enroll_ui.cc`、`src/common/teleport_enroll_logic.{h,cc}`
- `src/common/teleport_server_identity.{h,cc}`:**既有接口不动**,仅新增 `VerifyAgainstRootSet` 集合重载(理由见 §4.2)

v1 "无新注入点,全部是既有 patch 扩档"这句自我保证**已删除**——不成立。

**gn check 风险**:`browser_policy_connector.cc` 若要用 buildflag,需注意 `patches/components/policy/core/browser/BUILD.gn.patch` 目前只加了 `teleport_deployment_config` dep,而后者不 include buildflag 头;chromium `.gn:84-92` 未设 `check_targets` ⇒ 全量 header check 生效,会报 "Include not allowed"。§4.4 改到 `chrome/browser/policy` 层后该风险消失,但实现时须复核。

**脚本**
`scripts/_build.py`(渠道注册表 + 守卫判定轴重写)、`_package.py`、`_publish.py`、`package.py`、`_config.py`、`_release.py`、`gen_policy_verification_key.py`、`release_config.local.toml.example`

**测试**
`scripts/tests/test_build.py`、`scripts/tests/test_package_cli.py`、`src/common/teleport_channel_unittest.cc`、`src/common/teleport_deployment_config_unittest.cc`、新增档位纯函数 seam 的单测

**文档**
`CLAUDE.md`、`docs/tech-debt.md`、`docs/chromium-upgrade-runbook.md`(后两者含将失效的 TD-026 命令)

**密钥**
`keys/staging-policy-root.pub.pem`、`keys/release-policy-root.pub.pem`、`keys/release-policy-recovery-root.pub.pem`

## 6. 交付边界

本轮实现到"**差一把公钥**":各档根值为占位,由 fail-closed 断言挡住;dev 档与现状等价。

**占位期的三条合法通道(A6 决策,全取)**

- **a · 具名"可构建不可发布"通道**:新增 `teleport_policy_key_placeholder_ack`(默认 false)。置 true 时断言放行、产物 Info.plist 烙 `TeleportUnpublishable=YES`、`package.py --distribute` 前置**硬拒**。目的是让"我知道这是占位、只想验证构建机制"成为**具名合法动作**,而不是每个人临时发明 `gn gen` 覆盖并遗留在 args.gn 里——TD-026 已演示过后果(`docs/tech-debt.md:271`;实测 `out/mac/arm64/release/args.gn` 此刻仍含当年的 `teleport_use_release_endpoints = false`)。
- **b · §10 的可验证性**:凡需要 staging/release 二进制才能验证的条目,降级到 buildflag 展开 + 单测层;交叉否定 e2e 明确标注"阻塞于 T5,不属本轮完成定义"。
- **c · 提前跑通一次 staging 全发布路径**:用 a 的通道构建 staging 档占位包,走完整签名 → 公证 → dmg → appcast → OSS → Sparkle 升级验证。否则 `[channel.staging]` / `staging.mac.gn` / staging 全发布链在本轮合入后**从未被真实执行过一次**,数月后 T5 落地时第一次真跑就是"首次执行 + 要出真包"。

  **演练不依赖服务端**:上传目标为**现有 OSS 桶下的一个演练专用前缀**(与 canary 同桶、不同前缀),不需要 §9 中那个尚不存在的 staging 正式分发桶,也不需要 staging 集群可达——演练验证的是打包/签名/公证/分发/升级链路,不是策略链路。

公钥到位后的交付动作:替换 `keys/*.pub.pem` → 重跑生成 → `--check --require-real` 通过 → 翻断言 → 构建。

## 7. 测试策略

- **档位判定下沉为纯函数 seam**:现有 `teleport_deployment_config_unittest.cc:39-43` 是 `#if`/`#else`,一个二进制只编译一档,而 `teleport_unittests` 只在 dev out 构建 ⇒ 三档预期最多验证 1/3,`TELEPORT_ALLOWS_DOMAIN_OVERRIDE=false` 档更是**永远编不出来**。照既有 `teleport_enrollment_gate_logic` / `teleport_enroll_logic` 模式,让 `ReadCommandLineDomain()` 的策略部分接受 `bool allows_override` 参数,三态在同一 dev 二进制内全部可测;buildflag 只出现在唯一调用点。
- `gen_policy_verification_key.py`:四把公钥 ↔ patch 烘焙值 ↔ hash 三方一致性 + 占位指纹检测(pytest)。
- 集合验签单测:主根通过、恢复根通过、集合外拒绝、空集合拒绝;**verdict 聚合**用例(恢复根签名 + 已过期 ⇒ 必须报过期而非签名错)。
- `CheckCachedKey()` 路径单测:恢复根签的缓存 key 在重启后仍被接受。
- `teleport_channel_unittest.cc`:`"staging"` → `CANARY`。
- `scripts/tests/test_build.py`:守卫的 env×channel 正反用例,**必须包含"args.gn 只有一行别的 env 的 import"**这一例(现有文本正则方案在此失效)。
- enroll 页 fail-loud:`kBadSignature` 必须可见呈现(§4.3-D3)。
- **交叉否定 e2e(阻塞于 T5,不属本轮 DoD)**:staging 变体指向 release 域时验签必须失败,反之亦然。正向通过只证明配对正确,反向失败才证明隔离真实存在。

## 8. 已知取舍与风险

- **R1 · staging 保留 level-1 后门**(已决策):staging 与 release 因此不严格同构,`ReadCommandLineDomain()` 在 release 下的 `nullopt` 分支不被 staging 覆盖。缓解:§7 的纯函数 seam 单测。残余风险低——staging 包外流后攻击者仍需 staging 私钥才能签出可信策略。
- **R2 · env 冒充 channel**:见 §4.5,已升级为硬性前置条件。
- **R3 · 主根泄露窗口内 level-4 是完整接管路径**:`teleport_deployment_level4.cc:56-69` 中,blob 只要被集合任一根验过,`data.domain()` 即成为 `DeploymentDomain()`,进而驱动 DM / reporting / enroll / OIDC 可信重定向宿主 / 隧道 edge + cnf bearer token;而 BYOD 默认态下 enroll 页未锁,用户可输入任意域。⇒ 主根泄露后,攻击者签一个 `ServerIdentityData{domain=evil}` 并社工诱导 BYOD 用户 enroll,即可接管该客户端全部端点,**无需网络位置、无需 MDM 权限、无需 root**。受管设备因 level 2/3 优先 + `IsDomainChangeLocked` 免疫。**裁定:登记为已知风险**(收紧 level-4 的可接受域会与私有化客户使用自有域名直接冲突);交付文档须量化 Sparkle 收敛时间。
- **R4 · 恢复根:取值与宿主已定(2026-08-10),切换机制仍未定**。离线仪式已产出真实恢复根,公钥指纹 `a45361da7f060b221458350e564d3bdc40683ae0256620e864e4326ef23a56a0`,已 vendored 至 `keys/release-policy-recovery-root.pub.pem` 并烤进 patch;私钥离线冷存,从不触网(与 `2026-07-04` spec:63 一致,推翻 v1 误写的"prod KMS")。**这不解除任何闸门**:release 档仍因**主根**是占位而被 fail-closed 挡住(`--require-real --env release` 的失败原因现已收敛为一条)。
  **仍未定的是切换机制**:root-signer 的 `ROOT_KEY_ID`(`cmd/root-signer/main.go:164-167`)只能指向 KMS key id,而恢复根不在 KMS 中——服务端如何用一把离线密钥重签存量背书,尚无设计。在此之前,恢复根提供的是"事故当天不必停服"的余地,而不是可执行的轮换流程。
- **R5 · Developer ID 跨环境共用**:EdDSA 已分环境(§4.6),但 Developer ID 证书仍共用。登记。
- **R6 · 构建成本(A5 知情决策)**:staging 开 PGO 以保"逐字相同"。实测 `release` = **118 GB**、`staging` = 67 GB、`dev` = 17 GB;两个 official out 目录**零对象复用**,staging 首次全量编译 57511 步、`cached` 命中 **0**。故每次发版 = 两次全量 official+PGO 构建。此为保真度优先的知情选择。

  **零复用的确切原因(2026-08-14 查清,勿再重复排查)**:不是"没配编译缓存",而是 **siso 的缓存与 RBE 绑定,而我们没有 RBE**。siso 自带 `-local_cache_enable` 与 `-cache_dir`(默认 `~/Library/Caches/siso`),`autoninja` 也会把这些 flag 原样透传(`autoninja.py:549-550` 直接拼 `input_args[1:]`),但:
  - 直接 `siso ninja -local_cache_enable` → `failed to initialize credentials: need to run siso login`,说明缓存后端就是 RBE 的 CAS;
  - 而 `use_remoteexec=false` 时 autoninja 自动追加 `--offline`(`autoninja.py:550`),offline 下缓存读写整条路径被跳过 —— 实测 `--offline -local_cache_enable -cache_dir <新路径>` 构建成功但**缓存目录零文件**。

  即 `use_remoteexec = false` 一个选择同时关掉了远程执行**和**缓存,二者在 siso 里不是两件事。若要拿回跨目录复用,只有两条路:①接入 RBE(需要 Google RBE 项目授权);②装 ccache 走 `cc_wrapper`(不依赖后端,但须先验证它把 PGO 的 `-fprofile-instr-use` profile 正确纳入 hash)。**在此之前,R6 的成本是结构性的,不是配置疏漏。**

  **两种"慢"要分开看(2026-08-14 实测)**:
  - **新建 out 目录** = 真·全量编译(staging 首次 57511 步、`cached` 0)。这是缓存能救的场景。
  - **VERSION bump** ≠ 全量重编。实测 bump `0.2.0.0 → 0.2.0.1` 后,47198 个 `.o` 中仅约 **1748 个(3.7%)** 重编,96.3% 原样复用——ninja 增量工作正常。慢的是**链接**:那些 `.o` 散布在多个大 target 中,而 official+PGO 下 `Teleport Framework` 的链接(340M,LTO/PGO 在链接期做)加上 `chrome/installer/mac` 的 bundle 重组,是整条流水线最重的单步,且**无法被编译缓存消除**。

  推论:CLAUDE.md 那句"VERSION 变更触发大范围重编,发版构建本为全量"体感正确但归因不准——代价在链接不在编译。这直接影响"要不要投入 RBE/ccache"的判断:**缓存能显著加速新建 out 目录,但几乎救不了发版 bump**。
- **R7 · 半成品长期滞留 —— 对 staging 已关闭(2026-08-14)**。原风险:staging 全发布路径在合入后从未被真实执行过,数月后第一次真跑就是"首次执行 + 要出真包"(TD-026 正是这个模式:"只是因为期间没有发过版,所以没人注意到这个阻断")。**§6-c 演练已完成**——整条链路用真根、真 Developer ID 签名、真 Apple 公证、真 OSS、真自动升级跑通两轮(`0.2.0.0 → 0.2.0.1`),故对 staging 不再成立。
  **对 release 仍然成立**:release 档因主根仍是占位而被 fail-closed 挡住,其发布路径依旧从未执行过。但差异是实质的——staging 已证明这套机器能工作,release 首发时的未知量只剩"换一把公钥"。
- **R8 · §4.7 的两条非密钥面风险**(共享 MDM 域、same-site)。

## 9. 依赖与阻塞

状态经 fairyland 侧实测确认(2026-08-10)。

| 依赖 | 状态 | 影响 |
|---|---|---|
| staging KMS `teleport-root` | ✅ 就绪且规格正确——`DescribeKey` 实测 RSA_2048 / SIGN/VERIFY,`KeyVersionId = key-hzz6a7870093hviipht64-cdfb5kjmws` | 无 |
| staging 根公钥**导出** | ❌ regional `GetPublicKey` 返回 `UnsupportedOperation`(密钥住专属实例 DKMS `kst-hzz6a786ecfeepjmmg5rc`),须走 `{instance}.cryptoservice.kms.aliyuncs.com` + AAP 鉴权;工具需新写 | 阻塞"填入真实公钥",不阻塞本轮实现 |
| root-signer 的 Aliyun KMS 后端 | ❌ 未实现(`cmd/root-signer` 仅 OpenBao Transit);**与上一行同一条 DKMS 接入**,建议合并。注:`internal/rootsigner/kms.go:17-35` 的 TODO 给的是 **regional** SDK 配方,对本密钥不适用 | 阻塞闭环验证 |
| T5 轨道 | 🟡 部分——secret-manager / RRSA 半边已 staging 实测通过(`a4dbce8`);**未开工的是 KMS 签名后端 + 密钥仪式 + 公钥导出** | 见上两行 |
| release KMS 主根仪式 | ❌ 未执行(TD-026) | 阻塞 T6b;现为 release 档唯一的占位阻塞点 |
| release 恢复根 | ✅ **已就位**(2026-08-10 离线仪式,`a45361da…`,私钥冷存) | 不再阻塞;**但切换机制仍未定**,见 R4 |
| 恢复根的切换路径 | ❌ 未设计——root-signer 只能指向 KMS key id,恢复根不在 KMS | 阻塞"可执行的轮换流程",不阻塞发版 |
| 存量租户背书重签机制 | ❌ 两侧此前均未提及(§4.3-D1) | 阻塞根切换的可执行性 |
| staging 分发面 | ✅ **已就位**(2026-08-13,fairyland `894c027`):tools 层持久桶 `douan-fl-distribution`,private,匿名读**仅**对 `teleport/*` 与 `teleport-rehearsal/*` 两个前缀开放,已开 versioning(noncurrent 90 天) | 解除 |
| staging 访问白名单 | ❓ 服务端 IaC 中仍无 acl / source_cidr_ip | 不阻塞:分发走 OSS,与集群解耦 |

**对 §6 的排期含义**:那把公钥并非随手可取,需 T5 先建立专属 KMS 实例的网关接入。不应按"几天内拿到"排期。

## 10. 完成定义

1. `teleport_deployment_env` 三态生效;墓碑 arg 使旧名覆盖**硬失败**;三份 args 模板齐备且 staging 用链式 import。
2. dev 档构建与运行与现状完全等价(无回归)。
3. §4.2 表中**全部六个**验签点改造完毕;verdict 聚合语义按 §4.2 实现;单测覆盖 §7 全部用例。
4. `uv run pytest` 全绿;`teleport_unittests` 全绿;`apply_patches.py` 幂等。
5. staging 独立 EdDSA 落地,`_config` 的跨渠道公钥去重断言生效。
6. 发布守卫按**生效值**判定,`test_build.py` 覆盖"args.gn 只有一行别的 env 的 import"用例。
7. §6-c 的 staging 全发布路径演练**已真实执行过一次**,含 Sparkle 升级验证。
8. §4.3 全部条目已在 fairyland 侧 spec 中**镜像记录并提交**(附 commit 号);D 组跨仓待办已提交对方轨道。
9. `CLAUDE.md`、`docs/tech-debt.md`、`docs/chromium-upgrade-runbook.md` 同步更新。

**曾降级、现已达成(2026-08-14)**:
- **staging 真实纳管闭环 ✅** —— fairyland 侧真机验证:staging 档客户端纳管成功、设备证书签发、策略下发。这一次握手同时闭合了三方此前只是各自核对纸面值的关系:客户端烤入的 `8b06e78b…` 字节、服务端 Transit 里 BYOK 的私钥、device-manager trust set 里的那条 hash。**§4.3 的跨仓契约至此有了运行时证据**,不再只是双方对表。
- **T11 隧道 e2e ✅** —— browser → edge(设备证书 mTLS,gate 1-4)→ 后端,真机取到响应;gate-4 撤销负向测试亦 GREEN。

**仍未达成**:
- **交叉否定 e2e**(staging 变体指向 release 域须验签失败,反之亦然)—— 需要两个真实环境,而 release 环境尚不存在(prod cloud 从未 apply)。**注意**:正向已证不能替代它——正向通过只说明配对正确,反向失败才证明隔离真实存在。这条应在 prod 环境建立时补做。

## 11. 事故处置(新增)

现有流水线**机制上不支持回滚**:重发 N-1 被 `assert_publishable` 拒、重发 N 被 `tag_exists` 拒、appcast 只列最新版且 Sparkle 的 `--versions`(插入比 feed 最新版更旧的更新)未使用。

**一处已改善(2026-08-13)**:分发桶 `douan-fl-distribution` 已开 versioning(noncurrent 90 天),所以"`ossutil cp -f` 覆盖不可恢复"这一条不再成立——被覆盖的对象 90 天内可取回。这把误发的**代价**从不可逆降为可恢复,但**发现手段**仍然缺失:没有人会去查一个没人知道发生了的覆盖。下面第二项因此仍然必要。

以下三项须在实现期一并建立:

- **根泄露处置**:①切换活跃根 ≠ 撤销泄露根(§4.3),必须同时启动客户端更新推送;②切换需强制重签存量背书,期间 KMS 成为全租户硬依赖;③**staging 为单根**,其根泄露的处置只能是全量重发 staging 客户端——须核对 QA 机规模并写入清单。
- **误发处置**:发布后回读 appcast,校验 URL / 签名 / bundle id 与预期渠道一致(自动化);撤回手段需 OSS bucket versioning + `generate_appcast --versions` 回插能力。
- **并排安装禁令**:§4.7 的共享 MDM 域使 release + staging 不可并排安装;QA 手册须明令,并说明切换环境的正确做法是卸载后重装。
