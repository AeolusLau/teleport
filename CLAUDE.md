# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 说明:按用户全局偏好,本仓库的 Markdown 文档使用简体中文;代码、注释、提交信息、脚本、配置等其余产物一律使用英文。

## 产品

- 代号 `teleport`;中文名(暂定)**闪现**;英文名(暂定)**Teleport**。
- 基于 **Chromium 源码**自研的**企业安全浏览器**:作为受管端,接收并执行服务端集中下发的安全策略。

## 与 `fairyland` 的关系

- 服务端**不在本仓库**,在同级 `../fairyland`(公司全部服务端产品的 monorepo,本身是 B2B DSPM 平台,微服务架构)。
- 浏览器的策略下发后端将作为 fairyland 中的服务存在;**该服务代号、浏览器↔后端的策略协议均尚未定义**(见「待定/后续」)。改动任一端协议时务必同步另一端。
- fairyland 的工程约定是本项目基线参考:`../fairyland/CLAUDE.md`、`../fairyland/README.md`。

## 命名约定

fairyland 用**奇幻代号**作规范标识符(`sigil`/`realm`/`warden`/`prism`/`telepathy`/`seer`/`phantom`/`portal`)。`teleport`(闪现,"瞬移")延续此体系;新增模块/服务代号保持该风格,并在 GN 路径、C++ 命名空间、目录等各处统一(如 `//teleport`、`teleport::`)。

## 架构:Brave 式 Chromium overlay

- **不 fork 整个 Chromium**。上游 M148 由 depot_tools/gclient 检出到**仓库外**(gitignore 的 `chromium/`,可用 `$TELEPORT_CHROMIUM_DIR` 覆盖)。
- **加法为主**:`src/` 是 overlay 纯源码,构建期以符号名 **`teleport`** 链接进 `chromium/src/teleport`,成为 GN 模块 `//teleport`,经一个最小上游 patch 编进 chrome。
- **改上游为辅**:文本改动走 `patches/`(`git apply`),整文件/二进制资源走 `branding/`(覆盖拷贝)。
- 上游基线钉死在 `CHROMIUM_VERSION`(当前 **148.0.7778.180**);M150 非稳定,后续再升级。
- **当前进度**:macOS overlay 基础**已构建并验证**——品牌化 `Teleport.app`、自定义 `//teleport` 启动 banner、图标、单测均通过;**macOS canary 渠道包 + Sparkle 自动升级已端到端跑通**(签名/公证/样式 dmg/OSS 分发,实测 0.1.0→0.1.1 自动升级)。Windows/Linux/国产 OS/CI 为后续 phase。

## 仓库布局

```
src/                       overlay 源码 → 构建期链接为 chromium/src/teleport(GN //teleport)
  BUILD.gn                 //teleport:teleport(source_set)+ teleport_unittests(test)
  teleport.gni             共享 GN args/路径(teleport_enable_updater、sparkle 目录;供上游 BUILD.gn import)
  browser/teleport_startup.{h,cc,_unittest.cc}   启动 banner 钩子
  browser/mac/teleport_sparkle_user_driver.{h,mm}  无界面 SPUUserDriver:自动下载/暂存,进度喂 About 页,驱动升级指示
  browser/mac/teleport_updater.{h,mm}+_stub.cc   Sparkle 更新器入口(StartMacUpdater/CheckForUpdatesNow)
  browser/mac/teleport_update_buildstate.{h,mm}  暂存更新点亮工具栏升级指示(编进 chrome/browser,见 gotcha)
  browser/mac/teleport_version_updater.mm        VersionUpdater::Create() macOS 实现(编进 chrome/browser/ui,见 gotcha)
  common/teleport_channel.{h,cc,_unittest.cc}+_mac.mm  TeleportChannel plist 串 → version_info::Channel 映射
  common/teleport_version.{h,cc,_unittest.cc}+_mac.mm  About/chrome://version 显示版本(永不暴露 Chromium 版本号)
  common/teleport_url_scheme.{h,cc,_unittest.cc} teleport:// 方案别名 + teleport-urls 主机重写
  common/teleport_feed_url.{h,cc,_unittest.cc}   appcast feed 仅允许 https 校验
  gn/args/dev.mac.gn       开发期 GN args 模板(updater 关)
  gn/args/release.mac.gn   official 渠道 GN args 模板(updater 开)
scripts/                   Python 编排(系统 py 3.9 无 pytest → 用 uv)
  bootstrap.py             建/定位 chromium 检出 + 建两个链接(可 --skip-sync)
  sync.py                  gclient sync 到 CHROMIUM_VERSION + 版本校验
  apply_patches.py         应用 patches/ + branding/(幂等、fail-fast)
  generate_icons.py        brand/teleport.svg → macOS app.icns(经 uv 拉 resvg-py/icnsutil)
  branding_strings.py      rebrand chromium_strings.grd + zh .xtb 的产品/公司名(→ 闪现)
  fetch_sparkle.py         钉版本拉 Sparkle.framework(SHA256 校验,真实拷进检出)
  package.py               打包主入口:--channel(默认 dev,仅构建)/--distribute(发布,仅 main)
  _build.py                渠道注册表(dev/canary)+ autoninja 构建步骤
  _package.py              stamp 版本/注入 Sparkle 键 + 签名 .app + 样式 dmg(签名/公证/staple)
  _publish.py              发布护栏(分支/干净树/tag+feed 双查)+ appcast + OSS 上传 + 打 v<semver> tag
  _config.py               嵌套 [channel.x] 发布配置加载 + 分级 key 校验
  _release.py              发布 helper:semver 解析/比较 + appcast 护栏
  gen_dmg_background.py     重生 dmg 背景;dmg_settings.py/dmg_layout.py 为 dmgbuild 配置与窗口几何
  preview_dmg_window.py    本地预览 dmg 窗口布局做视觉 QA(不出 dmg)
  release_config.local.toml.example  发布配置样板(本地副本 gitignored)
  _lib.py, tests/          路径/链接 helper + pytest
  smoke_check.md           构建与冒烟检查清单
patches/                   一文件一 patch,镜像 chromium/src 路径(注入/启动钩子/BRANDING/strings)
branding/                  资源覆盖(整文件),镜像 chromium/src 路径(app.icns)
brand/teleport.svg         品牌源资产(手改这个;派生物由 generate_icons.py 产出)
CHROMIUM_VERSION           钉死的上游版本
docs/superpowers/{specs,plans}/   设计与实现计划
chromium/                  (gitignore)外部 chromium 检出
build/                     (gitignore)→ chromium/src/out 的符号链接(产物访问入口)
```

## 构建与测试命令(macOS,已验证)

前置:depot_tools 在 PATH、Xcode、`uv`;检出在仓库外时 `export TELEPORT_CHROMIUM_DIR=/abs/path/to/chromium`。

```bash
# 一次性 / 同步上游(首次去掉 --skip-sync 会完整 sync,数小时)
python scripts/bootstrap.py --skip-sync     # 建链接:src/teleport→src、build→chromium/src/out
python scripts/sync.py                       # gclient sync 到 CHROMIUM_VERSION 并校验

python scripts/apply_patches.py              # 应用 overlay(幂等)

# 构建(首次数小时;Siso、本地无 RBE)
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev chrome    # 产物 Teleport.app(亦在 <repo>/build/mac/arm64/dev/)

# 测试
uv run pytest                                # 工具脚本单测(仓库根运行)
autoninja -C out/mac/arm64/dev teleport_unittests && \
  "$TELEPORT_CHROMIUM_DIR"/src/out/mac/arm64/dev/teleport_unittests   # //teleport gtest

python scripts/generate_icons.py             # 改了 brand/teleport.svg 后重生成图标
# 冒烟验证清单见 scripts/smoke_check.md
```

### 渠道包 / 自动升级(canary,已端到端验证)

official 构建 + Sparkle 自动升级 + Developer ID 签名 + Apple 公证 + 样式 dmg + OSS 直连分发,已跑通(实测 0.1.0→0.1.1 自动升级)。前置:Developer ID Application 证书在 keychain、`xcrun notarytool store-credentials` 存好 profile、EdDSA 密钥(`<sparkle>/bin/generate_keys`)、`scripts/release_config.local.toml`(见 `.example`,gitignored)。

```bash
python scripts/fetch_sparkle.py                  # 钉版本拉 Sparkle.framework(SHA256 校验,落 ~/.cache/teleport/deps,真实拷贝进检出)
# PGO profile(release 已开 chrome_pgo_phase=2,Chrome + V8 builtins 均硬依赖)由 gclient sync
# 拉取:bootstrap.py 已把 checkout_pgo_profiles=True 写进 .gclient;改了开关后重跑一次 sync:
python scripts/sync.py                           # 触发 chromium DEPS 的两个 PGO hook(幂等)
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
printf '0.1.2\n' > TELEPORT_VERSION              # 每次发版 bump(semver,单调递增)并提交
uv run python scripts/package.py                          # 默认:本地打 dev 包(仅构建,不签名/不发布)
uv run python scripts/package.py --channel canary        # 本地渠道包:构建+签名+公证+样式dmg,不发布
uv run python scripts/package.py --channel canary --distribute  # 发布(仅 main):+appcast+上传OSS+打 v<semver> tag 并 push
python scripts/gen_dmg_background.py             # 改 dmg 文案/布局后重生背景(uv run --with pillow)
```

## 关键 gotcha

- **chromium 检出位置**:默认 `<repo>/chromium`,可用 `$TELEPORT_CHROMIUM_DIR` 覆盖——几百 GB 检出不该绑定在每个 worktree 里。
- **out 链接方向**:`<repo>/build → chromium/src/out`(**不可反向!** autoninja 从 out 目录向上找检出根,out 必须留在检出树内;曾因 out→build 反向链接导致构建失败)。
- **一文件一 patch**:每个 `.patch` 只改一个上游文件、文件名镜像其在 `chromium/src` 下的路径;顺序无关;同文件多处改动累加进同一 patch。
- **Python 工具链**:系统 python 是 3.9 且无 pytest;统一用 `uv`(`pyproject.toml` 中 `requires-python>=3.13`、`[tool.uv] package=false`)。
- **`.gitignore`**:用 `/build`(无尾斜杠)才能忽略 `build` 这个**符号链接**;`/chromium` 同理。
- **两层品牌**:磁盘/标识符 = `Teleport`(BRANDING `PRODUCT_FULLNAME` → `Teleport.app`、`com.beansec.Teleport`);应用内显示名 = `闪现`(`chrome/app/chromium_strings.grd` 的 `IDS_PRODUCT_NAME`);macOS 菜单/Finder 名 = `闪现`(`CFBundleDisplayName` 已覆盖)。
- **TDD 范围**:产品代码(`//teleport` C++)走 TDD(gtest);构建/工具脚本不强求 TDD,仅在有价值处务实地写 pytest。
- **源码 symlink**:`src/` 经符号链接挂进 `chromium/src/teleport`,M148 上 GN + clang 已验证可正常解析与编译(无需退路)。
- **M148 注入点**(实现期已确认):`chrome/browser/BUILD.gn` 的 `static_library("browser")` deps 加 `//teleport`;启动 banner 调用在 `chrome/browser/chrome_browser_main.cc` 的 `PreMainMessageLoopRun`。
- **运行 dev 构建加 `--disable-field-trial-config`**:dev 构建(`is_official_build=false`)会自动套用 `testing/variations/fieldtrial_testing_config.json`,强开一批实验特性,部分未完成会崩溃。已知:`UsePersistentCacheForCodeCache` 在加载页面时,生成代码缓存经沙箱 SQLite VFS 的 WAL 路径命中 `NOTREACHED` 而 abort。dev 运行加 `--disable-field-trial-config`(或精确 `--disable-features=UsePersistentCacheForCodeCache`)。**非 overlay 问题**,stable/official 构建不强开。
- **从 worktree 跑发布脚本必须 `export TELEPORT_CHROMIUM_DIR=...`**:否则 `_lib` 默认到 `<worktree>/chromium` 假路径(fetch_sparkle 会把框架桥到错误位置)。
- **Sparkle 集成**:GN arg `teleport_enable_updater`(official 开/dev 关);`fetch_sparkle.py` 把框架**真实拷贝**进检出 `//third_party/teleport_sparkle`(符号链接会被 GN 原样拷进 .app → dmg 内死链);框架链接 Sparkle 必须有 LC_RPATH(`//teleport` 的 `sparkle_rpath` config,`@loader_path/../../..`),否则启动即崩溃(`no LC_RPATH's found`);`frameworks` 直接设在 source_set 上(用 `all_dependent_configs` 会把 `-framework Sparkle` 泄漏进主 exe,触发 `verify_dynamic_libraries`)。
- **PGO(release 开,dev 关)**:`release.mac.gn` 设 `chrome_pgo_phase=2`(贴近生产性能;这是 official 无 PGO 包与正式 Chrome 的主要性能差)。`chrome_pgo_phase=2` 同时令 V8 `v8_enable_builtins_optimization` 自动开启,所以**两套 profile 都是构建硬依赖**:① Chrome 顶层 PGO(`chrome/build/pgo_profiles/`,`gn gen` 时 `update_pgo_profiles.py get_profile_path` 解析+断言,缺则 hard-assert);② V8 builtins PGO(`v8/tools/builtins-pgo/profiles/`,arm64 复用 `x64.profile`,该文件是 mksnapshot 的 build source 且带 `--abort-on-bad-builtin-profile-data`,缺则**构建步骤直接失败**,不会静默降级)。两者都**不随构建自动下载**,但都能由 `gclient sync` 拉:chromium 顶层 DEPS 有两个 hook(`update_pgo_profiles.py` + `v8/tools/builtins-pgo/download_profiles.py`),**均仅由 `checkout_pgo_profiles` 一个 var 门控**(`checkout_v8_builtins_pgo_profiles` 是 standalone V8 专用,这里用不上;且 `src/v8` 不在 chromium 的 `recursedeps` 里,V8 自己的 hook 不会跑)。`bootstrap.py` 已把 `checkout_pgo_profiles=True` 写进 `.gclient`,故 `python scripts/sync.py` 会一并拉好两套 profile(用 `src/third_party/depot_tools`)。PGO 会显著拉长 release 编译时间。
- **签名/公证**:复用 `chrome/installer/mac/signing`,入口是**生成的「Teleport Packaging」目录里的** `sign_chrome.py`(源码树那份缺 build_props);品牌/版本从 build_props 自动取(无需 fork 配置);patch 了 `chromium_config`(`run_spctl_assess=False`,公证前 spctl 必失败)、`signing.py`(codesign 加 `--force`,重签已签的 Sparkle)、`parts.py`(把 Sparkle 框架+Autoupdate+Updater.app+XPC 用我们的 Developer ID 重签,否则公证报「no secure timestamp / not a valid Developer ID」)。通知凭据经 `--notary-arg=--keychain-profile`。
- **dmg 样式**:用 `dmgbuild`(`scripts/dmg_settings.py` + `brand/dmg/background.tiff`)出背景/命名 Applications/卷图标,`format=ULMO`(lzma,~105MB);Chrome 自带 pkg-dmg 样式资源仅 Google 品牌有,故改走 dmgbuild。背景 CJK 字体 fallback 含 STHeiti(PingFang 不一定在,缺则 tofu)。
- **版本**:`TELEPORT_VERSION`(semver)单一事实来源,签名前 `plutil` 戳进 `CFBundleVersion`(Sparkle 比较版)+`CFBundleShortVersionString`;dmg 改名为 `Teleport-<semver>.dmg`(签名模块按 Chromium 版本命名会跨版本撞车);appcast 只列最新版(`package` 裁到当前 dmg,避免 `--maximum-deltas 0` 仍残留的 delta 悬挂引用)。 发布时给当前 commit 打 `v<semver>` annotated tag 并 push 到 remote(默认 origin);tag 在上传成功后才打,tag 或线上 feed 任一已含该版本即拒绝发布。
- **EdDSA 私钥**仅在 login keychain + 离线备份(`generate_keys -x`),**绝不入库**;丢失靠 Developer-ID 兜底的密钥轮换(仅 dmg、一次只换一个锚,绝不同时换 Developer ID 和 EdDSA)。Sparkle 用 Ed25519,Secure Enclave 只支持 P-256,故密钥不走 SEP。
- **OSS 直连(无 CDN,无自有域名)**:阿里云 OSS 关「阻止公共访问」+ 桶策略授匿名 `oss:GetObject` 于难猜路径前缀;上传用受限 RAM 用户的 ossutil(2.x 用 `--cache-control`,非 `--meta`);appcast 不缓存、dmg 长缓存 immutable。详见 `docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`。

- **渠道并排共存(per-channel 身份)**:各渠道身份由上游 `channel_customize` 引擎一键派生——bundle id 后缀(`com.beansec.Teleport` 裸=stable;`.canary`/`.beta`=其余)、app 改名(`Teleport Canary` / 显示名 `闪现 Canary`)、数据目录(Info.plist `CrProductDirName`,如 `Teleport Canary`)、图标。打包期 `_package.py:sign_app` 经环境变量 `TELEPORT_SIGN_CHANNEL` 驱动 `chromium_config.py` 的 `distributions` 覆盖;同一 channel 名同时驱动 bundle id 后缀与运行时 `TeleportChannel` 键(单一事实源)。**我们无 Keystone**:`modification.py.patch` 以 `if _KS_PRODUCT_ID in app_plist:` gate 掉 `KSProductID`/`KSChannelID` 写入(否则前者 KeyError、后者凭空植入脏键)。图标走最低复用:`stage_channel_icons` 把 `app.icns`/`Assets.car` 复制成 `app_<channel>.icns`/`Assets_<channel>.car` 喂给引擎硬依赖的 `_replace_icons`。签名产物落 `<output>/sxs-<channel>-…/Teleport <Fragment>.app`,`build_styled_dmg` 经 `_find_signed_app` 放宽 glob 定位。**bundle id 变更 → Sparkle 不跨 id 自动升级**:旧裸 id 的 canary 需手动重分发到新 `.canary` 包。

- **About 页 / 升级指示集成(跨 target 编译)**:`teleport_update_buildstate.{h,mm}`(启动时 `InstallUpdateReadyBuildStateBridge()`,须在 `StartMacUpdater()` 前调用)与 `teleport_version_updater.mm`(`VersionUpdater::Create()` 的 macOS 实现)虽物理在 `src/` 下,但经 `chrome/browser/BUILD.gn` 与 `chrome/browser/ui/BUILD.gn` 的 patch **编进 chrome target、不在 `//teleport` source_set**——它们要 include chrome 头(BuildState / VersionUpdater),放进 source_set 会造成 GN 依赖环。故这两个文件**不出现在 `src/BUILD.gn`**;改它们要动对应 patch,别往 `src/BUILD.gn` 加。About 页面板本身的改动在 `patches/chrome/browser/resources/settings/about_page/*`(版本展示、Sparkle check-for-updates、页脚链接)。

- **工具栏主菜单升级角标依赖 `enable_update_notifications`**:点亮「⋮ 菜单的重启更新角标」的唯一通道是 `BuildState::SetUpdate` → `UpgradeDetectorImpl` → `AppMenuIconController`。但 `UpgradeDetectorImpl::Init()` 里 `build_state->AddObserver(this)` 与 `InstalledVersionPoller` 整段包在 `#if BUILDFLAG(ENABLE_UPDATE_NOTIFICATIONS)`,而该 flag 上游默认 `= is_chrome_branded`(`//chrome/browser/buildflags.gni`)——非品牌构建恒为 0,detector **根本不订阅 BuildState**,我们 bridge 的 `SetUpdate()` 全程无效,角标永不亮(About 页却仍显示 Relaunch,因为它走另一条 VersionUpdater 通道)。我们有 Sparkle,故在 `gn/args/{release,dev}.mac.gn` 显式 `enable_update_notifications = true`。验证可纯本地、不发版:dev 构建用 `--simulate-critical-update`(经 InstalledVersionPoller 合成 BuildState 更新)即可秒亮角标(critical 红;普通更新走 1h 的 VERY_LOW 阈值后转绿)。副作用:同时编入 outdated-build 检测器(满 8 周对非受管/organic 构建提示;受管安装 `IsManaged()` 下不触发)。

## 目标平台

Windows、macOS、Linux(企业以 Windows 为主);未来适配国产 OS(鸿蒙等),MVP 暂不。**目前仅 macOS(Apple Silicon)跑通构建**。

## 开发工作流

- 分支:GitLab Flow,`main` 唯一事实来源;合并用 **rebase onto main + squash + fast-forward**(无 merge commit)。
- 文档:`docs/superpowers/specs/`(设计)、`docs/superpowers/plans/`(实现计划)。
- brainstorming:在新分支的独立 git worktree 进行,spec/plan/实现提交到该分支。
- CI:fairyland 用 Gitea Actions;**本仓库 CI 尚未建立**(后续)。

## 待定 / 后续 phase

- 后端服务代号(在 fairyland 内)、浏览器↔后端**策略下发协议**(传输/格式/鉴权)。
- Windows / Linux 构建(注入从 symlink 换 junction 或受管检出)、国产 OS 适配。
- ~~代码签名、打包、分发、自动更新~~ → **macOS canary 已完成**(Sparkle 自动升级 + Developer ID 签名 + Apple 公证 + 样式 dmg + OSS 分发,实测升级闭环)。剩:Windows/Linux 签名与分发、多通道(beta/stable)、全静默后台升级、未来企业版 Omaha 4。
- CI(构建缓存与产物策略)。
- patch 的创建/刷新/冲突处理工具链(当前只做「应用」)。
- 完整 rebrand(各平台图标/安装包等)。

## 参考材料

- 本仓库:`docs/superpowers/specs/2026-05-25-overlay-build-foundation-design.md`、`docs/superpowers/plans/2026-05-25-overlay-build-foundation.md`、`scripts/smoke_check.md`。
- 渠道包/自动升级:`docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`、`docs/superpowers/plans/2026-05-26-macos-canary-channel.md`、`docs/canary-install.md`。
- 同级:`../fairyland/CLAUDE.md`、`../fairyland/README.md`(服务端工程约定基线)。
