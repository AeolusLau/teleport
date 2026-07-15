# Chrome 企业版多租户纳管与策略下发机制调研

> 调研日期:2026-07-14
> 上游基线:**M148.0.7778.180**(`CHROMIUM_VERSION`),本地检出 `<repo>/chromium/src`
> 方法:deep-research 多路检索(20 个来源、98 条 claim 提取、25 条经三票对抗验证、24 条确认、1 条否决)+ 本地 M148 源码逐条核实(file:line 均实地核对)+ Microsoft Edge 官方文档补充对照。
> 目的:回答「同一用户服务多个租户」场景下,机器级纳管是否应租户无关、多租户如何隔离、SaaS / 私有化 / 气隙三种部署形态如何兼容;为 teleport(闪现)自研策略下发后端的架构决策提供依据。

## 0. 核心结论速查

| 问题 | 结论 |
| --- | --- |
| 一台设备可否被多个租户做机器级纳管 | **不可**。单 DM token、注册互斥;仲裁机制是「谁先注册谁是唯一主人」,不是策略优先级 |
| 一个用户可否服务多个租户 | **可**,完全下沉到 profile 层:一租户账号一 managed profile,策略 per-profile 隔离 |
| 机器级策略是否租户无关 | **否**。Chrome 的选择是「租户相关 + 单一写入者」;「租户无关的机器级策略」在 Chrome/Edge 中都不存在 |
| CBCM 是否有私有化/气隙形态 | **无**,仅 SaaS(admin.google.com);官方 on-prem 路径 = 平台策略通道(GPO/plist/JSON),本地读取零云依赖,天然兼容气隙 |
| 默认策略优先级(桌面,低→高) | cloud user < platform user < cloud machine < **platform machine(默认最高)**;metapolicy 可条件抬升出 `kCloudUserRaised`/`kCloudMachineRaised`/`kCloudUserDoubleRaised` 三个提权档(完整阶梯见 §3.1) |
| 跨租户防线 | affiliation 交集门控:用户租户 ≠ 机器租户时,用户策略永远最低优先级、绝不与机器策略合并 |
| 租户归属交互 | 先登录、后按账号所属组织自动归属;无「先选租户」步骤 |

## 1. 机器级纳管:租户相关、单一写入者、注册互斥

### 1.1 单 DM token,无多租户容器

- `BrowserDMTokenStorage` 为全局单例(`components/enterprise/browser/controller/browser_dm_token_storage.h:69`,`static BrowserDMTokenStorage* Get()`),私有成员只有单个 `std::string client_id_; std::string enrollment_token_; DMToken dm_token_;`(同文件 `:142-144`),不存在任何多 token 集合。
- `MachineLevelUserCloudPolicyManager` 亦为单实例:`chrome/browser/policy/chrome_browser_policy_connector.h:178` 只有一个 `machine_level_user_cloud_policy_manager_` 指针,经单个 `proxy_policy_provider_` 下发到所有 profile。

### 1.2 注册互斥:已有主人时,新 enrollment token 是 no-op

`components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc:250-274` 的三态逻辑(注释原文即如此陈述):

1. **存在 valid DM token** → 直接拉策略,**enrollment token 被完全忽略**。机器已归租户 A 时,下发租户 B 的 enrollment token 无任何效果。
2. **DM token 为空** → 才用 enrollment token 发起注册(`register_browser`)。
3. **DM token 被标记 invalid** → fail-closed:既不拉策略也不重注册,直到人工清除 token 存储。

**推论**:跨租户「换绑」的唯一路径是显式解除纳管(清除 DM token)后重新注册;不存在并存,也不存在覆盖。

### 1.3 enrollment token / DM token 的分发与存储位置

| 平台 | enrollment token 读取来源 | DM token 存储 |
| --- | --- | --- |
| Windows | `HKLM\SOFTWARE\Policies\<Company>\CloudManagement\EnrollmentToken`,回退 `HKLM\SOFTWARE\Policies\<Company>\<Product>\CloudManagementEnrollmentToken`(`chrome/installer/util/install_util.cc:448-458`) | `HKLM\SOFTWARE\<Company>\Enrollment\dmtoken`(`install_util.cc:461-474`) |
| macOS | managed plist 键 `CloudManagementEnrollmentToken`,回退 `/Library/<Product>/CloudManagementEnrollmentToken` 文件(`chrome/browser/policy/browser_dm_token_storage_mac.mm:127-159`) | `DIR_APP_DATA/<Product>/Cloud Enrollment/<base64url(sha1(client_id))>`(同文件 `:80-101`) |
| Linux | `DIR_POLICY_FILES/enrollment/CloudManagementEnrollmentToken`(`browser_dm_token_storage_linux.cc:133-155`) | `DIR_USER_DATA/Policy/Enrollment/<client_id>`;client_id 取自 `/etc/machine-id`(同文件 `:41-72,:102-120`) |

分发即「平台策略通道运输 token」:GPO/MDM/镜像预置皆可,安装包本身通用、不含租户身份。

### 1.4 enrollment token 的生成与生命周期(Google 官方流程)

来源:CBCM 注册帮助页 9301891(2026-07 在线核对)。

- **生成**:管理员(需 Mobile Device Management 管理权限)在 Admin console → Devices > Chrome > Managed browsers,选择顶层组织或某个 **OU** 生成;**token 与 OU 绑定**,用它注册的浏览器落进该 OU、接收该 OU 的机器级策略。
- **共享复用,非一机一 token**:同一 token 部署到任意多台机器("enrollment tokens are only used during enrollment"),各机器注册后获得各自唯一的 DM token。
- **每 OU 同一时刻仅一个活跃 token**("For each organizational unit, there can only be one active enrollment token");换 token 须先吊销再生成。
- **无自动过期**,长期有效直到显式吊销;**吊销不影响已注册设备**("Devices that you already enrolled with the revoked token remain active and enrolled"),只挡新注册;踢已注册设备须在控制台删除该浏览器(服务端将其 DM token 置 invalid → 客户端 fail-closed,见 1.2)。
- **删 DM token 留 enrollment token → 下次重启自动重新注册**;故 enrollment token 长期留存于 registry/plist(官方明确 "Do not delete the enrollment token on the managed device"),与 1.2 的三态逻辑吻合。
- **安全语义**:enrollment token 是长期有效、可共享的 bearer 凭据——持有者可将任意设备注册进该租户 OU。Google 以「可吊销 + 控制台删设备 + 每 OU 单 token 便于轮换」兜底,换取镜像/GPO 一键铺开的运维便利;另有 `CloudManagementEnrollmentMandatory` 策略可令注册失败时浏览器不可用(与 teleport 的 `RequireEnrollmentToBrowse` 同构)。teleport 若需收紧可考虑短时效 token / 按批次多 token(不必继承每 OU 单 token 限制)/ 注册审批流,但须权衡对镜像预置场景的破坏。

**官方分发方式**(全部走设备级写入,无「安装器内嵌 token」形态,安装包恒通用):

| 平台 | 方式 |
| --- | --- |
| Windows | ① GPO(ADMX → `CloudManagementEnrollmentToken`)② 直接写 registry ③ 控制台一键下载 `.reg` 文件(写 token + 清旧注册,「IT 脚本」的官方成品形态)④ UEM(Workspace ONE 等) |
| macOS | ① MDM 推配置(Profile Manager / Jamf / Workspace ONE)② 文本文件放 `/Library/Google/Chrome/`(必须设备级,"It won't work if you add it at user level")③ Jamf Pro ≥10.19 原生集成(UEM 侧直接生成 token) |
| Linux | 文本文件 `/etc/opt/chrome/policies/enrollment/CloudManagementEnrollmentToken`("must only contain the token and nothing else");控制台提供 "Download file (Mac & Linux)" |
| Android / iOS | EMM/UEM managed configuration(单独指南) |

- **推荐排序**:文档无显式 "recommended",仅条件式建议——"If your organization doesn't use mobile device management (MDM) tools… consider using Option 2: Edit the registry file"。隐含顺序:有管理工具用管理工具(域→GPO;MDM 机队→Intune/Jamf/Workspace ONE),无工具才退 registry/成品文件;Jamf/Workspace ONE 原生集成为最省心形态(管理员不碰 Admin console)。
- **镜像预置边界规则**:官方明确 "Do not include a device token in system image"——golden image **可**预烧 enrollment token(批量部署正路),**绝不能**烧 DM token(设备身份),否则整批克隆同一身份。「共享归属凭据可入镜像、唯一设备身份必须现场注册」应原样继承进 teleport 运维文档。
- **分发的前提是设备本就被 IT 摸得到**(域/MDM/脚本/镜像的设备级写入权限):CBCM 机器级纳管的 bootstrap 完全寄生于既有 IT 管理能力;真正无管理的 BYOD 设备没有 token 分发路径——再次印证 BYOD 走 profile 级而非机器级(见 §2)。teleport 同构照搬:控制台生成 token + 按平台产出成品物料(`.reg` / plist 描述文件 / 一行脚本),优先引导客户走既有 MDM/GPO,后续可与国产终端管理工具做 Jamf 式原生集成。

## 2. profile 级纳管:多租户共存的唯一层

- 每个 profile 有独立 `ProfilePolicyConnector` / `UserCloudPolicyManager`,策略 scope 固定 `POLICY_SCOPE_USER`(`components/policy/core/common/cloud/user_cloud_policy_manager.cc:185`);connector 按 BrowserContext 创建(`chrome/browser/policy/profile_policy_connector_builder.cc:37-72`)。不同 profile 登录不同租户账号,策略互不可见。
- 用户云策略绑定**账号**而非设备。Chromium 官方文档(`docs/enterprise/policies.md`)原文:"User policies are bound to user accounts, so a personal account on an enterprise-enrolled device would be affected only by device policy, while an enterprise-owned account on a personal device would only be affected by user policy for that account." —— BYOD 的机制即在此:个人设备不做机器级纳管,只做 profile 级。
- **登录流程是「先登录、后自动归属」**:企业账号登录触发 `DiceWebSigninInterceptor`(Google 账号)或 OIDC interceptor(第三方身份,`chrome/browser/enterprise/signin/`),按账号所属组织自动分流,无「先选租户」步骤。
  - `ProfileSeparationSettings` = ENFORCED 时强制新建独立 work profile(`chrome/browser/signin/signin_util.cc:210-225`;拦截入口 `dice_web_signin_interceptor.cc:697,:1029-1044`),用户拒绝则被登出账号;SUGGESTED 为建议。
  - OIDC 场景按 `subject/issuer` 查重、一账号一 profile(proto `ProfileRegistrationPayload`,`device_management_backend.proto:3557-3571`);一个 profile 绑定一个管理账号/域。

## 3. 策略优先级(桌面端,M148 源码 + 官方文档双重确认)

### 3.1 完整优先级阶梯(`PolicyPriorityBrowser` 全部枚举值)

`components/policy/core/common/policy_types.h:83-116`(枚举声明顺序即优先级,低→高)与 `policy_map.cc:66-111`(`GetPriority` 决定每个策略条目落在哪一级),与官方帮助页一致:

```
低 ── kEnterpriseDefault        企业环境默认值(POLICY_SOURCE_ENTERPRISE_DEFAULT)
      < kCommandLine            测试用命令行(POLICY_SOURCE_COMMAND_LINE)
      < kCloudUser              云·用户级:profile 内企业账号下发(默认落点)
      < kPlatformUser           平台·用户级:per-user GPO 等
      < kCloudMachine           云·机器级:CBCM 设备纳管下发(默认落点)
      < kCloudUserRaised        云·用户级·提权一档 †(条件触发)
      < kPlatformMachine        平台·机器级:GPO / MDM plist ── 可配置来源中的默认最高
      < kCloudMachineRaised     云·机器级·提权 ‡(条件触发)
      < kCloudUserDoubleRaised  云·用户级·提权两档 §(条件触发)
最高 ─ kMerged                  多来源合并产物(POLICY_SOURCE_MERGED,合成来源,恒为最终值)
```

**`kEnterpriseDefault` 不是下发通道,而是编译期烘焙的「受管环境专用默认值」**:管理员未配置该策略时,浏览器检测到用户/设备受管后自行注入的、与消费者版不同的默认值(chrome://policy 显示来源 "Default")。数据源是策略 YAML 的 `default_for_enterprise_users:` 字段(M148 共 55 条,如 `CastReceiverEnabled: false`),构建期由 `generate_policy_source.py:1200-1256` 生成 `SetEnterpriseUsersDefaults()`——每条带 `if (!policy_map->Get(...))` 守卫,只填空缺、任何真实来源都覆盖它,故居最底。注意:该机制**整体包在 `#if BUILDFLAG(IS_CHROMEOS)` 里,ChromeOS 专属**;运行期写入点仅三处——ChromeOS 受管用户(`user_cloud_policy_manager_ash.cc:571-580`)、ChromeOS kiosk/managed guest session 硬编码若干条(`device_local_account_policy_provider.cc:138-171`)、Android 受管账号独一条 `NTPContentSuggestionsEnabled=false`(`user_cloud_policy_manager.cc:181-188`);桌面端浏览器策略路径无任何注入。对 teleport 的启示:「受管即收紧」的安全基线可仿此烘焙进客户端、以纳管状态激活——零网络依赖(气隙友好)、租户无关、永远可被管理员显式配置覆盖;复用 `POLICY_SOURCE_ENTERPRISE_DEFAULT` 即可继承现有优先级/展示/覆盖语义。

三个条件级别的触发条件(`policy_map.cc:78-101`,均只作用于云来源,平台来源恒定落在 kPlatformUser/kPlatformMachine):

- **† `kCloudUserRaised`**:`CloudUserPolicyOverridesCloudMachinePolicy=true` **且**用户 affiliated,**且** `CloudPolicyOverridesPlatformPolicy=false` 时,云用户级从 `kCloudUser` 抬到此级——压过 `kCloudMachine`,但**仍低于 `kPlatformMachine`**。即单开 `CloudUserPolicyOverridesCloudMachinePolicy` 只提权「云内序」,不越平台机器级。
- **‡ `kCloudMachineRaised`**:`CloudPolicyOverridesPlatformPolicy=true` 时,云机器级从 `kCloudMachine` 抬到此级——反超 `kPlatformMachine`。该 metapolicy 与 affiliation 无关(机器级策略本就来自纳管租户自身)。
- **§ `kCloudUserDoubleRaised`**:两条路径可达——
  1. 两条 metapolicy 均为 true 且用户 affiliated(`policy_map.cc:91-100`):云用户级连带反超平台机器级。之所以叫「double raised」,是因为云用户级相对云机器级的相对位置取决于 `CloudPolicyOverridesPlatformPolicy`——云机器级被抬到 `kCloudMachineRaised` 后,云用户级要继续压过它就必须再抬一档;
  2. 策略定义本身为 `kSingleProfile` scope(只能由 managed account 设置的策略,`policy_map.cc:86-90`):这类策略**无条件**直达此级,与 metapolicy、affiliation 均无关——保证「本就只能来自用户云来源」的策略不被其他来源覆盖。
- **`kMerged`**:经 `PolicyListMultipleSourceMergeList` 等合并后的值以 `POLICY_SOURCE_MERGED` 合成来源写回(`policy_map.cc:106-107`),优先级恒最高——合并产物不再被任何单一来源覆盖。它不是可配置的策略来源,故「默认序最高」的表述仍指 `kPlatformMachine`。

- **平台机器级策略是可配置来源中的默认最高优先级**(常见误记为最低,实为相反)。MDM 下发的基础策略是默认的最终裁决者;仅 `kCloudMachineRaised`/`kCloudUserDoubleRaised` 两个条件级别可反超,且触发条件都握在机器级来源手里(见 3.2 闸门)。
- `PolicyLevel` 先于来源比较(`policy_map.cc:667`,`std::tie(lhs.level, lhs_priority)`):**mandatory 永远压过 recommended**,与来源无关。
- 冲突默认取最高来源、同优先级保留在先者(first-writer-wins,`policy_map.h` 注释);可用 `PolicyListMultipleSourceMergeList` / `PolicyDictionaryMultipleSourceMergeList`(支持 `*`)改为多来源合并,字典合并冲突键取最高优先级来源(`policy_merger.h`)。

### 3.2 改序 metapolicy 与两道防越权闸门

| metapolicy | 自版本 | 效果 |
| --- | --- | --- |
| `CloudPolicyOverridesPlatformPolicy` | Chrome 75 | 云机器级 → `kCloudMachineRaised`,反超平台机器级 |
| `CloudUserPolicyOverridesCloudMachinePolicy` | Chrome 96 | 云用户级 → `kCloudUserRaised`(两者都开 + affiliated → `kCloudUserDoubleRaised`,可反超平台) |

两道闸门:

1. **metapolicy 只认机器级来源**:user-cloud 来源下发的 precedence 元策略在 `PolicyServiceImpl::IgnoreUserCloudPrecedencePolicies()`(`policy_service_impl.cc:618-631`)被显式 `SetIgnored()`——租户用户策略无法自我提权。两条 metapolicy 的 YAML 定义均为 `per_profile: false` + `metapolicy_type: precedence`。
2. **affiliation 门控**:云用户策略提权还要求用户 affiliated——用户 affiliation ID 与设备 affiliation ID **交集非空**(`components/policy/core/common/cloud/affiliation.cc:18-25`),即用户所属组织 == 纳管该机器的组织(`policy_map.cc:91-100`,提权分支以 `is_user_affiliated` 为条件)。

### 3.3 跨租户语义:降权 + 绝不合并

机器被 A 组织纳管、用户属于 B 组织时:affiliation 交集为空 → B 的用户策略既不能提权也不能合并(`CloudUserPolicyMerge` 同样要求 affiliated,`policy_service_impl.cc:486-492`、`policy_merger.cc:66-89`),只能以默认最低优先级存在。官方帮助页即以 Company A/B 举例:"To prevent data leaks, machine and user policies can not be merged if they do not originate from the same Admin console… Company A's policies will always take precedence over Company B's user profile policies."

## 4. 部署形态:SaaS 独占云纳管,on-prem/气隙走平台策略通道

- **CBCM(现名 Chrome Enterprise Core)只有 SaaS**,管理控制台仅 admin.google.com;对「自托管 CBCM」做过对抗性检索,无任何来源存在。
- **官方 on-prem 路径 = 纯平台策略通道**:Windows GPO(ADMX 模板 → registry)、macOS managed preferences plist、Linux `/etc/opt/chrome/policies` JSON,或 Intune/Workspace ONE 等 MDM。官方文档:"Use your preferred on-premise tools to keep management behind your organization's firewall"(帮助页 187202、9037717)。
- 该通道**本地读取、零云依赖**,天然兼容气隙(注意:「气隙可用」是机制推断,Google 未字面承诺 air-gapped;CBCM 的报表/远程指令等云功能在气隙下自然不存在)。
- 关键洞察:**平台策略通道就是 Google 版的「气隙口子」,且默认还是最高优先级**——气隙/私有化形态无需复用云纳管协议。

## 5. DMServer 协议要点:机器级与 profile 级是两条独立通道

| | 机器级(CBCM) | profile 级(账号登录) |
| --- | --- | --- |
| register 请求 | `register_browser`(`RegisterBrowserRequest`,proto `:3540-3555`,顶层字段 `:5151-5152`) | 标准 `register`(`DeviceRegisterRequest` type=`BROWSER`,proto `:202-215`)或 OIDC 注册(`TYPE_OIDC_REGISTRATION`,`cloud_policy_client.cc:658-673`) |
| 鉴权 | enrollment token(`DMAuth::FromEnrollmentToken`,`cloud_policy_client.cc:586,:598-603`) | 用户 OAuth token / OIDC 凭据 |
| policy_type | `google/chrome/machine-level-user`(`cloud_policy_constants.cc:99-106`) | `google/chrome/user`(同文件 `:142-154`) |
| 身份产物 | 机器 DM token(单值) | profile 级绑定(OIDC 按 `subject/issuer`) |

Chromium 文档对机器级云策略的定性:"machine-wide cloud-based policy from DMServer. It is a user policy, but it would be applied to all users."(`docs/enterprise/policies.md`)

## 6. 对照:Microsoft Edge for Business

> ⚠️ 本节来自微软官方文档单轮抓取,未经三票对抗验证,置信度低于其余章节。

- 同构:work/personal profile 自动分离(独立 cache/storage),Entra ID 登录激活 work profile,租户归属按账号自动,machine 级(Intune/GPO)与 profile 级策略并存。
- **跨租户是显式支持的产品场景**(contractors/partners/mergers):设备被租户 A 的 Intune 纳管时,租户 B 可经 **Intune MAM(App Protection)+ Entra Conditional Access** 对用户在该设备上的 Edge work profile 做 **profile 级 enrollment,不纳管设备**;策略只作用于 B 的组织数据(剪贴板限制、受保护下载、水印、防泄漏),个人/A 的浏览不受影响。(learn.microsoft.com `microsoft-edge-cross-tenant-support-using-intune-mam`,2026-04 更新,要求 Edge 147+)
- 值得注意的两个设计点:
  1. 该 MAM+CA 路径**不支持同租户受管设备**(同租户场景走完整设备管理,二者互斥);
  2. 设备开了 A 租户的设备级 Endpoint DLP 时,B 的跨租户 MAM 默认被阻断,需**设备主租户 A** 配置 `MAMWithDeviceDLPEnabled` 放行——「跨租户 profile 纳管需要设备主人配合让路」,设备主人始终占上位。

**结论**:Edge 与 Chrome 殊途同归——机器级单一主人,跨租户全部下沉到 profile/应用层,且设备主租户拥有最终否决权。

## 7. 对 teleport 的架构启示

以下为调研直接推出的建议,供后续 brainstorm/spec 采纳:

1. **机器级策略:租户相关 + 单一写入者**。通用安装包不含租户身份;enrollment token(或等价物)决定归属;注册互斥、fail-closed。**不要设计「多租户机器级策略合并/排序」**——那是伪需求且是数据泄露源;要设计的是显式**换绑流程**(解除纳管 → 清 token → 重新注册)。
2. **多租户 = profile 层**:租户策略随企业账号(teleport 的 OIDC enrollment)下发,严格 per-profile——与现行 enterprise-account-system 方向一致。交互采用「先登录、后按账号归属自动分流」,无需先选租户。
3. **照搬 affiliation 语义**:仅「用户租户 == 机器租户」时允许用户策略提权/与机器策略合并;跨租户用户策略永远最低优先级、绝不合并。建议进协议设计(server 侧签发 affiliation ID,client 侧取交集)。
4. **保留平台策略通道并保持其默认最高优先级**:它同时是 ① 企业 MDM 基础策略载体(禁多 profile、强制登录、钉死租户 slug 等),② 私有化/气隙兜底通道,③ 无云依赖逃生舱。precedence 元策略若引入,须复刻「只认机器级来源」的过滤。
5. **气隙口子 = 租户专有包或预置策略文件**,语义等价于平台策略通道,不复用云纳管协议。气隙形态下多租户能力整体退化(单租户、机器级为主)是特性而非缺陷:气隙设备无公网,物理上不可能同时服务非气隙租户;多个气隙租户共存同理不存在。
6. **「SaaS 租户 + 私有化租户并存于一台设备」不会发生机器级互相覆盖**——在单一写入者模型下,谁先纳管谁持有 token,另一租户只能走 profile 级。设备属于谁(通常是发设备的那家),谁做机器级纳管。

## 8. 已知边界与未决问题

- 所有优先级结论仅适用**桌面端**;ChromeOS 是另一套基于 source 的直排序(`policy_map.cc:648-650`),不在本次范围。
- 一条被三票否决的 claim 值得记住:「平台机器策略压过一切」只在**默认序**下成立,`CloudPolicyOverridesPlatformPolicy` 开启后云机器级可反超。引用默认序结论时勿超出限定。
- Edge 对照(第 6 节)未经三票验证;Edge 的 machine 级多租户细节(Intune/Entra 侧)未深入,如需要可单独调研。
- 历史演进(medium 置信,2-1 票):2016 年时 `PolicySource` 尚不参与优先级裁决(只比 level/scope),来源感知优先级与两条 precedence 元策略(2019/2021)为后置演进——自研后端初版可先只做 level/scope,分层演进有先例。
- Chrome「同一 profile 内 secondary account 的策略是否完全不生效」未找到直接断言,仅从 affiliation/不可合并侧面证实,如成为设计依赖需二次确认。

## 9. 主要来源

- [Understand Chrome policy management(策略优先级官方文档,帮助页 9037717)](https://support.google.com/chrome/a/answer/9037717)
- [Chromium docs/enterprise/policies.md](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/enterprise/policies.md)
- [Set Chrome policies with on-premise tools(帮助页 187202)](https://support.google.com/chrome/a/answer/187202)
- [Understanding policy precedence for Chrome browser(Google Cloud 博客)](https://cloud.google.com/blog/products/chrome-enterprise/understanding-policy-precedence-for-chrome-browser)
- [ProfileSeparationSettings 策略定义](https://chromeenterprise.google/policies/profile-separation-settings/)、[Set up Chrome browser profile separation(帮助页 11198768)](https://support.google.com/chrome/a/answer/11198768)
- [CBCM enrollment token 管理(帮助页 9301891)](https://support.google.com/chrome/a/answer/9301891)
- [Protect corporate data in Microsoft Edge using Intune App Protection(MAM)](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-cross-tenant-support-using-intune-mam)、[Microsoft Edge for Business](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-for-business)
- 本地 M148 源码(148.0.7778.180,file:line 已在文中标注):`components/policy/core/common/{policy_types.h,policy_map.cc,policy_service_impl.cc,policy_merger.cc}`、`components/policy/core/common/cloud/{affiliation.cc,cloud_policy_client.cc,cloud_policy_constants.cc}`、`components/enterprise/browser/controller/{browser_dm_token_storage.h,chrome_browser_cloud_management_controller.cc}`、`chrome/browser/policy/browser_dm_token_storage_{win.cc,mac.mm,linux.cc}`、`chrome/browser/signin/{signin_util.cc,dice_web_signin_interceptor.cc}`、`components/policy/proto/device_management_backend.proto`
