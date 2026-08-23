"""Shared helpers for the teleport overlay build scripts."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path


def repo_root() -> Path:
    """teleport repo root (the dir containing this scripts/ folder)."""
    return Path(__file__).resolve().parent.parent


def deps_cache_dir() -> Path:
    """External deps cache (Sparkle, etc.). Honors $TELEPORT_DEPS_DIR;
    defaults to ~/.cache/teleport/deps. Shared across worktrees; gitignored
    (lives outside the repo)."""
    env = os.environ.get("TELEPORT_DEPS_DIR")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "teleport" / "deps"


def depot_tool(name: str) -> str:
    """Absolute path to a depot_tools launcher (`gclient`, `gn`, `autoninja`).

    Resolved with shutil.which rather than passed to subprocess as a bare name.
    depot_tools ships each of these twice -- an extensionless POSIX shell script
    and a `.bat` -- and on Windows the shell script is the one a bare name finds:
    CreateProcess (what subprocess uses without shell=True) only ever appends
    .exe, it does not consult PATHEXT, so it matches the extensionless file and
    fails with "not a valid Win32 application". shutil.which does apply PATHEXT
    and returns the .bat. On POSIX it simply returns the shell script, so the
    call site is identical on both platforms.
    """
    exe = shutil.which(name)
    if exe is None:
        raise RuntimeError(
            f"{name} not found on PATH -- add depot_tools to PATH "
            f"(https://chromium.googlesource.com/chromium/tools/depot_tools.git)")
    return exe


def write_text_lf(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write `content` with LF endings, whatever the host's line separator is.

    Path.write_text opens in text mode with newline=None, which translates every
    "\n" to os.linesep -- on Windows that silently rewrites the file with CRLF.
    Every file this repo generates into the checkout is subsequently compared
    against, or diffed into, an LF artifact: `git apply --reverse --check` is how
    apply_patches.py decides a patch is already applied, and it needs the context
    lines to match byte for byte. A CRLF rewrite of a patched file therefore does
    not corrupt the build -- it breaks idempotency, and the second
    apply_patches.py run fails with "patch does not apply cleanly" on a tree that
    is in fact correctly patched.
    """
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(content)


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file's contents (streamed)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# Default parent of all upstream checkouts. One subdirectory per upstream
# release branch (MAJOR.MINOR.BUILD), so a security-patch bump reuses the same
# checkout while a milestone jump gets a fresh one.
_DEFAULT_CHROMIUM_ROOT = Path.home() / "workspace" / "chromium"


def parse_four_segment(text: str) -> str:
    """Validate a 4-segment dotted version; return it stripped."""
    parts = text.strip().split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise ValueError(f"expected 4-segment numeric version, got {text!r}")
    return ".".join(parts)


def pinned_chromium_version(root: Path | None = None) -> str:
    """The upstream version pinned in CHROMIUM_VERSION."""
    text = ((root or repo_root()) / "CHROMIUM_VERSION").read_text()
    return parse_four_segment(text)


def release_branch(version: str) -> str:
    """MAJOR.MINOR.BUILD — identifies exactly one upstream release branch
    (refs/branch-heads/<BUILD>). PATCH moves stay inside this branch, so the
    checkout directory is keyed on this rather than the full version."""
    return ".".join(parse_four_segment(version).split(".")[:3])


def chromium_root() -> Path:
    """Parent dir holding one checkout per upstream release branch.
    Honors $TELEPORT_CHROMIUM_ROOT."""
    env = os.environ.get("TELEPORT_CHROMIUM_ROOT")
    return Path(env) if env else _DEFAULT_CHROMIUM_ROOT


def chromium_dir(root: Path | None = None) -> Path:
    """Chromium checkout for the pinned baseline: <root>/<MAJOR.MINOR.BUILD>.

    Deriving from CHROMIUM_VERSION means switching branches automatically
    points at the matching checkout — no environment variable to forget.
    $TELEPORT_CHROMIUM_DIR still overrides the whole path (CI / ad-hoc).
    """
    env = os.environ.get("TELEPORT_CHROMIUM_DIR")
    if env:
        return Path(env)
    return chromium_root() / release_branch(pinned_chromium_version(root))


def chromium_src(root: Path | None = None) -> Path:
    return chromium_dir(root) / "src"


def is_windows() -> bool:
    return os.name == "nt"


_SYMLINK_REQUIRED_HELP = """\
{link}
  -> {target}

must be a real SYMBOLIC LINK on Windows, and creating one needs
SeCreateSymbolicLinkPrivilege, which this process does not hold.

A directory junction (mklink /J) needs no privilege and is what this script
uses for links the build system never walks through -- but it will NOT do for
this one. siso's filesystem layer refuses to traverse a junction, and it does so
LATE and opaquely: `gn gen` resolves the junction perfectly and reports all
~31.5k targets, then the build dies before compiling anything with

    error in depfile "out/.../build.ninja.d": deps input
    "../../../../teleport/BUILD.gn" not exist: store resolve next dir <name> failed

which says nothing about junctions or privileges. Falling back to a junction
here would trade one clear error for that one, so this fails now instead.

Two ways to fix it, either is enough:

  1. Turn on Developer Mode (Settings -> System -> For developers). Symbolic
     link creation then works unelevated, and this script needs no special
     treatment ever again. This is the option to pick.

  2. Create the link once from an ELEVATED prompt -- the privilege is only
     needed to CREATE it, after which everything uses it unprivileged:

       cmd /c mklink /D "{link}" "{target}"

     Then re-run this script; it will find the link already correct and move on.
"""


def create_dir_link(link: Path, target: Path, *,
                    traversed_by_build: bool = False) -> None:
    """Create a directory link named `link` pointing at `target`.

    POSIX: always a symlink. Windows: a directory junction (`mklink /J`) by
    default, because a junction needs no privilege; but a real symbolic link
    when `traversed_by_build` is set.

    That distinction is not cosmetic. The build system walks INTO the overlay
    injection link, and siso will not traverse a junction; it will traverse a
    symlink. Links that exist purely as a convenience for humans (the repo's
    build/ -> out shortcut) are never walked by the build and stay junctions, so
    the privileged path is required only where it actually buys something.

    Idempotent when the link already points at `target`; raises if it points
    elsewhere or a real file is in the way.
    """
    link = Path(link)
    target = Path(target).resolve()
    if link.is_symlink() or (is_windows() and link.exists() and _points_somewhere(link)):
        existing = Path(os.path.realpath(link))
        if existing == target:
            return
        raise RuntimeError(f"link {link} -> {existing}, expected {target}")
    if link.exists():
        # Replace an empty real dir (e.g., a stray out/ created earlier).
        if link.is_dir() and not any(link.iterdir()):
            link.rmdir()
        else:
            raise RuntimeError(f"{link} exists and is not an empty dir or link")
    link.parent.mkdir(parents=True, exist_ok=True)
    if is_windows() and not traversed_by_build:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True, text=True,
        )
        return
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as e:
        if not is_windows():
            raise
        raise RuntimeError(
            _SYMLINK_REQUIRED_HELP.format(link=link, target=target)) from e


def repoint_dir_link(link: Path, target: Path) -> None:
    """Like create_dir_link, but an existing *link* pointing elsewhere is
    replaced instead of raising. Only for links that are pure access
    conveniences (e.g. <repo>/build). A real non-empty directory is still
    refused — we never delete data.
    """
    link = Path(link)
    if link.is_symlink() or (is_windows() and link.exists() and _points_somewhere(link)):
        if Path(os.path.realpath(link)) == Path(target).resolve():
            return
        link.unlink() if link.is_symlink() else link.rmdir()
    create_dir_link(link, target)


def _points_somewhere(path: Path) -> bool:
    """True if `path` is a reparse point (Windows junction) we can resolve."""
    try:
        return os.path.realpath(path) != str(path)
    except OSError:
        return False
