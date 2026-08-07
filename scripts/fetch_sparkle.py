#!/usr/bin/env python3
"""Fetch the pinned, notarized Sparkle release into the shared deps cache and
place a REAL copy of Sparkle.framework in the chromium checkout for GN
bundle_data to copy into the app. A symlink would be copied verbatim into the
signed .app/dmg as a dangling link to ~/.cache, so the in-checkout framework
must be real files. Idempotent: reuses the cache + an existing real copy.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from _lib import chromium_src, deps_cache_dir, sha256_of

# Pinned Sparkle 2.x release. Update SPARKLE_VERSION + SPARKLE_SHA256 together
# (recompute via: curl -fsSL "$(archive_url)" | shasum -a 256).
SPARKLE_VERSION = "2.9.2"
SPARKLE_SHA256 = "1cb340cbbef04c6c0d162078610c25e2221031d794a3449d89f2f56f4df77c95"

# Path inside the chromium checkout holding the real framework copy. GN
# bundle_data + framework_dirs reference //third_party/teleport_sparkle.
LINK_RELPATH = "third_party/teleport_sparkle"


def archive_url() -> str:
    return (
        "https://github.com/sparkle-project/Sparkle/releases/download/"
        f"{SPARKLE_VERSION}/Sparkle-{SPARKLE_VERSION}.tar.xz"
    )


def cache_dir() -> Path:
    return deps_cache_dir() / "sparkle" / SPARKLE_VERSION


def cache_framework_path() -> Path:
    return cache_dir() / "Sparkle.framework"


def link_path(root: Path | None = None) -> Path:
    return chromium_src(root) / LINK_RELPATH / "Sparkle.framework"


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_of(path)
    if actual != expected:
        raise RuntimeError(f"sha256 mismatch for {path}: got {actual}, expected {expected}")


def download_and_extract() -> None:
    """Download the pinned archive, verify sha256, extract into the cache."""
    dst = cache_dir()
    if (dst / "Sparkle.framework").exists():
        return  # already populated
    dst.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.xz", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve(archive_url(), tmp_path)
        verify_sha256(tmp_path, SPARKLE_SHA256)
        with tarfile.open(tmp_path, "r:xz") as tar:
            tar.extractall(dst, filter="data")
    finally:
        tmp_path.unlink(missing_ok=True)


def install_framework(root: Path | None = None) -> None:
    """Place a REAL copy (not a symlink) of the cached framework in the
    checkout, preserving the framework's internal version symlinks."""
    src = chromium_src(root)
    if not (src / ".git").exists():
        raise RuntimeError(
            f"{src} is not a chromium git checkout -- refusing to install "
            f"Sparkle.framework into it. Run this after the checkout exists "
            f"(bootstrap.py, or the runbook's §B0 `git clone --local`), "
            f"not before: without this guard, install_framework() would "
            f"`mkdir -p` a phantom {src}/{LINK_RELPATH}/ tree under a "
            f"checkout that does not exist yet, which then breaks a later "
            f"`git clone --local` into the same path with a confusing "
            f"'destination path already exists' error instead of the real "
            f"cause.")
    dest = link_path(root)
    if dest.is_symlink():
        dest.unlink()  # replace a legacy symlink from an older fetch_sparkle
    if dest.is_dir():
        return  # real copy already in place
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cache_framework_path(), dest, symlinks=True)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Fetch + install the pinned Sparkle.framework").parse_args(argv)
    src = chromium_src()
    if not (src / ".git").exists():
        print(f"error: {src} is not a chromium git checkout -- run this after "
              f"the checkout exists (bootstrap.py / the runbook's §B0 "
              f"`git clone --local`), not before", file=sys.stderr)
        return 1
    download_and_extract()
    fw = cache_framework_path()
    if not fw.exists():
        print(f"error: {fw} missing after extract", file=sys.stderr)
        return 1
    install_framework()
    print(f"sparkle ready: real copy at {link_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
