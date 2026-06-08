# Phase 5 · Idle 超时 + Data Controls(剪贴板/打印)— 设计(teleport 主控 + 客户端)

> 承接《chrome 企业版能力对齐》总纲(`2026-06-04-chrome-enterprise-alignment-design.md`)的 **Phase 5**。配对仓服务端设计见 fairyland 同名 `...-server-design.md`。本轮 **DLP 内容送检(Content Analysis)仍 Out**。

## 1. 目标与可见成果

把 Chrome 原生的两类「控件簇」能力接入 teleport(受管端)+ fairyland(下发面),全部**策略驱动、无新协议**,复用 Phase 3 的 catalog + admin gRPC + `policy_assignments` 下发管道:

- **Idle 超时**:受管浏览器闲置达阈值后自动执行清理/登出类动作(关浏览器、清浏览数据、显示 Profile 选择器等)。
- **Data Controls 剪贴板/打印**:按 URL 规则限制复制/粘贴、打印,并弹出**警告(WARN)/ 阻断(BLOCK)对话框**(品牌化为「闪现」)。

**可见成果**:① 闲置超时后动作执行 + idle 气泡;② 按规则阻断/警告复制粘贴与打印,对话框显示「闪现」。

## 2. 范围与非目标

**In**:`IdleTimeout` / `IdleTimeoutActions` / `DataControlsRules` 三策略的下发与执行;数据管控与 idle 对话框品牌化;live e2e。

**Out(本轮)**:
- DLP 内容送检 / Content Analysis(连接器送检)。
- Data Controls 的 Screenshot / Files / FileDownload restriction —— **桌面 Chrome 未接 hook**(`chrome_rules_service.cc` 仅实现剪贴板 + `GetPrintVerdict`),Screenshot 留待 Phase 6。
- Watermark(Phase 6)、脱敏(Phase 7)。
- Idle 的 user-scope 下发(本轮只走已验证的 **machine CBCM** 通道)。
- `DataControlsRules` 的结构化建模 / Web 表单(见 §4 决策:本轮不透明透传)。

## 3. 关键事实(已核对 M148 源码)

策略字段(`out/.../gen/components/policy/proto/cloud_policy.proto`):

| 策略 | 字段号 | wire 类型 | catalog 形态 |
|---|---|---|---|
| `IdleTimeout` | 996 | `IntegerPolicyProto` | 纯整数(分钟) |
| `IdleTimeoutActions` | 1038 | `StringListPolicyProto` | 字符串列表(动作 token) |
| `DataControlsRules` | 121 | `StringPolicyProto` | JSON 字符串(不透明透传) |

客户端事实:
- **Idle 非品牌门控**:`IdleServiceFactory`(`chrome/browser/enterprise/idle/idle_service_factory.cc`)`!IS_ANDROID`、`ServiceIsCreatedWithBrowserContext()==true`,随 profile 创建并监听 `prefs::kIdleTimeout`。`IdleTimeout` 由 `IntRangePolicyHandler` 处理,**clamp 最小 1 分钟**;`IdleTimeoutActions` 与 `IdleTimeout` 有**跨策略依赖**(`idle_timeout_policy_handler.cc` 缺 timeout 时报 `IDS_POLICY_DEPENDENCY_ERROR_ANY_VALUE`)。
- **`IdleTimeoutActions` 13 个合法 token**(`components/enterprise/idle/action_type.cc`):`close_browsers`、`close_tabs`、`show_profile_picker`、`sign_out`、`reload_pages`、`clear_browsing_history`、`clear_download_history`、`clear_hosted_app_data`、`clear_cookies_and_other_site_data`、`clear_cached_images_and_files`、`clear_password_signin`、`clear_autofill`、`clear_site_settings`。(`sign_out` / `close_tabs` 在桌面多为 no-op,但仍属合法 token;平台适用性交给 Chrome,服务端只校 token 合法性。)
- **Data Controls 非品牌门控**:`components/enterprise/data_controls/` 下唯一 BUILDFLAG 是 CrOS/Android/`ENTERPRISE_SCREENSHOT_PROTECTION`,无 `is_chrome_branded` 门。`DataControlsRules` handler 设 `kDataControlsRulesScopePref = policy->scope` + `kDataControlsRulesPref`,机器 scope 路径(`rules_service_base.cc:130` 的 `scope==machine` 判定)与 P4 `OnSecurityEventEnterpriseConnector` 同理可用。桌面执行点:剪贴板 + `GetPrintVerdict`。

## 4. 关键决策

- **`DataControlsRules` 不透明透传**:服务端只存储 + 下发 + 校 JSON 语法,**绝不解释规则语义**(规则的解析/匹配/verdict 全在 Chrome)。规则 JSON 的「作者」是 admin gRPC 的调用方(当前手工/脚本,未来可由 fairyland 上层控制台的表单生成);把「表单→JSON」的职责留在上层,不塞进下发后端。与 P4 连接器一致,抗 Chrome rules schema 演进,零维护。
- **Idle token 枚举校验 + 跨策略护栏**:catalog 校验每个 action ∈ 13 token(拒 typo);`SetTenantPolicies`/`SetPolicy` 加护栏:设了 `IdleTimeoutActions` 必须同时有 `IdleTimeout`(镜像 Chrome 的 dependency,提前报 `InvalidArgument`)。
- **单一 P5 spec/plan,服务端重、客户端轻**:Idle 太小且与 Data Controls 共享下发机制,合为一个 phase(仿 P3 形态)。
- **scope = machine、mode = mandatory**:三策略均执行类,走已验证的机器 CBCM 通道、mandatory 模式(后续可扩 recommended)。

## 5. 客户端工作(teleport,预计近零 patch)

1. **验证 Idle**:机器下发 `IdleTimeout`+`IdleTimeoutActions` → `IdleService` 执行动作。仅验证。
2. **验证 Data Controls**:机器下发 `DataControlsRules` → 剪贴板/打印 verdict 生效;确认机器 scope 的 `kDataControlsRulesScopePref` 路径应用规则。仅验证。
3. **品牌化**(唯一可能 patch 处):定位剪贴板/打印的 WARN/BLOCK 对话框 + idle 超时对话框/气泡,产品名 → 闪现。优先 `branding_strings.py` 的 grd sweep;若有硬编码 C++ 字符串泄漏(参照 Phase 3 `kChromePoliciesName`),镜像路径单文件 patch。**精确 UI 落点 plan 阶段定**。
4. **客户端不 vendor proto**:三者均上游内建策略(自带 handler),Chrome 用自身 `cloud_policy.proto` 解码;overlay 不碰客户端 proto。

## 6. e2e(live,机器 CBCM,复用 dev stack + `docker-compose.phase2-worktree.override.yml` + tenant 1111)

1. **delivery**:`SetTenantPolicies` 把三策略写到 tenant 1111 machine scope;浏览器 Reload policies → `chrome://policy` 显示三条(值/Level=Mandatory/Source=Cloud)。
2. **Idle**:`{IdleTimeout:1, IdleTimeoutActions:["clear_browsing_history","clear_cookies_and_other_site_data"]}`(护栏要求两者同设)→ relaunch(缓存后启动确保启动即生效)→ 闲置 ~1 分钟 → 观察动作执行 + idle 气泡。
3. **Data Controls**:`DataControlsRules` 下发一条「source 匹配某 URL → 剪贴板 BLOCK」+ 一条 WARN(及/或打印阻断)→ relaunch → 在匹配页复制/打印 → 观察阻断/警告对话框,确认显示「闪现」。

## 7. 测试策略

- **服务端 TDD**(详见配对仓 server 设计):catalog 三条目、`ValueInt`/`ValueJSON`/`AllowedTokens` 校验、跨策略护栏均有 Go 单测;无新表。
- **客户端**:以 live e2e 为主(同 P2/P3/P4,纯策略驱动+品牌,gtest 价值低);若产生品牌 patch,确认 `apply_patches.py` 幂等 + 单 TU 编译。
- **风险**:① Idle e2e 墙钟慢(≥1 分钟闲置);② DC 对话框 UI 精确落点 plan 阶段确认;③ 策略缓存时序同 P4(规则在机器策略拉取后生效,缓存后下次启动即在)——e2e 用「预热 + 缓存后启动」。

## 8. 跨仓协作

- **teleport**(本文,主控 + 客户端):验证执行 + 品牌 + e2e。
- **fairyland**(server 设计):vendor 3 proto 字段 + 3 catalog 条目 + `ValueInt`/`ValueJSON`/`AllowedTokens` + 跨策略护栏 + docs 模板。
- 改任一端策略契约务必同步另一端;三策略字段号钉死上游 M148。
