"""Release config: nested [channel.x] TOML loader + per-operation key checks.

Top-level keys are account-shared (notary_profile, codesign_identity,
git_remote); [channel.<name>] holds per-channel publish settings (Sparkle
public key, feed URL, OSS endpoints). Validation is deferred to require_keys()
so each operation only demands what it actually needs (a dev build needs no
config at all; a local channel package needs sparkle+notarize keys; publishing
additionally needs the OSS keys).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

# Keys required per operation phase.
SPARKLE_KEYS = ("public_ed_key", "ed_key_account", "feed_url")
NOTARIZE_KEYS = ("notary_profile",)
# oss_endpoint / oss_region are per-channel and required: ossutil 2.x signs
# with SigV4, so the signing region must match the endpoint, and our channels
# now live in different regions -- neither value can be defaulted.
PUBLISH_KEYS = ("download_base_url", "oss_upload_target", "oss_endpoint",
                "oss_region")


def load_channel_config(path: Path, channel: str) -> dict:
    """Flatten the channel's [channel.<name>] section over the shared top-level
    keys. Raises SystemExit if the file or the channel section is absent.
    Does NOT validate completeness — call require_keys() for the pending op.
    """
    if not path.exists():
        raise SystemExit(f"missing {path} (copy release_config.local.toml.example)")
    raw = tomllib.loads(path.read_text())
    shared = {k: v for k, v in raw.items() if k != "channel"}
    channels = raw.get("channel", {})
    if channel not in channels:
        raise SystemExit(f"release config has no [channel.{channel}] section")
    merged = {**shared, **channels[channel]}
    merged.setdefault("git_remote", "origin")
    return merged


def require_keys(cfg: dict, keys: tuple[str, ...]) -> None:
    """Exit non-zero if any of `keys` is missing/empty in cfg."""
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        raise SystemExit(f"release config missing keys: {', '.join(missing)}")


def assert_channel_keys_distinct(path: Path) -> None:
    """Refuse if two channels share a Sparkle public key.

    A shared public key means a shared private key, which means the machine that
    publishes one channel can sign an update the other channel's clients accept.
    That matters most for staging: it is deliberately the weaker environment
    (ciMock, mock IdP, e2e tokens on disk), yet an update it signs would install
    on release clients -- and an update delivers arbitrary code, not just policy.
    The per-environment policy roots do nothing about this; the update chain is a
    second, independent trust chain.

    Config is the only place this can be caught. Nothing downstream can tell two
    identical keys apart.
    """
    raw = tomllib.loads(path.read_text())
    seen: dict[str, str] = {}
    for name, section in raw.get("channel", {}).items():
        key = section.get("public_ed_key")
        if not key:
            continue
        if key in seen:
            raise SystemExit(
                f"channels {seen[key]!r} and {name!r} share the same "
                f"public_ed_key. Each channel needs its own EdDSA key pair: "
                f"sharing one lets whichever machine publishes one channel sign "
                f"updates the other channel's clients will install."
            )
        seen[key] = name


def assert_channel_urls_self_consistent(path: Path, channel: str) -> None:
    """Refuse if a channel's three URL keys disagree about which channel they are.

    The failure this prevents is mundane: copy [channel.canary] to
    [channel.staging] and miss one key. If the missed key is oss_upload_target,
    publishing staging overwrites the RELEASE prefix -- and generate_appcast has
    already deleted the local copies by then, while the objects it overwrites
    are served with immutable cache headers.
    """
    raw = tomllib.loads(path.read_text())
    url_keys = ("feed_url", "download_base_url", "oss_upload_target")
    shared_offenders = [k for k in url_keys if k in raw]
    if shared_offenders:
        raise SystemExit(
            f"{', '.join(shared_offenders)} must not live in the shared "
            f"top-level section of {path}: a shared URL silently applies to "
            f"every channel, which is how one channel ends up publishing over "
            f"another's prefix."
        )
    section = raw.get("channel", {}).get(channel, {})
    missing = [k for k in url_keys if k in section and channel not in section[k]]
    if missing:
        raise SystemExit(
            f"[channel.{channel}] has {', '.join(missing)} not containing "
            f"{channel!r}. Every publish URL must name its own channel, so a "
            f"copied section that was only half-edited fails here rather than "
            f"at upload time."
        )
