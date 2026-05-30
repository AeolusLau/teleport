"""Channel registry and the build (autoninja) step.

A channel maps to a default GN out dir, whether it is distributable, and the
autoninja targets to build. The script does NOT run `gn gen` — the human runs
that first (release channels also need PGO profiles fetched via gclient sync).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from _lib import chromium_src


@dataclass(frozen=True)
class Channel:
    name: str
    out: str                  # default GN out dir, relative to chromium src
    distributable: bool
    targets: tuple[str, ...]  # autoninja targets


CHANNELS = {
    "dev": Channel("dev", "out/mac/arm64/dev", False, ("chrome",)),
    "canary": Channel(
        "canary", "out/mac/arm64/release", True,
        ("chrome", "chrome/installer/mac"),
    ),
}


def resolve_channel(name: str) -> Channel:
    try:
        return CHANNELS[name]
    except KeyError:
        valid = ", ".join(sorted(CHANNELS))
        raise SystemExit(f"unknown channel {name!r}; valid channels: {valid}")


def build(out: str, channel: Channel) -> None:
    """Run autoninja for the channel's targets inside the chromium src tree."""
    subprocess.run(
        ["autoninja", "-C", out, *channel.targets],
        cwd=chromium_src(), check=True,
    )
