"""Release config: nested [channel.x] TOML loader + per-operation key checks.

Top-level keys are account-shared (notary_profile, codesign_identity,
git_remote); [channel.<name>] holds per-channel publish settings (Sparkle
public key, feed URL, OSS endpoints). Validation is deferred to require_keys()
so each operation only demands what it actually needs (a dev build needs no
config at all; a local channel package needs stamp+notarize keys; publishing
additionally needs the OSS keys).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

# Keys required per operation phase.
STAMP_KEYS = ("public_ed_key", "feed_url")
NOTARIZE_KEYS = ("notary_profile",)
PUBLISH_KEYS = ("download_base_url", "oss_upload_target")


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
