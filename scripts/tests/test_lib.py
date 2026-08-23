import os
from pathlib import Path

import pytest

import _lib
from tests.conftest import requires_symlinks


def _is_dir_link(p: Path) -> bool:
    """True for whichever link kind create_dir_link makes on this host.

    Path.is_symlink() is False for a Windows junction -- junctions carry a
    different reparse tag -- so asserting is_symlink() would demand the one link
    kind create_dir_link deliberately does NOT use there: a real symlink needs
    SeCreateSymbolicLinkPrivilege, a junction needs none, and that is what lets
    bootstrap.py run unelevated.
    """
    return p.is_symlink() or (p.is_dir() and os.path.realpath(p) != str(p))


def test_create_dir_link_creates_a_directory_link(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, target)
    assert _is_dir_link(link)
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
    assert _is_dir_link(link)


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


# --- Windows portability -------------------------------------------------

def test_write_text_lf_keeps_lf_on_every_host(tmp_path: Path):
    """Path.write_text opens with newline=None, which translates every linefeed
    to os.linesep -- CRLF on Windows. Files this repo generates into the chromium
    checkout are then compared byte for byte by `git apply --reverse --check`,
    which is how apply_patches.py decides a patch is already applied; a CRLF
    rewrite breaks idempotency on a tree that is correctly patched."""
    p = tmp_path / "f.txt"
    _lib.write_text_lf(p, "a\nb\n")
    assert p.read_bytes() == b"a\nb\n"


def test_write_text_lf_round_trips_utf8(tmp_path: Path):
    p = tmp_path / "f.txt"
    _lib.write_text_lf(p, "闪现\n")
    assert p.read_bytes() == "闪现\n".encode("utf-8")


def test_depot_tool_resolves_through_which(monkeypatch):
    """A bare "gclient"/"gn"/"autoninja" passed to subprocess is not runnable on
    Windows: depot_tools ships each as both an extensionless POSIX script and a
    .bat, and CreateProcess only ever appends .exe -- it never consults PATHEXT,
    so it picks the sh script and fails as "not a valid Win32 application"."""
    monkeypatch.setattr(_lib.shutil, "which", lambda name: f"/dt/{name}.bat")
    assert _lib.depot_tool("gclient") == "/dt/gclient.bat"


def test_depot_tool_raises_when_not_on_path(monkeypatch):
    monkeypatch.setattr(_lib.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="depot_tools"):
        _lib.depot_tool("gn")


@requires_symlinks
def test_create_dir_link_traversed_by_build_is_a_real_symlink(tmp_path: Path):
    """The overlay injection link must be a SYMLINK, not a junction: siso walks
    into it, and it will not traverse a junction. os.path.islink() distinguishes
    the two on Windows (a junction is a mount-point reparse tag, not a symlink
    one), so this asserts the stronger property, unlike _is_dir_link above."""
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _lib.create_dir_link(link, target, traversed_by_build=True)
    assert os.path.islink(link)
    assert Path(os.path.realpath(link)) == target.resolve()


def test_create_dir_link_symlink_failure_is_actionable(tmp_path: Path, monkeypatch):
    """Windows without SeCreateSymbolicLinkPrivilege must fail HERE, naming both
    remedies -- not fall back to a junction. The junction failure surfaces much
    later, from siso, as `store resolve next dir ... failed`, long after `gn gen`
    has reported ~31.5k targets and with nothing in the message connecting it to
    a link type or a privilege."""
    monkeypatch.setattr(_lib, "is_windows", lambda: True)

    def _denied(*a, **kw):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(_lib.os, "symlink", _denied)
    with pytest.raises(RuntimeError) as e:
        _lib.create_dir_link(tmp_path / "link", tmp_path, traversed_by_build=True)
    msg = str(e.value)
    assert "Developer Mode" in msg          # remedy 1
    assert "mklink /D" in msg               # remedy 2
    assert "siso" in msg                    # why a junction is not accepted


def test_create_dir_link_convenience_link_does_not_need_the_privilege(
        tmp_path: Path, monkeypatch):
    """The build/ -> out link is never walked by the build, so it stays a
    junction: requiring elevation for it would be a cost that buys nothing."""
    calls = []
    monkeypatch.setattr(_lib, "is_windows", lambda: True)
    monkeypatch.setattr(_lib.os, "symlink",
                        lambda *a, **kw: pytest.fail("must not symlink"))
    monkeypatch.setattr(_lib.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    _lib.create_dir_link(tmp_path / "link", tmp_path)
    assert calls and calls[0][:4] == ["cmd", "/c", "mklink", "/J"]
