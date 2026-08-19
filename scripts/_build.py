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

# Matches a `teleport_deployment_env = "dev"|"staging"|"release"` line the way
# GN writes it back into args.gn (and the way our gn/args/*.mac.gn templates
# spell it): possibly indented, `=` surrounded by whitespace, nothing else on
# the line.
#
# This replaced a `teleport_use_release_endpoints = true|false` matcher when
# the boolean became a tristate. That rename alone silently disarmed the guard:
# it kept looking for a name that, post-rename, no template can legally contain
# (teleport.gni asserts on it as a tombstone), so `expected` was always None and
# every comparison was skipped.
_DEPLOYMENT_ENV_RE = re.compile(
    r"""^\s*teleport_deployment_env\s*=\s*"(dev|staging|release)"\s*$""",
    re.MULTILINE)


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
    # staging is an ENVIRONMENT that borrows a channel slot: same official
    # pipeline as release, different baked trust material. It gets its own out
    # dir because the two differ inside //components/policy, which relinks most
    # of the browser -- sharing a dir would mean a full rebuild on every switch.
    "staging": Channel(
        "staging", "out/mac/arm64/staging", True,
        ("chrome", "chrome/installer/mac"), "staging.mac.gn",
    ),
}


def resolve_channel(name: str) -> Channel:
    try:
        return CHANNELS[name]
    except KeyError:
        valid = ", ".join(sorted(CHANNELS))
        raise SystemExit(f"unknown channel {name!r}; valid channels: {valid}")


_GN_ARG_VALUE_RE = re.compile(r'^\s*(\w+)\s*=\s*"?([^"\n]*?)"?\s*$')


def gn_bin():
    return chromium_src() / "buildtools" / "mac" / "gn"


def effective_gn_arg(out: str, arg: str) -> str | None:
    """The value GN actually resolves for `arg` in <out>, or None if unset.

    Asks gn rather than reading args.gn as text. Text cannot see through an
    import() chain, and a normal `gn gen` writes an args.gn containing exactly
    one import line -- so a text matcher finds nothing to compare against and
    skips the comparison entirely. That is how the previous guard came to
    protect nothing at all.

    gn exits 0 even for an unknown argument (it prints an ERROR banner on
    stdout), so the returned SHAPE is validated rather than the exit code.
    """
    try:
        r = subprocess.run(
            [str(gn_bin()), "args", out, f"--list={arg}", "--short"],
            # cwd matters: gn locates the source root by walking up from the
            # working directory looking for a .gn file. Run it from anywhere
            # else -- this repo, a worktree, CI's checkout dir -- and it fails
            # with "Can't find source root" regardless of how absolute the out
            # path is, which would make every lookup return None and every
            # distributable channel fail the guard spuriously.
            cwd=chromium_src(),
            capture_output=True, text=True, check=False,
        )
    except OSError:
        # No gn binary reachable (fresh checkout, CI image without buildtools).
        # "Cannot determine" is the honest answer, and callers treat it as a
        # refusal rather than as consent -- raising here instead would turn an
        # environment gap into an unhandled traceback.
        return None
    m = _GN_ARG_VALUE_RE.match(r.stdout.strip())
    if not m or m.group(1) != arg:
        return None
    return m.group(2)


def _extract_deployment_env(gn_args_text: str) -> str | None:
    """"dev"/"staging"/"release" as textually parsed out of a GN args file, or
    None if the arg is not explicitly set there."""
    m = _DEPLOYMENT_ENV_RE.search(gn_args_text)
    return m.group(1) if m else None


def assert_release_endpoints_consistent(out: str, channel: Channel, *, distributing: bool) -> None:
    """Guard the trap a stale <out>/args.gn otherwise leaves in place: gn gen
    only runs when args.gn is missing (see ensure_gn_gen below), so an
    args.gn left over from a manual override -- e.g. `gn gen ...
    teleport_deployment_env="dev"` used to work around TD-026's KMS
    fail-closed assert while validating something else about a release build
    -- persists across every future package.py run against the same out dir.

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
      with a truthful teleport_deployment_env="dev" override for
      TD-026) proceed. `--skip-build` already hard-refuses `--distribute`
      (see package.py), so a non-distributing run can never reach the
      hazard this guard exists to prevent -- there is nothing left to
      protect against by also raising here.

    `distributing` has no default: every call site must explicitly state
    intent, so a future refactor cannot silently regress a real --distribute
    run to the warn-only branch by omitting the argument.

    Only checked for distributable channels at all: dev's out dir has no
    shipped-artifact risk, and its template intentionally sets
    teleport_deployment_env="dev" anyway.

    The comparison uses the EFFECTIVE value from `gn args --list`, not the text
    of args.gn. That distinction is the whole point. An args.gn produced by a
    normal `gn gen` contains exactly one line -- `import("//teleport/gn/args/
    <channel>.mac.gn")` -- so a text matcher finds no assignment, has nothing to
    compare, and returns early. Every out dir this codebase's own tooling
    creates has that shape, which means the text-based version of this guard
    skipped essentially every real case while appearing to run.

    Reading the effective value catches both shapes that matter: an explicit
    override appended after the import (the TD-026 workaround shape), and an
    out dir seeded from a DIFFERENT channel's template altogether -- e.g. a
    directory once gn-gen'd for staging and later reused for a canary
    `--distribute`, where nothing in the text disagrees with anything because
    the text says almost nothing at all.

    A None result means gn could not resolve the argument. That is treated as a
    mismatch rather than as "no override": if we cannot establish what this out
    dir bakes, we must not sign and publish whatever it happens to contain.
    """
    if not channel.distributable:
        return
    args_gn = chromium_src() / out / "args.gn"
    if not args_gn.exists():
        return  # ensure_gn_gen will seed it fresh from the template below
    # The EFFECTIVE value, not the text: an args.gn that merely imports a
    # template still resolves to a concrete environment, and that resolution is
    # exactly what a stale out dir gets wrong.
    actual = effective_gn_arg(out, "teleport_deployment_env")
    template = repo_root() / "src" / "gn" / "args" / channel.gn_args
    expected = _extract_deployment_env(template.read_text())
    if actual == expected:
        return
    if actual is None:
        found = (
            "gn could not resolve teleport_deployment_env for this out dir at "
            "all, so what it bakes cannot be established")
    else:
        found = f"resolves teleport_deployment_env to {actual!r}"
    detail = (
        f"{args_gn} {found}, but the {channel.name!r} channel's template "
        f"({template}) expects {expected!r}. This out dir was very likely "
        f"gn-gen'd for another channel or with a manual override (e.g. to work "
        f"around TD-026's KMS assert) -- "
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
