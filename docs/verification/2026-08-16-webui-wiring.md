# 验证结论:`teleport://enroll` 页的完整接线(Task 10 Step 1)

- 日期:2026-08-16
- 仓库:`/Users/liulichao/workspace/teleport/.worktrees/tunnel-webapp-compat`
- 上游检出:`/Users/liulichao/workspace/chromium/151.0.7922/src`(下称 `$CR`)
- 方法:逐个 walk `patches/` 与 `src/browser/{webui,resources}/`,不靠记忆推断 Chromium 惯例。

---

## ⚠️ 首先:本次验证**推翻**了计划里的两条假设

### 反例 1(重要):计划 Task 10 Step 1 的验证命令**只覆盖 5 个 patch,漏了 2 个致命 patch**

计划第 1036–1044 行列出的验证命令是:

```
cat src/browser/resources/enroll/BUILD.gn
grep -n "enroll" patches/third_party/lit/v3_0/BUILD.gn.patch
grep -n "enroll" patches/chrome/browser/BUILD.gn.patch
grep -n "enroll" patches/chrome/browser/ui/webui/BUILD.gn.patch
grep -n "enroll" patches/chrome/chrome_paks.gni.patch
grep -n "enroll" patches/tools/gritsettings/resource_ids.spec.patch
```

对全仓 `grep -rn "teleport_enroll\|resources/enroll\|webui/enroll\|enroll_resources" patches/ src/` 的结果显示,enroll 页实际依赖 **7 个 patch**,上面漏掉的两个是:

| 漏掉的 patch | 漏掉的后果 |
|---|---|
| `patches/chrome/browser/ui/webui/chrome_web_ui_configs.cc.patch` | `WebUIConfig` 从不注册 ⇒ `teleport://tunnel` **404**(页面根本不存在,不是白屏) |
| `patches/chrome/browser/chrome_browser_interface_binders_webui_parts_desktop.cc.patch` | `PageHandlerFactory` 从不绑定 ⇒ 页面能加载但 Mojo 首次调用即断管,**页面永远停在 loading** |

这两处都是**编译能过、运行才炸**的失败模式——GN 不会报错,构建绿灯,只有真机打开页面才暴露。**Task 10 Step 2「按结论建文件并接线」必须以本文档的 7 项清单为准,不能以计划 Step 1 的 grep 列表为准。**

### 反例 2:计划 Step 1 问题 1 的措辞("lit 那个 patch 改的是 `visibility` 还是 `extra_deps`?")暗示有 `extra_deps` 这个可能

`third_party/lit/v3_0/BUILD.gn` 的 `ts_library("build_ts")` **根本没有 `extra_deps` 变量**;唯一存在的列表是 `visibility`(`$CR/third_party/lit/v3_0/BUILD.gn:13` 起、`:177` 止)。答案唯一,见下文 §2。

---

## 1. enroll 页需要的**全部**文件清单

### 1.1 overlay 源文件(9 个,全部在 `src/` 下,`git` 跟踪)

| 文件 | 作用 |
|---|---|
| `src/browser/webui/enroll.mojom` | 页面 ↔ 浏览器的 Mojo 接口(`PageHandlerFactory` / `PageHandler` / `EnrollState` / `VerifyResult`) |
| `src/browser/webui/teleport_enroll_ui.h` | `kTeleportEnrollHost`、`TeleportEnrollUIConfig`、`TeleportEnrollUI`(`ui::MojoWebUIController`) |
| `src/browser/webui/teleport_enroll_ui.cc` | `EnrollPageHandler` 实现 + `WebUIDataSource` 装配 + `WEB_UI_CONTROLLER_TYPE_IMPL` |
| `src/browser/resources/enroll/BUILD.gn` | `build_webui("build")`(见 §5) |
| `src/browser/resources/enroll/enroll.html` | `static_files` 里唯一一项,页面外壳 |
| `src/browser/resources/enroll/enroll.ts` | 入口模块(只 `import './enroll_app.js'`) |
| `src/browser/resources/enroll/enroll_app.ts` | `CrLitElement` 组件本体 |
| `src/browser/resources/enroll/enroll_app.html.ts` | **手写**的 Lit 模板(不是 `html_to_wrapper` 生成的,见 §5) |
| `src/browser/resources/enroll/enroll_app.css` | 带 `#css_wrapper_metadata_start` / `#type=style-lit` 头的 Lit 样式 |

证据:`src/browser/webui/` 与 `find src/browser/resources -type f` 的完整列举;`src/browser/resources/enroll/enroll_app.css:5-8` 的 `#type=style-lit` 元数据头。

**注意:这三个 `webui/` 文件都不在 `src/BUILD.gn` 里。**`src/BUILD.gn` 的 `source_set("teleport")`(`src/BUILD.gn:100-172`)不含 `browser/webui/*`;`src/browser/resources/enroll/BUILD.gn` 是独立的 GN 文件,靠 symlink 变成 `//teleport/browser/resources/enroll`。

### 1.2 patch(7 个)

| # | patch | hunk 数 | 干了什么 |
|---|---|---|---|
| P1 | `patches/chrome/browser/ui/webui/BUILD.gn.patch` | 3 | `import(mojom.gni)` + `mojom("teleport_enroll_mojo")`/`source_set("teleport_enroll")` + `:configs` 的 deps(详见 §3) |
| P2 | `patches/chrome/browser/BUILD.gn.patch` | 4(其中 1 处与 enroll 相关) | `group("browser_generated_files")` 加两个 target(详见 §4) |
| P3 | `patches/chrome/browser/ui/webui/chrome_web_ui_configs.cc.patch` | 2 | `#include teleport_enroll_ui.h`(:9)+ `map.AddWebUIConfig(std::make_unique<teleport::TeleportEnrollUIConfig>())`(:17) |
| P4 | `patches/chrome/browser/chrome_browser_interface_binders_webui_parts_desktop.cc.patch` | 2 | include `enroll.mojom.h` + `teleport_enroll_ui.h`;`RegisterWebUIControllerInterfaceBinder<teleport::enroll::mojom::PageHandlerFactory, teleport::TeleportEnrollUI>(map)` |
| P5 | `patches/chrome/chrome_paks.gni.patch` | 2 | 两个列表(详见 §7) |
| P6 | `patches/tools/gritsettings/resource_ids.spec.patch` | 1 | grit id 区块(详见 §6) |
| P7 | `patches/third_party/lit/v3_0/BUILD.gn.patch` | 1 | `visibility` 白名单(详见 §2) |

> P4 落在 `//chrome/browser/ui`:`chrome_browser_interface_binders_webui_parts_desktop.cc` 被 `$CR/chrome/browser/ui/BUILD.gn:1420` 以绝对路径拉进 `static_library("ui")` 的 sources。这条边**是 §4 那处 `browser_generated_files` 编辑存在的唯一理由**。

### 1.3 **不需要**改的地方(反直觉,记录下来防止后续任务多做)

- `src/BUILD.gn`:无需任何改动。
- `patches/chrome/browser/ui/BUILD.gn.patch`:该文件确实存在且提到 enroll(`teleport_voluntary_signin.{h,cc}`),但那是**自愿纳管入口**,与 enroll **页面**无关;enroll 页没有往这里加任何东西。
- `src/common/teleport_url_scheme.cc`:`teleport://X → chrome://X` 是**通用重写**(`teleport_url_scheme.cc:11-23`),只对 `teleport-urls` 这一个 host 做特判;新增页面**不需要**登记 host。
- `patches/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc.patch`:同样是通用的 `chrome:// → teleport://` 反向改写(`:96-102`),新页面自动出现在 `teleport://teleport-urls` 里——只要 §1.2 的 P3 注册了 `WebUIConfig`(`chrome_urls_handler.cc` 的 `GetUrls` 直接遍历 `WebUIConfigMap::GetWebUIConfigList`,见 `$CR/chrome/browser/ui/webui/chrome_urls/chrome_urls_handler.cc:76-95`)。

---

## 2. `patches/third_party/lit/v3_0/BUILD.gn.patch` 改的是什么?

**改的是 `ts_library("build_ts")` 的 `visibility` 列表。** 不是 `extra_deps`(该 target 无此变量),也不是 `deps`。

原始 hunk(`patches/third_party/lit/v3_0/BUILD.gn.patch:5-14`):

```diff
@@ -171,6 +171,9 @@ ts_library("build_ts") {
     "//ui/webui/resources/cr_components/searchbox:build_ts",
     "//ui/webui/resources/cr_components/theme_color_picker:build_ts",
     "//ui/webui/resources/cr_elements:build_ts",
+
+    # teleport overlay: chrome://enroll Lit page (build_webui).
+    "//teleport/browser/resources/enroll:build_ts",
   ]
   tsconfig_base = "tsconfig_base.json"
   composite = true
```

上游确证:
- `$CR/third_party/lit/v3_0/BUILD.gn:12` = `ts_library("build_ts") {`
- `$CR/third_party/lit/v3_0/BUILD.gn:13` = `visibility = [`
- `$CR/third_party/lit/v3_0/BUILD.gn:177` = `]`(列表结束),`:178` 是 `tsconfig_base`,`:179` 是 `composite = true`

上游在 `:19-26` 写明这份白名单的用途:"Explicitly tracking targets that can depend on third_party/lit is still useful to audit UIs that depend on Lit"。

**对 tunnel 页的含义**:只要页面用 `CrLitElement`(enroll 页 `enroll_app.ts:19` 就是),`ts_deps` 里就得有 `//third_party/lit/v3_0:build_ts`,而该 target 的 `visibility` 不含你就 **GN gen 直接失败**。必须加 `"//teleport/browser/resources/tunnel:build_ts"`。

---

## 3. `patches/chrome/browser/ui/webui/BUILD.gn.patch` 一共几处编辑?

**3 处(3 个 hunk)。是的,除 `mojom()` / `source_set()` 之外,确实有一处把页面加进 `source_set("configs")` 的 `deps`。**

| hunk | 位置 | 内容 |
|---|---|---|
| ① | `@@ -8,6 +8,7 @@` | 新增 `import("//mojo/public/tools/bindings/mojom.gni")` —— 上游该文件原本**没有** import mojom.gni,不加则 `mojom()` 模板未定义 |
| ② | `@@ -27,6 +28,38 @@` | 一次性新增 `mojom("teleport_enroll_mojo")` 与 `source_set("teleport_enroll")` 两个 target |
| ③ | `@@ -52,6 +85,7 @@` | 在 `source_set("configs")` 的 `deps` 里插入 `":teleport_enroll"` |

hunk ③ 原文(`patches/chrome/browser/ui/webui/BUILD.gn.patch` 尾部):

```diff
@@ -52,6 +85,7 @@ source_set("configs") {
     ":net_export_ui",
     ":ntp_tiles_internals_ui",
     ":signin_internals_ui",
+    ":teleport_enroll",
     ":webui",
```

上游确证:`$CR/chrome/browser/ui/webui/BUILD.gn:63` = `source_set("configs") {`,`:87` = `":teleport_enroll",`(patch 已应用状态)。

hunk ② 的 target 全文(patch 已应用后的 `$CR/chrome/browser/ui/webui/BUILD.gn:31-60`):

```gn
mojom("teleport_enroll_mojo") {
  sources = [ "//teleport/browser/webui/enroll.mojom" ]
  public_deps = [ "//mojo/public/mojom/base" ]
  webui_module_path = "/"
}

source_set("teleport_enroll") {
  sources = [
    "//teleport/browser/webui/teleport_enroll_ui.cc",
    "//teleport/browser/webui/teleport_enroll_ui.h",
  ]
  deps = [
    ":teleport_enroll_mojo",
    "//base",
    "//components/policy/core/common:common_constants",
    "//content/public/browser",
    "//content/public/common",
    "//net",
    "//services/network/public/cpp",
    "//services/network/public/mojom",
    "//teleport",
    "//teleport/browser/resources/enroll:resources",
    "//ui/webui",
    "//url",
  ]
}
```

`webui_module_path = "/"` 决定生成物落在 `$root_gen_dir/teleport/browser/webui/enroll.mojom-webui.ts`(与 `src/browser/resources/enroll/BUILD.gn:24-25` 的 `mojo_files` 一致),页面侧 import 为 `./enroll.mojom-webui.js`。

---

## 4. `patches/chrome/browser/BUILD.gn.patch` 里有没有对 `group("browser_generated_files")` 的编辑?

**有。** 原文(`patches/chrome/browser/BUILD.gn.patch:55-63`):

```diff
@@ -4918,6 +4947,8 @@ group("browser_generated_files") {
       "//chrome/browser/enterprise/connectors/device_trust/attestation/common/proto:attestation_ca_proto",
       "//chrome/browser/enterprise/connectors/device_trust/attestation/common/proto:google_key_proto",
       "//chrome/browser/enterprise/connectors/device_trust/attestation/common/proto:interface_proto",
+      "//chrome/browser/ui/webui:teleport_enroll",
+      "//chrome/browser/ui/webui:teleport_enroll_mojo",
       "//chrome/browser/ui/webui/app_home:mojo_bindings",
       "//chrome/browser/ui/webui/on_device_translation_internals:mojo_bindings",
       "//chrome/browser/ui/webui/whats_new:mojo_bindings",
```

**为什么必须有这一处**(这是本次验证里最容易漏掉的一环):

1. `chrome_browser_interface_binders_webui_parts_desktop.cc`(P4 的目标)被编进 `//chrome/browser/ui`(`$CR/chrome/browser/ui/BUILD.gn:1420`)。
2. 它 `#include "teleport/browser/webui/enroll.mojom.h"` 与 `teleport_enroll_ui.h`。
3. `//chrome/browser/ui` 与 `//chrome/browser` 互为循环依赖,上游对这类 target 的解法是 `public_deps = [ ":browser_public_dependencies" ]`(注释在 `$CR/chrome/browser/BUILD.gn:4641-4663`)。
4. `group("browser_public_dependencies")` 的 `public_deps` 头一项就是 `":browser_generated_files"`(`$CR/chrome/browser/BUILD.gn:4664-4670`)。
5. `group("browser_generated_files")` 的注释(`$CR/chrome/browser/BUILD.gn:4805-4809`)明说:"All generated files in //chrome/browser/ depended on by //chrome/browser:browser **or targets that circularly depend on** //chrome/browser:browser should be listed here."

所以:**只要新页面的 mojom 头会被任何一个「与 chrome/browser 循环依赖」的文件 include(而 interface binder 恰恰就是),就必须在 `browser_generated_files` 里登记 mojom target。** tunnel 页只要走同一条 interface-binder 路径,这一处就必须照抄。

另外三处 `patches/chrome/browser/BUILD.gn.patch` 的 hunk 与 enroll **页面**无关:`source_set("core")` 的 sources(含 `teleport_tunnel_service.{h,cc}` 与 `teleport_tunnel_service_factory.{h,cc}`,`:23-26`)、`source_set("core")` 的 deps(`:36-38`)、mac 分支的 `teleport_update_buildstate`(`:50-51`)。

---

## 5. `src/browser/resources/enroll/BUILD.gn` 用到的**每一个**变量

全文 38 行,`build_webui("build")` 里设了 8 个变量:

| 变量 | 值(行号) | 作用与证据 |
|---|---|---|
| `grd_prefix` | `"enroll"`(:10) | 决定全部产物命名:`grit/enroll_resources.h`、`grit/enroll_resources_map.{cc,h}`、`enroll_resources.pak`(`$CR/ui/webui/resources/tools/build_webui.gni:885-888`)。C++ 侧对应 `teleport_enroll_ui.cc` 的 `#include "chrome/grit/enroll_resources.h"` 与 `kEnrollResources` |
| `static_files` | `[ "enroll.html" ]`(:12) | 原样(经 `preprocess_if_expr`)打进 grd 的文件;`build_webui.gni:163-178` 明确**禁止**放 `.js`(`assert(static_js_files == [])`) |
| `css_files` | `[ "enroll_app.css" ]`(:14) | 经 `css_to_wrapper` 生成 `enroll_app.css.ts` → `.css.js`(`build_webui.gni:146-153`);要求源文件带 `#css_wrapper_metadata_start` 头 |
| `ts_files` | `enroll.ts` / `enroll_app.ts` / `enroll_app.html.ts`(:16-20) | 直接进 TS 编译的文件(`build_webui.gni:114-116`)。**注意这里没有用 `web_component_files`**:若用 `web_component_files`,`build_webui.gni:118-138` 会为每个 `.ts` 推导一个同名 `.html` 并跑 `html_to_wrapper` 生成 `.html.ts`;enroll 选择**手写** `enroll_app.html.ts`(见其 `:5` 的 `import {html} from '//resources/lit/v3_0/lit.rollup.js'`),因此三个文件全部当普通 `ts_files` 处理 |
| `mojo_files_deps` | `[ "//chrome/browser/ui/webui:teleport_enroll_mojo_ts__generator" ]`(:22-23) | 生成 TS binding 的 target。`build_webui.gni:155-157` 里 `assert(defined(invoker.mojo_files_deps))` —— 设了 `mojo_files` 就必须设它 |
| `mojo_files` | `[ "$root_gen_dir/teleport/browser/webui/enroll.mojom-webui.ts" ]`(:24-25) | 被 `copy("copy_mojo")` 拷进 preprocess 目录参与 TS 编译(`build_webui.gni:425-430`)。路径由 mojom target 的 `webui_module_path = "/"` 决定 |
| `ts_composite` | `true`(:27) | 传给 `ts_library("build_ts")` 的 `composite`(`build_webui.gni:449-452`)。设 `true` 时 `build_ts` **不收窄 `visibility`**(`:454-465` 只在 `!composite` 分支里限制可见性)——正因如此 `//third_party/lit/v3_0:build_ts` 才能把 `//teleport/browser/resources/enroll:build_ts` 列进自己的 `visibility` 并被 TS 侧引用 |
| `ts_deps` | lit + color_change_listener + cr_elements + js + mojo(:29-35) | TS 编译期依赖;`build_webui.gni:322-334` 用它推导默认 tsconfig(含 lit ⇒ 用 Lit 的 base) |
| `webui_context_type` | `"trusted"`(:37) | 传给 `webui_path_mappings("build_path_map")`(`build_webui.gni:433-443`)→ `path_mappings.py`。取值范围 `['trusted','untrusted','relative','trusted_only']`,默认 `trusted`(`$CR/tools/typescript/path_mappings.py:179-182`);`trusted` 使 `chrome://resources/...` 形式的 import 被解析(`:221-228`,`untrusted` 会换成 `chrome-untrusted:`)。enroll 页 `enroll_app.ts:15-19` 正是用 `chrome://resources/...` import |

**未设的变量**(默认生效,tunnel 页照抄即可):`generate_grdp`(默认 false ⇒ 生成 `.grd` 而非 `.grdp`,并产出 `grit("resources")`,`build_webui.gni:89-93`、`:877-888`)、`grit_output_dir`(默认 `$root_gen_dir/chrome`,`:894-896`,这就是为什么 pak 叫 `$root_gen_dir/chrome/enroll_resources.pak` 而不是 `.../teleport/...`)、`web_component_files`、`icons_html_files`、`ts_tsconfig_base`、`ts_out_dir`、`grd_resource_path_prefix`。

**实测产出**(`$CR/out/mac/arm64/dev/gen/teleport/browser/resources/enroll/resources.grd`):6 个 `<include>` —— `IDR_ENROLL_ENROLL_HTML`、`_ENROLL_JS`、`_ENROLL_APP_JS`、`_ENROLL_APP_HTML_JS`、`_ENROLL_APP_CSS_JS`、`_ENROLL_ENROLL_MOJOM_WEBUI_JS`。

---

## 6. `resource_ids.spec` 里 enroll 占了哪个区块?新页面的**硬约束**是什么?

### enroll 占的区块

`patches/tools/gritsettings/resource_ids.spec.patch:9-13`:

```
  # teleport overlay: chrome://enroll page resources (build_webui-generated grd).
  "<(SHARED_INTERMEDIATE_DIR)/teleport/browser/resources/enroll/resources.grd": {
    "META": {"sizes": {"includes": [10]}},
    "includes": [11800],
  },
```

位置(patch 已应用后的 `$CR/tools/gritsettings/resource_ids.spec`):
- `:1800-1803` 前邻 `.../chrome/browser/resources/webui_toolbar_shared/resources.grd` → `includes: [10140]`
- `:1805-1809` 本条 → `includes: [11800]`,`META.sizes.includes = 10`
- `:1811-1814` 后邻 `<(SHARED_INTERMEDIATE_DIR)/THIS_IS_A_PLACEHOLDER.grd` → `includes: [12000]`
- `:1816` 是 `# END "everything else" section.`

即 enroll 挂在 **"everything else" 段的末尾**,`10140 < 11800 < 12000`。

### 硬约束(**不是**"任何未用过的数字")

`$CR/tools/gritsettings/README.md` 与 grit 实现共同给出四条约束:

1. **数值是 "fake start ID",只有相对顺序有意义,不是真实资源 id。** README「Details on resource_ids.spec」段:"Start IDs are replaced with 'fake start IDs' to capture 'ordering structure'"。真实 id 在构建期动态求解。

2. **必须严格落在前后邻居之间的开区间内。** README 的解码规则:递增值 = 串联(series,push);**重复或递减值 = 创建 split(互斥分支,资源 id 可复用)**。"The tree building algorithm uses a stack: Increasing values are pushed; repeated or decreasing values cause pops until a match is found."
   ⇒ 对 tunnel 页,取值必须 `11800 < x < 12000`(例如 **11900**)。取 `11800` 会被解释成"与 enroll 互斥、可共用 id 段"——但两个页面同时编进同一个 chrome,**id 会真冲突**;取 `> 12000` 会跌到 `THIS_IS_A_PLACEHOLDER` 之后,越过 `# END "everything else" section` 边界。

3. **`META.sizes` 是生成式 grd 的**硬性**上限,超了直接构建失败(不是静默截断)。** `$CR/tools/grit/grit/node/misc.py:660-663` 把 `META.sizes.<type>` 写进节点的 `max_ids`;`:127-140` 的 `check_group_count()` 在超出时 `raise exception.IdRangeOverflow`,报错文案是 "Generated .grd file used more IDs (%d) than were allocated for it (%s)"。
   ⇒ enroll 用 6 / 预留 10。tunnel 页若文件更多(比如多几个 `.css` / 子组件),必须相应把 `includes` 的 size 调大;宁可预留宽一点。

4. **必须放进正确的 section 并尽量保持字母序**(README「Updating resource_ids.spec」)。overlay 选了 "everything else" 段尾,新增 tunnel 页跟着放在 enroll 之后是自洽的(`enroll` < `tunnel` 字母序也成立)。

5. 一旦 fake id 挤不下(`11800` 与 `12000` 之间用完),官方做法是重跑
   `python3 ../grit/grit.py update_resource_ids -i resource_ids.spec --fake`
   整体重排,不要手工硬塞。

---

## 7. `patches/chrome/chrome_paks.gni.patch` 碰了几个列表?

**2 个,且都在同一个 `if (is_win || is_mac || is_linux)` 块里。**

`patches/chrome/chrome_paks.gni.patch` 的两个 hunk 分别是:

```diff
@@ -577,6 +577,7 @@ template("chrome_extra_paks") {
         "$root_gen_dir/chrome/browser_switch_resources.pak",
+        "$root_gen_dir/chrome/enroll_resources.pak",
```

```diff
@@ -587,6 +588,7 @@ template("chrome_extra_paks") {
         "//chrome/browser/resources/updater:resources",
+        "//teleport/browser/resources/enroll:resources",
       ]
```

上游确证(patch 已应用后的 `$CR/chrome/chrome_paks.gni`):
- `:575` = `if (is_win || is_mac || is_linux) {`
- `:576-584` = `sources += [ ... ]`,其中 `:580` 是 `"$root_gen_dir/chrome/enroll_resources.pak"`
- `:585-592` = `deps += [ ... ]`,其中 `:591` 是 `"//teleport/browser/resources/enroll:resources"`

即 **`sources`(pak 文件路径)+ `deps`(生成它的 grit target)成对出现**。`$root_gen_dir/chrome/` 这个前缀来自 `build_webui.gni:894` 的默认 `grit_output_dir = "$root_gen_dir/chrome"`。漏掉 `sources` ⇒ 资源不进 `resources.pak` ⇒ 页面白屏;漏掉 `deps` ⇒ ninja 报缺文件。

---

## 8. 承重题:`teleport_enroll` 的 source_set 依赖 `//chrome/browser` 吗?tunnel 页怎么办?

### 8.1 事实

**不依赖,一点都不依赖。** `source_set("teleport_enroll")` 的完整 `deps`(`patches/chrome/browser/ui/webui/BUILD.gn.patch` hunk ②,即 `$CR/chrome/browser/ui/webui/BUILD.gn:46-59`)是:

```
:teleport_enroll_mojo, //base, //components/policy/core/common:common_constants,
//content/public/browser, //content/public/common, //net,
//services/network/public/cpp, //services/network/public/mojom,
//teleport, //teleport/browser/resources/enroll:resources, //ui/webui, //url
```

没有 `//chrome/browser`、没有 `//chrome/browser:core`、没有 `//chrome/browser/profiles:profile`、没有 `//chrome/common`。

### 8.2 为什么**不能**简单加上 `//chrome/browser:core`——这是一个真实的 GN 环

- `$CR/chrome/browser/BUILD.gn:828` = `source_set("core") {`
- `$CR/chrome/browser/BUILD.gn:1082` = `"//chrome/browser/ui/webui:configs",`(在 `:core` 的 `deps` 里,`deps = [` 起于 `:899`)
- `$CR/chrome/browser/ui/webui/BUILD.gn:87` = `":teleport_enroll",`(在 `source_set("configs")` 的 `deps` 里)

⇒ `//chrome/browser:core` → `//chrome/browser/ui/webui:configs` → `//chrome/browser/ui/webui:teleport_enroll`。
若 tunnel 页的 source_set 反过来 dep `:core`,就是 **`core → configs → tunnel → core`,GN gen 直接报 dependency cycle**。

同理,把 `teleport_tunnel_ui.{h,cc}` **整体塞进 `:core` 的 sources**(像 `teleport_update_buildstate.mm` 那样)也不成立:`chrome_web_ui_configs.cc` 编在 `:configs` 里、必须 `#include teleport_tunnel_ui.h` 才能注册 `WebUIConfig`,而 `:configs` 无法 dep `:core`(同一个环,方向相反)。

而 `TeleportTunnelService` 确实编在 `:core`:`patches/chrome/browser/BUILD.gn.patch:23-26` 把
`teleport_tunnel_service.{cc,h}` 与 `teleport_tunnel_service_factory.{cc,h}` 加进了 `source_set("core")` 的 `sources`。

顺带一个有用的事实:`src/browser/enterprise/teleport_tunnel_service.h:1-32` 本身**不 include 任何 chrome/browser 头**(只前向声明 `class Profile;`);脏活在 `.cc`(`teleport_tunnel_service.cc:21-22` include `chrome/browser/enterprise/signin/enterprise_signin_prefs.h` 与 `chrome/browser/profiles/profile.h`)。真正的障碍是 **gn check 的归属**(头文件被声明在 `:core` 的 sources 里,想 include 就得有到 `:core` 的 dep 路径),不是头文件内容。`$CR/.gn` 只有 `no_check_targets`(`:84`,仅列了 6 个 v8 target)、没有 `check_targets`,所以 chrome 全树的 gn check 是**开着**的。

### 8.3 可行路径枚举(含 chrome 内的先例)

| 方案 | 做法 | 先例 | 判定 |
|---|---|---|---|
| **A. 回调 seam(推荐)** | 在 `//teleport` 里声明 chrome-free 的自由函数 + `base::RepeatingCallback` 注册点;`//chrome/browser:core` 在启动期注册真实实现;webui target 只调自由函数 | **本仓库 enroll 页自己就是这么干的**:`src/common/teleport_enroll_logic.h:74-100` 声明 `SetServerIdentityEntryWriter/Clearer`、`SetRelaunchHandler` 三个 seam,注释直书 "must NOT reach into g_browser_process to write Local State (that would drag chrome/browser into this WebUI target)";`src/browser/teleport_deployment_level4.cc:77-84` 在 `RegisterServerIdentityLevel4()` 里注册;`src/browser/webui/teleport_enroll_ui.cc:183/191/199` 调用 | ✅ **选它** |
| **B. header-only GN target** | 在 `chrome/browser/BUILD.gn` 新建 `source_set("teleport_tunnel_service_headers") { public = [两个 .h] }`,`.cc` 留在 `:core`,`:core` 与 webui target 双方都 dep 它 | 上游确有此惯用法:`$CR/chrome/browser/BUILD.gn:810-816` 的 `source_set("chrome_browser_interface_binders_webui_parts")`,注释写明 "Header-only targets so the platform-specific .cc files that include //chrome/browser/ui monolith headers can move out of :browser without depending on :core (which would cycle through the ui target). The .cc files stay in :core.";`:915` 让 `:core` dep 它 | ✅ 可行,但改动面更大 |
| **C. 把 service 拆出 `:core`,单开 source_set + `public_deps = [":browser_public_dependencies"]`** | 新 target 只 dep `//chrome/browser/profiles:profile`(`$CR/chrome/browser/profiles/BUILD.gn:282-290` 声明 `profile.h`/`profile_keyed_service_factory.h`)与 `//chrome/browser/enterprise`(`$CR/chrome/browser/enterprise/BUILD.gn:9` 的 `source_set("enterprise")`,`:329` 声明 `signin/enterprise_signin_prefs.h`),两者都已在 `browser_public_dependencies` 里 | 上游标准姿势:`$CR/chrome/browser/ui/webui/about/BUILD.gn:24`、`$CR/chrome/browser/ui/webui/management/BUILD.gn:19` 都是 `public_deps = [ "//chrome/browser:browser_public_dependencies" ]` | ⚠️ 最"正统",但要动 `:core` 的 sources、验证 `profiles_extra_parts_impl`(`$CR/chrome/browser/profiles/BUILD.gn:603-604`,factory 注册点所在)的依赖方向,风险最高 |
| **D. 直接 dep `//chrome/browser:core`** | — | — | ❌ **环,GN gen 失败**(§8.2) |
| **E. 把 `TeleportTunnelUI` 整体塞进 `:core`** | — | — | ❌ `:configs` 需要 include 它注册 config,反向环(§8.2) |

### 8.4 推荐:方案 A,理由

1. **零 GN 风险**:不新增任何 GN 边,不动 `:core` 的 sources,不可能引入环。tunnel 页的 `source_set` deps 表可以**逐字复制** enroll 的那张(§8.1),只把 `enroll` 换成 `tunnel`。
2. **本仓已验证**:enroll 页四年前就踩过同一个问题(写 Local State、调 `chrome::AttemptRestart()`),解法就是 seam,已经在生产构建里跑通。评审时无需说服任何人这是不是"新花样"。
3. **与计划的 Global Constraint 同向**:计划第 14 行要求纯逻辑留在 `teleport_tunnel_logic`(`TD-TUNNEL-UNITTEST-WIRING`)。`TunnelStateSnapshot` 这个结构体天然应该放进 `//teleport:teleport_tunnel_logic`(`src/BUILD.gn:85-98`,deps 只有 `//base`+`//net`+`//services/network/public/mojom`+`//url`),于是 `teleport_unittests` **可以直接单测快照构造**,而无需链接 chrome/browser。方案 B/C 做不到这一点。
4. **诊断页的交互形状天然是 pull**:Task 11 要的是 `GetState()` 全字段快照 + `Rebind()`,与 enroll 的 `GetState/Verify/Confirm/Unbind/Relaunch` 完全同构;不需要 observer 推送。

**落地形状(建议,供 Task 10 Step 2 使用):**

在 `src/browser/enterprise/teleport_tunnel_logic.h`(而非 `_service.h`)加:

```cpp
// Diagnostics seam: the tunnel page's handler lives in
// //chrome/browser/ui/webui and must NOT include teleport_tunnel_service.h —
// that header is declared in //chrome/browser:core, and :core already deps
// //chrome/browser/ui/webui:configs, so the include would close a GN cycle.
// //chrome/browser registers the providers; the handler invokes the free
// functions. Both are no-ops (empty snapshot / false) when unregistered.
struct TunnelStateSnapshot { /* … 无 token 字段 … */ };

using TunnelStateProvider =
    base::RepeatingCallback<TunnelStateSnapshot(content::BrowserContext*)>;
void SetTunnelStateProvider(TunnelStateProvider provider);
TunnelStateSnapshot GetTunnelStateSnapshot(content::BrowserContext* context);

using TunnelRebindRequester =
    base::RepeatingCallback<bool(content::BrowserContext*)>;
void SetTunnelRebindRequester(TunnelRebindRequester requester);
bool RequestTunnelRebind(content::BrowserContext* context);
```

> 注意 `content::BrowserContext*` 参数**不可省**:seam 是进程级全局,而 `TeleportTunnelService` 是 per-profile 的(`TeleportTunnelServiceFactory::GetForProfile`,`src/browser/enterprise/teleport_tunnel_service_factory.h:33`)。handler 侧拿 context 的写法与 enroll 一致:`web_ui_->GetWebContents()->GetBrowserContext()`(`src/browser/webui/teleport_enroll_ui.cc:169-172`)。
> 若 `content::BrowserContext` 让 `teleport_tunnel_logic` 多出 `//content` 依赖(会破坏 `teleport_unittests` 的轻量链接),就把这两个 seam 放进 `//teleport:teleport` 的一个新文件(如 `common/teleport_tunnel_seam.{h,cc}`),只让 `TunnelStateSnapshot` 结构体留在 `teleport_tunnel_logic`——`//teleport` 已经 dep `//content/public/common`(`src/BUILD.gn:142`),但**不** dep `//content/public/browser`,所以更稳妥的做法是 seam 参数用 `void*` 之外的中立形式:让 `//chrome/browser` 侧注册的 lambda 自己捕获 profile 解析逻辑,seam 参数类型用 `content::BrowserContext*` 的前向声明(`namespace content { class BrowserContext; }`)即可,头文件不需要 include `//content` 的任何头。

注册点(与 enroll 完全对称):在 `//chrome/browser:core` 里已存在的某个 teleport 文件中调用 `SetTunnelStateProvider(...)` / `SetTunnelRebindRequester(...)`,实现体内 `TeleportTunnelServiceFactory::GetForProfile(Profile::FromBrowserContext(context))`。最省事的宿主是 `teleport_tunnel_service_factory.cc`(已经在 `:core` 的 sources 里,`patches/chrome/browser/BUILD.gn.patch:25-26`),在其构造函数或 `RegisterServerIdentityLevel4()` 同层的启动路径上注册一次。

**回退方案**:如果后续 Task 11 发现诊断页需要**实时推送**(observer 而非 pull),再升级到方案 B(header-only target),它的上游先例(`$CR/chrome/browser/BUILD.gn:810-816`)已经确认可用。

---

## 结论:tunnel 页的完整接线清单

以 enroll 为模板,`teleport://tunnel` 需要 **9 个新建 overlay 文件 + 7 处 patch 编辑**。逐项打勾:

**A. 新建 overlay 源文件**

- [ ] A1 `src/browser/webui/tunnel.mojom` —— `module teleport.tunnel.mojom;`,`PageHandlerFactory` + `PageHandler`(`GetState()` / `Rebind()`)
- [ ] A2 `src/browser/webui/teleport_tunnel_ui.h` —— `kTeleportTunnelHost = "tunnel"`、`TeleportTunnelUIConfig : content::WebUIConfig`、`TeleportTunnelUI : ui::MojoWebUIController, tunnel::mojom::PageHandlerFactory`、`WEB_UI_CONTROLLER_TYPE_DECL()`
- [ ] A3 `src/browser/webui/teleport_tunnel_ui.cc` —— `TunnelPageHandler` + `WebUIDataSource::CreateAndAdd` + `webui::SetupWebUIDataSource(source, kTunnelResources, IDR_TUNNEL_TUNNEL_HTML)` + `WEB_UI_CONTROLLER_TYPE_IMPL`
- [ ] A4 `src/browser/resources/tunnel/BUILD.gn` —— `build_webui("build")`,变量照 §5 抄:`grd_prefix="tunnel"`、`static_files`、`css_files`、`ts_files`、`mojo_files_deps=["//chrome/browser/ui/webui:teleport_tunnel_mojo_ts__generator"]`、`mojo_files=["$root_gen_dir/teleport/browser/webui/tunnel.mojom-webui.ts"]`、`ts_composite=true`、`ts_deps`、`webui_context_type="trusted"`
- [ ] A5–A9 `src/browser/resources/tunnel/{tunnel.html, tunnel.ts, tunnel_app.ts, tunnel_app.html.ts, tunnel_app.css}`(`.css` 必须带 `#css_wrapper_metadata_start` / `#type=style-lit` 头)

**B. patch 编辑(7 处,一个都不能少)**

- [ ] B1 `patches/chrome/browser/ui/webui/BUILD.gn.patch` —— **新增第 4 个 hunk**:`mojom("teleport_tunnel_mojo")` + `source_set("teleport_tunnel")`(deps 逐字复制 §8.1 那张表,把 `enroll` 换成 `tunnel`,**不要**加 `//chrome/browser*`);并在 `source_set("configs")` 的 deps 里追加 `":teleport_tunnel"`。`import(mojom.gni)` 已由 enroll 加过,不用再加
- [ ] B2 `patches/chrome/browser/BUILD.gn.patch` —— 在 `group("browser_generated_files")` 的 hunk 里追加 `"//chrome/browser/ui/webui:teleport_tunnel"` 与 `"//chrome/browser/ui/webui:teleport_tunnel_mojo"`
- [ ] B3 `patches/chrome/browser/ui/webui/chrome_web_ui_configs.cc.patch` —— include `teleport/browser/webui/teleport_tunnel_ui.h` + `map.AddWebUIConfig(std::make_unique<teleport::TeleportTunnelUIConfig>())`。**计划的 grep 清单漏了这个,漏了 = teleport://tunnel 404**
- [ ] B4 `patches/chrome/browser/chrome_browser_interface_binders_webui_parts_desktop.cc.patch` —— include `tunnel.mojom.h` + `teleport_tunnel_ui.h`,并 `RegisterWebUIControllerInterfaceBinder<teleport::tunnel::mojom::PageHandlerFactory, teleport::TeleportTunnelUI>(map)`。**计划的 grep 清单也漏了这个,漏了 = 页面永远 loading**
- [ ] B5 `patches/chrome/chrome_paks.gni.patch` —— 两个列表各加一行:`sources` 加 `"$root_gen_dir/chrome/tunnel_resources.pak"`,`deps` 加 `"//teleport/browser/resources/tunnel:resources"`
- [ ] B6 `patches/tools/gritsettings/resource_ids.spec.patch` —— 在 enroll 条目(`11800`)与 `THIS_IS_A_PLACEHOLDER`(`12000`)之间插入 tunnel 条目,`"includes": [11900]`(**严格开区间内**),`META.sizes.includes` 按实际文件数留余量(enroll 6 用 10;tunnel 页组件更多则给 15–20)
- [ ] B7 `patches/third_party/lit/v3_0/BUILD.gn.patch` —— 在 `ts_library("build_ts")` 的 **`visibility`** 列表里追加 `"//teleport/browser/resources/tunnel:build_ts"`

**C. 依赖 seam(见下一节)**

- [ ] C1 在 `//teleport` 侧声明 `TunnelStateSnapshot` + 两个 seam(provider / rebind requester)
- [ ] C2 在 `//chrome/browser:core` 里已有的 teleport 文件(建议 `teleport_tunnel_service_factory.cc`)注册 seam 实现

**D. 验证**

- [ ] D1 `python scripts/apply_patches.py` 幂等通过(patch 重生成走 CLAUDE.md 的"修改已有 patch 的工作流",禁止手改 hunk)
- [ ] D2 `autoninja -C out/mac/arm64/dev chrome` 编译通过
- [ ] D3 真机 `teleport://tunnel` 能打开(验 B3)、Mojo `GetState()` 有返回(验 B4)、页面出现在 `teleport://teleport-urls`(自动,验 B3)

---

## 结论:chrome/browser 依赖问题的解法

**问题定型**:`TeleportTunnelService` 编在 `//chrome/browser:core`(`patches/chrome/browser/BUILD.gn.patch:23-26`);而 `//chrome/browser:core` 已经 dep `//chrome/browser/ui/webui:configs`(`$CR/chrome/browser/BUILD.gn:1082`),`:configs` 又 dep 每个页面的 source_set(`$CR/chrome/browser/ui/webui/BUILD.gn:87`)。因此**任何**从 webui 页面 target 指向 `:core` 的边都会闭合成 GN 环;反向把整个 `TeleportTunnelUI` 塞进 `:core` 同样不行(`:configs` 必须 include 它的 Config 头才能注册)。`gn check` 在本树是开着的(`$CR/.gn` 只有 `no_check_targets`,没有 `check_targets`),不能指望它放行。

**采纳:方案 A —— `//teleport` 回调 seam。**

理由(按权重):
1. **本仓已有活体先例,且是同一类问题的同一个解**:enroll 页要写 Local State、要 `chrome::AttemptRestart()`,两者都在 `//chrome/browser`,解法是 `src/common/teleport_enroll_logic.h:74-100` 的三个 seam + `src/browser/teleport_deployment_level4.cc:77-84` 的注册 + `src/browser/webui/teleport_enroll_ui.cc:183/191/199` 的调用。tunnel 页照抄即可,评审无争议。
2. **零 GN 风险**:tunnel 页的 `source_set` deps 表与 enroll 逐字同构(§8.1),没有任何新的 GN 边,不可能引环。
3. **与计划 Global Constraint 同向**:`TunnelStateSnapshot` 落在 `//teleport:teleport_tunnel_logic`(`src/BUILD.gn:85-98`,零 chrome/content 依赖),`teleport_unittests` 可以直接单测快照构造,正是 `TD-TUNNEL-UNITTEST-WIRING` 要保住的能力。方案 B/C 会把这块拖回 chrome/browser 侧、只能用重量级 `unit_tests` 测。
4. **交互形状匹配**:诊断页是 pull 型(`GetState()` 快照 + `Rebind()` 动作),与 enroll 的 `GetState/Verify/Confirm/Unbind/Relaunch` 完全同构,不需要 observer 推送。

**注意事项**:
- seam 是进程级全局,而 service 是 per-profile,所以两个 seam 的签名**必须带 `content::BrowserContext*`**;头文件里用前向声明 `namespace content { class BrowserContext; }` 即可,不需要 include `//content` 的任何头(不会破坏 `teleport_tunnel_logic` 的轻依赖)。handler 侧取 context 的写法见 `src/browser/webui/teleport_enroll_ui.cc:169-172`。
- 未注册时必须是安全默认值(空快照 / `false`),与 `teleport_enroll_logic.cc:106-129` 的三个 seam 行为一致。
- 快照结构体**绝不能含 `cnf_token_`**(Task 11 Step 1 的 `StateSnapshotNeverCarriesTheToken` 测试就是钉这一点)。

**回退方案(记录备查,当前不采用)**:若后续需要实时推送(observer),升级为**方案 B —— header-only GN target**:在 `chrome/browser/BUILD.gn` 新建 `source_set("teleport_tunnel_service_headers") { public = [ 两个 .h ] }`,`.cc` 留在 `:core`,`:core` 与 webui target 各自 dep 它。上游对这个惯用法有明确背书:`$CR/chrome/browser/BUILD.gn:810-816` 的 `source_set("chrome_browser_interface_binders_webui_parts")`,注释原文 "Header-only targets so the platform-specific .cc files that include //chrome/browser/ui monolith headers can move out of :browser without depending on :core (which would cycle through the ui target). The .cc files stay in :core.",并在 `:915` 由 `:core` 反向 dep。

**明确否决**:
- 给 tunnel 页 source_set 加 `//chrome/browser:core` —— GN 环,gen 阶段就失败。
- 把 `teleport_tunnel_ui.{h,cc}` 加进 `:core` 的 sources(像 `teleport_update_buildstate.mm` 那样)—— 反向环,`:configs` 拿不到 Config 头。
- 指望 `nogncheck` 注释绕过 —— 它只关掉 include 检查,**关不掉 GN 的依赖环检测**;而且这里的问题本质是环,不是 check。
