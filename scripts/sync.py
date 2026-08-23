"""Sync chromium/src to the pinned version and verify it matches CHROMIUM_VERSION."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _lib import chromium_src, depot_tool, repo_root


def resolved_tag_commit(src: Path, tag: str) -> str:
    """Resolve `tag` to the commit it points at: locally if the checkout has the
    tag, otherwise by asking origin.

    A `gclient sync --no-history` checkout -- which is what sync() below asks for
    -- is a depth-1 shallow clone carrying NO tags at all. `--with_tags` cannot
    change that: a shallow fetch of one specific revision never negotiates the
    tag refs, so there is nothing for it to bring along. The local lookup
    therefore comes up empty on a checkout that is in fact exactly right, and the
    old code reported that as "pinned tag not found ... should have fetched it" --
    an accusation aimed at gclient for a checkout with nothing wrong with it.

    Fetching the tag to resolve it would defeat the point of --no-history by
    pulling objects into a deliberately shallow repo. `git ls-remote` answers the
    same question from the ref advertisement alone, transferring no objects, so
    the check keeps verifying the thing it exists to verify: that HEAD is the
    exact commit the pinned tag names upstream.
    """
    r = subprocess.run(
        ["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"],
        cwd=src, capture_output=True, text=True,
    )
    if r.returncode == 0:
        return r.stdout.strip()
    return remote_tag_commit(src, tag)


def remote_tag_commit(src: Path, tag: str) -> str:
    """Peel `tag` to a commit by asking origin, without transferring objects.

    Both ref forms are requested because upstream uses both: an annotated tag
    advertises the tag object under `refs/tags/<tag>` and the commit it wraps
    under `refs/tags/<tag>^{}`, while a lightweight tag (which is what the
    chromium release tags are) advertises only the first, already pointing at the
    commit. The peeled line wins when present -- taking the unpeeled line for an
    annotated tag would compare HEAD against a tag object's hash, which never
    equals a commit hash, and the mismatch would look like a wrong checkout.
    """
    r = subprocess.run(
        ["git", "ls-remote", "origin", f"refs/tags/{tag}^{{}}", f"refs/tags/{tag}"],
        cwd=src, capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"could not reach origin to resolve pinned tag {tag} "
            f"(git ls-remote: {r.stderr.strip()})")
    refs = {}
    for line in r.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if sha and ref:
            refs[ref.strip()] = sha.strip()
    for ref in (f"refs/tags/{tag}^{{}}", f"refs/tags/{tag}"):
        if ref in refs:
            return refs[ref]
    raise RuntimeError(
        f"pinned tag {tag} does not exist upstream (origin advertises no "
        f"refs/tags/{tag}). Check CHROMIUM_VERSION against "
        f"scripts/check_upstream_release.py.")


def verify_version(src: Path, expected: str) -> None:
    """Verify `src`'s checked-out HEAD is exactly the pinned upstream tag.

    Deliberately does NOT read chrome/VERSION. apply_patches.py unconditionally
    overwrites that file with TELEPORT_VERSION (the 4-segment product version,
    see generate_version.py) as part of applying the overlay, so on any
    checkout that already carries the overlay it no longer reflects what
    gclient actually synced. That is not a rare edge case: it is the normal
    state of every 路径 A (security-patch) re-sync in
    docs/chromium-upgrade-runbook.md, which by design reuses an
    already-overlaid checkout. Comparing chrome/VERSION there raised on every
    single run -- the 24-48h 0-day response path check_upstream_release.py
    points operators at -- not just on a genuine mismatch.

    git HEAD is unaffected by anything apply_patches.py does, and directly
    reflects what `gclient sync --revision src@<expected>` actually checked
    out (that flag IS the git ref gclient resolves and checks out), so
    resolving the pinned tag to a commit and comparing it to HEAD verifies
    the one thing this function exists to verify -- correctly on a brand new
    checkout AND an overlay-applied one alike.
    """
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True, check=True,
    ).stdout.strip()
    pinned_commit = resolved_tag_commit(src, expected)
    if head != pinned_commit:
        described = subprocess.run(
            ["git", "describe", "--tags", "--always", "HEAD"],
            cwd=src, capture_output=True, text=True,
        ).stdout.strip() or head
        raise RuntimeError(
            f"chromium checkout mismatch: HEAD is {described} ({head}), "
            f"pinned tag {expected} resolves to {pinned_commit}")


def main() -> int:
    root = repo_root()
    pinned = (root / "CHROMIUM_VERSION").read_text().strip()
    src = chromium_src(root)
    chromium = src.parent
    print(f"gclient sync src@{pinned} ...")
    rc = subprocess.run(
        # depot_tool(), not a bare "gclient": on Windows a bare name resolves to
        # depot_tools' extensionless POSIX script instead of gclient.bat.
        [depot_tool("gclient"), "sync", "--revision", f"src@{pinned}",
         "--with_tags", "--no-history"],
        cwd=chromium,
    ).returncode
    if rc != 0:
        return rc
    verify_version(src, pinned)
    print(f"synced and verified chromium {pinned}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
