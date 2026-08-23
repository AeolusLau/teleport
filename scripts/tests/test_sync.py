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


def test_resolved_tag_commit_falls_back_to_origin_on_a_shallow_checkout(
        tmp_path: Path, monkeypatch):
    """`gclient sync --no-history` yields a depth-1 clone with NO tags -- a
    shallow fetch of one revision never negotiates the tag refs, so --with_tags
    has nothing to bring along. The local lookup must not be read as "the
    checkout is wrong"; it means "ask origin"."""
    src = _make_tagged_repo(tmp_path, "other-tag")   # pinned tag absent locally
    monkeypatch.setattr(
        sync, "remote_tag_commit", lambda s, tag: "deadbeef" * 5)
    assert sync.resolved_tag_commit(src, "151.0.7922.76") == "deadbeef" * 5


def test_resolved_tag_commit_prefers_the_local_tag_when_present(tmp_path: Path,
                                                                monkeypatch):
    """A full checkout answers locally -- no network round trip per sync."""
    src = _make_tagged_repo(tmp_path, "151.0.7922.76")
    monkeypatch.setattr(sync, "remote_tag_commit", lambda s, tag: "wrong")
    head = _git(src, "rev-parse", "HEAD").strip()
    assert sync.resolved_tag_commit(src, "151.0.7922.76") == head


def _ls_remote(monkeypatch, stdout: str, returncode: int = 0):
    class _R:
        pass
    r = _R()
    r.stdout, r.stderr, r.returncode = stdout, "", returncode
    monkeypatch.setattr(sync.subprocess, "run", lambda *a, **kw: r)


def test_remote_tag_commit_prefers_the_peeled_ref(tmp_path: Path, monkeypatch):
    """An ANNOTATED tag advertises the tag object under refs/tags/<t> and the
    commit it wraps under refs/tags/<t>^{}. Taking the unpeeled line would
    compare HEAD against a tag object's hash -- never equal to a commit hash --
    and the mismatch would be reported as a wrong checkout."""
    _ls_remote(monkeypatch,
               "aaaa\trefs/tags/151.0.7922.76\n"
               "bbbb\trefs/tags/151.0.7922.76^{}\n")
    assert sync.remote_tag_commit(tmp_path, "151.0.7922.76") == "bbbb"


def test_remote_tag_commit_accepts_a_lightweight_tag(tmp_path: Path, monkeypatch):
    """Chromium's release tags are lightweight: only the unpeeled ref is
    advertised, and it already points at the commit."""
    _ls_remote(monkeypatch, "aaaa\trefs/tags/151.0.7922.76\n")
    assert sync.remote_tag_commit(tmp_path, "151.0.7922.76") == "aaaa"


def test_remote_tag_commit_raises_when_upstream_has_no_such_tag(
        tmp_path: Path, monkeypatch):
    _ls_remote(monkeypatch, "")
    with pytest.raises(RuntimeError, match="does not exist upstream"):
        sync.remote_tag_commit(tmp_path, "151.0.7922.99")


def test_remote_tag_commit_raises_when_origin_is_unreachable(
        tmp_path: Path, monkeypatch):
    _ls_remote(monkeypatch, "", returncode=128)
    with pytest.raises(RuntimeError, match="could not reach origin"):
        sync.remote_tag_commit(tmp_path, "151.0.7922.76")


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
