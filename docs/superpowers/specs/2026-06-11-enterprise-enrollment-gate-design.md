# Teleport 企业纳管门禁设计:未纳管即不可上网(路径 A,第一轮)

- 状态:设计(评审中)
- 日期:2026-06-11
- 仓库:`teleport`(Chromium overlay 客户端)
- 本文归属:**客户端设计权威**。服务端触点(下发 `RequireEnrollmentToBrowse` 策略)在 `fairyland`,见 §6;本轮服务端改动极小,暂不单独成 spec,待第二轮策略开关成体系时再配对。
- 上位文档:
  - `docs/superpowers/specs/2026-06-03-enterprise-account-system-design.md`(总体账号体系)
  - `docs/superpowers/specs/2026-06-04-enterprise-oidc-client-design.md`(OIDC 纳管 throttle 契约,**本设计直接复用**)
  - `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`(企业对齐总纲)
- 分支/worktree:`enterprise-enrollment-gate`(`.claude/worktrees/enterprise-enrollment-gate`)
- 关联:[[enterprise-account-system]]、[[chrome-enterprise-alignment-roadmap]]、[[channel-side-by-side-feature]](buildflag/per-channel)

> 目标效果:企业用户装好 Teleport 后,**必须先用企业账号完成 OIDC profile 纳管(接受 user 级纳管)才能正常访问互联网**。本轮以**最小可评估切片**落地「纳管门禁」,复用已跑通的 OIDC 纳管流程,不碰多 profile 锁与就地纳管(见 §2 范围边界的推迟项)。

---

## 1. 目标与背景

### 1.1 为什么不用 `BrowserSignin=2`

Chrome 自带的「强制登录才能用浏览器」策略 `BrowserSignin=2`(pref `kForceBrowserSignin`)死绑 **GAIA 登录完成态**:其判定(`signin_util::IsForceSigninEnabled`、`ForceSigninVerifier` 要求 `IdentityManager::HasPrimaryAccount`)、其 UI(ProfilePicker forced-signin 对话框托管 `GaiaUrls::reauth_chrome_dice()`)全部假设 Google 身份基础设施。我们走的是 [[enterprise-account-system]] 重指向 Keystone 的**第三方 OIDC profile enrollment**,与之对不上。故自建门禁。

### 1.2 安全默认(default-deny)+ 策略开关

能力做成**策略开关,默认锁紧**,租户按需经 device CBCM/Keystone(未来 Windows GPO)下发策略放开:

| 策略(暂定名) | 默认 | 含义 |
|---|---|---|
| `RequireEnrollmentToBrowse` | **on** | 未纳管即不可上网(本轮实现) |
| `AllowMultipleProfiles` | **off** | 是否放开多 profile(**第二轮**) |

新装设备在收到任何策略前 = 必须纳管(安全默认)。

---

## 2. 范围边界

### In(第一轮,本分支)

- 策略 `RequireEnrollmentToBrowse`(默认 on),经已跑通的 device CBCM/Keystone 通道下发。
- //teleport 导航门禁 throttle:未纳管时拦截一切非纳管流程导航,导回 enroll 落地页。
- 启动导向:未纳管时首个标签页直落 `EnterpriseEnrollUrl()`。
- 纳管判定谓词 `IsEnrolled(profile)`(单一事实源)。
- **原样复用** [[enterprise-account-system]] 已跑通的 OIDC 纳管(上游默认的**新建-profile**路径),不重建、不改 in-place。
- 平台:仅 macOS(Apple Silicon)实现 + 活验。
- gtest 单测(TDD)。

### Out(显式推迟到第二轮,看第一轮效果再定)

- `AllowMultipleProfiles` 策略 + `ProfileManager::CanCreateProfileAtPath()` 多 profile 硬锁。
- **就地纳管单 profile**(把当前 default profile 原地转受管)——仅当决定锁多 profile 时才必需(否则 OIDC 新建-profile 与硬锁互斥)。
- Layer 1 复用 forced-signin profile 锁(仅当需要「ProfilePicker 显示锁定 + 绝对零窗口」硬保证;代价是重指向 picker 对话框托管 IdP 流,扎进上游最易碎的 signin 区,uprev 负债高——本轮不取)。
- 运行期周期性重查纳管/会话有效性(Q2 的重档)。
- Windows GPO 下发;Linux / 国产 OS。
- 加固级/要塞级威胁模型(命令行 flag、`--user-data-dir`、guest、卸载重装等绕过)——本轮**合规级**:只拦好意用户的正常使用路径。

---

## 3. 关键决策(本轮已拍板)

1. **路径 A,先实现评估**:NavigationThrottle 门禁 + 启动导向(+ 多 profile 锁第二轮)。理由:OIDC 纳管**需要一个可导航的普通窗口**跑 IdP 重定向链,NavigationThrottle 正好是「让窗口开、只放行纳管流程」的恰当高度;补丁面小、几乎全在 overlay 加法层;释放条件就是已持久化的纳管态;合规级下无需 forced-signin 锁的「零窗口」硬保证。
2. **第一轮不锁多 profile,故不需就地纳管**:多 profile 硬锁与「就地纳管」绑定(只有锁死多 profile 时,才必须把 OIDC 新建-profile 改成就地,否则锁会挡掉 enrollment 自己的建 profile)。第一轮把「纳管门禁」单独切出,信号最高、避开最重的 in-place 补丁。
3. **纳管判定 = 纳管完成 + 首次用户策略拉取成功**(Q2 中档):证明服务端确实纳管了该用户,而非仅本地走过 OIDC 流程。一次性门槛;之后凭已持久化的纳管态放行(后续启动即便离线也放行)。
4. **安全默认 + 策略开关**:`RequireEnrollmentToBrowse` 默认 on;机器级策略拉取走 DM server 独立通道、**不经 NavigationThrottle**,故「放开未登录」的策略能在用户被挡前生效,无引导死锁(§7 实证)。
5. **单一事实源**:门禁判定谓词、纳管流程 URL 白名单各只有一处实现,启动导向与 throttle 共用,避免 drift。

---

## 4. 架构(客户端)

### 4.1 判定谓词(单一事实源)

```cpp
// src/browser/enterprise/teleport_enrollment_gate.{h,cc}  (//teleport)
namespace teleport {

// 门禁是否对该 profile 生效:常规 profile(非 OTR/guest/system)
// 且策略 RequireEnrollmentToBrowse 为 on。
bool ShouldGateProfile(Profile* profile);

// 纳管完成谓词:ProfileManagementId 已写 且 用户云策略已拉到。
//  - ProfileAttributesEntry::GetProfileManagementId() 非空(OIDC 纳管落地时持久化)
//  - 用户级 CloudPolicyStore has_policy()(首次策略拉取成功)
// 注:两个 accessor 的精确取法在 plan 阶段于 M148 检出钉死(见 §7 假设 2)。
bool IsEnrolled(Profile* profile);

// 纳管流程 URL 白名单(放行,使 OIDC 重定向链能跑):
//  teleport::EnterpriseEnrollUrl() / EnterpriseRegisterHandlerUrl()
//  / EnterpriseTrustedRedirectHosts()  —— 全部复用 src/common/teleport_enterprise_urls。
bool IsEnrollmentFlowUrl(const GURL& url);

}  // namespace teleport
```

### 4.2 Layer 2 — 导航门禁 throttle

`src/browser/enterprise/teleport_enrollment_gate_throttle.{h,cc}`(//teleport),`content::NavigationThrottle`:

- `WillStartRequest` / `WillRedirectRequest`:`ShouldGateProfile && !IsEnrolled && !IsEnrollmentFlowUrl(url)` → `CANCEL`(`net::ERR_BLOCKED_BY_CLIENT`)并将该标签页导向 `EnterpriseEnrollUrl()`(或展示品牌化 interstitial,本轮取「重定向到 enroll 页」最小实现)。
- 纳管流程 URL 一律 `PROCEED`,使 [[enterprise-account-system]] 既有的 `OidcAuthResponseCaptureNavigationThrottle`(读 `X-Profile-Registration-Payload` 头)能在普通窗口里正常触发。
- 释放自动:`ProfileManagementId` 一旦写入且策略拉到,谓词翻转,后续导航放行。
- **参照**:上游 `ManagedProfileRequiredNavigationThrottle`(`chrome/browser/enterprise/signin/`,在 `chrome_content_browser_client_navigation_throttles.cc:447` 全局注册,受 `features::kManagedProfileRequiredInterstitial` 门控)证明「按 BrowserContext 阻断除白名单外全部导航」机制在 M148 可行;我们的 throttle 自包含、持久化判定,不复用其闭包式 BlockingInfo。

### 4.3 Layer 1 — 启动导向

未纳管时,启动不恢复/打开普通会话标签,首个标签页直落 `EnterpriseEnrollUrl()`,使「开浏览器即纳管页」,而非先白屏再被 throttle 弹回。patch `chrome/browser/ui/startup/startup_browser_creator{,_impl}.cc`(具体注入点 plan 阶段钉死)。

### 4.4 客户端 patch 面

| 文件 | 改动 | 类型 |
|---|---|---|
| `src/browser/enterprise/teleport_enrollment_gate.{h,cc}` + `_throttle.{h,cc}` + `_unittest.cc` | 新增 //teleport | 加法 |
| `src/BUILD.gn` | 注册新源文件到 `//teleport` source_set + unittests | 加法 |
| `chrome/browser/chrome_content_browser_client_navigation_throttles.cc` | +1 行注册 gate throttle | **唯一必需注册 patch** |
| `chrome/browser/ui/startup/startup_browser_creator{,_impl}.cc` | 未纳管时首页导向 enroll | patch |

> 多 profile 锁(`CanCreateProfileAtPath`)与 `AllowMultipleProfiles` 策略**不在本轮**,故无对应 patch。

---

## 5. 数据流

```
[新装/未纳管 profile 启动]
   └─ ShouldGateProfile=true, IsEnrolled=false
        └─ 启动导向: 首页 = EnterpriseEnrollUrl()           (Layer 1)
        └─ 用户任何其它导航 → throttle CANCEL → 导回 enroll  (Layer 2 兜底)
   ↓
[enroll 落地页 → 跳 per-tenant OP → 委派 accounts 手机号登录 → 回 code]
   ↓  (复用 enterprise-account-system 已跑通链路)
[enroll-landing 换 id_token + HPKE → X-Profile-Registration-Payload 头]
   ↓
[OidcAuthResponseCaptureNavigationThrottle 截头 → 受管 profile 创建/注册]
   ↓
[device-manager register_profile 200 → 首次用户策略 200 拉到]
   ↓
   └─ ProfileManagementId 已写 且 用户云策略 has_policy() → IsEnrolled=true
        └─ throttle 与启动导向同时放行 → 正常上网
```

> 关键:机器级策略拉取(`?request=policy`,经 DM server 独立 URLLoader)**不走 NavigationThrottle**,不被门禁阻断;故租户下发的 `RequireEnrollmentToBrowse`(乃至未来「放开未登录」)能在 web 导航被挡的同时正常到达(§7 假设 1 实证)。

---

## 6. 服务端触点(fairyland)

本轮服务端改动极小:在策略目录(catalog,见 `2026-06-07-enterprise-alignment-phase3-policy-framework-design.md`)中新增一条 `RequireEnrollmentToBrowse`(machine scope,Boolean,默认下发 true,可按租户置 false)。客户端原生消费(经 `chrome://policy` 链路),无需新协议字段。

> 改动任一端协议时同步另一端(本仓 CLAUDE.md 约定)。`AllowMultipleProfiles` 与多 profile 锁第二轮再配对设计。

---

## 7. plan 阶段必须实证的假设

1. **机器级策略拉取不走导航层**:确认 `?request=policy` / CBCM 策略 fetch 经独立 `URLLoader`,不经 `NavigationThrottle`,从而 default-deny 不死锁(放开类策略能先于用户解禁到达)。— 看 `device_management_service` / `CloudPolicyClient` 的请求路径。
2. **纳管完成有可靠可观测信号**:钉死 `IsEnrolled` 两个 accessor 的精确取法 —— `ProfileAttributesEntry::GetProfileManagementId()` 与 OIDC(dasherless)路径下「用户云策略首次拉到」的判定(`UserCloudPolicyManager`/对应 manager 的 `core()->store()->has_policy()` 或等价)。确认二者在 M148 OIDC 路径上确实置位、且时序上「策略拉到」晚于「ProfileManagementId 写入」。
3. **throttle 注入点与时序**:确认 `chrome_content_browser_client_navigation_throttles.cc` 注册点能覆盖主框架导航;`startup_browser_creator` 的导向注入点不与 OIDC 流程/会话恢复打架。
4. **enroll 流程在受门禁 profile 内可跑通**:即门禁放行白名单足够,OIDC 重定向链(OP→accounts→回跳→register-handler)全程命中白名单、`OidcAuthResponseCaptureNavigationThrottle` 正常触发。

---

## 8. 测试与验收

### 8.1 客户端单测(TDD,gtest,`teleport_unittests`)

- `IsEnrollmentFlowUrl`:enroll/register-handler/受信源 host 放行;任意第三方 URL 不放行;dev/release 双端点。
- `ShouldGateProfile`:常规 profile 受门禁;OTR/guest/system 不受;策略 off 时不门禁。
- `IsEnrolled`:`ProfileManagementId` 空/非空 × 策略未拉到/拉到 的判定矩阵(以可注入的 fake profile 状态驱动)。
- throttle 决策:`(受门禁 × 未纳管 × 非白名单)` → CANCEL;其余组合 → PROCEED。

### 8.2 端到端活验(macOS dev)

重建 Teleport.app(dev)→ 起 [[enterprise-account-system]] 服务端栈 + seed 租户 → 全新 profile 启动:
1. 门禁生效:首页落 enroll 页;手敲任意网址被弹回 enroll。
2. 完成手机号登录 + 受管 profile 纳管(GUI 人工)。
3. `register_profile` 200(DASHERLESS)+ 用户策略 200 拉到。
4. 纳管后:门禁释放,正常访问任意网站;重启浏览器(含离线)仍放行(凭持久化纳管态)。
5. 将 `RequireEnrollmentToBrowse` 置 false 下发 → 未纳管也可直接上网(验证策略开关 + 安全默认可被运营放开)。

---

## 9. 工作分解(交 writing-plans 细化)

1. 谓词 + URL 白名单 `teleport_enrollment_gate.{h,cc}` + 单测(TDD 先行)。
2. `TeleportEnrollmentGateThrottle` + 单测;`src/BUILD.gn` 注册。
3. throttle 全局注册 patch(`chrome_content_browser_client_navigation_throttles.cc`)。
4. 启动导向 patch(`startup_browser_creator{,_impl}.cc`)。
5. 策略 `RequireEnrollmentToBrowse` 接入(客户端消费 + fairyland catalog 一条目)。
6. §7 四项假设的实证(穿插在 1–4,先验后写)。
7. 端到端活验(§8.2)+ 冒烟。

> plan 阶段先做 §7 假设实证(尤其 1、2),再按 TDD 红→绿→重构推进 1–5。
