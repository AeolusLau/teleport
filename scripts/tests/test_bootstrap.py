import os
from pathlib import Path

import _lib
import bootstrap
from tests.conftest import requires_symlinks


def test_gclient_template_enables_pgo_profiles():
    assert '"checkout_pgo_profiles": True' in bootstrap.GCLIENT_SOLUTION


def test_ensure_gclient_writes_when_missing(tmp_path):
    p = tmp_path / ".gclient"
    bootstrap.ensure_gclient(p)
    assert p.exists()
    assert "checkout_pgo_profiles" in p.read_text()


def test_ensure_gclient_rewrites_legacy_file_without_var(tmp_path):
    p = tmp_path / ".gclient"
    p.write_text(
        'solutions = [\n'
        '  {\n'
        '    "name": "src",\n'
        '    "url": "https://chromium.googlesource.com/chromium/src.git",\n'
        '    "managed": False,\n'
        '    "custom_deps": {},\n'
        '    "custom_vars": {},\n'
        '  },\n'
        ']\n'
    )
    bootstrap.ensure_gclient(p)
    assert "checkout_pgo_profiles" in p.read_text()


def test_ensure_gclient_is_noop_when_var_present(tmp_path):
    p = tmp_path / ".gclient"
    bootstrap.ensure_gclient(p)
    sentinel = p.read_text() + "# user edit\n"
    p.write_text(sentinel)
    bootstrap.ensure_gclient(p)  # var already present -> must not clobber
    assert p.read_text() == sentinel


@requires_symlinks  # bootstrap plants the overlay injection link, which must
                    # be a real symlink (siso will not traverse a junction).
def test_bootstrap_repoints_stale_build_link(tmp_path: Path, monkeypatch):
    """A build/ link left over from the previous baseline must be repointed,
    not raise."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "CHROMIUM_VERSION").write_text("151.0.7922.76\n")

    old_src = tmp_path / "old" / "src"
    (old_src / "out").mkdir(parents=True)
    (old_src / ".git").mkdir()
    new_src = tmp_path / "roots" / "151.0.7922" / "src"
    (new_src / ".git").mkdir(parents=True)

    _lib.create_dir_link(repo / "build", old_src / "out")

    monkeypatch.setenv("TELEPORT_CHROMIUM_ROOT", str(tmp_path / "roots"))
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "/usr/bin/gclient")

    assert bootstrap.main(["--skip-sync", "--root", str(repo)]) == 0
    assert Path(os.path.realpath(repo / "build")) == (new_src / "out").resolve()
