import pytest

import bump_version


def test_bump_patch():
    assert bump_version.bump("0.1.6", "patch") == "0.1.7"
    assert bump_version.bump("1.2.3", "patch") == "1.2.4"


def test_bump_minor_zeros_patch():
    assert bump_version.bump("0.1.6", "minor") == "0.2.0"
    assert bump_version.bump("1.2.3", "minor") == "1.3.0"


def test_bump_major_zeros_minor_and_patch():
    assert bump_version.bump("0.1.6", "major") == "1.0.0"
    assert bump_version.bump("1.2.3", "major") == "2.0.0"


def test_bump_rejects_unknown_part():
    with pytest.raises(ValueError):
        bump_version.bump("0.1.6", "build")


def test_bump_rejects_bad_version():
    with pytest.raises(ValueError):
        bump_version.bump("1.2", "patch")
