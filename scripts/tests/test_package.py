import subprocess

import pytest

import _package


# ---------------------------------------------------------------------------
# version_plist_keys
# ---------------------------------------------------------------------------


def test_version_plist_keys_sets_both_version_fields():
    assert _package.version_plist_keys("0.1.3") == {
        "CFBundleShortVersionString": "0.1.3",
        "CFBundleVersion": "0.1.3",
    }


# ---------------------------------------------------------------------------
# detect_codesign_identity (hermetic: fake `security find-identity` stdout)
# ---------------------------------------------------------------------------


def _fake_find_identity(stdout):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    return _run


def test_detect_codesign_none_raises(monkeypatch):
    monkeypatch.setattr(_package.subprocess, "run",
                        _fake_find_identity("  0 valid identities found\n"))
    with pytest.raises(SystemExit, match="no 'Developer ID Application'"):
        _package.detect_codesign_identity()


def test_detect_codesign_single_returns_it(monkeypatch):
    stdout = (
        "  1) ABC123 \"Developer ID Application: Acme Inc (T1234)\"\n"
        "     1 valid identities found\n"
    )
    monkeypatch.setattr(_package.subprocess, "run", _fake_find_identity(stdout))
    assert (_package.detect_codesign_identity()
            == "Developer ID Application: Acme Inc (T1234)")


def test_detect_codesign_multiple_raises(monkeypatch):
    stdout = (
        "  1) ABC \"Developer ID Application: Acme Inc (T1234)\"\n"
        "  2) DEF \"Developer ID Application: Beta LLC (T5678)\"\n"
        "     2 valid identities found\n"
    )
    monkeypatch.setattr(_package.subprocess, "run", _fake_find_identity(stdout))
    with pytest.raises(SystemExit) as exc:
        _package.detect_codesign_identity()
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
    monkeypatch.setattr(_package.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    cfg = {"feed_url": "https://h/a.xml", "public_ed_key": "k"}
    _package.stamp_and_inject(tmp_path / "Teleport.app", "0.1.3", cfg)

    interval = next(c for c in calls if "SUScheduledCheckInterval" in c)
    assert interval[:4] == ["plutil", "-replace", "SUScheduledCheckInterval", "-integer"]
    assert interval[4] == "3600"
    assert _package._CHECK_INTERVAL_SECONDS == 3600


def test_stamp_and_inject_writes_all_plist_keys(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(_package.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    cfg = {"feed_url": "https://h/a.xml", "public_ed_key": "edkey"}
    _package.stamp_and_inject(tmp_path / "Teleport.app", "1.2.3", cfg)

    # Build a lookup {key: argv} for plutil -replace calls
    plist_calls = {
        c[2]: c
        for c in calls
        if len(c) == 6 and c[:2] == ["plutil", "-replace"]
    }

    expected_plist = str(tmp_path / "Teleport.app" / "Contents" / "Info.plist")

    for key, (typeflag, value) in {
        "CFBundleShortVersionString": ("-string", "1.2.3"),
        "CFBundleVersion": ("-string", "1.2.3"),
        "SUFeedURL": ("-string", "https://h/a.xml"),
        "SUPublicEDKey": ("-string", "edkey"),
        "SUEnableAutomaticChecks": ("-bool", "YES"),
        "SUScheduledCheckInterval": ("-integer", "3600"),
    }.items():
        assert key in plist_calls, f"missing plutil call for {key}"
        argv = plist_calls[key]
        assert argv[3] == typeflag, f"{key}: expected type flag {typeflag!r}, got {argv[3]!r}"
        assert argv[4] == value, f"{key}: expected value {value!r}, got {argv[4]!r}"
        assert argv[5].endswith("Teleport.app/Contents/Info.plist"), (
            f"{key}: plist path {argv[5]!r} does not end with expected suffix"
        )
