# 渠道并排共存 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Teleport 各发布渠道在 macOS 上拥有独立的 bundle id 后缀 / app 名 / 显示名 / 数据目录 / 图标,从而可并排安装与同时运行;本期落地 canary,并打通未来 beta/stable 复用的机制。

**Architecture:** 复用上游 `chrome/installer/mac/signing` 的 `channel_customize` 引擎——我们的签名流程(`sign_chrome.py --disable-packaging`)本已无条件调用 `customize_distribution`,只因 `config.distributions` 返回裸 `[Distribution()]` 而空跑。改动两点:① 在 `chromium_config.py` patch 中按环境变量 `TELEPORT_SIGN_CHANNEL` 让 `distributions` 返回一个 `channel_customize=True` 的 `Distribution`;② 给 `modification.py` 打一个「去 Keystone」补丁,gate 掉我们包内无 `KSProductID` 时会崩溃/写脏键的两处。脚本侧(`_package.py` / `package.py`)负责:暂存渠道图标、把渠道名透传给签名子进程、放宽签名产物 glob。运行时渠道仍由 `TeleportChannel` 键驱动(C++ 零改动),与 bundle id 后缀同源于一个 channel 名。

**Tech Stack:** Python 3.13(`uv` + pytest),Chromium M148 signing 模块(Python),`git apply` 文本补丁,macOS 签名/打包(`codesign`/`dmgbuild`/`notarytool`)。

**关键事实(已核实于检出 `chromium/src` 与构建产物 `out/mac/arm64/release/Teleport.app`):**
- `--disable-packaging` 仅跳过最终 dmg/pkg 打包(`pipeline.py:694`);`customize_distribution` 无条件执行(`pipeline.py:749, 83`)。
- 构建产物中 `KSProductID` / `KSChannelID` **不存在**;`com.beansec.Teleport.manifest`(企业策略)**存在**且结构完整。
- 签名产物落点 `<output>/<intermediate-dir>/<app_product>.app`,其中 intermediate-dir 由 `_intermediate_work_dir_name` 把 `sxs`+channel+fragment+product_dirname+creator_code 用 `-` 连接(`pipeline.py:551-569`);本期 canary → `<output>/sxs-canary-Canary-Teleport Canary-Cr24/Teleport Canary.app`。glob `*/Teleport*.app`(一层深 + app 名含空格)即可命中,无需关心子目录确切拼法。
- `config.product` 不随渠道改变(仍 `Teleport`),故 packaging 目录恒为 `Teleport Packaging`;`_replace_icons` 从那里读 `app_<channel>.icns` / `Assets_<channel>.car`(`modification.py:149-156`,文件名用**原始渠道名**)。
- bundle id 前缀权威值 `com.beansec.Teleport`(`BRANDING` 的 `MAC_BUNDLE_ID`);creator code `Cr24`。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `scripts/_package.py` | 修改 | 新增 `_find_signed_app`(可单测 glob)、`stage_channel_icons`(暂存渠道图标)、`sign_app` 增 `channel_name` 形参并注入 `TELEPORT_SIGN_CHANNEL`;`build_styled_dmg` 改用 `_find_signed_app` |
| `scripts/package.py` | 修改 | 在 `sign_app` 前调 `stage_channel_icons`,并把 `channel.name` 透传给 `sign_app` |
| `scripts/tests/test_package.py` | 修改 | `_find_signed_app` / `stage_channel_icons` / `sign_app` 环境注入的单测 |
| `scripts/tests/test_package_cli.py` | 修改 | `package.main` canary 流程透传 `channel.name` 的断言 |
| `patches/chrome/installer/mac/signing/modification.py.patch` | 新建 | gate 掉 `KSProductID` 追加与 KSChannelID 标签写入(`if _KS_PRODUCT_ID in app_plist:`) |
| `patches/chrome/installer/mac/signing/chromium_config.py.patch` | 修改 | `distributions` 按 `TELEPORT_SIGN_CHANNEL` 返回渠道定制 Distribution |
| `scripts/smoke_check.md` | 修改 | 新增 canary bundle id / 数据目录 / 并排 三行 |
| `CLAUDE.md` | 修改 | 订正 bundle id 前缀;补并排共存 gotcha |

---

## Task 1: `_package.py` — 抽出可单测的签名产物定位 `_find_signed_app`,并放宽 glob

把 `build_styled_dmg` 内联的 glob 抽成独立函数并加宽,使其同时匹配旧 `stable/Teleport.app` 与新的渠道定制子目录(canary 实为 `sxs-canary-Canary-Teleport Canary-Cr24/Teleport Canary.app`,见上「关键事实」)。glob 一层深,不关心子目录确切拼法。

**Files:**
- Modify: `scripts/_package.py`(`build_styled_dmg` 顶部 glob,约 `_package.py:122-124`)
- Test: `scripts/tests/test_package.py`

- [ ] **Step 1: 写失败测试**

在 `scripts/tests/test_package.py` 末尾追加:

```python
# ---------------------------------------------------------------------------
# _find_signed_app (glob widened for channel-customized output dirs)
# ---------------------------------------------------------------------------
from pathlib import Path


def _touch_app(root: Path, rel: str) -> Path:
    app = root / rel
    (app / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    return app


def test_find_signed_app_legacy_stable_layout(tmp_path):
    # Pre-side-by-side canary signed into <output>/stable/Teleport.app
    want = _touch_app(tmp_path, "stable/Teleport.app")
    assert _package._find_signed_app(tmp_path) == want


def test_find_signed_app_channel_layout_with_space(tmp_path):
    # Side-by-side canary: the signing engine names the intermediate dir
    # sxs-<channel>-<Fragment>-<product_dirname>-<creator_code> and renames the
    # app with a space (pipeline.py:551-569). The glob is one level deep, so the
    # exact dir spelling does not matter — only that it matches "Teleport*.app".
    want = _touch_app(
        tmp_path, "sxs-canary-Canary-Teleport Canary-Cr24/Teleport Canary.app")
    assert _package._find_signed_app(tmp_path) == want


def test_find_signed_app_top_level(tmp_path):
    want = _touch_app(tmp_path, "Teleport.app")
    assert _package._find_signed_app(tmp_path) == want
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_package.py -k find_signed_app -v`
Expected: FAIL — `AttributeError: module '_package' has no attribute '_find_signed_app'`

- [ ] **Step 3: 写最小实现**

在 `scripts/_package.py` 中 `build_styled_dmg` 定义**之前**新增函数:

```python
def _find_signed_app(updates_dir: Path) -> Path:
    """Locate the signed .app the signing module produced. It lands under a
    per-distribution subdir named `<dist.channel or 'stable'>`, and a
    channel-customized app is renamed (e.g. `Teleport Canary.app`). Match both
    the legacy `stable/Teleport.app` layout and channel layouts with a space.
    """
    matches = (list(updates_dir.glob("Teleport*.app")) +
               list(updates_dir.glob("*/Teleport*.app")))
    return next(iter(matches))
```

然后把 `build_styled_dmg` 里原本的:

```python
    signed_app = next(iter(
        list(updates_dir.glob("Teleport.app")) +
        list(updates_dir.glob("*/Teleport.app"))))
```

替换为:

```python
    signed_app = _find_signed_app(updates_dir)
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_package.py -k find_signed_app -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add scripts/_package.py scripts/tests/test_package.py
git commit -m "refactor(package): extract _find_signed_app, widen glob for channel-customized apps"
```

---

## Task 2: `_package.py` — `stage_channel_icons` 暂存渠道图标(满足 `_replace_icons` 硬依赖)

签名前把构建产物的 `app.icns` / `Assets.car` 复制成引擎要求的 `app_<channel>.icns` / `Assets_<channel>.car`(本期复用同一图标)。基底渠道(`""`/`stable`)为 no-op。

**Files:**
- Modify: `scripts/_package.py`(新增函数 + 顶部 `import os`、`import shutil`)
- Test: `scripts/tests/test_package.py`

- [ ] **Step 1: 写失败测试**

在 `scripts/tests/test_package.py` 末尾追加:

```python
# ---------------------------------------------------------------------------
# stage_channel_icons (copy built icons to channel-named files for the engine)
# ---------------------------------------------------------------------------


def _make_built_app(tmp_path) -> Path:
    out = tmp_path / "release"
    res = out / "Teleport.app" / "Contents" / "Resources"
    res.mkdir(parents=True)
    (res / "app.icns").write_bytes(b"ICNS-DATA")
    (res / "Assets.car").write_bytes(b"CAR-DATA")
    (out / "Teleport Packaging").mkdir()
    return out / "Teleport.app"


def test_stage_channel_icons_copies_with_channel_names(tmp_path):
    app = _make_built_app(tmp_path)
    _package.stage_channel_icons(app, "canary")
    pkg = app.parent / "Teleport Packaging"
    assert (pkg / "app_canary.icns").read_bytes() == b"ICNS-DATA"
    assert (pkg / "Assets_canary.car").read_bytes() == b"CAR-DATA"


def test_stage_channel_icons_noop_for_base_channel(tmp_path):
    app = _make_built_app(tmp_path)
    _package.stage_channel_icons(app, "stable")
    _package.stage_channel_icons(app, "")
    pkg = app.parent / "Teleport Packaging"
    assert list(pkg.iterdir()) == []  # nothing staged for the base channel
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_package.py -k stage_channel_icons -v`
Expected: FAIL — `AttributeError: module '_package' has no attribute 'stage_channel_icons'`

- [ ] **Step 3: 写最小实现**

在 `scripts/_package.py` 顶部 import 区把:

```python
import re
import subprocess
import sys
from pathlib import Path
```

改为:

```python
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
```

然后新增函数(放在 `sign_app` 之前):

```python
def stage_channel_icons(app: Path, channel_name: str) -> None:
    """Copy the built app's icon assets to the channel-named files the signing
    engine's _replace_icons() requires. The engine reads
    `app_<channel>.icns` / `Assets_<channel>.car` from the "Teleport Packaging"
    dir (named by config.product, which does not change per channel). We reuse
    the base icons (no per-channel differentiation yet). No-op for the base
    channel, which is not channel-customized.
    """
    if channel_name in ("", "stable"):
        return
    res = app / "Contents" / "Resources"
    pkg = app.parent / "Teleport Packaging"
    shutil.copyfile(res / "app.icns", pkg / f"app_{channel_name}.icns")
    shutil.copyfile(res / "Assets.car", pkg / f"Assets_{channel_name}.car")
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_package.py -k stage_channel_icons -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add scripts/_package.py scripts/tests/test_package.py
git commit -m "feat(package): stage per-channel icons for the signing engine"
```

---

## Task 3: `_package.py` — `sign_app` 透传渠道(注入 `TELEPORT_SIGN_CHANNEL`)

`sign_app` 增 `channel_name` 形参;当为可定制渠道时,给签名子进程设环境变量 `TELEPORT_SIGN_CHANNEL`,驱动 `chromium_config.py` 的 `distributions`(Task 6)。

**Files:**
- Modify: `scripts/_package.py`(`sign_app`,约 `_package.py:95-112`)
- Test: `scripts/tests/test_package.py`

- [ ] **Step 1: 写失败测试**

在 `scripts/tests/test_package.py` 末尾追加:

```python
# ---------------------------------------------------------------------------
# sign_app injects TELEPORT_SIGN_CHANNEL for channel-customized runs
# ---------------------------------------------------------------------------


def _capture_sign_run(monkeypatch):
    captured = {}

    def _run(argv, **kw):
        captured["argv"] = argv
        captured["env"] = kw.get("env")
        return None

    monkeypatch.setattr(_package.subprocess, "run", _run)
    return captured


def test_sign_app_sets_channel_env(monkeypatch, tmp_path):
    captured = _capture_sign_run(monkeypatch)
    app = tmp_path / "out" / "Teleport.app"
    app.mkdir(parents=True)
    _package.sign_app(app, tmp_path / "dist" / "canary", "ident", "canary")
    assert captured["env"]["TELEPORT_SIGN_CHANNEL"] == "canary"


def test_sign_app_omits_channel_env_for_base(monkeypatch, tmp_path):
    captured = _capture_sign_run(monkeypatch)
    app = tmp_path / "out" / "Teleport.app"
    app.mkdir(parents=True)
    _package.sign_app(app, tmp_path / "dist" / "stable", "ident", "stable")
    assert "TELEPORT_SIGN_CHANNEL" not in (captured["env"] or {})


def test_sign_app_default_channel_is_base(monkeypatch, tmp_path):
    captured = _capture_sign_run(monkeypatch)
    app = tmp_path / "out" / "Teleport.app"
    app.mkdir(parents=True)
    _package.sign_app(app, tmp_path / "dist" / "x", "ident")  # no channel arg
    assert "TELEPORT_SIGN_CHANNEL" not in (captured["env"] or {})
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_package.py -k sign_app -v`
Expected: FAIL — `sign_app()` 现仅接受 3 个位置参数 / 未设 `env`(`TypeError` 或 KeyError)

- [ ] **Step 3: 写最小实现**

把 `scripts/_package.py` 的 `sign_app` 整体替换为(增形参 + 构造 env):

```python
def sign_app(app: Path, updates_dir: Path, identity: str,
             channel_name: str = "") -> None:
    """Sign the .app only (--disable-packaging) via the generated signing module.

    The signing module must run from the generated "<product> Packaging" dir:
    it holds signing/ PLUS the build-time-generated build_props_config.py
    (branding/version). The source tree's copy lacks it.

    For a channel-customized channel, TELEPORT_SIGN_CHANNEL drives the
    overridden `distributions` in chromium_config.py so the engine renames the
    app, suffixes the bundle id, and stamps CrProductDirName. The base channel
    leaves it unset (engine uses the bare Distribution).
    """
    sign_chrome = app.parent / "Teleport Packaging" / "sign_chrome.py"
    # signing's make_dir uses os.mkdir (single level), so pre-create the output
    # tree; the driver skips its own mkdir when the dir already exists.
    updates_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if channel_name and channel_name != "stable":
        env["TELEPORT_SIGN_CHANNEL"] = channel_name
    subprocess.run([
        sys.executable, str(sign_chrome),
        "--identity", identity,
        "--input", str(app.parent),
        "--output", str(updates_dir),
        "--disable-packaging",
    ], check=True, env=env)
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_package.py -k sign_app -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 回归全量 _package 测试**

Run: `uv run pytest scripts/tests/test_package.py -v`
Expected: PASS(含原有 stamp/detect 等用例)

- [ ] **Step 6: 提交**

```bash
git add scripts/_package.py scripts/tests/test_package.py
git commit -m "feat(package): sign_app injects TELEPORT_SIGN_CHANNEL for channel customization"
```

---

## Task 4: `package.py` — 在签名前暂存图标并把渠道名透传给 `sign_app`

`package.py` 的 distributable 分支当前调用 `_package.sign_app(app, updates_dir, cfg["codesign_identity"])`;改为先 `stage_channel_icons`,再带 `channel.name` 调 `sign_app`。

**Files:**
- Modify: `scripts/package.py`(约 `package.py:97`,实跑分支;dry-run 文案可选更新)
- Test: `scripts/tests/test_package_cli.py`

- [ ] **Step 1: 写失败测试**

在 `scripts/tests/test_package_cli.py` 的 `_stub_distributable` 中,为 `stage_channel_icons` 增桩并记录;在 `sign` 桩里记录 channel。把:

```python
    monkeypatch.setattr(package._package, "sign_app",
                        lambda app, ud, ident: order.append(("sign", ident)))
```

替换为:

```python
    monkeypatch.setattr(package._package, "stage_channel_icons",
                        lambda app, ch: order.append(("stage_icons", ch)))
    monkeypatch.setattr(package._package, "sign_app",
                        lambda app, ud, ident, ch: order.append(("sign", ident, ch)))
```

并在文件末尾新增断言用例:

```python
def test_distribute_passes_channel_to_sign_and_stages_icons(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    rc = package.main(["--channel", "canary", "--distribute"])
    assert rc == 0
    # icons staged before signing, both for the canary channel
    names = [c[0] for c in order]
    assert names.index("stage_icons") < names.index("sign")
    assert ("stage_icons", "canary") in order
    assert ("sign", "Developer ID Application: X (T)", "canary") in order
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_package_cli.py -v`
Expected: FAIL — `sign_app` 桩签名不匹配 / `stage_channel_icons` 未被调用(原 `package.py` 调 sign_app 仅 3 参,且未调 stage)

- [ ] **Step 3: 写最小实现**

在 `scripts/package.py` 中,把实跑分支(`# Build -> stamp -> sign -> styled dmg`)里的:

```python
    build(out, channel)
    _package.stamp_and_inject(app, version, cfg, channel.name)
    _package.sign_app(app, updates_dir, cfg["codesign_identity"])
```

替换为:

```python
    build(out, channel)
    _package.stamp_and_inject(app, version, cfg, channel.name)
    _package.stage_channel_icons(app, channel.name)
    _package.sign_app(app, updates_dir, cfg["codesign_identity"], channel.name)
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_package_cli.py -v`
Expected: PASS(含原有 canary 流程用例)

- [ ] **Step 5: 全量脚本测试回归**

Run: `uv run pytest`
Expected: PASS(全绿)

- [ ] **Step 6: 提交**

```bash
git add scripts/package.py scripts/tests/test_package_cli.py
git commit -m "feat(package): stage channel icons + pass channel to sign_app in package.main"
```

---

## Task 5: 新建 `modification.py.patch` — 去 Keystone(gate `KSProductID` 相关写入)

`channel_customize=True` 时,`modification.py:82` 在无 `KSProductID` 时 KeyError;`:90-100` 会凭空写入 `KSChannelID`。两处统一以 `if _KS_PRODUCT_ID in app_plist:` 门控,既修崩溃又不留 Keystone 脏键,且 `KSProductID` 存在时(上游 fixture)行为不变。

**Files:**
- Create: `patches/chrome/installer/mac/signing/modification.py.patch`
- 影响:`chromium/src/chrome/installer/mac/signing/modification.py`(应用后)

- [ ] **Step 1: 先确认上游基线干净**

Run:
```bash
cd "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src" && git -C chrome/installer/mac/signing diff --stat modification.py
```
Expected: 空输出(modification.py 未被改过;若非空,先 `git checkout chrome/installer/mac/signing/modification.py`)

- [ ] **Step 2: 在检出里手工改出目标内容**

编辑 `<checkout>/src/chrome/installer/mac/signing/modification.py`:

(a) 把(约 82 行,`if dist.channel_customize:` 块末尾):
```python
            app_plist[_KS_PRODUCT_ID] += '.' + dist.channel
```
改为:
```python
            # teleport overlay: only Keystone-enabled (Google) builds carry a
            # KSProductID. Our Sparkle build has none, so guard the append
            # (an unguarded += KeyErrors). No-op when the key is absent.
            if _KS_PRODUCT_ID in app_plist:
                app_plist[_KS_PRODUCT_ID] += '.' + dist.channel
```

(b) 把(约 90-100 行,KSChannelID 标签块):
```python
        base_tag = app_plist.get(_KS_CHANNEL_ID)
        base_channel_tag_components = []
        if base_tag:
            base_channel_tag_components.append(base_tag)
        if dist.channel:
            base_channel_tag_components.append(dist.channel)
        base_channel_tag = '-'.join(base_channel_tag_components)
        if base_channel_tag:
            app_plist[_KS_CHANNEL_ID] = base_channel_tag
        elif _KS_CHANNEL_ID in app_plist:
            del app_plist[_KS_CHANNEL_ID]
```
改为(整体多缩进一层,置于 `if _KS_PRODUCT_ID in app_plist:` 下):
```python
        # teleport overlay: the KSChannelID tag is a Keystone update-channel
        # label. Our runtime reads the channel from TeleportChannel instead, and
        # an un-guarded write would plant a stray KSChannelID on a build that
        # has no Keystone. Only touch it on Keystone-enabled builds.
        if _KS_PRODUCT_ID in app_plist:
            base_tag = app_plist.get(_KS_CHANNEL_ID)
            base_channel_tag_components = []
            if base_tag:
                base_channel_tag_components.append(base_tag)
            if dist.channel:
                base_channel_tag_components.append(dist.channel)
            base_channel_tag = '-'.join(base_channel_tag_components)
            if base_channel_tag:
                app_plist[_KS_CHANNEL_ID] = base_channel_tag
            elif _KS_CHANNEL_ID in app_plist:
                del app_plist[_KS_CHANNEL_ID]
```

> 注意:其下的 `if dist.product_dirname:`(CrProductDirName)与 `if dist.creator_code:`(CFBundleSignature)**保持不变**(它们不是 Keystone,是我们数据目录/creator 的必需逻辑)。`KSChannelID-` 后缀循环(约 108-114)是 no-op,亦不改。

- [ ] **Step 3: 生成 patch 文件**

Run:
```bash
cd "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src" && \
  git diff chrome/installer/mac/signing/modification.py \
  > "$OLDPWD/patches/chrome/installer/mac/signing/modification.py.patch"
```
(`$OLDPWD` 为 teleport 仓库根;若从别处运行,换成绝对路径)
Expected: 生成的 `.patch` 含上述两处改动,diff 头为 `diff --git a/chrome/installer/mac/signing/modification.py ...`

- [ ] **Step 4: 校验幂等应用(reverse→forward)**

Run:
```bash
cd "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src" && \
  git checkout chrome/installer/mac/signing/modification.py && \
  cd "$OLDPWD" && uv run python scripts/apply_patches.py 2>&1 | grep modification
```
Expected: 输出 `apply patches/chrome/installer/mac/signing/modification.py.patch`,无报错;再跑一次 `apply_patches.py` 仍幂等(无 "does not apply")。

- [ ] **Step 5: 跑上游签名单测,确保未破坏**

Run:
```bash
cd "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src/chrome/installer/mac/signing" && \
  python3 run_mac_signing_tests.py
```
Expected: 全部通过(`modification_test.py` 等;`KSProductID` 存在的 fixture 路径行为不变)。

- [ ] **Step 6: 提交**

```bash
cd "$OLDPWD"  # teleport repo root
git add patches/chrome/installer/mac/signing/modification.py.patch
git commit -m "feat(signing): de-Keystone patch — gate KSProductID/KSChannelID writes"
```

---

## Task 6: 扩展 `chromium_config.py.patch` — `distributions` 按 `TELEPORT_SIGN_CHANNEL` 返回渠道定制

让 `ChromiumCodeSignConfig.distributions` 读环境变量:基底渠道返回裸 `[Distribution()]`,其余返回 `channel_customize=True` 的 Distribution(后缀/改名/CrProductDirName/creator code 一键派生)。

**Files:**
- Modify: `patches/chrome/installer/mac/signing/chromium_config.py.patch`
- 影响:`chromium/src/chrome/installer/mac/signing/chromium_config.py`(应用后)

- [ ] **Step 1: 确认基线 + 已应用现有 patch**

Run:
```bash
cd "$PWD" && uv run python scripts/apply_patches.py >/dev/null 2>&1; \
  sed -n '1,40p' "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src/chrome/installer/mac/signing/chromium_config.py"
```
Expected: 文件含现有 `run_spctl_assess`(已 patch)。确认当前内容与 `patches/.../chromium_config.py.patch` 一致。

- [ ] **Step 2: 在检出里手工加入 `distributions` 覆盖**

编辑 `<checkout>/src/chrome/installer/mac/signing/chromium_config.py`:

把顶部:
```python
from signing.build_props_config import BuildPropsCodeSignConfig
```
改为:
```python
import os

from signing.build_props_config import BuildPropsCodeSignConfig
from signing.model import Distribution
```

在类末尾(`run_spctl_assess` 之后)追加:
```python

    @property
    def distributions(self):
        # teleport overlay: select the side-by-side distribution from
        # TELEPORT_SIGN_CHANNEL (set by scripts/_package.py:sign_app). The base
        # channel (unset / "stable") is the un-customized bundle: bare bundle
        # id, default data dir. Other channels are channel_customize=True so the
        # engine suffixes the bundle id, renames the app to
        # "<product> <Fragment>", stamps CrProductDirName, and swaps icons. The
        # one channel name is the single source of truth, shared with the
        # TeleportChannel Info.plist key stamped at packaging.
        channel = os.environ.get('TELEPORT_SIGN_CHANNEL', '').strip()
        if channel in ('', 'stable'):
            return [Distribution()]
        fragment = channel.capitalize()  # canary -> Canary, beta -> Beta
        return [
            Distribution(
                channel=channel,
                app_name_fragment=fragment,
                product_dirname='{} {}'.format(self.app_product, fragment),
                creator_code='Cr24',
                channel_customize=True)
        ]
```

> `self.app_product` 来自构建期生成的 build_props(= `Teleport`),故 `product_dirname` = `Teleport Canary`,与 §3/§9 一致。`creator_code` 用 BRANDING 的 `Cr24`。

- [ ] **Step 3: 重新生成 patch**

Run:
```bash
cd "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src" && \
  git diff chrome/installer/mac/signing/chromium_config.py \
  > "$OLDPWD/patches/chrome/installer/mac/signing/chromium_config.py.patch"
```
Expected: patch 同时含旧的 `run_spctl_assess` 与新的 `distributions`+imports。

- [ ] **Step 4: 幂等应用校验**

Run:
```bash
cd "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src" && \
  git checkout chrome/installer/mac/signing/chromium_config.py && \
  cd "$OLDPWD" && uv run python scripts/apply_patches.py 2>&1 | grep chromium_config
```
Expected: 应用成功;二次运行幂等。

- [ ] **Step 5: 跑上游签名单测,确保未破坏**

Run:
```bash
cd "${TELEPORT_CHROMIUM_DIR:-$PWD/chromium}/src/chrome/installer/mac/signing" && \
  python3 run_mac_signing_tests.py
```
Expected: 全部通过(覆盖 chromium_config 的用例不依赖该环境变量;默认分支返回裸 Distribution,与原行为一致)。

> 说明(已知盲区):`distributions` 覆盖无法用我们的 pytest 验证——`chromium_config.py` 的基类 `build_props_config` 在源码树不存在(构建期才生成),模块无法独立 import。其端到端正确性由 Task 9 真机冒烟验证。

- [ ] **Step 6: 提交**

```bash
cd "$OLDPWD"
git add patches/chrome/installer/mac/signing/chromium_config.py.patch
git commit -m "feat(signing): distributions override selects channel via TELEPORT_SIGN_CHANNEL"
```

---

## Task 7: `smoke_check.md` — 新增并排共存验证行

把不可单测的真机检查写入清单。

**Files:**
- Modify: `scripts/smoke_check.md`

- [ ] **Step 1: 阅读现有清单结构**

Run: `sed -n '1,60p' scripts/smoke_check.md`
Expected: 看到现有 canary 相关检查行的格式(表格或勾选项),据其风格追加。

- [ ] **Step 2: 追加并排共存检查项**

在 canary 章节追加(沿用文件既有 Markdown 风格;下为内容要点,按现有格式落):

```markdown
### canary 并排共存(per-channel 身份)

- [ ] canary 包 `Teleport Canary.app` 的 `CFBundleIdentifier` = `com.beansec.Teleport.canary`
      (`/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "/Applications/Teleport Canary.app/Contents/Info.plist"`)
- [ ] Finder 磁盘名为 `Teleport Canary`,应用内显示名为 `闪现 Canary`
- [ ] `CrProductDirName` = `Teleport Canary`,首次启动后存在
      `~/Library/Application Support/Teleport Canary/`(与 `~/Library/Application Support/Teleport` 分离)
- [ ] `chrome://version` 的「渠道 / Channel」行 = `canary`(由 TeleportChannel 键驱动,未受 bundle id 改名影响)
- [ ] **并排**:同时安装裸 `com.beansec.Teleport`(dev/未来 stable)与 `com.beansec.Teleport.canary`,二者可同时运行,各自独立 profile,互不干扰
- [ ] 嵌套身份正确:`Teleport Canary.app` 内 Alert Helper 的 bundle id 以 `com.beansec.Teleport.canary` 为前缀(`codesign -dvvv` 或 PlistBuddy 抽查),签名校验通过(`codesign --verify --deep --strict`)
```

- [ ] **Step 3: 提交**

```bash
git add scripts/smoke_check.md
git commit -m "docs(smoke): add canary side-by-side coexistence checks"
```

---

## Task 8: `CLAUDE.md` — 订正 bundle id 前缀 + 补并排共存 gotcha

`CLAUDE.md` 现写 `org.teleport.Teleport`,实际权威值为 `com.beansec.Teleport`(`BRANDING` 的 `MAC_BUNDLE_ID`)。订正并补一条 gotcha。

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 定位错误前缀**

Run: `grep -n "org.teleport.Teleport\|org\.teleport" CLAUDE.md`
Expected: 命中「两层品牌」gotcha 行(`org.teleport.Teleport`)。

- [ ] **Step 2: 订正前缀**

把 `CLAUDE.md` 中 `org.teleport.Teleport` 全部替换为 `com.beansec.Teleport`(磁盘/标识符示例处)。逐处确认上下文(如「`org.teleport.Teleport`」→「`com.beansec.Teleport`」)。

- [ ] **Step 3: 在「关键 gotcha」追加一条**

追加:

```markdown
- **渠道并排共存(per-channel 身份)**:各渠道身份由上游 `channel_customize` 引擎一键派生——bundle id 后缀(`com.beansec.Teleport` 裸=stable;`.canary`/`.beta`=其余)、app 改名(`Teleport Canary` / 显示名 `闪现 Canary`)、数据目录(Info.plist `CrProductDirName`,如 `Teleport Canary`)、图标。打包期 `_package.py:sign_app` 经环境变量 `TELEPORT_SIGN_CHANNEL` 驱动 `chromium_config.py` 的 `distributions` 覆盖;同一 channel 名同时驱动 bundle id 后缀与运行时 `TeleportChannel` 键(单一事实源)。**我们无 Keystone**:`modification.py.patch` 以 `if _KS_PRODUCT_ID in app_plist:` gate 掉 `KSProductID`/`KSChannelID` 写入(否则前者 KeyError、后者凭空植入脏键)。图标走最低复用:`stage_channel_icons` 把 `app.icns`/`Assets.car` 复制成 `app_<channel>.icns`/`Assets_<channel>.car` 喂给引擎硬依赖的 `_replace_icons`。签名产物落 `<output>/<channel>/Teleport <Fragment>.app`,`build_styled_dmg` 经 `_find_signed_app` 放宽 glob 定位。**bundle id 变更 → Sparkle 不跨 id 自动升级**:旧裸 id 的 canary 需手动重分发到新 `.canary` 包。
```

- [ ] **Step 4: 提交**

```bash
git add CLAUDE.md
git commit -m "docs(claude): fix bundle-id prefix to com.beansec.Teleport; add side-by-side gotcha"
```

---

## Task 9: 真机集成冒烟 + 迁移(人工,需 release 构建与签名证书)

前置:`TELEPORT_CHROMIUM_DIR` 已 export(若从 worktree 跑);Developer ID 证书在 keychain;`notarytool` profile 已存;`scripts/release_config.local.toml` 的 `[channel.canary]` 就绪;PGO profile 已 sync。

- [ ] **Step 1: 应用 overlay 并 gn gen**

```bash
uv run python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
```
Expected: 无报错。

- [ ] **Step 2: 本地打 canary 渠道包(构建+签名+公证,不发布)**

```bash
cd "$OLDPWD"  # teleport repo root
printf '0.1.7\n' > TELEPORT_VERSION   # 单调递增;若已更高则跳过
uv run python scripts/package.py --channel canary
```
Expected:产出 `dist/canary/Teleport-0.1.7.dmg`;构建期 `sign_chrome.py` 在 `TELEPORT_SIGN_CHANNEL=canary` 下把 app 改名为 `Teleport Canary.app`。

- [ ] **Step 3: 按 `smoke_check.md` 的并排章节逐项验证**

挂载 dmg、拖入 `/Applications`,逐项核对 Task 7 写入的 6 项(bundle id、显示名、数据目录、`chrome://version` 渠道行、并排运行、嵌套身份与签名校验)。
Expected:全部满足。重点确认 `chrome://version` 渠道行 = `canary`(回归 0.1.6 的 About 页崩溃也顺带复验,见 [[channel-alignment-feature]] 记忆中的 landmine)。

- [ ] **Step 4: 迁移(现网旧裸-id canary 用户)**

- 因 bundle id 由 `com.beansec.Teleport` → `com.beansec.Teleport.canary`,Sparkle 不跨 id 自升级:把本次 `Teleport-0.1.7.dmg` **手动分发**给内部少数 canary 用户,替换其旧安装。
- 数据目录从 `Teleport` → `Teleport Canary` 不自动迁移:告知用户重新登录,或手动 `cp -R "~/Library/Application Support/Teleport" "~/Library/Application Support/Teleport Canary"`。
Expected:用户装上新 `.canary` 包,后续经新 canary feed 正常自动升级。

- [ ] **Step 5: 发布(确认无误后)**

```bash
uv run python scripts/package.py --channel canary --distribute
```
Expected:appcast 生成 + OSS 上传 + 打 `v0.1.7` tag 并 push;新 feed 指向 `.canary` 包。

- [ ] **Step 6: 记录完成**

更新 `MEMORY.md` 中 [[channel-side-by-side-feature]] 状态为「DONE + 已发布」,记录实际版本号与迁移完成情况。

---

## Self-Review(规划者自查)

**1. Spec 覆盖**(逐节对照 `2026-05-30-channel-side-by-side-design.md`):
- §3 复用引擎 → Task 6(distributions 覆盖)+ Task 3(env 透传)✅
- §4 运行时 TeleportChannel 不变 → C++ 零改动,Task 中无 C++ 任务(刻意)✅
- §5 去-Keystone 补丁 → Task 5 ✅
- §6.1 注入点 → Task 6 ✅;§6.2 图标最低复用 → Task 2 + Task 4 ✅;§6.3 脚本适配 → Task 1(glob)+ Task 3(env)+ Task 4(透传)✅
- §7 测试 → Task 1-4 pytest + Task 5/6 上游签名单测 + Task 9 冒烟 ✅
- §8 迁移 → Task 9 Step 4 ✅
- §9 映射表 → Task 6(派生逻辑)+ Task 8(文档)✅
- §10 文件清单 → 全部出现在某 Task ✅

**2. 占位符扫描**:无 TBD/TODO;每个代码步均给出完整代码与确切命令、预期输出。✅

**3. 类型/命名一致性**:
- `stage_channel_icons(app, channel_name)` — Task 2 定义,Task 3 测试无关,Task 4 调用签名一致 ✅
- `sign_app(app, updates_dir, identity, channel_name="")` — Task 3 定义,Task 4 调用(4 参)与 test_package_cli 桩(4 参)一致 ✅
- `_find_signed_app(updates_dir)` — Task 1 定义,`build_styled_dmg` 调用一致 ✅
- `TELEPORT_SIGN_CHANNEL` — Task 3 写入、Task 6 读取,字符串一致 ✅
- `Distribution(channel=, app_name_fragment=, product_dirname=, creator_code=, channel_customize=)` — 与 `model.py:266-278` 形参一致 ✅
- 图标文件名用原始 channel(`app_canary.icns`),与 `modification.py:150-152` 的 `dist.channel` 一致 ✅

无遗留问题。
