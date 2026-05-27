# macOS dogfood 通道包 + 自动升级 — 设计

> **状态**:已批准设计(brainstorm 产出)。
> **日期**:2026-05-26。**分支**:`worktree-macos-dogfood-channel`。
> **上游**:M148(`148.0.7778.180`)。**平台**:仅 macOS(Apple Silicon)。

## 1. 目标

为内部团队提供一条可分发、**具备自动升级能力**的 dogfood 通道包:首次分发之后,新版本通过自动升级触达,无需手动重新下载安装。一次性打通"编译 official → 打包 → Developer ID 签名 → 公证 → 托管 → 升级触达"的完整流水线。

## 2. 范围

**本期(MVP)做:**

- 仅 **macOS(Apple Silicon)**,复用现有已跑通的 overlay 构建。
- **official 构建**(`is_official_build=true`),独立 out 目录 `out/mac/arm64/release`(dev 仍在 `out/mac/arm64/dev`)。
- 升级框架:**Sparkle 2**(静态 appcast),不用 Omaha。
- 升级体验:**提示 + 一键升级**(Sparkle 自带 UI);app 安装在 **`/Applications`**。
- 托管:**对象存储 + HTTPS** 静态 feed;桶**公开可读 + 难猜路径 + EdDSA 签名**。
- 签名:**Developer ID Application(个人账号)**+ Hardened Runtime,**复用 Chrome 自带的 `chrome/installer/mac/signing/`** 模块,`notarytool` 公证 + `stapler` 装订。
- **版本号体系**:新增 `TELEPORT_VERSION` 静态文件,semver 形式(起始 `0.1.0`),显示与 Sparkle 比较两用。
- 产物:**单一 `.dmg`**,同时用于首装与升级(dmg 亦保住 Sparkle 密钥轮换的代码签名兜底,见 §7.1)。
- 首次分发引导 + 升级闭环冒烟验证 + 回滚预案。

**不在本期(YAGNI / 后续 phase):**

- **全静默后台升级**(Chrome 式):地基前向兼容,后续翻开关即可,**不需要废弃任何本期工作**。
- **Omaha 4 / `chrome/updater` + 自建 Omaha 服务器**:留给未来面向企业批量部署的 phase。
- 增量(delta)更新;Intel / universal binary;Windows / Linux。
- CI(本仓库 CI 尚未建立);崩溃 / 隐私上报;多通道实装(结构留口,只上 dogfood 单通道)。
- 完整 rebrand(`CFBundleDisplayName`=闪现、产品 semver 命名策略等)——版本号形式 `0.1.0` 已前向兼容,rebrand 时只换名字、版本形式不动。

## 3. 方案决策

### 3.1 Sparkle 而非 Omaha

对象存储是静态托管,服务不了 Omaha 的动态 JSON 请求/响应协议;静态托管下实质只能用 Sparkle。Sparkle 2 的静态 appcast + EdDSA 签名正好契合,且是 macOS 生态最成熟方案(Brave、Vivaldi 均用)。自建 Omaha(rebrand `chrome/updater` + 自建并运维 Omaha 服务器 + root 特权助手)为周到月级工程,并自背一块提权攻击面(参见 CVE-2026-7997),dogfood 阶段严重过度设计。

### 3.2 提示 + 一键升级,装 /Applications,无 root 助手

"能否在 `/Applications` 静默升级"取决于**是否常驻 root 特权助手**(Chrome 的 Keystone/Omaha4 守护进程),与升级协议正交。本期选**提示 + 一键**:用户点「更新」时本就在交互,Sparkle 安装时最多弹一次管理员密码(若 dmg 把 app 属主设为当前用户+staff,则连密码都不弹),**无需任何 root 助手**,规避提权攻击面。

> 若未来要 Chrome 式"装 `/Applications` 且全静默",路径是给 Sparkle 配特权助手(`SMAppService` LaunchDaemon)——作为后续增量,本期不做。

### 3.3 桶访问:公开可读 + 难猜路径 + EdDSA

dogfood 阶段取最简:对象公开可读,但 appcast/产物路径含**不可猜测的随机段**,完整性由 **EdDSA 签名 + Sparkle 代码签名校验**保证。已知取舍:拿到 URL 者可下载到内部构建。若未来需要真正访问控制,需引入鉴权端点(Sparkle 对带鉴权 feed 支持弱),会把方案推向后端服务——超出 dogfood 范围。

### 3.4 通道与构建:编译一次,按通道分别打包签名

dogfood / beta / stable 三通道(未来)是**同一份源码**(同 M148 + 同 overlay),差异只在:① 更新 feed(`SUFeedURL`)② app 身份(bundle ID,使多通道并存、各收各的更新)③ 可选显示名/图标 ④ 何时把某构建"晋级"到该通道。这些差异**都不是编译期的**:feed URL 与 bundle ID 在 Info.plist 里、被代码签名封死,故在**打包签名阶段**烘焙;in-app 通道标识(若做)走**运行期**读 Info.plist(同 Chrome `GetChannel()`)。

因此模型为:**编译一次(共享 `out/mac/arm64/release`,数小时)→ 按通道分别打包+签名+公证**,各通道产出各自的 dmg + 各自的 appcast(同 Chrome 签名模块"一次构建、多份 distribution")。**不为每个通道单独编译**;只有出现编译期差异(不同 feature flags 等,本项目没有)才需分别编译。"晋级"= 把已编译版本用目标通道身份打包并发到该通道 feed,stable 只是更新更慢。

**本期**:仅 dogfood 单通道 = 一次编译、一份 distribution;架构按"编译一次 → 打 N 份"预留,加 beta/stable 时不改编译,只在打包/签名层加通道配置。

## 4. 架构与 overlay 落点

核心原则:**贴合现有三层模型**(`patches/` 文本注入、`branding/` 整文件/二进制、`src/` overlay 源码),并用**一个 GN 开关把整套 updater 关在 official 构建里**,dev 工作流零改动。

| 单元 | 位置 | 职责 |
| --- | --- | --- |
| **GN 开关** | `//teleport` GN arg `teleport_enable_updater` | official 默认开、dev 默认关;dev 构建不签名、不加载 Sparkle |
| Sparkle.framework 获取 | 新增 `scripts/fetch_sparkle.py` | 钉版本拉取官方已公证 release → SHA256 校验 → 落全局缓存 → 建符号链接桥进检出 |
| updater 控制器 | `//teleport`(新增 `src/browser/mac/teleport_updater.{h,mm}` + `_unittest`) | 封装 `SPUStandardUpdaterController`;抽薄可测层 |
| framework 入包 | patch chrome mac 打包 BUILD.gn | `bundle_data` 把 `Sparkle.framework` 拷进 `Teleport.app/Contents/Frameworks/` |
| Info.plist 键 | patch mac Info.plist 模板 | 注入 `SUFeedURL`、`SUPublicEDKey`、`SUEnableAutomaticChecks` |
| 启动 + 菜单 | patch `chrome/browser/app_controller_mac.mm` | 启动时实例化 updater;「检查更新…」菜单由 Keystone 改接 Sparkle |
| 版本号 | 新增 `TELEPORT_VERSION` 文件 | semver 单一事实来源,构建期(签名前)戳进 plist |
| 打包驱动 | 新增 `scripts/package_release.py` | official 构建 → 调签名模块 → 产出已签名+已公证+已装订 dmg → 生成 appcast → 上传 |
| Sparkle 组件签名 | 扩展 `chrome/installer/mac/signing/parts.py`(patch) | 把 Sparkle 内嵌 XPC/Autoupdate 纳入 inside-out 签名顺序 |

> M148 已确认:`chrome/installer/mac/signing/` 存在(含 `notarize.py` 用 notarytool、`pipeline.py`、`parts.py`、`rebranding.py`);`chrome/app/app-Info.plist`、`app-entitlements.plist` 等模板存在;`chrome/browser/app_controller_mac.mm` 存在;Keystone 引用在 `keystone_infobar_delegate`、`chrome/browser/updater/`。

## 5. 组件设计

### 5.1 Sparkle.framework 获取与落位(`fetch_sparkle.py`)

复用项目"重物在外、符号链接桥进树内"模式(同 `chromium/`、`build/`、`src/teleport`):

- **钉版本**:钉死某个 Sparkle 2.x 已公证 release(实现期定具体版本号,记录 SHA256;不入库)。
- **全局缓存**:`$TELEPORT_DEPS_DIR`,默认 `~/.cache/teleport/deps`;版本化子目录 `…/sparkle/<version>/Sparkle.framework`——多版本共存,跨 worktree 复用,切分支不必重下。
- **桥接**:`fetch_sparkle.py` 幂等创建符号链接,落在**已 gitignore 的检出区内**(随 chromium 检出走,不属于 teleport 仓库),GN `bundle_data` 引用该稳定树内路径。具体路径(候选 `//teleport/third_party/sparkle/` vs `chromium/src/third_party/teleport_sparkle/`)实现期定,以"`bundle_data` 引用最干净且不污染已提交的 `src/`"为准。
- **校验**:SHA256 不符 fail-fast。

### 5.2 overlay 集成

- **updater 控制器**(`src/browser/mac/teleport_updater.{h,mm}`):封装 `SPUStandardUpdaterController` 的实例化、feed 配置读取、与菜单/启动钩子的接口;尽量把可单测逻辑(如版本可比性、feed URL 组装)抽成纯函数。`//teleport` 的 `BUILD.gn` 在 `teleport_enable_updater` 为真时加入该 `.mm` 并链接 Sparkle.framework。
- **patch · 入包**:chrome mac 打包 GN 加 `bundle_data`,把 `Sparkle.framework` 拷进 `Contents/Frameworks/`(确切 target 实现期用代码探查定位)。
- **patch · Info.plist**:注入三个键——`SUFeedURL`(指向对象存储上含随机段的 appcast URL)、`SUPublicEDKey`(我们的 ed25519 公钥)、`SUEnableAutomaticChecks=YES`(由 Sparkle 自带调度定期检查)。这些键随签名一并封入 bundle;改 feed URL 或轮换密钥需重新构建。
- **patch · 启动 + 菜单**:`app_controller_mac.mm` 在 `AppController` 生命周期内实例化 updater(类比现有 banner 挂在 `chrome_browser_main.cc` 的方式);原 Keystone「Check for Updates」菜单项改接 `SPUStandardUpdaterController.checkForUpdates:`。

### 5.3 版本号体系(`TELEPORT_VERSION`)

- **单一事实来源**:新增 `TELEPORT_VERSION` 静态文件(同 Chrome 的 `chrome/VERSION`、我们现有的 `CHROMIUM_VERSION` 范式:静态、提交进仓库、构建期读取,**不靠 git tag 动态生成**),内含一个 semver(起始 `0.1.0`)。
- **两用**:构建期(**签名之前**,否则破坏签名)同时写入 `CFBundleShortVersionString`(显示)与 `CFBundleVersion`(Sparkle 比较)。Sparkle 标准比较器正确排序 `0.1.0 < 0.1.1 < 0.2.0`,故单一 semver 两用,无需额外整数。具体杠杆(GN arg 注入 vs 签名模块 `modification` 步骤改 plist)实现期确认。
- **显示**:关于页呈现「闪现 / Teleport 0.1.0 · 基于 Chromium 148.0.7778.180」;Chromium 基线版本仍自动出现在 `chrome://version`。rebrand 后版本形式原样不动。
- **递增**:每次发版手动 bump(major/minor/patch 由发布者定)并提交。`package_release.py` 加**护栏**:读线上 appcast 当前最高版,新 semver 不严格大于它则**拒绝发布**,堵死"忘了 bump"。

### 5.4 打包 / 签名 / 公证流水线(`package_release.py` + 复用签名模块)

- **复用 `chrome/installer/mac/signing/`**:它已正确处理 Chrome.app 内嵌 5+ 个需签名项(framework 版本化目录、renderer/gpu/plugin/alerts 等 helper)的 inside-out 签名顺序、entitlements、`notarytool` 公证、`stapler` 装订、dmg 打包。fork 自研风险高,坚决复用。
- **要做的配置/扩展**:
  1. 用 teleport 标识符 + Developer ID(个人)配置 `config.py`/`model.py`(参考 `rebranding.py`)。
  2. 扩展 `parts.py`,把 Sparkle 的 XPC 服务/Autoupdate 加进需签名组件清单,纳入 inside-out 顺序。
  3. 在签名模块的 bundle 定制阶段(签名前)写入 `TELEPORT_VERSION` 的版本。
- **entitlements**:复用 Chrome 现成 `app-entitlements.plist` 等;Sparkle 组件配最小 entitlements(进 `branding/` 或签名配置)。
- **`package_release.py` 串联**:official 构建(`autoninja -C out/mac/arm64/release chrome`)→ 调签名 driver,**按目标通道**套 Info.plist(feed URL / bundle ID / 通道标识)+ 可选图标后签名+公证+装订+dmg → 版本护栏校验 → `generate_appcast` → 上传对象存储。本期只产出 dogfood 一份 distribution。

### 5.5 发布与 appcast

- **生成**:用 Sparkle 的 `generate_appcast`,从 keychain 读 EdDSA 私钥算签名(**私钥绝不入库**),产出/更新 `appcast.xml`。
- **对象存储布局**(单通道,留口给未来多通道):

  ```
  <bucket>/dogfood/<unguessable-token>/
    appcast.xml          ← 短缓存 TTL(新版尽快被发现)
    Teleport-0.1.0.dmg   ← 不可变、长缓存(文件名带 semver)
    Teleport-0.1.1.dmg
  ```

- **appcast 条目**:`url`、`sparkle:version`(= semver)、`sparkle:shortVersionString`、`sparkle:edSignature`、`length`、`minimumSystemVersion`。
- **HTTPS + EdDSA** 双保险。

## 6. 数据流(升级流程)

1. app 启动 → Sparkle 按 `SUEnableAutomaticChecks` 调度,定期 GET `appcast.xml`(HTTPS)。
2. 比对 `sparkle:version` 与本机 `CFBundleVersion` → 有更高版本则弹「有更新可用」。
3. 用户点「更新」→ 下载对应 `Teleport-x.y.z.dmg`。
4. Sparkle 校验 **EdDSA 签名** + 新版**代码签名/团队一致性**(防异签名恶意更新)。
5. 重启时将新版替换进 `/Applications`(必要时弹一次管理员密码)→ 启动新版本。

## 7. 安全

- **传输**:HTTPS feed。**完整性**:EdDSA(ed25519)签名 + Sparkle 代码签名/团队一致性校验,双重防篡改。
- **密钥**:Developer ID 私钥 + EdDSA 私钥**均不入库**(keychain / 密码管理器)。
- **攻击面**:**不跑 root 特权助手**,规避 Keystone 类提权风险(CVE-2026-7997)。
- **桶访问**:公开可读 + 难猜路径(已知取舍见 §3.3)。

### 7.1 密钥管理与丢失恢复

涉及两套独立密钥:**Apple Developer ID**(苹果身份,签名+公证)与 **Sparkle EdDSA**(升级 feed 防伪)。

- **备份(首要)**:EdDSA 私钥不能只躺在发版机 login Keychain。用 `generate_keys -x <file>` 导出,加密存离线 + 密码管理器。Developer ID 证书丢失可经 Apple 吊销并重新签发(Team ID 不变,现网信任不断),恢复性较好。
  - **不走 Secure Enclave**:Sparkle 用 Ed25519,而 Secure Enclave 只支持 P-256 ECC,**Ed25519 无法由 SEP 托管**;Developer ID 私钥为 RSA,同样非 SEP 托管。两把钥匙都走 Keychain + 离线备份,硬件级非导出托管只能靠外部 HSM/智能卡且 Sparkle 无集成,dogfood 不做。
- **EdDSA 私钥丢失的恢复路径 = 密钥轮换**:因包同时有 Developer ID 代码签名,Sparkle 升级校验有两个独立信任锚,允许**一次只换一个**。丢了 EdDSA 私钥时,发"恢复更新":用新 EdDSA 密钥 + 新 `SUPublicEDKey`,但**仍用同一 Developer ID 签名**;现网版本经未变的代码签名接受该更新,从此信任新 EdDSA 密钥。
- **不预埋多公钥**:Sparkle 不支持静态多公钥信任列表(仅为提案),无需也无法靠"备用公钥"恢复;Developer-ID 兜底的轮换才是机制。
- **两条硬约束**:① 轮换的代码签名兜底**仅对 dmg 生效,新版 Sparkle 对 zip/tar 不再支持**——这是选 dmg 作升级产物的又一条理由;② **绝不同时换 Developer ID 与 EdDSA**(两锚皆失配则现网彻底升不动),要换一次只换一个、待全员升级后再换另一个。
- **跨通道/架构/平台密钥策略**:Developer ID 身份所有通道/架构共用一个(通道靠 bundle ID 区分);同一产品不同架构(arm64 / 未来 Intel)共用同一 EdDSA 密钥;EdDSA 为 Sparkle/macOS 专属,未来 Windows/Linux 各用各的更新器与密钥、不共用。通道层面:dogfood / 内部阶段所有通道共用一把 EdDSA 密钥(最简);将来 stable 面向更广受众时,建议给 stable 单独一把以缩小爆炸半径。

## 8. 错误处理

- **公证卡顿**(2026 初已知 Apple 服务问题):`package_release.py` 用 `notarytool` 轮询 + 超时 + 清晰报错,发版流程预留重试缓冲。
- **签名失败**:fail-fast,明确指出哪个组件/哪步。
- **版本护栏**:新 semver ≤ 线上最高版 → 拒绝发布。
- **回滚 / 坏版本**:从 appcast 下架或替换该条目;必要时用 `minimumAutoupdateVersion` 卡最低版本。
- **SHA256 / 下载校验失败**:fetch 与升级各自校验失败即中止。

## 9. 测试策略

- **产品胶水**(`teleport_updater`):抽薄可测层(纯函数:版本可比性、feed URL 组装等),务实写少量 gtest(产品代码走 TDD)。
- **工具脚本**(`fetch_sparkle.py`、`package_release.py`、版本护栏、appcast 校验):有价值处写 pytest(工具不强求 TDD)。
- **端到端冒烟**:构建 v1 → 装 → 构建版本号更高的 v2 → 发 appcast 到测试路径 → 验证完整升级闭环(检测→下载→校验→替换→重启);补进 `scripts/smoke_check.md`。

## 10. 工作分解(Phase)

- **Phase 0 — 前置**:Developer ID 证书就绪;生成 EdDSA 密钥对(私钥安全保管,公钥备用);对象存储桶 + HTTPS + 随机段路径准备。
- **Phase 1 — official 构建**:official GN args + 独立 out 目录 `out/mac/arm64/release`(dev 仍 `out/mac/arm64/dev`);`TELEPORT_VERSION` 文件 + 版本戳记接入。
- **Phase 2 — Sparkle 织入 overlay**:`fetch_sparkle.py`;`teleport_enable_updater` 开关;`teleport_updater.{h,mm}`;入包/Info.plist/启动+菜单 patches。
- **Phase 3 — 签名/公证**:配置 + 扩展 `chrome/installer/mac/signing/`;entitlements;产出可分发 dmg。
- **Phase 4 — 发布流水线**:`package_release.py`(含版本护栏);`generate_appcast`;对象存储布局与上传。
- **Phase 5 — 首次分发**:下载引导(链接/内部页);首次打开 Gatekeeper 提示说明。
- **Phase 6 — 闭环验证 + 预案**:v1→v2 真实升级冒烟;回滚预案;补 `smoke_check.md`。

## 11. 待定 / 实现期确认

- Sparkle 具体钉版本号 + SHA256。
- M148 上 framework 入包的确切 GN target、Info.plist 模板确切文件、Keystone 菜单项当前接法(代码探查确认)。
- 版本戳进 plist 的确切杠杆(GN arg vs 签名模块 modification)。
- 符号链接桥接的确切树内路径。
- 对象存储厂商与随机段 token 生成方式。
- stable 通道引入时是否给其单独 EdDSA 密钥(缩小爆炸半径)。

## 12. 参考

- 本仓库:`docs/superpowers/specs/2026-05-25-overlay-build-foundation-design.md`、`CLAUDE.md`、`scripts/smoke_check.md`。
- Sparkle:<https://sparkle-project.org/documentation/customization/>。
- Apple 公证:<https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution>。
- 集成 Sparkle 进 Chromium:<https://groups.google.com/a/chromium.org/d/topic/chromium-dev/PgzI-a_7ChY>。
- Omaha 4 / 自建 server:<https://omaha-consulting.com/chromium-updater-omaha-4-tutorial>、<https://github.com/omaha-consulting/omaha-server>。
- Sparkle EdDSA 密钥轮换:<https://github.com/sparkle-project/Sparkle/issues/1501>。
