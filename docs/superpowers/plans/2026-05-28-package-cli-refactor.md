# package.py 多渠道重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `scripts/package_release.py` 重构成参数驱动的多渠道打包工具 `scripts/package.py`:默认本地打 dev 包(仅构建),`--channel` 选渠道,`--distribute` 才发布(仅 main 分支、打 `v<semver>` tag 并推送、tag+feed 双查阻止重复发布)。

**Architecture:** 单入口 `package.py` 编排,内部按阶段拆成 `_build`(渠道注册表+autoninja)、`_package`(stamp/签名/dmg)、`_publish`(护栏/appcast/上传/打 tag)、`_config`(嵌套 TOML 加载+分级校验),`_release` 保留(semver/appcast 解析)。逐任务 TDD。

**Tech Stack:** Python 3.13(`uv run pytest`),`pythonpath=["scripts"]`,扁平模块导入(`import _build` 等),hermetic 单测靠 monkeypatch `subprocess.run`。

参照设计文档:`docs/superpowers/specs/2026-05-28-package-cli-refactor-design.md`。

---

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `scripts/_config.py` | Create | 嵌套 `[channel.x]` TOML 加载 + 分级 key 校验 |
| `scripts/_build.py` | Create | 渠道注册表 `Channel` + `resolve_channel` + `build` |
| `scripts/_package.py` | Create | `detect_codesign_identity`/`sparkle_bin`/`stamp_and_inject`/`sign_app`/`build_styled_dmg`(从旧脚本搬出) |
| `scripts/_publish.py` | Create | `fetch_live_appcast`/护栏/`generate_appcast`/`upload_to_oss`/`tag_and_push` |
| `scripts/package.py` | Create | 入口:argparse、渠道解析、按模式编排、dry-run |
| `scripts/_release.py` | 不改 | semver/appcast 解析(已存在,已测) |
| `scripts/package_release.py` | Delete | 被 `package.py` + 模块取代 |
| `scripts/tests/test_config.py` | Create | _config 单测 |
| `scripts/tests/test_build.py` | Create | _build 单测 |
| `scripts/tests/test_package.py` | Create | _package 单测(迁移 codesign/stamp 用例) |
| `scripts/tests/test_publish.py` | Create | _publish 单测 |
| `scripts/tests/test_package_cli.py` | Create | package.py 入口决策单测 |
| `scripts/tests/test_package_release.py` | Delete | 被上面拆分取代 |
| `scripts/release_config.local.toml.example` | Modify | 改嵌套 `[channel.dogfood]` 形态 |
| `CLAUDE.md` | Modify | 更新 layout 描述 + 命令块 + 版本注 |
| `scripts/smoke_check.md` | Modify | 更新发布命令 |
| `scripts/dmg_settings.py` | Modify | 注释里 `package_release.py` → `package.py` |
| `scripts/preview_dmg_window.py` | Modify | 注释里 `package_release` → `package` |

> 历史 spec/plan(`2026-05-26-*`、`2026-05-27-*`)是归档记录,**不改**。

---

### Task 1: `_config.py` — 嵌套配置加载 + 分级校验

**Files:**
- Create: `scripts/_config.py`
- Test: `scripts/tests/test_config.py`

- [ ] **Step 1: 写失败测试**

`scripts/tests/test_config.py`:

```python
import pytest

import _config

_NESTED = (
    'notary_profile = "p"\n'
    'codesign_identity = "Developer ID Application: X (T)"\n'
    "\n"
    "[channel.dogfood]\n"
    'public_ed_key = "k"\n'
    'feed_url = "https://h.example.com/a/appcast.xml"\n'
    'download_base_url = "https://h.example.com/a/"\n'
    'oss_upload_target = "oss://bucket/a/"\n'
)


def test_load_channel_config_merges_shared_and_channel(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(_NESTED)
    cfg = _config.load_channel_config(p, "dogfood")
    assert cfg["notary_profile"] == "p"
    assert cfg["feed_url"].startswith("https://")
    assert cfg["oss_upload_target"].startswith("oss://")
    assert cfg["git_remote"] == "origin"  # default applied


def test_load_channel_config_missing_section_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('notary_profile = "p"\n')
    with pytest.raises(SystemExit, match="channel.beta"):
        _config.load_channel_config(p, "beta")


def test_load_channel_config_missing_file_raises(tmp_path):
    with pytest.raises(SystemExit, match="missing"):
        _config.load_channel_config(tmp_path / "nope.toml", "dogfood")


def test_load_channel_config_respects_explicit_git_remote(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('git_remote = "upstream"\n[channel.dogfood]\nfeed_url="x"\n')
    cfg = _config.load_channel_config(p, "dogfood")
    assert cfg["git_remote"] == "upstream"


def test_require_keys_missing_raises():
    with pytest.raises(SystemExit, match="oss_upload_target"):
        _config.require_keys({"feed_url": "x"}, ("feed_url", "oss_upload_target"))


def test_require_keys_present_ok():
    _config.require_keys({"a": "1", "b": "2"}, ("a", "b"))  # no raise


def test_key_tuples_exist():
    assert "public_ed_key" in _config.STAMP_KEYS
    assert "feed_url" in _config.STAMP_KEYS
    assert "notary_profile" in _config.NOTARIZE_KEYS
    assert set(_config.PUBLISH_KEYS) == {"download_base_url", "oss_upload_target"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_config.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named '_config'`）

- [ ] **Step 3: 写实现**

`scripts/_config.py`:

```python
"""Release config: nested [channel.x] TOML loader + per-operation key checks.

Top-level keys are account-shared (notary_profile, codesign_identity,
git_remote); [channel.<name>] holds per-channel publish settings (Sparkle
public key, feed URL, OSS endpoints). Validation is deferred to require_keys()
so each operation only demands what it actually needs (a dev build needs no
config at all; a local channel package needs stamp+notarize keys; publishing
additionally needs the OSS keys).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

# Keys required per operation phase.
STAMP_KEYS = ("public_ed_key", "feed_url")
NOTARIZE_KEYS = ("notary_profile",)
PUBLISH_KEYS = ("download_base_url", "oss_upload_target")


def load_channel_config(path: Path, channel: str) -> dict:
    """Flatten the channel's [channel.<name>] section over the shared top-level
    keys. Raises SystemExit if the file or the channel section is absent.
    Does NOT validate completeness — call require_keys() for the pending op.
    """
    if not path.exists():
        raise SystemExit(f"missing {path} (copy release_config.local.toml.example)")
    raw = tomllib.loads(path.read_text())
    shared = {k: v for k, v in raw.items() if k != "channel"}
    channels = raw.get("channel", {})
    if channel not in channels:
        raise SystemExit(f"release config has no [channel.{channel}] section")
    merged = {**shared, **channels[channel]}
    merged.setdefault("git_remote", "origin")
    return merged


def require_keys(cfg: dict, keys: tuple[str, ...]) -> None:
    """Exit non-zero if any of `keys` is missing/empty in cfg."""
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        raise SystemExit(f"release config missing keys: {', '.join(missing)}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_config.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add scripts/_config.py scripts/tests/test_config.py
git commit -m "feat(scripts): nested [channel.x] release config loader"
```

---

### Task 2: `_build.py` — 渠道注册表 + 构建

**Files:**
- Create: `scripts/_build.py`
- Test: `scripts/tests/test_build.py`

- [ ] **Step 1: 写失败测试**

`scripts/tests/test_build.py`:

```python
import pytest

import _build


def test_resolve_dev():
    ch = _build.resolve_channel("dev")
    assert ch.name == "dev"
    assert ch.out == "out/mac/arm64/dev"
    assert ch.distributable is False
    assert ch.targets == ("chrome",)


def test_resolve_dogfood():
    ch = _build.resolve_channel("dogfood")
    assert ch.distributable is True
    assert ch.out == "out/mac/arm64/release"
    assert ch.targets == ("chrome", "chrome/installer/mac")


def test_resolve_unknown_raises():
    with pytest.raises(SystemExit, match="unknown channel"):
        _build.resolve_channel("beta")


def test_build_runs_autoninja(monkeypatch):
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: "/fake/src")
    ch = _build.resolve_channel("dogfood")
    _build.build("out/x", ch)
    argv, kw = calls[0]
    assert argv == ["autoninja", "-C", "out/x", "chrome", "chrome/installer/mac"]
    assert str(kw["cwd"]) == "/fake/src"
    assert kw["check"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_build.py -q`
Expected: FAIL（`No module named '_build'`）

- [ ] **Step 3: 写实现**

`scripts/_build.py`:

```python
"""Channel registry and the build (autoninja) step.

A channel maps to a default GN out dir, whether it is distributable, and the
autoninja targets to build. The script does NOT run `gn gen` — the human runs
that first (release channels also need PGO profiles fetched via gclient sync).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from _lib import chromium_src


@dataclass(frozen=True)
class Channel:
    name: str
    out: str                  # default GN out dir, relative to chromium src
    distributable: bool
    targets: tuple[str, ...]  # autoninja targets


CHANNELS = {
    "dev": Channel("dev", "out/mac/arm64/dev", False, ("chrome",)),
    "dogfood": Channel(
        "dogfood", "out/mac/arm64/release", True,
        ("chrome", "chrome/installer/mac"),
    ),
}


def resolve_channel(name: str) -> Channel:
    try:
        return CHANNELS[name]
    except KeyError:
        valid = ", ".join(sorted(CHANNELS))
        raise SystemExit(f"unknown channel {name!r}; valid channels: {valid}")


def build(out: str, channel: Channel) -> None:
    """Run autoninja for the channel's targets inside the chromium src tree."""
    subprocess.run(
        ["autoninja", "-C", out, *channel.targets],
        cwd=chromium_src(), check=True,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_build.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add scripts/_build.py scripts/tests/test_build.py
git commit -m "feat(scripts): channel registry + build step"
```

---

### Task 3: `_package.py` — stamp / 签名 / dmg(从旧脚本搬出)

**Files:**
- Create: `scripts/_package.py`
- Test: `scripts/tests/test_package.py`

- [ ] **Step 1: 写失败测试**(迁移 codesign + stamp 用例,签名探测函数改公开名 `detect_codesign_identity`)

`scripts/tests/test_package.py`:

```python
import subprocess

import pytest

import _package


# ---------------------------------------------------------------------------
# detect_codesign_identity (hermetic: fake `security find-identity` stdout)
# ---------------------------------------------------------------------------


def _fake_find_identity(stdout):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    return _run


def test_detect_codesign_none_raises(monkeypatch):
    monkeypatch.setattr(_package.subprocess, "run",
                        _fake_find_identity("  0 valid identities found\n"))
    with pytest.raises(SystemExit, match="no 'Developer ID Application'"):
        _package.detect_codesign_identity()


def test_detect_codesign_single_returns_it(monkeypatch):
    stdout = (
        "  1) ABC123 \"Developer ID Application: Acme Inc (T1234)\"\n"
        "     1 valid identities found\n"
    )
    monkeypatch.setattr(_package.subprocess, "run", _fake_find_identity(stdout))
    assert (_package.detect_codesign_identity()
            == "Developer ID Application: Acme Inc (T1234)")


def test_detect_codesign_multiple_raises(monkeypatch):
    stdout = (
        "  1) ABC \"Developer ID Application: Acme Inc (T1234)\"\n"
        "  2) DEF \"Developer ID Application: Beta LLC (T5678)\"\n"
        "     2 valid identities found\n"
    )
    monkeypatch.setattr(_package.subprocess, "run", _fake_find_identity(stdout))
    with pytest.raises(SystemExit) as exc:
        _package.detect_codesign_identity()
    msg = str(exc.value)
    assert "multiple" in msg
    assert "codesign_identity" in msg
    assert "Acme Inc (T1234)" in msg
    assert "Beta LLC (T5678)" in msg


# ---------------------------------------------------------------------------
# stamp_and_inject (hermetic: capture plutil calls instead of touching a plist)
# ---------------------------------------------------------------------------


def test_stamp_and_inject_sets_hourly_check_interval(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(_package.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    cfg = {"feed_url": "https://h/a.xml", "public_ed_key": "k"}
    _package.stamp_and_inject(tmp_path / "Teleport.app", "0.1.3", cfg)

    interval = next(c for c in calls if "SUScheduledCheckInterval" in c)
    assert interval[:4] == ["plutil", "-replace", "SUScheduledCheckInterval", "-integer"]
    assert interval[4] == "3600"
    assert _package._CHECK_INTERVAL_SECONDS == 3600
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_package.py -q`
Expected: FAIL（`No module named '_package'`）

- [ ] **Step 3: 写实现**(从 `package_release.py` 搬出并解耦 cfg)

`scripts/_package.py`:

```python
"""Packaging steps for a distributable channel: stamp version + Sparkle keys,
sign the .app via the generated signing module, and build the styled dmg
(sign + notarize + staple). All macOS / Developer-ID specific.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from _lib import deps_cache_dir, repo_root
from fetch_sparkle import SPARKLE_VERSION

# dogfood checks for updates hourly instead of Sparkle's 1-day default
# (SUDefaultUpdateCheckInterval). 3600s is Sparkle's enforced minimum.
_CHECK_INTERVAL_SECONDS = 3600


def detect_codesign_identity() -> str:
    """Find the unique 'Developer ID Application' certificate in the keychain.

    Refuses to guess when more than one such identity exists -- the caller must
    then set `codesign_identity` explicitly in the config.
    """
    r = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True, check=True,
    )
    matches = re.findall(r'"(Developer ID Application: [^"]+)"', r.stdout)
    if not matches:
        raise SystemExit("no 'Developer ID Application' certificate found in keychain")
    if len(matches) > 1:
        found = "\n  ".join(matches)
        raise SystemExit(
            "multiple 'Developer ID Application' certificates found in keychain; "
            "refusing to guess. Set codesign_identity explicitly in "
            "release_config.local.toml to one of:\n  " + found
        )
    return matches[0]


def sparkle_bin(name: str) -> Path:
    return deps_cache_dir() / "sparkle" / SPARKLE_VERSION / "bin" / name


def stamp_and_inject(app: Path, version: str, cfg: dict) -> None:
    """Stamp version + inject Sparkle keys into the app's Info.plist (pre-sign)."""
    info = app / "Contents" / "Info.plist"
    sets = {
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "SUFeedURL": cfg["feed_url"],
        "SUPublicEDKey": cfg["public_ed_key"],
    }
    for key, val in sets.items():
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


def sign_app(app: Path, updates_dir: Path, identity: str) -> None:
    """Sign the .app only (--disable-packaging) via the generated signing module.

    The signing module must run from the generated "<product> Packaging" dir:
    it holds signing/ PLUS the build-time-generated build_props_config.py
    (branding/version). The source tree's copy lacks it.
    """
    sign_chrome = app.parent / "Teleport Packaging" / "sign_chrome.py"
    # signing's make_dir uses os.mkdir (single level), so pre-create the output
    # tree; the driver skips its own mkdir when the dir already exists.
    updates_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, str(sign_chrome),
        "--identity", identity,
        "--input", str(app.parent),
        "--output", str(updates_dir),
        "--disable-packaging",
    ], check=True)


def build_styled_dmg(updates_dir: Path, version: str, identity: str,
                     notary_profile: str) -> Path:
    """Build a styled dmg from the signed app (dmgbuild), then sign + notarize +
    staple the dmg itself. The chrome signing module only signs the .app
    (--disable-packaging); its plain pkg-dmg output isn't styled for Chromium."""
    # The signing module writes the signed app under the distribution's channel
    # subdir, e.g. <output>/stable/Teleport.app.
    signed_app = next(iter(
        list(updates_dir.glob("Teleport.app")) +
        list(updates_dir.glob("*/Teleport.app"))))
    target_dmg = updates_dir / f"Teleport-{version}.dmg"
    target_dmg.unlink(missing_ok=True)

    dmgbuild = Path(sys.executable).parent / "dmgbuild"
    settings = repo_root() / "scripts" / "dmg_settings.py"
    background = repo_root() / "brand" / "dmg" / "background.tiff"
    icns = signed_app / "Contents" / "Resources" / "app.icns"
    cmd = [str(dmgbuild), "-s", str(settings),
           "-D", f"app={signed_app}", "-D", f"background={background}"]
    if icns.exists():
        cmd += ["-D", f"icon={icns}"]
    cmd += ["Teleport", str(target_dmg)]
    subprocess.run(cmd, check=True)

    # The signed app is now inside the dmg; drop the loose copy (and its channel
    # subdir) so it isn't left in the staging/upload dir.
    stale = signed_app.parent if signed_app.parent != updates_dir else signed_app
    subprocess.run(["rm", "-rf", str(stale)], check=True)

    # Sign, notarize, and staple the dmg itself.
    subprocess.run(["codesign", "--force", "--sign", identity,
                    "--timestamp", str(target_dmg)], check=True)
    subprocess.run(["xcrun", "notarytool", "submit", str(target_dmg),
                    "--keychain-profile", notary_profile, "--wait"], check=True)
    subprocess.run(["xcrun", "stapler", "staple", str(target_dmg)], check=True)
    return target_dmg
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_package.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add scripts/_package.py scripts/tests/test_package.py
git commit -m "feat(scripts): extract stamp/sign/dmg into _package module"
```

---

### Task 4: `_publish.py` — 护栏 / appcast / 上传 / 打 tag

**Files:**
- Create: `scripts/_publish.py`
- Test: `scripts/tests/test_publish.py`

- [ ] **Step 1: 写失败测试**

`scripts/tests/test_publish.py`:

```python
import subprocess

import pytest

import _publish


def _completed(stdout):
    def _run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
    return _run


def test_tag_name():
    assert _publish.tag_name("0.1.0") == "v0.1.0"


def test_assert_on_main_ok(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed("main\n"))
    _publish.assert_on_main()  # no raise


def test_assert_on_main_rejects_branch(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed("feature/x\n"))
    with pytest.raises(SystemExit, match="refusing to publish from branch"):
        _publish.assert_on_main()


def test_assert_clean_tree_ok(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed(""))
    _publish.assert_clean_tree()  # no raise


def test_assert_clean_tree_rejects_dirty(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed(" M scripts/x.py\n"))
    with pytest.raises(SystemExit, match="dirty working tree"):
        _publish.assert_clean_tree()


def test_tag_exists_true(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed("v0.1.0\n"))
    assert _publish.tag_exists("0.1.0") is True


def test_tag_exists_false(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed(""))
    assert _publish.tag_exists("0.1.0") is False


def test_assert_not_published_rejects_existing_tag(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v: True)
    with pytest.raises(SystemExit, match="tag v0.1.0 already exists"):
        _publish.assert_not_published("0.1.0", None)


def test_assert_not_published_rejects_feed_not_newer(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v: False)
    feed = (
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
        '<channel><item><sparkle:version>0.1.0</sparkle:version></item></channel></rss>'
    )
    with pytest.raises(SystemExit, match="not newer"):
        _publish.assert_not_published("0.1.0", feed)


def test_assert_not_published_ok_when_newer(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v: False)
    feed = (
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
        '<channel><item><sparkle:version>0.1.0</sparkle:version></item></channel></rss>'
    )
    _publish.assert_not_published("0.1.1", feed)  # no raise


def test_tag_and_push_invokes_git(monkeypatch):
    calls = []
    monkeypatch.setattr(_publish.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(_publish, "repo_root", lambda: "/repo")
    _publish.tag_and_push("0.1.0", "origin")
    assert calls[0][:3] == ["git", "tag", "-a"]
    assert "v0.1.0" in calls[0]
    assert calls[1] == ["git", "push", "origin", "v0.1.0"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_publish.py -q`
Expected: FAIL（`No module named '_publish'`）

- [ ] **Step 3: 写实现**

`scripts/_publish.py`:

```python
"""Publish phase: branch/clean/already-published guards, appcast generation,
OSS upload, and version tagging. Distributable channels only.
"""
from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path

from _lib import repo_root
from _package import sparkle_bin
from _release import assert_publishable


def fetch_live_appcast(feed_url: str) -> str | None:
    try:
        with urllib.request.urlopen(feed_url) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None  # first release: no feed yet


def current_branch() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def assert_on_main() -> None:
    branch = current_branch()
    if branch != "main":
        raise SystemExit(
            f"refusing to publish from branch {branch!r}; switch to main"
        )


def assert_clean_tree() -> None:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    if r.stdout.strip():
        raise SystemExit(
            "refusing to publish with a dirty working tree; commit or stash first"
        )


def tag_name(version: str) -> str:
    return f"v{version}"


def tag_exists(version: str) -> bool:
    r = subprocess.run(
        ["git", "tag", "--list", tag_name(version)],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    return bool(r.stdout.strip())


def assert_not_published(version: str, appcast_xml: str | None) -> None:
    """Refuse if `version` is already released -- by git tag OR by the live feed.

    Tag check is local and authoritative for anything we published (we always
    tag on publish). Feed check is defense-in-depth for a publish from another
    machine that never pushed a tag.
    """
    if tag_exists(version):
        raise SystemExit(
            f"refusing to publish {version}: tag {tag_name(version)} already "
            f"exists; bump TELEPORT_VERSION"
        )
    assert_publishable(version, appcast_xml)


def generate_appcast(updates_dir: Path, download_base_url: str,
                     keep_dmg: str) -> None:
    """Trim staging dir to the single current dmg, then run generate_appcast.

    Keeping only the current dmg makes the appcast list just the latest version
    and avoids dangling .delta references (generate_appcast preserves
    pre-existing delta entries even with --maximum-deltas 0).
    """
    for p in updates_dir.iterdir():
        if p.is_file() and p.name != keep_dmg:
            p.unlink()
    subprocess.run([
        str(sparkle_bin("generate_appcast")),
        "--maximum-deltas", "0",
        "--download-url-prefix", download_base_url,
        str(updates_dir),
    ], check=True)


def upload_to_oss(updates_dir: Path, target: str) -> None:
    """Upload dmg(s) + appcast.xml to OSS with correct cache headers.

    Versioned dmgs are immutable -> long cache; appcast.xml changes every
    release -> never cache.
    """
    for dmg in sorted(updates_dir.glob("*.dmg")):
        subprocess.run(
            ["ossutil", "cp", "-f", str(dmg), target,
             "--cache-control", "public, max-age=31536000, immutable"],
            check=True,
        )
    subprocess.run(
        ["ossutil", "cp", "-f", str(updates_dir / "appcast.xml"), target,
         "--cache-control", "no-cache"],
        check=True,
    )


def tag_and_push(version: str, remote: str) -> None:
    """Annotated-tag HEAD as v<version> and push the tag to `remote`."""
    name = tag_name(version)
    subprocess.run(
        ["git", "tag", "-a", name, "-m", f"release {version}"],
        cwd=repo_root(), check=True,
    )
    subprocess.run(["git", "push", remote, name], cwd=repo_root(), check=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_publish.py -q`
Expected: PASS（12 passed）

- [ ] **Step 5: 提交**

```bash
git add scripts/_publish.py scripts/tests/test_publish.py
git commit -m "feat(scripts): publish guards, appcast, upload, version tagging"
```

---

### Task 5: `package.py` — 入口编排

**Files:**
- Create: `scripts/package.py`
- Test: `scripts/tests/test_package_cli.py`

- [ ] **Step 1: 写失败测试**(入口的可单测决策:dev+distribute 报错、未知渠道报错、dev dry-run 仅打印不构建)

`scripts/tests/test_package_cli.py`:

```python
import pytest

import package


def test_distribute_on_dev_raises(monkeypatch):
    # read_teleport_version reads the repo TELEPORT_VERSION; stub for hermeticity.
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    with pytest.raises(SystemExit, match="not distributable"):
        package.main(["--channel", "dev", "--distribute"])


def test_unknown_channel_raises(monkeypatch):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    with pytest.raises(SystemExit, match="unknown channel"):
        package.main(["--channel", "beta"])


def test_dev_dry_run_does_not_build(monkeypatch, capsys):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    called = []
    monkeypatch.setattr(package, "build", lambda *a, **k: called.append(a))
    rc = package.main(["--dry-run"])  # default channel = dev
    assert rc == 0
    assert called == []  # dry-run must not build
    assert "DRY RUN" in capsys.readouterr().out


def test_dev_build_invokes_build_only(monkeypatch, capsys):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    calls = []
    monkeypatch.setattr(package, "build", lambda out, ch: calls.append((out, ch.name)))
    rc = package.main([])  # default channel = dev, no distribute
    assert rc == 0
    assert calls == [("out/mac/arm64/dev", "dev")]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_package_cli.py -q`
Expected: FAIL（`No module named 'package'`）

- [ ] **Step 3: 写实现**

`scripts/package.py`:

```python
#!/usr/bin/env python3
"""Build, sign, and optionally publish a teleport package.

Default builds a local dev app (build only). --channel selects a channel;
--distribute publishes a distributable channel package (main branch only, with
a v<semver> git tag pushed to the remote). Run from the repo root with
TELEPORT_CHROMIUM_DIR set; for distributable channels, `gn gen` the channel's
out dir first.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import _config
import _package
import _publish
from _build import build, resolve_channel
from _lib import chromium_src, repo_root
from _release import read_teleport_version


def _default_config() -> Path:
    return repo_root() / "scripts" / "release_config.local.toml"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build + sign + optionally publish a teleport package")
    p.add_argument("--channel", default="dev")
    p.add_argument("--distribute", action="store_true",
                   help="publish after building (distributable channels, main only)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--config", type=Path, default=_default_config())
    p.add_argument("--out", default=None, help="override the channel's default out dir")
    p.add_argument("--updates-dir", type=Path, default=None)
    args = p.parse_args(argv)

    channel = resolve_channel(args.channel)
    out = args.out or channel.out
    updates_dir = args.updates_dir or (repo_root() / "dist" / channel.name)
    version = read_teleport_version()

    if args.distribute and not channel.distributable:
        raise SystemExit(
            f"channel {channel.name!r} is not distributable; --distribute not allowed")

    # ---- non-distributable channel (dev): build only ----
    if not channel.distributable:
        if args.dry_run:
            print(f"DRY RUN: autoninja -C {out} {' '.join(channel.targets)}  "
                  f"(build only, channel {channel.name})")
            return 0
        build(out, channel)
        print(f"built {channel.name} app at {chromium_src() / out / 'Teleport.app'}")
        return 0

    # ---- distributable channel ----
    cfg = _config.load_channel_config(args.config, channel.name)
    _config.require_keys(cfg, _config.STAMP_KEYS + _config.NOTARIZE_KEYS)
    if not cfg.get("codesign_identity"):
        cfg["codesign_identity"] = _package.detect_codesign_identity()
    app = chromium_src() / out / "Teleport.app"

    if args.distribute:
        _config.require_keys(cfg, _config.PUBLISH_KEYS)
        # Pre-build guards (fail fast before a multi-hour build).
        _publish.assert_on_main()
        _publish.assert_clean_tree()
        _publish.assert_not_published(version, _publish.fetch_live_appcast(cfg["feed_url"]))

    if args.dry_run:
        plan = [
            f"autoninja -C {out} {' '.join(channel.targets)}",
            f"stamp version {version} + inject Sparkle keys into {app}/Contents/Info.plist",
            f"sign .app (--disable-packaging) with '{cfg['codesign_identity']}'",
            "dmgbuild styled dmg -> codesign -> notarytool submit --wait -> stapler staple",
        ]
        if args.distribute:
            plan += [
                f"generate_appcast (download-url-prefix {cfg['download_base_url']}) into {updates_dir}",
                f"ossutil upload dmg + appcast.xml to {cfg['oss_upload_target']}",
                f"git tag -a v{version} -m 'release {version}' && git push {cfg['git_remote']} v{version}",
            ]
        print(f"DRY RUN (channel {channel.name}"
              f"{', distribute' if args.distribute else ''}):\n  " + "\n  ".join(plan))
        return 0

    # Build -> stamp -> sign -> styled dmg (notarized).
    build(out, channel)
    _package.stamp_and_inject(app, version, cfg)
    _package.sign_app(app, updates_dir, cfg["codesign_identity"])
    target_dmg = _package.build_styled_dmg(
        updates_dir, version, cfg["codesign_identity"], cfg["notary_profile"])

    if not args.distribute:
        print(f"built + signed {channel.name} dmg at {target_dmg} (not published)")
        return 0

    # Re-check (cheap) in case another publish landed during the build, then
    # generate appcast -> upload -> tag + push (tag only after a successful upload).
    _publish.assert_not_published(version, _publish.fetch_live_appcast(cfg["feed_url"]))
    _publish.generate_appcast(updates_dir, cfg["download_base_url"], target_dmg.name)
    _publish.upload_to_oss(updates_dir, cfg["oss_upload_target"])
    _publish.tag_and_push(version, cfg["git_remote"])
    print(f"published {version} ({channel.name}), tagged v{version}: feed {cfg['feed_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_package_cli.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: dry-run 冒烟(可分发渠道,需配置文件;无则跳过此步)**

若本地已有 `scripts/release_config.local.toml`:
Run: `uv run python scripts/package.py --channel dogfood --dry-run`
Expected: 打印含 `stamp version` / `dmgbuild` 的计划,不构建。

- [ ] **Step 6: 提交**

```bash
git add scripts/package.py scripts/tests/test_package_cli.py
git commit -m "feat(scripts): package.py multi-channel build/publish entrypoint"
```

---

### Task 6: 迁移收尾 — 删旧脚本、更新文档与注释

**Files:**
- Delete: `scripts/package_release.py`, `scripts/tests/test_package_release.py`
- Modify: `scripts/release_config.local.toml.example`, `CLAUDE.md`, `scripts/smoke_check.md`, `scripts/dmg_settings.py`, `scripts/preview_dmg_window.py`

- [ ] **Step 1: 删除旧脚本与旧测试**

```bash
git rm scripts/package_release.py scripts/tests/test_package_release.py
```

- [ ] **Step 2: 改 example 配置为嵌套形态**

把 `scripts/release_config.local.toml.example` 整体替换为:

```toml
# Copy to scripts/release_config.local.toml (gitignored) and fill in.
#
# Top-level keys are account-shared across channels; [channel.<name>] holds
# the per-channel publish settings.

# notarytool keychain profile name (xcrun notarytool store-credentials).
notary_profile = "teleport-notary"

# Developer ID Application identity (auto-detected from keychain if omitted).
# codesign_identity = "Developer ID Application: <Name> (<TEAMID>)"

# Git remote the v<semver> release tag is pushed to (default: origin).
# git_remote = "origin"

[channel.dogfood]
# Sparkle public EdDSA key (base64) printed by generate_keys.
public_ed_key = "PASTE_BASE64_PUBLIC_KEY"
# Appcast feed URL (public https; the OSS native endpoint + unguessable token).
feed_url = "https://<bucket>.oss-cn-<region>.aliyuncs.com/dogfood/<token>/appcast.xml"
# Public https base the appcast download links + SUFeedURL point at (trailing /).
download_base_url = "https://<bucket>.oss-cn-<region>.aliyuncs.com/dogfood/<token>/"
# OSS path the dmg + appcast are uploaded to via ossutil (trailing /).
oss_upload_target = "oss://<bucket>/dogfood/<token>/"
```

- [ ] **Step 3: 更新 `CLAUDE.md`**

3a. 仓库布局描述(原第 49 行):
```
  package_release.py       发版主入口:构建→签名→公证→样式 dmg→appcast→上传 OSS
```
替换为:
```
  package.py               打包主入口:--channel(默认 dev,仅构建)/--distribute(发布,仅 main)
  _build.py                渠道注册表(dev/dogfood)+ autoninja 构建步骤
  _package.py              stamp 版本/注入 Sparkle 键 + 签名 .app + 样式 dmg(签名/公证/staple)
  _publish.py              发布护栏(分支/干净树/tag+feed 双查)+ appcast + OSS 上传 + 打 v<semver> tag
  _config.py               嵌套 [channel.x] 发布配置加载 + 分级 key 校验
```

3b. 渠道包命令块(原第 101-102 行):
```
uv run python scripts/package_release.py         # 构建→签名→公证→样式dmg(dmgbuild/ULMO)→appcast→上传OSS
uv run python scripts/package_release.py --no-upload   # 仅本地构建+签名+公证(测试,跳过版本护栏)
```
替换为:
```
uv run python scripts/package.py                          # 默认:本地打 dev 包(仅构建,不签名/不发布)
uv run python scripts/package.py --channel dogfood        # 本地渠道包:构建+签名+公证+样式dmg,不发布
uv run python scripts/package.py --channel dogfood --distribute  # 发布(仅 main):+appcast+上传OSS+打 v<semver> tag 并 push
```

3c. 版本注(原第 123 行)中 `package_release` 改为 `package`,并补充 tag:
把 `appcast 只列最新版(\`package_release\` 裁到当前 dmg…` 中的 `package_release` 改为 `package`;在该条目句末追加:`发布时给当前 commit 打 \`v<semver>\` annotated tag 并 push 到 remote(默认 origin);tag 在上传成功后才打,tag 或线上 feed 任一已含该版本即拒绝发布。`

- [ ] **Step 4: 更新 `scripts/smoke_check.md`**(原第 99 行)

把:
```
| 1 | `uv run python scripts/package_release.py`(`TELEPORT_CHROMIUM_DIR` 已设) | 构建→签名→公证→样式dmg→appcast→上传,末尾 `published <ver>` | ✅ |
```
替换为:
```
| 1 | `uv run python scripts/package.py --channel dogfood --distribute`(`TELEPORT_CHROMIUM_DIR` 已设,main 分支) | 构建→签名→公证→样式dmg→appcast→上传→打 `v<ver>` tag,末尾 `published <ver> (dogfood), tagged v<ver>` | ✅ |
```

- [ ] **Step 5: 更新代码注释引用**

5a. `scripts/dmg_settings.py:3`:把 `Invoked by scripts/package_release.py via:` 改为 `Invoked by scripts/package.py via:`。

5b. `scripts/preview_dmg_window.py:7`:把 `WITHOUT running a multi-hour package_release build.` 改为 `WITHOUT running a multi-hour package build.`。

- [ ] **Step 6: 跑全量测试 + 确认无残留引用**

Run: `uv run pytest -q`
Expected: PASS（全绿;含 _config/_build/_package/_publish/package_cli 新用例,旧 test_package_release 已删)

Run: `grep -rn "package_release" scripts/ CLAUDE.md` 
Expected: 无输出(除 `docs/` 历史归档外,代码与活动文档无残留)。

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "refactor(scripts): retire package_release.py for package.py + docs"
```

---

## Self-Review 记录

- **Spec 覆盖**:CLI/渠道模型→Task 2+5;dev 仅构建→Task 5(`test_dev_build_invokes_build_only`);三模式→Task 5;嵌套配置+分级校验→Task 1+5;发布护栏(分支/干净树/tag+feed 双查)→Task 4;tag+push→Task 4;上传后打 tag 时序→Task 5;测试矩阵→各任务;迁移(改名/CLAUDE/example/注释)→Task 6。全部有对应任务。
- **占位符**:无 TBD/TODO;每个代码步骤含完整代码。
- **类型/命名一致**:`Channel.{name,out,distributable,targets}`、`resolve_channel`/`build`、`detect_codesign_identity`/`sparkle_bin`/`stamp_and_inject`/`sign_app`/`build_styled_dmg`、`assert_on_main`/`assert_clean_tree`/`tag_name`/`tag_exists`/`assert_not_published`/`generate_appcast`/`upload_to_oss`/`tag_and_push`、`load_channel_config`/`require_keys`/`STAMP_KEYS`/`NOTARIZE_KEYS`/`PUBLISH_KEYS` 在定义任务与 `package.py` 调用处一致。
