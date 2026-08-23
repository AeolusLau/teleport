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

- **不 fork 整个 Chromium**。上游由 depot_tools/gclient 检出到**仓库外**,默认按发布分支派生到 `$TELEPORT_CHROMIUM_ROOT/<MAJOR.MINOR.BUILD>`(取 `CHROMIUM_VERSION` 前三段;`$TELEPORT_CHROMIUM_ROOT` 默认 `~/workspace/chromium`),`$TELEPORT_CHROMIUM_DIR` 仍可整体覆盖(见「关键 gotcha」);仓库内 gitignore 的 `chromium/` 是早期 M148 检出的原地位置,现由符号链接接入这套派生规则。
- **加法为主**:`src/` 是 overlay 纯源码,构建期以符号名 **`teleport`** 链接进 `chromium/src/teleport`,成为 GN 模块 `//teleport`,经一个最小上游 patch 编进 chrome。
- **改上游为辅**:文本改动走 `patches/`(`git apply`),整文件/二进制资源走 `branding/`(覆盖拷贝)。
- 上游基线钉死在 `CHROMIUM_VERSION`(当前 **151.0.7922.76**);升级流程见 `docs/chromium-upgrade-runbook.md`。
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
  gn/args/dev.mac.gn       开发期 GN args 模板(updater 关,env=dev)
  gn/args/staging.mac.gn   staging 渠道模板(链式 import release.mac.gn,仅覆盖 env=staging)
  gn/args/release.mac.gn   official 渠道 GN args 模板(updater 开,env=release)
  gn/args/dev.win.gni      Windows dev 的架构无关参数(**非模板**,供下面两个 import)
  gn/args/dev.win.x64.gn   Windows x64 dev 模板(→ out/win-x64-dev;企业实装架构)
  gn/args/dev.win.arm64.gn Windows arm64 dev 模板(→ out/win-arm64-dev;ARM64 宿主原生跑)
scripts/                   Python 编排(系统 py 3.9 无 pytest → 用 uv)
  bootstrap.py             建/定位 chromium 检出 + 建两个链接(可 --skip-sync)
  sync.py                  gclient sync 到 CHROMIUM_VERSION + 版本校验
  apply_patches.py         应用 patches/ + branding/(幂等、fail-fast)
  check_upstream_release.py  查 Chrome VersionHistory API 判定「同分支有新 PATCH」/「里程碑已跃迁」/「已最新」,驱动升级走哪条路径
  rebase_overlay.py        里程碑升级核心:在新检出上把 overlay 从旧基线 tag 三方合并(rebase --onto)到新基线 tag
  export_patches.py        rebase 完成后从检出重新导出 patches/(三分类安全阀:patch/branding/生成物,漏分类即报错)
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
keys/*.pub.pem             四把策略验签根公钥锚(dev / staging / release 主根 / release 恢复根);
                           由 gen_policy_verification_key.py 生成并校验补丁内容
branding/                  资源覆盖(整文件),镜像 chromium/src 路径(app.icns)
brand/teleport.svg         品牌源资产(手改这个;派生物由 generate_icons.py 产出)
CHROMIUM_VERSION           钉死的上游版本
docs/superpowers/{specs,plans}/   设计与实现计划
docs/cross-repo/           与 fairyland 的跨仓对话留痕(密钥交付、契约确认、联合验收证据)
chromium/                  (gitignore)外部 chromium 检出
build/                     (gitignore)→ chromium/src/out 的符号链接(产物访问入口)
```

## 构建与测试命令(macOS,已验证)

前置:depot_tools 在 PATH、Xcode、`uv`。检出位置默认按发布分支派生:`$TELEPORT_CHROMIUM_ROOT/<MAJOR.MINOR.BUILD>`(取 `CHROMIUM_VERSION` 前三段,`$TELEPORT_CHROMIUM_ROOT` 默认 `~/workspace/chromium`);`$TELEPORT_CHROMIUM_DIR` 仍可整体覆盖派生结果(向后兼容 / CI)。详见「关键 gotcha」与 `docs/chromium-upgrade-runbook.md`。

```bash
# 每个新 shell 先建立环境(见「关键 gotcha」「chromium 检出位置」):
unset TELEPORT_CHROMIUM_DIR                                                          # 确认没有残留覆盖
export TELEPORT_CHROMIUM_ROOT="${TELEPORT_CHROMIUM_ROOT:-$HOME/workspace/chromium}"  # 下面命令按字面展开这个变量,必须先导出

# 一次性 / 同步上游(首次去掉 --skip-sync 会完整 sync,数小时)
python scripts/bootstrap.py --skip-sync     # 建链接:src/teleport→src、build→chromium/src/out
python scripts/sync.py                       # gclient sync 到 CHROMIUM_VERSION 并校验

python scripts/apply_patches.py              # 应用 overlay(幂等)

# 构建(首次数小时;Siso、本地无 RBE)
uv run python scripts/package.py             # dev 一键:args.gn 缺失时自动 gn gen,再 autoninja + 烘焙版本校验
# 等价手动路径(gn gen 仅首次需要,out 目录建好后 ninja 会自动 re-gen):
cd "$TELEPORT_CHROMIUM_ROOT"/<release_branch>/src   # <release_branch> = CHROMIUM_VERSION 前三段,如 151.0.7922;设了 $TELEPORT_CHROMIUM_DIR 则直接 cd 到它
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev chrome    # 产物 Teleport.app(亦在 <repo>/build/mac/arm64/dev/)

# 测试
uv run pytest                                # 工具脚本单测(仓库根运行)
autoninja -C out/mac/arm64/dev teleport_unittests && ./out/mac/arm64/dev/teleport_unittests   # //teleport gtest
uv run python scripts/gen_policy_verification_key.py --check   # 补丁烘焙 key ↔ 公钥锚一致性(apply_patches 亦自动前置执行)

python scripts/generate_icons.py             # 改了 brand/teleport.svg 后重生成图标
# 冒烟验证清单见 scripts/smoke_check.md
```

### 上游发布跟踪 / 基线升级(完整流程见 `docs/chromium-upgrade-runbook.md`)

```bash
uv run python scripts/check_upstream_release.py
# 三选一结论:已最新 / 同发布分支有新 PATCH(路径 A,复用检出)/ 上游已切新发布分支(路径 B,新检出+完整 rebase)

# 路径 B 专用(里程碑升级):新检出建好之后即可直接跑——不要提前手动跑 apply_patches.py
uv run python scripts/rebase_overlay.py --from-tag <old-tag> --onto-tag <new-tag>   # 三方合并 overlay 到新基线,停在真实冲突处
uv run python scripts/export_patches.py --tag <new-tag>                             # rebase 干净后重新导出 patches/
```

`rebase_overlay.py` 用 `git rebase --onto`(而非 `git merge`)把 overlay 从旧基线 tag 迁到新基线 tag,只让「我们的改动」× 「旧→新上游 delta」参与合并;`export_patches.py` 对导出结果做三分类安全阀(patch / branding / 生成物),分类不到的改动直接报错,防止静默漏导出。二者均要求 overlay 在**跳过品牌重写**(`apply_patches.py --skip-branding`)的树上操作,细节与踩过的坑见 runbook。**`rebase_overlay.py` 自己会 `git checkout -B` 到旧基线 tag、再以 `--skip-branding` 跑一遍 `apply_patches.py` 建立待 rebase 的 overlay 提交**——这一步是脚本内部流程,不是调用前的手动前置步骤;在旧基线 tag 上提前手动跑 `apply_patches.py` 不但多余,还会让脚本在 M151 tag 上重复应用 M151 patch 而 fail-fast,留下一棵局部应用的脏树(runbook §G1 为准)。

### 渠道包 / 自动升级(canary,已端到端验证)

official 构建 + Sparkle 自动升级 + Developer ID 签名 + Apple 公证 + 样式 dmg + OSS 直连分发,已跑通(实测 0.1.0→0.1.1 自动升级)。前置:Developer ID Application 证书在 keychain、`xcrun notarytool store-credentials` 存好 profile、EdDSA 密钥(`<sparkle>/bin/generate_keys`)、`scripts/release_config.local.toml`(见 `.example`,gitignored)。

```bash
python scripts/fetch_sparkle.py                  # 钉版本拉 Sparkle.framework(SHA256 校验,落 ~/.cache/teleport/deps,真实拷贝进检出)
# PGO profile(release 已开 chrome_pgo_phase=2,Chrome + V8 builtins 均硬依赖)由 gclient sync
# 拉取:bootstrap.py 已把 checkout_pgo_profiles=True 写进 .gclient;改了开关后重跑一次 sync:
python scripts/sync.py                           # 触发 chromium DEPS 的两个 PGO hook(幂等)
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'   # 可省:package.py 在 args.gn 缺失时自动执行
# 注:staging 档**已解锁**(fairyland 于 2026-08-13 交付真实 staging 根,`teleport_staging_policy_key_is_real=true`),
# 无需任何逃生口即可 gn gen。release 档仍被占位主根的 fail-closed assert 挡住(TD-026);
# **canary 渠道走 release.mac.gn,env 即 release,故 canary 构建当前一并被挡**——
# 「canary 已端到端验证」说的是历史上跑通过,不是现在就能发。
# 只想验证流水线机制时,加具名逃生口 —— 产物会被烙上 TeleportUnpublishable 且 --distribute 硬拒:
#   gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn") teleport_policy_key_placeholder_ack=true'
uv run python scripts/gen_policy_verification_key.py --check                 # 四把根 ↔ patch ↔ hash 一致性
uv run python scripts/gen_policy_verification_key.py --check --require-real --env release   # 额外拒绝占位根(release 档当前必然失败,这就是它的作用)
uv run python scripts/gen_policy_verification_key.py --check --require-real --env staging   # staging 已是真实根,应当通过
printf '<new-version>\n' > TELEPORT_VERSION       # 每次发版 bump(四段 MAJOR.MINOR.BUILD.PATCH,严格大于当前 TELEPORT_VERSION,单调递增;或用 scripts/bump_version.py)并提交
uv run python scripts/package.py                          # 默认:本地打 dev 包(仅构建,不签名/不发布)
uv run python scripts/package.py --channel canary        # 本地渠道包:构建+签名+公证+样式dmg,不发布
uv run python scripts/package.py --channel canary --distribute  # 发布(仅 main):+appcast+上传OSS+打 v<semver> tag 并 push
uv run python scripts/package.py --channel staging               # staging 本地包(env=staging,不受 TD-026 阻塞)
uv run python scripts/package.py --channel staging --rehearse    # 演练:真实端点全链、发布级守卫,唯独不打 tag(可从特性分支跑)
python scripts/gen_dmg_background.py             # 改 dmg 文案/布局后重生背景(uv run --with pillow)
```

### Windows(P1 进行中:目标是 `chrome.exe` 编出来)

完整搭建步骤、ARM64 宿主专项、与 macOS 的差异一览见 **`docs/windows-build-setup.md`**。

```powershell
$env:DEPOT_TOOLS_WIN_TOOLCHAIN='0'          # 用本机 VS,别拉 Google 内部工具链
# TELEPORT_CHROMIUM_ROOT 指向大容量卷(如 D:\workspace\chromium);别设 TELEPORT_CHROMIUM_DIR

uv run python scripts/bootstrap.py --skip-sync   # 建两条链接:注入链接=符号链接(需开发者模式),build/=junction
uv run python scripts/apply_patches.py           # overlay,幂等
uv run pytest                                    # 工具脚本单测

Set-Location $env:TELEPORT_CHROMIUM_ROOT\151.0.7922\src
# 在 ARM64 宿主上先验 arm64、再验 x64:x64 产物只能模拟跑,拿结论慢;且绝大多数坑与架构无关。
# 不要并行两个全量构建——16 vCPU + 模拟工具链,并行只会互相拖慢。
gn gen out/win-arm64-dev --args='import("//teleport/gn/args/dev.win.arm64.gn")'
gn gen out/win-x64-dev   --args='import("//teleport/gn/args/dev.win.x64.gn")'
autoninja -C out/win-arm64-dev obj/teleport/teleport/teleport_startup.obj  # 快速验证:只编我们的 TU(35 个,分钟级)
autoninja -C out/win-arm64-dev chrome                # 主构建
autoninja -C out/win-arm64-dev teleport_unittests    # 注意:闭包 ~45.8k 步,约等于 chrome 的七八成
# arm64 全绿之后再走一遍 x64(-C out/win-x64-dev)
```

**`package.py` 在 Windows 上不可用**(dev 分支写死 `Teleport.app`),打包/签名/分发/自动升级整条链路是后续 phase。

## 关键 gotcha

- **chromium 检出位置**:默认按**发布分支**派生,`$TELEPORT_CHROMIUM_ROOT/<MAJOR.MINOR.BUILD>`(取 `CHROMIUM_VERSION` 前三段;`$TELEPORT_CHROMIUM_ROOT` 默认 `~/workspace/chromium`)——几百 GB 检出不该绑定在每个 worktree 里,且换分支时路径自动跟着 `CHROMIUM_VERSION` 变化,不用手改任何变量。`$TELEPORT_CHROMIUM_DIR` 仍可整体覆盖这条派生规则(向后兼容 / CI),但**一旦设置就覆盖一切**——每次执行升级相关脚本前先 `unset TELEPORT_CHROMIUM_DIR` 确认它是空的,否则会悄悄对着上一次会话残留的旧路径操作而不报错。同一发布分支内的 PATCH 级安全补丁(如 `.76 → .132`)复用同一检出目录;里程碑跃迁(`MAJOR`/`BUILD` 变化)落到新目录,旧检出(含全部构建缓存)原地保留作回退底座,永不迁移或删除。完整流程见 `docs/chromium-upgrade-runbook.md`。
- **上游 tag ≠ 已发布**:`chromium/src` 仓库里的 git tag 不能用来判断某版本是否真的对外发布过——上游从每条发布分支(`refs/branch-heads/<BUILD>`)再切子分支(如 `7871_48`、`7871_183`),各自独立递增 `PATCH` 号,tag 日期与编号也不单调。判断「是否真的发布」用 Chrome VersionHistory API(`scripts/check_upstream_release.py` 已封装),不要扫 tag 列表。
- **桌面 Mac/Win 同线、Linux 取子集**:实测 M151 已发布序列 Mac 与 Win64 完全一致(`.76 .75 .72 .71 .47 .34`),Linux 是同一序列的子集(`.75 .71`)——桌面三平台共用同一条发布线,故**单一 `CHROMIUM_VERSION` pin 服务全部桌面平台是正确的**,不需要按平台分别维护;Linux 落后不构成问题(同一分支源码,只是比 Google 推给 Linux 用户的多带若干还没轮到 Linux 的修复)。`check_upstream_release.py` 若报 mac/win64 版本不一致会显式告警,届时需人工判断。
- **out 链接方向**:`<repo>/build → chromium/src/out`(**不可反向!** autoninja 从 out 目录向上找检出根,out 必须留在检出树内;曾因 out→build 反向链接导致构建失败)。
- **一文件一 patch**:每个 `.patch` 只改一个上游文件、文件名镜像其在 `chromium/src` 下的路径;顺序无关;同文件多处改动累加进同一 patch。
- **Python 工具链**:系统 python 是 3.9 且无 pytest;统一用 `uv`(`pyproject.toml` 中 `requires-python>=3.13`、`[tool.uv] package=false`)。
- **`.gitignore`**:用 `/build`(无尾斜杠)才能忽略 `build` 这个**符号链接**;`/chromium` 同理。
- **两层品牌**:磁盘/标识符 = `Teleport`(BRANDING `PRODUCT_FULLNAME` → `Teleport.app`、`cn.douan.Teleport`);应用内显示名 = `闪现`(`chrome/app/chromium_strings.grd` 的 `IDS_PRODUCT_NAME`);macOS 菜单/Finder 名 = `闪现`(`CFBundleDisplayName` 已覆盖)。
- **TDD 范围**:产品代码(`//teleport` C++)走 TDD(gtest);构建/工具脚本不强求 TDD,仅在有价值处务实地写 pytest。
- **源码 symlink**:`src/` 经符号链接挂进 `chromium/src/teleport`,M148、M151 上 GN + clang 均已验证可正常解析与编译(无需退路)。
- **上游注入点会随里程碑漂移,每次升级需重新核对**:M148 上 `//teleport` 的 sources/deps 挂在 `chrome/browser/BUILD.gn` 的 `static_library("browser")`;M151 把该 target 拆分,**改挂 `source_set("core")`**(`static_library("browser")` 已无自有 sources,只在文件里剩一段解释 GN 循环依赖机制的注释,提到它作为历史示例,不代表真实构造)。启动 banner 调用未受影响,仍在 `chrome/browser/chrome_browser_main.cc` 的 `PreMainMessageLoopRun`。下次升级前先按这个模式(`grep '"//teleport"' chrome/browser/BUILD.gn` 找当前挂载的 target 名)重新核对,不要假设名字不变。
- **fieldtrial_testing_config 已在构建期关掉(运行不再加 `--disable-field-trial-config`)**:dev 构建(`is_official_build=false`)原本会自动套用 `testing/variations/fieldtrial_testing_config.json`,强开一批实验特性,部分未完成会崩溃(已知:`UsePersistentCacheForCodeCache` 在加载页面时,生成代码缓存经沙箱 SQLite VFS 的 WAL 路径命中 `NOTREACHED` 而 abort)。**现已由 GN arg `disable_fieldtrial_testing_config = true`(`src/gn/args/{dev,release}.mac.gn`,commit `69bac78`)在构建期把每个 `base::Feature` 钉到编译默认值,永久修掉该 abort**——故运行时**不再需要** `--disable-field-trial-config`(传了也是 no-op),也无需 `--disable-features=UsePersistentCacheForCodeCache`。**非 overlay 问题**,stable/official 构建本就不强开。
- **~~从 worktree 跑发布脚本必须 `export TELEPORT_CHROMIUM_DIR=...`~~ 已不成立**:旧版 `_lib.chromium_dir()` 默认落到 `<worktree>/chromium` 假路径,当年必须显式覆盖才能避免 `fetch_sparkle` 把框架拷到错误位置。现在 `chromium_dir()` 默认按发布分支从 `CHROMIUM_VERSION` 派生(见「chromium 检出位置」gotcha),从任意 worktree 运行都会解析到同一份正确的共享检出,**不再需要**为此设置该变量。唯一仍然合法的场景是主动覆盖成一个非标准路径(CI 隔离环境、临时指向另一份检出做对比测试)——这种场景下用完必须 `unset`,否则就是「chromium 检出位置」gotcha 警告的那种残留污染,会让脚本悄悄对着错误检出操作。
- **Sparkle 集成**:GN arg `teleport_enable_updater`(official 开/dev 关);`fetch_sparkle.py` 把框架**真实拷贝**进检出 `//third_party/teleport_sparkle`(符号链接会被 GN 原样拷进 .app → dmg 内死链);框架链接 Sparkle 必须有 LC_RPATH(`//teleport` 的 `sparkle_rpath` config,`@loader_path/../../..`),否则启动即崩溃(`no LC_RPATH's found`);`frameworks` 直接设在 source_set 上(用 `all_dependent_configs` 会把 `-framework Sparkle` 泄漏进主 exe,触发 `verify_dynamic_libraries`)。
- **跨 out 目录零编译复用是结构性的,不是配置疏漏(2026-08-14 查清)**:`use_remoteexec = false` 在 siso 里**同时**关掉远程执行与缓存——二者不是两件事。siso 确实自带 `-local_cache_enable` / `-cache_dir`(默认 `~/Library/Caches/siso`),`autoninja` 也原样透传(`autoninja.py:549-550`),但直接调用会报 `need to run siso login`(缓存后端 = RBE 的 CAS),而无 RBE 时 autoninja 自动加 `--offline`,offline 下缓存读写被整条跳过(实测:显式 `-cache_dir` 到新路径后仍零文件)。**故新建一个 out 目录 = 一次全量编译**,哪怕旁边就有一个只差一个 buildflag 头的完整 out 目录(实测 staging 首次 57511 步、`cached` 命中 0)。要拿回复用只有:①接入 RBE;②装 ccache 走 `cc_wrapper`(须先验证 PGO 的 `-fprofile-instr-use` 是否被正确纳入 hash)。**别再重新排查「siso 不是有缓存吗」——答案是有,但够不着。** 注:同目录增量构建不受影响,发版 bump 版本号走的是增量。

- **PGO(release 开,dev 关)**:`release.mac.gn` 设 `chrome_pgo_phase=2`(贴近生产性能;这是 official 无 PGO 包与正式 Chrome 的主要性能差)。`chrome_pgo_phase=2` 同时令 V8 `v8_enable_builtins_optimization` 自动开启,所以**两套 profile 都是构建硬依赖**:① Chrome 顶层 PGO(`chrome/build/pgo_profiles/`,`gn gen` 时 `update_pgo_profiles.py get_profile_path` 解析+断言,缺则 hard-assert);② V8 builtins PGO(`v8/tools/builtins-pgo/profiles/`,arm64 复用 `x64.profile`,该文件是 mksnapshot 的 build source 且带 `--abort-on-bad-builtin-profile-data`,缺则**构建步骤直接失败**,不会静默降级)。两者都**不随构建自动下载**,但都能由 `gclient sync` 拉:chromium 顶层 DEPS 有两个 hook(`update_pgo_profiles.py` + `v8/tools/builtins-pgo/download_profiles.py`),**均仅由 `checkout_pgo_profiles` 一个 var 门控**(`checkout_v8_builtins_pgo_profiles` 是 standalone V8 专用,这里用不上;且 `src/v8` 不在 chromium 的 `recursedeps` 里,V8 自己的 hook 不会跑)。`bootstrap.py` 已把 `checkout_pgo_profiles=True` 写进 `.gclient`,故 `python scripts/sync.py` 会一并拉好两套 profile(用 `src/third_party/depot_tools`)。PGO 会显著拉长 release 编译时间。
- **签名/公证**:复用 `chrome/installer/mac/signing`,入口是**生成的「Teleport Packaging」目录里的** `sign_chrome.py`(源码树那份缺 build_props);品牌/版本从 build_props 自动取(无需 fork 配置);patch 了 `chromium_config`(`run_spctl_assess=False`,公证前 spctl 必失败)、`signing.py`(codesign 加 `--force`,重签已签的 Sparkle)、`parts.py`(把 Sparkle 框架+Autoupdate+Updater.app+XPC 用我们的 Developer ID 重签,否则公证报「no secure timestamp / not a valid Developer ID」)。通知凭据经 `--notary-arg=--keychain-profile`。
- **dmg 样式**:用 `dmgbuild`(`scripts/dmg_settings.py` + `brand/dmg/background.tiff`)出背景/命名 Applications/卷图标,`format=ULMO`(lzma,~105MB);Chrome 自带 pkg-dmg 样式资源仅 Google 品牌有,故改走 dmgbuild。背景 CJK 字体 fallback 含 STHeiti(PingFang 不一定在,缺则 tofu)。
- **版本**:`TELEPORT_VERSION`(四段 MAJOR.MINOR.BUILD.PATCH)单一事实来源;`apply_patches.py` 经 `generate_version.py` 把它现场生成进检出 `chrome/VERSION`(内容比较跳过写入,避免无谓全量重编;`chrome/VERSION` 在检出里是"生成物"而非 patch),同时从 `CHROMIUM_VERSION` 生成 `components/version_info/teleport_engine_version.h`(untracked)供 UA/UA-CH patch 引用——**UA 恒为引擎版本**(当前 `Chrome/151.0.0.0`,随 `CHROMIUM_VERSION` 升级同步变化),产品版本绝不进 UA。打包**不再 stamp 版本**(`assert_baked_version` 校验烘焙版本==TELEPORT_VERSION,不符拒绝打包);`CFBundleVersion` 经 `tweak_info_plist.py` patch 为完整四段(上游 `BUILD.PATCH` 跨 minor 非单调,会断 Sparkle 升级)。dmg 名 `Teleport-<四段>.dmg`,发布打 `v<四段>` tag;appcast 只列最新版。bump 后必须重跑 `apply_patches.py` 再构建(VERSION 变更触发大范围重编,发版构建本为全量)。`MAJOR=0` 会踩上游脚本的真值判断坑——已 patch `components/policy/tools/generate_policy_source.py` 与 `tools/flags/generate_unexpire_flags.py`(`is None` 判空 + `m >= 0` 里程碑过滤),升基线若这两处冲突需按同语义重解;另有三处已知残余(扩展 minimum_chrome_version 门 / flags 过期失效 / 政策过滤超集)见 TD-015。
- **版本号语义:标识源码,不标识产物**。产物身份 = **(版本号 × 环境)**。三条规则:①**跨渠道可以同号**,且同号**应当**意味着同一份源码——这正是"staging 上验过的源码就是 release 要发的那份"的可追溯性来源(tag 命名空间 `_publish.tag_name` + 每渠道独立 feed 保证不冲突;Sparkle 也不跨 bundle id 升级);②**同一渠道内严格单调**,由 `assert_not_published`(渠道命名空间 tag + 该渠道 feed max version)双查;③**同一个版本号必须对应同一份源码**——这才是真约束,不是"跨渠道不能重复";源码换了就必须换号,哪怕换到另一个渠道。规则的实现散落在三处,完整表述见 spec `2026-08-10-deployment-env-tristate-design.md` §4.5。

- **`package.py --rehearse`:演练发布**。对渠道的**真实端点**跑完整链(构建→签名→公证→dmg→appcast→上传),只省略 **tag**;**所有守卫保持发布级强度**(`distributing=True`),与 `--distribute` 互斥。**演练会真实消耗版本号**并留下 Apple 公证记录——`--rehearse` 跳过的是"声明这是正式发布",不是"假装什么都没发生";能退回版本号就等于在版本管理上走了捷径,而不走捷径正是演练的意义。2026-08-14 首次演练即用它跑通 `0.2.0.0 → 0.2.0.1` 真实 Sparkle 自动升级。

- **演练/发布路径的两条经验(2026-08-14 实跑得来)**:①**`--dry-run` 的计划必须反映本次调用的真实行为**——它曾在 `--rehearse` 下仍打印 `git tag`、且把 tag 名写死 `v<ver>` 而非渠道命名空间;会误导人的 dry-run 比没有更糟,所以它现在还一并显示签名账户/endpoint/region(最易配错且最难发现的三项)。②**`assert_clean_tree` 对 staging 也不可放宽**(即使 `assert_on_main` 已为 staging 放宽):脏树会让 `TeleportSourceRevision` 指向一棵不复存在的树,而 staging 没有 release tag,该 stamp 是**唯一**能把产物回溯到 commit 的东西——演练中它正是靠 `7dc7d1a` vs `2505419` 的差异证明了"装上的是下载来的新包而非缓存"。

- **EdDSA 私钥**仅在 login keychain + 离线备份(`generate_keys -x`),**绝不入库**;丢失靠 Developer-ID 兜底的密钥轮换(仅 dmg、一次只换一个锚,绝不同时换 Developer ID 和 EdDSA)。Sparkle 用 Ed25519,Secure Enclave 只支持 P-256,故密钥不走 SEP。
- **ossutil 凭据/region 必须显式传参(两个静默陷阱)**:① **`~/.ossutilconfig` 优先于环境变量** —— 在发布过其它渠道的机器上 `export ALIBABA_CLOUD_ACCESS_KEY_*` 会被静默忽略,请求以错误 RAM 用户发出,表现为针对目标桶的 `AccessDenied … does not belong to you`,**极易被误判成对方授权配错**(本项目已因此误报并撤回过一次跨仓 BLOCKER)。② **ossutil 2.x 用 SigV4** —— 只给 `-e` 而不给 `--region`,签名 region 仍取自配置文件,报 `Invalid signing region in Authorization header`。故 `upload_to_oss` 把 `-i`/`-k`/`-e`/`--region` **全部显式传参**,凭据缺失即硬失败;`oss_endpoint`/`oss_region` 是每渠道必需键(canary 桶在 beijing、staging 演练桶在 hangzhou,无法有默认值)。凭据永不入配置文件,只经环境变量传入。

- **OSS 直连(无 CDN,无自有域名)**:阿里云 OSS 关「阻止公共访问」+ 桶策略授匿名 `oss:GetObject` 于难猜路径前缀;上传用受限 RAM 用户的 ossutil(2.x 用 `--cache-control`,非 `--meta`);appcast 不缓存、dmg 长缓存 immutable。详见 `docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`。

- **渠道并排共存(per-channel 身份)**:各渠道身份由上游 `channel_customize` 引擎一键派生——bundle id 后缀(`cn.douan.Teleport` 裸=stable;`.canary`/`.beta`=其余)、app 改名(`Teleport Canary` / 显示名 `闪现 Canary`)、数据目录(Info.plist `CrProductDirName`,如 `Teleport Canary`)、图标。打包期 `_package.py:sign_app` 经环境变量 `TELEPORT_SIGN_CHANNEL` 驱动 `chromium_config.py` 的 `distributions` 覆盖;同一 channel 名同时驱动 bundle id 后缀与运行时 `TeleportChannel` 键(单一事实源)。**我们无 Keystone**:`modification.py.patch` 以 `if _KS_PRODUCT_ID in app_plist:` gate 掉 `KSProductID`/`KSChannelID` 写入(否则前者 KeyError、后者凭空植入脏键)。图标走最低复用:`stage_channel_icons` 把 `app.icns`/`Assets.car` 复制成 `app_<channel>.icns`/`Assets_<channel>.car` 喂给引擎硬依赖的 `_replace_icons`。签名产物落 `<output>/sxs-<channel>-…/Teleport <Fragment>.app`,`build_styled_dmg` 经 `_find_signed_app` 放宽 glob 定位。**bundle id 变更 → Sparkle 不跨 id 自动升级**:旧裸 id 的 canary 需手动重分发到新 `.canary` 包。**平台策略读取域跨渠道恒为基础 id `cn.douan.Teleport`**(patch `chrome_browser_policy_connector.cc`,镜像上游 Chrome 品牌构建恒读 `com.google.Chrome` 的行为):上游策略键(BrowserSignin 等)与 Teleport 自有键(DeploymentDomain / 纳管 token)同一偏好域,一份 MDM payload 配置全部渠道;`.canary`/`.beta` 后缀域**不再**被策略加载器读取。

- **About 页 / 升级指示集成(跨 target 编译)**:`teleport_update_buildstate.{h,mm}`(启动时 `InstallUpdateReadyBuildStateBridge()`,须在 `StartMacUpdater()` 前调用)与 `teleport_version_updater.mm`(`VersionUpdater::Create()` 的 macOS 实现)虽物理在 `src/` 下,但经 `chrome/browser/BUILD.gn` 与 `chrome/browser/ui/webui/help/BUILD.gn`(**M151 起**;上游把 `version_updater_mac.mm` 从 `chrome/browser/ui` 顶层迁到 `chrome/browser/ui/webui/help:help` 子 target 后,落点随之搬到这个新 patch 文件,不再是 `chrome/browser/ui/BUILD.gn`)的 patch **编进 chrome target、不在 `//teleport` source_set**——它们要 include chrome 头(BuildState / VersionUpdater),放进 source_set 会造成 GN 依赖环。故这两个文件**不出现在 `src/BUILD.gn`**;改它们要动对应 patch,别往 `src/BUILD.gn` 加。About 页面板本身的改动在 `patches/chrome/browser/resources/settings/about_page/*`(版本展示、Sparkle check-for-updates、页脚链接)。

- **工具栏主菜单升级角标依赖 `enable_update_notifications`**:点亮「⋮ 菜单的重启更新角标」的唯一通道是 `BuildState::SetUpdate` → `UpgradeDetectorImpl` → `AppMenuIconController`。但 `UpgradeDetectorImpl::Init()` 里 `build_state->AddObserver(this)` 与 `InstalledVersionPoller` 整段包在 `#if BUILDFLAG(ENABLE_UPDATE_NOTIFICATIONS)`,而该 flag 上游默认 `= is_chrome_branded`(`//chrome/browser/buildflags.gni`)——非品牌构建恒为 0,detector **根本不订阅 BuildState**,我们 bridge 的 `SetUpdate()` 全程无效,角标永不亮(About 页却仍显示 Relaunch,因为它走另一条 VersionUpdater 通道)。我们有 Sparkle,故在 `gn/args/{release,dev}.mac.gn` 显式 `enable_update_notifications = true`。验证可纯本地、不发版:dev 构建用 `--simulate-critical-update`(经 InstalledVersionPoller 合成 BuildState 更新)即可秒亮角标(critical 红;普通更新走 1h 的 VERY_LOW 阈值后转绿)。副作用:同时编入 outdated-build 检测器(满 8 周对非受管/organic 构建提示;受管安装 `IsManaged()` 下不触发)。

- **修改已有 patch 的工作流**:先 `apply_patches.py` 确保全部已应用 → 直接编辑 `chromium/src/<file>` → `git -C chromium/src diff -- <path> > patches/<path>.patch` 重生成 → 再跑 `apply_patches.py` 验证幂等。禁止手改 hunk。**三个例外路径**(同时是手写 patch 目标 **和** `branding_strings.py` 重写目标):`chrome/app/generated_resources.grd`、`chrome/app/resources/generated_resources_zh-CN.xtb`、`chrome/app/settings_strings.grdp`——对这三个文件重生成 patch 前,树必须是用 `apply_patches.py --skip-branding` 建的(而不是普通 `apply_patches.py`)。原因:普通 `apply_patches.py` 会先应用手写 patch 再跑品牌重写,`git diff` 出来的内容会把品牌重写也一起烤进 patch;下一次正常 `apply_patches.py` 对着一个已经改过名的 grd 再跑品牌重写,`transform_en_grd` 的幂等性使 id 重映射算出空结果,对应的 zh-CN/zh-TW `.xtb` 会静默失去重键、退回英文——参见 `export_patches.py` 的 `branding_pass_has_run()` 安全阀(同一坑,`rebase_overlay.py`/`export_patches.py` 走脚本化路径时由它兜底;这里是手工路径,没有安全阀,只能靠遵守这条规则)。
- **部署环境三态(`teleport_deployment_env = dev | staging | release`)**:一个 GN arg 选定本二进制烤哪一套信任材料(策略验签根集合 + 默认 deployment domain),**其余环境的材料不在二进制里**——这是 fairyland F6「分环境根」隔离的兑现方式,运行时判断只能做到「更难利用」,不烤才是「不可能」。展开为三个 buildflag:`TELEPORT_ENV_IS_RELEASE` / `TELEPORT_ENV_IS_STAGING`(dev = 两者皆 false)/ `TELEPORT_ALLOWS_DOMAIN_OVERRIDE`。用布尔不用字符串,因为 `#if` 无法比较字符串。
  - **墓碑 arg**:旧名 `teleport_use_release_endpoints` 仍声明着,默认是字符串哨兵 `"unset"`,任何显式赋值(**含 `=false`**)都触发 assert。GN 对未声明 arg 只告警且退出码 0,直接删名会让存量覆盖静默失效;而 `=false` 恰是更危险的那个值——TD-026 的书面变通就是它叠在 release 模板上,迁移后该覆盖变 no-op 而模板的 `env="release"` 照常生效,操作者会以为烤的是 dev 端点。
  - **staging = 环境借用渠道槽位**:`staging.mac.gn` 链式 `import` release 模板只覆盖 env,故 PGO / official / updater 全部继承(实测确认),两者共用一条流水线;`ChannelFromName("staging")` → `Channel::CANARY`(落 UNKNOWN 会产出 `is_official_build=true` + 上游不认识的渠道)。**将来 staging 需要多渠道时必须先拆开 env 与 channel 两个轴**,这是硬性前置而非可登记取舍。
- **策略验签根是「集合」而非单把**:`GetPolicyVerificationKeys()` 返回本档全部受信根,`IsKnownVerificationKey()` 判成员;`GetPolicyVerificationKey()` 仍返回**主根**(推导 `kPolicyVerificationKeyHash`、写盘记录用)。release 烤**两把**(主根 + 离线冷存的休眠恢复根),dev/staging 各一把。**六个验签点全部按集合遍历**:`cloud_policy_validator` 的 4 处(新式 + deprecated × `CheckNewPublicKeyVerificationSignature`/`CheckCachedKey`)、`user_cloud_policy_store` 的轮换判定(改为**集合成员**判定,否则恢复根启用后每次启动全量重拉)、以及 overlay 的两个 server-identity 调用点(经 `VerifyAgainstRootSet`,verdict 聚合规则:任一 kValid 即通过;否则优先返回**非签名类**失败,因为那意味着某把根的签名验过了而字段没过——报成 kBadSignature 会把排障引向不存在的密钥问题)。
  - **恢复根买到什么**:客户端对集合内两把根**一视同仁**,故它**不撤销**主根,也不让轮换自动无缝(服务端还需重签存量租户背书)。它买到的是**泄露当天服务不中断、有从容推更新的时间**。撤销泄露根仍必须发新客户端。
  - **`--require-real`**:`gen_policy_verification_key.py --check` 只能证明 PEM 与 patch 一致——占位密钥同样满足。`--require-real <env>` 对照占位指纹表 fail-closed。dev 根私钥有意提交在 fairyland(`products/teleport/device-manager/keys/dev-policy-root.pem`,dev-only 锚);**staging 主根已是真实根**(2026-08-13 由 fairyland 交付,指纹 `8b06e78b…`,私钥 BYOK 导入 staging 的 OpenBao Transit;它与 dev 根**刻意不同**——dev 私钥提交在仓库里,共用就等于让每个读仓库的人都成为合法签名者);**release 主根仍是占位**,由 `teleport_release_policy_key_is_real` assert 挡住(TD-026,prod 云未落地,根仪式是刻意推迟而非待办)。
  - **占位期的具名逃生口**:`teleport_policy_key_placeholder_ack=true` 放行构建,但把 `TeleportUnpublishable` 烙进 Info.plist 且 `package.py --distribute` 硬拒。设计意图是让「我知道是占位、只想验流水线」成为显式、可 grep、自我解除的动作——TD-026 正是「临时覆盖留在 args.gn 里没人记得」的后果。
- **发布链的三条护栏(与三态同批加固)**:① 陈旧 args.gn 守卫改查 **`gn args --list` 的生效值**(文本看不穿 `import()` 链,而正常 `gn gen` 写出的 args.gn 恰恰只有一行 import,旧守卫因此几乎从未真正比较过;注意 gn 靠**工作目录**向上找 `.gn`,调用必须 `cwd=检出根`,且未知 arg 时退出码仍是 0);② **EdDSA 按渠道分离**(`ed_key_account`),共用一把意味着 staging 发布机能签出 release 客户端接受的更新,而更新投递的是任意代码——比策略链更重;③ **tag 按渠道命名空间**(`staging/v<四段>`),staging 与 release 共用 `TELEPORT_VERSION`,单一命名空间会让「先在 staging 演练同一版本再发 release」变成自我拒绝。另:`fetch_live_appcast` 只对 404 返回 None,其余异常硬失败(否则一次超时就会让 `assert_publishable` 静默失效)。
- **`InstalledVersionPoller` 与 Sparkle「暂存-重启才替换」冲突(patch `upgrade_detector_impl.cc`)**:`enable_update_notifications=true` 在 `UpgradeDetectorImpl::Init()` 里除了订阅 BuildState,还顺带 `installed_version_poller_.emplace()`。该 poller 每 2h(+ 启动首轮 + bundle 监听)读**磁盘 .app 版本**比对运行版:`installed==running` → `SetUpdate(kNone)`。但 Sparkle 把更新暂存到自己缓存、**重启才换主 bundle**,故重启前磁盘版恒等于运行版 → poller 不停 `SetUpdate(kNone)`,与我们 bridge 的 `SetUpdate(kNormalUpdate)` **抢同一 BuildState**。致命点:`UpgradeDetected(NONE)` 把 `upgrade_notification_stage_` 重置为 NONE 但**不调 `NotifyUpgrade()`**(`set_upgrade_notification_stage` 是纯 setter)→ 观察者不被通知 → **chip 缓存的 `kUpgradeNotification` 成 stale(蓝底 Update 一直在),而菜单 `Build()` live 查 `GetTypeAndSeverity()` 因 `stage==NONE`→`severity==kNone` 落空,upgrade 块整段跳过 → 「Relaunch to update」菜单项消失、默认浏览器项浮顶**。chip 与菜单项 desync,即此因。**为何 `--simulate-*` 复现不出**:simulate 走 `SimulateGetInstalledVersion` 伪造 `components[3]+=2` 的高版本,poller 自己就报 update、单写入者、不打架。修复:patch 把 poller 创建**门控在 `if (is_testing_)`**——生产路径(无 simulate)不建 poller,bridge 成 BuildState 唯一写入者;保留 `--simulate-upgrade/--simulate-critical-update` 的本地调试能力(它俩本就依赖 poller 跑 `SimulateGetInstalledVersion`)。

- **强制纳管是自愿(voluntary-enrollment-ux 特性)**:单一开关 `kRequireEnrollmentToBrowse`(local_state 布尔,`teleport_enrollment_gate.{h,cc}`,**默认 false**,BYOD-first)经会话冻结谓词 `teleport::RequireEnrollmentGateEnabled()` 读取(首次读后缓存,镜像上游 `IsForceSigninEnabled` 的进程级缓存语义,中途翻转不生效,重启后生效)。该谓词 OR 进 `signin_util.cc::IsForceSigninEnabled()` 的出口,复活 Layer-1 picker 强制纳管机制(未纳管 profile 启动即锁进 ProfilePicker,走 GAIA-free 的 enrollment step 完成才解锁);gate OFF 时该 OR 不生效,profile 正常创建/浏览。GAIA 全表面(菜单/设置/picker 建号/FRE/DICE 拦截)经 `AccountConsistencyModeManager::CanEnableDiceForBuild()` 恒 `return false` **结构性**钉死(不再依赖「构建无 OAuth key」的偶然性);gate 有**平台策略通道**:`BrowserSignin=2 (Force)` 与遗留 `ForceBrowserSignin`(布尔,`BrowserSignin` 未设时生效)均已改映射为设置 gate pref(patch `browser_signin_policy_handler.cc` + `configuration_policy_handler_list_factory.cc`)——MDM/GPO/managed pref 下发即可开 gate(策略本身 `dynamic_refresh:false`,与会话冻结谓词一致,重启生效;非 forced 的 recommended 层亦生效,已活体验证);上游 `kForceBrowserSignin` pref 在本构建已无任何写入方,gate pref 是强制登录**唯一**来源。注意语义与 Chrome 文档不同(Chrome=强制 Google 登录,本产品=强制纳管),交付文档须注明。guest 在 gate ON 时于两个谓词点(`IsGuestModeGloballyDisabledInternal`/`IsGuestModeRequested`)+ 两个动作层 fail-closed guard(`SwitchToGuestProfile`/`HandleLaunchGuestProfile`)共四处禁用。gate OFF(默认)下的自愿纳管入口:未纳管 profile 菜单顶部常驻「登录」按钮 → 新 tab 打开 `EnterpriseEnrollUrl()` → OIDC capture → 复用上游披露对话框确认「组织将管理此 profile」→ 就地纳管(不新建 profile)。详见 spec `docs/superpowers/specs/2026-07-24-voluntary-enrollment-ux-design.md`、runbook `docs/deployment-domain-migration-runbook.md`。

- **隧道路由表来自 bind 响应,不再来自 `AutoSelectCertificateForUrls`**:`POST https://gate.<D>/tunnel/bind` 的响应体里的 `routable_origins` 数组(结构化条目 `{host, port, include_subdomains, blocked}`)是路由白名单的**唯一**来源;`teleport_tunnel_logic.cc::ParseRoutableOrigins` 解析+校验+排除 edge/gate+去重后交给 `BuildTunnelProxyConfig` 产出 `CustomProxyConfig`。旧路径(从 content-settings 的 `[*.]host` 模式推导)已删,连同 `DeriveRoutableOrigins` 这个符号——**它在旧文档/旧 TD 里还会出现,那是历史,不是现状**。`AutoSelectCertificateForUrls` 策略**仍在读值门里、别当残留删掉**:它不再供给路由表,但它是让网络栈愿意在 gate 的 mTLS 握手上出示设备证书的那个条件。响应体上限 `kMaxBindBodyBytes = 64 KiB` 与服务端截断预算 48 KiB 是**跨仓成对常量,任何一侧改动必须同批改另一侧**(超限不是截断而是整个 bind 失败),理由与算术见 `docs/verification/2026-08-16-payload-budget.md`。响应体**无签名**,host 校验是唯一补偿(`TD-TUNNEL-BIND-RESPONSE-UNSIGNED`,该条目已按实际判据重写)。
- **`teleport://tunnel` 是隧道诊断页**:显示派生后的实际状态(纳管/策略/编排/凭据/到期时刻、生效路由表、**被跳过条目及原因**、最近 CONNECT 结果与 authority),并提供手动重绑。它存在的意义是让「路由表到底变成了什么」第一次可见——静默丢弃(C-2)正是本次改动要消灭的缺陷,所以**每一条拒绝都必须可上报**。页面 handler 编在 `//chrome/browser/ui/webui`,经 `teleport_tunnel_logic.h` 的 callback seam 取状态,**不得** include `teleport_tunnel_service.h`(会成 GN 环,普通 `gn gen` 就报)。
- **隧道的纯逻辑必须留在 `teleport_tunnel_logic.{h,cc}`**:`teleport_tunnel_service.cc` 经 `patches/chrome/browser/BUILD.gn.patch` 编进 `chrome/browser`,轻量 `teleport_unittests` **链不到它的符号**(`TD-TUNNEL-UNITTEST-WIRING`),写进去的东西只能靠重型 `unit_tests` 覆盖。协议常量同理——`kMaxBindBodyBytes` 就是为了能被钉住才从 service 的匿名 namespace 搬进 logic 头的。
- **Windows 上工作区行尾是硬要求,不是风格问题**:Git for Windows 默认 `core.autocrlf=true`,clone 出来的**整棵树都是 CRLF**,而索引仍是 LF——`git status` 全程干净,看不出任何异常。后果是 `patches/*.patch` 在磁盘上带 CRLF,对着 LF 的 chromium 检出既不能正向 `git apply` 也不能 `--reverse --check`;而 `apply_patches.py` 恰恰用后者判定「已应用」,于是它在一棵**完全正常**的树上报 `patch does not apply cleanly`。两道防线:① 仓库根 `.gitattributes` 的 `* text=auto eol=lf` 把工作区行尾钉死,不再依赖每人的 `core.autocrlf`;② **所有生成进检出的文件一律走 `_lib.write_text_lf()`**(`chrome/VERSION`、引擎版本头、品牌重写后的 grd/xtb、导出的 patch)——`Path.write_text()` 以 `newline=None` 打开,会把换行翻译成 `os.linesep`。新增「往检出里写文件」的代码时**别用 `Path.write_text()`**。
- **Windows 上 overlay 注入链接必须是真符号链接,不能是目录联接(junction)——siso 不穿越 junction**(2026-08-22 实测):`mklink /J` 建的联接,`gn gen` 能完美解析并报出全部 ~31.5k targets,然后 siso 在**编译任何东西之前**死于 `error in depfile ...: deps input "../../../../teleport/BUILD.gn" not exist: store resolve next dir teleport failed`——这条错误里没有半个字提到链接或权限。换成 `mklink /D` 的真符号链接(reparse tag 从 `0xa0000003` 变成 `0xa000000c`)siso 立刻正常。siso 是 Go 写的,Go 标准库对这两种 reparse point 的语义历来就不一样。**因此 `create_dir_link(..., traversed_by_build=True)` 在 Windows 上只建符号链接,建不了就硬失败并给出两条出路**(开开发者模式 / 提权跑一次 `mklink /D`),**绝不回退到 junction**——回退等于把一个当场的清晰错误换成上面那个又晚又费解的。反过来,`<repo>/build → out` 这条链接构建系统从不走进去,继续用免权限的 junction。
- **Windows out 目录必须正好在 `out/` 下一层**(`out/win-x64-dev` ✅,`out/win/x64/dev` ❌):Chromium 把 MIDL 的生成产物**签进仓库**(`third_party/win_build_output/midl/…`),构建期跑一遍 midl.exe 再与签入基线**逐字节比对**,不一致即失败。而 midl.exe 会把 `.idl` 的路径原样写进生成文件的注释里,签入基线里是 `../../third_party/…`——那是 out 目录在 `out/<名字>` 时的相对路径。照搬 macOS 的 `out/mac/arm64/dev` 分层会让它变成 `../../../../third_party/…`,于是**每个 MIDL target 都失败**,报的是「midl.exe output different from files in …」加一段只有注释行不同的 diff,完全看不出是目录深度问题。macOS 不跑 MIDL,所以那边分几层都无所谓——这条只约束 Windows。
- **git 把 junction 当普通目录**:`git status --porcelain` 对 junction 报 `?? teleport/`(带尾斜杠),对符号链接报 `?? teleport`。`export_patches.is_injected_artifact()` 因此对路径做 `rstrip("/")`(现在注入链接已是符号链接,这条是给早期 junction 检出兜底)。同理 `patch_paths()`/`branding_paths()` 用 `as_posix()` 而非 `str()`——git 恒输出正斜杠,拿 Windows 的反斜杠去比会**全不匹配**,而失败形态不是崩溃,是每个文件都被判成「未分类」从而在健康的树上触发安全阀。
- **depot_tools 的 `gclient`/`gn`/`autoninja` 必须经 `_lib.depot_tool()` 解析**:三者都同时存在「无扩展名的 POSIX 脚本」和「`.bat`」两份,而 `subprocess`(不带 `shell=True`)走 CreateProcess,**只会补 `.exe`、不查 PATHEXT**,于是裸名字命中 sh 脚本并以「not a valid Win32 application」失败。`shutil.which` 会查 PATHEXT,返回 `.bat`。
- **`gclient sync --no-history` 的检出一个 tag 都没有**:depth-1 浅克隆压根不协商 tag ref,`--with_tags` 无从带回。所以 `sync.py` 的版本校验先查本地 tag,查不到就 `git ls-remote` 向 origin 取(只读 ref 广播、不传对象),而不是把「本地没这个 tag」当成「检出错了」。chromium 的发布 tag 是**轻量 tag**,`refs/tags/<t>` 直接指向 commit,没有 `^{}` 那行。
- **ARM64 Windows 宿主缺 `Debuggers\x64`**:SDK 安装器按宿主架构过滤载荷,ARM64 上只装 `Debuggers\arm64`;但 Chromium 总会额外实例化一套 x64 宿主工具链(`win_clang_x64`),`vs_toolchain.py:_CopyDebugger()` 对每套工具链都按 `Debuggers\<target_cpu>` 取 dbghelp/dbgcore/symsrv——**所以 `target_cpu="arm64"` 也照样卡在缺 x64 那份上**。取法见 `docs/windows-build-setup.md` §2.4(从微软 SDK 载荷 CDN 取 MSI + `msiexec /a` 展开,不需要第二台机器)。
- **在 ARM64 宿主上编 x64,MSVC 运行时 DLL 会被拷成宿主架构的——本机永远测不出来**(2026-08-23 实测,已 patch `build/vs_toolchain.py`):`_CopyUCRTRuntime()` 上游**只对 `target_cpu == 'arm64'` 特判**去 VC redist 取,x86/x64 一律用宿主的 `C:\Windows\System32`。这个假设只在「宿主架构 == 目标架构」时成立。ARM64 宿主上编 x64 时,557 个 DLL 里有 5 个是错的:`msvcp140` / `msvcp140_atomic_wait` / `vccorlib140` / `vcruntime140` 直接是 **ARM64**,`vcruntime140_1` 是 x64 但**依赖 `RtlIsEcCode`**(只有 ARM64 Windows 的 ntdll 才导出这个符号)。**构建绿、本地冒烟也绿**——那 4 个 ARM64 的根本不会被加载(Chromium 用自带 libc++,不用 MSVC 的 STL),EC 版那个在 ARM64 宿主上加载正常;直到把产物拷到真 x64 机器才炸:「无法定位程序输入点 RtlIsEcCode 于动态链接库 VCRUNTIME140_1.dll 上」。patch 把「优先用**目标 CPU** 的 VC redist」从 arm64 专属推广到所有架构,redist 不存在时才回退 System32。**核对方法**:产物目录里所有 `*.dll` 的 PE machine 都应是 `0x8664`,且无一含 `RtlIsEcCode` 字符串。
- **便携解压的 Windows 产物必须显式授 AppContainer ACL,否则浏览器进程 FATAL**(2026-08-23 真 x64 Win10 实测):Chromium 部分子进程用 **AppContainer** 沙箱,`sandbox_win.cc:798` 在启动前 `AccessCheck` **AppContainer SID 对 `chrome.exe` 的读+执行**;不通过就返回 `SBOX_ERROR_CREATE_APPCONTAINER_ACCESS_CHECK`,上层 `sandbox_win.cc:591` 的 `DCHECK(false)` 命中 → **整个浏览器进程死**。
  - **判据是目录 ACL 里有没有 AppContainer 授权,与「是否共享目录」无关**——这一点极易误判。实测:`C:\` 根、`C:\Users\<user>`、`AppData\Local`、`D:\` 根**全都没有**;只有 `C:\Program Files` 这类由安装程序/系统设好的位置才有。所以「换个非共享目录」「挪到 C 盘」都不解决问题。
  - **迷惑现象:先能正常渲染,多开几个页面才崩**——最初的渲染进程不走 AppContainer,直到某个用它的子进程按需启动才触发。
  - **解法**(非提权即可,已验证子文件能继承到 `(I)(RX)`):
    ```
    icacls <dir> /grant "*S-1-15-2-1:(OI)(CI)(RX)" /T   # ALL APPLICATION PACKAGES
    icacls <dir> /grant "*S-1-15-2-2:(OI)(CI)(RX)" /T   # ALL RESTRICTED APPLICATION PACKAGES(LPAC)
    ```
    **必须用 SID**:英文名在中文系统上是「所有应用程序包」,写英文名匹配不到。
  - **这是便携解压包特有的**:正式安装包由 installer 负责设这些 ACL,所以将来的 Windows 打包 phase 必须覆盖这一步(TD-042)。另注意 DCHECK 构建把它放大成了浏览器崩溃;release 构建里只是子进程启动失败、功能静默不可用。
- **搬运 Windows 构建产物用 `gn desc <out> //chrome:chrome runtime_deps`**,不要手挑文件——那是 GN 自己维护的运行时闭包,改构建参数/升基线后自动跟着变。唯一要做的过滤是**剔掉 `.pdb`**:实测 8367 MB 里符号占 6817 MB(81%),运行完全用不到(要在对端调崩溃再单独拷,文件名一一对应)。剩下 1550 MB 中 1344 MB 是 550 个 DLL,那是 `is_component_build=true` 的代价。
- **`gn check` 在本树是红的(既有 overlay 违规,28 处/19 文件)**,`gn gen` 不跑它,所以日常构建一直绿。**不要引用「gn check 会兜住坏依赖边」作为设计依据**——它兜不住。默认 `--error-limit` 会在 10 条截断并打印「Too many errors」,只看默认输出会误以为只有一处违规。详见 `TD-OVERLAY-GN-CHECK-VIOLATIONS`。

## 目标平台

Windows、macOS、Linux(企业以 Windows 为主);未来适配国产 OS(鸿蒙等),MVP 暂不。**macOS(Apple Silicon)构建 + 渠道包全链路已跑通;Windows P1 已达成并在真实 x64 硬件上验证**(x64 `chrome.exe` 编出;`teleport_unittests` 169/169;在真 x64 Windows 10 上沙箱开启下页面正常渲染、关于页显示 `0.2.0.1-dev` / 「闪现」。构建机是 ARM64 虚拟机,其沙箱异常已定性为环境特有,见 TD-041;便携包需授 AppContainer ACL,见 TD-042),见 `docs/windows-build-setup.md`。Linux 未开始。

## 开发工作流

- 分支:GitLab Flow,`main` 唯一事实来源;合并用 **rebase onto main + squash + fast-forward**(无 merge commit)。
- 文档:`docs/superpowers/specs/`(设计)、`docs/superpowers/plans/`(实现计划)。
- brainstorming:在新分支的独立 git worktree 进行,spec/plan/实现提交到该分支。
- CI:fairyland 用 Gitea Actions;**本仓库 CI 尚未建立**(后续)。

## 待定 / 后续 phase

- 后端服务代号(在 fairyland 内)、浏览器↔后端**策略下发协议**(传输/格式/鉴权)。
- ~~Windows 构建的注入方式(symlink 换 junction 或受管检出)~~ → **已定**:仍是符号链接,Windows 上需 `SeCreateSymbolicLinkPrivilege`(开发者模式);junction 被 siso 拒绝,受管/拷贝检出不需要了。见「关键 gotcha」。Windows 剩余工作见 `docs/windows-build-setup.md` §6 与 TD-040。
- Linux 构建、国产 OS 适配。
- ~~代码签名、打包、分发、自动更新~~ → **macOS canary 已完成**(Sparkle 自动升级 + Developer ID 签名 + Apple 公证 + 样式 dmg + OSS 分发,实测升级闭环)。剩:Windows/Linux 签名与分发、多通道(beta/stable)、全静默后台升级、未来企业版 Omaha 4。
- CI(构建缓存与产物策略)。
- 完整 rebrand(各平台图标/安装包等)。

## 参考材料

- 本仓库:`docs/superpowers/specs/2026-05-25-overlay-build-foundation-design.md`、`docs/superpowers/plans/2026-05-25-overlay-build-foundation.md`、`scripts/smoke_check.md`。
- 渠道包/自动升级:`docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`、`docs/superpowers/plans/2026-05-26-macos-canary-channel.md`、`docs/canary-install.md`。
- Chromium 基线升级:`docs/superpowers/specs/2026-08-06-chromium-milestone-upgrade-design.md`、`docs/superpowers/plans/2026-08-06-chromium-milestone-upgrade.md`、`docs/chromium-upgrade-runbook.md`(操作手册,新升级从这里开始读)。
- 同级:`../fairyland/CLAUDE.md`、`../fairyland/README.md`(服务端工程约定基线)。
