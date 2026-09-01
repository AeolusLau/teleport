import re
from pathlib import Path

import pytest

import package


def test_distribute_on_dev_raises(monkeypatch):
    # read_teleport_version reads the repo TELEPORT_VERSION; stub for hermeticity.
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    with pytest.raises(SystemExit, match="not distributable"):
        package.main(["--channel", "dev", "--distribute"])


def test_unknown_channel_raises(monkeypatch):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    with pytest.raises(SystemExit, match="unknown channel"):
        package.main(["--channel", "beta"])


def test_dev_dry_run_does_not_build(monkeypatch, capsys):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    called = []
    monkeypatch.setattr(package, "build", lambda *a, **k: called.append(a))
    rc = package.main(["--dry-run"])  # default channel = dev
    assert rc == 0
    assert called == []  # dry-run must not build
    assert "DRY RUN" in capsys.readouterr().out


def test_dev_build_invokes_build_only(monkeypatch, capsys):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    calls = []
    monkeypatch.setattr(package, "build",
                        lambda out, ch, distributing: calls.append((out, ch.name, distributing)))
    monkeypatch.setattr(package._package, "assert_baked_version",
                        lambda app, v: calls.append(("assert_baked_version", v)))
    rc = package.main([])  # default channel = dev, no distribute
    assert rc == 0
    assert ("out/mac/arm64/dev", "dev", False) in calls
    assert ("assert_baked_version", "9.9.9") in calls


def test_dev_build_asserts_baked_version_after_build(monkeypatch, capsys):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "0.1.3")
    order = []
    monkeypatch.setattr(package, "build",
                        lambda out, ch, distributing: order.append(("build", ch.name)))
    monkeypatch.setattr(package._package, "assert_baked_version",
                        lambda app, v: order.append(("assert_baked_version", v)))
    rc = package.main([])
    assert rc == 0
    assert order.index(("build", "dev")) < order.index(("assert_baked_version", "0.1.3"))
    out = capsys.readouterr().out
    assert "0.1.3" in out


def _stub_distributable(monkeypatch, order, *, distribute):
    """Stub every side-effecting call package.main makes for a canary run,
    recording call order. Returns nothing; assertions live in the test."""
    monkeypatch.setattr(package, "read_teleport_version", lambda: "1.2.3")
    monkeypatch.setattr(package._config, "assert_channel_keys_distinct", lambda p: None)
    monkeypatch.setattr(package._config, "assert_channel_urls_self_consistent", lambda p, c: None)
    monkeypatch.setattr(package, "build",
                        lambda out, ch, distributing: order.append(
                            ("build", out, ch.name, distributing)))
    cfg = {
        "public_ed_key": "k", "ed_key_account": "ed25519", "feed_url": "https://h/appcast.xml",
        "notary_profile": "p", "codesign_identity": "Developer ID Application: X (T)",
        "download_base_url": "https://h/dl/", "oss_upload_target": "oss://b/x/",
        "oss_endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
        "oss_region": "cn-hangzhou",
        "git_remote": "origin",
    }
    monkeypatch.setattr(package._config, "load_channel_config", lambda path, ch: dict(cfg))
    # Must be stubbed: effective_gn_arg shells out to `gn args <out>` against the
    # REAL checkout. Left unstubbed, these tests read whatever the developer last
    # generated -- and a release out dir produced through the placeholder-key
    # escape hatch (which every baseline upgrade's G5 creates) makes package.main
    # correctly refuse to --distribute, failing six tests that are not about that
    # guard at all. The guard has its own coverage in
    # test_distribute_refuses_a_placeholder_ack_build, which stubs this to "true".
    monkeypatch.setattr(package._build, "effective_gn_arg",
                        lambda out, arg: None if "placeholder_ack" in arg
                        else "release")
    monkeypatch.setattr(package._package, "assert_baked_version",
                        lambda app, v: order.append(("assert_baked_version", v)))
    monkeypatch.setattr(package._package, "inject_sparkle_keys",
                        lambda app, c, ch: order.append(("inject_sparkle_keys", ch)))
    # Both stamps shell out to plutil against a real Info.plist; these tests use
    # a fake app bundle, so record the calls instead of performing them.
    monkeypatch.setattr(package._package, "stamp_source_revision",
                        lambda app: order.append(("stamp_source_revision",)) or "abc123")
    monkeypatch.setattr(package._package, "stamp_unpublishable",
                        lambda app, out: False)
    monkeypatch.setattr(package._package, "stage_channel_icons",
                        lambda app, ch: order.append(("stage_icons", ch)))
    monkeypatch.setattr(package._package, "sign_app",
                        lambda app, ud, ident, ch: order.append(("sign", ident, ch)))

    monkeypatch.setattr(package._package, "build_styled_dmg",
                        lambda ud, v, ident, notary, ch: (order.append(("dmg", v, ch)) or Path("/tmp/Teleport-1.2.3.dmg")))
    monkeypatch.setattr(package._publish, "assert_on_main",
                        lambda: order.append(("assert_on_main",)))
    monkeypatch.setattr(package._publish, "assert_clean_tree",
                        lambda: order.append(("assert_clean_tree",)))
    monkeypatch.setattr(package._publish, "fetch_live_appcast", lambda url: None)
    monkeypatch.setattr(package._publish, "assert_not_published",
                        lambda v, ch, xml: order.append(("assert_not_published", v, ch)))
    monkeypatch.setattr(package._publish, "generate_appcast",
                        lambda ud, base, keep, acct: order.append(("generate_appcast", keep, acct)))
    monkeypatch.setattr(package._publish, "upload_to_oss",
                        lambda ud, target, ep, rg: order.append(("upload", target)))
    monkeypatch.setattr(package._publish, "tag_and_push",
                        lambda v, ch, remote: order.append(("tag_and_push", v, ch, remote)))

    # package-state cache: default to "no reuse" so existing tests are unaffected.
    monkeypatch.setattr(package._package_state, "app_content_digest",
                        lambda app: "DIGEST")
    monkeypatch.setattr(package._package_state, "load_state", lambda p: None)
    monkeypatch.setattr(package._package_state, "write_state",
                        lambda p, key, dmg: order.append(("write_state", dmg)))
    monkeypatch.setattr(package._package_state, "can_reuse",
                        lambda state, key, dmg: False)
    monkeypatch.setattr(package._package, "stapler_validate",
                        lambda dmg: order.append(("stapler_validate", getattr(dmg, "name", str(dmg)))) or True)
    monkeypatch.setattr(package._package, "target_dmg_path",
                        lambda ud, v, ch: Path(f"/tmp/Teleport-{v}.dmg"))


def test_distribute_runs_guards_before_build_and_tags_after_upload(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    rc = package.main(["--channel", "canary", "--distribute"])
    assert rc == 0
    names = [c[0] for c in order]
    # fail-fast: all three guards precede the build
    assert names.index("assert_on_main") < names.index("build")
    assert names.index("assert_clean_tree") < names.index("build")
    # pipeline order: assert_baked_version and inject_sparkle_keys both precede sign
    assert names.index("build") < names.index("assert_baked_version") < names.index("sign") < names.index("dmg")
    assert names.index("inject_sparkle_keys") < names.index("sign")
    # tag strictly after upload; appcast uses the dmg name as keep
    assert names.index("upload") < names.index("tag_and_push")
    assert ("generate_appcast", "Teleport-1.2.3.dmg", "ed25519") in order
    assert ("tag_and_push", "1.2.3", "canary", "origin") in order
    assert ("assert_baked_version", "1.2.3") in order
    assert ("inject_sparkle_keys", "canary") in order
    assert ("build", "out/mac/arm64/release", "canary", True) in order  # distributing=True forwarded
    assert "published 1.2.3 (canary)" in capsys.readouterr().out


def test_distribute_local_without_publish_stops_after_dmg(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=False)
    rc = package.main(["--channel", "canary"])  # no --distribute
    assert rc == 0
    names = [c[0] for c in order]
    assert "dmg" in names
    assert "upload" not in names and "tag_and_push" not in names
    assert ("build", "out/mac/arm64/release", "canary", False) in order  # distributing=False forwarded
    assert "not published" in capsys.readouterr().out


def test_canary_distribute_dry_run_has_no_side_effects(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    # If any guard/build/network stub fires, it appends to order — must stay empty.
    rc = package.main(["--channel", "canary", "--distribute", "--dry-run"])
    assert rc == 0
    assert order == []  # dry-run did not build, guard, fetch, sign, tag, or upload
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "git tag -a v1.2.3" in out  # publish steps shown in the plan


def test_distribute_passes_channel_to_sign_and_stages_icons(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    rc = package.main(["--channel", "canary", "--distribute"])
    assert rc == 0
    # icons staged before signing, both for the canary channel
    names = [c[0] for c in order]
    assert names.index("stage_icons") < names.index("sign")
    assert ("stage_icons", "canary") in order
    assert ("sign", "Developer ID Application: X (T)", "canary") in order


def test_reuse_skips_sign_and_dmg_when_app_unchanged(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    rc = package.main(["--channel", "canary", "--distribute"])
    assert rc == 0
    names = [c[0] for c in order]
    assert "sign" not in names and "dmg" not in names      # skipped
    assert "write_state" not in names                       # nothing new to record
    assert "upload" in names and "tag_and_push" in names    # still publishes
    assert "reusing notarized dmg" in capsys.readouterr().out


def test_no_reuse_runs_full_chain_and_writes_state(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)  # can_reuse False by default
    rc = package.main(["--channel", "canary", "--distribute"])
    assert rc == 0
    names = [c[0] for c in order]
    assert names.index("sign") < names.index("dmg")
    assert ("write_state", "Teleport-1.2.3.dmg") in order   # recorded after dmg


def test_force_bypasses_reuse(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=False)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    rc = package.main(["--channel", "canary", "--force"])
    assert rc == 0
    names = [c[0] for c in order]
    assert "sign" in names and "dmg" in names               # forced rebuild


def test_distribute_final_gate_refuses_dmg_that_fails_revalidation(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    # stapler passes at the reuse decision, then FAILS at the final pre-upload gate
    # (defends against a ticket that became invalid between decision and upload).
    results = iter([True, False])
    monkeypatch.setattr(package._package, "stapler_validate", lambda dmg: next(results))
    with pytest.raises(SystemExit, match="stapler validate"):
        package.main(["--channel", "canary", "--distribute"])
    names = [c[0] for c in order]
    assert "sign" not in names and "dmg" not in names            # reuse path taken
    assert "upload" not in names and "tag_and_push" not in names  # gate blocked publish


def test_dry_run_reports_reuse_when_cached(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._package_state, "can_reuse", lambda s, k, d: True)
    rc = package.main(["--channel", "canary", "--distribute", "--dry-run"])
    assert rc == 0
    assert order == []  # dry-run still has no side effects
    out = capsys.readouterr().out
    assert "reuse notarized dmg" in out
    assert "notarytool" not in out  # not planning to notarize


def test_dry_run_reports_renotarize_when_not_cached(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)  # can_reuse False (default)
    rc = package.main(["--channel", "canary", "--distribute", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "notarytool submit" in out  # plan shows notarization


def test_distribute_final_gate_refuses_after_rebuild(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)  # can_reuse False (default)
    monkeypatch.setattr(package._package, "stapler_validate", lambda dmg: False)
    with pytest.raises(SystemExit, match="stapler validate"):
        package.main(["--channel", "canary", "--distribute"])
    names = [c[0] for c in order]
    assert "dmg" in names                                         # rebuild ran
    assert "upload" not in names and "tag_and_push" not in names  # gate blocked publish


# ---- --skip-build: package an already-built app without rebuilding ----
#
# This flag exists to run the sign/notarize/dmg pipeline against an app whose
# build args could not be re-verified in this run (e.g. a poisoned out dir
# whose args.gn no longer matches the app already sitting on disk). It must
# never become a path to publishing an unverified artifact.

def test_skip_build_with_distribute_raises_before_any_side_effect(monkeypatch):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    with pytest.raises(SystemExit, match=r"--skip-build.*--distribute"):
        package.main(["--channel", "canary", "--distribute", "--skip-build"])
    # explicit hard error, not a silent no-op: nothing downstream ran either
    assert order == []


def test_skip_build_missing_app_names_the_path(monkeypatch, tmp_path):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    called = []
    monkeypatch.setattr(package, "build", lambda *a, **k: called.append(a))
    expected_app = tmp_path / "out" / "mac" / "arm64" / "dev" / "Teleport.app"
    with pytest.raises(SystemExit, match=re.escape(str(expected_app))):
        package.main(["--skip-build"])  # default channel = dev; nothing on disk
    assert called == []  # build must not run when the app is missing either


def test_skip_build_still_asserts_baked_version(monkeypatch, tmp_path):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    (tmp_path / "out" / "mac" / "arm64" / "dev" / "Teleport.app").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(package, "build", lambda *a, **k: calls.append(("build",)))
    monkeypatch.setattr(package._package, "assert_baked_version",
                        lambda app, v: calls.append(("assert_baked_version", v)))
    rc = package.main(["--skip-build"])
    assert rc == 0
    assert calls == [("assert_baked_version", "9.9.9")]  # build skipped, version check ran


def test_skip_build_prints_provenance_warning(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    (tmp_path / "out" / "mac" / "arm64" / "dev" / "Teleport.app").mkdir(parents=True)
    monkeypatch.setattr(package, "build",
                        lambda *a, **k: pytest.fail("build must not run under --skip-build"))
    monkeypatch.setattr(package._package, "assert_baked_version", lambda app, v: None)
    rc = package.main(["--skip-build"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "--skip-build" in out
    assert "NOT verified" in out or "not verified" in out.lower()


def test_skip_build_dev_channel_skips_endpoint_consistency_check(monkeypatch, tmp_path):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "9.9.9")
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    (tmp_path / "out" / "mac" / "arm64" / "dev" / "Teleport.app").mkdir(parents=True)
    monkeypatch.setattr(package._package, "assert_baked_version", lambda app, v: None)
    called = []
    monkeypatch.setattr(package._build, "assert_release_endpoints_consistent",
                        lambda out, ch, distributing: called.append(ch.name))
    rc = package.main(["--skip-build"])
    assert rc == 0
    assert called == []  # only distributable channels carry this guard


def test_skip_build_canary_skips_build_but_still_signs(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    (tmp_path / "out" / "mac" / "arm64" / "release" / "Teleport.app").mkdir(parents=True)
    _stub_distributable(monkeypatch, order, distribute=False)
    monkeypatch.setattr(package._build, "assert_release_endpoints_consistent",
                        lambda out, ch, distributing: order.append(
                            ("assert_endpoints_consistent", ch.name, distributing)))
    rc = package.main(["--channel", "canary", "--skip-build"])
    assert rc == 0
    names = [c[0] for c in order]
    assert "build" not in names                                      # build skipped
    assert "assert_endpoints_consistent" in names
    assert names.index("assert_endpoints_consistent") < names.index("assert_baked_version")
    assert "sign" in names and "dmg" in names                        # pipeline still runs
    assert ("assert_endpoints_consistent", "canary", False) in order  # always non-distributing


# ---- Regression pin: --distribute must never quietly become non-blocking ----
#
# This exercises the REAL _build.build -> ensure_gn_gen -> assert_release_endpoints_
# consistent chain (nothing stubbed past chromium_src/repo_root), so a future refactor
# that widens the allowance -- e.g. giving `distributing` a default of False, or
# downgrading the raise to a warning -- breaks this test, not just the unit-level one
# in test_build.py.

def test_distribute_refuses_against_a_real_stale_args_gn_override(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(package, "read_teleport_version", lambda: "1.2.3")
    monkeypatch.setattr(package._config, "assert_channel_keys_distinct", lambda p: None)
    monkeypatch.setattr(package._config, "assert_channel_urls_self_consistent", lambda p, c: None)
    monkeypatch.setattr(package._build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(package._config, "load_channel_config", lambda path, ch: {
        "public_ed_key": "k", "ed_key_account": "ed25519", "feed_url": "https://h/appcast.xml",
        "notary_profile": "p", "codesign_identity": "Developer ID Application: X (T)",
        "download_base_url": "https://h/dl/", "oss_upload_target": "oss://b/x/",
        "oss_endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
        "oss_region": "cn-hangzhou",
        "git_remote": "origin",
    })
    monkeypatch.setattr(package._publish, "assert_on_main", lambda: None)
    monkeypatch.setattr(package._publish, "assert_clean_tree", lambda: None)
    monkeypatch.setattr(package._publish, "fetch_live_appcast", lambda url: None)
    monkeypatch.setattr(package._publish, "assert_not_published", lambda v, ch, xml: None)
    # Stub the effective-value lookup rather than letting it shell out to gn:
    # this test asserts the guard refuses BEFORE any build subprocess runs, and
    # a real gn invocation would both land in `calls` and require a checkout.
    monkeypatch.setattr(package._build, "effective_gn_arg", lambda out, arg: "dev")

    out = "out/mac/arm64/release"
    (tmp_path / out).mkdir(parents=True)
    # Truthfully describes a TD-026 verification build -- but this is a --distribute
    # run, so it must still be refused loudly, exactly like the old channel-
    # distributability-keyed guard did.
    (tmp_path / out / "args.gn").write_text(
        'import("//teleport/gn/args/release.mac.gn")\n'
        'teleport_deployment_env = "dev"\n')

    calls = []
    monkeypatch.setattr(package._build.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))

    with pytest.raises(SystemExit, match="teleport_deployment_env"):
        package.main(["--channel", "canary", "--distribute"])
    assert calls == []  # refused before any autoninja/gn subprocess ran


def test_distribute_refuses_a_placeholder_ack_build(monkeypatch, tmp_path):
    """A build made through the placeholder escape hatch must never publish.

    The hatch exists so that exercising the pipeline against placeholder roots
    is explicit and self-disarming. If --distribute still worked against it, the
    hatch would just be the TD-026 override with extra steps -- and TD-026 is
    precisely the pattern of a one-off override outliving the reason for it.
    """
    monkeypatch.setattr(package, "read_teleport_version", lambda: "1.2.3")
    monkeypatch.setattr(package._config, "assert_channel_keys_distinct", lambda p: None)
    monkeypatch.setattr(package._config, "assert_channel_urls_self_consistent", lambda p, c: None)
    monkeypatch.setattr(package._build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(package._config, "load_channel_config", lambda path, ch: {
        "public_ed_key": "k", "ed_key_account": "ed25519", "feed_url": "https://h/appcast.xml",
        "notary_profile": "p", "codesign_identity": "Developer ID Application: X (T)",
        "download_base_url": "https://h/dl/", "oss_upload_target": "oss://b/x/",
        "oss_endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
        "oss_region": "cn-hangzhou",
        "git_remote": "origin",
    })
    monkeypatch.setattr(package._build, "effective_gn_arg",
                        lambda out, arg: "true" if "placeholder_ack" in arg else "release")
    calls = []
    monkeypatch.setattr(package._build.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    with pytest.raises(SystemExit, match="placeholder_ack"):
        package.main(["--channel", "canary", "--distribute"])
    assert calls == []  # refused before any build subprocess ran


def test_staging_may_publish_off_main_but_not_from_a_dirty_tree(monkeypatch, tmp_path):
    """staging rehearses from feature branches, so the main-branch requirement
    is release-only. The clean-tree requirement is NOT relaxed: a dirty tree
    makes TeleportSourceRevision a lie, and that stamp is the only way to trace
    a staging artifact back to source now that it carries no release tag."""
    order = []
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._build, "effective_gn_arg",
                        lambda out, arg: "staging" if "env" in arg else "false")
    package.main(["--channel", "staging", "--distribute"])
    names = [c[0] for c in order]
    assert "assert_on_main" not in names       # relaxed for staging
    assert "assert_clean_tree" in names        # still required


# --- Rehearsal mode --------------------------------------------------------
#
# A rehearsal exercises the REAL publish path -- that is its whole point, and
# why it is a mode rather than a hand-run sequence of the same commands. It
# differs from a publish in exactly one respect: it does not tag. Every guard
# stays armed, because a rehearsal that skipped them would rehearse something
# other than what publishing does.

def test_rehearse_runs_the_publish_chain_but_does_not_tag(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._build, "effective_gn_arg",
                        lambda out, arg: "staging" if "env" in arg else "false")
    package.main(["--channel", "staging", "--rehearse"])
    names = [c[0] for c in order]
    # The publish chain runs...
    for step in ("assert_not_published", "generate_appcast", "upload"):
        assert step in names, f"{step} must still run in a rehearsal"
    # ...and the one irreversible, outward-facing step does not.
    assert "tag_and_push" not in names


def test_rehearse_arms_the_stale_args_guard_at_publish_strength(
        monkeypatch, tmp_path):
    """The guard must be told distributing=True during a rehearsal.

    That keyword is what decides between refusing and merely warning. If a
    rehearsal passed False it would sail past a stale out dir that a real
    publish rejects -- rehearsing a path publishing does not take, which is
    the one thing a rehearsal must never do.
    """
    order = []
    monkeypatch.setattr(package, "chromium_src", lambda: tmp_path)
    _stub_distributable(monkeypatch, order, distribute=True)
    monkeypatch.setattr(package._build, "effective_gn_arg",
                        lambda out, arg: "staging" if "env" in arg else "false")
    package.main(["--channel", "staging", "--rehearse"])
    # build() forwards `distributing` to ensure_gn_gen -> the stale-args guard,
    # so this is where the strength is decided.
    build_call = next(c for c in order if c[0] == "build")
    assert build_call[-1] is True, f"rehearsal must build at publish strength: {build_call}"


def test_rehearse_and_distribute_are_mutually_exclusive(monkeypatch):
    with pytest.raises(SystemExit, match="--rehearse"):
        package.main(["--channel", "staging", "--distribute", "--rehearse"])


def test_rehearse_refuses_a_non_distributable_channel(monkeypatch):
    """dev has no publish surface at all, so there is nothing to rehearse."""
    with pytest.raises(SystemExit, match="not distributable"):
        package.main(["--channel", "dev", "--rehearse"])
