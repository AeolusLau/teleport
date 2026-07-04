import os
import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest

import branding_strings as bs


def test_rebrand_text_replaces_standalone_product_name():
    src = "Welcome to Chromium\nAbout Chromium Browser"
    assert bs.rebrand_en_text(src) == "Welcome to Teleport\nAbout Teleport Browser"


def test_rebrand_text_replaces_authors():
    assert (bs.rebrand_en_text("The Chromium Authors")
            == "Beijing Xiaodou Shuan Technology Co., Ltd.")
    assert (bs.rebrand_en_text("Chromium Authors")
            == "Beijing Xiaodou Shuan Technology Co., Ltd.")


def test_rebrand_text_authors_sentence_final_no_double_period():
    # The replacement ends with "Ltd."; when the source has its own sentence
    # period ("...The Chromium Authors. All rights reserved.") the two must
    # collapse into one, or the about-page copyright renders "Ltd..".
    assert (bs.rebrand_en_text(
        "Copyright 2026 The Chromium Authors. All rights reserved.")
        == "Copyright 2026 Beijing Xiaodou Shuan Technology Co., Ltd. "
           "All rights reserved.")
    # zh replacement has no trailing period: the English sentence period after
    # the company name must survive untouched.
    assert (bs.rebrand_zh_text("The Chromium Authors. 保留所有权利。", "zh-CN")
            == "北京小豆数安科技有限公司. 保留所有权利。")


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


# --- pristine-input mirror ---------------------------------------------------
#
# apply_patches.py rebrands the checkout's grd/grdp/xtb IN PLACE, so the
# working tree normally holds the transform's *output*. Tests that exercise
# the transform need its *input* (pristine upstream text), which is always
# available as git HEAD: the checkout sits detached at the CHROMIUM_VERSION
# tag and all branding edits are unstaged. These helpers materialize HEAD
# content into a tmp mirror that branding_strings can consume as a src root —
# <part> includes resolve inside the mirror, and tools/grit is symlinked so
# _load_grd_reader(mirror) imports the real grit.

_PART_FILE = re.compile(r'<part file="([^"]+)"')
_XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _pristine_bytes(src: Path, rel: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(src), "show", f"HEAD:{rel}"], capture_output=True)
    assert proc.returncode == 0, (
        f"cannot read pristine HEAD:{rel} from the checkout: "
        f"{proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def _materialize_pristine(src: Path, mirror: Path, rel: str, done: set,
                          part_base: PurePosixPath | None = None) -> None:
    """Copy pristine (git HEAD) content of ``rel`` into ``mirror/rel``; for
    grd/grdp files recurse into every ``<part file=...>`` reference (grit
    parses all of them, even inside inactive ``<if>`` blocks, and raises
    FileNotFound for missing ones). grd_reader joins each part path — at any
    nesting depth — onto the top grd's directory, so ``part_base`` stays the
    grd's directory through the whole recursion."""
    if rel in done:
        return
    done.add(rel)
    data = _pristine_bytes(src, rel)
    out = mirror / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    if rel.endswith((".grd", ".grdp")):
        base = part_base or PurePosixPath(rel).parent
        text = _XML_COMMENT.sub("", data.decode("utf-8"))
        for part in _PART_FILE.findall(text):
            _materialize_pristine(src, mirror, (base / part).as_posix(),
                                  done, base)


def _grit_mirror(src: Path, root: Path) -> Path:
    """Prepare ``root`` to act as a chromium-src stand-in for branding_strings:
    tools/grit is symlinked from the real checkout so _load_grd_reader works."""
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "grit").symlink_to(src / "tools" / "grit")
    return root


@pytest.fixture(scope="session")
def pristine(tmp_path_factory):
    """Factory materializing pristine checkout files into a shared mirror.

    Returns ``materialize(*rels) -> Path`` (the mirror root). The mirror is
    session-shared for speed, so tests must leave it as they found it
    (write-then-restore inside the helpers under test is fine); a test that
    rewrites files without restoring must build its own mirror instead."""
    src = _chromium_src()
    mirror = _grit_mirror(src, tmp_path_factory.mktemp("pristine-mirror"))
    done: set[str] = set()

    def materialize(*rels: str) -> Path:
        for rel in rels:
            _materialize_pristine(src, mirror, rel, done)
        return mirror

    return materialize


def test_remap_changes_id_when_text_changes():
    src = _chromium_src()
    old_id = _grit_id(src, "About Chromium")
    new_id = _grit_id(src, "About Teleport")
    assert old_id != new_id


def test_rekey_xtb_substitutes_value_and_id():
    xtb = '<translation id="111">关于Chromium</translation>'
    out = bs.rekey_xtb(xtb, {"111": "222"}, "zh-CN")
    assert 'id="222"' in out and "关于闪现" in out and "111" not in out


def test_rekey_xtb_dedupes_colliding_new_ids():
    # When two old ids remap to the SAME new id (two messages whose rebranded
    # text collapsed to identical content), only ONE <translation> may survive,
    # else grit's xtb_reader asserts on a duplicate translation id at build time.
    xtb = ('<translation id="111">重启Chromium</translation>'
           '<translation id="222">重启Chrome</translation>')
    out = bs.rekey_xtb(xtb, {"111": "999", "222": "999"}, "zh-CN", sweep_chrome=True)
    assert out.count('id="999"') == 1     # duplicate dropped
    assert "重启闪现" in out                # surviving translation localized


def test_message_name_to_id_reads_real_grd_stably(pristine):
    """grit enumerates message ids deterministically for the real grd."""
    mirror = pristine("chrome/app/chromium_strings.grd")
    grd = mirror / "chrome" / "app" / "chromium_strings.grd"
    m1 = bs.message_name_to_id(mirror, grd)
    m2 = bs.message_name_to_id(mirror, grd)
    assert len(m1) > 100  # the real grd has hundreds of messages
    assert m1 == m2  # ids are stable across parses of the unmodified grd
    assert "IDS_PRODUCT_NAME" in m1


def test_build_id_remap_only_changed_ids(pristine):
    """Remapping the pristine grd against its rebranded form yields only
    the ids whose source text changed, keyed old->new."""
    mirror = pristine("chrome/app/chromium_strings.grd")
    grd = mirror / "chrome" / "app" / "chromium_strings.grd"
    original = grd.read_text(encoding="utf-8")
    transformed = bs.transform_en_grd(original)
    assert transformed != original  # pristine input: the transform must bite
    # Both copies live in the mirror grd dir so <part> includes resolve.
    old_copy = grd.parent / "_branding_old.grd"
    new_copy = grd.parent / "_branding_new.grd"
    try:
        old_copy.write_text(original, encoding="utf-8")
        new_copy.write_text(transformed, encoding="utf-8")
        remap = bs.build_id_remap(mirror, old_copy, new_copy)
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


# --- shared-superset "Chrome" sweep -----------------------------------------

def test_sweep_chrome_replaces_standalone_en():
    assert bs.rebrand_en_text("Open Chrome now", sweep_chrome=True) == "Open Teleport now"
    assert bs.rebrand_en_text("Google Chrome is fast", sweep_chrome=True) == "Teleport is fast"


def test_sweep_chrome_default_off_is_backward_compatible():
    # Without the flag, "Chrome" is untouched (existing targets unaffected).
    assert bs.rebrand_en_text("Open Chrome now") == "Open Chrome now"


def test_sweep_chrome_zh():
    assert bs.rebrand_zh_text("在 Chrome 中打开", "zh-CN", sweep_chrome=True) == "在 闪现 中打开"
    assert bs.rebrand_zh_text("Google Chrome 浏览器", "zh-TW", sweep_chrome=True) == "閃現 浏览器"


def test_sweep_chrome_word_boundary():
    assert bs.rebrand_en_text("Chromecast and Chromium", sweep_chrome=True) == "Chromecast and Teleport"


def test_sweep_chrome_keeps_external_products():
    src = "Open the Chrome Web Store on Chrome OS via Chrome Remote Desktop and Chrome Canvas"
    # External products preserved; no standalone Chrome here to replace.
    assert bs.rebrand_en_text(src, sweep_chrome=True) == src


def test_sweep_chrome_keeps_external_but_replaces_standalone():
    src = "Chrome can install apps from the Chrome Web Store"
    assert bs.rebrand_en_text(src, sweep_chrome=True) == "Teleport can install apps from the Chrome Web Store"


def test_sweep_chrome_skips_desc_attribute():
    # desc="" is a translator note, never displayed: must NOT be rebranded.
    grd = '<message name="IDS_X" desc="Shown in Chrome settings">Open Chrome</message>'
    out = bs._sub_chrome(grd, "Teleport")
    assert 'desc="Shown in Chrome settings"' in out   # desc preserved
    assert ">Open Teleport<" in out                    # body replaced


def test_sweep_chrome_skips_ex_example():
    # <ex>Chrome</ex> is placeholder example text, never displayed.
    src = '<ph name="IDS_SHORT_PRODUCT_NAME">$1<ex>Chrome</ex></ph> is updating'
    out = bs._sub_chrome(src, "Teleport")
    assert "<ex>Chrome</ex>" in out          # example preserved
    assert "</ph> is updating" in out


def test_sweep_chrome_skips_google_chrome_in_desc():
    grd = '<message name="IDS_X" desc="Google Chrome sign-in">Sign in to Google Chrome</message>'
    out = bs._sub_chrome(grd, "Teleport")
    assert 'desc="Google Chrome sign-in"' in out
    assert ">Sign in to Teleport<" in out


def test_sweep_chrome_skips_both_desc_and_ex():
    src = '<message name="X" desc="Chrome help"><ph name="P">$1<ex>Chrome</ex></ph> settings</message>'
    out = bs._sub_chrome(src, "Teleport")
    assert 'desc="Chrome help"' in out
    assert "<ex>Chrome</ex>" in out
    assert "</ph> settings" in out


def test_mask_google_chrome_blocks_simple():
    src = ('<if expr="not _google_chrome">Open Chrome</if>'
           '<if expr="_google_chrome">Open Chrome branded</if>')
    out = bs._sub_chrome(src, "Teleport")
    # active (not _google_chrome) branch rebranded; google_chrome branch kept
    assert '>Open Teleport<' in out
    assert 'Open Chrome branded' in out


def test_mask_google_chrome_blocks_nested():
    src = ('<if expr="_google_chrome">'
           '<if expr="not is_chromeos">Use Chrome here</if>'
           '</if>'
           ' and standalone Chrome')
    out = bs._sub_chrome(src, "Teleport")
    assert 'Use Chrome here' in out            # whole google_chrome block kept
    assert 'and standalone Teleport' in out    # outside replaced


def test_mask_google_chrome_blocks_ignores_if_prefixed_tokens():
    # '<if' is a prefix of '<ifoo'; the scanner must not treat it as a nested <if>.
    src = ('<if expr="_google_chrome"><ifoo>Open Chrome</ifoo></if>'
           ' then standalone Chrome')
    out = bs._sub_chrome(src, "Teleport")
    assert '<ifoo>Open Chrome</ifoo>' in out      # google_chrome block kept intact
    assert 'then standalone Teleport' in out      # text after the block rebranded


def test_restore_spans_desc_containing_chrome_keep():
    # A keep-list phrase inside a desc="" produces a nested sentinel; restore
    # must unwrap outer-before-inner (reverse index order) or the inner sentinel
    # is stranded as malformed XML.
    grd = '<message desc="See the Chrome Web Store">Open Chrome</message>'
    out = bs._sub_chrome(grd, "Teleport")
    assert 'desc="See the Chrome Web Store"' in out  # desc intact incl. keep term
    assert ">Open Teleport<" in out                   # body rebranded
    assert "\x00" not in out                           # no sentinel stranded


def test_components_strings_renamed_set_is_frozen(pristine):
    grd = "components/components_strings.grd"
    got = bs.renamed_message_names(pristine(grd), grd, bs._target_grdp(grd),
                                   sweep_chrome=True)
    fixture = Path(__file__).parent / "fixtures" / "branding_renamed_components_strings.txt"
    assert fixture.exists(), "fixture not generated yet — see Step 3"
    expected = fixture.read_text(encoding="utf-8").split()
    assert got == sorted(expected), (
        "rebranded components message set drifted from frozen fixture — review the "
        "diff and update the fixture only after confirming new entries are correct")


def test_generated_resources_renamed_set_is_frozen(pristine):
    grd = "chrome/app/generated_resources.grd"
    got = bs.renamed_message_names(pristine(grd), grd, bs._target_grdp(grd),
                                   sweep_chrome=True)
    fixture = Path(__file__).parent / "fixtures" / "branding_renamed_generated_resources.txt"
    assert fixture.exists(), "fixture not generated yet — see Step 4"
    expected = fixture.read_text(encoding="utf-8").split()
    assert got == sorted(expected), (
        "rebranded message set drifted from frozen fixture — review the diff and "
        "update the fixture only after confirming new entries are correct")


def test_rebrand_target_handles_unlisted_parts_via_inplace_snapshot(tmp_path):
    """The snapshot must compute old ids from the pristine on-disk grd (so all
    <part> includes resolve) without enumerating them. We assert _rebrand_target
    no longer requires copying grdp includes: it accepts a grd with parts it was
    not told about. Runs on a private mirror (not the session-shared one):
    _rebrand_target rewrites the grd + xtbs in place and does not restore."""
    src = _chromium_src()
    grd_rel = "chrome/app/generated_resources.grd"
    xtb_map = {
        "zh-CN": "chrome/app/resources/generated_resources_zh-CN.xtb",
        "zh-TW": "chrome/app/resources/generated_resources_zh-TW.xtb",
    }
    mirror = _grit_mirror(src, tmp_path)
    done: set[str] = set()
    for rel in (grd_rel, *xtb_map.values()):
        _materialize_pristine(src, mirror, rel, done)
    remapped, injected = bs._rebrand_target(
        mirror, grd_rel, xtb_map, grdp_includes=(), inject_names=(),
        sweep_chrome=True)
    assert remapped > 0  # generated_resources has product-name strings


def test_sweep_chrome_keeps_external_products_zh():
    """Chinese external-product phrases must survive the zh sweep unchanged."""
    # zh-CN: Chrome 应用商店 (Web Store), Chrome 操作系统 (OS), and
    # standalone Chrome (our browser) must still be rebranded.
    src_cn = "在 Chrome 应用商店 中安装，或直接打开 Chrome 浏览器"
    out_cn = bs.rebrand_zh_text(src_cn, "zh-CN", sweep_chrome=True)
    assert "Chrome 应用商店" in out_cn          # external product kept
    assert "打开 闪现 浏览器" in out_cn          # standalone Chrome rebranded

    # zh-CN: additional external forms
    assert "Chrome 操作系统" in bs.rebrand_zh_text(
        "更新 Chrome 操作系统", "zh-CN", sweep_chrome=True)
    assert "Chrome 企业核心版" in bs.rebrand_zh_text(
        "试用 Chrome 企业核心版", "zh-CN", sweep_chrome=True)
    assert "Chrome 远程桌面" in bs.rebrand_zh_text(
        "通过 Chrome 远程桌面连接", "zh-CN", sweep_chrome=True)
    assert "Chrome 浏览器云管理" in bs.rebrand_zh_text(
        "注册 Chrome 浏览器云管理", "zh-CN", sweep_chrome=True)

    # zh-TW: Chrome 線上應用程式商店 (Web Store TW) and Chrome Enterprise
    src_tw = "前往 Chrome 線上應用程式商店 查找，或使用 Chrome 瀏覽器"
    out_tw = bs.rebrand_zh_text(src_tw, "zh-TW", sweep_chrome=True)
    assert "Chrome 線上應用程式商店" in out_tw   # TW external product kept
    assert "使用 閃現 瀏覽器" in out_tw           # standalone Chrome rebranded

    # zh-TW: Chrome Enterprise must survive (TW uses English "Enterprise")
    assert "Chrome Enterprise" in bs.rebrand_zh_text(
        "試用 Chrome Enterprise 基本版", "zh-TW", sweep_chrome=True)


def test_surviving_chrome_phrases_are_frozen(pristine):
    got = set()
    for grd in ("chrome/app/generated_resources.grd",
                "components/components_strings.grd"):
        got.update(bs.surviving_chrome_phrases(pristine(grd), grd,
                                               bs._target_grdp(grd)))
    fixture = Path(__file__).parent / "fixtures" / "branding_chrome_kept.txt"
    assert fixture.exists(), "fixture not generated yet — see Step 3"
    expected = fixture.read_text(encoding="utf-8").split("\n")
    expected = [e for e in expected if e]  # drop trailing empty
    assert sorted(got) == sorted(expected), (
        "kept 'Chrome X' phrase set drifted — a new proper noun may need adding "
        "to _CHROME_KEEP, or a string that should rebrand was missed")


# --- frozen-snapshot tests for the 3 new standalone grds --------------------

@pytest.mark.parametrize("grd_rel,fixture_name", [
    (
        "components/privacy_sandbox_strings.grd",
        "branding_renamed_privacy_sandbox_strings.txt",
    ),
    (
        "extensions/strings/extensions_strings.grd",
        "branding_renamed_extensions_strings.txt",
    ),
    (
        "components/plus_addresses/core/browser/resources/strings/plus_addresses_strings.grd",
        "branding_renamed_plus_addresses_strings.txt",
    ),
])
def test_standalone_grd_renamed_set_is_frozen(grd_rel, fixture_name, pristine):
    """Frozen snapshot of message names that change under sweep_chrome rebranding.

    Mirrors test_generated_resources_renamed_set_is_frozen for the three
    standalone grds that were previously missing from _GRD_TARGETS.
    """
    got = bs.renamed_message_names(pristine(grd_rel), grd_rel,
                                   bs._target_grdp(grd_rel), sweep_chrome=True)
    fixture = Path(__file__).parent / "fixtures" / fixture_name
    assert fixture.exists(), f"fixture not generated yet: {fixture_name}"
    expected = fixture.read_text(encoding="utf-8").split()
    assert got == sorted(expected), (
        f"rebranded message set for {grd_rel} drifted from frozen fixture — "
        "review the diff and update the fixture only after confirming new entries are correct"
    )
