# `teleport://` 内部 URL scheme 别名 — 设计

> **状态**:已批准设计(brainstorm 产出)。
> **日期**:2026-05-26。**分支**:`worktree-feature+teleport-scheme-alias`。
> **上游**:M148(`148.0.7778.180`)。**输入材料**:`docs/research/2026-05-25-teleport-url-scheme-alias.md`。

## 1. 目标

让所有内部页面在**地址栏**中以 `teleport://` 呈现(如 `teleport://settings`、`teleport://version`),替代 Chromium 默认的 `chrome://`,同时保留 `chrome://` 在底层完全可用。

## 2. 范围

**本期(MVP)做:**
- 仅别名 `chrome://`(不含 `chrome-untrusted://`、`devtools://`)。
- `teleport://host/path` 可导航,加载既有 WebUI。
- **地址栏(location bar / omnibox)统一显示** `teleport://`:无论用户输入 `chrome://` / `teleport://`,还是点击内部 `chrome://` 链接、打开 `chrome://` 书签。
- `chrome://` 仍完全可用(扩展、企业策略、CDP/DevTools、硬编码链接、历史/书签中的旧 URL 不受影响)。
- `chrome://chrome-urls` 目录页改名为 `teleport://teleport-urls`(host 成对改名 `chrome-urls`↔`teleport-urls`);页内链接**标签**也显示为 `teleport://`。

**不在本期:**
- `chrome-untrusted://` / `devtools://` 别名。
- 地址栏以外的 URL 显示面(页面信息气泡、悬停链接的状态栏、分享/复制以外路径)——若仍显示 `chrome://` 作为后续增量。
- `chrome-urls` 以外、页面内硬编码的 `chrome://` 文本(设置页文字、错误页等)。
- omnibox 对 `teleport://` 的自动补全建议。
- 历史/书签**列表**里 URL 字符串的显示。

## 3. 方案决策

采用**别名 + 显示**(Brave `brave://`、Edge `edge://`、Vivaldi `vivaldi://` 的通行做法):`chrome://` 仍是底层规范 scheme(实际加载地址);`teleport://` 注册为一等标准 scheme;导航经 `BrowserURLHandler` 把 `teleport://` 正向重写到 `chrome://` 加载;地址栏在显示层把 `chrome://` 规范化显示为 `teleport://`。

**不做硬替换**(详见研究笔记 §2):`kChromeUIScheme` 符号约 371 处引用、硬编码 `"chrome://…"` 字面量约 1005 处、WebUI 安全模型与 `chrome` scheme 强绑定——硬改破坏面大、脆弱、升级 rebase 成本高。

## 4. 架构与 overlay 落点

逻辑尽量收进 `//teleport`(`src/`),patch 只做最小注入,契合 overlay「加法为主、改上游为辅」的约定。

| 单元 | 位置 | 职责 |
| --- | --- | --- |
| scheme 常量 + 重写纯函数 | `//teleport`(新增 `src/common/teleport_url_scheme.{h,cc}` + `_unittest.cc`) | `kTeleportScheme`;`RewriteTeleportToChrome` / `RewriteChromeToTeleport`;纯 `GURL→GURL`,可单测 |
| scheme 登记 | patch `chrome/common/chrome_content_client.cc`(`AddAdditionalSchemes`) | 把 `teleport` 注册为与 `chrome` 同级的标准 scheme |
| 导航重写 | patch `chrome/browser/chrome_content_browser_client.cc`(`BrowserURLHandlerCreated`) | `AddHandlerPair(正向, 反向)`,调用 `//teleport` 纯函数 |
| **显示规范化** | patch `components/omnibox/browser/location_bar_model_impl.cc`(`GetFormattedURL`) | 地址栏把实际 `chrome://` URL 规范化显示为 `teleport://` |
| **omnibox 输入分类** | patch `chrome/browser/autocomplete/chrome_autocomplete_scheme_classifier.cc`(`GetInputTypeForScheme`) | 把**键入**的 `teleport://…` 判为可导航 URL(否则被当搜索词) |
| chrome-urls 标签 | patch `chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc` | 列表项 URL 由 `chrome://` 显示为 `teleport://` |

## 5. 组件设计

### 5.1 常量与纯函数(`//teleport`)
```cpp
namespace teleport {
inline constexpr char kTeleportScheme[] = "teleport";

// teleport://host/path[?query][#frag] -> chrome://host/path...(仅当 scheme==teleport)。
// 返回 true 表示已改写。其余 scheme 原样返回 false。
bool RewriteTeleportToChrome(GURL* url, content::BrowserContext*);

// chrome://host/path... -> teleport://host/path...(仅当 scheme==chrome)。
// chrome-untrusted/devtools/chrome-extension/http(s) 透传,返回 false。
bool RewriteChromeToTeleport(GURL* url, content::BrowserContext*);
}
```
两个函数替换 scheme,并对目录页 host 做 `chrome-urls` ↔ `teleport-urls` 成对改名(其余 host 与 path/query/ref 原样保留)。签名匹配 `content::BrowserURLHandler::URLHandler`(`bool(GURL*, BrowserContext*)`);导航 handler 与 chrome-urls 标签复用本函数,而 `GetFormattedURL` 显示钩子因 `//components`→`//content` 层级限制改为就地内联同样的 scheme+host 改写。

### 5.2 scheme 登记
在 `ChromeContentClient::AddAdditionalSchemes(Schemes*)` 把 `kTeleportScheme` 加入与 `chrome` **同级**的集合:`standard_schemes`(`SCHEME_WITH_HOST`)、`secure_schemes`、`cors_enabled_schemes`、`service_worker_schemes`。`AddAdditionalSchemes` 在所有进程的 `RegisterContentSchemes()` 早期被调用,保证跨进程一致。实现期按需收窄(可能不需要全部集合)。

### 5.3 导航重写(正向)
在 `ChromeContentBrowserClient::BrowserURLHandlerCreated(handler)` 增加:
```cpp
handler->AddHandlerPair(&teleport::RewriteTeleportToChrome,
                        &teleport::RewriteChromeToTeleport);
```
- **正向**(`RewriteURLIfNecessary`,导航开始):`teleport://x` → `chrome://x`,落到既有 WebUI 加载链路。`chrome://` 不被匹配,原样放行。
- **反向**(`ReverseURLRewrite`,经 `NavigationControllerImpl::UpdateVirtualURLToURL`):仅当**原虚拟 URL 是 `teleport://`** 时把回填的实际 `chrome://` 还原为 `teleport://`,即"用户输入 `teleport://`"时保持 `NavigationEntry` 虚拟 URL 为 `teleport://`(影响复制/历史)。

> 注意:`ReverseURLRewrite` 仅在"正向 handler 能匹配原虚拟 URL"时触发,因此它**只覆盖用户输入 `teleport://` 的情形**;用户输入/点击 `chrome://` 的统一显示由 §5.4 解决。

### 5.4 显示规范化(地址栏统一显示的关键)
`LocationBarModelImpl::GetFormattedURL` 以 `GURL url(GetURL())`(实际地址,可能是 `chrome://`)经 `url_formatter::FormatUrl` 生成地址栏文本;`GetFormattedFullURL`、`GetURLForDisplay` 都经此。**在 `FormatUrl` 之前**对该局部 `url` 调用 `RewriteChromeToTeleport`,使任何实际为 `chrome://` 的页面(用户输入 chrome://、点击内部链接、打开书签)在地址栏统一显示 `teleport://`。仅改**显示字符串**,不动 `GetURL()`(实际地址、安全状态等仍基于 `chrome://`)。

### 5.5 chrome-urls 标签
`chrome_urls_handler.cc` 中列表项以 `GURL("chrome://" + host)` 构造,并经 `CompareWebuiUrlInfos`(其 `CHECK` 要求 scheme 为 `chrome://` 或 `chrome-untrusted://`)排序。**在排序之后、写入结果之前**,对每个 `url_info->url` 调用 `RewriteChromeToTeleport`(`chrome-untrusted://` 透传不变)。标签与链接 href 显示为 `teleport://`,点击经正向重写仍正常加载。

## 6. 数据流

- **导航(正向)**:输入/链接 `teleport://host/path` →(forward handler)→ `chrome://host/path` 实际加载;`chrome://` 原样放行。
- **显示(规范化)**:地址栏文本由 `GetFormattedURL` 生成;其中实际地址若为 `chrome://host/path`,先 `RewriteChromeToTeleport` → 显示 `teleport://host/path`。覆盖用户输入 chrome://、内部 chrome:// 链接、chrome:// 书签。
- **输入 `teleport://`** 时,虚拟 URL 经 §5.3 反向保持 `teleport://`,显示层也是 `teleport://`,一致。
- path/query/fragment 全程原样保留。

## 7. scheme 登记细节与理由

实际加载地址始终是 `chrome://`,故 WebUI bindings / CSP / 进程模型仍挂在 `chrome` scheme 上,**无需**为 `teleport://` 单独授予 WebUI 绑定。把 `teleport://` 注册为标准 scheme(`SCHEME_WITH_HOST`)是为了让 URL 解析正确切分 host/path,forward handler 才能拿到结构合法的 `GURL`。

> **注意(实测修正)**:标准 scheme 注册**不足以**让 omnibox 把**键入**的 `teleport://…` 当可导航 URL。omnibox 的"网址 vs 搜索"判定走 `ChromeAutocompleteSchemeClassifier::GetInputTypeForScheme`(默认只认 `IsHandledProtocol`/view-source/js/data 及 OS 注册的外部协议);未识别的 `teleport` 在 macOS 会落到"查询是否有应用注册该 scheme"分支、返回 `EMPTY` → 被当**搜索词**。因此需单独 patch 该分类器,让 `teleport` 返回 `URL`(见 §4「omnibox 输入分类」)。

## 8. 边界与容错

- **匹配范围**:正向/显示钩子仅处理对应 scheme;`chrome-untrusted://`、`devtools://`、`chrome-extension://`、`http(s)://` 一律透传。
- **无 host**:`teleport://`(无 host)与无 host 的 `chrome://` 行为一致(错误页)。
- **`about:` 形式**:仍按上游 `WillHandleBrowserAboutURL` 映射到 `chrome://`,再经 §5.4 显示 `teleport://`(自动)。
- **NTP**:新标签页地址栏留空的特殊行为保持不变,显示钩子不得破坏(列入冒烟)。

## 9. 为何不会死循环

`BrowserURLHandlerImpl::RewriteURLIfNecessary`(正向)对 handler 列表**只遍历一趟、命中即 `return`**,不迭代到不动点、不回灌结果;`ReverseURLRewrite` 单趟。**导航重写单向**(只有 `teleport:// → chrome://`),导航必收敛到 `chrome://`。§5.4 显示规范化是对一份 `GURL` 拷贝做纯字符串格式化、**不触发任何导航**,更不构成循环。

## 10. 测试策略

**gtest(`//teleport` 纯函数,`teleport_unittests`)**:
- forward:`teleport://settings/x?q#f` → `chrome://settings/x?q#f`。
- reverse / 显示:`chrome://settings/x?q#f` → `teleport://settings/x?q#f`。
- 往返:forward∘reverse、reverse∘forward 还原原值。
- 幂等:对已是目标 scheme 的 URL 不重复改写、返回 false。
- 透传:`chrome-untrusted://`、`devtools://`、`http(s)://`、`chrome-extension://` 不变。
- 边界:无 host、仅 host、带 query+fragment、host 大小写。

**冒烟(`scripts/smoke_check.md` 增补)**:
- 输入 `teleport://settings` → 能打开,地址栏显 `teleport://settings`。
- 输入 `chrome://settings` → 能打开,地址栏显 `teleport://settings`。
- 点击内部 `chrome://` 链接 / 打开 `chrome://` 书签 → 地址栏显 `teleport://`。
- `teleport://teleport-urls`(或 `chrome://chrome-urls`)→ 地址栏显 `teleport://teleport-urls`,列表标签显 `teleport://`,点击可达。
- DevTools / `chrome://inspect` 远程调试仍正常(未别名 `devtools://`)。
- 新标签页地址栏仍留空;复制地址栏 URL 得到 `teleport://`。

## 11. 风险与开放

- **显示面覆盖**:§5.4 钩子规范化的是**地址栏**(`GetFormattedURL`,含 `GetFormattedFullURL`/`GetURLForDisplay`)。页面信息气泡、悬停链接状态栏等其它 URL 显示面可能仍出现 `chrome://`,本期不强求(增量)。需在实现期确认 `ChildProcessSecurityPolicy` 等不因显示态 `teleport://` 误判(显示层不改 `GetURL()`,风险低)。
- **跨进程一致性**:scheme 必须在所有进程一致登记,漏进程会导致 URL 解析不一致/崩溃。
- **升级维护**:三个注入点(`AddAdditionalSchemes`、`BrowserURLHandlerCreated`、`GetFormattedURL`)行号随上游漂移;逻辑收敛进 `//teleport` 以最小化 patch。

## 12. 关键文件与注入点(M148,已核实)

| 作用 | 文件:行 |
| --- | --- |
| scheme 早期注册 | `content/common/url_schemes.cc:53`(`RegisterContentSchemes`)、`:62/:72/:92/:120` |
| 嵌入方追加 scheme | `chrome/common/chrome_content_client.cc:203`(`AddAdditionalSchemes`)、`content/public/common/content_client.h:158` |
| 导航重写注册 | `chrome/browser/chrome_content_browser_client.cc:5055`(`BrowserURLHandlerCreated`)、`AddHandlerPair` |
| 正/反向单趟语义 | `content/browser/browser_url_handler_impl.cc`(`RewriteURLIfNecessary` / `ReverseURLRewrite`);反向触发点 `content/browser/renderer_host/navigation_controller_impl.cc:1657`(`UpdateVirtualURLToURL`) |
| 显示规范化钩子 | `components/omnibox/browser/location_bar_model_impl.cc:110`(`GetFormattedURL`,`GURL url(GetURL())` → `url_formatter::FormatUrl`) |
| omnibox 输入分类 | `chrome/browser/autocomplete/chrome_autocomplete_scheme_classifier.cc:66`(`GetInputTypeForScheme`;未识别 scheme 在 macOS 返回 `EMPTY`→搜索,需让 `teleport` 返回 `URL`) |
| 重写范例 | `chrome/browser/browser_about_handler.cc:41`(`HandleChromeAboutAndChromeSyncRewrite`) |
| chrome-urls 列表构造 | `chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc`(`GURL(kChromeUIScheme + host)`,排序后改写) |

## 13. 验收标准

1. `teleport://settings`、`teleport://version`、`teleport://history` 等可正常打开,内容与 `chrome://` 版本一致。
2. 地址栏在各入口(输入 teleport://、输入 chrome://、点击内部链接、书签)均统一显示 `teleport://`;复制得到 `teleport://`。
3. `chrome://` 全部保持可用,DevTools/CDP 不受影响。
4. `teleport://teleport-urls` 打开目录页,地址栏与标签均显 `teleport://`,点击可达。
5. `teleport_unittests` 覆盖 §10 全部 gtest 用例并通过。
6. `--disable-field-trial-config` dev 构建下冒烟项全过,无崩溃。
