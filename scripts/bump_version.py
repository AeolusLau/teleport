#!/usr/bin/env python3
"""Bump the TELEPORT_VERSION semver and commit the change.

Usage (run from anywhere; operates on the repo root):

    python scripts/bump_version.py             # bump patch (default)
    python scripts/bump_version.py --patch     # 0.1.6 -> 0.1.7
    python scripts/bump_version.py --minor     # 0.1.6 -> 0.2.0
    python scripts/bump_version.py --major     # 0.1.6 -> 1.0.0

Only one of --major/--minor/--patch may be given. Bumping a segment zeros every
segment after it. Must be run on `main`; the new TELEPORT_VERSION is committed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _lib import repo_root
from _publish import current_branch
from _release import parse_semver, read_teleport_version

# Ordered: bumping a part zeros every part to its right.
_PARTS = ("major", "minor", "patch")


def bump(version: str, part: str) -> str:
    """Return `version` with `part` incremented and lower segments zeroed.

    Raises ValueError on an unknown part or a non-semver version.
    """
    if part not in _PARTS:
        raise ValueError(f"unknown version part: {part!r} (expected one of {_PARTS})")
    nums = list(parse_semver(version))
    i = _PARTS.index(part)
    nums[i] += 1
    for j in range(i + 1, len(nums)):
        nums[j] = 0
    return ".".join(str(n) for n in nums)


def assert_on_main() -> None:
    branch = current_branch()
    if branch != "main":
        raise SystemExit(f"refusing to bump version from branch {branch!r}; switch to main")


def commit_version(root: Path, new_version: str) -> None:
    version_file = root / "TELEPORT_VERSION"
    subprocess.run(["git", "add", str(version_file)], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"release: bump TELEPORT_VERSION to {new_version}"],
        cwd=root,
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump TELEPORT_VERSION and commit.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--major", action="store_const", const="major", dest="part",
                       help="bump MAJOR, zero MINOR and PATCH")
    group.add_argument("--minor", action="store_const", const="minor", dest="part",
                       help="bump MINOR, zero PATCH")
    group.add_argument("--patch", action="store_const", const="patch", dest="part",
                       help="bump PATCH (default)")
    parser.set_defaults(part="patch")
    args = parser.parse_args(argv)

    assert_on_main()

    root = repo_root()
    current = read_teleport_version(root)
    new_version = bump(current, args.part)

    (root / "TELEPORT_VERSION").write_text(new_version + "\n")
    commit_version(root, new_version)

    print(f"bumped {args.part}: {current} -> {new_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
