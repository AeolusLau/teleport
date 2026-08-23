"""Unit coverage for rebase_overlay.py's pure, operator-facing message
helpers. The orchestration in main() itself is deliberately not unit tested
(per the task brief: it depends on real git state and the valuable logic is
already covered by export_patches' classification), but every helper that
formats an error message is pure string composition and cheap to pin --
these are exactly the strings an operator reads at the moment a milestone
upgrade is going sideways, so they are also the part most likely to rot
silently if left untested.
"""
import os
from pathlib import Path

import _lib

import bootstrap
import fetch_sparkle
import rebase_overlay as ro


def test_format_git_failure_surfaces_stderr_not_just_the_exit_code():
    """subprocess.CalledProcessError's default str() only reports the exit
    status; the diagnosable git message lives in stderr and must appear in
    the formatted text, not just the numeric code."""
    msg = ro._format_git_failure(
        ("fetch", "origin", "tag", "bogus-tag"), 128,
        "fatal: couldn't find remote ref refs/tags/bogus-tag\n")
    assert "fatal: couldn't find remote ref refs/tags/bogus-tag" in msg
    assert "128" in msg
    assert "git fetch origin tag bogus-tag" in msg


def test_format_git_failure_handles_empty_stderr():
    msg = ro._format_git_failure(("status",), 1, "")
    assert "1" in msg
    assert "nothing to stderr" in msg.lower()


def test_dirty_tree_message_ordinary_case_mentions_status():
    msg = ro._dirty_tree_message(Path("/tmp/src"), mid_rebase=False)
    assert "local changes" in msg
    assert "rebase" not in msg.lower()


def test_dirty_tree_message_mid_rebase_case_mentions_abort_and_continue():
    msg = ro._dirty_tree_message(Path("/tmp/src"), mid_rebase=True)
    assert "rebase --abort" in msg
    assert "rebase --continue" in msg
    assert "prior run" in msg


def test_rebase_in_progress_false_on_a_plain_checkout(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert ro._rebase_in_progress(tmp_path) is False


def test_rebase_in_progress_true_with_rebase_merge_marker(tmp_path: Path):
    (tmp_path / ".git" / "rebase-merge").mkdir(parents=True)
    assert ro._rebase_in_progress(tmp_path) is True


def test_rebase_in_progress_true_with_rebase_apply_marker(tmp_path: Path):
    """The legacy am-based backend uses a different marker directory; both
    must be recognized, not just the merge-based one."""
    (tmp_path / ".git" / "rebase-apply").mkdir(parents=True)
    assert ro._rebase_in_progress(tmp_path) is True


def _link_overlay(tmp_path: Path, src: Path) -> None:
    """Plant the overlay link exactly as bootstrap.py does -- a symlink on POSIX,
    a directory junction on Windows. os.symlink() directly would fail there with
    WinError 1314 for an unelevated user without Developer Mode, which is the
    normal state of a developer machine and has nothing to do with what these
    tests are checking."""
    target = tmp_path / "overlay_src"
    target.mkdir(exist_ok=True)
    _lib.create_dir_link(src / bootstrap.SRC_LINK_NAME, target)


def test_apply_patches_failed_message_gives_a_literal_recovery_command():
    # The path is interpolated natively -- backslashes on Windows -- because the
    # message exists to be copy-pasted into the operator's shell, so it must
    # spell the path the way THAT shell expects, not the way POSIX does.
    src = Path("/chromium/src")
    msg = ro._apply_patches_failed_message(src, "148.0.7778.180", 1)
    assert f"git -C {src} reset --hard 148.0.7778.180" in msg
    assert f"git -C {src} clean -fd" in msg
    assert ro.WORK_BRANCH in msg
    assert "exit 1" in msg


def test_conflict_message_lists_the_conflicting_files():
    msg = ro._conflict_message(Path("/chromium/src"), "chrome/browser/foo.cc\n")
    assert "chrome/browser/foo.cc" in msg
    assert "rebase --continue" in msg
    assert "rebase --abort" in msg
    assert ro.WORK_BRANCH in msg


def test_conflict_message_falls_back_when_conflict_listing_is_empty():
    msg = ro._conflict_message(Path("/chromium/src"), "")
    assert "see git status" in msg


# ---------------------------------------------------------------------------
# _status_line_is_injected_artifact() / _is_dirty() -- the dirty-tree
# precheck's injected-artifact exception.
#
# bootstrap.py plants an untracked `teleport` symlink in every bootstrapped
# checkout; a naive `git status --porcelain` truthiness check therefore
# refuses to run on every correctly-prepared checkout, always -- this was
# caught not by an isolated review of this file, but by Task 6 actually
# running the precheck against the real M151 checkout. Real coverage here,
# not just the narrow-parse pin below, is warranted precisely because it is
# now proven reachable and blocking.
# ---------------------------------------------------------------------------

def test_status_line_is_injected_artifact_matches_the_teleport_symlink():
    assert ro._status_line_is_injected_artifact(f"?? {bootstrap.SRC_LINK_NAME}") is True


def test_status_line_is_injected_artifact_matches_sparkle_subtree():
    line = f"?? {fetch_sparkle.LINK_RELPATH}/Sparkle.framework/Versions/A/Sparkle"
    assert ro._status_line_is_injected_artifact(line) is True


def test_status_line_is_injected_artifact_false_for_a_tracked_modification():
    """A tracked change to a file that happens to be named "teleport" uses
    status code " M", not "??" -- the narrow parse only special-cases the
    untracked code, so this must not be misread as the injected symlink."""
    assert ro._status_line_is_injected_artifact(" M teleport") is False


def test_status_line_is_injected_artifact_false_for_an_unrelated_untracked_file():
    assert ro._status_line_is_injected_artifact("?? surprise.txt") is False


def test_status_line_is_injected_artifact_false_for_a_conflict_marker():
    """Mid-rebase conflict lines use "UU", not "??" -- must still count as
    dirty so the rebase-in-progress case is unaffected by this change."""
    assert ro._status_line_is_injected_artifact("UU chrome/browser/foo.cc") is False


def test_is_dirty_false_for_empty_status():
    assert ro._is_dirty("") is False


def test_is_dirty_false_for_only_injected_artifact_lines():
    status = (f"?? {bootstrap.SRC_LINK_NAME}\n"
              f"?? {fetch_sparkle.LINK_RELPATH}/Sparkle.framework/x\n")
    assert ro._is_dirty(status) is False


def test_is_dirty_true_when_one_line_is_not_injected():
    """An injected-artifact line must not mask real dirtiness elsewhere in
    the same status output."""
    status = f"?? {bootstrap.SRC_LINK_NAME}\n M chrome/browser/foo.cc\n"
    assert ro._is_dirty(status) is True


# --- Same three scenarios, driven through real git ---------------------
#
# The unit tests above pin the parsing logic against hand-built porcelain
# strings. These drive an actual git repo (a real symlink, a real Sparkle-
# shaped untracked subtree, a real tracked modification) so the test also
# covers git's own formatting choices -- in particular whether a wholly
# untracked directory collapses to one porcelain line ("normal" mode) or is
# enumerated file-by-file, which the prefix match in is_injected_artifact()
# must tolerate either way.

def _make_bootstrapped_repo(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    ro.git(src, "init", "-q")
    ro.git(src, "config", "user.email", "t@t")
    ro.git(src, "config", "user.name", "t")
    (src / "chrome" / "browser").mkdir(parents=True)
    (src / "chrome" / "browser" / "foo.cc").write_text("content\n")
    ro.git(src, "add", "-A")
    ro.git(src, "commit", "-qm", "base")
    return src


def test_precheck_passes_on_a_freshly_bootstrapped_checkout(tmp_path: Path):
    """The exact scenario Task 6 hit: only the injection symlink is
    untracked, nothing else has changed -- the precheck must let this
    through."""
    src = _make_bootstrapped_repo(tmp_path)
    link_target = tmp_path / "overlay_src"
    link_target.mkdir()
    _lib.create_dir_link(src / bootstrap.SRC_LINK_NAME, link_target)

    status = ro.git(src, "status", "--porcelain").stdout
    assert ro._is_dirty(status) is False


def test_precheck_passes_when_only_the_sparkle_copy_is_untracked(tmp_path: Path):
    """After the release flow has run, third_party/teleport_sparkle/ holds
    real (non-symlink) files copied in by fetch_sparkle.py -- also must not
    block, and must be tolerated whether git collapses the wholly-untracked
    directory into one porcelain line or lists each file.

    The fixture commits a TRACKED sibling under third_party/ before adding
    the untracked Sparkle copy -- this matters, and was caught by this test
    failing without it: git's "normal" untracked-files mode collapses a
    wholly-untracked directory to its outermost untracked ANCESTOR. With no
    tracked sibling, third_party/ itself is wholly untracked and collapses
    all the way up to a single "?? third_party/" line, which
    is_injected_artifact()'s "third_party/teleport_sparkle/" prefix match
    correctly does NOT match (it isn't the injected path) -- so the
    precheck would incorrectly refuse. The real checkout never hits this:
    third_party/ holds hundreds of thousands of tracked files (verified
    against the real M148 checkout), so only third_party/teleport_sparkle/
    itself is wholly untracked and collapse stops exactly there. Mirroring
    that shape here is what makes this fixture representative rather than
    accidentally testing a directory layout that cannot occur in practice.
    """
    src = _make_bootstrapped_repo(tmp_path)
    (src / "third_party" / "some_other_lib").mkdir(parents=True)
    (src / "third_party" / "some_other_lib" / "README").write_text("tracked sibling\n")
    ro.git(src, "add", "-A")
    ro.git(src, "commit", "-qm", "tracked third_party sibling")

    fw_dir = src / fetch_sparkle.LINK_RELPATH / "Sparkle.framework" / "Versions" / "A"
    fw_dir.mkdir(parents=True)
    (fw_dir / "Sparkle").write_bytes(b"fake-binary")
    (fw_dir / "Resources.txt").write_text("fake resource\n")

    status = ro.git(src, "status", "--porcelain").stdout
    assert ro._is_dirty(status) is False


def test_precheck_refuses_on_a_genuinely_untracked_unrelated_file(tmp_path: Path):
    src = _make_bootstrapped_repo(tmp_path)
    _link_overlay(tmp_path, src)
    (src / "surprise.txt").write_text("new, never staged\n")

    status = ro.git(src, "status", "--porcelain").stdout
    assert ro._is_dirty(status) is True


def test_precheck_refuses_on_a_genuinely_modified_tracked_file(tmp_path: Path):
    src = _make_bootstrapped_repo(tmp_path)
    _link_overlay(tmp_path, src)
    (src / "chrome" / "browser" / "foo.cc").write_text("modified\n")

    status = ro.git(src, "status", "--porcelain").stdout
    assert ro._is_dirty(status) is True
