from pathlib import Path

import pytest

import sync


def test_parse_chrome_version(tmp_path: Path):
    v = tmp_path / "VERSION"
    v.write_text("MAJOR=148\nMINOR=0\nBUILD=7000\nPATCH=3\n")
    assert sync.parse_chrome_version(v) == "148.0.7000.3"


def test_verify_version_mismatch_raises(tmp_path: Path):
    v = tmp_path / "VERSION"
    v.write_text("MAJOR=150\nMINOR=0\nBUILD=1\nPATCH=0\n")
    with pytest.raises(RuntimeError):
        sync.verify_version(v, "148.0.7000.3")


def test_verify_version_match_ok(tmp_path: Path):
    v = tmp_path / "VERSION"
    v.write_text("MAJOR=148\nMINOR=0\nBUILD=7000\nPATCH=3\n")
    sync.verify_version(v, "148.0.7000.3")  # must not raise
