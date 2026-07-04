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

### TD-005 release 构建下 Google 登录按钮可见且通向失败流程

- **登记日期**:2026-05-31 · **优先级**:P1
- **背景**:Dice 因 `HasOAuthClientConfigured()==false` 被构建级禁用,但 profile 菜单登录按钮只看 `prefs::kSigninAllowed`(默认 true,`signin_utils_desktop.cc:35`),**不查 OAuth client 是否配置**;且 `ShowDiceSigninTab` 对「Dice 未启用」的检查只在 `DCHECK_IS_ON()` 内(`signin_view_controller.cc:599`)。official/release 构建 DCHECK 关闭 → 跳过检查 → 打开真实 `accounts.google.com`,OAuth 用 `dummytoken` 交换令牌**失败**(dev 构建则命中 DCHECK abort)。
- **影响**:用户能从 profile 菜单/`chrome://settings/syncSetup` 走到 Google 登录页并失败。关联 TD-001 B 类。
- **当前处置**:无(overlay 未触碰 signin/sync;grep 命中的 "signin" 实为代码 **signing** 误报)。
- **将来方向**:**首选 S(policy,零改码零后端)** = 默认下发 `BrowserSignin=0`(+ 可选 `SyncDisabled=true`)策略,经 macOS managed preferences plist(`com.beansec.Teleport` 域)注入,`CanOfferSignin` 立即返回 disallowed → 登录按钮消失、syncSetup 入口关闭,profile 管理/头像不受影响。彻底做法 = 编译期 `enable_dice_support=false` 整段移除 Dice(成本更高、与「加法为主」理念冲突,暂不)。自有受管身份是独立未来大工程,强依赖 fairyland。

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
- **将来方向(S)**:常量改为**平级兄弟目录** `"Teleport Cloud Enrollment/"`(无公司伞目录时对 Chrome 布局最忠实的直译;不采用 `"BeanSec/Teleport Cloud Enrollment/"`——只为此一处引入伞目录而产品目录仍在顶层,不彻底)。改动面已 grep 收口:头文件常量+注释、`src/common/teleport_enterprise_enrollment_unittest.cc:26` 断言(TDD 先行)、`docs/enterprise-device-enrollment.md:97`;fairyland 侧零引用(服务端不关心客户端文件布局)。迁移:pre-release 仅内部测试机,可不写迁移代码——旧目录成无害遗留(顺手删),测试机下次启动经强制注册自动重取 token;需确认 device-manager 按 client id(硬件 UUID 派生,不随清理变)幂等 upsert、不产生重复设备记录。若想省测试机一次重注册,可加「新路径不存在且旧路径存在则搬运」的三行一次性迁移。**须在首个外部发布前完成**,否则升级为带兼容回退的正式迁移工程。
- **关键引用**:`src/common/teleport_enterprise_enrollment.h:25`、`src/common/teleport_enterprise_enrollment_unittest.cc:26`、`patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch`、`patches/chrome/common/chrome_paths_mac.mm.patch`、`docs/enterprise-device-enrollment.md:97`、plan `2026-06-04-enterprise-alignment-phase1-device-enrollment.md:528`。

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

### TD-010 隐私设置存在 UKM「死 toggle」(已解决)

- **登记日期**:2026-05-31 · **结清日期**:2026-06-01 · **优先级**:P2
- **背景**:「让搜索和浏览更好」开关(`url_keyed_anonymized_data_collection`)位于 `_google_chrome` 块**之外**(`chrome/browser/resources/settings/privacy_page/personalization_options.html:93`),非品牌构建仍渲染;但 UKM 上送 URL 在公开 Chromium 为空(`components/metrics/server_urls.grd` 占位 `-`)→ `NetMetricsLogUploader` 短路丢弃日志,成为「点了有反应却无任何后果」的死控件。
- **处置**:新增 patch `patches/chrome/browser/resources/settings/privacy_page/personalization_options.html.patch`,把 `urlCollectionToggle` 裹进 `<if expr="_google_chrome">...</if>`,使本构建(`_google_chrome=false`)不渲染该 toggle(与相邻 toggle 的上游写法一致)。见 spec/plan `docs/superpowers/{specs,plans}/2026-05-31-settings-residual-branding-cleanup*`。
