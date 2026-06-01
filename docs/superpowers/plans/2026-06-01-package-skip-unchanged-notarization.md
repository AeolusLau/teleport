# 打包跳过"无变更"重复公证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当新构建后的(未签名)app 与上次成功打包逐字节相同、且已有有效已公证 dmg 时,跳过 sign + dmg + 公证 + staple 并复用该 dmg;fail-closed。

**Architecture:** 新增 `scripts/_package_state.py`(app 全内容 SHA-256 指纹、`dist/.package-state/<channel>.json` 清单读写、纯逻辑 `can_reuse`)。`scripts/_package.py` 加 `stapler_validate` 与 `target_dmg_path` helper。`scripts/package.py` 在分发渠道 `build+stamp+stage` 之后、`sign_app` 之前接入复用判定:命中(哈希一致 + 键一致 + dmg 存在 + `stapler validate` 通过)则复用现有 dmg、跳过签名与公证;否则照旧并写清单。`--distribute` 上传前再做一次 `stapler validate` 最终闸。`--force` 绕过。

**Tech Stack:** Python 3.13(经 `uv`)、pytest(monkeypatch 打桩,无 chromium 检出依赖)、macOS `xcrun stapler`。

参考 spec:`docs/superpowers/specs/2026-06-01-package-skip-unchanged-notarization-design.md`

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `scripts/_package_state.py` | app 内容指纹 + 打包状态清单读写 + 纯逻辑 `can_reuse` | 创建 |
| `scripts/_package.py` | 加 `target_dmg_path`(DRY dmg 路径)+ `stapler_validate`(有副作用,subprocess) | 修改 |
| `scripts/package.py` | 接入 fail-closed 复用判定 + `--force` + 发布前最终闸 + `--dry-run` 显示 | 修改 |
| `scripts/tests/test_package_state.py` | 指纹 / 清单 / `can_reuse` 单测 | 创建 |
| `scripts/tests/test_package.py` | `target_dmg_path` / `stapler_validate` 单测 | 修改 |
| `scripts/tests/test_package_cli.py` | 复用命中/未命中/`--force`/最终闸/`--dry-run` 的 CLI 分支 | 修改 |

**约束**:`_package_state.py` 的 `can_reuse` 保持纯逻辑(无 subprocess),便于单测;有副作用的 `stapler_validate` 放 `_package.py`。复用键字段顺序/命名在 `reuse_key` 单一处定义,各处复用。

## 背景速览(实现者须知)

- 跑测试:仓库根 `uv run pytest scripts/tests/ -q`。本计划所有单测**不需要** chromium 检出(指纹用 `tmp_path` 造目录;CLI 用 monkeypatch 打桩)。
- `package.py main()` 分发渠道真实路径(当前):detect identity →(distribute)guards → `build` → `stamp_and_inject` → `stage_channel_icons` → `sign_app` → `build_styled_dmg`(内部:dmgbuild → codesign → `notarytool submit --wait` → `stapler staple`)→(distribute)`assert_not_published` → `generate_appcast` → `upload_to_oss` → `tag_and_push`。
- `codesign --timestamp` 每次重签字节不同 → 不能"只跳公证";复用 = 复用整个已公证 dmg,连带跳过 sign+dmg。
- 清单放 `dist/.package-state/<channel>.json`(在被 `generate_appcast` 裁剪的 `dist/<channel>/` 之外;`dist/` 已被 .gitignore)。

---

## Task 1: `_package_state.py` — app 内容指纹

**Files:**
- Create: `scripts/_package_state.py`
- Test: `scripts/tests/test_package_state.py`

- [ ] **Step 1: Write the failing tests**

创建 `scripts/tests/test_package_state.py`:

```python
import os
from pathlib import Path

import _package_state as ps


def _make_app(root: Path) -> Path:
    app = root / "Teleport.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Teleport").write_bytes(b"\x00binary\x01")
    (app / "Contents" / "Info.plist").write_text("<plist/>")
    return app


def test_app_content_digest_is_stable(tmp_path):
    app = _make_app(tmp_path)
    assert ps.app_content_digest(app) == ps.app_content_digest(app)


def test_app_content_digest_changes_on_content_change(tmp_path):
    app = _make_app(tmp_path)
    d1 = ps.app_content_digest(app)
    (app / "Contents" / "Info.plist").write_text("<plist><k/></plist>")
    assert ps.app_content_digest(app) != d1


def test_app_content_digest_changes_on_new_file(tmp_path):
    app = _make_app(tmp_path)
    d1 = ps.app_content_digest(app)
    (app / "Contents" / "extra.txt").write_text("x")
    assert ps.app_content_digest(app) != d1


def test_app_content_digest_changes_on_rename(tmp_path):
    app = _make_app(tmp_path)
    d1 = ps.app_content_digest(app)
    (app / "Contents" / "Info.plist").rename(app / "Contents" / "Info2.plist")
    assert ps.app_content_digest(app) != d1


def test_app_content_digest_reflects_symlink_target(tmp_path):
    app = _make_app(tmp_path)
    link = app / "Contents" / "Current"
    link.symlink_to("A")
    d1 = ps.app_content_digest(app)
    link.unlink(); link.symlink_to("B")  # repoint without following
    assert ps.app_content_digest(app) != d1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest scripts/tests/test_package_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_package_state'`.

- [ ] **Step 3: Implement `app_content_digest`**

创建 `scripts/_package_state.py`:

```python
"""Package-state cache: fingerprint a built .app, persist a per-channel state
manifest, and decide whether a previously-notarized dmg can be reused.

The reuse gate is fail-closed: a hit requires the (unsigned) app to be
byte-identical to the last successful package AND the signing-affecting key
fields to match. Caller additionally `stapler validate`s the dmg before reuse.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def app_content_digest(app: Path) -> str:
    """SHA-256 over every entry under ``app`` (sorted relative posix path), so
    any content/structure change flips the digest. Symlinks contribute their
    target text (not dereferenced); files contribute path + size + bytes."""
    h = hashlib.sha256()
    for p in sorted(app.rglob("*"), key=lambda x: x.relative_to(app).as_posix()):
        rel = p.relative_to(app).as_posix()
        if p.is_symlink():
            h.update(f"L\0{rel}\0{os.readlink(p)}\0".encode("utf-8"))
        elif p.is_file():
            h.update(f"F\0{rel}\0{p.stat().st_size}\0".encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest scripts/tests/test_package_state.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/_package_state.py scripts/tests/test_package_state.py
git commit -m "feat(package): add app content digest for package-state cache"
```

---

## Task 2: `_package_state.py` — 清单读写 + 纯逻辑 `can_reuse`

**Files:**
- Modify: `scripts/_package_state.py`
- Test: `scripts/tests/test_package_state.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_state_path_is_outside_trimmed_updates_dir(tmp_path):
    p = ps.state_path(tmp_path, "canary")
    assert p == tmp_path / "dist" / ".package-state" / "canary.json"
    # NOT under dist/canary/ (which generate_appcast trims)
    assert (tmp_path / "dist" / "canary") not in p.parents


def test_write_then_load_state_roundtrip(tmp_path):
    p = ps.state_path(tmp_path, "canary")
    key = ps.reuse_key("1.2.3", "canary", "Developer ID Application: X (T)", "prof", "deadbeef")
    ps.write_state(p, key, "TeleportCanary-1.2.3.dmg")
    state = ps.load_state(p)
    assert state == {**key, "dmg_name": "TeleportCanary-1.2.3.dmg"}


def test_load_state_missing_returns_none(tmp_path):
    assert ps.load_state(tmp_path / "nope.json") is None


def _key():
    return ps.reuse_key("1.2.3", "canary", "Developer ID Application: X (T)", "prof", "deadbeef")


def test_can_reuse_true_when_key_matches_and_dmg_exists(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"; dmg.write_text("d")
    state = {**_key(), "dmg_name": dmg.name}
    assert ps.can_reuse(state, _key(), dmg) is True


def test_can_reuse_false_when_state_none(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"; dmg.write_text("d")
    assert ps.can_reuse(None, _key(), dmg) is False


def test_can_reuse_false_when_digest_differs(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"; dmg.write_text("d")
    state = {**_key(), "dmg_name": dmg.name}
    other = ps.reuse_key("1.2.3", "canary", "Developer ID Application: X (T)", "prof", "OTHER")
    assert ps.can_reuse(state, other, dmg) is False


def test_can_reuse_false_when_identity_differs(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"; dmg.write_text("d")
    state = {**_key(), "dmg_name": dmg.name}
    other = ps.reuse_key("1.2.3", "canary", "Developer ID Application: Y (T)", "prof", "deadbeef")
    assert ps.can_reuse(state, other, dmg) is False


def test_can_reuse_false_when_dmg_name_differs(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"; dmg.write_text("d")
    state = {**_key(), "dmg_name": "TeleportCanary-9.9.9.dmg"}
    assert ps.can_reuse(state, _key(), dmg) is False


def test_can_reuse_false_when_dmg_missing(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"  # not created
    state = {**_key(), "dmg_name": dmg.name}
    assert ps.can_reuse(state, _key(), dmg) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest scripts/tests/test_package_state.py -k "state or can_reuse or roundtrip" -v`
Expected: FAIL — `AttributeError: module '_package_state' has no attribute 'state_path'`.

- [ ] **Step 3: Implement state manifest + `can_reuse`** (append to `_package_state.py`)

```python
def state_path(repo_root_dir: Path, channel_name: str) -> Path:
    """Per-channel manifest path, kept OUTSIDE dist/<channel>/ because
    generate_appcast trims that dir to the single current dmg."""
    return repo_root_dir / "dist" / ".package-state" / f"{channel_name}.json"


def reuse_key(version: str, channel_name: str, identity: str,
              notary_profile: str, app_digest: str) -> dict:
    """The fields that must all match for a previously-notarized dmg to be
    reusable: app content + every signing/notarization-affecting input."""
    return {
        "version": version,
        "channel": channel_name,
        "identity": identity,
        "notary_profile": notary_profile,
        "app_digest": app_digest,
    }


def load_state(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def write_state(path: Path, key: dict, dmg_name: str) -> None:
    """Bind the reuse key to the produced dmg. Call ONLY after notarize+staple
    succeeds, so the manifest never points at an un-notarized artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**key, "dmg_name": dmg_name}, indent=2),
                    encoding="utf-8")


def can_reuse(state: dict | None, key: dict, dmg_path: Path) -> bool:
    """Pure gate (no I/O beyond dmg existence): the stored state must match the
    current key exactly, name the same dmg, and that dmg must exist. The caller
    additionally `stapler validate`s the dmg before actually reusing it."""
    if state is None:
        return False
    if any(state.get(k) != v for k, v in key.items()):
        return False
    return state.get("dmg_name") == dmg_path.name and dmg_path.exists()
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest scripts/tests/test_package_state.py -v`
Expected: PASS (all, ~14 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/_package_state.py scripts/tests/test_package_state.py
git commit -m "feat(package): state manifest read/write + pure can_reuse gate"
```

---

## Task 3: `_package.py` — `target_dmg_path` + `stapler_validate`

**Files:**
- Modify: `scripts/_package.py`(加 `target_dmg_path`、`stapler_validate`;`build_styled_dmg` 改用 `target_dmg_path`)
- Test: `scripts/tests/test_package.py`

- [ ] **Step 1: Write the failing tests** (append to `scripts/tests/test_package.py`)

```python
def test_target_dmg_path_channel_suffixed(tmp_path):
    import _package
    p = _package.target_dmg_path(tmp_path, "1.2.3", "canary")
    assert p == tmp_path / "TeleportCanary-1.2.3.dmg"


def test_target_dmg_path_base_channel(tmp_path):
    import _package
    p = _package.target_dmg_path(tmp_path, "1.2.3", "")
    assert p == tmp_path / "Teleport-1.2.3.dmg"


def test_stapler_validate_true_on_zero_exit(monkeypatch, tmp_path):
    import _package
    calls = {}
    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        class R: returncode = 0
        return R()
    monkeypatch.setattr(_package.subprocess, "run", fake_run)
    assert _package.stapler_validate(tmp_path / "x.dmg") is True
    assert calls["cmd"][:3] == ["xcrun", "stapler", "validate"]


def test_stapler_validate_false_on_nonzero_exit(monkeypatch, tmp_path):
    import _package
    def fake_run(cmd, **kw):
        class R: returncode = 65
        return R()
    monkeypatch.setattr(_package.subprocess, "run", fake_run)
    assert _package.stapler_validate(tmp_path / "x.dmg") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest scripts/tests/test_package.py -k "target_dmg_path or stapler_validate" -v`
Expected: FAIL — `AttributeError: module '_package' has no attribute 'target_dmg_path'`.

- [ ] **Step 3: Implement helpers + refactor `build_styled_dmg`**

In `scripts/_package.py`, add after `dmg_names`:

```python
def target_dmg_path(updates_dir: Path, version: str, channel_name: str = "") -> Path:
    """The channel-suffixed, versioned dmg path (e.g. TeleportCanary-1.2.3.dmg)."""
    file_prefix, _ = dmg_names(channel_name)
    return updates_dir / f"{file_prefix}-{version}.dmg"


def stapler_validate(dmg: Path) -> bool:
    """True iff `xcrun stapler validate <dmg>` exits 0 (dmg has a valid stapled
    notarization ticket for its current bytes). Side-effecting; kept out of the
    pure can_reuse gate."""
    return subprocess.run(
        ["xcrun", "stapler", "validate", str(dmg)],
        capture_output=True,
    ).returncode == 0
```

In `build_styled_dmg`, replace the two lines that compute `target_dmg`:

```python
    file_prefix, volume_name = dmg_names(channel_name)
    target_dmg = updates_dir / f"{file_prefix}-{version}.dmg"
```

with (keep `volume_name`, derive the path via the helper):

```python
    _, volume_name = dmg_names(channel_name)
    target_dmg = target_dmg_path(updates_dir, version, channel_name)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest scripts/tests/test_package.py -v`
Expected: PASS (new + existing; `build_styled_dmg` behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add scripts/_package.py scripts/tests/test_package.py
git commit -m "feat(package): add target_dmg_path + stapler_validate helpers"
```

---

## Task 4: `package.py` — fail-closed 复用判定 + `--force` + 发布前最终闸

**Files:**
- Modify: `scripts/package.py`
- Test: `scripts/tests/test_package_cli.py`

- [ ] **Step 1: Write the failing tests**

First extend the shared stub in `scripts/tests/test_package_cli.py` — add to the END of `_stub_distributable` (so reuse defaults to OFF unless a test overrides):

```python
    # package-state cache: default to "no reuse" so existing tests are unaffected.
    monkeypatch.setattr(package._package_state, "app_content_digest",
                        lambda app: "DIGEST")
    monkeypatch.setattr(package._package_state, "load_state", lambda p: None)
    monkeypatch.setattr(package._package_state, "write_state",
                        lambda p, key, dmg: order.append(("write_state", dmg)))
    monkeypatch.setattr(package._package_state, "can_reuse",
                        lambda state, key, dmg: False)
    monkeypatch.setattr(package._package, "stapler_validate",
                        lambda dmg: order.append(("stapler_validate", getattr(dmg, "name", str(dmg)))) or True)
    monkeypatch.setattr(package._package, "target_dmg_path",
                        lambda ud, v, ch: __import__("pathlib").Path(f"/tmp/Teleport-{v}.dmg"))
```

Then add new tests:

```python
def test_reuse_skips_sign_and_dmg_when_app_unchanged(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    rc = package.main(["--channel", "canary", "--distribute"])
    assert rc == 0
    names = [c[0] for c in order]
    assert "sign" not in names and "dmg" not in names      # skipped
    assert "write_state" not in names                       # nothing new to record
    assert "upload" in names and "tag_and_push" in names    # still publishes
    assert "reusing notarized dmg" in capsys.readouterr().out


def test_no_reuse_runs_full_chain_and_writes_state(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)  # can_reuse False by default
    rc = package.main(["--channel", "canary", "--distribute"])
    assert rc == 0
    names = [c[0] for c in order]
    assert names.index("sign") < names.index("dmg")
    assert ("write_state", "Teleport-1.2.3.dmg") in order   # recorded after dmg


def test_force_bypasses_reuse(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=False)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    rc = package.main(["--channel", "canary", "--force"])
    assert rc == 0
    names = [c[0] for c in order]
    assert "sign" in names and "dmg" in names               # forced rebuild


def test_distribute_final_gate_refuses_unstapled_dmg(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    monkeypatch.setattr(package._package, "stapler_validate", lambda dmg: False)
    with pytest.raises(SystemExit, match="stapler validate"):
        package.main(["--channel", "canary", "--distribute"])
    names = [c[0] for c in order]
    assert "upload" not in names and "tag_and_push" not in names  # never published
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest scripts/tests/test_package_cli.py -v`
Expected: FAIL — `AttributeError: module 'package' has no attribute '_package_state'` (and `--force` unknown).

- [ ] **Step 3: Implement in `package.py`**

Add the import near the other imports:

```python
import _package_state
```

Add the `--force` argument (after `--distribute`):

```python
    p.add_argument("--force", action="store_true",
                   help="ignore the package-state cache; re-sign + re-notarize even "
                        "if the app is unchanged")
```

Replace the real-run "Build -> ... -> styled dmg" block (the section after the
fail-fast guards, before the `if not args.distribute:` return) with:

```python
    # Build -> stamp -> stage icons, then decide whether a previously-notarized
    # dmg can be reused (app byte-identical) or must be rebuilt + re-notarized.
    build(out, channel)
    _package.stamp_and_inject(app, version, cfg, channel.name)
    _package.stage_channel_icons(app, channel.name)

    sp = _package_state.state_path(repo_root(), channel.name)
    key = _package_state.reuse_key(
        version, channel.name, cfg["codesign_identity"], cfg["notary_profile"],
        _package_state.app_content_digest(app))
    target_dmg = _package.target_dmg_path(updates_dir, version, channel.name)
    if (not args.force
            and _package_state.can_reuse(_package_state.load_state(sp), key, target_dmg)
            and _package.stapler_validate(target_dmg)):
        print(f"reusing notarized dmg {target_dmg.name} (app unchanged); "
              f"skipping sign + notarize")
    else:
        _package.sign_app(app, updates_dir, cfg["codesign_identity"], channel.name)
        target_dmg = _package.build_styled_dmg(
            updates_dir, version, cfg["codesign_identity"], cfg["notary_profile"],
            channel.name)
        _package_state.write_state(sp, key, target_dmg.name)

    if not args.distribute:
        print(f"built + signed {channel.name} dmg at {target_dmg} (not published)")
        return 0

    # Re-check (cheap), then a final notarization gate before ANY upload.
    _publish.assert_not_published(version, _publish.fetch_live_appcast(cfg["feed_url"]))
    if not _package.stapler_validate(target_dmg):
        raise SystemExit(
            f"{target_dmg.name} failed stapler validate; refusing to publish")
    _publish.generate_appcast(updates_dir, cfg["download_base_url"], target_dmg.name)
    _publish.upload_to_oss(updates_dir, cfg["oss_upload_target"])
    _publish.tag_and_push(version, cfg["git_remote"])
    print(f"published {version} ({channel.name}), tagged v{version}: feed {cfg['feed_url']}")
    return 0
```

(`repo_root` is already imported in package.py.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest scripts/tests/test_package_cli.py -v`
Expected: PASS (new + all existing CLI tests; the default `can_reuse=False` keeps prior tests' full-chain expectations).

- [ ] **Step 5: Commit**

```bash
git add scripts/package.py scripts/tests/test_package_cli.py
git commit -m "feat(package): fail-closed reuse of notarized dmg when app unchanged (--force)"
```

---

## Task 5: `package.py` — `--dry-run` 显示复用判定

**Files:**
- Modify: `scripts/package.py`
- Test: `scripts/tests/test_package_cli.py`

- [ ] **Step 1: Write the failing test**

```python
def test_dry_run_reports_reuse_when_cached(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    rc = package.main(["--channel", "canary", "--distribute", "--dry-run"])
    assert rc == 0
    assert order == []  # dry-run still has no side effects
    out = capsys.readouterr().out
    assert "reuse notarized dmg" in out
    assert "notarytool" not in out  # not planning to notarize


def test_dry_run_reports_renotarize_when_not_cached(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)  # can_reuse False
    rc = package.main(["--channel", "canary", "--distribute", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "notarytool submit" in out  # plan shows notarization
```

> Note: the existing `test_canary_distribute_dry_run_has_no_side_effects` asserts `order == []`. The dry-run reuse probe must NOT call any stubbed side-effecting recorder. `can_reuse`/`load_state`/`stapler_validate`/`app_content_digest`/`target_dmg_path` stubs either return values or (for `stapler_validate`) append — so in dry-run, do NOT call `stapler_validate`; base the dry-run display on `can_reuse(load_state(...), key, target_dmg)` only (which doesn't append). Keep `app_content_digest` stub side-effect-free (it is).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest scripts/tests/test_package_cli.py -k dry_run -v`
Expected: FAIL — dry-run output lacks the reuse/renotarize line.

- [ ] **Step 3: Implement dry-run display**

In `package.py`, the dry-run branch for distributable channels currently builds a
`plan` list with a fixed `"dmgbuild ... notarytool ... staple"` line. Replace that
single line with a reuse-aware computation. Before building `plan`, compute:

```python
        sp = _package_state.state_path(repo_root(), channel.name)
        identity = cfg.get("codesign_identity") or "<auto-detected from keychain>"
        target_dmg = _package.target_dmg_path(updates_dir, version, channel.name)
        # Dry-run probe must stay side-effect-free: no stapler_validate here.
        key = _package_state.reuse_key(
            version, channel.name, identity, cfg["notary_profile"],
            "<app-digest-after-build>")
        would_reuse = (not args.force
                       and _package_state.can_reuse(
                           _package_state.load_state(sp), key, target_dmg))
```

Then set the dmg/notarize plan line conditionally:

```python
        if would_reuse:
            dmg_line = (f"reuse notarized dmg {target_dmg.name} (app unchanged "
                        f"per cache); skip sign + notarytool + staple")
        else:
            dmg_line = ("sign .app (--disable-packaging) with "
                        f"'{identity}'  ->  dmgbuild styled dmg -> codesign -> "
                        "notarytool submit --wait -> stapler staple")
```

and build `plan` from `[autoninja..., stamp..., dmg_line]` plus the publish lines
when `args.distribute`. (Drop the now-redundant separate sign/dmg lines so the
plan shows exactly one of reuse-vs-renotarize.)

> Caveat: in real dry-run the app isn't built, so the digest is unknown — the
> `<app-digest-after-build>` placeholder will almost never match a stored key, so
> `would_reuse` is conservatively False unless a prior key happened to store that
> literal. That's acceptable for a *plan* preview (it errs toward showing
> "re-notarize"). The test forces `can_reuse=True` to exercise the reuse line.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest scripts/tests/test_package_cli.py -v`
Expected: PASS (incl. the pre-existing `order == []` dry-run test — the probe uses only non-appending stubs).

- [ ] **Step 5: Commit**

```bash
git add scripts/package.py scripts/tests/test_package_cli.py
git commit -m "feat(package): dry-run shows reuse vs re-notarize decision"
```

---

## Task 6: 手动集成验证(连跑两次 canary)

**Files:** 无代码改动(真实公证无法在单测里跑,手动验证)。

- [ ] **Step 1: Full unit suite green**

Run: `uv run pytest scripts/tests/ -q`
Expected: all pass.

- [ ] **Step 2: First package run records state**

前置:`export TELEPORT_CHROMIUM_DIR=...`、release out 已 `gn gen`、Sparkle/PGO 就绪、`release_config.local.toml` 配好。
```bash
uv run python scripts/package.py --channel canary
```
Expected: 完整跑(含一次 `notarytool submit --wait`);结束后存在 `dist/.package-state/canary.json`,且 `dist/canary/TeleportCanary-<ver>.dmg` 存在。

- [ ] **Step 3: Second run reuses (no re-notarize)**

不改任何源码,直接:
```bash
uv run python scripts/package.py --channel canary
```
Expected: 输出 `reusing notarized dmg TeleportCanary-<ver>.dmg (app unchanged); skipping sign + notarize`;**无** `notarytool` 提交;秒级完成。

- [ ] **Step 4: `--force` re-notarizes; dry-run shows decision**

```bash
uv run python scripts/package.py --channel canary --force        # 完整重做 + 刷新 state
uv run python scripts/package.py --channel canary --distribute --dry-run   # 显示 reuse 或 re-notarize
```
Expected: `--force` 重新公证;`--dry-run` 打印 reuse/renotarize 计划行,无副作用。

> 注:`--distribute` 的真实发布不在常规验证内(会打 tag + 上传 OSS);仅在确需发版时跑。

---

## Self-Review

**Spec coverage:**
- §3 安全模型(全内容哈希 / 键含签名配置 / 复用需 stapler validate / 发布前最终闸 / fail-closed)→ Task 1(digest)+ Task 2(`can_reuse` 键比对)+ Task 3(`stapler_validate`)+ Task 4(复用判定 + 最终闸 + `--force`)✓
- §4.1 `_package_state.py`(digest/state_path/reuse_key/load_state/write_state/can_reuse)→ Task 1+2 ✓
- §4.2 hook 点(build+stamp+stage 之后、sign 之前)+ 复用/重做分支 + 写清单(公证成功后)+ 最终闸 → Task 4 ✓
- §4.3 `--force` + `--dry-run` 显示 → Task 4(force)+ Task 5(dry-run)✓
- §4.4 dev 不变 → 未触碰 dev 路径 ✓
- §5 测试(digest / state / can_reuse 各分支 / CLI 复用命中·未命中·force·最终闸)→ Task 1/2/4/5 ✓;§5 集成手动验证 → Task 6 ✓
- §6 风险(`dist/` 已 gitignore,实现期无需补)→ 已在 brainstorm 阶段确认 ✓

**Placeholder scan:** Task 5 的 `<app-digest-after-build>` 是 dry-run 计划预览的**有意占位字符串**(真实 dry-run 不构建、拿不到 digest),其行为(偏向显示"re-notarize")在 caveat 中说明,非代码空缺。其余步骤均含可执行代码 + 命令 + 预期。

**Type consistency:** `reuse_key(version, channel_name, identity, notary_profile, app_digest)` 五参在 Task 2 定义,Task 4/5 调用一致;`can_reuse(state, key, dmg_path)`、`state_path(repo_root_dir, channel_name)`、`write_state(path, key, dmg_name)`、`load_state(path)`、`app_content_digest(app)`、`target_dmg_path(updates_dir, version, channel_name)`、`stapler_validate(dmg)` 签名在定义处与 `package.py` 调用处一致。`package.py` 经 `import _package_state` 暴露给测试 monkeypatch(`package._package_state`),与现有 `package._package`/`package._publish` 模式一致。
