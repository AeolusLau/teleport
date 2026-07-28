# Teleport(闪现)

> 基于 **Chromium** 源码自研的**企业安全浏览器**:作为受管端,接收并执行服务端集中下发的安全策略。

- **代号**:`teleport`(闪现,取「瞬移 / 传送」之意)
- **磁盘 / 标识名**:`Teleport`(`Teleport.app`、bundle id 前缀 `cn.douan.Teleport`)
- **应用内显示名**:`闪现`
- **当前版本**:`0.1.12`(见 `TELEPORT_VERSION`)
- **上游基线**:Chromium `148.0.7778.180`(见 `CHROMIUM_VERSION`)
- **构建状态**:仅 **macOS(Apple Silicon)** 已跑通;Windows / Linux / 国产 OS 为后续 phase。

---

## 这是什么

Teleport 是一款面向企业的受管浏览器。它不 fork 整个 Chromium,而是采用 **Brave 式 overlay** 方案:以「加法为主、改上游为辅」的方式在上游 Chromium 之上叠加自研能力,产出品牌化、可集中管控的浏览器。

浏览器本身是**受管端**;负责下发安全策略的服务端不在本仓库,位于同级 monorepo `../fairyland`(公司的 B2B DSPM 平台)。改动任一端的协议时,务必同步另一端。

## 架构:Chromium overlay

- **不 fork Chromium**:上游 M148 由 depot_tools / gclient 检出到**仓库外**(gitignore 的 `chromium/`,可用 `$TELEPORT_CHROMIUM_DIR` 覆盖)。几百 GB 的检出不绑定在每个 worktree 里。
- **加法为主**:`src/` 是纯 overlay 源码,构建期以符号名 `teleport` 链接进 `chromium/src/teleport`,成为 GN 模块 `//teleport`,经一个最小上游 patch 编进 chrome。
- **改上游为辅**:
  - 文本改动走 `patches/`(`git apply`,一文件一 patch,文件名镜像其在 `chromium/src` 下的路径)。
  - 整文件 / 二进制资源走 `branding/`(覆盖拷贝)。
- **上游版本钉死**在 `CHROMIUM_VERSION`。
- **命名体系**:延续 fairyland 的奇幻代号风格,在 GN 路径、C++ 命名空间、目录等各处统一(如 `//teleport`、`teleport::`)。

## 仓库布局

```
src/            overlay 源码 → 构建期链接为 chromium/src/teleport(GN //teleport)
  BUILD.gn      //teleport:teleport(source_set)+ teleport_unittests(test)
  teleport.gni  共享 GN args / 路径(updater、sparkle 目录等,供上游 BUILD.gn import)
  browser/      启动 banner、macOS Sparkle 更新器 / 无界面 user driver、升级指示桥接
  common/       渠道映射、版本展示、teleport:// 方案别名、appcast feed 校验
  gn/args/      dev / release 的 GN args 模板
scripts/        Python 编排(bootstrap / sync / apply_patches / package / 发布等,用 uv 跑)
patches/        一文件一 patch,镜像 chromium/src 路径
branding/       资源覆盖(整文件),镜像 chromium/src 路径
brand/          品牌源资产(手改 teleport.svg;派生物由脚本产出)+ dmg 素材
docs/           设计 spec / 实现 plan / 研究 / 安装说明
CHROMIUM_VERSION  钉死的上游版本
TELEPORT_VERSION  产品版本(semver,单一事实来源)
chromium/       (gitignore)外部 chromium 检出
build/          (gitignore)→ chromium/src/out 的符号链接(产物访问入口)
```

## 快速开始(macOS / Apple Silicon)

前置:`depot_tools` 在 `PATH`、Xcode、`uv`;检出在仓库外时先 `export TELEPORT_CHROMIUM_DIR=/abs/path/to/chromium`。

```bash
# 1) 建立检出与符号链接(首次去掉 --skip-sync 会完整 sync,数小时)
python scripts/bootstrap.py --skip-sync     # src/teleport→src、build→chromium/src/out
python scripts/sync.py                        # gclient sync 到 CHROMIUM_VERSION 并校验

# 2) 应用 overlay(幂等)
python scripts/apply_patches.py

# 3) 构建(首次数小时;Siso,本地无 RBE)
uv run python scripts/package.py             # dev 一键:args.gn 缺失时自动 gn gen,再 autoninja + 烘焙版本校验
# 等价手动路径(gn gen 仅首次需要,out 目录建好后 ninja 会自动 re-gen):
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev chrome        # 产物 Teleport.app,亦在 <repo>/build/mac/arm64/dev/
```

## 测试

```bash
uv run pytest                                  # 工具脚本单测(仓库根运行)

autoninja -C out/mac/arm64/dev teleport_unittests && \
  "$TELEPORT_CHROMIUM_DIR"/src/out/mac/arm64/dev/teleport_unittests   # //teleport gtest
```

- 产品代码(`//teleport` C++)走 **TDD**(gtest,Red → Green → Refactor)。
- 构建 / 工具脚本不强求 TDD,仅在有价值处务实地写 pytest。
- 冒烟验证清单见 `scripts/smoke_check.md`。

## 打包与自动升级(macOS canary,已端到端验证)

official 构建 + Sparkle 自动升级 + Developer ID 签名 + Apple 公证 + 样式 dmg + 阿里云 OSS 直连分发,已实测 `0.1.0 → 0.1.1` 自动升级闭环。

```bash
python scripts/fetch_sparkle.py                                # 钉版本拉 Sparkle.framework(SHA256 校验)
printf '0.1.13\n' > TELEPORT_VERSION                          # 每次发版 bump(semver 单调递增)并提交
uv run python scripts/package.py                              # 默认:本地打 dev 包(仅构建)
uv run python scripts/package.py --channel canary            # 渠道包:构建 + 签名 + 公证 + 样式 dmg(不发布)
uv run python scripts/package.py --channel canary --distribute  # 发布(仅 main):+ appcast + 上传 OSS + 打 v<semver> tag
```

- 发布依赖本地凭据:Developer ID 证书、`notarytool` profile、EdDSA 密钥、`scripts/release_config.local.toml`(见 `.example`,gitignored)。
- **EdDSA 私钥绝不入库**,仅 login keychain + 离线备份。
- release 构建默认开 PGO(`chrome_pgo_phase=2`),编译时间显著更长;两套 profile(Chrome 顶层 + V8 builtins)由 `gclient sync` 拉取。
- 详见 `docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md` 与 `docs/canary-install.md`。

## 企业能力

对齐 Chrome Enterprise 的多阶段路线图正在推进(设备 CBCM 注册、OIDC 用户注册、设备状态上报、策略框架、强制注册门禁等)。协议 / 后端服务在 `../fairyland` 内实现,与浏览器端配套演进。相关设计与计划见:

- `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`
- `docs/superpowers/specs/2026-06-03-enterprise-account-system-design.md`
- `docs/enterprise-device-enrollment.md`

## 与 fairyland 的关系

- 服务端**不在本仓库**,在同级 `../fairyland`(微服务架构的 B2B DSPM 平台)。
- 浏览器的策略下发后端将作为 fairyland 中的服务存在;**该服务代号、浏览器 ↔ 后端的策略协议尚未定义**。
- fairyland 的工程约定是本项目基线参考:`../fairyland/CLAUDE.md`、`../fairyland/README.md`。

## 开发工作流

- 分支:**GitLab Flow**,`main` 唯一事实来源;合并用 **rebase onto main + squash + fast-forward**(无 merge commit)。
- 文档:设计放 `docs/superpowers/specs/`,实现计划放 `docs/superpowers/plans/`。
- brainstorming 在新分支的独立 git worktree 进行,spec / plan / 实现提交到该分支。
- 语言约定:Markdown 文档用简体中文;代码、注释、提交信息、脚本、配置等一律英文。

## 目标平台

Windows、macOS、Linux(企业以 Windows 为主);未来适配国产 OS(鸿蒙等),MVP 暂不。**目前仅 macOS(Apple Silicon)跑通构建**。

## 后续 phase

- 后端服务代号与浏览器 ↔ 后端策略下发协议(传输 / 格式 / 鉴权)。
- Windows / Linux 构建(注入从 symlink 换 junction 或受管检出)、国产 OS 适配。
- 多通道(beta / stable)、全静默后台升级、未来企业版 Omaha 4;Windows / Linux 签名与分发。
- CI(本仓库尚未建立)、patch 的创建 / 刷新 / 冲突处理工具链、完整 rebrand。

## 参考

- 面向贡献者的详细工程说明与「关键 gotcha」:见仓库根的 `CLAUDE.md`。
- 设计与计划:`docs/superpowers/specs/`、`docs/superpowers/plans/`。
- 安装说明:`docs/canary-install.md`。
