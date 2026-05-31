"""Packaging steps for a distributable channel: stamp version + Sparkle keys,
sign the .app via the generated signing module, and build the styled dmg
(sign + notarize + staple). All macOS / Developer-ID specific.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _lib import deps_cache_dir, repo_root
from fetch_sparkle import SPARKLE_VERSION

# canary checks for updates hourly instead of Sparkle's 1-day default
# (SUDefaultUpdateCheckInterval). 3600s is Sparkle's enforced minimum.
_CHECK_INTERVAL_SECONDS = 3600


def version_plist_keys(version: str) -> dict[str, str]:
    """The Info.plist version fields stamped for any channel (Sparkle compares
    CFBundleVersion; CFBundleShortVersionString is the user-facing string)."""
    return {
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
    }


def stamp_version_only(app: Path, version: str) -> None:
    """Stamp just the version fields into the app's Info.plist (no Sparkle keys,
    no signing). Used by the dev channel so dev builds also display the real
    Teleport version on the About page / chrome://version."""
    info = app / "Contents" / "Info.plist"
    for key, val in version_plist_keys(version).items():
        subprocess.run(["plutil", "-replace", key, "-string", val, str(info)],
                       check=True)


def detect_codesign_identity() -> str:
    """Find the unique 'Developer ID Application' certificate in the keychain.

    Refuses to guess when more than one such identity exists -- the caller must
    then set `codesign_identity` explicitly in the config.
    """
    r = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True, check=True,
    )
    matches = re.findall(r'"(Developer ID Application: [^"]+)"', r.stdout)
    if not matches:
        raise SystemExit("no 'Developer ID Application' certificate found in keychain")
    if len(matches) > 1:
        found = "\n  ".join(matches)
        raise SystemExit(
            "multiple 'Developer ID Application' certificates found in keychain; "
            "refusing to guess. Set codesign_identity explicitly in "
            "release_config.local.toml to one of:\n  " + found
        )
    return matches[0]


def sparkle_bin(name: str) -> Path:
    return deps_cache_dir() / "sparkle" / SPARKLE_VERSION / "bin" / name


def sparkle_plist_string_keys(version: str, cfg: dict, channel_name: str) -> dict[str, str]:
    """The string-valued Info.plist keys stamped for a distributable channel:
    version fields, the Sparkle feed/key, and the TeleportChannel marker that
    drives chrome::GetChannel() at runtime."""
    return {
        **version_plist_keys(version),
        "SUFeedURL": cfg["feed_url"],
        "SUPublicEDKey": cfg["public_ed_key"],
        "TeleportChannel": channel_name,
    }


def stamp_and_inject(app: Path, version: str, cfg: dict, channel_name: str) -> None:
    """Stamp version + Sparkle keys + the TeleportChannel marker into the app's
    Info.plist (pre-sign)."""
    info = app / "Contents" / "Info.plist"
    for key, val in sparkle_plist_string_keys(version, cfg, channel_name).items():
        subprocess.run(["plutil", "-replace", key, "-string", val, str(info)], check=True)
    subprocess.run(
        ["plutil", "-replace", "SUEnableAutomaticChecks", "-bool", "YES", str(info)],
        check=True,
    )
    subprocess.run(
        ["plutil", "-replace", "SUScheduledCheckInterval", "-integer",
         str(_CHECK_INTERVAL_SECONDS), str(info)],
        check=True,
    )


def stage_channel_icons(app: Path, channel_name: str) -> None:
    """Copy the built app's icon assets to the channel-named files the signing
    engine's _replace_icons() requires. The engine reads
    `app_<channel>.icns` / `Assets_<channel>.car` from the "Teleport Packaging"
    dir (named by config.product, which does not change per channel). We reuse
    the base icons (no per-channel differentiation yet). No-op for the base
    channel, which is not channel-customized.
    """
    if channel_name in ("", "stable"):
        return
    res = app / "Contents" / "Resources"
    pkg = app.parent / "Teleport Packaging"
    shutil.copyfile(res / "app.icns", pkg / f"app_{channel_name}.icns")
    shutil.copyfile(res / "Assets.car", pkg / f"Assets_{channel_name}.car")


def sign_app(app: Path, updates_dir: Path, identity: str,
             channel_name: str = "") -> None:
    """Sign the .app only (--disable-packaging) via the generated signing module.

    The signing module must run from the generated "<product> Packaging" dir:
    it holds signing/ PLUS the build-time-generated build_props_config.py
    (branding/version). The source tree's copy lacks it.

    For a channel-customized channel, TELEPORT_SIGN_CHANNEL drives the
    overridden `distributions` in chromium_config.py so the engine renames the
    app, suffixes the bundle id, and stamps CrProductDirName. The base channel
    leaves it unset (engine uses the bare Distribution).
    """
    sign_chrome = app.parent / "Teleport Packaging" / "sign_chrome.py"
    # signing's make_dir uses os.mkdir (single level), so pre-create the output
    # tree; the driver skips its own mkdir when the dir already exists.
    updates_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if channel_name and channel_name != "stable":
        env["TELEPORT_SIGN_CHANNEL"] = channel_name
    subprocess.run([
        sys.executable, str(sign_chrome),
        "--identity", identity,
        "--input", str(app.parent),
        "--output", str(updates_dir),
        "--disable-packaging",
    ], check=True, env=env)


def _find_signed_app(updates_dir: Path) -> Path:
    """Locate the signed .app the signing module produced. It lands under a
    per-distribution subdir named `<dist.channel or 'stable'>`, and a
    channel-customized app is renamed (e.g. `Teleport Canary.app`). Match both
    the legacy `stable/Teleport.app` layout and channel layouts with a space.
    """
    matches = (list(updates_dir.glob("Teleport*.app")) +
               list(updates_dir.glob("*/Teleport*.app")))
    return next(iter(matches))


def dmg_names(channel_name: str) -> tuple[str, str]:
    """The dmg file-name prefix and the mounted volume name for a channel,
    mirroring Chrome: the file name is space-free (`TeleportCanary`, like
    Chrome's `GoogleChromeCanary`) while the volume name keeps the space
    (`Teleport Canary`, matching the renamed `Teleport Canary.app`). The base
    channel ('' / 'stable') is the bare `Teleport` for both."""
    if channel_name in ("", "stable"):
        return "Teleport", "Teleport"
    fragment = channel_name.capitalize()  # canary -> Canary, beta -> Beta
    return f"Teleport{fragment}", f"Teleport {fragment}"


def build_styled_dmg(updates_dir: Path, version: str, identity: str,
                     notary_profile: str, channel_name: str = "") -> Path:
    """Build a styled dmg from the signed app (dmgbuild), then sign + notarize +
    staple the dmg itself. The chrome signing module only signs the .app
    (--disable-packaging); its plain pkg-dmg output isn't styled for Chromium.

    The dmg file name and mounted volume name are channel-suffixed (see
    dmg_names) so a canary image is `TeleportCanary-<ver>.dmg` mounting as
    `Teleport Canary`, coexisting with a stable `Teleport-<ver>.dmg`."""
    # The signing module writes the signed app under the distribution's channel
    # subdir, e.g. <output>/stable/Teleport.app.
    signed_app = _find_signed_app(updates_dir)
    file_prefix, volume_name = dmg_names(channel_name)
    target_dmg = updates_dir / f"{file_prefix}-{version}.dmg"
    target_dmg.unlink(missing_ok=True)

    dmgbuild = Path(sys.executable).parent / "dmgbuild"
    settings = repo_root() / "scripts" / "dmg_settings.py"
    background = repo_root() / "brand" / "dmg" / "background.tiff"
    icns = signed_app / "Contents" / "Resources" / "app.icns"
    cmd = [str(dmgbuild), "-s", str(settings),
           "-D", f"app={signed_app}", "-D", f"background={background}"]
    if icns.exists():
        cmd += ["-D", f"icon={icns}"]
    cmd += [volume_name, str(target_dmg)]
    subprocess.run(cmd, check=True)

    # The signed app is now inside the dmg; drop the loose copy (and its channel
    # subdir) so it isn't left in the staging/upload dir.
    stale = signed_app.parent if signed_app.parent != updates_dir else signed_app
    subprocess.run(["rm", "-rf", str(stale)], check=True)

    # Sign, notarize, and staple the dmg itself.
    subprocess.run(["codesign", "--force", "--sign", identity,
                    "--timestamp", str(target_dmg)], check=True)
    subprocess.run(["xcrun", "notarytool", "submit", str(target_dmg),
                    "--keychain-profile", notary_profile, "--wait"], check=True)
    subprocess.run(["xcrun", "stapler", "staple", str(target_dmg)], check=True)
    return target_dmg
