import os
from pathlib import Path

import pytest

import branding_strings as bs


def test_rebrand_text_replaces_standalone_product_name():
    src = "Welcome to Chromium\nAbout Chromium Browser"
    assert bs.rebrand_en_text(src) == "Welcome to Teleport\nAbout Teleport Browser"


def test_rebrand_text_replaces_authors():
    assert bs.rebrand_en_text("The Chromium Authors") == "BeanSec"
    assert bs.rebrand_en_text("Chromium Authors") == "BeanSec"


def test_rebrand_text_preserves_non_product_names():
    src = "ChromiumOS visit https://www.chromium.org and the Chromium Projects"
    assert bs.rebrand_en_text(src) == src


def test_rebrand_zh_text():
    assert bs.rebrand_zh_text("关于Chromium", "zh-CN") == "关于闪现"
    assert bs.rebrand_zh_text("关于Chromium", "zh-TW") == "关于閃現"
    assert bs.rebrand_zh_text("The Chromium Authors", "zh-CN") == "北京小豆数安科技有限公司"
    assert bs.rebrand_zh_text("The Chromium Authors", "zh-TW") == "北京小豆數安科技有限公司"


def test_rebrand_text_right_word_boundary():
    # 'Chromium' as a prefix of a longer word must NOT be rebranded
    assert bs.rebrand_en_text("Chromiumize the Chromiumfoo") == "Chromiumize the Chromiumfoo"
    # but a standalone word still rebrands
    assert bs.rebrand_en_text("use Chromium today") == "use Teleport today"


def test_make_product_name_translatable():
    grd = ('<message name="IDS_PRODUCT_NAME" desc="x" translateable="false">\n'
           '  Chromium\n</message>')
    out = bs.transform_en_grd(grd)
    assert 'name="IDS_PRODUCT_NAME"' in out
    assert 'translateable="false"' not in out   # flipped
    assert "Teleport" in out and "Chromium" not in out


def test_transform_en_grd_rebrands_bodies():
    grd = '<message name="IDS_X" desc="d">About Chromium</message>'
    assert "About Teleport" in bs.transform_en_grd(grd)


def test_rebrand_preserves_os_reference():
    assert bs.rebrand_en_text("Chromium OS update") == "Chromium OS update"
    assert bs.rebrand_zh_text("重启以更新 Chromium 操作系统", "zh-CN") == "重启以更新 Chromium 操作系统"
    # but standalone product name still rebrands in zh
    assert bs.rebrand_zh_text("Chromium 是默认浏览器", "zh-CN") == "闪现 是默认浏览器"


# --- Task 4: grit-based id remap + zh xtb rewrite -------------------------

def _chromium_src() -> Path:
    env = os.environ.get("TELEPORT_CHROMIUM_DIR")
    if not env:
        pytest.skip("TELEPORT_CHROMIUM_DIR not set; needs in-tree grit")
    src = Path(env) / "src"
    if not (src / "tools" / "grit").is_dir():
        pytest.skip("in-tree grit not found under $TELEPORT_CHROMIUM_DIR/src")
    return src


def _grit_id(chromium_src: Path, presentable: str) -> str:
    import sys
    sys.path.insert(0, str(chromium_src / "tools" / "grit"))
    from grit.extern import tclib
    return tclib.GenerateMessageId(presentable)


def test_remap_changes_id_when_text_changes():
    src = _chromium_src()
    old_id = _grit_id(src, "About Chromium")
    new_id = _grit_id(src, "About Teleport")
    assert old_id != new_id


def test_rekey_xtb_substitutes_value_and_id():
    xtb = '<translation id="111">关于Chromium</translation>'
    out = bs.rekey_xtb(xtb, {"111": "222"}, "zh-CN")
    assert 'id="222"' in out and "关于闪现" in out and "111" not in out


def test_message_name_to_id_reads_real_grd_stably():
    """grit enumerates message ids deterministically for the real grd."""
    src = _chromium_src()
    grd = src / "chrome" / "app" / "chromium_strings.grd"
    m1 = bs.message_name_to_id(src, grd)
    m2 = bs.message_name_to_id(src, grd)
    assert len(m1) > 100  # the real grd has hundreds of messages
    assert m1 == m2  # ids are stable across parses of the unmodified grd
    assert "IDS_PRODUCT_NAME" in m1


def test_build_id_remap_only_changed_ids():
    """Remapping the pristine grd against its rebranded form yields only
    the ids whose source text changed, keyed old->new."""
    src = _chromium_src()
    grd = src / "chrome" / "app" / "chromium_strings.grd"
    original = grd.read_text(encoding="utf-8")
    transformed = bs.transform_en_grd(original)
    if transformed == original:
        pytest.skip("checkout already rebranded; build_id_remap needs a pristine grd")
    # Both copies live in the real grd dir so <part> includes resolve.
    old_copy = grd.parent / "_branding_old.grd"
    new_copy = grd.parent / "_branding_new.grd"
    try:
        old_copy.write_text(original, encoding="utf-8")
        new_copy.write_text(transformed, encoding="utf-8")
        remap = bs.build_id_remap(src, old_copy, new_copy)
    finally:
        old_copy.unlink(missing_ok=True)
        new_copy.unlink(missing_ok=True)
    assert remap  # rebranding changes at least the product-name ids
    # All keys/values are non-negative numeric strings, and no key maps to itself.
    for old_id, new_id in remap.items():
        assert old_id.isdigit() and new_id.isdigit()
        assert old_id != new_id


# --- attribution link-label preservation + product-name injection ----------

def test_rebrand_preserves_chromium_project_link_label():
    # The "made possible by the Chromium open source project" attribution: the
    # product name rebrands, but the link label (which names the real upstream
    # project) must stay "Chromium".
    src = ('Chromium is made possible by the '
           '<ph name="BEGIN_LINK_CHROMIUM">&lt;a&gt;</ph>'
           'Chromium<ph name="END_LINK_CHROMIUM">&lt;/a&gt;</ph>'
           ' open source project.')
    out = bs.rebrand_en_text(src)
    assert out.startswith("Teleport is made possible by the ")
    assert '</ph>Chromium<ph name="END_LINK_CHROMIUM">' in out
    assert "Teleport open source project" not in out


def test_rebrand_zh_preserves_chromium_project_link_label():
    src = ('<ph name="BEGIN_LINK_CHROMIUM"/>Chromium'
           '<ph name="END_LINK_CHROMIUM"/>开源项目')
    out = bs.rebrand_zh_text(src, "zh-CN")
    assert 'Chromium<ph name="END_LINK_CHROMIUM"/>' in out  # label preserved
    assert "闪现开源项目" not in out


def test_inject_translations_appends_missing_only():
    xtb = ('<translationbundle lang="zh-CN">\n'
           '<translation id="111">x</translation>\n'
           '</translationbundle>')
    out = bs.inject_translations(xtb, {"222", "111"}, "闪现")
    assert '<translation id="222">闪现</translation>' in out  # added
    assert out.count('id="111"') == 1  # not duplicated
    assert bs.inject_translations(out, {"222"}, "闪现") == out  # idempotent
