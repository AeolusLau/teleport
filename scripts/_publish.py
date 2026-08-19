"""Publish phase: branch/clean/already-published guards, appcast generation,
OSS upload, and version tagging. Distributable channels only.
"""
from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from _lib import repo_root
from _package import sparkle_bin
from _release import assert_publishable


def fetch_live_appcast(feed_url: str) -> str | None:
    """The live appcast, or None when the feed genuinely does not exist yet.

    Only a 404 counts as "no feed yet". Every other failure is raised, because
    returning None on, say, a timeout would make assert_publishable a no-op --
    and that is one of only two guards against republishing a version over an
    immutable OSS object. A blocked publisher is not hypothetical here: staging
    is meant to sit behind an IP allowlist.
    """
    try:
        with urllib.request.urlopen(feed_url) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # first release: no feed yet
        raise SystemExit(
            f"refusing to publish: fetching the appcast at {feed_url} failed "
            f"with HTTP {e.code}. Treating that as 'no feed yet' would disable "
            f"the already-published check."
        )
    except Exception as e:
        raise SystemExit(
            f"refusing to publish: could not fetch the appcast at {feed_url} "
            f"({type(e).__name__}: {e}). Treating that as 'no feed yet' would "
            f"disable the already-published check."
        )


def current_branch() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def assert_on_main() -> None:
    branch = current_branch()
    if branch != "main":
        raise SystemExit(
            f"refusing to publish from branch {branch!r}; switch to main"
        )


def assert_clean_tree() -> None:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    if r.stdout.strip():
        raise SystemExit(
            "refusing to publish with a dirty working tree; commit or stash first"
        )


def tag_name(version: str, channel: str) -> str:
    """Release tags stay `v<version>`; other channels get their own namespace.

    staging and release share TELEPORT_VERSION, so a single namespace would make
    them collide: rehearsing 0.2.0.0 on staging would then make the real release
    of 0.2.0.0 refuse itself as already tagged. Namespacing keeps the intended
    workflow -- rehearse a version, then ship that same version -- possible,
    while still giving staging a local, authoritative record that it published.
    """
    if channel == "staging":
        return f"staging/v{version}"
    return f"v{version}"


def tag_exists(version: str, channel: str) -> bool:
    r = subprocess.run(
        ["git", "tag", "--list", tag_name(version, channel)],
        cwd=repo_root(), capture_output=True, text=True, check=True,
    )
    return bool(r.stdout.strip())


def assert_not_published(version: str, channel: str,
                         appcast_xml: str | None) -> None:
    """Refuse if `version` is already released -- by git tag OR by the live feed.

    Tag check is local and authoritative for anything we published (we always
    tag on publish). Feed check is defense-in-depth for a publish from another
    machine that never pushed a tag.
    """
    if tag_exists(version, channel):
        raise SystemExit(
            f"refusing to publish {version}: tag {tag_name(version, channel)} "
            f"already exists; bump TELEPORT_VERSION"
        )
    assert_publishable(version, appcast_xml)


def generate_appcast(updates_dir: Path, download_base_url: str,
                     keep_dmg: str, ed_key_account: str) -> None:
    """Trim staging dir to the single current dmg, then run generate_appcast.

    Keeping only the current dmg makes the appcast list just the latest version
    and avoids dangling .delta references (generate_appcast preserves
    pre-existing delta entries even with --maximum-deltas 0).
    """
    for p in updates_dir.iterdir():
        if p.is_file() and p.name != keep_dmg:
            p.unlink()
    subprocess.run([
        str(sparkle_bin("generate_appcast")),
        # Name the keychain account explicitly: the default picks the single
        # "ed25519" entry, which is how every channel came to share one signing
        # key. The private half never leaves the keychain either way.
        "--account", ed_key_account,
        "--maximum-deltas", "0",
        "--download-url-prefix", download_base_url,
        str(updates_dir),
    ], check=True)


def _oss_credentials() -> tuple[str, str]:
    """The OSS access key from the environment, required to be present.

    Read here and handed to ossutil via -i/-k rather than left for ossutil to
    discover, because ossutil prefers ~/.ossutilconfig OVER the environment. On
    a machine that has ever configured another bucket -- which is any machine
    that has published a different channel -- exporting these variables is
    silently ignored and the request goes out as the wrong RAM user.

    That failure does not look like a local mistake. It surfaces as
    "AccessDenied ... the bucket you access does not belong to you" against the
    target bucket, which reads exactly like the other side botched their grant.
    It cost a full cross-repo round-trip and a retracted BLOCKER report before
    anyone suspected the client. Hence: nothing about identity, endpoint or
    region is left for ossutil to infer.

    (The key does appear in the process list for the duration of the upload.
    That is accepted: publishing is a local, interactive operation, and the
    alternative -- writing the secret to a config file -- persists it.)
    """
    key_id = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    missing = [
        name for name, value in (
            ("ALIBABA_CLOUD_ACCESS_KEY_ID", key_id),
            ("ALIBABA_CLOUD_ACCESS_KEY_SECRET", secret),
        ) if not value
    ]
    if missing:
        raise SystemExit(
            f"refusing to upload: {', '.join(missing)} not set. Export the "
            f"credential for THIS channel's bucket. Falling back to whatever "
            f"~/.ossutilconfig holds would publish as a different identity, or "
            f"fail in a way that looks like someone else's misconfiguration."
        )
    return key_id, secret


def upload_to_oss(updates_dir: Path, target: str, endpoint: str,
                  region: str) -> None:
    """Upload dmg(s) + appcast.xml to OSS with correct cache headers.

    Versioned dmgs are immutable -> long cache; appcast.xml changes every
    release -> never cache.

    endpoint and region are per-channel and both required: ossutil 2.x signs
    with SigV4, so -e alone leaves the signing region at whatever the config
    file says and the request is rejected with "Invalid signing region in
    Authorization header". Our channels now live in different regions, so
    neither can be a default.
    """
    key_id, secret = _oss_credentials()
    auth = ["-i", key_id, "-k", secret, "-e", endpoint, "--region", region]
    for dmg in sorted(updates_dir.glob("*.dmg")):
        subprocess.run(
            ["ossutil", "cp", "-f", str(dmg), target, *auth,
             "--cache-control", "public, max-age=31536000, immutable"],
            check=True,
        )
    subprocess.run(
        ["ossutil", "cp", "-f", str(updates_dir / "appcast.xml"), target, *auth,
         "--cache-control", "no-cache"],
        check=True,
    )


def tag_and_push(version: str, channel: str, remote: str) -> None:
    """Annotated-tag HEAD for this channel and push the tag to `remote`."""
    name = tag_name(version, channel)
    subprocess.run(
        ["git", "tag", "-a", name, "-m", f"release {version}"],
        cwd=repo_root(), check=True,
    )
    subprocess.run(["git", "push", remote, name], cwd=repo_root(), check=True)
