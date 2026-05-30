#!/usr/bin/env python3
"""Assemble a preview of the canary dmg window for visual QA.

Composites the real app icon, the system Applications folder + alias badge, and
the Finder-style app label onto the generated background, at the exact icon
positions read from scripts/dmg_settings.py and the size from
scripts/dmg_layout.py — WITHOUT running a multi-hour package build. Use
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
