# 渠道对齐(version_info::Channel)+ dogfood→canary 改名 设计

- 状态:设计稿(待评审)
- 日期:2026-05-30
- 分支:`worktree-channel-alignment`
- 范围:仅 macOS(Apple Silicon)。Windows/Linux channel 解析为后续 phase。
- 关联:`docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`(Sparkle/打包/分发基线)、`docs/superpowers/specs/2026-05-29-about-page-polish-design.md`(升级提示徽标)。

## 1. 背景与目标

### 1.1 问题来源

About 页那次改动(2026-05)接通了工具栏/主菜单的升级提示徽标(经 `BuildState::SetUpdate`),但徽标只在升级「烦扰等级」升到一定档位后才出现。在我们当前的构建下,这意味着检测到更新后要**等约 2 天**徽标才亮。

根因:**非品牌构建下 `chrome::GetChannel()` 恒为 `version_info::Channel::UNKNOWN`**。

- `chrome/common/channel_info_mac.mm` 的 `GetChannelState()` 在非品牌(`#else`)分支硬编码返回 `{"", false}`;
- `GetChannelByName()` 中 `beta`/`dev`/`canary` 的解析全部位于 `#if BUILDFLAG(GOOGLE_CHROME_BRANDING)` 内;
- 故 `GetChannel() = GetChannelByName(GetChannelState().name)` 对我们永远是 `UNKNOWN`。

升级徽标时机(`upgrade_detector_impl.cc`,自检测到更新起算):VERY_LOW 1h(仅 canary/dev 亮)、LOW 2d(绿点,stable 首次可见)、ELEVATED 4d(黄)、HIGH 7d(红);每 20 分钟重估。所以 `UNKNOWN`(等同 stable 处理)要等 2 天;而 `DEV`/`CANARY` 1 小时即亮(`app_menu_icon_controller.cc` 的 `IsUnstableChannel()` = 通道为 DEV 或 CANARY)。

### 1.2 目标

让非品牌 Teleport 构建在**运行期上报真实的 `version_info::Channel`**,使所有 channel 感知的 Chrome 逻辑(升级提示时机、UI 标识、特性分叉等)按通道正确工作。借此把内部分发通道映射到 `CANARY`,徽标时机回到 1 小时档。

附带本期一并做:

1. **运营渠道 `dogfood` 更名为 `canary`**:消除「我们的运营渠道 `dev`」与「Chrome 枚举 `DEV`」的撞名隐患——只要 `canary→CANARY`、`dev→UNKNOWN`,我们就根本不用到 `version_info::Channel::DEV`,撞名不存在。
2. **钉死字段试验**:GN args 设 `disable_fieldtrial_testing_config = true`,令所有 `base::Feature` 回落编译默认,杜绝意外开启的实验特性,并永久根治 dev 构建的 `UsePersistentCacheForCodeCache` 崩溃。

### 1.3 关键前提调研(已在 M148 源码核实)

为确认「让 `GetChannel()` 返回真实通道」对我们这个**非品牌(`GOOGLE_CHROME_BRANDING` OFF)+ official(`is_official_build=true`)+ macOS** 画像是否安全,事前做了三项核实:

- **字段试验与 channel 正交。** 非品牌构建**不拉取** variations seed(`variations_service.cc` 的 `IsFetchingEnabled()` 受品牌门控,非品牌恒 `false`)→ 零台服务端试验。channel 只通过「seed 的 `study.filter.channel`」影响试验,而我们无 seed,故 **channel 对字段试验的影响为 0**。唯一的试验暴露面是编译进二进制的 `fieldtrial_testing_config.json`,它**只按 platform/form-factor 过滤、不看 channel**,且默认即便 official 也会应用——这正是 `--disable-field-trial-config` gotcha 的来源,用 GN arg `disable_fieldtrial_testing_config=true` 可编译期关死(详见 §3.4)。
- **UMA / 崩溃上报对我们 inert。** 两道编译期硬门各自即可阻断上报:非品牌 consent 恒 `false`;上报 URL 在公开 Chromium 里**故意留空**。channel 只影响采样率与报告标签,且 macOS 上采样 trial 未编译进来(仅 Win/Android)。故 channel 相关的 metrics/crash 行为**安全可忽略**。
- **改成 CANARY 不触发会致错的行为。** 穷举了 channel 的行为分叉(bucket E),过滤到「非品牌 macOS 真正生效且非 Google 账号功能」的极少:`data sharing` 端点(Google 协作功能,我们不用)、`Chrome Labs`/chrome://flags 实验 flag 可见性(内部 canary 可接受甚至想要)、`--disable-webrtc-encryption` 允许传播(仅显式加该 flag 才有意义)。两个经典 canary 坑均不咬我们:① mac 上**无** canary 不能设默认浏览器的硬限制(唯一相关代码在 `#if GOOGLE_CHROME_BRANDING`);② profile 目录名来自 Info.plist `CrProductDirName`,我们**不设此键**,`ProductDirName()` 硬编码 `"Teleport"`,channel 不会 fork profile。

> CANARY 与 DEV 对我们的实际差异极小:大部分「非稳定通道」行为按 `IsCanaryDev()`(CANARY 或 DEV 一视同仁)分组。选 CANARY 而非 DEV 纯为命名清晰。两者都会打开一批诊断插桩(GWP-ASAN 采样、2× perf 采样等),有轻微运行时开销,但数据不外发——对内部 canary 可接受(本地崩溃 dump 更丰富);未来 `stable→STABLE` 会全部关闭。

## 2. 渠道模型与映射

| teleport 运营渠道 | 含义 | `TeleportChannel` Info.plist 值 | `version_info::Channel` |
|---|---|---|---|
| `dev` | 本地源码构建(`is_official_build=false`),不分发 | 键缺失 | `UNKNOWN`("from source",诚实) |
| `canary` | 已分发,official + Sparkle 自动升级 | `"canary"` | `CANARY` |
| `beta`(未来) | 更广预发布受众 | `"beta"` | `BETA` |
| `stable`(未来) | 企业 GA | `"stable"` | `STABLE` |

整条阶梯**跳过 Chrome 的 DEV 档**,`DEV vs dev` 撞名彻底不存在。本期只实装 `dev`(本就 UNKNOWN)与 `canary`;`beta`/`stable` 仅在映射/配置层占位,**本期不打包发布**。

**bundle ID 全程保持 `org.teleport.Teleport` 不变。** per-channel bundle ID 与侧载并存(显示名「闪现 Canary」/独立图标/独立数据目录)解耦为**下一个特性**(见 §7)。

## 3. 组件与改动

### 3.1 运行期解析器(overlay C++,走 TDD)

- **`src/common/teleport_channel.{h,cc}`**:纯函数

  ```cpp
  namespace teleport {
  // Maps a TeleportChannel string to a runtime channel. Unknown/empty/"dev"
  // and any unrecognized value map to UNKNOWN (a from-source / unstamped build).
  version_info::Channel ChannelFromName(std::string_view name);
  }  // namespace teleport
  ```

  映射:`"canary"→CANARY`、`"beta"→BETA`、`"stable"→STABLE`、其余 `→UNKNOWN`。**纯函数,是 TDD 红→绿的对象。**

- **`src/common/teleport_channel_mac.mm`**:`std::string teleport::ReadChannelNameFromBundle()` —— 读主 bundle 的 `TeleportChannel` 键,缺失返回 `""`。
- **非 mac**:`teleport_channel.cc` 内提供 `ReadChannelNameFromBundle()` 的 `#if !BUILDFLAG(IS_MAC)` stub 返回 `""`(后续 phase 再接各平台来源),与现有 `teleport_version.cc` 同构。
- `src/BUILD.gn`:新增上述源文件与单测目标。

### 3.2 最小上游补丁 `patches/chrome/common/channel_info_mac.mm.patch`

一文件一 patch,镜像 `chrome/common/channel_info_mac.mm` 路径。两处非品牌(`#else`)落点改动:

1. `GetChannelState()` 的 `#else` 分支:`return ChannelState{"", false};` → `return ChannelState{teleport::ReadChannelNameFromBundle(), false};`
2. `GetChannelByName()` 的非品牌落点:`return version_info::Channel::UNKNOWN;` → `return teleport::ChannelFromName(channel);`

并在文件加 `#include "teleport/common/teleport_channel.h"`(与既有 overlay patch 同法)。

这样:

- `GetChannel() = GetChannelByName(GetChannelState().name)` 自然贯通,**139 个 channel 消费点一次点亮**;
- name→enum 的映射表只活在 `teleport::ChannelFromName`(DRY + 可单测);
- 键缺失 → name `""` → 非品牌下无 `""→STABLE` 规则(该规则在 `#if GOOGLE_CHROME_BRANDING` 内)→ 落 `UNKNOWN`,正确;
- `GetChannelName()`(返回 `channel.name`)随之返回 `"canary"`/`"beta"`/`"stable"`/`""`,供 chrome://version 等 UI 显示。

> 品牌分支(`#if GOOGLE_CHROME_BRANDING`)及 `SetChannelIdForTesting`/`ClearChannelIdForTesting` 等保持原样不动。

### 3.3 打包 stamp(`scripts/_package.py`)

- `stamp_and_inject()`(分发通道路径,与 `SUFeedURL` 注入同处)新增:`plutil -replace TeleportChannel -string <value>`,**签名前**注入(被代码签名覆盖,防篡改)。
- 注入值来自渠道注册表(见 §3.5);`dev` 走 `stamp_version_only()`,**不注入此键** → 运行期 `UNKNOWN`。

### 3.4 钉死字段试验(GN args)

- `src/gn/args/release.mac.gn` 与 `src/gn/args/dev.mac.gn` 均加:`disable_fieldtrial_testing_config = true`。
- 效果:`field_trial_util` 的 testing-config 应用块被编译掉,所有 `base::Feature` 回落各自 `FEATURE_ENABLED/DISABLED_BY_DEFAULT`。**无意外实验特性**;并**永久根治** dev 的 `UsePersistentCacheForCodeCache` 崩溃 → dev 运行**不再需要** `--disable-field-trial-config`(传了也是 no-op)。
- 注意:GN 关死后若传 `--enable-field-trial-config` 会硬退出(`ExitWithMessage`)——我们不传,无影响。

### 3.5 改名 `dogfood`→`canary`

- **渠道注册表 `scripts/_build.py`**:`CHANNELS` 键与 `Channel.name` 由 `"dogfood"`→`"canary"`;`out`(`out/mac/arm64/release`)、`distributable`、`targets` 不变。`_package.py` 注入的 `TeleportChannel` 值即取 `channel.name`(改名后恰为 `"canary"`)。
- **配置样例 `scripts/release_config.local.toml.example`**:`[channel.dogfood]`→`[channel.canary]`,示例 `feed_url`/`download_base_url`/`oss_upload_target` 路径段 `/dogfood/`→`/canary/`。
- **pytest**:`scripts/tests/test_build.py`、`test_config.py`、`test_package_cli.py` 中的 `"dogfood"` 与 `published … (dogfood)` 断言。
- **注释/docstring**:`scripts/_package.py`、`dmg_settings.py`、`dmg_layout.py`、`gen_dmg_background.py`、`preview_dmg_window.py`、`src/gn/args/release.mac.gn`。
- **overlay 测试夹具**:`src/common/teleport_feed_url_unittest.cc` 中示例 URL 的 `dogfood` 段。
- **文档(含历史 spec/plan,全量改活)**:`docs/canary-install.md`(原 dogfood-install.md 已重命名)及正文 URL;`docs/superpowers/specs|plans/*` 中所有 `dogfood` 字样;`CLAUDE.md`(进度note、命令块、文件指针)。要翻历史按对应 git tag `checkout`。
- **由用户手动维护(gitignored)**:`scripts/release_config.local.toml` 的 `[channel.dogfood]`→`[channel.canary]` + 三个真实路径键改 `.../canary/<token>/…`。

## 4. 数据流

1. **构建**:`autoninja -C out/mac/arm64/release chrome`(非品牌 official)——不烘 channel。
2. **打包**:`package.py --channel canary [--distribute]` → `_package.py` stamp Info.plist:version + `SUFeedURL` + `SUPublicEDKey` + **`TeleportChannel=canary`** → 签名 → 公证 → dmg。
3. **运行**:`chrome::GetChannel()` → `GetChannelState().name = ReadChannelNameFromBundle() = "canary"` → `GetChannelByName("canary") = ChannelFromName("canary")` → **`CANARY`**。
4. **生效**:`IsUnstableChannel() → true` → 升级徽标 1 小时档;chrome://version 通道行显示通道;其余 channel 消费点按 CANARY 行为。

## 5. 测试与边界

### 5.1 测试

- **gtest(TDD)**:`src/common/teleport_channel_unittest.cc` 覆盖 `ChannelFromName` 全分支:`canary→CANARY`、`beta→BETA`、`stable→STABLE`、`""`/`"dev"`/乱值 `→UNKNOWN`。
- **pytest**:改名后 `scripts/tests/*` 全绿。
- **冒烟(更新 `scripts/smoke_check.md`)**:① canary 包 chrome://version 通道行正确;② 移除「dev 运行需 `--disable-field-trial-config`」一条(已由 GN 钉死)。

### 5.2 边界与失败处理

- `TeleportChannel` 键缺失 / 乱值 → `UNKNOWN`(防御式,等同 from-source 行为)。
- 非 mac 平台 → stub 返回 `""` → `UNKNOWN`(后续 phase)。
- 字段试验与 channel 正交(已查实),CANARY 不引入实验特性。
- 未打包/裸构建无此键 → `UNKNOWN`,与「dev = 本地构建」语义一致。

## 6. 发布 / 迁移(操作性,随特性落地执行)

1. **OSS(用户操作)**:在桶 `fairyland-distribution` 建 `canary/<token>/` 前缀;桶策略加匿名 `oss:GetObject` 于该前缀;受限 RAM 用户加 `oss:PutObject`(按需 `GetObject`/`DeleteObject`)。token 可复用现有那段或新生成。
2. **版本**:`TELEPORT_VERSION` 升到 ≥ `0.1.5`(全局 tag `v0.1.4` 已存在;canary feed 全新,`assert_not_published` 不拦)。
3. **首发**:第一个 canary 包(Info.plist `SUFeedURL`=新 canary feed、`TeleportChannel=canary`)**手动分发**给内部用户;因 bundle ID 不变(`org.teleport.Teleport`),手动安装即**原地替换**旧 dogfood 装机;其 `SUFeedURL` 指向新 feed → 之后自动升级闭环。
4. **收尾**:确认全员迁移到 canary feed 后,删旧 `dogfood/` 对象与桶策略条目。

> 已知一次性代价:现存 dogfood 装机(`SUFeedURL` 仍指旧 `dogfood/` appcast)不会自动跨到 canary feed——内部用户极少,以本次手动分发解决。

## 7. 明确不做(本期范围外)

- **per-channel bundle ID / 侧载并存**:显示名「闪现 Canary」、独立图标、独立用户数据目录、签名模块 channel-customize——下一个特性单独 brainstorm,理想在 `stable` 首次发客户前落地(届时客户 stable 落 `org.teleport.Teleport`,内部 canary 迁到 `.canary`,一次迁移、仅内部)。
- **beta / stable 实际打包发布**:本期仅映射/配置占位。
- **Windows / Linux channel 解析**:非 mac 先 stub。
- **canary 改 bundle ID**:保持 `org.teleport.Teleport`。
