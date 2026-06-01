"""Package-state cache: fingerprint a built .app, persist a per-channel state
manifest, and decide whether a previously-notarized dmg can be reused.

The reuse gate is fail-closed: a hit requires the (unsigned) app to be
byte-identical to the last successful package AND the signing-affecting key
fields to match. Caller additionally `stapler validate`s the dmg before reuse.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def app_content_digest(app: Path) -> str:
    """SHA-256 over every entry under ``app`` (sorted relative posix path), so
    any content/structure change flips the digest. Symlinks contribute their
    target text (not dereferenced); files contribute path + size + bytes."""
    h = hashlib.sha256()
    for p in sorted(app.rglob("*"), key=lambda x: x.relative_to(app).as_posix()):
        rel = p.relative_to(app).as_posix()
        if p.is_symlink():
            h.update(f"L\0{rel}\0{os.readlink(p)}\0".encode("utf-8"))
        elif p.is_file():
            h.update(f"F\0{rel}\0{p.stat().st_size}\0".encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()


def state_path(repo_root_dir: Path, channel_name: str) -> Path:
    """Per-channel manifest path, kept OUTSIDE dist/<channel>/ because
    generate_appcast trims that dir to the single current dmg."""
    return repo_root_dir / "dist" / ".package-state" / f"{channel_name}.json"


def reuse_key(version: str, channel_name: str, identity: str,
              notary_profile: str, app_digest: str) -> dict:
    """The fields that must all match for a previously-notarized dmg to be
    reusable: app content + every signing/notarization-affecting input."""
    return {
        "version": version,
        "channel": channel_name,
        "identity": identity,
        "notary_profile": notary_profile,
        "app_digest": app_digest,
    }


def load_state(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def write_state(path: Path, key: dict, dmg_name: str) -> None:
    """Bind the reuse key to the produced dmg. Call ONLY after notarize+staple
    succeeds, so the manifest never points at an un-notarized artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**key, "dmg_name": dmg_name}, indent=2),
                    encoding="utf-8")


def can_reuse(state: dict | None, key: dict, dmg_path: Path) -> bool:
    """Pure gate (no I/O beyond dmg existence): the stored state must match the
    current key exactly, name the same dmg, and that dmg must exist. The caller
    additionally `stapler validate`s the dmg before actually reusing it."""
    if state is None:
        return False
    if any(state.get(k) != v for k, v in key.items()):
        return False
    return state.get("dmg_name") == dmg_path.name and dmg_path.exists()
