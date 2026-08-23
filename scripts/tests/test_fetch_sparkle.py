import pytest

import fetch_sparkle


def test_cache_framework_path_uses_version(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPORT_DEPS_DIR", str(tmp_path))
    p = fetch_sparkle.cache_framework_path()
    assert p.parent.name == fetch_sparkle.SPARKLE_VERSION
    assert p.name == "Sparkle.framework"


def test_link_path_under_chromium_src(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(tmp_path / "cr"))
    p = fetch_sparkle.link_path()
    assert p.name == "Sparkle.framework"
    # as_posix(): str() on a Windows Path yields backslashes.
    assert "third_party/teleport_sparkle" in p.as_posix()


def test_verify_sha256_matches(tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"abc")
    fetch_sparkle.verify_sha256(
        f, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )  # must not raise


def test_verify_sha256_mismatch_raises(tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"abc")
    with pytest.raises(RuntimeError):
        fetch_sparkle.verify_sha256(f, "deadbeef")


# --- Regression coverage for the missing checkout-exists guard (F10) -------
#
# Run fetch_sparkle.py after bumping CHROMIUM_VERSION but before the new
# checkout is created (e.g. before runbook §B0's `git clone --local`), and
# install_framework() would previously `mkdir -p` a phantom
# third_party/teleport_sparkle/ tree under a checkout directory that does not
# exist yet -- printing success and exiting 0, then breaking the later
# `git clone --local` with a confusing "destination path already exists"
# error instead of the real cause.

def test_install_framework_refuses_when_checkout_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(tmp_path / "not-a-checkout-yet"))
    with pytest.raises(RuntimeError, match="git checkout"):
        fetch_sparkle.install_framework()
    # And it must not have created the phantom directory tree either.
    assert not (tmp_path / "not-a-checkout-yet").exists()


def test_install_framework_proceeds_when_checkout_exists(tmp_path, monkeypatch):
    checkout = tmp_path / "cr"
    (checkout / "src" / ".git").mkdir(parents=True)
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(checkout))
    monkeypatch.setattr(
        fetch_sparkle, "cache_framework_path", lambda: tmp_path / "no-such-cache")
    # Past the guard, it proceeds to shutil.copytree and fails on the
    # (deliberately) missing cache source -- proving the guard itself did not
    # block a real checkout, without needing a real Sparkle.framework fixture.
    with pytest.raises(FileNotFoundError):
        fetch_sparkle.install_framework()


def test_main_refuses_when_checkout_does_not_exist(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TELEPORT_CHROMIUM_DIR", str(tmp_path / "not-a-checkout-yet"))
    rc = fetch_sparkle.main([])
    assert rc == 1
    assert "git checkout" in capsys.readouterr().err
