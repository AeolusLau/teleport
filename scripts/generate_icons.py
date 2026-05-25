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
    return 0


if __name__ == "__main__":
    sys.exit(main())
