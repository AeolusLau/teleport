import sys
from pathlib import Path

import pytest

import _package_state as ps


def _make_app(root: Path) -> Path:
    app = root / "Teleport.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Teleport").write_bytes(b"\x00binary\x01")
    (app / "Contents" / "Info.plist").write_text("<plist/>")
    return app


def test_app_content_digest_is_stable(tmp_path):
    app = _make_app(tmp_path)
    assert ps.app_content_digest(app) == ps.app_content_digest(app)


def test_app_content_digest_changes_on_content_change(tmp_path):
    app = _make_app(tmp_path)
    d1 = ps.app_content_digest(app)
    (app / "Contents" / "Info.plist").write_text("<plist><k/></plist>")
    assert ps.app_content_digest(app) != d1


def test_app_content_digest_changes_on_new_file(tmp_path):
    app = _make_app(tmp_path)
    d1 = ps.app_content_digest(app)
    (app / "Contents" / "extra.txt").write_text("x")
    assert ps.app_content_digest(app) != d1


def test_app_content_digest_changes_on_rename(tmp_path):
    app = _make_app(tmp_path)
    d1 = ps.app_content_digest(app)
    (app / "Contents" / "Info.plist").rename(app / "Contents" / "Info2.plist")
    assert ps.app_content_digest(app) != d1


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Exercises the Versions/Current symlink inside a macOS .app bundle. "
           "Creating a file symlink on Windows needs SeCreateSymbolicLinkPrivilege "
           "(Developer Mode or elevation), and there is no .app to fingerprint "
           "there anyway -- the packaging path this covers is macOS-only.")
def test_app_content_digest_reflects_symlink_target(tmp_path):
    app = _make_app(tmp_path)
    link = app / "Contents" / "Current"
    link.symlink_to("A")
    d1 = ps.app_content_digest(app)
    link.unlink()
    link.symlink_to("B")  # repoint without following
    assert ps.app_content_digest(app) != d1


def test_state_path_is_outside_trimmed_updates_dir(tmp_path):
    p = ps.state_path(tmp_path, "canary")
    assert p == tmp_path / "dist" / ".package-state" / "canary.json"
    assert (tmp_path / "dist" / "canary") not in p.parents


def test_write_then_load_state_roundtrip(tmp_path):
    p = ps.state_path(tmp_path, "canary")
    key = ps.reuse_key("1.2.3", "canary", "Developer ID Application: X (T)", "prof", "deadbeef")
    ps.write_state(p, key, "TeleportCanary-1.2.3.dmg")
    assert ps.load_state(p) == {**key, "dmg_name": "TeleportCanary-1.2.3.dmg"}


def test_load_state_missing_returns_none(tmp_path):
    assert ps.load_state(tmp_path / "nope.json") is None


def _key():
    return ps.reuse_key("1.2.3", "canary", "Developer ID Application: X (T)", "prof", "deadbeef")


def test_can_reuse_true_when_key_matches_and_dmg_exists(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"
    dmg.write_text("d")
    assert ps.can_reuse({**_key(), "dmg_name": dmg.name}, _key(), dmg) is True


def test_can_reuse_false_when_state_none(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"
    dmg.write_text("d")
    assert ps.can_reuse(None, _key(), dmg) is False


def test_can_reuse_false_when_digest_differs(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"
    dmg.write_text("d")
    state = {**_key(), "dmg_name": dmg.name}
    other = ps.reuse_key("1.2.3", "canary", "Developer ID Application: X (T)", "prof", "OTHER")
    assert ps.can_reuse(state, other, dmg) is False


def test_can_reuse_false_when_identity_differs(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"
    dmg.write_text("d")
    state = {**_key(), "dmg_name": dmg.name}
    other = ps.reuse_key("1.2.3", "canary", "Developer ID Application: Y (T)", "prof", "deadbeef")
    assert ps.can_reuse(state, other, dmg) is False


def test_can_reuse_false_when_dmg_name_differs(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"
    dmg.write_text("d")
    assert ps.can_reuse({**_key(), "dmg_name": "TeleportCanary-9.9.9.dmg"}, _key(), dmg) is False


def test_can_reuse_false_when_dmg_missing(tmp_path):
    dmg = tmp_path / "TeleportCanary-1.2.3.dmg"  # not created
    assert ps.can_reuse({**_key(), "dmg_name": dmg.name}, _key(), dmg) is False
