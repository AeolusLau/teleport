# Phase 1 设计 · 设备纳管点亮 + 企业管理面品牌化

- 状态:已评审(设计)
- 日期:2026-06-04
- 范围:**仅 teleport 客户端单仓**(服务端机器流已活验,本 phase 不开 fairyland 配对仓)
- 上位文档(总纲):`docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md` 的 **Phase 1**
- 分支/worktree:`worktree-chrome-enterprise-alignment`

> 本 phase 是总纲 7-phase roadmap 的第 1 个,**可直接实施**(不同于总纲的留白)。承接账号体系刻意推后的两个设备纳管 patch。

## 1. 目标与可见成果

把 Chrome 企业版的**设备级 CBCM 纳管**(无用户、登录前)在 Teleport 非品牌构建上点亮,并把**企业管理面品牌化**前置完成:

> MDM 经 Configuration Profile 推 enrollment token → 启动即机器 `register_browser` → 拿机器 DMToken → 拉**浏览器级**签名策略并应用(如 `AuthServerAllowlist`)→ `chrome://management` 显示「由 闪现 / <租户域> 管理」,工具栏/菜单管理提示品牌正确,**全程无 Google 字样穿帮**。

服务端复用账号体系已活验的机器 `register_browser` + 机器级策略下发 + `CreateEnrollmentToken` gRPC,本 phase 不新增服务端代码。

## 2. 背景:为何是 patch 而非零改

已核实于 M148 检出(148.0.7778.180):

- **CBCM 在非品牌构建默认关**:`components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc` 的 `IsEnabled()`——
  ```cpp
  #if BUILDFLAG(GOOGLE_CHROME_BRANDING)
    return true;
  #else
    return base::CommandLine::ForCurrentProcess()->HasSwitch(
        switches::kEnableChromeBrowserCloudManagement);
  #endif
  ```
  非品牌恒需命令行开关,否则 `CreatePolicyManager()` 首行 `if (!IsEnabled()) return nullptr;` 直接关闭整条机器纳管。
- **macOS enrollment token 读取硬编码 Google**:`chrome/browser/policy/browser_dm_token_storage_mac.mm`——bundle id 显式锁 `CFSTR("com.google.Chrome")`(:62,注释 "no matter what this... Explicitly access");enrollment token 文件路径 `/Library/Google/Chrome/CloudManagementEnrollmentToken`(:50)、options 路径(:56)、策略 plist `/Library/com.google.Chrome.plist`(:118)。
- **macOS Platform 策略不受品牌门控**:`chrome/browser/policy/chrome_browser_policy_connector.cc:335` 用 `base::apple::BaseBundleID()` 运行时取 bundle id 作 managed-prefs 域 → MDM 推到我们 bundle id 域的策略理论直接被 `PolicyLoaderMac` 读取。本 phase 仅验证 + 文档化。

## 3. 关键设计决策(本轮已拍板)

1. **CBCM 启用门控 = 无条件 true**(方案 A):patch `IsEnabled()` 非品牌分支直接 `return true`。理由——我们就是企业浏览器,机器纳管应默认可用;**实际是否纳管由「有没有 enrollment token」决定**(无 token 时 controller 不发起注册)。比起保留 `--enable-...` 开关更贴合 Chrome 品牌版行为。
2. **enrollment token 读取域 = 单一固定基础域**(对齐 Chrome 的固定 id 语义):所有渠道(stable/canary/beta)都读固定的 **`com.beansec.Teleport`**(裸/基础 bundle id)域 + 固定路径 **`/Library/Teleport/`**。机器级纳管本就是整机维度、与渠道无关;MDM 只推一份配置即可纳管所有渠道。**不**读运行时 per-channel bundle id(那会迫使 MDM 为每渠道各推一份,偏离 Chrome 行为)。
3. **保留标准 MDM 策略键名**:`CloudManagementEnrollmentToken` / `CloudManagementEnrollmentMandatory`(管理员沿用 Chrome 文档心智,只是域/路径换成我们的)。
4. **品牌范围限定**:本 phase 只清扫**企业管理面**这批字符串(`chrome://management` + 工具栏/菜单 managed-ui),不外扩到其他企业串(留各自 phase)。

## 4. 客户端改动

### 4.1 patch ① — CBCM 启用
- **文件**:`patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch`
- **改动**:`IsEnabled()` 非品牌分支 `return true`(无条件)。
- **验证点(plan 阶段)**:确认空 enrollment token 时 `CreatePolicyManager()` / 后续控制器路径不发起误注册(no-op)。

### 4.2 patch ② — macOS enrollment token 读取重指
- **文件**:`patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch`
- **改动**(均引用 `teleport::` 常量,不在 patch 内写裸字面量):
  - bundle id `CFSTR("com.google.Chrome")`(:62)→ `teleport::kEnterpriseManagedPrefsBundleId`(= `com.beansec.Teleport`,固定基础域)。
  - enrollment token 文件路径(:50)→ `/Library/Teleport/CloudManagementEnrollmentToken`。
  - options 文件路径(:56)→ `/Library/Teleport/CloudManagementEnrollmentOptions`。
  - 策略 plist 路径(:118 注释 + 实现)→ `/Library/com.beansec.Teleport.plist`。
  - pref 键名 `CloudManagementEnrollmentToken` / `CloudManagementEnrollmentMandatory` **保持不变**。

### 4.3 新增 `//teleport` 常量(走 TDD + gtest)
- **文件**:`src/common/teleport_enterprise_enrollment.{h,cc,_unittest.cc}`(与现有 `teleport_enterprise_urls.*` 同风格,把可变值从 patch 抽出)。
- **内容**:固定基础 bundle id 常量、enrollment token 文件路径、options 路径、策略 plist 路径。
- **BUILD.gn**:加入 `//teleport` source_set + `teleport_unittests`。

### 4.4 Platform 策略验证(近零 patch)
- 验证 `BaseBundleID()` 在我们构建解析到 `com.beansec.Teleport*`;MDM Configuration Profile 推到该域的策略被 `PolicyLoaderMac` 读取、在 `chrome://policy` 以 Platform 来源显示。
- 产出:`docs/` 一页 MDM 配置 + 验证步骤文档(enrollment token payload + 一条样例平台策略)。

## 5. 企业管理面品牌化(Phase 1 前置横切)

- **`chrome://management`**:`chrome/browser/ui/webui/management/management_ui_handler.cc` 的 `IDS_MANAGEMENT_*`(尤其 `IDS_MANAGEMENT_SUBTITLE_MANAGED_BY`)产品名串 → 闪现。组织名/域是策略数据驱动,**不动逻辑**。
- **工具栏/应用菜单「由组织管理」+ 管理图标 tooltip**:`chrome/browser/ui/managed_ui.cc` 的 `IDS_MANAGED_UI_*`。
- **手法**:并入既有 `.grd` / `.xtb` + `scripts/branding_strings.py` superset 清扫路径(与历史品牌 sweep 一致),**范围限定**于上述管理面串。
- 两层品牌不变:磁盘标识 `Teleport`、应用内显示 `闪现`。

## 6. 验证方式(dev 构建 + docker.lima fairyland 栈)

1. dev 构建:DM URL 默认已指本地 device-manager(账号体系 `teleport_use_release_endpoints=false` buildflag),无需命令行覆盖。
2. 起 fairyland 栈(docker.lima),经 `CreateEnrollmentToken` gRPC / seed 生成 per-tenant enrollment token。
3. 注入 token:`sudo defaults write /Library/Teleport/CloudManagementEnrollmentToken …` 或写 `/Library/Teleport/…` 文件 / `/Library/com.beansec.Teleport.plist`(模拟 MDM)。
4. 启动 dev 构建(**不再需要 `--disable-field-trial-config`**——已由 GN arg `disable_fieldtrial_testing_config=true` 构建期关掉;按需加 `--no-proxy-server`)。
5. 观察:机器 `register_browser` HTTP 200 + 机器 DMToken → 浏览器级签名策略 fetch 200 + 应用;`chrome://management` 文案/品牌正确;`chrome://policy` 显示 Cloud(机器级)与 Platform(MDM)两来源。

## 7. 测试

- `//teleport` 新常量件:gtest(常量值、路径拼接),TDD 红-绿-重构。
- patch 行为:以 §6 端到端活验为主(历史证明真 Chrome 能抓出单测掩盖的线协议/路径 bug)。
- 管理面品牌:可加最小串存在性 / 渲染检查。

## 8. 风险与未决(plan 阶段处理)

- **空 token 不误纳管**:核实 `IsEnabled()=true` 但无 token 时控制器 no-op。
- **固定基础域 vs per-channel side-by-side**:canary 与 stable 共享同一机器纳管域属预期(整机维度);核实不与 per-channel 数据目录 / `CrProductDirName` 冲突。
- **机器纳管(登录前)× 用户 OIDC 纳管(登录后)并存**:核实两条纳管路径与各自 DMToken / policy scope 不互相干扰。
- **路径权限**:`/Library/Teleport/` 需管理员写(MDM 场景天然满足);dev 手工注入需 `sudo`。

## 9. 参考

- 总纲:`docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`。
- L0 地基:`docs/superpowers/specs/2026-06-03-enterprise-account-system-design.md`(§6.1/§6.3 标注的两个推后 patch 即本 phase)。
- 能力盘点:`docs/research/2026-06-02-chromium-enterprise-modules.md`。
- 运行约定:项目记忆 `no-disable-field-trial-config-flag`(dev 运行不再加该参数)。
