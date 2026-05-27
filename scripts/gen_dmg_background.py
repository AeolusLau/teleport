#!/usr/bin/env python3
"""Generate the dogfood dmg background image (brand/dmg/background.png).

The dmg window is 640x400; Finder draws the Teleport.app icon on the left and
the Applications symlink on the right (positions set in scripts/dmg_settings.py).
This background draws the guidance between them: product title, a drag arrow,
and a hint line. Run via: uv run --with pillow python scripts/gen_dmg_background.py
Produces @1x and @2x (Retina) so Finder picks the crisp one.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 640, 400
BG_TOP = (247, 247, 249)     # near-white, subtle vertical gradient
BG_BOTTOM = (228, 230, 235)
INK = (60, 63, 70)
HINT = (140, 144, 152)
ARROW = (120, 170, 255)      # soft blue drag arrow

# Icon centers (must match dmg_settings.py icon_locations + 64 for center).
APP_C = (160, 196)
APPS_C = (480, 196)


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(scale: int) -> Image.Image:
    w, h = W * scale, H * scale
    img = Image.new("RGB", (w, h), BG_TOP)
    px = img.load()
    for y in range(h):  # vertical gradient
        t = y / (h - 1)
        px_row = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = px_row
    d = ImageDraw.Draw(img)

    # PingFang isn't present on every macOS; fall through to other CJK fonts
    # before the Latin-only Helvetica (which renders Chinese as tofu boxes).
    cjk = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    title_f = _font(cjk, 30 * scale)
    hint_f = _font(cjk, 15 * scale)

    title = "闪现 · Teleport"
    tb = d.textbbox((0, 0), title, font=title_f)
    d.text(((w - (tb[2] - tb[0])) / 2, 40 * scale), title, font=title_f, fill=INK)

    hint = "将 Teleport 拖入「应用程序」完成安装"
    hb = d.textbbox((0, 0), hint, font=hint_f)
    d.text(((w - (hb[2] - hb[0])) / 2, 320 * scale), hint, font=hint_f, fill=HINT)

    # Drag arrow between the two icon slots (centered on the icon row).
    y = APP_C[1] * scale
    x0, x1 = 250 * scale, 392 * scale
    shaft = 7 * scale
    d.line([(x0, y), (x1 - 18 * scale, y)], fill=ARROW, width=shaft)
    d.polygon([(x1, y), (x1 - 26 * scale, y - 20 * scale),
               (x1 - 26 * scale, y + 20 * scale)], fill=ARROW)
    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "brand" / "dmg"
    out.mkdir(parents=True, exist_ok=True)
    base = render(1)
    base.save(out / "background.png")
    render(2).save(out / "background@2x.png")
    # Finder reads a multi-resolution TIFF for crisp Retina backgrounds.
    # LZW-compress so the committed asset stays small.
    base.save(out / "background.tiff", save_all=True,
              append_images=[render(2)], compression="tiff_lzw")
    print(f"wrote {out}/background.png (+@2x, +.tiff)")


if __name__ == "__main__":
    main()
