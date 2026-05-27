# macOS dogfood 通道包 + 自动升级 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 macOS(Apple Silicon)产出可分发、能自动升级的 dogfood 通道包:编译 official → 打包 → Developer ID 签名 → 公证 → 对象存储托管 → Sparkle 提示+一键升级。

**Architecture:** Sparkle 2 静态 appcast + EdDSA 签名;app 装 `/Applications`;复用 Chrome 的 `chrome/installer/mac/signing/` 做签名/公证/dmg;一个 GN 开关 `teleport_enable_updater` 把 updater 关在 official 构建;Sparkle.framework 钉版本拉取到全局缓存、符号链接桥进检出;`TELEPORT_VERSION` 单一 semver 既作显示版也作 Sparkle 比较版。

**Tech Stack:** Chromium M148 GN/Siso/autoninja、Sparkle 2(Obj-C++)、`chrome/installer/mac/signing`(Python)、`notarytool`/`stapler`、对象存储 + HTTPS、uv + pytest、gtest。

> **规约**:本仓库 patch = `git diff` 格式、文件名镜像 `chromium/src` 路径、`scripts/apply_patches.py` 幂等应用;一文件一 patch(同文件多处改动累加进同一 patch)。`$TELEPORT_CHROMIUM_DIR` 指向检出,以下用 `$SRC = $TELEPORT_CHROMIUM_DIR/src`。pytest 经 `uv run pytest`(`pythonpath=scripts`)。**先做廉价可测的脚本/纯函数,再做数小时的构建与外部步骤。**

> **对 spec §5.2 的一处落地细化**:Sparkle 的 `SUFeedURL` / `SUPublicEDKey` / `SUEnableAutomaticChecks` **不写进 committed patch**(feed URL 含难猜 token,属敏感信息),改为 `package_release.py` 在签名前用 `plutil` 注入,值来自**未入库**的 `scripts/release_config.local.toml`。其余与 spec 一致。

---

## 文件结构

**新建**
- `TELEPORT_VERSION` — 静态 semver(单一事实来源)。
- `scripts/_release.py` — semver 解析/比较、appcast 版本护栏、读 TELEPORT_VERSION、读发布配置。
- `scripts/tests/test_release.py` — 上者的 pytest。
- `scripts/fetch_sparkle.py` — 钉版本拉取 Sparkle.framework → SHA256 校验 → 落缓存 → 桥接符号链接。
- `scripts/tests/test_fetch_sparkle.py` — 纯函数部分的 pytest。
- `scripts/package_release.py` — 编排:构建 → 戳版本/注入 Sparkle 键 → 签名 driver → 版本护栏 → generate_appcast → 上传。
- `scripts/release_config.local.toml.example` — 发布配置样例(真实文件 `*.local.toml` 不入库)。
- `src/common/teleport_feed_url.h` / `.cc` / `_unittest.cc` — 纯函数 `IsSecureFeedUrl`(gtest)。
- `src/browser/mac/teleport_updater.h` / `.mm` — Sparkle 启动/检查胶水。
- `src/gn/args/release.mac.gn` — official 构建 args。

**修改**
- `scripts/_lib.py` — 加 `deps_cache_dir()`、`sha256_of()`。
- `scripts/tests/test_lib.py` — 上者的 pytest。
- `src/BUILD.gn` — 加 `teleport_enable_updater` arg、feed_url 源文件、mac 条件源 + Sparkle 链接、测试源。
- `patches/chrome/<mac bundle BUILD.gn>.patch` — bundle_data 拷 Sparkle.framework 进 `Contents/Frameworks/`(新建 patch)。
- `patches/chrome/browser/app_controller_mac.mm.patch` — 启动调 `StartMacUpdater`、菜单接 Sparkle(新建 patch)。
- `patches/chrome/installer/mac/signing/parts.py.patch` — 把 Sparkle 内嵌组件纳入签名清单(新建 patch)。
- `patches/chrome/installer/mac/signing/config.py.patch` — teleport 标识符 + Developer ID(新建 patch)。
- `scripts/smoke_check.md` — 追加升级闭环冒烟。
- `CLAUDE.md` — 追加 release 构建 + updater 命令/gotcha。
- `.gitignore` — 忽略 `scripts/release_config.local.toml`。

---

## Phase 0 — 前置(一次性、操作型)

### Task 1: 生成并备份 EdDSA 密钥

**Files:** 无仓库文件改动(密钥进 Keychain + 离线备份)。

- [ ] **Step 1: 先确保 Sparkle 工具已就位**(依赖 Task 7 的 fetch;若尚未拉取,可先手动下载同版本)

Run: `ls "$(python3 -c 'import sys;sys.path.insert(0,"scripts");import _lib;print(_lib.deps_cache_dir())')"/sparkle/*/bin/generate_keys 2>/dev/null || echo "run fetch_sparkle.py first (Task 7)"`

- [ ] **Step 2: 生成 EdDSA 密钥对(私钥进 login Keychain)**

Run: `"<sparkle>/bin/generate_keys"`
Expected: 打印 base64 公钥(`SUPublicEDKey` 用),并提示私钥已存入 Keychain。记下公钥。

- [ ] **Step 3: 导出私钥做离线加密备份**

Run: `"<sparkle>/bin/generate_keys" -x sparkle_private_ed_key.txt`
Expected: 生成私钥文件。将其加密存入密码管理器 + 离线介质,然后 `rm sparkle_private_ed_key.txt`。**切勿入库。**

- [ ] **Step 4: 记录公钥到本地发布配置(见 Task 15 的 release_config.local.toml)**

无命令;把 Step 2 的公钥粘进 `scripts/release_config.local.toml` 的 `public_ed_key`。

### Task 2: 确认 Developer ID 身份 + 准备对象存储桶

**Files:** 无。

- [ ] **Step 1: 确认 Developer ID Application 证书在 Keychain**

Run: `security find-identity -v -p codesigning | grep "Developer ID Application"`
Expected: 至少一条 `Developer ID Application: <Name> (<TEAMID>)`。记下完整身份串与 TEAMID。

- [ ] **Step 2: 准备 notarytool 凭据(App Store Connect API key 或 app-specific 密码)存 Keychain profile**

Run: `xcrun notarytool store-credentials teleport-notary --apple-id "<apple-id>" --team-id "<TEAMID>" --password "<app-specific-password>"`
Expected: `Credentials saved to Keychain.`(profile 名 `teleport-notary` 供后续 `notarytool submit --keychain-profile teleport-notary`)。

- [ ] **Step 3: 创建对象存储桶 + 难猜路径前缀(手动,厂商自选)**

无统一命令。要点:公开可读、HTTPS、路径含不可猜测随机段,例如 `dogfood/<token>/`。记录基址 `https://<host>/dogfood/<token>/` 供 feed URL。

---

## Phase 1 — 版本号与发布护栏(TDD)

### Task 3: `TELEPORT_VERSION` + semver 解析/比较

**Files:**
- Create: `TELEPORT_VERSION`
- Create: `scripts/_release.py`
- Test: `scripts/tests/test_release.py`

- [ ] **Step 1: 写失败测试**

```python
# scripts/tests/test_release.py
import pytest

import _release


def test_parse_semver_ok():
    assert _release.parse_semver("0.1.0") == (0, 1, 0)
    assert _release.parse_semver(" 1.2.3 ") == (1, 2, 3)


@pytest.mark.parametrize("bad", ["0.1", "1.2.3.4", "v1.0.0", "x", ""])
def test_parse_semver_rejects(bad):
    with pytest.raises(ValueError):
        _release.parse_semver(bad)


def test_is_newer():
    assert _release.is_newer("0.1.1", "0.1.0")
    assert _release.is_newer("0.2.0", "0.1.9")
    assert not _release.is_newer("0.1.0", "0.1.0")
    assert not _release.is_newer("0.1.0", "0.1.1")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_release.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named '_release'`）。

- [ ] **Step 3: 写最小实现**

```python
# scripts/_release.py
"""Release helpers: teleport semver parsing/comparison and the appcast guard."""
from __future__ import annotations

import re

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse 'MAJOR.MINOR.PATCH' into a comparable tuple. Raises ValueError."""
    m = _SEMVER_RE.match(version.strip())
    if not m:
        raise ValueError(f"not a MAJOR.MINOR.PATCH semver: {version!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_newer(candidate: str, baseline: str) -> bool:
    """True iff candidate semver is strictly greater than baseline semver."""
    return parse_semver(candidate) > parse_semver(baseline)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_release.py -q`
Expected: PASS。

- [ ] **Step 5: 创建 TELEPORT_VERSION**

```
0.1.0
```

Run: `printf '0.1.0\n' > TELEPORT_VERSION`

- [ ] **Step 6: 提交**

```bash
git add TELEPORT_VERSION scripts/_release.py scripts/tests/test_release.py
git commit -m "feat(release): TELEPORT_VERSION + semver helpers"
```

### Task 4: appcast 版本护栏 + 读 TELEPORT_VERSION

**Files:**
- Modify: `scripts/_release.py`
- Test: `scripts/tests/test_release.py`

- [ ] **Step 1: 追加失败测试**

```python
# append to scripts/tests/test_release.py
APPCAST = """<?xml version="1.0"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
 <channel>
  <item><sparkle:version>0.1.0</sparkle:version></item>
  <item><sparkle:version>0.1.2</sparkle:version></item>
  <item><sparkle:version>0.1.1</sparkle:version></item>
 </channel>
</rss>"""


def test_max_appcast_version():
    assert _release.max_appcast_version(APPCAST) == "0.1.2"


def test_max_appcast_version_empty():
    empty = '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel/></rss>'
    assert _release.max_appcast_version(empty) is None


def test_assert_publishable_allows_newer():
    _release.assert_publishable("0.1.3", APPCAST)  # must not raise


def test_assert_publishable_blocks_equal_or_older():
    with pytest.raises(SystemExit):
        _release.assert_publishable("0.1.2", APPCAST)
    with pytest.raises(SystemExit):
        _release.assert_publishable("0.1.0", APPCAST)


def test_assert_publishable_empty_feed_ok():
    _release.assert_publishable("0.1.0", None)
    _release.assert_publishable("0.1.0", "")


def test_read_teleport_version(tmp_path):
    (tmp_path / "TELEPORT_VERSION").write_text("0.4.2\n")
    assert _release.read_teleport_version(tmp_path) == "0.4.2"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_release.py -q`
Expected: FAIL（`AttributeError: module '_release' has no attribute 'max_appcast_version'`）。

- [ ] **Step 3: 追加实现**

```python
# append to scripts/_release.py
import xml.etree.ElementTree as ET
from pathlib import Path

_SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def max_appcast_version(appcast_xml: str) -> str | None:
    """Highest sparkle:version across <item>s, or None for an empty feed.

    Accepts sparkle:version either as a child element or as an attribute on the
    <enclosure> (both forms occur in the wild).
    """
    root = ET.fromstring(appcast_xml)
    best: tuple[int, int, int] | None = None
    best_raw: str | None = None
    for item in root.iter("item"):
        el = item.find(f"{{{_SPARKLE_NS}}}version")
        if el is not None and el.text:
            raw = el.text.strip()
        else:
            enc = item.find("enclosure")
            raw = enc.get(f"{{{_SPARKLE_NS}}}version") if enc is not None else None
        if not raw:
            continue
        try:
            t = parse_semver(raw)
        except ValueError:
            continue
        if best is None or t > best:
            best, best_raw = t, raw
    return best_raw


def assert_publishable(new_version: str, appcast_xml: str | None) -> None:
    """Exit non-zero if new_version is not strictly newer than the feed's max."""
    if not appcast_xml or not appcast_xml.strip():
        return
    current = max_appcast_version(appcast_xml)
    if current is None:
        return
    if not is_newer(new_version, current):
        raise SystemExit(
            f"refusing to publish {new_version}: not newer than current feed max {current}"
        )


def read_teleport_version(root: Path | None = None) -> str:
    """Read + validate the TELEPORT_VERSION semver from the repo root."""
    from _lib import repo_root
    p = (root or repo_root()) / "TELEPORT_VERSION"
    v = p.read_text().strip()
    parse_semver(v)  # validate; raises on garbage
    return v
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_release.py -q`
Expected: PASS（全部）。

- [ ] **Step 5: 提交**

```bash
git add scripts/_release.py scripts/tests/test_release.py
git commit -m "feat(release): appcast version guard + read_teleport_version"
```

---

## Phase 2 — Sparkle 获取 + overlay 集成

### Task 5: `_lib.py` 加 `deps_cache_dir()` + `sha256_of()`（TDD）

**Files:**
- Modify: `scripts/_lib.py`
- Test: `scripts/tests/test_lib.py`

- [ ] **Step 1: 追加失败测试**

```python
# append to scripts/tests/test_lib.py
def test_deps_cache_dir_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPORT_DEPS_DIR", str(tmp_path / "d"))
    assert _lib.deps_cache_dir() == tmp_path / "d"


def test_deps_cache_dir_default(monkeypatch):
    monkeypatch.delenv("TELEPORT_DEPS_DIR", raising=False)
    d = _lib.deps_cache_dir()
    assert d.name == "deps" and d.parent.name == "teleport"


def test_sha256_of_known_vectors(tmp_path):
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    assert _lib.sha256_of(empty) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    abc = tmp_path / "abc"
    abc.write_bytes(b"abc")
    assert _lib.sha256_of(abc) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_lib.py -q`
Expected: FAIL（`AttributeError: module '_lib' has no attribute 'deps_cache_dir'`）。

- [ ] **Step 3: 追加实现到 `scripts/_lib.py`**

```python
# add near the top-level helpers in scripts/_lib.py
import hashlib


def deps_cache_dir() -> Path:
    """External deps cache (Sparkle, etc.). Honors $TELEPORT_DEPS_DIR;
    defaults to ~/.cache/teleport/deps. Shared across worktrees; gitignored
    (lives outside the repo)."""
    env = os.environ.get("TELEPORT_DEPS_DIR")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "teleport" / "deps"


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file's contents (streamed)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_lib.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/_lib.py scripts/tests/test_lib.py
git commit -m "feat(deps): deps_cache_dir + sha256_of helpers"
```

### Task 6: `fetch_sparkle.py` — 拉取/校验/桥接

**Files:**
- Create: `scripts/fetch_sparkle.py`
- Test: `scripts/tests/test_fetch_sparkle.py`

- [ ] **Step 1: 写失败测试(纯函数:路径解析 + 校验)**

```python
# scripts/tests/test_fetch_sparkle.py
import pytest

import fetch_sparkle


def test_cache_framework_path_uses_version(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPORT_DEPS_DIR", str(tmp_path))
    p = fetch_sparkle.cache_framework_path()
    assert p.parent.name == fetch_sparkle.SPARKLE_VERSION
    assert p.name == "Sparkle.framework"


def test_link_path_under_chromium_src(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(tmp_path / "cr"))
    p = fetch_sparkle.link_path()
    assert p.name == "Sparkle.framework"
    assert "third_party/teleport_sparkle" in str(p)


def test_verify_sha256_matches(tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"abc")
    fetch_sparkle.verify_sha256(
        f, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )  # must not raise


def test_verify_sha256_mismatch_raises(tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"abc")
    with pytest.raises(RuntimeError):
        fetch_sparkle.verify_sha256(f, "deadbeef")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_fetch_sparkle.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'fetch_sparkle'`）。

- [ ] **Step 3: 写实现(纯函数先就位,常量待 Step 5 钉死)**

```python
# scripts/fetch_sparkle.py
#!/usr/bin/env python3
"""Fetch the pinned, notarized Sparkle release into the shared deps cache and
bridge Sparkle.framework into the chromium checkout via a symlink that GN
bundle_data references. Idempotent: re-running only re-ensures the symlink.
"""
from __future__ import annotations

import argparse
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from _lib import chromium_src, create_dir_link, deps_cache_dir, sha256_of

# Pinned Sparkle 2.x release. Update SPARKLE_VERSION + SPARKLE_SHA256 together
# (Step 5 of this task computes the sha from the downloaded asset).
SPARKLE_VERSION = "2.6.4"  # TODO(Step 5): confirm latest stable 2.x
SPARKLE_SHA256 = "0" * 64  # TODO(Step 5): pin to the real asset sha256

# Path inside the chromium checkout where the framework is symlinked. GN
# bundle_data + the link config reference //third_party/teleport_sparkle.
LINK_RELPATH = "third_party/teleport_sparkle"


def archive_url() -> str:
    return (
        "https://github.com/sparkle-project/Sparkle/releases/download/"
        f"{SPARKLE_VERSION}/Sparkle-{SPARKLE_VERSION}.tar.xz"
    )


def cache_dir() -> Path:
    return deps_cache_dir() / "sparkle" / SPARKLE_VERSION


def cache_framework_path() -> Path:
    return cache_dir() / "Sparkle.framework"


def link_path(root: Path | None = None) -> Path:
    return chromium_src(root) / LINK_RELPATH / "Sparkle.framework"


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_of(path)
    if actual != expected:
        raise RuntimeError(f"sha256 mismatch for {path}: got {actual}, expected {expected}")


def download_and_extract() -> None:
    """Download the pinned archive, verify sha256, extract into the cache."""
    dst = cache_dir()
    if (dst / "Sparkle.framework").exists():
        return  # already populated
    dst.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.xz", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve(archive_url(), tmp_path)
        verify_sha256(tmp_path, SPARKLE_SHA256)
        with tarfile.open(tmp_path, "r:xz") as tar:
            tar.extractall(dst, filter="data")
    finally:
        tmp_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Fetch + link the pinned Sparkle.framework").parse_args(argv)
    download_and_extract()
    fw = cache_framework_path()
    if not fw.exists():
        print(f"error: {fw} missing after extract", file=sys.stderr)
        return 1
    create_dir_link(link_path(), fw)
    print(f"sparkle ready: {link_path()} -> {fw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_fetch_sparkle.py -q`
Expected: PASS（纯函数测试;未触网)。

- [ ] **Step 5: 钉死真实版本与 SHA256(实测)**

1. 打开 <https://github.com/sparkle-project/Sparkle/releases> 选最新 stable 2.x,把 `SPARKLE_VERSION` 改成该版本号。
2. 计算资产 sha256:
   Run: `curl -fsSL "$(python3 -c 'import sys;sys.path.insert(0,"scripts");import fetch_sparkle as f;print(f.archive_url())')" | shasum -a 256`
   把输出的 64 位 hex 填入 `SPARKLE_SHA256`,删掉两个 `TODO`。

- [ ] **Step 6: 真跑一次(集成验证,需网络 + 已 bootstrap 的检出)**

Run: `uv run python scripts/fetch_sparkle.py`
Expected: `sparkle ready: .../third_party/teleport_sparkle/Sparkle.framework -> ~/.cache/teleport/deps/sparkle/<ver>/Sparkle.framework`
Verify: `ls -l "$SRC/third_party/teleport_sparkle/Sparkle.framework/Versions/Current/Sparkle"` 存在;`ls "$(...)"/sparkle/<ver>/bin/generate_keys` 存在(供 Task 1)。

- [ ] **Step 7: 提交**

```bash
git add scripts/fetch_sparkle.py scripts/tests/test_fetch_sparkle.py
git commit -m "feat(deps): fetch_sparkle.py (pinned fetch + sha256 + symlink bridge)"
```

### Task 7: 纯 C++ `IsSecureFeedUrl` + gtest

**Files:**
- Create: `src/common/teleport_feed_url.h`, `src/common/teleport_feed_url.cc`, `src/common/teleport_feed_url_unittest.cc`
- Modify: `src/BUILD.gn`

- [ ] **Step 1: 写头文件 + 失败测试**

```cpp
// src/common/teleport_feed_url.h
#ifndef TELEPORT_COMMON_TELEPORT_FEED_URL_H_
#define TELEPORT_COMMON_TELEPORT_FEED_URL_H_

#include <string_view>

namespace teleport {

// True only for an https:// URL. The updater refuses to start with anything
// else (defense-in-depth alongside the EdDSA appcast signature).
bool IsSecureFeedUrl(std::string_view url);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_FEED_URL_H_
```

```cpp
// src/common/teleport_feed_url_unittest.cc
#include "teleport/common/teleport_feed_url.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportFeedUrlTest, AcceptsHttps) {
  EXPECT_TRUE(IsSecureFeedUrl("https://example.com/dogfood/tok/appcast.xml"));
}

TEST(TeleportFeedUrlTest, RejectsHttp) {
  EXPECT_FALSE(IsSecureFeedUrl("http://example.com/appcast.xml"));
}

TEST(TeleportFeedUrlTest, RejectsEmptyAndBareScheme) {
  EXPECT_FALSE(IsSecureFeedUrl(""));
  EXPECT_FALSE(IsSecureFeedUrl("https://"));
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: 把测试源加入 `src/BUILD.gn` 的 test 目标,跑确认失败**

在 `test("teleport_unittests")` 的 `sources` 加 `"common/teleport_feed_url_unittest.cc"`,并在 `source_set("teleport")` 的 `sources` 加 `"common/teleport_feed_url.cc"` 与 `"common/teleport_feed_url.h"`。

Run: `python scripts/apply_patches.py && autoninja -C out/mac/arm64/dev teleport_unittests`
Expected: 链接失败 `undefined symbol teleport::IsSecureFeedUrl`(.cc 尚空)。

- [ ] **Step 3: 写实现**

```cpp
// src/common/teleport_feed_url.cc
#include "teleport/common/teleport_feed_url.h"

namespace teleport {

bool IsSecureFeedUrl(std::string_view url) {
  constexpr std::string_view kHttps = "https://";
  return url.size() > kHttps.size() && url.substr(0, kHttps.size()) == kHttps;
}

}  // namespace teleport
```

- [ ] **Step 4: 构建并跑 gtest 确认通过**

Run: `autoninja -C out/mac/arm64/dev teleport_unittests && "$SRC/out/mac/arm64/dev/teleport_unittests" --gtest_filter='TeleportFeedUrlTest.*'`
Expected: 3 个用例 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/common/teleport_feed_url.h src/common/teleport_feed_url.cc src/common/teleport_feed_url_unittest.cc src/BUILD.gn
git commit -m "feat(updater): IsSecureFeedUrl pure helper + gtest"
```

### Task 8: GN 开关 + mac updater 胶水 + Sparkle 链接

**Files:**
- Create: `src/browser/mac/teleport_updater.h`, `src/browser/mac/teleport_updater.mm`
- Modify: `src/BUILD.gn`

- [ ] **Step 1: 写头文件**

```cpp
// src/browser/mac/teleport_updater.h
#ifndef TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_

namespace teleport {

// Starts the Sparkle updater once on the main thread. Reads SUFeedURL /
// SUPublicEDKey from the main bundle (injected at packaging time). No-op if
// the feed is missing or not https. Idempotent.
void StartMacUpdater();

// User-initiated check, for the "Check for Updates…" menu item.
void CheckForUpdatesNow();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
```

- [ ] **Step 2: 写实现**

```objc
// src/browser/mac/teleport_updater.mm
#import "teleport/browser/mac/teleport_updater.h"

#import <Foundation/Foundation.h>
#import <Sparkle/Sparkle.h>

#include <string>

#include "teleport/common/teleport_feed_url.h"

namespace teleport {
namespace {

// Global objects under ARC are __strong by default, so this retains.
SPUStandardUpdaterController* g_controller = nil;

bool FeedIsSecure() {
  NSString* feed =
      [[NSBundle mainBundle] objectForInfoDictionaryKey:@"SUFeedURL"];
  return feed != nil && IsSecureFeedUrl(std::string([feed UTF8String]));
}

}  // namespace

void StartMacUpdater() {
  if (g_controller != nil || !FeedIsSecure()) {
    return;
  }
  g_controller = [[SPUStandardUpdaterController alloc]
      initWithStartingUpdater:YES
              updaterDelegate:nil
           userDriverDelegate:nil];
}

void CheckForUpdatesNow() {
  StartMacUpdater();
  [g_controller checkForUpdates:nil];
}

}  // namespace teleport
```

- [ ] **Step 3: 改 `src/BUILD.gn`(完整内容)**

```gn
# The //teleport additive module, compiled into chrome via a minimal upstream
# BUILD.gn dep patch (see patches/). A standalone test() target keeps unit
# tests buildable without patching upstream test targets.
import("//testing/test.gni")

declare_args() {
  # Enable the Sparkle-based auto-updater. On for official channel builds
  # (release.mac.gn); off for dev so the dev workflow needs no framework/signing.
  teleport_enable_updater = false
}

# Inside-checkout dir where fetch_sparkle.py symlinks the pinned framework.
teleport_sparkle_dir = "//third_party/teleport_sparkle"

config("sparkle_link") {
  visibility = [ ":*" ]
  framework_dirs = [ rebase_path(teleport_sparkle_dir, root_build_dir) ]
  frameworks = [ "Sparkle.framework" ]
}

source_set("teleport") {
  sources = [
    "browser/teleport_startup.cc",
    "browser/teleport_startup.h",
    "common/teleport_feed_url.cc",
    "common/teleport_feed_url.h",
    "common/teleport_url_scheme.cc",
    "common/teleport_url_scheme.h",
  ]
  deps = [
    "//base",
    "//content/public/common",
    "//url",
  ]
  if (teleport_enable_updater && is_mac) {
    sources += [
      "browser/mac/teleport_updater.h",
      "browser/mac/teleport_updater.mm",
    ]
    configs += [ ":sparkle_link" ]
  }
}

test("teleport_unittests") {
  sources = [
    "browser/teleport_startup_unittest.cc",
    "common/teleport_feed_url_unittest.cc",
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

- [ ] **Step 4: 验证 dev 构建不受影响(updater 默认关)**

Run: `python scripts/apply_patches.py && autoninja -C out/mac/arm64/dev teleport_unittests && "$SRC/out/mac/arm64/dev/teleport_unittests" -q`
Expected: 构建通过、单测全过(未编译 .mm,无需 Sparkle)。

- [ ] **Step 5: 验证开 updater 能编译链接(需 Task 6 已拉 Sparkle)**

先确保 `python scripts/fetch_sparkle.py` 已跑。
Run: `gn gen out/mac/arm64/release-probe --args='import("//teleport/gn/args/dev.mac.gn") teleport_enable_updater=true' && autoninja -C out/mac/arm64/release-probe teleport`
Expected: `teleport` 目标编译链接成功(`teleport_updater.mm` 找到 `<Sparkle/Sparkle.h>` 并链接 Sparkle.framework)。若 `framework_dirs`/`frameworks` 不被链接接受,据报错调整为 `ldflags = [ "-F" + rebase_path(teleport_sparkle_dir, root_build_dir) ]` + `libs`/`frameworks`,直至链接通过。完成后 `rm -rf "$SRC/out/mac/arm64/release-probe"`。

- [ ] **Step 6: 提交**

```bash
git add src/browser/mac/teleport_updater.h src/browser/mac/teleport_updater.mm src/BUILD.gn
git commit -m "feat(updater): teleport_enable_updater gate + Sparkle mac glue"
```

### Task 9: patch — 把 Sparkle.framework 拷进 app bundle 的 Frameworks

**Files:**
- Create: `patches/chrome/<定位到的 mac bundle BUILD.gn>.patch`

- [ ] **Step 1: 定位拷贝 framework 进 bundle 的 GN target**

Run: `grep -rn "Contents/Frameworks\|bundle_data\|chrome_framework_bundle_data" "$SRC/chrome/BUILD.gn" | head -30`
找到把 `*.framework` 装进 `{{bundle_contents_dir}}/Frameworks` 的 `bundle_data`/`mac_app_bundle` 处(通常在 `chrome/BUILD.gn`)。记下文件与 target。

- [ ] **Step 2: 在该文件加一个 bundle_data 并让 app 依赖它**

编辑 `$SRC/<定位文件>`,新增(并把 target 名加入 app bundle 的 `deps`):

```gn
if (teleport_enable_updater) {
  bundle_data("teleport_sparkle_framework") {
    sources = [ "//third_party/teleport_sparkle/Sparkle.framework" ]
    outputs = [ "{{bundle_contents_dir}}/Frameworks/Sparkle.framework" ]
  }
}
```

`teleport_enable_updater` 在 `//teleport/BUILD.gn` 已 `declare_args`,跨文件可见。若该 BUILD.gn 未 import 到该 arg 作用域,在文件顶部加 `import("//teleport/BUILD.gn")` 不可取——改为在 app bundle 的 `deps` 处用 `if (teleport_enable_updater) { deps += [ "//chrome:teleport_sparkle_framework" ] }`(arg 为全局 build arg,声明一次即全局可见,无需 import)。

> 注:`bundle_data` 对**目录型** framework 的拷贝,M148 GN 用 `sources = [ ".../Sparkle.framework" ]` + `{{bundle_contents_dir}}/Frameworks/Sparkle.framework`;若 GN 要求逐文件,改用 framework 的 `copy`/`mac_framework_bundle` 惯用法,以 Step 4 构建验证为准。

- [ ] **Step 3: 生成 patch**

Run: `git -C "$SRC" diff -- chrome/BUILD.gn > patches/chrome/BUILD.gn.patch`（路径替换为 Step 1 实际文件;若该文件已有 patch,改为把改动**累加**进既有 patch:先 `git -C "$SRC" checkout <file>`、`python scripts/apply_patches.py`、再编辑、再 `git diff` 覆盖原 patch)。

- [ ] **Step 4: 构建 official-probe 验证 framework 进包**

Run: `gn gen out/mac/arm64/release-probe --args='import("//teleport/gn/args/release.mac.gn")' && autoninja -C out/mac/arm64/release-probe chrome`
Expected: 构建成功。Verify: `ls -d out/mac/arm64/release-probe/Teleport.app/Contents/Frameworks/Sparkle.framework`（注:`release.mac.gn` 由 Task 11 创建;若尚未,临时用 `dev.mac.gn + teleport_enable_updater=true`)。完成后清理 probe 目录。

- [ ] **Step 5: 提交**

```bash
git add patches/
git commit -m "feat(updater): bundle Sparkle.framework into the app Frameworks"
```

### Task 10: patch — `app_controller_mac.mm` 启动调用 + 菜单接 Sparkle

**Files:**
- Create: `patches/chrome/browser/app_controller_mac.mm.patch`

- [ ] **Step 1: 定位启动钩子与「检查更新」菜单**

Run: `grep -n "applicationDidFinishLaunching\|applicationWillFinishLaunching" "$SRC/chrome/browser/app_controller_mac.mm" | head`
Run: `grep -in "update\|keystone\|IDC_.*UPDATE\|checkForUpdates" "$SRC/chrome/browser/app_controller_mac.mm" | head -30`
记下:启动方法名、菜单动作选择器/命令位置。

- [ ] **Step 2: 注入 include + 启动调用 + 菜单路由**

在 `$SRC/chrome/browser/app_controller_mac.mm`:
1. 顶部加 `#import "teleport/browser/mac/teleport_updater.h"  // teleport overlay`。
2. 在 `-applicationDidFinishLaunching:`(或 `-applicationWillFinishLaunching:`)体内加:
   ```objc
   teleport::StartMacUpdater();  // teleport overlay
   ```
3. 把原 Keystone「Check for Updates」动作体改为调用 `teleport::CheckForUpdatesNow();`(据 Step 1 定位的选择器;若 Keystone 路径用 `#if BUILDFLAG(...)` 包裹,在其旁加 teleport 分支)。

> 这些 `teleport::` 符号仅在 `teleport_enable_updater && is_mac` 编进 `//teleport`。dev 构建(updater 关)下 `//teleport` 不含这些符号,故该 patch 的调用**必须**同样受编译期保护。做法:在调用处用 `#if defined(TELEPORT_ENABLE_UPDATER)` 包裹,并在 `config("sparkle_link")` 加 `defines = [ "TELEPORT_ENABLE_UPDATER" ]`、同时让 `app_controller` 在该 arg 下获得该 define。**更简单稳妥**:把调用恒定保留,但在 `//teleport` 中**无条件**导出 `StartMacUpdater`/`CheckForUpdatesNow` 的弱实现——见 Step 3。

- [ ] **Step 3: 让符号无条件存在(避免 dev 构建链接失败)**

把 `teleport_updater.h` 的两个函数改为**始终声明**;在 `src/BUILD.gn` 中**无条件**编译一个轻量 `browser/mac/teleport_updater_stub.cc`(当 `!teleport_enable_updater || !is_mac`)提供空实现,真实 `.mm`(含 Sparkle)仅在开关开时替换。即:
- `teleport_enable_updater && is_mac` → 编 `teleport_updater.mm`(真实现 + 链接 Sparkle)。
- 否则 → 编 `browser/mac/teleport_updater_stub.cc`(空实现,无 Sparkle 依赖)。

新增 `src/browser/mac/teleport_updater_stub.cc`:
```cpp
#include "teleport/browser/mac/teleport_updater.h"
namespace teleport {
void StartMacUpdater() {}
void CheckForUpdatesNow() {}
}  // namespace teleport
```
并改 `src/BUILD.gn` 的条件块:
```gn
  if (is_mac) {
    sources += [ "browser/mac/teleport_updater.h" ]
    if (teleport_enable_updater) {
      sources += [ "browser/mac/teleport_updater.mm" ]
      configs += [ ":sparkle_link" ]
    } else {
      sources += [ "browser/mac/teleport_updater_stub.cc" ]
    }
  }
```
这样 `app_controller_mac.mm` 可**无条件**调用,dev 构建拿到空实现、不依赖 Sparkle。

- [ ] **Step 4: 生成 patch 并验证 dev + official 均构建通过**

Run: `git -C "$SRC" diff -- chrome/browser/app_controller_mac.mm > patches/chrome/browser/app_controller_mac.mm.patch`
Run（dev,updater 关):`python scripts/apply_patches.py && autoninja -C out/mac/arm64/dev chrome`
Expected: 链接通过(空实现)。
Run（official-probe,updater 开):同 Task 9 Step 4 构建 chrome,通过。

- [ ] **Step 5: 提交**

```bash
git add patches/chrome/browser/app_controller_mac.mm.patch src/browser/mac/teleport_updater_stub.cc src/browser/mac/teleport_updater.h src/BUILD.gn
git commit -m "feat(updater): start Sparkle at launch + wire Check-for-Updates menu"
```

### Task 11: official 构建 args `release.mac.gn`

**Files:**
- Create: `src/gn/args/release.mac.gn`

- [ ] **Step 1: 写 args**

```gn
# Official channel build args for the teleport overlay on macOS (Apple Silicon).
# Distinct out dir from dev (out/mac/arm64/release). One build serves all
# channels; channel identity (feed URL / bundle id) is applied at packaging
# time by scripts/package_release.py — see the dogfood channel spec §3.4.
target_os = "mac"
target_cpu = "arm64"

is_debug = false
is_official_build = true
is_component_build = false
use_remoteexec = false

# Enable the Sparkle auto-updater (compiles browser/mac/teleport_updater.mm and
# links Sparkle.framework; requires `python scripts/fetch_sparkle.py` first).
teleport_enable_updater = true

# Proprietary / platform audio-video codecs (same as dev.mac.gn rationale).
proprietary_codecs = true
ffmpeg_branding = "Chrome"
enable_hevc_parser_and_hw_decoder = true
enable_platform_dolby_vision = true
enable_platform_ac3_eac3_audio = true
enable_platform_ac4_audio = true
enable_platform_dts_audio = true
enable_platform_mpeg_h_audio = true
```

- [ ] **Step 2: 验证 args 解析 + gn gen 成功**

Run: `python scripts/fetch_sparkle.py && python scripts/apply_patches.py && gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'`
Expected: `Done. Made N targets ...`,无 args 报错。

- [ ] **Step 3: 提交**

```bash
git add src/gn/args/release.mac.gn
git commit -m "feat(build): release.mac.gn official channel build args"
```

---

## Phase 3 — 签名 / 公证(复用 chrome/installer/mac/signing)

### Task 12: 配置签名模块为 teleport 标识符 + Developer ID

**Files:**
- Create: `patches/chrome/installer/mac/signing/config.py.patch`(或模块内对应配置文件)

- [ ] **Step 1: 读懂签名模块的 fork 配置入口**

Run: `sed -n '1,80p' "$SRC/chrome/installer/mac/signing/config.py"; echo ---; sed -n '1,60p' "$SRC/chrome/installer/mac/signing/rebranding.py"`
确认:`base_config_identifier`、`identity`(签名身份)、bundle id、distributions 的来源。

- [ ] **Step 2: 配置为 teleport 值**

编辑 `$SRC/chrome/installer/mac/signing/config.py`(或其引用的 brand 配置),设置:
- 签名 `identity` = Task 2 记录的 `Developer ID Application: <Name> (<TEAMID>)`。
- product/bundle id = `org.teleport.Teleport`(与 BRANDING 的 `MAC_BUNDLE_ID` 一致;Run `grep -n MAC_BUNDLE_ID "$SRC/chrome/app/theme/chromium/BRANDING"` 核对)。
- 单一 distribution(dogfood),无 channel 后缀。

具体字段名以 Step 1 实际为准;保持「最小改动让模块认得 teleport 身份」。

- [ ] **Step 3: 生成 patch**

Run: `git -C "$SRC" diff -- chrome/installer/mac/signing/config.py > patches/chrome/installer/mac/signing/config.py.patch`

- [ ] **Step 4: 用模块自带测试做回归**

Run: `python "$SRC/chrome/installer/mac/signing/run_mac_signing_tests.py"`
Expected: 测试通过(确认配置改动未破坏模块自检)。

- [ ] **Step 5: 提交**

```bash
git add patches/chrome/installer/mac/signing/config.py.patch
git commit -m "feat(signing): configure mac signing module for teleport identity"
```

### Task 13: patch — 把 Sparkle 内嵌组件纳入签名清单(parts.py)

**Files:**
- Create: `patches/chrome/installer/mac/signing/parts.py.patch`

- [ ] **Step 1: 读 parts.py 的组件清单结构**

Run: `grep -n "CodeSignedProduct\|Frameworks/\|XPCServices\|def get_parts\|parts\[" "$SRC/chrome/installer/mac/signing/parts.py" | head -40`
理解每个内嵌项(framework、helper)如何登记、签名顺序(inside-out)。

- [ ] **Step 2: 追加 Sparkle 的内嵌项**

在 `get_parts(...)`(或等价)按现有 helper 项的写法,登记(路径相对 `Contents/Frameworks/Sparkle.framework`):
- `Sparkle.framework/Versions/B/Autoupdate`
- `Sparkle.framework/Versions/B/Updater.app`
- `Sparkle.framework/Versions/B/XPCServices/Installer.xpc`
- `Sparkle.framework/Versions/B/XPCServices/Downloader.xpc`
- `Sparkle.framework` 本体

确切子路径以拉取到的 Sparkle 版本为准:`ls -R "$SRC/third_party/teleport_sparkle/Sparkle.framework/Versions/Current/"` 核对实际内嵌可执行/xpc,逐一登记,确保排在 app 本体之前(inside-out)。

- [ ] **Step 3: 生成 patch**

Run: `git -C "$SRC" diff -- chrome/installer/mac/signing/parts.py > patches/chrome/installer/mac/signing/parts.py.patch`

- [ ] **Step 4: 模块自检**

Run: `python "$SRC/chrome/installer/mac/signing/run_mac_signing_tests.py"`
Expected: 通过。

- [ ] **Step 5: 提交**

```bash
git add patches/chrome/installer/mac/signing/parts.py.patch
git commit -m "feat(signing): sign nested Sparkle XPC/Autoupdate components"
```

---

## Phase 4 — 打包 + 发布

### Task 14: 发布配置样例 + gitignore

**Files:**
- Create: `scripts/release_config.local.toml.example`
- Modify: `.gitignore`

- [ ] **Step 1: 写样例配置**

```toml
# Copy to scripts/release_config.local.toml (gitignored) and fill in.
# Sparkle public EdDSA key (base64) printed by generate_keys (Task 1).
public_ed_key = "PASTE_BASE64_PUBLIC_KEY"

# Appcast feed URL (object storage, https, includes the unguessable token).
feed_url = "https://<host>/dogfood/<token>/appcast.xml"

# Base https URL the dmg + appcast are uploaded under (trailing slash).
upload_base_url = "https://<host>/dogfood/<token>/"

# Developer ID Application identity (security find-identity output).
codesign_identity = "Developer ID Application: <Name> (<TEAMID>)"

# notarytool keychain profile name (Task 2 Step 2).
notary_profile = "teleport-notary"
```

- [ ] **Step 2: gitignore 真实文件**

在 `.gitignore` 追加:
```
# Local release config (holds feed token / signing identity)
/scripts/release_config.local.toml
```

- [ ] **Step 3: 提交**

```bash
git add scripts/release_config.local.toml.example .gitignore
git commit -m "feat(release): release config example + gitignore local config"
```

### Task 15: `package_release.py` — 编排脚本

**Files:**
- Create: `scripts/package_release.py`
- Test: `scripts/tests/test_package_release.py`

- [ ] **Step 1: 写失败测试(纯函数:读配置 + 校验必填)**

```python
# scripts/tests/test_package_release.py
import pytest

import package_release


def test_load_config_ok(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text(
        'public_ed_key="k"\nfeed_url="https://h/a/appcast.xml"\n'
        'upload_base_url="https://h/a/"\ncodesign_identity="Developer ID Application: X (T)"\n'
        'notary_profile="p"\n'
    )
    c = package_release.load_config(cfg)
    assert c["feed_url"].startswith("https://")
    assert c["notary_profile"] == "p"


def test_load_config_missing_key_raises(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('feed_url="https://h/a/appcast.xml"\n')
    with pytest.raises(SystemExit):
        package_release.load_config(cfg)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest scripts/tests/test_package_release.py -q`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 写实现**

```python
# scripts/package_release.py
#!/usr/bin/env python3
"""Package a signed + notarized teleport dmg and publish its appcast entry.

Pipeline: build (official) -> stamp version + inject Sparkle keys (pre-sign) ->
chrome signing module (sign + notarize + dmg) -> appcast version guard ->
generate_appcast -> upload. Run from the repo root after `gn gen out/mac/arm64/release`.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

from _lib import chromium_src, deps_cache_dir, repo_root
from _release import assert_publishable, read_teleport_version
from fetch_sparkle import SPARKLE_VERSION

_REQUIRED = ("public_ed_key", "feed_url", "upload_base_url", "codesign_identity", "notary_profile")


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing {path} (copy release_config.local.toml.example)")
    cfg = tomllib.loads(path.read_text())
    missing = [k for k in _REQUIRED if not cfg.get(k)]
    if missing:
        raise SystemExit(f"release config missing keys: {', '.join(missing)}")
    return cfg


def fetch_live_appcast(feed_url: str) -> str | None:
    try:
        with urllib.request.urlopen(feed_url) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None  # first release: no feed yet


def stamp_and_inject(app: Path, version: str, cfg: dict) -> None:
    info = app / "Contents" / "Info.plist"
    sets = {
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "SUFeedURL": cfg["feed_url"],
        "SUPublicEDKey": cfg["public_ed_key"],
    }
    for key, val in sets.items():
        subprocess.run(["plutil", "-replace", key, "-string", val, str(info)], check=True)
    subprocess.run(["plutil", "-replace", "SUEnableAutomaticChecks", "-bool", "YES", str(info)], check=True)


def sparkle_bin(name: str) -> Path:
    return deps_cache_dir() / "sparkle" / SPARKLE_VERSION / "bin" / name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build + sign + publish a teleport dmg")
    p.add_argument("--out", default="out/mac/arm64/release")
    p.add_argument("--config", type=Path, default=repo_root() / "scripts" / "release_config.local.toml")
    p.add_argument("--updates-dir", type=Path, default=repo_root() / "dist" / "dogfood")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    version = read_teleport_version()
    src = chromium_src()
    app = src / args.out / "Teleport.app"

    # 1. Version guard against the live feed (cheap, fail fast before the build).
    assert_publishable(version, fetch_live_appcast(cfg["feed_url"]))

    plan = [
        f"autoninja -C {args.out} chrome   (in {src})",
        f"stamp version {version} + inject Sparkle keys into {app}/Contents/Info.plist",
        "run chrome/installer/mac/signing driver (sign + notarize + dmg)",
        f"generate_appcast into {args.updates_dir}",
        f"upload dmg + appcast.xml to {cfg['upload_base_url']}",
    ]
    if args.dry_run:
        print("DRY RUN:\n  " + "\n  ".join(plan))
        return 0

    # 2. Official build.
    subprocess.run(["autoninja", "-C", args.out, "chrome"], cwd=src, check=True)
    # 3. Stamp + inject (pre-sign).
    stamp_and_inject(app, version, cfg)
    # 4. Sign + notarize + dmg via the chrome signing module.
    subprocess.run([
        sys.executable, "-m", "signing.driver",
        "--development", "false",
        "--identity", cfg["codesign_identity"],
        "--notary-profile", cfg["notary_profile"],
        "--input", str(app.parent),
        "--output", str(args.updates_dir),
    ], cwd=src / "chrome" / "installer" / "mac", check=True)
    # 5. Republish guard + appcast.
    assert_publishable(version, fetch_live_appcast(cfg["feed_url"]))
    subprocess.run([
        str(sparkle_bin("generate_appcast")),
        "--download-url-prefix", cfg["upload_base_url"],
        str(args.updates_dir),
    ], check=True)
    print(f"built + signed. upload {args.updates_dir}/*.dmg and appcast.xml to {cfg['upload_base_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> 注:`signing.driver` 的精确参数名以 Task 12 Step 1 读到的 `driver.py`/`standard_invoker.py` 为准;Step 6 的 dry-run + Task 16 的真跑会校准。`dist/dogfood/` 为本地暂存(应 gitignore,见 Step 5)。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest scripts/tests/test_package_release.py -q`
Expected: PASS。

- [ ] **Step 5: gitignore 本地产物目录**

`.gitignore` 追加 `/dist`。
Run: `git add scripts/package_release.py scripts/tests/test_package_release.py .gitignore`

- [ ] **Step 6: dry-run 校验编排**

Run: `cp scripts/release_config.local.toml.example scripts/release_config.local.toml`（填好真实值)然后 `uv run python scripts/package_release.py --dry-run`
Expected: 打印 5 步计划,不报缺配置。

- [ ] **Step 7: 提交**

```bash
git commit -m "feat(release): package_release.py build+sign+publish orchestrator"
```

### Task 16: 真出一份已签名已公证的 dmg(集成,重 / 外部依赖)

**Files:** 无新文件(校准 Task 12/13/15 的参数)。

- [ ] **Step 1: 前置就位**

确认:`gn gen out/mac/arm64/release` 完成(Task 11)、`fetch_sparkle.py` 已跑、`release_config.local.toml` 已填、EdDSA 密钥在 Keychain(Task 1)、notary profile 已存(Task 2)。

- [ ] **Step 2: 跑完整打包(数小时首次构建 + 公证等待)**

Run: `uv run python scripts/package_release.py`
Expected: 末尾打印产物路径;`dist/dogfood/Teleport-0.1.0.dmg` 与 `appcast.xml` 生成。若 `signing.driver` 参数不符,据报错对照 `driver.py` 修正 Task 15 Step 3 的命令并重跑。

- [ ] **Step 3: 验证签名 / 公证 / 装订**

Run: `codesign --verify --deep --strict --verbose=2 dist/dogfood/Teleport.app 2>&1 | tail`
Expected: `valid on disk` / `satisfies its Designated Requirement`。
Run: `spctl -a -vvv -t install dist/dogfood/Teleport-0.1.0.dmg`
Expected: `accepted` + `source=Notarized Developer ID`。
Run: `xcrun stapler validate dist/dogfood/Teleport-0.1.0.dmg`
Expected: `The validate action worked!`。

- [ ] **Step 4: 验证版本与 Sparkle 键已注入**

Run: `defaults read "$(pwd)/dist/dogfood/Teleport.app/Contents/Info" CFBundleVersion; defaults read "$(pwd)/dist/dogfood/Teleport.app/Contents/Info" SUFeedURL`
Expected: `0.1.0` 与配置里的 feed URL。

- [ ] **Step 5: 上传到对象存储(手动 / 厂商 CLI)**

把 `dist/dogfood/Teleport-0.1.0.dmg` 与 `appcast.xml` 传到 `upload_base_url`;appcast.xml 设短缓存、dmg 设长缓存/immutable。
Verify: `curl -fsSLI "<feed_url>"` 返回 200;`curl -fsSL "<feed_url>" | head` 含 `sparkle:edSignature`。

---

## Phase 5 — 首次分发

### Task 17: 首次分发引导文档

**Files:**
- Create: `docs/dogfood-install.md`

- [ ] **Step 1: 写引导**

```markdown
# 闪现 / Teleport dogfood 安装指南

1. 下载 `Teleport-<版本>.dmg`(链接:<分发链接>)。
2. 打开 dmg,把 **Teleport** 拖入「应用程序 / Applications」。
3. 首次打开:右键点 Teleport → 打开 →「打开」(已公证,通常直接放行;若提示来自身份不明开发者,按此步)。
4. 之后无需再手动下载:有新版时会弹「有更新可用」,点「更新」即可,重启后生效。
```

- [ ] **Step 2: 提交**

```bash
git add docs/dogfood-install.md
git commit -m "docs: dogfood first-install guide"
```

---

## Phase 6 — 升级闭环验证 + 文档

### Task 18: v1→v2 真实升级冒烟 + 写入 smoke_check.md

**Files:**
- Modify: `scripts/smoke_check.md`

- [ ] **Step 1: 装 v1**

确保线上 feed 已是 `0.1.0`(Task 16)。把 `0.1.0` 装进 `/Applications` 并打开,菜单「检查更新…」应显示已是最新。

- [ ] **Step 2: 出 v2 并发布**

Run: `printf '0.1.1\n' > TELEPORT_VERSION && uv run python scripts/package_release.py`
然后上传 `Teleport-0.1.1.dmg` + 更新后的 `appcast.xml`(Task 16 Step 5)。

- [ ] **Step 3: 验证自动升级闭环**

在运行中的 `0.1.0` 触发检查(或等定期检查)→ 出现「有更新可用 0.1.1」→ 点更新 → 下载 → 校验 → 重启 → 关于页显示 `0.1.1`。
Expected: 全程无报错;`spctl`/EdDSA 校验通过(若失败,Console.app 搜 `Sparkle` 看校验日志)。

- [ ] **Step 4: 把闭环步骤写进 `scripts/smoke_check.md`**

追加一节「dogfood 升级闭环」,含 Step 1–3 的命令与期望、以及回滚预案(下架/替换 appcast 条目;必要时 `minimumAutoupdateVersion`)。

- [ ] **Step 5: 提交**

```bash
git add scripts/smoke_check.md TELEPORT_VERSION
git commit -m "test(release): document v1->v2 upgrade smoke + rollback"
```

### Task 19: 更新 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 追加 release/updater 说明**

在「构建与测试命令」加 official 通道命令:
```bash
python scripts/fetch_sparkle.py                 # 拉取 Sparkle.framework(钉版本)
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
uv run python scripts/package_release.py        # 构建+签名+公证+发 appcast(需 release_config.local.toml)
```
在「关键 gotcha」加:`teleport_enable_updater` 仅 official 开;Sparkle.framework 在 `~/.cache/teleport/deps`(`$TELEPORT_DEPS_DIR` 可覆盖)+ 检出内符号链接;版本号单一事实来源 `TELEPORT_VERSION`(semver,每次发版 bump);EdDSA 私钥仅在 Keychain + 离线备份,绝不入库。

- [ ] **Step 2: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: document release build, updater, and version workflow"
```

---

## 自查清单(写计划者已核对)

- **spec 覆盖**:Sparkle 集成(T7–T10)、GN 开关(T8)、Sparkle.framework 缓存+链接(T6)、版本体系+护栏(T3/T4)、official 构建(T11)、签名/公证复用模块(T12/T13/T16)、appcast+对象存储(T15/T16)、首装(T17)、升级闭环+回滚(T18)、密钥管理(T1,且 §7.1 已在 spec)、通道-构建关系(T11/release.mac.gn 注释 + T15 打包期注入)均有对应任务。
- **占位符**:`fetch_sparkle.py` 的 `SPARKLE_VERSION`/`SHA256` 由 T6 Step 5 用精确命令钉死;`signing.driver` 参数由 T12 Step1/T15 Step6 dry-run/T16 校准;mac bundle BUILD.gn 与 app_controller/parts/config 的确切行由各任务的 grep 定位步骤给出——均为「精确命令 + 待实测填」而非空泛 TODO。
- **类型一致**:Python `parse_semver`/`is_newer`/`max_appcast_version`/`assert_publishable`/`read_teleport_version`、`deps_cache_dir`/`sha256_of`、`cache_framework_path`/`link_path`/`verify_sha256`;C++ `teleport::IsSecureFeedUrl`/`StartMacUpdater`/`CheckForUpdatesNow`;GN `teleport_enable_updater`/`teleport_sparkle_dir`/`config("sparkle_link")`——跨任务引用名一致。
