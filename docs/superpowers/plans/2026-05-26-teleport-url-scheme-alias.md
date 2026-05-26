# teleport:// URL Scheme 别名 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为内部页面注册 `teleport://` 别名,导航时正向重写到 `chrome://` 加载,地址栏统一显示 `teleport://`,`chrome://` 保持完全可用。

**Architecture:** 纯重写逻辑放进 `//teleport`(可单测);经三处最小上游 patch 注入——scheme 登记(`AddAdditionalSchemes`)、导航正向重写(`BrowserURLHandlerCreated` 的 `AddHandlerPair`)、地址栏显示规范化(`LocationBarModelImpl::GetFormattedURL`,因 `//components` 层级限制就地内联);外加 `chrome://chrome-urls` 标签 patch。

**Tech Stack:** Chromium M148、C++、GN/Siso、gtest、Python 编排脚本(`apply_patches.py`/`bootstrap.py`)。

**Spec:** `docs/superpowers/specs/2026-05-26-teleport-url-scheme-alias-design.md`

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `src/common/teleport_url_scheme.h` | 新建 | `kTeleportScheme` + 两个重写函数声明 |
| `src/common/teleport_url_scheme.cc` | 新建 | 重写函数实现(纯 `GURL→GURL`) |
| `src/common/teleport_url_scheme_unittest.cc` | 新建 | gtest |
| `src/BUILD.gn` | 改 | 把上述源文件加入 `:teleport` 与 `teleport_unittests`,补 `//url`、`//content/public/common` 依赖 |
| `patches/chrome/common/chrome_content_client.cc.patch` | 新建 | `AddAdditionalSchemes` 登记 `teleport` |
| `patches/chrome/browser/chrome_content_browser_client.cc.patch` | 新建 | `BrowserURLHandlerCreated` 注册正/反向 handler |
| `patches/components/omnibox/browser/location_bar_model_impl.cc.patch` | 新建 | `GetFormattedURL` 显示规范化 |
| `patches/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc.patch` | 新建 | chrome-urls 列表标签显示 `teleport://` |
| `scripts/smoke_check.md` | 改 | 增补 scheme 别名冒烟项 |

**约定**:`src/` 下是 overlay 源码(真实文件,提交进分支);上游改动走 `patches/`(`git diff` 生成、一文件一 patch、镜像上游路径)。环境变量 `TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`。构建产物在 `out/mac/arm64/dev`。

---

## Task 0: 把 overlay 源码 symlink 指向本 worktree

**背景**:`chromium/src/teleport` 当前指向 `main` 的 `src/`。本特性新增 `src/common/*`,必须让该 symlink 指向**本 worktree 的 `src/`**,否则新文件不会被编译。

**Files:**
- 无源码改动(仅重建 symlink)

- [ ] **Step 1: 重建 `//teleport` 源链接指向本 worktree**

```bash
WT=/Users/liulichao/workspace/teleport/.claude/worktrees/feature+teleport-scheme-alias
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
unlink "$TELEPORT_CHROMIUM_DIR/src/teleport"      # 移除指向 main/src 的旧链接(rm 可能被 -i 别名)
cd "$WT" && uv run python scripts/bootstrap.py --skip-sync
```
Expected: 打印建立链接;无报错。

- [ ] **Step 2: 验证链接指向本 worktree**

```bash
ls -ld "$TELEPORT_CHROMIUM_DIR/src/teleport"
readlink "$TELEPORT_CHROMIUM_DIR/src/teleport"
```
Expected: `…/teleport` → `…/.claude/worktrees/feature+teleport-scheme-alias/src`。

> 收尾(合并后)需把链接重新指回 `main` 的 `src/`(`rm` 后从主仓库根跑 `bootstrap.py --skip-sync`)。本计划末尾的「完成开发」环节处理。

---

## Task 1: `//teleport` scheme 常量 + 重写纯函数(TDD)

**Files:**
- Create: `src/common/teleport_url_scheme.h`
- Create: `src/common/teleport_url_scheme.cc`
- Test: `src/common/teleport_url_scheme_unittest.cc`
- Modify: `src/BUILD.gn`

- [ ] **Step 1: 写头文件**

`src/common/teleport_url_scheme.h`:
```cpp
// Copyright 2026 BeanSec.
#ifndef TELEPORT_COMMON_TELEPORT_URL_SCHEME_H_
#define TELEPORT_COMMON_TELEPORT_URL_SCHEME_H_

class GURL;
namespace content {
class BrowserContext;
}

namespace teleport {

// Teleport-branded alias for content::kChromeUIScheme ("chrome").
inline constexpr char kTeleportScheme[] = "teleport";

// Navigation rewrite: teleport://host/path... -> chrome://host/path...
// Returns true and rewrites |url| in place when its scheme is "teleport";
// returns false (|url| unchanged) otherwise. Signature matches
// content::BrowserURLHandler::URLHandler; |browser_context| is unused.
bool RewriteTeleportToChrome(GURL* url, content::BrowserContext* browser_context);

// Display rewrite: chrome://host/path... -> teleport://host/path...
// Returns true and rewrites |url| when its scheme is "chrome"; false otherwise.
bool RewriteChromeToTeleport(GURL* url, content::BrowserContext* browser_context);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_URL_SCHEME_H_
```

- [ ] **Step 2: 写实现**

`src/common/teleport_url_scheme.cc`:
```cpp
// Copyright 2026 BeanSec.
#include "teleport/common/teleport_url_scheme.h"

#include "content/public/common/url_constants.h"
#include "url/gurl.h"

namespace teleport {

namespace {
GURL ReplaceScheme(const GURL& url, std::string_view scheme) {
  GURL::Replacements replacements;
  replacements.SetSchemeStr(scheme);
  return url.ReplaceComponents(replacements);
}
}  // namespace

bool RewriteTeleportToChrome(GURL* url, content::BrowserContext* /*unused*/) {
  if (!url->SchemeIs(kTeleportScheme)) {
    return false;
  }
  *url = ReplaceScheme(*url, content::kChromeUIScheme);
  return true;
}

bool RewriteChromeToTeleport(GURL* url, content::BrowserContext* /*unused*/) {
  if (!url->SchemeIs(content::kChromeUIScheme)) {
    return false;
  }
  *url = ReplaceScheme(*url, kTeleportScheme);
  return true;
}

}  // namespace teleport
```

- [ ] **Step 3: 写失败测试**

`src/common/teleport_url_scheme_unittest.cc`:
```cpp
// Copyright 2026 BeanSec.
#include "teleport/common/teleport_url_scheme.h"

#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"
#include "url/url_util.h"

namespace teleport {
namespace {

// teleport:// must be a standard (SCHEME_WITH_HOST) scheme for GURL to parse
// host/path; register it for the duration of the test.
class TeleportUrlSchemeTest : public testing::Test {
 public:
  TeleportUrlSchemeTest() {
    url::AddStandardScheme(kTeleportScheme, url::SCHEME_WITH_HOST);
  }

 private:
  url::ScopedSchemeRegistryForTests scoped_registry_;
};

TEST_F(TeleportUrlSchemeTest, ForwardRewritesSchemeOnly) {
  GURL url("teleport://settings/passwords?q=1#frag");
  EXPECT_TRUE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_EQ(url.spec(), "chrome://settings/passwords?q=1#frag");
}

TEST_F(TeleportUrlSchemeTest, ReverseRewritesSchemeOnly) {
  GURL url("chrome://settings/passwords?q=1#frag");
  EXPECT_TRUE(RewriteChromeToTeleport(&url, nullptr));
  EXPECT_EQ(url.spec(), "teleport://settings/passwords?q=1#frag");
}

TEST_F(TeleportUrlSchemeTest, RoundTrip) {
  GURL url("teleport://version/");
  EXPECT_TRUE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_TRUE(RewriteChromeToTeleport(&url, nullptr));
  EXPECT_EQ(url.spec(), "teleport://version/");
}

TEST_F(TeleportUrlSchemeTest, ForwardIsNoOpForChrome) {
  GURL url("chrome://settings/");
  EXPECT_FALSE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_EQ(url.spec(), "chrome://settings/");
}

TEST_F(TeleportUrlSchemeTest, ReverseIsNoOpForNonChrome) {
  for (const char* spec :
       {"chrome-untrusted://foo/", "devtools://devtools/bundled/x.html",
        "https://example.com/", "chrome-extension://abc/x.html"}) {
    GURL url(spec);
    EXPECT_FALSE(RewriteChromeToTeleport(&url, nullptr)) << spec;
    EXPECT_EQ(url.spec(), GURL(spec).spec()) << spec;
  }
}

TEST_F(TeleportUrlSchemeTest, HostOnlyNoPath) {
  GURL url("teleport://version");
  EXPECT_TRUE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_EQ(url.spec(), "chrome://version/");
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 4: 更新 `src/BUILD.gn`**

把 `src/BUILD.gn` 改成:
```python
# The //teleport additive module, compiled into chrome via a minimal upstream
# BUILD.gn dep patch (see patches/). A standalone test() target keeps unit
# tests buildable without patching upstream test targets.
import("//testing/test.gni")

source_set("teleport") {
  sources = [
    "browser/teleport_startup.cc",
    "browser/teleport_startup.h",
    "common/teleport_url_scheme.cc",
    "common/teleport_url_scheme.h",
  ]
  deps = [
    "//base",
    "//content/public/common",
    "//url",
  ]
}

test("teleport_unittests") {
  sources = [
    "browser/teleport_startup_unittest.cc",
    "common/teleport_url_scheme_unittest.cc",
  ]
  deps = [
    ":teleport",
    "//base/test:run_all_unittests",
    "//testing/gtest",
    "//url",
  ]
}
```

- [ ] **Step 5: 构建并运行 gtest**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests
./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportUrlScheme*'
```
Expected: 全部 PASS(6 个 `TeleportUrlSchemeTest.*`)。

- [ ] **Step 6: 提交**

```bash
cd "$WT"
git add src/common/teleport_url_scheme.h src/common/teleport_url_scheme.cc \
        src/common/teleport_url_scheme_unittest.cc src/BUILD.gn
git commit -m "feat(teleport): add teleport:// scheme constant + URL rewrite helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 注册 `teleport://` 为标准 scheme(patch)

**Files:**
- Create: `patches/chrome/common/chrome_content_client.cc.patch`

`ChromeContentClient::AddAdditionalSchemes`(`chrome/common/chrome_content_client.cc:203`)登记 `teleport`,与 `chrome` 同级(standard / secure / cors / service_worker)。`chrome/common` 可依赖 `//teleport`(后者只依赖 `//base`/`//url`/`//content/public/common`,无环),故直接用 `teleport::kTeleportScheme`。

- [ ] **Step 1: 在 checkout 内编辑上游文件**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/common/chrome_content_client.cc`:

顶部 include 区加入:
```cpp
#include "teleport/common/teleport_url_scheme.h"
```
在 `void ChromeContentClient::AddAdditionalSchemes(Schemes* schemes) {` 函数体**开头**(`for (auto* standard_scheme ...)` 之前)加入:
```cpp
  // teleport overlay: register teleport:// as a first-class alias of chrome://.
  schemes->standard_schemes.push_back(teleport::kTeleportScheme);
  schemes->secure_schemes.push_back(teleport::kTeleportScheme);
  schemes->cors_enabled_schemes.push_back(teleport::kTeleportScheme);
  schemes->service_worker_schemes.push_back(teleport::kTeleportScheme);
```

- [ ] **Step 2: 让 `chrome/common` 依赖 `//teleport`**

`chrome_content_client.cc` 属于 `//chrome/common` 目标。先定位编译它的 target:
```bash
grep -n "chrome_content_client.cc" "$TELEPORT_CHROMIUM_DIR/src/chrome/common/BUILD.gn"
```
(通常是 `static_library("common")`。)编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/common/BUILD.gn`,在该 target 的 `deps` 中加入 `"//teleport"`。

> 该 BUILD.gn 改动也作为一文件一 patch:`patches/chrome/common/BUILD.gn.patch`(在 Step 4 一并生成)。

- [ ] **Step 3: 生成 gn + 构建验证编译通过**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev chrome
```
Expected: 编译链接通过(本步仅验证 scheme 登记不破坏构建)。

- [ ] **Step 4: 生成 patch 并还原 checkout**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p "$WT/patches/chrome/common"
git diff chrome/common/chrome_content_client.cc > "$WT/patches/chrome/common/chrome_content_client.cc.patch"
git diff chrome/common/BUILD.gn > "$WT/patches/chrome/common/BUILD.gn.patch"
git checkout -- chrome/common/chrome_content_client.cc chrome/common/BUILD.gn
```

- [ ] **Step 5: 经 apply_patches 重新应用并确认幂等**

```bash
cd "$WT"
TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium uv run python scripts/apply_patches.py
```
Expected: 打印 `apply patches/chrome/common/chrome_content_client.cc.patch` 等,`overlay applied.`,无冲突。

- [ ] **Step 6: 提交**

```bash
cd "$WT"
git add patches/chrome/common/chrome_content_client.cc.patch patches/chrome/common/BUILD.gn.patch
git commit -m "feat(teleport): register teleport:// scheme via AddAdditionalSchemes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 导航正向重写(patch)

**Files:**
- Create: `patches/chrome/browser/chrome_content_browser_client.cc.patch`

在 `ChromeContentBrowserClient::BrowserURLHandlerCreated`(`chrome/browser/chrome_content_browser_client.cc:5055`)注册一对 handler。正向 `RewriteTeleportToChrome` 命中即把 `teleport://x` 改为 `chrome://x` 并返回 true(短路);反向 `RewriteChromeToTeleport` 让"用户输入 `teleport://`"时虚拟 URL 保持 `teleport://`。`//chrome/browser` 已依赖 `//teleport`(overlay 基础),无需改 BUILD.gn。

**已知 MVP 限制**:短路会跳过 `HandleWebUI` 对个别 chrome:// host 的改写(如 `chrome://help → chrome://settings/help`),故 `teleport://help` 可能不重定向;`teleport://settings`/`version`/`history` 等不受影响。记入 spec「不在本期」。

- [ ] **Step 1: 在 checkout 内编辑上游文件**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/chrome_content_browser_client.cc`:

顶部 include 区加入:
```cpp
#include "teleport/common/teleport_url_scheme.h"
```
在 `BrowserURLHandlerCreated` 内,`for (auto& part : extra_parts_) { ... }` 之后、`// Handler to rewrite chrome://about ...` 之前,插入:
```cpp
  // teleport overlay: rewrite teleport://x -> chrome://x for navigation, and
  // keep a typed teleport:// URL shown as teleport:// (virtual URL). Inserted
  // before the chrome:// handlers so the rewritten URL still loads its WebUI.
  handler->AddHandlerPair(&teleport::RewriteTeleportToChrome,
                          &teleport::RewriteChromeToTeleport);
```

- [ ] **Step 2: 构建并冒烟验证导航**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev chrome
open -n ./out/mac/arm64/dev/Teleport.app --args --disable-field-trial-config
```
人工验证:地址栏输入 `teleport://settings`、`teleport://version`、`teleport://history` 均能打开对应页面(内容与 `chrome://` 版本一致)。

- [ ] **Step 3: 生成 patch 并还原**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p "$WT/patches/chrome/browser"
git diff chrome/browser/chrome_content_browser_client.cc > "$WT/patches/chrome/browser/chrome_content_browser_client.cc.patch"
git checkout -- chrome/browser/chrome_content_browser_client.cc
```

- [ ] **Step 4: 重新应用确认幂等**

```bash
cd "$WT" && TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium uv run python scripts/apply_patches.py
```
Expected: `apply patches/chrome/browser/chrome_content_browser_client.cc.patch`,`overlay applied.`

- [ ] **Step 5: 提交**

```bash
cd "$WT"
git add patches/chrome/browser/chrome_content_browser_client.cc.patch
git commit -m "feat(teleport): rewrite teleport:// -> chrome:// for navigation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 地址栏显示规范化(patch)

**Files:**
- Create: `patches/components/omnibox/browser/location_bar_model_impl.cc.patch`

`LocationBarModelImpl::GetFormattedURL`(`components/omnibox/browser/location_bar_model_impl.cc:109`)在 `GURL url(GetURL());` 之后,对实际为 `chrome://` 的 URL 就地改 scheme 为 `teleport://` 再格式化。**因 `//components` 不得依赖 `//teleport`,此处内联**(用 `content::kChromeUIScheme` + 字面量 `"teleport"`,注释指向 `teleport::kTeleportScheme`)。仅改显示字符串,不动 `GetURL()`。

- [ ] **Step 1: 在 checkout 内编辑上游文件**

编辑 `$TELEPORT_CHROMIUM_DIR/src/components/omnibox/browser/location_bar_model_impl.cc`:

确认顶部已 include `content/public/common/url_constants.h` 与 `url/gurl.h`;若无则加入:
```cpp
#include "content/public/common/url_constants.h"
```
把:
```cpp
  GURL url(GetURL());
```
改为:
```cpp
  GURL url(GetURL());

  // teleport overlay: display internal chrome:// pages as teleport:// (the
  // Teleport-branded alias). Display-only — GetURL() (actual address, security
  // state) is unchanged. Keep "teleport" in sync with teleport::kTeleportScheme.
  if (url.SchemeIs(content::kChromeUIScheme)) {
    GURL::Replacements teleport_scheme;
    teleport_scheme.SetSchemeStr("teleport");
    url = url.ReplaceComponents(teleport_scheme);
  }
```

- [ ] **Step 2: 构建并冒烟验证显示**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev chrome
open -n ./out/mac/arm64/dev/Teleport.app --args --disable-field-trial-config
```
人工验证:输入 `chrome://settings` → 能打开且**地址栏显示 `teleport://settings`**;输入 `teleport://settings` → 同样显示 `teleport://settings`;点击页面内部 `chrome://` 链接后地址栏显示 `teleport://`;新标签页地址栏仍为空。

- [ ] **Step 3: 生成 patch 并还原**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p "$WT/patches/components/omnibox/browser"
git diff components/omnibox/browser/location_bar_model_impl.cc > "$WT/patches/components/omnibox/browser/location_bar_model_impl.cc.patch"
git checkout -- components/omnibox/browser/location_bar_model_impl.cc
```

- [ ] **Step 4: 重新应用确认幂等**

```bash
cd "$WT" && TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium uv run python scripts/apply_patches.py
```
Expected: `apply patches/components/omnibox/browser/location_bar_model_impl.cc.patch`,`overlay applied.`

- [ ] **Step 5: 提交**

```bash
cd "$WT"
git add patches/components/omnibox/browser/location_bar_model_impl.cc.patch
git commit -m "feat(teleport): display chrome:// internal pages as teleport:// in the location bar

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `chrome://chrome-urls` 标签显示 `teleport://`(patch)

**Files:**
- Create: `patches/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc.patch`

`chrome_urls_handler.cc` 把每个 host 拼成 `GURL("chrome://" + host)` 并经 `CompareWebuiUrlInfos`(其 `CHECK` 要求 `chrome://`/`chrome-untrusted://`)排序。**在 `std::sort(...)` 之后**,把每个 `chrome://` 项的 URL 改显示为 `teleport://`。该文件属 `//chrome/browser`,可用 `teleport::RewriteChromeToTeleport`。

- [ ] **Step 1: 在 checkout 内编辑上游文件**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc`:

顶部 include 区加入:
```cpp
#include "teleport/common/teleport_url_scheme.h"
```
在 `std::sort(webui_urls.begin(), webui_urls.end(), &CompareWebuiUrlInfos);` 之后插入:
```cpp
  // teleport overlay: present chrome:// directory entries as teleport://
  // (sorting above CHECK-requires chrome://, so rewrite afterwards;
  // chrome-untrusted:// passes through unchanged).
  for (auto& url_info : webui_urls) {
    teleport::RewriteChromeToTeleport(&url_info->url, /*browser_context=*/nullptr);
  }
```

- [ ] **Step 2: 构建并冒烟验证**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev chrome
open -n ./out/mac/arm64/dev/Teleport.app --args --disable-field-trial-config
```
人工验证:打开 `teleport://chrome-urls`(或 `chrome://chrome-urls`),列表中的内部页链接标签显示为 `teleport://…`,点击可正常跳转;`chrome-untrusted://` 项保持不变。

- [ ] **Step 3: 生成 patch 并还原**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p "$WT/patches/chrome/browser/ui/webui/chrome_urls"
git diff chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc > "$WT/patches/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc.patch"
git checkout -- chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc
```

- [ ] **Step 4: 重新应用确认幂等**

```bash
cd "$WT" && TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium uv run python scripts/apply_patches.py
```
Expected: `apply patches/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc.patch`,`overlay applied.`

- [ ] **Step 5: 提交**

```bash
cd "$WT"
git add patches/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc.patch
git commit -m "feat(teleport): show teleport:// labels on chrome://chrome-urls

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 冒烟清单 + 全量验收

**Files:**
- Modify: `scripts/smoke_check.md`

- [ ] **Step 1: 增补冒烟项**

在 `scripts/smoke_check.md` 末尾追加一节(简体中文):
```markdown
## teleport:// scheme 别名

- 输入 `teleport://settings`、`teleport://version`、`teleport://history` → 能打开,内容与 chrome:// 版本一致。
- 输入 `chrome://settings` → 能打开,地址栏显示 `teleport://settings`。
- 点击页面内部 `chrome://` 链接 / 打开 `chrome://` 书签 → 地址栏显示 `teleport://`;复制地址栏 URL 得到 `teleport://`。
- `teleport://chrome-urls` / `chrome://chrome-urls` → 列表标签显示 `teleport://`,点击可达。
- DevTools / `chrome://inspect` 远程调试仍正常(未别名 devtools://)。
- 新标签页地址栏仍为空。
- 已知限制:`teleport://help` 不重定向到 settings/help(改用 `teleport://settings/help`)。
```

- [ ] **Step 2: 全量构建 + gtest + 冒烟**

```bash
cd "$WT" && TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium uv run python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests chrome
./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportUrlScheme*'
open -n ./out/mac/arm64/dev/Teleport.app --args --disable-field-trial-config
```
逐条对照 spec §13 验收标准与 smoke_check 新增项。

- [ ] **Step 3: 提交**

```bash
cd "$WT"
git add scripts/smoke_check.md
git commit -m "docs(teleport): add scheme-alias smoke checks

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## 完成开发

所有任务完成且验收通过后:
- 用 `superpowers:finishing-a-development-branch` 收尾;合并方式按项目约定 **rebase onto main + squash + fast-forward**。
- **合并后**把 overlay 源链接指回 `main`:
```bash
unlink /Users/liulichao/workspace/teleport/chromium/src/teleport
cd /Users/liulichao/workspace/teleport && TELEPORT_CHROMIUM_DIR=$PWD/chromium uv run python scripts/bootstrap.py --skip-sync
```
