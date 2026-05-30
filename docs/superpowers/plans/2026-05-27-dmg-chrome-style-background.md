# Chrome 风格 canary dmg 背景实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 canary dmg 打开后的窗口做成 macOS 版 Google Chrome 默认安装窗口的观感(竖版纯白底、下方岩蓝圆角卡片含大白下箭头、应用程序文件夹带别名角标、普通黑字标签)。

**Architecture:** 几何/配色集中到一个无第三方依赖的纯模块 `scripts/dmg_layout.py`,作为"背景美术"与"Finder 图标摆放"两边的唯一事实来源;`gen_dmg_background.py` 据此只画静态美术(白底 + 卡片 + 箭头),`dmg_settings.py` 据此摆放真实图标并隐藏文件夹标签;pytest 守护两边对齐(纯逻辑,免 PIL),渲染与最终窗口靠合成预览图人工比对。

**Tech Stack:** Python 3.13(`uv`)、Pillow(经 `uv run --with pillow`,非测试依赖)、dmgbuild、pytest(`pythonpath=["scripts"]`,dev 依赖仅 pytest + dmgbuild)。

参照设计:`docs/superpowers/specs/2026-05-27-dmg-chrome-style-background-design.md`。

**约定与边界**

- `gen_dmg_background.py`、`dmg_settings.py`、`preview_dmg_window.py` 属构建/工具脚本(非随产品发布的 C++ 产品代码),按项目约定不强制 TDD;本计划对**可测的纯逻辑**(几何不变量、settings 与 layout 的对齐)写 pytest,对**视觉渲染**用合成预览图人工核验。
- pytest dev 依赖不含 Pillow;因此**测试只 import `dmg_layout`(纯)并 exec `dmg_settings.py`(仅依赖 `os.path`)**,绝不在测试里 import `gen_dmg_background`/`preview_dmg_window`(它们 import PIL)。
- `scripts/package_release.py` **不改**(已指向 `brand/dmg/background.tiff`,卷名已是 `Teleport`)。

---

## File Structure

- Create: `scripts/dmg_layout.py` — 纯几何/配色常量 + 箭头几何 helper(无第三方依赖)。
- Create: `scripts/tests/test_dmg_layout.py` — 几何不变量测试。
- Create: `scripts/tests/test_dmg_settings.py` — exec `dmg_settings.py` 守护其与 `dmg_layout` 对齐、文件夹标签隐藏。
- Create: `scripts/preview_dmg_window.py` — 合成预览(真实图标 + 系统文件夹 + 角标 + 标签)供人工比对的 QA 工具。
- Rewrite: `scripts/gen_dmg_background.py` — 据 `dmg_layout` 只画白底 + 卡片 + 箭头。
- Rewrite: `scripts/dmg_settings.py` — 竖版 `window_rect`/`icon_size`/`icon_locations`,空格名隐藏文件夹标签。
- Regenerate (committed artifacts): `brand/dmg/background.png`、`background@2x.png`、`background.tiff`。

---

## Task 1: 共享几何模块 `dmg_layout.py` + 不变量测试(TDD)

**Files:**
- Create: `scripts/dmg_layout.py`
- Test: `scripts/tests/test_dmg_layout.py`

- [ ] **Step 1: 写失败测试** — `scripts/tests/test_dmg_layout.py`

```python
import dmg_layout as L


def test_portrait_canvas():
    assert L.W > 0 and L.H > 0
    assert L.H > L.W  # portrait window, like Chrome's dmg


def test_card_within_canvas_and_in_lower_region():
    x0, y0, x1, y1 = L.CARD
    assert 0 <= x0 < x1 <= L.W
    assert 0 <= y0 < y1 <= L.H
    assert (y0 + y1) / 2 > L.H / 2  # card sits in the lower half


def test_app_icon_clears_the_card():
    _, card_top, _, _ = L.CARD
    app_bottom = L.APP_CENTER[1] + L.ICON_SIZE / 2
    assert app_bottom < card_top  # app icon on the white area, above the card


def test_apps_folder_inside_card():
    x0, y0, x1, y1 = L.CARD
    cx, cy = L.APPS_CENTER
    half = L.ICON_SIZE / 2
    assert x0 <= cx - half and cx + half <= x1
    assert y0 <= cy - half and cy + half <= y1


def test_arrow_sits_above_folder_inside_card():
    folder_top = L.APPS_CENTER[1] - L.ICON_SIZE / 2
    assert L.ARROW_TIP <= folder_top           # arrow points down to the folder
    assert L.ARROW_SHAFT_TOP > L.CARD[1]       # arrow starts below the card top


def test_apps_label_is_blank():
    assert L.APPS_LABEL.strip() == ""          # blank name => no Finder label


def test_arrow_helpers_match_constants():
    sx0, sy0, sx1, sy1 = L.arrow_shaft()
    assert (sy0, sy1) == (L.ARROW_SHAFT_TOP, L.ARROW_SHAFT_BOTTOM)
    head = L.arrow_head()
    assert head[-1] == (L.APPS_CENTER[0], L.ARROW_TIP)  # tip is last point
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd <worktree> && uv run pytest scripts/tests/test_dmg_layout.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dmg_layout'`

- [ ] **Step 3: 实现 `scripts/dmg_layout.py`**

```python
"""Single source of truth for the canary dmg window geometry & colors.

Both scripts/gen_dmg_background.py (paints the static background art) and
scripts/dmg_settings.py (places the Finder icons) must agree on these numbers,
or the app icon / Applications folder won't line up with the painted card and
arrow. scripts/tests/test_dmg_layout.py and test_dmg_settings.py guard that.

Pure data + tiny helpers, no third-party deps, so it imports cleanly under
`uv run pytest` (Pillow is not a test dependency).
"""

# Window content size (== background image size). Portrait, like Chrome's dmg.
W = 480
H = 512

# Finder draws every icon at one size; 128 matches Chrome's large icons.
ICON_SIZE = 128

# Icon centers (logical px; origin = top-left of the background image).
APP_CENTER = (240, 128)    # app icon on the white upper area
APPS_CENTER = (240, 396)   # Applications folder, centered on the lower card

# Lower rounded card (x0, y0, x1, y1) and its corner radius.
CARD = (72, 256, 408, 468)
CARD_RADIUS = 28

# Colors. Slate-blue card is a Teleport brand nudge from Chrome's lavender.
BG_FILL = (255, 255, 255)
CARD_FILL = (214, 222, 238)
ARROW_FILL = (255, 255, 255)

# The Applications symlink is named with a single space so Finder shows no
# label under it (matches Chrome's default). icon_locations keys on this name.
APPS_LABEL = " "

# Big white down-arrow, centered on APPS_CENTER x, in the card's upper portion.
ARROW_SHAFT_TOP = 272
ARROW_SHAFT_BOTTOM = 304
ARROW_TIP = 328
ARROW_SHAFT_HALFWIDTH = 18
ARROW_HEAD_TOP = 302
ARROW_HEAD_HALFWIDTH = 38


def arrow_shaft():
    """Rectangle (x0, y0, x1, y1) for the arrow shaft."""
    cx = APPS_CENTER[0]
    return (cx - ARROW_SHAFT_HALFWIDTH, ARROW_SHAFT_TOP,
            cx + ARROW_SHAFT_HALFWIDTH, ARROW_SHAFT_BOTTOM)


def arrow_head():
    """Triangle [(x, y), ...] for the arrow head; tip is the last point."""
    cx = APPS_CENTER[0]
    return [(cx - ARROW_HEAD_HALFWIDTH, ARROW_HEAD_TOP),
            (cx + ARROW_HEAD_HALFWIDTH, ARROW_HEAD_TOP),
            (cx, ARROW_TIP)]
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest scripts/tests/test_dmg_layout.py -q`
Expected: PASS(7 passed)

- [ ] **Step 5: 提交**

```bash
git add scripts/dmg_layout.py scripts/tests/test_dmg_layout.py
git commit -m "feat(dmg): add shared dmg window layout module + invariants"
```

---

## Task 2: 竖版 `dmg_settings.py` + 对齐守护测试(TDD)

**Files:**
- Test: `scripts/tests/test_dmg_settings.py`
- Modify (rewrite): `scripts/dmg_settings.py`

- [ ] **Step 1: 写失败测试** — `scripts/tests/test_dmg_settings.py`

```python
from pathlib import Path

import dmg_layout as L

SETTINGS = Path(__file__).resolve().parent.parent / "dmg_settings.py"


def _exec_settings(app="/tmp/Teleport.app"):
    # dmgbuild injects `defines`; emulate it so we can read the module's vars.
    g = {"defines": {"app": app, "icon": None, "background": None}}
    exec(compile(SETTINGS.read_text(), str(SETTINGS), "exec"), g)
    return g


def test_window_rect_matches_layout():
    g = _exec_settings()
    assert g["window_rect"][1] == (L.W, L.H)


def test_icon_size_matches_layout():
    g = _exec_settings()
    assert g["icon_size"] == L.ICON_SIZE


def test_icon_locations_match_layout():
    g = _exec_settings()
    assert g["icon_locations"]["Teleport.app"] == L.APP_CENTER
    assert g["icon_locations"][L.APPS_LABEL] == L.APPS_CENTER


def test_applications_label_is_hidden():
    g = _exec_settings()
    assert g["symlinks"] == {L.APPS_LABEL: "/Applications"}


def test_icon_view_and_ulmo_preserved():
    g = _exec_settings()
    assert g["default_view"] == "icon-view"
    assert g["format"] == "ULMO"
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest scripts/tests/test_dmg_settings.py -q`
Expected: FAIL — 现有 `dmg_settings.py` 是横版 `window_rect=((220,220),(640,400))`、`symlinks={"Applications":...}`、`icon_locations` 用 `"Applications"` 键且坐标为 `(160,196)`/`(480,196)`,故 `window_rect`/`icon_locations`/`symlinks` 三项断言失败。

- [ ] **Step 3: 重写 `scripts/dmg_settings.py`**

```python
"""dmgbuild settings for the Teleport canary disk image.

Invoked by scripts/package_release.py via:
  dmgbuild -s scripts/dmg_settings.py \
    -D app=<signed Teleport.app> -D icon=<volume .icns> -D background=<tiff> \
    Teleport <out.dmg>

dmgbuild evaluates this file with `defines` (the -D values) in scope.

Portrait layout mirroring Chrome's default install window: the app icon on the
white upper area, a lower rounded card with a big white down-arrow above the
Applications folder. Geometry MUST stay in sync with scripts/dmg_layout.py
(which paints the matching background art); scripts/tests/test_dmg_settings.py
guards the alignment.
"""
import os.path

app = defines.get("app")  # noqa: F821 (dmgbuild injects `defines`)
appname = os.path.basename(app)

# Contents: the app plus an Applications symlink named with a single space, so
# Finder shows no label under it (matches Chrome's default install window).
files = [app]
symlinks = {" ": "/Applications"}

# Volume icon (the app's .icns) and the window background art.
icon = defines.get("icon")  # noqa: F821
background = defines.get("background")  # noqa: F821

# lzma-compressed UDIF (needs macOS 10.15+; our floor is 12.0).
format = "ULMO"

# Portrait icon-view layout. window_rect is ((x, y), (width, height)); width and
# height equal the background image size (dmg_layout.W, dmg_layout.H = 480, 512).
default_view = "icon-view"
window_rect = ((220, 220), (480, 512))
icon_size = 128
text_size = 13
icon_locations = {
    appname: (240, 128),   # dmg_layout.APP_CENTER  — app icon on the white area
    " ": (240, 396),       # dmg_layout.APPS_CENTER — Applications folder on card
}
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest scripts/tests/test_dmg_settings.py -q`
Expected: PASS(5 passed)

- [ ] **Step 5: 提交**

```bash
git add scripts/dmg_settings.py scripts/tests/test_dmg_settings.py
git commit -m "feat(dmg): portrait Chrome-style window layout + hidden Apps label"
```

---

## Task 3: 重写 `gen_dmg_background.py` 并重新生成背景产物(视觉核验)

**Files:**
- Rewrite: `scripts/gen_dmg_background.py`
- Regenerate: `brand/dmg/background.png`、`background@2x.png`、`background.tiff`

- [ ] **Step 1: 重写 `scripts/gen_dmg_background.py`**

```python
#!/usr/bin/env python3
"""Generate the canary dmg background image (brand/dmg/background.png).

Paints only the static art for a Chrome-style portrait install window: a white
canvas and a lower rounded card with a big white down-arrow. The app icon, the
Applications folder, its alias badge, and ALL text labels are drawn by Finder on
top of this background (positions in scripts/dmg_settings.py), so they are NOT
painted here. Geometry/colors come from scripts/dmg_layout.py.

Run via: uv run --with pillow python scripts/gen_dmg_background.py
Produces @1x and @2x (Retina) plus a multi-resolution .tiff for Finder.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import dmg_layout as L


def _scale(box, s):
    return [int(round(v * s)) for v in box]


def render(scale: int) -> Image.Image:
    img = Image.new("RGB", (L.W * scale, L.H * scale), L.BG_FILL)
    d = ImageDraw.Draw(img)

    # Lower rounded card.
    d.rounded_rectangle(_scale(L.CARD, scale),
                        radius=L.CARD_RADIUS * scale, fill=L.CARD_FILL)

    # Big white down-arrow (shaft + head), centered on the Applications folder.
    d.rectangle(_scale(L.arrow_shaft(), scale), fill=L.ARROW_FILL)
    head = [(int(round(x * scale)), int(round(y * scale))) for x, y in L.arrow_head()]
    d.polygon(head, fill=L.ARROW_FILL)
    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "brand" / "dmg"
    out.mkdir(parents=True, exist_ok=True)
    base = render(1)
    base.save(out / "background.png")
    render(2).save(out / "background@2x.png")
    # Finder reads a multi-resolution TIFF for crisp Retina backgrounds.
    base.save(out / "background.tiff", save_all=True,
              append_images=[render(2)], compression="tiff_lzw")
    print(f"wrote {out}/background.png (+@2x, +.tiff)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 重新生成背景产物**

Run: `uv run --with pillow python scripts/gen_dmg_background.py`
Expected: `wrote <repo>/brand/dmg/background.png (+@2x, +.tiff)`

- [ ] **Step 3: 视觉核验背景美术**

用 Read 工具查看 `brand/dmg/background@2x.png`。
Expected: 纯白底 + 下方岩蓝圆角卡片 + 卡片上半部一个大白色块状下箭头;**无任何文字、无图标**(图标由 Finder 叠加)。尺寸应为 960×1024(480×512 @2x)。

- [ ] **Step 4: 确认纯逻辑测试仍全绿**

Run: `uv run pytest -q`
Expected: PASS(原有 + 新增 layout/settings 测试全部通过)

- [ ] **Step 5: 提交(脚本 + 重新生成的产物)**

```bash
git add scripts/gen_dmg_background.py brand/dmg/background.png brand/dmg/background@2x.png brand/dmg/background.tiff
git commit -m "feat(dmg): repaint background as Chrome-style white canvas + arrow card"
```

---

## Task 4: 组装窗口预览 QA 工具 + 与 Chrome 比对、收尾

**Files:**
- Create: `scripts/preview_dmg_window.py`

- [ ] **Step 1: 创建 `scripts/preview_dmg_window.py`**

```python
#!/usr/bin/env python3
"""Assemble a preview of the canary dmg window for visual QA.

Composites the real app icon, the system Applications folder + alias badge, and
the Finder-style app label onto the generated background, at the exact icon
positions read from scripts/dmg_settings.py and the size from
scripts/dmg_layout.py — WITHOUT running a multi-hour package_release build. Use
it to eyeball alignment/colors against Chrome's default install window.

Run: uv run --with pillow python scripts/preview_dmg_window.py
Writes /tmp/teleport_dmg_preview.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import dmg_layout as L

REPO = Path(__file__).resolve().parent.parent
BG = REPO / "brand" / "dmg" / "background@2x.png"
APP_ICNS = REPO / "branding" / "chrome" / "app" / "theme" / "chromium" / "mac" / "app.icns"
APPS_ICNS = "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/ApplicationsFolderIcon.icns"
ALIAS_ICNS = "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/AliasBadgeIcon.icns"
S = 2  # background@2x is rendered at 2x


def _settings(app="/x/Teleport.app"):
    g = {"defines": {"app": app, "icon": None, "background": None}}
    path = REPO / "scripts" / "dmg_settings.py"
    exec(compile(path.read_text(), str(path), "exec"), g)
    return g


def _icns(path, size_logical):
    im = Image.open(path).convert("RGBA")
    return im.resize((size_logical * S, size_logical * S), Image.LANCZOS)


def _font(size_logical):
    for c in ["/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(c, size_logical * S)
        except OSError:
            continue
    return ImageFont.load_default()


def _paste_centered(canvas, icon, center_logical):
    cx, cy = center_logical[0] * S, center_logical[1] * S
    canvas.alpha_composite(icon, (cx - icon.width // 2, cy - icon.height // 2))


def main():
    g = _settings()
    loc, isize = g["icon_locations"], g["icon_size"]
    canvas = Image.open(BG).convert("RGBA")
    d = ImageDraw.Draw(canvas)

    # App icon + black label (Finder draws the label from the .app's name).
    app_center = loc["Teleport.app"]
    _paste_centered(canvas, _icns(APP_ICNS, isize), app_center)
    f = _font(g["text_size"])
    label = "Teleport"
    b = d.textbbox((0, 0), label, font=f)
    lx = app_center[0] * S - (b[2] - b[0]) // 2 - b[0]
    ly = (app_center[1] + isize // 2) * S + 6 * S
    d.text((lx, ly), label, font=f, fill=(35, 35, 38, 255))

    # Applications folder + alias badge. Finder auto-draws the badge for a real
    # symlink; composited here only for the preview. No label (blank symlink name).
    apps_center = loc[L.APPS_LABEL]
    folder = _icns(APPS_ICNS, isize)
    _paste_centered(canvas, folder, apps_center)
    badge = _icns(ALIAS_ICNS, isize // 2)
    fx = apps_center[0] * S - folder.width // 2
    fy = apps_center[1] * S - folder.height // 2
    canvas.alpha_composite(badge, (fx - 8 * S, fy + folder.height - badge.height + 6 * S))

    out = Path("/tmp/teleport_dmg_preview.png")
    canvas.convert("RGB").save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 生成预览并人工比对**

Run: `uv run --with pillow python scripts/preview_dmg_window.py`
Expected: `wrote /tmp/teleport_dmg_preview.png`
然后用 Read 工具查看 `/tmp/teleport_dmg_preview.png`,与参照(Chrome 默认安装窗口截图)比对:竖版布局、app 图标在白区上方居中、黑字 "Teleport" 标签、下方岩蓝卡片含白箭头 + 应用程序文件夹、文件夹左下角别名角标、文件夹无文字标签。

- [ ] **Step 3:(条件性)对齐微调**

若比对发现图标与卡片/箭头错位或留白不佳:仅在 `scripts/dmg_layout.py` 调整对应常量(`APP_CENTER`/`APPS_CENTER`/`CARD`/`ARROW_*`/`H` 等),然后重跑 `scripts/gen_dmg_background.py`(重生背景)与 `uv run pytest -q`(不变量 + 对齐守护须仍全绿),再重跑预览。`dmg_settings.py` 的字面量若涉及坐标需同步改动(测试会强制其与 `dmg_layout` 一致)。无需微调则跳过。

- [ ] **Step 4: 全量测试 + 提交**

Run: `uv run pytest -q`
Expected: PASS(全绿)

```bash
git add scripts/preview_dmg_window.py
# 若 Step 3 有微调,一并 add 受影响文件:
#   scripts/dmg_layout.py scripts/dmg_settings.py \
#   brand/dmg/background.png brand/dmg/background@2x.png brand/dmg/background.tiff
git commit -m "feat(dmg): add assembled-window preview tool for dmg QA"
```

- [ ] **Step 5:(可选,重量级,通常交由人工)端到端打包核验**

需 `export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`、已签名 release 构建、签名/公证凭据齐备。
Run: `uv run python scripts/package_release.py --no-upload`
然后打开生成的 `Teleport-<ver>.dmg`,确认实际 Finder 渲染与预览一致(尤其别名角标由 Finder 自动绘制为标准白圈箭头、空格名文件夹确无标签)。若空格名在目标 macOS 上渲染异常,回退:`dmg_layout.APPS_LABEL = "Applications"`(并相应放开"隐藏标签"预期)后重跑 Task 1/2 测试与本步。

---

## Self-Review

**Spec coverage**(对照 spec 各节):
- 竖版/白底/卡片/箭头/别名角标 → Task 1(几何)+ Task 3(美术)+ Task 4(角标由 Finder/预览体现)。✓
- B 岩蓝配色 → `dmg_layout.CARD_FILL=(214,222,238)`(Task 1)。✓
- 普通黑字标签、隐藏文件夹标签 → `dmg_settings.symlinks={" ":...}` + `APPS_LABEL`(Task 2),预览中体现(Task 4)。✓
- 背景无文字 / 消除 CJK 字体隐患 → `gen_dmg_background.py` 不再绘制任何文字(Task 3)。✓
- 关键参数(尺寸/icon_size/坐标/配色)→ `dmg_layout.py` 常量(Task 1)。✓
- `package_release.py` 不改 → 全计划未触及。✓
- 验证方式(轻量预览 + 全链路)→ Task 4 Step 2 / Step 5。✓
- 空格名隐藏标签的风险与回退 → Task 4 Step 5 回退说明。✓
- TDD 范围(工具脚本务实测试)→ 纯逻辑 TDD(Task 1/2),渲染视觉核验(Task 3/4)。✓

**Placeholder scan:** 无 TBD/TODO;每个代码步骤均给出完整代码;每个命令步骤给出预期输出。Task 4 Step 3 为条件性微调(明确触发条件与操作),非占位。

**Type/name consistency:** `dmg_layout` 的 `W/H/ICON_SIZE/APP_CENTER/APPS_CENTER/CARD/CARD_RADIUS/BG_FILL/CARD_FILL/ARROW_FILL/APPS_LABEL/ARROW_*` 与 `arrow_shaft()`/`arrow_head()` 在 Task 1 定义,Task 2(测试 exec settings 比对)、Task 3(render 使用)、Task 4(预览使用)引用一致;`dmg_settings.py` 的 `icon_locations` 键 `appname`(="Teleport.app")与 `" "`(==`APPS_LABEL`)与测试断言一致;`window_rect[1]==(W,H)`、`icon_size==ICON_SIZE` 一致。
