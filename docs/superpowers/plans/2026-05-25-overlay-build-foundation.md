# Overlay Build Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 teleport 仓库能从 overlay 构建出一个带「闪现」品牌、并加载自定义 `//teleport` 模块的 Chromium(macOS 最小里程碑)。

**Architecture:** Brave 式 overlay。chromium 签出到仓库内 `chromium/`(gitignore);overlay 纯源码在 `<repo>/src/`,构建期以符号名 `teleport` 链接进 `chromium/src/teleport`(GN `//teleport`);产物落在真实目录 `chromium/src/out`(autoninja 要求 out 在检出树内),由仓库根 `build/` 反向链接暴露为 `build/<os>/<arch>/<build_type>/`。定制加法为主(`//teleport` 模块),改上游为辅(`patches/` 文本补丁 + `branding/` 资源覆盖)。

**Tech Stack:** Chromium M148、depot_tools、GN + Siso(`autoninja`)、Python 3.13 编排脚本(pytest)、C++(gtest)。

**参考:** 设计 spec `docs/superpowers/specs/2026-05-25-overlay-build-foundation-design.md`。

**TDD 范围(已与用户确认):** 产品代码(`//teleport` C++)走 TDD;构建/编排脚本不强求 TDD,仅在逻辑有价值处(`apply_patches` 的幂等/fail-fast、链接 helper、版本校验)写务实的 pytest。

**阶段与门槛:**
- **Phase 0–3(Task 1–7)**:仓库脚手架、Python 工具、`//teleport` 源码与测试、GN args。**不需要 chromium 检出**,可在本机直接 `pytest` 验证。
- **Phase 4(Task 8–12)**:真实 M148 检出 + 版本相关补丁 + 品牌化 + 构建与冒烟验证。**需要数百 GB 检出与数小时构建**,且补丁内容须对照 M148 真实源码现场确定(spec §15)。

---

## Phase 0 — 仓库脚手架

### Task 1: 仓库脚手架与工具配置

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `CHROMIUM_VERSION`
- Create: `scripts/tests/__init__.py`(空文件,使 tests 成为包)

- [ ] **Step 1: 写 `.gitignore`**

```gitignore
# Chromium checkout (managed by depot_tools / gclient)
/chromium/

# Build outputs (linked from chromium/src/out)
/build/

# Python
__pycache__/
*.pyc
.venv/
.pytest_cache/
```

- [ ] **Step 2: 写 `pyproject.toml`(pytest 配置,让测试能 import scripts/ 下的模块)**

```toml
[project]
name = "teleport-overlay-tools"
version = "0.0.0"
description = "Build orchestration tooling for the teleport Chromium overlay"
requires-python = ">=3.13"

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["scripts/tests"]
pythonpath = ["scripts"]

[tool.uv]
package = false
```

> 工具链:本机系统 Python 为 3.9 且无 pytest;用 `uv` 运行测试(`uv run pytest`),uv 会按 `requires-python` 取 3.13 并装 dev 组的 pytest。`package = false` 让 uv 只管理环境/依赖、不把本仓库当可安装包构建。

- [ ] **Step 3: 确定并写入 M148 上游版本号到 `CHROMIUM_VERSION`**

Run(查最新 M148 稳定版,macOS 平台):
```bash
curl -s 'https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Mac&milestone=148&num=1' | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["version"])'
```
把输出(形如 `148.0.7xxx.xx`)写入 `CHROMIUM_VERSION`(单行,无多余空白)。例:
```
148.0.7000.0
```
> 该值是外部事实,以上述命令现场取到的为准;不要沿用此示例数字。

- [ ] **Step 4: 创建空的测试包标记**

`scripts/tests/__init__.py` 为空文件。

- [ ] **Step 5: Commit**

```bash
git add .gitignore pyproject.toml CHROMIUM_VERSION scripts/tests/__init__.py
git commit -m "chore: scaffold overlay repo (gitignore, pytest config, version pin)"
```

---

## Phase 1 — Python 编排工具

### Task 2: 链接与路径 helper(`_lib.py`)

**Files:**
- Create: `scripts/_lib.py`
- Test: `scripts/tests/test_lib.py`

- [ ] **Step 1: 写失败测试(POSIX symlink 行为:创建、幂等、错目标报错)**

`scripts/tests/test_lib.py`:
```python
import os
from pathlib import Path

import pytest

import _lib


def test_create_dir_link_creates_symlink(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, target)
    assert link.is_symlink()
    assert Path(os.path.realpath(link)) == target.resolve()


def test_create_dir_link_is_idempotent(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, target)
    _lib.create_dir_link(link, target)  # second call must not raise
    assert Path(os.path.realpath(link)) == target.resolve()


def test_create_dir_link_wrong_target_raises(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, tmp_path / "a")
    with pytest.raises(RuntimeError):
        _lib.create_dir_link(link, tmp_path / "b")
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_lib.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named '_lib'`)

- [ ] **Step 3: 写最小实现**

`scripts/_lib.py`:
```python
"""Shared helpers for the teleport overlay build scripts."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def repo_root() -> Path:
    """teleport repo root (the dir containing this scripts/ folder)."""
    return Path(__file__).resolve().parent.parent


def chromium_src(root: Path | None = None) -> Path:
    return (root or repo_root()) / "chromium" / "src"


def is_windows() -> bool:
    return os.name == "nt"


def create_dir_link(link: Path, target: Path) -> None:
    """Create a directory link named `link` pointing at `target`.

    POSIX: symlink. Windows: directory junction (`mklink /J`) — needs no
    privilege and works for same-volume dirs. Idempotent when the link already
    points at `target`; raises if it points elsewhere or a real file is in the way.
    """
    link = Path(link)
    target = Path(target).resolve()
    if link.is_symlink() or (is_windows() and link.exists() and _points_somewhere(link)):
        existing = Path(os.path.realpath(link))
        if existing == target:
            return
        raise RuntimeError(f"link {link} -> {existing}, expected {target}")
    if link.exists():
        raise RuntimeError(f"{link} exists and is not a link")
    link.parent.mkdir(parents=True, exist_ok=True)
    if is_windows():
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True, text=True,
        )
    else:
        os.symlink(target, link, target_is_directory=True)


def _points_somewhere(path: Path) -> bool:
    """True if `path` is a reparse point (Windows junction) we can resolve."""
    try:
        return os.path.realpath(path) != str(path)
    except OSError:
        return False
```
> 注:Windows junction 分支在 macOS 里程碑用不到,其具体行为在三端化 phase 于 Windows 上验证;本任务测试只覆盖 POSIX symlink。

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_lib.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/_lib.py scripts/tests/test_lib.py
git commit -m "feat: add path + directory-link helper for overlay scripts"
```

---

### Task 3: patch / 资源覆盖应用(`apply_patches.py`)

**Files:**
- Create: `scripts/apply_patches.py`
- Test: `scripts/tests/test_apply_patches.py`

- [ ] **Step 1: 写失败测试(用临时 git 仓库当假 chromium/src)**

`scripts/tests/test_apply_patches.py`:
```python
import subprocess
from pathlib import Path

import pytest

import apply_patches


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _make_fake_src(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "t@t")
    _git(src, "config", "user.name", "t")
    (src / "chrome").mkdir()
    (src / "chrome" / "foo.txt").write_text("line1\nline2\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "base")
    return src


def _make_patch(tmp_path: Path, src: Path) -> Path:
    # Edit the file, capture the diff as a one-file patch mirroring the src path.
    (src / "chrome" / "foo.txt").write_text("line1\nCHANGED\n")
    diff = _git(src, "diff")
    _git(src, "checkout", "--", ".")  # restore clean tree
    patches = tmp_path / "patches"
    (patches / "chrome").mkdir(parents=True)
    patch = patches / "chrome" / "foo.txt.patch"
    patch.write_text(diff)
    return patch


def test_apply_then_idempotent(tmp_path: Path):
    src = _make_fake_src(tmp_path)
    patch = _make_patch(tmp_path, src)
    apply_patches.apply_patch(patch, src)
    assert "CHANGED" in (src / "chrome" / "foo.txt").read_text()
    # Second apply is a no-op (does not raise, content unchanged).
    apply_patches.apply_patch(patch, src)
    assert (src / "chrome" / "foo.txt").read_text().count("CHANGED") == 1


def test_apply_conflict_fails_fast(tmp_path: Path):
    src = _make_fake_src(tmp_path)
    patch = _make_patch(tmp_path, src)
    # Make the target incompatible so the patch neither applies nor reverses.
    (src / "chrome" / "foo.txt").write_text("totally different\n")
    with pytest.raises(RuntimeError):
        apply_patches.apply_patch(patch, src)


def test_find_patches_sorted(tmp_path: Path):
    patches = tmp_path / "patches"
    (patches / "b").mkdir(parents=True)
    (patches / "a").mkdir(parents=True)
    (patches / "b" / "z.patch").write_text("")
    (patches / "a" / "y.patch").write_text("")
    found = apply_patches.find_patches(patches)
    assert [p.relative_to(patches).as_posix() for p in found] == ["a/y.patch", "b/z.patch"]
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_apply_patches.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'apply_patches'`)

- [ ] **Step 3: 写最小实现**

`scripts/apply_patches.py`:
```python
"""Apply text patches (patches/) and resource overlays (branding/) onto chromium/src.

One-patch-per-file: each *.patch mirrors one upstream path; application is
order-independent (sorted only for reproducibility). Idempotent and fail-fast.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from _lib import chromium_src, repo_root


def find_patches(patches_dir: Path) -> list[Path]:
    return sorted(p for p in Path(patches_dir).rglob("*.patch") if p.is_file())


def _reverse_applies(patch: Path, src: Path) -> bool:
    r = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(patch)],
        cwd=src, capture_output=True, text=True,
    )
    return r.returncode == 0


def _forward_applies(patch: Path, src: Path) -> bool:
    r = subprocess.run(
        ["git", "apply", "--check", str(patch)],
        cwd=src, capture_output=True, text=True,
    )
    return r.returncode == 0


def apply_patch(patch: Path, src: Path) -> None:
    if _reverse_applies(patch, src):
        return  # already applied -> idempotent no-op
    if not _forward_applies(patch, src):
        raise RuntimeError(f"patch does not apply cleanly: {patch}")
    subprocess.run(["git", "apply", str(patch)], cwd=src, check=True)


def apply_branding(branding_dir: Path, src: Path) -> None:
    branding_dir = Path(branding_dir)
    for f in sorted(branding_dir.rglob("*")):
        if not f.is_file():
            continue
        dest = src / f.relative_to(branding_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)  # whole-file overlay; naturally idempotent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply teleport overlay onto chromium/src")
    parser.add_argument("--root", type=Path, default=repo_root())
    args = parser.parse_args(argv)
    src = chromium_src(args.root)
    if not (src / ".git").exists():
        print(f"error: {src} is not a chromium git checkout (run bootstrap.py first)", file=sys.stderr)
        return 1
    for patch in find_patches(args.root / "patches"):
        print(f"apply {patch.relative_to(args.root)}")
        apply_patch(patch, src)
    branding = args.root / "branding"
    if branding.exists():
        print("overlay branding/")
        apply_branding(branding, src)
    print("overlay applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_apply_patches.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/apply_patches.py scripts/tests/test_apply_patches.py
git commit -m "feat: add idempotent patch + branding overlay applier"
```

---

### Task 4: 首次设置脚本(`bootstrap.py`)

**Files:**
- Create: `scripts/bootstrap.py`

> 编排脚本(调用 `gclient`、创建链接)。`gclient` 部分依赖网络与 depot_tools,不做单测;链接逻辑已在 Task 2 测过。

- [ ] **Step 1: 写实现**

`scripts/bootstrap.py`:
```python
"""One-time setup: ensure chromium checkout, create the teleport + out links.

Steps:
  1. Verify depot_tools (`gclient`) is on PATH.
  2. Ensure chromium/.gclient (src solution).
  3. Initial `gclient sync` to the pinned version (delegated to sync.py).
  4. Ensure <repo>/build exists.
  5. Create links: chromium/src/teleport -> <repo>/src, chromium/src/out -> <repo>/build.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from _lib import chromium_src, create_dir_link, repo_root

GCLIENT_SOLUTION = """\
solutions = [
  {
    "name": "src",
    "url": "https://chromium.googlesource.com/chromium/src.git",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {},
  },
]
"""


def main() -> int:
    root = repo_root()
    if shutil.which("gclient") is None:
        print("error: depot_tools not found on PATH. Install depot_tools and add it to PATH:\n"
              "  https://chromium.googlesource.com/chromium/tools/depot_tools.git", file=sys.stderr)
        return 1

    chromium = root / "chromium"
    chromium.mkdir(exist_ok=True)
    gclient_file = chromium / ".gclient"
    if not gclient_file.exists():
        gclient_file.write_text(GCLIENT_SOLUTION)
        print(f"wrote {gclient_file}")

    # Initial sync to the pinned version.
    print("running initial gclient sync (this may take a long time)...")
    rc = subprocess.run([sys.executable, str(root / "scripts" / "sync.py")]).returncode
    if rc != 0:
        return rc

    build = root / "build"
    build.mkdir(exist_ok=True)

    src = chromium_src(root)
    create_dir_link(src / "teleport", root / "src")
    create_dir_link(src / "out", build)
    print("bootstrap complete: links created (src/teleport -> src, src/out -> build).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 冒烟检查(无 depot_tools 时友好报错)**

Run: `env PATH=/usr/bin python -m py_compile scripts/bootstrap.py && echo OK`
Expected: `OK`(仅校验语法;完整运行在 Task 8)

- [ ] **Step 3: Commit**

```bash
git add scripts/bootstrap.py
git commit -m "feat: add bootstrap (chromium checkout + overlay links)"
```

---

### Task 5: 同步与版本校验(`sync.py`)

**Files:**
- Create: `scripts/sync.py`
- Test: `scripts/tests/test_sync.py`

- [ ] **Step 1: 写失败测试(校验 chrome/VERSION 解析与比对)**

`scripts/tests/test_sync.py`:
```python
from pathlib import Path

import pytest

import sync


def test_parse_chrome_version(tmp_path: Path):
    v = tmp_path / "VERSION"
    v.write_text("MAJOR=148\nMINOR=0\nBUILD=7000\nPATCH=3\n")
    assert sync.parse_chrome_version(v) == "148.0.7000.3"


def test_verify_version_mismatch_raises(tmp_path: Path):
    v = tmp_path / "VERSION"
    v.write_text("MAJOR=150\nMINOR=0\nBUILD=1\nPATCH=0\n")
    with pytest.raises(RuntimeError):
        sync.verify_version(v, "148.0.7000.3")


def test_verify_version_match_ok(tmp_path: Path):
    v = tmp_path / "VERSION"
    v.write_text("MAJOR=148\nMINOR=0\nBUILD=7000\nPATCH=3\n")
    sync.verify_version(v, "148.0.7000.3")  # must not raise
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_sync.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'sync'`)

- [ ] **Step 3: 写最小实现**

`scripts/sync.py`:
```python
"""Sync chromium/src to the pinned version and verify it matches CHROMIUM_VERSION."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _lib import chromium_src, repo_root


def parse_chrome_version(version_file: Path) -> str:
    fields: dict[str, str] = {}
    for line in Path(version_file).read_text().splitlines():
        if "=" in line:
            k, _, val = line.partition("=")
            fields[k.strip()] = val.strip()
    return f"{fields['MAJOR']}.{fields['MINOR']}.{fields['BUILD']}.{fields['PATCH']}"


def verify_version(version_file: Path, expected: str) -> None:
    actual = parse_chrome_version(version_file)
    if actual != expected:
        raise RuntimeError(f"chromium version mismatch: checked out {actual}, pinned {expected}")


def main() -> int:
    root = repo_root()
    pinned = (root / "CHROMIUM_VERSION").read_text().strip()
    src = chromium_src(root)
    chromium = src.parent
    print(f"gclient sync src@{pinned} ...")
    rc = subprocess.run(
        ["gclient", "sync", "--revision", f"src@{pinned}", "--with_tags", "--no-history"],
        cwd=chromium,
    ).returncode
    if rc != 0:
        return rc
    verify_version(src / "chrome" / "VERSION", pinned)
    print(f"synced and verified chromium {pinned}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
> `gclient sync` 的精确参数(`--with_tags` / `--revision` 解析 tag)在 Task 8 实跑时按需要微调;`parse_chrome_version` / `verify_version` 已被单测覆盖。

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_sync.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/sync.py scripts/tests/test_sync.py
git commit -m "feat: add gclient sync with version verification"
```

---

## Phase 2 — `//teleport` 加法模块(产品代码,TDD)

### Task 6: `//teleport` 模块与启动 banner(测试先行)

**Files:**
- Create: `src/browser/teleport_startup_unittest.cc`(先)
- Create: `src/browser/teleport_startup.h`
- Create: `src/browser/teleport_startup.cc`
- Create: `src/BUILD.gn`

> 产品代码走 TDD:先写 gtest。C++ 测试的红/绿**运行**需要 chromium 检出,放到 Task 12 执行;本任务完成「测试先行的编写 + 实现 + 编译期自洽」。

- [ ] **Step 1: 先写失败测试**

`src/browser/teleport_startup_unittest.cc`:
```cpp
#include "teleport/browser/teleport_startup.h"

#include <string>

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportStartupTest, BannerIdentifiesOverlayAndMilestone) {
  const std::string banner = StartupBanner();
  EXPECT_NE(banner.find("teleport"), std::string::npos);
  EXPECT_NE(banner.find("M148"), std::string::npos);
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: 写头文件**

`src/browser/teleport_startup.h`:
```cpp
#ifndef TELEPORT_BROWSER_TELEPORT_STARTUP_H_
#define TELEPORT_BROWSER_TELEPORT_STARTUP_H_

namespace teleport {

// One-line banner identifying the teleport overlay build.
const char* StartupBanner();

// Logs the startup banner. Called from an early browser-startup hook.
void LogStartupBanner();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_TELEPORT_STARTUP_H_
```

- [ ] **Step 3: 写实现**

`src/browser/teleport_startup.cc`:
```cpp
#include "teleport/browser/teleport_startup.h"

#include "base/logging.h"

namespace teleport {

const char* StartupBanner() {
  return "[teleport] 闪现 overlay active (M148)";
}

void LogStartupBanner() {
  LOG(INFO) << StartupBanner();
}

}  // namespace teleport
```

- [ ] **Step 4: 写 `src/BUILD.gn`**

`src/BUILD.gn`:
```gn
# The //teleport additive module, compiled into chrome via a minimal upstream
# BUILD.gn dep patch (see patches/). A standalone test() target keeps unit
# tests buildable without patching upstream test targets.
import("//testing/test.gni")

source_set("teleport") {
  sources = [
    "browser/teleport_startup.cc",
    "browser/teleport_startup.h",
  ]
  deps = [ "//base" ]
}

test("teleport_unittests") {
  sources = [ "browser/teleport_startup_unittest.cc" ]
  deps = [
    ":teleport",
    "//base/test:run_all_unittests",
    "//testing/gtest",
  ]
}
```
> 说明:spec §10 写的是 `static_library`;此处用 `source_set`——chrome 内部「总会被链接」的加法代码用 `source_set` 更地道(省去中间 `.a`,符号不会被误丢)。属对 spec 的实现期细化。

- [ ] **Step 5: 编译期自洽检查(不需 chromium)**

Run: `python -c "import pathlib; assert pathlib.Path('src/BUILD.gn').exists() and pathlib.Path('src/browser/teleport_startup.cc').exists(); print('files present')"`
Expected: `files present`
> 真正的 gtest 红/绿在 Task 12(需检出与构建)。

- [ ] **Step 6: Commit**

```bash
git add src/BUILD.gn src/browser/teleport_startup.h src/browser/teleport_startup.cc src/browser/teleport_startup_unittest.cc
git commit -m "feat: add //teleport module with startup banner + unit test"
```

---

## Phase 3 — GN 构建参数

### Task 7: 开发期 args 模板

**Files:**
- Create: `src/gn/args/dev.mac.gn`

- [ ] **Step 1: 写 args 模板**

`src/gn/args/dev.mac.gn`:
```gn
# Dev build args for the teleport overlay on macOS (Apple Silicon).
# Fast iteration: release-ish + component build + minimal symbols.
target_os = "mac"
target_cpu = "arm64"

is_debug = false
is_component_build = true
symbol_level = 1
blink_symbol_level = 0
v8_symbol_level = 0

is_official_build = false
use_remoteexec = false
```
> 引用方式:`gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'`。发布版另建模板(后续 phase)。

- [ ] **Step 2: Commit**

```bash
git add src/gn/args/dev.mac.gn
git commit -m "feat: add macOS dev GN args template"
```

---

## Phase 4 — 真实检出、版本相关补丁、构建与验证(重,需 M148 检出)

> 以下任务需要数百 GB 检出与数小时构建;补丁内容须对照 M148 真实源码现场确定(spec §15)。每个补丁遵守「一文件一 patch」、文件名镜像 `chromium/src` 下路径。

### Task 8: 拉起真实 M148 检出并建立链接

**Files:** 无(生成 `chromium/`、`build/` 与两个链接,均 gitignore)

- [ ] **Step 1: 建立链接(检出已存在则 `--skip-sync`)**

检出在仓库外时用 `$TELEPORT_CHROMIUM_DIR` 指向它;已 sync 过则加 `--skip-sync`(只建链接,不重复同步):
```bash
export TELEPORT_CHROMIUM_DIR=/abs/path/to/chromium
python scripts/bootstrap.py --skip-sync
```
首次未检出时去掉 `--skip-sync` 让其完整 sync(耗时长)。
Expected: 末尾打印 `bootstrap complete: .../src/teleport -> .../src, .../src/out -> .../build`。

> 后续步骤里的 `cd chromium/src` 在用了 `$TELEPORT_CHROMIUM_DIR` 时应改为 `cd "$TELEPORT_CHROMIUM_DIR/src"`。

- [ ] **Step 2: 验证链接与版本**

Run:
```bash
ls -l chromium/src/teleport chromium/src/out
python -c "import sys; sys.path.insert(0,'scripts'); import sync; print(sync.parse_chrome_version('chromium/src/chrome/VERSION'))"
cat CHROMIUM_VERSION
```
Expected: `teleport -> .../src`、`out -> .../build`;两个版本号一致。

- [ ] **Step 3: 验证 GN 是否接受被链接的源码目录(spec §6 风险点)**

Run: `cd chromium/src && gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'`
Expected: 成功生成,无「source file not inside source root / outside root」类报错。
> 若失败:启用 spec §6 退路——改为把 `<repo>/src` 拷贝/受管检出成 `chromium/src/teleport` 真实目录(改 `bootstrap.py` 的源码链接为复制),只保留 `out` 链接;记录该决策。

- [ ] **Step 4: 提交(无源码改动,仅记录里程碑)**

无文件变更;若 Step 3 触发退路改了 `bootstrap.py`,则:
```bash
git add scripts/bootstrap.py
git commit -m "fix: fall back to real src checkout when GN rejects linked source dir"
```

---

### Task 9: 注入 `//teleport` 到 chrome 链接图(GN dep patch)

**Files:**
- Create: `patches/<upstream BUILD.gn 路径>.patch`(具体路径现场确定)

- [ ] **Step 1: 定位承载启动钩子的 chrome target 的 BUILD.gn**

Run(在 `chromium/src`):
```bash
grep -rl --include=BUILD.gn "chrome_browser_main" chrome/browser | head
```
（找到定义 `chrome_browser_main.cc` 所在 source_set 的 `BUILD.gn`,记为 `<F>`。)

- [ ] **Step 2: 在该 target 的 `deps` 中加入 `//teleport`**

编辑 `chromium/src/<F>`,在对应 `source_set`/`static_library` 的 `deps = [ ... ]` 里加一行:
```gn
    "//teleport",
```

- [ ] **Step 3: 捕获为镜像路径的单文件 patch**

Run(在 `chromium/src`):
```bash
mkdir -p ../../patches/$(dirname <F>)
git diff -- <F> > ../../patches/<F>.patch
git checkout -- <F>
```

- [ ] **Step 4: 验证 patch 幂等应用**

Run: `python scripts/apply_patches.py && python scripts/apply_patches.py`
Expected: 两次均成功,第二次为 no-op;`git -C chromium/src diff --stat` 显示 `<F>` 被改。

- [ ] **Step 5: Commit**

```bash
git add patches/
git commit -m "feat: patch chrome BUILD.gn to link //teleport"
```

---

### Task 10: 启动期调用 `teleport::LogStartupBanner()`(启动钩子 patch)

**Files:**
- Create: `patches/chrome/browser/<startup file>.patch`(具体文件现场确定)

- [ ] **Step 1: 定位浏览器启动早期钩子**

Run(在 `chromium/src`):
```bash
grep -rn "PreMainMessageLoopRun\|PreProfileInit" chrome/browser/chrome_browser_main.cc | head
```
选一个早期、稳定的钩子(记为函数 `<H>`,文件 `chrome/browser/chrome_browser_main.cc` 或其平台变体)。

- [ ] **Step 2: 插入 include 与调用**

在该文件顶部 include 区加:
```cpp
#include "teleport/browser/teleport_startup.h"
```
在 `<H>` 的早期位置加一行:
```cpp
  teleport::LogStartupBanner();
```

- [ ] **Step 3: 捕获为单文件 patch**

Run(在 `chromium/src`,`<S>` 为该启动文件路径):
```bash
mkdir -p ../../patches/$(dirname <S>)
git diff -- <S> > ../../patches/<S>.patch
git checkout -- <S>
```

- [ ] **Step 4: 验证幂等应用**

Run: `python scripts/apply_patches.py && python scripts/apply_patches.py`
Expected: 两次成功,第二次 no-op。

- [ ] **Step 5: Commit**

```bash
git add patches/
git commit -m "feat: patch browser startup to log teleport banner"
```

---

### Task 11: 品牌化(显示名「闪现」+ 图标 + bundle 名)

**Files:**
- Create: `patches/<BRANDING 文件>.patch`
- Create: `patches/<macOS Info.plist 模板>.patch`(`CFBundleDisplayName` 等)
- Create: `branding/<上游 app 图标路径>`(替换用 `.icns`)

- [ ] **Step 1: 定位品牌相关文件**

Run(在 `chromium/src`):
```bash
ls chrome/app/theme/chromium/BRANDING
grep -rn "CFBundleDisplayName\|PRODUCT_FULLNAME\|chromium" chrome/app/*Info.plist* 2>/dev/null | head
find chrome/app/theme/chromium -iname "*app*.icns" | head
```
（确定 `BRANDING`、Info.plist 模板、app 图标资源的确切路径。)

- [ ] **Step 2: 改 BRANDING:显示名「闪现」、ASCII 标识符 Teleport**

编辑 `chromium/src/chrome/app/theme/chromium/BRANDING`:用户可见 `PRODUCT_FULLNAME` 等显示字段设为 `闪现`;ASCII 标识(产品短名/可执行名/bundle id 相关)保持 `Teleport`/`teleport`/反向 DNS。捕获:
```bash
git -C chromium/src diff -- chrome/app/theme/chromium/BRANDING > patches/chrome/app/theme/chromium/BRANDING.patch
git -C chromium/src checkout -- chrome/app/theme/chromium/BRANDING
```

- [ ] **Step 3: 改 macOS Info.plist 模板:`CFBundleDisplayName` = 闪现,磁盘名/标识符保持 Teleport(ASCII)**

按 Step 1 找到的 plist 模板编辑后,捕获为镜像路径 patch(同 Step 2 模式)。

- [ ] **Step 4: 放置「闪现」图标到 branding/(资源覆盖)**

把准备好的 `.icns` 放到 `branding/<与上游图标完全相同的相对路径>`。

- [ ] **Step 5: 应用并验证**

Run: `python scripts/apply_patches.py`
Expected: BRANDING / plist patch 应用;`branding/` 图标覆盖到 `chromium/src` 对应路径(`git -C chromium/src status` 显示图标被改)。

- [ ] **Step 6: Commit**

```bash
git add patches/ branding/
git commit -m "feat: rebrand to 闪现 (display name, icon, bundle name)"
```

---

### Task 12: 构建与冒烟验证(definition of done)

**Files:** 无(构建产物在 `build/`,gitignore)

- [ ] **Step 1: 应用全部 overlay 并生成构建目录**

Run:
```bash
python scripts/apply_patches.py
cd chromium/src && gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
```
Expected: 成功。

- [ ] **Step 2: 运行 `//teleport` 单测(完成 Task 6 的 TDD 红/绿)**

Run(在 `chromium/src`):
```bash
autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportStartupTest.*'
```
Expected: `[  PASSED  ] 1 test.`
> 若想看「红」:临时把 `StartupBanner()` 改为不含 `M148` 再跑,确认失败,再改回。

- [ ] **Step 3: 构建 chrome**

Run(在 `chromium/src`): `autoninja -C out/mac/arm64/dev chrome`
Expected: 构建成功;产物在 `<repo>/build/mac/arm64/dev/`(经 out 链接)。

- [ ] **Step 4: 启动并校验 banner 与品牌**

Run:
```bash
ls ../../build/mac/arm64/dev/Chromium.app  # 经 out 链接可见
out/mac/arm64/dev/Chromium.app/Contents/MacOS/* --no-sandbox 2>&1 | grep "\[teleport\] 闪现 overlay active (M148)"
```
Expected: 命中 banner 行;应用显示名为「闪现」(关于页 / Dock),磁盘为 `Teleport.app` 系列(ASCII)。

- [ ] **Step 5: 校验 apply_patches 幂等(干净 sync 后)**

Run:
```bash
git -C chromium/src checkout -- . && python scripts/sync.py
python scripts/apply_patches.py && python scripts/apply_patches.py
```
Expected: 干净树全部应用成功,第二次为 no-op。

- [ ] **Step 6: 固化 smoke 检查清单**

把 Step 1–5 的命令与期望写入 `scripts/smoke_check.md`(中文清单),并:
```bash
git add scripts/smoke_check.md
git commit -m "docs: add build smoke-check checklist"
```

---

## 自查(spec 覆盖)

- §2 范围三件事 → Task 6/9/10(模块+注入)、Task 11(品牌化)、Task 3(patch 应用):覆盖。
- §5 布局 → Task 1/2/6/7 创建 `src/`、`scripts/`、`patches/`、`branding/`、`build/`、`.gitignore`:覆盖。
- §6 检出/两链接/Windows/退路 → Task 4(链接)、Task 8(检出+GN 风险实测+退路):覆盖。
- §7/§8 两类 overlay + 一文件一 patch + 幂等/fail-fast → Task 3:覆盖。
- §9 品牌化两层 → Task 11:覆盖。
- §10 模块+trivial 证明 → Task 6 + Task 12 Step 4:覆盖。
- §11 构建流程/产物位置 → Task 7/8/12:覆盖。
- §12 验证 → Task 12:覆盖。
- §13 TDD 范围 → 产品代码 Task 6 走 gtest;脚本仅 Task 2/3/5 测核心逻辑:覆盖。
- §14 错误处理 → bootstrap/sync/apply_patches 实现含 fail-fast 与友好报错:覆盖。
- §15 实现期核对项 → Task 8(GN 风险)、Task 9/10/11(版本相关路径现场确定):覆盖。
