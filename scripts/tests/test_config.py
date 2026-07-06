import pytest

import _config

_NESTED = (
    'notary_profile = "p"\n'
    'codesign_identity = "Developer ID Application: X (T)"\n'
    "\n"
    "[channel.canary]\n"
    'public_ed_key = "k"\n'
    'feed_url = "https://h.example.com/a/appcast.xml"\n'
    'download_base_url = "https://h.example.com/a/"\n'
    'oss_upload_target = "oss://bucket/a/"\n'
)


def test_load_channel_config_merges_shared_and_channel(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(_NESTED)
    cfg = _config.load_channel_config(p, "canary")
    assert cfg["notary_profile"] == "p"
    assert cfg["feed_url"].startswith("https://")
    assert cfg["oss_upload_target"].startswith("oss://")
    assert cfg["git_remote"] == "origin"  # default applied


def test_load_channel_config_missing_section_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('notary_profile = "p"\n')
    with pytest.raises(SystemExit, match="channel.beta"):
        _config.load_channel_config(p, "beta")


def test_load_channel_config_missing_file_raises(tmp_path):
    with pytest.raises(SystemExit, match="missing"):
        _config.load_channel_config(tmp_path / "nope.toml", "canary")


def test_load_channel_config_respects_explicit_git_remote(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('git_remote = "upstream"\n[channel.canary]\nfeed_url="x"\n')
    cfg = _config.load_channel_config(p, "canary")
    assert cfg["git_remote"] == "upstream"


def test_require_keys_missing_raises():
    with pytest.raises(SystemExit, match="oss_upload_target"):
        _config.require_keys({"feed_url": "x"}, ("feed_url", "oss_upload_target"))


def test_require_keys_present_ok():
    _config.require_keys({"a": "1", "b": "2"}, ("a", "b"))  # no raise


def test_key_tuples_exist():
    assert "public_ed_key" in _config.SPARKLE_KEYS
    assert "feed_url" in _config.SPARKLE_KEYS
    assert "notary_profile" in _config.NOTARIZE_KEYS
    assert set(_config.PUBLISH_KEYS) == {"download_base_url", "oss_upload_target"}
