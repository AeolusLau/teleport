"""Channel registry and the build (gn gen + autoninja) step.

A channel maps to a default GN out dir, whether it is distributable, the
autoninja targets to build, and the //teleport/gn/args file that seeds the out
dir. `gn gen` runs automatically when <out>/args.gn is missing (first build,
fresh checkout, deleted out dir) and is skipped otherwise — ninja re-gens on
its own once the dir exists. Release channels still need PGO profiles fetched
via gclient sync first; a missing profile fails the auto `gn gen` with the
same upstream assert a manual run would hit.
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
    gn_args: str              # args template under //teleport/gn/args/


CHANNELS = {
    "dev": Channel("dev", "out/mac/arm64/dev", False, ("chrome",), "dev.mac.gn"),
    "canary": Channel(
        "canary", "out/mac/arm64/release", True,
        ("chrome", "chrome/installer/mac"), "release.mac.gn",
    ),
}


def resolve_channel(name: str) -> Channel:
    try:
        return CHANNELS[name]
    except KeyError:
        valid = ", ".join(sorted(CHANNELS))
        raise SystemExit(f"unknown channel {name!r}; valid channels: {valid}")


def ensure_gn_gen(out: str, channel: Channel) -> None:
    """Seed the out dir via `gn gen` if <out>/args.gn is missing; else no-op."""
    src = chromium_src()
    if (src / out / "args.gn").exists():
        return
    print(f"gn gen {out} (args.gn missing; seeding from {channel.gn_args})")
    subprocess.run(
        ["gn", "gen", out,
         f'--args=import("//teleport/gn/args/{channel.gn_args}")'],
        cwd=src, check=True,
    )


def build(out: str, channel: Channel) -> None:
    """Run autoninja for the channel's targets inside the chromium src tree,
    seeding the out dir first if it was never gn-gen'd."""
    ensure_gn_gen(out, channel)
    subprocess.run(
        ["autoninja", "-C", out, *channel.targets],
        cwd=chromium_src(), check=True,
    )
