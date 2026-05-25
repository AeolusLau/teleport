"""Apply text patches (patches/) and resource overlays (branding/) onto chromium/src.

One-patch-per-file: each *.patch mirrors one upstream path; application is
order-independent (sorted only for reproducibility). Idempotent and fail-fast.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from _lib import chromium_src, repo_root


def find_patches(patches_dir: Path) -> list[Path]:
    return sorted(p for p in Path(patches_dir).rglob("*.patch") if p.is_file())


def _reverse_applies(patch: Path, src: Path) -> bool:
    r = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(patch)],
        cwd=src, capture_output=True, text=True,
    )
    return r.returncode == 0


def _forward_applies(patch: Path, src: Path) -> bool:
    r = subprocess.run(
        ["git", "apply", "--check", str(patch)],
        cwd=src, capture_output=True, text=True,
    )
    return r.returncode == 0


def apply_patch(patch: Path, src: Path) -> None:
    if _reverse_applies(patch, src):
        return  # already applied -> idempotent no-op
    if not _forward_applies(patch, src):
        raise RuntimeError(f"patch does not apply cleanly: {patch}")
    subprocess.run(["git", "apply", str(patch)], cwd=src, check=True)


def apply_branding(branding_dir: Path, src: Path) -> None:
    branding_dir = Path(branding_dir)
    for f in sorted(branding_dir.rglob("*")):
        if not f.is_file():
            continue
        dest = src / f.relative_to(branding_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)  # whole-file overlay; naturally idempotent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply teleport overlay onto chromium/src")
    parser.add_argument("--root", type=Path, default=repo_root())
    args = parser.parse_args(argv)
    src = chromium_src(args.root)
    if not (src / ".git").exists():
        print(f"error: {src} is not a chromium git checkout (run bootstrap.py first)", file=sys.stderr)
        return 1
    for patch in find_patches(args.root / "patches"):
        print(f"apply {patch.relative_to(args.root)}")
        apply_patch(patch, src)
    branding = args.root / "branding"
    if branding.exists():
        print("overlay branding/")
        apply_branding(branding, src)
    print("overlay applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
