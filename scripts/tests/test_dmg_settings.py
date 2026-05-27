from pathlib import Path

import dmg_layout as L

SETTINGS = Path(__file__).resolve().parent.parent / "dmg_settings.py"


def _exec_settings(app="/tmp/Teleport.app"):
    # dmgbuild injects `defines`; emulate it so we can read the module's vars.
    g = {"defines": {"app": app, "icon": None, "background": None}}
    exec(compile(SETTINGS.read_text(), str(SETTINGS), "exec"), g)
    return g


def test_window_rect_matches_layout():
    g = _exec_settings()
    assert g["window_rect"][1] == (L.W, L.H)


def test_icon_size_matches_layout():
    g = _exec_settings()
    assert g["icon_size"] == L.ICON_SIZE


def test_text_size_matches_layout():
    g = _exec_settings()
    assert g["text_size"] == L.TEXT_SIZE


def test_icon_locations_match_layout():
    g = _exec_settings()
    assert g["icon_locations"]["Teleport.app"] == L.APP_CENTER
    assert g["icon_locations"][L.APPS_LABEL] == L.APPS_CENTER


def test_applications_label_is_hidden():
    g = _exec_settings()
    assert g["symlinks"] == {L.APPS_LABEL: "/Applications"}


def test_icon_view_and_ulmo_preserved():
    g = _exec_settings()
    assert g["default_view"] == "icon-view"
    assert g["format"] == "ULMO"
