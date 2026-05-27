import pytest

import _release


def test_parse_semver_ok():
    assert _release.parse_semver("0.1.0") == (0, 1, 0)
    assert _release.parse_semver(" 1.2.3 ") == (1, 2, 3)


@pytest.mark.parametrize("bad", ["0.1", "1.2.3.4", "v1.0.0", "x", ""])
def test_parse_semver_rejects(bad):
    with pytest.raises(ValueError):
        _release.parse_semver(bad)


def test_is_newer():
    assert _release.is_newer("0.1.1", "0.1.0")
    assert _release.is_newer("0.2.0", "0.1.9")
    assert not _release.is_newer("0.1.0", "0.1.0")
    assert not _release.is_newer("0.1.0", "0.1.1")


APPCAST = """<?xml version="1.0"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
 <channel>
  <item><sparkle:version>0.1.0</sparkle:version></item>
  <item><sparkle:version>0.1.2</sparkle:version></item>
  <item><sparkle:version>0.1.1</sparkle:version></item>
 </channel>
</rss>"""


def test_max_appcast_version():
    assert _release.max_appcast_version(APPCAST) == "0.1.2"


def test_max_appcast_version_empty():
    empty = '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel/></rss>'
    assert _release.max_appcast_version(empty) is None


def test_assert_publishable_allows_newer():
    _release.assert_publishable("0.1.3", APPCAST)  # must not raise


def test_assert_publishable_blocks_equal_or_older():
    with pytest.raises(SystemExit):
        _release.assert_publishable("0.1.2", APPCAST)
    with pytest.raises(SystemExit):
        _release.assert_publishable("0.1.0", APPCAST)


def test_assert_publishable_empty_feed_ok():
    _release.assert_publishable("0.1.0", None)
    _release.assert_publishable("0.1.0", "")


def test_read_teleport_version(tmp_path):
    (tmp_path / "TELEPORT_VERSION").write_text("0.4.2\n")
    assert _release.read_teleport_version(tmp_path) == "0.4.2"
