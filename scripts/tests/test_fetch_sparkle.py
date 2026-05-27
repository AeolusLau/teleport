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
    assert "third_party/teleport_sparkle" in str(p)


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
