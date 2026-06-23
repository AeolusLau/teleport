# 企业纳管门禁 · Layer 1 重设计实现计划(rev4 · plan rev2,已纳入两轮对抗性评审修订)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让未纳管的受门禁 profile 被 force-signin 锁住(纳管前无可用浏览器窗口),在 ProfilePicker 内经一个无 GAIA 的 Teleport step **就地**完成 3P OIDC 纳管(当前 profile 原地转受管、OP 会话原地供搭便车 SSO),纳管成功后解锁并打开正常浏览器。

**Architecture:** ① 全局把 `ProfileImpl` 的 cloud-policy-manager 统一为 `ProfileCloudPolicyManager`(dasherless-only,使任意 profile 出生即可就地纳管);② **最后**开 force-signin 复用其 per-profile 锁 + picker(运行时无浏览器窗口);③ picker 锁屏分支增设 Teleport step/provider(异步加载目标 profile),在当前 profile 上跑 OIDC 登录;④ patch OIDC throttle 把捕获 token 改投我们的就地注册器(经 WebContents UserData 拿 step 注入的 done_cb),复用 Chrome 底层注册/属性/策略机器标记当前 profile;⑤ 照搬 `OnReauthCompleted` 解锁。

**Tech Stack:** Chromium M148 overlay、C++、GN、gtest、Brave 式 patch(edit-live → `git diff` → patch → revert → `apply_patches`)、`policy::CloudPolicyClient`/`ProfileCloudPolicyManager`/`UserPolicyOidcSigninService`、ProfilePicker flow controller。

**Spec:** `docs/superpowers/specs/2026-06-14-enterprise-enrollment-lock-gate-design.md`(rev4)

**前置环境**:worktree `enterprise-enrollment-gate`;`chromium/src/teleport` 已链接本 worktree `src`;`out/mac/arm64/dev` 存在;`TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`。

---

## 全局工作流铁律(每个上游 patch 都遵守)

- **patch 生成**:`apply_patches.py` 先把现有 patch 全部应用 → 在**已含前序 hunk 的 live 文件**上叠加新 edit → `git -C $CHROMIUM/src diff -- <path>` 重生为**累积** patch → `git checkout -- <path>` → 再 `apply_patches.py` 验证。**扩展共享文件 patch 时绝不先 `git checkout`**(否则丢前序 hunk,评审 I4)。
- commit 一律从 worktree(`git -C <worktree>`)。
- **关键时序铁律(违反即崩,spec §6)**:就地注册里 `SetDasherlessManagement(true)` + `SetProfileManagementOidcTokens` **必须早于** `FetchPolicyForOidcUser`。
- **force-signin 最后开**(评审 C1):在全流程接通(Task 1–9)前,**不**全局开 force-signin;否则浏览器被锁成砖、无法测。仅 Spike B/C 用临时 patch 短暂开、做完即 revert。

---

## 关键已核实事实(评审已逐条对源,file:line)

- **全局 manager**:`profile_impl.cc:615-628` if/else → 永远建 `ProfileCloudPolicyManager`(`is_dasherless` 硬编码 `true`,**不读可能为 null 的 `entry`**)。`profile_cloud_policy_store.cc:54-55` 的 `CHECK(is_dasherless ? IsUserLevelPolicyType : ...)` 在 true 下通过。工厂帮助函数 `user_policy_oidc_signin_service_factory.cc:25-34` `GetCloudPolicyManager` 返回 `std::variant<UserCloudPolicyManager*, ProfileCloudPolicyManager*>` → 改为永远 `return profile->GetProfileCloudPolicyManager();`(确认消费者 `user_policy_oidc_signin_service.cc` 各 `std::get`/`std::visit` 处理 profile 变体)。**安全**:stock 本就给每个 desktop profile 建非空 `UserCloudPolicyManager`,我们只换类型不换 null 性。
- **force-signin 开法**(评审 I1):pref `kForceBrowserSignin` 注册在 **`chrome/browser/profiles/profiles_state.cc:85`**(`RegisterBooleanPref(..., false)`,local_state)。开法 = patch 该默认为 `true`;`IsForceSigninEnabled()`(`signin_util.cc:157-166`)缓存读取,无 `BrowserSignin` 策略时默认不被覆盖。副作用:guest 被禁(`ForceBrowserSignin.yaml`)。
- **锁豁免**:`profile_attributes_entry.cc:194-198` 上锁:`if (IsForceSigninEnabled()) { if ((!IsReplaceSyncPromos()||kNotSignedIn) && !CanBeManaged()) SetBool(locked,true); }`。dasherless 永远 `CanBeManaged()=false`(`:503-512`,`kNotSignedIn`)→ 即便纳管也会被重锁,故**必须**加 `&& !teleport::ShouldLockProfile-的反`豁免:把内层条件改为 `... && !CanBeManaged() && teleport::ShouldLockProfile(this)`(`ShouldLockProfile`= 受门禁且 `GetProfileManagementId().empty()`)。
- **picker 分支**(评审 C2):`TryLaunchLockedProfile(ProfileAttributesEntry& entry)`(`profile_picker_handler.cc:392`)作用域**无 `Profile*`**;reauth 分支(`:403-418`)经 `LoadProfileByPath(entry.GetPath(), false, OnProfileLoadedForSwitchToReauth)` 异步加载,回调 `OnProfileLoadedForSwitchToReauth(Profile*)`(`:453`)里才调 `SwitchToReauth(profile,...)`。我们须照此:插入点(在 reauth `if` 之后、`GetActiveTime().is_null()` 的 fresh 分支 `:426` 之前)kick off `LoadProfileByPath(..., OnProfileLoadedForSwitchToEnrollment)`,回调里 `SwitchToEnrollment(profile)`。
- **step 范式**:克隆 `ReauthFlowStepController`/`CreateReauthtep`(`profile_picker_flow_controller.cc:280-323`);provider **全新无 GAIA**(不复用 `ProfilePickerReauthProvider`,其 ctor `DCHECK(!gaia_id...)`/`DCHECK(!email...)` `:74-75`);provider WebContents 建在**当前(被锁)profile**(同 `:91`);`ShowScreen`→`LoadURL`(`profile_picker_view.cc:383`);完成照搬 `OnReauthCompleted`(`:557-578`)。
- **token 改投**:throttle 两处终点 `oidc_auth_response_capture_navigation_throttle.cc:398`(`tokens`/`*issuer_id`/`*subject_id`)、`:494`(`registration_payload.*`)token 在作用域内。
- **就地注册三层**:① `CloudPolicyClientRegistrationHelper::StartRegistrationWithOidcTokens`(`cloud_policy_client_registration_helper.cc:134`)→ `CloudPolicyClient::RegisterWithOidcResponse`(`cloud_policy_client.cc:658/672`),建独立 client 仿 `oidc_authentication_signin_interceptor.cc:336-360`;② 属性 setter(`oidc_managed_profile_creation_delegate.cc:50-52`+`managed_profile_creator.cc:82`)+ recovery prefs(`interceptor:595-598`);③ `UserPolicyOidcSigninService::FetchPolicyForOidcUser(account_id=AccountId(), dm_token, client_id, email, policy_fetch_start_time=base::TimeTicks::Now(), switch_to_entry=false, profile_url_loader_factory=profile->GetDefaultStoragePartition()->GetURLLoaderFactoryForBrowserProcess(), …)`(完整 8 参,评审 I6;先 `ResetGaiaPolicyManagement()`,`interceptor:621-623`)。
- **Layer 2 throttle × picker**(评审 C3'):既有 `TeleportEnrollmentGateThrottle` 会在 picker provider WebContents(跑在受门禁未纳管 profile)上拦非纳管域导航。须验证 OP 链全部主机在 `EnterpriseEnrollmentDomainSuffixes()`(`.fairyland.io`/`.beansec.com`)内;若有例外,在该 throttle 加「纳管 step 的 WebContents 豁免」。
- **复用既有 //teleport**(Path A iter1):`teleport_pref_names.h`(`prefs::kRequireEnrollmentToBrowse`)、`teleport_enterprise_urls`(`EnterpriseEnrollUrl()`)、`teleport_enrollment_gate.{h,cc}`(`ShouldGateProfile`/`IsEnrolled`,后者已用 `GetCloudPolicyManager()->core()->store()->has_policy()`)。

---

## 文件结构

**新增 //teleport(编进 chrome target,经 `chrome/browser/BUILD.gn` patch;参照 `teleport_enrollment_gate` 模式):**
- `src/browser/enterprise/teleport_enrollment_lock.{h,cc}` — `ShouldLockProfile(ProfileAttributesEntry*)`。
- `src/browser/enterprise/teleport_oidc_inplace_registrar.{h,cc}` — 就地注册编排器(**3 个协作者可注入**以便单测顺序)。
- `src/browser/enterprise/teleport_enrollment_step.{h,cc}` — Teleport step controller + 无 GAIA provider。

**上游 patch:**
- `patches/chrome/browser/profiles/profile_impl.cc.patch`(new)、`patches/chrome/browser/enterprise/signin/user_policy_oidc_signin_service_factory.cc.patch`(new) — 全局 manager。
- `patches/chrome/browser/profiles/profiles_state.cc.patch`(new) — force-signin 默认 true(**最后启用**)。
- `patches/chrome/browser/profiles/profile_attributes_entry.cc.patch`(new) — 锁豁免。
- `patches/chrome/browser/profiles/BUILD.gn.patch`(**new,评审 C3**) — 给 `source_set("profile_util_impl")` deps 加 `//teleport`。
- `patches/chrome/browser/ui/webui/signin/profile_picker_handler.cc.patch`(new) — Teleport 分支(异步 load)。
- `patches/chrome/browser/ui/views/profiles/profile_picker_flow_controller.{h,cc}.patch` + `patches/chrome/browser/ui/profiles/profile_picker.{h,cc}.patch`(new) — `SwitchToEnrollment` + step。
- `patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch`(**扩展既有**) — token 改投。
- `patches/chrome/browser/BUILD.gn.patch`(**扩展**) — 加 3 个新 //teleport 源文件。
- 删 `patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch`(撤 Path A 启动导向,**早删**)。

---

# Phase 0 — 去风险 spike(go/no-go,先做)

## Task 1: Spike A + 落地 — 全局 ProfileCloudPolicyManager(地基,可落地保留)

**Files:** `patches/chrome/browser/profiles/profile_impl.cc.patch`、`patches/.../user_policy_oidc_signin_service_factory.cc.patch`

- [ ] **Step 1: edit-live profile_impl.cc** — `:615-628` if/else 改为永远 `ProfileCloudPolicyManager::Create(... /*is_dasherless=*/true)`(删 else 的 UserCloudPolicyManager 分支;`is_dasherless` 传字面 `true` 不读 `entry`)。
- [ ] **Step 2: edit-live factory** — `user_policy_oidc_signin_service_factory.cc:25-34` 的 `GetCloudPolicyManager` 帮助函数改为单一 `return profile->GetProfileCloudPolicyManager();`(`grep -n` 定位)。
- [ ] **Step 3: 生成 2 patch + revert + apply**(按工作流铁律)。Expected `overlay applied.`
- [ ] **Step 4: 构建** `autoninja -C out/mac/arm64/dev chrome` → `The build has finished successfully.`
- [ ] **Step 5: 加深冒烟(评审 I1)** — 全新临时 profile 启动 `chrome://policy` 正常、无崩;**并**逐一确认 4 处 `GetUserCloudPolicyManager()` 调用点(`user_policy_oidc_signin_service.cc:315` dasher 分支、`factory.cc:33`、`turn_sync_on_helper_policy_fetch_tracker.cc:82`、`dependency_factory_impl.cc:21`)在 dasherless/禁 GAIA 路径下不可达或有 null 防护;若构建里能触到任一 GAIA 登录入口,确认不崩(DCHECK/no-op 即可)。
  **fallback**:若某裸解引用崩 → 在该处加 `if (!m) return;` 守卫,重建。
- [ ] **Step 6: Commit** `feat(enrollment-lock): global ProfileCloudPolicyManager (dasherless-only)`。

## Task 2: Spike B — picker provider 能否承载 OP 多主机登录链(最高风险 go/no-go,临时代码不提交)

- [ ] **Step 1: 起服务端栈** — fairyland dev 栈 + seed 租户 dadou + 手机号测试用户,`https://enroll.teleport.fairyland.io/enroll` 可达。
- [ ] **Step 2: 临时开 force-signin + 临时托管 enroll(评审 C1)** — **临时** patch `profiles_state.cc:85` 默认改 true(spike 后 revert);临时改 reauth provider 的托管 URL 为 `teleport::EnterpriseEnrollUrl()`、在目标 profile WebContents `ShowScreen`、**不**装 WebContentsDelegate(模拟我们的 provider)。临时在 throttle 加日志。
- [ ] **Step 3: 真机走链 + 观测(评审 C3')** — 锁定 profile 进 picker → 加载 enroll → 手机号登录,观测:① 多主机重定向链(enroll→OP→accounts→回跳)是否走完、还是某步因 `window.open`/弹窗被丢弃卡死;② **OP 链每一个主机是否都在 `.fairyland.io` 下**(若有 apex 外主机 → Layer 2 throttle 会拦,记录);③ throttle 是否捕获 `X-Profile-Registration-Payload`;④ 该 profile cookie jar 是否落 OP 会话(`chrome://settings/cookies` 查 `dadou.fairyland.io`)。
- [ ] **Step 4: 判定 go/no-go**
  - **GO**:链路走通 + 全主机在域内 + throttle 捕获 + OP cookie 在该 profile。
  - **NO-GO(弹窗依赖 / delegate 缺失卡死)**:fallback ①给 provider 装受控 `WebContentsDelegate`(放行同源/纳管域 `OpenURLFromTab`/`AddNewContents`,转同窗导航);若仍不行 ②改 `TYPE_POPUP` Browser 宿主(真 Browser、自带 delegate;须评估:Ctrl+N 逃逸 → 禁 `IDC_NEW_WINDOW`/`IDC_NEW_TAB`、popup 与 picker 共存、关闭后 re-gate),回 spec 重估。
  - **NO-GO(有 apex 外主机被 Layer 2 拦)**:在 `TeleportEnrollmentGateThrottle` 加「纳管 step 的 WebContents 豁免」(经 WebContents UserData 标记),纳入 Task 7。
- [ ] **Step 5: revert 所有临时改动**(含 profiles_state 临时 patch),结论记入分支 commit msg / spec 附注。**不提交临时代码。**

## Task 3: Spike C — 就地注册三层端到端(用 stub token,不依赖真实登录,评审 I5)

- [ ] **Step 1: 临时注入** — 在 throttle `MaybeIntercept` 前临时插一段:命中特定 URL 参数时,用**上游 stub** feature params(`kOidcAuthStubDmToken`/`kOidcAuthStubProfileId`/`kOidcAuthStubClientId`,`profile_management_features.cc`)或硬编码 mock token,对**当前 profile** 按「就地注册三层」顺序调用(严格 SetDasherlessManagement(true)+token 先于 FetchPolicyForOidcUser)。
- [ ] **Step 2: 真机验证** — `register_profile` 200(device-manager 日志,或 stub 短路)、`GetProfileManagementId()` 写、当前 profile `GetProfileCloudPolicyManager()->core()->store()->has_policy()` 翻真(临时日志)。
- [ ] **Step 3: 判定** GO/NO-GO(NO-GO:记录是否仍走 dasher 分支/bad-cast)。
- [ ] **Step 4: revert 临时代码,记录结论。不提交。**

> **三个 spike 任一 NO-GO → 停下回报,按 fallback 重估,不硬推 Phase 1。**

---

# Phase 1 — 撤 Path A + 谓词/组件(force-signin 仍关,浏览器全程可正常用)

## Task 4: 撤 Path A 启动导向(评审 M1,早删)

**Files:** Delete `patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch`

- [ ] **Step 1** `git rm` 该 patch;`apply_patches.py` + `autoninja chrome` 确认无残留依赖。Layer 2 throttle/pref/谓词保留。
- [ ] **Step 2: Commit** `chore(enrollment-lock): drop Path A startup redirect (superseded)`。

## Task 5: `ShouldLockProfile` + 锁豁免 patch + profile_util_impl dep(评审 C3)

**Files:** Create `src/browser/enterprise/teleport_enrollment_lock.{h,cc}`;`patches/chrome/browser/BUILD.gn.patch`(扩展)、`patches/chrome/browser/profiles/BUILD.gn.patch`(new)、`patches/chrome/browser/profiles/profile_attributes_entry.cc.patch`(new)

- [ ] **Step 1: 头** `teleport_enrollment_lock.h`:fwd-decl `class ProfileAttributesEntry;`,声明 `bool teleport::ShouldLockProfile(ProfileAttributesEntry* entry);`(注释:受门禁 + `GetProfileManagementId().empty()`,keyed on management id 非 `CanBeManaged()`)。
- [ ] **Step 2: 实现** `teleport_enrollment_lock.cc`:`if (!entry || !entry->GetProfileManagementId().empty()) return false; PrefService* ls = g_browser_process->local_state(); return ls && ls->GetBoolean(prefs::kRequireEnrollmentToBrowse);`(include `teleport/common/teleport_pref_names.h`、`chrome/browser/browser_process.h`、`components/prefs/pref_service.h`、`chrome/browser/profiles/profile_attributes_entry.h`)。
- [ ] **Step 3: BUILD.gn 两处** — 扩展 `chrome/browser/BUILD.gn.patch` 加 `//teleport/browser/enterprise/teleport_enrollment_lock.{cc,h}` 进 `static_library("browser")` sources;**新增** `patches/chrome/browser/profiles/BUILD.gn.patch` 给 `source_set("profile_util_impl")`(`chrome/browser/profiles/BUILD.gn:259`)的 `deps` 加 `"//teleport"`(无环:`//teleport` deps 不触 profile_util_impl)。
- [ ] **Step 4: edit-live profile_attributes_entry.cc** — `:195-197` 内层 `if` 末加 `&& teleport::ShouldLockProfile(this)`(include teleport 头)。生成 patch。
- [ ] **Step 5: apply + 构建过**(force-signin 仍关 → 不锁任何 profile,仅验证编译/链接通过、无 GN 环)。
- [ ] **Step 6: Commit** `feat(enrollment-lock): ShouldLockProfile exemption predicate + profile_util_impl dep`。

## Task 6: 无 GAIA Teleport step/provider(评审 I2:接 done_cb)

**Files:** Create `src/browser/enterprise/teleport_enrollment_step.{h,cc}`;扩展 `chrome/browser/BUILD.gn.patch`

- [ ] **Step 1: 读范式** `profile_picker_flow_controller.cc:280-323` + `profile_picker_reauth_provider.{h,cc}`。
- [ ] **Step 2: 写 step/provider** — 持目标 `Profile*`;`Show()` 在目标 profile 上 `WebContents::Create(CreateParams(profile))`(同 reauth `:91`)+ `host_->ShowScreen(contents, GURL(EnterpriseEnrollUrl()), ...)`;**无任何 gaia/email DCHECK / 无 ForceSigninVerifier / 无 DiceTabHelper**。**完成信号 = 直接 callback 注入**(评审 I2):step 在 `Show()` 时把一个 `base::OnceClosure on_enrolled`(其体为「照搬 `OnReauthCompleted`:`entry->LockForceSigninProfile(false)` + `FinishFlowAndRunInBrowser(profile,{})`」)经 **WebContents UserData**(`teleport::EnrollmentDoneUserData`,持 `base::OnceClosure`)挂到 provider 的 WebContents 上,供 throttle(Task 8/9)查取。若 Spike B 需 delegate fallback,在此给 provider 装受控 delegate。
- [ ] **Step 3: BUILD.gn patch sources + 构建过。**
- [ ] **Step 4: Commit** `feat(enrollment-lock): GAIA-free enrollment step/provider with done-callback UserData`。

---

# Phase 2 — 就地注册器 + token 改投(force-signin 仍关)

## Task 7: 就地注册器(评审 I3 可注入、I6 全参)

**Files:** Create `src/browser/enterprise/teleport_oidc_inplace_registrar.{h,cc}` + `_unittest.cc`;扩展 `chrome/browser/BUILD.gn.patch`

- [ ] **Step 1: 读底层** `oidc_authentication_signin_interceptor.cc:297-360`/`:595-623`、`user_policy_oidc_signin_service.cc:182`。
- [ ] **Step 2: 写编排器(可注入协作者)** — `EnrollCurrentProfileInPlace(Profile*, ProfileManagementOidcTokens, issuer, subject, email, base::OnceClosure done, Collaborators*)`:`Collaborators` 是个可注入接口(默认实现包真 `CloudPolicyClientRegistrationHelper` / 属性 setter / `FetchPolicyForOidcUser`),便于单测验顺序。流程:① 注册(仿 interceptor:336);② 回调里**先**写 `SetDasherlessManagement(true)`+`SetProfileManagementOidcTokens`+`SetProfileManagementId`+recovery prefs,**再** `ResetGaiaPolicyManagement()` + `FetchPolicyForOidcUser(AccountId(), dm_token, client_id, email, base::TimeTicks::Now(), /*switch_to_entry=*/false, profile->GetDefaultStoragePartition()->GetURLLoaderFactoryForBrowserProcess(), ...)`(全 8 参);③ `has_policy()` 翻真 → `std::move(done).Run()`。
- [ ] **Step 3: 单测** `_unittest.cc` 以 fake `Collaborators` 断言**调用顺序**(SetDasherlessManagement+token 必在 FetchPolicy 之前)。(可注入设计使此单测可行,不降级。)
- [ ] **Step 4: BUILD.gn patch + 构建 + 跑单测过。**
- [ ] **Step 5: Commit** `feat(enrollment-lock): in-place OIDC registrar (injectable, ordering-tested)`。

## Task 8: throttle token 改投 → 注册器 → done_cb

**Files:** 扩展 `patches/.../oidc_auth_response_capture_navigation_throttle.cc.patch`

- [ ] **Step 1: edit-live throttle** — `:398` 与 `:494` 调 `MaybeInterceptOidcAuthentication` 前判:`teleport::ShouldGateProfile(profile) && !teleport::IsEnrolled(profile)`(profile 取自 `GetWebContents()->GetBrowserContext()`)时,从该 WebContents 的 `EnrollmentDoneUserData` 取 `on_enrolled` closure,调 `teleport::EnrollCurrentProfileInPlace(profile, tokens/payload..., std::move(on_enrolled))`,**不**调拦截器;否则原逻辑。
- [ ] **Step 2: 重生扩展 patch + apply + 构建过。**
- [ ] **Step 3: Commit** `feat(enrollment-lock): reroute captured OIDC tokens to in-place registrar`。

---

# Phase 3 — picker 接入 + 解锁(force-signin 仍关;末端开)

## Task 9: 把 step 接进 picker(评审 C2 异步 load)+ Layer 2 豁免(评审 C3')

**Files:** `patches/.../profile_picker.{h,cc}.patch`、`patches/.../profile_picker_flow_controller.{h,cc}.patch`、`patches/.../profile_picker_handler.cc.patch`(均 new);若 Spike B 判定需要,扩展 `teleport_enrollment_gate_throttle` 豁免

- [ ] **Step 1: `SwitchToEnrollment` 入口** — edit-live `profile_picker.{h,cc}` 仿 `SwitchToReauth` 加 `static void SwitchToEnrollment(Profile* target)`;`profile_picker_flow_controller.{h,cc}` 加方法,注册 Teleport step(仿 `SwitchToReauth`→`CreateReauthtep`)。
- [ ] **Step 2: handler 异步分支(C2)** — edit-live `profile_picker_handler.cc:TryLaunchLockedProfile`,在 reauth `if` 之后、`GetActiveTime().is_null()` fresh 分支(`:426`)之前插:
  ```cpp
    // teleport: gated-unenrolled profiles enroll via our OIDC step, not GAIA.
    if (teleport::ShouldLockProfile(&entry)) {
      g_browser_process->profile_manager()->LoadProfileByPath(
          entry.GetPath(), /*incognito=*/false,
          base::BindOnce(&ProfilePickerHandler::OnProfileLoadedForSwitchToEnrollment,
                         weak_factory_.GetWeakPtr()));
      return;
    }
  ```
  并加 `OnProfileLoadedForSwitchToEnrollment(Profile* profile)`:`if (profile) ProfilePicker::SwitchToEnrollment(profile);`(仿 reauth 的 `OnProfileLoadedForSwitchToReauth` `:453`)。
- [ ] **Step 3: Layer 2 豁免(若 Spike B 需)** — 据 Spike B 结论:若 OP 链有 apex 外主机,给 `TeleportEnrollmentGateThrottle` 加判:WebContents 带 `EnrollmentDoneUserData` 时一律 PROCEED(纳管 step 上下文放行)。
- [ ] **Step 4: 各 patch + apply + 构建过**(force-signin 仍关 → 此分支暂不触发,仅验编译)。
- [ ] **Step 5: Commit** `feat(enrollment-lock): route locked-unenrolled profiles to the Teleport enrollment step (async load)`。

## Task 10: 末端开启全局 force-signin + 全链冒烟 + OP 会话验证(评审 C1/I3)

**Files:** `patches/chrome/browser/profiles/profiles_state.cc.patch`(new)

- [ ] **Step 1: edit-live profiles_state.cc:85** — `RegisterBooleanPref(prefs::kForceBrowserSignin, true)`(默认 true)。生成 patch。
- [ ] **Step 2: apply + 构建 + 全链真机(需服务端栈)** — 全新 profile 启动 → picker → **Teleport enroll 页**(无外壳、无 Ctrl+N 逃逸)→ 手机号登录 → throttle 改投 → 就地注册 → `has_policy` 翻真 → done_cb → 解锁 → 开正常浏览器。
- [ ] **Step 3: OP 会话原地验证(评审 I3,提前到此)** — 解锁后正常浏览器里 `chrome://settings/cookies` 查 `dadou.fairyland.io` session cookie **存在**;访问一个搭便车 SSO 页能免登。
- [ ] **Step 4: 重锁不变式** — 重启浏览器:已纳管 profile **不**被重锁(豁免生效)、直接开正常浏览器;`RequireEnrollmentToBrowse=false` 下发后未纳管 profile 也不锁。
- [ ] **Step 5: Commit** `feat(enrollment-lock): enable global force-signin (gate now fully wired)`。

---

# Phase 4 — 验收

## Task 11: 全量构建 + 端到端 + 副作用核对

- [ ] **Step 1: 全 patch + 全单测** `apply_patches.py` + `autoninja teleport_unittests` + 跑(全过;pytest 6 branding 失败为 main 既有、无关)。
- [ ] **Step 2: 端到端(spec §10)** 复跑 Task 10 全链;另核 **force-signin 副作用**(评审覆盖缺口):guest 模式已禁是否符合预期、picker 启动必经无异常;`chrome://policy` 正确、无 Google 穿帮。
- [ ] **Step 3: 记录结果,据效果定下一步**(多 profile / 添加-profile / 真正 reauth 为后续)。

---

## Self-Review(对照 spec rev4 + 两轮评审)

- **时序炸砖(评审 C1)**:force-signin 移到 **Task 10 末端**,Path A 撤到 **Task 4**;Task 1–9 全程 force-signin 关、浏览器正常可测 ✓。
- **C2 异步 load**:Task 9 Step 2 给出 `LoadProfileByPath` + `OnProfileLoadedForSwitchToEnrollment` ✓。
- **C3 分层**:Task 5 Step 3 新增 `profiles/BUILD.gn.patch` 给 profile_util_impl 加 `//teleport` dep ✓。
- **C3' Layer 2 × picker**:Spike B Step 3 验证 OP 链主机域覆盖 + Task 9 Step 3 豁免 ✓。
- **I1 force-signin 开法**:`profiles_state.cc:85` 默认 true(非 browser_prefs)+ guest 副作用核对(Task 11)✓。
- **I2 完成信号**:直接 callback 注入(`EnrollmentDoneUserData` 挂 WebContents,throttle 查取)✓。
- **I6 全参**:Task 7 Step 2 FetchPolicyForOidcUser 8 参齐 ✓。
- **I3 单测**:registrar 可注入协作者 → 顺序单测可行不降级 ✓。
- **I4 patch 累积**:全局工作流铁律明写「在已 apply 的 live 树上叠加再 diff」✓。
- **spike**:Spike B 用临时 profiles_state patch(非不存在的 flag);Spike C 用 `kOidcAuthStubDmToken` stub ✓。
- **OP 会话不变式**:Task 10 Step 3 提前验证(非等 Task 12)✓。
- **占位符扫描**:无 TODO/TBD;原「调研 force-signin」「取实际句柄」「或回调或 observer」「降级 e2e」软点均已拍板具体化。
- **命名一致**:`ShouldLockProfile`/`EnrollCurrentProfileInPlace`/`SwitchToEnrollment`/`OnProfileLoadedForSwitchToEnrollment`/`EnrollmentDoneUserData`/`teleport_enrollment_lock`/`teleport_oidc_inplace_registrar`/`teleport_enrollment_step` 全程一致。

> **执行铁律**:Phase 0 三 spike 是 go/no-go 闸;任一 NO-GO 不得硬推,按 fallback 重估(尤其 Spike B 失败 → provider 装 delegate 或改 TYPE_POPUP 宿主,回 spec)。force-signin 仅在 Task 10 才全局开。
