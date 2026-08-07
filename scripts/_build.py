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

import re
import subprocess
from dataclasses import dataclass

from _lib import chromium_src, repo_root

# Matches a `teleport_use_release_endpoints = true|false` line the way GN
# writes it back into args.gn (and the way our gn/args/*.mac.gn templates
# spell it): possibly indented, `=` surrounded by whitespace, nothing else on
# the line.
_USE_RELEASE_ENDPOINTS_RE = re.compile(
    r"^\s*teleport_use_release_endpoints\s*=\s*(true|false)\s*$", re.MULTILINE)


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


def _extract_use_release_endpoints(gn_args_text: str) -> str | None:
    """"true"/"false" as textually parsed out of a GN args file, or None if
    the arg is not explicitly set there."""
    m = _USE_RELEASE_ENDPOINTS_RE.search(gn_args_text)
    return m.group(1) if m else None


def assert_release_endpoints_consistent(out: str, channel: Channel, *, distributing: bool) -> None:
    """Guard the trap a stale <out>/args.gn otherwise leaves in place: gn gen
    only runs when args.gn is missing (see ensure_gn_gen below), so an
    args.gn left over from a manual override -- e.g. `gn gen ... teleport_
    use_release_endpoints=false` used to work around TD-026's KMS fail-closed
    assert while validating something else about a release build -- persists
    across every future package.py run against the same out dir.

    Fires on DISTRIBUTION INTENT (the `distributing` keyword -- i.e. whether
    this run is a `--distribute` run), not on whether the channel merely CAN
    be distributed. The hazard this guards against -- sign -> notarize ->
    upload to OSS -> tag a package that secretly bakes dev endpoints -- can
    only happen on a `--distribute` run:

    - distributing=True and a mismatch is found: raise SystemExit. This is
      the loud, blocking failure that closes the hazard. It is unconditional
      and must never be weakened -- `package.py --channel canary --distribute`
      must always refuse here rather than silently ship a dev-endpoint build,
      because assert_baked_version only checks the version string, not the
      endpoint configuration.
    - distributing=False and a mismatch is found: print a warning naming the
      exact override and stating the artifact must not be published, then
      return normally without raising. This is what lets a non-distributing
      run (e.g. `package.py --channel canary --skip-build`, used to verify
      packaging mechanics against an out dir that was deliberately gn-gen'd
      with a truthful teleport_use_release_endpoints=false override for
      TD-026) proceed. `--skip-build` already hard-refuses `--distribute`
      (see package.py), so a non-distributing run can never reach the
      hazard this guard exists to prevent -- there is nothing left to
      protect against by also raising here.

    `distributing` has no default: every call site must explicitly state
    intent, so a future refactor cannot silently regress a real --distribute
    run to the warn-only branch by omitting the argument.

    Only checked for distributable channels at all: dev's out dir has no
    shipped-artifact risk, and its template intentionally sets
    teleport_use_release_endpoints=false anyway.

    A real args.gn generated with no override -- just `import("//teleport/gn/
    args/<channel>.mac.gn")`, e.g. every `gn gen` this codebase's own
    tooling runs -- has nothing to compare: whatever the imported template
    currently says IS the effective value, by construction, and there is
    nothing in args.gn's own text to contradict it. The only way for a
    genuine mismatch to exist is an EXPLICIT override baked into args.gn
    (typically appended after the import in the --args string) that
    disagrees with the template -- exactly the TD-026 workaround shape. So
    this only compares when args.gn explicitly sets the var; an args.gn
    that relies purely on the import is trusted, not skipped due to a
    parsing limitation.
    """
    if not channel.distributable:
        return
    args_gn = chromium_src() / out / "args.gn"
    if not args_gn.exists():
        return  # ensure_gn_gen will seed it fresh from the template below
    actual = _extract_use_release_endpoints(args_gn.read_text())
    if actual is None:
        return  # no explicit override in args.gn -- nothing to contradict
    template = repo_root() / "src" / "gn" / "args" / channel.gn_args
    expected = _extract_use_release_endpoints(template.read_text())
    if actual == expected:
        return
    detail = (
        f"{args_gn} has an explicit teleport_use_release_endpoints={actual!r} "
        f"override, but the {channel.name!r} channel's template ({template}) "
        f"expects {expected!r}. This out dir was very likely gn-gen'd with a "
        f"manual override (e.g. to work around TD-026's KMS assert) -- "
        f"ensure_gn_gen() silently no-ops whenever args.gn already exists, so "
        f"that override otherwise persists across every future run against "
        f"this out dir.")
    if distributing:
        raise SystemExit(
            f"{detail} Refusing to --distribute: publishing must never ship "
            f"a build whose baked endpoints do not match the {channel.name!r} "
            f"channel's real release configuration. Delete {args_gn} (forces "
            f"`gn gen` to regenerate it from the real template on the next "
            f"build; does not touch build output) or regenerate it by hand, "
            f"then retry.")
    print(
        f"WARNING: {detail} This artifact does NOT match the {channel.name!r} "
        f"channel's real release configuration and MUST NOT be published. "
        f"Proceeding because --distribute was not requested.")


def ensure_gn_gen(out: str, channel: Channel, *, distributing: bool) -> None:
    """Seed the out dir via `gn gen` if <out>/args.gn is missing; else no-op
    (after checking a pre-existing args.gn is not silently stale, see
    assert_release_endpoints_consistent). `distributing` is forwarded as-is
    (see assert_release_endpoints_consistent for why it has no default)."""
    src = chromium_src()
    if (src / out / "args.gn").exists():
        assert_release_endpoints_consistent(out, channel, distributing=distributing)
        return
    print(f"gn gen {out} (args.gn missing; seeding from {channel.gn_args})")
    subprocess.run(
        ["gn", "gen", out,
         f'--args=import("//teleport/gn/args/{channel.gn_args}")'],
        cwd=src, check=True,
    )


def build(out: str, channel: Channel, *, distributing: bool) -> None:
    """Run autoninja for the channel's targets inside the chromium src tree,
    seeding the out dir first if it was never gn-gen'd. `distributing` is
    forwarded as-is (see assert_release_endpoints_consistent for why it has
    no default)."""
    ensure_gn_gen(out, channel, distributing=distributing)
    subprocess.run(
        ["autoninja", "-C", out, *channel.targets],
        cwd=chromium_src(), check=True,
    )
