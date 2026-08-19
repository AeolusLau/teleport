import subprocess

import pytest

import urllib.error

import _publish


def _completed(stdout):
    def _run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
    return _run


def test_tag_name():
    assert _publish.tag_name("0.1.0", "canary") == "v0.1.0"


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
    assert _publish.tag_exists("0.1.0", "canary") is True


def test_tag_exists_false(monkeypatch):
    monkeypatch.setattr(_publish.subprocess, "run", _completed(""))
    assert _publish.tag_exists("0.1.0", "canary") is False


def test_assert_not_published_rejects_existing_tag(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v, ch: True)
    with pytest.raises(SystemExit, match="tag v0.1.0 already exists"):
        _publish.assert_not_published("0.1.0", "canary", None)


def test_assert_not_published_rejects_feed_not_newer(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v, ch: False)
    feed = (
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
        '<channel><item><sparkle:version>0.1.0</sparkle:version></item></channel></rss>'
    )
    with pytest.raises(SystemExit, match="not newer"):
        _publish.assert_not_published("0.1.0", "canary", feed)


def test_assert_not_published_ok_when_newer(monkeypatch):
    monkeypatch.setattr(_publish, "tag_exists", lambda v, ch: False)
    feed = (
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
        '<channel><item><sparkle:version>0.1.0</sparkle:version></item></channel></rss>'
    )
    _publish.assert_not_published("0.1.1", "canary", feed)  # no raise


def test_tag_and_push_invokes_git(monkeypatch):
    calls = []
    monkeypatch.setattr(_publish.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(_publish, "repo_root", lambda: "/repo")
    _publish.tag_and_push("0.1.0", "canary", "origin")
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

    _publish.generate_appcast(tmp_path, "https://h/dl/", "Teleport-0.1.0.dmg", "ed25519")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["Teleport-0.1.0.dmg"]
    assert calls[0] == [
        "/fake/generate_appcast",
        # The signing account is named explicitly: the default picks the single
        # "ed25519" keychain entry, which is how every channel came to share one
        # update-signing key.
        "--account", "ed25519",
        "--maximum-deltas", "0",
        "--download-url-prefix", "https://h/dl/",
        str(tmp_path),
    ]


def test_upload_to_oss_cache_headers(monkeypatch, tmp_path):
    (tmp_path / "Teleport-0.1.0.dmg").write_bytes(b"")
    (tmp_path / "appcast.xml").write_bytes(b"")

    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "SECRET")
    calls = []
    monkeypatch.setattr(_publish.subprocess, "run", lambda argv, **kw: calls.append(argv))

    _publish.upload_to_oss(tmp_path, "oss://bucket/x/",
                           "https://oss-cn-beijing.aliyuncs.com", "cn-beijing")

    dmg_call = next(c for c in calls if c[3].endswith("Teleport-0.1.0.dmg"))
    assert dmg_call[:3] == ["ossutil", "cp", "-f"]
    assert dmg_call[4] == "oss://bucket/x/"
    assert dmg_call[-2:] == ["--cache-control", "public, max-age=31536000, immutable"]

    appcast_call = next(c for c in calls if c[3].endswith("appcast.xml"))
    assert appcast_call[-2:] == ["--cache-control", "no-cache"]


# --- Per-channel tag namespace --------------------------------------------

def test_tag_name_is_namespaced_per_channel():
    assert _publish.tag_name("0.2.0.0", "canary") == "v0.2.0.0"
    assert _publish.tag_name("0.2.0.0", "staging") == "staging/v0.2.0.0"


def test_staging_and_release_can_hold_the_same_version():
    """This is the workflow the namespace exists for: rehearse a version on
    staging, then ship that same version. A single namespace makes it
    impossible -- the release publish would refuse itself as already tagged,
    because staging got there first."""
    assert (_publish.tag_name("0.2.0.0", "staging")
            != _publish.tag_name("0.2.0.0", "canary"))


# --- Feed fetch must not launder failures into "no feed yet" ---------------

def test_fetch_live_appcast_returns_none_only_for_404(monkeypatch):
    def raise_404(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(_publish.urllib.request, "urlopen", raise_404)
    assert _publish.fetch_live_appcast("https://h/appcast.xml") is None


def test_fetch_live_appcast_refuses_on_a_transport_failure(monkeypatch):
    """A timeout must not read as 'first release'. That misreading turns
    assert_publishable into a no-op, removing one of only two guards against
    republishing over an immutable OSS object -- and a blocked publisher is
    realistic here, since staging is meant to sit behind an IP allowlist."""
    def raise_timeout(url):
        raise TimeoutError("connection timed out")
    monkeypatch.setattr(_publish.urllib.request, "urlopen", raise_timeout)
    with pytest.raises(SystemExit, match="appcast"):
        _publish.fetch_live_appcast("https://h/appcast.xml")


def test_fetch_live_appcast_refuses_on_a_server_error(monkeypatch):
    def raise_503(url):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
    monkeypatch.setattr(_publish.urllib.request, "urlopen", raise_503)
    with pytest.raises(SystemExit, match="503"):
        _publish.fetch_live_appcast("https://h/appcast.xml")


# --- OSS upload: explicit credentials, endpoint and region -----------------
#
# ossutil reads ~/.ossutilconfig in preference to the environment. On a machine
# that has ever configured another bucket, exporting ALIBABA_CLOUD_ACCESS_KEY_*
# is SILENTLY IGNORED and the wrong RAM user is used -- which surfaces as a
# permission error against the target bucket and reads exactly like the other
# side misconfigured their grant. That misdiagnosis cost a full cross-repo
# round-trip, so nothing here may be left for ossutil to infer.

def test_upload_passes_credentials_endpoint_and_region_explicitly(
        tmp_path, monkeypatch):
    (tmp_path / "Teleport-1.2.3.dmg").write_bytes(b"")
    (tmp_path / "appcast.xml").write_bytes(b"")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "SECRET")
    calls = []
    monkeypatch.setattr(_publish.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))

    _publish.upload_to_oss(tmp_path, "oss://b/p/",
                           "https://oss-cn-hangzhou.aliyuncs.com", "cn-hangzhou")

    assert len(calls) == 2  # one dmg + appcast
    for argv in calls:
        assert argv[:2] == ["ossutil", "cp"]
        # Every knob ossutil could otherwise take from ~/.ossutilconfig is given.
        assert "-i" in argv and argv[argv.index("-i") + 1] == "AKID"
        assert "-k" in argv and argv[argv.index("-k") + 1] == "SECRET"
        assert "-e" in argv
        assert argv[argv.index("-e") + 1] == "https://oss-cn-hangzhou.aliyuncs.com"
        assert "--region" in argv
        assert argv[argv.index("--region") + 1] == "cn-hangzhou"


def test_upload_refuses_when_credentials_are_absent(tmp_path, monkeypatch):
    """Fail loudly rather than let ossutil fall back to whatever credential the
    user-level config happens to hold -- that fallback publishes as the wrong
    identity, or fails in a way that looks like someone else's bug."""
    (tmp_path / "appcast.xml").write_bytes(b"")
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.setattr(_publish.subprocess, "run",
                        lambda argv, **kw: pytest.fail("must not shell out"))
    with pytest.raises(SystemExit, match="ALIBABA_CLOUD_ACCESS_KEY_ID"):
        _publish.upload_to_oss(tmp_path, "oss://b/p/",
                               "https://oss-cn-hangzhou.aliyuncs.com", "cn-hangzhou")


def test_upload_keeps_the_cache_headers_distinct(tmp_path, monkeypatch):
    """Regression pin: versioned dmgs are immutable, the appcast never is."""
    (tmp_path / "Teleport-1.2.3.dmg").write_bytes(b"")
    (tmp_path / "appcast.xml").write_bytes(b"")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "SECRET")
    calls = []
    monkeypatch.setattr(_publish.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    _publish.upload_to_oss(tmp_path, "oss://b/p/", "https://e", "r")
    dmg_call = next(a for a in calls if a[3].endswith(".dmg"))
    cast_call = next(a for a in calls if a[3].endswith("appcast.xml"))
    assert "immutable" in dmg_call[dmg_call.index("--cache-control") + 1]
    assert cast_call[cast_call.index("--cache-control") + 1] == "no-cache"
