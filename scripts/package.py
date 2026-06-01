#!/usr/bin/env python3
"""Build, sign, and optionally publish a teleport package.

Default builds a local dev app (build only). --channel selects a channel;
--distribute publishes a distributable channel package (main branch only, with
a v<semver> git tag pushed to the remote). Run from the repo root with
TELEPORT_CHROMIUM_DIR set; for distributable channels, `gn gen` the channel's
out dir first.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import _config
import _package
import _package_state
import _publish
from _build import build, resolve_channel
from _lib import chromium_src, repo_root
from _release import read_teleport_version


def _default_config() -> Path:
    return repo_root() / "scripts" / "release_config.local.toml"


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
    args = p.parse_args(argv)

    channel = resolve_channel(args.channel)
    out = args.out or channel.out
    updates_dir = args.updates_dir or (repo_root() / "dist" / channel.name)
    version = read_teleport_version()

    if args.distribute and not channel.distributable:
        raise SystemExit(
            f"channel {channel.name!r} is not distributable; --distribute not allowed")

    # ---- non-distributable channel (dev): build + stamp version ----
    if not channel.distributable:
        app = chromium_src() / out / "Teleport.app"
        if args.dry_run:
            print(f"DRY RUN: autoninja -C {out} {' '.join(channel.targets)} + "
                  f"stamp version {version} into {app}/Contents/Info.plist  "
                  f"(build only, channel {channel.name})")
            return 0
        build(out, channel)
        _package.stamp_version_only(app, version)
        print(f"built {channel.name} app at {app} (version {version})")
        return 0

    # ---- distributable channel ----
    cfg = _config.load_channel_config(args.config, channel.name)
    _config.require_keys(cfg, _config.STAMP_KEYS + _config.NOTARIZE_KEYS)
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
            f"stamp version {version} + inject Sparkle keys into {app}/Contents/Info.plist",
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

    # Build -> stamp -> stage icons, then decide whether a previously-notarized
    # dmg can be reused (app byte-identical) or must be rebuilt + re-notarized.
    build(out, channel)
    _package.stamp_and_inject(app, version, cfg, channel.name)
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
