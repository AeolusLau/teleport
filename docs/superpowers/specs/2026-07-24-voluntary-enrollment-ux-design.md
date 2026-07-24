# 自愿纳管形态与 picker 强制纳管修复(voluntary-enrollment-ux)设计

- 日期:2026-07-24(v2,已吸收六路对抗性评审修订)
- 状态:评审修订完成,待产品负责人复核
- 范围:纯客户端(teleport 仓);fairyland 零改动(仅 runbook 补充披露文案要求,见 §5.4)
- 前置事实来源:commit `1adc884`(Layer 1 picker 强制纳管)、commit `dfef774`(deployment-domain,删除 `profiles_state.cc.patch`)、`docs/superpowers/plans/2026-06-15-enterprise-enrollment-lock-gate.md`
- 评审基线:六个独立对抗性子代理对照 M148 检出全量实证(force-signin 27 调用点 / picker 创建链 / 菜单渲染约束 / guest 与启动路径 / GAIA 暴露面 / 死代码清查),下文所有 file:line 断言均已核对

## 1. 背景与问题(根因)

仓库先后存在两代「强制纳管」设计:

1. **Path A(第一代,tab 页方案)**:启动首 tab 指向 enroll 页(`patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch`)+ `TeleportEnrollmentGateThrottle` 把未纳管 profile 的一切 http(s) 主框架导航重定向到登录。
2. **Layer 1(第二代,picker 方案,commit `1adc884`)**:`kForceBrowserSignin` 默认 true → 未纳管 profile 启动即锁进 ProfilePicker,在 picker 内的 GAIA-free Teleport enrollment step(`ProfilePicker::SwitchToEnrollment`)就地完成 OIDC 纳管后解锁。同 commit 禁用 guest(OTR 不受 gate 管,开着即绕过洞)与「添加 profile」。Path A 的启动重定向 patch 物理保留但成为死路径。

commit `dfef774` 为了让 BYOD 用户在纳管前能打开浏览器访问 `teleport://enroll` 设置部署域,删除了 `profiles_state.cc.patch`(force-signin / guest / add-person 三个默认一起回到上游),但:

- `kRequireEnrollmentToBrowse` 仍默认 true → 「取消强制登录」实际未发生;
- 锁没了 → Layer 1 picker enrollment 全套机器成死代码(`ShouldLockProfile` 仅在锁定分支被查询);
- Path A 启动重定向僵尸复活 → 强制表现回退为 tab 页形态;
- 未提供任何自愿登录入口。**评审实证的「今天菜单无入口」根因链**:本构建未烘焙 Google OAuth client key → `CanEnableDiceForBuild()` 恒 false(`account_consistency_mode_manager.cc:66-80`)→ 每次启动 `kSigninAllowed` 被强制写 false(`:125-134`)→ `CanOfferSignin` 失败 → 上游 GAIA 按钮不渲染。即 GAIA 被挡是「无 key」的涌现副作用,不是设计保证(见 §4.8);
- guest 默认重新开启 → gate 绕过洞回归。

该删除不在 deployment-domain 任何 spec 中,属实现期未经设计的顺手改动。

## 2. 目标 / 非目标

**目标**

- G1:`RequireEnrollmentToBrowse` 成为「强制纳管」唯一开关,默认 **false**(BYOD-first,产品负责人已确认翻转当初 secure default)。
- G2:gate ON 时,强制纳管回到 **picker 内完成**:未纳管 profile(含新建)锁进 picker,走 enrollment step 完成才可用;新建中途**取消删除半成品**(失败可就地重试,见 §4.6)。
- G3:gate OFF 时,profile 可跳过登录正常创建、正常浏览;未纳管 profile 在 **profile 菜单顶部有常驻「登录」入口**,点击在当前窗口新 tab 打开 `EnterpriseEnrollUrl()`,经 OIDC capture 链路**就地**纳管为受管 profile(绝不落入上游「新建 work profile」interceptor,见 §4.7)。
- G4:移除 Path A 启动重定向 patch;throttle 保留为 gate ON 的纵深兜底(明确:**只覆盖 http(s) 主框架导航;启动期的可靠边界是 force-signin 锁**,评审已实证 `--profile-directory`/`--app`/session-restore/关 picker 策略等旁路全部被上游 `IsSigninRequired` 锁检查兜住)。
- G5:guest 可用性与 gate 动态耦合(gate ON ⇒ guest 禁用;这是对 Chrome force-signin 行为的**有意加强**——上游 force-signin 并不自动禁 guest)。
- G6:已纳管 profile 菜单顶部显示「由 <机构> 管理」header;GAIA 登录/同步 UI 在所有表面**结构性**抑制(§4.8),不再依赖「无 key」的偶然性。

**非目标**

- 企业**下发** gate 开关的通道(MDM forced pref / 机器配置文件字段 / CBCM 云策略映射)本期不做,记 TD;dev 验证经 local_state 手改或测试钩子。
- BYOD「先设域后登录」引导:菜单登录按钮始终指向当前已解析的 D,不做 SaaS/私有化分流。
- 服务端改动:无(fairyland 侧仅在私有化 runbook 补一条 enroll 页披露文案要求,§5.4)。

## 3. 行为矩阵

| 场景 | gate OFF(默认) | gate ON(企业开启) |
|---|---|---|
| 首个 profile 启动 | 正常窗口,NTP,不弹登录(FRE 因 signin 禁用自动跳过,评审 A7 实证) | force-signin 锁 → picker → enrollment step,完成才有窗口(冷启动即锁,入冒烟) |
| picker 新建 profile | 上游本地创建(本构建无 GAIA 面,§4.8 后为结构保证) | 隐藏式创建即进 enrollment step;**取消→删除半成品;失败→错误页可重试**(§4.6) |
| 未纳管浏览 | 完全正常 | 锁定态到不了导航层;throttle 兜底(仅 http(s) 主框架) |
| 自愿登录入口 | 菜单顶部「登录」按钮 → 新 tab `enroll/start` → OIDC → **就地**纳管(不新建 profile、无上游对话框) | 不适用(锁定态无浏览器菜单) |
| Guest | 上游默认(可用) | 动态禁用(谓词两点 + 动作层守卫,§4.4) |
| 已纳管菜单 | 「由 <机构> 管理」header(点击进 chrome://management),无登录按钮 | 同左 |
| GAIA 登录/同步 UI | 结构性恒抑制(§4.8) | 同左 |

## 4. 机制设计

### 4.1 默认翻转 + 会话冻结谓词

- `RegisterEnrollmentGateLocalStatePrefs`:`kRequireEnrollmentToBrowse` 默认 `true → false`。
- 新增谓词 `teleport::RequireEnrollmentGateEnabled()`:**首次成功读取后会话内冻结**(镜像上游 `IsForceSigninEnabled` 的进程级缓存;`BrowserSignin` 策略本身 `dynamic_refresh: false`)。评审实证多处上游调用点以 CHECK/DCHECK 断言会话内恒定(`profile_picker_view.cc:495`、`profile_picker_handler.cc:395`、`profile_attributes_entry.cc:766`),活读 pref 中途翻转会崩。实现形态(照评审给定):
  - `g_browser_process`/local_state 为空 → 返回 false **且不缓存**(fail-open);
  - `FindPreference` 未注册 → 返回 false 且不缓存(防上游 `GetBoolean` 对未注册 pref 的 release CHECK);
  - 读到值即缓存,配 `ResetRequireEnrollmentGateForTesting()`。
- `ShouldGateProfile` / `ShouldLockProfile` / §4.4 guest 谓词 / §4.2 signin_util 全部收口消费同一快照,消除多读点漂移(现状 gate.cc 有两处内联 GetBoolean)。
- 已知不变式(写入实现注释):叠加后 `IsForceSigninEnabled()` 的取值依赖 gate 快照;`ProfileAttributesEntry::Initialize` 等一次性决策点必须晚于 local_state 就绪(M148 成立,评审已核;冒烟矩阵加「gate ON 冷启动即锁」断言兜底)。
- 谓词本体编进 chrome/browser(`teleport_unittests` 链接不到);**可 gtest 的纯决策逻辑放 `src/common`**(如 `ShouldShowTeleportSigninEntry(is_enrolled, is_regular_profile, is_web_app)`),UI/进程侧只留薄 seam。

### 4.2 force-signin 动态耦合

- patch `chrome/browser/signin/signin_util.cc::IsForceSigninEnabled()`:保持上游缓存结构原样,仅在出口 `return 上游缓存 == ENABLE || teleport::RequireEnrollmentGateEnabled();`。**禁止**把 OR 烘进 `SetForceSigninPolicy` 缓存(污染测试 setter 语义)。
- **`BrowserSignin` 策略去 GAIA 化**:patch `BrowserSigninPolicyHandler` 的 `kForced` case 不再设置 `kForceBrowserSignin`(降级为 Enable 语义)。理由(评审发现 3):本产品无 GAIA,上游策略单独强制时会把用户锁进不可完成的 GAIA 登录死路(picker 的 teleport 分支以 gate 为键,策略-only 锁定会落进 fresh-signin/ReauthNotAllowed 分支)。gate pref 由此成为强制登录**唯一**来源;上游缓存值理论上恒 false,OR 仅为保守保留。
- Layer 1 配套 patch 全部继续生效且重新可达:`profile_attributes_entry.cc`(锁 + **已纳管 dasherless 主动解锁豁免**——评审确认该豁免是「已纳管 profile 永不被锁死」的关键依赖,必须保留)、`profile_picker_handler.cc`、flow controller 系列。
- 评审已全量核对 27 个 `IsForceSigninEnabled` 调用点在 gate OFF / ON+未纳管 / ON+已纳管三态的行为:锁建立/豁免、启动路由、picker 路由、签出/删除(上游 ephemeral/删除语义对已纳管与初始 profile 零威胁)、ForceSigninVerifier(dasherless 无 primary account → fetcher 永不创建、零 Google 网络调用)、macOS 特有路径(Dock 重开/安全 profile 选择)全部成立。plan 期不必重复核对,引用评审报告即可。

### 4.3 Path A 清除

- 删除 `patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch`。评审实证删除安全:gate ON 锁定态下 `GetStartupProfile`(`startup_browser_creator.cc:1717`)的 `IsSigninRequired` 检查兜住全部旁路(`--profile-directory`、`--app`/app shim、`kBrowserShowProfilePickerOnStartup=false`、session restore),必然落 picker。
- `TeleportEnrollmentGateThrottle` 保留,但其角色**限定**为:gate ON 的 http(s) 主框架导航兜底 + allow-hosts 注入 + 迁移检测触发点之一。gate ON 的正确性依赖锁,不依赖 throttle。

### 4.4 guest 动态禁用(两谓词点 + 动作层守卫)

评审证伪了「单一收口点」假设,修正为四处(同文件两 patch + 两守卫):

1. `profiles_state.cc::IsGuestModeGloballyDisabledInternal()`(覆盖 `IsGuestModeEnabled` 两个重载的全部 UI 入口:profile 菜单、app 菜单、picker WebUI、mac 控制器);
2. `profiles_state.cc::IsGuestModeRequested()`(覆盖 `--guest` 命令行与 `BrowserGuestModeEnforced` 策略路径——否则 gate ON 下一条 `--guest` 即得无策略会话);
3. fail-closed 动作守卫:`profiles::SwitchToGuestProfile`(`profile_window.cc`)入口 `if (!profiles::IsGuestModeEnabled()) return;`(IDC 命令无条件 enabled,上游只靠隐藏按钮);
4. 同守卫加在 `ProfilePickerHandler::HandleLaunchGuestProfile`(上游自带 TODO 承认无服务端校验)。

已知限制(记 TD):gate ON 动态禁用时 `chrome://settings` 的 guest 开关回显仍是上游 pref 值(enabled),显示与行为 desync;彻底一致需 settings 数据源接谓词。

### 4.5 profile 菜单登录入口(核心新增 UI)

扩展 `patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch`,改 `GetIdentitySectionParams`:

- **分支位置与顺序**(评审 F6/F10):teleport 分支插在上游 **web-app early-return 之后**(PWA 窗口菜单不出登录按钮);置于现有 dasherless subtitle 抑制 hunk **之前**(dasherless hunk 降级为兜底),使「dasherless 但 `IsEnrolled()==false`」中间态(store 未载/策略被撤/迁移后)落进「未纳管→登录按钮」分支(行为=引导重纳管,正确)。
- **未纳管**(`ShouldShowTeleportSigninEntry` 为真):
  - `button_text` = 品牌串「登录」族 + **`subtitle` 必须同时提供**(评审 blocker:`SetProfileIdentityWithCallToAction` 硬性 CHECK「有 button 必有 subtitle」,`profile_menu_view_base.cc:533-535`),subtitle 文案如「登录后由你的组织统一管理」;
  - `button_action` → 关闭菜单后 `NavigateParams(profile, EnterpriseEnrollUrl(), PAGE_TRANSITION_LINK) + NEW_FOREGROUND_TAB`(照抄上游 `NavigateToGoogleAccountPage` 范式);
  - 结构上跳过上游 `CanOfferSignin` GAIA 按钮逻辑。
- **已纳管**:
  - `header_string` = 「由 <机构> 管理」,机构名**首选 `GetAccountManagerIdentity(profile)`**(= PolicyData.managed_by,与 ⋮ 菜单「Managed by」项和 chrome://management 副标题同源,三表面一致;评审 B4),为空(策略未到)回退 `prefs::kEnrolledDeploymentDomain`;**不用**实时 `DeploymentDomain()`(换域窗口期错位);
  - **`header_image` 必须同时提供**(评审 major:string+image 同非空才渲染,`profile_menu_view_base.cc:473`):`ui::ImageModel::FromVectorIcon(GetManagedUiIcon(&profile()), ui::kColorIcon)`;
  - `header_action` 复用上游 `OnProfileManagementButtonClicked`(`IDC_SHOW_MANAGEMENT_PAGE` → chrome://management,零新代码);
  - 不显示登录按钮。不依赖 `CanShowEnterpriseBadgingForMenu`(评审确认其对 dasherless 恒 false,且**不得**改走「注册器置 `UserAcceptedAccountManagement`」路线——血域太大);自填 header 无双渲染风险(评审已核唯一写点)。
- **feature 区同 patch 内一并抑制**(评审 major):`MaybeBuildChromeAccountSettingsButtonWithSync` 的 `!kSigninAllowed` 触发臂对 teleport profile 加 guard——否则两态菜单都常驻「Google services settings」行。
- **身份呈现补齐**(评审 B5):in-place registrar 成功路径顺手写 `enterprise_signin::prefs::kProfileUserDisplayName / kProfileUserEmail`(数据已在手)——否则已纳管菜单 a11y 标题落到「未登录」串;device-signals 同意位记 TD。
- **新增品牌串落地路径**(评审 F8,产品负责人已定:正规 i18n):新 IDS message **英文源文本**进对应 grd(patch),**zh-CN 翻译**进对应 `.xtb`(patch);xtb entry id 为 grit 内容哈希,**复用/扩展 `branding_strings.py` 既有哈希机器**生成并以 pytest 校验;`apply_patches.py` 幂等覆盖两类 patch。
- 菜单每次打开全新构建(`profile_menu_coordinator.cc:99-104`),enrollment 完成后下次打开即切态,无需通知机制(评审已核)。

### 4.6 gate ON 的 picker 新建 profile(评审重写:两条原路线均不可行,采合并机制)

评审实证:「复用上游 force-signin 创建路径」不可行(该路径是 GAIA 专用管道,step 一开始就加载 accounts.google.com,且被我们 throttle 重导成僵尸流);「本地创建→锁定路由」也不可行(`ShouldLockProfile` 是谓词非动作;隐藏 profile 无 tile,锁定路由不可达)。**定案实现**:

1. `HandleSelectNewAccount` teleport 分支(gate ON):`ProfileManager::CreateMultiProfileAsync(..., is_hidden=true)`(复用上游 ephemeral+omitted 语义;创建即被现有 `profile_attributes_entry.cc.patch` 自动上锁)→ init 回调里 `ProfilePicker::SwitchToEnrollment(new_profile)`(现有 step 复用;`DCHECK_EQ(Step::kProfilePicker, current_step())` 在此成立)。
2. **成功 → teleport 自写 finalize**(评审 blocker:缺此步则新 profile 保持 ephemeral,**下次启动被 `CleanUpEphemeralProfiles` 静默删除**):`entry->IsOmitted()` 即「picker 新增」判据 → `SetLocalProfileName(ChooseNameForNewProfile())` + `SetIsOmitted(false)` + `SetIsEphemeral(false)`(尊重 `kForceEphemeralProfiles`,镜像 `profile_customization_util.cc:75-80`)→ 解锁 → `FinishFlowAndRunInBrowser`。**禁止调用上游 `FinalizeNewProfileSetup`**(对 dasherless 在 force-signin 下必命中 `CHECK(HasPrimaryAccount)`)。
3. **取消(用户返回)→ 删除**:自定义 pop 闭包 = 先 `SwitchToStep(kProfilePicker)` **再** `UnregisterStep(kTeleportEnrollment)`(注意 `CHECK_NE` 先切后删;模式同上游 `HandleSignInCompleted`)→ 释放 provider keepalive → ephemeral 语义自动删目录。**失败 ≠ 取消**:失败走现有错误页+就地重试 UX,仅显式返回才删。
4. **首 profile 天然豁免**:非 ephemeral/非 omitted,`RemoveKeepAlive` 不调度删除——留 tile 语义由 ephemeral 位隔离,无需显式分支(评审 F7 确认两重区分点足够)。
5. **在途竞态防护**(评审 F9):registrar 终态回调前检查 profile 是否已调度删除(`IsProfileDirectoryMarkedForDeletion`)或 entry 仍 omitted——是则跳过 `PersistEnrolledDomain` 并 LOG(服务端孤儿注册记录记为已知残余,与机器 DM token 清理同池);退出进程杀死在途 enrollment,由 ephemeral 下次启动清扫兜底(可接受,记入注释)。
6. 设计注记(堵未来重复质疑):不采用上游 OIDC interceptor 的「先注册后建 profile」次序,因 OIDC web 流的 cookie/state 必须落在目标 profile 内(Layer-1 定案的必然代价即删除机器)。
7. gate OFF:完全上游行为=纯本地创建(本构建无 GAIA 面;§4.8 后为结构保证)。
8. 同步重写 `HandleSelectNewAccount` patch 的失实注释(「add-person 默认 false 挡 tile」「GAIA 创建 CHECK-fail」均不成立,真实根据=GAIA 被 gate 重导不可达 + finalize 阶段 dasherless CHECK + DoNothing 僵尸流)。

### 4.7 OIDC capture 改道谓词与 gate 解耦(评审 blocker,新增)

现状 `oidc_auth_response_capture_navigation_throttle.cc.patch` 两处改道点(URL 路径 + header 路径)的条件是 `ShouldGateProfile(profile) && !IsEnrolled(profile)`——gate 默认 OFF 后,**自愿登录会落回上游 `OidcAuthenticationSigninInterceptor`**(Browser 锚定确认对话框 + 新建 work profile),G3 整条失效。修正:

- 改道谓词与 gate 解耦:teleport 构建内,凡命中我们的 register-handler capture(D 域内 `EnterpriseRegisterHandlerUrl()`)一律走就地纳管(条件仅 `!IsEnrolled(profile)`),上游「新建 work profile」interceptor 在本产品视为不可达死代码;
- **自愿 tab 流在注册前复用上游披露对话框**(产品负责人已定,§5.4):capture 后、`EnrollCurrentProfileInPlace` 前,经上游 `WebSigninInterceptor` 气泡机器(kEnterpriseOIDC 样式,`show_managed_disclaimer`,Browser 锚定——自愿流必有 Browser)弹「你的组织将管理此 profile」确认;接受 → 就地纳管;拒绝 → 不纳管、停留原页。账号信息取 OIDC payload(上游 dasherless 分支同源,不依赖 GAIA);气泡文案上游语义为「继续到新工作 profile」,经 grd/xtb 覆写为就地纳管措辞(plan 期核对可覆写面;若发现气泡机器对 IdentityManager 有无法绕开的硬依赖,回退方案=服务端 enroll 页披露 + 记 TD,连同证据回报)。picker 强制流免此对话框(无 Browser 可锚定——这正是 Layer-1 当年绕开它的唯一真实原因;强制流的披露由 picker 内 enroll 页承载);
- **自愿 tab 流的终态反馈**(评审缺口):tab 流无 `EnrollmentDoneUserData`(`Take()` 返回 DoNothing)→ registrar 失败时用户零反馈。capture patch 为 tab 流装显式 done 回调:失败 → 导航该 tab 至 enrollment 错误页(复用 picker 流的 `EnrollmentErrorUrl` 机制);成功 → tab 停留在服务端 continue/成功页(现有行为)。
- 同步更新该 patch 内「gated context」相关注释。

### 4.8 GAIA 结构性抑制(新增;上游复用哲学的双保险)

评审实证:今天全部 GAIA 表面(菜单按钮、设置 People 区登录行、picker GAIA 建号、FRE 登录屏、DICE web 拦截、头像 pill、书签/密码等 promo)之所以不出现,**全部悬挂在「构建无 OAuth key」这一偶然事实上**;未来任何构建为别的 Google 服务烘 key,它们会同一天全部复活,而我们只 patch 了菜单。修正:

- **patch `AccountConsistencyModeManager::CanEnableDiceForBuild()` 恒 return false**(一行):`kSigninAllowed` 恒 false、DICE=kDisabled 成为结构保证,上述所有表面一次钉死;
- 设置页 dasherless 残留(评审 A4,今天可见的垃圾 UX):已纳管后 People 区常驻「This account isn't associated with Google…」通知(`people_page.html:155-162`),与菜单 dasherless subtitle 同源同理——同策略抑制(隐藏或改「由组织管理,详见 chrome://management」文案);
- 记 TD(不阻断):settings「Sync and Google services」死行隐藏/改名;`chrome://signin-*` 等 WebUI 死壳从 teleport-urls 目录清理。
- 冒烟第 6 条从「菜单无 GAIA 按钮」扩为表面集断言(菜单两态、settings People、picker 建号、FRE、头像按钮)。

### 4.9 换域迁移触发面修复(评审 blocker/major,新增)

- **事实纠偏**:`MaybeHandleDomainMigration` 全仓唯一调用点是 gate throttle(`teleport_enrollment_gate_throttle.cc:105`);「enrollment 路径也调用」不实。`PendingDomainMigrationFrom()` 现为零调用死代码(chrome://version patch 内联重写了同逻辑)。
- **运行期半纳管窗口**(gate ON):迁移在运行时清 management id 后,锁只在 `Initialize()`(启动)时上,重启前该 profile「gate ON + 未纳管 + 已开窗」。修正:`MaybeHandleDomainMigration` 重置 enrollment 时,若 gate ON 则同步 `entry->LockForceSigninProfile(true)`(未来窗口/启动即锁);已开窗口的网页导航仍由 throttle 兜(http(s) 主框架),残余(已加载页面 + chrome:// 页)记为已知限制,窗口关闭策略记 TD。
- **无导航则无迁移**:换域后从不发起 http(s) 导航的用户(恢复的标签、纯 chrome:// 使用)迁移永不触发。修正:在 profile 加载路径挂启动期迁移检查(plan 期选点:profile attributes 初始化 patch 既有挂点或 `chrome_browser_main` teleport 钩子);`PendingDomainMigrationFrom()` 转正:chrome://version patch 改为调用它(消除逻辑重复,死代码得到唯一归宿),不再删除。

## 5. 边界与安全

1. **guest 洞**:§4.4 四点覆盖(谓词两点 + 动作层两守卫);`--guest` 进冒烟矩阵。
2. **锁与 throttle 的边界分工**:启动期正确性=force-signin 锁(上游 `IsSigninRequired` 全旁路兜底,评审实证);运行期兜底=throttle(仅 http(s) 主框架,chrome://、about: 放行是设计内让渡)。gate 中途翻 ON 不影响已开窗口,重启后生效(与上游 force-signin 策略一致)。
3. **ON→OFF 三态**(评审重写):(a) 未纳管被锁 profile:上游 `Initialize()` else 分支主动解锁 ✓;(b) 已纳管 dasherless profile:靠我们 `profile_attributes_entry.cc.patch` 的豁免分支「永不被锁」,ON/OFF 均无副作用 ✓(该豁免是关键依赖,列入回归保护);(c) 迁移运行期窗口:§4.9 的 re-lock 收口。
4. **受管披露时刻**(评审 B3,产品负责人复核后改为复用上游):**自愿 tab 流复用上游 OIDC interception 披露对话框**(§4.7)——Layer-1 绕开它的唯一原因是 picker 锁定流无 Browser 可锚定,该理由对自愿流不成立;picker 强制流维持免对话框(披露由 picker 内 enroll 页承载,亦写入 fairyland runbook)。
5. **GAIA 不变量**:构建永不配置 Google OAuth client;§4.8 的 DICE 钉死使其从「偶然」变「结构」。手动访问 accounts.google.com = 纯网站登录,零浏览器 UI 反应(评审 A10 实证),BYOD 文档可提一句。
6. **`CanBeManaged()==true` 的未纳管 profile 理论上不被锁**(gate 旁路):本产品 GAIA 被抑制、该形态不可造;仅未来引入外部 user-data 导入时需处理(记录,不实现)。
7. **迁移路径**:§4.9 收口后,gate ON 重锁指向新 D、gate OFF 菜单回未纳管态;`MaybeHandleDomainMigration` 幂等性不变。
8. **不引入新网络面**:登录链路 100% 复用 `enroll/start` → `accounts.<D>` → register-handler capture → in-place registrar(§4.7 保证该链路在两种 gate 态下都成立)。

## 6. 测试策略

**gtest(//teleport,src/common 纯逻辑)**

- `ShouldShowTeleportSigninEntry(is_enrolled, is_regular_profile, is_web_app)` 纯函数(TDD 新增);
- `ShouldBlockNavigation` 参数化回归(现有);
- gate 谓词的纯决策部分(默认 false / fail-open 语义)经 `PrefService*` 注入的 seam 单测(谓词本体在 chrome/browser,链接不可达,seam 放 src/common)。

**工具链**:`uv run pytest` 全绿;`apply_patches.py` 幂等(含删除的 startup patch、全部修改/新增 patch)。

**活体冒烟矩阵(fairyland.ai 栈,dev 构建)**

1. gate OFF 默认:全新 user-data-dir 启动 → 正常 NTP、无 enroll tab、无 FRE 登录窗、可任意浏览;
2. 菜单登录:未纳管菜单见「登录」(含 subtitle)→ 新 tab OIDC 全链 → **披露对话框出现**(就地纳管措辞)→ 接受 → **就地纳管**(断言:不新建 profile)→ `chrome://policy` 用户策略生效 → 菜单转「由 <机构> 管理」header(机构名与 ⋮ 菜单「Managed by」、chrome://management 副标题三表面同串);另断言:拒绝对话框 → 不纳管、原页停留、可重试;
3. 自愿流失败反馈:模拟 registrar 失败 → tab 呈现错误页(非静默);
4. gate ON(手改 local_state):**冷启动即锁**进 picker → enrollment step 完成 → 解锁开窗;
5. gate ON 新建 profile:「添加」→ enrollment step;中途取消 → 返回 picker 且 registrar 终态后 profile 目录消失;完成 → profile 存活且下次启动仍在(finalize 生效);
6. guest:gate ON 时 UI 入口消失 **且 `--guest` 启动被拒**;OFF 时可用;
7. GAIA 表面集:两态菜单、settings People 区(含已纳管后无「isn't associated with Google」残留)、picker 建号流、头像按钮均无任何 GAIA/Google 品牌登录项;
8. 换域迁移:enroll → 改 D → 重启 → 迁移日志 + chrome://version「changed from」+ gate ON 下重锁/OFF 下菜单回未纳管;运行期迁移(不重启)后新开窗口即锁(gate ON)。

## 7. 后续(技术债登记)

- TD:gate 开关的企业下发通道(MDM forced pref / 机器配置文件 / CBCM 策略映射)。
- TD:settings guest 开关回显与动态谓词 desync(§4.4)。
- TD:settings「Sync and Google services」死行;`chrome://signin-*` WebUI 死壳目录清理(§4.8)。
- TD:device-signals 同意位(§4.5)。
- TD:迁移时已开窗口的关闭策略(§4.9 残余)。
- TD(既有):fairyland 私有化交付文档补「BYOD 先设域后登录」引导 + enroll 页披露文案;机器级 CBCM DM token 迁移清除。

## 8. 清理清单(评审死代码清查,plan 期逐项落 task,杜绝「顺手改动不入册」)

**删除**:`startup_browser_creator_impl.cc.patch`(§4.3)。
**转正**:`PendingDomainMigrationFrom()` 由 version_ui patch 改为调用方(§4.9),不再是死代码。
**重写失实注释/文本**:
- `profile_picker_handler.cc.patch` `HandleSelectNewAccount` hunk(§4.6.8);
- `profile_picker_flow_controller.cc.patch` `OnEnrollmentSucceeded`「new-profile creation intentionally not supported」(§4.6 后失实);
- `teleport_enrollment_gate.{h,cc}`/`teleport_pref_names.h` 的「secure default true / cannot browse」注释(默认翻转后条件化);
- `teleport_enterprise_urls.{h,cc}` 「injection … empty today」注释(per-tenant OP 注入已实现并活体验证);
- `version_ui.cc.patch`「the gate has re-locked」(仅 gate ON 成立);
- capture throttle patch 的「gated context」注释(§4.7)。
**文档同步**:
- `scripts/smoke_check.md:67`(`--dump-dom` 挂起条目改为「仅 gate ON」);
- `docs/deployment-domain-migration-runbook.md` 全篇 gate-ON-默认叙述条件化 + 修正「CBCM DM token 清除为后续项」的失实表述(代码已做);
- `docs/tech-debt.md` TD-005 状态更新(菜单面已解,settings 面见 §7 TD);
- 旧 plan 文档(enrollment-gate / lock-gate)的 `RegisterBooleanPref(...,true)` 快照过期——史料不改,在本 spec 此处声明防误抄;
- 合并后刷新 auto-memory(`enterprise-enrollment-gate-feature` 的 default-on 记述)。
**保留(评审确认非死代码)**:Layer-1 picker 纳管机器全套、共享 enrollment 底座(`profile_impl` 全局 ProfileCloudPolicyManager 等)、gate throttle、`infobar_utils.cc.patch`(API-key infobar 抑制,正确且足够)、`chrome_browser_main.cc.patch`(仅启动 banner)、BUILD.gn patch 无孤儿。
