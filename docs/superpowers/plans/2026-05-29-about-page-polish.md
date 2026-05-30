# About 页优化实现计划:版本号 / 检查更新 / 底部链接

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 About 页(`chrome://settings/help`)与 `chrome://version` 展示 Teleport 版本号、把「检查更新」对接到既有 Sparkle 能力(含工具栏/菜单升级提示与重启安装),并显示 Report an issue / Privacy policy / Terms of Service 三个链接。

**Architecture:** `//teleport` 核心 source_set 保持零 chrome 依赖,只放与 chrome 无关的 Sparkle 逻辑(统一 `SPUUpdater` 单例 + 自定义 `SPUUserDriver`)与版本解析纯函数。面向 chrome 的适配层(`VersionUpdater::Create`、`BuildState` 桥)作为 overlay 文件,通过 BUILD.gn patch 以 `//teleport/...` 跨目录源**编进 chrome 目标**,从而既能 include chrome 头文件又不形成 GN 依赖环。其余上游文件改动走 `patches/`(一文件一 patch)。

**Tech Stack:** Chromium M148 overlay(GN/Siso/clang)、Objective-C++ + Sparkle 2.9.2、C++(`//teleport` gtest)、Python(`uv` + pytest,打包脚本)。

---

## 背景与约定(实现前必读)

- 本仓库是 Chromium overlay:上游检出在仓库外 `chromium/src`(`$TELEPORT_CHROMIUM_DIR` 覆盖),`src/` 经符号链接挂为 `chromium/src/teleport`(GN `//teleport`)。
- **依赖环约束**:`chrome/browser` 依赖 `//teleport`。所以 `//teleport` 核心 source_set **绝不能** include `chrome/*` 头文件。需要 chrome 头文件的 overlay 文件,必须通过 BUILD.gn patch 以 `//teleport/<path>` 形式加进**对应 chrome 目标的 `sources`**(它们随该 chrome 目标编译,可见 chrome 头文件;同时该目标 deps 里加 `//teleport` 以见到核心头文件)。
- **绝不改全局 `version_info::GetVersionNumber()`**(User-Agent 的 `Chrome/148` 必须保持)。
- 一文件一 patch:`patches/<mirror chromium/src path>.patch`,`git apply` 应用(见 `scripts/apply_patches.py`)。新增 patch 文件须用 `git -C <chromium/src> diff` 生成标准 unified diff(含 `a/`、`b/` 前缀与 index 行)。
- 构建命令(release/updater 开):
  ```bash
  export TELEPORT_CHROMIUM_DIR=/abs/path/to/chromium   # 本机已有检出
  cd "$TELEPORT_CHROMIUM_DIR/src"
  gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
  autoninja -C out/mac/arm64/release chrome
  ```
  dev(updater 关):`out/mac/arm64/dev` + `dev.mac.gn`。
- `//teleport` 单测:`autoninja -C <out> teleport_unittests && <out>/teleport_unittests`。
- 脚本单测:仓库根 `uv run pytest`。
- **构建很慢**(首次数小时,增量数分钟~数十分钟)。C++/overlay 任务的「验证」以 `gn gen` + `autoninja` + 手动冒烟为准,无法做到秒级 TDD 循环;只有纯函数(版本解析、脚本纯逻辑)走真正的红绿 TDD。

## 文件结构总览

**`//teleport` 核心(零 chrome 依赖,编进 `//teleport:teleport` source_set)**
- `src/common/teleport_version.h` —— `GetDisplayVersion()` + 纯函数 `ResolveDisplayVersion()` 声明。
- `src/common/teleport_version.cc` —— `ResolveDisplayVersion()`(跨平台)+ 非 mac 的 `GetDisplayVersion()` 兜底。
- `src/common/teleport_version_mac.mm` —— mac 的 `GetDisplayVersion()`(读 bundle)。
- `src/common/teleport_version_unittest.cc` —— `ResolveDisplayVersion()` 单测。
- `src/browser/mac/teleport_updater.h` —— 核心 updater 自由函数 + 枚举/回调类型(扩展现有文件)。
- `src/browser/mac/teleport_updater.mm` —— 统一 `SPUUpdater` 单例(重构现有文件)。
- `src/browser/mac/teleport_sparkle_user_driver.h/.mm` —— 自定义 `SPUUserDriver`。
- `src/browser/mac/teleport_updater_stub.cc` —— updater 关时的桩(扩展现有文件)。

**面向 chrome 的适配层(overlay 文件,经 BUILD.gn patch 编进 chrome 目标,**不**进 `//teleport` source_set)**
- `src/browser/mac/teleport_version_updater.mm` —— `VersionUpdater::Create`(编进 `chrome/browser/ui:ui`,仅 updater 开)。
- `src/browser/mac/teleport_update_buildstate.h/.mm` —— `BuildState` 桥(编进 `chrome/browser`,mac)。

**patches(上游文件文本改动)**
- `patches/chrome/browser/ui/webui/version/version_ui.cc.patch`
- `patches/chrome/browser/ui/BUILD.gn.patch`
- `patches/chrome/browser/lifetime/application_lifetime.cc.patch`
- `patches/chrome/browser/app_controller_mac.mm.patch`(扩展现有)
- `patches/chrome/browser/BUILD.gn.patch`(扩展现有)
- `patches/chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc.patch`
- `patches/chrome/browser/resources/settings/about_page/about_page.html.patch`
- `patches/chrome/browser/resources/settings/about_page/about_page.ts.patch`

**脚本**
- `scripts/branding_strings.py`(ToS 标签)
- `scripts/_package.py`(抽取版本键 + 新增 `stamp_version_only`)
- `scripts/package.py`(dev 路径补 stamp)
- `scripts/tests/test_package.py`(纯函数单测)

**其它**
- `src/BUILD.gn`(注册核心新源 + 单测)
- `scripts/smoke_check.md`(补冒烟清单)

---

## Task 1: 版本解析纯函数(TDD,`//teleport` 核心)

**Files:**
- Create: `src/common/teleport_version.h`
- Create: `src/common/teleport_version.cc`
- Create: `src/common/teleport_version_mac.mm`
- Test: `src/common/teleport_version_unittest.cc`
- Modify: `src/BUILD.gn`

- [ ] **Step 1: 写头文件**

Create `src/common/teleport_version.h`:

```cpp
#ifndef TELEPORT_COMMON_TELEPORT_VERSION_H_
#define TELEPORT_COMMON_TELEPORT_VERSION_H_

#include <string>

namespace teleport {

// The version string shown in the About page and chrome://version. On macOS
// this is the bundle's CFBundleShortVersionString (stamped to TELEPORT_VERSION
// at packaging time). Never exposes the upstream Chromium version number.
std::string GetDisplayVersion();

// Pure resolver behind GetDisplayVersion(), separated for testing.
// `bundle_short_version` is the app bundle's CFBundleShortVersionString;
// `chromium_version` is version_info::GetVersionNumber(). Returns a "0.0.0-dev"
// placeholder when the bundle was not stamped with a Teleport version (i.e. it
// still equals the compiled-in Chromium version, or is empty) so the Chromium
// version is never displayed.
std::string ResolveDisplayVersion(const std::string& bundle_short_version,
                                  const std::string& chromium_version);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_VERSION_H_
```

- [ ] **Step 2: 写失败的测试**

Create `src/common/teleport_version_unittest.cc`:

```cpp
#include "teleport/common/teleport_version.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportVersionTest, ReturnsBundleVersionWhenStamped) {
  EXPECT_EQ("0.1.3", ResolveDisplayVersion("0.1.3", "148.0.7778.180"));
}

TEST(TeleportVersionTest, FallsBackToDevWhenUnstamped) {
  // Unstamped build: bundle short version still equals the Chromium version.
  EXPECT_EQ("0.0.0-dev",
            ResolveDisplayVersion("148.0.7778.180", "148.0.7778.180"));
}

TEST(TeleportVersionTest, FallsBackToDevWhenEmpty) {
  EXPECT_EQ("0.0.0-dev", ResolveDisplayVersion("", "148.0.7778.180"));
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 3: 写实现(.cc 纯函数 + 非 mac 兜底)**

Create `src/common/teleport_version.cc`:

```cpp
#include "teleport/common/teleport_version.h"

#include "build/build_config.h"

namespace teleport {

std::string ResolveDisplayVersion(const std::string& bundle_short_version,
                                  const std::string& chromium_version) {
  if (bundle_short_version.empty() ||
      bundle_short_version == chromium_version) {
    return "0.0.0-dev";
  }
  return bundle_short_version;
}

#if !BUILDFLAG(IS_MAC)
// Non-mac platforms are a later phase; until they have a real version source,
// return the placeholder rather than leaking the Chromium version.
std::string GetDisplayVersion() {
  return "0.0.0-dev";
}
#endif

}  // namespace teleport
```

Create `src/common/teleport_version_mac.mm`:

```cpp
#include "teleport/common/teleport_version.h"

#import <Foundation/Foundation.h>

#include "base/strings/sys_string_conversions.h"
#include "components/version_info/version_info.h"

namespace teleport {

std::string GetDisplayVersion() {
  NSString* short_version = [[NSBundle mainBundle]
      objectForInfoDictionaryKey:@"CFBundleShortVersionString"];
  std::string bundle =
      short_version ? base::SysNSStringToUTF8(short_version) : std::string();
  return ResolveDisplayVersion(bundle,
                               std::string(version_info::GetVersionNumber()));
}

}  // namespace teleport
```

- [ ] **Step 4: 注册到 `src/BUILD.gn`**

In `src/BUILD.gn`, add to the `source_set("teleport")` `sources` list (keep alphabetical with the existing `common/` entries):

```gn
    "common/teleport_version.cc",
    "common/teleport_version.h",
```

Add to the same `source_set`'s `deps`:

```gn
    "//components/version_info",
```

Inside the existing `if (is_mac) {` block of the `source_set` (alongside the updater header line), add:

```gn
    sources += [ "common/teleport_version_mac.mm" ]
```

In `test("teleport_unittests")` `sources`, add:

```gn
    "common/teleport_version_unittest.cc",
```

- [ ] **Step 5: 运行单测(先确认失败,再确认通过)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport_unittests
./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportVersionTest.*'
```
Expected: 3 tests PASS。(若先在 Step 3 前运行,应因符号缺失而编译/链接失败。)

- [ ] **Step 6: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add src/common/teleport_version.h src/common/teleport_version.cc \
        src/common/teleport_version_mac.mm src/common/teleport_version_unittest.cc \
        src/BUILD.gn
git commit -m "feat(teleport): add display version resolver"
```

---

## Task 2: 版本号接入 version_ui.cc(About 页 + chrome://version)

**Files:**
- Create: `patches/chrome/browser/ui/webui/version/version_ui.cc.patch`
- Create: `patches/chrome/browser/ui/BUILD.gn.patch`

> 说明:`version_ui.cc` 在 `chrome/browser/ui:ui` 目标。该目标当前未依赖 `//teleport`,需在 BUILD.gn patch 中加 `//teleport` 到其 `deps`(Task 5 还会在同一 patch 里加 updater 适配源,本任务先建立 dep + 版本号改动)。

- [ ] **Step 1: 在 chromium 工作树里改 version_ui.cc**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/ui/webui/version/version_ui.cc`:

加 include(放在文件已有 include 区,保持排序合理):
```cpp
#include "teleport/common/teleport_version.h"
```

把 `AddVersionDetailStrings` 里的:
```cpp
  html_source->AddString(version_ui::kVersion,
                         version_info::GetVersionNumber());
```
改为:
```cpp
  html_source->AddString(version_ui::kVersion, teleport::GetDisplayVersion());
```

把 `GetAnnotatedVersionStringForUi()` 里的:
```cpp
      base::UTF8ToUTF16(version_info::GetVersionNumber()),
```
改为:
```cpp
      base::UTF8ToUTF16(teleport::GetDisplayVersion()),
```

- [ ] **Step 2: 在 chromium 工作树里改 chrome/browser/ui/BUILD.gn(加 `//teleport` dep)**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/ui/BUILD.gn`,在 `static_library("ui") {` 的 `deps` / `public_deps` 列表中加入 `//teleport`。找到该 target 的 `deps = [` 起始处(第一条依赖通常是 `":ui_features"` 之类),在其中加一行:
```gn
    "//teleport",
```
(放在该 `deps` 列表首部即可;GN 不要求顺序。)

- [ ] **Step 3: 生成两个 patch 文件**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/webui/version/version_ui.cc \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/ui/webui/version/version_ui.cc.patch
git diff -- chrome/browser/ui/BUILD.gn \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/ui/BUILD.gn.patch
```
检查两个 patch 文件:含 `diff --git a/... b/...` 头与 `index` 行,且只动目标文件。

- [ ] **Step 4: 重置工作树改动,改用 patch 流水线验证幂等**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git checkout -- chrome/browser/ui/webui/version/version_ui.cc chrome/browser/ui/BUILD.gn
cd /Users/liulichao/workspace/teleport-about-page
python scripts/apply_patches.py        # 应重新干净地应用(幂等、fail-fast)
```
Expected: 应用成功,无报错。

- [ ] **Step 5: 构建 + 冒烟**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
autoninja -C out/mac/arm64/release chrome
# 运行 release 构建(official,无需 --disable-field-trial-config)
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/release/Teleport.app/Contents/MacOS/Teleport" &
```
冒烟:`chrome://settings/help` 版本行 = `版本 0.0.0-dev(...)`(release 未打包时 bundle 仍是 chromium 版本 → 回退占位);`chrome://version` 首行值同为 `0.0.0-dev`,且不出现 `148.x`。(打包后显示真实版本见 Task 3/8。)

- [ ] **Step 6: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add patches/chrome/browser/ui/webui/version/version_ui.cc.patch \
        patches/chrome/browser/ui/BUILD.gn.patch
git commit -m "feat(about): show Teleport version in About page and chrome://version"
```

---

## Task 3: dev 通道补 version stamp(脚本)

**Files:**
- Modify: `scripts/_package.py`
- Modify: `scripts/package.py:48-56`
- Create: `scripts/tests/test_package.py`

- [ ] **Step 1: 写失败的 pytest(纯函数:版本键映射)**

Create `scripts/tests/test_package.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _package import version_plist_keys


def test_version_plist_keys_sets_both_version_fields():
    assert version_plist_keys("0.1.3") == {
        "CFBundleShortVersionString": "0.1.3",
        "CFBundleVersion": "0.1.3",
    }
```

Run:
```bash
cd /Users/liulichao/workspace/teleport-about-page
uv run pytest scripts/tests/test_package.py -v
```
Expected: FAIL(`ImportError: cannot import name 'version_plist_keys'`)。

- [ ] **Step 2: 在 `scripts/_package.py` 抽取纯函数 + 新增 dev stamp**

在 `scripts/_package.py` 顶部(`detect_codesign_identity` 之前)加:

```python
def version_plist_keys(version: str) -> dict[str, str]:
    """The Info.plist version fields stamped for any channel (Sparkle compares
    CFBundleVersion; CFBundleShortVersionString is the user-facing string)."""
    return {
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
    }


def stamp_version_only(app: Path, version: str) -> None:
    """Stamp just the version fields into the app's Info.plist (no Sparkle keys,
    no signing). Used by the dev channel so dev builds also display the real
    Teleport version on the About page / chrome://version."""
    info = app / "Contents" / "Info.plist"
    for key, val in version_plist_keys(version).items():
        subprocess.run(["plutil", "-replace", key, "-string", val, str(info)],
                       check=True)
```

把 `stamp_and_inject` 中手写的两条版本键改为复用纯函数。将:
```python
    sets = {
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "SUFeedURL": cfg["feed_url"],
        "SUPublicEDKey": cfg["public_ed_key"],
    }
```
改为:
```python
    sets = {
        **version_plist_keys(version),
        "SUFeedURL": cfg["feed_url"],
        "SUPublicEDKey": cfg["public_ed_key"],
    }
```

- [ ] **Step 3: 在 `scripts/package.py` 的 dev 路径调用 stamp**

`scripts/package.py` 的非 distributable 分支(约 49-56 行):
```python
    if not channel.distributable:
        if args.dry_run:
            print(f"DRY RUN: autoninja -C {out} {' '.join(channel.targets)}  "
                  f"(build only, channel {channel.name})")
            return 0
        build(out, channel)
        print(f"built {channel.name} app at {chromium_src() / out / 'Teleport.app'}")
        return 0
```
改为:
```python
    if not channel.distributable:
        app = chromium_src() / out / "Teleport.app"
        if args.dry_run:
            print(f"DRY RUN: autoninja -C {out} {' '.join(channel.targets)} + "
                  f"stamp version {version} into {app}/Contents/Info.plist  "
                  f"(build only, channel {channel.name})")
            return 0
        build(out, channel)
        _package.stamp_version_only(app, version)
        print(f"built {channel.name} app at {app} (version {version})")
        return 0
```

- [ ] **Step 4: 运行 pytest(确认通过)**

```bash
cd /Users/liulichao/workspace/teleport-about-page
uv run pytest scripts/tests/test_package.py -v
```
Expected: PASS。

- [ ] **Step 5: 手动验证 dev stamp(可选,需已有 dev 构建)**

```bash
printf '0.1.3\n' > TELEPORT_VERSION   # 若尚未设置
uv run python scripts/package.py --channel dev --dry-run   # 看到 stamp 计划
```

- [ ] **Step 6: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add scripts/_package.py scripts/package.py scripts/tests/test_package.py
git commit -m "feat(package): stamp Teleport version into dev channel builds"
```

---

## Task 4: 统一 Sparkle updater 核心(零 chrome 依赖)

> 重构现有 `teleport_updater.mm`(当前用 `SPUStandardUpdaterController`)为单一 `SPUUpdater` + 自定义用户驱动,供后台静默检查与 About 页用户检查共用。本任务只动 `//teleport` 核心;面向 chrome 的接线在 Task 5/6。
> 此处无法独立运行端到端(需 chrome 与运行环境);验证以「`autoninja chrome` 编译通过 + 后台升级回归(Task 8)」为准。本任务结束时至少保证 `chrome` 目标在 release(updater 开)下编译链接通过。

**Files:**
- Modify: `src/browser/mac/teleport_updater.h`
- Modify: `src/browser/mac/teleport_updater.mm`
- Create: `src/browser/mac/teleport_sparkle_user_driver.h`
- Create: `src/browser/mac/teleport_sparkle_user_driver.mm`
- Modify: `src/browser/mac/teleport_updater_stub.cc`
- Modify: `src/BUILD.gn`

- [ ] **Step 1: 扩展 `teleport_updater.h`**

Replace `src/browser/mac/teleport_updater.h` content with:

```cpp
#ifndef TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_

#include <string>

#include "base/functional/callback.h"

namespace teleport {

// Coarse update lifecycle stages surfaced to the About page UI.
enum class UpdateStage {
  kChecking,
  kDownloading,      // `progress` is 0..100
  kExtracting,
  kReadyToRelaunch,  // staged; awaiting install + relaunch
  kUpToDate,
  kFailed,           // `message` carries an error string
};

// Reports progress of a user-initiated check to the About page. `progress` is
// meaningful only for kDownloading; `message` only for kFailed.
using UpdateStatusSink =
    base::RepeatingCallback<void(UpdateStage stage,
                                 int progress,
                                 const std::u16string& message)>;

// Fired once when an update finishes staging and is ready to install on
// relaunch (background OR user-initiated). `version` is the appcast
// CFBundleVersion string. Used by the chrome-side bridge to light the
// toolbar/menu upgrade indicator.
using UpdateReadyCallback =
    base::RepeatingCallback<void(const std::string& version)>;

// Starts the Sparkle updater once on the main thread and kicks a silent
// background check. Reads SUFeedURL / SUPublicEDKey from the main bundle
// (injected at packaging time). No-op if the feed is missing or not https.
// Idempotent.
void StartMacUpdater();

// User-initiated check, for the legacy "Check for Updates…" menu item.
void CheckForUpdatesNow();

// Begins a user-initiated check that reports progress to `sink` (the About
// page). Starts the updater if needed. No-op if the feed is not secure.
void CheckForUpdateUserInitiated(UpdateStatusSink sink);

// If a staged update is ready, ask Sparkle to install it and relaunch now,
// returning true. Otherwise return false (the caller should do a normal
// relaunch). Must be called on the main thread.
bool InstallPendingUpdateAndRelaunchIfReady();

// Registers the callback fired when an update becomes ready. Set once at
// startup by the chrome-side BuildState bridge.
void SetUpdateReadyCallback(UpdateReadyCallback callback);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
```

- [ ] **Step 2: 写自定义用户驱动头文件**

Create `src/browser/mac/teleport_sparkle_user_driver.h`:

```cpp
#ifndef TELEPORT_BROWSER_MAC_TELEPORT_SPARKLE_USER_DRIVER_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_SPARKLE_USER_DRIVER_H_

#import <Foundation/Foundation.h>
#import <Sparkle/Sparkle.h>

#include "teleport/browser/mac/teleport_updater.h"

// A headless SPUUserDriver: it never shows Sparkle's own windows. Instead it
// auto-advances the update (download -> extract -> stage), reports progress to
// an optional status sink (the About page), fires a "ready" callback to drive
// the chrome upgrade indicator, and holds the final install+relaunch reply so
// it can be triggered later from chrome::AttemptRelaunch().
@interface TeleportSparkleUserDriver : NSObject <SPUUserDriver>

// Set/cleared by the updater for each user-initiated check. May be null for
// silent background checks.
- (void)setStatusSink:(teleport::UpdateStatusSink)sink;

// Set once at startup.
- (void)setReadyCallback:(teleport::UpdateReadyCallback)callback;

// True if an update is staged and the install+relaunch reply is held.
- (BOOL)hasPendingUpdate;

// Invokes the held reply to install + relaunch. No-op if none pending.
- (void)installPendingUpdateAndRelaunch;

@end

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_SPARKLE_USER_DRIVER_H_
```

- [ ] **Step 3: 写自定义用户驱动实现**

Create `src/browser/mac/teleport_sparkle_user_driver.mm`:

```cpp
#import "teleport/browser/mac/teleport_sparkle_user_driver.h"

#include "base/strings/sys_string_conversions.h"

@implementation TeleportSparkleUserDriver {
  teleport::UpdateStatusSink _sink;
  teleport::UpdateReadyCallback _readyCallback;
  void (^_relaunchReply)(SPUUserUpdateChoice);
  std::string _pendingVersion;
  uint64_t _expectedLength;
  uint64_t _receivedLength;
}

- (void)setStatusSink:(teleport::UpdateStatusSink)sink {
  _sink = std::move(sink);
}

- (void)setReadyCallback:(teleport::UpdateReadyCallback)callback {
  _readyCallback = std::move(callback);
}

- (BOOL)hasPendingUpdate {
  return _relaunchReply != nil;
}

- (void)installPendingUpdateAndRelaunch {
  if (_relaunchReply) {
    void (^reply)(SPUUserUpdateChoice) = _relaunchReply;
    _relaunchReply = nil;
    reply(SPUUserUpdateChoiceInstall);
  }
}

- (void)reportStage:(teleport::UpdateStage)stage
           progress:(int)progress
            message:(const std::u16string&)message {
  if (_sink) {
    _sink.Run(stage, progress, message);
  }
}

#pragma mark - SPUUserDriver

- (void)showUpdatePermissionRequest:(SPUUpdatePermissionRequest*)request
                              reply:(void (^)(SUUpdatePermissionResponse*))reply {
  reply([SUUpdatePermissionResponse responseWithAutomaticUpdateChecks:YES
                                                   sendSystemProfile:NO]);
}

- (void)showUserInitiatedUpdateCheckWithCancellation:(void (^)(void))cancellation {
  [self reportStage:teleport::UpdateStage::kChecking progress:0 message:u""];
}

- (void)showUpdateFoundWithAppcastItem:(SUAppcastItem*)appcastItem
                                 state:(SPUUserUpdateState*)state
                                 reply:(void (^)(SPUUserUpdateChoice))reply {
  _pendingVersion = base::SysNSStringToUTF8(appcastItem.versionString);
  if (appcastItem.informationOnlyUpdate) {
    reply(SPUUserUpdateChoiceDismiss);
    return;
  }
  reply(SPUUserUpdateChoiceInstall);  // proceed to download/extract
}

- (void)showUpdateReleaseNotesWithDownloadData:(SPUDownloadData*)downloadData {
}

- (void)showUpdateReleaseNotesFailedToDownloadWithError:(NSError*)error {
}

- (void)showUpdateNotFoundWithError:(NSError*)error
                    acknowledgement:(void (^)(void))acknowledgement {
  [self reportStage:teleport::UpdateStage::kUpToDate progress:0 message:u""];
  acknowledgement();
}

- (void)showUpdaterError:(NSError*)error
         acknowledgement:(void (^)(void))acknowledgement {
  [self reportStage:teleport::UpdateStage::kFailed
           progress:0
            message:base::SysNSStringToUTF16(error.localizedDescription)];
  acknowledgement();
}

- (void)showDownloadInitiatedWithCancellation:(void (^)(void))cancellation {
  _expectedLength = 0;
  _receivedLength = 0;
}

- (void)showDownloadDidReceiveExpectedContentLength:(uint64_t)expectedContentLength {
  _expectedLength = expectedContentLength;
}

- (void)showDownloadDidReceiveDataOfLength:(uint64_t)length {
  _receivedLength += length;
  int progress = 0;
  if (_expectedLength > 0) {
    progress = static_cast<int>((_receivedLength * 100) / _expectedLength);
    if (progress > 100) {
      progress = 100;
    }
  }
  [self reportStage:teleport::UpdateStage::kDownloading
           progress:progress
            message:u""];
}

- (void)showDownloadDidStartExtractingUpdate {
  [self reportStage:teleport::UpdateStage::kExtracting progress:0 message:u""];
}

- (void)showExtractionReceivedProgress:(double)progress {
  [self reportStage:teleport::UpdateStage::kExtracting progress:0 message:u""];
}

- (void)showReadyToInstallAndRelaunch:(void (^)(SPUUserUpdateChoice))reply {
  _relaunchReply = [reply copy];
  [self reportStage:teleport::UpdateStage::kReadyToRelaunch
           progress:0
            message:u""];
  if (_readyCallback && !_pendingVersion.empty()) {
    _readyCallback.Run(_pendingVersion);
  }
}

- (void)showInstallingUpdateWithApplicationTerminated:(BOOL)applicationTerminated
                          retryTerminatingApplication:(void (^)(void))retry {
}

- (void)showUpdateInstalledAndRelaunched:(BOOL)relaunched
                         acknowledgement:(void (^)(void))acknowledgement {
  acknowledgement();
}

- (void)dismissUpdateInstallation {
}

@end
```

- [ ] **Step 4: 重写 `teleport_updater.mm`(统一单例)**

Replace `src/browser/mac/teleport_updater.mm` content with:

```cpp
#import "teleport/browser/mac/teleport_updater.h"

#import <Foundation/Foundation.h>
#import <Sparkle/Sparkle.h>

#include <string>

#include "base/no_destructor.h"
#include "teleport/browser/mac/teleport_sparkle_user_driver.h"
#include "teleport/common/teleport_feed_url.h"

namespace teleport {
namespace {

bool FeedIsSecure() {
  NSString* feed =
      [[NSBundle mainBundle] objectForInfoDictionaryKey:@"SUFeedURL"];
  return feed != nil && IsSecureFeedUrl(std::string([feed UTF8String]));
}

// Single Sparkle updater + headless user driver shared by background and
// user-initiated checks. Lives for the process lifetime.
class SparkleUpdater {
 public:
  static SparkleUpdater& Get() {
    static base::NoDestructor<SparkleUpdater> instance;
    return *instance;
  }

  void Start() {
    if (started_ || !FeedIsSecure()) {
      return;
    }
    driver_ = [[TeleportSparkleUserDriver alloc] init];
    if (ready_callback_) {
      [driver_ setReadyCallback:ready_callback_];
    }
    updater_ = [[SPUUpdater alloc] initWithHostBundle:NSBundle.mainBundle
                                    applicationBundle:NSBundle.mainBundle
                                           userDriver:driver_
                                             delegate:nil];
    NSError* error = nil;
    if (![updater_ startUpdater:&error]) {
      updater_ = nil;
      driver_ = nil;
      return;
    }
    started_ = true;
    // Kick a silent check now, on top of Sparkle's scheduled interval.
    [driver_ setStatusSink:teleport::UpdateStatusSink()];
    [updater_ checkForUpdatesInBackground];
  }

  void CheckUserInitiated(UpdateStatusSink sink) {
    Start();
    if (!started_) {
      return;
    }
    [driver_ setStatusSink:std::move(sink)];
    [updater_ checkForUpdates];
  }

  bool InstallPendingAndRelaunch() {
    if (driver_ && [driver_ hasPendingUpdate]) {
      [driver_ installPendingUpdateAndRelaunch];
      return true;
    }
    return false;
  }

  void SetReadyCallback(UpdateReadyCallback callback) {
    ready_callback_ = std::move(callback);
    if (driver_) {
      [driver_ setReadyCallback:ready_callback_];
    }
  }

 private:
  friend class base::NoDestructor<SparkleUpdater>;
  SparkleUpdater() = default;

  bool started_ = false;
  SPUUpdater* updater_ = nil;
  TeleportSparkleUserDriver* driver_ = nil;
  UpdateReadyCallback ready_callback_;
};

}  // namespace

void StartMacUpdater() {
  SparkleUpdater::Get().Start();
}

void CheckForUpdatesNow() {
  SparkleUpdater::Get().CheckUserInitiated(teleport::UpdateStatusSink());
}

void CheckForUpdateUserInitiated(UpdateStatusSink sink) {
  SparkleUpdater::Get().CheckUserInitiated(std::move(sink));
}

bool InstallPendingUpdateAndRelaunchIfReady() {
  return SparkleUpdater::Get().InstallPendingAndRelaunch();
}

void SetUpdateReadyCallback(UpdateReadyCallback callback) {
  SparkleUpdater::Get().SetReadyCallback(std::move(callback));
}

}  // namespace teleport
```

- [ ] **Step 5: 更新 stub(updater 关时的全部符号)**

Replace `src/browser/mac/teleport_updater_stub.cc` content with:

```cpp
// No-op updater implementation for builds with the Sparkle updater disabled
// (teleport_enable_updater=false, e.g. dev). Lets chrome call the updater entry
// points unconditionally without linking Sparkle.
#include "teleport/browser/mac/teleport_updater.h"

namespace teleport {

void StartMacUpdater() {}
void CheckForUpdatesNow() {}
void CheckForUpdateUserInitiated(UpdateStatusSink) {}
bool InstallPendingUpdateAndRelaunchIfReady() {
  return false;
}
void SetUpdateReadyCallback(UpdateReadyCallback) {}

}  // namespace teleport
```

- [ ] **Step 6: 注册用户驱动源到 `src/BUILD.gn`**

In `src/BUILD.gn`, inside `if (teleport_enable_updater) {`(updater 开分支),把:
```gn
      sources += [ "browser/mac/teleport_updater.mm" ]
```
改为:
```gn
      sources += [
        "browser/mac/teleport_sparkle_user_driver.h",
        "browser/mac/teleport_sparkle_user_driver.mm",
        "browser/mac/teleport_updater.mm",
      ]
```

- [ ] **Step 7: 编译核心(release/updater 开)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/release chrome
```
Expected: 编译链接通过(端到端行为在 Task 5/6/8 验证)。

- [ ] **Step 8: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add src/browser/mac/teleport_updater.h src/browser/mac/teleport_updater.mm \
        src/browser/mac/teleport_sparkle_user_driver.h \
        src/browser/mac/teleport_sparkle_user_driver.mm \
        src/browser/mac/teleport_updater_stub.cc src/BUILD.gn
git commit -m "refactor(updater): unify Sparkle into a single SPUUpdater with headless driver"
```

---

## Task 5: About 页「检查更新」适配器(`VersionUpdater::Create`)

> overlay 文件 `teleport_version_updater.mm` 经 BUILD.gn patch 编进 `chrome/browser/ui:ui`(updater 开),并移除上游 `version_updater_mac.mm`(避免 `VersionUpdater::Create` 重复定义)。

**Files:**
- Create: `src/browser/mac/teleport_version_updater.mm`
- Modify: `patches/chrome/browser/ui/BUILD.gn.patch`(在 Task 2 的基础上追加)

- [ ] **Step 1: 写适配器**

Create `src/browser/mac/teleport_version_updater.mm`:

```cpp
// Provides VersionUpdater::Create() on macOS, backed by the teleport Sparkle
// updater. Compiled into the chrome/browser/ui target (NOT the //teleport
// source_set) so it can include chrome headers without a GN dependency cycle.
#include "chrome/browser/ui/webui/help/version_updater.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ptr_util.h"
#include "base/memory/weak_ptr.h"
#include "teleport/browser/mac/teleport_updater.h"

namespace {

class TeleportVersionUpdater : public VersionUpdater {
 public:
  TeleportVersionUpdater() = default;
  TeleportVersionUpdater(const TeleportVersionUpdater&) = delete;
  TeleportVersionUpdater& operator=(const TeleportVersionUpdater&) = delete;
  ~TeleportVersionUpdater() override = default;

  void CheckForUpdate(StatusCallback status_callback,
                      PromoteCallback promote_callback) override {
    // Sparkle has no per-user/system promotion; keep the promote UI hidden.
    promote_callback.Run(VersionUpdater::PROMOTE_HIDDEN);
    teleport::CheckForUpdateUserInitiated(base::BindRepeating(
        &TeleportVersionUpdater::OnStage, weak_factory_.GetWeakPtr(),
        status_callback));
  }

  void PromoteUpdater() override {}

 private:
  void OnStage(StatusCallback callback,
               teleport::UpdateStage stage,
               int progress,
               const std::u16string& message) {
    Status status = CHECKING;
    int reported_progress = 0;
    switch (stage) {
      case teleport::UpdateStage::kChecking:
        status = CHECKING;
        break;
      case teleport::UpdateStage::kDownloading:
        status = UPDATING;
        reported_progress = progress;
        break;
      case teleport::UpdateStage::kExtracting:
        status = UPDATING;
        break;
      case teleport::UpdateStage::kReadyToRelaunch:
        status = NEARLY_UPDATED;
        break;
      case teleport::UpdateStage::kUpToDate:
        status = UPDATED;
        break;
      case teleport::UpdateStage::kFailed:
        status = FAILED;
        break;
    }
    callback.Run(status, reported_progress, /*rollback=*/false,
                 /*powerwash=*/false, std::string(), /*update_size=*/0,
                 message);
  }

  base::WeakPtrFactory<TeleportVersionUpdater> weak_factory_{this};
};

}  // namespace

std::unique_ptr<VersionUpdater> VersionUpdater::Create(
    content::WebContents* /*web_contents*/) {
  return base::WrapUnique(new TeleportVersionUpdater());
}
```

- [ ] **Step 2: 在 chromium 工作树里改 chrome/browser/ui/BUILD.gn(条件替换 mac updater 源)**

确保 Task 2 的 `//teleport` dep 改动已在(若已重置工作树,先 `python scripts/apply_patches.py` 再编辑)。

在 `static_library("ui")` 的 mac 源块里(`webui/help/version_updater_mac.mm` 当前是 `sources` 的一条)做条件化。找到:
```gn
      "webui/help/version_updater_mac.mm",
```
保留它,并在该 mac 源块结束后(同一 `if (is_mac)` 内,`sources = [ ... ]` 之后的位置)追加一段:
```gn
    if (teleport_enable_updater) {
      # The teleport Sparkle-backed VersionUpdater replaces the upstream mac
      # (Omaha-based) one; compiled here so it can see chrome headers without a
      # GN dependency cycle on //teleport.
      sources -= [ "webui/help/version_updater_mac.mm" ]
      sources += [ "//teleport/browser/mac/teleport_version_updater.mm" ]
    }
```
> 注:`import("//teleport/teleport.gni")` 提供 `teleport_enable_updater`。检查 `chrome/browser/ui/BUILD.gn` 顶部是否已 import;若无,在文件顶部 import 区加 `import("//teleport/teleport.gni")`(此 import 也纳入本 patch)。

- [ ] **Step 3: 重新生成 chrome/browser/ui/BUILD.gn 的 patch(覆盖 Task 2 版本)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/BUILD.gn \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/ui/BUILD.gn.patch
```
该 patch 现应同时包含:加 `//teleport` dep、(可能的)`import` 行、`teleport_enable_updater` 条件块。

- [ ] **Step 4: patch 流水线幂等验证**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git checkout -- chrome/browser/ui/BUILD.gn
cd /Users/liulichao/workspace/teleport-about-page
python scripts/apply_patches.py
```
Expected: 成功。

- [ ] **Step 5: 构建 + 冒烟(检查更新)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
autoninja -C out/mac/arm64/release chrome
```
冒烟需要可用的 appcast feed(已配置 canary)。打开 `chrome://settings/help`,点检查更新:
- 无新版本:转圈 → 「已是最新版本」(UPDATED)。
- 有新版本:转圈 → 下载进度 → 出现「重启以更新」按钮(NEARLY_UPDATED)。
(「重启」按钮的安装动作在 Task 6 接线;本任务先验证状态展示;此时点击按钮走默认 chrome 重启,尚不应用 Sparkle 更新。)

- [ ] **Step 6: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add src/browser/mac/teleport_version_updater.mm \
        patches/chrome/browser/ui/BUILD.gn.patch
git commit -m "feat(about): wire About page Check for Updates to Sparkle"
```

---

## Task 6: 重启安装接线 + 工具栏/菜单升级提示

> 在 `chrome::AttemptRelaunch()` 一处拦截待装更新(覆盖 About 按钮与主菜单升级项);并在启动时注册 `BuildState` 桥,使后台/用户检查就绪时点亮升级提示。

**Files:**
- Create: `src/browser/mac/teleport_update_buildstate.h`
- Create: `src/browser/mac/teleport_update_buildstate.mm`
- Create: `patches/chrome/browser/lifetime/application_lifetime.cc.patch`
- Modify: `patches/chrome/browser/app_controller_mac.mm.patch`(扩展现有)
- Modify: `patches/chrome/browser/BUILD.gn.patch`(扩展现有)

- [ ] **Step 1: 写 BuildState 桥**

Create `src/browser/mac/teleport_update_buildstate.h`:

```cpp
#ifndef TELEPORT_BROWSER_MAC_TELEPORT_UPDATE_BUILDSTATE_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_UPDATE_BUILDSTATE_H_

namespace teleport {

// Registers the "update ready" callback so a staged Sparkle update lights the
// toolbar app-menu upgrade indicator (via BuildState). Call once at startup,
// before StartMacUpdater(). Compiled into chrome/browser so it can touch
// BuildState without a GN dependency cycle on //teleport.
void InstallUpdateReadyBuildStateBridge();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_UPDATE_BUILDSTATE_H_
```

Create `src/browser/mac/teleport_update_buildstate.mm`:

```cpp
#include "teleport/browser/mac/teleport_update_buildstate.h"

#include <optional>
#include <string>

#include "base/functional/bind.h"
#include "base/version.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/upgrade_detector/build_state.h"
#include "teleport/browser/mac/teleport_updater.h"

namespace teleport {
namespace {

void OnUpdateReady(const std::string& version) {
  if (!g_browser_process) {
    return;
  }
  BuildState* build_state = g_browser_process->GetBuildState();
  if (!build_state) {
    return;
  }
  base::Version parsed(version);
  build_state->SetUpdate(
      BuildState::UpdateType::kNormalUpdate,
      parsed.IsValid() ? parsed : base::Version(), std::nullopt);
}

}  // namespace

void InstallUpdateReadyBuildStateBridge() {
  SetUpdateReadyCallback(base::BindRepeating(&OnUpdateReady));
}

}  // namespace teleport
```

- [ ] **Step 2: 改 application_lifetime.cc(拦截重启)**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/lifetime/application_lifetime.cc`:

在 include 区(`build/build_config.h` 之后)加:
```cpp
#if BUILDFLAG(IS_MAC)
#include "teleport/browser/mac/teleport_updater.h"  // teleport overlay
#endif
```

把:
```cpp
void AttemptRelaunch() {
  AttemptRestart();
}
```
改为:
```cpp
void AttemptRelaunch() {
#if BUILDFLAG(IS_MAC)
  // teleport overlay: if a Sparkle update is staged, install + relaunch via
  // Sparkle instead of a plain restart so the new version is applied.
  if (teleport::InstallPendingUpdateAndRelaunchIfReady()) {
    return;
  }
#endif
  AttemptRestart();
}
```

- [ ] **Step 3: 改 app_controller_mac.mm(注册桥 + 已有 StartMacUpdater)**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/app_controller_mac.mm`。当前已有(由现有 patch 注入):
```objc
#import "teleport/browser/mac/teleport_updater.h"  // teleport overlay
...
  teleport::StartMacUpdater();  // teleport overlay: start Sparkle auto-update
```
在 include 处再加:
```objc
#import "teleport/browser/mac/teleport_update_buildstate.h"  // teleport overlay
```
把 `teleport::StartMacUpdater();` 那行改为(桥必须在 Start 之前注册):
```objc
  teleport::InstallUpdateReadyBuildStateBridge();  // teleport overlay
  teleport::StartMacUpdater();  // teleport overlay: start Sparkle auto-update
```

- [ ] **Step 4: 改 chrome/browser/BUILD.gn(把桥源编进 chrome/browser)**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/BUILD.gn`。当前 `deps` 已含 `//teleport`(由现有 patch)。新增桥源:在 mac 源块里加(若无 mac 专属 `sources` 块,放在 `if (is_mac) { sources += [...] }` 处;同时确保顶部 `import("//teleport/teleport.gni")` 可用,如缺则加):
```gn
    sources += [
      "//teleport/browser/mac/teleport_update_buildstate.h",
      "//teleport/browser/mac/teleport_update_buildstate.mm",
    ]
```
> 桥对 updater 开/关都安全(关时 `SetUpdateReadyCallback` 是 stub 空实现),故 mac 下无条件编入即可。

- [ ] **Step 5: 生成/更新三个 patch**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/lifetime/application_lifetime.cc \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/lifetime/application_lifetime.cc.patch
git diff -- chrome/browser/app_controller_mac.mm \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/app_controller_mac.mm.patch
git diff -- chrome/browser/BUILD.gn \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/BUILD.gn.patch
```

- [ ] **Step 6: patch 流水线幂等验证**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git checkout -- chrome/browser/lifetime/application_lifetime.cc \
                chrome/browser/app_controller_mac.mm chrome/browser/BUILD.gn
cd /Users/liulichao/workspace/teleport-about-page
python scripts/apply_patches.py
```
Expected: 成功。

- [ ] **Step 7: 构建 + 端到端冒烟**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
autoninja -C out/mac/arm64/release chrome
```
端到端(用一个比当前低的 `TELEPORT_VERSION` 打较低版本、发布较高版本到 feed,沿用 0.1.x 升级验证法):
- 启动后台静默检查发现新版本 → 工具栏主菜单按钮出现升级小圆点 + 菜单出现「重启以更新」。
- About 页检查 → 「重启以更新」按钮。
- 点 About 按钮 或 主菜单升级项 → Sparkle 安装并重启到新版本。

- [ ] **Step 8: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add src/browser/mac/teleport_update_buildstate.h \
        src/browser/mac/teleport_update_buildstate.mm \
        patches/chrome/browser/lifetime/application_lifetime.cc.patch \
        patches/chrome/browser/app_controller_mac.mm.patch \
        patches/chrome/browser/BUILD.gn.patch
git commit -m "feat(updater): apply staged update on relaunch and light upgrade indicator"
```

---

## Task 7: 底部链接(Report an issue / Privacy policy / Terms of Service)

**Files:**
- Create: `patches/chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc.patch`
- Create: `patches/chrome/browser/resources/settings/about_page/about_page.html.patch`
- Create: `patches/chrome/browser/resources/settings/about_page/about_page.ts.patch`
- Modify: `scripts/branding_strings.py`

- [ ] **Step 1: ToS 标签字符串(branding_strings.py)**

`IDS_ABOUT_TERMS_OF_SERVICE` 在非 CfT 的 chromium 分支是占位文案(「Not used in Teleport. Placeholder…」)。在 `scripts/branding_strings.py` 增加一处替换,把该占位行改为真实标签 `Terms of Service`。

先查看 `branding_strings.py` 现有替换写法(它已 rebrand `chromium_strings.grd`),沿用同样机制新增一条:把 `chromium_strings.grd` 中
```
          <message name="IDS_ABOUT_TERMS_OF_SERVICE" desc="The terms of service label in the About box." translateable="false">
            Not used in Teleport. Placeholder to keep resource maps in sync.
          </message>
```
的消息体替换为(去掉 `translateable="false"`,给出真实英文源):
```
          <message name="IDS_ABOUT_TERMS_OF_SERVICE" desc="The terms of service label in the About box.">
            Terms of Service
          </message>
```
> 实现细节:在 `branding_strings.py` 里用与既有替换一致的字符串替换/正则方式定位这段(`_is_chrome_for_testing_branded` 的 `<else>` 分支内)。运行 `python scripts/branding_strings.py` 后用 `git -C "$TELEPORT_CHROMIUM_DIR/src" diff -- chrome/app/chromium_strings.grd` 确认只改了这一处。

- [ ] **Step 2: strings provider(无条件注入四个键)**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc` 的 `AddAboutStrings`。

把:
```cpp
#if BUILDFLAG(GOOGLE_CHROME_BRANDING)
      {"aboutReportAnIssue", IDS_SETTINGS_ABOUT_PAGE_REPORT_AN_ISSUE},
      {"aboutPrivacyPolicy", IDS_SETTINGS_ABOUT_PAGE_PRIVACY_POLICY},
#endif
```
改为(去掉守卫):
```cpp
      // teleport overlay: always show these links (placeholder URLs for now).
      {"aboutReportAnIssue", IDS_SETTINGS_ABOUT_PAGE_REPORT_AN_ISSUE},
      {"aboutPrivacyPolicy", IDS_SETTINGS_ABOUT_PAGE_PRIVACY_POLICY},
```

把函数末尾:
```cpp
#if BUILDFLAG(GOOGLE_CHROME_BRANDING) || \
    BUILDFLAG(GOOGLE_CHROME_FOR_TESTING_BRANDING)
  html_source->AddString("aboutTermsURL", chrome::kChromeUITermsURL);
  html_source->AddLocalizedString("aboutProductTos",
                                  IDS_ABOUT_TERMS_OF_SERVICE);
#endif
```
改为(去掉守卫,URL 用占位):
```cpp
  // teleport overlay: show Terms of Service with a placeholder URL.
  html_source->AddString("aboutTermsURL", "https://teleport.example.com/terms");
  html_source->AddLocalizedString("aboutProductTos",
                                  IDS_ABOUT_TERMS_OF_SERVICE);
```

- [ ] **Step 3: about_page.html(去守卫)**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/resources/settings/about_page/about_page.html`。

把:
```html
<if expr="_google_chrome">
      <cr-link-row class="hr" id="reportIssue" on-click="onReportIssueClick_"
          hidden="[[!prefs.feedback_allowed.value]]"
          label="$i18n{aboutReportAnIssue}" external></cr-link-row>
      <cr-link-row class="hr" id="privacyPolicy"
        on-click="onPrivacyPolicyClick_" label="$i18n{aboutPrivacyPolicy}"
        external></cr-link-row>
</if>
```
改为(去掉 `<if>`/`</if>` 两行,保留中间内容):
```html
      <cr-link-row class="hr" id="reportIssue" on-click="onReportIssueClick_"
          hidden="[[!prefs.feedback_allowed.value]]"
          label="$i18n{aboutReportAnIssue}" external></cr-link-row>
      <cr-link-row class="hr" id="privacyPolicy"
        on-click="onPrivacyPolicyClick_" label="$i18n{aboutPrivacyPolicy}"
        external></cr-link-row>
```

把 ToS 段:
```html
<if expr="_google_chrome or _is_chrome_for_testing_branded">
        <div class="secondary">
          <a id="tos" href="$i18n{aboutTermsURL}">$i18n{aboutProductTos}</a>
        </div>
</if>
```
改为(去掉 `<if>`/`</if>`):
```html
        <div class="secondary">
          <a id="tos" href="$i18n{aboutTermsURL}">$i18n{aboutProductTos}</a>
        </div>
```

- [ ] **Step 4: about_page.ts(去守卫 + 占位隐私 URL)**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/resources/settings/about_page/about_page.ts`。

把:
```ts
// <if expr="_google_chrome">
export const ABOUT_PAGE_PRIVACY_POLICY_URL: string =
    'https://policies.google.com/privacy';
// </if>
```
改为(去守卫 + 占位 URL):
```ts
// teleport overlay: placeholder privacy policy URL (replace later).
export const ABOUT_PAGE_PRIVACY_POLICY_URL: string =
    'https://teleport.example.com/privacy';
```

把:
```ts
  // <if expr="_google_chrome">
  private onReportIssueClick_() {
    this.aboutBrowserProxy_.openFeedbackDialog();
  }

  private onPrivacyPolicyClick_() {
    OpenWindowProxyImpl.getInstance().openUrl(ABOUT_PAGE_PRIVACY_POLICY_URL);
  }
  // </if>
```
改为(去 `// <if>` / `// </if>` 两行):
```ts
  private onReportIssueClick_() {
    this.aboutBrowserProxy_.openFeedbackDialog();
  }

  private onPrivacyPolicyClick_() {
    OpenWindowProxyImpl.getInstance().openUrl(ABOUT_PAGE_PRIVACY_POLICY_URL);
  }
```

- [ ] **Step 5: 生成三个 patch**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc.patch
git diff -- chrome/browser/resources/settings/about_page/about_page.html \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/resources/settings/about_page/about_page.html.patch
git diff -- chrome/browser/resources/settings/about_page/about_page.ts \
  > /Users/liulichao/workspace/teleport-about-page/patches/chrome/browser/resources/settings/about_page/about_page.ts.patch
```

- [ ] **Step 6: patch 流水线幂等验证(注意 branding_strings.py 顺序)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git checkout -- chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc \
                chrome/browser/resources/settings/about_page/about_page.html \
                chrome/browser/resources/settings/about_page/about_page.ts \
                chrome/app/chromium_strings.grd
cd /Users/liulichao/workspace/teleport-about-page
python scripts/apply_patches.py        # 应用 patches/ + branding/
python scripts/branding_strings.py     # 重新 rebrand(含新增 ToS 标签)
```
> 确认 `branding_strings.py` 幂等:重复运行不报错、结果一致。

- [ ] **Step 7: 构建 + 冒烟**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/release chrome
```
冒烟:`chrome://settings/help` 底部出现 `Report an issue`(点击弹原生反馈对话框)、`Privacy policy`(打开占位 URL)、版权段末尾 `Terms of Service`(打开占位 URL)。

- [ ] **Step 8: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add patches/chrome/browser/ui/webui/settings/settings_localized_strings_provider.cc.patch \
        patches/chrome/browser/resources/settings/about_page/about_page.html.patch \
        patches/chrome/browser/resources/settings/about_page/about_page.ts.patch \
        scripts/branding_strings.py
git commit -m "feat(about): show Report an issue / Privacy policy / Terms of Service links"
```

---

## Task 8: 冒烟清单 + 端到端回归

**Files:**
- Modify: `scripts/smoke_check.md`

- [ ] **Step 1: 补充冒烟清单**

在 `scripts/smoke_check.md` 增加「About 页 / 版本 / 更新」一节,逐项列出:

```markdown
## About 页 / 版本 / 更新(macOS)

- [ ] dev(经 `package.py --channel dev` stamp 后):chrome://settings/help 版本行 = `版本 <TELEPORT_VERSION>(非正式版本) (arm64)`;chrome://version 首行值 = `<TELEPORT_VERSION>`,不出现 `148.x`。
- [ ] 裸 `autoninja chrome`(未 stamp):版本显示 `0.0.0-dev`,不出现 chromium 版本号。
- [ ] canary 打包:版本行含「正式版本」+ `arm64` + 真实 Teleport 版本。
- [ ] 检查更新 - 无更新:转圈 → 「已是最新版本」。
- [ ] 检查更新 - 有更新:转圈 → 进度 → 「重启以更新」按钮;同时工具栏主菜单按钮升级小圆点 + 菜单「重启以更新」项出现。
- [ ] 点 About「重启」或主菜单升级项 → Sparkle 安装并重启到新版本。
- [ ] 底部链接:Report an issue 弹原生反馈对话框;Privacy policy / Terms of Service 打开占位 URL。
- [ ] 回归:不触发更新时,About「重启」与主菜单普通重启行为正常(走 AttemptRestart)。
- [ ] 回归:后台静默升级闭环正常(架构 A 重构后重点项,沿用 0.1.x 升级验证法)。
```

- [ ] **Step 2: 完整 patch 流水线 + 全量构建 + 单测**

```bash
cd /Users/liulichao/workspace/teleport-about-page
uv run pytest                                  # 脚本单测
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/release chrome
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests       # //teleport gtest
```

- [ ] **Step 3: 按清单逐项手动冒烟**

按 Step 1 清单实测,全部勾选通过。端到端升级用「低版本装机 + 高版本发 feed」法(参考 canary 渠道 spec 与既有 0.1.x 验证)。

- [ ] **Step 4: Commit**

```bash
cd /Users/liulichao/workspace/teleport-about-page
git add scripts/smoke_check.md
git commit -m "docs(smoke): add About page / version / update checks"
```

---

## 自查(spec 覆盖核对)

- 版本号(Teleport,隐藏 chromium)→ Task 1/2(About 页 + chrome://version),dev stamp → Task 3。 ✓
- 检查更新对接 Sparkle(原生嵌入)→ Task 4(核心)+ Task 5(适配器)。 ✓
- 重启安装(About + 主菜单单点拦截)→ Task 6。 ✓
- 工具栏/主菜单升级提示(BuildState)→ Task 6。 ✓
- 底部三链接(Report/Privacy/ToS,占位 URL,ToS 标签字符串)→ Task 7。 ✓
- 测试:ResolveDisplayVersion gtest(Task 1)、version_plist_keys pytest(Task 3)、冒烟清单(Task 8)。 ✓
- 不改全局 version_info / UA → Task 2 只改 version_ui 两个展示点。 ✓
- 依赖环规避(核心零 chrome 依赖,适配层跨目录编进 chrome 目标)→ Task 4/5/6 文件归属。 ✓

## 关键风险与提示

- **跨目录 GN 源**(`sources += [ "//teleport/..." ]` 进 chrome 目标):这是规避依赖环的核心手段。Task 5/6 的 `gn gen` 必须先通过再继续;若 GN 报错,改用「在 chrome 目标新增子 group/source_set 并加 `//teleport` 到其 deps」的等价写法,但**不得**让 `//teleport` 核心 source_set 依赖 chrome。
- **架构 A 重构**(Task 4)动了已跑通的后台升级:Task 6/8 必须回归后台静默升级闭环。
- **`branding_strings.py` 与 patch 的应用顺序**:`apply_patches.py` 先行,`branding_strings.py` 后跑(它改 `chromium_strings.grd`);两者都需幂等。
- **patch 生成规范**:务必用 `git -C "$TELEPORT_CHROMIUM_DIR/src" diff -- <file>` 生成,保证 `a/`、`b/`、`index` 头齐全,`git apply` 可用。
- **DCHECK**:`AboutHandler::SetUpdateStatus` 要求非 UPDATING 时 progress==0;适配器仅在 kDownloading 传非零进度,已满足。
