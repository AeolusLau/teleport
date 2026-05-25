import os
from pathlib import Path

import pytest

import _lib


def test_create_dir_link_creates_symlink(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, target)
    assert link.is_symlink()
    assert Path(os.path.realpath(link)) == target.resolve()


def test_create_dir_link_is_idempotent(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, target)
    _lib.create_dir_link(link, target)  # second call must not raise
    assert Path(os.path.realpath(link)) == target.resolve()


def test_create_dir_link_wrong_target_raises(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, tmp_path / "a")
    with pytest.raises(RuntimeError):
        _lib.create_dir_link(link, tmp_path / "b")


def test_create_dir_link_replaces_empty_dir(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.mkdir()  # empty real dir (e.g., a stray out/)
    _lib.create_dir_link(link, target)
    assert link.is_symlink()


def test_create_dir_link_nonempty_dir_raises(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.mkdir()
    (link / "x").write_text("")  # non-empty -> must not be removed
    with pytest.raises(RuntimeError):
        _lib.create_dir_link(link, target)


def test_chromium_src_honors_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(tmp_path / "cr"))
    assert _lib.chromium_src() == tmp_path / "cr" / "src"


def test_chromium_src_default(monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    src = _lib.chromium_src()
    assert src.name == "src"
    assert src.parent.name == "chromium"
