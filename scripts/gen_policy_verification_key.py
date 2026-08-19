"""Generate / verify the baked Teleport policy verification roots.

Each deployment environment bakes its own trusted root set; the PUBLIC halves
are vendored under keys/ and baked into
patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch.
This script is the single generator/verifier for that content:

  uv run python scripts/gen_policy_verification_key.py                  # print C snippet (all envs)
  uv run python scripts/gen_policy_verification_key.py --env release    # one env
  uv run python scripts/gen_policy_verification_key.py --check          # verify patch == keys
  uv run python scripts/gen_policy_verification_key.py --check --require-real --env release

Which roots are real, and where their private halves live:

  dev              real -- private half deliberately COMMITTED in the fairyland
                   repo as a dev-only anchor (durability over secrecy).
  staging          real -- private half lives server-side only, BYOK-imported
                   into staging's OpenBao Transit key. Never copied into this
                   repo: verification needs the public half and nothing else.
  release primary  PLACEHOLDER -- private half discarded at generation, pending
                   the production ceremony.
  release recovery real -- offline ceremony, private half in cold storage.

--require-real is what makes that distinction machine-checkable: plain --check is
satisfied by a placeholder, because the PEM and the patch agree about it
perfectly well. Only PLACEHOLDER_ROOTS knows the difference.

Hash derivation: "1:" + first 8 bytes of SHA-256(DER SPKI), lowercase hex.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUB_PEM = REPO / "keys" / "dev-policy-root.pub.pem"
PATCH = (
    REPO
    / "patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch"
)


@dataclass(frozen=True)
class RootSpec:
    symbol: str         # C array symbol name inside the patch
    pem: str            # filename under keys/
    derives_hash: bool  # kPolicyVerificationKeyHash comes from this root


# Which roots each environment bakes, and under what symbol.
#
# release carries a dormant recovery root beside the primary. Baking a public key
# is irreversible in the direction that matters -- a client shipped without one
# can never be taught to trust it later -- so it goes in from the first release
# build even though its ceremony has not happened. Only the primary derives
# kPolicyVerificationKeyHash: that is the value the client reports to the server,
# and the wire protocol has exactly one slot for it.
ENVS: dict[str, tuple[RootSpec, ...]] = {
    "dev": (RootSpec("kDevPolicyKey", "dev-policy-root.pub.pem", True),),
    "staging": (RootSpec("kStagingPolicyKey", "staging-policy-root.pub.pem", True),),
    "release": (
        RootSpec("kReleasePolicyKey", "release-policy-root.pub.pem", True),
        RootSpec(
            "kReleasePolicyRecoveryKey",
            "release-policy-recovery-root.pub.pem",
            False,
        ),
    ),
}

# Fingerprint (full SHA-256 of the DER SPKI) -> note, for every root known to be
# a throwaway placeholder. Registering them is what lets --require-real refuse a
# build that claims a real KMS key while still baking one of these.
PLACEHOLDER_ROOTS: dict[str, str] = {
    "a6d2a37bee6b696c4caba24d7c737dc6b1b774b50245709c5c5e8eedf666d933":
        "release primary placeholder (pre-KMS ceremony)",
    # Retired placeholder fingerprints are deliberately NOT retained here. A
    # stale entry would make --require-real reject the very real key that has
    # since taken the file's place, so this table tracks the CURRENT contents of
    # keys/ rather than accumulating history:
    #   81c6dfed... release recovery placeholder, replaced 2026-08-10
    #   526fcb2b... staging placeholder, replaced 2026-08-13
}


def load_pub_der(pem_path: Path = PUB_PEM) -> bytes:
    m = re.search(
        r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----",
        pem_path.read_text(),
        re.S,
    )
    if not m:
        raise SystemExit(f"no PUBLIC KEY block in {pem_path}")
    return base64.b64decode("".join(m.group(1).split()))


def key_hash(der: bytes) -> str:
    return "1:" + hashlib.sha256(der).digest()[:8].hex()


def c_array_lines(der: bytes) -> str:
    """Format DER bytes in the patch's style: 12 bytes/line, 4-space indent,
    closing `};` glued to the last byte."""
    hexes = [f"0x{b:02x}" for b in der]
    lines = [
        "    " + ", ".join(hexes[i : i + 12]) + ","
        for i in range(0, len(hexes), 12)
    ]
    lines[-1] = lines[-1].rstrip(",") + "};"
    return "\n".join(lines)


def der_fingerprint(der: bytes) -> str:
    """Full SHA-256 of the DER SPKI, hex. Distinct from key_hash(), which is the
    truncated form the wire protocol carries."""
    return hashlib.sha256(der).hexdigest()


def placeholder_fingerprints() -> dict[str, str]:
    """Fingerprint -> note, for every root whose private half was discarded."""
    return dict(PLACEHOLDER_ROOTS)


def patch_key(spec: RootSpec, patch_path: Path = PATCH) -> bytes:
    """The DER bytes baked for `spec` in the patch text. Tolerant of diff `+`
    prefixes: it matches byte tokens only."""
    text = patch_path.read_text()
    m = re.search(rf"{spec.symbol}\[\] = \{{(.*?)\}};", text, re.S)
    if not m:
        raise SystemExit(f"{spec.symbol} block not found in {patch_path}")
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9a-fA-F]{2})", m.group(1)))


def patch_hash_for(spec: RootSpec, patch_path: Path = PATCH) -> str:
    """The kPolicyVerificationKeyHash belonging to `spec`'s preprocessor branch:
    the first one after the key block, having confirmed no branch delimiter sits
    in between.

    The positional search alone would silently pick up a neighbouring branch's
    hash if the block order ever changed -- and the failure mode of pairing a key
    with the wrong hash is a client that reports an anchor it does not hold, which
    the server can only answer with a refusal that looks like an outage.
    """
    text = patch_path.read_text()
    m = re.search(rf"{spec.symbol}\[\] = \{{.*?\}};", text, re.S)
    if not m:
        raise SystemExit(f"{spec.symbol} block not found in {patch_path}")
    rest = text[m.end():]
    hm = re.search(r'kPolicyVerificationKeyHash\[\] = "([^"]+)"', rest)
    if not hm:
        raise SystemExit(f"no kPolicyVerificationKeyHash after {spec.symbol}")
    if re.search(r"^\+?\s*#\s*(elif|else|endif)\b", rest[: hm.start()], re.M):
        raise SystemExit(
            f"{spec.symbol}'s hash lookup crossed a preprocessor branch -- the "
            f"patch layout changed; fix patch_hash_for()"
        )
    return hm.group(1)


def run_check(env: str | None = None, require_real: bool = False) -> None:
    envs = [env] if env else list(ENVS)
    problems: list[str] = []
    for e in envs:
        for spec in ENVS[e]:
            der = load_pub_der(REPO / "keys" / spec.pem)
            if patch_key(spec) != der:
                problems.append(
                    f"{e}: {spec.symbol} bytes != vendored {spec.pem}"
                )
            if spec.derives_hash:
                baked = patch_hash_for(spec)
                if baked != key_hash(der):
                    problems.append(
                        f"{e}: kPolicyVerificationKeyHash {baked!r} != "
                        f"derived {key_hash(der)!r} from {spec.pem}"
                    )
            if require_real:
                note = PLACEHOLDER_ROOTS.get(der_fingerprint(der))
                if note:
                    problems.append(
                        f"{e}: {spec.pem} is still a PLACEHOLDER ({note}); "
                        f"vendor the real KMS public key before claiming it is real"
                    )
    if problems:
        raise SystemExit(
            "policy verification root drift:\n  - "
            + "\n  - ".join(problems)
            + "\nRegenerate the patch content with "
            "scripts/gen_policy_verification_key.py."
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the patch matches the vendored keys")
    ap.add_argument("--env", choices=sorted(ENVS),
                    help="limit to one environment (default: all)")
    ap.add_argument("--require-real", action="store_true",
                    help="also fail if any checked root is a known placeholder")
    args = ap.parse_args()

    if args.check or args.require_real:
        run_check(env=args.env, require_real=args.require_real)
        scope = args.env or "all environments"
        extra = " (all roots real)" if args.require_real else ""
        print(f"policy verification roots OK: {scope}{extra}")
        return

    print("// generated by scripts/gen_policy_verification_key.py")
    for e in [args.env] if args.env else list(ENVS):
        print(f"// --- {e} ---")
        for spec in ENVS[e]:
            der = load_pub_der(REPO / "keys" / spec.pem)
            print(f"const uint8_t {spec.symbol}[] = {{")
            print(c_array_lines(der))
            if spec.derives_hash:
                print(
                    f'const char kPolicyVerificationKeyHash[] = "{key_hash(der)}";'
                )


if __name__ == "__main__":
    main()
