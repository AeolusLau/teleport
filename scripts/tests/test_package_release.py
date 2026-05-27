import pytest

import package_release

_FULL = (
    'public_ed_key="k"\n'
    'feed_url="https://h.example.com/a/appcast.xml"\n'
    'download_base_url="https://h.example.com/a/"\n'
    'oss_upload_target="oss://bucket/a/"\n'
    'codesign_identity="Developer ID Application: X (T)"\n'
    'notary_profile="p"\n'
)


def test_load_config_ok(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text(_FULL)
    c = package_release.load_config(cfg)
    assert c["feed_url"].startswith("https://")
    assert c["oss_upload_target"].startswith("oss://")
    assert c["notary_profile"] == "p"


def test_load_config_missing_key_raises(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('feed_url="https://h/a/appcast.xml"\n')
    with pytest.raises(SystemExit):
        package_release.load_config(cfg)
