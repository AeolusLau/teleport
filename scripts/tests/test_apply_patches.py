import os
import subprocess
import time
from pathlib import Path

import pytest

import apply_patches


def test_apply_branding_overwrites_with_fresh_mtime(tmp_path: Path):
    # A stale dest mtime makes ninja skip recompiling, so apply_branding must NOT
    # preserve the source's (old) mtime — the overwritten file must be "fresh".
    branding = tmp_path / "branding" / "sub"
    branding.mkdir(parents=True)
    srcf = branding / "logo.png"
    srcf.write_bytes(b"NEW-LOGO")
    old = time.time() - 100_000
    os.utime(srcf, (old, old))  # source is intentionally old
    src = tmp_path / "src" / "sub"
    src.mkdir(parents=True)
    dest = (tmp_path / "src" / "sub" / "logo.png")
    dest.write_bytes(b"OLD-LOGO")
    apply_patches.apply_branding(tmp_path / "branding", tmp_path / "src")
    assert dest.read_bytes() == b"NEW-LOGO"
    assert dest.stat().st_mtime > old + 1000  # fresh mtime, not the source's old one


def test_apply_branding_skips_identical_file(tmp_path: Path):
    branding = tmp_path / "branding"
    branding.mkdir()
    (branding / "same.txt").write_bytes(b"X")
    src = tmp_path / "src"
    src.mkdir()
    dest = src / "same.txt"
    dest.write_bytes(b"X")
    old = time.time() - 100_000
    os.utime(dest, (old, old))
    apply_patches.apply_branding(branding, src)
    # identical content -> not rewritten -> mtime unchanged (no needless rebuild)
    assert abs(dest.stat().st_mtime - old) < 2


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _make_fake_src(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "t@t")
    _git(src, "config", "user.name", "t")
    (src / "chrome").mkdir()
    (src / "chrome" / "foo.txt").write_text("line1\nline2\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "base")
    return src


def _make_patch(tmp_path: Path, src: Path) -> Path:
    # Edit the file, capture the diff as a one-file patch mirroring the src path.
    (src / "chrome" / "foo.txt").write_text("line1\nCHANGED\n")
    diff = _git(src, "diff")
    _git(src, "checkout", "--", ".")  # restore clean tree
    patches = tmp_path / "patches"
    (patches / "chrome").mkdir(parents=True)
    patch = patches / "chrome" / "foo.txt.patch"
    patch.write_text(diff)
    return patch


def test_apply_then_idempotent(tmp_path: Path):
    src = _make_fake_src(tmp_path)
    patch = _make_patch(tmp_path, src)
    apply_patches.apply_patch(patch, src)
    assert "CHANGED" in (src / "chrome" / "foo.txt").read_text()
    # Second apply is a no-op (does not raise, content unchanged).
    apply_patches.apply_patch(patch, src)
    assert (src / "chrome" / "foo.txt").read_text().count("CHANGED") == 1


def test_apply_conflict_fails_fast(tmp_path: Path):
    src = _make_fake_src(tmp_path)
    patch = _make_patch(tmp_path, src)
    # Make the target incompatible so the patch neither applies nor reverses.
    (src / "chrome" / "foo.txt").write_text("totally different\n")
    with pytest.raises(RuntimeError):
        apply_patches.apply_patch(patch, src)


def test_find_patches_sorted(tmp_path: Path):
    patches = tmp_path / "patches"
    (patches / "b").mkdir(parents=True)
    (patches / "a").mkdir(parents=True)
    (patches / "b" / "z.patch").write_text("")
    (patches / "a" / "y.patch").write_text("")
    found = apply_patches.find_patches(patches)
    assert [p.relative_to(patches).as_posix() for p in found] == ["a/y.patch", "b/z.patch"]
