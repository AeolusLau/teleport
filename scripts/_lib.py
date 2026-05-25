"""Shared helpers for the teleport overlay build scripts."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def repo_root() -> Path:
    """teleport repo root (the dir containing this scripts/ folder)."""
    return Path(__file__).resolve().parent.parent


def chromium_dir(root: Path | None = None) -> Path:
    """Chromium checkout dir. Honors $TELEPORT_CHROMIUM_DIR so a large external
    checkout is not tied to the per-worktree repo path; defaults to <repo>/chromium.
    """
    env = os.environ.get("TELEPORT_CHROMIUM_DIR")
    if env:
        return Path(env)
    return (root or repo_root()) / "chromium"


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


def _points_somewhere(path: Path) -> bool:
    """True if `path` is a reparse point (Windows junction) we can resolve."""
    try:
        return os.path.realpath(path) != str(path)
    except OSError:
        return False
