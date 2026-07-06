import pytest

import bump_version


def test_bump_hotfix():
    assert bump_version.bump("0.1.12.0", "hotfix") == "0.1.12.1"


def test_bump_patch_zeros_hotfix():
    assert bump_version.bump("0.1.12.1", "patch") == "0.1.13.0"
    assert bump_version.bump("1.2.3.4", "patch") == "1.2.4.0"


def test_bump_minor_zeros_lower():
    assert bump_version.bump("0.1.12.3", "minor") == "0.2.0.0"


def test_bump_major_zeros_lower():
    assert bump_version.bump("1.2.3.4", "major") == "2.0.0.0"


def test_bump_rejects_unknown_part():
    with pytest.raises(ValueError):
        bump_version.bump("0.1.12.0", "build")


def test_bump_rejects_bad_version():
    with pytest.raises(ValueError):
        bump_version.bump("1.2", "patch")
