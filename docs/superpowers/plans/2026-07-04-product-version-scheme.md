# 产品版本方案实现计划(TD-014:以 TELEPORT_VERSION 替换 chrome/VERSION)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建期用四段 `TELEPORT_VERSION` 生成 `chrome/VERSION`,使框架目录/全部 plist/内嵌路径只呈现产品版本;UA/UA-CH 经生成的引擎版本头保持 Chromium 版本;打包链删 stamp 改断言。

**Architecture:** 新模块 `scripts/generate_version.py` 被 `apply_patches.py` 前置调用,内容比较跳过写入(避免无谓全量重编);5 个上游文件 patch(UA×3、tweak_info_plist、DM agent);`//teleport` 的 `teleport_version` 简化为 `version_info` + `IsOfficialBuild()`。规格见 `docs/superpowers/specs/2026-07-04-product-version-scheme-design.md`。

**Tech Stack:** Python 3.13(uv + pytest)、GN/autoninja(Siso)、gtest、git patch 工作流(one-file-one-patch)。

## Global Constraints(每个任务隐含遵守)

- 仓库根:`/Users/liulichao/workspace/teleport`;本计划在 worktree `/Users/liulichao/workspace/teleport/.claude/worktrees/product-version-scheme`(分支 `worktree-product-version-scheme`)实施,以下称 `$WT`。
- chromium 检出共享主仓:每个 shell 会话先 `export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`(worktree 内无 `chromium/`,不 export 会落到假路径)。
- **一文件一 patch**:patch 文件名镜像 `chromium/src` 下路径;修改已有 patch 的流程 = 确保已应用 → 直接编辑检出文件 → `git -C $TELEPORT_CHROMIUM_DIR/src diff -- <path> > $WT/patches/<path>.patch` 重生成 → 重跑 `apply_patches.py` 验证幂等。禁止手改 hunk。
- pytest 一律在 `$WT` 根运行:`cd $WT && uv run pytest -q`;gtest:`autoninja -C out/mac/arm64/dev teleport_unittests && "$TELEPORT_CHROMIUM_DIR"/src/out/mac/arm64/dev/teleport_unittests`。
- 构建命令一律 `cd "$TELEPORT_CHROMIUM_DIR/src"` 后执行;dev 产物在 `out/mac/arm64/dev/Teleport.app`。
- 不许跳过/禁用任何测试;每任务以提交(英文 commit message)收尾。
- Markdown 中文;代码/注释/提交信息英文。
- 当前值:`TELEPORT_VERSION` = `0.1.12`(任务 5 改为 `0.1.12.0`);`CHROMIUM_VERSION` = `148.0.7778.180`。

---

### Task 1: worktree 构建接线

**Files:** 无代码改动(环境准备)。

**Interfaces:**
- Produces: 检出的 `src/teleport` 符号链接指向 worktree 的 `src/`,后续所有构建/patch 操作作用于 worktree 内容。

- [ ] **Step 1: 重指符号链接并验证**

```bash
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
WT=/Users/liulichao/workspace/teleport/.claude/worktrees/product-version-scheme
ln -sfn "$WT/src" "$TELEPORT_CHROMIUM_DIR/src/teleport"
readlink "$TELEPORT_CHROMIUM_DIR/src/teleport"
```

Expected: 输出 `$WT/src` 路径。

- [ ] **Step 2: 基线健康检查(overlay 应用 + 两套测试全绿)**

```bash
cd "$WT" && python scripts/apply_patches.py && uv run pytest -q
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && out/mac/arm64/dev/teleport_unittests
```

Expected: `overlay applied.`;pytest `178 passed`;gtest `SUCCESS: all tests passed.`

---

### Task 2: `scripts/generate_version.py` 模块(TDD)

**Files:**
- Create: `scripts/generate_version.py`
- Test: `scripts/tests/test_generate_version.py`

**Interfaces:**
- Consumes: `_lib.repo_root()`、`_lib.chromium_src(root)`(既有)。
- Produces(后续任务依赖的精确签名):
  - `parse_product_version(text: str) -> tuple[int, int, int, int]`(四段严格校验,拒绝三段)
  - `chrome_version_content(v: tuple[int,int,int,int]) -> str`
  - `parse_engine_version(text: str) -> str`、`engine_header_content(engine_version: str) -> str`
  - `write_chrome_version(root: Path | None = None) -> bool`、`write_engine_header(root: Path | None = None) -> bool`(返回是否发生写入;**内容相同必须跳过写**——`chrome/VERSION` 是几乎全部目标的输入,mtime 无谓变化会触发全量重编)

- [ ] **Step 1: 写失败测试**

`scripts/tests/test_generate_version.py`:

```python
import pytest

import generate_version as gv


def test_parse_product_version_four_segments():
    assert gv.parse_product_version("0.1.12.0\n") == (0, 1, 12, 0)
    assert gv.parse_product_version(" 1.2.3.4 ") == (1, 2, 3, 4)


@pytest.mark.parametrize("bad", ["0.1.12", "1.2", "1.2.3.4.5", "v1.2.3.0", "", "a.b.c.d"])
def test_parse_product_version_rejects(bad):
    with pytest.raises(ValueError):
        gv.parse_product_version(bad)


def test_chrome_version_content_format():
    assert (gv.chrome_version_content((0, 1, 12, 0))
            == "MAJOR=0\nMINOR=1\nBUILD=12\nPATCH=0\n")


def test_parse_engine_version_ok_and_reject():
    assert gv.parse_engine_version("148.0.7778.180\n") == "148.0.7778.180"
    with pytest.raises(ValueError):
        gv.parse_engine_version("148.0")


def test_engine_header_content_macros():
    h = gv.engine_header_content("148.0.7778.180")
    assert '#define TELEPORT_ENGINE_VERSION_STRING "148.0.7778.180"' in h
    assert '#define TELEPORT_ENGINE_VERSION_MAJOR "148"' in h
    assert h.startswith("//")  # generated-file banner
    assert "#ifndef COMPONENTS_VERSION_INFO_TELEPORT_ENGINE_VERSION_H_" in h


def _fake_root(tmp_path, monkeypatch, teleport="0.1.12.0\n", chromium="148.0.7778.180\n"):
    # chromium_src() prefers $TELEPORT_CHROMIUM_DIR; neutralize it for hermetic tests.
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    (tmp_path / "TELEPORT_VERSION").write_text(teleport)
    (tmp_path / "CHROMIUM_VERSION").write_text(chromium)
    (tmp_path / "chromium" / "src" / "chrome").mkdir(parents=True)
    (tmp_path / "chromium" / "src" / "components" / "version_info").mkdir(parents=True)
    return tmp_path


def test_write_chrome_version_writes_then_skips(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch)
    target = root / "chromium" / "src" / "chrome" / "VERSION"
    assert gv.write_chrome_version(root) is True
    assert target.read_text() == "MAJOR=0\nMINOR=1\nBUILD=12\nPATCH=0\n"
    mtime = target.stat().st_mtime_ns
    assert gv.write_chrome_version(root) is False   # unchanged -> no write
    assert target.stat().st_mtime_ns == mtime        # mtime untouched


def test_write_engine_header_writes_then_skips(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch)
    target = (root / "chromium" / "src" / "components" / "version_info"
              / "teleport_engine_version.h")
    assert gv.write_engine_header(root) is True
    assert 'TELEPORT_ENGINE_VERSION_STRING "148.0.7778.180"' in target.read_text()
    assert gv.write_engine_header(root) is False


def test_write_chrome_version_rejects_three_segment_file(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch, teleport="0.1.12\n")
    with pytest.raises(ValueError):
        gv.write_chrome_version(root)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd $WT && uv run pytest scripts/tests/test_generate_version.py -q`
Expected: FAIL/ERROR(`ModuleNotFoundError: generate_version`)

- [ ] **Step 3: 最小实现**

`scripts/generate_version.py`:

```python
"""Generate version artifacts into the chromium checkout from repo version files.

- chrome/VERSION  <- TELEPORT_VERSION (4-segment product version): makes every
  build-time version derivative (framework Versions/ dir, all bundle plists,
  CHROME_VERSION_STRING) the PRODUCT version.
- components/version_info/teleport_engine_version.h  <- CHROMIUM_VERSION: the
  pinned upstream engine version, consumed ONLY by the UA / UA-CH patches.

Writes are content-compared and skipped when unchanged: chrome/VERSION is an
input of nearly every target, so a gratuitous mtime bump would trigger a full
rebuild on each apply_patches run.
"""
from __future__ import annotations

import re
from pathlib import Path

from _lib import chromium_src, repo_root

_FOUR_SEG_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)$")

_CHROME_VERSION_REL = Path("chrome") / "VERSION"
_ENGINE_HEADER_REL = (
    Path("components") / "version_info" / "teleport_engine_version.h")


def parse_product_version(text: str) -> tuple[int, int, int, int]:
    """Parse the 4-segment TELEPORT_VERSION. Raises ValueError on anything else
    (including legacy 3-segment values: the file must be migrated, not guessed)."""
    m = _FOUR_SEG_RE.match(text.strip())
    if not m:
        raise ValueError(
            f"TELEPORT_VERSION must be 4-segment MAJOR.MINOR.BUILD.PATCH, got {text!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))


def chrome_version_content(v: tuple[int, int, int, int]) -> str:
    major, minor, build, patch = v
    return f"MAJOR={major}\nMINOR={minor}\nBUILD={build}\nPATCH={patch}\n"


def parse_engine_version(text: str) -> str:
    """Validate CHROMIUM_VERSION as a 4-segment dotted string; return it stripped."""
    s = text.strip()
    if not _FOUR_SEG_RE.match(s):
        raise ValueError(f"CHROMIUM_VERSION must be 4-segment, got {text!r}")
    return s


def engine_header_content(engine_version: str) -> str:
    major = engine_version.split(".")[0]
    return (
        "// Generated by scripts/generate_version.py from CHROMIUM_VERSION.\n"
        "// Pinned upstream engine version: consumed ONLY by the UA / UA-CH\n"
        "// surface (web compat). Product versioning lives in chrome/VERSION.\n"
        "#ifndef COMPONENTS_VERSION_INFO_TELEPORT_ENGINE_VERSION_H_\n"
        "#define COMPONENTS_VERSION_INFO_TELEPORT_ENGINE_VERSION_H_\n"
        f'#define TELEPORT_ENGINE_VERSION_STRING "{engine_version}"\n'
        f'#define TELEPORT_ENGINE_VERSION_MAJOR "{major}"\n'
        "#endif  // COMPONENTS_VERSION_INFO_TELEPORT_ENGINE_VERSION_H_\n"
    )


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def write_chrome_version(root: Path | None = None) -> bool:
    root = root or repo_root()
    v = parse_product_version((root / "TELEPORT_VERSION").read_text())
    return _write_if_changed(
        chromium_src(root) / _CHROME_VERSION_REL, chrome_version_content(v))


def write_engine_header(root: Path | None = None) -> bool:
    root = root or repo_root()
    engine = parse_engine_version((root / "CHROMIUM_VERSION").read_text())
    return _write_if_changed(
        chromium_src(root) / _ENGINE_HEADER_REL, engine_header_content(engine))
```

- [ ] **Step 4: 运行确认通过**

Run: `cd $WT && uv run pytest scripts/tests/test_generate_version.py -q`
Expected: `9 passed`

- [ ] **Step 5: 提交**

```bash
cd $WT && git add scripts/generate_version.py scripts/tests/test_generate_version.py
git commit -m "feat(version): generate_version module — chrome/VERSION + engine header from repo version files"
```

---

### Task 3: apply_patches 接入引擎头生成(暂不接 VERSION)

**Files:**
- Modify: `scripts/apply_patches.py:82-84`(`branding_strings` 调用附近)

**Interfaces:**
- Consumes: `generate_version.write_engine_header()`(Task 2)。
- Produces: 每次 overlay 运行后,检出存在 `components/version_info/teleport_engine_version.h`(Task 4 的 patch 依赖它编译)。`write_chrome_version` **本任务不接**——UA patch(Task 4)落地前翻转 VERSION 会使 UA 变 `Chrome/0.0.0.0`,任务间保持可构建。

- [ ] **Step 1: 修改 `apply_patches.py` 的 `main()`**

将:

```python
    import branding_strings
    branding_strings.main()
    print("overlay applied.")
```

改为:

```python
    import branding_strings
    branding_strings.main()
    import generate_version
    if generate_version.write_engine_header(args.root):
        print("engine version header written")
    print("overlay applied.")
```

- [ ] **Step 2: 运行验证生成物与幂等**

```bash
cd $WT && python scripts/apply_patches.py | tail -3
cat "$TELEPORT_CHROMIUM_DIR/src/components/version_info/teleport_engine_version.h"
python scripts/apply_patches.py | grep -c "engine version header written" || echo "second run: skipped (idempotent)"
uv run pytest -q
```

Expected: 首跑出现 `engine version header written`;头文件含 `TELEPORT_ENGINE_VERSION_STRING "148.0.7778.180"`;二跑无该行(内容未变跳过);pytest 全绿。

- [ ] **Step 3: 提交**

```bash
cd $WT && git add scripts/apply_patches.py
git commit -m "feat(version): apply_patches generates the engine version header"
```

---

### Task 4: UA / UA-CH 三个 patch(引擎版本)

**Files:**
- Create: `patches/components/version_info/version_info_with_user_agent.h.patch`
- Create: `patches/components/version_info/version_info_with_user_agent.cc.patch`
- Create: `patches/components/embedder_support/user_agent_utils.cc.patch`

**Interfaces:**
- Consumes: `TELEPORT_ENGINE_VERSION_STRING` / `TELEPORT_ENGINE_VERSION_MAJOR`(Task 3 生成的头)。
- Produces: UA 全链路(完整 UA、reduced UA、UA-CH brands/full_version_list/full_version)钉在引擎版本;`chrome/VERSION` 翻转后(Task 5)UA 不变。

- [ ] **Step 1: 编辑检出 `components/version_info/version_info_with_user_agent.h`**

将:

```cpp
// Returns the product name and version information for the User-Agent header,
// in the format: Chrome/<major_version>.<minor_version>.<build>.<patch>.
constexpr std::string_view GetProductNameAndVersionForUserAgent() {
  return "Chrome/" PRODUCT_VERSION;
}
```

改为:

```cpp
// Returns the product name and version information for the User-Agent header,
// in the format: Chrome/<major_version>.<minor_version>.<build>.<patch>.
// Teleport: the UA must carry the pinned Chromium ENGINE version for web
// compatibility; PRODUCT_VERSION is Teleport's own product version.
constexpr std::string_view GetProductNameAndVersionForUserAgent() {
  return "Chrome/" TELEPORT_ENGINE_VERSION_STRING;
}
```

并在文件的 include 块(`#include "base/version_info/version_info_values.h"` 之后)加:

```cpp
#include "components/version_info/teleport_engine_version.h"
```

- [ ] **Step 2: 编辑检出 `components/version_info/version_info_with_user_agent.cc`**

将:

```cpp
std::string GetProductNameAndVersionForReducedUserAgent() {
  return base::StrCat({"Chrome/", GetMajorVersionNumber(), ".0.0.0"});
}
```

改为:

```cpp
std::string GetProductNameAndVersionForReducedUserAgent() {
  // Teleport: engine (not product) major version — see the .h counterpart.
  return "Chrome/" TELEPORT_ENGINE_VERSION_MAJOR ".0.0.0";
}
```

并在 include 块加 `#include "components/version_info/teleport_engine_version.h"`。

- [ ] **Step 3: 编辑检出 `components/embedder_support/user_agent_utils.cc`(三处)**

include 块加 `#include "components/version_info/teleport_engine_version.h"`。三处版本源替换(Teleport: UA-CH carries the engine version):

`GetUserAgentBrandMajorVersionListInternal` 中:

```cpp
  return GetUserAgentBrandList(TELEPORT_ENGINE_VERSION_MAJOR,
                               TELEPORT_ENGINE_VERSION_STRING,
                               blink::UserAgentBrandVersionType::kMajorVersion,
                               additional_brand_version);
```

`GetUserAgentBrandFullVersionListInternal` 中:

```cpp
  return GetUserAgentBrandList(TELEPORT_ENGINE_VERSION_MAJOR,
                               TELEPORT_ENGINE_VERSION_STRING,
                               blink::UserAgentBrandVersionType::kFullVersion,
                               additional_brand_version);
```

高熵 client hints 处:

```cpp
  metadata.full_version = TELEPORT_ENGINE_VERSION_STRING;
```

(原三处分别是 `version_info::GetMajorVersionNumber(), std::string(version_info::GetVersionNumber())` ×2 与 `std::string(version_info::GetVersionNumber())`。)

- [ ] **Step 4: 生成三个 patch + 幂等验证**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p $WT/patches/components/version_info $WT/patches/components/embedder_support
git diff -- components/version_info/version_info_with_user_agent.h > $WT/patches/components/version_info/version_info_with_user_agent.h.patch
git diff -- components/version_info/version_info_with_user_agent.cc > $WT/patches/components/version_info/version_info_with_user_agent.cc.patch
git diff -- components/embedder_support/user_agent_utils.cc > $WT/patches/components/embedder_support/user_agent_utils.cc.patch
cd $WT && python scripts/apply_patches.py | tail -1
```

Expected: `overlay applied.`(幂等,无冲突)。

- [ ] **Step 5: 构建 + UA 运行时验证(此时 VERSION 仍是 148,输出应与今天一致)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport \
  --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/tp-ua-probe about:blank &
sleep 5 && curl -s http://127.0.0.1:9222/json/version | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["User-Agent"]); print(d["Browser"])'
kill %1; rm -rf /tmp/tp-ua-probe
```

Expected: `User-Agent` 含 `Chrome/148.0.0.0`;`Browser` 形如 `Chrome/148.0.7778.180`(DevTools Browser 串走 GetProductNameAndVersionForUserAgent → 引擎全版本)。

- [ ] **Step 6: 提交**

```bash
cd $WT && git add patches/components
git commit -m "feat(version): pin UA / UA-CH surface to the engine version header"
```

---

### Task 5: 翻转 chrome/VERSION 生成 + TELEPORT_VERSION 四段化

**Files:**
- Modify: `TELEPORT_VERSION`(`0.1.12` → `0.1.12.0`)
- Modify: `scripts/apply_patches.py`(接入 `write_chrome_version`)

**Interfaces:**
- Produces: 构建产物全面产品版本化(框架目录 `Versions/0.1.12.0/`、plist、内嵌 dlopen 路径);后续任务(6/8/9)依赖 `version_info::GetVersionNumber()` == `0.1.12.0`。

- [ ] **Step 1: 四段化版本文件**

```bash
cd $WT && printf '0.1.12.0\n' > TELEPORT_VERSION
```

- [ ] **Step 2: 接入 VERSION 生成**

`apply_patches.py` 中 Task 3 加过的块改为:

```python
    import branding_strings
    branding_strings.main()
    import generate_version
    if generate_version.write_engine_header(args.root):
        print("engine version header written")
    if generate_version.write_chrome_version(args.root):
        print("chrome/VERSION written from TELEPORT_VERSION")
    print("overlay applied.")
```

- [ ] **Step 3: 运行 overlay,验证 VERSION 内容与幂等**

```bash
cd $WT && python scripts/apply_patches.py | tail -3
cat "$TELEPORT_CHROMIUM_DIR/src/chrome/VERSION"
python scripts/apply_patches.py | tail -2
```

Expected: 首跑含 `chrome/VERSION written…`;文件为 `MAJOR=0/MINOR=1/BUILD=12/PATCH=0` 四行;二跑不再出现该行。

- [ ] **Step 4: 构建 + 产物验证(VERSION 变更触达面大,本次构建显著变长,预期内)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
ls "out/mac/arm64/dev/Teleport.app/Contents/Frameworks/Teleport Framework.framework/Versions/"
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' out/mac/arm64/dev/Teleport.app/Contents/Info.plist
out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport \
  --headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/tp-ua-probe about:blank &
sleep 5 && curl -s http://127.0.0.1:9222/json/version | python3 -c 'import json,sys; print(json.load(sys.stdin)["User-Agent"])'
kill %1; rm -rf /tmp/tp-ua-probe
```

Expected: `Versions/` 下为 `0.1.12.0`(+ `Current` 链接);`CFBundleShortVersionString` = `0.1.12.0`;UA 仍含 `Chrome/148.0.0.0`。

- [ ] **Step 5: gtest 回归(teleport_version 旧启发式在 dev 下仍显示 0.0.0-dev,旧测试仍绿——重构在 Task 6)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && out/mac/arm64/dev/teleport_unittests
```

Expected: `SUCCESS: all tests passed.`

- [ ] **Step 6: 提交**

```bash
cd $WT && git add TELEPORT_VERSION scripts/apply_patches.py
git commit -m "feat(version): bake TELEPORT_VERSION (4-segment) into chrome/VERSION at overlay time"
```

---

### Task 6: `teleport_version` 重构(TDD)

**Files:**
- Modify: `src/common/teleport_version.h`、`src/common/teleport_version.cc`、`src/common/teleport_version_unittest.cc`
- Delete: `src/common/teleport_version_mac.mm`
- Modify: `src/BUILD.gn`(移除 `sources += [ "common/teleport_version_mac.mm" ]` 行,位于 `is_mac` 块)

**Interfaces:**
- Produces: `teleport::GetDisplayVersion() -> std::string`(产品版本;非 official 构建带 `-dev` 后缀)。`ResolveDisplayVersion` 删除(全仓唯一消费方是 About/version 展示 patch,经 `GetDisplayVersion` 间接调用,签名不变)。

- [ ] **Step 1: 重写单测(Red)**

`src/common/teleport_version_unittest.cc` 全文替换为:

```cpp
#include "teleport/common/teleport_version.h"

#include <string>

#include "components/version_info/version_info.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// The display version is the baked product version (chrome/VERSION is
// generated from TELEPORT_VERSION at overlay time) — never the engine version.
TEST(TeleportVersionTest, DisplaysBakedProductVersion) {
  const std::string version = GetDisplayVersion();
  EXPECT_EQ(version.rfind(std::string(version_info::GetVersionNumber()), 0), 0u)
      << version;
  EXPECT_EQ(version.find("7778"), std::string::npos) << version;
}

TEST(TeleportVersionTest, DevSuffixTracksOfficialBuildFlag) {
  const std::string expected =
      std::string(version_info::GetVersionNumber()) +
      (version_info::IsOfficialBuild() ? "" : "-dev");
  EXPECT_EQ(expected, GetDisplayVersion());
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: 构建并运行确认 Red**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportVersionTest.*'
```

Expected: 两个测试 FAILED(旧实现读 unittest 二进制的 bundle 版本,返回 `0.0.0-dev`)。

- [ ] **Step 3: 实现(Green)**

`src/common/teleport_version.h` 全文替换为:

```cpp
#ifndef TELEPORT_COMMON_TELEPORT_VERSION_H_
#define TELEPORT_COMMON_TELEPORT_VERSION_H_

#include <string>

namespace teleport {

// The version string shown in the About page and chrome://version: the baked
// 4-segment product version (chrome/VERSION is generated from
// TELEPORT_VERSION at overlay time), with a "-dev" suffix on non-official
// builds. Never exposes the upstream Chromium version — the engine version
// exists only in the UA / UA-CH surface.
std::string GetDisplayVersion();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_VERSION_H_
```

`src/common/teleport_version.cc` 全文替换为:

```cpp
#include "teleport/common/teleport_version.h"

#include "components/version_info/version_info.h"

namespace teleport {

std::string GetDisplayVersion() {
  std::string version(version_info::GetVersionNumber());
  if (!version_info::IsOfficialBuild()) {
    version += "-dev";
  }
  return version;
}

}  // namespace teleport
```

删除 `src/common/teleport_version_mac.mm`,并从 `src/BUILD.gn` 的 `is_mac` 块删除 `"common/teleport_version_mac.mm",` 一行。

- [ ] **Step 4: 构建运行确认 Green + 全量 gtest**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && out/mac/arm64/dev/teleport_unittests
```

Expected: `SUCCESS: all tests passed.`(dev 构建下新测试断言 `0.1.12.0-dev`)。

- [ ] **Step 5: 提交**

```bash
cd $WT && git add src/common/teleport_version.h src/common/teleport_version.cc src/common/teleport_version_unittest.cc src/BUILD.gn
git rm src/common/teleport_version_mac.mm
git commit -m "refactor(version): display version from version_info + IsOfficialBuild, drop plist heuristic"
```

---

### Task 7: `tweak_info_plist.py` patch —— mac `CFBundleVersion` 全四段

**Files:**
- Create: `patches/build/apple/tweak_info_plist.py.patch`

**Interfaces:**
- Produces: 构建期主 app 与全部嵌套 bundle 的 `CFBundleVersion` = 完整四段(Sparkle 比较键;上游 `@BUILD@.@PATCH@` 在产品版本 minor 提升时非单调,如 `0.1.12.0→"12.0"` 而 `0.2.0.0→"0.0"`)。Task 9 的打包断言与 appcast 语义依赖它。

- [ ] **Step 1: 编辑检出 `build/apple/tweak_info_plist.py`**

`if options.platform == 'mac':` 分支内,将:

```python
        # BUILD will always be an increasing value, so BUILD_PATH gives us
        # something unique that meetings what LS wants.
        'CFBundleVersion': '@BUILD@.@PATCH@',
```

改为:

```python
        # BUILD will always be an increasing value, so BUILD_PATH gives us
        # something unique that meetings what LS wants.
        # Teleport: CFBundleVersion is Sparkle's comparison key. The upstream
        # BUILD.PATCH form is non-monotonic across product minor bumps
        # (0.1.12.0 -> "12.0" but 0.2.0.0 -> "0.0"), so write the full
        # 4-segment version. Values stay far below the 429496.72.95 LS limit.
        'CFBundleVersion': '@MAJOR@.@MINOR@.@BUILD@.@PATCH@',
```

- [ ] **Step 2: 生成 patch + 幂等**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p $WT/patches/build/apple
git diff -- build/apple/tweak_info_plist.py > $WT/patches/build/apple/tweak_info_plist.py.patch
cd $WT && python scripts/apply_patches.py | tail -1
```

Expected: `overlay applied.`

- [ ] **Step 3: 构建 + plist 验证(主 app 与一个 helper)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' out/mac/arm64/dev/Teleport.app/Contents/Info.plist
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "out/mac/arm64/dev/Teleport.app/Contents/Frameworks/Teleport Framework.framework/Versions/Current/Helpers/Teleport Helper.app/Contents/Info.plist"
```

Expected: 两者均 `0.1.12.0`。

- [ ] **Step 4: 提交**

```bash
cd $WT && git add patches/build
git commit -m "feat(version): CFBundleVersion carries the full 4-segment product version on mac"
```

---

### Task 8: `_release.py` / `bump_version.py` 四段化(TDD)

**Files:**
- Modify: `scripts/_release.py`、`scripts/bump_version.py`
- Test: `scripts/tests/test_release.py`、`scripts/tests/test_bump_version.py`

**Interfaces:**
- Produces:
  - `_release.parse_semver(version: str) -> tuple[int,int,int,int]`(接受三段——历史 tag/feed 兼容,缺位补 0;返回恒四元组)
  - `_release.read_teleport_version(root=None) -> str`(**严格四段**,三段报 `ValueError`)
  - `bump_version.bump(version: str, part: str) -> str`(part ∈ major/minor/patch/hotfix,右侧清零;输入输出均四段)
  - `is_newer` / `max_appcast_version` / `assert_publishable` 语义不变(经新 parse 自动兼容混段比较)。

- [ ] **Step 1: 改写测试(Red)**

`scripts/tests/test_release.py` 中以下测试函数替换/新增(其余保留):

```python
def test_parse_semver_ok():
    assert _release.parse_semver("0.1.12.0") == (0, 1, 12, 0)
    assert _release.parse_semver(" 1.2.3.4 ") == (1, 2, 3, 4)


def test_parse_semver_pads_legacy_three_segment():
    # Pre-4-segment history (old tags / feed items) compares as PATCH=0.
    assert _release.parse_semver("0.1.12") == (0, 1, 12, 0)


@pytest.mark.parametrize("bad", ["0.1", "1.2.3.4.5", "v1.0.0.0", "x", ""])
def test_parse_semver_rejects(bad):
    with pytest.raises(ValueError):
        _release.parse_semver(bad)


def test_is_newer():
    assert _release.is_newer("0.1.12.1", "0.1.12.0")
    assert _release.is_newer("0.2.0.0", "0.1.9.5")
    assert _release.is_newer("0.1.13.0", "0.1.12")      # mixed vs legacy
    assert not _release.is_newer("0.1.12.0", "0.1.12")  # equal after padding
    assert not _release.is_newer("0.1.12.0", "0.1.12.1")


def test_read_teleport_version(tmp_path):
    (tmp_path / "TELEPORT_VERSION").write_text("0.4.2.0\n")
    assert _release.read_teleport_version(tmp_path) == "0.4.2.0"


def test_read_teleport_version_rejects_three_segment(tmp_path):
    (tmp_path / "TELEPORT_VERSION").write_text("0.4.2\n")
    with pytest.raises(ValueError):
        _release.read_teleport_version(tmp_path)
```

`scripts/tests/test_bump_version.py` 全文替换为:

```python
import pytest

import bump_version


def test_bump_hotfix():
    assert bump_version.bump("0.1.12.0", "hotfix") == "0.1.12.1"


def test_bump_patch_zeros_hotfix():
    assert bump_version.bump("0.1.12.1", "patch") == "0.1.13.0"
    assert bump_version.bump("1.2.3.4", "patch") == "1.2.4.0"


def test_bump_minor_zeros_lower():
    assert bump_version.bump("0.1.12.3", "minor") == "0.2.0.0"


def test_bump_major_zeros_lower():
    assert bump_version.bump("1.2.3.4", "major") == "2.0.0.0"


def test_bump_rejects_unknown_part():
    with pytest.raises(ValueError):
        bump_version.bump("0.1.12.0", "build")


def test_bump_rejects_bad_version():
    with pytest.raises(ValueError):
        bump_version.bump("1.2", "patch")
```

- [ ] **Step 2: 运行确认 Red**

Run: `cd $WT && uv run pytest scripts/tests/test_release.py scripts/tests/test_bump_version.py -q`
Expected: 多个 FAIL(四段解析/hotfix 不存在)。

- [ ] **Step 3: 实现**

`scripts/_release.py` 顶部解析区替换为:

```python
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_semver(version: str) -> tuple[int, int, int, int]:
    """Parse 'MAJOR.MINOR.BUILD[.PATCH]' into a comparable 4-tuple.

    A missing 4th segment defaults to 0 so pre-4-segment history (old tags and
    feed items like '0.1.12') stays comparable. New TELEPORT_VERSION values
    must be written 4-segment — enforced by read_teleport_version().
    """
    m = _VERSION_RE.match(version.strip())
    if not m:
        raise ValueError(f"not a MAJOR.MINOR.BUILD[.PATCH] version: {version!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4) or 0))
```

`read_teleport_version` 替换为:

```python
def read_teleport_version(root: Path | None = None) -> str:
    """Read + validate the 4-segment TELEPORT_VERSION from the repo root."""
    from _lib import repo_root
    p = (root or repo_root()) / "TELEPORT_VERSION"
    v = p.read_text().strip()
    if v.count(".") != 3:
        raise ValueError(
            f"TELEPORT_VERSION must be 4-segment MAJOR.MINOR.BUILD.PATCH, got {v!r}")
    parse_semver(v)  # validate digits; raises on garbage
    return v
```

`scripts/bump_version.py`:`_PARTS = ("major", "minor", "patch", "hotfix")`;docstring 的用法示例更新为四段(`0.1.12.0 -> 0.1.13.0` 等);CLI `argparse` 增加 `--hotfix` 互斥选项(与 --major/--minor/--patch 同组);`bump()` 本体无需改(`parse_semver` 已返回四元组,右侧清零逻辑通用)。

- [ ] **Step 4: 运行确认 Green + 全量 pytest**

Run: `cd $WT && uv run pytest -q`
Expected: 全绿(若 `test_publish.py`/`test_package_state.py` 存在三段字面量断言失败,按同样"三段→四段字面量"规则更新其断言——它们只是数据值,不涉及行为变化)。

- [ ] **Step 5: 提交**

```bash
cd $WT && git add scripts/_release.py scripts/bump_version.py scripts/tests/test_release.py scripts/tests/test_bump_version.py
git commit -m "feat(release): 4-segment TELEPORT_VERSION parsing, legacy padding compare, hotfix bump"
```

---

### Task 9: 打包链——删 stamp,改断言 + Sparkle 注入拆分

**Files:**
- Modify: `scripts/_package.py:22-38,68-94`、`scripts/package.py:61,118`
- Test: `scripts/tests/test_package.py`、`scripts/tests/test_package_cli.py`

**Interfaces:**
- Consumes: `_release.read_teleport_version`(四段)。
- Produces:
  - `_package.read_baked_short_version(app: Path) -> str`
  - `_package.assert_baked_version(app: Path, version: str) -> None`(不匹配 `SystemExit`)
  - `_package.inject_sparkle_keys(app: Path, cfg: dict, channel_name: str) -> None`(原 `stamp_and_inject` 去掉版本键)
  - 删除:`version_plist_keys`、`stamp_version_only`、`stamp_and_inject`、`sparkle_plist_string_keys` 的版本合并。

- [ ] **Step 1: 改写测试(Red)**

`scripts/tests/test_package.py`:删除 `test_version_plist_keys_sets_both_version_fields`;将两个 `stamp_and_inject` 测试改为 `inject_sparkle_keys`(调用去掉版本参数;期望键表中**移除** `CFBundleShortVersionString`/`CFBundleVersion` 两行,其余不变);新增:

```python
def test_assert_baked_version_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(_package, "read_baked_short_version", lambda app: "0.1.12.0")
    _package.assert_baked_version(tmp_path / "Teleport.app", "0.1.12.0")  # no raise


def test_assert_baked_version_mismatch_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(_package, "read_baked_short_version", lambda app: "0.1.11.0")
    with pytest.raises(SystemExit, match="re-run scripts/apply_patches.py"):
        _package.assert_baked_version(tmp_path / "Teleport.app", "0.1.12.0")
```

`scripts/tests/test_package_cli.py`:先 `sed -n '25,80p' scripts/tests/test_package_cli.py` 查看上下文,然后按此规则逐处替换:`monkeypatch.setattr(package._package, "stamp_version_only", lambda app, v: calls.append(("stamp_version_only", v)))` → `monkeypatch.setattr(package._package, "assert_baked_version", lambda app, v: calls.append(("assert_baked_version", v)))`;断言 `("stamp_version_only", "9.9.9") in calls` → `("assert_baked_version", "9.9.9") in calls`;`stamp_and_inject` 的 monkeypatch → `assert_baked_version` + `inject_sparkle_keys` 两个(渠道路径两个都必须被调用,断言两者都出现在 `calls`)。

- [ ] **Step 2: 运行确认 Red**

Run: `cd $WT && uv run pytest scripts/tests/test_package.py scripts/tests/test_package_cli.py -q`
Expected: FAIL(`inject_sparkle_keys`/`assert_baked_version` 不存在)。

- [ ] **Step 3: 实现 `_package.py`**

删除 `version_plist_keys` 与 `stamp_version_only`,替换为:

```python
def read_baked_short_version(app: Path) -> str:
    """CFBundleShortVersionString baked into the built app's Info.plist."""
    r = subprocess.run(
        ["plutil", "-extract", "CFBundleShortVersionString", "raw", "-o", "-",
         str(app / "Contents" / "Info.plist")],
        capture_output=True, text=True, check=True)
    return r.stdout.strip()


def assert_baked_version(app: Path, version: str) -> None:
    """The build must already carry TELEPORT_VERSION (chrome/VERSION is
    generated from it at overlay time). A mismatch means a stale build or a
    missed apply_patches run after a version bump — refuse to package."""
    baked = read_baked_short_version(app)
    if baked != version:
        raise SystemExit(
            f"baked app version {baked!r} != TELEPORT_VERSION {version!r}; "
            "re-run scripts/apply_patches.py and rebuild before packaging")
```

`sparkle_plist_string_keys(version, cfg, channel_name)` → `sparkle_plist_string_keys(cfg, channel_name)`,返回字典去掉 `**version_plist_keys(version),`;`stamp_and_inject(app, version, cfg, channel_name)` → 重命名:

```python
def inject_sparkle_keys(app: Path, cfg: dict, channel_name: str) -> None:
    """Inject Sparkle keys + the TeleportChannel marker into the app's
    Info.plist (pre-sign). Version fields are baked at build time and verified
    by assert_baked_version()."""
    info = app / "Contents" / "Info.plist"
    for key, val in sparkle_plist_string_keys(cfg, channel_name).items():
        subprocess.run(["plutil", "-replace", key, "-string", val, str(info)], check=True)
```

(函数内其后的 `SUEnableAutomaticChecks`/`SUScheduledCheckInterval` 两个 plutil 调用原样保留。)模块 docstring 的 "stamp version + Sparkle keys" 改为 "verify baked version + inject Sparkle keys"。

- [ ] **Step 4: 更新 `package.py` 两个调用点**

`:61` `_package.stamp_version_only(app, version)` → `_package.assert_baked_version(app, version)`;
`:118` `_package.stamp_and_inject(app, version, cfg, channel.name)` →

```python
    _package.assert_baked_version(app, version)
    _package.inject_sparkle_keys(app, cfg, channel.name)
```

- [ ] **Step 5: 运行确认 Green + 全量 pytest**

Run: `cd $WT && uv run pytest -q`
Expected: 全绿。

- [ ] **Step 6: 真实产物断言冒烟(用 Task 7 构建的 dev app)**

```bash
cd $WT && uv run python -c "
from pathlib import Path
import sys; sys.path.insert(0, 'scripts')
import _package
app = Path('$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/Teleport.app')
_package.assert_baked_version(app, '0.1.12.0'); print('baked version OK')"
```

Expected: `baked version OK`。

- [ ] **Step 7: 提交**

```bash
cd $WT && git add scripts/_package.py scripts/package.py scripts/tests/test_package.py scripts/tests/test_package_cli.py
git commit -m "feat(package): drop version stamping — verify baked version, split Sparkle key injection"
```

---

### Task 10: DM `agent` 参数附带引擎版本

**Files:**
- Create: `patches/chrome/browser/policy/device_management_service_configuration.cc.patch`

**Interfaces:**
- Produces: 每个 DM 请求的 `agent` query 参数为 `"<产品名> <产品版本> Chromium/<引擎版本>(<lastchange>)"`。fairyland device-manager(配对分支)按 `Chromium/([0-9.]+)` 解析存 `engine_version`。

- [ ] **Step 1: 编辑检出 `chrome/browser/policy/device_management_service_configuration.cc`**

include 块(`#include "components/version_info/version_info.h"` 之后)加:

```cpp
#include "components/version_info/teleport_engine_version.h"
```

将:

```cpp
std::string DeviceManagementServiceConfiguration::GetAgentParameter() const {
  return base::StrCat({version_info::GetProductName(), " ",
                       version_info::GetVersionNumber(), "(",
                       version_info::GetLastChange(), ")"});
}
```

改为:

```cpp
std::string DeviceManagementServiceConfiguration::GetAgentParameter() const {
  // Teleport: GetVersionNumber() is the product version; append the pinned
  // Chromium engine version so the fairyland device-manager can persist and
  // display both (management UI shows product + engine).
  return base::StrCat({version_info::GetProductName(), " ",
                       version_info::GetVersionNumber(),
                       " Chromium/" TELEPORT_ENGINE_VERSION_STRING "(",
                       version_info::GetLastChange(), ")"});
}
```

- [ ] **Step 2: 生成 patch + 幂等 + 编译**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/policy/device_management_service_configuration.cc > $WT/patches/chrome/browser/policy/device_management_service_configuration.cc.patch
cd $WT && python scripts/apply_patches.py | tail -1
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```

Expected: 幂等通过;编译成功。(运行态验证归 Task 11 的移交清单——需要 fairyland dev 环境抓请求日志,属跨仓库联调。)

- [ ] **Step 3: 提交**

```bash
cd $WT && git add patches/chrome/browser/policy/device_management_service_configuration.cc.patch
git commit -m "feat(enterprise): DM agent parameter carries product + engine versions"
```

---

### Task 11: 文档 + 终验 + 交接

**Files:**
- Modify: `CLAUDE.md`(§构建命令 `printf` 示例、§gotcha「版本」条)、`scripts/smoke_check.md`(版本暴露检查行)、`docs/tech-debt.md`(TD-014 移「已结清」)

- [ ] **Step 1: CLAUDE.md 两处**

`printf '0.1.2\n' > TELEPORT_VERSION              # 每次发版 bump(semver,单调递增)并提交` 改为:

```
printf '0.1.13.0\n' > TELEPORT_VERSION           # 每次发版 bump(四段 MAJOR.MINOR.BUILD.PATCH,单调递增;或用 scripts/bump_version.py)并提交
```

「**版本**」gotcha 条目改写为(全文替换该条):

```
- **版本**:`TELEPORT_VERSION`(四段 MAJOR.MINOR.BUILD.PATCH)单一事实来源;`apply_patches.py` 经 `generate_version.py` 把它现场生成进检出 `chrome/VERSION`(内容比较跳过写入,避免无谓全量重编;`chrome/VERSION` 在检出里是"生成物"而非 patch),同时从 `CHROMIUM_VERSION` 生成 `components/version_info/teleport_engine_version.h`(untracked)供 UA/UA-CH patch 引用——**UA 恒为引擎版本**(`Chrome/148.0.0.0`),产品版本绝不进 UA。打包**不再 stamp 版本**(`assert_baked_version` 校验烘焙版本==TELEPORT_VERSION,不符拒绝打包);`CFBundleVersion` 经 `tweak_info_plist.py` patch 为完整四段(上游 `BUILD.PATCH` 跨 minor 非单调,会断 Sparkle 升级)。dmg 名 `Teleport-<四段>.dmg`,发布打 `v<四段>` tag;appcast 只列最新版。bump 后必须重跑 `apply_patches.py` 再构建(VERSION 变更触发大范围重编,发版构建本为全量)。
```

- [ ] **Step 2: smoke_check.md 版本暴露行替换**

「版本不暴露」行替换为:

```
| 版本不暴露 | `ls ".../Teleport Framework.framework/Versions/"` = `<TELEPORT_VERSION>`;`PlistBuddy -c 'Print :SCMRevision' …` = Does Not Exist;`python3 - <<'EOF'`(遍历 .app 全部 plist/路径名 grep `7778`)零命中;`curl :9222/json/version` 的 UA 仍 `Chrome/148.0.0.0` | ✅ |
```

- [ ] **Step 3: tech-debt TD-014 结清**

把 `### TD-014 …` 整节移动到「已结清」段,标题追加「(已解决)」,`- **登记日期**` 行追加 ` · **结清日期**:` + 执行当日日期(`date +%F` 的 YYYY-MM-DD),并在节尾追加:

```
- **处置**:构建期以 `TELEPORT_VERSION`(四段化)生成 `chrome/VERSION`(`scripts/generate_version.py`,经 apply_patches 前置),框架目录/全部 plist/内嵌路径随之为产品版本;UA/UA-CH 经生成的 `teleport_engine_version.h` 钉住引擎版本(3 个 patch);`CFBundleVersion` patch 为完整四段;打包删 stamp 改烘焙断言;DM `agent` 参数附 `Chromium/<引擎版本>` 供 fairyland 存储展示。见 spec `docs/superpowers/specs/2026-07-04-product-version-scheme-design.md`。
```

- [ ] **Step 4: 终验(全套件 + 审计)**

```bash
cd $WT && python scripts/apply_patches.py | tail -1 && python scripts/apply_patches.py | tail -1
uv run pytest -q
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome teleport_unittests && out/mac/arm64/dev/teleport_unittests
python3 - <<'EOF'
import plistlib, sys
from pathlib import Path
app = Path("out/mac/arm64/dev/Teleport.app")
bad = [str(p.relative_to(app)) for p in app.rglob("*") if "7778" in p.name]
for p in app.rglob("*"):
    if p.is_file() and (p.suffix == ".plist" or p.name == "InfoPlist.strings"):
        try:
            data = plistlib.loads(p.read_bytes())
        except Exception:
            continue
        if "7778" in str(data):
            bad.append(f"{p.relative_to(app)} :: {data}")
print("\n".join(bad) or "AUDIT CLEAN: no chromium version in paths/plists")
sys.exit(1 if bad else 0)
EOF
```

Expected: 幂等两跑均 `overlay applied.`;pytest 全绿;gtest 全绿;审计输出 `AUDIT CLEAN…`。

再跑 UA-CH 运行时探测(brands 必须是 Chromium 148,不得出现产品版本 0.x):

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport \
  --headless=new --user-data-dir=/tmp/tp-uach-probe --dump-dom \
  'data:text/html,<script>document.write(JSON.stringify(navigator.userAgentData.brands))</script>' \
  | grep -o '{.*}]' ; rm -rf /tmp/tp-uach-probe
```

Expected: 输出的 brands JSON 含 `"Chromium"` 且 version 为 `"148"`;不含 `"0"`/产品版本段。

- [ ] **Step 5: 符号链接还原 + 提交**

```bash
ln -sfn /Users/liulichao/workspace/teleport/src "$TELEPORT_CHROMIUM_DIR/src/teleport"
cd $WT && git add CLAUDE.md scripts/smoke_check.md docs/tech-debt.md
git commit -m "docs: 4-segment version workflow, smoke checks, close TD-014"
```

注意:还原链接后,worktree 分支合并回 main 前若需再构建验证,须重新执行 Task 1 Step 1。

- [ ] **Step 6: 交接清单(不在本计划内实施,记录移交)**

- fairyland 配对分支(同名 `worktree-product-version-scheme`):device-manager 解析 `agent` 参数 `Chromium/([0-9.]+)` → 存 `engine_version` → 管理面双版本展示;其侧独立 spec/plan。
- 联调(fairyland 侧完成后):dev 环境跑纳管注册,确认请求日志中 `agent=Teleport 0.1.12.0 Chromium/148.0.7778.180(...)`、库中双版本落地。
- 合并:worktree 分支按 rebase onto main + squash + fast-forward 收尾(经 `superpowers:finishing-a-development-branch`)。
