# Branding Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 macOS + 跨平台公共的 Chromium 图标与文案全部替换为我方品牌(产品名 闪现/閃現/Teleport;公司 北京小豆数安/BeanSec),`MAC_BUNDLE_ID=com.beansec.Teleport`。

**Architecture:** 图片由 `brand/teleport.svg` 标记渲染、经 `branding/` 资源覆盖替换上游;文案由 sync 后脚本 `branding_strings.py` 现场变换——改英文源 `chromium_strings.grd`(独立 `Chromium`→`Teleport`、`Chromium Authors`→`BeanSec`、产品名消息翻 translateable),并用 in-tree grit 按 `name` 映射重算、只重写 `zh-CN/zh-TW` 两个 `.xtb`(→闪现/閃現/中文公司名);其余语言自动回退英文。

**Tech Stack:** Python 3.13(uv)、resvg-py/icnsutil、in-tree grit(`tools/grit`)、Chromium M148 / GN+Siso。

**参考:** spec `docs/superpowers/specs/2026-05-25-branding-completion-design.md`。

**前置:** 已在 `main` 合入的 overlay 基础;`$TELEPORT_CHROMIUM_DIR` 指向 chromium 检出;`bootstrap.py --skip-sync` 已建链接。

**TDD 范围:** 变换脚本影响最终产品文案 → 关键逻辑写 pytest(替换/排除/grit-id/幂等)。图片生成与整构建由冒烟验证覆盖。

---

## Phase A — 品牌图片生成

### Task 1: 扩展图片生成器产出全部 product logo

**Files:**
- Modify: `scripts/generate_icons.py`(扩展为生成全套 + 现有 .icns)
- Output(生成物,纳入 `branding/` 覆盖,镜像 `chrome/app/theme/` 路径):见下

- [ ] **Step 1: 在 generate_icons.py 增加 product-logo 渲染**

在现有 `scripts/generate_icons.py` 末尾(`main()` 之前)加入:
```python
# --- product logo PNGs (overlay paths under chrome/app/theme) ---
THEME = REPO_ROOT / "branding" / "chrome" / "app" / "theme"
PRODUCT_LOGO_SIZES = (16, 24, 48, 64, 128, 256)
DEFAULT_100 = THEME / "default_100_percent" / "chromium"
APPICONSET = THEME / "chromium" / "mac" / "Assets.xcassets" / "AppIcon.appiconset"
ICONSET = THEME / "chromium" / "mac" / "Assets.xcassets" / "Icon.iconset"


def render_product_logos() -> None:
    base = THEME / "chromium"
    for s in PRODUCT_LOGO_SIZES:
        render_svg_to_png(SRC_SVG, base / f"product_logo_{s}.png", s)
    render_svg_to_png(SRC_SVG, base / "product_logo_22_mono.png", 22)  # 单色尽力而为
    shutil.copyfile(SRC_SVG, base / "product_logo.svg")
    for s in (16, 32):
        render_svg_to_png(SRC_SVG, DEFAULT_100 / f"product_logo_{s}.png", s)
    # 文字标位:先用标记顶上(无 wordmark 资产)
    render_svg_to_png(SRC_SVG, DEFAULT_100 / "product_logo_name_22.png", 22)
    render_svg_to_png(SRC_SVG, DEFAULT_100 / "product_logo_name_22_white.png", 22)


def render_mac_iconsets() -> None:
    for s in (16, 32, 64, 128, 256, 512, 1024):
        render_svg_to_png(SRC_SVG, APPICONSET / f"appicon_{s}.png", s)
    render_svg_to_png(SRC_SVG, ICONSET / "icon_256x256.png", 256)
    render_svg_to_png(SRC_SVG, ICONSET / "icon_256x256@2x.png", 512)
```
并在 `main()` 里 `pack_icns(...)` 之后调用 `render_product_logos()` 与 `render_mac_iconsets()`。

- [ ] **Step 2: 运行并确认生成物存在**

Run:
```bash
python scripts/generate_icons.py
ls branding/chrome/app/theme/chromium/product_logo_256.png \
   branding/chrome/app/theme/default_100_percent/chromium/product_logo_name_22.png \
   branding/chrome/app/theme/chromium/mac/Assets.xcassets/AppIcon.appiconset/appicon_1024.png
```
Expected: 三个文件都在;`file` 显示 PNG。
> ⚠️ 实现期对照 M148 真实目录核对路径/尺寸(尤其 `Icon.iconset` 命名、是否存在新版 `AppIcon.icon/`)。多余/缺失的目标按真实情况增删。

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_icons.py branding/
git commit -m "feat: generate full product-logo set from brand mark"
```

---

## Phase B — 字符串变换脚本

### Task 2: 英文源替换 + 排除(纯文本,先不碰 grit)

**Files:**
- Create: `scripts/branding_strings.py`
- Test: `scripts/tests/test_branding_strings.py`

- [ ] **Step 1: 写失败测试(词边界替换 + 排除)**

`scripts/tests/test_branding_strings.py`:
```python
import branding_strings as bs


def test_rebrand_text_replaces_standalone_product_name():
    src = "Welcome to Chromium\nAbout Chromium Browser"
    assert bs.rebrand_en_text(src) == "Welcome to Teleport\nAbout Teleport Browser"


def test_rebrand_text_replaces_authors():
    assert bs.rebrand_en_text("The Chromium Authors") == "BeanSec"
    assert bs.rebrand_en_text("Chromium Authors") == "BeanSec"


def test_rebrand_text_preserves_non_product_names():
    src = "ChromiumOS visit https://www.chromium.org and the Chromium Projects"
    # ChromiumOS / chromium.org / Chromium Projects 必须原样保留
    assert bs.rebrand_en_text(src) == src


def test_rebrand_zh_text():
    assert bs.rebrand_zh_text("关于Chromium", "zh-CN") == "关于闪现"
    assert bs.rebrand_zh_text("关于Chromium", "zh-TW") == "关于閃現"
    assert bs.rebrand_zh_text("The Chromium Authors", "zh-CN") == "北京小豆数安科技有限公司"
    assert bs.rebrand_zh_text("The Chromium Authors", "zh-TW") == "北京小豆數安科技有限公司"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'branding_strings'`)

- [ ] **Step 3: 写最小实现(替换逻辑)**

`scripts/branding_strings.py`:
```python
"""Rebrand Chromium product/company names in chromium_strings.grd + zh .xtb.

English source: standalone "Chromium" -> "Teleport", "(The )Chromium Authors"
-> "BeanSec". zh-CN/zh-TW .xtb values are rebranded to 闪现/閃現 + Chinese company
name and re-keyed to the new source message ids (via in-tree grit). Other locales
fall back to English. Excludes non-product names (ChromiumOS, chromium.org, etc.).
"""
from __future__ import annotations

import re

# Authors first (longest match), then standalone Chromium with exclusions.
_AUTHORS = re.compile(r"(?:The )?Chromium Authors")
# Standalone "Chromium" NOT followed by "OS"/".org"/" Projects" and not part of a URL/host.
_PRODUCT = re.compile(r"\bChromium\b(?!OS)(?!\.org)(?! Projects)(?!-)")

_ZH_PRODUCT = {"zh-CN": "闪现", "zh-TW": "閃現"}
_ZH_COMPANY = {"zh-CN": "北京小豆数安科技有限公司", "zh-TW": "北京小豆數安科技有限公司"}


def rebrand_en_text(text: str) -> str:
    text = _AUTHORS.sub("BeanSec", text)
    return _PRODUCT.sub("Teleport", text)


def rebrand_zh_text(text: str, locale: str) -> str:
    text = _AUTHORS.sub(_ZH_COMPANY[locale], text)
    return _PRODUCT.sub(_ZH_PRODUCT[locale], text)
```
> 排除规则用否定环视实现:`chromium.org` 因 `(?!\.org)` 保留;`ChromiumOS` 因 `(?!OS)` 保留;`Chromium Projects` 因 `(?! Projects)` 保留。实现期用 `grep -o` 扫 grd 里所有 `Chromium\S*` / `Chromium ` 上下文,补全否定环视清单(§spec 11)。

- [ ] **Step 4: 运行测试,确认通过**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py
git commit -m "feat: add product/company rebrand text transforms"
```

---

### Task 3: 翻转产品名消息为可翻译 + 写出英文源 grd

**Files:**
- Modify: `scripts/branding_strings.py`
- Test: `scripts/tests/test_branding_strings.py`

- [ ] **Step 1: 写失败测试(translateable 翻转 + 整文件变换)**

追加到 `scripts/tests/test_branding_strings.py`:
```python
def test_make_product_name_translatable():
    grd = ('<message name="IDS_PRODUCT_NAME" desc="x" translateable="false">\n'
           '  Chromium\n</message>')
    out = bs.transform_en_grd(grd)
    assert 'name="IDS_PRODUCT_NAME"' in out
    assert 'translateable="false"' not in out   # 已翻转
    assert "Teleport" in out and "Chromium" not in out


def test_transform_en_grd_rebrands_bodies():
    grd = '<message name="IDS_X" desc="d">About Chromium</message>'
    assert "About Teleport" in bs.transform_en_grd(grd)
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k "translatable or en_grd" -v`
Expected: FAIL（`AttributeError: ... transform_en_grd`)

- [ ] **Step 3: 实现 transform_en_grd**

追加到 `scripts/branding_strings.py`:
```python
# Product-name messages upstream marks translateable="false"; flip so zh .xtb applies.
_TRANSLATABLE_FALSE_NAMES = ("IDS_PRODUCT_NAME", "IDS_SHORT_PRODUCT_NAME")


def transform_en_grd(grd_text: str) -> str:
    for name in _TRANSLATABLE_FALSE_NAMES:
        grd_text = re.sub(
            r'(<message name="%s"[^>]*?) translateable="false"' % re.escape(name),
            r"\1",
            grd_text,
        )
    return rebrand_en_text(grd_text)
```
> ⚠️ 实现期确认 `translateable="false"` 的产品名消息完整清单(扫 `grep 'translateable="false"' chromium_strings.grd` 并判断哪些是产品名),补全 `_TRANSLATABLE_FALSE_NAMES`。注意不要误伤 `<ex>` 里的 Chromium(那是给翻译者的示例,不显示;`rebrand_en_text` 会改到它但无害,因为 ex 不进产物)。

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py
git commit -m "feat: flip product-name messages translatable in en grd"
```

---

### Task 4: 用 in-tree grit 重算并重写 zh-CN/zh-TW xtb

**Files:**
- Modify: `scripts/branding_strings.py`
- Test: `scripts/tests/test_branding_strings.py`

- [ ] **Step 1: 写失败测试(用 grit 算 id;微型 fixture)**

追加:
```python
import os
from pathlib import Path


def _grit_id(chromium_src: Path, presentable: str) -> str:
    import sys
    sys.path.insert(0, str(chromium_src / "tools" / "grit"))
    from grit.extern import tclib
    return tclib.GenerateMessageId(presentable)


def test_remap_changes_id_when_text_changes(tmp_path, monkeypatch):
    # 当源文本含 Chromium -> Teleport,id 应变化
    src = Path(os.environ["TELEPORT_CHROMIUM_DIR"]) / "src"
    old_id = _grit_id(src, "About Chromium")
    new_id = _grit_id(src, "About Teleport")
    assert old_id != new_id


def test_rekey_xtb_substitutes_value_and_id():
    # name->old_id, name->new_id 给定时,旧 xtb 条目应换 id 且译文本地化
    xtb = '<translation id="111">关于Chromium</translation>'
    out = bs.rekey_xtb(xtb, {"111": "222"}, "zh-CN")
    assert 'id="222"' in out and "关于闪现" in out and "111" not in out
```
> 该测试需 `TELEPORT_CHROMIUM_DIR` 指向检出(grit 在 `tools/grit`)。CI/无检出环境跳过 grit 用例。

- [ ] **Step 2: 运行,确认失败**

Run: `TELEPORT_CHROMIUM_DIR=$TELEPORT_CHROMIUM_DIR uv run pytest scripts/tests/test_branding_strings.py -k rekey -v`
Expected: FAIL（`AttributeError: ... rekey_xtb`)

- [ ] **Step 3: 实现 id 映射 + xtb 重写**

追加到 `scripts/branding_strings.py`:
```python
import sys
from pathlib import Path


def _load_grit(chromium_src: Path):
    grit_root = str(chromium_src / "tools" / "grit")
    if grit_root not in sys.path:
        sys.path.insert(0, grit_root)
    from grit import grd_reader  # noqa: E402
    return grd_reader


def message_name_to_id(chromium_src: Path, grd_path: Path) -> dict[str, str]:
    """{IDS_name: grit message id} for a grd, computed by grit itself."""
    grd_reader = _load_grit(chromium_src)
    grd = grd_reader.Parse(str(grd_path), os.path.dirname(str(grd_path)))
    grd.SetOutputLanguage("en")
    out: dict[str, str] = {}
    for node in grd.ActiveDescendants():
        if node.name == "message" and "name" in node.attrs:
            out[node.attrs["name"]] = node.GetId()
    return out


def build_id_remap(chromium_src: Path, old_grd: Path, new_grd: Path) -> dict[str, str]:
    old = message_name_to_id(chromium_src, old_grd)
    new = message_name_to_id(chromium_src, new_grd)
    return {old[n]: new[n] for n in old if n in new and old[n] != new[n]}


def rekey_xtb(xtb_text: str, id_remap: dict[str, str], locale: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        old_id, value = m.group(1), m.group(2)
        new_id = id_remap.get(old_id, old_id)
        return f'<translation id="{new_id}">{rebrand_zh_text(value, locale)}</translation>'
    return re.sub(r'<translation id="(\d+)">(.*?)</translation>', repl, xtb_text, flags=re.DOTALL)
```
> ⚠️ `grd_reader.Parse` 的精确签名、`SetOutputLanguage`、`ActiveDescendants`、`GetId` 在实现期对照 `tools/grit/grit/grd_reader.py` 与 `grit/node/message.py` 确认;若 API 不符按真实接口调整(核心不变:用 grit 取每条 message 的 id,按 `name` 建 old→new 映射)。

- [ ] **Step 4: 运行,确认通过**

Run: `TELEPORT_CHROMIUM_DIR=$TELEPORT_CHROMIUM_DIR uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py
git commit -m "feat: grit-based id remap + zh xtb rewrite"
```

---

### Task 5: `main()` 串起来 + 接入 apply 流程

**Files:**
- Modify: `scripts/branding_strings.py`(加 `main()`)
- Modify: `scripts/apply_patches.py`(末尾调用 branding_strings)

- [ ] **Step 1: 写 `main()`(就地变换 chromium/src)**

追加到 `scripts/branding_strings.py`:
```python
import shutil
import tempfile

from _lib import chromium_src, repo_root

GRD = "chrome/app/chromium_strings.grd"
XTB = {"zh-CN": "chrome/app/resources/chromium_strings_zh-CN.xtb",
       "zh-TW": "chrome/app/resources/chromium_strings_zh-TW.xtb"}


def main() -> int:
    src = chromium_src(repo_root())
    grd_path = src / GRD
    original = grd_path.read_text(encoding="utf-8")
    if "Teleport" in original and "Chromium" not in rebrand_en_text(original):
        pass  # already-applied trees still re-transform deterministically (idempotent)
    # snapshot original for id remap, then write transformed grd
    with tempfile.TemporaryDirectory() as td:
        old_copy = Path(td) / "old.grd"
        old_copy.write_text(original, encoding="utf-8")
        transformed = transform_en_grd(original)
        grd_path.write_text(transformed, encoding="utf-8")
        remap = build_id_remap(src, old_copy, grd_path)
    for locale, rel in XTB.items():
        p = src / rel
        p.write_text(rekey_xtb(p.read_text(encoding="utf-8"), remap, locale), encoding="utf-8")
    print(f"rebranded {GRD} + zh-CN/zh-TW xtb ({len(remap)} ids remapped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
> 幂等说明:脚本始终从「当前 chromium/src 的源」推导,变换是确定性的;在已替换树上重跑会基于已替换文本再算(为真正幂等,实现期让 `sync.py` 在每次同步后先还原这几个文件,或脚本检测已替换则跳过——以实测为准,记入 smoke)。

- [ ] **Step 2: 在 apply_patches.py 末尾调用**

修改 `scripts/apply_patches.py` 的 `main()`,在 `apply_branding(...)` 之后、`print("overlay applied.")` 之前加入:
```python
    import branding_strings
    branding_strings.main()
```

- [ ] **Step 3: 编译检查**

Run: `uv run python -m py_compile scripts/branding_strings.py scripts/apply_patches.py && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add scripts/branding_strings.py scripts/apply_patches.py
git commit -m "feat: wire branding_strings into apply flow"
```

---

## Phase C — 与现有 overlay 整合

### Task 6: 删除旧 grd patch,更新 BRANDING patch

**Files:**
- Delete: `patches/chrome/app/chromium_strings.grd.patch`
- Modify: `patches/chrome/app/theme/chromium/BRANDING.patch`

- [ ] **Step 1: 删除 MVP 的 grd patch(职责并入 branding_strings)**

```bash
git rm patches/chrome/app/chromium_strings.grd.patch
```

- [ ] **Step 2: 重做 BRANDING.patch(bundle id + 公司名)**

在干净检出上重新捕获(`$TELEPORT_CHROMIUM_DIR` 已设):
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && git checkout -- chrome/app/theme/chromium/BRANDING
python3 - <<'PY'
from pathlib import Path
f = Path("chrome/app/theme/chromium/BRANDING"); s = f.read_text()
repls = {
  "COMPANY_FULLNAME=The Chromium Authors\n": "COMPANY_FULLNAME=BeanSec\n",
  "COMPANY_SHORTNAME=The Chromium Authors\n": "COMPANY_SHORTNAME=BeanSec\n",
  "PRODUCT_FULLNAME=Chromium\n": "PRODUCT_FULLNAME=Teleport\n",
  "PRODUCT_SHORTNAME=Chromium\n": "PRODUCT_SHORTNAME=Teleport\n",
  "PRODUCT_INSTALLER_FULLNAME=Chromium Installer\n": "PRODUCT_INSTALLER_FULLNAME=Teleport Installer\n",
  "PRODUCT_INSTALLER_SHORTNAME=Chromium Installer\n": "PRODUCT_INSTALLER_SHORTNAME=Teleport Installer\n",
  "MAC_BUNDLE_ID=org.chromium.Chromium\n": "MAC_BUNDLE_ID=com.beansec.Teleport\n",
}
for o,n in repls.items():
    assert s.count(o)==1, o
    s=s.replace(o,n)
f.write_text(s); print("edited BRANDING")
PY
git -C "$TELEPORT_CHROMIUM_DIR/src" diff -- chrome/app/theme/chromium/BRANDING \
  > <repo>/patches/chrome/app/theme/chromium/BRANDING.patch
git -C "$TELEPORT_CHROMIUM_DIR/src" checkout -- chrome/app/theme/chromium/BRANDING
```
（把 `<repo>` 换成本 worktree 根。)Expected: patch 含 `COMPANY_*=BeanSec`、`MAC_BUNDLE_ID=com.beansec.Teleport`。

- [ ] **Step 3: 验证整套 overlay 干净应用**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && git checkout -- chrome/ && python <repo>/scripts/apply_patches.py
```
Expected: patches + branding 图标 + branding_strings 均成功;`grep -c 'Teleport' chrome/app/theme/chromium/BRANDING` ≥ 1;`grep -c '闪现' chrome/app/resources/chromium_strings_zh-CN.xtb` > 0。

- [ ] **Step 4: Commit**

```bash
git add patches/
git commit -m "chore: drop MVP grd patch; BRANDING -> BeanSec + com.beansec.Teleport"
```

---

## Phase D — 构建与冒烟验证

### Task 7: 整 chrome 构建 + 品牌冒烟验证

**Files:** Modify `scripts/smoke_check.md`

- [ ] **Step 1: 全量应用 + 构建(数小时)**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && git checkout -- chrome/
python <repo>/scripts/apply_patches.py
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/release chrome
```
Expected: 构建成功;产物 `Teleport.app`。

- [ ] **Step 2: 验证 bundle id 与图标**

Run:
```bash
APP=out/mac/arm64/release/Teleport.app
/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Contents/Info.plist"   # com.beansec.Teleport
cmp "$APP/Contents/Resources/app.icns" <repo>/branding/chrome/app/theme/chromium/mac/app.icns && echo icon-ok
```
Expected: `com.beansec.Teleport`;`icon-ok`。

- [ ] **Step 3: 验证文案(en=Teleport / zh-CN=闪现)**

Run(en;`--lang` 控制 UI 语言):
```bash
BIN="$APP/Contents/MacOS/Teleport"
rm -f /tmp/b_en.log /tmp/b_zh.log
"$BIN" --disable-field-trial-config --lang=en-US --user-data-dir=/tmp/b_en \
  --enable-logging --log-file=/tmp/b_en.log --no-first-run "chrome://version" &
P=$!; sleep 12; kill $P 2>/dev/null; wait $P 2>/dev/null
"$BIN" --disable-field-trial-config --lang=zh-CN --user-data-dir=/tmp/b_zh \
  --enable-logging --log-file=/tmp/b_zh.log --no-first-run "chrome://version" &
P=$!; sleep 12; kill $P 2>/dev/null; wait $P 2>/dev/null
```
然后人工在 GUI 关于页核对:en 显示 "Teleport"/"BeanSec";zh-CN 显示「闪现」「北京小豆数安科技有限公司」。
> 文案在 `.pak`(二进制),命令行不易 grep;以 GUI 关于页(`chrome://version`、`chrome://settings/help`)目视为准。

- [ ] **Step 4: 验证排除项未被破坏**

Run:
```bash
strings "$APP/Contents/Frameworks/"*/Resources/*.pak 2>/dev/null | grep -i "chromium.org\|ChromiumOS" | head
```
Expected: `chromium.org` / `ChromiumOS` 仍存在(未被改成 teleport.*)。
> pak 为压缩格式,`strings` 可能抓不全;主以 GUI 抽查为准。

- [ ] **Step 5: 固化 smoke 清单并提交**

把上述步骤补进 `scripts/smoke_check.md`(品牌验证小节),并:
```bash
git add scripts/smoke_check.md
git commit -m "docs: add branding smoke checks"
```

---

## 自查(spec 覆盖)

- spec §3 命名规则 → Task 2(替换映射)、Task 6(BRANDING):覆盖。
- §5 图片 → Task 1:覆盖(`win/`/`linux/` 平台专属按 spec 非目标)。
- §6.1 英文源替换 + translateable 翻转 + 排除 → Task 2/3:覆盖。
- §6.2 zh xtb 重写 + grit id 重算 → Task 4:覆盖。
- §6.3 其他语言回退 → 由「改源 → 失配 → 回退」机制达成(Task 3+4 的结果),Task 7 Step 3 抽查。
- §7 整合(删旧 grd patch、更新 BRANDING:com.beansec.Teleport + BeanSec) → Task 6:覆盖。
- §9 验证 → Task 7:覆盖。
- §10 测试 → Task 2/3/4 的 pytest:覆盖。
- §11 实现期核对项 → Task 1/3/4 的 ⚠️ 注记:覆盖。
