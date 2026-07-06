"""Release helpers: teleport semver parsing/comparison and the appcast guard."""
from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_semver(version: str) -> tuple[int, int, int, int]:
    """Parse 'MAJOR.MINOR.BUILD[.PATCH]' into a comparable 4-tuple.

    A missing 4th segment defaults to 0 so pre-4-segment history (old tags and
    feed items like '0.1.12') stays comparable. New TELEPORT_VERSION values
    must be written 4-segment — enforced by read_teleport_version().
    """
    m = _VERSION_RE.match(version.strip())
    if not m:
        raise ValueError(f"not a MAJOR.MINOR.BUILD[.PATCH] version: {version!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4) or 0))


def is_newer(candidate: str, baseline: str) -> bool:
    """True iff candidate semver is strictly greater than baseline semver."""
    return parse_semver(candidate) > parse_semver(baseline)


import xml.etree.ElementTree as ET
from pathlib import Path

_SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def max_appcast_version(appcast_xml: str) -> str | None:
    """Highest sparkle:version across <item>s, or None for an empty feed.

    Accepts sparkle:version either as a child element or as an attribute on the
    <enclosure> (both forms occur in the wild).
    """
    root = ET.fromstring(appcast_xml)
    best: tuple[int, int, int, int] | None = None
    best_raw: str | None = None
    for item in root.iter("item"):
        el = item.find(f"{{{_SPARKLE_NS}}}version")
        if el is not None and el.text:
            raw = el.text.strip()
        else:
            enc = item.find("enclosure")
            raw = enc.get(f"{{{_SPARKLE_NS}}}version") if enc is not None else None
        if not raw:
            continue
        try:
            t = parse_semver(raw)
        except ValueError:
            continue
        if best is None or t > best:
            best, best_raw = t, raw
    return best_raw


def assert_publishable(new_version: str, appcast_xml: str | None) -> None:
    """Exit non-zero if new_version is not strictly newer than the feed's max."""
    if not appcast_xml or not appcast_xml.strip():
        return
    current = max_appcast_version(appcast_xml)
    if current is None:
        return
    if not is_newer(new_version, current):
        raise SystemExit(
            f"refusing to publish {new_version}: not newer than current feed max {current}"
        )


def read_teleport_version(root: Path | None = None) -> str:
    """Read + validate the 4-segment TELEPORT_VERSION from the repo root."""
    from _lib import repo_root
    p = (root or repo_root()) / "TELEPORT_VERSION"
    v = p.read_text().strip()
    if v.count(".") != 3:
        raise ValueError(
            f"TELEPORT_VERSION must be 4-segment MAJOR.MINOR.BUILD.PATCH, got {v!r}")
    parse_semver(v)  # validate digits; raises on garbage
    return v
