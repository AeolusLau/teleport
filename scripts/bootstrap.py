"""One-time setup: ensure chromium checkout, create the teleport + out links.

Steps:
  1. Verify depot_tools (`gclient`) is on PATH.
  2. Ensure <chromium>/.gclient (src solution).
  3. Initial `gclient sync` to the pinned version (delegated to sync.py),
     unless --skip-sync (checkout already synced).
  4. Ensure <repo>/build exists.
  5. Create links: <chromium>/src/teleport -> <repo>/src, <chromium>/src/out -> <repo>/build.

The chromium checkout location is derived from CHROMIUM_VERSION under
$TELEPORT_CHROMIUM_ROOT (defaulting to ~/workspace/chromium); $TELEPORT_CHROMIUM_DIR
still overrides the whole path when set (see _lib.chromium_dir).

Link semantics differ by direction: <chromium>/src/teleport -> <repo>/src is strict
(create_dir_link) — pointing elsewhere means cross-worktree contamination and must
raise. <repo>/build -> <chromium>/src/out is a pure access convenience and gets
repointed (repoint_dir_link) when a baseline switch leaves it aimed at the previous
checkout.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from _lib import (chromium_dir, chromium_src, create_dir_link, repo_root,
                  repoint_dir_link, write_text_lf)

# Name of the symlink this script creates at <chromium>/src/teleport, pointing
# at <repo>/src. Exported as a named constant (not just a literal below) so
# export_patches.py can recognize it as an injection artifact rather than an
# unclassified change -- it is untracked in every bootstrapped checkout, and
# without that recognition it trips the safety valve unconditionally.
SRC_LINK_NAME = "teleport"

# checkout_pgo_profiles=True makes `gclient sync` run chromium's own DEPS hooks
# that download BOTH PGO profile sets the release build needs:
#   * Chrome PGO       -> tools/update_pgo_profiles.py (--target mac-arm)
#   * V8 builtins PGO  -> v8/tools/builtins-pgo/download_profiles.py
# Both hooks are gated on this single var (the v8-standalone-only
# checkout_v8_builtins_pgo_profiles is NOT used here). release.mac.gn sets
# chrome_pgo_phase=2, which hard-requires both profiles, so fetching them at sync
# time via the upstream hooks keeps it reproducible without a bespoke script.
GCLIENT_SOLUTION = """\
solutions = [
  {
    "name": "src",
    "url": "https://chromium.googlesource.com/chromium/src.git",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {
      "checkout_pgo_profiles": True,
    },
  },
]
"""


def ensure_gclient(path: Path) -> None:
    """Write the canonical .gclient, or rewrite it when it predates the
    checkout_pgo_profiles custom_var. Idempotent: a no-op once the var is set.

    The .gclient is fully managed by this script (gitignored, generated), so
    rewriting from the template is safe."""
    if path.exists() and "checkout_pgo_profiles" in path.read_text():
        return
    verb = "updated" if path.exists() else "wrote"
    write_text_lf(path, GCLIENT_SOLUTION)
    print(f"{verb} {path} (enabled checkout_pgo_profiles)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up chromium checkout + overlay links")
    parser.add_argument("--skip-sync", action="store_true",
                        help="skip gclient sync (checkout already synced to the pinned version)")
    parser.add_argument("--root", type=Path, default=None,
                        help="teleport repo root (default: auto-detected; for tests)")
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else repo_root()
    if shutil.which("gclient") is None:
        print("error: depot_tools not found on PATH. Install depot_tools and add it to PATH:\n"
              "  https://chromium.googlesource.com/chromium/tools/depot_tools.git", file=sys.stderr)
        return 1

    chromium = chromium_dir(root)
    chromium.mkdir(parents=True, exist_ok=True)
    ensure_gclient(chromium / ".gclient")

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
    # traversed_by_build: the build system walks INTO this one, so on Windows it
    # must be a real symlink -- siso will not follow a junction. The build/ link
    # below is only a human convenience (nothing walks through it), so it stays
    # a junction and needs no privilege. See _lib.create_dir_link.
    create_dir_link(src / SRC_LINK_NAME, root / "src", traversed_by_build=True)
    repoint_dir_link(root / "build", out)
    print(f"bootstrap complete: {src}/{SRC_LINK_NAME} -> {root}/src, {root}/build -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
