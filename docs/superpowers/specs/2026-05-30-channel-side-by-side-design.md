---
title: 渠道并排共存设计(per-channel bundle ID / 名称 / 数据目录 / 图标)
date: 2026-05-30
status: designed
tags: [channel, side-by-side, bundle-id, signing, macos, branding]
---

# 渠道并排共存设计(per-channel bundle ID / 名称 / 数据目录 / 图标)

## 1. 背景与目标

「通道对齐」(见 `2026-05-30-channel-alignment-design.md`)已让 Teleport 的运行时
`version_info::Channel` 由打包期戳入的 `TeleportChannel` Info.plist 键驱动,
canary 渠道已端到端上线(当前 0.1.6)。但目前**所有渠道仍共用同一套磁盘身份**:
裸 bundle id `com.beansec.Teleport`、单一 app 名 `Teleport` / 显示名 `闪现`、
单一数据目录 `~/Library/Application Support/Teleport`、单一图标。

这导致两个问题,且是未来 beta / stable 落地的硬前置:

- **无法并排共存**:多个渠道 bundle id 相同 → macOS 视作同一 App,装不下两个;
  数据目录相同 → 即便能装也会互相踩 profile。
- **身份与渠道脱节风险**:渠道仅由 `TeleportChannel` 键表达,磁盘身份完全不区分。

**目标**:对齐 Chrome 在 macOS 上的多渠道身份逻辑——一个「渠道名」旋钮同时派生出
独立 bundle id 后缀、独立 app 名 / 显示名、独立数据目录、(可选)独立图标,使各渠道
能在同一台机器上并排安装与同时运行,互不干扰。

**非目标**:Windows / Linux / 国产 OS 的渠道身份(后续 phase);差异化渠道图标
(本期最低复用,见 §6);新增 beta / stable 渠道本身(本期仅打通机制 + 改造现网 canary)。

## 2. Chrome 的多渠道身份逻辑(基线参考)

源码核实自本仓库检出(M148, `chromium/src`):

核心模型:**只构建一份产物(= stable 基底),在打包 / 签名阶段把它「渠道定制」
派生成 N 个可并排共存的兄弟版本**。stable 即未加工的基底;beta/dev/canary 是
`channel_customize=True` 的派生体。所有维度由单一 `channel` 旋钮推导。

| 维度 | stable(基底) | beta/dev/canary(派生) | 源码出处 |
|---|---|---|---|
| bundle ID | `com.google.Chrome`(裸) | `base + '.' + channel` | `model.py:384-388` |
| 名称(磁盘+显示) | `Google Chrome` | `+ app_name_fragment` | `modification.py:76-81` |
| 数据目录 | 不设键 → 默认 `Google/Chrome` | `CrProductDirName = Google/Chrome <X>` | `modification.py:102` / `chrome_paths_mac.mm:31` |
| 图标 | 默认 `app.icns` | 打包期换 `app_<channel>.icns` + `Assets_<channel>.car` | `modification.py:151-156` |
| 运行时渠道 | `KSChannelID`(Keystone) | 同 | `channel_info_mac.mm`(GOOGLE_CHROME_BRANDING) |

关键事实:

- **数据目录的不对称**:stable 不设 `CrProductDirName`,运行时回退代码内默认值;
  其余渠道靠打包期显式注入该键才独立。`model.py:316-322` 用断言强制
  `channel_customize` 时必须同时具备「独立名 + 独立 creator code + 独立数据目录」,
  从机制上杜绝「换了 bundle id 却共用 profile」的半成品。
- **运行时渠道来源是专用键 `KSChannelID`,不是解析 bundle id**;bundle id 后缀只是
  「结果」。我们的 `TeleportChannel` 键就是这一模式的对齐版(去掉 Keystone 包袱)。
- **公开 Chromium 检出中并无 Beta/Dev/Canary 的 `Distribution` 定义**:`config.py:182`
  仅返回裸 `[Distribution()]`;真正四渠道配置在 Google 私有 `internal_config`
  (本检出确认不存在)。故 Teleport 的渠道矩阵需由我们自行定义。

## 3. 总体架构:复用上游 `channel_customize` 引擎

**决定性发现**:我们现行签名走 `sign_chrome.py --disable-packaging`。读 `pipeline.py`
确认:`disable_packaging` **只**跳过最后生成 .dmg/.pkg 的步骤(`pipeline.py:694`);
渠道定制 `customize_distribution` 在 `sign_all → _sign_and_maybe_notarize_distributions
→ _customize_and_sign_chrome` 中**无条件执行**(`pipeline.py:749, 83`)。

也就是说:**渠道定制引擎我们早已在调用**,只因 `config.distributions` 返回裸
`[Distribution()]`(无定制)而空跑。要做的不是接一条新流水线,而是**让
`distributions` 返回一个渠道定制版 `Distribution`**,引擎即自动完成:

- 改 bundle id 后缀、重命名 outer app、注入 `CrProductDirName`、换图标;
- 重写嵌套子组件(Alert Helper)的 bundle id、entitlements 的 app-id、
  重命名企业策略 manifest——这些「易手工漏掉的嵌套身份」全由引擎兜住。

**路线:复用引擎,而非手工 plutil 改键。** 代价是给 `modification.py` 打一个
「去 Keystone」补丁(§5),消除引擎中对 Keystone / Google 私有资产的硬依赖。

## 4. 运行时渠道来源:保留 `TeleportChannel` 键

**不改用「解析 bundle id 后缀」**,原因:**stable 与 dev / 从源码构建共用裸 bundle id
`com.beansec.Teleport`**。从后缀推导无法区分二者,会把 dev 误判为 STABLE
(危险回归——现状 dev 无键 → 诚实报 UNKNOWN)。Chrome 靠「无 `KSProductID` → unknown」
兜底,我们无 Keystone,没有该兜底。

故运行时渠道来源 = `TeleportChannel` 键(保持现状),C++ 侧
(`teleport_channel.{h,cc,_mac.mm}`)**零改动**。原先担心的「bundle id 与渠道键两个
独立来源、写错一个就脱节」——复用引擎后消失:`Distribution.channel` 这**一个**参数
同时驱动 bundle id 后缀(引擎)与 `TeleportChannel` 戳值(`_package.py`),脚本层
单一事实源,构造上不可能不一致。

## 5. `modification.py` 去-Keystone 补丁(本路线唯一代价)

`channel_customize=True` 时引擎会写若干 Keystone / Google 专有 Info.plist 键,
我们的包内无 Keystone(已核实:构建产物 `Teleport.app` 中
`KSProductID` / `KSChannelID` 均不存在)。需处理:

1. **`modification.py:82`** `app_plist[_KS_PRODUCT_ID] += '.' + dist.channel`:
   无 `KSProductID` 键 → KeyError(**致命**,必须 gate)。
2. **`modification.py:90-100`** KSChannelID 通道标签块:`KSProductID` 缺失时不报错,
   但会**凭空写入 `KSChannelID="canary"`**——一个我们整套设计刻意不使用的 Keystone
   键(运行时只读 `TeleportChannel`)。属噪声,一并 gate 掉以贯彻「去 Keystone」。

两处统一以 `if _KS_PRODUCT_ID in app_plist:` 门控(语义对齐
`channel_info_mac.mm:70`「无 KSProductID 即非 Keystone」)。该门控在 `KSProductID`
存在时(上游测试 fixture)行为完全不变,故上游签名单测仍绿。

**不需要处理的(已核实,与初版 spec 不同)**:

- **`_rename_enterprise_manifest`(`modification.py:267`)**:构建产物中
  `com.beansec.Teleport.manifest`(及其嵌套结构)**确实存在**,rename 会正常成功,
  **无需 gate**。
- **`_replace_icons`(`modification.py:266`)**:无条件要求
  `app_<channel>.icns` + `Assets_<channel>.car`,缺则 `FileNotFoundError`。
  **不改 `modification.py`**,改由 `_package.py` 在签名前把图标喂进 packaging 目录
  (§6.2)。图标文件名用**原始渠道名**(`app_canary.icns`),非 fragment。

补丁形式沿用「一文件一 patch」:新增
`patches/chrome/installer/mac/signing/modification.py.patch`,仅 gate 上述第 1、2 处。
验证靠应用补丁后运行上游 `signing/run_mac_signing_tests.py`(无需签名证书,
hermetic)。

## 6. 渠道配置注入与脚本改造

### 6.1 注入点:`chromium_config.py` 覆盖 `distributions`

`build_props_config.py` 由 GN 自动生成(注入 BRANDING + 版本):
`app_product='Teleport'`、`base_bundle_id='com.beansec.Teleport'`、
`is_chrome_branded()=False`。`ChromiumCodeSignConfig` 继承它(已 patch
`run_spctl_assess`)。

在 `chromium_config.py.patch` 中扩展,覆盖 `distributions`,按环境变量
`TELEPORT_SIGN_CHANNEL` 选择:

- `stable` 或未设 → `[Distribution()]`(裸基底,不定制,bundle id 保持裸)。
- `canary` → `[Distribution(channel="canary", app_name_fragment="Canary",
  product_dirname="Teleport Canary", creator_code="Cr24", channel_customize=True)]`。

`to_config`(`model.py:376-388`)据此自动派生 `app_product="Teleport Canary"`
(→ `Teleport Canary.app`)、`base_bundle_id="com.beansec.Teleport.canary"`。

> creator_code 复用现有 `Cr24`(`BRANDING` 中 `MAC_CREATOR_CODE`)。Chrome 给每渠道
> 不同 creator code 是历史习惯而非必需;`model.py` 仅要求 `channel_customize` 时
> `creator_code` 非空。

未来 beta / stable 仅在此表追加条目,无需改引擎或脚本。

### 6.2 图标:最低复用(满足引擎硬依赖)

本期不做差异化图标。`_package.py` 在调 `sign_chrome.py` 前,把构建产物
`out/.../Teleport.app/Contents/Resources/{app.icns,Assets.car}` 复制为 packaging
目录下的 `app_canary.icns` / `Assets_canary.car`,满足 `_replace_icons` 的硬依赖。
canary 与未来 stable 图标暂时相同。差异化(色调 / 角标)留作后续品牌决策——
当前 canary 是唯一活跃渠道,无并排区分需求。

### 6.3 `_package.py` / `package.py` 适配

1. **传渠道**:`sign_app` 调 `sign_chrome.py` 前,对可定制渠道设
   `TELEPORT_SIGN_CHANNEL=<channel.name>`。
2. **图标喂入**:见 §6.2,签名前复制。
3. **签名产物定位**:引擎输出变为 `Teleport Canary.app`(含空格),落于
   `_intermediate_work_dir_name` 子目录。该子目录名**不是**裸 `canary`,而是把
   `channel_customize`→`sxs`、channel、app_name_fragment、product_dirname、
   creator_code 用 `-` 连接(已核实 `pipeline.py:551-569`),canary 实为
   `sxs-canary-Canary-Teleport Canary-Cr24/`。故产物在
   `<output>/<该子目录>/Teleport Canary.app`。现有 `build_styled_dmg` 的 glob
   `*/Teleport.app` 需放宽为 `*/Teleport*.app`(一层深 + app 名含空格即可命中,
   无需关心子目录确切拼法;同时兼容旧 `stable/Teleport.app`)。实现期把该 glob
   抽成可单测的 `_find_signed_app(updates_dir)` 辅助函数。
4. **`TeleportChannel` 戳值不变**:`stamp_and_inject` 仍写 `TeleportChannel=canary`,
   与 bundle id 后缀同源于 `channel.name`。
5. **dmg 名**:`Teleport-<semver>.dmg` 不变(按 semver,跨渠道不撞)。

## 7. 测试与验证

- **pytest**:`_package.py` 的图标暂存(`stage_channel_icons`)、签名环境变量注入
  (`sign_app` 设 `TELEPORT_SIGN_CHANNEL`)、签名产物定位(`_find_signed_app` glob)、
  以及 `package.py` 把 `channel.name` 透传到这三处,均可单测。
- **`distributions` 覆盖无法 pytest**:`chromium_config.py` 的基类
  `build_props_config` 在源码树不存在(构建期才生成进「Teleport Packaging」),
  故该 patch 模块无法独立 import。其逻辑(~6 行、按 `TELEPORT_SIGN_CHANNEL` 派生
  Distribution)仅由真机冒烟验证(bundle id / 数据目录 / `chrome://version` 渠道行)。
  这是已知且明示的测试盲区,不静默掩盖。
- **上游签名单测**:应用两个 signing patch 后运行
  `chrome/installer/mac/signing/run_mac_signing_tests.py`,确保未破坏上游
  `modification_test.py` 等。
- **C++ gtest**:`teleport_channel` 现有测试无需改(运行时来源不变)。
- **真机冒烟**(不可单测,必须手验,补入 `scripts/smoke_check.md`):
  - canary 包 bundle id = `com.beansec.Teleport.canary`;
  - Finder 磁盘名 `Teleport Canary` / 显示名 `闪现 Canary`;
  - 数据目录 `~/Library/Application Support/Teleport Canary`;
  - `chrome://version` 渠道行 = canary;
  - **关键回归**:与裸 `com.beansec.Teleport`(未来 stable / 现网旧 canary)
    并排可同时运行(bundle id + 数据目录双独立)。

## 8. 现网 canary 迁移(0.1.6 → 改造后)

现网 canary 为裸 `com.beansec.Teleport`。改造后变 `com.beansec.Teleport.canary`:

- **bundle id 变更 → Sparkle 不会自动跨 id 升级**(Sparkle 按 bundle id 识别)。
  新 canary 首包需**手动重分发**给内部少数用户。
- **数据目录从 `Teleport` 变 `Teleport Canary` → 老 profile 不自动迁移**。
  内部用户少,可接受「重新登录」或手动拷贝旧目录。
- 记为已知一次性迁移成本。迁移完成后旧裸 id 的安装可自然淘汰。

## 9. 渠道身份映射总表(Teleport)

| 渠道 | bundle ID | 磁盘名 / 显示名 | 数据目录 | channel_customize |
|---|---|---|---|---|
| stable(未来) | `com.beansec.Teleport`(裸) | `Teleport` / `闪现` | `Teleport` | 否(基底) |
| beta(未来) | `com.beansec.Teleport.beta` | `Teleport Beta` / `闪现 Beta` | `Teleport Beta` | 是 |
| canary(本期) | `com.beansec.Teleport.canary` | `Teleport Canary` / `闪现 Canary` | `Teleport Canary` | 是 |
| dev | `com.beansec.Teleport`(裸) | `Teleport` / `闪现` | `Teleport` | 否 |

> 前缀 `com.beansec.Teleport` 为权威值(源自 `BRANDING` 的 `MAC_BUNDLE_ID`)。
> CLAUDE.md 与记忆中 `org.teleport.Teleport` 为旧错值,定稿后一并订正。

## 10. 受影响文件清单(实现期参照,非穷举)

- `patches/chrome/installer/mac/signing/chromium_config.py.patch`(扩展:覆盖
  `distributions`,按 `TELEPORT_SIGN_CHANNEL` 返回渠道定制 Distribution)。
- `patches/chrome/installer/mac/signing/modification.py.patch`(新增:gate 掉
  `KSProductID` 追加与 `_rename_enterprise_manifest`)。
- `scripts/_package.py`(传 `TELEPORT_SIGN_CHANNEL`、签名前复制渠道图标、放宽
  签名产物 glob)。
- `scripts/package.py`(把 `channel.name` 透传到签名步骤)。
- `scripts/tests/`(新增 distributions 选择与图标复制的 pytest)。
- `scripts/smoke_check.md`(新增 canary bundle id / 数据目录 / 并排三行)。
- `CLAUDE.md`(订正 bundle id 前缀 `org.teleport.Teleport` → `com.beansec.Teleport`;
  补记并排共存 gotcha)。
