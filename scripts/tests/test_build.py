import pytest

import _build


def test_resolve_dev():
    ch = _build.resolve_channel("dev")
    assert ch.name == "dev"
    assert ch.out == "out/mac/arm64/dev"
    assert ch.distributable is False
    assert ch.targets == ("chrome",)
    assert ch.gn_args == "dev.mac.gn"


def test_resolve_canary():
    ch = _build.resolve_channel("canary")
    assert ch.name == "canary"
    assert ch.distributable is True
    assert ch.out == "out/mac/arm64/release"
    assert ch.targets == ("chrome", "chrome/installer/mac")
    assert ch.gn_args == "release.mac.gn"


def test_resolve_unknown_raises():
    with pytest.raises(SystemExit, match="unknown channel"):
        _build.resolve_channel("beta")


def test_ensure_gn_gen_noop_when_args_gn_exists(tmp_path, monkeypatch):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text('import("//teleport/gn/args/dev.mac.gn")\n')
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.ensure_gn_gen("out/x", _build.resolve_channel("dev"))
    assert calls == []


def test_ensure_gn_gen_runs_gn_gen_when_args_gn_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.ensure_gn_gen("out/x", _build.resolve_channel("dev"))
    argv, kw = calls[0]
    assert argv == ["gn", "gen", "out/x",
                    '--args=import("//teleport/gn/args/dev.mac.gn")']
    assert kw["cwd"] == tmp_path
    assert kw["check"] is True


def test_ensure_gn_gen_uses_channel_gn_args(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.ensure_gn_gen("out/x", _build.resolve_channel("canary"))
    argv, _ = calls[0]
    assert argv == ["gn", "gen", "out/x",
                    '--args=import("//teleport/gn/args/release.mac.gn")']


def test_build_runs_autoninja_only_when_args_gn_exists(tmp_path, monkeypatch):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text('import("//teleport/gn/args/release.mac.gn")\n')
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    ch = _build.resolve_channel("canary")
    _build.build("out/x", ch)
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv == ["autoninja", "-C", "out/x", "chrome", "chrome/installer/mac"]
    assert kw["cwd"] == tmp_path
    assert kw["check"] is True


def test_build_gn_gens_first_when_args_gn_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    ch = _build.resolve_channel("dev")
    _build.build("out/x", ch)
    assert [argv[0] for argv, _ in calls] == ["gn", "autoninja"]
    assert calls[0][0] == ["gn", "gen", "out/x",
                           '--args=import("//teleport/gn/args/dev.mac.gn")']
