import os
import subprocess
from pathlib import Path

import pytest

import _lib
import bootstrap
import export_patches as ep
import fetch_sparkle


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "browser").mkdir(parents=True)
    (repo / "patches" / "chrome" / "browser" / "foo.cc.patch").write_text("x")
    (repo / "patches" / "net").mkdir(parents=True)
    (repo / "patches" / "net" / "bar.h.patch").write_text("x")
    (repo / "branding" / "chrome" / "app" / "theme").mkdir(parents=True)
    (repo / "branding" / "chrome" / "app" / "theme" / "logo.png").write_bytes(b"\x89PNG")
    return repo


def test_patch_paths_strips_prefix_and_suffix(tmp_path: Path):
    repo = _make_repo(tmp_path)
    assert ep.patch_paths(repo) == {"chrome/browser/foo.cc", "net/bar.h"}


def test_branding_paths_lists_files_only(tmp_path: Path):
    repo = _make_repo(tmp_path)
    assert ep.branding_paths(repo) == {"chrome/app/theme/logo.png"}


def test_classify_patch(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/browser/foo.cc", p, b, g) == "patch"


def test_classify_branding(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/app/theme/logo.png", p, b, g) == "branding"


def test_classify_generated(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/VERSION", p, b, g) == "generated"


def test_classify_unknown_is_the_safety_valve(tmp_path: Path):
    repo = _make_repo(tmp_path)
    p, b, g = ep.patch_paths(repo), ep.branding_paths(repo), {"chrome/VERSION"}
    assert ep.classify_change("chrome/browser/surprise.cc", p, b, g) == "unknown"


def test_classify_injected_teleport_symlink():
    """bootstrap.py's <chromium>/src/teleport symlink is untracked in every
    bootstrapped checkout; it must classify as "injected", not "unknown"."""
    assert ep.classify_change(bootstrap.SRC_LINK_NAME, set(), set(), set()) == "injected"


def test_classify_injected_sparkle_framework_file():
    """fetch_sparkle.py copies real files (not a symlink) into
    third_party/teleport_sparkle/, so each shows up individually in `git
    ls-files --others` -- any path under that subtree must classify as
    "injected"."""
    path = fetch_sparkle.LINK_RELPATH + "/Sparkle.framework/Versions/A/Sparkle"
    assert ep.classify_change(path, set(), set(), set()) == "injected"


def test_rebase_in_progress_false_on_a_plain_checkout(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert ep.rebase_in_progress(tmp_path) is False


def test_rebase_in_progress_true_with_rebase_merge_marker(tmp_path: Path):
    (tmp_path / ".git" / "rebase-merge").mkdir(parents=True)
    assert ep.rebase_in_progress(tmp_path) is True


def test_rebase_in_progress_true_with_rebase_apply_marker(tmp_path: Path):
    """The legacy am-based backend uses a different marker directory; both
    must be recognized, not just the merge-based one."""
    (tmp_path / ".git" / "rebase-apply").mkdir(parents=True)
    assert ep.rebase_in_progress(tmp_path) is True


def test_classify_injected_is_anchored_not_a_blanket_teleport_prefix():
    """Injected-artifact recognition is anchored to the exact names
    bootstrap.py / fetch_sparkle.py use, not a wildcard on "teleport*" --
    an unrelated path that merely contains that substring must still trip
    the safety valve."""
    assert ep.classify_change("chrome/teleport_unrelated.cc", set(), set(), set()) == "unknown"
    assert ep.classify_change(
        "third_party/teleport_sparkle_other/file", set(), set(), set()) == "unknown"


def test_generated_paths_includes_version_and_engine_header(tmp_path: Path):
    g = ep.generated_paths(tmp_path)
    assert "chrome/VERSION" in g
    assert "components/version_info/teleport_engine_version.h" in g


def test_version_generated_paths_is_exactly_the_version_generated_set(tmp_path: Path):
    """rebase_overlay.py needs the version-generated set WITHOUT
    branding_strings' rewrite targets mixed in, to stage the overlay commit
    precisely. This pins that version_generated_paths() is exactly
    {chrome/VERSION, the engine header} -- neither more (no branding leak)
    nor less."""
    assert ep.version_generated_paths(tmp_path) == {
        "chrome/VERSION",
        "components/version_info/teleport_engine_version.h",
    }


def test_version_generated_paths_excludes_branding_strings_targets(tmp_path: Path):
    assert "chrome/app/chromium_strings.grd" not in ep.version_generated_paths(tmp_path)


def test_generated_paths_includes_branding_strings_targets(tmp_path: Path):
    g = ep.generated_paths(tmp_path)
    assert "chrome/app/chromium_strings.grd" in g


def test_assert_all_classified_raises_on_unknown(tmp_path: Path):
    repo = _make_repo(tmp_path)
    with pytest.raises(RuntimeError, match="unclassified"):
        ep.assert_all_classified(repo, ["chrome/browser/surprise.cc"])


def test_assert_all_classified_passes_on_known(tmp_path: Path):
    repo = _make_repo(tmp_path)
    ep.assert_all_classified(repo, ["chrome/browser/foo.cc",
                                    "chrome/app/theme/logo.png",
                                    "chrome/VERSION"])


# ---------------------------------------------------------------------------
# export() / changed_paths() / branding_pass_has_run() -- real git fixtures.
#
# These exercise the module against an actual chromium/src-shaped git repo
# rather than only its pure-Python helpers: the git diff invocation, the
# empty-diff guard, the untracked-file blind spot, and the branding-applied
# refusal are all only meaningful against real git state.
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _make_src_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """A one-commit git repo at tmp_path/src containing `files`, tagged
    "baseline" at that commit -- stands in for a chromium/src checkout that
    already carries the overlay, about to be diffed against the pre-overlay
    tag."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "t@t")
    _git(src, "config", "user.name", "t")
    for rel, content in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "baseline")
    _git(src, "tag", "baseline")
    return src


def _no_branding_targets(monkeypatch):
    """Most fixtures below don't exercise branding detection at all; pinning
    touched_paths() to empty keeps them independent of the real _GRD_TARGETS
    (which changes across milestone upgrades) and avoids a real, 61-pathspec
    git diff call on every one of them."""
    monkeypatch.setattr(ep.branding_strings, "touched_paths", set)


def test_changed_paths_lists_tracked_modification(tmp_path: Path):
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / "chrome/browser/foo.cc").write_text("orig\nmodified\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "modify")
    assert ep.changed_paths(src, "baseline") == ["chrome/browser/foo.cc"]


def test_changed_paths_includes_untracked_files(tmp_path: Path):
    """git diff --name-only alone is blind to files that were never `git
    add`ed. A file created while porting an overlay change into a path
    upstream renamed would be exactly such a file -- if changed_paths()
    missed it, it would never be classified and never exported, silently."""
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / "chrome/browser/new_file.cc").write_text("new content\n")
    assert ep.changed_paths(src, "baseline") == ["chrome/browser/new_file.cc"]


def test_changed_paths_combines_tracked_and_untracked(tmp_path: Path):
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / "chrome/browser/foo.cc").write_text("orig\nmodified\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "modify")
    (src / "chrome/browser/new_file.cc").write_text("new content\n")
    assert ep.changed_paths(src, "baseline") == [
        "chrome/browser/foo.cc", "chrome/browser/new_file.cc"]


def test_export_rewrites_patch_with_real_diff_content(tmp_path: Path, monkeypatch):
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "browser").mkdir(parents=True)
    (repo / "patches" / "chrome" / "browser" / "foo.cc.patch").write_text("stale placeholder")
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / "chrome/browser/foo.cc").write_text("orig\noverlay change\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "overlay")

    rewritten = ep.export(repo, src, "baseline")
    assert rewritten == ["chrome/browser/foo.cc"]
    patch_text = (repo / "patches" / "chrome" / "browser" / "foo.cc.patch").read_text()
    assert "diff --git" in patch_text
    assert "overlay change" in patch_text


def test_export_is_idempotent_when_patch_content_unchanged(tmp_path: Path, monkeypatch):
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "browser").mkdir(parents=True)
    (repo / "patches" / "chrome" / "browser" / "foo.cc.patch").write_text("stale")
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / "chrome/browser/foo.cc").write_text("orig\nchange\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "overlay")

    assert ep.export(repo, src, "baseline") == ["chrome/browser/foo.cc"]
    # Re-running against the same tree rewrites nothing -- the patch file
    # already holds the current diff.
    assert ep.export(repo, src, "baseline") == []


def test_export_raises_on_empty_diff_patch_target(tmp_path: Path, monkeypatch):
    """A registered patch target with no diff against the tag means either
    the change was lost in the rebase or the patch is obsolete -- either way,
    exporting it would silently produce an empty patch file. Must be a hard
    error, not a no-op."""
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "browser").mkdir(parents=True)
    (repo / "patches" / "chrome" / "browser" / "stale.cc.patch").write_text("stale")
    src = _make_src_repo(tmp_path, {"chrome/browser/stale.cc": "unchanged\n"})
    # No commits after baseline -> the patch target has nothing to export.

    with pytest.raises(RuntimeError, match="no diff"):
        ep.export(repo, src, "baseline")


def test_export_raises_when_untracked_file_is_unclassified(tmp_path: Path, monkeypatch):
    """The untracked-file fix to changed_paths() must actually reach the
    safety valve: an untracked, unregistered file must abort export(), not
    be silently skipped."""
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / "chrome/browser/surprise.cc").write_text("new file, never staged\n")

    with pytest.raises(RuntimeError, match="unclassified"):
        ep.export(repo, src, "baseline")


def test_branding_pass_has_run_true_when_a_branding_only_path_changed(
        tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)  # no patch registered for the grd
    src = _make_src_repo(tmp_path, {"chrome/app/chromium_strings.grd": "Chromium\n"})
    monkeypatch.setattr(ep.branding_strings, "touched_paths",
                        lambda: {"chrome/app/chromium_strings.grd"})
    (src / "chrome/app/chromium_strings.grd").write_text("Teleport\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "branding ran")

    assert ep.branding_pass_has_run(repo, src, "baseline") is True


def test_branding_pass_has_run_false_on_a_branding_free_tree(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/app/chromium_strings.grd": "Chromium\n"})
    monkeypatch.setattr(ep.branding_strings, "touched_paths",
                        lambda: {"chrome/app/chromium_strings.grd"})
    # No commits after baseline -> the branding-exclusive candidate is untouched.

    assert ep.branding_pass_has_run(repo, src, "baseline") is False


# --- Regression coverage for the in-progress-rebase defect (F9) -----------
#
# During an unresolved rebase conflict, a conflicted file's working-tree
# content still contains literal <<<<<<< HEAD / ======= / >>>>>>> conflict
# markers. `git diff <tag> -- <file>` treats those as ordinary text and
# exits 0, so every classification valve in this module stays silent and
# export() would happily bake the conflict markers into a patch file that
# then applies cleanly (and idempotently) on every future apply_patches.py
# run. The guard must fire before any of that -- reaching classification at
# all is already too late.

def test_export_refuses_when_a_rebase_is_in_progress(tmp_path: Path, monkeypatch):
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / ".git" / "rebase-merge").mkdir()

    with pytest.raises(RuntimeError, match="rebase"):
        ep.export(repo, src, "baseline")


def test_export_refuses_when_a_rebase_is_in_progress_even_with_conflict_markers_present(
        tmp_path: Path, monkeypatch):
    """The exact failure shape the reviewer verified empirically: a
    conflicted file with literal conflict markers, diffing non-empty and
    clean against every other valve. Without the guard this would export
    successfully; with it, export() must refuse before ever computing a
    diff."""
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "browser").mkdir(parents=True)
    (repo / "patches" / "chrome" / "browser" / "foo.cc.patch").write_text("stale")
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    (src / "chrome/browser/foo.cc").write_text(
        "orig\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> onto-tag\n")
    (src / ".git" / "rebase-merge").mkdir()

    with pytest.raises(RuntimeError, match="rebase"):
        ep.export(repo, src, "baseline")


def test_export_refuses_when_branding_pass_has_run(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/app/chromium_strings.grd": "Chromium\n"})
    monkeypatch.setattr(ep.branding_strings, "touched_paths",
                        lambda: {"chrome/app/chromium_strings.grd"})
    (src / "chrome/app/chromium_strings.grd").write_text("Teleport\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "branding ran")

    with pytest.raises(RuntimeError, match="branding pass"):
        ep.export(repo, src, "baseline")


# --- Regression coverage for the patch/generated overlap defect ------------
#
# chrome/app/generated_resources.grd (a real M151 example) is BOTH a
# registered patch target AND a branding_strings.py target. The two sets are
# allowed to overlap -- classify_change() checks "patch" first on purpose --
# but that is only correct when the tree is branding-free, because otherwise
# the re-exported patch would bake in the rebrand pass's rewrite alongside
# the hand-authored change. These two tests pin the required behavior on
# both sides of that line, not the (false) invariant that the sets are
# disjoint.

def test_overlap_target_exports_as_patch_on_a_branding_free_tree(
        tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "app").mkdir(parents=True)
    (repo / "patches" / "chrome" / "app" / "generated_resources.grd.patch").write_text("stale")
    src = _make_src_repo(tmp_path, {"chrome/app/generated_resources.grd": "line1\n"})
    monkeypatch.setattr(ep.branding_strings, "touched_paths",
                        lambda: {"chrome/app/generated_resources.grd"})
    (src / "chrome/app/generated_resources.grd").write_text("line1\nhand-authored change\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "hand patch only, branding did not run")

    rewritten = ep.export(repo, src, "baseline")
    assert rewritten == ["chrome/app/generated_resources.grd"]
    patch_text = (repo / "patches" / "chrome" / "app"
                  / "generated_resources.grd.patch").read_text()
    assert "hand-authored change" in patch_text


def test_export_refuses_even_when_an_overlap_target_also_exists(
        tmp_path: Path, monkeypatch):
    """Overlap on one path must not mask branding having run on a different,
    branding-exclusive path -- this is the exact shape of the defect the
    review caught: a hand-authored patch target that happens to also be a
    branding_strings.py target sailed through classify_change() as "patch"
    while an un-flagged sibling branding-only file carried the rebrand
    pass's output into what would have been an unrelated silent data loss."""
    repo = tmp_path / "repo"
    (repo / "patches" / "chrome" / "app").mkdir(parents=True)
    (repo / "patches" / "chrome" / "app" / "generated_resources.grd.patch").write_text("stale")
    src = _make_src_repo(tmp_path, {
        "chrome/app/generated_resources.grd": "line1\n",
        "chrome/app/chromium_strings.grd": "Chromium\n",
    })
    monkeypatch.setattr(
        ep.branding_strings, "touched_paths",
        lambda: {"chrome/app/generated_resources.grd", "chrome/app/chromium_strings.grd"})

    (src / "chrome/app/generated_resources.grd").write_text("line1\nhand patch\n")
    (src / "chrome/app/chromium_strings.grd").write_text("Teleport\n")  # branding ran
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "overlay + branding")

    with pytest.raises(RuntimeError, match="branding pass"):
        ep.export(repo, src, "baseline")


# --- Regression coverage for the injected-artifact defect -------------------
#
# bootstrap.py plants an untracked symlink at <chromium>/src/teleport, and
# fetch_sparkle.py plants an untracked real-file copy under
# third_party/teleport_sparkle/ whenever the release flow has run. Neither is
# ignored by chromium's own .gitignore. Before is_injected_artifact() existed,
# changed_paths()'s untracked-file scan (added earlier this round to close the
# silent-loss gap) surfaced these on every bootstrapped checkout, and
# classify_change() called them "unknown" -- so export() refused
# unconditionally, and the branding-applied fix above was unreachable in
# practice. These tests reproduce that shape directly against export(),
# not just classify_change() in isolation.

def test_export_ignores_the_bootstrap_teleport_symlink(tmp_path: Path, monkeypatch):
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    link_target = tmp_path / "overlay_src"
    link_target.mkdir()
    # create_dir_link, not os.symlink: this is the artifact bootstrap.py
    # actually plants, and on Windows that is a junction rather than a symlink.
    _lib.create_dir_link(src / bootstrap.SRC_LINK_NAME, link_target)

    # Must not raise "unclassified changes" -- the symlink is a recognized
    # injected artifact, and there is nothing else to export.
    assert ep.export(repo, src, "baseline") == []


def test_export_ignores_the_fetch_sparkle_framework_copy(tmp_path: Path, monkeypatch):
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    fw_dir = src / fetch_sparkle.LINK_RELPATH / "Sparkle.framework" / "Versions" / "A"
    fw_dir.mkdir(parents=True)
    (fw_dir / "Sparkle").write_bytes(b"fake-binary")
    (fw_dir / "Resources.txt").write_text("fake resource\n")

    # Multiple files under the subtree, each a separate untracked-file scan
    # hit -- all must be recognized, not just the directory as a whole.
    assert ep.export(repo, src, "baseline") == []


def test_export_still_catches_an_unrelated_untracked_symlink(tmp_path: Path, monkeypatch):
    """The injected-artifact allowance is specific, not "symlinks are always
    fine": an untracked symlink under any other name is still an
    unclassified change and must still trip the safety valve."""
    _no_branding_targets(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/browser/foo.cc": "orig\n"})
    _lib.create_dir_link(src / "surprise_link", tmp_path)

    with pytest.raises(RuntimeError, match="unclassified"):
        ep.export(repo, src, "baseline")


# --- Regression coverage for the non-actionable refusal message defect -----

def test_branding_applied_refusal_gives_a_literal_restore_command(
        tmp_path: Path, monkeypatch):
    """`apply_patches.py --skip-branding` cannot clear an already-branded
    tree by itself (branding_strings.py only ever moves forward), so the
    refusal must not merely point at --skip-branding -- it must give a
    literal, copy-pasteable command to restore the rebrand-owned files from
    the tag first."""
    repo = tmp_path / "repo"
    (repo / "patches").mkdir(parents=True)
    src = _make_src_repo(tmp_path, {"chrome/app/chromium_strings.grd": "Chromium\n"})
    monkeypatch.setattr(ep.branding_strings, "touched_paths",
                        lambda: {"chrome/app/chromium_strings.grd"})
    (src / "chrome/app/chromium_strings.grd").write_text("Teleport\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "branding ran")

    with pytest.raises(RuntimeError) as excinfo:
        ep.export(repo, src, "baseline")
    message = str(excinfo.value)
    # A literal git command naming the real src, the real tag, and the file
    # to restore -- not a placeholder or a description of what to do.
    assert f"git -C {src} checkout baseline --" in message
    assert "chrome/app/chromium_strings.grd" in message
    assert "--skip-branding" in message
