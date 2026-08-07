# Chromium 基线升级实施计划（M148 → M151）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Chromium overlay 的上游基线从 M148 升到 M151，并建立可复用的 patch 迁移工具链与上游发布跟踪机制，验证到能出 canary 包（不发布）。

**Architecture:** 用 git 自带的三方合并（`git rebase --onto` 内部的 `merge-ort`）把 105 个 patch 从旧基线搬到新基线，再从结果重新导出 patch 文件；导出时按「patch 类 / branding 类 / 生成物类」三分类并带安全阀，未归类改动直接报错。检出目录按上游发布分支（`MAJOR.MINOR.BUILD`）划分并由 `CHROMIUM_VERSION` 派生，使安全补丁跟进复用同一检出、里程碑跃迁才新建检出。

**Tech Stack:** Python 3.13（`uv` 管理，pytest）、git、depot_tools（gclient / autoninja）、GN / Siso、Chromium M151。

**设计依据：** `docs/superpowers/specs/2026-08-06-chromium-milestone-upgrade-design.md`

## Global Constraints

- 上游基线：`CHROMIUM_VERSION = 151.0.7922.76`（已提交于 `c223c9d`）
- 产品版本：`TELEPORT_VERSION = 0.2.0.0`（已提交于 `c223c9d`）
- 旧基线（rebase 的 base）：`148.0.7778.180`
- 新检出：`~/workspace/chromium/151.0.7922`（已建，`gclient sync` 进行中）
- 旧检出：`/Users/liulichao/workspace/teleport/chromium`（M148，**原地保留不动**，回退用）；`~/workspace/chromium/148.0.7778` 符号链接已指向它
- 工作分支：`chore/chromium-151-upgrade`，worktree 位于 `.claude/worktrees/chromium-151-upgrade`
- 语言：Markdown 文档用简体中文；代码、注释、提交信息、脚本、配置一律英文
- 提交规范：Conventional Commits
- 完成定义终点：`package.py --channel canary` 出包成功，**不加 `--distribute`**
- fairyland 仓库**不改任何代码**，仅作为 G4 的联调对端
- 测试不得跳过、禁用或注释；每次测试运行必须全绿

## File Structure

**新建**

| 路径 | 职责 |
|---|---|
| `scripts/check_upstream_release.py` | 查 Chrome VersionHistory API，判定「同分支有新 PATCH / 上游已切新 BUILD / 已最新」 |
| `scripts/export_patches.py` | 从 rebase 结果重新导出 patch 文件，含三类分类与安全阀 |
| `scripts/rebase_overlay.py` | 编排三方合并 rebase 流程 |
| `scripts/tests/test_check_upstream_release.py` | 版本解析 / 分类判定的单测（不测网络） |
| `scripts/tests/test_export_patches.py` | 三类分类与安全阀的单测 |
| `docs/chromium-upgrade-runbook.md` | 里程碑升级与安全补丁跟进两条路径的操作手册 |

**修改**

| 路径 | 改动 |
|---|---|
| `scripts/_lib.py` | 检出路径按发布分支派生；新增 `TELEPORT_CHROMIUM_ROOT`、`pinned_chromium_version()`、`release_branch()`、`repoint_dir_link()` |
| `scripts/bootstrap.py` | `build` 链接指向不符时重建 |
| `scripts/branding_strings.py` | 新增 `touched_paths()`，暴露它改写的全部相对路径 |
| `scripts/tests/test_lib.py` | 更新受影响的默认路径断言，新增派生逻辑测试 |
| `scripts/tests/test_bootstrap.py` | 新增 `build` 链接重建测试 |
| `patches/**/*.patch` | 全部重新导出；其中 2 个人工重写 |
| `src/browser/enterprise/teleport_voluntary_signin.{h,cc}` | 上游 API 迁移 |
| `CLAUDE.md` | 基线版本、检出布局、新脚本、gotcha 更新 |
| `docs/tech-debt.md` | TD-016 现状修订 |

**任务并行性**：Task 1 → Task 2 有依赖（同一 `_lib`）。Task 3、Task 4、Task 5 彼此无共享文件，可并行派发。Task 6 起必须串行（依赖真实检出状态）。

---

### Task 1: `_lib.py` 检出路径按发布分支派生

**Files:**
- Modify: `scripts/_lib.py`
- Test: `scripts/tests/test_lib.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `_lib.parse_four_segment(text: str) -> str`
  - `_lib.pinned_chromium_version(root: Path | None = None) -> str`
  - `_lib.release_branch(version: str) -> str`
  - `_lib.chromium_root() -> Path`
  - `_lib.chromium_dir(root: Path | None = None) -> Path`（语义变更）
  - `_lib.chromium_src(root: Path | None = None) -> Path`（不变，基于 `chromium_dir`）

- [ ] **Step 1: 写失败测试**

追加到 `scripts/tests/test_lib.py`：

```python
def test_parse_four_segment_ok():
    assert _lib.parse_four_segment(" 151.0.7922.76\n") == "151.0.7922.76"


def test_parse_four_segment_rejects_three(tmp_path: Path):
    with pytest.raises(ValueError):
        _lib.parse_four_segment("151.0.7922")


def test_parse_four_segment_rejects_non_numeric():
    with pytest.raises(ValueError):
        _lib.parse_four_segment("151.0.7922.beta")


def test_release_branch_drops_patch():
    assert _lib.release_branch("151.0.7922.76") == "151.0.7922"


def test_pinned_chromium_version_reads_file(tmp_path: Path):
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.pinned_chromium_version(tmp_path) == "151.0.7922.76"


def test_chromium_root_honors_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    assert _lib.chromium_root() == tmp_path / "roots"


def test_chromium_root_default(monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_ROOT", raising=False)
    assert _lib.chromium_root() == Path.home() / "workspace" / "chromium"


def test_chromium_dir_derives_from_pinned_version(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.chromium_dir(tmp_path) == tmp_path / "roots" / "151.0.7922"


def test_chromium_dir_env_overrides_derivation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.chromium_dir(tmp_path) == tmp_path / "explicit"


def test_chromium_src_under_derived_dir(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.chromium_src(tmp_path) == tmp_path / "roots" / "151.0.7922" / "src"
```

同时**修改**现有的 `test_chromium_src_default`（`scripts/tests/test_lib.py:60`），它断言旧的 `<repo>/chromium` 默认值，改为：

```python
def test_chromium_src_default(monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    monkeypatch.delenv("TELEPORT_CHROMIUM_ROOT", raising=False)
    src = _lib.chromium_src()
    # Derived from the repo's own CHROMIUM_VERSION under the default root.
    assert src.parent.name == _lib.release_branch(_lib.pinned_chromium_version())
    assert src.name == "src"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_lib.py -v`
Expected: 新增用例全部 FAIL，报 `AttributeError: module '_lib' has no attribute 'parse_four_segment'` 等

- [ ] **Step 3: 实现**

在 `scripts/_lib.py` 中，把现有的 `chromium_dir` / `chromium_src` 替换为：

```python
# Default parent of all upstream checkouts. One subdirectory per upstream
# release branch (MAJOR.MINOR.BUILD), so a security-patch bump reuses the same
# checkout while a milestone jump gets a fresh one.
_DEFAULT_CHROMIUM_ROOT = Path.home() / "workspace" / "chromium"


def parse_four_segment(text: str) -> str:
    """Validate a 4-segment dotted version; return it stripped."""
    parts = text.strip().split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise ValueError(f"expected 4-segment numeric version, got {text!r}")
    return ".".join(parts)


def pinned_chromium_version(root: Path | None = None) -> str:
    """The upstream version pinned in CHROMIUM_VERSION."""
    text = ((root or repo_root()) / "CHROMIUM_VERSION").read_text()
    return parse_four_segment(text)


def release_branch(version: str) -> str:
    """MAJOR.MINOR.BUILD — identifies exactly one upstream release branch
    (refs/branch-heads/<BUILD>). PATCH moves stay inside this branch, so the
    checkout directory is keyed on this rather than the full version."""
    return ".".join(parse_four_segment(version).split(".")[:3])


def chromium_root() -> Path:
    """Parent dir holding one checkout per upstream release branch.
    Honors $TELEPORT_CHROMIUM_ROOT."""
    env = os.environ.get("TELEPORT_CHROMIUM_ROOT")
    return Path(env) if env else _DEFAULT_CHROMIUM_ROOT


def chromium_dir(root: Path | None = None) -> Path:
    """Chromium checkout for the pinned baseline: <root>/<MAJOR.MINOR.BUILD>.

    Deriving from CHROMIUM_VERSION means switching branches automatically
    points at the matching checkout — no environment variable to forget.
    $TELEPORT_CHROMIUM_DIR still overrides the whole path (CI / ad-hoc).
    """
    env = os.environ.get("TELEPORT_CHROMIUM_DIR")
    if env:
        return Path(env)
    return chromium_root() / release_branch(pinned_chromium_version(root))


def chromium_src(root: Path | None = None) -> Path:
    return chromium_dir(root) / "src"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_lib.py -v`
Expected: PASS

- [ ] **Step 5: 跑全量脚本测试，确认没打破别的**

Run: `uv run pytest`
Expected: 全绿。若 `test_sync.py` / `test_bootstrap.py` / `test_package*.py` 因路径默认值变化失败，按新语义修正断言（**不得跳过测试**）。

- [ ] **Step 6: 提交**

```bash
git add scripts/_lib.py scripts/tests/test_lib.py
git commit -m "refactor(scripts): derive chromium checkout path from the pinned release branch

Checkout dirs are now <TELEPORT_CHROMIUM_ROOT>/<MAJOR.MINOR.BUILD>, derived
from CHROMIUM_VERSION. A security-patch bump stays inside one checkout; only a
milestone jump creates a new one. Switching branches now selects the matching
checkout automatically, removing the 'forgot to export TELEPORT_CHROMIUM_DIR
and wrote to a phantom path' failure mode."
```

---

### Task 2: `bootstrap.py` 的 `build` 链接可重建

**Files:**
- Modify: `scripts/_lib.py`, `scripts/bootstrap.py`
- Test: `scripts/tests/test_lib.py`, `scripts/tests/test_bootstrap.py`

**Interfaces:**
- Consumes: Task 1 的 `_lib.chromium_src()`
- Produces: `_lib.repoint_dir_link(link: Path, target: Path) -> None`

**背景：** 切换基线时 `<repo>/build` 需指向新检出的 `src/out`，但 `create_dir_link()` 在链接已指向别处时抛 `RuntimeError`。`build` 是纯访问入口，重指安全；而 `<checkout>/src/teleport` 指向别处意味着跨 worktree 污染，**必须保持严格抛错**，不要一起放宽。

- [ ] **Step 1: 写失败测试**

追加到 `scripts/tests/test_lib.py`：

```python
def test_repoint_dir_link_replaces_existing(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, a)
    _lib.repoint_dir_link(link, b)
    assert Path(os.path.realpath(link)) == b.resolve()


def test_repoint_dir_link_is_idempotent(tmp_path: Path):
    target = tmp_path / "t"
    target.mkdir()
    link = tmp_path / "link"
    _lib.repoint_dir_link(link, target)
    _lib.repoint_dir_link(link, target)
    assert Path(os.path.realpath(link)) == target.resolve()


def test_repoint_dir_link_refuses_nonempty_real_dir(tmp_path: Path):
    target = tmp_path / "t"
    target.mkdir()
    link = tmp_path / "link"
    link.mkdir()
    (link / "stuff.txt").write_text("do not delete me")
    with pytest.raises(RuntimeError):
        _lib.repoint_dir_link(link, target)
```

追加到 `scripts/tests/test_bootstrap.py`：

```python
def test_bootstrap_repoints_stale_build_link(tmp_path: Path, monkeypatch):
    """A build/ link left over from the previous baseline must be repointed,
    not raise."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")

    old_src = tmp_path / "old" / "src"
    (old_src / "out").mkdir(parents=True)
    (old_src / ".git").mkdir()
    new_src = tmp_path / "roots" / "151.0.7922" / "src"
    (new_src / ".git").mkdir(parents=True)

    _lib.create_dir_link(repo / "build", old_src / "out")

    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "/usr/bin/gclient")

    assert bootstrap.main(["--skip-sync", "--root", str(repo)]) == 0
    assert Path(os.path.realpath(repo / "build")) == (new_src / "out").resolve()
```

> `--root` 是本步要给 `bootstrap.py` 新增的参数（现有 `main()` 直接调 `repo_root()`，无法注入）。有了它就不需要再 monkeypatch `repo_root`。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_lib.py scripts/tests/test_bootstrap.py -v`
Expected: FAIL（`repoint_dir_link` 不存在；bootstrap 抛 `RuntimeError`）

- [ ] **Step 3: 实现**

在 `scripts/_lib.py` 的 `create_dir_link` 之后加：

```python
def repoint_dir_link(link: Path, target: Path) -> None:
    """Like create_dir_link, but an existing *link* pointing elsewhere is
    replaced instead of raising. Only for links that are pure access
    conveniences (e.g. <repo>/build). A real non-empty directory is still
    refused — we never delete data.
    """
    link = Path(link)
    if link.is_symlink() or (is_windows() and link.exists() and _points_somewhere(link)):
        if Path(os.path.realpath(link)) == Path(target).resolve():
            return
        link.unlink() if link.is_symlink() else link.rmdir()
    create_dir_link(link, target)
```

在 `scripts/bootstrap.py` 中，把 `create_dir_link(root / "build", out)` 改为 `repoint_dir_link(root / "build", out)`，并把 import 改成：

```python
from _lib import (chromium_dir, chromium_src, create_dir_link, repo_root,
                  repoint_dir_link)
```

`create_dir_link(src / "teleport", root / "src")` **保持不变**（严格语义）。

同时把 `bootstrap.py` 的 `main()` 增加 `--root` 参数支持（若尚未有）以便测试注入，并在文件顶部 docstring 里补一句说明 `build` 链接可重建、`teleport` 链接严格。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_lib.py scripts/tests/test_bootstrap.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/_lib.py scripts/bootstrap.py scripts/tests/test_lib.py scripts/tests/test_bootstrap.py
git commit -m "feat(scripts): repoint the build link when the baseline changes

Switching baselines leaves <repo>/build pointing at the previous checkout's
out/. That link is a pure access convenience, so repoint it rather than
failing. The <checkout>/src/teleport link keeps strict semantics: pointing
elsewhere means cross-worktree contamination and must surface."
```

---

### Task 3: `check_upstream_release.py` 上游发布跟踪

**Files:**
- Create: `scripts/check_upstream_release.py`
- Test: `scripts/tests/test_check_upstream_release.py`

**Interfaces:**
- Consumes: `_lib.pinned_chromium_version()`、`_lib.release_branch()`、`_lib.parse_four_segment()`（Task 1）
- Produces:
  - `version_key(v: str) -> tuple[int, int, int, int]`
  - `classify(pinned: str, released: dict[str, list[str]]) -> Verdict`
  - `Verdict` 具名元组：`status: str`（`"current"` / `"patch_available"` / `"milestone_moved"`）、`latest: str | None`、`platforms_disagree: bool`
  - `fetch_released_versions(platform: str) -> list[str]`（网络，不测）

**设计要点：** `released` 是「平台 → 已发布版本列表」的映射。判定只看桌面平台（`mac`、`win64`）；`linux` 仅作参考输出，不参与判定（实测 linux 是同序列子集，参与判定会永远显示落后）。

- [ ] **Step 1: 写失败测试**

创建 `scripts/tests/test_check_upstream_release.py`：

```python
import pytest

import check_upstream_release as cur


def test_version_key_orders_numerically():
    assert cur.version_key("151.0.7922.9") < cur.version_key("151.0.7922.76")
    assert cur.version_key("150.0.7871.213") < cur.version_key("151.0.7922.34")


def test_classify_current_when_pin_is_latest():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.76", "151.0.7922.75"],
                                       "win64": ["151.0.7922.76"]})
    assert v.status == "current"
    assert v.platforms_disagree is False


def test_classify_patch_available_same_branch():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.132", "151.0.7922.76"],
                                       "win64": ["151.0.7922.132"]})
    assert v.status == "patch_available"
    assert v.latest == "151.0.7922.132"


def test_classify_milestone_moved_on_new_build():
    v = cur.classify("151.0.7922.76", {"mac": ["152.0.8001.40"],
                                       "win64": ["152.0.8001.40"]})
    assert v.status == "milestone_moved"
    assert v.latest == "152.0.8001.40"


def test_classify_flags_desktop_platform_disagreement():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.90"],
                                       "win64": ["151.0.7922.76"]})
    assert v.platforms_disagree is True


def test_classify_ignores_linux_for_the_verdict():
    """Linux ships a subset of the desktop sequence; it must not make us think
    we are ahead or behind."""
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.76"],
                                       "win64": ["151.0.7922.76"],
                                       "linux": ["151.0.7922.75"]})
    assert v.status == "current"
    assert v.platforms_disagree is False


def test_classify_rejects_empty_desktop_data():
    with pytest.raises(ValueError):
        cur.classify("151.0.7922.76", {"linux": ["151.0.7922.75"]})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_check_upstream_release.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'check_upstream_release'`

- [ ] **Step 3: 实现**

创建 `scripts/check_upstream_release.py`：

```python
"""Report whether upstream has shipped a newer Chrome than the pinned baseline.

Uses the Chrome VersionHistory API, which lists only *released* versions. The
chromium/src tag list must NOT be used for this: release sub-branches
(refs/branch-heads/<BUILD>_<n>) allocate PATCH numbers in blocks, so the tag
list contains many builds that were never shipped, and each platform ships its
own PATCH number.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import NamedTuple

from _lib import parse_four_segment, pinned_chromium_version, release_branch

API = ("https://versionhistory.googleapis.com/v1/chrome/platforms/"
       "{platform}/channels/stable/versions")

# Verdict-bearing platforms. mac and win64 have historically shipped the exact
# same desktop sequence; linux ships a subset of it, so including linux would
# permanently read as "behind". linux is fetched for information only.
DESKTOP = ("mac", "win64")
INFO_ONLY = ("linux",)


class Verdict(NamedTuple):
    status: str          # "current" | "patch_available" | "milestone_moved"
    latest: str | None
    platforms_disagree: bool


def version_key(v: str) -> tuple[int, int, int, int]:
    a, b, c, d = parse_four_segment(v).split(".")
    return (int(a), int(b), int(c), int(d))


def classify(pinned: str, released: dict[str, list[str]]) -> Verdict:
    """Compare the pin against what the desktop platforms actually shipped."""
    latest_per_platform = {}
    for platform in DESKTOP:
        versions = released.get(platform) or []
        if versions:
            latest_per_platform[platform] = max(versions, key=version_key)
    if not latest_per_platform:
        raise ValueError(f"no released versions for any of {DESKTOP}")

    disagree = len(set(latest_per_platform.values())) > 1
    latest = max(latest_per_platform.values(), key=version_key)

    if version_key(latest) <= version_key(pinned):
        return Verdict("current", latest, disagree)
    if release_branch(latest) != release_branch(pinned):
        return Verdict("milestone_moved", latest, disagree)
    return Verdict("patch_available", latest, disagree)


def fetch_released_versions(platform: str) -> list[str]:
    with urllib.request.urlopen(API.format(platform=platform), timeout=30) as r:
        payload = json.load(r)
    return [entry["version"] for entry in payload.get("versions", [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether upstream shipped a newer Chrome than our pin")
    parser.parse_args(argv)

    pinned = pinned_chromium_version()
    released = {p: fetch_released_versions(p) for p in DESKTOP + INFO_ONLY}
    verdict = classify(pinned, released)

    print(f"pinned:        {pinned}  (release branch {release_branch(pinned)})")
    for p in DESKTOP + INFO_ONLY:
        newest = max(released[p], key=version_key) if released[p] else "(none)"
        tag = "" if p in DESKTOP else "  [informational]"
        print(f"  {p:<8} {newest}{tag}")

    if verdict.platforms_disagree:
        print("\nWARNING: mac and win64 shipped different versions. The "
              "'one pin serves all desktop platforms' assumption no longer "
              "holds — decide by hand which to track.", file=sys.stderr)

    print()
    if verdict.status == "current":
        print("Up to date. No action.")
    elif verdict.status == "patch_available":
        print(f"Security patch available: {pinned} -> {verdict.latest}\n"
              f"  Same release branch: reuse the existing checkout.\n"
              f"  Update CHROMIUM_VERSION, then run sync.py, apply_patches.py, "
              f"and an incremental build.")
    else:
        print(f"Upstream moved to a new release branch: {verdict.latest}\n"
              f"  Branch {release_branch(pinned)} stops receiving fixes.\n"
              f"  A milestone upgrade is required — see "
              f"docs/chromium-upgrade-runbook.md.")

    print("\nSeverity of the fixes in that release is NOT in this API. Check "
          "https://chromereleases.googleblog.com/feeds/posts/default")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_check_upstream_release.py -v`
Expected: PASS

- [ ] **Step 5: 真跑一次（网络）确认输出合理**

Run: `uv run python scripts/check_upstream_release.py`
Expected: 打印 pinned `151.0.7922.76`，mac / win64 均为 `151.0.7922.76`，结论 `Up to date. No action.`，无平台分歧告警。

- [ ] **Step 6: 提交**

```bash
git add scripts/check_upstream_release.py scripts/tests/test_check_upstream_release.py
git commit -m "feat(scripts): track real upstream releases via the VersionHistory API

Repo tags are not releases: release sub-branches allocate PATCH numbers in
blocks and each platform ships its own number, so the tag list cannot answer
'did upstream actually ship'. The VersionHistory API can.

Verdict is driven by mac + win64 only (they ship the same desktop sequence);
linux ships a subset and is reported for information. A mac/win64 divergence
warns loudly, since it would break the single-pin assumption."
```

---

### Task 4: `export_patches.py` 重新导出 patch（含三类分类与安全阀）

**Files:**
- Create: `scripts/export_patches.py`
- Modify: `scripts/branding_strings.py`
- Test: `scripts/tests/test_export_patches.py`

**Interfaces:**
- Consumes: `_lib.repo_root()`、`_lib.chromium_src()`
- Produces:
  - `branding_strings.touched_paths() -> set[str]`（相对 `chromium/src` 的路径）
  - `patch_paths(repo_root: Path) -> set[str]`
  - `branding_paths(repo_root: Path) -> set[str]`
  - `generated_paths(repo_root: Path) -> set[str]`
  - `classify_change(path: str, patches: set[str], branding: set[str], generated: set[str]) -> str`（返回 `"patch"` / `"branding"` / `"generated"` / `"unknown"`）
  - `export(repo_root: Path, src: Path, tag: str) -> list[str]`

**这是本计划最需要测试的一环**：漏导出等于静默丢改动，要到下一次 `apply_patches.py` 才暴露。

- [ ] **Step 1: 先给 `branding_strings.py` 加 `touched_paths()` 及其测试**

在 `scripts/branding_strings.py` 的 `_GRD_TARGETS` 定义之后追加：

```python
def touched_paths() -> set[str]:
    """Every chromium/src-relative path this module rewrites.

    export_patches.py consumes this so the generated-file set is derived rather
    than hand-maintained — a hand-written list would silently drift the moment a
    target is added here.
    """
    paths: set[str] = set()
    for target in _GRD_TARGETS:
        grd = PurePosixPath(target["grd"])
        paths.add(str(grd))
        paths.update(target["xtb"].values())
        for grdp in target["grdp"]:
            paths.add(str(grd.parent / grdp))
    return paths
```

并在文件顶部加 `from pathlib import PurePosixPath`（若已 import `Path` 则一并加）。

新增测试到 `scripts/tests/test_branding_strings.py`：

```python
def test_touched_paths_covers_every_target():
    paths = branding_strings.touched_paths()
    # Every grd and every xtb must be present.
    assert "chrome/app/chromium_strings.grd" in paths
    assert "chrome/app/resources/chromium_strings_zh-CN.xtb" in paths
    assert "components/strings/components_strings_zh-TW.xtb" in paths
    # grdp entries resolve relative to their grd's directory.
    assert "chrome/app/settings_chromium_strings.grdp" in paths
    assert "components/autofill_strings.grdp" in paths
    # No path may be absolute or contain a backslash.
    assert all(not p.startswith("/") and "\\" not in p for p in paths)
```

Run: `uv run pytest scripts/tests/test_branding_strings.py -k touched_paths -v`
Expected: 先 FAIL（函数不存在），实现后 PASS。

> 注：`components/autofill_strings.grdp` 是按 `components/components_strings.grd` 的父目录解析得到的。执行时若实际 grd 父目录不同，以真实解析结果为准修正断言，**不要改实现去迁就断言**。

- [ ] **Step 2: 写 `export_patches` 的失败测试**

创建 `scripts/tests/test_export_patches.py`：

```python
from pathlib import Path

import pytest

import export_patches as ep


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "browser").mkdir(parents=True)
    (repo / "patches" / "chrome" / "browser" / "foo.cc.patch").write_text("x")
    (repo / "patches" / "net" / "bar.h.patch").write_text("x")
    (repo / "branding" / "chrome" / "app" / "theme").mkdir(parents=True)
    (repo / "branding" / "chrome" / "app" / "theme" / "logo.png").write_bytes(b"\x89PNG")
    return repo


def test_patch_paths_strips_prefix_and_suffix(tmp_path: Path):
    repo = _make_repo(tmp_path)
    assert ep.patch_paths(repo) == {"chrome/browser/foo.cc", "net/bar.h"}


def test_branding_paths_lists_files_only(tmp_path: Path):
    repo = _make_repo(tmp_path)
    assert ep.branding_paths(repo) == {"chrome/app/theme/logo.png"}


def test_classify_patch(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/browser/foo.cc", p, b, g) == "patch"


def test_classify_branding(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/app/theme/logo.png", p, b, g) == "branding"


def test_classify_generated(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/VERSION", p, b, g) == "generated"


def test_classify_unknown_is_the_safety_valve(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/browser/surprise.cc", p, b, g) == "unknown"


def test_generated_paths_includes_version_and_engine_header(tmp_path: Path):
    g = ep.generated_paths(tmp_path)
    assert "chrome/VERSION" in g
    assert "components/version_info/teleport_engine_version.h" in g


def test_generated_paths_includes_branding_strings_targets(tmp_path: Path):
    g = ep.generated_paths(tmp_path)
    assert "chrome/app/chromium_strings.grd" in g


def test_assert_all_classified_raises_on_unknown(tmp_path: Path):
    repo = _make_repo(tmp_path)
    with pytest.raises(RuntimeError, match="unclassified"):
        ep.assert_all_classified(repo, ["chrome/browser/surprise.cc"])


def test_assert_all_classified_passes_on_known(tmp_path: Path):
    repo = _make_repo(tmp_path)
    ep.assert_all_classified(repo, ["chrome/browser/foo.cc",
                                    "chrome/app/theme/logo.png",
                                    "chrome/VERSION"])
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_export_patches.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'export_patches'`

- [ ] **Step 4: 实现**

创建 `scripts/export_patches.py`：

```python
"""Re-export patches/ from a chromium/src tree that already carries the overlay.

Run this after rebase_overlay.py has moved the overlay onto a new upstream tag.
Every file changed in the tree must fall into exactly one of three classes:

  patch      -> re-exported as patches/<path>.patch
  branding   -> skipped (branding/ is a whole-file copy overlay, not a patch)
  generated  -> skipped (produced at overlay time from CHROMIUM_VERSION /
                TELEPORT_VERSION, or by branding_strings.py)

Anything else is a hard error. Silently skipping an unclassified change would
drop it from patches/, and the loss would only surface at the next
apply_patches.py run.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import branding_strings
from _lib import chromium_src, repo_root

# Written at overlay time by generate_version.py.
_VERSION_GENERATED = (
    "chrome/VERSION",
    "components/version_info/teleport_engine_version.h",
)


def patch_paths(root: Path) -> set[str]:
    """Upstream paths covered by patches/, derived from the tree itself."""
    base = Path(root) / "patches"
    return {
        str(p.relative_to(base))[: -len(".patch")]
        for p in base.rglob("*.patch") if p.is_file()
    }


def branding_paths(root: Path) -> set[str]:
    base = Path(root) / "branding"
    if not base.exists():
        return set()
    return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}


def generated_paths(root: Path) -> set[str]:
    return set(_VERSION_GENERATED) | branding_strings.touched_paths()


def classify_change(path: str, patches: set[str], branding: set[str],
                    generated: set[str]) -> str:
    if path in patches:
        return "patch"
    if path in branding:
        return "branding"
    if path in generated:
        return "generated"
    return "unknown"


def assert_all_classified(root: Path, changed: list[str]) -> None:
    patches, branding, generated = (patch_paths(root), branding_paths(root),
                                    generated_paths(root))
    unknown = [p for p in changed
               if classify_change(p, patches, branding, generated) == "unknown"]
    if unknown:
        listing = "\n  ".join(sorted(unknown))
        raise RuntimeError(
            "unclassified changes in the chromium tree — refusing to export.\n"
            "Each must become a patch (add patches/<path>.patch), a branding\n"
            "overlay (add branding/<path>), or a generated file (teach\n"
            "export_patches.py about it):\n  " + listing)


def changed_paths(src: Path, tag: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", tag],
        cwd=src, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def export(root: Path, src: Path, tag: str) -> list[str]:
    """Rewrite patches/ from the tree's diff against `tag`. Returns the paths
    whose patch file changed."""
    assert_all_classified(root, changed_paths(src, tag))
    rewritten = []
    for rel in sorted(patch_paths(root)):
        diff = subprocess.run(
            ["git", "diff", tag, "--", rel],
            cwd=src, capture_output=True, text=True, check=True).stdout
        if not diff.strip():
            raise RuntimeError(
                f"patch target has no diff against {tag}: {rel}\n"
                "The patch would export empty. Either the change was lost in "
                "the rebase, or the patch is obsolete and should be deleted.")
        dest = Path(root) / "patches" / f"{rel}.patch"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_text() != diff:
            dest.write_text(diff)
            rewritten.append(rel)
    return rewritten


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-export patches/ from chromium/src")
    parser.add_argument("--tag", required=True,
                        help="upstream tag the overlay now sits on, e.g. 151.0.7922.76")
    parser.add_argument("--root", type=Path, default=repo_root())
    args = parser.parse_args(argv)

    src = chromium_src(args.root)
    rewritten = export(args.root, src, args.tag)
    print(f"re-exported {len(rewritten)} patch file(s) against {args.tag}")
    for rel in rewritten:
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_export_patches.py scripts/tests/test_branding_strings.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add scripts/export_patches.py scripts/branding_strings.py \
        scripts/tests/test_export_patches.py scripts/tests/test_branding_strings.py
git commit -m "feat(scripts): re-export patches from a rebased chromium tree

Classifies every changed file as patch / branding / generated and refuses to
export when anything is unclassified. Silently skipping an unknown change would
drop it from patches/ and the loss would only surface at the next
apply_patches.py run.

The generated set is derived from branding_strings.touched_paths() rather than
hand-listed, so it cannot drift when a rebrand target is added."
```

---

### Task 5: `rebase_overlay.py` 三方合并编排

**Files:**
- Create: `scripts/rebase_overlay.py`

**Interfaces:**
- Consumes: `_lib.chromium_src()`、`_lib.repo_root()`、`export_patches.{patch_paths,branding_paths}`、`apply_patches.py --skip-branding`
- Produces: CLI，无供其他任务调用的函数
- **本任务需先给 `export_patches.py` 补一个公开访问器** `version_generated_paths(root: Path) -> set[str]`，返回 `_VERSION_GENERATED`（即 `chrome/VERSION` 与 `components/version_info/teleport_engine_version.h`）。现在这份路径集是模块私有的，而 `rebase_overlay` 需要它来精确 stage。写成访问器而不是在 `rebase_overlay` 里现算 `generated_paths() - branding_strings.touched_paths()`——后者是同一件事的绕远写法，且日后会被误读。

**Task 4 落地后的既有事实（写代码前必须知道）：**
- `apply_patches.py` 已有 `--skip-branding`，默认行为不变
- `export_patches.py` 已有 `is_injected_artifact()`，识别 `teleport` 符号链接与 `third_party/teleport_sparkle/`，二者**不得** stage 进 commit
- `branding_strings.main()` 硬编码 `chromium_src(repo_root())`、无视 `--root`（既有耦合）。因为本流程走 `--skip-branding`，该调用被完全跳过，故不受影响；但若将来要在非默认 root 上跑品牌化，需经 `TELEPORT_CHROMIUM_DIR` 而非 `--root`

**不写单测**：编排逻辑依赖真实 git 仓库状态，按项目约定（工具脚本只在有价值处写 pytest）此处价值在 Task 4 的分类逻辑，已覆盖。

**与 spec 的一处有意偏离**：spec §7.5 把「保证旧基线 tag 可达」列为 `sync.py` 的改动。本计划改放在 `rebase_overlay.py` 的 `ensure_tag()` 里，因为这是 **rebase 的前置条件而非 sync 的职责**——`sync.py` 只负责把树同步到 pin，让它去 fetch 一个与当前 pin 无关的历史 tag 会模糊职责，且每次安全补丁跟进都会白跑一次。执行本任务后需回头把 spec §7.5 的表格改为记录此决定。

- [ ] **Step 1: 实现**

创建 `scripts/rebase_overlay.py`：

```python
"""Move the overlay from one upstream baseline to another via git's three-way merge.

The overlay normally lives as uncommitted working-tree changes, which git
cannot merge. This commits it on top of the OLD baseline, then rebases that
commit onto the NEW one: git then does a per-file three-way merge with
base = old upstream file, ours = new upstream file, theirs = our modified file.
Pure context drift merges automatically; only genuine overlaps conflict, and
they conflict inside real source with full context rather than as .rej files.

rebase (not merge) is deliberate: `git merge <new tag>` would use the point
where the old release branch forked from trunk as the merge base, dragging the
old branch's own fixes into the merge. `rebase --onto` pins the base to the old
tag exactly, so only "our changes" x "old->new upstream delta" participate.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import export_patches
from _lib import chromium_src, repo_root

WORK_BRANCH = "teleport/overlay-rebase"


def git(src: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=src, text=True,
                          capture_output=True, check=check)


def ensure_tag(src: Path, tag: str) -> None:
    """The old baseline's objects must be reachable or there is no merge base.
    A checkout created with `gclient sync --no-history` will not have them."""
    if git(src, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
        return
    print(f"fetching tag {tag} (needed as the three-way merge base) ...")
    git(src, "fetch", "origin", "tag", tag)


def tracked_overlay_paths(root: Path) -> list[str]:
    """Exactly the paths the overlay may touch. `git add -A` is unusable here:
    a synced tree carries DEPS checkouts and build products we must not commit.

    Deliberately EXCLUDES branding_strings' ~58 rewrite targets: the overlay is
    built with --skip-branding (see below), so those files are unmodified, and
    committing rebranded content would bake it into the exported patches.
    Also excludes injected artifacts (the teleport symlink, the Sparkle copy) —
    they are the injection mechanism, not overlay content."""
    return sorted(export_patches.patch_paths(root)
                  | export_patches.branding_paths(root)
                  | export_patches.version_generated_paths(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebase the teleport overlay from one upstream tag onto another")
    parser.add_argument("--from-tag", required=True, help="old baseline, e.g. 148.0.7778.180")
    parser.add_argument("--onto-tag", required=True, help="new baseline, e.g. 151.0.7922.76")
    parser.add_argument("--root", type=Path, default=repo_root())
    args = parser.parse_args(argv)

    root, src = args.root, chromium_src(args.root)
    if not (src / ".git").exists():
        print(f"error: {src} is not a chromium checkout", file=sys.stderr)
        return 1

    status = git(src, "status", "--porcelain").stdout
    if status.strip():
        print("error: chromium/src has local changes; commit or clean them first",
              file=sys.stderr)
        return 1

    ensure_tag(src, args.from_tag)
    ensure_tag(src, args.onto_tag)

    git(src, "checkout", "-B", WORK_BRANCH, args.from_tag)
    print(f"applying the overlay on top of {args.from_tag} ...")
    # --skip-branding is load-bearing, not an optimization. branding_strings
    # rewrites ~58 grd/grdp/xtb paths, 3 of which ALSO carry hand-authored
    # patches. With branding applied, `git diff <tag> -- <those 3>` captures the
    # rebranding too and export_patches would bake it into the patch files. The
    # rebranding is derived output, regenerated on every apply_patches run, so it
    # must never enter the commit that gets rebased.
    rc = subprocess.run([sys.executable, str(root / "scripts" / "apply_patches.py"),
                         "--root", str(root), "--skip-branding"]).returncode
    if rc != 0:
        return rc

    paths = tracked_overlay_paths(root)
    git(src, "add", "--", *paths)
    git(src, "commit", "-m", f"teleport overlay @{args.from_tag}")

    print(f"rebasing onto {args.onto_tag} ...")
    r = git(src, "rebase", "--onto", args.onto_tag, args.from_tag, check=False)
    if r.returncode != 0:
        conflicts = git(src, "diff", "--name-only", "--diff-filter=U").stdout
        print(r.stdout + r.stderr)
        print("\nCONFLICTS — resolve these in the tree, then "
              "`git add <file>` and `git rebase --continue`:\n"
              + (conflicts or "  (see git status)"), file=sys.stderr)
        print(f"\nWhen the rebase finishes, run:\n"
              f"  uv run python scripts/export_patches.py --tag {args.onto_tag}",
              file=sys.stderr)
        return 2

    print(f"rebase clean. Now run:\n"
          f"  uv run python scripts/export_patches.py --tag {args.onto_tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 冒烟检查（不改变仓库状态）**

Run: `uv run python scripts/rebase_overlay.py --help`
Expected: 打印参数说明，退出码 0

- [ ] **Step 3: 提交**

```bash
git add scripts/rebase_overlay.py
git commit -m "feat(scripts): rebase the overlay onto a new upstream tag

Commits the overlay on top of the old baseline so git's three-way merge can
move it, then rebases onto the new tag. Uses rebase rather than merge so the
merge base is exactly the old tag instead of the release branch's fork point.

Stages an explicit path set rather than 'git add -A': a synced tree carries
DEPS checkouts and build products that must never be committed."
```

---

### Task 6: G0 环境就绪与 dry-run 复核

**Files:** 无代码改动（产出为验证记录）

**前置：** 后台 `gclient sync` 已完成。

- [ ] **Step 1: 确认 sync 成功**

```bash
tail -20 /private/tmp/claude-501/-Users-liulichao-workspace-teleport/*/tasks/*.output
cd ~/workspace/chromium/151.0.7922/src && cat chrome/VERSION
```
Expected: `MAJOR=151 MINOR=0 BUILD=7922 PATCH=76`，sync 无报错

- [ ] **Step 2: 确认 PGO profile 两套都在（release 构建硬依赖，缺失会硬失败）**

```bash
cd ~/workspace/chromium/151.0.7922/src
ls chrome/build/pgo_profiles/*.profdata
ls v8/tools/builtins-pgo/profiles/x64.profile
```
Expected: 两者都存在。缺失则重跑 `gclient sync`（`.gclient` 已带 `checkout_pgo_profiles=True`）。

- [ ] **Step 3: 确认 rebase 前置条件（旧基线 tag 可达）**

```bash
cd ~/workspace/chromium/151.0.7922/src
git rev-parse --verify refs/tags/148.0.7778.180
git rev-parse --verify refs/tags/151.0.7922.76
```
Expected: 两个 tag 都解析成功

- [ ] **Step 4: 建 overlay 链接**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
uv run python scripts/bootstrap.py --skip-sync
```
Expected: 打印 `bootstrap complete: .../151.0.7922/src/teleport -> <worktree>/src, <worktree>/build -> .../151.0.7922/src/out`

- [ ] **Step 5: 用实际钉住的版本复跑 patch dry-run**

```bash
cd ~/workspace/chromium/151.0.7922/src
export GIT_INDEX_FILE=/tmp/idx151_76; rm -f "$GIT_INDEX_FILE"
git read-tree 151.0.7922.76
for p in $(find /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade/patches -name '*.patch' | sort); do
  if git apply --cached --check "$p" 2>/dev/null; then echo "CLEAN $p"
  elif git apply --cached --check --3way "$p" 2>/dev/null; then echo "3WAY $p"
  else echo "CONFLICT $p"; fi
done | awk '{print $1}' | sort | uniq -c
unset GIT_INDEX_FILE
```
Expected: 约 83 CLEAN / 20 3WAY / **2 CONFLICT**。CONFLICT 应恰为 `about_page.html.patch` 与 `status_box.html.patch`。若数字与 spec §3.1 有出入，记录实际值并在 Task 7 中按实际处理。

- [ ] **Step 6: 记录复核结果**

把实际 dry-run 数字追加到 spec 的 §3.1 表格下方作为「G0 实测复核」一行，提交：

```bash
git add docs/superpowers/specs/2026-08-06-chromium-milestone-upgrade-design.md
git commit -m "docs(teleport): record the G0 dry-run against the pinned 151.0.7922.76"
```

---

### Task 7: 执行 rebase 并重写两个 Lit 冲突 patch

**Files:**
- Modify: `patches/**/*.patch`（全部重新导出）
- Delete: `patches/chrome/browser/resources/settings/about_page/about_page.html.patch`
- Delete: `patches/components/policy/resources/webui/status_box.html.patch`
- Create: `patches/chrome/browser/resources/settings/about_page/about_page.html.ts.patch`
- Create: `patches/components/policy/resources/webui/status_box.html.ts.patch`

**背景：** 上游在 M151 把这两个文件迁到 Lit 模板形态（`.html` → `.html.ts`），原文件不存在，故原 patch 无处可打。参考本仓库自有的 `src/browser/resources/enroll/enroll_app.html.ts` 了解目标形态。

- [ ] **Step 1: 先记录旧 patch 的语义（重写的依据）**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
cat patches/chrome/browser/resources/settings/about_page/about_page.html.patch
cat patches/components/policy/resources/webui/status_box.html.patch
```
把每个 hunk 的**意图**写成清单（改了哪个元素、加了什么、删了什么），保存到 `/tmp` 备查。重写必须逐条对应，不能凭印象。

- [ ] **Step 2: 先删掉两个失效 patch，跑 rebase**

```bash
git rm patches/chrome/browser/resources/settings/about_page/about_page.html.patch
git rm patches/components/policy/resources/webui/status_box.html.patch
uv run python scripts/rebase_overlay.py --from-tag 148.0.7778.180 --onto-tag 151.0.7922.76
```
Expected: rebase 完成或停在冲突。若停在冲突，逐个解决（`git status` 列出），解完 `git add <file>` + `git rebase --continue`。

> 冲突解决原则：`components/policy/tools/generate_policy_source.py` 与 `tools/flags/generate_unexpire_flags.py` 的 `MAJOR=0` 补丁，**必须按同语义重解**（`is None` 判空、`m >= 0` 里程碑过滤），不得盲目接受三方合并结果。`tools/gritsettings/resource_ids.spec` 的冲突要确认 ID 区间不与上游新分配的区间重叠。

- [ ] **Step 3: 在 M151 树上重写两个 Lit patch**

在 `~/workspace/chromium/151.0.7922/src` 中直接编辑：
- `chrome/browser/resources/settings/about_page/about_page.html.ts`
- `components/policy/resources/webui/status_box.html.ts`

按 Step 1 记录的意图逐条落实。Lit 模板是 TS 模板字符串（`` html`...` ``），不是裸 HTML，属性绑定语法不同（`?disabled=${...}`、`@click=${...}`、`.prop=${...}`）。

- [ ] **Step 4: 导出全部 patch**

```bash
uv run python scripts/export_patches.py --tag 151.0.7922.76
```
Expected: 打印重新导出的 patch 数量。若报 `unclassified changes`，说明有改动既不属于 patch/branding/generated——按提示决定它该归哪一类，**不要放宽安全阀**。

- [ ] **Step 5: 验证幂等（G1 闸门）**

> **绝对不要在 chromium 检出里跑 `git clean -fdx`。** gclient 管理的 DEPS 子仓（`third_party/**`、`v8`、`buildtools`、`tools/**` 等上百个）在主仓看来全是**未跟踪目录**，`git clean -fdx` 会把它们连同 `out/` 一起删光，等于毁掉整次 sync。下面用「只还原被跟踪文件 + 点名删除已知生成物」的安全方式。

```bash
cd ~/workspace/chromium/151.0.7922/src
git checkout -q 151.0.7922.76 -- .          # 只还原被跟踪文件到该 tag
rm -f components/version_info/teleport_engine_version.h   # overlay 产生的未跟踪生成物
git status --porcelain -- . | grep -v '^?? teleport$' | head   # 应为空（teleport 是 overlay 符号链接，保留）

cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
uv run python scripts/apply_patches.py           # 第一次：必须全绿
uv run python scripts/apply_patches.py           # 第二次：必须幂等
```
Expected: 两次 `apply_patches.py` 都成功；第二次不产生任何文件内容变化（`apply_patches.py` 对已应用的 patch 是 no-op，branding 与生成物按内容比较跳过写入）。

- [ ] **Step 6: 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
git add patches/
git commit -m "chore(patches): re-export the overlay onto Chromium 151.0.7922.76

Moved via git three-way merge (rebase --onto) from 148.0.7778.180.

about_page.html and status_box.html were migrated to Lit (.html.ts) upstream,
so those two patches were rewritten against the new template form rather than
merged. The MAJOR=0 guards in generate_policy_source.py and
generate_unexpire_flags.py were re-resolved by intent, not by accepting the
merge result."
```

---

### Task 8: overlay 源码的上游 API 迁移

**Files:**
- Modify: `src/browser/enterprise/teleport_voluntary_signin.h`
- Modify: `src/browser/enterprise/teleport_voluntary_signin.cc`

**背景（实测）：** M151 删除了 `chrome/browser/ui/browser_finder.h`，`chrome::FindBrowserWithTab()` 由 `GlobalBrowserCollection::GetInstance()->FindBrowserWithTab()` 取代（`chrome/browser/ui/browser_window/public/global_browser_collection.h`），返回 `BrowserWindowInterface*`。`browser_navigator.h` 与 `browser_navigator_params.h` 移入 `chrome/browser/ui/navigator/`。

- [ ] **Step 1: 确认新 API 的真实签名**

```bash
cd ~/workspace/chromium/151.0.7922/src
sed -n '1,80p' chrome/browser/ui/browser_window/public/global_browser_collection.h
grep -rn 'FindBrowserWithTab' chrome/browser/ui/browser_window/public/*.h
```
以真实头文件为准记录返回类型与参数类型，**不要照抄本计划的推测**。

- [ ] **Step 2: 修 include 路径**

`src/browser/enterprise/teleport_voluntary_signin.cc` 中：

```cpp
// 旧
#include "chrome/browser/ui/browser_finder.h"
#include "chrome/browser/ui/browser_navigator.h"
#include "chrome/browser/ui/browser_navigator_params.h"

// 新
#include "chrome/browser/ui/browser_window/public/global_browser_collection.h"
#include "chrome/browser/ui/navigator/browser_navigator.h"
#include "chrome/browser/ui/navigator/browser_navigator_params.h"
```

- [ ] **Step 3: 迁移调用点**

`teleport_voluntary_signin.cc:170` 附近：

```cpp
// 旧
if (!wc || !chrome::FindBrowserWithTab(wc)) {

// 新
if (!wc || !GlobalBrowserCollection::GetInstance()->FindBrowserWithTab(wc)) {
```

按 Step 1 查到的真实命名空间补前缀（可能需要 `::` 或某个 namespace）。若 `OpenVoluntaryEnrollmentTab(Browser* browser)` 的参数类型因此需改为 `BrowserWindowInterface*`，同步改 `.h` 中的声明与全部调用点：

```bash
grep -rn 'OpenVoluntaryEnrollmentTab' src/ patches/
```

- [ ] **Step 4: 单目标编译验证**

```bash
cd ~/workspace/chromium/151.0.7922/src
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport
```
Expected: `//teleport` 目标编译通过

- [ ] **Step 5: 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
git add src/browser/enterprise/teleport_voluntary_signin.h src/browser/enterprise/teleport_voluntary_signin.cc
git commit -m "fix(teleport): follow the M151 Browser decomposition refactor

browser_finder.h is gone in M151; chrome::FindBrowserWithTab moved onto
GlobalBrowserCollection. browser_navigator{,_params}.h moved under
chrome/browser/ui/navigator/."
```

---

### Task 9: G2 全量编译到绿（迭代任务）

**Files:** 视编译错误而定，主要为 `src/**` 与 `patches/**`

**这是本计划最大的不确定性来源。** overlay 引用了 36 个在 M148→M150 就已变动的上游头文件（M151 只多不少），是否报错只有编译知道。

- [ ] **Step 1: 全量构建**

```bash
cd ~/workspace/chromium/151.0.7922/src
autoninja -C out/mac/arm64/dev chrome
```

- [ ] **Step 2: 逐轮修错**

每轮：读第一个错误 → 定位是 overlay 源码问题还是 patch 语义问题 → 修 → 重跑。

修复原则：
- **overlay 源码**（`src/**`）直接改，改完 patch 不受影响
- **patch 打进去的上游代码**：按 CLAUDE.md 的工作流——直接编辑 `~/workspace/chromium/151.0.7922/src/<file>`，然后 `git -C ~/workspace/chromium/151.0.7922/src diff 151.0.7922.76 -- <path> > patches/<path>.patch` 重生成，**禁止手改 hunk**
- 每修好一个独立问题就提交一次，不要攒一大堆

- [ ] **Step 3: 编译 `teleport_unittests` 目标**

```bash
autoninja -C out/mac/arm64/dev teleport_unittests
```

- [ ] **Step 4: 确认 patch 仍幂等**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
uv run python scripts/apply_patches.py
```
Expected: 全绿无变化（若有变化说明 Step 2 里改了树但没重新导出 patch）

- [ ] **Step 5: 提交剩余改动**

```bash
git add -A src/ patches/
git commit -m "fix(teleport): resolve M151 API drift across the overlay"
```

---

### Task 10: G3 单测绿

**Files:** 视失败情况而定

- [ ] **Step 1: `//teleport` 单测**

```bash
cd ~/workspace/chromium/151.0.7922/src
autoninja -C out/mac/arm64/dev teleport_unittests && ./out/mac/arm64/dev/teleport_unittests
```
Expected: 全绿

- [ ] **Step 2: 被 patch 的上游单测（必须真跑，不能只看编译过）**

```bash
cd ~/workspace/chromium/151.0.7922/src
autoninja -C out/mac/arm64/dev unit_tests net_unittests services_unittests

./out/mac/arm64/dev/unit_tests --gtest_filter='*UserAgent*:*BrowserDMTokenStorageMac*'
./out/mac/arm64/dev/net_unittests --gtest_filter='HttpNetworkTransactionTest.*'
./out/mac/arm64/dev/services_unittests --gtest_filter='*NetworkServiceProxyDelegate*'
```
Expected: 全绿。失败必须修（改代码或改测试），**不得跳过或注释**。

> 若某个 filter 匹配不到用例，说明上游重命名了测试套件名——用 `--gtest_list_tests` 找到真名并修正命令，同时更新 runbook 里记录的命令。

- [ ] **Step 3: 脚本单测**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
uv run pytest
```
Expected: 全绿

- [ ] **Step 4: 提交任何修复**

```bash
git add -A
git commit -m "test(teleport): fix unit tests against the M151 baseline"
```

---

### Task 11: G4 GUI 冒烟（活体）

**Files:** 视问题而定

**前置：** fairyland 服务端作为纳管/策略联调对端运行。**注意：fairyland 已从 docker 迁移到 k3s**——先启动 `fairyland-test` 这台 VM，在 VM 内用 `../fairyland/scripts/` 下的整套 k3s 部署脚本把服务端部署起来，不要再走 `docker.lima` 路径。

- [ ] **Step 1: 启动并逐项验证**

```bash
open ~/workspace/chromium/151.0.7922/src/out/mac/arm64/dev/Teleport.app
```

逐项核对（每项记录通过/失败）：

1. 启动 banner 出现、品牌名为「闪现」、图标正确
2. `chrome://version`：产品版本显示 `0.2.0.0`；**页面任何位置不得出现 Chromium 版本号**；User Agent 为 `Chrome/151.0.0.0`
3. `teleport://version` 别名可跳转
4. **About 页**（`chrome://settings/help`）：版本展示正确、「检查更新」按钮可点、页脚链接正确 —— *patch 被重写过，重点验*
5. **`chrome://policy`**：状态框显示我们的品牌而非 Chromium —— *patch 被重写过，重点验*
6. 自愿纳管：profile 菜单顶部「登录」→ 新 tab 打开 enroll 页 → OIDC → 披露对话框 → 就地纳管成功
7. 纳管后 `chrome://policy` 显示服务端下发的策略
8. 隧道（Track T）：按 `scripts/smoke_check.md` 中的隧道用例验证转发头注入
9. 升级角标：`--simulate-critical-update` 启动后工具栏角标秒亮

```bash
open -a ~/workspace/chromium/151.0.7922/src/out/mac/arm64/dev/Teleport.app --args --simulate-critical-update
```

- [ ] **Step 2: 修复发现的问题并重验**

每个问题独立修复并提交。

- [ ] **Step 3: 记录冒烟结果**

把本轮结果写入 `scripts/smoke_check.md` 的一个新章节「M151 基线升级冒烟记录（2026-08-xx）」，提交：

```bash
git add scripts/smoke_check.md
git commit -m "docs(scripts): record the M151 baseline smoke results"
```

---

### Task 12: G5 release 构建与出包

**Files:** 无代码改动（除非出错）

- [ ] **Step 1: release 构建（PGO，耗时数小时）**

```bash
cd ~/workspace/chromium/151.0.7922/src
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
autoninja -C out/mac/arm64/release chrome
```
Expected: 成功。若因 PGO profile 缺失硬失败，回 Task 6 Step 2 重新 sync。

- [ ] **Step 2: 拉 Sparkle 框架进新检出**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chromium-151-upgrade
uv run python scripts/fetch_sparkle.py
```
Expected: SHA256 校验通过，框架**真实拷贝**（非符号链接）进 `~/workspace/chromium/151.0.7922/src/third_party/teleport_sparkle`

- [ ] **Step 3: 出 canary 包（不发布）**

```bash
uv run python scripts/package.py --channel canary
```
Expected: 构建 → `assert_baked_version` 通过（烘焙版本 `0.2.0.0`）→ 签名 → 公证 → 样式 dmg 产出 `Teleport-0.2.0.0.dmg`

> **不得加 `--distribute`**。完成定义到出包为止。

- [ ] **Step 4: 验证产物**

```bash
ls -lh ~/workspace/chromium/151.0.7922/src/out/mac/arm64/release/*.dmg
codesign -dv --verbose=4 <签名后的 .app 路径> 2>&1 | grep -E 'Identifier|TeamIdentifier|Timestamp'
spctl -a -vv <签名后的 .app 路径>
```
Expected: dmg 存在；签名标识为 `cn.douan.Teleport.canary`；`spctl` 接受（公证后）

- [ ] **Step 5: 提交任何为出包所做的修复**

```bash
git add -A
git commit -m "fix(scripts): unblock canary packaging on the M151 baseline"
```

---

### Task 13: 文档更新

**Files:**
- Create: `docs/chromium-upgrade-runbook.md`
- Modify: `CLAUDE.md`
- Modify: `docs/tech-debt.md`

- [ ] **Step 1: 写 runbook**

创建 `docs/chromium-upgrade-runbook.md`（简体中文），必须包含：

- **两条路径的判定入口**：先跑 `uv run python scripts/check_upstream_release.py`，按其结论走 A 或 B
- **路径 A：安全补丁跟进（同一发布分支）** —— 改 `CHROMIUM_VERSION` → `sync.py` → `apply_patches.py` → 增量构建 → 单测 → 出包；同一检出，不新建
- **路径 B：里程碑升级** —— 建新检出（含本次用的 `git clone --local` 硬链接技巧，省掉 66 GB 重复下载）→ `rebase_overlay.py` → 解冲突 → `export_patches.py` → G1..G5 闸门
- **跟进时机表**（在野 0-day / Critical·High / 常规 / 里程碑）
- **踩过的坑**：`gclient sync --no-history` 会让三方合并失去 base；`git add -A` 不可用；`out/` 目录不可移动（含 GN 绝对路径）；旧检出保留为回退底座
- **本次实测数据**作为下次的预期基准

- [ ] **Step 2: 更新 `CLAUDE.md`**

- 「架构」段的基线版本 `148.0.7778.180` → `151.0.7922.76`
- 「仓库布局」加入 `scripts/{rebase_overlay,export_patches,check_upstream_release}.py`
- 「构建与测试命令」加入检出布局说明与三个新脚本的用法
- 「关键 gotcha」：
  - 更新「chromium 检出位置」条目为新的按发布分支派生规则
  - 新增「上游 tag ≠ 已发布」（含子分支号段分配的原理）
  - 新增「桌面 Mac/Win 同线、Linux 取子集，故单一 pin 服务全部桌面平台」
  - **修正已过时的条目**：`--disable-field-trial-config` 已是 no-op（构建期 GN arg 已关），文档仍写着运行时要传
- 「待定 / 后续 phase」：移除「patch 的创建/刷新/冲突处理工具链」一项
- 「参考材料」加入本次 spec、plan、runbook

- [ ] **Step 3: 更新 `docs/tech-debt.md`**

- TD-016 现状修订：不同基线的 worktree 已由路径派生天然隔离；**同基线 worktree 之间的共享检出污染仍存在，条目不可关闭**
- 若 Task 7/9 中有 patch 按降级语义重解，新增条目登记
- **新增条目：M151 图标迁移导致的品牌泄漏（用户已裁定登记而非本次修复）**。上游在 M151 把 177 个图标重命名为 `*_old`、新增 202 个；我们现有的 3 个 `branding/` 覆盖落在遗留的 `*_old` 路径上，新的 `components/omnibox/browser/vector_icons/chrome_product.icon` 等未被覆盖 → 该路径生效时显示 Chrome logo，涉及任务管理器 / omnibox / 应用菜单 / PDF / 会话恢复 / 默认浏览器提示条等 20+ 调用点。**当前休眠**（`kRoundedIcons` 与 `kDesktopGlowUp` 均 `FEATURE_DISABLED_BY_DEFAULT`，且我们把 feature 钉到编译默认值）。**触发条件**：显式 `--enable-features=DesktopGlowUp`，或上游在后续里程碑翻开默认。**必须在 M152 升级前解决**——需先查清 202 个新图标里哪些展示产品 logo，再补美术资源。条目须写明这是**下次发版前的阻塞项**，不是普通 medium。
- **新增条目：跨仓文档漂移（fairyland 侧，本仓不改代码）**。M151 删除了 OIDC 的 `#access_token=` fragment 捕获路径，故 fairyland 注释与配置文档中「`ENROLL_HPKE_PRIVATE_KEY` 未配时 fragment 路径仍可用」的降级承诺对 M151+ 客户端**已不成立**——服务端仍在提供，浏览器已无法消费。k3s 部署恒定启用 header 通道（`local-setup.sh` 自动生成密钥、`k3s-secrets-load.sh` 装载、e2e 断言非空），故**不影响纳管**；但 fairyland 的注释与文档需在其仓侧修正。

- [ ] **Step 4: 跑全量脚本测试确认文档改动没打破什么**

Run: `uv run pytest`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add docs/chromium-upgrade-runbook.md CLAUDE.md docs/tech-debt.md
git commit -m "docs(teleport): runbook for baseline upgrades and security-patch tracking

Also refreshes CLAUDE.md for the M151 baseline and the release-branch checkout
layout, and corrects the stale --disable-field-trial-config gotcha (it has been
a no-op since the GN arg landed)."
```

---

## 完成检查

全部任务完成后确认：

- [ ] `uv run pytest` 全绿
- [ ] `teleport_unittests` 全绿
- [ ] 被 patch 的上游单测全绿（`unit_tests` / `net_unittests` / `services_unittests` 对应 filter）
- [ ] `apply_patches.py` 在干净的 151 检出上幂等
- [ ] G4 冒烟清单逐项通过并记录
- [ ] `Teleport-0.2.0.0.dmg` 产出、签名与公证通过
- [ ] **未执行 `--distribute`**
- [ ] `CLAUDE.md`、`docs/tech-debt.md`、runbook 已更新
- [ ] 旧检出 `/Users/liulichao/workspace/teleport/chromium` 仍完好（回退能力保留）
