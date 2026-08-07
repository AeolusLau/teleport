"""Shared helpers for the teleport overlay build scripts."""
from __future__ import annotations

import hashlib
import os
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


def create_dir_link(link: Path, target: Path) -> None:
    """Create a directory link named `link` pointing at `target`.

    POSIX: symlink. Windows: directory junction (`mklink /J`) — needs no
    privilege and works for same-volume dirs. Idempotent when the link already
    points at `target`; raises if it points elsewhere or a real file is in the way.
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
    if is_windows():
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True, text=True,
        )
    else:
        os.symlink(target, link, target_is_directory=True)


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
