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
    _build.ensure_gn_gen("out/x", _build.resolve_channel("dev"), distributing=False)
    assert calls == []


def test_ensure_gn_gen_runs_gn_gen_when_args_gn_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.ensure_gn_gen("out/x", _build.resolve_channel("dev"), distributing=False)
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
    _build.ensure_gn_gen("out/x", _build.resolve_channel("canary"), distributing=True)
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
    _build.build("out/x", ch, distributing=True)
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
    _build.build("out/x", ch, distributing=False)
    assert [argv[0] for argv, _ in calls] == ["gn", "autoninja"]
    assert calls[0][0] == ["gn", "gen", "out/x",
                           '--args=import("//teleport/gn/args/dev.mac.gn")']


def test_build_requires_distributing_keyword(tmp_path, monkeypatch):
    """distributing has no default anywhere in this chain -- a call site must
    always state intent explicitly, so a future refactor cannot silently
    regress a real --distribute run to the warn-only branch by omitting it."""
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    with pytest.raises(TypeError):
        _build.build("out/x", _build.resolve_channel("dev"))  # missing distributing
    with pytest.raises(TypeError):
        _build.ensure_gn_gen("out/x", _build.resolve_channel("dev"))  # missing distributing


# --- Regression coverage for the stale-args.gn distribution trap (F6) ------
#
# ensure_gn_gen() is a no-op whenever <out>/args.gn already exists (that's
# the whole point -- ninja re-gens on its own). A stale args.gn left behind
# by a one-off `gn gen ... teleport_use_release_endpoints=false` override
# (used to work around TD-026's KMS fail-closed assert) would otherwise
# persist silently into every future package.py run against that out dir,
# including `--channel canary --distribute`, and nothing else checks it:
# assert_baked_version only looks at the version string.
#
# The guard fires on DISTRIBUTION INTENT (the `distributing` keyword), not on
# channel distributability alone: distributing=True + a mismatch is a hard
# SystemExit (the hazard this guard exists to close, and must never be
# weakened); distributing=False + a mismatch is a printed warning that lets a
# non-distributing verification run (--skip-build, which already hard-refuses
# --distribute) proceed against an out dir that was truthfully gn-gen'd with
# an explicit teleport_use_release_endpoints override for TD-026.

def test_assert_release_endpoints_consistent_noop_when_args_gn_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("canary"), distributing=True)
    # must not raise -- ensure_gn_gen will seed it fresh right after this


def test_assert_release_endpoints_consistent_noop_for_non_distributable_channel(
        tmp_path, monkeypatch):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/dev.mac.gn")\n'
        'teleport_use_release_endpoints = true\n')  # nonsensical for dev, but dev ships nothing
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("dev"), distributing=True)
    # must not raise -- dev has no shipped-artifact risk, even under distributing=True
    # (unreachable in practice: package.py refuses --distribute for a non-distributable
    # channel before this could ever be called that way)


def test_assert_release_endpoints_consistent_passes_when_args_gn_has_no_override(
        tmp_path, monkeypatch):
    """The normal shape of a real args.gn generated by this codebase's own
    `gn gen ... --args='import(...)'` with no extra override appended: just
    the import line. Nothing in args.gn's own text to contradict the
    template, so it is trusted rather than flagged."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n')
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("canary"), distributing=True)


def test_assert_release_endpoints_consistent_passes_when_explicit_override_matches_template(
        tmp_path, monkeypatch):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_use_release_endpoints = true\n')  # matches the real template
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("canary"), distributing=True)


def test_assert_release_endpoints_consistent_raises_when_distributing_and_override_is_stale(
        tmp_path, monkeypatch):
    """Pin: the --distribute refusal must never be weakened. A future refactor
    that quietly widens this allowance (e.g. defaulting distributing to False,
    or downgrading this branch to a warning) breaks this test."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_use_release_endpoints = false\n')  # the TD-026 workaround, left behind
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    with pytest.raises(SystemExit, match="teleport_use_release_endpoints"):
        _build.assert_release_endpoints_consistent(
            "out/x", _build.resolve_channel("canary"), distributing=True)


def test_assert_release_endpoints_consistent_warns_but_proceeds_when_not_distributing(
        tmp_path, monkeypatch, capsys):
    """The new allowance: a non-distributing run (e.g. --skip-build, which
    already hard-refuses --distribute) against the exact same stale override
    must NOT raise -- it must print a warning naming the override and stating
    the artifact must not be published, then return normally."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_use_release_endpoints = false\n')
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("canary"), distributing=False)  # must not raise
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "teleport_use_release_endpoints" in out
    assert "false" in out and "true" in out  # names the specific override found and expected
    assert "must not be published" in out.lower()


def test_ensure_gn_gen_raises_instead_of_no_op_when_distributing_and_args_gn_is_stale(
        tmp_path, monkeypatch):
    """The actual reachable path: ensure_gn_gen's args.gn-exists branch must
    run the guard, not just skip straight to the no-op it used to be."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_use_release_endpoints = false\n')
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    with pytest.raises(SystemExit):
        _build.ensure_gn_gen("out/x", _build.resolve_channel("canary"), distributing=True)
    assert calls == []  # must fail before ever shelling out


def test_ensure_gn_gen_warns_and_no_ops_when_not_distributing_and_args_gn_is_stale(
        tmp_path, monkeypatch, capsys):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_use_release_endpoints = false\n')
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.ensure_gn_gen("out/x", _build.resolve_channel("canary"), distributing=False)
    assert calls == []  # args.gn already exists -- no gn gen, no autoninja
    assert "WARNING" in capsys.readouterr().out
