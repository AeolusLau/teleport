"""Rebrand Chromium product/company names in chromium_strings.grd + zh .xtb.

English source: standalone "Chromium" -> "Teleport", "(The )Chromium Authors"
-> "Beijing Xiaodou Shuan Technology Co., Ltd.". zh-CN/zh-TW .xtb values are
rebranded to 闪现/閃現 + Chinese company name and re-keyed to the new source
message ids (via in-tree grit). Other locales fall back to English. Excludes
non-product names (ChromiumOS, chromium.org, etc.).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path, PurePosixPath

_AUTHORS = re.compile(r"(?:The )?Chromium Authors")
# The English company name ends with an abbreviation period ("Ltd."). Where the
# source has its own sentence period right after the authors name, absorb it —
# substituting the bare pattern alone would render "Ltd.." in the copyright.
_AUTHORS_SENTENCE = re.compile(r"(?:The )?Chromium Authors\.")
_COMPANY_EN = "Beijing Xiaodou Shuan Technology Co., Ltd."
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

# External Google products/platforms whose name contains a word-boundary
# "Chrome" token must stay verbatim. (Single-token names like "ChromeOS" or
# "Chromecast" are already excluded by the word-boundary regex, and
# "Google Account/Pay/Wallet" contain no "Chrome" token — so neither needs
# listing here.)
_CHROME_KEEP = (
    "Chrome Web Store",
    "Chrome Remote Desktop",
    "Chrome Canvas",
    "Chrome OS",
    # Google PKI infrastructure names (not our product's feature names):
    "Chrome Root Store",
    "Chrome Root Program",
    # Legacy platform name that users and developers still reference externally:
    "Chrome Apps",
    # External developer-documentation brand (links to Google's extension docs):
    "Chrome Extension developer",
    # Google enterprise management products/services (not our product's features):
    "Chrome Browser Cloud Management",
    "Chrome Enterprise Connectors",
    "Chrome Enterprise Core",
    # Alternate (no-space) spelling of the Chrome Web Store used in policy strings:
    "Chrome Webstore",
)

# Chinese forms of the external products in _CHROME_KEEP. zh xtb values write
# these as "Chrome <中文>" / "Chromium <中文>"; without masking, the standalone
# "Chrome" token inside them would be wrongly rebranded to 闪现/閃現.
# zh-CN (Simplified) forms:
#   - Chrome 应用商店  = Chrome Web Store
#   - Chrome 远程桌面  = Chrome Remote Desktop
#   - Chrome 企业核心版 = Chrome Enterprise Core
#   - Chrome 企业版接口 = Chrome Enterprise Connectors
#   - Chrome 操作系统  = Chrome OS
#   - Chrome 浏览器云管理 = Chrome Browser Cloud Management
# zh-TW (Traditional) forms (may differ in vocabulary):
#   - Chrome 線上應用程式商店 = Chrome Web Store (TW)
#   - Chrome 遠端桌面       = Chrome Remote Desktop (TW)
#   - Chrome Enterprise     = Chrome Enterprise products (TW uses English "Enterprise")
#   - Chrome 作業系統       = Chrome OS (TW)
#   - Chrome 瀏覽器雲端管理  = Chrome Browser Cloud Management (TW)
# Note: do NOT add our-product forms like "Chrome 設定" / "Chrome 中" — those
# are correct rebranding targets.
_CHROME_KEEP_ZH = (
    # zh-CN (Simplified Chinese) external product forms
    "Chrome 应用商店",
    "Chrome 远程桌面",
    "Chrome 企业核心版",
    "Chrome 企业版接口",
    "Chrome 操作系统",
    "Chrome 浏览器云管理",
    # zh-TW (Traditional Chinese) external product forms
    "Chrome 線上應用程式商店",
    "Chrome 遠端桌面",
    "Chrome Enterprise",
    "Chrome 作業系統",
    "Chrome 瀏覽器雲端管理",
)

# Product-name "Chrome" / "Google Chrome". Word-boundaried so "Chromecast" and
# "Chromium" do not match. "Google Chrome" handled first so "Google" is dropped.
_GOOGLE_CHROME = re.compile(r'(?<![A-Za-z0-9_])Google Chrome(?![A-Za-z0-9_])')
_CHROME = re.compile(r'(?<![A-Za-z0-9_])Chrome(?![A-Za-z0-9_])')

# Spans that must never be rebranded, masked before substitution:
#  - desc="..."  translator notes (not displayed; multi-line, no embedded quotes)
#  - <ex>...</ex>  placeholder example text (not displayed)
_DESC_ATTR = re.compile(r'desc="[^"]*"')
_EX_SPAN = re.compile(r'<ex>.*?</ex>', re.DOTALL)
_SENTINEL = "\x00\x00{}\x00\x00"


def _mask_google_chrome_blocks(text: str, store: list[str]) -> str:
    """Mask ``<if expr="_google_chrome">...</if>`` blocks (depth-aware over
    nested ``<if ...>``) so their bodies are never rebranded."""
    open_tag = '<if expr="_google_chrome">'
    out: list[str] = []
    i = 0
    while True:
        start = text.find(open_tag, i)
        if start == -1:
            out.append(text[i:])
            break
        out.append(text[i:start])
        depth = 0
        j = start
        n = len(text)
        while j < n:
            nxt_if = text.find('<if ', j)  # trailing space: grit <if> tags always have expr="..."
            nxt_end = text.find('</if>', j)
            if nxt_end == -1:
                j = n
                break
            if nxt_if != -1 and nxt_if < nxt_end:
                depth += 1
                j = nxt_if + 3
            else:
                depth -= 1
                j = nxt_end + len('</if>')
                if depth == 0:
                    break
        key = _SENTINEL.format(len(store))
        store.append(text[start:j])
        out.append(key)
        i = j
    return "".join(out)


def _mask_regex_spans(text: str, store: list[str],
                      keep: tuple[str, ...] = _CHROME_KEEP) -> str:
    """Replace desc=/<ex>/keep-list spans with sentinels; record originals in
    ``store`` (sentinel index = position in store).

    ``keep`` defaults to ``_CHROME_KEEP`` (English) but callers may pass
    ``_CHROME_KEEP + _CHROME_KEEP_ZH`` for zh xtb values so that Chinese
    external-product phrases are masked before the Chrome substitution runs.
    """
    for phrase in keep:
        parts = text.split(phrase)
        if len(parts) > 1:
            key = _SENTINEL.format(len(store))
            store.append(phrase)
            text = key.join(parts)

    def repl(m: "re.Match[str]") -> str:
        key = _SENTINEL.format(len(store))
        store.append(m.group(0))
        return key

    for pat in (_DESC_ATTR, _EX_SPAN):
        text = pat.sub(repl, text)
    return text


def _restore_spans(text: str, store: list[str]) -> str:
    # Restore in reverse order: later-masked items may embed earlier sentinels
    # (e.g. a desc= attribute that contains a _CHROME_KEEP string). Restoring
    # highest index first brings nested sentinels back into text so earlier
    # iterations can then replace them correctly.
    for i in range(len(store) - 1, -1, -1):
        text = text.replace(_SENTINEL.format(i), store[i])
    return text


def _sub_chrome(text: str, repl: str,
                keep: tuple[str, ...] = _CHROME_KEEP) -> str:
    """Replace product-name Chrome/Google Chrome with ``repl``, preserving
    desc=/<ex>/keep-list spans and <if expr="_google_chrome">...</if> blocks
    (whose bodies compile only in Google-branded builds we never produce).

    Pass ``keep=_CHROME_KEEP + _CHROME_KEEP_ZH`` when processing zh xtb values
    so that Chinese external-product phrases (e.g. "Chrome 应用商店") survive
    the substitution unchanged.
    """
    store: list[str] = []
    masked = _mask_google_chrome_blocks(text, store)
    masked = _mask_regex_spans(masked, store, keep)
    masked = _GOOGLE_CHROME.sub(repl, masked)
    masked = _CHROME.sub(repl, masked)
    return _restore_spans(masked, store)


def rebrand_en_text(text: str, sweep_chrome: bool = False) -> str:
    text = _AUTHORS_SENTENCE.sub(_COMPANY_EN, text)
    text = _AUTHORS.sub(_COMPANY_EN, text)
    text = _PRODUCT.sub("Teleport", text)
    if sweep_chrome:
        text = _sub_chrome(text, "Teleport")
    return text


def rebrand_zh_text(text: str, locale: str, sweep_chrome: bool = False) -> str:
    text = _AUTHORS.sub(_ZH_COMPANY[locale], text)
    text = _PRODUCT.sub(_ZH_PRODUCT[locale], text)
    if sweep_chrome:
        text = _sub_chrome(text, _ZH_PRODUCT[locale],
                           keep=_CHROME_KEEP + _CHROME_KEEP_ZH)
    return text


# Product-name messages upstream marks translateable="false"; flip so zh .xtb applies.
_TRANSLATABLE_FALSE_NAMES = ("IDS_PRODUCT_NAME", "IDS_SHORT_PRODUCT_NAME")


def transform_en_grd(grd_text: str, sweep_chrome: bool = False) -> str:
    for name in _TRANSLATABLE_FALSE_NAMES:
        grd_text = re.sub(
            r'(<message name="%s"[^>]*?) translateable="false"' % re.escape(name),
            r"\1",
            grd_text,
        )
    return rebrand_en_text(grd_text, sweep_chrome)


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

# <if expr> variables that grit does not derive from the target platform. Their
# exact values do not affect message ids (ids depend only on source text +
# meaning); they only select which <if> branch is active. Both the old and new
# grd are parsed with these identical defines, so a message name resolves to
# exactly one node in each and the old->new diff is purely the result of the
# text change. Platform vars (is_win/is_macosx/is_posix/...) are resolved by
# grit from target_platform and must NOT be listed here.
_GRIT_DEFINES = {
    "_google_chrome": False,
    "_is_chrome_for_testing_branded": False,
    "chrome_root_store_cert_management_ui": True,  # is_win||is_mac||is_linux||is_chromeos (chrome/common/features.gni)
    "enable_arcore": False,
    "enable_cardboard": False,
    "enable_extensions": True,
    "enable_extensions_core": True,
    "enable_pdf": True,
    "enable_pdf_ink2": True,
    "enable_pdf_save_to_drive": True,
    "enable_print_preview": True,
    "enable_printing": True,
    "enable_screen_ai_service": True,
    "enable_vr": False,
    "enable_webui_ntp": True,  # target_os=="mac" default (ui/webui/webui_features.gni)
    "enable_webui_tab_strip": False,
    "is_android": False,
    "is_cfm": False,
    "is_chromeos": False,
    "reven": False,
    "toolkit_views": True,
    "use_blink": True,
    "use_titlecase": False,
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


def active_message_sources(
    chromium_src: Path, grd_path: Path, grd_dir: Path | None = None
) -> dict[str, str | None]:
    """Map ``{message name -> nearest enclosing <part file=...> value}`` for
    every ACTIVE message in a grd, as grit resolves it for our target platform
    + defines (so ``<if expr="is_android">``-only parts, etc. are correctly
    excluded). ``None`` means the message is declared directly in the grd, not
    inside a ``<part>``.

    Lets a caller tell which physical ``.grdp`` file backs a given message
    name without re-deriving grit's own splicing: a ``<part>`` node is a real
    ancestor in the parsed tree (grit/node/misc.py ``PartNode``, a
    ``SplicingNode``), so the nearest ``part`` ancestor's ``file`` attribute is
    exactly the file grit spliced that message in from. Used to catch a
    ``<part>`` upstream added to a tracked grd that we forgot to register in
    that target's ``grdp`` tuple (see test_branding_strings.py).
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
    out: dict[str, str | None] = {}
    for node in grd.ActiveDescendants():
        if node.name == "message" and "name" in node.attrs and node.GetCliques():
            source = None
            ancestor = node.parent
            while ancestor is not None:
                if ancestor.name == "part":
                    source = ancestor.attrs.get("file")
                    break
                ancestor = ancestor.parent
            out[node.attrs["name"]] = source
    return out


def id_for_message_name(
    chromium_src: Path, grd_path: Path, name: str, grd_dir: Path | None = None
) -> str:
    """Return the grit message id for a single message ``name`` in ``grd_path``.

    Thin wrapper over :func:`message_name_to_id` (grit has no cheaper
    single-message lookup — computing one id still walks the whole grd). Gives
    callers that need to hand-key a zh .xtb ``<translation id=...>`` for a
    *new* message a name-keyed entry point instead of re-deriving the id map
    inline, so the id is guaranteed to match what grit will emit at build time.
    """
    return message_name_to_id(chromium_src, grd_path, grd_dir)[name]


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


def rekey_xtb(xtb_text: str, id_remap: dict[str, str], locale: str,
              sweep_chrome: bool = False) -> str:
    """Rewrite a zh .xtb: re-key each translation to the rebranded source id
    and localize the value (Chromium -> 闪现/閃現, authors -> Chinese company).

    Rebranding can collapse two distinct messages onto one grit content id when
    their rebranded source text becomes identical (e.g. the branded/non-branded
    "Relaunch Chrome"/"Relaunch Chromium" variants both -> "Relaunch Teleport").
    Their translations then re-key to the same id; emitting both would produce a
    duplicate <translation id=...> that makes grit's xtb_reader assert at build
    time. Keep only the first occurrence of each (post-remap) id — collapsed
    messages share identical rebranded text, so their translations are equal."""

    seen: set[str] = set()

    def repl(m: re.Match[str]) -> str:
        old_id, value = m.group(1), m.group(2)
        new_id = id_remap.get(old_id, old_id)
        if new_id in seen:
            return ""  # duplicate after id collapse: drop (first one is kept)
        seen.add(new_id)
        return (f'<translation id="{new_id}">'
                f"{rebrand_zh_text(value, locale, sweep_chrome)}</translation>")

    return _XTB_TRANSLATION.sub(repl, xtb_text)


# ---------------------------------------------------------------------------
# main() — apply branding to the real chromium checkout in-place
# ---------------------------------------------------------------------------

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
        "sweep_chrome": False,
    },
    {
        "grd": "components/components_chromium_strings.grd",
        "xtb": {
            "zh-CN": "components/strings/components_chromium_strings_zh-CN.xtb",
            "zh-TW": "components/strings/components_chromium_strings_zh-TW.xtb",
        },
        "grdp": (),
        "inject": (),
        "sweep_chrome": False,
    },
    {
        "grd": "components/components_strings.grd",
        "xtb": {
            "zh-CN": "components/strings/components_strings_zh-CN.xtb",
            "zh-TW": "components/strings/components_strings_zh-TW.xtb",
        },
        "grdp": (
            "arc_strings.grdp",
            "autofill_payments_strings.grdp",
            "autofill_strings.grdp",
            "browsing_data_strings.grdp",
            "collaboration_strings.grdp",
            "commerce_strings.grdp",
            "contextual_cueing_strings.grdp",
            "error_page_strings.grdp",
            "heavy_ad_intervention_strings.grdp",
            "history_strings.grdp",
            "management_strings.grdp",
            "new_or_sad_tab_strings.grdp",
            # Nested <part> of omnibox_strings.grdp (not a direct child of the
            # grd), but grit resolves <part file=...> relative to the grd's own
            # base dir regardless of nesting depth, so a bare filename here
            # still rewrites it correctly -- see
            # test_all_active_grdp_parts_are_registered_or_product_name_free.
            "omnibox_pedal_ui_strings.grdp",
            "omnibox_strings.grdp",
            "page_info_strings.grdp",
            "password_manager_strings.grdp",
            "payments_strings.grdp",
            "pdf_strings.grdp",
            "permissions_strings.grdp",
            "policy_strings.grdp",
            "privacy_sandbox_chrome_strings.grdp",
            "reset_password_strings.grdp",
            "search_engine_choice_strings.grdp",
            "security_interstitials_strings.grdp",
            "send_tab_to_self_strings.grdp",
            "smart_tab_sharing.grdp",
            "ssl_errors_strings.grdp",
        ),
        "inject": (),
        "sweep_chrome": True,
    },
    {
        "grd": "chrome/app/generated_resources.grd",
        "xtb": {
            "zh-CN": "chrome/app/resources/generated_resources_zh-CN.xtb",
            "zh-TW": "chrome/app/resources/generated_resources_zh-TW.xtb",
        },
        "grdp": (
            "access_code_cast_strings.grdp",
            "actor_strings.grdp",
            "app_management_strings.grdp",
            "certificate_manager.grdp",
            "extensions_strings.grdp",
            "glic_strings.grdp",
            "media_router_strings.grdp",
            "password_manager_ui_strings.grdp",
            "printing_strings.grdp",
            "profiles_strings.grdp",
            "settings_strings.grdp",
            "shared_settings_strings.grdp",
            "skills_strings.grdp",
            "support_tool_strings.grdp",
        ),
        "inject": (),
        "sweep_chrome": True,
    },
    # Standalone component grds that carry displayed product-name strings and
    # compile into the desktop browser but are not included in any of the above
    # targets.  Each has its own .xtb files.
    {
        "grd": "components/privacy_sandbox_strings.grd",
        "xtb": {
            "zh-CN": "components/strings/privacy_sandbox_strings_zh-CN.xtb",
            "zh-TW": "components/strings/privacy_sandbox_strings_zh-TW.xtb",
        },
        "grdp": (), "inject": (), "sweep_chrome": True,
    },
    {
        "grd": "extensions/strings/extensions_strings.grd",
        "xtb": {
            "zh-CN": "extensions/strings/extensions_strings_zh-CN.xtb",
            "zh-TW": "extensions/strings/extensions_strings_zh-TW.xtb",
        },
        "grdp": (), "inject": (), "sweep_chrome": True,
    },
    {
        # No zh xtb files upstream (translations section intentionally empty per
        # crbug.com/326392415); xtb map is empty so only the en grd is rebranded.
        "grd": "components/plus_addresses/core/browser/resources/strings/plus_addresses_strings.grd",
        "xtb": {},
        "grdp": (), "inject": (), "sweep_chrome": True,
    },
)


def touched_paths() -> set[str]:
    """Every chromium/src-relative path this module rewrites.

    export_patches.py consumes this so the generated-file set is derived rather
    than hand-maintained — a hand-written list would silently drift the moment a
    target is added here.
    """
    paths: set[str] = set()
    for target in _GRD_TARGETS:
        grd = PurePosixPath(target["grd"])
        paths.add(str(grd))
        paths.update(target["xtb"].values())
        for grdp in target["grdp"]:
            paths.add(str(grd.parent / grdp))
    return paths


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
                    inject_names: tuple = (), sweep_chrome: bool = False
                    ) -> tuple[int, int]:
    """Rebrand one grd (+ its grdp includes) and re-key its zh xtb in place.

    Old ids are read from the pristine on-disk grd *before* any write, so all
    <part> includes resolve in their real directory without being enumerated.
    Then the grd (+ listed grdp) are rewritten in place and new ids are read.
    Returns ``(remapped, injected)``.
    """
    grd_path = src / grd_rel
    grd_dir = grd_path.parent
    old_ids = message_name_to_id(src, grd_path, grd_dir)        # pristine
    grd_path.write_text(
        transform_en_grd(grd_path.read_text(encoding="utf-8"), sweep_chrome),
        encoding="utf-8")
    for g in grdp_includes:
        gp = grd_dir / g
        gp.write_text(rebrand_en_text(gp.read_text(encoding="utf-8"), sweep_chrome),
                      encoding="utf-8")
    new_ids = message_name_to_id(src, grd_path, grd_dir)        # rebranded
    remap = {old_ids[n]: new_ids[n]
             for n in old_ids if n in new_ids and old_ids[n] != new_ids[n]}
    inject_ids = {new_ids[n] for n in inject_names if n in new_ids}
    for locale, rel in xtb_map.items():
        p = src / rel
        text = rekey_xtb(p.read_text(encoding="utf-8"), remap, locale, sweep_chrome)
        if inject_ids:
            text = inject_translations(text, inject_ids, _ZH_PRODUCT[locale])
        p.write_text(text, encoding="utf-8")
    return len(remap), len(inject_ids)


def renamed_message_names(src: Path, grd_rel: str, grdp_includes: tuple,
                          sweep_chrome: bool) -> list[str]:
    """Sorted active-message *names* whose presentable text changes under
    rebranding the grd + its listed parts. Rebrands in place, then restores
    every touched file from a snapshot — the checkout is left unchanged."""
    grd_path = src / grd_rel
    grd_dir = grd_path.parent
    before = message_name_to_id(src, grd_path, grd_dir)
    paths = [grd_path] + [grd_dir / g for g in grdp_includes]
    originals = {p: p.read_text(encoding="utf-8") for p in paths}
    try:
        grd_path.write_text(
            transform_en_grd(originals[grd_path], sweep_chrome), encoding="utf-8")
        for g in grdp_includes:
            gp = grd_dir / g
            gp.write_text(rebrand_en_text(originals[gp], sweep_chrome),
                          encoding="utf-8")
        after = message_name_to_id(src, grd_path, grd_dir)
    finally:
        for p, original in originals.items():
            p.write_text(original, encoding="utf-8")
    return sorted(n for n in before if n in after and before[n] != after[n])


def _target_grdp(grd_rel: str) -> tuple:
    for t in _GRD_TARGETS:
        if t["grd"] == grd_rel:
            return t["grdp"]
    raise KeyError(grd_rel)


_CHROME_X = re.compile(r'(?<![A-Za-z0-9_])Chrome [A-Z][a-zA-Z]+')


def _displayed_text_only(text: str) -> str:
    """Drop non-displayed spans (desc="" notes, <ex> examples, _google_chrome
    <if> blocks) so a scan sees only what users actually see. Keep-list phrases
    are deliberately left intact."""
    store: list[str] = []
    text = _mask_google_chrome_blocks(text, store)  # -> sentinels (no "Chrome X")
    text = _DESC_ATTR.sub("", text)
    text = _EX_SPAN.sub("", text)
    return text


def surviving_chrome_phrases(src: Path, grd_rel: str, grdp_includes: tuple) -> list[str]:
    """Sorted distinct 'Chrome <Word>' phrases that remain in DISPLAYED text
    after rebranding the grd + its listed parts (i.e. the effective kept
    external-product set). Reads files into memory only; never modifies the
    checkout."""
    found: set[str] = set()
    grd_dir = (src / grd_rel).parent
    texts = [(src / grd_rel).read_text(encoding="utf-8")]
    texts += [(grd_dir / g).read_text(encoding="utf-8") for g in grdp_includes]
    for txt in texts:
        rebranded = rebrand_en_text(txt, sweep_chrome=True)
        found.update(_CHROME_X.findall(_displayed_text_only(rebranded)))
    return sorted(found)


def main() -> int:
    src = chromium_src(repo_root())
    total = 0
    for t in _GRD_TARGETS:
        n, injected = _rebrand_target(
            src, t["grd"], t["xtb"], t["grdp"], t.get("inject", ()),
            sweep_chrome=t.get("sweep_chrome", False))
        extra = f", {injected} product-name ids injected" if injected else ""
        print(f"rebranded {t['grd']} (+{len(t['grdp'])} grdp) + zh-CN/zh-TW xtb "
              f"({n} ids remapped{extra})")
        total += n
    print(f"branding_strings: {total} ids remapped across {len(_GRD_TARGETS)} grds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
