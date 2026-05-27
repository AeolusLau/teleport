#!/usr/bin/env python3
"""Generate the dogfood dmg background image (brand/dmg/background.png).

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
