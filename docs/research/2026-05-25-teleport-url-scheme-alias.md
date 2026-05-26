# 内部页面 URL scheme:`chrome://` → `teleport://`(研究笔记)

> **状态**:研究笔记,**非已批准设计**。实现留待后续 `brainstorming` 正式产出 spec/plan 后进行。
> **日期**:2026-05-25。**关联**:品牌化完善(`branding-completion`)的延伸,但作为**独立子项目**对待。

## 1. 目标与已定决策

把所有内部页面在地址栏中以 `teleport://` 呈现(如 `teleport://settings`、`teleport://version`),替代 Chromium 默认的 `chrome://`。

**已选方案(用户拍板)**:**别名 + 显示**——把 `teleport://` 注册为一等 scheme 并在 omnibox 中显示;`chrome://` 在底层仍作为规范 scheme 保留,静默兼容(扩展、企业策略、硬编码链接、历史/书签中的旧 URL 仍可用)。

> 这正是 **Brave(`brave://`)、Edge(`edge://`)、Vivaldi(`vivaldi://`)** 的通行做法。

## 2. 为什么不做"硬替换"

把 `chrome` 这个 scheme 名在全仓库改成 `teleport` 不可行:

- **符号 `kChromeUIScheme`**:约 **371** 个文件引用(改常量值可统一这些)。
- **硬编码字符串 `"chrome://…"`**:约 **1005** 个文件直接写死字面量(改常量**不会**联动这些,会大面积失配)。
- **WebUI 安全模型**与 `chrome` scheme 强绑定:进程隔离、WebUI bindings、CSP、`RegisterContentSchemes` 中对该 scheme 的 standard/secure/cors/service-worker 等多重登记。
- **上游 rebase 维护成本**:每次升级 Chromium 都要重新处理上千处冲突。

结论:硬替换破坏面大、脆弱、长期维护痛苦。别名方案以最小侵入达成同样的用户可见效果。

## 3. 技术组成(待 brainstorm 细化)

### 3.1 定义常量
在 overlay(`//teleport`)中定义 `kTeleportScheme = "teleport"`,集中一处供注册与重写复用。

### 3.2 scheme 注册(进程早期、所有进程一致)
- 入口:`content::ContentClient::AddAdditionalSchemes(Schemes*)`,Chrome 侧实现在
  `chrome/common/chrome_content_client.cc:203`(`ChromeContentClient::AddAdditionalSchemes`)。
- 需把 `"teleport"` 加入与 `chrome` **同等**的集合。参考 `content/common/url_schemes.cc` 中
  `RegisterContentSchemes()`(约 `:53`)对 `kChromeUIScheme` 的处理:
  - `url::AddStandardScheme(..., url::SCHEME_WITH_HOST)`(`:62`)
  - `secure_schemes`(`:72`)、`cors_enabled_schemes`(`:92`)、`service_worker_schemes`(`:120`)等。
- **关键约束**:scheme 必须在**每个子进程**启动早期一致注册,否则跨进程 URL 解析不一致会导致崩溃或安全问题。

### 3.3 URL 重写(`content::BrowserURLHandler` 一对 handler)
注册点:`chrome/browser/chrome_content_browser_client.cc:5055`
`ChromeContentBrowserClient::BrowserURLHandlerCreated()`,内部用 `handler->AddHandlerPair(forward, reverse)`
(已有范例:`HandleChromeAboutAndChromeSyncRewrite`,见 `:5068`;`about:` ⇄ `chrome://` 的现成机制)。

- **正向(导航时)**:`teleport://host/path` → `chrome://host/path`
  使其复用全部既有 WebUI 工厂与 host 注册,WebUI 正常加载。
- **反向(显示时)**:`chrome://host/path` → `teleport://host/path`
  使 omnibox/地址栏、内部链接展示为 `teleport://`。
- 参考:`chrome/browser/browser_about_handler.cc`(`HandleChromeAboutAndChromeSyncRewrite` 在 `:41`,
  以及 `WillHandleBrowserAboutURL` / 反向 handler)。

### 3.4 WebUI bindings 与 omnibox 识别
- 确认经反向重写后 `teleport://` 出现在地址栏时,不被当作"非法/可搜索"输入:涉及
  `components/url_formatter`(scheme 识别/修正,如 `url_fixer.cc`)与 omnibox 的 `AutocompleteInput`。
- 由于正向重写把导航落到 `chrome://`,WebUI bindings 仍由 `chrome` scheme 承载,**通常无需**再给
  `teleport://` 单独授予 bindings;但需在实现期验证 `ChildProcessSecurityPolicy` 等检查不会因显示态的
  `teleport://` 而误判。

## 4. 关键文件与注入点(M148,已核实)

| 作用 | 文件:行 |
| --- | --- |
| scheme 早期注册 | `content/common/url_schemes.cc:53`(`RegisterContentSchemes`)、`:62/:72/:92/:120` |
| 嵌入方追加 scheme | `chrome/common/chrome_content_client.cc:203`(`AddAdditionalSchemes`)、`content/public/common/content_client.h:158` |
| URL 重写 handler 注册 | `chrome/browser/chrome_content_browser_client.cc:5055`(`BrowserURLHandlerCreated`)、`AddHandlerPair` |
| about/chrome 重写范例 | `chrome/browser/browser_about_handler.cc:41`(`HandleChromeAboutAndChromeSyncRewrite`) |
| scheme 识别/修正 | `components/url_formatter/url_fixer.cc` |

> 多个 component 内有 `kChromeUIScheme[] = "chrome"` 的**本地副本**(如 `url_formatter`、`error_page`、
> `content_settings` 等),它们各自独立;别名方案下一般无需改动这些(底层仍是 `chrome`)。

## 5. 范围边界与开放问题(留给 brainstorm 决策)

- **别名覆盖面**:是否只别名 `chrome://`,还是也覆盖 `chrome-untrusted://`、`devtools://`?(MVP 倾向只做 `chrome://`。)
- **`chrome-extension://`、`chrome-search://`** 等保持不变(与本议题无关)。
- **用户输入**:`chrome://settings` 是否继续可用?(是,兼容保留。)
- **内部跳转链接**:WebUI 内大量硬编码 `chrome://` 跳转,依赖反向 handler 在显示层统一为 `teleport://`;
  需冒烟覆盖"点击内部链接后地址栏显示"的场景。
- **历史/书签迁移**:已存的 `chrome://` URL 的展示与去重策略。
- **DevTools / 远程调试 / 自动化(CDP)**:确认 `teleport://` 不影响这些以 `chrome://` 为契约的接口。
- **默认页**:NTP、设置等默认 URL 的显示态。

## 6. 风险

- **注册时机/一致性**:scheme 必须在 `RegisterContentSchemes` 阶段、且所有进程一致注册;遗漏子进程会崩溃。
- **显示态泄漏**:某些路径(错误页、安全 UI、enterprise 报告)可能仍以 `chrome://` 文案出现,需逐一排查。
- **上游升级**:重写 handler 与注册点行号会随版本漂移;尽量把逻辑收敛进 `//teleport`,patch 只做最小注入。

## 7. 与 overlay 架构的契合

- 常量、`AddAdditionalSchemes` 追加逻辑、`BrowserURLHandler` 的正/反向 handler 尽量实现在 `//teleport`(`src/`),
  通过既有注入点(`chrome_content_client` / `chrome_content_browser_client`)调用;文本/最小钩子走 `patches/`。
- 重写函数是纯逻辑(URL in → URL out),**适合 TDD**(gtest 覆盖正向/反向/边界:无 host、带 query/fragment、
  非 `chrome` scheme 透传、大小写等)。

## 8. 下一步

通过 `superpowers:brainstorming` 正式立项 → 产出 `docs/superpowers/specs/` 设计与 `docs/superpowers/plans/` 计划 →
在独立 worktree 分支实现。本笔记作为该 brainstorm 的输入材料。
