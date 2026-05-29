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
    monkeypatch.setattr(package, "build", lambda out, ch: calls.append((out, ch.name)))
    rc = package.main([])  # default channel = dev, no distribute
    assert rc == 0
    assert calls == [("out/mac/arm64/dev", "dev")]


def _stub_distributable(monkeypatch, order, *, distribute):
    """Stub every side-effecting call package.main makes for a dogfood run,
    recording call order. Returns nothing; assertions live in the test."""
    monkeypatch.setattr(package, "read_teleport_version", lambda: "1.2.3")
    monkeypatch.setattr(package, "build",
                        lambda out, ch: order.append(("build", out, ch.name)))
    cfg = {
        "public_ed_key": "k", "feed_url": "https://h/appcast.xml",
        "notary_profile": "p", "codesign_identity": "Developer ID Application: X (T)",
        "download_base_url": "https://h/dl/", "oss_upload_target": "oss://b/x/",
        "git_remote": "origin",
    }
    monkeypatch.setattr(package._config, "load_channel_config", lambda path, ch: dict(cfg))
    monkeypatch.setattr(package._package, "stamp_and_inject",
                        lambda app, v, c: order.append(("stamp", v)))
    monkeypatch.setattr(package._package, "sign_app",
                        lambda app, ud, ident: order.append(("sign", ident)))

    class _Dmg:
        name = "Teleport-1.2.3.dmg"
    monkeypatch.setattr(package._package, "build_styled_dmg",
                        lambda ud, v, ident, notary: (order.append(("dmg", v)) or _Dmg()))
    monkeypatch.setattr(package._publish, "assert_on_main",
                        lambda: order.append(("assert_on_main",)))
    monkeypatch.setattr(package._publish, "assert_clean_tree",
                        lambda: order.append(("assert_clean_tree",)))
    monkeypatch.setattr(package._publish, "fetch_live_appcast", lambda url: None)
    monkeypatch.setattr(package._publish, "assert_not_published",
                        lambda v, xml: order.append(("assert_not_published", v)))
    monkeypatch.setattr(package._publish, "generate_appcast",
                        lambda ud, base, keep: order.append(("generate_appcast", keep)))
    monkeypatch.setattr(package._publish, "upload_to_oss",
                        lambda ud, target: order.append(("upload", target)))
    monkeypatch.setattr(package._publish, "tag_and_push",
                        lambda v, remote: order.append(("tag_and_push", v, remote)))


def test_distribute_runs_guards_before_build_and_tags_after_upload(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    rc = package.main(["--channel", "dogfood", "--distribute"])
    assert rc == 0
    names = [c[0] for c in order]
    # fail-fast: all three guards precede the build
    assert names.index("assert_on_main") < names.index("build")
    assert names.index("assert_clean_tree") < names.index("build")
    # pipeline order
    assert names.index("build") < names.index("stamp") < names.index("sign") < names.index("dmg")
    # tag strictly after upload; appcast uses the dmg name as keep
    assert names.index("upload") < names.index("tag_and_push")
    assert ("generate_appcast", "Teleport-1.2.3.dmg") in order
    assert ("tag_and_push", "1.2.3", "origin") in order
    assert "published 1.2.3 (dogfood)" in capsys.readouterr().out


def test_distribute_local_without_publish_stops_after_dmg(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=False)
    rc = package.main(["--channel", "dogfood"])  # no --distribute
    assert rc == 0
    names = [c[0] for c in order]
    assert "dmg" in names
    assert "upload" not in names and "tag_and_push" not in names
    assert "not published" in capsys.readouterr().out


def test_dogfood_distribute_dry_run_has_no_side_effects(monkeypatch, capsys):
    order = []
    _stub_distributable(monkeypatch, order, distribute=True)
    # If any guard/build/network stub fires, it appends to order — must stay empty.
    rc = package.main(["--channel", "dogfood", "--distribute", "--dry-run"])
    assert rc == 0
    assert order == []  # dry-run did not build, guard, fetch, sign, tag, or upload
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "git tag -a v1.2.3" in out  # publish steps shown in the plan
