# 技术债登记

> 本文件登记已知但暂缓处理的技术债。每条记录写明:背景、影响、暂行处置、将来方向。处理完成后移到「已结清」或删除并在提交信息中说明。

## 未结清

### TD-001 缺少 Google API key 导致部分云端能力不可用

- **登记日期**:2026-05-31
- **背景**:Teleport 基于 Chromium 自研,构建时未配置 Google API key(`google_api_key` / `google_default_client_id` / `google_default_client_secret`;`src/gn/args/*.mac.gn` 均未设置)。Chromium 的一批云端功能依赖这些 key,缺失时启动会弹「Google API keys are missing. Some functionality of Teleport will be disabled.」提示。
- **当前处置**:已 patch 掉该启动提示(`patches/chrome/browser/ui/startup/infobar_utils.cc.patch`,commit `64d33a8`),避免新装首启被打扰。**提示消除 ≠ 功能恢复**,以下能力仍缺失。

#### 影响分类(基于 M148 源码核实)

判定依据:提示触发条件为 `chrome/browser/ui/startup/infobar_utils.cc` 的 `!google_apis::HasAPIKeyConfigured()`;但各功能是否真坏取决于自身有无兜底。

**A. 因缺 key 而失效 / 退化(理论上配上自有 key 可恢复)**

| 能力 | 源码位置 | 现状 |
|---|---|---|
| Google 整页翻译 | `components/translate/core/browser/translate_script.cc`、`translate_url_util.cc` | 请求带空 key,翻译脚本拉取/调用失败 |
| 密码泄露检测(「检查密码」)| `components/password_manager/core/browser/leak_detection/leak_detection_check_factory_impl.cc` | 安全类,失效 |
| 在线/增强拼写检查 | `components/spellcheck/browser/spelling_service_client.cc` | 仅在线档失效;本地 Hunspell 词典不受影响 |
| Autofill 众包字段识别 | `components/autofill/core/browser/crowdsourcing/autofill_crowdsourcing_manager.cc` | 表单填充仍可用(本地启发式),不查/不传众包数据 |

**B. 需 key 且第三方构建无论如何都拿不到授权(配 key 也无解)**

| 能力 | 说明 |
|---|---|
| Safe Browsing(恶意网址/下载防护)| `components/safe_browsing/**` 多处用 key;Google 仅授权官方 Chrome,个人 key 无效或被限流 |
| 账号登录 / Sync | 需 OAuth `client_id`/`client_secret`,同样仅授权官方 Chrome |
| Lens、Feed、Nearby Share 等 | 多为 Google 专有云服务或 ChromeOS 路径,桌面企业版基本用不到 |

**C. 不受影响(曾被高估,已核实正常)**

- 地址栏搜索建议:走搜索引擎自身 suggest 接口,空 key 占位也照常返回。
- 地理位置(macOS):走 CoreLocation,不经 Google。
- 基础拼写检查、普通浏览/搜索/音视频/扩展:不依赖这些 key。

#### 将来方向(待决策,不在本次范围)

- **B 类(Safe Browsing 等)**:不应依赖 Google,应由 fairyland 自有后端统一提供安全能力(恶意网址拦截、策略管控)。属产品核心方向,需单独立项设计。
- **A 类(翻译等)**:按企业需求取舍——
  - 若保留:评估能否合法获取/自建对应 API key 或替代服务(如自建翻译网关);
  - 若放弃:在产品层面明确禁用并隐藏入口,避免用户点了无反应。
- 决策落地前,A 类功能对用户呈现为「点了无效果」,需注意是否会造成困惑。

#### 补充(2026-05-31「与 Chrome 体验对齐」专项审计,基于 M148 源码核实)

- **优先级:P0**(与「企业安全浏览器」定位直接冲突)。
- **Safe Browsing 的失效形态比「不可用」更糟**:无 key 时各处只做 `if (!api_key.empty())` 判断,而未配置时 key 是字面量 `"dummytoken"`(`google_apis/default_api_keys.h:19`)而非空串,于是拼出 `&key=dummytoken` 发往 `safebrowsing.googleapis.com` 被服务端拒绝(400/403)。`kSafeBrowsingEnabled` 仍为 `true`、设置页显示「防护已开启」——属**「自以为在工作的静默失败」**;叠加本条已抑制的缺 key infobar,用户失去最后的视觉警告,构成**安全剧场**。
- **两条独立链路、同源(均无 Google 后端)**:Safe Browsing 的哈希前缀本地库走 v4/v5 API(`safebrowsing.googleapis.com`,见 `v4_update_protocol_manager.cc`、`hash_realtime_service.cc`),**不走**组件更新器;而 CRLSet/CT 列表等走组件更新器(见 TD-002)。两者都因「无 Google 后端」而失效,需并案评估。
- **止血与方向**:最低止血 = 注入自有 Google Cloud Safe Browsing API key(GN arg `GOOGLE_API_KEY` 或环境变量;非品牌构建 `allow_override_via_environment=true` 允许,见 `api_key_cache.cc`),成本 S,但受 Google ToS/配额限制;长期应由 fairyland 提供自有威胁情报或代理转发(L)。
- **关键引用**:`patches/chrome/browser/ui/startup/infobar_utils.cc.patch`、`google_apis/api_key_cache.cc:334`、`components/safe_browsing/core/common/safe_browsing_prefs.cc:278`、`.../hashprefix_realtime/hash_realtime_service.cc:611`。

---

> **以下 TD-002 ~ TD-011 来自同一次 2026-05-31「与 Chrome 体验对齐」专项审计**,均基于 M148(148.0.7778.180)源码核实。背景统一:Teleport 由 Chromium 源码自建,`GOOGLE_CHROME_BRANDING=false`,缺少 Google 全套后端(API key / 组件更新服务 / 账号同步 / 反馈),导致一批「Chrome 官方版才有」的体验缺失、降级或残留。优先级:P0=与安全定位冲突;P1=半成品/死流程(影响「完整浏览器」观感);P2=品牌一致性;P3=企业决策(刻意偏离 Chrome,多依赖 fairyland 或外部授权)。

### TD-002 组件更新器停摆,安全组件冻结(CT 70 天后 fail-open)

- **登记日期**:2026-05-31 · **优先级**:P0
- **背景**:overlay 完全未触碰 component_updater(`src/`/`patches/` 零命中)。组件更新后端硬编码 `https://update.googleapis.com/service/update2/json`(`components/component_updater/component_updater_url_constants.cc:17`,**无品牌门控**),我们无此后端。结果:有编译期 baseline 的组件**冻结在 build 快照**,无 baseline 的下载式组件**彻底缺失**;浏览器仍每 ~5 小时周期性外联 Google(返回 no-update),既泄露遥测又无收益。注:浏览器本体自更新走 overlay 自研的 Sparkle 链路,与本子系统**无关**。
- **影响(按严重度,均已核实)**:
  - **CT 强制在 build 满 70 天后静默 fail-open**(最严重,可定时):CT 日志列表来自 PKI metadata 组件,无更新则冻结在编译期 `kLogListTimestamp`(`ct_known_logs.cc:22`);`chrome_ct_policy_enforcer.cc:184` 的 `IsLogDataTimely` 判定超 70 天后返回 `CT_POLICY_BUILD_NOT_TIMELY`,而 `net/cert/require_ct_delegate.cc:27` 把该状态视作「满足要求」→ **CT 强制被静默关闭**。错误签发且未上 CT 的证书不再被拦截。
  - **CRLSet 始终为空**(`crl_set_component_installer.cc`,无 baseline):被盗/被吊销中间 CA 的快速吊销能力等同关闭。
  - **Chrome Root Store 冻结**:新增/移除受信根、紧急 distrust 不生效。
  - 次要:File Type Policies(危险文件分级)、Subresource Filter、Safety Tips(反钓鱼提示)停更。
- **当前处置**:无。
- **将来方向**:
  - **止损(S,零后端依赖)**:用 `ComponentUpdatesEnabled` 策略关掉组件更新外联(消除周期连 Google),并以**发版纪律 ≤8 周/版**守住 CT 70 天窗口、跟随上游 root store。
  - **中期(M,依赖 fairyland)**:在 fairyland 起 update2/json 兼容端点,经 `--component-updater=url-source=<url>`(`configurator_impl.cc:80`)或 patch 常量重定向;需自建 CRX 签名 + 改对应 `GetHash()` 公钥 + 镜像/再签 CRLSet 与 PKI metadata。**优先只接 CRLSet + PKI metadata(CT/Root Store)两项必做组件**,这是性价比拐点。与未来企业版 Omaha 4 自更新栈可共用签名/分发基建。

### TD-003 首次运行弹出指向 Google 登录的死路卡

- **登记日期**:2026-05-31 · **优先级**:P1
- **背景**:M148「For You FRE」在 macOS 非品牌构建照常运行(`enable_dice_support` 在 mac 为 true,`components/signin/features.gni:13`;门控 `first_run_service.cc:51,92,345`)。Intro 步骤是一张 sign-in 促销卡(`first_run_flow_controller.cc:541`、`intro_app.html.ts:15`),指向 `accounts.google.com`。
- **影响**:全新安装首启即弹「登录到闪现」引导卡,但无 Google OAuth client/同步后端,点登录无法完成,观感像半成品/借来的流程。后续「设为默认浏览器」卡本身可用。
- **当前处置**:无。
- **将来方向**:S = 加 `--no-first-run` 或标记 FRE 已完成,整体禁用 FRE 直接落 NTP;M = 改造 Intro 移除登录卡、保留默认浏览器卡,登录卡最终形态待企业身份(fairyland)。注:TD-005 的 `BrowserSignin=0` 策略很可能顺带短路本卡(FRE 门控含「允许 sign-in」)。

### TD-004 新标签页展示完整 Google 首页(doodle / OneGoogleBar)

- **登记日期**:2026-05-31 · **优先级**:P1(品牌错位 + 数据外泄)
- **背景**:默认搜索仍是 Google(预置 fallback `google.id`,`template_url_prepopulate_data.cc:274-281`),`DefaultSearchProviderIsGoogle()` 为 true → `search.cc:178` 选用全功能 `chrome://new-tab-page`,注入 Google doodle(`LogoService`,`new_tab_page_ui.cc:1200`)、OneGoogleBar(`:269`,真实向 Google 发请求)、模块。
- **影响**:企业浏览器的新标签页呈现 Google 首页观感,OneGoogleBar 向 Google 外发请求。
- **当前处置**:无。
- **将来方向**:**高杠杆 S** = 把默认搜索锚点从 `google.id` 换成占位企业引擎 → `DefaultSearchProviderIsGoogle()` 变 false → NTP **自动**切到极简 `chrome://new-tab-page-third-party`(无搜索框/无 doodle/无 OneGoogleBar),一举消除 Google 首页。富企业门户 NTP 自研为 L、依赖 fairyland。与 TD-005 同属「锁定企业默认搜索」的产品决策。

### TD-006 「报告问题」反馈提交到 Google(数据外泄)

- **登记日期**:2026-05-31 · **优先级**:P1
- **背景**:overlay 自己解开了 `_google_chrome` gate 让「报告问题」常显(`about_page.html.patch` 还删掉了 `hidden="[[!prefs.feedback_allowed.value]]"` 守卫,`about_page.ts.patch`/`about_page_browser_proxy.ts.patch` 接通 `openFeedbackDialog`),但提交端点仍硬编码 `https://www.google.com/tools/feedback/chrome/__submit`(`components/feedback/feedback_uploader.cc:45`,**非品牌门控**)。
- **影响**:反馈对话框能填能交,数据(可能含截图、系统日志、URL)POST 到 Google——既无法被 Google 正确归集,又构成数据外泄,与「企业安全」定位直接冲突。另:C++ `CanShowFeedback()` 仍读策略 pref `kUserFeedbackAllowed`,策略禁用时点击被静默拦截而前端 link 仍可见(轻微不一致)。
- **当前处置**:无(入口被 overlay 主动启用)。
- **将来方向**:S 止血 = patch `kFeedbackPostUrl` 指向自有/空,或把入口改回隐藏直到后端就绪;M 完整 = 端点指向 fairyland 反馈服务(兼容现有 multipart 格式)+ 恢复有意义的前端可见性守卫。

### TD-007 关于页「隐私政策 / 服务条款」为占位死链

- **登记日期**:2026-05-31 · **优先级**:P1(上线前必须处理)
- **背景**:overlay 去掉 `_google_chrome` gate 无条件显示这两行,并填了占位 URL:服务条款 `https://teleport.example.com/terms`(`patches/.../settings_localized_strings_provider.cc.patch:25`)、隐私政策 `https://teleport.example.com/privacy`(`patches/.../about_page.ts.patch:24`)。
- **影响**:`chrome://settings/help` 页脚两个链接点击即死链。
- **当前处置**:占位 URL。
- **将来方向**:S,待 fairyland/法务提供真实 ToS、隐私政策页 URL 后替换。同类需替换的外部 URL 还有帮助中心(见 TD-009)。

### TD-008 chrome://management 残留 "Chromium" 字样 + Google 帮助链

- **登记日期**:2026-05-31 · **优先级**:P1(企业核心受管页)
- **背景**:`components/management_strings.grdp:78,81` 的非 Google 分支字面写 "managed outside of **Chromium**";该文件属 `components_strings.grd`,**不在** `branding_strings.py` 覆盖的 `components_chromium_strings.grd` 内 → 重写脚本扫不到 → 原样显示。同页「Learn more」链接 `kManagedUiLearnMoreUrl` 指向 `support.google.com/chrome?p=is_chrome_managed`(`url_constants.h:343`)。
- **影响**:企业「由组织管理」页露出 Chromium 字样并跳 Google。
- **当前处置**:**字符串部分已收口**——`branding_strings.py` 扩展为覆盖 `components_strings.grd`(含 `management_strings.grdp`),`IDS_MANAGEMENT_BROWSER_NOTICE` / `..._NOT_MANAGED_NOTICE` 的 "managed outside of **Chromium**" 现 rebrand 为「闪现」(见 spec/plan `docs/superpowers/{specs,plans}/2026-05-31-settings-residual-branding-cleanup*`)。**「Learn more」Google 链接(`kManagedUiLearnMoreUrl`)仍未处理**,随其余指向 Google 的链接一并推迟。
- **将来方向**:剩余的 Learn more 链接重定向/移除,待 fairyland 帮助页 URL 就绪后另起 spec(与 TD-009 链接部分合并处理)。

### TD-009 设置页大面积字面 "Chrome" 残留 + 多处指向 Google 的链接

- **登记日期**:2026-05-31 · **优先级**:P2
- **背景**:`branding_strings.py` 只替换独立单词 "Chromium",**不替换 "Chrome"**,且**不覆盖** `chrome/app/settings_strings.grdp` 与 `chrome/app/generated_resources.grd`(两者共约 500 处含 "Chrome",需甄别可见正文 vs `desc=`/`_google_chrome` 分支/已用 `$1`/`IDS_SHORT_PRODUCT_NAME` 占位的安全条目)。代表样本:`settings_strings.grdp:254`(Chrome Colors)、`:822-831`(地址自动填充 "Remove from Chrome")、`:1480-1582`(广告隐私 "estimated by Chrome")、`:2284-2296`(设置重置)、`:2442-2460`(搜索引擎 "part of Chrome")等。指向 Google 的链接:帮助中心 `kChromeHelpVia{Menu,WebUI,Keyboard}URL`(菜单栏「帮助」也走它)、Chrome Web Store 入口(`extension_urls.cc:41`)、Safe Browsing 说明链(`url_constants.h:500+`)。
- **影响**:设置页多处字面 "Chrome";多个入口跳转 Google。
- **当前处置**:**品牌串部分已收口**——`branding_strings.py` 扩展为新增两个 target:`generated_resources.grd`(含 `settings_strings.grdp` 等 14 个 part)与 `components_strings.grd`(25 个 part),按 en `_CHROME_KEEP` + zh `_CHROME_KEEP_ZH` 外部产品保留表,把可见消息体里的 "Chrome"/"Chromium"/"Google Chrome" → Teleport/闪现(遮罩 `desc=`/`<ex>`/`_google_chrome` 分支),并对四个 `.xtb` 做 id 重键 + 去重;配 3 个 frozen-snapshot drift 测试。dev 增量构建通过(见 spec/plan `docs/superpowers/{specs,plans}/2026-05-31-settings-residual-branding-cleanup*`)。**指向 Google 的链接(帮助中心 `kChromeHelpVia*URL`、Chrome Web Store 入口、Safe Browsing 说明链)仍未处理。**
- **将来方向**:剩余的指向 Google 链接逐个重定向到 fairyland 或隐藏,待 fairyland 帮助/隐私/ToS 落地页 URL 就绪后另起一份 spec(与 TD-007/TD-008 链接部分合并)。

### TD-011 无 DRM / 受保护媒体播放能力

- **登记日期**:2026-05-31 · **优先级**:P3(企业决策 + 外部授权)
- **背景**:`enable_widevine=false`(`is_chrome_branded=false`,默认值见 `third_party/widevine/cdm/widevine.gni:15`);Widevine CDM 二进制走 Google 私有通道 `checkout_src_internal`(`DEPS:3959`,本检出该目录为空);macOS 无 FairPlay 兜底。已开的 codec 开关(`proprietary_codecs`/HEVC/Dolby 等)只覆盖**明文**媒体,加密(EME/DRM)内容仍需 CDM。
- **影响**:Netflix / Disney+ / HBO Max / Amazon Prime Video / Spotify Web Player / Apple TV+ Web 等受 DRM 保护内容**全部无法播放**(报「浏览器不受支持」)。
- **当前处置**:无(默认零 DRM 能力)。
- **将来方向**:**硬前置(商务/法务,L)** = 与 Google Widevine 签订集成/分发授权,拿到授权二进制 + host-verification 证书;之后接入 release 打包链(M)。即便接通,桌面 macOS 仅 L3 / 最高 1080p(与官方 Chrome 相同)。**不依赖 fairyland**。企业办公场景多可作为「已知限制」接受,在产品说明中标注「不支持受 DRM 保护的商业流媒体」。

### TD-012 浏览器画像同步(Chrome Sync 服务端)延期实现

- **登记日期**:2026-06-01 · **优先级**:P3(产品路线项;工程量大,依赖 fairyland 后端)
- **来源**:fairyland 身份平台 / Teleport 账号体系设计(2026-06-01 头脑风暴专门决策延期;fairyland 侧设计文档编写中,落地后回填其路径)。
- **背景**:
  - Teleport 账号体系最终态要求受管浏览器把企业画像(书签/历史/密码/设置等)同步到 **fairyland 自有后端**,而非 Google。Chromium 的 sync server 地址可经 `--sync-url` 完全改向(`components/sync/base/sync_util.h` 的 `GetSyncServiceURL`;与 TD-001-B「账号/Sync 需 Google OAuth」同源问题的自有替代方向),**客户端侧零 fork**。
  - **但 Chrome Sync 协议是 Google 私有的**(`components/sync/protocol/*.proto`),**服务端必须由 fairyland `products/teleport/gateway` 自行实现**(实现 Chrome Sync 协议,或改用基于 Nigori 加密的自定义同步)。这是一块重后端工程,故本期不做。
- **影响**:
  - 一期无企业画像同步(换机/多端不漫游)。
  - **连带影响离职/失权强制**:强制能力中的「**擦除已同步画像数据**」依赖 Sync 先存在,随之延期。一期强制**仍具备**:平台事件驱动的**主动推送强制登出** + 清除企业应用本地 cookie/token(`BrowsingDataRemover` / 远程命令 `BROWSER_CLEAR_BROWSING_DATA`)+ **阻断导航**到企业应用;仅缺「擦同步数据」一项(且无 Sync 时本就无同步数据可擦,自洽,无安全缺口)。
- **当前处置**:不实现 Sync 服务端;`--sync-url` 暂不下发(或指向占位)。身份认证、策略下发、离职强制三条链路**均不依赖 Sync**,可独立先行落地。
- **将来方向**:
  1. 在 `products/teleport/gateway` 实现 Chrome Sync 协议服务端(或 Nigori 加密自定义同步);经托管策略下发 `--sync-url` 指向之;随后补齐强制链路的「擦除已同步数据」。
  2. **关联备忘(同属推送链路的二期增强,非本条但一并留档)**:Chromium 实时失效走 Google FCM(硬绑、不可改向),故一期「主动推送强制」由 teleport-gateway 让浏览器**短间隔(~30–60s)轮询** command-invalidation topic 实现**准实时**(强制延迟 = 轮询周期);二期可自建 invalidation 服务做**真·实时推送**。
- **关键引用**:`components/sync/base/sync_util.h`(`GetSyncServiceURL` / `--sync-url`)、`components/sync/protocol/*.proto`(Google 私有协议)、`chrome/browser/browsing_data/chrome_browsing_data_remover_delegate.*`(`BrowsingDataRemover`)、设备管理远程命令 `DEVICE_WIPE_USERS` / `BROWSER_CLEAR_BROWSING_DATA`(`components/policy/proto/device_management_backend.proto`)。

### TD-013 DMToken 存储目录嵌套在 stable/dev 用户数据目录内(`kDmTokenStorageDir` 布局缺陷)

- **登记日期**:2026-07-04 · **优先级**:P1(布局设计缺陷;pre-release 修复成本 S,拖到发布后则需长期保留迁移逻辑)
- **背景**:`src/common/teleport_enterprise_enrollment.h:25` 的 `kDmTokenStorageDir = "Teleport/Cloud Enrollment/"` 注释声称「Mirrors Chrome's "Google/Chrome Cloud Enrollment/"」,但直译时丢掉了公司伞目录层级:Chrome 的 `Google/` 是伞目录,`Chrome Cloud Enrollment` 与各渠道数据目录(`Chrome`、`Chrome Canary`)**平级**;而我们裸渠道(dev/stable)的用户数据目录本身就是 `Teleport`(`patches/chrome/common/chrome_paths_mac.mm.patch` 的非品牌回退值),于是机器级 DMToken 缓存 `~/Library/Application Support/Teleport/Cloud Enrollment/` **嵌套进了 dev/stable 的用户数据目录内部**——渠道无关的机器级状态寄生在单渠道私有目录里,违背同一头文件注释声明的 channel-agnostic 意图。当时 plan(`docs/superpowers/plans/2026-06-04-enterprise-alignment-phase1-device-enrollment.md:528`)只验证了「不与 per-channel 目录(如 `Teleport Canary`)**冲突**」,嵌套副作用未被识别——属漏看,非有记录的权衡。
- **影响**(功能今日自洽:各渠道读写同一路径、注册链路已 live 验证;以下均为布局带来的耦合):
  - `rm -rf ~/Library/Application Support/Teleport`(最自然的「重置 dev/stable」操作:IT 支持脚本、AppCleaner 类清理工具、用户手动重置)会**静默反注册整台机器的所有渠道**(机器级 token 随单渠道数据陪葬);Chrome 里删 `Google/Chrome` 永远不会碰到 token。
  - 单独运行 canary/beta 会在 stable 的(未来)用户数据目录内创建并写文件(Chrome 从不跨渠道数据目录边界);反向清空 canary 自身目录却**不**清 token——语义不对称、反直觉。
  - 清理文档/脚本被迫 carve-out(`find ... ! -name 'Cloud Enrollment'`)才能做「只清浏览数据、保留注册」。
  - 该常量是未来 Windows/Linux 移植会照抄的模板,不修则错误模式被复制。
- **当前处置**:无。注意给用户/测试机的清理指引须排除 `Cloud Enrollment` 子目录。
- **将来方向(S)**:常量改为**平级兄弟目录** `"Teleport Cloud Enrollment/"`(无公司伞目录时对 Chrome 布局最忠实的直译;不采用 `"Xiaodou Shuan/Teleport Cloud Enrollment/"`——只为此一处引入伞目录而产品目录仍在顶层,不彻底)。改动面已 grep 收口:头文件常量+注释、`src/common/teleport_enterprise_enrollment_unittest.cc:26` 断言(TDD 先行)、`docs/enterprise-device-enrollment.md:97`;fairyland 侧零引用(服务端不关心客户端文件布局)。迁移:pre-release 仅内部测试机,可不写迁移代码——旧目录成无害遗留(顺手删),测试机下次启动经强制注册自动重取 token;需确认 device-manager 按 client id(硬件 UUID 派生,不随清理变)幂等 upsert、不产生重复设备记录。若想省测试机一次重注册,可加「新路径不存在且旧路径存在则搬运」的三行一次性迁移。**须在首个外部发布前完成**,否则升级为带兼容回退的正式迁移工程。
- **关键引用**:`src/common/teleport_enterprise_enrollment.h:25`、`src/common/teleport_enterprise_enrollment_unittest.cc:26`、`patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch`、`patches/chrome/common/chrome_paths_mac.mm.patch`、`docs/enterprise-device-enrollment.md:97`、plan `2026-06-04-enterprise-alignment-phase1-device-enrollment.md:528`。

### TD-015 MAJOR=0 产品版本的残余暴露面(扩展版本门 / flags 过期失效 / 政策过滤超集)

- **登记日期**:2026-07-04 · **优先级**:P2(当下无功能故障;扩展 force-install 落地前升 P1)
- **背景**:产品版本方案(TD-014 的根治工程)把 `chrome/VERSION` 设为四段产品版本(MAJOR=0)。两处 codegen 真值判断已 patch;终审在真实产物中证实仍有三处按 Chromium 里程碑语义消费 MAJOR 的机制受影响。
- **影响**:①`chrome/common/extensions/manifest_handlers/minimum_chrome_version_checker.cc` 以 `version_info::GetVersion()`(=0.1.12.0)比对扩展 manifest 的 `minimum_chrome_version`——几乎所有商店扩展都声明(如 "88"),一律被拒载;Web Store 协议上行 `prodversion=0.1.12.0` 同理会被服务端版本门拦。当下未启用扩展分发,无实际故障;**启用 ExtensionInstallForcelist 前必须处理**。②`tools/flags/generate_expired_list.py` 以 MAJOR 为当前 mstone → `expired_flags_list.cc` 的 `kExpiredFlags` 为空表(已在 dev 产物证实;M148 应有数百条)——上游已过期实验 flag 在 chrome://flags 全部重新可用,企业安全浏览器的用户可达配置面静默扩大。③`components/policy/tools/generate_policy_source.py:130` 的 `if chrome_major_version:` 使 `supported_on` 过滤整体失效,等效 `--all-chrome-versions`,生成政策为超集——**方向安全**(只多不少,无在管政策被丢弃),备案防止将来升基线时被「修好」成会丢政策的方向。
- **当前处置**:无(记录在案)。
- **将来方向**:①扩展门在扩展能力落地时按 UA 同款一文件 patch 换成 `TELEPORT_ENGINE_VERSION_STRING` 比对(S);②flags 过期可接受现状(受管场景可另以策略锁 chrome://flags)或 patch `generate_expired_list.py` 改读引擎版本(S);③政策超集保持现状并在升基线检查清单中注明(零成本)。
- **关键引用**:`minimum_chrome_version_checker.cc:41-51`、`tools/flags/generate_expired_list.py`、`out/.../gen/chrome/browser/expired_flags_list.cc`(空表证据)、`generate_policy_source.py:130`、spec `2026-07-04-product-version-scheme-design.md` §8。

### TD-016 共享 chromium 检出的跨 worktree 状态污染(overlay 只应用不复原、打包无状态守卫)

- **登记日期**:2026-07-05 · **优先级**:P1(污染是**静默的**且直接进入分发产物;当前靠操作纪律而非机制保证,首个外部发布前须落最低守卫)
- **背景**:chromium 检出与 out 目录按设计全局共享(几百 GB 不绑 worktree),`src/teleport` 符号链接是指向某一个 worktree 的**全局单指针**。`apply_patches.py` 的幂等是「向前收敛不复原」:patch reverse-check 命中即跳过、从不回滚(`apply_patches.py:39-44`);`branding_strings` 就地变换**只进不退**(已烘焙的 grd 匹配不到源模式即 no-op);`generate_version` 是唯一无条件收敛项。`package.py` 不前置 `apply_patches.py`、无任何检出状态校验,唯一护栏 `assert_baked_version` 只看版本号一个维度。
- **影响**(多 worktree 来回切换时,三条通道,两条完全静默):①**遗留 patch 混入**——A worktree 独有的 patch 留在检出,B 打包静默带上(仅当 A/B 对同一文件的 patch 冲突才 fail-fast);②**grd 烘焙态残留**——A 烘焙的品牌串使 B 的 `branding_strings` no-op,B 的包带 A 的文案(本轮公司改名时已实际踩过,靠手动恢复 56 个 pristine grd 解决);③**符号链接指错**——B 打包编进 A 的 `//teleport` 源码,无任何脚本校验链接指向。净效果 = 打出「本 worktree 源 + 他 worktree patch/文案」的杂交分发包。
- **当前处置**:操作纪律——同一时刻单活跃 worktree;切换时 `ln -sfn <repo>/src "$TELEPORT_CHROMIUM_DIR/src/teleport"` + 重跑 `apply_patches.py`;品牌串类变更前先恢复 pristine grd 族再重跑。无机制保证。
- **将来方向**:①`package.py` 与 `apply_patches.py` 前置校验 `src/teleport` 链接 realpath == 当前 repo 的 `src/`,不符拒绝(S,几行,最高杠杆);②`package.py` 强制前置跑 `apply_patches.py`(S);③检出内落 overlay 来源 marker(repo root + patches 树 hash + branding 输入指纹),不匹配时拒绝并指引恢复(M);④补「恢复 pristine」工具(reverse 全部 patch + checkout grd 族 + 清生成物)——即 CLAUDE.md「待定」已承认的 patch 工具链缺口(M)。①+②为最低守卫;③④随多人/CI 阶段。
- **关键引用**:`scripts/apply_patches.py:39-44`、`scripts/branding_strings.py`(就地变换)、`scripts/package.py:52-121`(无 overlay 前置/状态校验)、`scripts/_package.py` `assert_baked_version`(仅版本维度)、CLAUDE.md gotcha「从 worktree 跑发布脚本必须 export TELEPORT_CHROMIUM_DIR」(只防路径、不防状态)。

---

> **以下 TD-017 ~ TD-024 来自 voluntary-enrollment-ux 特性实现评审(2026-07-24)**,均基于该特性 spec `docs/superpowers/specs/2026-07-24-voluntary-enrollment-ux-design.md` 与实现期核实。背景统一:该特性把强制纳管 gate 默认值翻转为关闭(BYOD-first),新增 profile 菜单自愿登录入口与 GAIA 结构性抑制;以下均为实现期评审发现、明确记录为暂缓处理的残余,而非本特性范围内的阻断项。

### TD-017 gate 的企业下发通道未实现(仅 dev 本地生效)

- **登记日期**:2026-07-24 · **优先级**:P2(功能自洽——BYOD-first 默认对当前发布阶段正确;企业客户要求强制纳管前必须补)
- **背景**:强制纳管唯一开关 `kRequireEnrollmentToBrowse`(`teleport_pref_names.h`)是纯 local_state 布尔 pref,注册于 `RegisterEnrollmentGateLocalStatePrefs`(默认 false)。本特性**没有**提供任何企业下发该开关的通道——既非 MDM forced pref(macOS managed preferences),也非机器配置文件字段(`/Library/Teleport/DeploymentConfig.json` 目前只承载 `DeploymentDomain`,不含 gate 开关),也未映射为 CBCM 云策略。
- **影响**:企业客户今天**没有任何生产可用的方式**把浏览器切到强制纳管模式;唯一验证手段是手改 local_state 或测试钩子(`ResetRequireEnrollmentGateForTesting`),不可用于真实设备下发。
- **当前处置**:无(spec §2 非目标,dev-only 验证)。
- **将来方向**:比照 `DeploymentDomain` 已有的三级下发模式(命令行 / MDM forced pref / 机器配置文件)新增一个 gate 布尔键,读取时机与 `RequireEnrollmentGateEnabled()` 的会话冻结语义对齐(§4.1);CBCM 云策略映射需与 fairyland 策略协议同步设计。
- **关键引用**:`src/browser/enterprise/teleport_enrollment_gate.{h,cc}`、`src/browser/enterprise/teleport_force_signin.{h,cc}`、spec §2「非目标」。

### TD-018 `chrome://settings` guest 开关回显与动态禁用 desync

- **登记日期**:2026-07-24 · **优先级**:P2(视觉误导,无安全缺口——实际动作已 fail-closed)
- **背景**:gate ON 时 `profiles_state.cc.patch` 的 `IsGuestModeGloballyDisabledInternal()` 无条件 `return true`(不查 `kBrowserGuestModeEnabled` pref),`IsGuestModeRequested()` 同样在 gate ON 时提前拒绝 `--guest`/`BrowserGuestModeEnforced`。但 `chrome://settings` 里 guest 开关的显示态绑定的是底层 pref `kBrowserGuestModeEnabled` 本身(未改动),该 pref 值不受 gate 影响,故 UI 仍显示「已启用」,与实际行为(禁用)不一致。
- **影响**:管理员/用户在 settings 页看到 guest 开关「开」,但实际点击 profile 菜单/picker 里的 guest 入口已不可用(隐藏或 fail-closed guard 拦截)——纯展示误导,不构成绕过(§4.4 四点覆盖已 fail-closed)。
- **当前处置**:无(spec §4.4 已记录为已知限制)。
- **将来方向**:S,settings 数据源(`people_page`/`guest_mode`相关 handler)接入 `teleport::RequireEnrollmentGateEnabled()` 谓词,gate ON 时开关本身回显禁用态(而非仅动作被拦)。
- **关键引用**:`patches/chrome/browser/profiles/profiles_state.cc.patch`、spec §4.4。

### TD-019 settings「Sync and Google services」死行 + `chrome://signin-*` 死壳未清理

- **登记日期**:2026-07-24 · **优先级**:P2(品牌/体验一致性,非安全)
- **背景**:GAIA 已经 §4.8 结构性抑制(`CanEnableDiceForBuild()=false`),但 `chrome://settings` 内仍残留「Sync and Google services」相关行(死路,点击不可达任何功能),且 `chrome://signin-*` 系列 WebUI(如 `signin-internals`)仍作为死壳出现在 `teleport://teleport-urls`(`chrome://chrome-urls`)目录列表里。
- **影响**:非功能性但观感不专业——用户在 URL 目录页看到一批点了无意义的 `signin-*` 条目,settings 页有一行导向无实际内容的入口。
- **当前处置**:无(TD-005 结清时记录的已知残余)。
- **将来方向**:S,从 `teleport-urls`/`chrome-urls` 目录页隐藏这批 WebUI host(比照已有 host 隐藏机制,若无则新增);settings 侧隐藏或删除该死行(可能需 patch `people_page.html` 或相邻 grdp)。
- **关键引用**:spec §4.8;`chrome/browser/ui/webui/signin_internals_ui.{h,cc}`。

### TD-020 device-signals 永久同意位未由就地注册器设置

- **登记日期**:2026-07-24 · **优先级**:P3(评估型;当前无已知功能故障)
- **背景**:上游 OIDC 新建 profile 流程(`OidcAuthenticationSigninInterceptor` / `ManagedProfileCreator` 路径)在纳管时会顺带设置 device-signals 的永久同意 pref;本特性的就地注册器(`TeleportOidcInPlaceRegistrar::ApplyManagedAttributes`)只设置了 management id / OIDC tokens / dasherless 标记 / 身份显示名与邮箱(见 `teleport_oidc_inplace_registrar.cc:156-196`),**未**设置该同意位。
- **影响**:待评估——若企业策略(如设备信号上报)依赖该 pref 判断「用户已同意」,就地纳管的 profile 可能被判定为未同意,阻塞相关信号采集;若该 pref 只是上游遗留的 UX 记忆而非策略强依赖,则无实际影响。
- **当前处置**:无(spec §4.5 记为待评估 TD)。
- **将来方向**:S,核实该 pref 是否被任何已启用的策略/信号采集路径读取;若是,则在 `ApplyManagedAttributes` 内同批设置。
- **关键引用**:`src/browser/enterprise/teleport_oidc_inplace_registrar.cc:156-196`、spec §4.5。

### TD-021 picker 纳管中途取消的删除竞态:现有 guard 只是纵深防御,非精确修复

- **登记日期**:2026-07-24 · **优先级**:P2(已知残余,已接受;非阻断)
- **背景**:gate ON 的 picker 新建 profile 流程中,用户中途取消会触发半成品 profile 删除(ephemeral 语义)。Task 6.4 加的 guard(`teleport_oidc_inplace_registrar.cc:331-337`)在 `OnPolicyFetchComplete` 里检查 `profile_->GetPath().empty() || IsProfileDirectoryMarkedForDeletion(...)`,命中则跳过 `PersistEnrolledDomain()`。但实测时序追踪显示:删除标记(deletion mark)是在该 guard 检查**之后**才落下的——即这条 guard 是纵深防御(缩小竞态窗口),不是精确修复;真正精确的修复需要一个从「picker 取消」贯穿到「注册器」的显式取消信号(如 `base::WeakPtr` 失效检测,或注册器持有的 `IsCancelled()` 查询点)。
- **影响**(已接受的已知残余,与机器 DM token 清理同池):取消竞态命中时,①`kEnrolledDeploymentDomain` 全局 pref 可能被写入一个随后即被删除的 profile 的纳管域名(不阻断——下次成功纳管会覆盖该值);②服务端可能留下一条孤儿注册记录(同 §4.6 item 5 已知残余)。均非安全缺口,只是清理不彻底。
- **当前处置**:Task 6.4 的 guard 作为纵深防御保留;残余记录在案,不阻断发布。
- **将来方向**:M,给 `TeleportOidcInPlaceRegistrar` 接一个取消信号(picker pop 闭包触发时置位,注册器在 `OnPolicyFetchComplete`/`RunDoneAndDelete` 前查询),彻底消除该竞态窗口而非仅缩小。
- **关键引用**:`src/browser/enterprise/teleport_oidc_inplace_registrar.cc:322-337`、spec §4.6 item 5。

### TD-022 换域迁移时已开浏览器窗口的关闭策略未定义

- **登记日期**:2026-07-24 · **优先级**:P2(已知限制,非阻断)
- **背景**:§4.9(Task 7.1)的运行期换域迁移修复让 `MaybeHandleDomainMigration` 在检测到 `resolved_D ≠ enrolled_D` 时,gate ON 下同步 `entry->LockForceSigninProfile(true)`,确保**该 entry**在未来的窗口/启动即被锁定;运行期的 http(s) 主框架导航则由 throttle 兜底重定向。但**当前已经打开的浏览器窗口**(已加载的页面、已打开的 chrome:// 标签等)在锁定生效那一刻应该被强制关闭、最小化,还是允许用户继续操作直至下次导航被 throttle 拦截——这一策略未定义,当前实现只覆盖了「锁 + throttle」两点,未覆盖「已开窗口本身」。
- **影响**:迁移发生的瞬间,用户已打开的窗口/标签仍可继续与已加载页面交互(仅新的 http(s) 主框架导航会被拦),行为在锁定态与「浏览器窗口仍存活」之间存在一个未明确定义的中间态。
- **当前处置**:无(spec §4.9 记为已知限制)。
- **将来方向**:M,产品决策 + 实现:明确迁移瞬间对已开窗口的处理策略(强制关闭 / 提示后关闭 / 维持现状仅拦新导航),据此决定是否需要新增窗口层面的响应逻辑。
- **关键引用**:`src/browser/enterprise/teleport_enrollment_gate.cc:73-124`、spec §4.9。

### TD-023 profile 菜单 Teleport 登录入口缺 browsertest 覆盖

- **登记日期**:2026-07-24 · **优先级**:P2(测试覆盖缺口,非功能故障)
- **背景**:`ProfileMenuView::OnTeleportSigninButtonClicked()`(`profile_menu_view.cc.patch`)镜像上游其余菜单按钮处理器的模式:先 `OnActionableItemClicked()`(这一步同时记录 UMA 桶、且是抑制菜单关闭后 HaTS 调查弹出的关键副作用),再检查 `perform_menu_actions()` 测试门(测试态下短路,不真正关闭菜单/跳转),最后关闭菜单并打开纳管 tab。这套「HaTS 抑制 + 测试门」行为目前**没有任何 browsertest** 覆盖(仓库内搜索 `OnTeleportSigninButtonClicked`/相关 browsertest 均零命中)。
- **影响**:该点击处理器的正确性(尤其是 HaTS 抑制副作用与 `perform_menu_actions` 测试门是否真的生效)只能靠人工验证或代码走读确认,回归风险无自动化兜底。
- **当前处置**:无。
- **将来方向**:S,新增一个 browsertest(比照上游其余 `OnSigninButtonClicked` 等处理器已有的测试模式),断言点击后:UMA 记录、`perform_menu_actions_for_testing(false)` 下不跳转、菜单正常关闭并打开 `EnterpriseEnrollUrl()`。
- **关键引用**:`patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch:40-48`。

### TD-024 `SetProfileManagementOidcTokens` 的 `identity_name` 写入未做空值 guard

- **登记日期**:2026-07-24 · **优先级**:P3(观感一致性,非功能故障)
- **背景**:`TeleportOidcInPlaceRegistrar::ApplyManagedAttributes`(`teleport_oidc_inplace_registrar.cc:162-164`)无条件把 `user_display_name_`(可能为空串)塞进 `tokens_with_name.identity_name` 再调用 `entry_->SetProfileManagementOidcTokens(tokens_with_name)`;而同一函数内紧随其后的 `kProfileUserDisplayName`/`kProfileUserEmail` pref 写入(`:183-190`)都有 `!empty()` 判空 guard 才写。两处对「显示名可能为空」的处理不一致。
- **影响**:纯粹的代码一致性问题——若 `user_display_name_` 为空,`identity_name` 会被显式设为空 `std::u16string`(而非保持未设置/默认值),目前未观察到因此导致的可见异常(下游读取路径大概率对空串已有兜底),但风格上与旁边的判空写法不对称,容易被后续维护者误解为「有意为之的差异」。
- **当前处置**:无。
- **将来方向**:S,评估是否给 `identity_name` 赋值同样加 `!user_display_name_.empty()` guard,或反过来把旁边两处 pref 写入的判空去掉、统一为无条件写入——两个方向都可,择一并写清楚理由注释即可。
- **关键引用**:`src/browser/enterprise/teleport_oidc_inplace_registrar.cc:156-190`。

### TD-NOTE 已核实「沉默良好态」,无需处理(留档防重复调研)

- **登记日期**:2026-05-31
- 因 `GOOGLE_CHROME_BRANDING=false`,以下遥测/上报在非品牌构建里被上游默认关死,**均不联 Google**,现状即理想 MVP 态,无需做减法:
  - **崩溃上报(Crashpad)**:上报 URL 仅在 `GOOGLE_CHROME_BRANDING && OFFICIAL_BUILD` 定义,非品牌返回空串且 consent 恒 false(`crash_reporter_client.cc:26,148`;`chrome_crash_reporter_client.cc:198`)→ 只写本地 minidump、不上传、无死 UI。
  - **UMA 指标**:上送 URL 经 Google 内部 GRD 注入,公开树为空(`server_urls.cc:24`);consent toggle 整块 `_google_chrome` 门控 → 不渲染。日志采集后丢弃。
  - **Variations / Finch 种子**:`IsFetchingEnabled()` 在非品牌构建除非命令行给 URL 否则返 false(`variations_service.cc:222`),叠加已开的 `disable_fieldtrial_testing_config` → 启动不拉任何 seed,每个 feature 钉死编译期默认。
  - **RLZ**:`enable_rlz=is_chrome_branded` → 编译期即关闭,代码不编入。
- 未来若要自建 telemetry/crash/variations 后端,各为 L 级且依赖 fairyland 对应服务,归入后续 phase,MVP 不动。
- 唯一从「沉默良好态」被 overlay 自己**破坏**的是反馈端点 → 已单列 TD-006。

---

## 已结清

### TD-005 release 构建下 Google 登录按钮可见且通向失败流程(已解决:菜单面)

- **登记日期**:2026-05-31 · **结清日期**:2026-07-24 · **优先级**:P1
- **背景**:Dice 因 `HasOAuthClientConfigured()==false` 被构建级禁用,但 profile 菜单登录按钮只看 `prefs::kSigninAllowed`(默认 true,`signin_utils_desktop.cc:35`),**不查 OAuth client 是否配置**;且 `ShowDiceSigninTab` 对「Dice 未启用」的检查只在 `DCHECK_IS_ON()` 内(`signin_view_controller.cc:599`)。official/release 构建 DCHECK 关闭 → 跳过检查 → 打开真实 `accounts.google.com`,OAuth 用 `dummytoken` 交换令牌**失败**(dev 构建则命中 DCHECK abort)。
- **处置(voluntary-enrollment-ux 特性,spec §4.8)**:不再是「policy 顺带短路」的权宜止血,而是**结构性**修复——patch `AccountConsistencyModeManager::CanEnableDiceForBuild()` 恒 `return false`,使 `kSigninAllowed` 恒为 false、DICE 恒 `kDisabled`,`CanOfferSignin` 结构性失败,上游 GAIA 登录按钮/建号/FRE 登录屏/DICE web 拦截/头像 pill 等**全部表面**一次钉死(不再依赖「构建无 OAuth key」的偶然性)。同时 profile 菜单(`profile_menu_view.cc.patch` 的 `GetIdentitySectionParams`)新增 Teleport 自有「登录」入口(未纳管态)与「由 <机构> 管理」header(已纳管态),替代上游 GAIA 分支——菜单面不再有任何指向 `accounts.google.com` 的按钮。People 设置页的 dasherless「isn't associated with Google」残留通知同批用 `people_page.html.patch` 强制 `dom-if` 恒 false 抑制。
- **仍未解决(见 TD-019)**:`chrome://settings`「Sync and Google services」死行、`chrome://signin-*` 系列死壳 WebUI 未清理,`teleport-urls` 目录仍列出这些不可达/无实际功能的入口。
- **关键引用**:`patches/chrome/browser/signin/account_consistency_mode_manager.cc.patch`、`patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch`、`patches/chrome/browser/resources/settings/people_page/people_page.html.patch`、spec `docs/superpowers/specs/2026-07-24-voluntary-enrollment-ux-design.md` §4.5/§4.8。

### TD-010 隐私设置存在 UKM「死 toggle」(已解决)

- **登记日期**:2026-05-31 · **结清日期**:2026-06-01 · **优先级**:P2
- **背景**:「让搜索和浏览更好」开关(`url_keyed_anonymized_data_collection`)位于 `_google_chrome` 块**之外**(`chrome/browser/resources/settings/privacy_page/personalization_options.html:93`),非品牌构建仍渲染;但 UKM 上送 URL 在公开 Chromium 为空(`components/metrics/server_urls.grd` 占位 `-`)→ `NetMetricsLogUploader` 短路丢弃日志,成为「点了有反应却无任何后果」的死控件。
- **处置**:新增 patch `patches/chrome/browser/resources/settings/privacy_page/personalization_options.html.patch`,把 `urlCollectionToggle` 裹进 `<if expr="_google_chrome">...</if>`,使本构建(`_google_chrome=false`)不渲染该 toggle(与相邻 toggle 的上游写法一致)。见 spec/plan `docs/superpowers/{specs,plans}/2026-05-31-settings-residual-branding-cleanup*`。

### TD-014 分发包内多处暴露 Chromium 版本号(根治需构建期版本方案工程)(已解决)

- **登记日期**:2026-07-04 · **优先级**:P2(信息暴露/品牌一致性;无功能故障) · **结清日期**:2026-07-04
- **背景**:产品对外版本应只呈现 `TELEPORT_VERSION`(About/`chrome://version` 已由 `//teleport` 的 `teleport_version` 处理;dmg 命名、appcast、主 app 两个版本键的打包期 stamp 亦然),但 2026-07-04 对 dev 构建 + 已装 canary 包的全量审计(遍历 plist 键值 + 路径名 + `strings -a` 二进制,扫 `148.0.7778.180`)发现 .app 内部仍多处为 Chromium 版本。
- **已修(commit 本条同批)**:① 各 locale `InfoPlist.strings` 的 `CFBundleGetInfoString`(Finder 简介可见「Teleport 148.0.7778.180」)——patch `infoplist_strings_util.cc` 去掉版本段,只保留「产品名, 版权」;② `SCMRevision`(主 app/Framework/Alerts helper 三处 plist,泄露 chromium 检出 commit + `branch-heads/7778`)——`chrome/BUILD.gn` 的 `tweak_info_plist` 三处置 `--scm=0`(注意:该开关**默认开**,Alerts helper 因未显式传参而中招)。
- **未修(根治由本工程完成)**:
  1. **框架 versioned 目录名** `Teleport Framework.framework/Versions/148.0.7778.180/`——与主 exe 硬耦合:`chrome/app/chrome_exe_main_mac.cc:182` 以编译期常量 `CHROME_VERSION_STRING` 拼相对路径 `dlopen`,打包期改名必启动失败;
  2. **嵌套 bundle 版本键**:4 个 Helper .app、Framework `Resources/Info.plist`、`app_mode-Info.plist`(app shim 模板)的 `CFBundleShortVersionString=148.0.7778.180` / `CFBundleVersion=7778.180`(`_package.py` 只 stamp 主 app);
  3. **二进制内嵌串**:主 exe 的 dlopen 路径、Framework 内裸版本串与 `Chrome/148.0.7778.180`(UA 模板常量;实际外发 UA 经 UA reduction 为 `Chrome/148.0.0.0`);
  4. **Web 可见指纹**:UA major(148)与 UA-CH brands——web 兼容性依赖,业界(含 Brave)均不隐藏,**视为不可修**;
  5. **企业上报**:DM 状态上报的浏览器版本 = Chromium 版本(fairyland 管理面可见)——功能性信息(服务端按引擎版本适配策略),是否改为产品版本属产品决策、牵动跨仓库协议。
- **将来方向(L)**:构建期版本方案工程(Brave 路线)——以 `TELEPORT_VERSION` 替换/派生 `chrome/VERSION`,让 `CHROME_VERSION_STRING`、框架 `Versions/` 目录、全部嵌套 plist 版本键一体变为产品版本。设计面:UA 必须保留 Chromium 版本(否则 `Chrome/0.x` 致 web 兼容崩坏,需双版本常量,Brave 即如此)、Sparkle 比较键语义(构建期即产品版本后,打包期 stamp 冗余化)、DM 上报版本语义(fairyland 协议面)、发版 bump 触发的全量重编成本。
- **关键引用**:`chrome/app/chrome_exe_main_mac.cc:182`、`patches/chrome/BUILD.gn.patch`(`--scm=0` ×3)、`patches/chrome/tools/build/mac/infoplist_strings_util.cc.patch`、`build/apple/tweak_info_plist.py:336`(`--scm` 默认开)、`scripts/_package.py`(stamp 仅主 app)。
- **处置**:构建期以 `TELEPORT_VERSION`(四段化)生成 `chrome/VERSION`(`scripts/generate_version.py`,经 apply_patches 前置),框架目录/全部 plist/内嵌路径随之为产品版本;UA/UA-CH 经生成的 `teleport_engine_version.h` 钉住引擎版本(3 个 patch);`CFBundleVersion` patch 为完整四段;打包删 stamp 改烘焙断言;DM `agent` 参数附 `Chromium/<引擎版本>` 供 fairyland 存储展示。见 spec `docs/superpowers/specs/2026-07-04-product-version-scheme-design.md`。

## TD-TUNNEL-UNITTEST-WIRING · P1d Track T tunnel 单测在 teleport_unittests 里不可编/不可跑 — ✅ 完全解决(2026-07-27,4/4 组真跑真过)

- **登记日期**:2026-07-26 · **优先级**:P2(测试覆盖缺口;client 构建与运行不受影响) · **结清日期**:2026-07-27
- **已解决 · 纯逻辑三组(轻量 `teleport_unittests`)**:把两个纯 free function(`DeriveRoutableOrigins`/`BuildTunnelProxyConfig`)从 `teleport_tunnel_service.{h,cc}` 抽进**独立轻量 source_set `:teleport_tunnel_logic`**(`teleport_tunnel_logic.{h,cc}`,只依赖 //base+//net+//services/network mojom+//url)。三组测试(`RoutesDeriver`×2 + `ProxyConfig`)搬入 `teleport_tunnel_logic_unittest.cc` 接进 `teleport_unittests`。**零 chrome/browser patch 改动**:`:teleport_tunnel_logic` 设为 `:teleport` 的 `public_dep`,chrome/browser(已 `deps += "//teleport"`)经传递链接。实证:`teleport_unittests` 128 测试绿 + 增量 `chrome` 构建 `libchrome_dll.dylib` 重链 `nm` 确认含两符号。
- **已解决 · BindClient fixture 五组(重型 `unit_tests`)**:`TeleportTunnelBindClientTest`(5 个测试:单跳 bind 无 Authorization、8min 刷新环重铸+重推、刷新失败复用 backoff、重启自启、未纳管不自启)需完整 `TeleportTunnelService`(编在 chrome/browser)+ content/chrome/network test_support,不能进轻量 `teleport_unittests`。改经 `patches/chrome/test/BUILD.gn.patch` **接进 Chromium 既有的 `unit_tests`**(那里本就链 chrome/browser + 全 test_support;补 `//teleport` dep 供测试 include teleport 头)。首跑逮到 1 个**测试自身 bug**:auto-start 测试用 `profile_.GetPrefs()->SetList(kManagedAutoSelectCertificateForUrls,…)`(user store)触发上游 `content_settings::PolicyProvider::DCHECK(!HasUserSetting())` 崩溃——策略 pref 须经 **managed store**,改用 `GetTestingPrefService()->SetManagedPref` 修复。**5/5 全过**。
- **顺带补丁安全验证(用户诉求)**:借 `unit_tests` 已构建,定向跑我们 ~13 个行为补丁文件的上游覆盖套件(181 测试)。**全绿,除** `BrowserDMTokenStorageMacTest.{SaveDMToken,DeleteDMToken}` 2 个失败——根因 = 我们 `browser_dm_token_storage_mac.mm` 补丁**有意**把 DM token 存储目录从 `Google/Chrome Cloud Enrollment` 挪到 `teleport::kDmTokenStorageDir`(`Teleport/Cloud Enrollment/`),上游测试算旧路径故失败(**有意分叉,非回归**;真机 enrollment 一直正常)。处置:`patches/chrome/browser/policy/browser_dm_token_storage_mac_unittest.cc.patch` 把测试常量 fork 到 `teleport::kDmTokenStorageDir`(实现同款,路径按构造相等)→ DM-token 套件 5/5 转绿。**结论:已跑的上游套件里,我们的补丁除这一处有意路径分叉外均不破坏上游预期。**
- **补丁安全验证 · components_unittests(gap 已闭合,2026-07-27)**:同法构建 `components_unittests` + 定向跑我们 9 个 `components/*` 行为补丁的覆盖套件(**444 测试 / 34 套件**:UserAgentUtils / LocationBarModel / KeychainPassword / PolicyConversions / CloudPolicy* / CloudManagement / MachineLevelUserCloudPolicy)。最大补丁 `cloud_policy_constants.cc`(DM server URL)覆盖的 CloudPolicy* 全绿。唯一失败 = `UserAgentUtilsTest` 8 个——根因 = 我们 `user_agent_utils.cc` 补丁**有意**让 UA-CH 携带**引擎版本**(`TELEPORT_ENGINE_VERSION`=148,网站按此判 Chromium 兼容性)而非**产品版本**(`chrome/VERSION` MAJOR=0,即 Teleport 产品版 0.1),外加 `PRODUCT_FULLNAME=Teleport` 使 UA 品牌("Chromium",web-compat)≠ 产品名。**有意分叉非回归**。fork `patches/components/embedder_support/user_agent_utils_unittest.cc.patch`:测试里 `version_info::Get*Version*`→`TELEPORT_ENGINE_VERSION_*`(引擎版)、product-brand→`"Chromium"`(UA 实际品牌)→ **8/8 转绿,444/444 全绿**。**运行坑**:`components_unittests` 含未实例化参数化套件(autofill,与我们无关),base::TestLauncher 会 abort 全部——用 `--single-process-tests` 绕过。
- **总结论**:两个测试二进制(`unit_tests` + `components_unittests`)覆盖我们全部行为补丁的定向套件,**我们的补丁不造成任何功能回归**;所有失败都是**有意的品牌/路径/版本分叉**(DM-token 目录、UA 引擎版、UA 品牌),已同法 fork 各自上游测试转绿。**全量深扫(无基线归因环境噪音)仍属 CI + 基线工程,非本轮。**
- **背景**:P1d Track T 的 `teleport_tunnel_service_unittest.cc`(T2 交付,含 4 组:`TeleportTunnelRoutesDeriverTest` ×2 纯逻辑、`TeleportTunnelProxyConfigTest` 纯逻辑、`TeleportTunnelBindClientTest` fixture)首次真编时发现**无法接进 `teleport_unittests`**:① 该文件未登记进 `src/BUILD.gn` 的 `teleport_unittests` sources(T2 建了测试却没接线);② 更本质——`teleport_tunnel_service.cc`/`_factory.cc` 是经 **T3 的 `patches/chrome/browser/BUILD.gn.patch` 直接编进 `chrome/browser`**(巨型 browser 库),**不在独立可测的 `:teleport` source_set**,故轻量 `teleport_unittests` 链不到 `TeleportTunnelService` 构造符号与 `tunnel_internal::` free functions;③ `BindClientTest` 还需 `//content/test:test_support`(`BrowserTaskEnvironment`)+ `//services/network/public/cpp:test_support`(`TestURLLoaderFactory`)deps。
- **影响**:纯测试覆盖缺口。**client(Teleport.app)构建与运行完全正常**,tunnel service 已随 chrome/browser 正常编译链接;Track T 的功能真相靠 P1d V1(net-export)/ V2(联合真浏览器 e2e)。
- **未修**:上述三点。改名修复(`base::ListValue/DictValue`)已随 client-build fix 提交,故测试文件本身现可编(仅缺接线与源结构)。
- **处置(将来)**:把 tunnel 的纯 free functions(`DeriveRoutableOrigins`/`BuildTunnelProxyConfig`)抽进独立可测 source_set(或把 tunnel service 加进 `:teleport`),再把 `teleport_tunnel_service_unittest.cc` 接进 `teleport_unittests` sources + 加 content/network `test_support` deps;`BindClientTest` 若嫌 content 依赖重,可改用 `base::test::TaskEnvironment`(仅需 `//base/test:test_support` + network public/cpp test_support)。
- **关键引用**:`patches/chrome/browser/BUILD.gn.patch`(tunnel service 编进 chrome/browser)、`src/BUILD.gn` `teleport_unittests`、`src/browser/enterprise/teleport_tunnel_service_unittest.cc`。

## TD-UPSTREAM-UT-CI-BASELINE · 上游 UT(`unit_tests`+`components_unittests`)接 CI + 建 expected-pass 基线 — 📌 待排期(P2,CI 加固)

- **登记日期**:2026-07-27 · **优先级**:P2(补丁回归防护;client 构建/运行不受影响) · **结清日期**:未
- **背景**:我们给上游打了 ~90 个补丁,其中约 22 个**行为性修改**上游 `.cc/.mm` 逻辑。2026-07-27 做了**定向补丁安全验证**(build 两个测试二进制 + 只跑覆盖我们补丁文件的上游套件):`unit_tests`(181 测试,~13 个 chrome/browser 补丁)+ `components_unittests`(444 测试,9 个 components/* 补丁)。**结论:零功能回归**;所有失败都是**有意分叉**(DM-token 存储目录、UA 引擎版 vs 产品版、UA "Chromium" 品牌 vs 产品名),已 fork 各自上游测试转绿(`patches/chrome/browser/policy/browser_dm_token_storage_mac_unittest.cc.patch`、`patches/components/embedder_support/user_agent_utils_unittest.cc.patch`)。
- **仍缺(本 TD)**:① 这两个上游 UT **未接 CI**——补丁回归目前靠人工定向跑,未来改补丁/rebase 上游可能悄悄破坏上游测试而无人发现;② **全量深扫需 expected-pass 基线**:fork + 自定义 config(component/dev/mac-arm64)首跑必有一批**与我们补丁无关**的失败(需 display/keychain/network、config-disabled、flaky),**无基线无法归因**"我们补丁造成 vs 本来就红"。
- **处置(将来)**:CI 加一个 job:(a) build `unit_tests` + `components_unittests`;(b) **定向档**——跑覆盖我们行为补丁文件的套件(本次用的 filter,便宜可归因,推荐先上);或 (c) **全量档**——跑全部,配一份 pinned expected-pass/known-fail 基线(首次人工审一遍 fork+自 config 的固有失败,之后 diff 门禁)。补丁新增/改动时,若动了有上游测试的文件,同步 fork 其上游测试(改实现连测试一起 fork 的纪律)。
- **运行坑(必记)**:① `components_unittests` 含未实例化参数化套件(autofill,与我们无关)使 `base::TestLauncher` **abort 全部测试**——CI 必须 `--single-process-tests`(或修那些 autofill 套件);② `unit_tests` 首次构建编 ~1366 个测试源(数十分钟),`components_unittests` 类似——CI 需缓存 out 目录或接受首建成本;③ 定向跑用 `--gtest_filter`(只减运行时,不减构建)。
- **影响**:纯 CI 覆盖缺口。**当前补丁已人工定向验证零回归**;缺的是自动化 + 全量基线。
- **关键引用**:本轮 filter 见 `TD-TUNNEL-UNITTEST-WIRING`(unit_tests 侧)+ commit `cd3f11f`(components 侧);构建配方 `PATH=<depot_tools>:$PATH autoninja -C out/mac/arm64/dev <unit_tests|components_unittests>`。
