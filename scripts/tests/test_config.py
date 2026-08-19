"""Tests for the release config loader and its cross-channel invariants."""
import pytest

import _config


def _write(tmp_path, body: str):
    p = tmp_path / "release_config.local.toml"
    p.write_text(body)
    return p


def test_sparkle_keys_include_a_signing_account():
    """Naming the keychain account is what makes per-channel signing keys
    expressible at all; the default picks the single "ed25519" entry."""
    assert "ed_key_account" in _config.SPARKLE_KEYS


def test_duplicate_public_ed_key_across_channels_is_rejected(tmp_path):
    """Two channels sharing an EdDSA public key share the private one, which
    puts a release-accepted signing capability on the staging release machine.
    An update delivers arbitrary code, so this is a heavier exposure than the
    policy chain the per-environment roots protect."""
    cfg = _write(tmp_path, '''
notary_profile = "p"
[channel.canary]
public_ed_key = "SAME"
ed_key_account = "ed25519"
[channel.staging]
public_ed_key = "SAME"
ed_key_account = "ed25519-staging"
''')
    with pytest.raises(SystemExit, match="public_ed_key"):
        _config.assert_channel_keys_distinct(cfg)


def test_distinct_public_ed_keys_are_accepted(tmp_path):
    cfg = _write(tmp_path, '''
[channel.canary]
public_ed_key = "AAA"
[channel.staging]
public_ed_key = "BBB"
''')
    _config.assert_channel_keys_distinct(cfg)


def test_channel_urls_must_contain_the_channel_name(tmp_path):
    """The failure this prevents: copy [channel.canary] to [channel.staging]
    and miss one key. If the missed key is oss_upload_target, publishing
    staging overwrites the release prefix -- after generate_appcast has already
    deleted the local copies, over objects served with immutable cache headers."""
    cfg = _write(tmp_path, '''
[channel.staging]
feed_url = "https://h/staging/appcast.xml"
download_base_url = "https://h/staging/"
oss_upload_target = "oss://b/canary/"
''')
    with pytest.raises(SystemExit, match="oss_upload_target"):
        _config.assert_channel_urls_self_consistent(cfg, "staging")


def test_url_keys_must_not_live_in_the_shared_section(tmp_path):
    """A URL in the shared section silently applies to every channel, which is
    the same collision arriving by a different route."""
    cfg = _write(tmp_path, '''
feed_url = "https://h/canary/appcast.xml"
[channel.staging]
download_base_url = "https://h/staging/"
oss_upload_target = "oss://b/staging/"
''')
    with pytest.raises(SystemExit, match="shared"):
        _config.assert_channel_urls_self_consistent(cfg, "staging")


def test_self_consistent_channel_passes(tmp_path):
    cfg = _write(tmp_path, '''
[channel.staging]
feed_url = "https://h/staging/appcast.xml"
download_base_url = "https://h/staging/"
oss_upload_target = "oss://b/staging/"
''')
    _config.assert_channel_urls_self_consistent(cfg, "staging")
