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
        plan = [
            f"autoninja -C {out} {' '.join(channel.targets)}",
            f"stamp version {version} + inject Sparkle keys into {app}/Contents/Info.plist",
            f"sign .app (--disable-packaging) with '{identity}'",
            "dmgbuild styled dmg -> codesign -> notarytool submit --wait -> stapler staple",
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

    # Build -> stamp -> sign -> styled dmg (notarized).
    build(out, channel)
    _package.stamp_and_inject(app, version, cfg)
    _package.sign_app(app, updates_dir, cfg["codesign_identity"])
    target_dmg = _package.build_styled_dmg(
        updates_dir, version, cfg["codesign_identity"], cfg["notary_profile"])

    if not args.distribute:
        print(f"built + signed {channel.name} dmg at {target_dmg} (not published)")
        return 0

    # Re-check (cheap) in case another publish landed during the build, then
    # generate appcast -> upload -> tag + push (tag only after a successful upload).
    _publish.assert_not_published(version, _publish.fetch_live_appcast(cfg["feed_url"]))
    _publish.generate_appcast(updates_dir, cfg["download_base_url"], target_dmg.name)
    _publish.upload_to_oss(updates_dir, cfg["oss_upload_target"])
    _publish.tag_and_push(version, cfg["git_remote"])
    print(f"published {version} ({channel.name}), tagged v{version}: feed {cfg['feed_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
