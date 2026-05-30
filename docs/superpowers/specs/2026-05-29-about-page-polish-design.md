# About 页优化设计：版本号 / 检查更新 / 底部链接

- 状态:设计稿(待评审)
- 日期:2026-05-29
- 范围:仅 macOS(Apple Silicon)。Windows/Linux 为后续 phase。
- 关联:`docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`(Sparkle/打包/分发基线)。

## 1. 背景与目标

当前 `chrome://settings/help`(About 页,中文名「关于 闪现」)与 `chrome://version` 存在三类问题:

1. **版本号是 chromium 的**(如 `148.0.7778.180`),应改为展示 Teleport 自己的版本(`TELEPORT_VERSION`,如 `0.1.3`),并隐藏 chromium 版本号。
2. **「检查更新」完全不可用**:上游 mac 实现 `version_updater_mac.mm` 走的是 chromium 自带 updater(Omaha 4 / `EnsureUpdater`),而我们用的是 Sparkle,二者未对接,所以点了无反应。需对接到既有 Sparkle 能力。
3. **底部链接缺失**:`Report an issue`、`Privacy policy`、`Terms of Service` 三项在 chromium(非 Google 品牌)构建里被 `_google_chrome` / `GOOGLE_CHROME_BRANDING` 守卫隐藏了,应显示出来,链接先用占位 URL。

附带(本次一并做):

4. **chrome://version 首行版本值**:名字已是「Teleport」但版本值仍是 chromium 版本号,一并改为 Teleport 版本。
5. **工具栏主菜单升级提示**:检查到更新但用户未重启时,点亮主菜单按钮小圆点 + 菜单「重启以更新」项(对接 Sparkle)。

### 目标

- About 页与 chrome://version 只展示 Teleport 版本号,绝不展示 chromium 版本号。
- About 页「检查更新」原生驱动 Sparkle:就地展示转圈/进度/「已是最新」/「重启以更新」,不弹 Sparkle 自带窗口。
- 工具栏/主菜单的「有新版本」提示与 Sparkle 联动。
- 三个底部链接可见;`Report an issue` 走原生反馈对话框,`Privacy policy`/`Terms of Service` 为外部占位 URL。

### 非目标

- 不改全局 `version_info::GetVersionNumber()`(User-Agent 的 `Chrome/148` 必须保持,否则伤网站兼容)。
- 不实现反馈上报的自有后端(后续单独对接;本次仅复用上游 `OpenFeedbackDialog`)。
- 不做 Windows/Linux。
- 不做 beta/stable 多通道、全静默后台升级等(沿用既有 canary 基线)。

## 2. 总体架构决策:Sparkle 统一为单一 updater(方案 A)

现状是两套并行入口:启动时 `teleport::StartMacUpdater()` 用 `SPUStandardUpdaterController` 做静默后台检查(已验证 0.1.x 自动升级)。本次「检查更新」需要一个能把状态喂回 About 页的 updater。

**决策:重构为单一 `SPUUpdater` 单例 + 自定义 `TeleportSparkleUserDriver`。** 后台检查走「静默路径」(行为同现在),About 页检查走「页面路径」(状态回灌 UI)。

理由:Sparkle 并不为「同一 app 两个 updater 实例」设计,双实例会出现重复下载/状态打架、`sessionInProgress` 互不可见。统一为单实例是正确架构。代价:要改动已跑通的后台升级代码,需回归验证升级闭环(见 §7 测试)。

`SPUStandardUpdaterController` 被弃用,改用:

```objc
SPUUpdater* updater = [[SPUUpdater alloc]
    initWithHostBundle:NSBundle.mainBundle
     applicationBundle:NSBundle.mainBundle
            userDriver:teleportUserDriver
              delegate:nil];
[updater startUpdater:&error];
```

后台静默:`-checkForUpdatesInBackground`(用户驱动在无活动 About 会话时静默处理,等价现状)。
用户发起:About 页触发 `-checkForUpdates`,用户驱动把状态回灌页面。

## 3. 功能设计

### 3.1 版本号展示(目标 1、4)

新增 `//teleport` 助手 `teleport::GetDisplayVersion()`(返回 `std::string`):

- 读主 bundle 的 `CFBundleShortVersionString`。
- **若读到的值等于编译期 chromium 版本**(`version_info::GetVersionNumber()`),说明该 bundle 未被 stamp(裸 `autoninja chrome`,未走 package.py),回退为占位符 `0.0.0-dev`。
- 否则返回 bundle 里的值(即 `TELEPORT_VERSION`)。

> 这样无需按 `is_official_build` 分支:dev/canary 经 package.py stamp 后都显示真实 Teleport 版本(见 §4.4 给 dev 补 stamp),只有未打包的裸构建才显示占位符,且任何情况下都不会暴露 chromium 版本号。

两个展示点覆盖(均在同一文件 `chrome/browser/ui/webui/version/version_ui.cc`):

- **About 页**:`VersionUI::GetAnnotatedVersionStringForUi()` 的第一个参数(版本号)替换为 `teleport::GetDisplayVersion()`。保留 `(正式版本)`(来自 `IsOfficialBuild()`)与 `(arm64)` 架构后缀——满足 release 展示「正式版本 + CPU 架构」;dev 自然显示「非正式版本」。
- **chrome://version**:`kVersion` 字段(`AddString(version_ui::kVersion, ...)`)替换为 `teleport::GetDisplayVersion()`。`kVersionSuffix`、`kVersionModifier`、`kUserAgent` 等保持不变(UA 仍是 chromium 148)。

### 3.2 检查更新对接 Sparkle(目标 2,原生嵌入)

新增 `//teleport` 类 `MacSparkleVersionUpdater : public VersionUpdater`,在 mac 上提供 `VersionUpdater::Create()`。自定义 `TeleportSparkleUserDriver`(实现 `SPUUserDriver` 协议)把 Sparkle 状态机映射到 About 页原生 UI:

| Sparkle 用户驱动回调 | 处理 / `VersionUpdater::Status` |
|---|---|
| `showUserInitiatedUpdateCheckWithCancellation:` | `CHECKING`(暂存 cancellation) |
| `showUpdateFoundWithAppcastItem:state:reply:` | reply `SPUUserUpdateChoiceInstall` 开始下载;记录 appcastItem 版本号备用 |
| `showDownloadDidReceiveExpectedContentLength:` | 记录总长度 |
| `showDownloadDidReceiveDataOfLength:` | `UPDATING` + 进度 |
| `showDownloadDidStartExtractingUpdate` / `showExtractionReceivedProgress:` | `UPDATING` |
| `showReadyToInstallAndRelaunch:` | **暂存 reply**;上报 `NEARLY_UPDATED`;调 `BuildState::SetUpdate(...)`(见 §3.3) |
| `showUpdateNotFoundWithError:acknowledgement:` | `UPDATED`(调 acknowledgement) |
| `showUpdaterError:acknowledgement:` | `FAILED`(调 acknowledgement) |
| `showInstallingUpdateWithApplicationTerminated:…` | `UPDATING` |
| `dismissUpdateInstallation` | 收尾清理 |

`PromoteUpdater()`(mac 接口要求)实现为空操作(Sparkle 无 per-user/system 提升概念,促销 UI 在 `about_page.html` 中仅 `_google_chrome` 下出现,我们不显示)。

构建接线:patch `chrome/browser/ui/BUILD.gn`——当 `teleport_enable_updater` 为真时,从 mac 源里移除上游 `webui/help/version_updater_mac.mm`(避免 `VersionUpdater::Create` 符号重复),改由 `//teleport` 提供;dev(updater 关)仍用上游实现。

### 3.3 工具栏 / 主菜单升级提示(目标 5)

Sparkle 是「退出时安装」,更新就绪时磁盘上的 .app 尚未替换,所以上游基于 `InstalledVersionPoller` 轮询磁盘版本的机制不会触发。改为主动驱动:

- 在 `showReadyToInstallAndRelaunch:` 时(更新已下载+解压、就绪),在 UI 线程调用
  `g_browser_process->GetBuildState()->SetUpdate(BuildState::UpdateType::kNormalUpdate, <appcast 版本>, std::nullopt)`。
- `UpgradeDetectorImpl` 监听 `BuildState`,据此点亮主菜单按钮小圆点(annoyance level)与菜单「重启以更新」项。
- `<appcast 版本>` 取自 `showUpdateFoundWithAppcastItem:` 记录的 `appcastItem.versionString`,解析为 `base::Version`。

### 3.4 重启接线(单一拦截点)

About 页「重启」按钮(`RelaunchMixin` → `BrowserLifetimeHandler::HandleRelaunch`)与主菜单「重启以更新」(`IDC_UPGRADE_DIALOG` → `OpenUpdateChromeDialog` → 确认后)**最终都汇到 `chrome::AttemptRelaunch()`**(`chrome/browser/lifetime/application_lifetime.cc`)。

故在 `chrome::AttemptRelaunch()` 一处拦截:

```cpp
void AttemptRelaunch() {
  if (teleport::InstallPendingUpdateAndRelaunchIfReady())
    return;          // Sparkle 接管:触发暂存的 reply -> 安装并重启
  AttemptRestart();  // 无待装更新时走原逻辑
}
```

`teleport::InstallPendingUpdateAndRelaunchIfReady()`:若存在 §3.2 暂存的就绪 reply,则以 `SPUUserUpdateChoiceInstall` 调用之(Sparkle 安装并重启),返回 `true`;否则返回 `false`。单点拦截覆盖 About 页 + 主菜单两个入口,且仅在有待装更新时改变行为,其它重启原因(如改 flag)不受影响。

### 3.5 底部链接(目标 3)

去掉 `_google_chrome` / `GOOGLE_CHROME_BRANDING` 守卫并补齐字符串/URL:

- **Report an issue**:显示;点击走现有 `openFeedbackDialog`(`chrome::OpenFeedbackDialog`,handler 本就常注册)。上报后端后续接自有服务(本 spec 不实现)。字符串 `IDS_SETTINGS_ABOUT_PAGE_REPORT_AN_ISSUE` 在 `settings_strings.grdp` 中已存在(全品牌可用),只是注入被守卫挡住。
- **Privacy policy**:显示;`ABOUT_PAGE_PRIVACY_POLICY_URL`(`about_page.ts` 内,原 `_google_chrome` 守卫)改为外部占位 URL。字符串 `IDS_SETTINGS_ABOUT_PAGE_PRIVACY_POLICY` 同样已存在。
- **Terms of Service**:显示;`aboutTermsURL` 改为外部占位 URL。**注意**:上游 `IDS_ABOUT_TERMS_OF_SERVICE` 在非 CfT 的 chromium 分支里是占位文案(「Not used in Teleport. Placeholder…」,见 `chromium_strings.grd`),不可直接复用——需提供真实标签字符串(英文源 `Terms of Service`,本地化后续补)。
- 「Get help with Chrome」已显示,保留不动。

占位 URL(统一定义、便于后续替换):

- Privacy policy:`https://teleport.example.com/privacy`
- Terms of Service:`https://teleport.example.com/terms`

## 4. Overlay 改动清单

### 4.1 新增 `//teleport` 源(`src/`)

- `common/teleport_version.h` —— `std::string teleport::GetDisplayVersion();`
- `common/teleport_version_mac.mm` —— mac 实现(读 `CFBundleShortVersionString` + 占位回退)。
- `common/teleport_version.cc` —— 非 mac 占位实现(返回 `version_info::GetVersionNumber()`,供后续平台;当前不编译进 mac)。
- `browser/mac/teleport_version_updater.h/.mm` —— `MacSparkleVersionUpdater` + `VersionUpdater::Create`。
- `browser/mac/teleport_sparkle_user_driver.h/.mm` —— `TeleportSparkleUserDriver`(`SPUUserDriver`)+ 暂存 reply / `InstallPendingUpdateAndRelaunchIfReady` / `BuildState` 接线。
- 重构 `browser/mac/teleport_updater.{h,mm}` —— 统一 `SPUUpdater` 单例;`StartMacUpdater` 静默路径与 About 页页面路径共用同一 updater 与用户驱动。
- `browser/mac/teleport_updater_stub.cc` —— 同步更新 updater 关闭时的桩(含新增导出符号的空实现)。
- `BUILD.gn` —— 注册新源到 `//teleport:teleport` 与 `teleport_unittests`;`teleport_enable_updater` 条件编入 mac updater 源。

### 4.2 patch(一文件一 patch,镜像 `chromium/src` 路径)

- `chrome/browser/ui/webui/version/version_ui.cc` —— About 页与 chrome://version 版本号改用 `teleport::GetDisplayVersion()`。
- `chrome/browser/ui/BUILD.gn` —— `teleport_enable_updater` 时移除 `version_updater_mac.mm`。
- `chrome/browser/lifetime/application_lifetime.cc` —— `AttemptRelaunch()` 加 Sparkle 待装更新拦截。
- `chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc` —— 无条件注入 `aboutReportAnIssue` / `aboutPrivacyPolicy` / `aboutProductTos` / `aboutTermsURL`(占位 URL)。
- `chrome/browser/resources/settings/about_page/about_page.html` —— 去掉 `reportIssue` / `privacyPolicy` 的 `_google_chrome` 守卫与 ToS 段的 `_google_chrome or _is_chrome_for_testing_branded` 守卫。
- `chrome/browser/resources/settings/about_page/about_page.ts` —— 去掉 `ABOUT_PAGE_PRIVACY_POLICY_URL`、`onReportIssueClick_`、`onPrivacyPolicyClick_` 的 `_google_chrome` 守卫;占位 URL。

### 4.3 字符串(ToS 标签)

`IDS_ABOUT_TERMS_OF_SERVICE` 在非 CfT 是占位,需提供真实标签。走既有品牌字符串路径:

- 优先:在 `scripts/branding_strings.py` 把 chromium 分支下该消息的占位文案替换为 `Terms of Service`(与现有 rebrand 流程一致),`aboutProductTos` 继续用 `IDS_ABOUT_TERMS_OF_SERVICE`;或
- 备选:patch `settings_strings.grdp` 新增 `IDS_SETTINGS_ABOUT_PAGE_TERMS_OF_SERVICE`(英文源,本地化回退),`aboutProductTos` 改用之。

实现期二选一(倾向前者,改动更小、复用既有 ID)。

### 4.4 打包脚本(给 dev 补 stamp)

`scripts/package.py` 的 dev(非 distributable)路径在 `build()` 后增加轻量 stamp:用 `plutil` 把 `CFBundleShortVersionString` 与 `CFBundleVersion` 写为 `TELEPORT_VERSION`(复用/抽取 `_package.py` 现有 stamp 逻辑的纯版本部分,**不**注入 Sparkle 键、**不**签名)。

## 5. 数据流

```
[启动] applicationDidFinishLaunching
  -> teleport::StartMacUpdater()  // 统一 SPUUpdater 单例 + TeleportSparkleUserDriver
     -> checkForUpdatesInBackground()  // 静默;就绪则 BuildState::SetUpdate 点亮主菜单

[About 页] connectedCallback -> refreshUpdateStatus
  -> AboutHandler::CheckForUpdate -> VersionUpdater::CheckForUpdate (MacSparkleVersionUpdater)
     -> SPUUpdater checkForUpdates -> TeleportSparkleUserDriver 回调
        -> StatusCallback(status, progress, ...) -> FireWebUIListener("update-status-changed")
        -> 就绪时:暂存 reply + 上报 NEARLY_UPDATED + BuildState::SetUpdate

[重启](About 按钮 或 主菜单升级项)
  -> chrome::AttemptRelaunch()
     -> teleport::InstallPendingUpdateAndRelaunchIfReady()
        -> 暂存 reply(SPUUserUpdateChoiceInstall) -> Sparkle 安装并重启
     -> 否则 AttemptRestart()
```

## 6. 错误处理与边界

- **未打包裸构建**:`GetDisplayVersion()` 检测到 bundle 版本 == 编译期 chromium 版本 → 显示 `0.0.0-dev`,不暴露 chromium 版本号。
- **feed 不可用 / 非 https**:沿用既有 `IsSecureFeedUrl` 校验;`StartMacUpdater` 无 feed 时不启动 updater。About 页检查在 updater 未就绪时上报 `FAILED` 或 `DISABLED`(实现期确定:无安全 feed → `DISABLED`)。
- **重复点击检查更新**:`SPUUpdater.sessionInProgress` 防重入;会话进行中再次点击复用当前会话状态。
- **下载进度无增量**:mac 常报 0%,沿用上游对 0% 的处理(显示「正在更新」而非「0%」)。
- **用户取消**:`showUserInitiatedUpdateCheckWithCancellation:` 暂存的 cancellation 在页面关闭/再次操作时按需调用。
- **AttemptRelaunch 拦截**:仅当存在就绪待装更新才接管,避免影响其它重启场景(改 flag、企业策略等)。

## 7. 测试

### 7.1 `//teleport` gtest(`teleport_unittests`,走 TDD)

- `GetDisplayVersion()`:bundle == chromium 版本 → 占位 `0.0.0-dev`;bundle 为其它值 → 原值返回。(用可注入的版本读取点以避免真实 bundle 依赖。)
- Sparkle 状态 → `VersionUpdater::Status` 映射:逐个回调断言映射正确(checking/updating+progress/nearly_updated/updated/failed)。
- 暂存 reply 逻辑:`InstallPendingUpdateAndRelaunchIfReady()` 在有/无待装更新时的返回值与副作用。

### 7.2 脚本 pytest(务实)

- `package.py` dev 路径 stamp:断言 dev 构建后 `plutil` 写入了 `TELEPORT_VERSION`(可对 stamp 纯函数做单测)。

### 7.3 手动冒烟(补进 `scripts/smoke_check.md`)

1. dev(经 package.py):About 页显示 `版本 <TELEPORT_VERSION>(非正式版本) (arm64)`;chrome://version 首行值为 Teleport 版本。
2. 裸 `autoninja chrome`:About 页显示 `0.0.0-dev`,不出现 chromium 版本号。
3. canary 打包:版本行显示 `正式版本` + `arm64` + Teleport 版本。
4. 检查更新-无更新:转圈 → 「已是最新版本」。
5. 检查更新-有更新:转圈 → 下载/更新进度 → 「重启以更新」按钮出现;主菜单按钮小圆点 + 菜单「重启以更新」项出现。
6. 点 About「重启」或主菜单升级项 → Sparkle 安装并重启到新版本(端到端,沿用 0.1.x 升级验证方式)。
7. 三个链接:Report an issue 打开反馈对话框;Privacy policy / Terms of Service 打开占位 URL。
8. 回归:静默后台升级闭环仍正常(架构 A 重构后重点回归项)。

## 8. 待办占位(后续替换)

- Privacy policy / Terms of Service 真实 URL。
- 反馈上报自有后端。
- ToS / 新增标签的多语言翻译(`.xtb`)。
- Windows/Linux 对应实现。
