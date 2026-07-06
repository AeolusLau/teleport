import pytest

import generate_version as gv


def test_parse_product_version_four_segments():
    assert gv.parse_product_version("0.1.12.0\n") == (0, 1, 12, 0)
    assert gv.parse_product_version(" 1.2.3.4 ") == (1, 2, 3, 4)


@pytest.mark.parametrize("bad", ["0.1.12", "1.2", "1.2.3.4.5", "v1.2.3.0", "", "a.b.c.d"])
def test_parse_product_version_rejects(bad):
    with pytest.raises(ValueError):
        gv.parse_product_version(bad)


def test_chrome_version_content_format():
    assert (gv.chrome_version_content((0, 1, 12, 0))
            == "MAJOR=0\nMINOR=1\nBUILD=12\nPATCH=0\n")


def test_parse_engine_version_ok_and_reject():
    assert gv.parse_engine_version("148.0.7778.180\n") == "148.0.7778.180"
    with pytest.raises(ValueError):
        gv.parse_engine_version("148.0")


def test_engine_header_content_macros():
    h = gv.engine_header_content("148.0.7778.180")
    assert '#define TELEPORT_ENGINE_VERSION_STRING "148.0.7778.180"' in h
    assert '#define TELEPORT_ENGINE_VERSION_MAJOR "148"' in h
    assert h.startswith("//")  # generated-file banner
    assert "#ifndef COMPONENTS_VERSION_INFO_TELEPORT_ENGINE_VERSION_H_" in h


def _fake_root(tmp_path, monkeypatch, teleport="0.1.12.0\n", chromium="148.0.7778.180\n"):
    # chromium_src() prefers $TELEPORT_CHROMIUM_DIR; neutralize it for hermetic tests.
    monkeypatch.delenv("TELEPORT_CHROMIUM_DIR", raising=False)
    (tmp_path / "TELEPORT_VERSION").write_text(teleport)
    (tmp_path / "CHROMIUM_VERSION").write_text(chromium)
    (tmp_path / "chromium" / "src" / "chrome").mkdir(parents=True)
    (tmp_path / "chromium" / "src" / "components" / "version_info").mkdir(parents=True)
    return tmp_path


def test_write_chrome_version_writes_then_skips(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch)
    target = root / "chromium" / "src" / "chrome" / "VERSION"
    assert gv.write_chrome_version(root) is True
    assert target.read_text() == "MAJOR=0\nMINOR=1\nBUILD=12\nPATCH=0\n"
    mtime = target.stat().st_mtime_ns
    assert gv.write_chrome_version(root) is False   # unchanged -> no write
    assert target.stat().st_mtime_ns == mtime        # mtime untouched


def test_write_engine_header_writes_then_skips(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch)
    target = (root / "chromium" / "src" / "components" / "version_info"
              / "teleport_engine_version.h")
    assert gv.write_engine_header(root) is True
    assert 'TELEPORT_ENGINE_VERSION_STRING "148.0.7778.180"' in target.read_text()
    assert gv.write_engine_header(root) is False


def test_write_chrome_version_rejects_three_segment_file(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, monkeypatch, teleport="0.1.12\n")
    with pytest.raises(ValueError):
        gv.write_chrome_version(root)
