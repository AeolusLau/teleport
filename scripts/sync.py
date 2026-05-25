"""Sync chromium/src to the pinned version and verify it matches CHROMIUM_VERSION."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _lib import chromium_src, repo_root


def parse_chrome_version(version_file: Path) -> str:
    fields: dict[str, str] = {}
    for line in Path(version_file).read_text().splitlines():
        if "=" in line:
            k, _, val = line.partition("=")
            fields[k.strip()] = val.strip()
    return f"{fields['MAJOR']}.{fields['MINOR']}.{fields['BUILD']}.{fields['PATCH']}"


def verify_version(version_file: Path, expected: str) -> None:
    actual = parse_chrome_version(version_file)
    if actual != expected:
        raise RuntimeError(f"chromium version mismatch: checked out {actual}, pinned {expected}")


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
    verify_version(src / "chrome" / "VERSION", pinned)
    print(f"synced and verified chromium {pinned}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
