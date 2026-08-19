"""Tests for the baked policy verification key generator/checker."""
import hashlib

import pytest

import gen_policy_verification_key as g
from gen_policy_verification_key import (
    c_array_lines,
    key_hash,
    load_pub_der,
    run_check,
)


def test_key_hash_derivation() -> None:
    der = b"\x01\x02\x03"
    want = "1:" + hashlib.sha256(der).digest()[:8].hex()
    assert key_hash(der) == want


def test_c_array_lines_format() -> None:
    out = c_array_lines(bytes(range(14)))
    lines = out.splitlines()
    # 12 bytes on the first line, remainder on the second, 4-space indent.
    assert lines[0].startswith("    0x00, 0x01,")
    assert lines[0].endswith("0x0b,")
    assert lines[1] == "    0x0c, 0x0d};"


def test_run_check_passes_on_repo_state() -> None:
    run_check()  # raises SystemExit on mismatch


# --- Tristate: per-environment root sets ----------------------------------


def test_envs_cover_all_three_environments() -> None:
    assert set(g.ENVS) == {"dev", "staging", "release"}


def test_release_has_two_roots_exactly_one_deriving_the_hash() -> None:
    """release bakes a dormant recovery root beside the primary. Only the
    primary derives kPolicyVerificationKeyHash -- that value is what the client
    reports to the server, and the server has exactly one slot for it."""
    roots = g.ENVS["release"]
    assert len(roots) == 2
    assert [r.derives_hash for r in roots] == [True, False]


def test_dev_and_staging_are_single_root() -> None:
    for env in ("dev", "staging"):
        assert len(g.ENVS[env]) == 1
        assert g.ENVS[env][0].derives_hash


def test_every_vendored_pem_is_loadable_and_294_bytes() -> None:
    """294 bytes is the DER SubjectPublicKeyInfo length of an RSA-2048 key,
    which is what the Aliyun KMS teleport-root keys are (key_spec RSA_2048)
    and what the client's RSA_PKCS1_SHA256 verifier expects."""
    for env, roots in g.ENVS.items():
        for r in roots:
            der = load_pub_der(g.REPO / "keys" / r.pem)
            assert len(der) == 294, f"{env}/{r.pem} is {len(der)} bytes"


def test_placeholder_registry_matches_the_current_key_inventory() -> None:
    """Pins which roots are still placeholders.

    When a ceremony produces a real key this test fails until the fingerprint is
    dropped from PLACEHOLDER_ROOTS -- which is the point, since --require-real is
    only ever as good as this registry. It also fails if a stale entry is left
    behind, which would make --require-real reject the very key it now names.
    """
    fps = g.placeholder_fingerprints()
    inventory = {
        r.pem: g.der_fingerprint(load_pub_der(g.REPO / "keys" / r.pem)) in fps
        for roots in g.ENVS.values()
        for r in roots
    }
    assert inventory == {
        # Real: private half committed in fairyland, dev-only trust anchor.
        "dev-policy-root.pub.pem": False,
        # Real since 2026-08-13: private half server-side only, BYOK-imported
        # into staging's OpenBao Transit key.
        "staging-policy-root.pub.pem": False,
        # Placeholder: awaiting the production KMS ceremony (TD-026).
        "release-policy-root.pub.pem": True,
        # Real since 2026-08-10: offline ceremony, private half in cold storage.
        "release-policy-recovery-root.pub.pem": False,
    }


def test_require_real_rejects_a_placeholder_env() -> None:
    """The whole point of --require-real: plain --check is satisfied by a
    placeholder, since the PEM and the patch agree perfectly well about a key
    whose private half was thrown away."""
    with pytest.raises(SystemExit, match="PLACEHOLDER"):
        run_check(env="release", require_real=True)


def test_require_real_accepts_staging() -> None:
    """staging holds a real root as of 2026-08-13, so this must pass -- and it
    must pass for the right reason. A stale placeholder entry left in the
    registry would reject the very key that replaced it."""
    run_check(env="staging", require_real=True)


def test_require_real_on_release_now_fails_only_on_the_primary() -> None:
    """The recovery root is real, so release must fail for exactly one reason.

    This is the acceptance check for importing that key: it proves the import
    narrowed the blocker without unlocking release builds, which stay blocked on
    the primary until its KMS ceremony happens.
    """
    with pytest.raises(SystemExit) as exc:
        run_check(env="release", require_real=True)
    message = str(exc.value)
    assert "release-policy-root.pub.pem is still a PLACEHOLDER" in message
    assert "release-policy-recovery-root.pub.pem" not in message


def test_require_real_accepts_the_dev_root() -> None:
    run_check(env="dev", require_real=True)  # must not raise


def test_run_check_scoped_to_one_env_still_validates_bytes() -> None:
    for env in g.ENVS:
        run_check(env=env)  # raises SystemExit on drift
