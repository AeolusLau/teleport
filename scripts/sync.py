"""Sync chromium/src to the pinned version and verify it matches CHROMIUM_VERSION."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _lib import chromium_src, repo_root


def resolved_tag_commit(src: Path, tag: str) -> str:
    """Resolve `tag` to the commit it points at in `src`'s git history."""
    r = subprocess.run(
        ["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"],
        cwd=src, capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"pinned tag {tag} not found in {src} -- `gclient sync --with_tags` "
            f"should have fetched it (git rev-parse: {r.stderr.strip()})")
    return r.stdout.strip()


def verify_version(src: Path, expected: str) -> None:
    """Verify `src`'s checked-out HEAD is exactly the pinned upstream tag.

    Deliberately does NOT read chrome/VERSION. apply_patches.py unconditionally
    overwrites that file with TELEPORT_VERSION (the 4-segment product version,
    see generate_version.py) as part of applying the overlay, so on any
    checkout that already carries the overlay it no longer reflects what
    gclient actually synced. That is not a rare edge case: it is the normal
    state of every 路径 A (security-patch) re-sync in
    docs/chromium-upgrade-runbook.md, which by design reuses an
    already-overlaid checkout. Comparing chrome/VERSION there raised on every
    single run -- the 24-48h 0-day response path check_upstream_release.py
    points operators at -- not just on a genuine mismatch.

    git HEAD is unaffected by anything apply_patches.py does, and directly
    reflects what `gclient sync --revision src@<expected>` actually checked
    out (that flag IS the git ref gclient resolves and checks out), so
    resolving the pinned tag to a commit and comparing it to HEAD verifies
    the one thing this function exists to verify -- correctly on a brand new
    checkout AND an overlay-applied one alike.
    """
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True, check=True,
    ).stdout.strip()
    pinned_commit = resolved_tag_commit(src, expected)
    if head != pinned_commit:
        described = subprocess.run(
            ["git", "describe", "--tags", "--always", "HEAD"],
            cwd=src, capture_output=True, text=True,
        ).stdout.strip() or head
        raise RuntimeError(
            f"chromium checkout mismatch: HEAD is {described} ({head}), "
            f"pinned tag {expected} resolves to {pinned_commit}")


def main() -> int:
    root = repo_root()
    pinned = (root / "CHROMIUM_VERSION").read_text().strip()
    src = chromium_src(root)
    chromium = src.parent
    print(f"gclient sync src@{pinned} ...")
    rc = subprocess.run(
        ["gclient", "sync", "--revision", f"src@{pinned}", "--with_tags", "--no-history"],
        cwd=chromium,
    ).returncode
    if rc != 0:
        return rc
    verify_version(src, pinned)
    print(f"synced and verified chromium {pinned}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
