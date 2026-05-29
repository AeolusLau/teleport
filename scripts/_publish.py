"""Publish phase: branch/clean/already-published guards, appcast generation,
OSS upload, and version tagging. Distributable channels only.
"""
from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path

from _lib import repo_root
from _package import sparkle_bin
from _release import assert_publishable


def fetch_live_appcast(feed_url: str) -> str | None:
    try:
        with urllib.request.urlopen(feed_url) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None  # first release: no feed yet


def current_branch() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def assert_on_main() -> None:
    branch = current_branch()
    if branch != "main":
        raise SystemExit(
            f"refusing to publish from branch {branch!r}; switch to main"
        )


def assert_clean_tree() -> None:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    if r.stdout.strip():
        raise SystemExit(
            "refusing to publish with a dirty working tree; commit or stash first"
        )


def tag_name(version: str) -> str:
    return f"v{version}"


def tag_exists(version: str) -> bool:
    r = subprocess.run(
        ["git", "tag", "--list", tag_name(version)],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    return bool(r.stdout.strip())


def assert_not_published(version: str, appcast_xml: str | None) -> None:
    """Refuse if `version` is already released -- by git tag OR by the live feed.

    Tag check is local and authoritative for anything we published (we always
    tag on publish). Feed check is defense-in-depth for a publish from another
    machine that never pushed a tag.
    """
    if tag_exists(version):
        raise SystemExit(
            f"refusing to publish {version}: tag {tag_name(version)} already "
            f"exists; bump TELEPORT_VERSION"
        )
    assert_publishable(version, appcast_xml)


def generate_appcast(updates_dir: Path, download_base_url: str,
                     keep_dmg: str) -> None:
    """Trim staging dir to the single current dmg, then run generate_appcast.

    Keeping only the current dmg makes the appcast list just the latest version
    and avoids dangling .delta references (generate_appcast preserves
    pre-existing delta entries even with --maximum-deltas 0).
    """
    for p in updates_dir.iterdir():
        if p.is_file() and p.name != keep_dmg:
            p.unlink()
    subprocess.run([
        str(sparkle_bin("generate_appcast")),
        "--maximum-deltas", "0",
        "--download-url-prefix", download_base_url,
        str(updates_dir),
    ], check=True)


def upload_to_oss(updates_dir: Path, target: str) -> None:
    """Upload dmg(s) + appcast.xml to OSS with correct cache headers.

    Versioned dmgs are immutable -> long cache; appcast.xml changes every
    release -> never cache.
    """
    for dmg in sorted(updates_dir.glob("*.dmg")):
        subprocess.run(
            ["ossutil", "cp", "-f", str(dmg), target,
             "--cache-control", "public, max-age=31536000, immutable"],
            check=True,
        )
    subprocess.run(
        ["ossutil", "cp", "-f", str(updates_dir / "appcast.xml"), target,
         "--cache-control", "no-cache"],
        check=True,
    )


def tag_and_push(version: str, remote: str) -> None:
    """Annotated-tag HEAD as v<version> and push the tag to `remote`."""
    name = tag_name(version)
    subprocess.run(
        ["git", "tag", "-a", name, "-m", f"release {version}"],
        cwd=repo_root(), check=True,
    )
    subprocess.run(["git", "push", remote, name], cwd=repo_root(), check=True)
