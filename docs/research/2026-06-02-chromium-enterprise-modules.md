# Chromium 企业版模块技术参考

> 调研日期:2026-06-02
> 上游基线:**M148.0.7778.180**(`CHROMIUM_VERSION`),检出位于 `<repo>/chromium/src`
> 目的:盘点 Chromium 开源树内 Chrome 企业版相关模块的能力、实现位置、编译门控,评估对 teleport(闪现)受管端浏览器的可对接性。所有结论均基于实地核对源码,非记忆推断。

## 0. 速查表

| 模块 | 核心能力 | 源码位置 | 编译门控 | teleport 相关度 |
| --- | --- | --- | --- | --- |
| 策略框架 | 1482 条策略、多来源 provider、`chrome://policy` | `components/policy/`、`chrome/browser/policy/` | 平台无关 | 地基,必接 |
| 云管理 / DMServer | CBCM 注册、策略拉取、remote commands | `components/policy/core/common/cloud/` | 平台无关 | 高(协议要替换) |
| Content Analysis | 上传/下载/粘贴/打印内容送检(DLP/恶意) | `chrome/browser/enterprise/connectors/analysis/` | `enterprise_*_content_analysis`(平台) | 高(DSPM 对口) |
| Realtime Reporting | 安全事件上报 SIEM | `chrome/browser/enterprise/connectors/reporting/` | 平台无关 | 高 |
| Data Controls | 剪贴板/打印等本地规则引擎(看元数据) | `components/enterprise/data_controls/` | `enterprise_data_controls`(平台) | 中高 |
| Watermark | 页面平铺文字水印(屏幕+打印) | `components/enterprise/watermarking/` | `enterprise_watermark`(平台) | 高 |
| Device Trust | 零信任设备证明(挑战-应答 + 设备信号) | `chrome/browser/enterprise/connectors/device_trust/` | feature | 中(协议绑 Google) |
| Cache Encryption | HTTP 磁盘缓存 AES-256-GCM 加密 | `services/network/enterprise/encryption/` | `enterprise_cache_encryption`(平台)+ feature + 策略 | 中 |
| Idle | 闲置超时自动登出/清理 | `chrome/browser/enterprise/idle/` | 平台无关 | 高(直接可用) |
| Platform Auth | OS 级企业 SSO 桥接(Entra/Okta) | `chrome/browser/enterprise/platform_auth/` | 平台无关 | 中 |
| Screenshot Protection | 阻止截图/录屏 | buildflag | `enterprise_screenshot_protection`(win/mac) | 中 |

## 1. 关键全局结论(最重要)

### 1.1 企业能力门控在「平台」而非「品牌」

`components/enterprise/buildflags/buildflags.gni` 实测:这些 buildflag 几乎都按 `is_win || is_mac || is_linux` 门控,**没有一个挂 `is_chrome_branded`**:

```gn
enterprise_cloud_content_analysis = is_win || is_mac || is_linux || is_chromeos || is_ios
enterprise_local_content_analysis = is_win || is_mac || is_linux
enterprise_data_controls          = is_win || is_mac || is_linux || is_chromeos || is_android || is_ios
enterprise_client_certificates    = is_win || is_mac || is_linux || is_android || is_ios
enterprise_watermark              = toolkit_views && (is_win || is_mac || is_linux || is_chromeos) && !is_castos
enterprise_screenshot_protection  = is_win || is_mac
enterprise_telomere_reporting     = is_win || is_mac || is_linux
enterprise_cache_encryption       = is_win || is_mac || is_linux || is_chromeos || is_android
```

**结论**:Content Analysis、Data Controls、Watermark、Client Certs、Screenshot Protection 在 teleport 的 macOS **非品牌构建里默认就编进来、可用**。与「升级角标 `enable_update_notifications` 默认 `= is_chrome_branded` 导致非品牌构建失效」那次坑**不同**,这批模块不受品牌门控影响。

> 例外:部分能力额外挂 `base::Feature`(默认关)或企业策略(见各模块小节),需运行/构建期显式开。

### 1.2 DMServer / 上报地址可命令行覆盖,但 stable/beta 渠道被禁(teleport 必踩的坑)

`components/policy/core/browser/browser_policy_connector.cc:37` 默认地址:

```cpp
kDefaultDeviceManagementServerUrl    = "https://m.google.com/devicemanagement/data/api";
kDefaultRealtimeReportingServerUrl   = "https://chromereporting-pa.googleapis.com/v1/events";
kDefaultEncryptedReportingServerUrl  = "https://chromereporting-pa.googleapis.com/v1/record";
```

覆盖开关存在(`components/policy/core/common/policy_switches.cc`):
`--device-management-url=` / `--realtime-reporting-url=` / `--encrypted-reporting-url=`。

但 `ChromeBrowserPolicyConnector::IsCommandLineSwitchSupported()`(`chrome/browser/policy/chrome_browser_policy_connector.cc:241`):

```cpp
version_info::Channel channel = chrome::GetChannel();
return channel != version_info::Channel::STABLE &&
       channel != version_info::Channel::BETA;
```

**→ stable / beta 渠道下,URL 覆盖开关被直接忽略。** teleport 现跑通的 canary 渠道(非 stable)命令行覆盖可生效;将来上 stable/beta 要把 DMServer 指向 fairyland,**必须 patch 这里**(改 gate 或改默认常量)。这恰好落在已有的 `TeleportChannel` 渠道体系上。

## 2. 策略框架(Policy)

一切企业管控的地基。`components/policy/` + `chrome/browser/policy/`。

- **策略定义**:`components/policy/resources/templates/policy_definitions/`,实测 **1482 条** YAML。构建期生成 `policy_constants`、ADMX/ADML(Win 组策略)、Mac plist manifest、`chrome://policy` 元数据。
- **Policy Providers(来源链)**:
  - Windows:注册表 / 组策略(`PolicyLoaderWin`)
  - macOS:`NSUserDefaults` / MCX / 配置描述文件(`PolicyLoaderMac`)
  - Linux:`/etc/opt/chrome/policies/{managed,recommended}/*.json`
  - 全平台:Cloud Policy(见 §3)
- **PolicyService / PolicyMap**:多来源合并、优先级(mandatory > recommended,platform vs cloud)、冲突解析。
- **`chrome://policy`**:查看生效策略、来源、冲突、刷新。

> teleport 的「服务端集中下发策略」最自然的落点:复用 cloud-policy provider(见 §3),或在 `ConfigurationPolicyProvider` 层注入 fairyland 自有协议。

## 3. 云端管理与注册(Cloud Management)

`components/policy/core/common/cloud/` + `chrome/browser/enterprise/`。

- **DMServer 协议**:`components/policy/proto/device_management_backend.proto`,定义注册、策略拉取、状态上报、命令下发。**这是 Google 后端专用协议,teleport 要替换成 fairyland 协议。**
- **CBCM(Chrome Browser Cloud Management)**:enrollment token 把浏览器实例注册到组织,拉 machine-level 策略。`BrowserDMTokenStorage`、`MachineLevelUserCloudPolicy*`。
- **Remote Commands**:服务端下发命令(清数据、轮转密钥等)。
- **Policy Invalidation**:经 FCM 推「策略有变」信号触发即时刷新。
- **Component Cloud Policy**:扩展/特定组件的独立云策略(`component_cloud_policy_*`)。

**两条对接路线**:
1. **复用客户端栈**:fairyland 实现兼容 DM protobuf 的端点,客户端零改动,只需把 URL 指过去(注意 §1.2 stable 渠道 gate)。最省力。
2. **自定义 PolicyProvider**:绕开 DMServer,在 `ConfigurationPolicyProvider` 层注入自有协议。更自由,但要自己做注册/刷新/失效。

## 4. Enterprise Connectors

`components/enterprise/connectors/` + `chrome/browser/enterprise/connectors/`。专为安全厂商设计的扩展点,与 teleport DSPM 定位最贴。

- **Content Analysis**(`analysis/`):上传、下载、粘贴、打印、拖拽时把内容送分析服务做 DLP / 恶意扫描,按 verdict 放行/阻断/警告。云端(`enterprise_cloud_content_analysis`)或本地 Agent(`enterprise_local_content_analysis`,跨进程 SDK)。**会看内容。**
- **Reporting**(`reporting/`):安全事件上报 SIEM/审计。事件路由器:`realtime_reporting_client`、`extension_*_event_router`、`browser_crash_event_router`、`telomere_event_router`。默认端点 `chromereporting-pa.googleapis.com/v1/events`(`service_provider_config.cc:92`)。
- **proto**:`components/enterprise/common/proto/`(`connectors.proto`、`upload_request_response.proto`)。

## 5. Data Controls

`components/enterprise/data_controls/`。**声明式本地规则引擎**,只按元数据(来源/目的地/上下文)匹配,**不看内容**(与 Content Analysis 互补)。是 ChromeOS `DataLeakPreventionRulesList` 下沉到桌面的版本。

### 5.1 可管控操作(`core/browser/rule.h` 的 `Restriction`)

| 枚举 | 管什么 |
| --- | --- |
| `kClipboard` | 剪贴板分享(复制/粘贴/拖拽) |
| `kScreenshot` | 截图 / 录屏 |
| `kPrinting` | 打印机密内容 |
| `kPrivacyScreen` | 强制隐私屏 |
| `kScreenShare` | 屏幕共享 |
| `kFiles` | 文件操作(复制、上传) |
| `kFileDownload` | 下载文件 |

### 5.2 动作分级(`rule.h` 的 `Level`)

`kReport`(只审计) < `kWarn`(警告可继续,弹 `data_controls_dialog`) < `kBlock`(阻断);`kAllow` 用于白名单豁免。

### 5.3 条件模型(`core/browser/conditions/`)

规则核心 = `sources` + `destinations` 两组属性条件,可匹配属性:
- `urls`(URL 模式)、`incognito`(无痕)、`os_clipboard`(是否流向 OS 级剪贴板)、`components`(目的地组件:`USB`/`DRIVE`/`ONEDRIVE`/`ARC`/`CROSTINI`/`PLUGIN_VM`,主要 ChromeOS 语境)。
- 支持布尔组合:`and_condition` / `or_condition` / `not_condition` 任意嵌套。
- 求值产物 `Verdict`(`verdict.h`),`rules_service_base` 对一次操作求所有规则取最严档。

### 5.4 桌面实际生效范围(重要)

**枚举定义 ≠ 桌面都实现。** 实测桌面端 `chrome/browser/enterprise/data_controls/chrome_rules_service.cc` 只实现了:
- `GetPrintVerdict`(打印)
- `GetClipboardXxxVerdict`(剪贴板,enforcement 在 `data_protection/data_protection_clipboard_utils.cc`)

**Screenshot / ScreenShare / Files / FileDownload 在桌面要么走 ChromeOS DLP / Connectors,要么尚未在桌面接 hook。** 所以 Data Controls 在 mac 上**真正生效的只有「剪贴板」和「打印」**。`components` 维度多为 ChromeOS 语境,USB 在桌面是否生效需单独验证。

### 5.5 不支持的控制(实测确认)

- **无 Save Page As(另存网页)控制**;**无 view-source 控制**。`Restriction` 枚举无此项,全仓 grep `SavePage`/`view-source` 在 data_controls 下零命中。
- 替代手段(均为粗粒度,非 Data Controls 风格的按规则分级):
  - view-source → 上游策略 `URLBlocklist` 加 `view-source:*` 方案,只能全局禁。
  - Save Page As → `AllowFileSelectionDialogs=false` 整体禁选择框,或 `DownloadRestrictions`,或走 Content Analysis 下载扫描。
  - 想要「按来源 + 分级」的细粒度控制须自行扩:在 `SavePackage` / view-source 导航入口加 teleport hook,复用 Data Controls 规则引擎数据模型,但 enforcement 点要新写。

## 6. Watermark

`components/enterprise/watermarking/`。页面**平铺文字水印块**,用于威慑 + 取证溯源(**不是阻断**)。

### 6.1 渲染表面

- **屏幕**:`WatermarkView` 挂 `chrome/browser/ui/views/frame/contents_container_view.cc`(内容区 overlay),截屏/拍照会带上。
- **打印 / 导出 PDF**:`components/printing/browser/print_composite_client.cc:379` 经 `WatermarkTextContainer` 合成进打印输出(`SetWatermarkBlock`),**印到纸/PDF**。
- 经 `watermarking/mojom/watermark.mojom` 序列化,可在浏览器进程外绘制。

### 6.2 文本来源(关键)

服务端**按 URL 动态下发**:来自 Connectors 内容分析裁决的 `navigation_rule.watermark_message`(`connectors/core/reporting_utils.cc:422`)。落地:`data_protection_navigation_observer`(按导航取 `settings.watermark_text`)→ `data_protection_navigation_controller`(存住并通知)→ `contents_container_view::SetString`。**逐页面、可随导航切换/清除。**

### 6.3 样式可配(`WatermarkStyle` 策略,`watermark_style_policy_handler.cc`)

- `fill_opacity`、`outline_opacity`、`font_size`。
- 默认黑填充 + 白描边(`settings.h`),文字同时画填充和描边两遍(`CreateFillRenderText` + `CreateOutlineRenderText`),保证任何背景上可读。
- 文字 block 按 `GetWatermarkBlockHeight` 计算,在 `contents_bounds` 内平铺重复,支持多行。

### 6.4 边界

- 不防截图本身(那是 `enterprise_screenshot_protection`,互补)。
- 视觉/合成层水印,非文本隐写;看源码、复制文字绕得过。纯防「视觉外泄(拍照/截屏/打印)」。
- 依赖 `toolkit_views`,mac 默认开。

## 7. Device Trust / Context-Aware Access

`chrome/browser/enterprise/connectors/device_trust/`(`components/enterprise/device_trust/` 仅剩 prefs)。零信任:受管浏览器访问受保护应用时,密码学证明设备身份 + 上报设备安全态势,服务端据此放行/拒绝。

### 7.1 握手协议(`navigation_throttle.h` 头注释)

`ContextAwareAccessSignalsAllowlist` 策略配可信 URL。访问时 `DeviceTrustNavigationThrottle` 介入,走 HTTP header 挑战-应答(即 Google **Verified Access** 协议):

```
1. 浏览器 → IdP:请求头加 X-Device-Trust: VerifiedAccess
2. IdP → 302 重定向,带 X-Verified-Access-Challenge: <challenge>
3. 浏览器用设备密钥签名 challenge + 打包设备信号,
   回送 X-Verified-Access-Challenge-Response: <signed response>
4. IdP 验证签名 + 校验信号 → 放行 / 拒绝
```

Throttle 在 `WillStartRequest` / `WillRedirectRequest` 注入头,异步签名应答后 `Resume()`。

### 7.2 设备密钥(`key_management/`)

设备级签名密钥对,公钥注册时上报后台,私钥永不离开设备。`KeyTrustLevel` 分 `HARDWARE` vs `OS_SOFTWARE`。平台后端:

| 平台 | 后端 |
| --- | --- |
| macOS | **Secure Enclave**(P-256/EC,`core/mac/secure_enclave_signing_key.*`) |
| Windows | TPM(`win_key_persistence_delegate`) |
| Linux | 软件密钥(`linux_key_persistence_delegate`) |

密钥轮换:`key_management/installer/key_rotation_manager*`,可经 remote command 触发,`signing_key_policy_observer` 监听策略。

> 与 teleport 已知约束呼应:macOS Secure Enclave 只支持 P-256;Device Trust 只需 P-256 签名,恰好能用 SEP(对比 Sparkle 用 Ed25519 走不了 SEP)。

### 7.3 设备信号(`signals/decorators/`)

decorator 拼信号进应答(`device_signals::names::*`):`kDeviceModel`、`kSerialNumber`、`kOsVersion`、`kBrowserVersion`、磁盘加密、屏幕锁、`os_firewall`、Secure Boot、`password_protection_warning_trigger`,以及第三方 EDR(CrowdStrike 等)在册检测。采集前有 `UserPermissionService` + `ConsentRequester`(非受管/个人 profile 需同意,affiliated 设备静默)。

### 7.4 对接成本

- 可复用骨架:throttle 注入头 + 异步签名应答、SEP 设备密钥 + 轮换、signals decorator。
- 要替换:`X-Verified-Access-Challenge` 是 Google Verified Access 私有协议,challenge 打包(`attestation/`)绑 Google 后端。fairyland 要么实现兼容验证端,要么替换握手协议。
- 最易裁剪复用的是 signals 层,作为 fairyland 条件访问的输入。

## 8. Cache Encryption

`services/network/enterprise/encryption/`(实现)+ `chrome/browser/enterprise/encryption/`(密钥)。HTTP 磁盘缓存落盘加密。

### 8.1 架构

- `CacheEncryptionProviderImpl`(`chrome/browser/...`)产密钥 → mojo 传到**网络服务进程** → `encrypted_backend_file_operations.cc` 作为装饰器包在 `disk_cache::BackendFileOperations` 之上(`EncryptedCacheFile` 每条目读写加解密)。
- **算法**:`os_crypt_async::Encryptor` 的 `kAES256GCM`(`os_crypt/async/common/encryptor.cc:117`,`crypto::Aead::AES_256_GCM`,96-bit nonce)。
- **密钥**:每 profile 一把,存 prefs,被 OSCrypt(mac Keychain / Win DPAPI)包裹,运行时 `crypto::ProcessBoundString` 绑进程。
- **开关(双重)**:`base::Feature kEnableCacheEncryption` **且** 策略 `kCacheEncryptionEnabledPref` 均为真(`cache/utils.cc:ShouldEncryptHttpCache`),**默认关**。

### 8.2 性能影响

- **加密边界仅磁盘缓存读写**;不碰内存缓存、网络传输、渲染。
- AES-256-GCM 在 Apple Silicon(ARMv8 Crypto Ext)/x86(AES-NI)硬件加速,~1–5 GB/s/核;50KB 资源加解密 ~十几微秒,瓶颈是磁盘 I/O 而非加密。
- 净效果:典型浏览近无感;仅「缓存命中极密集 + 无硬件 AES 的老 CPU」可能个位数百分比回退。mac/arm64 有硬件 AES,开销可忽略。
- **注意**:2025 年新特性,默认关,`utils.cc` 留 TODO(crbug.com/474585860)补性能埋点,**无权威公开基准**;上述为算法+架构推算。

## 9. Idle

`components/enterprise/idle/` + `chrome/browser/enterprise/idle/`。`IdleTimeout` + `IdleTimeoutActions` 两策略驱动:用户空闲达设定时长后执行一组动作。受管会话卫生。

动作(`action_type.h` 的 `ActionType`):`kCloseBrowsers`、`kCloseTabs`、`kSignOut`、`kShowProfilePicker`、一组清理(`kClearBrowsingHistory`/`kClearCookiesAndOtherSiteData`/`kClearCachedImagesAndFiles`/`kClearPasswordSignin`/`kClearAutofill`/`kClearDownloadHistory`/`kClearHostedAppData`/`kClearSiteSettings`)、`kReloadPages`;配套 `kShowDialog`/`kShowBubble` 倒计时提示(`dialog_manager.cc`)。

> 跨平台、无品牌门控,teleport 几乎可原样用,只需把两条策略纳入下发。

## 10. Platform Auth

`components/enterprise/platform_auth/` + `chrome/browser/enterprise/platform_auth/`。复用 OS 已有企业身份,导航到企业 IdP 时自动 SSO。

Provider(按平台):
- **Windows**:`cloud_ap_provider_win` —— Azure AD/Entra Cloud AP,取系统 PRT。
- **macOS**:`extensible_enterprise_sso_provider_mac` + `extensible_enterprise_sso_entra` —— Apple Extensible Enterprise SSO 框架,支持 Microsoft Entra 与 Okta。
- **Android**:`entra_provider_android`。

机制:`platform_auth_navigation_throttle` 拦导航 → `platform_auth_provider_manager` 判断是否受配 IdP → `platform_auth_proxying_url_loader_factory` 把 OS 注入的认证头挂到请求。`ExtensibleEnterpriseSSO` 等策略控制。

> 相关度取决于 fairyland 是否用 Entra/Okta;自有 IdP 则现成 provider 帮助有限,但 throttle + proxying loader 架构可作 OS 身份桥接参考骨架。

## 11. teleport 对接建议汇总

按优先级:

1. **策略下发协议**:替换 DM 协议。优先「复用客户端栈 + fairyland 实现兼容端点」,次选自定义 PolicyProvider。**记得处理 §1.2 stable 渠道 URL override gate**。
2. **DSPM 首选 Enterprise Connectors**:`analysis/`(内容分析,本就给第三方安全厂商设计)+ `reporting/`(事件上报)。改 `service_provider_config.cc` 硬编码端点指向 fairyland。
3. **Data Controls + Watermark**:mac 默认编入。Data Controls 桌面实际只有剪贴板/打印生效;Watermark 屏幕+打印均覆盖,文本源需从 Google 裁决改为 fairyland 注入(改 `data_protection_navigation_controller` 的 `settings.watermark_text` 注入点最小)。
4. **Idle**:通用受管会话卫生,直接可用。
5. **Device Trust / Signals**:设备身份与信号采集,signals 层最易裁剪,作为条件访问输入。
6. **Cache Encryption**:受管端数据落盘保护,mac 开销可忽略;需下发 `kCacheEncryptionEnabledPref` + 开 `kEnableCacheEncryption` feature。

### 反复出现的注意点

- **buildflag 门控按平台非品牌**(§1.1):大部分模块 mac 默认编入,但部分额外挂 `base::Feature`(默认关)或企业策略。
- **stable/beta 渠道禁 URL 覆盖开关**(§1.2):teleport 上 stable 必须 patch。
- **桌面 enforcement 不等于枚举定义**(§5.4):Data Controls 桌面只落了剪贴板/打印。
- **多处协议/端点硬编码 Google**:DMServer、Reporting 端点、Verified Access challenge 格式,均需替换为 fairyland。

## 附:本文涉及的关键源码路径

```
components/enterprise/buildflags/buildflags.gni                          企业 buildflag 定义
components/policy/core/browser/browser_policy_connector.cc:37            DMServer/上报默认地址
chrome/browser/policy/chrome_browser_policy_connector.cc:241             URL override 渠道 gate
components/policy/proto/device_management_backend.proto                  DM 协议
components/enterprise/connectors/core/service_provider_config.cc:92      Reporting 默认端点
components/enterprise/data_controls/core/browser/rule.h                  Restriction/Level 枚举
chrome/browser/enterprise/data_controls/chrome_rules_service.cc          桌面实际 enforcement
components/enterprise/watermarking/watermark.h                           水印渲染 API
chrome/browser/enterprise/watermark/watermark_style_policy_handler.cc    水印样式策略
components/printing/browser/print_composite_client.cc:379                打印水印合成
chrome/browser/enterprise/connectors/device_trust/navigation_throttle.h  Device Trust 握手
chrome/browser/enterprise/connectors/device_trust/key_management/        设备密钥(SEP/TPM)
services/network/enterprise/encryption/encrypted_backend_file_operations.cc  缓存加密
components/os_crypt/async/common/encryptor.cc:117                        AES-256-GCM
components/enterprise/idle/action_type.h                                 Idle 动作枚举
chrome/browser/enterprise/platform_auth/                                 OS 级 SSO
```
