# 设计:`package_release.py` → `package.py` 重构

> 目标:把"构建 / 签名 / 公证 / stamp / 发布"从一条写死的 canary 流水线,重构成
> **以参数驱动的多渠道打包工具**——默认本地打 dev 包,可选渠道,显式 `--distribute`
> 才发布;发布仅限 main 分支、自动打版本 tag、阻止重复发布。

## 背景

现状 `scripts/package_release.py` 是一条写死的 canary/release 流水线:固定用
`out/mac/arm64/release`(official + PGO + updater)→ stamp 版本/注入 Sparkle key →
chrome 签名模块 → 样式 dmg(签名/公证/staple)→ appcast 版本护栏 → `generate_appcast` →
ossutil 上传 OSS。`--no-upload` 跳过上传与版本护栏,`--dry-run` 只打印计划。"已发布"
判定靠拉线上 appcast feed 比 semver(`_release.assert_publishable`)。

开发期痛点:所有能力揉在一个脚本里,且默认行为就是走完整发布流水线,本地迭代不便。

## 需求

1. **默认打 dev 包**,本地测试用,默认不发布(不上传 OSS);`--channel` 选其它渠道包。
2. `--distribute` 在打包后顺带发布,但**只有渠道包可发布,dev 包不可发布**。
3. **打包可在任意分支**;**发布仅限 `main` 分支**,非 main 上发布报错。
4. 发布时给当前 commit 打 `v<semver>` tag(如 `0.1.0` → `v0.1.0`),并**推送到 remote**。
5. **当前 version 已发布过则不能发布**(但仍可打包)。
6. 单脚本 vs 拆分:采用**单入口 + 内部模块化**(下文方案 A)。

## 关键技术结论:dev 包不需要为沙箱而签名

- Apple Silicon 上不存在"完全无签名"的可执行文件:内核要求每个 Mach-O 至少带 **ad-hoc
  签名**才能运行,链接器在 arm64 链接时自动 ad-hoc 签名。dev 构建出的 `chrome` 本就可运行。
- Chromium 用的是 **Seatbelt 沙箱**(`sandbox_init` + `.sb` profile),不是 App Store 那套
  基于 entitlement 的 App Sandbox;Seatbelt 沙箱**不读签名身份、不需要 hardened runtime**,
  dev 构建照常全沙箱运行(可在 `chrome://sandbox` 验证 fully sandboxed)。
- 真正需要 Developer ID + hardened runtime + entitlements 的是:公证/Gatekeeper 分发、
  Sparkle 自动更新、hardened-runtime 下的 JIT entitlement、keychain-access-groups——
  这些都不是渲染器/GPU 沙箱。

**结论:dev 包 = 仅构建 `.app`,不加签名、不打 dmg。**

## 架构:单入口 + 内部模块化(方案 A)

`package_release.py` 重命名为 `package.py`(默认打 dev,"release"名不副实),按阶段拆成
内部模块。

| 文件 | 职责 |
|---|---|
| `package.py` | 入口:argparse、解析渠道、按模式编排各阶段、dry-run、打印结果。 |
| `_build.py` | 渠道注册表 + `build(out, channel)`(autoninja)。 |
| `_package.py` | `stamp_and_inject` / `sign_app` / `build_styled_dmg` / `_detect_codesign_identity` / `sparkle_bin`(从现脚本搬出)。 |
| `_publish.py` | 发布护栏(`assert_on_main` / `assert_clean_tree` / `assert_not_published`)、`generate_appcast` / `upload_to_oss` / `tag_and_push`。 |
| `_config.py` | 加载嵌套 TOML、按渠道解析、按操作校验所需 key。 |
| `_release.py` | **保留**:semver 解析/比较 + appcast 解析(`parse_semver`/`is_newer`/`max_appcast_version`/`read_teleport_version`)。 |

## CLI 与渠道模型

```
python scripts/package.py [--channel dev|canary] [--distribute] [--dry-run]
                          [--config PATH] [--out DIR] [--updates-dir DIR]
```

- `--channel` 默认 `dev`。`--distribute` 仅对可分发渠道有效。`--dry-run` 打印解析后的计划。
- 移除 `--no-upload`(默认即不发布)。
- `--updates-dir` 默认 `dist/<channel>`(`/dist` 已 gitignored)。

### 渠道注册表(代码内,`_build.py`)

| channel | out 目录 | distributable | autoninja 目标 |
|---|---|---|---|
| `dev` | `out/mac/arm64/dev` | ✗ | `chrome` |
| `canary` | `out/mac/arm64/release` | ✓ | `chrome chrome/installer/mac` |

- 脚本**不做 `gn gen`**(沿用现状:人工先 `gn gen`,release 渠道还要拉 PGO);渠道只决定
  out 目录、是否可分发、构建目标。
- `--out` 可覆盖默认 out 目录。
- 未来 beta/stable 在表中追加条目即可(复用 release 构建,渠道身份按打包期注入)。

### 三种运行模式

| 命令 | 行为 |
|---|---|
| `package.py`(默认 dev) | 仅 `autoninja … chrome`,产出 `Teleport.app`。不签名/不 dmg/不发布。 |
| `package.py --channel canary` | 构建 → stamp → 签名 → 公证 → 样式 dmg,**本地停**(测渠道包)。不 appcast/上传/tag。 |
| `package.py --channel canary --distribute` | 上面 + 发布护栏 + appcast + OSS 上传 + 打 tag + push。 |
| `--distribute` 用在 dev | **报错**:dev 渠道不可分发。 |

## 配置(嵌套 `[channel.x]`)

```toml
# 账号级共享
notary_profile = "teleport-notary"
# codesign_identity = "Developer ID Application: <Name> (<TEAMID>)"   # 省略则自动探测
# git_remote = "origin"   # 省略默认 origin

[channel.canary]
public_ed_key      = "PASTE_BASE64_PUBLIC_KEY"
feed_url           = "https://<bucket>.../canary/<token>/appcast.xml"
download_base_url  = "https://<bucket>.../canary/<token>/"
oss_upload_target  = "oss://<bucket>/canary/<token>/"
```

- **dev 完全不读配置文件**:默认 `package.py`(dev)不依赖 `release_config.local.toml`。
- **按操作分级校验**:
  - stamp 需 `public_ed_key` + `feed_url`;
  - 公证需 `notary_profile`(+ codesign 身份);
  - 发布额外需 `download_base_url` + `oss_upload_target`。
  - 缺哪个报哪个,而非一上来要求全部。
- 同步把 `release_config.local.toml.example` 改成嵌套形态。

## 发布护栏与时序(`--distribute`)

**构建前**(快速失败,避免白等数小时编译):

1. 渠道可分发?否则报错。
2. 当前在 `main` 分支?(`git rev-parse --abbrev-ref HEAD == "main"`)否则报错。
3. 工作区干净?(`git status --porcelain` 为空)否则报错——否则 tag 代表不了实际产物。
4. 未发布过?**tag 与 feed 双查**:`v<version>` tag 不存在 **且** feed 最大版本 < version。
   命中任一即报错(tag 已存在 → 提示 bump `TELEPORT_VERSION`)。

**构建后、上传后**:

5. 上传前**再查一次**已发布(防长构建期间被别处抢发,廉价)。
6. 裁剪 updates-dir 到单个 dmg(沿用现逻辑)→ `generate_appcast` → `upload_to_oss`。
7. **上传成功后**才 `git tag -a v<version> -m "release <version>"`(annotated)→
   `git push <remote> v<version>`(remote 默认 `origin`,可配 `git_remote`)。

> 边界:上传成功但 push 失败 → OSS 已发布、tag 仅本地。重跑会被 feed 双查拦下并提示手动
> push tag。tag 在上传**之后**打,避免给失败发布留死 tag。

## 测试(pytest,务实)

- `_release` 现有 semver/appcast 测试保留。
- 渠道解析:未知渠道报错;dev 非 distributable;out 映射正确。
- `--distribute` + dev → 报错文案。
- 护栏(mock git/subprocess):非 main 拒绝;脏树拒绝;tag 存在或 feed ≥ version 拒绝。
- tag 名格式 `v<semver>`。
- `stamp_and_inject` 每小时 `SUScheduledCheckInterval` 用例迁移后仍绿。
- config:dev 无需配置;distributable 缺 key 报错;嵌套渠道解析。

## 迁移 / 杂项

- `package_release.py` → `package.py`;更新 CLAUDE.md 全部引用、`scripts/smoke_check.md`(若涉及)、测试 import。
- 更新 CLAUDE.md "渠道包/自动升级"命令块:`--no-upload` → `--channel canary`;
  发布 → `--channel canary --distribute`;dev 本地包 → `package.py`(默认)。
- `release_config.local.toml.example` 改嵌套形态。`/dist` 已忽略,无需改。

## 非目标(YAGNI)

- 不实现 beta/stable 渠道(仅在注册表/配置预留扩展点)。
- 不做 Windows/Linux 打包。
- 不让脚本自动 `gn gen`(继续人工)。
- 不做全静默后台升级、企业版 Omaha 等(见 CLAUDE.md「待定/后续」)。
