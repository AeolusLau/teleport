import subprocess
from pathlib import Path

import pytest

import sync


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _make_tagged_repo(tmp_path: Path, tag: str) -> Path:
    """A one-commit git repo tagged `tag` at HEAD -- stands in for a chromium/
    src checkout that `gclient sync --revision src@<tag> --with_tags` just
    produced."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "t@t")
    _git(src, "config", "user.name", "t")
    (src / "chrome").mkdir()
    (src / "chrome" / "VERSION").write_text("MAJOR=0\nMINOR=0\nBUILD=0\nPATCH=0\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "baseline")
    _git(src, "tag", tag)
    return src


def test_verify_version_passes_when_head_is_the_pinned_tag(tmp_path: Path):
    src = _make_tagged_repo(tmp_path, "151.0.7922.76")
    sync.verify_version(src, "151.0.7922.76")  # must not raise


def test_verify_version_raises_when_head_has_moved_past_the_pinned_tag(tmp_path: Path):
    src = _make_tagged_repo(tmp_path, "151.0.7922.76")
    (src / "chrome" / "VERSION").write_text("MAJOR=151\nMINOR=0\nBUILD=7922\nPATCH=132\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "a later commit HEAD now points at")
    with pytest.raises(RuntimeError, match="chromium checkout mismatch"):
        sync.verify_version(src, "151.0.7922.76")


def test_verify_version_raises_a_readable_error_when_the_tag_is_missing(tmp_path: Path):
    src = _make_tagged_repo(tmp_path, "151.0.7922.76")
    with pytest.raises(RuntimeError, match="151.0.7922.999"):
        sync.verify_version(src, "151.0.7922.999")


def test_verify_version_ignores_chrome_version_entirely(tmp_path: Path):
    """Regression pin for the F2 defect: apply_patches.py unconditionally
    overwrites chrome/VERSION with TELEPORT_VERSION (the product version) as
    part of applying the overlay -- see generate_version.py. That is the
    normal state of every 路径 A (security-patch) re-sync, which reuses an
    already-overlaid checkout. verify_version() must pass on exactly this
    checkout shape: HEAD is genuinely the pinned tag, chrome/VERSION holds an
    unrelated product version that does not even parse as the pinned tag."""
    src = _make_tagged_repo(tmp_path, "151.0.7922.76")
    (src / "chrome" / "VERSION").write_text("MAJOR=0\nMINOR=2\nBUILD=0\nPATCH=0\n")
    sync.verify_version(src, "151.0.7922.76")  # must not raise


def test_resolved_tag_commit_matches_head_of_the_tagged_commit(tmp_path: Path):
    src = _make_tagged_repo(tmp_path, "151.0.7922.76")
    head = _git(src, "rev-parse", "HEAD").strip()
    assert sync.resolved_tag_commit(src, "151.0.7922.76") == head
