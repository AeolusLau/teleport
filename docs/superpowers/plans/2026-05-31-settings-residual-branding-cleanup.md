# 共用字符串残留品牌收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把共用字符串超集里指代本产品的 "Chrome"/"Chromium"/"Google Chrome" 统一收口为 Teleport/闪现,并隐藏无后端的 UKM toggle。

**Architecture:** 扩展 `scripts/branding_strings.py` 现成的 grit message-id 重映射机制,新增两个 target(`generated_resources.grd`、`components_strings.grd`)。文本替换层引入一条受保护的 "Chrome" 规则:遮罩 `desc=`/`<ex>`/`_google_chrome` 分支/外部产品 keep-list 后再替换,避免误伤;zh 侧同理并重键四个 `.xtb`。UKM toggle 用一个 settings 资源 patch 裹进 `_google_chrome` 块使其本构建不渲染。纯前端/字符串层,零后端依赖,零新增 C++。

**Tech Stack:** Python 3.13(经 `uv`)、pytest、in-tree grit(`$TELEPORT_CHROMIUM_DIR/src/tools/grit`)、Chromium grd/grdp/xtb 资源、overlay patch(`git apply`)。

参考 spec:`docs/superpowers/specs/2026-05-31-settings-residual-branding-cleanup-design.md`

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `scripts/branding_strings.py` | 品牌重写引擎:文本替换 + grit id 重映射 + xtb 重键 + target 注册表 | 修改:加 "Chrome" 规则与遮罩、`sweep_chrome` 开关、快照策略改造、两个新 target |
| `scripts/tests/test_branding_strings.py` | 现有单测 | 修改:新增文本替换 / 遮罩 / 快照 / 冻结快照测试 |
| `scripts/tests/fixtures/branding_chrome_kept.txt` | 冻结"被保留的 Chrome X 短语"清单(drift 守卫) | 创建(实现期生成+审查后提交) |
| `scripts/tests/fixtures/branding_renamed_generated_resources.txt` | 冻结 generated_resources 被改 message 名单 | 创建(生成+审查) |
| `scripts/tests/fixtures/branding_renamed_components_strings.txt` | 冻结 components_strings 被改 message 名单 | 创建(生成+审查) |
| `patches/chrome/browser/resources/settings/privacy_page/personalization_options.html.patch` | 隐藏 UKM toggle | 创建 |

**约束**:`branding_strings.py` 仍是单文件脚本(现状如此,不拆分);新增逻辑加在其内、保持函数小而聚焦。现有公开函数签名向后兼容(新增参数都有默认值),旧测试不改动即应继续通过。

---

## 背景速览(实现者须知)

- `branding_strings.py` 不是简单文本替换:改了英文源文本会改变 grit 的 message id → zh `.xtb` 翻译按旧 id 失联。脚本用 in-tree grit 算出 `旧id→新id`,再把 `.xtb` 重键并本地化。
- 现有 target 只处理 `chromium_strings.grd` / `components_chromium_strings.grd`,只替换 "Chromium"。
- 本次新增的两个超集是**品牌/非品牌共用**文件:`generated_resources.grd`(26 个 `<part>`)、`components_strings.grd`(67 个 `<part>`)。它们里既有 "Chrome" 又有 "Chromium" 残留。
- **`_google_chrome` 分支不能改**:`<if expr="_google_chrome">...</if>` 内的串本构建不编;遮罩需 depth-aware(分支会嵌套 `<if>`)。
- **外部 Google 产品保留**:`Chrome Web Store`/`Chrome OS`/`Chrome Remote Desktop`/`Chrome Canvas`;`Google Account/Pay/Wallet` 不含 `Chrome` token,天然不受影响。
- 跑测试:仓库根 `uv run pytest scripts/tests/test_branding_strings.py -v`。grit 相关测试需 `export TELEPORT_CHROMIUM_DIR=/abs/path/to/chromium`,否则自动 skip。

---

## Task 1: "Chrome" / "Google Chrome" 文本替换 + keep-list/desc/ex 遮罩

**Files:**
- Modify: `scripts/branding_strings.py`
- Test: `scripts/tests/test_branding_strings.py`

- [ ] **Step 1: Write the failing tests**

追加到 `scripts/tests/test_branding_strings.py` 末尾:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k sweep_chrome -v`
Expected: FAIL — `AttributeError: module 'branding_strings' has no attribute '_sub_chrome'` / `rebrand_en_text() got an unexpected keyword argument 'sweep_chrome'`.

- [ ] **Step 3: Implement the Chrome rule + regex-span masking**

在 `branding_strings.py` 的 `_PRODUCT` 定义之后新增:

```python
# External Google products/platforms: "Chrome X" here is NOT our product name
# and must stay verbatim. (Google Account/Pay/Wallet contain no "Chrome" token,
# so they are unaffected and need not be listed.)
_CHROME_KEEP = (
    "Chrome Web Store",
    "Chrome Remote Desktop",
    "Chrome Canvas",
    "ChromeOS",
    "Chrome OS",
)

# Product-name "Chrome" / "Google Chrome". Word-boundaried so "Chromecast" and
# "Chromium" do not match. "Google Chrome" handled first so "Google" is dropped.
_GOOGLE_CHROME = re.compile(r'(?<![A-Za-z0-9_])Google Chrome(?![A-Za-z0-9_])')
_CHROME = re.compile(r'(?<![A-Za-z0-9_])Chrome(?![A-Za-z0-9_])')

# Spans that must never be rebranded, masked before substitution:
#  - desc="..."  translator notes (not displayed; multi-line, no embedded quotes)
#  - <ex>...</ex>  placeholder example text (not displayed)
_DESC_ATTR = re.compile(r'desc="[^"]*"', re.DOTALL)
_EX_SPAN = re.compile(r'<ex>.*?</ex>', re.DOTALL)
_SENTINEL = "\x00\x00{}\x00\x00"


def _mask_regex_spans(text: str, store: list[str]) -> str:
    """Replace desc=/<ex>/keep-list spans with sentinels; record originals in
    ``store`` (sentinel index = position in store)."""
    for keep in _CHROME_KEEP:
        parts = text.split(keep)
        if len(parts) > 1:
            key = _SENTINEL.format(len(store))
            store.append(keep)
            text = key.join(parts)
    for pat in (_DESC_ATTR, _EX_SPAN):
        def repl(m: "re.Match[str]") -> str:
            key = _SENTINEL.format(len(store))
            store.append(m.group(0))
            return key
        text = pat.sub(repl, text)
    return text


def _restore_spans(text: str, store: list[str]) -> str:
    for i, original in enumerate(store):
        text = text.replace(_SENTINEL.format(i), original)
    return text


def _sub_chrome(text: str, repl: str) -> str:
    """Replace product-name Chrome/Google Chrome with ``repl``, preserving
    desc=/<ex>/keep-list spans. (``_google_chrome`` <if> blocks are masked by
    the caller via :func:`_mask_google_chrome_blocks` in Task 2.)"""
    store: list[str] = []
    masked = _mask_regex_spans(text, store)
    masked = _GOOGLE_CHROME.sub(repl, masked)
    masked = _CHROME.sub(repl, masked)
    return _restore_spans(masked, store)
```

把 `rebrand_en_text` / `rebrand_zh_text` 扩成可选 sweep:

```python
def rebrand_en_text(text: str, sweep_chrome: bool = False) -> str:
    text = _AUTHORS.sub("BeanSec", text)
    text = _PRODUCT.sub("Teleport", text)
    if sweep_chrome:
        text = _sub_chrome(text, "Teleport")
    return text


def rebrand_zh_text(text: str, locale: str, sweep_chrome: bool = False) -> str:
    text = _AUTHORS.sub(_ZH_COMPANY[locale], text)
    text = _PRODUCT.sub(_ZH_PRODUCT[locale], text)
    if sweep_chrome:
        text = _sub_chrome(text, _ZH_PRODUCT[locale])
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k sweep_chrome -v`
Expected: PASS(8 个 sweep_chrome 测试全绿)。

- [ ] **Step 5: Run the full existing suite to confirm no regression**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS(旧测试因默认 `sweep_chrome=False` 不受影响)。

- [ ] **Step 6: Commit**

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py
git commit -m "feat(branding): add guarded Chrome/Google-Chrome text sweep with keep-list"
```

---

## Task 2: depth-aware 遮罩 `_google_chrome` 分支

**Files:**
- Modify: `scripts/branding_strings.py`
- Test: `scripts/tests/test_branding_strings.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k mask_google_chrome -v`
Expected: FAIL — the `_google_chrome` branch's "Chrome" gets replaced (no masking yet).

- [ ] **Step 3: Implement depth-aware if-block masking and wire into `_sub_chrome`**

新增函数:

```python
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
            nxt_if = text.find('<if', j)
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
```

在 `_sub_chrome` 中,于 `_mask_regex_spans` **之前**先遮罩 `_google_chrome` 块:

```python
def _sub_chrome(text: str, repl: str) -> str:
    store: list[str] = []
    masked = _mask_google_chrome_blocks(text, store)
    masked = _mask_regex_spans(masked, store)
    masked = _GOOGLE_CHROME.sub(repl, masked)
    masked = _CHROME.sub(repl, masked)
    return _restore_spans(masked, store)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k "mask_google_chrome or sweep_chrome" -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py
git commit -m "feat(branding): mask nested _google_chrome <if> blocks from Chrome sweep"
```

---

## Task 3: 快照策略改造(支持多 `<part>`,行为等价)

**Files:**
- Modify: `scripts/branding_strings.py:220-253`(`_rebrand_target`)
- Test: `scripts/tests/test_branding_strings.py`

> 现有 `_rebrand_target` 把列出的 grdp include 逐个拷进临时目录算旧 id。新 target 有 26/67 个 part,逐个拷贝不现实。改为"写前先在真实目录算旧 id → 就地改写 → 再算新 id"。

- [ ] **Step 1: Write the failing test**

```python
def test_rebrand_target_handles_unlisted_parts_via_inplace_snapshot(tmp_path):
    """The snapshot must compute old ids from the pristine on-disk grd (so all
    <part> includes resolve) without enumerating them. We assert _rebrand_target
    no longer requires copying grdp includes: it accepts a grd with parts it was
    not told about."""
    src = _chromium_src()
    # generated_resources.grd has 26 <part> includes we do NOT list.
    grd_rel = "chrome/app/generated_resources.grd"
    xtb_map = {
        "zh-CN": "chrome/app/resources/generated_resources_zh-CN.xtb",
        "zh-TW": "chrome/app/resources/generated_resources_zh-TW.xtb",
    }
    # Snapshot originals so we can restore (do not leave the checkout mutated).
    grd_path = src / grd_rel
    backups = {grd_path: grd_path.read_text(encoding="utf-8")}
    for rel in xtb_map.values():
        p = src / rel
        backups[p] = p.read_text(encoding="utf-8")
    try:
        remapped, injected = bs._rebrand_target(
            src, grd_rel, xtb_map, grdp_includes=(), inject_names=(),
            sweep_chrome=True)
        assert remapped > 0  # generated_resources has product-name strings
    finally:
        for p, original in backups.items():
            p.write_text(original, encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k handles_unlisted_parts -v`
Expected: FAIL — `_rebrand_target` 当前签名无 `sweep_chrome`,且其临时拷贝逻辑无法解析未列出的 26 个 part(grit 解析旧 grd 时报缺 part)。

- [ ] **Step 3: Rewrite `_rebrand_target` to snapshot-before-write + thread `sweep_chrome`**

把 `_rebrand_target` 整体替换为:

```python
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
```

同步把下游签名补上 `sweep_chrome`:

```python
def transform_en_grd(grd_text: str, sweep_chrome: bool = False) -> str:
    for name in _TRANSLATABLE_FALSE_NAMES:
        grd_text = re.sub(
            r'(<message name="%s"[^>]*?) translateable="false"' % re.escape(name),
            r"\1", grd_text)
    return rebrand_en_text(grd_text, sweep_chrome)
```

```python
def rekey_xtb(xtb_text, id_remap, locale, sweep_chrome: bool = False):
    def repl(m):
        old_id, value = m.group(1), m.group(2)
        new_id = id_remap.get(old_id, old_id)
        return (f'<translation id="{new_id}">'
                f"{rebrand_zh_text(value, locale, sweep_chrome)}</translation>")
    return _XTB_TRANSLATION.sub(repl, xtb_text)
```

> 旧 `_rebrand_target` 调用点(`main()`)在 Task 4 一并更新;此刻 `main()` 仍用旧 target 列表、默认 `sweep_chrome=False`,行为不变。注意:旧实现里临时目录 + `grdp_includes` 拷贝逻辑被删除,但 `grdp_includes` 仍作为"需要随 grd 改写的 part"参数保留(如 `settings_chromium_strings.grdp`)。

- [ ] **Step 4: Run the new test + full suite**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS(含新测试;旧测试 `test_build_id_remap_only_changed_ids` 等仍绿,因 `build_id_remap`/`message_name_to_id` 未改)。

- [ ] **Step 5: Verify the existing two targets still rebrand correctly end-to-end**

Run(需 checkout;会改写后再用 git 还原):
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && git stash list >/dev/null 2>&1; cd -
uv run python scripts/branding_strings.py
```
Expected: 打印 `rebranded chrome/app/chromium_strings.grd ...` 与 `rebranded components/components_chromium_strings.grd ...`,无报错。随后还原检出:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && git checkout -- chrome/app components/ ; cd -
```

- [ ] **Step 6: Commit**

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py
git commit -m "refactor(branding): snapshot old ids before write to support multi-part grds"
```

---

## Task 4: 接入 `generated_resources.grd` target + 冻结快照测试

**Files:**
- Modify: `scripts/branding_strings.py`(`_GRD_TARGETS`、`main`)
- Create: `scripts/tests/fixtures/branding_renamed_generated_resources.txt`
- Create: `scripts/tests/fixtures/branding_chrome_kept.txt`
- Test: `scripts/tests/test_branding_strings.py`

- [ ] **Step 1: Add the target + per-target `sweep_chrome` flag**

把 `_GRD_TARGETS` 改为带 `sweep_chrome` 键,并追加 generated_resources(现有两项默认 `sweep_chrome=False`):

```python
_GRD_TARGETS = (
    {
        "grd": "chrome/app/chromium_strings.grd",
        "xtb": {"zh-CN": "chrome/app/resources/chromium_strings_zh-CN.xtb",
                "zh-TW": "chrome/app/resources/chromium_strings_zh-TW.xtb"},
        "grdp": ("settings_chromium_strings.grdp",),
        "inject": ("IDS_PRODUCT_NAME", "IDS_SHORT_PRODUCT_NAME"),
        "sweep_chrome": False,
    },
    {
        "grd": "components/components_chromium_strings.grd",
        "xtb": {"zh-CN": "components/strings/components_chromium_strings_zh-CN.xtb",
                "zh-TW": "components/strings/components_chromium_strings_zh-TW.xtb"},
        "grdp": (), "inject": (), "sweep_chrome": False,
    },
    {
        "grd": "chrome/app/generated_resources.grd",
        "xtb": {"zh-CN": "chrome/app/resources/generated_resources_zh-CN.xtb",
                "zh-TW": "chrome/app/resources/generated_resources_zh-TW.xtb"},
        "grdp": (), "inject": (), "sweep_chrome": True,
    },
)
```

更新 `main()` 把 `sweep_chrome` 传下去:

```python
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
```

**关键事实**:`generated_resources.grd` 的可见品牌串大量在 `<part>`(如 `settings_strings.grdp`)里,这些是独立文件。`transform_en_grd` 只作用于传入的 grd 主体文本,**不会**碰到 `<part>` 文件;因此承载可见串的 part 必须列进 target 的 `grdp`(由 `_rebrand_target` 的 grdp 循环各自改写)。Step 1 的 target 已列 `settings_strings.grdp`;实现期须先跑 `grep -l 'Chrome' chrome/app/*.grdp` 确认是否还有别的 generated_resources part 含可见串并补全。

- [ ] **Step 2: Add a read-only probe that reports what a target would change**

新增一个计算函数,供冻结测试与 fixture 生成用。它**就地改写 grd + 列出的 part、算差异、再从快照还原**(不留改动),与现有 `test_build_id_remap_only_changed_ids` 的"临时改写后还原"模式一致:

```python
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
```

- [ ] **Step 3: Write the frozen-snapshot test**

```python
def test_generated_resources_renamed_set_is_frozen():
    src = _chromium_src()
    got = bs.renamed_message_names(
        src, "chrome/app/generated_resources.grd",
        grdp_includes=("settings_strings.grdp",), sweep_chrome=True)
    fixture = Path(__file__).parent / "fixtures" / "branding_renamed_generated_resources.txt"
    if not fixture.exists():
        pytest.skip("fixture not generated yet; run scripts/branding_strings.py probe")
    expected = fixture.read_text(encoding="utf-8").split()
    assert got == sorted(expected), (
        "rebranded message set drifted from frozen fixture — review the diff and "
        "update the fixture only after confirming new entries are correct")
```

- [ ] **Step 4: Generate + review + freeze the fixture**

实现期手动执行(把 probe 输出写进 fixture,**逐项审查**确认无外部产品名被误改、无该改未改):

```bash
mkdir -p scripts/tests/fixtures
uv run python - <<'PY'
import sys; sys.path.insert(0, "scripts")
import branding_strings as bs
from _lib import chromium_src, repo_root
names = bs.renamed_message_names(chromium_src(repo_root()),
    "chrome/app/generated_resources.grd", ("settings_strings.grdp",), True)
open("scripts/tests/fixtures/branding_renamed_generated_resources.txt","w").write(
    "\n".join(names) + "\n")
print(len(names), "names frozen")
PY
```
**审查清单**:对照 `git diff` 看实际文本改动——确认 `Chrome Web Store/OS/Remote Desktop/Canvas` 未被改;`Chrome Colors/Settings/...` 已改为 `闪现`;安全/隐私敏感串语义自然。审查通过后还原检出(`cd "$TELEPORT_CHROMIUM_DIR/src" && git checkout -- chrome/`)。

- [ ] **Step 5: Run tests**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k "generated_resources or sweep_chrome or mask_google" -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py scripts/tests/fixtures/branding_renamed_generated_resources.txt
git commit -m "feat(branding): sweep generated_resources.grd Chrome/Chromium with frozen test"
```

---

## Task 5: 接入 `components_strings.grd` target + 冻结快照

**Files:**
- Modify: `scripts/branding_strings.py`(`_GRD_TARGETS`)
- Create: `scripts/tests/fixtures/branding_renamed_components_strings.txt`
- Test: `scripts/tests/test_branding_strings.py`

- [ ] **Step 1: List which component parts carry visible brand strings**

实现期先跑:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
grep -lE '\bChrom(e|ium)\b' components/*.grdp | sed 's#components/##' | sort
```
把结果(§1 实测含 `management_strings.grdp`、`autofill_payments_strings.grdp`、`autofill_strings.grdp`、`security_interstitials_strings.grdp`、`page_info_strings.grdp`、`password_manager_strings.grdp`、`omnibox_*`、`search_engine_choice_strings.grdp` 等)填入下方 `grdp`。

- [ ] **Step 2: Add the target**

```python
    {
        "grd": "components/components_strings.grd",
        "xtb": {"zh-CN": "components/strings/components_strings_zh-CN.xtb",
                "zh-TW": "components/strings/components_strings_zh-TW.xtb"},
        "grdp": (  # parts carrying visible Chrome/Chromium (from Step 1)
            "management_strings.grdp",
            "autofill_payments_strings.grdp",
            "autofill_strings.grdp",
            "security_interstitials_strings.grdp",
            "page_info_strings.grdp",
            "password_manager_strings.grdp",
            "omnibox_strings.grdp",
            "omnibox_pedal_ui_strings.grdp",
            "search_engine_choice_strings.grdp",
            # ... complete from Step 1 grep
        ),
        "inject": (), "sweep_chrome": True,
    },
```

> 注:components 的 part 在 `components/` 目录下(grd 同目录),`_rebrand_target` 的 `grd_dir / g` 解析正确。

- [ ] **Step 3: Write the frozen-snapshot test**

```python
def test_components_strings_renamed_set_is_frozen():
    src = _chromium_src()
    parts = bs._target_grdp("components/components_strings.grd")  # see Step 4
    got = bs.renamed_message_names(
        src, "components/components_strings.grd", grdp_includes=parts,
        sweep_chrome=True)
    fixture = Path(__file__).parent / "fixtures" / "branding_renamed_components_strings.txt"
    if not fixture.exists():
        pytest.skip("fixture not generated yet")
    assert got == sorted(fixture.read_text(encoding="utf-8").split())
```

- [ ] **Step 4: Add a tiny accessor so the test reads grdp from the registry (DRY)**

```python
def _target_grdp(grd_rel: str) -> tuple:
    for t in _GRD_TARGETS:
        if t["grd"] == grd_rel:
            return t["grdp"]
    raise KeyError(grd_rel)
```

- [ ] **Step 5: Generate + review + freeze the fixture**

```bash
uv run python - <<'PY'
import sys; sys.path.insert(0, "scripts")
import branding_strings as bs
from _lib import chromium_src, repo_root
src = chromium_src(repo_root())
parts = bs._target_grdp("components/components_strings.grd")
names = bs.renamed_message_names(src, "components/components_strings.grd", parts, True)
open("scripts/tests/fixtures/branding_renamed_components_strings.txt","w").write(
    "\n".join(names) + "\n")
print(len(names), "names frozen")
PY
```
**审查清单**(重点):管理页 `IDS_MANAGEMENT_BROWSER_NOTICE`/`..._NOT_MANAGED_NOTICE` 的 "Chromium" 已改;autofill_payments 的 "made in Chromium"/"Chromium will store" 已改;`Google Account/Pay/Wallet` 原样保留;安全拦截页/密码提示语义自然。还原检出。

- [ ] **Step 6: Run tests + Commit**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS。

```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py scripts/tests/fixtures/branding_renamed_components_strings.txt
git commit -m "feat(branding): sweep components_strings.grd Chrome/Chromium with frozen test"
```

---

## Task 6: "被保留的 Chrome X" drift 守卫(keep-list 冻结)

**Files:**
- Modify: `scripts/branding_strings.py`(新增只读扫描函数)
- Create: `scripts/tests/fixtures/branding_chrome_kept.txt`
- Test: `scripts/tests/test_branding_strings.py`

> 目的:rebase 后若上游引入新的 `Chrome <ProperNoun>`,而它不在 keep-list、被错误替换或错误保留,要能暴露。冻结"rebrand 后仍残留于 active body 的 `Chrome <Word>` 短语集合"。

- [ ] **Step 1: Add a read-only scanner for surviving "Chrome X" phrases**

```python
_CHROME_X = re.compile(r'(?<![A-Za-z0-9_])Chrome [A-Z][a-zA-Z]+')

def surviving_chrome_phrases(src: Path, grd_rel: str, grdp_includes: tuple) -> list[str]:
    """Sorted distinct 'Chrome <Word>' phrases that remain after rebranding the
    grd + its listed parts (i.e. the effective keep-list as applied)."""
    found: set[str] = set()
    grd_dir = (src / grd_rel).parent
    texts = [(src / grd_rel).read_text(encoding="utf-8")]
    texts += [(grd_dir / g).read_text(encoding="utf-8") for g in grdp_includes]
    for txt in texts:
        rebranded = rebrand_en_text(txt, sweep_chrome=True)
        found.update(_CHROME_X.findall(rebranded))
    return sorted(found)
```

- [ ] **Step 2: Write the frozen test**

```python
def test_surviving_chrome_phrases_are_frozen():
    src = _chromium_src()
    got = set()
    for grd, parts in (
        ("chrome/app/generated_resources.grd", ("settings_strings.grdp",)),
        ("components/components_strings.grd",
         bs._target_grdp("components/components_strings.grd")),
    ):
        got.update(bs.surviving_chrome_phrases(src, grd, parts))
    fixture = Path(__file__).parent / "fixtures" / "branding_chrome_kept.txt"
    if not fixture.exists():
        pytest.skip("fixture not generated yet")
    assert sorted(got) == sorted(fixture.read_text(encoding="utf-8").split("\n")) , (
        "kept 'Chrome X' phrase set drifted — a new proper noun may need adding "
        "to _CHROME_KEEP, or a string that should rebrand was missed")
```

> 注:fixture 用换行分隔(短语含空格,不能用空白分隔)。生成时 `"\n".join(sorted(got))`。

- [ ] **Step 3: Generate + review + freeze**

```bash
uv run python - <<'PY'
import sys; sys.path.insert(0, "scripts")
import branding_strings as bs
from _lib import chromium_src, repo_root
src = chromium_src(repo_root()); got=set()
for grd,parts in (("chrome/app/generated_resources.grd",("settings_strings.grdp",)),
  ("components/components_strings.grd", bs._target_grdp("components/components_strings.grd"))):
    got.update(bs.surviving_chrome_phrases(src, grd, parts))
open("scripts/tests/fixtures/branding_chrome_kept.txt","w").write("\n".join(sorted(got)))
print(len(got), "kept phrases")
PY
```
**审查**:这份清单应只剩外部 Google 产品(`Chrome Web Store/OS/Remote Desktop/Canvas` 及 §4.3 分类判定保留的项)。若出现本应替换的 `Chrome Colors` 之类,说明该项需从 keep 行为里移除(它本就不在 `_CHROME_KEEP`,出现即 bug,排查 `_sub_chrome`)。

- [ ] **Step 4: Run + Commit**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS。
```bash
git add scripts/branding_strings.py scripts/tests/test_branding_strings.py scripts/tests/fixtures/branding_chrome_kept.txt
git commit -m "test(branding): freeze surviving 'Chrome X' keep-list to catch upstream drift"
```

---

## Task 7: TD-010 — 隐藏 UKM toggle

**Files:**
- Create: `patches/chrome/browser/resources/settings/privacy_page/personalization_options.html.patch`

> `urlCollectionToggle`(`personalization_options.html:93-98`)在 `_google_chrome` 块外,本构建会渲染但 UKM 上送 URL 为空 → 死控件。裹进 `<if expr="_google_chrome">` 使本构建不发出该元素(与相邻 toggle 的上游写法一致)。

- [ ] **Step 1: Produce the patch from the checkout**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git checkout -- chrome/browser/resources/settings/privacy_page/personalization_options.html
```
手动编辑该文件,把第 93–98 行:
```html
    <settings-toggle-button id="urlCollectionToggle"
        class="hr"
        pref="{{prefs.url_keyed_anonymized_data_collection.enabled}}"
        label="$i18n{urlKeyedAnonymizedDataCollection}"
        sub-label="$i18n{urlKeyedAnonymizedDataCollectionDesc}">
    </settings-toggle-button>
```
改为(裹入 `_google_chrome`,使非品牌构建不渲染):
```html
<if expr="_google_chrome">
    <settings-toggle-button id="urlCollectionToggle"
        class="hr"
        pref="{{prefs.url_keyed_anonymized_data_collection.enabled}}"
        label="$i18n{urlKeyedAnonymizedDataCollection}"
        sub-label="$i18n{urlKeyedAnonymizedDataCollectionDesc}">
    </settings-toggle-button>
</if><!-- _google_chrome: UKM toggle has no backend in teleport (TD-010) -->
```

- [ ] **Step 2: Generate the patch file (one file per patch, mirrored path)**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/resources/settings/privacy_page/personalization_options.html \
  > /Users/liulichao/workspace/teleport/patches/chrome/browser/resources/settings/privacy_page/personalization_options.html.patch
git checkout -- chrome/browser/resources/settings/privacy_page/personalization_options.html
```

- [ ] **Step 3: Verify the patch applies idempotently**

Run:
```bash
cd /Users/liulichao/workspace/teleport
uv run python scripts/apply_patches.py
```
Expected: 无报错;再跑一次仍幂等通过(`apply_patches.py` 设计为幂等)。

- [ ] **Step 4: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add patches/chrome/browser/resources/settings/privacy_page/personalization_options.html.patch
git commit -m "feat(settings): hide backendless UKM url-collection toggle (TD-010)"
```

---

## Task 8: 端到端落地 + dev 冒烟 QA

**Files:** 无代码改动(执行 + 目视验收)。

- [ ] **Step 1: Run the full rebrand against a fresh checkout**

```bash
cd /Users/liulichao/workspace/teleport
cd "$TELEPORT_CHROMIUM_DIR/src" && git checkout -- chrome/ components/ ; cd -
uv run python scripts/apply_patches.py
uv run python scripts/branding_strings.py
```
Expected: branding 打印 4 个 target 的 remap 计数(含两个新 target,components 计数应达数百量级)。

- [ ] **Step 2: Full unit suite**

Run: `uv run pytest scripts/tests/test_branding_strings.py -v`
Expected: PASS(全部,含冻结测试)。

- [ ] **Step 3: dev build smoke**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev chrome
```
Expected: 构建成功。运行(加 `--disable-field-trial-config`)后逐屏目视:
- `chrome://settings`(外观/隐私/安全/自动填充/搜索引擎/性能/重置)— 无指代本产品的 "Chrome"/"Chromium",UKM toggle 不出现。
- `chrome://management` — "managed outside of **闪现**"(不再是 Chromium)。
- 触发安全拦截页(自签证书站点)、密码保存提示、地址栏 pedal、付款保存提示 — 品牌串均为 闪现。
- 抽查 `Chrome Web Store`/`Chrome OS` 等仍为原文(若有出现处)。

- [ ] **Step 4: 还原检出 + 最终提交(如有 QA 修正)**

若 QA 发现漏改/误改:回到 Task 4/5 调整 `grdp` 列表或 `_CHROME_KEEP`,更新对应 fixture,重跑。无问题则本任务无新提交。

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && git checkout -- chrome/ components/ ; cd -
```

---

## Self-Review

**Spec coverage:**
- §3 TD-010 → Task 7 ✓
- §4.1 快照改造 → Task 3 ✓
- §4.2 替换模型(Chrome/Google Chrome、desc/ex/keep-list/`_google_chrome` 遮罩、`Google <非Chrome>` 天然保留)→ Task 1 + Task 2 ✓
- §4.3 keep-list + 逐条分类 → Task 1(`_CHROME_KEEP`)+ Task 6 冻结守卫;模糊项逐条分类在 Task 4/5 的 fixture 审查中落定 ✓
- §4.4 xtb 重键(四个 xtb)→ Task 3(`rekey_xtb` 加 sweep)+ Task 4/5 target 的 xtb 映射 ✓
- §5 测试(冻结快照 ×2、幂等、构建冒烟、回归)→ Task 4/5/6(冻结)、Task 3(回归)、Task 8(冒烟);幂等由 `_sub_chrome` 对已替换文本不再命中(已无 "Chrome" token)天然成立,Task 8 Step1 重跑验证 ✓
- §6 风险 → keep-list/冻结测试/目视 QA 覆盖 ✓
- §2 两个超集 → Task 4(generated_resources)+ Task 5(components_strings)✓

**Placeholder scan:** Task 5 的 `grdp` 列表标注"complete from Step 1 grep"、Task 4 的"实现期须先跑 grep 确认是否还有别的 part"——这是**有意的实现期数据收集**(grep 命令已给出),非代码占位。`renamed_message_names` 已给出完整的"就地改写+还原"实现(含 part 循环),无残留骨架。其余步骤均含可执行代码/命令与预期输出。

**Type consistency:** `rebrand_en_text(text, sweep_chrome=False)` / `rebrand_zh_text(text, locale, sweep_chrome=False)` / `transform_en_grd(text, sweep_chrome=False)` / `rekey_xtb(text, remap, locale, sweep_chrome=False)` / `_rebrand_target(..., sweep_chrome=False)` 五处签名在 Task 1/3 一致定义并在 Task 4/5 调用一致;`renamed_message_names` / `surviving_chrome_phrases` / `_target_grdp` / `_sub_chrome` / `_mask_google_chrome_blocks` / `_mask_regex_spans` / `_restore_spans` 命名在引用处一致。
