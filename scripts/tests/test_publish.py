import subprocess

import pytest

import _publish


def _completed(stdout):
    def _run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
    return _run


def test_tag_name():
    assert _publish.tag_name("0.1.0") == "v0.1.0"


def test_assert_on_main_ok(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed("main\n"))
    _publish.assert_on_main()  # no raise


def test_assert_on_main_rejects_branch(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed("feature/x\n"))
    with pytest.raises(SystemExit, match="refusing to publish from branch"):
        _publish.assert_on_main()


def test_assert_clean_tree_ok(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed(""))
    _publish.assert_clean_tree()  # no raise


def test_assert_clean_tree_rejects_dirty(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed(" M scripts/x.py\n"))
    with pytest.raises(SystemExit, match="dirty working tree"):
        _publish.assert_clean_tree()


def test_tag_exists_true(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed("v0.1.0\n"))
    assert _publish.tag_exists("0.1.0") is True


def test_tag_exists_false(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed(""))
    assert _publish.tag_exists("0.1.0") is False


def test_assert_not_published_rejects_existing_tag(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v: True)
    with pytest.raises(SystemExit, match="tag v0.1.0 already exists"):
        _publish.assert_not_published("0.1.0", None)


def test_assert_not_published_rejects_feed_not_newer(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v: False)
    feed = (
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
        '<channel><item><sparkle:version>0.1.0</sparkle:version></item></channel></rss>'
    )
    with pytest.raises(SystemExit, match="not newer"):
        _publish.assert_not_published("0.1.0", feed)


def test_assert_not_published_ok_when_newer(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v: False)
    feed = (
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
        '<channel><item><sparkle:version>0.1.0</sparkle:version></item></channel></rss>'
    )
    _publish.assert_not_published("0.1.1", feed)  # no raise


def test_tag_and_push_invokes_git(monkeypatch):
    calls = []
    monkeypatch.setattr(_publish.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(_publish, "repo_root", lambda: "/repo")
    _publish.tag_and_push("0.1.0", "origin")
    assert calls[0][:3] == ["git", "tag", "-a"]
    assert "v0.1.0" in calls[0]
    assert calls[1] == ["git", "push", "origin", "v0.1.0"]
    assert calls[0] == ["git", "tag", "-a", "v0.1.0", "-m", "release 0.1.0"]


def test_generate_appcast_trims_to_keep_dmg(monkeypatch, tmp_path):
    (tmp_path / "Teleport-0.1.0.dmg").write_bytes(b"")
    (tmp_path / "Teleport-0.0.9.dmg").write_bytes(b"")
    (tmp_path / "appcast.xml").write_bytes(b"")
    (tmp_path / "Teleport-0.0.9.dmg.delta").write_bytes(b"")

    monkeypatch.setattr(_publish, "sparkle_bin", lambda name: "/fake/" + name)

    calls = []
    monkeypatch.setattr(_publish.subprocess, "run", lambda argv, **kw: calls.append(argv))

    _publish.generate_appcast(tmp_path, "https://h/dl/", "Teleport-0.1.0.dmg")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["Teleport-0.1.0.dmg"]
    assert calls[0] == [
        "/fake/generate_appcast",
        "--maximum-deltas", "0",
        "--download-url-prefix", "https://h/dl/",
        str(tmp_path),
    ]


def test_upload_to_oss_cache_headers(monkeypatch, tmp_path):
    (tmp_path / "Teleport-0.1.0.dmg").write_bytes(b"")
    (tmp_path / "appcast.xml").write_bytes(b"")

    calls = []
    monkeypatch.setattr(_publish.subprocess, "run", lambda argv, **kw: calls.append(argv))

    _publish.upload_to_oss(tmp_path, "oss://bucket/x/")

    dmg_call = next(c for c in calls if c[3].endswith("Teleport-0.1.0.dmg"))
    assert dmg_call[:3] == ["ossutil", "cp", "-f"]
    assert dmg_call[4] == "oss://bucket/x/"
    assert dmg_call[-2:] == ["--cache-control", "public, max-age=31536000, immutable"]

    appcast_call = next(c for c in calls if c[3].endswith("appcast.xml"))
    assert appcast_call[-2:] == ["--cache-control", "no-cache"]
