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
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: "release")
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
# by a one-off `gn gen ... teleport_deployment_env="dev"` override
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
# an explicit teleport_deployment_env override for TD-026.

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
        'teleport_deployment_env = "release"\n')  # nonsensical for dev, but dev ships nothing
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
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: 'release')
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("canary"), distributing=True)


def test_assert_release_endpoints_consistent_passes_when_explicit_override_matches_template(
        tmp_path, monkeypatch):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_deployment_env = "release"\n')  # matches the real template
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: 'release')
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
        'teleport_deployment_env = "dev"\n')  # the TD-026 workaround, left behind
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: 'dev')
    with pytest.raises(SystemExit, match="teleport_deployment_env"):
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
        'teleport_deployment_env = "dev"\n')
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: 'dev')
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("canary"), distributing=False)  # must not raise
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "teleport_deployment_env" in out
    assert "'dev'" in out and "'release'" in out  # names the specific override found and expected
    assert "must not be published" in out.lower()


def test_ensure_gn_gen_raises_instead_of_no_op_when_distributing_and_args_gn_is_stale(
        tmp_path, monkeypatch):
    """The actual reachable path: ensure_gn_gen's args.gn-exists branch must
    run the guard, not just skip straight to the no-op it used to be."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_deployment_env = "dev"\n')
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: 'dev')
    with pytest.raises(SystemExit):
        _build.ensure_gn_gen("out/x", _build.resolve_channel("canary"), distributing=True)
    assert calls == []  # must fail before ever shelling out


def test_ensure_gn_gen_warns_and_no_ops_when_not_distributing_and_args_gn_is_stale(
        tmp_path, monkeypatch, capsys):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_deployment_env = "dev"\n')
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: 'dev')
    _build.ensure_gn_gen("out/x", _build.resolve_channel("canary"), distributing=False)
    assert calls == []  # args.gn already exists -- no gn gen, no autoninja
    assert "WARNING" in capsys.readouterr().out


# --- Effective-value guard (replaces text matching) ------------------------
#
# The old guard read args.gn as text. Text cannot see through an import() chain,
# and a normal `gn gen` writes args.gn containing exactly ONE import line -- so
# the matcher found nothing to compare and returned early. The check that exists
# to stop a mismatched build reaching sign -> notarize -> upload -> tag was
# therefore passing everything. These tests pin the replacement.

class _Done:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.returncode = 0


def test_effective_gn_arg_parses_a_string_value(monkeypatch):
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda *a, **k: _Done('teleport_deployment_env = "staging"\n'))
    assert _build.effective_gn_arg("out/x", "teleport_deployment_env") == "staging"


def test_effective_gn_arg_parses_a_bool_value(monkeypatch):
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda *a, **k: _Done("teleport_policy_key_placeholder_ack = true\n"))
    assert _build.effective_gn_arg(
        "out/x", "teleport_policy_key_placeholder_ack") == "true"


def test_effective_gn_arg_treats_unknown_arg_as_absent(monkeypatch):
    """gn prints an ERROR banner and still exits 0 for an unknown argument, so
    the parser validates the returned shape instead of trusting the exit code."""
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda *a, **k: _Done("ERROR Unknown build argument.\n"))
    assert _build.effective_gn_arg("out/x", "no_such_arg") is None


def test_effective_gn_arg_rejects_a_mismatched_name(monkeypatch):
    """Defensive: never accept a value that belongs to a different argument."""
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda *a, **k: _Done('some_other_arg = "staging"\n'))
    assert _build.effective_gn_arg("out/x", "teleport_deployment_env") is None


def test_guard_catches_import_only_args_gn_pointing_at_another_env(
        tmp_path, monkeypatch):
    """The case the text matcher could not see at all: args.gn holds only an
    import line, and that template is the wrong environment for this channel."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/staging.mac.gn")\n')
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: "staging")
    with pytest.raises(SystemExit, match="teleport_deployment_env"):
        _build.assert_release_endpoints_consistent(
            "out/x", _build.resolve_channel("canary"), distributing=True)


def test_guard_passes_when_effective_env_matches_the_channel(tmp_path, monkeypatch):
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n')
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: "release")
    _build.assert_release_endpoints_consistent(
        "out/x", _build.resolve_channel("canary"), distributing=True)


def test_staging_channel_is_registered_and_distributable():
    ch = _build.resolve_channel("staging")
    assert ch.gn_args == "staging.mac.gn"
    assert ch.distributable
    assert ch.out != _build.resolve_channel("canary").out  # separate ninja graph


def test_guard_refuses_when_gn_cannot_resolve_the_env(tmp_path, monkeypatch):
    """An unresolvable out dir must be refused, not waved through. 'We cannot
    tell what this bakes' is the one state where signing and publishing it is
    least defensible, so it cannot share the early-return path with 'nothing to
    compare'."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text("# hand-written, never gn-gen'd\n")
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg", lambda out, arg: None)
    with pytest.raises(SystemExit, match="could not resolve"):
        _build.assert_release_endpoints_consistent(
            "out/x", _build.resolve_channel("canary"), distributing=True)


# --- Windows portability: tool resolution + vendored gn path --------------

@pytest.fixture(autouse=True)
def _identity_depot_tool(monkeypatch):
    """Every gn/autoninja assertion in this module names the LOGICAL tool. In
    production _build resolves that name through _lib.depot_tool, which returns
    an absolute path (gn.bat / autoninja.bat on Windows). Stubbing it to identity
    keeps those assertions about argv SHAPE rather than about where depot_tools
    happens to be installed on the machine running the tests -- the resolution
    itself is covered by the test below."""
    monkeypatch.setattr(_build, "depot_tool", lambda name: name)


def test_gn_gen_and_autoninja_resolve_through_depot_tool(tmp_path, monkeypatch):
    """Both call sites must go through depot_tool(). A bare name reaches
    CreateProcess on Windows, which only appends .exe and never consults
    PATHEXT, so it selects depot_tools' extensionless POSIX script and fails as
    "not a valid Win32 application"."""
    asked = []
    monkeypatch.setattr(_build, "depot_tool",
                        lambda name: (asked.append(name), f"/dt/{name}")[1])
    calls = []
    monkeypatch.setattr(_build.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    _build.build("out/x", _build.resolve_channel("dev"), distributing=False)
    assert asked == ["gn", "autoninja"]
    assert [argv[0] for argv, _ in calls] == ["/dt/gn", "/dt/autoninja"]


def test_gn_bin_follows_the_host_not_a_hardcoded_mac_path(tmp_path, monkeypatch):
    """buildtools/<host>/gn -- keyed on the HOST, since gn is the tool being run,
    not the thing being built. Hardcoding mac here did not merely fail off macOS,
    it failed QUIETLY: effective_gn_arg catches the OSError from a missing binary
    and returns None, and assert_release_endpoints_consistent reads None as
    "cannot establish what this out dir bakes" -- refusing the build with a
    message about a stale args.gn that is not in fact the problem."""
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    for platform, rel in [("win32", ("win", "gn.exe")),
                          ("darwin", ("mac", "gn")),
                          ("linux", ("linux64", "gn"))]:
        monkeypatch.setattr(_build.sys, "platform", platform)
        assert _build.gn_bin() == tmp_path / "buildtools" / rel[0] / rel[1]


def test_gn_bin_rejects_an_unknown_host(tmp_path, monkeypatch):
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build.sys, "platform", "aix")
    with pytest.raises(RuntimeError, match="aix"):
        _build.gn_bin()
