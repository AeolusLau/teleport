"""Report whether upstream has shipped a newer Chrome than the pinned baseline.

Uses the Chrome VersionHistory API, which lists only *released* versions. The
chromium/src tag list must NOT be used for this: release sub-branches
(refs/branch-heads/<BUILD>_<n>) allocate PATCH numbers in blocks, so the tag
list contains many builds that were never shipped, and each platform ships its
own PATCH number.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import NamedTuple

from _lib import parse_four_segment, pinned_chromium_version, release_branch

API = ("https://versionhistory.googleapis.com/v1/chrome/platforms/"
       "{platform}/channels/stable/versions")

# Verdict-bearing platforms. mac and win64 have historically shipped the exact
# same desktop sequence; linux ships a subset of it, so including linux would
# permanently read as "behind". linux is fetched for information only.
DESKTOP = ("mac", "win64")
INFO_ONLY = ("linux",)


class Verdict(NamedTuple):
    status: str          # "current" | "patch_available" | "milestone_moved"
    latest: str | None
    platforms_disagree: bool
    # Desktop platforms (from DESKTOP) that reported no data at all. Non-empty
    # means the verdict above was computed from a subset of DESKTOP, so the
    # "mac and win64 agree" premise was never actually checked — this must be
    # surfaced distinctly from platforms_disagree, which requires at least
    # two platforms to have reported before it can even be evaluated.
    missing_platforms: tuple[str, ...] = ()


def version_key(v: str) -> tuple[int, int, int, int]:
    a, b, c, d = parse_four_segment(v).split(".")
    return (int(a), int(b), int(c), int(d))


def classify(pinned: str, released: dict[str, list[str]]) -> Verdict:
    """Compare the pin against what the desktop platforms actually shipped."""
    latest_per_platform = {}
    missing = []
    for platform in DESKTOP:
        versions = released.get(platform) or []
        if versions:
            latest_per_platform[platform] = max(versions, key=version_key)
        else:
            missing.append(platform)
    if not latest_per_platform:
        raise ValueError(f"no released versions for any of {DESKTOP}")

    disagree = len(set(latest_per_platform.values())) > 1
    missing_platforms = tuple(missing)
    latest = max(latest_per_platform.values(), key=version_key)

    if version_key(latest) <= version_key(pinned):
        return Verdict("current", latest, disagree, missing_platforms)
    if release_branch(latest) != release_branch(pinned):
        return Verdict("milestone_moved", latest, disagree, missing_platforms)
    return Verdict("patch_available", latest, disagree, missing_platforms)


def fetch_released_versions(platform: str) -> list[str]:
    with urllib.request.urlopen(API.format(platform=platform), timeout=30) as r:
        payload = json.load(r)
    return [entry["version"] for entry in payload.get("versions", [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether upstream shipped a newer Chrome than our pin")
    parser.parse_args(argv)

    pinned = pinned_chromium_version()
    released = {p: fetch_released_versions(p) for p in DESKTOP + INFO_ONLY}
    verdict = classify(pinned, released)

    print(f"pinned:        {pinned}  (release branch {release_branch(pinned)})")
    for p in DESKTOP + INFO_ONLY:
        newest = max(released[p], key=version_key) if released[p] else "(none)"
        tag = "" if p in DESKTOP else "  [informational]"
        print(f"  {p:<8} {newest}{tag}")

    if verdict.missing_platforms:
        print(f"\nWARNING: no released-version data for: "
              f"{', '.join(verdict.missing_platforms)}. The verdict below "
              f"was computed from a subset of {DESKTOP} — the 'mac and "
              f"win64 agree' premise has NOT been checked. Re-run before "
              f"acting on this.", file=sys.stderr)

    if verdict.platforms_disagree:
        print("\nWARNING: mac and win64 shipped different versions. The "
              "'one pin serves all desktop platforms' assumption no longer "
              "holds — decide by hand which to track.", file=sys.stderr)

    print()
    if verdict.status == "current":
        print("Up to date. No action.")
    elif verdict.status == "patch_available":
        print(f"Security patch available: {pinned} -> {verdict.latest}\n"
              f"  Same release branch: reuse the existing checkout.\n"
              f"  Update CHROMIUM_VERSION, then run sync.py, apply_patches.py, "
              f"and an incremental build.")
    else:
        print(f"Upstream moved to a new release branch: {verdict.latest}\n"
              f"  Branch {release_branch(pinned)} stops receiving fixes.\n"
              f"  A milestone upgrade is required — see "
              f"docs/chromium-upgrade-runbook.md.")

    print("\nSeverity of the fixes in that release is NOT in this API. Check "
          "https://chromereleases.googleblog.com/feeds/posts/default")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
