#!/usr/bin/env python3
"""Package a signed + notarized teleport dmg and publish its appcast entry.

Pipeline: official build -> stamp version + inject Sparkle keys (pre-sign) ->
chrome signing module (sign + notarize + dmg) -> appcast version guard ->
generate_appcast -> upload to OSS (ossutil).

Run from the repo root with TELEPORT_CHROMIUM_DIR set, after
`gn gen out/mac/arm64/release`.

Hosting is plain OSS over HTTPS (no CDN), so two base locations are split:
  - oss_upload_target: oss:// path the dmg + appcast are uploaded to (ossutil).
  - download_base_url: public https base the appcast download links + SUFeedURL
    point at (the OSS native endpoint, e.g.
    https://<bucket>.oss-cn-<region>.aliyuncs.com/dogfood/<token>/).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

from _lib import chromium_src, deps_cache_dir, repo_root
from _release import assert_publishable, read_teleport_version
from fetch_sparkle import SPARKLE_VERSION

_REQUIRED = (
    "public_ed_key",
    "feed_url",
    "download_base_url",
    "oss_upload_target",
    "codesign_identity",
    "notary_profile",
)


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing {path} (copy release_config.local.toml.example)")
    cfg = tomllib.loads(path.read_text())
    missing = [k for k in _REQUIRED if not cfg.get(k)]
    if missing:
        raise SystemExit(f"release config missing keys: {', '.join(missing)}")
    return cfg


def fetch_live_appcast(feed_url: str) -> str | None:
    try:
        with urllib.request.urlopen(feed_url) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None  # first release: no feed yet


def stamp_and_inject(app: Path, version: str, cfg: dict) -> None:
    info = app / "Contents" / "Info.plist"
    sets = {
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "SUFeedURL": cfg["feed_url"],
        "SUPublicEDKey": cfg["public_ed_key"],
    }
    for key, val in sets.items():
        subprocess.run(["plutil", "-replace", key, "-string", val, str(info)], check=True)
    subprocess.run(
        ["plutil", "-replace", "SUEnableAutomaticChecks", "-bool", "YES", str(info)],
        check=True,
    )


def sparkle_bin(name: str) -> Path:
    return deps_cache_dir() / "sparkle" / SPARKLE_VERSION / "bin" / name


def upload_to_oss(updates_dir: Path, cfg: dict) -> None:
    """Upload the dmg(s) + appcast.xml to OSS with correct cache headers.

    dmg files use versioned names and are immutable -> long cache.
    appcast.xml changes every release -> never cache (so clients see new
    versions immediately; plain OSS doesn't edge-cache, but be explicit).
    """
    target = cfg["oss_upload_target"]
    # ossutil 2.x: Cache-Control has a dedicated --cache-control flag (--metadata
    # is only for x-oss-meta-* user metadata). -f overwrites without prompting.
    for dmg in sorted(updates_dir.glob("*.dmg")):
        subprocess.run(
            ["ossutil", "cp", "-f", str(dmg), target,
             "--cache-control", "public, max-age=31536000, immutable"],
            check=True,
        )
    subprocess.run(
        ["ossutil", "cp", "-f", str(updates_dir / "appcast.xml"), target,
         "--cache-control", "no-cache"],
        check=True,
    )


def build_styled_dmg(updates_dir: Path, version: str, cfg: dict) -> Path:
    """Build a styled dmg (background + icon layout + named Applications
    symlink) from the signed app via dmgbuild, then sign + notarize + staple
    the dmg itself. The chrome signing module only signs the .app
    (--disable-packaging); its plain pkg-dmg output isn't styled for Chromium."""
    # The signing module (--disable-packaging) writes the signed app under the
    # distribution's channel subdir, e.g. <output>/stable/Teleport.app.
    signed_app = next(iter(
        list(updates_dir.glob("Teleport.app")) +
        list(updates_dir.glob("*/Teleport.app"))))
    target_dmg = updates_dir / f"Teleport-{version}.dmg"
    target_dmg.unlink(missing_ok=True)

    dmgbuild = Path(sys.executable).parent / "dmgbuild"
    settings = repo_root() / "scripts" / "dmg_settings.py"
    background = repo_root() / "brand" / "dmg" / "background.tiff"
    icns = signed_app / "Contents" / "Resources" / "app.icns"
    cmd = [str(dmgbuild), "-s", str(settings),
           "-D", f"app={signed_app}", "-D", f"background={background}"]
    if icns.exists():
        cmd += ["-D", f"icon={icns}"]
    cmd += ["Teleport", str(target_dmg)]
    subprocess.run(cmd, check=True)

    # The signed app is now inside the dmg; drop the loose copy (and its channel
    # subdir) so it isn't left in the staging/upload dir.
    stale = signed_app.parent if signed_app.parent != updates_dir else signed_app
    subprocess.run(["rm", "-rf", str(stale)], check=True)

    # Sign, notarize, and staple the dmg itself.
    subprocess.run(["codesign", "--force", "--sign", cfg["codesign_identity"],
                    "--timestamp", str(target_dmg)], check=True)
    subprocess.run(["xcrun", "notarytool", "submit", str(target_dmg),
                    "--keychain-profile", cfg["notary_profile"], "--wait"], check=True)
    subprocess.run(["xcrun", "stapler", "staple", str(target_dmg)], check=True)
    return target_dmg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build + sign + publish a teleport dmg")
    p.add_argument("--out", default="out/mac/arm64/release")
    p.add_argument("--config", type=Path,
                   default=repo_root() / "scripts" / "release_config.local.toml")
    p.add_argument("--updates-dir", type=Path, default=repo_root() / "dist" / "dogfood")
    p.add_argument("--no-upload", action="store_true", help="build+sign locally, skip OSS upload")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    version = read_teleport_version()
    src = chromium_src()
    app = src / args.out / "Teleport.app"

    # 1. Version guard against the live feed (cheap, fail fast before the build).
    # Only when actually publishing — local/dry runs build any version.
    if not args.dry_run and not args.no_upload:
        assert_publishable(version, fetch_live_appcast(cfg["feed_url"]))

    # The signing module must run from the generated "<product> Packaging" dir:
    # it holds a copy of signing/ PLUS the build-time-generated
    # build_props_config.py (branding/version). The source tree's copy lacks it,
    # so running source-tree sign_chrome.py fails with ModuleNotFoundError.
    sign_chrome = app.parent / "Teleport Packaging" / "sign_chrome.py"
    plan = [
        f"autoninja -C {args.out} chrome chrome/installer/mac   (in {src})",
        f"stamp version {version} + inject Sparkle keys into {app}/Contents/Info.plist",
        f"{sign_chrome} --identity '{cfg['codesign_identity']}' --disable-packaging",
        "dmgbuild styled dmg -> codesign -> notarytool submit --wait -> stapler staple",
        f"generate_appcast (download-url-prefix {cfg['download_base_url']}) into {args.updates_dir}",
        f"ossutil upload dmg + appcast.xml to {cfg['oss_upload_target']}",
    ]
    if args.dry_run:
        print("DRY RUN:\n  " + "\n  ".join(plan))
        return 0

    # 2. Official build. `chrome` builds the app; `chrome/installer/mac` builds
    # the "<product> Packaging" dir (dmg tools + generated signing/build_props).
    subprocess.run(
        ["autoninja", "-C", args.out, "chrome", "chrome/installer/mac"],
        cwd=src, check=True,
    )
    # 3. Stamp + inject (pre-sign).
    stamp_and_inject(app, version, cfg)
    # signing's make_dir uses os.mkdir (single level), so pre-create the output
    # tree; the driver skips its own mkdir when the dir already exists.
    args.updates_dir.mkdir(parents=True, exist_ok=True)
    # 4. Sign the app only (--disable-packaging). Branding/version flow from the
    # build's generated build_props_config.py, so no fork signing config is
    # needed; the signed .app is copied to the output dir. Notarization happens
    # later on the styled dmg.
    subprocess.run([
        sys.executable, str(sign_chrome),
        "--identity", cfg["codesign_identity"],
        "--input", str(app.parent),
        "--output", str(args.updates_dir),
        "--disable-packaging",
    ], check=True)
    # 4b. Build the styled dmg from the signed app, then sign + notarize +
    # staple the dmg itself.
    target_dmg = build_styled_dmg(args.updates_dir, version, cfg)

    # 5. Republish guard + appcast (download links point at the public OSS base).
    if not args.no_upload:
        assert_publishable(version, fetch_live_appcast(cfg["feed_url"]))
    # Keep only the current dmg in the staging dir so the appcast lists just the
    # latest version (clients always update to newest) and generate_appcast has
    # no second dmg to diff a delta from. Older dmgs stay published on OSS.
    # (generate_appcast preserves pre-existing delta entries even with
    # --maximum-deltas 0, so the only reliable way to avoid dangling .delta
    # references we don't upload is to generate from a single dmg.)
    for p in args.updates_dir.iterdir():
        if p.is_file() and p.name != target_dmg.name:
            p.unlink()
    subprocess.run([
        str(sparkle_bin("generate_appcast")),
        "--maximum-deltas", "0",
        "--download-url-prefix", cfg["download_base_url"],
        str(args.updates_dir),
    ], check=True)
    # 6. Upload.
    if args.no_upload:
        print(f"built + signed in {args.updates_dir} (upload skipped).")
        return 0
    upload_to_oss(args.updates_dir, cfg)
    print(f"published {version}: feed {cfg['feed_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
