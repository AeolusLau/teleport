import subprocess

import pytest

import package_release

_FULL = (
    'public_ed_key="k"\n'
    'feed_url="https://h.example.com/a/appcast.xml"\n'
    'download_base_url="https://h.example.com/a/"\n'
    'oss_upload_target="oss://bucket/a/"\n'
    'codesign_identity="Developer ID Application: X (T)"\n'
    'notary_profile="p"\n'
)

# Config without codesign_identity — should auto-detect from keychain.
_NO_CODESIGN = (
    'public_ed_key="k"\n'
    'feed_url="https://h.example.com/a/appcast.xml"\n'
    'download_base_url="https://h.example.com/a/"\n'
    'oss_upload_target="oss://bucket/a/"\n'
    'notary_profile="p"\n'
)


def test_load_config_ok(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text(_FULL)
    c = package_release.load_config(cfg)
    assert c["feed_url"].startswith("https://")
    assert c["oss_upload_target"].startswith("oss://")
    assert c["notary_profile"] == "p"
    assert c["codesign_identity"] == "Developer ID Application: X (T)"


def test_load_config_auto_detects_codesign(tmp_path, monkeypatch):
    # Hermetic: never touch the real keychain.
    monkeypatch.setattr(
        package_release,
        "_detect_codesign_identity",
        lambda: "Developer ID Application: X (T)",
    )
    cfg = tmp_path / "c.toml"
    cfg.write_text(_NO_CODESIGN)
    c = package_release.load_config(cfg)
    assert c["codesign_identity"] == "Developer ID Application: X (T)"


def test_load_config_missing_key_raises(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('feed_url="https://h/a/appcast.xml"\n')
    with pytest.raises(SystemExit):
        package_release.load_config(cfg)


# ---------------------------------------------------------------------------
# _detect_codesign_identity (hermetic: fake `security find-identity` stdout)
# ---------------------------------------------------------------------------


def _fake_find_identity(stdout):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    return _run


def test_detect_codesign_none_raises(monkeypatch):
    monkeypatch.setattr(
        package_release.subprocess,
        "run",
        _fake_find_identity("  0 valid identities found\n"),
    )
    with pytest.raises(SystemExit, match="no 'Developer ID Application'"):
        package_release._detect_codesign_identity()


def test_detect_codesign_single_returns_it(monkeypatch):
    stdout = (
        "  1) ABC123 \"Developer ID Application: Acme Inc (T1234)\"\n"
        "     1 valid identities found\n"
    )
    monkeypatch.setattr(
        package_release.subprocess, "run", _fake_find_identity(stdout)
    )
    assert (
        package_release._detect_codesign_identity()
        == "Developer ID Application: Acme Inc (T1234)"
    )


def test_detect_codesign_multiple_raises(monkeypatch):
    stdout = (
        "  1) ABC \"Developer ID Application: Acme Inc (T1234)\"\n"
        "  2) DEF \"Developer ID Application: Beta LLC (T5678)\"\n"
        "     2 valid identities found\n"
    )
    monkeypatch.setattr(
        package_release.subprocess, "run", _fake_find_identity(stdout)
    )
    with pytest.raises(SystemExit) as exc:
        package_release._detect_codesign_identity()
    msg = str(exc.value)
    assert "multiple" in msg
    assert "codesign_identity" in msg
    assert "Acme Inc (T1234)" in msg
    assert "Beta LLC (T5678)" in msg


# ---------------------------------------------------------------------------
# stamp_and_inject (hermetic: capture plutil calls instead of touching a plist)
# ---------------------------------------------------------------------------


def test_stamp_and_inject_sets_hourly_check_interval(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        package_release.subprocess,
        "run",
        lambda argv, **kw: calls.append(argv),
    )
    cfg = {"feed_url": "https://h/a.xml", "public_ed_key": "k"}
    package_release.stamp_and_inject(tmp_path / "Teleport.app", "0.1.3", cfg)

    interval = next(
        c for c in calls if "SUScheduledCheckInterval" in c
    )
    assert interval[:4] == ["plutil", "-replace", "SUScheduledCheckInterval", "-integer"]
    assert interval[4] == "3600"
    assert package_release._CHECK_INTERVAL_SECONDS == 3600
