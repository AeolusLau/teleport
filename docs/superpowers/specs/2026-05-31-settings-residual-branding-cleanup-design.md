# 共用字符串残留品牌收口设计(Chrome/Chromium → 闪现)

- **日期**:2026-05-31
- **收口的技术债**:TD-009(设置页及其余 UI 的字面 "Chrome")、TD-010(隐藏无后端的 UKM toggle),并顺带收口 **TD-008 的字符串部分**(chrome://management 的 "Chromium")与广义的"残留 Chromium"。
- **定位**:纯前端 / 字符串与资源层改动,**零后端依赖,可立即发布**。
- **明确不在本 spec 内**:任何"指向 Google 的链接 / 入口"(帮助中心 `kChromeHelpVia*URL`、Chrome Web Store 入口、Safe Browsing 说明链、management 页 "Learn more" `kManagedUiLearnMoreUrl`、about 页占位 ToS/隐私链)——需 fairyland 落地页 URL,推迟到另一份 spec(见末尾「后续」)。本 spec 只改**文本**,不动**链接**。

## 1. 背景与问题

Teleport 由 Chromium 源码自建,`GOOGLE_CHROME_BRANDING=false`。现有重命名脚本 `scripts/branding_strings.py` 通过 **grit 消息 id 重映射**把 `chromium_strings.grd` / `components_chromium_strings.grd` 里的独立单词 **"Chromium"** 替换为 Teleport(英文)/ 闪现·閃現(中文),并重键对应 zh `.xtb`。

但用户在 `chrome://settings`、安全拦截页、密码提示、地址栏、自动填充、`chrome://management` 等界面仍看到字面 **"Chrome"** 与 **"Chromium"**。根因:这些串不在 `*_chromium_strings.grd` 里,而在**品牌/非品牌共用**的两个超集:

1. `chrome/app/generated_resources.grd`(含 `<part>` `settings_strings.grdp` 等;26 个 part;翻译落 `chrome/app/resources/generated_resources_zh-CN.xtb` / `..._zh-TW.xtb`)。
2. `components/components_strings.grd`(含 `<part>` `management_strings.grdp`、`autofill_payments_strings.grdp`、`security_interstitials_strings.grdp`、`password_manager_strings.grdp`、`page_info_strings.grdp`、`omnibox_*` 等 67 个 part;翻译落 `components/strings/components_strings_zh-CN.xtb` / `..._zh-TW.xtb`)。

`branding_strings.py` 既不覆盖这两个文件、也不替换 "Chrome"。

### 实测规模(M148,已核实)

- **generated_resources.grd / settings_strings.grdp**:可见消息体里约 **40 余处 "Chrome"**(180 行含 Chrome,但 133 行在 `desc=`、3 行在 `<ex>`,均不显示)+ 1 处 "Chromium"。
- **components_strings.grd(67 个 part)**:可见消息体里约 **30 处 "Chromium" + ~190 处 "Chrome"**,散布在 security interstitials、page info、password manager、omnibox、autofill/payments、management 等常见 UI。
- 另有 **`Google Chrome` 整词**需一并处理(→ Teleport/闪现,去掉 "Google")。

### 两个关键细节

- **`Chromium` 非品牌变体真的会显示**:许多共用串成对出现——`_google_chrome` 分支说 "Chrome"、非品牌分支说 "Chromium"。我们的构建编的是**非品牌分支**,故用户看到的恰恰是 "Chromium"(如 autofill_payments "If enabled, **Chromium** will store a copy of your card…")。
- **`_google_chrome` 分支不能扫**:components 里大量 "Chrome" 串在 `<if expr="_google_chrome">` 分支内,我们的构建**不编、看不到**;替换它们既无用又干扰。替换模型必须**跳过 `_google_chrome` 分支**(对 components 尤其关键)。

### TD-010

隐私设置里的 "让搜索和浏览更好"(UKM,`url_keyed_anonymized_data_collection`)toggle 位于 `personalization_options.html:93`,在 `_google_chrome` 块**之外**,故本构建仍渲染;但 UKM 上送 URL 为空,采集后丢弃——是个**"有反应却无任何后果"的死控件**,文案还暗示数据外发。

## 2. 目标与非目标

**目标**

1. 两个共用超集(generated_resources.grd + components_strings.grd)及其余共用 UI,不再出现指代**本产品**的字面 "Chrome" / "Chromium" / "Google Chrome"(en→Teleport,zh→闪现·閃現)。
2. 隐藏 UKM 死 toggle。
3. 收口方式系统化、可复用、能抵御上游 rebase 漂移。

**非目标**

- 不处理任何指向 Google 的链接 / 入口(推迟,见「后续」)。
- 不改 `desc=` 译者注、`<ex>` 示例(不显示;`<ex>` 还可能扰动 grit id)。
- 不动 `_google_chrome` 分支(我们不编)。
- 不替换真正的外部 Google 产品/平台专有名(见 keep-list)。
- 不动 `chrome://` 之类小写 `chrome`(正则大小写敏感,只匹配 `Chrome`)。

## 3. TD-010 设计(简单项)

新增 patch:`patches/chrome/browser/resources/settings/privacy_page/personalization_options.html.patch`。把 `urlCollectionToggle`(`personalization_options.html:93`)包进一个本构建恒为否的条件(或直接置 `hidden`),使其不渲染。约 5 行,无 id/翻译影响,风险极低。

> 遵循 overlay 既有模式(`about_page.*` 系列已对 settings 资源打 patch)。

## 4. 品牌串收口设计

核心:**扩展 `scripts/branding_strings.py`,新增两个 target = `generated_resources.grd` 与 `components_strings.grd`**,复用其现成的 id-remap + xtb 重键机制。

### 4.1 快照策略改造(支持多 `<part>`)

现有 `_rebrand_target` 把列出的 grdp include 逐个拷进临时目录、以便解析"旧 grd"算旧 id。两个新 target 分别有 26 / 67 个 part,逐个拷贝既繁琐又易漏。

**改为**:在任何写入**之前**,先对真实磁盘上的原始 grd 调 `message_name_to_id`(真实目录下 grit 能解析全部 part)得到 `old_ids`;随后就地改写 grd 与被修改的 grdp;再调一次 `message_name_to_id` 得到 `new_ids`。未被修改的 part 文本不变、其 id 不变,故 `old→new` 差集纯粹来自我们的替换。该改造对现有两个 target 行为等价,只是去掉了临时拷贝依赖,使多 part 的 grd 也能正确处理。

### 4.2 替换模型

在 `rebrand_en_text`(→ `Teleport`)与 `rebrand_zh_text`(→ `闪现` / `閃現`)中,在现有 "Chromium" 规则旁**新增 "Chrome" / "Google Chrome" 规则**,两条规则**共用同一份 keep-list**,作用于上述两个新 target 的 grd/grdp 与四个 xtb。

约束:

- **词边界**:`(?<![A-Za-z0-9_])Chrome(?![A-Za-z0-9_])`(避免命中 `Chromecast` 等);`Google Chrome` 作为整词优先匹配并整体替换为 Teleport/闪现(去掉 "Google")。现有 "Chromium" 规则保持不变(已排除 `ChromiumOS`/`chromium.org`/`Chromium Projects`/`END_LINK_CHROMIUM` 归属链)。
- **只动可见消息体**:不替换 `desc="..."` 属性内文本与 `<ex>...</ex>` 示例文本。
- **跳过 `_google_chrome` 分支**:`<if expr="_google_chrome">...</if>` 内的串本构建不编,不替换。
- **排除上游归属链**:`BEGIN_LINK_CHROMIUM ... END_LINK_CHROMIUM` 跨度内文本不动;其中"Google Chrome help"等链接标签本属已推迟的 Google 链接范畴。
- **keep-list 优先**:命中 keep-list 短语时整体保留。
- **`Google <非 Chrome>` 天然保留**:规则只匹配 `Chrome`/`Chromium` token,故 `Google Account` / `Google Pay` / `Google Wallet` 等不含该 token、自动不被触碰(只有 `Google Chrome` 这一短语会被转换)。

> 实现注记:现有脚本以整文件正则方式替换。对 "Chrome" 引入"只动消息体 + 跳过 `<ex>` / `desc=` / `_google_chrome` 分支"的约束后,若纯文本正则的 lookaround 显得脆弱,可改为在已加载的 grit 节点层面、对每个 active message 节点的可翻译内容做替换(脚本已 `import grd_reader`,且 `ActiveDescendants()` 天然排除 inactive 的 `_google_chrome` 分支)。本 spec 不锁定具体手法,以"正确跳过 `desc`/`<ex>`/归属链/`_google_chrome` 分支"为验收标准。

### 4.3 keep-list 与分类规则

**判定原则**:`Chrome`/`Chromium` 视为本产品名,默认替换;**仅当 `Chrome X` 命名一个独立的外部 Google 产品/平台时才保留**。

**确定保留(keep-list,外部 Google 产品/平台)**

- `Chrome Web Store`
- `Chrome OS` / `ChromeOS`
- `Chrome Remote Desktop`
- `Chrome Canvas`
- `Google Account` / `Google Pay` / `Google Wallet`(不含 `Chrome` token,天然保留;列出以备审查)

**确定替换(= 本产品的某功能/界面/动作)**

- 独立 `Chrome`、`Chromium`、`Google Chrome`
- `Chrome Colors`、`Chrome Settings`、`Chrome Profile`、`Chrome Side Panel`、`Chrome Help`、`Chrome PDF`、`Chrome Signin`/`Chrome Signout`、`Chrome Search`、`Chrome Password Manager` 等"[本产品] 的 X";autofill/payments/page-info/security 等串里的 "saved to Chrome" / "made in Chromium" / "Chromium will store…" 等动作描述。

**实现期逐条分类(按上述原则,在真实上下文中判定,并记入 keep-list 或 replace-list)**

| 形态 | 倾向 | 说明 |
|---|---|---|
| `Chrome Updater` | 多数保留 | 多在更新策略串;命名更新组件,本构建用 Sparkle,相关串多不在主路径。逐条看是否可见。 |
| `Chrome Apps` | 倾向保留 | 旧 `chrome.apps` 平台名(已弃用)。 |
| `Chrome Labs` | 倾向替换 | 实验功能入口 = 本产品的 Labs。 |
| `Chrome Canary`/`Beta`/`Dev` | 视上下文 | 指本产品渠道→替换为 `Teleport Canary` 等;若 flags 中指实际 Google 渠道→保留。 |
| `Chrome Root` (Store) | 保留 | `Chrome Root Store` 是 Google 根证书库技术名。 |
| 其余 ChromeOS 相关(`Chrome IME`/`View` 等) | 保留/不活跃 | 多为 ChromeOS 路径,桌面不活跃。 |

分类产物 = 最终 keep-list,由 §5 的冻结测试锁定。

### 4.4 xtb 重键

将四个 xtb 纳入对应 target 的 `xtb` 映射(`generated_resources_zh-CN/TW.xtb`、`components_strings_zh-CN/TW.xtb`),复用 `rekey_xtb`:按 §4.1 得到的 `old_id→new_id` 重键,并对值跑 `rebrand_zh_text`(其中 Chrome/Chromium→闪现,同 keep-list)。这几个 xtb 体量大,但为一次性脚本执行,可接受。

> 两个新 target **无需** `inject`(这些消息本就 translateable、已有 zh 翻译),不涉及"注入产品名翻译"逻辑。

## 5. 测试

1. **冻结快照测试(pytest,`scripts/tests/`)**:对两个 target 各固化两张清单——① 被替换(id 重映射)的 message 名单;② 被保留的 `Chrome X` 名单。上游 rebase 后任一漂移(新专有名混入、或某可见串该改没改)都会让测试失败,强制进入 review。
2. **脚本幂等**:`branding_strings.py` 重复执行结果稳定(对已替换文本不二次替换)。
3. **构建冒烟**:`uv run python scripts/package.py`(dev)构建通过;目视确认——`chrome://settings` 各分页、`chrome://management`、安全拦截页(证书错误/Safe Browsing 警示)、密码保存提示、地址栏 pedal、自动填充/付款保存提示——无指代本产品的 Chrome/Chromium;UKM toggle 不再出现;**已知 Google 链接保持现状**(本 spec 不动)。
4. **回归**:确认现有 `branding_strings` 对前两个 target 的行为不变(§4.1 改造等价)。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 过度替换,误伤外部产品名 | keep-list + 冻结测试;§4.3 逐条分类 |
| 误扫 `_google_chrome` 分支或 `desc`/`<ex>` | 显式跳过;以测试 + 目视验收 |
| 误改 `<ex>` 扰动 grit id | 只动消息体、显式跳过 `<ex>` |
| 敏感 UI(安全拦截页/密码提示/付款)文案被改 | 这些正是要收口的目标;改后逐屏目视 QA,确保语义自然(如 "saved to 闪现") |
| 巨型 xtb(components_strings ~万级条目)处理 | 一次性脚本,性能可接受;只重键受影响 id |
| 上游 rebase 引入新 `Chrome X` | 冻结测试兜底,review 时暴露 |
| §4.1 快照改造影响既有 target | 回归测试确认行为等价 |

## 7. 落地顺序(TDD)

1. 先写 §5.1 冻结测试骨架(基线为空),建立验收闸。
2. §4.1 快照策略改造 + 现有 target 回归绿。
3. 加 "Chrome"/"Google Chrome" 规则 + keep-list(en/zh),接入 `generated_resources.grd` target,绿。
4. 接入 `components_strings.grd` target,绿。
5. §4.3 逐条分类,补全 keep-list,冻结测试转正。
6. TD-010 patch。
7. dev 构建冒烟,逐屏目视 QA。

> 产物:`scripts/branding_strings.py`(扩展)、`scripts/tests/`(新增测试)、`patches/.../personalization_options.html.patch`(新增)。整体仍属 overlay「加法 + 文本 patch」范畴,无新增 C++、无后端依赖。

## 8. 后续(不在本 spec)

- **指向 Google 的链接 / 入口**:帮助中心 `kChromeHelpVia{Menu,WebUI,Keyboard}URL`、Chrome Web Store 入口(`extension_urls.cc`)、Safe Browsing 说明链、management 页 "Learn more"(`kManagedUiLearnMoreUrl`,TD-008 链接部分)、about 页占位 ToS/隐私链(TD-007)。待 fairyland 提供帮助/隐私/ToS 落地页 URL 后另起一份 spec 统一重定向或隐藏。
- 若将来需要把 UKM/反馈接自有后端,另见 TD-006/TD-010 的"完整方案"。
