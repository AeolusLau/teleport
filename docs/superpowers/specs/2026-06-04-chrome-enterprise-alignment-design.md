# Chrome 企业版能力对齐 · 总纲设计(客户端侧)

- 状态:已评审(设计 · 总纲)
- 日期:2026-06-04
- 范围:跨 `teleport`(客户端 overlay)与 `fairyland`(服务端 monorepo)两仓
- 本文归属:**总纲权威 + 客户端侧设计**。服务端侧设计见 fairyland 仓配对 spec(见 §8),两份互相引用、各生成 plan。
- 性质:本文是**总纲(主方向 + 内容 + 实施节奏)**,不细化到可直接实施;每个 phase 后续各自独立脑暴 → plan → 实施。

> 配对文档:fairyland 仓 `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-server-design.md`(服务端侧:device-manager 渐进演进 + 控制面 API + 控制台面)。本文与之**同名配对 worktree/分支** `worktree-chrome-enterprise-alignment`。

## 1. 背景与北极星

Teleport(闪现)是基于 Chromium 源码自研的企业安全浏览器。**账号体系 / 云管理地基已建成并端到端活验**(见 `2026-06-03-enterprise-account-system-design.md`):策略框架 + CBCM/DMServer 协议面 + OIDC 用户纳管 + 签名策略下发 + 两层密钥 + Keystone 作唯一 OIDC OP。

本轮在此地基之上,系统性对齐 Chrome 企业版**其余能力模块**(技术盘点见 `docs/research/2026-06-02-chromium-enterprise-modules.md`)。

**北极星**:把 Chrome 企业版能力系统性对齐到 Teleport + Fairyland——

> 除 **DLP 内容送检(Content Analysis)** 与 **零信任设备证明(Device Trust / Verified Access)** 本轮暂不做之外,其余能力全部纳入路线图;排序按「**先地基(纳管/云管理)→ 再把策略框架用起来 → 再 Data Controls 控件簇**」;**品牌化贯穿始终**。

## 2. 范围边界(In / Out)

**In(纳入路线图,分阶段)**
- 设备/用户纳管收口(设备级 CBCM 纳管补齐;用户 OIDC 纳管已有)
- 云管理完整侧面:macOS Platform 策略验证、设备状态回报(status)、Remote Commands、即时刷新、安全事件 Reporting
- 把策略框架真正用起来(企业关心策略子集的批量编码下发 + 控制台配置)
- Data Controls 控件簇:剪贴板/打印、Watermark、Screenshot Protection、Idle、脱敏
- 企业管理 UI 全面品牌化

**Out(本轮明确不做)**
- DLP 内容送检(Content Analysis,会看内容)
- 零信任设备证明(Device Trust / Verified Access,协议绑 Google 后端)

**邻接可选**
- Cache Encryption(磁盘缓存加密):落在控件簇,作可选小项(双开关 feature + 策略,mac 开销可忽略)
- Platform Auth(OS 级 SSO 搭车):**已在账号体系 Layer 2 覆盖并活验**,不单列新 phase

## 3. 对齐四原则(对应需求第 4 点:少改源码、最大复用、行为对齐)

1. **复用优先**:能力一律复用上游模块,不重写。已核实这批模块在 macOS 非品牌构建**默认编入、不受品牌门控**(`components/enterprise/buildflags/buildflags.gni` 按平台而非 `is_chrome_branded` 门控;个别额外挂 `base::Feature`/策略,需显式开)。
2. **薄 patch**:可变常量收进 `//teleport` 源码,patch 只引用 `teleport::` 常量(延续仓库现有风格)。
3. **线协议兼容,而非改客户端协议**:让 **Fairyland 去说 Chrome 的协议**(DM 协议信封 / reporting ingest 格式),客户端原生就懂,行为天然与 Chrome 一致。device-manager 已是这个范式。
4. **行为对齐 Chrome**:启用能力的行为模式与 Chrome 保持一致。**唯一已知偏差点 = 策略即时刷新**:Chrome 靠 Google FCM 推送做秒级刷新,我们没有;本轮**以 Chrome 自带的周期轮询兜底**(行为=刷新有延迟),自建推送通道后置评估(见 Phase 4)。

## 4. 能力全景(分层)

| 层 | 能力 | 客户端改动 | Fairyland 改动 | 状态/归属 |
|---|---|---|---|---|
| **L0 地基(已建成)** | 策略框架 + CBCM/DMServer 协议面 + OIDC 用户纳管 + 签名策略下发 + 两层密钥 + Keystone OP | — | device-manager 已有 | ✅ 已活验 |
| **L1 纳管+云管理收尾** | 设备级 CBCM 纳管;macOS Platform 策略验证;status 回报;(后置)Remote Commands、即时刷新推送、安全事件 Reporting | 2 个 CBCM patch;reporting 端点重指 patch | status/commands/reporting ingest | 本轮核心起点 |
| **L2 策略框架用起来** | 企业关心策略子集批量编码下发 + 控制台配置 + 合并/优先级验证 | 近零 patch(多为策略 proto 编码) | 策略目录 + 配置面 | 本轮 |
| **L3 Data Controls 控件簇** | 剪贴板/打印、Watermark、Screenshot Protection、Idle、脱敏 | 水印文本源注入点、脱敏自研 hook;余为策略驱动 | 规则/文案下发 | 本轮 |
| **品牌(横切)** | chrome://management、'managed by' 文案、连接器/水印/数据管控对话框、chrome://policy | per-capability 收口,管理面前置 Phase 1 | — | 贯穿 |
| **L-Out** | DLP 内容送检、Device Trust 零信任 | — | — | 暂不做 |

### 关键技术事实(已核实于 M148 检出 148.0.7778.180,非记忆)

- **macOS Platform 策略大概率开箱可用**:平台策略加载器的 managed-prefs 域名走 `chrome/browser/policy/chrome_browser_policy_connector.cc:335` 的 `base::apple::BaseBundleID()`(运行时取我们的 bundle id)、**无品牌门控** → MDM 经 Configuration Profile 推到 `com.beansec.Teleport` 域的策略理论上直接被读取。本轮仅需「验证 + 文档化」。
- **设备 CBCM 纳管确实未做**:`components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc` 的 `IsEnabled()` 非品牌分支需 `--enable-chrome-browser-cloud-management` 开关或 patch 返回 true;`chrome/browser/policy/browser_dm_token_storage_mac.mm` 把 bundle id / 路径硬编码成 Google。两者在账号体系 spec 里标为「后续 phase 未实现」,本轮 Phase 1 落地。
- **Data Controls 桌面实际只落剪贴板 + 打印**:`chrome/browser/enterprise/data_controls/chrome_rules_service.cc` 仅实现 `GetPrintVerdict` + 剪贴板;Screenshot/Files/FileDownload 桌面未接 hook。
- **脱敏(masking)不是 Chrome 原生能力**:`Restriction` 枚举无此项;需自研 enforcement hook(复用 Data Controls 数据模型),很可能独立成一个 phase。
- **stable/beta 渠道禁 URL 覆盖开关**:`chrome/browser/policy/chrome_browser_policy_connector.cc:241` 的 `IsCommandLineSwitchSupported()` 在 STABLE/BETA 忽略 `--device-management-url` / `--realtime-reporting-url` 等 → 端点重指一律走 patch 内置常量,跨渠道稳健。

## 5. 实施节奏(7-phase Roadmap · 方案 C)

推进骨架 = **方案 C(地基先行 + 关键横切前置)**:按「地基 → 策略 → 控件」主轴纵向收口,每个 phase 内只做该能力必需的最小横切;唯独把「企业管理 UI 品牌化」提前到 Phase 1(设备纳管点亮后这些面板立刻可见,品牌穿帮最显眼)。

### Phase 1 · 设备纳管点亮 + 企业管理面品牌化 〔地基 · 需配对仓〕
- **客户端**:① patch `chrome_browser_cloud_management_controller.cc` 的 `IsEnabled()` 非品牌返回 true(或受策略门控);② patch `browser_dm_token_storage_mac.mm`——bundle id→运行时 `BaseBundleID()`、三处 `/Library/Google/Chrome/` 路径→ Teleport 路径;③ 验证 macOS Platform 策略 loader 落到 `com.beansec.Teleport`(最小验证 + MDM 文档,近零 patch);④ **企业管理 UI 品牌**:`chrome://management`、工具栏/菜单「由<组织>管理」文案、`ManagedUI` 字符串 sweep + 图标。
- **Fairyland**:机器 `register_browser` 流已活验;补 enrollment-token 签发面(已有雏形)。
- **可见成果**:MDM 推 enrollment token → 启动即机器纳管 → 浏览器级策略(登录前)生效 + `chrome://management` 显「由 闪现/<租户> 管理」、无 Google 穿帮。

### Phase 2 · 设备状态回报 〔地基 · 需配对仓〕
- **客户端**:原生 `status` 上报走 DM 协议(版本/策略生效态/设备标识),多为开关确认。
- **Fairyland**:device-manager 加 status ingest + 存储;控制台设备列表(版本/last-seen/策略态)。
- **可见成果**:控制台看到纳管设备清单 + 健康态。

### Phase 3 · 策略框架用起来 〔策略 · 需配对仓〕
- **客户端**:近零 patch——企业关心策略子集精确编码下发;`chrome://policy` 品牌 sweep;recommended/mandatory 合并与冲突展示验证。
- **Fairyland**:策略目录(catalog)+ 控制台配置面(按租户/scope)+ device-manager 编码下发扩展。
- **可见成果**:控制台配策略 → 端到端下发生效 → `chrome://policy` 正确展示来源/冲突/品牌。

### Phase 4 · 云管理进阶 〔云管理后置侧面 · 需配对仓〕
- **客户端**:① Remote Commands 原生通道确认;② 即时刷新——确认轮询兜底正常,**推送通道决策点**(自建兼容推送 vs 维持轮询);③ patch reporting 端点 `chromereporting-pa.googleapis.com` → Fairyland。
- **Fairyland**:命令签发端点;(可选)推送通道;reporting ingest(兼容 Chrome 上报格式)+ 事件存储/转 SIEM。
- **可见成果**:控制台下发「清数据/登出」生效;安全事件(登录/下载/拦截)上报可见。*注:只接事件上报,不接内容送检(DLP 仍 Out)。*

### Phase 5 · Idle + Data Controls(剪贴板/打印) 〔控件 · 需配对仓(下发面)〕
- **客户端**:Idle(`IdleTimeout`/`IdleTimeoutActions`)纯策略驱动;Data Controls 剪贴板+打印(桌面已落地)策略驱动;数据管控对话框品牌。
- **Fairyland**:下发 Idle 两策略 + Data Controls 规则(sources/destinations/level)。
- **可见成果**:闲置超时登出/清理;按规则限制复制粘贴/打印 + 警告/阻断对话框(品牌)。

### Phase 6 · Watermark + Screenshot Protection 〔控件 · 需配对仓(下发面)〕
- **客户端**:水印渲染(屏幕+打印/PDF)已具备,**改文本源**——从 connectors verdict 注入改为 policy/Fairyland 注入(`data_protection_navigation_controller` 的 `settings.watermark_text` 注入点最小改)+ `WatermarkStyle` 策略;Screenshot Protection(`enterprise_screenshot_protection` buildflag,win/mac)开启 + 策略驱动。
- **Fairyland**:按 URL 下发水印文案/样式 + 防截屏规则。
- **可见成果**:受管页面平铺水印(屏幕+打印都带)、防截屏生效。

### Phase 7 · 脱敏(自研,独立设计) 〔控件 · 高风险 · 纯客户端为主〕
- Chrome **无原生**:需自研 enforcement hook(复用 Data Controls 数据模型,enforcement 点新写于渲染/复制/导出入口)。改动量与风险最大,**独立脑暴 + spec**。

**邻接可选**:Cache Encryption 可在 Phase 5/6 附近作可选小项。

**依赖**:P1→P2→P3 顺序(地基);P4 依赖 P1(DM 通道);P5/P6/P7 依赖 P3(下发管道成熟);品牌横切。**顺序可调**——如 Reporting(P4)业务更急可上提。

## 6. 品牌化策略(贯穿,需求第 1 点)

延续仓库既有的 per-capability 收口 + 关键面前置:

- **Phase 1 前置(最显眼)**:`chrome://management` 页面、工具栏/菜单「由<组织>管理」文案、`ManagedUI`/管理图标 tooltip。
- **per-capability 收口**:`chrome://policy`(P3)、Data Controls 警告/阻断对话框 + Watermark 默认文案(P5/P6)、连接器相关字符串(随各能力)。
- **手法对齐既有 sweep**:复用 `branding_strings.py` + `.grd/.xtb` rebrand 路径;企业专有串(如 "Chrome Browser Cloud Management"、"managed by your administrator")并入 superset 清扫。两层品牌不变:磁盘标识 `Teleport`、应用内显示 `闪现`。

## 7. 客户端 patch 总览(随 phase 落地,行号待 plan 阶段复核)

| Phase | 目标文件 | 改动 |
|---|---|---|
| P1 | `components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc` | `IsEnabled()` 非品牌返回 true(或策略门控) |
| P1 | `chrome/browser/policy/browser_dm_token_storage_mac.mm` | bundle id→`BaseBundleID()`;Google 路径→ Teleport 路径 |
| P1 | 企业管理 UI 字符串/资源(`.grd`/`.xtb` + ManagedUI) | 品牌 sweep |
| P4 | `components/policy/core/browser/browser_policy_connector.cc`(reporting 默认 URL) | `kDefaultRealtimeReportingServerUrl` / `kDefaultEncryptedReportingServerUrl` → Fairyland(switch 在 STABLE/BETA 被忽略,改默认) |
| P6 | `data_protection_navigation_controller` 水印文本注入点 | 文本源从 connectors verdict 改 policy/Fairyland 注入 |
| P7 | 渲染/复制/导出入口(脱敏 enforcement) | 自研 hook(独立设计) |

> 已有(账号体系):`cloud_policy_constants.cc`(验签根钥 buildflag 双钥)、`browser_policy_connector.cc`(DM URL 默认值)、`oidc_auth_response_capture_navigation_throttle.cc`、`profile_management_features.cc`。本轮新增 patch 在其上叠加。

## 8. 跨仓协作(按 [[cross-repo-parallel-dev-workflow]] 约定)

每个**需要服务端支持的 phase**(P1 部分、P2、P3、P4、P5–P6 下发面)按统一流程:

1. **配对 worktree + 分支**:teleport 与 fairyland **各开一个同名** worktree/分支(均在各自 `<repo>/.claude/worktrees/<name>`)。本总纲所在分支 = `worktree-chrome-enterprise-alignment`。
2. **各落一份 spec**:每仓 `docs/superpowers/specs/` 写**只描述本仓设计**的 spec,并**引用 + 摘要对方 spec**(自洽且接缝显式)。权威划分:总纲 + 共享设计权威在 teleport(本文);协议契约权威在 `fairyland/proto/teleport/v1` + vendor DM 线协议;fairyland specs 放配对 server-design + 可选指针。
3. **各自 plan + 实施**:契约谈定后两仓半独立推进,实施期多子智能体并行。
4. **整体联调**:真客户端 × 真服务端(docker.lima fairyland 栈)端到端活验。

> **纯客户端 phase**(P7 脱敏、防截屏本地部分、Idle 纯策略)无需配对仓,只在 teleport 单仓走流程。

## 9. 测试策略

- `//teleport` 新增源码走 TDD + gtest。
- 客户端 patch 行为以「dev 构建 + docker.lima fairyland 栈」端到端活验为主(历史已证明真 Chrome 能抓出单测掩盖的线协议 bug)。
- 工具脚本按需写 pytest。

## 10. 风险与未决

- **即时刷新推送**:本轮唯一行为偏差点,以轮询兜底,Phase 4 决策是否自建推送(替换 Google FCM)。
- **脱敏(Phase 7)**:Chrome 无原生,自研 enforcement,改动量/风险最大,需独立 spec。
- **策略子集编码**:各策略到 `CloudPolicySettings` 的精确 proto 字段编码(Phase 3 plan 阶段从 vendor `cloud_policy.proto` 取)。
- **跨平台**:本轮仅 macOS 实现,设计预留;Windows/Linux/国产 OS 后续轮。

## 11. 参考

- 本仓:`docs/superpowers/specs/2026-06-03-enterprise-account-system-design.md`(L0 地基)、`docs/research/2026-06-02-chromium-enterprise-modules.md`(能力盘点)、`CHROMIUM_VERSION`(M148)。
- 配对(服务端):fairyland `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-server-design.md`。
- 工作流:项目记忆 [[cross-repo-parallel-dev-workflow]]、[[worktree-location-preference]]。
