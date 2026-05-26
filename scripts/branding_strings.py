"""Rebrand Chromium product/company names in chromium_strings.grd + zh .xtb.

English source: standalone "Chromium" -> "Teleport", "(The )Chromium Authors"
-> "BeanSec". zh-CN/zh-TW .xtb values are rebranded to 闪现/閃現 + Chinese company
name and re-keyed to the new source message ids (via in-tree grit). Other locales
fall back to English. Excludes non-product names (ChromiumOS, chromium.org, etc.).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_AUTHORS = re.compile(r"(?:The )?Chromium Authors")
# Standalone product name, but NOT: ChromiumOS / "Chromium Projects" /
# chromium.org, nor the label of an upstream-project link
# (...BEGIN_LINK_CHROMIUM...Chromium...END_LINK_CHROMIUM..., e.g. the "made
# possible by the Chromium open source project" attribution) — that names the
# real Chromium project we build on, not our product.
_PRODUCT = re.compile(
    r'(?<![A-Za-z0-9_])Chromium(?![A-Za-z0-9_])'
    r'(?! Projects)(?! OS)(?! 操作系统)(?!\.org)'
    r'(?!<ph name="END_LINK_CHROMIUM")'
)

_ZH_PRODUCT = {"zh-CN": "闪现", "zh-TW": "閃現"}
_ZH_COMPANY = {"zh-CN": "北京小豆数安科技有限公司", "zh-TW": "北京小豆數安科技有限公司"}


def rebrand_en_text(text: str) -> str:
    text = _AUTHORS.sub("BeanSec", text)
    return _PRODUCT.sub("Teleport", text)


def rebrand_zh_text(text: str, locale: str) -> str:
    text = _AUTHORS.sub(_ZH_COMPANY[locale], text)
    return _PRODUCT.sub(_ZH_PRODUCT[locale], text)


# Product-name messages upstream marks translateable="false"; flip so zh .xtb applies.
_TRANSLATABLE_FALSE_NAMES = ("IDS_PRODUCT_NAME", "IDS_SHORT_PRODUCT_NAME")


def transform_en_grd(grd_text: str) -> str:
    for name in _TRANSLATABLE_FALSE_NAMES:
        grd_text = re.sub(
            r'(<message name="%s"[^>]*?) translateable="false"' % re.escape(name),
            r"\1",
            grd_text,
        )
    return rebrand_en_text(grd_text)


# ---------------------------------------------------------------------------
# grit-based message-id remap + zh .xtb rewrite
#
# grit keys .xtb <translation id="N"> by N = GenerateMessageId(presentable
# source content, meaning) (grit/extern/tclib.py). Rebranding the English
# source changes that content, so N changes and the existing zh translations
# orphan. We use in-tree grit to compute, per message *name*, the id before and
# after rebranding, then rewrite the zh-CN/zh-TW .xtb to use the new ids (and
# localize the value to 闪现/閃現 + Chinese company name).
# ---------------------------------------------------------------------------

# <if expr> variables in chromium_strings.grd that grit does not derive from
# the target platform. Their exact values do not affect message ids (ids depend
# only on source text + meaning); they only select which <if> branch is active.
# Both the old and new grd are parsed with these identical defines, so a message
# name resolves to exactly one node in each and the old->new diff is purely the
# result of the text change. Platform vars (is_win/is_macosx/is_posix/...) are
# resolved by grit from target_platform and must NOT be listed here.
_GRIT_DEFINES = {
    "_is_chrome_for_testing_branded": False,
    "enable_extensions": True,
    "enable_extensions_core": True,
    "is_chromeos": False,
    "use_titlecase": False,
    "toolkit_views": True,
}
_GRIT_TARGET_PLATFORM = "darwin"


def _load_grd_reader(chromium_src: Path):
    grit_root = str(Path(chromium_src) / "tools" / "grit")
    if grit_root not in sys.path:
        sys.path.insert(0, grit_root)
    from grit import grd_reader  # noqa: E402  (path injected above)

    return grd_reader


def message_name_to_id(
    chromium_src: Path, grd_path: Path, grd_dir: Path | None = None
) -> dict[str, str]:
    """Map ``{message name -> grit message id}`` for a grd, computed by grit.

    ``grd_dir`` is the directory grit uses to resolve ``<part>`` includes; it
    defaults to the grd's own directory. When parsing a temporary copy of the
    grd, pass the *real* grd directory so its ``<part file=...>`` siblings still
    resolve.
    """
    grd_reader = _load_grd_reader(chromium_src)
    grd_path = Path(grd_path)
    base_dir = str(grd_dir) if grd_dir is not None else str(grd_path.parent)
    grd = grd_reader.Parse(
        str(grd_path),
        base_dir,
        defines=dict(_GRIT_DEFINES),
        target_platform=_GRIT_TARGET_PLATFORM,
        skip_validation_checks=True,
    )
    grd.SetOutputLanguage("en")
    out: dict[str, str] = {}
    for node in grd.ActiveDescendants():
        if node.name == "message" and "name" in node.attrs:
            cliques = node.GetCliques()
            if cliques:
                # MessageNode has no GetId(); the id lives on its clique's
                # source message (= GenerateMessageId(presentable, meaning)).
                out[node.attrs["name"]] = cliques[0].GetId()
    return out


def build_id_remap(
    chromium_src: Path, old_grd: Path, new_grd: Path, grd_dir: Path | None = None
) -> dict[str, str]:
    """Return ``{old_id -> new_id}`` for every message whose id changed.

    Keyed by message ``name`` so a message keeps its translation across the
    rebrand even though its source-text fingerprint changed. ``grd_dir`` is
    forwarded to :func:`message_name_to_id` for ``<part>`` resolution.
    """
    old = message_name_to_id(chromium_src, old_grd, grd_dir)
    new = message_name_to_id(chromium_src, new_grd, grd_dir)
    return {old[n]: new[n] for n in old if n in new and old[n] != new[n]}


# xtb ids are produced by GenerateMessageId, which masks the high bit, so they
# are always non-negative decimal integers.
_XTB_TRANSLATION = re.compile(
    r'<translation id="(\d+)">(.*?)</translation>', re.DOTALL
)


def rekey_xtb(xtb_text: str, id_remap: dict[str, str], locale: str) -> str:
    """Rewrite a zh .xtb: re-key each translation to the rebranded source id
    and localize the value (Chromium -> 闪现/閃現, authors -> Chinese company)."""

    def repl(m: re.Match[str]) -> str:
        old_id, value = m.group(1), m.group(2)
        new_id = id_remap.get(old_id, old_id)
        return (
            f'<translation id="{new_id}">'
            f"{rebrand_zh_text(value, locale)}</translation>"
        )

    return _XTB_TRANSLATION.sub(repl, xtb_text)


# ---------------------------------------------------------------------------
# main() — apply branding to the real chromium checkout in-place
# ---------------------------------------------------------------------------

import shutil  # noqa: E402
import tempfile  # noqa: E402

from _lib import chromium_src, repo_root  # noqa: E402

# Each target carries the standalone "Chromium" product name in user-visible
# strings. "grd" is the en source; "xtb" are its zh translations to re-key;
# "grdp" are <part file=...> includes that also carry the product name (their
# messages live in the grd's xtb, so rebranding their en text + re-keying the
# grd's xtb rebrands them too — grit parses the full grd incl. <part>). The iOS
# *_chromium_strings.grd are intentionally excluded (not a desktop platform).
_GRD_TARGETS = (
    {
        "grd": "chrome/app/chromium_strings.grd",
        "xtb": {
            "zh-CN": "chrome/app/resources/chromium_strings_zh-CN.xtb",
            "zh-TW": "chrome/app/resources/chromium_strings_zh-TW.xtb",
        },
        "grdp": ("settings_chromium_strings.grdp",),
        # Messages upstream marks translateable="false" (so they had no zh
        # translation). transform_en_grd flips them translateable, but the new
        # id is unkeyed in the xtb -> zh UI falls back to the English name
        # ("Teleport"). Inject 闪现/閃現 for these ids so the product name
        # localizes everywhere it is built from $1 (in-app title, chrome://version
        # first line, and — via infoplist_strings_util.cc — the macOS menu bar).
        "inject": ("IDS_PRODUCT_NAME", "IDS_SHORT_PRODUCT_NAME"),
    },
    {
        "grd": "components/components_chromium_strings.grd",
        "xtb": {
            "zh-CN": "components/strings/components_chromium_strings_zh-CN.xtb",
            "zh-TW": "components/strings/components_chromium_strings_zh-TW.xtb",
        },
        "grdp": (),
        "inject": (),
    },
)


def inject_translations(xtb_text: str, ids, value: str) -> str:
    """Append ``<translation id=ID>value</translation>`` for each id in ``ids``
    not already present in the xtb, just before ``</translationbundle>``.

    Used for messages that had no upstream translation (translateable="false")
    so their re-keyed id is otherwise unkeyed and falls back to English.
    """
    existing = set(re.findall(r'<translation id="(\d+)"', xtb_text))
    additions = "".join(
        f'<translation id="{i}">{value}</translation>\n'
        for i in sorted(set(ids)) if i not in existing
    )
    if not additions:
        return xtb_text
    return xtb_text.replace("</translationbundle>", additions + "</translationbundle>")


def _rebrand_target(src: Path, grd_rel: str, xtb_map: dict, grdp_includes: tuple,
                    inject_names: tuple = ()) -> tuple[int, int]:
    """Rebrand one grd (+ its grdp includes) and re-key its zh xtb in place.

    Returns ``(remapped, injected)``: the count of ids re-keyed (presentable
    text changed) and the count of product-name translations injected per
    locale. Old/new ids come from parsing a pristine snapshot (in a temp dir
    whose <part> filenames match, so the OLD grd resolves to the OLD grdp) vs
    the rebranded grd.
    """
    grd_path = src / grd_rel
    grd_dir = grd_path.parent
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        old_grd = tmp / grd_path.name
        old_grd.write_text(grd_path.read_text(encoding="utf-8"), encoding="utf-8")
        for g in grdp_includes:
            (tmp / g).write_text((grd_dir / g).read_text(encoding="utf-8"), encoding="utf-8")
        grd_path.write_text(transform_en_grd(grd_path.read_text(encoding="utf-8")), encoding="utf-8")
        for g in grdp_includes:
            gp = grd_dir / g
            gp.write_text(rebrand_en_text(gp.read_text(encoding="utf-8")), encoding="utf-8")
        old_ids = message_name_to_id(src, old_grd, tmp)
        new_ids = message_name_to_id(src, grd_path, grd_dir)
        remap = {old_ids[n]: new_ids[n]
                 for n in old_ids if n in new_ids and old_ids[n] != new_ids[n]}
        inject_ids = {new_ids[n] for n in inject_names if n in new_ids}
    for locale, rel in xtb_map.items():
        p = src / rel
        text = rekey_xtb(p.read_text(encoding="utf-8"), remap, locale)
        if inject_ids:
            text = inject_translations(text, inject_ids, _ZH_PRODUCT[locale])
        p.write_text(text, encoding="utf-8")
    return len(remap), len(inject_ids)


def main() -> int:
    src = chromium_src(repo_root())
    total = 0
    for t in _GRD_TARGETS:
        n, injected = _rebrand_target(
            src, t["grd"], t["xtb"], t["grdp"], t.get("inject", ()))
        extra = f", {injected} product-name ids injected" if injected else ""
        print(f"rebranded {t['grd']} (+{len(t['grdp'])} grdp) + zh-CN/zh-TW xtb "
              f"({n} ids remapped{extra})")
        total += n
    print(f"branding_strings: {total} ids remapped across {len(_GRD_TARGETS)} grds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
