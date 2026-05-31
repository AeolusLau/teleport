import subprocess
from pathlib import Path

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
    _package.stamp_and_inject(tmp_path / "Teleport.app", "0.1.3", cfg, "canary")

    interval = next(c for c in calls if "SUScheduledCheckInterval" in c)
    assert interval[:4] == ["plutil", "-replace", "SUScheduledCheckInterval", "-integer"]
    assert interval[4] == "3600"
    assert _package._CHECK_INTERVAL_SECONDS == 3600


def test_stamp_and_inject_writes_all_plist_keys(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(_package.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    cfg = {"feed_url": "https://h/a.xml", "public_ed_key": "edkey"}
    _package.stamp_and_inject(tmp_path / "Teleport.app", "1.2.3", cfg, "canary")

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
        "TeleportChannel": ("-string", "canary"),
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


# ---------------------------------------------------------------------------
# sparkle_plist_string_keys
# ---------------------------------------------------------------------------


def test_sparkle_plist_string_keys_includes_channel_marker():
    cfg = {"feed_url": "https://h/appcast.xml", "public_ed_key": "k"}
    keys = _package.sparkle_plist_string_keys("0.1.5", cfg, "canary")
    assert keys["TeleportChannel"] == "canary"
    assert keys["CFBundleShortVersionString"] == "0.1.5"
    assert keys["CFBundleVersion"] == "0.1.5"
    assert keys["SUFeedURL"] == "https://h/appcast.xml"
    assert keys["SUPublicEDKey"] == "k"


# ---------------------------------------------------------------------------
# _find_signed_app (glob widened for channel-customized output dirs)
# ---------------------------------------------------------------------------


def _touch_app(root: Path, rel: str) -> Path:
    app = root / rel
    (app / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    return app


def test_find_signed_app_legacy_stable_layout(tmp_path):
    # Pre-side-by-side canary signed into <output>/stable/Teleport.app
    want = _touch_app(tmp_path, "stable/Teleport.app")
    assert _package._find_signed_app(tmp_path) == want


def test_find_signed_app_channel_layout_with_space(tmp_path):
    # Side-by-side canary: the signing engine names the intermediate dir
    # sxs-<channel>-<Fragment>-<product_dirname>-<creator_code> and renames the
    # app with a space (pipeline.py:551-569). The glob is one level deep, so the
    # exact dir spelling does not matter — only that it matches "Teleport*.app".
    want = _touch_app(
        tmp_path, "sxs-canary-Canary-Teleport Canary-Cr24/Teleport Canary.app")
    assert _package._find_signed_app(tmp_path) == want


def test_find_signed_app_top_level(tmp_path):
    want = _touch_app(tmp_path, "Teleport.app")
    assert _package._find_signed_app(tmp_path) == want


# ---------------------------------------------------------------------------
# stage_channel_icons (copy built icons to channel-named files for the engine)
# ---------------------------------------------------------------------------


def _make_built_app(tmp_path) -> Path:
    out = tmp_path / "release"
    res = out / "Teleport.app" / "Contents" / "Resources"
    res.mkdir(parents=True)
    (res / "app.icns").write_bytes(b"ICNS-DATA")
    (res / "Assets.car").write_bytes(b"CAR-DATA")
    (out / "Teleport Packaging").mkdir()
    return out / "Teleport.app"


def test_stage_channel_icons_copies_with_channel_names(tmp_path):
    app = _make_built_app(tmp_path)
    _package.stage_channel_icons(app, "canary")
    pkg = app.parent / "Teleport Packaging"
    assert (pkg / "app_canary.icns").read_bytes() == b"ICNS-DATA"
    assert (pkg / "Assets_canary.car").read_bytes() == b"CAR-DATA"


def test_stage_channel_icons_noop_for_base_channel(tmp_path):
    app = _make_built_app(tmp_path)
    _package.stage_channel_icons(app, "stable")
    _package.stage_channel_icons(app, "")
    pkg = app.parent / "Teleport Packaging"
    assert list(pkg.iterdir()) == []  # nothing staged for the base channel


# ---------------------------------------------------------------------------
# sign_app injects TELEPORT_SIGN_CHANNEL for channel-customized runs
# ---------------------------------------------------------------------------


def _capture_sign_run(monkeypatch):
    captured = {}

    def _run(argv, **kw):
        captured["argv"] = argv
        captured["env"] = kw.get("env")
        return None

    monkeypatch.setattr(_package.subprocess, "run", _run)
    return captured


def test_sign_app_sets_channel_env(monkeypatch, tmp_path):
    captured = _capture_sign_run(monkeypatch)
    app = tmp_path / "out" / "Teleport.app"
    app.mkdir(parents=True)
    _package.sign_app(app, tmp_path / "dist" / "canary", "ident", "canary")
    assert captured["env"]["TELEPORT_SIGN_CHANNEL"] == "canary"


def test_sign_app_omits_channel_env_for_base(monkeypatch, tmp_path):
    captured = _capture_sign_run(monkeypatch)
    app = tmp_path / "out" / "Teleport.app"
    app.mkdir(parents=True)
    _package.sign_app(app, tmp_path / "dist" / "stable", "ident", "stable")
    assert "TELEPORT_SIGN_CHANNEL" not in (captured["env"] or {})


def test_sign_app_default_channel_is_base(monkeypatch, tmp_path):
    captured = _capture_sign_run(monkeypatch)
    app = tmp_path / "out" / "Teleport.app"
    app.mkdir(parents=True)
    _package.sign_app(app, tmp_path / "dist" / "x", "ident")  # no channel arg
    assert "TELEPORT_SIGN_CHANNEL" not in (captured["env"] or {})


# ---------------------------------------------------------------------------
# dmg_names (channel-suffixed dmg file name + mounted volume name)
# ---------------------------------------------------------------------------


def test_dmg_names_base_channel_is_bare_teleport():
    assert _package.dmg_names("") == ("Teleport", "Teleport")
    assert _package.dmg_names("stable") == ("Teleport", "Teleport")


def test_dmg_names_canary_file_is_spaceless_volume_has_space():
    # File name mirrors Chrome's GoogleChromeCanary (no space); the mounted
    # volume keeps the space to match the renamed Teleport Canary.app.
    assert _package.dmg_names("canary") == ("TeleportCanary", "Teleport Canary")


def test_dmg_names_beta():
    assert _package.dmg_names("beta") == ("TeleportBeta", "Teleport Beta")


def test_build_styled_dmg_uses_channel_names(monkeypatch, tmp_path):
    # The signed app the engine produced for canary, under a channel subdir.
    signed = tmp_path / "sxs-canary-Canary-Teleport Canary-Cr24" / "Teleport Canary.app"
    (signed / "Contents" / "Resources").mkdir(parents=True)

    calls = []
    monkeypatch.setattr(_package.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))

    dmg = _package.build_styled_dmg(tmp_path, "1.2.3", "ident", "profile", "canary")

    # dmg file name is space-free + channel-suffixed
    assert dmg == tmp_path / "TeleportCanary-1.2.3.dmg"
    # the dmgbuild invocation passes the spaced volume name as its positional arg
    dmgbuild_call = next(c for c in calls if any("dmgbuild" in str(p) for p in c))
    assert "Teleport Canary" in dmgbuild_call
    assert dmgbuild_call[-1] == str(dmg)


def test_build_styled_dmg_base_channel_stays_bare(monkeypatch, tmp_path):
    signed = tmp_path / "stable" / "Teleport.app"
    (signed / "Contents" / "Resources").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(_package.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))

    dmg = _package.build_styled_dmg(tmp_path, "1.2.3", "ident", "profile")  # no channel

    assert dmg == tmp_path / "Teleport-1.2.3.dmg"
    dmgbuild_call = next(c for c in calls if any("dmgbuild" in str(p) for p in c))
    assert "Teleport" in dmgbuild_call and "Teleport Canary" not in dmgbuild_call
