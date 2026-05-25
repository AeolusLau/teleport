"""One-time setup: ensure chromium checkout, create the teleport + out links.

Steps:
  1. Verify depot_tools (`gclient`) is on PATH.
  2. Ensure <chromium>/.gclient (src solution).
  3. Initial `gclient sync` to the pinned version (delegated to sync.py),
     unless --skip-sync (checkout already synced).
  4. Ensure <repo>/build exists.
  5. Create links: <chromium>/src/teleport -> <repo>/src, <chromium>/src/out -> <repo>/build.

The chromium checkout location honors $TELEPORT_CHROMIUM_DIR (see _lib.chromium_dir).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from _lib import chromium_dir, chromium_src, create_dir_link, repo_root

GCLIENT_SOLUTION = """\
solutions = [
  {
    "name": "src",
    "url": "https://chromium.googlesource.com/chromium/src.git",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {},
  },
]
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up chromium checkout + overlay links")
    parser.add_argument("--skip-sync", action="store_true",
                        help="skip gclient sync (checkout already synced to the pinned version)")
    args = parser.parse_args(argv)

    root = repo_root()
    if shutil.which("gclient") is None:
        print("error: depot_tools not found on PATH. Install depot_tools and add it to PATH:\n"
              "  https://chromium.googlesource.com/chromium/tools/depot_tools.git", file=sys.stderr)
        return 1

    chromium = chromium_dir(root)
    chromium.mkdir(parents=True, exist_ok=True)
    gclient_file = chromium / ".gclient"
    if not gclient_file.exists():
        gclient_file.write_text(GCLIENT_SOLUTION)
        print(f"wrote {gclient_file}")

    if not args.skip_sync:
        print("running initial gclient sync (this may take a long time)...")
        rc = subprocess.run([sys.executable, str(root / "scripts" / "sync.py")]).returncode
        if rc != 0:
            return rc

    src = chromium_src(root)
    if not (src / ".git").exists():
        print(f"error: {src} is not a chromium checkout (sync first, or set $TELEPORT_CHROMIUM_DIR)",
              file=sys.stderr)
        return 1

    # Build outputs stay in the standard <checkout>/src/out: autoninja locates the
    # checkout by walking up from the out dir, so out must live inside the tree.
    # Expose them at the repo root via a build/ -> src/out link (not the reverse).
    out = src / "out"
    out.mkdir(parents=True, exist_ok=True)
    create_dir_link(src / "teleport", root / "src")
    create_dir_link(root / "build", out)
    print(f"bootstrap complete: {src}/teleport -> {root}/src, {root}/build -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
