# 部署域名配置 Phase 2b(teleport 客户端)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans. Steps use `- [ ]`.

> **进度(2026-07-15)**:**子阶段 2b-1(B1/B2)+ 2b-2(B3/B4/B5)全部完成并活体验证**。
> - B4-core:`ServerIdentityVerdict` 分类枚举 + `VerifyServerIdentityDetailed`;`teleport_connect_logic` 纯状态机(`PlanServerIdentityFetch` / `VerifyFetchedIdentity`)+ 写入 seam(`SetServerIdentityEntryWriter`)。gtest 全绿。
> - B3:`chrome://connect` WebUI(独立 `//chrome/browser/ui/webui:teleport_connect` source_set,`:configs` 注册;`teleport://connect?domain=` 重写复用现有 scheme handler)。
> - B4-wire/B5:message handler(`SimpleURLLoader` GET server-identity,工厂取自 WebUI StoragePartition→**不碰 g_browser_process**;`GetPolicyVerificationKey` 验签;确认点击后经 writer seam 落 Local State)+ 内联 connect.js(深链接预填/自动验证、确认、done、IDN punycode textContent、分状态中文错误)。writer 由 `//chrome/browser` 的 level4 注册。
> - **活体闭环**(teleport.test 集群,经 SSH SOCKS):`teleport://connect?domain=teleport.test` → 自动验签通过 → 确认 → 写 `teleport.deployment.server_identity_entry` → **不带命令行开关重启后 `chrome://version` 显示 `Deployment domain: teleport.test (source: user-accepted)`**。level-4 生产者(connect)↔ 消费者(B2 resolver)闭环。
> - **B6(2b-3)完成 + 跨仓活体验证**:gate `IsEnrollmentFlowUrl` 从 `.D` 后缀通配收敛为**精确 host 集** `{teleport.D, accounts.D}`(均派生)+ 运行时注入集。**关键发现**:当前拓扑选租户后主帧确实跳 per-tenant OP `<slug>.D`(dadou.teleport.test)做 OIDC `/authorize`——精确 gate 会拦。按 spec §3.4a **服务端注入**:enroll-landing 在 `/resume→OP` 的 302 上发 `X-Teleport-Enroll-Allow-Hosts: <slug>.D` 头;客户端 throttle(WillRedirectRequest/WillProcessResponse)读头,`ParseInjectableEnrollmentHosts` 约束为 **D 严格子域**后注入。活体:读到头→注入 dadou.teleport.test→`/authorize` 放行(无 block)→注册完成→用户策略应用→gate 解锁;任意 `*.D` 子域被拦。teleport `3e30e0d` + fairyland `1de7097`。
> - **剩余**:**Phase 2c**(§4.5 换域重纳管接线 + 私有化交付规范);另 §4.2 的「已 enroll→connect 页拒改(只读)」状态约束在 B4/B5 暂缓(需一个 enrollment-state seam,功能上仍 fail-closed 安全)。
> - 提交:B4-core `ca2033e`、B3 `4f4ea52`、B4-wire+B5 `945ba84`、B6 `3e30e0d`(+fairyland `1de7097`)。115 teleport_unittests 全绿。

**Goal:** 把 Phase 2a 的验证基元接进浏览器:第 4 级 Local State 自认证条目 + resolver 离线重验接线;`teleport://connect` 页(含 `?domain=` 深链接、确认 UX、fetch+验签+落盘);gate 精确主机白名单 + 拦截页动态放行主机。

**Architecture:** 分三个子阶段,可独立交付:2b-1 后端接受机制(无 UI,可端到端测)、2b-2 connect 页 UI、2b-3 gate 收敛。依赖:2b-2 写 Local State 条目 → 2b-1 读并生效;2b-3 独立。

**Tech Stack:** C++ overlay + patches、Chromium WebUI(WebUIController/Config + loadTimeData + TS/HTML)、`network::SimpleURLLoader`、`components/prefs`、gtest。

## Global Constraints

- 协议准源:`docs/superpowers/specs/2026-07-15-deployment-domain-config-design.md` §4.2/§4.5/§5.0。
- **依赖环红线**:验证(crypto+proto)与 Local State 读取都在 **//chrome/browser 编译的 TU**,leaf `teleport_deployment_config` 仍只 //base+//url。第 4 级值经**注册回调**(在首次 `DeploymentDomain()` 前注册)喂进 leaf 的 `ResolveUncached`,leaf 不 dep 验证库/Local State。
- **第 4 级自认证**:Local State 存 `{domain, identity(signed_bytes b64), signature b64}`;每次启动离线重验(§5.0)——`VerifyServerIdentity` + 烘焙 `GetPolicyVerificationKey()` + `now`;任一不过丢弃、下探。
- **fetch**:`SimpleURLLoader` + `redirect_mode=kError` + `SetTimeoutDuration(10s)` + `credentials_mode=kOmit`,factory 取自 `system_network_context_manager()`;URL = `https://teleport.<D>/dm/server-identity`(`TeleportHostFor(D)` 构造)。
- **WebUI 特权导航**:`teleport://connect` 经 `teleport_url_scheme` 重写为 `chrome://connect`;web 内容不可导航到它(文档写「复制粘贴到地址栏」);确认页必须一次显式点击才落盘(§4.2,导航不改安全状态)。
- **IDN 显示**:确认/done 视图一律 punycode 展示域名;`textContent` 渲染,杜绝 `?domain=` 注入 HTML。
- **一文件一 patch**;WebUI 注册/资源改动落 `patches/`(参考 About 页跨 target 模式);纯逻辑抽 `src/common` 走 gtest。构建 worktree 需 `export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`。

---

## 子阶段 2b-1:后端接受机制(Local State 第 4 级 + resolver 接线,无 UI)

### Task B1: Local State 条目 pref + 纯编解码逻辑

**Files:** `src/common/teleport_pref_names.h`(加 `kServerIdentityEntry`);`src/common/teleport_server_identity_entry.{h,cc,_unittest.cc}`(纯:dict ↔ {domain, signed_bytes, signature} 编解码,base64);`src/BUILD.gn`(加进 `:teleport_server_identity` 或新 source_set + unittest)。

**Interfaces:** `std::optional<ServerIdentityParts+domain> DecodeServerIdentityEntry(const base::Value::Dict&)`;`base::Value::Dict EncodeServerIdentityEntry(domain, signed_bytes, signature)`。纯函数,base64 编解码 + 字段校验。

- [ ] Step 1: 写失败测试(编码往返;缺字段/坏 base64 → nullopt)。
- [ ] Step 2-4: 加 pref 常量 + 实现(base64 via `base::Base64Encode/Decode`)+ GREEN。
- [ ] Step 5: Commit。

### Task B2: 第 4 级读取器(//chrome/browser TU)+ 离线重验 + resolver 回调接线

**Files:** `src/browser/teleport_deployment_level4.{h,cc}`(//chrome/browser 编译,读 Local State + `VerifyServerIdentity(GetPolicyVerificationKey())` + `NormalizeDeploymentDomain`);patch 注册 pref(`browser_prefs.cc.patch` 的 `RegisterLocalState`);leaf 加 `SetUserAcceptedDomainReader(callback)` + `ResolveUncached` 调它;启动早期注册(patch 到 pref 注册后 / policy connector init 前)。

**Interfaces:**
- leaf(`teleport_deployment_config.{h,cc}`): `void SetUserAcceptedDomainReader(base::RepeatingCallback<std::optional<std::string>()>);` `ResolveUncached` 第 4 级参数改调该 reader(未注册→nullopt);保持 memoize。
- //chrome/browser: `std::optional<std::string> ReadVerifiedUserAcceptedDomain();`(读 pref → decode → VerifyServerIdentity → 返回 normalized domain 或 nullopt)。

- [ ] Step 1: 纯决策测试(在 leaf 单测:注册一个返回定值的 reader → 第 4 级生效;返回 nullopt → 下探)。这部分**可在 teleport_unittests 测**(reader 是注入回调)。
- [ ] Step 2: //chrome/browser 的 `ReadVerifiedUserAcceptedDomain` 实现 + 注册(编入 chrome,冒烟验证:seed Local State 条目 + 重启 → `chrome://version` 显示 D + source=user-accepted;篡改 signature → 回落)。
- [ ] Step 3: patch `browser_prefs.cc` 注册 pref;patch 启动路径注册 reader(须在首次 `DeploymentDomain()` 前——policy connector init 前;若时序不满足,reader 注册点前移到 `RegisterLocalState` 同阶段)。
- [ ] Step 4: 构建 chrome + 冒烟 + Commit。

> **时序风险(实现期重点)**:首次 `DeploymentDomain()` 在 policy connector init(启动极早)。reader 注册须更早。若无法早于,退路:第 4 级读取不走 memoized resolver,而是让 connect 页落盘后**要求重启**,重启后 reader 在 `RegisterLocalState` 阶段注册(早于 connector)。§4.2 本就要求重启生效,故此退路可接受。

---

## 子阶段 2b-2:connect 页 WebUI(greenfield)

### Task B3: connect WebUI 骨架(WebUIController + WebUIConfig 注册)

**Files:** `src/browser/webui/teleport_connect_ui.{h,cc}`(WebUIController + WebUIConfig,编入 //chrome/browser via patch);资源 `src/browser/resources/connect/{connect.html,connect.ts,connect.css}` + 资源 BUILD.gn/grit;patch 注册进 `WebUIConfigMap`(参考 `chrome_urls` handler 的 include `content/public/browser/webui_config_map.h`);`teleport_url_scheme` 已重写 `teleport://connect`→`chrome://connect`(确认 host 重写覆盖 `connect`)。

- [ ] Step 1: 最小页面(静态 HTML「连接组织服务器」),注册 `chrome://connect` 可打开。冒烟:地址栏 `chrome://connect` 渲染。
- [ ] Step 2: 资源管线(webui_ts / grit)构建通过。
- [ ] Step 3: Commit。

> greenfield 提示:overlay 无既有 WebUIController;模型参考上游简单 WebUI(如 `chrome://management`)的 controller/config/resources 三件套 + `BuildWebUIDataSource`。资源经 `build_webui` 或手写 `WebUIDataSource::CreateAndAdd` + `AddResourcePath`。

### Task B4: connect 页浏览器端 handler(fetch + 验签 + 落盘)

**Files:** connect UI 的 message handler(browser 端):读 `?domain=`;规范化(`NormalizeDeploymentDomain`);`SimpleURLLoader` GET `https://teleport.<D>/dm/server-identity`(no-redirect/timeout/omit-creds);`ParseServerIdentityContainer` + `VerifyServerIdentity(GetPolicyVerificationKey(), now)`;成功 → `EncodeServerIdentityEntry` 写 Local State;把验签结果/错误分类回传前端。

- [ ] Step 1: handler 纯逻辑抽 `src/common`(状态机:规范化→(fetch 结果)→验签→落盘决策)gtest(mock fetch 结果)。
- [ ] Step 2: 浏览器端 fetch + 落盘接线(冒烟:`chrome://connect?domain=fairyland.io` 对本地 fairyland 栈 → 验签通过 → 写条目 → 提示重启)。
- [ ] Step 3: Commit。

### Task B5: connect 前端 UX(深链接预填 + 确认点击 + done + IDN punycode + 错误分类)

**Files:** `connect.ts`/`connect.html`:空/预填两形态;确认按钮(一次显式点击才触发落盘);done 视图 + 重启按钮;域名一律 punycode `textContent`;错误分类中文提示(无法连接/TLS/非200/格式/类型标签/签名无效/域名不匹配/已过期/已 enroll 拒改)。

- [ ] Step 1-3: 前端交互 + 冒烟(粘贴深链接→验证→确认→done→重启)。Commit。

---

## 子阶段 2b-3:gate 精确主机白名单 + 动态注入

### Task B6: gate 从 `.D` 后缀收敛为精确主机白名单 + 拦截页动态放行主机

**Files:** `src/common/teleport_enrollment_gate_logic.{cc,_unittest.cc}`(`IsEnrollmentFlowUrl` 从后缀改精确 host 集:`teleport.D` + 注入的 OP host);拦截页渲染注入放行主机的通道(patch,browser 端);gate 消费注入集。

- [ ] Step 1: 纯逻辑测试(精确 host 集:`teleport.D` 命中、`evil.acme.internal` 子域**不再命中**、注入的 `<slug>.D` 命中、非 https 拒)。
- [ ] Step 2: 拦截页动态注入通道(browser 端)+ gate 消费。冒烟:登录链路 `<slug>.D`/`accounts.D` 经注入放行,enrollment 端到端仍通。
- [ ] Step 3: Commit。

> **依赖**:B6 改 gate 语义(D16),须与登录链路动态注入同时上,否则登录跳转被拦。fairyland OP 拓扑未变期间,OP host 形如 `<slug>.D`,由服务端登录重定向前置知晓并经拦截页注入。

---

## 子阶段 2d:enroll 重命名 + 受管设备锁定(准源 §4.6 / D17 / D18)

> 说明:本子阶段的重命名把 B3-B6 中的 `connect` 全部改为 `enroll`(`teleport://connect`→`teleport://enroll`、`chrome://connect`→`chrome://enroll`、`teleport_connect_*`→`teleport_enroll_*`、`connect.mojom`→`enroll.mojom` 等);上文 B 任务描述保留历史名,以此段为准。

### Task D1: connect → enroll 全量重命名(机械,构建绿 + 冒烟)
- URL/host:WebUI host `"connect"`→`"enroll"`(`teleport://enroll`→`chrome://enroll`,scheme handler 通用主机重写无需改);资源目录 `src/browser/resources/connect/`→`enroll/`,文件 `connect*.→enroll*.`。
- C++:`teleport_connect_ui.{h,cc}`→`teleport_enroll_ui.{h,cc}`(`TeleportConnectUI`→`TeleportEnrollUI`、`ConnectPageHandler`→`EnrollPageHandler`、`kTeleportConnectHost`→`kTeleportEnrollHost`);`teleport_connect_logic.{h,cc,_unittest.cc}`→`teleport_enroll_logic.*`(`ConnectStatus`/`ConnectFetchPlan`/`ConnectVerifyResult` → `Enroll*`);`connect.mojom`→`enroll.mojom`(module `teleport::connect::mojom`→`teleport::enroll::mojom`)。
- GN/资源:target `teleport_connect`/`teleport_connect_mojo`→`teleport_enroll`/`teleport_enroll_mojo`;`grd_prefix connect`→`enroll`;`resource_ids.spec`、`chrome_paks.gni`(`connect_resources.pak`→`enroll_resources.pak`)、interface binder、`browser_generated_files`、lit visibility patch 路径同步。
- patch:重生成受影响 patch(webui/BUILD.gn、browser/BUILD.gn、interface binder、chrome_paks、resource_ids、lit visibility)。
- 验收:`gn gen` + `autoninja chrome` 绿;`teleport://enroll` 活体渲染;115 unittests(重命名后)全绿。

### Task D2: 受管锁定谓词(TDD 纯逻辑)
- `src/common/teleport_deployment_config`:纯函数 `IsDomainChangeLocked(DeploymentDomainSource source, bool restrict_forced) → bool` = 第 1/2/3 级来源 ∨ restrict_forced。gtest 覆盖全排列(Red→Green)。(机器 CBCM 纳管**不**作锁信号,§4.6 评估后否决。)
- mac managed-pref reader:`ReadRestrictDomainChangeForced()`(复用 `ReadManagedPrefDomain` 的 `CFPreferencesAppValueIsForced` 模式,bundle `cn.douan.Teleport`,key `RestrictDeploymentDomainChange`);非 mac stub 返回 false。

### Task D3: GetState/Unbind Mojo + 加载态视图
- `enroll.mojom` 加 `GetState() → {string domain, string source, bool locked, bool canUnbind}` 与 `Unbind()`。
- `EnrollPageHandler`(在 //chrome/browser/ui/webui):`GetState` 组装——`locked = IsDomainChangeLocked(DeploymentDomainSourceLevel(), ReadRestrictDomainChangeForced())`;`canUnbind = (source==kUserAccepted) && !locked`。`Unbind()` 经新 seam `ClearServerIdentityEntry`(由 level4.cc 注册,清 `kServerIdentityEntry`)。`Verify` 开头防御性 `if locked → 拒`。
- `enroll_app.ts`:`firstUpdated` 调 `getState()` 定三视图——只读(locked;无 input/button + 「由你的组织管理」+ 当前绑定)/ 已绑定可改(canUnbind;当前绑定 + 表单 + 解除绑定)/ 未绑定(表单)。`unbind` 按钮 → `handler.unbind()` → 回落默认(提示重启)。
- 验收:构建绿;活体验证三态((a)restrict/来源锁 (b)BYOD 已绑定+解绑 (c)未绑定)。

### Task D4: 文档 + 交付规范
- 私有化交付规范 v1(fairyland 文档)补 `RestrictDeploymentDomainChange` managed-pref key(SaaS 受管租户锁域用)。
- 迁移 runbook(`docs/deployment-domain-migration-runbook.md`)补「受管锁定」小节。

---

## Self-Review / 非目标
- 覆盖准源 §4.2(enroll 页 + 深链接 + 确认 + IDN + 错误分类 + 加载态三视图)→ B3-B5 + D3;§4.6 受管锁定 → D2-D3;§5.0(自认证条目离线重验)→ B1-B2;D16 gate 精确白名单 → B6;§4.5 迁移接线 → **Phase 2c**;私有化交付规范 → **Phase 2c/D4**;connect→enroll 重命名 → D1。
- 联合 e2e(准源 §6 ④):粘贴深链接→验证→确认→重启→enroll,对 dev 栈——2b 全部落地后跑。
- 合并纪律:与 fairyland Phase 2a/2c 联合验证后双仓背靠背合并。
