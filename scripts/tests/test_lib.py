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
    monkeypatch.delenv("TELEPORT_CHROMIUM_ROOT", raising=False)
    src = _lib.chromium_src()
    # Derived from the repo's own CHROMIUM_VERSION under the default root.
    assert src.parent.name == _lib.release_branch(_lib.pinned_chromium_version())
    assert src.name == "src"


def test_deps_cache_dir_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPORT_DEPS_DIR", str(tmp_path / "d"))
    assert _lib.deps_cache_dir() == tmp_path / "d"


def test_deps_cache_dir_default(monkeypatch):
    monkeypatch.delenv("TELEPORT_DEPS_DIR", raising=False)
    d = _lib.deps_cache_dir()
    assert d.name == "deps" and d.parent.name == "teleport"


def test_parse_four_segment_ok():
    assert _lib.parse_four_segment(" 151.0.7922.76\n") == "151.0.7922.76"


def test_parse_four_segment_rejects_three(tmp_path: Path):
    with pytest.raises(ValueError):
        _lib.parse_four_segment("151.0.7922")


def test_parse_four_segment_rejects_non_numeric():
    with pytest.raises(ValueError):
        _lib.parse_four_segment("151.0.7922.beta")


def test_release_branch_drops_patch():
    assert _lib.release_branch("151.0.7922.76") == "151.0.7922"


def test_pinned_chromium_version_reads_file(tmp_path: Path):
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.pinned_chromium_version(tmp_path) == "151.0.7922.76"


def test_chromium_root_honors_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    assert _lib.chromium_root() == tmp_path / "roots"


def test_chromium_root_default(monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_ROOT", raising=False)
    assert _lib.chromium_root() == Path.home() / "workspace" / "chromium"


def test_chromium_dir_derives_from_pinned_version(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.chromium_dir(tmp_path) == tmp_path / "roots" / "151.0.7922"


def test_chromium_dir_env_overrides_derivation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.chromium_dir(tmp_path) == tmp_path / "explicit"


def test_chromium_src_under_derived_dir(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    (tmp_path / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")
    assert _lib.chromium_src(tmp_path) == tmp_path / "roots" / "151.0.7922" / "src"


def test_repoint_dir_link_replaces_existing(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, a)
    _lib.repoint_dir_link(link, b)
    assert Path(os.path.realpath(link)) == b.resolve()


def test_repoint_dir_link_is_idempotent(tmp_path: Path):
    target = tmp_path / "t"
    target.mkdir()
    link = tmp_path / "link"
    _lib.repoint_dir_link(link, target)
    _lib.repoint_dir_link(link, target)
    assert Path(os.path.realpath(link)) == target.resolve()


def test_repoint_dir_link_refuses_nonempty_real_dir(tmp_path: Path):
    target = tmp_path / "t"
    target.mkdir()
    link = tmp_path / "link"
    link.mkdir()
    (link / "stuff.txt").write_text("do not delete me")
    with pytest.raises(RuntimeError):
        _lib.repoint_dir_link(link, target)


def test_sha256_of_known_vectors(tmp_path):
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    assert _lib.sha256_of(empty) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    abc = tmp_path / "abc"
    abc.write_bytes(b"abc")
    assert _lib.sha256_of(abc) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
