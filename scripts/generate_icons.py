#!/usr/bin/env python3
"""Generate the macOS app icon (.icns) for the teleport overlay from brand/teleport.svg.

Pipeline: SVG -> PNG store (resvg-py) -> .icns (icnsutil). Both packages are
fetched per-invocation by `uv run --with`, so nothing needs to be installed on
the orchestrator interpreter. The output is written to the overlay path
branding/chrome/app/theme/chromium/mac/app.icns, which apply_patches.py copies
onto the Chromium checkout.

Run manually whenever brand/teleport.svg changes, then commit the regenerated
.icns. Adapted from the archived teleport-cef scripts/generate_icons.py.

Later phases will extend this with Windows .ico / Linux PNGs.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Pinned; bump deliberately.
RESVG_PY_VERSION = "0.3.1"
ICNSUTIL_VERSION = "1.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_SVG = REPO_ROOT / "brand" / "teleport.svg"
# Overlay target mirrors the chromium/src path; apply_patches.py copies it in.
ICNS_OUT = REPO_ROOT / "branding" / "chrome" / "app" / "theme" / "chromium" / "mac" / "app.icns"
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def preflight() -> None:
    if shutil.which("uv") is None:
        sys.exit("ERROR: 'uv' not found on PATH. Install with: brew install uv")
    if not SRC_SVG.is_file():
        sys.exit(f"ERROR: {SRC_SVG} not found")


def render_svg_to_png(svg: Path, out: Path, size: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    inline = (
        "import sys\n"
        "from pathlib import Path\n"
        "from resvg_py import svg_to_bytes\n"
        "svg = Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "Path(sys.argv[2]).write_bytes(\n"
        "    svg_to_bytes(svg_string=svg, width=int(sys.argv[3]), height=int(sys.argv[3]))\n"
        ")\n"
    )
    subprocess.run(
        ["uv", "run", "--with", f"resvg-py=={RESVG_PY_VERSION}",
         "python", "-c", inline, str(svg), str(out), str(size)],
        check=True,
    )


def pack_icns(png_dir: Path) -> None:
    ICNS_OUT.parent.mkdir(parents=True, exist_ok=True)
    inline = (
        "import sys\n"
        "import icnsutil\n"
        "out = sys.argv[1]\n"
        "icns = icnsutil.IcnsFile()\n"
        "# The ICNS spec has no 64@1x OSType; Apple assigned ic12 = 32pt @2x (64 px).\n"
        "for png in sys.argv[2:]:\n"
        "    if png.endswith('-64.png'):\n"
        "        icns.add_media('ic12', file=png)\n"
        "    else:\n"
        "        icns.add_media(file=png)\n"
        "icns.write(out)\n"
    )
    pngs = [str(png_dir / f"teleport-{s}.png") for s in ICNS_SIZES]
    subprocess.run(
        ["uv", "run", "--with", f"icnsutil=={ICNSUTIL_VERSION}",
         "python", "-c", inline, str(ICNS_OUT), *pngs],
        check=True,
    )


# --- product logo PNGs (overlay paths under chrome/app/theme) ---
THEME = REPO_ROOT / "branding" / "chrome" / "app" / "theme"
PRODUCT_LOGO_SIZES = (16, 24, 48, 64, 128, 256)
DEFAULT_100 = THEME / "default_100_percent" / "chromium"
DEFAULT_200 = THEME / "default_200_percent" / "chromium"
APPICONSET = THEME / "chromium" / "mac" / "Assets.xcassets" / "AppIcon.appiconset"
ICONSET = THEME / "chromium" / "mac" / "Assets.xcassets" / "Icon.iconset"

# WebUI logos (settings/about/downloads/history/extensions) come from IDR_PRODUCT_LOGO_*
# = chrome_scaled_image, which reads BOTH density dirs. (logical size, density multiplier)
_SCALED_LOGOS = {1: DEFAULT_100, 2: DEFAULT_200}


def render_product_logos() -> None:
    base = THEME / "chromium"
    for s in PRODUCT_LOGO_SIZES:
        render_svg_to_png(SRC_SVG, base / f"product_logo_{s}.png", s)
    render_svg_to_png(SRC_SVG, base / "product_logo_22_mono.png", 22)  # best-effort mono
    shutil.copyfile(SRC_SVG, base / "product_logo.svg")
    # IDR_PRODUCT_LOGO_{16,32} and IDR_PRODUCT_LOGO_NAME_22{,_WHITE} at 1x AND 2x density.
    # Retina (2x) is what an Apple Silicon Mac actually shows, so both are required.
    for mult, d in _SCALED_LOGOS.items():
        render_svg_to_png(SRC_SVG, d / "product_logo_16.png", 16 * mult)
        render_svg_to_png(SRC_SVG, d / "product_logo_32.png", 32 * mult)
        # wordmark slots: use the mark for now (no separate wordmark asset)
        render_svg_to_png(SRC_SVG, d / "product_logo_name_22.png", 22 * mult)
        render_svg_to_png(SRC_SVG, d / "product_logo_name_22_white.png", 22 * mult)


def render_mac_iconsets() -> None:
    for s in (16, 32, 64, 128, 256, 512, 1024):
        render_svg_to_png(SRC_SVG, APPICONSET / f"appicon_{s}.png", s)
    render_svg_to_png(SRC_SVG, ICONSET / "icon_256x256.png", 256)
    render_svg_to_png(SRC_SVG, ICONSET / "icon_256x256@2x.png", 512)


# chrome://version logo: IDR_PRODUCT_LOGO / IDR_PRODUCT_LOGO_WHITE come from
# components/resources/version_ui_scaled_resources.grdp -> chromium/product_logo.png
# and chromium/product_logo_white.png (chrome_scaled_image, read from
# default_{100,200}_percent). Upstream ships a "swirl + Chromium" wordmark; we
# compose "<mark> 闪现 Teleport" the same way. The page's #logo is
# float:right/width:180px with no forced <img> size, so the natural width is used.
# The mark sits on a white disc, so one mark works on both the light and dark
# page; only the text color changes (near-black for light, white for dark).
VERSION_RES = REPO_ROOT / "branding" / "components" / "resources"
VERSION_100 = VERSION_RES / "default_100_percent" / "chromium"
VERSION_200 = VERSION_RES / "default_200_percent" / "chromium"
WORDMARK_TEXT = "闪现 Teleport"
# CJK+Latin fonts Pillow can open (dev-time only — the PNG is committed). Pillow
# cannot open PingFang.ttc, so prefer Hiragino Sans GB, then Arial Unicode MS.
_WORDMARK_FONTS = (
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
)

# Compose at 2x for crispness, then downscale to 1x so the two density assets are
# exactly 2:1 (chrome_scaled_image expects 200% == 2x 100%).
_WORDMARK_PY = r'''
import sys
from PIL import Image, ImageDraw, ImageFont
mark_p, out2_p, out1_p, text = sys.argv[1:5]
r, g, b = int(sys.argv[5]), int(sys.argv[6]), int(sys.argv[7])
fonts = [(sys.argv[i], int(sys.argv[i + 1])) for i in range(8, len(sys.argv), 2)]
H = 64
size = round(H * 0.46)  # text cap height relative to the mark; smaller = subtler
font = None
for path, idx in fonts:
    try:
        font = ImageFont.truetype(path, size, index=idx)
        break
    except OSError:
        continue
if font is None:
    sys.exit("generate_icons: no Pillow-openable CJK+Latin font for the wordmark")
mark = Image.open(mark_p).convert("RGBA").resize((H, H), Image.LANCZOS)
gap, pad = round(H * 0.16), round(H * 0.12)
text_w = round(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=font))
w2 = H + gap + text_w + pad
w2 += w2 % 2  # even width so the 1x downscale is exactly half
img2 = Image.new("RGBA", (w2, H), (0, 0, 0, 0))
img2.alpha_composite(mark, (0, 0))
ImageDraw.Draw(img2).text((H + gap, H / 2), text, font=font, fill=(r, g, b, 255), anchor="lm")
img2.save(out2_p)
img2.resize((w2 // 2, H // 2), Image.LANCZOS).save(out1_p)
'''


def _compose_wordmark(mark_png: Path, out_1x: Path, out_2x: Path, rgb: tuple) -> None:
    out_1x.parent.mkdir(parents=True, exist_ok=True)
    out_2x.parent.mkdir(parents=True, exist_ok=True)
    font_args = [str(x) for pair in _WORDMARK_FONTS for x in pair]
    subprocess.run(
        ["uv", "run", "--with", "pillow", "python", "-c", _WORDMARK_PY,
         str(mark_png), str(out_2x), str(out_1x), WORDMARK_TEXT,
         str(rgb[0]), str(rgb[1]), str(rgb[2]), *font_args],
        check=True,
    )


def render_version_logos() -> None:
    with tempfile.TemporaryDirectory(prefix="teleport-wordmark-") as td:
        mark = Path(td) / "mark-64.png"
        render_svg_to_png(SRC_SVG, mark, 64)
        _compose_wordmark(mark, VERSION_100 / "product_logo.png",
                          VERSION_200 / "product_logo.png", (32, 33, 36))
        _compose_wordmark(mark, VERSION_100 / "product_logo_white.png",
                          VERSION_200 / "product_logo_white.png", (255, 255, 255))


def main() -> int:
    preflight()
    print("==> rendering PNGs + packing .icns from brand/teleport.svg")
    with tempfile.TemporaryDirectory(prefix="teleport-icons-") as td:
        png_dir = Path(td)
        for s in ICNS_SIZES:
            render_svg_to_png(SRC_SVG, png_dir / f"teleport-{s}.png", s)
            print(f"    rendered {s}x{s}")
        pack_icns(png_dir)
    print(f"wrote {ICNS_OUT.relative_to(REPO_ROOT)}")
    print("==> rendering product logos")
    render_product_logos()
    print("==> rendering chrome://version logos")
    render_version_logos()
    print("==> rendering macOS icon sets")
    render_mac_iconsets()
    return 0


if __name__ == "__main__":
    sys.exit(main())
