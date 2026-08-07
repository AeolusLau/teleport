"""Re-export patches/ from a chromium/src tree that already carries the overlay.

Run this after rebase_overlay.py has moved the overlay onto a new upstream tag,
against a tree built with `apply_patches.py --skip-branding` (see below for
why the branding pass must NOT have run). Every file changed in the tree must
fall into exactly one of four classes:

  patch      -> re-exported as patches/<path>.patch
  branding   -> skipped (branding/ is a whole-file copy overlay, not a patch)
  generated  -> skipped (produced at overlay time from CHROMIUM_VERSION /
                TELEPORT_VERSION, or by branding_strings.py)
  injected   -> skipped (planted directly inside the checkout by the
                overlay's own tooling -- bootstrap.py's teleport source
                symlink, fetch_sparkle.py's real Sparkle.framework copy --
                rather than by upstream, a patch, or a rewrite pass; both
                are untracked, so without this class the untracked-file
                scan below would trip the safety valve on every
                bootstrapped checkout, see is_injected_artifact())

Anything else is a hard error. Silently skipping an unclassified change would
drop it from patches/, and the loss would only surface at the next
apply_patches.py run.

A patch target and a branding_strings.py target are NOT mutually exclusive:
e.g. chrome/app/generated_resources.grd carries both a hand-authored patch
and rebrand-pass rewrites. classify_change() checks "patch" first, so such a
path is legitimately classified "patch" -- but that is only correct if the
tree's diff against `tag` is the hand-authored delta ALONE. If the branding
pass has also run, its rewrite gets baked into the re-exported patch; the
next apply_patches.py then rebrands an already-rebranded grd, transform_en_grd
is idempotent so the id remap comes out empty, and every zh xtb for that
target silently stops being re-keyed. export() therefore refuses to run
against a tree where the branding pass has left a mark (see
branding_pass_has_run()) -- the rebrand output is derived and regenerated
deterministically on every apply_patches.py run, so it must never be
captured inside a patch file.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import bootstrap
import branding_strings
import fetch_sparkle
from _lib import chromium_src, repo_root

# Written at overlay time by generate_version.py.
_VERSION_GENERATED = (
    "chrome/VERSION",
    "components/version_info/teleport_engine_version.h",
)

# Paths the overlay's own injection tooling plants directly inside the
# chromium checkout, rather than upstream, a patch, or a rewrite pass writing
# them. Derived from the constants that code itself uses -- bootstrap.SRC_LINK_NAME,
# fetch_sparkle.LINK_RELPATH -- so a rename there can't silently drift this
# out of sync with a second, hand-copied literal.
#
# bootstrap.py's teleport symlink is an exact single path; fetch_sparkle.py's
# Sparkle.framework is copied as REAL files (not a symlink -- a symlink would
# ship a dangling link into the signed .app/dmg, see fetch_sparkle.py), so it
# appears in `git ls-files --others` as one line per file under that
# directory, hence the prefix match. Deliberately NOT a blanket "teleport*"
# rule: matching is anchored to these two specific, code-derived paths so an
# unrelated upstream path that happens to contain "teleport" still trips the
# safety valve.
_INJECTED_EXACT = frozenset({bootstrap.SRC_LINK_NAME})
_INJECTED_PREFIX = fetch_sparkle.LINK_RELPATH + "/"


def is_injected_artifact(path: str) -> bool:
    return path in _INJECTED_EXACT or path.startswith(_INJECTED_PREFIX)


def rebase_in_progress(src: Path) -> bool:
    """True if a `git rebase` is currently underway in `src`. Both marker
    directories git creates for the two rebase backends (merge-based vs. the
    legacy am-based one) persist until the rebase finishes or is aborted, so
    either one's presence means a rebase is mid-flight.

    Canonical home for this predicate (rebase_overlay.py re-exports it rather
    than keeping a second copy -- see the alias there) because export_patches
    needs it independently: during an unresolved conflict, a conflicted
    file's working-tree content still contains literal `<<<<<<< HEAD` /
    `=======` / `>>>>>>>` conflict markers, and `git diff <tag> -- <file>`
    treats those as ordinary text and exits 0. Every classification valve in
    this module stays silent -- the diff is non-empty, the path classifies
    as "patch" or "branding" same as any other change -- so export() would
    happily write a patch file full of conflict markers, and a subsequent
    `git apply` would replay them verbatim into a source file, succeeding
    and staying idempotent on every later run. The corruption then surfaces
    only when that file is actually compiled (or never, for a file macOS
    does not build), far downstream of export_patches.py reporting success.
    """
    return (src / ".git" / "rebase-merge").exists() or (src / ".git" / "rebase-apply").exists()


def patch_paths(root: Path) -> set[str]:
    """Upstream paths covered by patches/, derived from the tree itself."""
    base = Path(root) / "patches"
    return {
        str(p.relative_to(base))[: -len(".patch")]
        for p in base.rglob("*.patch") if p.is_file()
    }


def branding_paths(root: Path) -> set[str]:
    base = Path(root) / "branding"
    if not base.exists():
        return set()
    return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}


def version_generated_paths(root: Path) -> set[str]:
    """Paths written at overlay time by generate_version.py from
    TELEPORT_VERSION / CHROMIUM_VERSION -- generated but NOT part of the
    branding_strings.py rewrite pass. `root` is unused (the set is a fixed
    module constant); it is accepted so callers can treat this the same as
    the other root-scoped path accessors here rather than special-casing it."""
    return set(_VERSION_GENERATED)


def generated_paths(root: Path) -> set[str]:
    return version_generated_paths(root) | branding_strings.touched_paths()


def classify_change(path: str, patches: set[str], branding: set[str],
                    generated: set[str]) -> str:
    if path in patches:
        return "patch"
    if path in branding:
        return "branding"
    if path in generated:
        return "generated"
    if is_injected_artifact(path):
        return "injected"
    return "unknown"


def assert_all_classified(root: Path, changed: list[str]) -> None:
    patches, branding, generated = (patch_paths(root), branding_paths(root),
                                    generated_paths(root))
    unknown = [p for p in changed
               if classify_change(p, patches, branding, generated) == "unknown"]
    if unknown:
        listing = "\n  ".join(sorted(unknown))
        raise RuntimeError(
            "unclassified changes in the chromium tree — refusing to export.\n"
            "Each must become a patch (add patches/<path>.patch), a branding\n"
            "overlay (add branding/<path>), or a generated file (teach\n"
            "export_patches.py about it):\n  " + listing)


def changed_paths(src: Path, tag: str) -> list[str]:
    """Every path that differs from `tag`, tracked or not.

    `git diff --name-only <tag>` alone only sees tracked changes. A file
    newly created while resolving a rebase conflict (e.g. porting an overlay
    change into a file upstream renamed) is untracked until `git add`, so it
    would be invisible to the diff, never classified, and silently dropped --
    exactly the loss this module's safety valve exists to prevent. `git
    ls-files --others --exclude-standard` closes that gap.
    """
    tracked = subprocess.run(
        ["git", "diff", "--name-only", tag],
        cwd=src, capture_output=True, text=True, check=True).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=src, capture_output=True, text=True, check=True).stdout
    paths = {line for line in tracked.splitlines() if line}
    paths.update(line for line in untracked.splitlines() if line)
    return sorted(paths)


def branding_pass_has_run(root: Path, src: Path, tag: str) -> bool:
    """True if branding_strings.main() has rewritten this tree since `tag`.

    Detection: take the paths branding_strings.py rewrites that are NOT also
    a registered patch target -- a patch target's diff is expected
    regardless of branding (a hand-authored patch may itself touch that
    path), so it carries no signal. A path exclusive to branding_strings.py
    can only differ from `tag` if the rebrand pass wrote it.
    """
    candidates = sorted(branding_strings.touched_paths() - patch_paths(root))
    if not candidates:
        return False
    out = subprocess.run(
        ["git", "diff", "--name-only", tag, "--", *candidates],
        cwd=src, capture_output=True, text=True, check=True).stdout
    return bool(out.strip())


def _branding_applied_recovery_message(root: Path, src: Path, tag: str) -> str:
    """An actionable remediation for branding_pass_has_run() == True.

    `apply_patches.py --skip-branding` alone does NOT clear this: branding_strings.py
    transforms grd/grdp/xtb files in place and only ever moves forward (TD-016 in
    docs/tech-debt.md -- an already-rebranded file matches no source pattern, so a
    later pass is a no-op, not a revert). The tree must be restored to the tag
    first; --skip-branding then keeps it that way. Restoring the FULL rebrand-owned
    set (not just the paths that tipped off branding_pass_has_run) is required even
    for patch/branding overlap targets: if the branding pass ran, it rewrote every
    _GRD_TARGETS entry unconditionally, including ones that also carry a
    hand-authored patch -- and restoring them to the tag is safe because the next
    `apply_patches.py` re-applies their patch (patches apply before branding runs).
    """
    touched = sorted(branding_strings.touched_paths())
    restore_cmd = "  git -C {} checkout {} -- \\\n      {}".format(
        src, tag, " \\\n      ".join(touched))
    return (
        "the branding pass has been applied to this tree -- export_patches "
        "requires a branding-free tree, and this cannot be cleared by "
        "--skip-branding alone: branding_strings.py transforms grd/grdp/xtb "
        "files in place and only ever moves forward (an already-rebranded file "
        "matches no source pattern, so re-running it is a no-op, not a revert -- "
        "see TD-016 in docs/tech-debt.md). To recover:\n"
        "  1. restore the rebrand-owned files to the pre-overlay tag "
        f"({len(touched)} paths):\n"
        f"{restore_cmd}\n"
        f"     (or discard this tree entirely and re-check it out fresh from {tag})\n"
        "  2. rebuild the overlay without the rebrand pass:\n"
        f"     uv run python scripts/apply_patches.py --root {root} --skip-branding\n"
        "  3. re-run export_patches.py")


def _rebase_in_progress_message(src: Path) -> str:
    return (
        f"{src} has an unresolved `git rebase` in progress (a rebase-merge/"
        f"rebase-apply marker is present) -- refusing to export. A conflicted "
        f"file's working-tree content still contains <<<<<<< HEAD / ======= / "
        f">>>>>>> conflict markers; `git diff` treats those as ordinary text "
        f"and `git apply` would replay them verbatim, so exporting now would "
        f"silently write a patch full of conflict markers that then applies "
        f"cleanly and idempotently on every future run. Finish the rebase "
        f"first (resolve conflicts, `git add <file>`, then `git -C {src} "
        f"rebase --continue`) or abandon it (`git -C {src} rebase --abort`), "
        f"then re-run export_patches.py.")


def export(root: Path, src: Path, tag: str) -> list[str]:
    """Rewrite patches/ from the tree's diff against `tag`. Returns the paths
    whose patch file changed."""
    if rebase_in_progress(src):
        raise RuntimeError(_rebase_in_progress_message(src))
    if branding_pass_has_run(root, src, tag):
        raise RuntimeError(_branding_applied_recovery_message(root, src, tag))
    assert_all_classified(root, changed_paths(src, tag))
    rewritten = []
    for rel in sorted(patch_paths(root)):
        diff = subprocess.run(
            ["git", "diff", tag, "--", rel],
            cwd=src, capture_output=True, text=True, check=True).stdout
        if not diff.strip():
            raise RuntimeError(
                f"patch target has no diff against {tag}: {rel}\n"
                "The patch would export empty. Either the change was lost in "
                "the rebase, or the patch is obsolete and should be deleted.")
        dest = Path(root) / "patches" / f"{rel}.patch"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_text() != diff:
            dest.write_text(diff)
            rewritten.append(rel)
    return rewritten


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-export patches/ from chromium/src")
    parser.add_argument("--tag", required=True,
                        help="upstream tag the overlay now sits on, e.g. 151.0.7922.76")
    parser.add_argument("--root", type=Path, default=repo_root())
    args = parser.parse_args(argv)

    src = chromium_src(args.root)
    rewritten = export(args.root, src, args.tag)
    print(f"re-exported {len(rewritten)} patch file(s) against {args.tag}")
    for rel in rewritten:
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
