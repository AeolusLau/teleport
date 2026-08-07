#!/usr/bin/env python3
"""Build, sign, and optionally publish a teleport package.

Default builds a local dev app (build only). --channel selects a channel;
--distribute publishes a distributable channel package (main branch only, with
a v<semver> git tag pushed to the remote). Run from the repo root with
TELEPORT_CHROMIUM_DIR set. `gn gen` runs automatically when the channel's out
dir has no args.gn (release channels still need PGO profiles synced first).

--skip-build packages an app that already exists on disk instead of building
one, for validating signing/notarization/dmg against an out-of-band build
(e.g. one whose out dir can no longer be gn-gen'd cleanly). It is refused
together with --distribute: publishing must only ship an app whose build args
were verified in THIS run. See _SKIP_BUILD_WARNING for exactly what is, and is
not, still checked in that mode.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import _build
import _config
import _package
import _package_state
import _publish
from _build import build, resolve_channel
from _lib import chromium_src, repo_root
from _release import read_teleport_version


def _default_config() -> Path:
    return repo_root() / "scripts" / "release_config.local.toml"


_SKIP_BUILD_WARNING = (
    "\n"
    "==================== WARNING: --skip-build UNVERIFIED BUILD ===============\n"
    "Packaging an app that was NOT built by this invocation of package.py. Its\n"
    "GN build args (endpoint config, PGO, updater, etc.) were NOT verified here.\n"
    "\n"
    "assert_baked_version (TELEPORT_VERSION) still runs below. For a\n"
    "distributable channel, assert_release_endpoints_consistent also still\n"
    "runs against <out>/args.gn -- since --distribute is refused whenever\n"
    "--skip-build is set (see below), this run can never reach the publish\n"
    "hazard that check exists to block, so a mismatch here only WARNS, it does\n"
    "not raise. That check can also only catch an EXPLICIT\n"
    "teleport_use_release_endpoints override still recorded as text in\n"
    "args.gn -- if args.gn has since been regenerated back to a plain template\n"
    "import (no override text left to compare against), this run has NO way to\n"
    "tell what endpoint configuration the on-disk app was actually built with.\n"
    "\n"
    "Treat this artifact as UNVERIFIED. --distribute is refused whenever\n"
    "--skip-build is set, precisely so this can never become a publish path.\n"
    "=============================================================================\n"
)


def _prepare_skip_build(app: Path, out: str, channel) -> None:
    """--skip-build's app-provenance guard: refuse if `app` does not exist,
    print the loud unverified-provenance warning, then re-run the one
    build-independent guard that skipping build() would otherwise silently
    drop -- assert_release_endpoints_consistent is a pure text comparison
    against <out>/args.gn, so it needs no gn gen / autoninja and can run here
    directly without a build. Its residual blind spot (an args.gn already
    regenerated back to the plain template import leaves no explicit override
    text to contradict) is named in the warning, not hidden.

    Called with distributing=False unconditionally: main() already refuses
    the --skip-build + --distribute combination before this function can run
    (see the check right after argparse below), so a --skip-build run is
    ALWAYS a non-distributing run by construction -- there is no live case
    where this needs to raise instead of warn.
    """
    if not app.exists():
        raise SystemExit(
            f"--skip-build: no app found at {app}. Build it first (without "
            "--skip-build), or pass --out to point at the out dir that holds it.")
    print(_SKIP_BUILD_WARNING)
    if channel.distributable:
        _build.assert_release_endpoints_consistent(out, channel, distributing=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build + sign + optionally publish a teleport package")
    p.add_argument("--channel", default="dev")
    p.add_argument("--distribute", action="store_true",
                   help="publish after building (distributable channels, main only)")
    p.add_argument("--force", action="store_true",
                   help="ignore the package-state cache; re-sign + re-notarize even "
                        "if the app is unchanged")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--config", type=Path, default=_default_config())
    p.add_argument("--out", default=None, help="override the channel's default out dir")
    p.add_argument("--updates-dir", type=Path, default=None)
    p.add_argument("--skip-build", action="store_true",
                   help="package an app that already exists on disk instead of "
                        "building one; its build args are NOT verified in this "
                        "run (see the warning printed at runtime). Mutually "
                        "exclusive with --distribute.")
    args = p.parse_args(argv)

    if args.skip_build and args.distribute:
        raise SystemExit(
            "--skip-build cannot be combined with --distribute: publishing must "
            "only ship an app whose build args were verified in THIS run. "
            "Re-run without --skip-build to build + sign + publish normally, or "
            "drop --distribute to package + sign + notarize the --skip-build "
            "app locally without publishing it.")

    channel = resolve_channel(args.channel)
    out = args.out or channel.out
    updates_dir = args.updates_dir or (repo_root() / "dist" / channel.name)
    version = read_teleport_version()

    if args.distribute and not channel.distributable:
        raise SystemExit(
            f"channel {channel.name!r} is not distributable; --distribute not allowed")

    # ---- non-distributable channel (dev): build + verify baked version ----
    if not channel.distributable:
        app = chromium_src() / out / "Teleport.app"
        if args.dry_run:
            print(f"DRY RUN: autoninja -C {out} {' '.join(channel.targets)} + "
                  f"verify baked version {version} in {app}/Contents/Info.plist  "
                  f"(build only, channel {channel.name})")
            return 0
        if args.skip_build:
            _prepare_skip_build(app, out, channel)
        else:
            build(out, channel, distributing=args.distribute)
        _package.assert_baked_version(app, version)
        verb = "packaged (--skip-build)" if args.skip_build else "built"
        print(f"{verb} {channel.name} app at {app} (version {version})")
        return 0

    # ---- distributable channel ----
    cfg = _config.load_channel_config(args.config, channel.name)
    _config.require_keys(cfg, _config.SPARKLE_KEYS + _config.NOTARIZE_KEYS)
    if args.distribute:
        _config.require_keys(cfg, _config.PUBLISH_KEYS)
    app = chromium_src() / out / "Teleport.app"

    if args.dry_run:
        identity = cfg.get("codesign_identity") or "<auto-detected from keychain>"
        sp = _package_state.state_path(repo_root(), channel.name)
        target_dmg = _package.target_dmg_path(updates_dir, version, channel.name)
        # Side-effect-free probe: real dry-run hasn't built the app, so use a
        # placeholder digest (errs toward "re-notarize"); do NOT call
        # stapler_validate here (it would run a subprocess).
        key = _package_state.reuse_key(
            version, channel.name, identity, cfg["notary_profile"],
            "<app-digest-after-build>")
        would_reuse = (not args.force and _package_state.can_reuse(
            _package_state.load_state(sp), key, target_dmg))
        if would_reuse:
            sign_dmg_line = (f"reuse notarized dmg {target_dmg.name} (app unchanged "
                             f"per cache); skip sign + codesign + staple (no re-submission)")
        else:
            sign_dmg_line = (
                f"sign .app (--disable-packaging) with '{identity}'  ->  "
                "dmgbuild styled dmg -> codesign -> notarytool submit --wait -> "
                "stapler staple")
        plan = [
            f"autoninja -C {out} {' '.join(channel.targets)}",
            f"verify baked version {version} + inject Sparkle keys into {app}/Contents/Info.plist",
            sign_dmg_line,
        ]
        if args.distribute:
            plan += [
                f"generate_appcast (download-url-prefix {cfg['download_base_url']}) into {updates_dir}",
                f"ossutil upload dmg + appcast.xml to {cfg['oss_upload_target']}",
                f"git tag -a v{version} -m 'release {version}' && git push {cfg['git_remote']} v{version}",
            ]
        print(f"DRY RUN (channel {channel.name}"
              f"{', distribute' if args.distribute else ''}):\n  " + "\n  ".join(plan))
        return 0

    # Real run: detect identity, then (for distribute) fail-fast guards BEFORE the build.
    if not cfg.get("codesign_identity"):
        cfg["codesign_identity"] = _package.detect_codesign_identity()
    if args.distribute:
        _publish.assert_on_main()
        _publish.assert_clean_tree()
        _publish.assert_not_published(version, _publish.fetch_live_appcast(cfg["feed_url"]))

    # Build -> verify baked version -> inject Sparkle keys -> stage icons, then
    # decide whether a previously-notarized dmg can be reused (app byte-identical)
    # or must be rebuilt + re-notarized. --skip-build substitutes an existing
    # app for the build step; see _prepare_skip_build for what is (and is not)
    # still verified in that case.
    if args.skip_build:
        _prepare_skip_build(app, out, channel)
    else:
        build(out, channel, distributing=args.distribute)
    _package.assert_baked_version(app, version)
    _package.inject_sparkle_keys(app, cfg, channel.name)
    _package.stage_channel_icons(app, channel.name)

    sp = _package_state.state_path(repo_root(), channel.name)
    key = _package_state.reuse_key(
        version, channel.name, cfg["codesign_identity"], cfg["notary_profile"],
        _package_state.app_content_digest(app))
    target_dmg = _package.target_dmg_path(updates_dir, version, channel.name)
    if (not args.force
            and _package_state.can_reuse(_package_state.load_state(sp), key, target_dmg)
            and _package.stapler_validate(target_dmg)):
        print(f"reusing notarized dmg {target_dmg.name} (app unchanged); "
              f"skipping sign + notarize")
    else:
        _package.sign_app(app, updates_dir, cfg["codesign_identity"], channel.name)
        target_dmg = _package.build_styled_dmg(
            updates_dir, version, cfg["codesign_identity"], cfg["notary_profile"],
            channel.name)
        _package_state.write_state(sp, key, target_dmg.name)

    if not args.distribute:
        print(f"built + signed {channel.name} dmg at {target_dmg} (not published)")
        return 0

    # Re-check (cheap), then a final notarization gate before ANY upload.
    _publish.assert_not_published(version, _publish.fetch_live_appcast(cfg["feed_url"]))
    if not _package.stapler_validate(target_dmg):
        raise SystemExit(
            f"{target_dmg.name} failed stapler validate; refusing to publish")
    _publish.generate_appcast(updates_dir, cfg["download_base_url"], target_dmg.name)
    _publish.upload_to_oss(updates_dir, cfg["oss_upload_target"])
    _publish.tag_and_push(version, cfg["git_remote"])
    print(f"published {version} ({channel.name}), tagged v{version}: feed {cfg['feed_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
