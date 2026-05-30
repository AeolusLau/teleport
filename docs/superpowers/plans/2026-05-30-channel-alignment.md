# 渠道对齐(version_info::Channel)+ dogfood→canary 改名 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让非品牌 Teleport 构建在运行期上报真实的 `version_info::Channel`(canary→CANARY),修复升级提示徽标时机,并把运营渠道 `dogfood` 更名为 `canary`、把字段试验钉死到编译默认。

**Architecture:** 打包期把 `TeleportChannel` 键 stamp 进已签名的 Info.plist;一处最小上游补丁让非品牌的 `channel_info_mac.mm` 经新 overlay `teleport::ChannelFromName` 解析该键,使 `chrome::GetChannel()` 返回真实通道。bundle ID 不变,「编译一次打 N 份」架构不变。

**Tech Stack:** Chromium M148 overlay(C++ source_set `//teleport` + gtest)、`git apply` 文本补丁、Python 打包脚本(`uv`/pytest)、GN args。

---

## 前置条件(实现期一次性设置)

> **关键(CLAUDE.md gotcha)**:本计划在独立 worktree `worktree-channel-alignment` 上实现,但巨大的 chromium 检出只存在于主检出 `/Users/liulichao/workspace/teleport/chromium`,且 overlay 源码经符号链接 `chromium/src/teleport` 挂载。实现前必须:
>
> 1. **导出 chromium 路径**(否则脚本会找 `<worktree>/chromium` 假路径):
>    ```bash
>    export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
>    ```
> 2. **把 overlay 符号链接指向本 worktree 的 src**(默认指向主检出 src,新增文件不会被编到):
>    ```bash
>    ln -sfn /Users/liulichao/workspace/teleport-channel-alignment/src \
>            /Users/liulichao/workspace/teleport/chromium/src/teleport
>    ```
>    > 合并回 main 后改回主检出:`ln -sfn /Users/liulichao/workspace/teleport/src /Users/liulichao/workspace/teleport/chromium/src/teleport`(主检出 src 届时已含合并内容)。
> 3. 确认 dev out 目录已 gen(CLAUDE.md 已验证存在):若无,`cd "$TELEPORT_CHROMIUM_DIR/src" && gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'`。
>
> **用户手动维护(不在本计划代码改动内)**:`scripts/release_config.local.toml`(gitignored,含真实 OSS 路径)的 `[channel.dogfood]`→`[channel.canary]`,三个键路径段 `/dogfood/`→`/canary/`。发布前的 OSS 前缀/桶策略/RAM 权限调整见 spec §6。

所有 `git` 命令在 worktree `/Users/liulichao/workspace/teleport-channel-alignment` 内执行;所有 `autoninja`/`gn` 命令在 `$TELEPORT_CHROMIUM_DIR/src` 内执行;所有 `uv run pytest` 在 worktree 根执行。

---

## Task 1: Overlay 运行期通道解析器(C++,TDD)

**Files:**
- Create: `src/common/teleport_channel.h`
- Create: `src/common/teleport_channel.cc`
- Create: `src/common/teleport_channel_mac.mm`
- Test: `src/common/teleport_channel_unittest.cc`
- Modify: `src/BUILD.gn`

- [ ] **Step 1: 创建头文件 `src/common/teleport_channel.h`**

```cpp
#ifndef TELEPORT_COMMON_TELEPORT_CHANNEL_H_
#define TELEPORT_COMMON_TELEPORT_CHANNEL_H_

#include <string>
#include <string_view>

#include "components/version_info/channel.h"

namespace teleport {

// Maps a TeleportChannel Info.plist string to a runtime release channel.
// "canary"->CANARY, "beta"->BETA, "stable"->STABLE; anything else (empty,
// "dev", or an unrecognized value) maps to UNKNOWN -- the honest value for a
// from-source / unstamped build. Pure; separated for testing.
version_info::Channel ChannelFromName(std::string_view name);

// Reads the main bundle's TeleportChannel key (stamped at packaging time),
// returning "" when absent. On non-mac platforms this is a stub returning ""
// until those platforms grow a real channel source.
std::string ReadChannelNameFromBundle();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_CHANNEL_H_
```

- [ ] **Step 2: 写失败的单测 `src/common/teleport_channel_unittest.cc`**

```cpp
#include "teleport/common/teleport_channel.h"

#include "components/version_info/channel.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportChannelTest, MapsCanaryToCanary) {
  EXPECT_EQ(version_info::Channel::CANARY, ChannelFromName("canary"));
}
TEST(TeleportChannelTest, MapsBetaToBeta) {
  EXPECT_EQ(version_info::Channel::BETA, ChannelFromName("beta"));
}
TEST(TeleportChannelTest, MapsStableToStable) {
  EXPECT_EQ(version_info::Channel::STABLE, ChannelFromName("stable"));
}
TEST(TeleportChannelTest, MapsEmptyToUnknown) {
  EXPECT_EQ(version_info::Channel::UNKNOWN, ChannelFromName(""));
}
TEST(TeleportChannelTest, MapsDevToUnknown) {
  EXPECT_EQ(version_info::Channel::UNKNOWN, ChannelFromName("dev"));
}
TEST(TeleportChannelTest, MapsGarbageToUnknown) {
  EXPECT_EQ(version_info::Channel::UNKNOWN, ChannelFromName("nonsense"));
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 3: 创建 `src/common/teleport_channel.cc`(先写 STUB,制造 red)**

```cpp
#include "teleport/common/teleport_channel.h"

#include "build/build_config.h"

namespace teleport {

version_info::Channel ChannelFromName(std::string_view name) {
  // STUB: implemented in a later step. Always UNKNOWN for now (red).
  return version_info::Channel::UNKNOWN;
}

#if !BUILDFLAG(IS_MAC)
// Non-mac platforms are a later phase; until they have a real channel source,
// report no channel (-> UNKNOWN) rather than guessing.
std::string ReadChannelNameFromBundle() {
  return std::string();
}
#endif

}  // namespace teleport
```

- [ ] **Step 4: 创建 `src/common/teleport_channel_mac.mm`**

```cpp
#include "teleport/common/teleport_channel.h"

#import <Foundation/Foundation.h>

#include "base/strings/sys_string_conversions.h"

namespace teleport {

std::string ReadChannelNameFromBundle() {
  NSString* channel = [[NSBundle mainBundle]
      objectForInfoDictionaryKey:@"TeleportChannel"];
  return channel ? base::SysNSStringToUTF8(channel) : std::string();
}

}  // namespace teleport
```

- [ ] **Step 5: 接进 `src/BUILD.gn`**

在 `source_set("teleport")` 的 `sources`(当前 `teleport_version.cc`/`.h` 之后,见 `src/BUILD.gn:25-26`)加:

```gn
    "common/teleport_channel.cc",
    "common/teleport_channel.h",
```

在 `if (is_mac) {` 块内、`sources += [ "common/teleport_version_mac.mm" ]`(`src/BUILD.gn:39`)之后加:

```gn
    sources += [ "common/teleport_channel_mac.mm" ]
```

在 `test("teleport_unittests")` 的 `sources`(`src/BUILD.gn:64-69`)加:

```gn
    "common/teleport_channel_unittest.cc",
```

把 `source_set("teleport")` 的 `deps`(`src/BUILD.gn:28-33`)中的 `//components/version_info` **移到 `public_deps`**——因为公共头 `teleport_channel.h` 直接 `#include "components/version_info/channel.h"`,需经 `public_deps` 把该 include 路径传给依赖者(本单测即依赖者)。改为:

```gn
  public_deps = [ "//components/version_info" ]
  deps = [
    "//base",
    "//content/public/common",
    "//url",
  ]
```

- [ ] **Step 6: 构建并运行单测,确认 RED**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportChannelTest.*'
```
Expected: 编译链接通过,但 `MapsCanaryToCanary`/`MapsBetaToBeta`/`MapsStableToStable` 三例 **FAIL**(实际 UNKNOWN);三个 Unknown 例通过。

- [ ] **Step 7: 实现真正映射(GREEN)——替换 `src/common/teleport_channel.cc` 的 `ChannelFromName`**

把 Step 3 的 STUB 函数体替换为:

```cpp
version_info::Channel ChannelFromName(std::string_view name) {
  if (name == "canary")
    return version_info::Channel::CANARY;
  if (name == "beta")
    return version_info::Channel::BETA;
  if (name == "stable")
    return version_info::Channel::STABLE;
  return version_info::Channel::UNKNOWN;
}
```

- [ ] **Step 8: 重新构建运行,确认 GREEN**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportChannelTest.*'
```
Expected: 6 例全部 **PASS**。

- [ ] **Step 9: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add src/common/teleport_channel.h src/common/teleport_channel.cc \
        src/common/teleport_channel_mac.mm src/common/teleport_channel_unittest.cc src/BUILD.gn
git commit -m "feat(channel): overlay TeleportChannel -> version_info::Channel resolver"
```

---

## Task 2: 把运行期通道接进 `channel_info_mac.mm`(上游补丁)

**Files:**
- Create: `patches/chrome/common/channel_info_mac.mm.patch`
- Modify: `patches/chrome/common/BUILD.gn.patch`(追加一处 hunk:给 `source_set("channel_info")` 加 `//teleport` dep——因为 `channel_info_mac.mm` 不在已加 dep 的 `common_lib` 里,而在 `channel_info` source_set 里;否则新 include 会在 Task 9 全量构建时才报找不到头)
- (临时编辑) `$TELEPORT_CHROMIUM_DIR/src/chrome/common/channel_info_mac.mm` 与 `$TELEPORT_CHROMIUM_DIR/src/chrome/common/BUILD.gn`

> 补丁生成法:直接编辑 chromium 检出里的文件 → `git diff` 导出补丁 → `git checkout` 还原 → `apply_patches.py` 重新应用以验证。一文件一 patch,镜像上游路径。注意 chromium 工作树里既有补丁已处于「已应用」状态,故 `BUILD.gn` 的 `git diff` 会同时包含既有的 `common_lib` 改动与本次新增的 `channel_info` 改动(2 个 hunk),这是预期的。

- [ ] **Step 1: 编辑 `chrome/common/channel_info_mac.mm` —— 加 include**

文件:`$TELEPORT_CHROMIUM_DIR/src/chrome/common/channel_info_mac.mm`。在 `#include "components/version_info/version_info.h"`(第 16 行)之后插入一行:

```cpp
#include "teleport/common/teleport_channel.h"
```

- [ ] **Step 2: 编辑同文件 —— 非品牌 `GetChannelState()` 读 bundle 键**

> 注意 `ChannelState{"", false}` 在文件中出现多次(品牌 `ParseChannelId` 内亦有),必须连同 `#if/#else/#endif` 上下文一起匹配以唯一定位。把 `GetChannelState()` 里的这整段:

```cpp
#if BUILDFLAG(GOOGLE_CHROME_BRANDING)
    return DetermineChannelState();
#else
    return ChannelState{"", false};
#endif
```

改为:

```cpp
#if BUILDFLAG(GOOGLE_CHROME_BRANDING)
    return DetermineChannelState();
#else
    // teleport overlay: unbranded builds carry their distribution channel in
    // the TeleportChannel Info.plist key (stamped at packaging).
    return ChannelState{teleport::ReadChannelNameFromBundle(), false};
#endif
```

- [ ] **Step 3: 编辑同文件 —— 非品牌 `GetChannelByName()` 落点经 teleport 解析**

把 `GetChannelByName()` 末尾这整段(`#endif` + 返回 + 右花括号,唯一):

```cpp
#endif
  return version_info::Channel::UNKNOWN;
}
```

改为:

```cpp
#endif
  // teleport overlay: unbranded path parses our canary/beta/stable names; any
  // other value (incl. empty / unstamped) -> UNKNOWN.
  return teleport::ChannelFromName(channel);
}
```

- [ ] **Step 3b: 编辑 `chrome/common/BUILD.gn` —— 给 `channel_info` target 加 `//teleport` dep**

文件:`$TELEPORT_CHROMIUM_DIR/src/chrome/common/BUILD.gn`。在 `source_set("channel_info")` 里把:

```gn
  deps = [ "//build:branding_buildflags" ]
```

改为:

```gn
  deps = [
    "//build:branding_buildflags",
    "//teleport",
  ]
```

> 该 target 的 sources 在 mac 下含 `channel_info_mac.mm`,加 dep 后其编译单元才能解析 `#include "teleport/common/teleport_channel.h"`。

- [ ] **Step 4: 导出两个补丁文件**

Run:
```bash
CA=/Users/liulichao/workspace/teleport-channel-alignment
git -C "$TELEPORT_CHROMIUM_DIR/src" diff -- chrome/common/channel_info_mac.mm \
  > "$CA/patches/chrome/common/channel_info_mac.mm.patch"
git -C "$TELEPORT_CHROMIUM_DIR/src" diff -- chrome/common/BUILD.gn \
  > "$CA/patches/chrome/common/BUILD.gn.patch"
```
Expected:`channel_info_mac.mm.patch` 含 3 处新增(include + 两处 `return`);`BUILD.gn.patch` 含 **2 个 hunk**(既有 `common_lib` 的 `//teleport` + 新增 `channel_info` 的 `//teleport`)。检查:
```bash
grep -c '+    "//teleport",' "$CA/patches/chrome/common/BUILD.gn.patch"
```
Expected: `2`。

- [ ] **Step 5: 还原 chromium 文件,再用 apply_patches 验证补丁可应用**

Run:
```bash
git -C "$TELEPORT_CHROMIUM_DIR/src" checkout -- chrome/common/channel_info_mac.mm chrome/common/BUILD.gn
cd /Users/liulichao/workspace/teleport-channel-alignment
uv run python scripts/apply_patches.py
```
Expected: 退出码 0,无 "FAILED"/冲突;两文件重新带上我们的改动。

- [ ] **Step 6: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add patches/chrome/common/channel_info_mac.mm.patch patches/chrome/common/BUILD.gn.patch
git commit -m "feat(channel): route unbranded channel_info_mac through teleport resolver"
```

> 端到端验证(`chrome` 全量构建 + chrome://version 通道行)在 Task 9 统一做(数小时)。

---

## Task 3: 钉死字段试验(GN args)

**Files:**
- Modify: `src/gn/args/release.mac.gn`
- Modify: `src/gn/args/dev.mac.gn`

- [ ] **Step 1: `src/gn/args/release.mac.gn` 末尾追加**

在文件末尾(`src/gn/args/release.mac.gn:36` 之后)追加:

```gn

# Pin every base::Feature to its compiled default: disable the compiled-in
# fieldtrial_testing_config (the only field-trial source for an unbranded build,
# which fetches no variations seed). Keeps distributed channels free of
# unexpected experiments. Independent of channel (channel only filters seed
# studies, of which we have none).
disable_fieldtrial_testing_config = true
```

- [ ] **Step 2: `src/gn/args/dev.mac.gn` 末尾追加**

在文件末尾(`src/gn/args/dev.mac.gn:39` 之后)追加:

```gn

# Pin every base::Feature to its compiled default (see release.mac.gn). Also
# permanently fixes the UsePersistentCacheForCodeCache renderer abort: dev runs
# no longer need --disable-field-trial-config (passing it becomes a no-op).
disable_fieldtrial_testing_config = true
```

- [ ] **Step 3: 验证 dev out 仍能 gn gen(GN arg 被识别)**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
```
Expected: 成功,无 "Unknown variable disable_fieldtrial_testing_config" 报错。

- [ ] **Step 4: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add src/gn/args/release.mac.gn src/gn/args/dev.mac.gn
git commit -m "build: pin field trials to compiled defaults (disable testing config)"
```

---

## Task 4: 改名 `dogfood`→`canary`(渠道注册表 + 配置 + pytest)

**Files:**
- Modify: `scripts/_build.py:23-29`
- Modify: `scripts/release_config.local.toml.example:15-23`
- Modify: `scripts/tests/test_build.py`
- Modify: `scripts/tests/test_config.py`
- Modify: `scripts/tests/test_package_cli.py`

- [ ] **Step 1: 先改 pytest,确认 RED**

`scripts/tests/test_build.py`:把 `test_resolve_dogfood`(第 14-18 行)整段替换为:

```python
def test_resolve_canary():
    ch = _build.resolve_channel("canary")
    assert ch.name == "canary"
    assert ch.distributable is True
    assert ch.out == "out/mac/arm64/release"
    assert ch.targets == ("chrome", "chrome/installer/mac")
```

`scripts/tests/test_build.py`:`test_build_runs_autoninja`(第 31 行)`resolve_channel("dogfood")` → `resolve_channel("canary")`。

`scripts/tests/test_config.py`:把所有 `dogfood` 改为 `canary`——`_NESTED` 里 `[channel.dogfood]`(第 9 行)→`[channel.canary]`;`load_channel_config(p, "dogfood")`(第 20、36、42 行)→`"canary"`;第 41 行内联 `[channel.dogfood]`→`[channel.canary]`。

`scripts/tests/test_package_cli.py`:第 95、113、125 行 `--channel dogfood` → `--channel canary`;第 107 行 `"published 1.2.3 (dogfood)"` → `"published 1.2.3 (canary)"`;第 121 行函数名 `test_dogfood_distribute_dry_run_has_no_side_effects` → `test_canary_distribute_dry_run_has_no_side_effects`;`_stub_distributable` docstring(第 56 行)`dogfood`→`canary`;第 64 行 `download_base_url`/第 65 不必改值,但把 `oss_upload_target`/`download_base_url` 里若含 `dogfood` 的无(当前是 `oss://b/x/`,无需改)。

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
uv run pytest scripts/tests/test_build.py scripts/tests/test_config.py scripts/tests/test_package_cli.py -q
```
Expected: **FAIL**(`resolve_channel("canary")` 抛 unknown channel 等)。

- [ ] **Step 2: 改渠道注册表 `scripts/_build.py`**

把 `CHANNELS`(第 23-29 行)中的 dogfood 项:

```python
    "dogfood": Channel(
        "dogfood", "out/mac/arm64/release", True,
        ("chrome", "chrome/installer/mac"),
    ),
```

改为:

```python
    "canary": Channel(
        "canary", "out/mac/arm64/release", True,
        ("chrome", "chrome/installer/mac"),
    ),
```

- [ ] **Step 3: 改配置样例 `scripts/release_config.local.toml.example`**

第 15 行 `[channel.dogfood]` → `[channel.canary]`;第 19/21/23 行 URL 路径段 `/dogfood/` → `/canary/`:

```toml
[channel.canary]
# Sparkle public EdDSA key (base64) printed by generate_keys.
public_ed_key = "PASTE_BASE64_PUBLIC_KEY"
# Appcast feed URL (public https; the OSS native endpoint + unguessable token).
feed_url = "https://<bucket>.oss-cn-<region>.aliyuncs.com/canary/<token>/appcast.xml"
# Public https base the appcast download links + SUFeedURL point at (trailing /).
download_base_url = "https://<bucket>.oss-cn-<region>.aliyuncs.com/canary/<token>/"
# OSS path the dmg + appcast are uploaded to via ossutil (trailing /).
oss_upload_target = "oss://<bucket>/canary/<token>/"
```

- [ ] **Step 4: 跑 pytest 确认 GREEN**

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
uv run pytest scripts/tests/test_build.py scripts/tests/test_config.py scripts/tests/test_package_cli.py -q
```
Expected: 全部 **PASS**。

- [ ] **Step 5: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add scripts/_build.py scripts/release_config.local.toml.example \
        scripts/tests/test_build.py scripts/tests/test_config.py scripts/tests/test_package_cli.py
git commit -m "refactor(channel): rename dogfood channel to canary (registry, config, tests)"
```

---

## Task 5: 打包期 stamp `TeleportChannel` 键(Python,TDD)

**Files:**
- Create: `scripts/tests/test_package.py`
- Modify: `scripts/_package.py:66-84`
- Modify: `scripts/package.py:96`
- Modify: `scripts/tests/test_package_cli.py`(stub 增参 + 断言通道值)

> 依赖 Task 4:`channel.name` 现为 `"canary"`,即 stamp 的值。

- [ ] **Step 1: 写失败单测 `scripts/tests/test_package.py`**

```python
import _package


def test_sparkle_plist_string_keys_includes_channel_marker():
    cfg = {"feed_url": "https://h/appcast.xml", "public_ed_key": "k"}
    keys = _package.sparkle_plist_string_keys("0.1.5", cfg, "canary")
    assert keys["TeleportChannel"] == "canary"
    assert keys["CFBundleShortVersionString"] == "0.1.5"
    assert keys["CFBundleVersion"] == "0.1.5"
    assert keys["SUFeedURL"] == "https://h/appcast.xml"
    assert keys["SUPublicEDKey"] == "k"
```

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
uv run pytest scripts/tests/test_package.py -q
```
Expected: **FAIL**(`AttributeError: module '_package' has no attribute 'sparkle_plist_string_keys'`)。

- [ ] **Step 2: 重构 `scripts/_package.py` —— 抽纯函数 + stamp 通道键**

把 `stamp_and_inject`(当前第 66-84 行)整段替换为(新增纯函数 + 4 参签名 + `TeleportChannel`):

```python
def sparkle_plist_string_keys(version: str, cfg: dict, channel_name: str) -> dict[str, str]:
    """The string-valued Info.plist keys stamped for a distributable channel:
    version fields, the Sparkle feed/key, and the TeleportChannel marker that
    drives chrome::GetChannel() at runtime."""
    return {
        **version_plist_keys(version),
        "SUFeedURL": cfg["feed_url"],
        "SUPublicEDKey": cfg["public_ed_key"],
        "TeleportChannel": channel_name,
    }


def stamp_and_inject(app: Path, version: str, cfg: dict, channel_name: str) -> None:
    """Stamp version + Sparkle keys + the TeleportChannel marker into the app's
    Info.plist (pre-sign)."""
    info = app / "Contents" / "Info.plist"
    for key, val in sparkle_plist_string_keys(version, cfg, channel_name).items():
        subprocess.run(["plutil", "-replace", key, "-string", val, str(info)], check=True)
    subprocess.run(
        ["plutil", "-replace", "SUEnableAutomaticChecks", "-bool", "YES", str(info)],
        check=True,
    )
    subprocess.run(
        ["plutil", "-replace", "SUScheduledCheckInterval", "-integer",
         str(_CHECK_INTERVAL_SECONDS), str(info)],
        check=True,
    )
```

- [ ] **Step 3: 跑单测确认 GREEN**

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
uv run pytest scripts/tests/test_package.py -q
```
Expected: **PASS**。

- [ ] **Step 4: 更新调用点 `scripts/package.py:96`**

把:

```python
    _package.stamp_and_inject(app, version, cfg)
```

改为:

```python
    _package.stamp_and_inject(app, version, cfg, channel.name)
```

- [ ] **Step 5: 更新 CLI 测试 stub 增参 + 断言通道值**

`scripts/tests/test_package_cli.py` 的 `_stub_distributable`,把 `stamp_and_inject` 的 stub(当前第 68-69 行)替换为:

```python
    monkeypatch.setattr(package._package, "stamp_and_inject",
                        lambda app, v, c, ch: order.append(("stamp", v, ch)))
```

在 `test_distribute_runs_guards_before_build_and_tags_after_upload`(第 92 行起)的断言区加一行,验证通道名被透传:

```python
    assert ("stamp", "1.2.3", "canary") in order
```

> 注:`names.index("stamp")` 仍可用,因元组首元素 `"stamp"` 不变。

- [ ] **Step 6: 跑全量 pytest 确认 GREEN**

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
uv run pytest -q
```
Expected: 全部 **PASS**。

- [ ] **Step 7: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add scripts/_package.py scripts/package.py scripts/tests/test_package.py scripts/tests/test_package_cli.py
git commit -m "feat(channel): stamp TeleportChannel into Info.plist at packaging"
```

---

## Task 6: 改名 `dogfood`→`canary`(注释 / docstring / overlay 测试夹具)

**Files:**
- Modify: `scripts/_package.py:15-16`
- Modify: `scripts/dmg_settings.py:1`、`scripts/dmg_layout.py:1`、`scripts/gen_dmg_background.py:2`、`scripts/preview_dmg_window.py:2`
- Modify: `src/gn/args/release.mac.gn:3-4,13`
- Modify: `src/common/teleport_feed_url_unittest.cc:9`

- [ ] **Step 1: 改各处注释/docstring 中的 "dogfood" 字样为 "canary"**

逐文件把 docstring/注释里的 `dogfood` 改为 `canary`(纯文字,无逻辑):
- `scripts/_package.py:15` 注释 `# dogfood checks for updates hourly ...` → `# canary checks for updates hourly ...`
- `scripts/dmg_settings.py:1` `"""dmgbuild settings for the Teleport dogfood disk image.` → `... Teleport canary disk image.`
- `scripts/dmg_layout.py:1` `"""Single source of truth for the dogfood dmg window geometry & colors.` → `... the canary dmg window ...`
- `scripts/gen_dmg_background.py:2` `"""Generate the dogfood dmg background image ...` → `... the canary dmg background image ...`
- `scripts/preview_dmg_window.py:2` `"""Assemble a preview of the dogfood dmg window for visual QA.` → `... the canary dmg window ...`
- `src/gn/args/release.mac.gn:3-4`:把注释中 `see the dogfood channel spec §3.4.` → `see the canary channel spec §3.4.`;`src/gn/args/release.mac.gn:13` `so dogfood runtime perf tracks ...` → `so canary runtime perf tracks ...`

- [ ] **Step 2: 改 overlay 测试夹具 `src/common/teleport_feed_url_unittest.cc:9`**

```cpp
  EXPECT_TRUE(IsSecureFeedUrl("https://example.com/canary/tok/appcast.xml"));
```

- [ ] **Step 3: 跑 pytest + 编译运行 overlay 单测,确认无回归**

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment && uv run pytest -q
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportFeedUrlTest.*:TeleportChannelTest.*'
```
Expected: pytest 全绿;gtest 相关用例 PASS。

- [ ] **Step 4: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add scripts/_package.py scripts/dmg_settings.py scripts/dmg_layout.py \
        scripts/gen_dmg_background.py scripts/preview_dmg_window.py \
        src/gn/args/release.mac.gn src/common/teleport_feed_url_unittest.cc
git commit -m "docs(channel): rename dogfood->canary in comments and test fixtures"
```

---

## Task 7: 改名 `dogfood`→`canary`(文档,含历史 spec/plan + CLAUDE.md)

用户要求历史文档也当「活文档」处理 → 不仅改正文,**含 `dogfood` 的文件名也一并重命名**,并修正全仓库对这些文件名的交叉引用,使除「解释本次改名的新 spec/plan」外不留任何 `dogfood`。

**Files:**
- Rename (git mv): `docs/dogfood-install.md` → `docs/canary-install.md`
- Rename (git mv): `docs/superpowers/specs/2026-05-26-macos-dogfood-channel-design.md` → `docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`
- Rename (git mv): `docs/superpowers/plans/2026-05-26-macos-dogfood-channel.md` → `docs/superpowers/plans/2026-05-26-macos-canary-channel.md`
- Modify: `CLAUDE.md` + 所有含 `dogfood` 的 `docs/superpowers/specs/*`、`docs/superpowers/plans/*`
- Update: 全仓库对上述被重命名文件名的交叉引用(含本特性的新 2026-05-30 spec/plan 里的路径引用)

- [ ] **Step 1: 三个 git mv**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git mv docs/dogfood-install.md docs/canary-install.md
git mv docs/superpowers/specs/2026-05-26-macos-dogfood-channel-design.md \
       docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md
git mv docs/superpowers/plans/2026-05-26-macos-dogfood-channel.md \
       docs/superpowers/plans/2026-05-26-macos-canary-channel.md
```

- [ ] **Step 2: 全文替换 `dogfood`→`canary`(正文 + 文件名引用)**

规则:
1. 在 `CLAUDE.md` 及所有 `docs/superpowers/specs/*`、`docs/superpowers/plans/*`(以及刚重命名的 `docs/canary-install.md`)中,把**散文里的 `dogfood` 一律改为 `canary`**——命令 `--channel dogfood`→`--channel canary`;路径段 `/dogfood/`→`/canary/`(含 install 指南第 8 行示例下载 URL);标题/措辞「macOS dogfood 通道包」→「macOS canary 通道包」等。
2. **文件名引用**:把任何指向被重命名文件的路径一并更新——`docs/dogfood-install.md`→`docs/canary-install.md`;`2026-05-26-macos-dogfood-channel-design.md`→`2026-05-26-macos-canary-channel-design.md`;`2026-05-26-macos-dogfood-channel.md`→`2026-05-26-macos-canary-channel.md`。这些引用散见于 `CLAUDE.md`、其它 spec/plan,以及**本特性的新文件** `docs/superpowers/specs/2026-05-30-channel-alignment-design.md`(其「关联」行)与 `docs/superpowers/plans/2026-05-30-channel-alignment.md`。
3. **唯一例外**:`docs/superpowers/specs/2026-05-30-channel-alignment-design.md` 与 `docs/superpowers/plans/2026-05-30-channel-alignment.md` 这两个新文件**散文中的 `dogfood`**(它们在描述「dogfood→canary 改名」「迁移旧 dogfood 装机」「删旧 `dogfood/` 前缀」)**保留不动**;**仅**更新它们里面对上面那些被重命名文件的**路径引用**。

定位辅助:
```bash
grep -rln "dogfood" --exclude-dir=chromium --exclude-dir=build --exclude-dir=.git docs CLAUDE.md
```

- [ ] **Step 3: 复查残留**

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
grep -rn "dogfood" --exclude-dir=chromium --exclude-dir=build --exclude-dir=.git \
  docs CLAUDE.md scripts src | grep -v "2026-05-30-channel-alignment"
```
Expected: **无输出**。(剩余的 `dogfood` 只允许出现在两个 `2026-05-30-channel-alignment` 文件的散文里,已被 `grep -v` 排除;若有其它命中——尤其旧文件名的残留引用——补改。)再单独确认那两个新文件里**没有**残留的旧文件名引用:
```bash
grep -rn "macos-dogfood-channel\|dogfood-install" docs/superpowers/specs/2026-05-30-channel-alignment-design.md \
  docs/superpowers/plans/2026-05-30-channel-alignment.md
```
Expected: **无输出**(路径引用已更新;只剩散文 `dogfood`)。

- [ ] **Step 4: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add -A docs CLAUDE.md
git commit -m "docs(channel): rename dogfood->canary across docs, filenames, and CLAUDE.md"
```

---

## Task 8: 更新冒烟清单 `scripts/smoke_check.md`

**Files:**
- Modify: `scripts/smoke_check.md`

- [ ] **Step 1: 加通道核对项 + 移除过时的 field-trial flag 注记**

编辑 `scripts/smoke_check.md`:
1. 在 canary 渠道包冒烟区(原 dogfood 区,已于 Task 7 改名)新增一行核对项:打开 `chrome://version`,确认 **「Channel」/通道行显示 `canary`**(而非空/`unknown`)。
2. 把「运行 dev 构建需加 `--disable-field-trial-config`」相关注记改为:**dev 构建已通过 GN `disable_fieldtrial_testing_config=true` 钉死,运行不再需要该 flag**。

- [ ] **Step 2: 提交**

```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
git add scripts/smoke_check.md
git commit -m "docs(smoke): add canary channel check; drop obsolete field-trial flag note"
```

---

## Task 9: 端到端构建 + 冒烟验证(手动,最终关)

> 全量 official 构建 + 打包数小时;为合并前最终验证,亦是发布前置。需 Developer ID 证书、notarytool profile、Sparkle 框架(`fetch_sparkle.py`)、本地 `release_config.local.toml` 已按 canary 更新。

- [ ] **Step 1: 应用补丁 + gen release out**

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment && uv run python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
```
Expected: 补丁干净应用;gn gen 成功。

- [ ] **Step 2: 本地打 canary 渠道包(构建+签名+公证+dmg,不发布)**

Run:
```bash
cd /Users/liulichao/workspace/teleport-channel-alignment
uv run python scripts/package.py --channel canary
```
Expected: 末尾打印 `built + signed canary dmg at … (not published)`。

- [ ] **Step 3: 验证 Info.plist 与运行期通道**

Run:
```bash
APP="$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/release/Teleport.app"
defaults read "$APP/Contents/Info" TeleportChannel
```
Expected: 输出 `canary`。

装上该 dmg 后打开 `chrome://version`:**通道行显示 `canary`**;检查升级提示徽标在检测到更新后约 1 小时档点亮(`IsUnstableChannel()` 路径,可结合 spec §1.1)。

- [ ] **Step 4: 全量 overlay 单测 + pytest 收尾**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests
cd /Users/liulichao/workspace/teleport-channel-alignment && uv run pytest -q
```
Expected: 全绿。

- [ ] **Step 5(可选,发布时):** 按 spec §6 执行发布——OSS 建 `canary/<token>/` 前缀+桶策略+RAM 权限;`TELEPORT_VERSION` 升 ≥`0.1.5`;`package.py --channel canary --distribute`;手动分发首个 canary 包给内部用户;全员迁移后删旧 `dogfood/`。

---

## 发布运行手册(手动,发布时执行,非合并前置)

见 spec `docs/superpowers/specs/2026-05-30-channel-alignment-design.md` §6。要点:① 阿里云 OSS 在桶 `fairyland-distribution` 建 `canary/<token>/` 前缀 + 匿名 `oss:GetObject` 桶策略 + RAM 用户 `oss:PutObject`;② `TELEPORT_VERSION` 升到 ≥ `0.1.5`(`v0.1.4` tag 已存在);③ 首个 canary 包手动分发(同 bundle ID 原地替换旧 dogfood 装机),其 `SUFeedURL` 指向新 feed → 之后自动升级;④ 全员迁移后删旧 `dogfood/` 对象与桶策略。
