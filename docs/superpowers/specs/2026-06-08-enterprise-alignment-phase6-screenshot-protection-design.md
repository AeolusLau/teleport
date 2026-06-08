# Phase 6 · Screenshot Protection(防截屏)— 设计 + Watermark 调研存档

> 承接《chrome 企业版能力对齐》总纲(`2026-06-04-chrome-enterprise-alignment-design.md`)的 **Phase 6**。总纲把 P6 定为「Watermark + Screenshot Protection」;调研后**本轮收敛为只做防截屏**(复用 P5 Data Controls 管道,近零新增代码),**水印改为调研存档、留独立 spec 再做**(见 §4)。DLP 内容送检仍 Out。

## 1. 目标与范围

- **In**:防截屏(Screenshot Protection)—— 受管端对匹配 URL 的页面阻断系统截屏/录屏(内容被 OS 排除/黑屏)。复用 P5 的 `DataControlsRules` 下发一条 `SCREENSHOT` 规则;**无新服务端代码、无客户端 patch**;本轮重点是 **live 验证** + 文档。
- **In**:Watermark 调研结论存档(§4),作为未来「水印」独立 spec 的输入。
- **Out(本轮)**:Watermark 实现(文本注入 patch + WatermarkStyle 下发);Data Controls 的 `FILE_DOWNLOAD`(feature 关)与 macOS 不支持的 `PRINTING`;DLP 内容送检。

## 2. 关键事实(已核对 M148 + 复用 P5)

- **防截屏是 Data Controls 的一条 restriction**:`SCREENSHOT` class → `data_controls::ChromeRulesService::BlockScreenshots(url)`。
- **执行链(macOS 已确认接通)**:`DataProtectionNavigationObserver`(`IsScreenshotAllowedByDataControls` → `BlockScreenshots(url)`)→ `BrowserView::ApplyScreenshotSettings(allow)`(在 `#if BUILDFLAG(ENTERPRISE_SCREENSHOT_PROTECTION)` 内)→ `GetWidget()->SetAllowScreenshots(false)` → OS 内容保护(macOS 上窗口内容从截屏/录屏中排除)。
- **构建开关**:`enterprise_screenshot_protection = is_win || is_mac` —— **macOS 默认 true**(本仓 `out/mac/arm64/dev` 实测 `= true`);`enterprise_data_controls = true`。无需改 GN args。
- **schema/平台**:`SCREENSHOT` 在 macOS schema 合法,**仅支持 `BLOCK` 级**(`rule.cc` 的 level 集只有 `kNotSet`/`kBlock`——无 WARN/REPORT,与剪贴板不同)。对比 P5 教训:`PRINTING` 在 macOS 不支持,`SCREENSHOT` 支持。
- **下发复用 P5**:`DataControlsRules`(catalog `ValueJSON` 不透明透传,编码进 `CloudPolicySubProto1.DataControlsRules`,字段 121)已在 P5 落地并 live 验证。SCREENSHOT 只是这串 JSON 里的另一条规则——**服务端零改动**。

## 3. 防截屏:交付与验证

### 3.1 服务端(fairyland)
零新增代码。仅 docs:在 `products/teleport/device-manager/docs/idle-and-data-controls.md` 的 Data Controls 段补一条 `SCREENSHOT` 规则示例 + 平台说明(macOS 支持、仅 BLOCK)。

### 3.2 客户端(teleport)
零 patch。`enterprise_screenshot_protection` 已开、执行链已接通。

### 3.3 规则示例(下发)
```json
[
  {
    "name": "block-screenshot-on-confidential",
    "sources": { "urls": ["example.com"] },
    "restrictions": [ { "class": "SCREENSHOT", "level": "BLOCK" } ]
  }
]
```
(可与 P5 的 `CLIPBOARD` 规则合并在同一个 `DataControlsRules` 数组里。)

### 3.4 live 验证(macOS,复用 dev stack + worktree override + tenant 1111)
1. 经 `SetTenantPolicy` 把上面的 SCREENSHOT 规则写到 tenant 1111 machine scope 的 `DataControlsRules`(单条覆盖即可,不影响其它策略)。
2. 预热缓存 + 重启浏览器,打开 `https://example.com`。
3. `chrome://policy` 确认 `DataControlsRules` 含 SCREENSHOT 规则、无 schema 报错。
4. 对该页面执行系统截屏/录屏(macOS `screencapture` 或录屏)→ 预期页面内容**被排除/黑屏**(`SetAllowScreenshots(false)` 生效)。导航到非匹配页(如 NTP)→ 截屏恢复正常。
5. 验证日志(可选 `--vmodule=*data_controls*=2`):`BlockScreenshots` 命中。

**视觉/交互验证需操作员**(实际截屏判断黑屏)。

## 4. Watermark 调研存档(未来独立 spec 的输入)

**结论:水印渲染已具备,卡点在「文本来源」,需要一个薄客户端 patch + 一种配置下发方式。**

- **渲染**:`components/enterprise/watermarking/`(`WatermarkView` + `watermark.cc`)已实现屏幕平铺水印;打印/PDF 水印同源。无需自研渲染。
- **文本来源(原生唯一)**:`DataProtectionNavigationObserver`(`chrome/browser/enterprise/data_protection/data_protection_navigation_observer.cc`)经**实时 URL 检查连接器**(`ChromeEnterpriseRealTimeUrlLookupService::DoLookup`)拿到 per-URL verdict,verdict 里携带 `watermark_text`;注入点是 `UrlSettings.watermark_text` → `DataProtectionNavigationController`(`watermark_text_ = settings.watermark_text`,约第 79/217 行)→ 通知 `WatermarkView` 绘制。
- **无原生水印文本策略**:Chrome 只有 `WatermarkStyle`(字段 **328**,**嵌套在 `CloudPolicySubProto1`**——P5 教训,vendor 时按嵌套)。`WatermarkStylePolicyHandler` 只从该 JSON 取 `fill_opacity`/`outline_opacity`/`font_size` 三个值写成 3 个 int pref(`kWatermarkStyle*Pref`),**不保留原始 JSON**——因此**不能把水印文本搭车进 WatermarkStyle**。
- **客户端解码限制**:Chrome 的 `policy_proto_decoders.cc` 只解码它内置注册的 `CloudPolicySettings` 字段;**自定义「水印文本」字段无法被未改动的客户端解码成 pref**——要么改解码表/注册 //teleport 策略,要么搭车现有已注册策略。

**未来 spec 的两条候选(Strategy A 系):**
- **A-i(最小):身份合成 + WatermarkStyle 作开关**。客户端 patch 在注入点把 `watermark_text` 合成为「登录用户/设备身份 + 时间戳」(均为客户端已有数据);下发 `WatermarkStyle`(经 P5 catalog,subProto1/328)既开启水印又控外观。零自定义策略、patch 最小。代价:管理员不能自定义文字措辞。
- **A-ii(灵活):专用 //teleport 水印策略**。新增携带「开关 + 自定义文本模板 + 可选 URL 范围」的 //teleport 策略,需额外 patch 客户端策略解码表/handler/pref 注册它。更灵活,patch 更重。

**未来 spec 还需定**:水印生效范围(全部受管页 vs URL 匹配)、文本模板占位符(`{user}`/`{device}`/`{time}`)、打印/PDF 路径是否一并覆盖、`WatermarkStyle` 经 catalog 下发的 e2e。

## 5. 测试

- 防截屏:以 **live e2e 为主**(纯策略驱动 + 内建执行,无新码;gtest 价值低)。验证 SCREENSHOT 规则下发 → `chrome://policy` 无错 → 实际截屏黑屏 → 切走恢复。
- 服务端:仅 docs,无新测试(`DataControlsRules` 的 catalog 校验/编码已在 P5 覆盖)。

## 6. 跨仓协作

- **teleport**(本文,主控 + 客户端):防截屏 live 验证 + 文档 + 水印调研存档。客户端零 patch。
- **fairyland**(服务端):仅在 P5 的 `idle-and-data-controls.md` 补 SCREENSHOT 示例 + 平台说明。无服务端代码。
- 改 `DataControlsRules` 契约不涉及(透传);SCREENSHOT 是规则内容,非新字段。
