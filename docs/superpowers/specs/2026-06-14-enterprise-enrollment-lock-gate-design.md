# Teleport 纳管门禁设计 · Layer 1 重设计:force-signin 框架 + 全局 ProfileCloudPolicyManager + picker step + 就地自驱 OIDC 注册

- 状态:设计(评审中)
- 日期:2026-06-15(**rev 4** — 收敛终版;由「全局 ProfileCloudPolicyManager」化解就地纳管的底层障碍)
- 仓库:`teleport`(Chromium overlay 客户端)
- 本文归属:**客户端设计权威**,**取代** `2026-06-11-...gate-design.md` 的 **Layer 1**;Layer 2(导航 throttle)、策略 pref、判定谓词沿用那份。本文 rev4 作废自身 rev1/rev2/rev3(见 §12 演进,均经第三方对抗性评审证伪)。
- 关联:`2026-06-04-enterprise-oidc-client-design.md`、`2026-06-03-enterprise-account-system-design.md`、[[enterprise-enrollment-gate-feature]]、[[enterprise-account-system]]
- 分支/worktree:`enterprise-enrollment-gate`

> **核心突破:** 我们是 **dasherless-only(3P OIDC,永不走 GAIA)**的受管浏览器。把 `ProfileImpl::DoFinalInit` 的 cloud-policy-manager 创建逻辑**全局统一为 `ProfileCloudPolicyManager`**——让**每个 profile 从出生就持有 dasherless 策略管理器**。这一刀化解了前三版绕不过去的底层障碍(dasherless 策略管理器在 profile 加载时一次性建定、运行时无法换 → 当前 profile 无法就地纳管),从而**复活最干净的「就地纳管」**:就地、单 profile、OP 中央会话原地(搭便车 SSO 最稳)。

---

## 1. 设计要点(一句话)

**(A)** 全局统一 `ProfileCloudPolicyManager`(dasherless-only);**(B)** 开全局 force-signin 让 per-profile 锁机器自洽、未纳管 profile 被锁、无浏览器窗口(无逃逸);**(C)** picker 处理被锁 profile 时增设 **Teleport 纳管 step**(克隆 `ReauthFlowStepController`,不替换 flow controller),provider 在**当前(被锁)profile** 上托管 OIDC 登录(OP 会话原地);**(D)** patch OIDC throttle 把捕获的 token 在纳管语境**改投给我们的就地注册器**(不调拦截器);**(E)** 就地注册器复用底层注册/属性/策略机器,把**当前** profile 标记受管并拉策略;**(F)** 完成照搬 `OnReauthCompleted`(`LockForceSigninProfile(false)` + `FinishFlowAndRunInBrowser(当前 profile)`)解锁开正常浏览器。**绝不新建 profile。**

---

## 2. 关键决策(已拍板)

1. **全局 `ProfileCloudPolicyManager`(决定性突破)**。我们 dasherless-only,`UserCloudPolicyManager`(GAIA 用)永不需要。统一后每个 profile 从出生持有正确管理器 → 就地纳管成立。**这是化解前三版核心障碍的关键**(§3 实证爆炸半径可控)。
2. **就地纳管,绝不新建 profile**。OP 中央会话留在用户实际使用的当前 profile,搭便车 SSO 最稳;无孤儿、单 profile、模型最干净。
3. **用 force-signin 框架(开全局 `kForceBrowserSignin`)**。锁位被该策略「拥有」(`Initialize` 清锁 `profile_attributes_entry.cc:200-204`、`LockForceSigninProfile` DCHECK `:756`、`TryLaunchLockedProfile` CHECK `profile_picker_handler.cc:394`)——开了三者自洽;`ForceSigninVerifier` 对 dasherless 空转无害。picker 运行时无浏览器窗口 → 无 Ctrl+N/新窗口/FRE 逃逸。
4. **picker 加 step,不换 flow controller**(reauth 现成先例 `profile_picker_flow_controller.cc:280-323`);换 controller 仅作实现期受阻兜底。
5. **不调 OIDC 拦截器,自驱就地注册;token 经 throttle patch 改投**。拦截器同意框锚定 Browser(picker 无 Browser 会崩)、默认新建 profile——全不要。**承认需要一个 throttle patch**(token 全树只在 throttle 私有方法解析,无对外回调口,§5)。
6. **per-profile 架构,单 profile 优先**;`AllowMultipleProfiles`、多 profile 并行、添加-profile 入口收口为后续。
7. **与 Path A 关系**:撤启动导向(原 Task 9);留 Layer 2 throttle(Task 6/7,作 provider WebContents 内导航兜底)、pref(Task 8)、谓词(Task 5)。

---

## 3. 突破基石:全局 ProfileCloudPolicyManager —— 爆炸半径已实证可控

`ProfileImpl::DoFinalInit`(`profile_impl.cc:615-628`)当前 if/else:有 enrollment token 或 `IsDasherlessManagement()` → `ProfileCloudPolicyManager`,否则 → `UserCloudPolicyManager`。**改为永远建 `ProfileCloudPolicyManager`(`is_dasherless=true`,它决定 policy type 取 dasherless user type),并 patch 工厂路由永远返回 `GetProfileCloudPolicyManager()`(`user_policy_oidc_signin_service_factory.cc:25-34`)。**

实证(M148):
- `ProfileCloudPolicyManager::Create`(`profile_cloud_policy_manager.cc:73-112`)对未纳管 profile **良性空跑**(空 store、`is_managed=false`、无 CHECK/DCHECK),与 `UserCloudPolicyManager` 空跑等价。
- ProfilePolicyConnector 对两类 manager 接口一致、type-agnostic(`profile_policy_connector_builder.cc:63-66`);未纳管 profile 仍 `IsManaged()=false`。
- **爆炸半径**:dasherless-only + 禁 GAIA 的 Mac/Win/Linux 构建里,**无任何「裸解引用 `GetUserCloudPolicyManager()`」破坏点可达**;唯一裸解引用(`user_policy_oidc_signin_service.cc:314`)在 **dasher-based** 分支(永不走)。`GetCloudPolicyManager()` 合一 getter 照常返回;`GetUserCloudPolicyManager()` 恒 null(安全)。
- 机器级 CBCM 是**独立 provider 层**(`profile_policy_connector.cc:492-507`),不冲突不重复。sync/identity 不受影响。
- **效果**:每个 profile 从出生持有非空 `ProfileCloudPolicyManager` + 工厂绑对 → **当前 profile 就地 dasherless 纳管成立,连「service 动态重绑」时序坑一并消失**。

> 唯一裸解引用若要 belt-and-suspenders,加一句 `if (!user_policy_manager) return;`(对我们是死代码)。

---

## 4. 锁与门禁框架(force-signin)

- 开全局 `kForceBrowserSignin`(经既有 CBCM 通道下发;默认 on = 安全默认,沿用 06-11 §1.2)。
- `Initialize` 上锁条件豁免加在 `profile_attributes_entry.cc:195-197` 内层 `if`,以 `GetProfileManagementId().empty()`(**非 `CanBeManaged()`**,dasherless 不满足)区分;已纳管永不重锁。
- session restore 对锁定 profile 有 `DCHECK(!IsSigninRequired())`(`session_restore.cc:1389`)→ restore 自动免疫。
- 被锁 profile → picker;`TryLaunchLockedProfile`(`profile_picker_handler.cc:392`,`CHECK(IsForceSigninEnabled())` `:394`)增设 Teleport 分支 → `SwitchToEnrollment`。**插入点必须在 reauth 分支 `if` 之后、fresh-profile 的 `SwitchToSignIn`(`:424`)之前**,以同时拦住「全新 profile(`GetActiveTime().is_null()`→原走 GAIA SwitchToSignIn)」与「既有未登录 profile(原走 `:447` ReauthNotAllowed 死路)」两类受门禁未纳管 profile(评审纠正:原 spec「:426/:447 之前」措辞含糊、会漏掉 fresh 这类)。

---

## 5. picker 内 Teleport step + token 改投

- **step 注入**:克隆 `ReauthFlowStepController`/`CreateReauthtep`(`profile_picker_flow_controller.cc:280-323`,本就是「非 SignInProvider 的自定义 provider + 自有 step controller」先例);host 契约(`ShowScreen`/`OnHidden`)不强制 GAIA 回调。**provider 必须是全新、无 GAIA 的实现,不可复用/包装 `ProfilePickerReauthProvider`**——它构造即 `DCHECK(!gaia_id_to_reauth_.empty())` + `DCHECK(!email_to_reauth_.empty())`(`profile_picker_reauth_provider.cc:74-75`)、且内部 `GetChromeReauthURL`/`ForceSigninVerifier`/DICE 全是 GAIA;dasherless 无 gaia/email 会直接触发这些 DCHECK。我们的 provider 只做「`ShowScreen(enroll_url)` + 监听我们自己的完成信号」,无任何 GAIA DCHECK。
- **provider WebContents 跑在当前(被锁)profile**(同 reauth `profile_picker_reauth_provider.cc:91`);`ShowScreen` 走真实 `LoadURL`(`profile_picker_view.cc:383`)→ NavigationThrottle 管线生效;OP 登录会话落当前 profile。
- **token 改投(承认的 patch)**:OIDC payload 全树只在 throttle 私有方法解析(`oidc_auth_response_capture_navigation_throttle.cc:284-503`),终点硬调 `MaybeInterceptOidcAuthentication`(`:398/:494`)。patch:在**纳管语境**(当前 profile 受门禁且未纳管)把已解析 token 改投 `teleport_oidc_inplace_registrar`,而非调拦截器。

---

## 6. 就地自驱注册(复用底层机器,绝不新建 profile)

`teleport_oidc_inplace_registrar` 拿到 token 后,对**当前** profile 顺序编排(均直接复用 Chrome 机器):
1. **注册**:`CloudPolicyClientRegistrationHelper::StartRegistrationWithOidcTokens`(`cloud_policy_client_registration_helper.cc:134`)→ `CloudPolicyClient::RegisterWithOidcResponse`(`cloud_policy_client.cc:658/672`,`TYPE_OIDC_REGISTRATION`)→ 拿 DMToken 字符串。
2. **属性**:对当前 profile entry 写 `SetDasherlessManagement(true)`(先行,见下)、`SetProfileManagementOidcTokens`、`SetProfileManagementId`(`oidc_managed_profile_creation_delegate.cc:50-52` + `managed_profile_creator.cc:82` 的 setter 体);+ recovery prefs(`interceptor:595-598`)。
3. **策略**:当前 profile 的 `UserPolicyOidcSigninService::FetchPolicyForOidcUser(AccountId(), dm_token, client_id, email, …)`(先 `ResetGaiaPolicyManagement()`)→ `FetchPolicyForSignedInUser`(`user_policy_signin_service_base.cc:88`)→ `SetupRegistration(dm_token)`(`:111`)→ `InitializeCloudPolicyManager`→`Connect`(`:263/272`)→ 当前 profile 的 `ProfileCloudPolicyManager`(§3 已保证非空)store 加载 + 首拉 → `has_policy()=true`。

`IsEnrolled(当前 profile)` = `GetProfileManagementId()` 非空 且 `ProfileCloudPolicyManager has_policy()` → 翻真。OP 会话全程原地。

> **§3 的工厂统一 patch 使「manager 重绑」时序坑消失**:service 构造即绑非空 `ProfileCloudPolicyManager`,无需设标志后重绑。
>
> **但有一条硬时序约束(违反即崩,评审纠正)**:步骤 2 的 `SetDasherlessManagement(true)` + `SetProfileManagementOidcTokens`(写 id_token)**必须严格早于**步骤 3 的 `FetchPolicyForOidcUser`。因为 `IsDasherlessProfile()`(`user_policy_oidc_signin_service.cc:72-78`)= 有 id_token **且** `IsDasherlessManagement()`;二者任一未先写,`FetchPolicyForSignedInUser` 会走 `dasher_based=true` 分支 → `static_cast<UserCloudPolicyManager*>(ProfileCloudPolicyManager*)` 错误转换 + 裸解引用 null `GetUserCloudPolicyManager()`(`:314`)→ **崩**。编排器必须保证「先写属性、后拉策略」,单测覆盖此顺序。

---

## 7. 状态机

```
[profile 加载]  DoFinalInit 强制建 ProfileCloudPolicyManager(全局,dasherless-only)
[未纳管 profile 初始化]  force-signin 开 + 豁免条件 → 置 force_signin_profile_locked
  ▼
[启动/选中该被锁 profile]  picker → TryLaunchLockedProfile →(Teleport 分支)SwitchToEnrollment
  ▼
[Teleport step/provider]  当前(被锁)profile 上托管 EnterpriseEnrollUrl();OP 登录,会话原地
  └ IdP 多主机重定向链 → OIDC throttle 捕获 token →(patch 改投)teleport_oidc_inplace_registrar
  ▼
[就地自驱注册]  层1 注册 → 层2 属性(SetDasherlessManagement 先行)→ 层3 FetchPolicyForOidcUser(当前 profile)
  └ ProfileManagementId 写 + has_policy()=true → IsEnrolled(当前 profile)=true(OP 会话原地)
  ▼
[完成]  照搬 OnReauthCompleted:LockForceSigninProfile(false) + FinishFlowAndRunInBrowser(当前 profile) → 解锁、开正常浏览器
  ▼
[正常浏览器]  当前 profile 已受管、持 OP 会话(搭便车 SSO 可用);后续启动豁免不再锁,直接放行
```

---

## 8. 组件与 patch 面

**新增 //teleport(编进 chrome target,经 BUILD.gn patch):**
- `teleport_enrollment_lock.{h,cc}`:`ShouldLockProfile(entry)` = 受门禁 + `ProfileManagementId` 空。
- `teleport_enrollment_step`(+ provider):克隆 reauth step;当前 profile 上托管 enroll URL;捕获→交注册器;完成照搬 `OnReauthCompleted`。
- `teleport_oidc_inplace_registrar.{h,cc}`:§6 编排器(注册→属性→策略),就地纳管当前 profile。

**上游 patch:**
- `profile_impl.cc:615-628`:全局强制 `ProfileCloudPolicyManager`。**`is_dasherless` 参数硬编码为字面 `true`,不读 `entry->IsDasherlessManagement()`**(评审纠正:全新 profile 在此刻 `entry` 可能为 null,`:1125` 才加 entry;读它会 null 解引用)。`ProfileCloudPolicyStore` 的 `CHECK(is_dasherless ? IsUserLevelPolicyType : ...)`(`profile_cloud_policy_store.cc:54-55`)在 true 下通过。
- `user_policy_oidc_signin_service_factory.cc:25-34`:路由永远 `GetProfileCloudPolicyManager()`。
- 开启全局 force-signin(GN args / 策略)。
- `profile_attributes_entry.cc:195-197`:`ShouldLockProfile` 豁免(一行级)。
- `profile_picker_handler.cc`(`TryLaunchLockedProfile`):加 Teleport 纳管分支。
- `profile_picker_flow_controller.{h,cc}` + `profile_picker.{h,cc}`:`SwitchToEnrollment` + Teleport step。
- `oidc_auth_response_capture_navigation_throttle.cc`:纳管语境 token 改投(扩展既有 patch)。
- 撤 Path A 启动导向 patch(原 Task 9)。

> **零改动**:`Browser::Create`、startup_browser_creator 路由、session restore、OIDC **拦截器**(自驱不调它)、机器级 CBCM。

---

## 9. plan 阶段必须实证(按风险排序)

1. **全局 ProfileCloudPolicyManager 真机无回归**:dev 构建启动正常、未纳管 profile 良性(`chrome://policy` 无异常、无崩);`GetUserCloudPolicyManager()` 恒 null 不触发可达裸解引用。**另需确认 GAIA turn-sync-on 流在我们构建里确实不可达**——否则 `turn_sync_on_helper_policy_fetch_tracker.cc:82` 的 `provider != GetUserCloudPolicyManager()` 恒真退化成 no-op,可能挂到超时(我们禁 GAIA,应不可达,但实证)。**先验(地基)。**
2. **picker 内 throttle/auth + token 改投跑通**:provider WebContents 内 OIDC throttle 触发、多主机重定向链可走、改投到注册器。**最高风险点(评审更正并加重)**:`profile_picker_sign_in_provider.cc:205` 的 `AddNewContents` 抑制只在 **GAIA SignInProvider** 里;reauth provider / 我们克隆的 provider 是 `WebContentsObserver`、**根本没有 `WebContentsDelegate`** → 我们 provider 的 WebContents 里任何 `window.open`/`target=_blank`/弹窗式 MFA **会被静默丢弃**。须实证 enroll→OP→accounts 登录链是**纯 30x 重定向、不依赖弹窗**;若依赖,需给 provider 装一个受控 delegate 或另想办法。**必须真机构建验证。**
3. **就地注册三步对当前 profile 成立**:注册/属性/`FetchPolicyForOidcUser` 在当前 profile 跑通,`ProfileCloudPolicyManager.Connect` + `has_policy()` 翻真;工厂统一后无重绑问题。
4. **OP 会话原地**:纳管后当前 profile cookie jar 仍持 OP 会话,搭便车 SSO 可用。
5. **加 step 是否够(vs 换 controller)**;**force-signin 全局副作用**(禁 guest、picker 启动必经、未纳管全锁=本意、FRE 次序)。

---

## 10. 测试与验收

- **单测(gtest)**:`ShouldLockProfile` 谓词矩阵;`teleport_oidc_inplace_registrar` 编排顺序(fake 驱动)。
- **端到端(macOS dev)**:全新 profile 启动 → picker → Teleport 纳管 step(**无浏览器外壳、无 Ctrl+N 逃逸**),窗内手机号登录(OP 会话落当前 profile)→ **就地**注册当前 profile(无新 profile)→ `register_profile` 200 + 用户策略 200 → 自动解锁、开正常浏览器;**当前 profile 持 OP 会话,搭便车 SSO 可用**;重启(含离线)放行;`RequireEnrollmentToBrowse=false` → 未纳管也放行;`chrome://policy` 展示正确、无 Google 穿帮。
- 多 profile / 添加-profile / reauth 实流:本轮**不验**(后续)。

---

## 11. 范围边界

**In(本轮)**:全局 `ProfileCloudPolicyManager` 统一;开 force-signin + 豁免;Teleport step/provider + token 改投;就地自驱注册;搭便车-SSO 不变式;`OnReauthCompleted` 解锁;撤 Path A 启动导向、留 throttle/pref/谓词;§9 五项实证;macOS 活验。

**Out(后续)**:`AllowMultipleProfiles` + 多 profile 并行;添加-profile 入口收口;会话有效性重查 / 真正 reauth 实流;换 flow controller(兜底);Windows GPO。

---

## 12. 设计演进(为什么不是前几版)

- **Path A(06-11,已实现迭代 1)**:throttle + 启动导向。痛点:外壳有反应却处处弹回、session restore 闪现、多窗口逃逸。
- **rev1/B(自建无外壳窗口)**:证伪——锁位被全局 force-signin 策略「拥有」(不开则每启动清锁 + DCHECK);Ctrl+N 经 `Browser::Create` 不查锁 → 逃逸开正常浏览器。
- **rev2(picker 内跑 OIDC 拦截器)**:证伪——拦截器同意框锚定 Browser,picker 无 Browser → 崩;且新建 profile + 自开 Browser。
- **rev3(picker + 自驱就地注册,但未统一 manager)**:证伪——① token 全树只在 throttle 解析、无对外口(需 patch);② **就地 dasherless 注册不可行**:`ProfileCloudPolicyManager` 在 `DoFinalInit` 加载时一次性建定、运行时无法换,当前 profile 拿到 null → 崩。
- **rev4(本版)**:用户洞察——**我们 dasherless-only,直接全局统一 `ProfileCloudPolicyManager`**,让每个 profile 出生即带正确管理器,**一次性铲平 rev3 的底层障碍**,复活最干净的「就地」。框架对、认证对、就地、OP 会话原地、最大化复用 Chrome 机器,补丁全是「表达 dasherless-only 受管浏览器」的 targeted 改动。
