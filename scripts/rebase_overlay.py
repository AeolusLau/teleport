"""Move the overlay from one upstream baseline to another via git's three-way merge.

The overlay normally lives as uncommitted working-tree changes, which git
cannot merge. This commits it on top of the OLD baseline, then rebases that
commit onto the NEW one: git then does a per-file three-way merge with
base = old upstream file, ours = new upstream file, theirs = our modified file.
Pure context drift merges automatically; only genuine overlaps conflict, and
they conflict inside real source with full context rather than as .rej files.

rebase (not merge) is deliberate: `git merge <new tag>` would use the point
where the old release branch forked from trunk as the merge base, dragging the
old branch's own fixes into the merge. `rebase --onto` pins the base to the old
tag exactly, so only "our changes" x "old->new upstream delta" participate.

Every early-exit below says what state chromium/src was left in and the exact
command to recover: this script is run precisely when a milestone upgrade is
going sideways, and its error output is the whole interface at the moment an
operator is least able to reverse-engineer the tree from first principles.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import export_patches
from _lib import chromium_src, repo_root

WORK_BRANCH = "teleport/overlay-rebase"


def _format_git_failure(args: tuple[str, ...], returncode: int, stderr: str) -> str:
    """A readable failure message for a failed git invocation.

    subprocess.CalledProcessError's default str() is only "Command '...'
    returned non-zero exit status N" -- the diagnosable text (e.g. "fatal:
    couldn't find remote ref refs/tags/<tag>" for a typo'd tag) lives in
    .stderr and is otherwise silently dropped, leaving an opaque traceback
    as the operator's only signal. Pure formatting so it can be pinned by a
    test without invoking git at all.
    """
    printable = " ".join(("git",) + args)
    detail = stderr.strip() or "(git printed nothing to stderr)"
    return f"`{printable}` failed (exit {returncode}):\n{detail}"


def git(src: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=src, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise RuntimeError(_format_git_failure(args, result.returncode, result.stderr))
    return result


def ensure_tag(src: Path, tag: str) -> None:
    """The old baseline's objects must be reachable or there is no merge base.
    A checkout created with `gclient sync --no-history` will not have them."""
    if git(src, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode == 0:
        return
    print(f"fetching tag {tag} (needed as the three-way merge base) ...")
    git(src, "fetch", "origin", "tag", tag)


def tracked_overlay_paths(root: Path) -> list[str]:
    """Exactly the paths the overlay may touch. `git add -A` is unusable here:
    a synced tree carries DEPS checkouts and build products we must not commit.

    Deliberately EXCLUDES branding_strings' ~58 rewrite targets: the overlay is
    built with --skip-branding (see below), so those files are unmodified, and
    committing rebranded content would bake it into the exported patches.
    Also excludes injected artifacts (the teleport symlink, the Sparkle copy) —
    they are the injection mechanism, not overlay content."""
    return sorted(export_patches.patch_paths(root)
                  | export_patches.branding_paths(root)
                  | export_patches.version_generated_paths(root))


def _status_line_is_injected_artifact(line: str) -> bool:
    """True if a single `git status --porcelain` line is entirely accounted
    for by an overlay-injected artifact -- the untracked `teleport` symlink
    bootstrap.py plants, or the untracked Sparkle.framework copy
    fetch_sparkle.py plants under third_party/teleport_sparkle/.

    Narrow, deliberately incomplete porcelain parse: only the "??"
    (untracked) status code is handled, taking the path as everything after
    the fixed 3-character "XY " prefix. That is enough here because both
    injected artifacts are ALWAYS untracked -- bootstrap.py and
    fetch_sparkle.py plant them directly in the checkout, never `git add`
    them -- so they can only ever appear under "??", never under a
    tracked-change status code (M/A/D/R/C/U...). That in turn means this
    never has to parse the " -> " rename-arrow syntax (renames only apply
    to tracked changes) or undo git's C-style quoting of paths with unusual
    bytes (both injected paths are plain ASCII, so they are never quoted).
    A line this can't positively clear -- wrong status code, quoted, a
    rename, anything else -- simply returns False, and _is_dirty() below
    correctly treats it as real dirtiness. The narrow parse can only ever
    produce false "dirty" verdicts, never false "clean" ones, so it is
    safe by construction rather than by the cases anticipated today.
    """
    if not line.startswith("?? "):
        return False
    path = line[3:]
    return export_patches.is_injected_artifact(path)


def _is_dirty(status: str) -> bool:
    """True if `git status --porcelain` output contains anything beyond the
    overlay's own injected artifacts (a freshly bootstrapped checkout is
    never fully clean: bootstrap.py's `teleport` symlink is untracked by
    design). Reuses is_injected_artifact() -- export_patches.py's single
    source of truth for "things the overlay's own tooling plants in the
    checkout" -- rather than growing a second, driftable notion of it here.
    """
    return any(not _status_line_is_injected_artifact(line)
               for line in status.splitlines() if line)


# Re-exported from export_patches: BOTH scripts must refuse to operate on a
# tree with an unresolved rebase (export_patches' own reason is documented on
# the function itself -- conflict markers pass every classification valve as
# ordinary text). export_patches cannot import this back from here --
# rebase_overlay already imports export_patches, and the reverse would be
# circular -- so the canonical implementation lives there and this is an
# alias rather than a second, driftable copy.
_rebase_in_progress = export_patches.rebase_in_progress


def _dirty_tree_message(src: Path, mid_rebase: bool) -> str:
    """Diagnose a non-clean chromium/src before starting. `mid_rebase` is
    passed in rather than computed here so the wording itself is pure and
    independently testable. A rebase already in progress is very likely a
    prior run of this script that stopped on a conflict and was never
    resolved -- that needs `rebase --abort`/`--continue`, not "commit or
    clean", so the two cases get different guidance."""
    if mid_rebase:
        return (
            f"error: {src} has local changes, and a rebase is already in "
            f"progress -- likely a prior run of this script that stopped on "
            f"a conflict and was never resolved. Either finish it (resolve "
            f"conflicts, `git add <file>`, then `git -C {src} rebase "
            f"--continue`) or abandon it (`git -C {src} rebase --abort`), "
            f"then re-run this script.")
    return (f"error: {src} has local changes; commit or clean them first "
            f"(`git -C {src} status` to inspect).")


def _apply_patches_failed_message(src: Path, from_tag: str, returncode: int) -> str:
    """Diagnose an apply_patches.py failure while building the overlay
    commit. Nothing has been committed or rebased yet at this point --
    `checkout -B` only reset the tree to `from_tag`, and apply_patches.py
    was still writing into it -- so recovery is just discarding whatever
    partial diff it left, not hand-repairing the tree."""
    return (
        f"\napply_patches.py failed while building the overlay commit on top "
        f"of {from_tag} (exit {returncode}; see its output above). Nothing "
        f"has been committed or rebased yet: {src} is left on branch "
        f"'{WORK_BRANCH}', still at {from_tag}, with only a partial, "
        f"uncommitted overlay diff in the working tree. Discard it and "
        f"retry:\n"
        f"  git -C {src} reset --hard {from_tag}\n"
        f"  git -C {src} clean -fd\n")


def _conflict_message(src: Path, conflicts: str) -> str:
    """Operator-facing diagnosis for a `git rebase --onto` that stopped on
    conflicts. Pure formatting over the already-collected conflicting-file
    listing, so the wording can be pinned by a test independent of driving
    a real conflict through git."""
    return (
        f"\n{src} is left mid-rebase on branch '{WORK_BRANCH}' with real "
        f"conflicts inside the source (not .rej files) -- resolve them in "
        f"the tree, `git add <file>`, then `git -C {src} rebase "
        f"--continue`. To abandon this attempt instead and return to "
        f"exactly where you started: `git -C {src} rebase --abort`.\n\n"
        f"CONFLICTS:\n" + (conflicts or "  (see git status)"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebase the teleport overlay from one upstream tag onto another")
    parser.add_argument("--from-tag", required=True, help="old baseline, e.g. 148.0.7778.180")
    parser.add_argument("--onto-tag", required=True, help="new baseline, e.g. 151.0.7922.76")
    parser.add_argument("--root", type=Path, default=repo_root())
    args = parser.parse_args(argv)

    root, src = args.root, chromium_src(args.root)
    if not (src / ".git").exists():
        print(f"error: {src} is not a chromium checkout", file=sys.stderr)
        return 1

    status = git(src, "status", "--porcelain").stdout
    if _is_dirty(status):
        print(_dirty_tree_message(src, _rebase_in_progress(src)), file=sys.stderr)
        return 1

    ensure_tag(src, args.from_tag)
    ensure_tag(src, args.onto_tag)

    git(src, "checkout", "-B", WORK_BRANCH, args.from_tag)
    print(f"applying the overlay on top of {args.from_tag} ...")
    # --skip-branding is load-bearing, not an optimization. branding_strings
    # rewrites ~58 grd/grdp/xtb paths, 3 of which ALSO carry hand-authored
    # patches. With branding applied, `git diff <tag> -- <those 3>` captures the
    # rebranding too and export_patches would bake it into the patch files. The
    # rebranding is derived output, regenerated on every apply_patches run, so it
    # must never enter the commit that gets rebased.
    rc = subprocess.run([sys.executable, str(root / "scripts" / "apply_patches.py"),
                         "--root", str(root), "--skip-branding"]).returncode
    if rc != 0:
        print(_apply_patches_failed_message(src, args.from_tag, rc), file=sys.stderr)
        return rc

    paths = tracked_overlay_paths(root)
    if not paths:
        # `git add --` with an empty pathspec exits 0 and adds nothing; the
        # ensuing `git commit` is what actually fails, on "nothing to
        # commit". Catching it here gives a diagnosable message instead of
        # relying on that indirect, easy-to-misread failure -- and guards a
        # future narrowing of tracked_overlay_paths() that empties this set.
        print("error: no overlay paths to stage -- patches/ and branding/ "
              "are both empty and there is no version-generated file; "
              "nothing to commit", file=sys.stderr)
        return 1
    git(src, "add", "--", *paths)
    git(src, "commit", "-m", f"teleport overlay @{args.from_tag}")

    print(f"rebasing onto {args.onto_tag} ...")
    r = git(src, "rebase", "--onto", args.onto_tag, args.from_tag, check=False)
    if r.returncode != 0:
        conflicts = git(src, "diff", "--name-only", "--diff-filter=U").stdout
        # Both halves of the failure report go to stderr -- a caller that
        # only captures one stream must still get the full picture.
        print(r.stdout + r.stderr, file=sys.stderr)
        print(_conflict_message(src, conflicts), file=sys.stderr)
        print(f"\nWhen the rebase finishes, run:\n"
              f"  uv run python scripts/export_patches.py --tag {args.onto_tag}",
              file=sys.stderr)
        return 2

    print(f"rebase clean. Now run:\n"
          f"  uv run python scripts/export_patches.py --tag {args.onto_tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
