# 设计:品牌全面替换(闪现 / Teleport · BeanSec)

- 状态:已评审通过(brainstorming),待转 implementation plan
- 日期:2026-05-25
- 代号:teleport(闪现 / Teleport)
- 子项目:#1 之后的「品牌全面替换」(MVP 只做了产品名串 + macOS app 图标,本轮做全)

## 1. 背景与目标

当前构建出的浏览器里,**绝大多数图标仍是 Chromium 的图标、文案仍写着 "Chromium"**(MVP 只换了 `IDS_PRODUCT_NAME` 与 macOS `app.icns`)。本轮把 **macOS + 跨平台公共资产**的图标与文案**全部替换**为我方品牌,并按语言本地化命名。

## 2. 范围

**做(本轮)**:
- macOS 可见 + 跨平台公共的产品 logo / 图标(从 `brand/teleport.svg` 标记生成);
- `chromium_strings.grd` 体系里所有会显示的独立 "Chromium" 产品名文案,按语言本地化;
- 公司/作者文案(`The Chromium Authors` 等)→ 本地化公司名;
- 整合并取代 MVP 的相关 patch。

**不做(后续 phase)**:
- Windows 专属图标(`win/*.ico`、`tiles/*`)、Linux 专属(`linux/*.xpm` 等)——各自构建 phase 再做;
- 正式 wordmark(文字标)设计——本轮文字标位先用标记顶上;
- `product_logo_22_mono` / `product_logo_name_22_white` 的精细单色/白色版(尽力而为);
- zh-TW 公司全称法务确认;非 zh 语言的中文化(其余语言一律 Teleport/BeanSec)。

## 3. 命名规则(贯穿全程)

| | zh-CN | zh-TW | 其他语言 |
|---|---|---|---|
| 产品名 | 闪现 | 閃現 | Teleport |
| 公司名 | 北京小豆数安科技有限公司 | 北京小豆數安科技有限公司 | BeanSec |

ASCII 标识符层(非本地化,用于磁盘/构建产物):
- 磁盘 `.app` / 可执行名 / `PRODUCT_FULLNAME` = `Teleport`;
- macOS `MAC_BUNDLE_ID` = **`com.beansec.Teleport`**(反向域名用公司域 beansec);
- `BRANDING` 的 `COMPANY_FULLNAME` / `COMPANY_SHORTNAME` = `BeanSec`。

## 4. 总体方式

- **图片**:机械——`brand/teleport.svg` 标记渲染出全部目标尺寸/格式,经 `branding/`(资源覆盖,镜像 `chromium/src` 路径)替换上游图片。
- **文案**:**sync 后脚本现场变换**(不走逐条静态 patch,以适配上游升级)。核心利用 grit `.xtb` 的 `<translation id>` = 源文本指纹的特性:改英文源后,非中文语言的 .xtb 自动失配 → 回退英文 = Teleport/BeanSec(正合要求);只需重写 zh-CN/zh-TW 两个 .xtb 并按新源指纹重算 id。

## 5. 图片替换

扩展 `scripts/generate_icons.py`(或新增 `scripts/generate_branding_images.py`),从 `brand/teleport.svg` 渲染并写入 `branding/` 下镜像路径(由 `apply_patches.py` 的资源覆盖拷入 `chromium/src`):

目标文件(`chrome/app/theme/...` 下):
- `chromium/product_logo_{16,24,48,64,128,256}.png`、`chromium/product_logo.svg`、`chromium/product_logo_22_mono.png`(单色尽力而为);
- `default_100_percent/chromium/product_logo_{16,32}.png`;
- `default_100_percent/chromium/product_logo_name_22{,_white}.png`(文字标位:**先用标记**,`_white` 用白色化变体尽力而为);
- macOS:`chromium/mac/app.icns`(已完成,纳入统一生成)+ `chromium/mac/Assets.xcassets/AppIcon.appiconset/appicon_{16,32,64,128,256,512,1024}.png` + `Icon.iconset/*`(+ 新版 `AppIcon.icon/*` 尽力);
- `chromium/product_logo_animation.svg`(加载动画)**本轮不动**,保留(非高优)。

> 上面无平台子目录的 `chromium/product_logo_*` 与 `default_100_percent/` 是跨平台公共资源(macOS UI 亦取用),在本轮;`linux/`、`win/`、`chromeos/` 子目录均为平台专属,**不在本轮**。确切尺寸/路径以 M148 真实目录为准(§11)。

## 6. 字符串变换:`scripts/branding_strings.py`

在 `apply_patches.py` 之后运行(或并入其流程),对 `chromium/src` 现场变换,**幂等、fail-fast**:

### 6.1 英文源 `chrome/app/chromium_strings.grd`
- **词边界替换**独立 `Chromium` → `Teleport`;
- `The Chromium Authors` / `Chromium Authors` → `BeanSec`;
- 把产品名相关、上游标了 `translateable="false"` 的消息(至少 `IDS_PRODUCT_NAME`、`IDS_SHORT_PRODUCT_NAME`)**翻转为 `translateable="true"`**,使 zh 译文能生效;
- **排除**(不替换):`ChromiumOS`、`chromium.org` 及其他 URL、`Chromium Projects`、许可证/法律文本里的项目专名等。排除规则用明确的正则 + 例外清单实现。

### 6.2 仅重写 `zh-CN.xtb` / `zh-TW.xtb`
(`chrome/app/resources/chromium_strings_{zh-CN,zh-TW}.xtb`)
- 译文正文里 `Chromium` → `闪现` / `閃現`;作者/公司 → 中文公司名;同 §6.1 的排除规则;
- **按变换后的英文源消息重算 `<translation id>`**:用 **in-tree grit 指纹函数**(`tools/grit/grit/extern/FP.py` 一带,具体入口实现期确认)。流程:对每条被改的消息,算其「旧英文源指纹」(= 旧 xtb 现有 id)与「新英文源指纹」,建立 `old_id → new_id` 映射,据此改写 zh xtb 的 id,并对其译文做产品名/公司名替换。
- 结果:zh-CN/zh-TW 命中新 id → 显示中文(已替换品牌);其余语言无对应 id → 回退新英文源 = Teleport/BeanSec。

### 6.3 其他语言
~100 个其他 `.xtb` **不动**;源文本变更后自动失配并回退英文(Teleport/BeanSec),正合要求。

## 7. 与现有 overlay 的整合

- **删除** `patches/chrome/app/chromium_strings.grd.patch`(MVP 里硬编码 `IDS_PRODUCT_NAME→闪现` 的那条)——职责并入 §6 脚本,统一本地化。
- **更新** `patches/chrome/app/theme/chromium/BRANDING.patch`:
  - `PRODUCT_FULLNAME` / `PRODUCT_SHORTNAME` = `Teleport`(不变);
  - `MAC_BUNDLE_ID` = **`com.beansec.Teleport`**(原 `org.teleport.Teleport`,本轮改);
  - `COMPANY_FULLNAME` / `COMPANY_SHORTNAME` = `BeanSec`(原 MVP 设为 `Teleport`,本轮改)。
- 启动 banner、`//teleport` 注入、macOS `Info.plist`(`CFBundleDisplayName`)等 patch 不变;`branding/` 图标覆盖扩充为 §5 全集。

## 8. 错误处理

- `branding_strings.py`:目标文件缺失/不可解析 → fail-fast 明确报错;指纹函数加载失败(grit 路径变化)→ 报错并提示;替换 0 命中(疑似上游已变)→ 警告。
- `apply_patches.py`/资源覆盖:沿用既有幂等 + fail-fast。

## 9. 验证(macOS 构建)

1. 关于页:zh-CN 显示「关于 闪现」「北京小豆数安科技有限公司」;切到 en 显示 "About Teleport"、"BeanSec";
2. 应用图标、NTP、设置等各处 product logo = 我方标记;
3. 抽查若干深层字符串:zh = 闪现 / en = Teleport;
4. 确认 `ChromiumOS`、`chromium.org` 等**未被破坏**;
5. 抽查一个其他语言(如 ja)= Teleport/BeanSec;
6. `MAC_BUNDLE_ID` = `com.beansec.Teleport`(`PlistBuddy` 验证)。

固化进 `scripts/smoke_check.md`。

## 10. 测试 / TDD

变换脚本影响最终产品文案 → 写 pytest(产品相关工具,务实地测关键逻辑):
- 词边界替换正确(`Chromium`→`Teleport`,但 `ChromiumOS`/`chromium.org`/`Chromium Projects` 不动);
- grit id 重算与 in-tree grit 对同一文本一致(用小样例);
- zh xtb 重写后 `old_id→new_id` 映射正确、译文已本地化;
- 幂等(重复跑结果一致)。
图片生成与整构建/视觉由 §9 冒烟覆盖。

## 11. 实现期需对照 M148 源码确认的点

- grit 指纹函数确切入口与调用方式(`tools/grit` 下);
- `translateable="false"` 的产品名消息完整清单(除 `IDS_PRODUCT_NAME`/`IDS_SHORT_PRODUCT_NAME` 外是否还有);
- 排除清单的完整集合(扫描 grd 里所有非产品名的 `Chromium*` 用法);
- 各图片确切路径/尺寸(尤其 macOS 新版 `AppIcon.icon` 格式是否需要、`appiconset` 是否为实际取用源);
- 公司名相关消息 id(`IDS_ABOUT_VERSION_COMPANY_NAME` 等)是否 translateable。

## 12. 非目标 / 后续 phase

Windows/Linux 平台专属图标(`.ico`/tiles/`.xpm`)、正式 wordmark 设计、`_mono`/`_white` 精细变体、`product_logo_animation`、zh-TW 公司法务确认、其余语言的本地化。
