import pytest

import _build


def test_resolve_dev():
    ch = _build.resolve_channel("dev")
    assert ch.name == "dev"
    assert ch.out == "out/mac/arm64/dev"
    assert ch.distributable is False
    assert ch.targets == ("chrome",)


def test_resolve_dogfood():
    ch = _build.resolve_channel("dogfood")
    assert ch.distributable is True
    assert ch.out == "out/mac/arm64/release"
    assert ch.targets == ("chrome", "chrome/installer/mac")


def test_resolve_unknown_raises():
    with pytest.raises(SystemExit, match="unknown channel"):
        _build.resolve_channel("beta")


def test_build_runs_autoninja(monkeypatch):
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: "/fake/src")
    ch = _build.resolve_channel("dogfood")
    _build.build("out/x", ch)
    argv, kw = calls[0]
    assert argv == ["autoninja", "-C", "out/x", "chrome", "chrome/installer/mac"]
    assert str(kw["cwd"]) == "/fake/src"
    assert kw["check"] is True
