"""Tests for the baked policy verification key generator/checker."""
import hashlib

from gen_policy_verification_key import (
    c_array_lines,
    key_hash,
    load_pub_der,
    patch_dev_key,
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


def test_vendored_key_matches_patch() -> None:
    der = load_pub_der()
    patch_der, patch_hash = patch_dev_key()
    assert der == patch_der
    assert key_hash(der) == patch_hash


def test_run_check_passes_on_repo_state() -> None:
    run_check()  # raises SystemExit on mismatch
