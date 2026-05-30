# 设计:canary dmg 复刻 Chrome 默认安装窗口观感

- 状态:已批准(brainstorming 产出)
- 日期:2026-05-27
- 关联:`docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md`(渠道包/自动升级)

## 背景与动机

当前 canary dmg 的背景由 `scripts/gen_dmg_background.py` 用 PIL 程序化绘制:浅灰垂直渐变 + 一行标题文字(`闪现 · Teleport`)+ 一个扁平蓝色横向箭头 + 一行中文提示。横版布局(640×400),图标左右排列。实测观感粗糙——扁平箭头无质感、渐变发灰、整体不像成熟产品安装包。

目标:把安装窗口做成 **macOS 版 Google Chrome 安装 dmg 的默认观感**(竖版、纯白底、下方淡色圆角卡片含大白下箭头、应用程序文件夹带别名角标),并以 Teleport 品牌微调配色。

### 参照(Chrome 默认安装窗口)

以 Google Chrome 安装 dmg 的**默认态**(未点击选中任何图标)为基准:

- 竖版窗口,纯白内容背景,无渐变。
- 顶部居中:app 图标**直接置于白底之上**(图标自带圆角/投影,无额外卡片)。其下为**普通黑字标签**(应用名)。
- 底部:一块**淡色圆角卡片**,卡片上半部一个**大白色块状下箭头**,下半部是**应用程序文件夹**(蓝色文件夹 + App Store "A" 标志),文件夹左下角带**别名角标**(白圈内一个弯曲箭头)。
- 应用程序文件夹**不显示文字标签**。

> 注意:网上常见的 Chrome 安装窗口截图里,app 图标背后有浅灰圆角卡片、名字是白字蓝底气泡——那是 Finder 的**选中高亮**(截图前点了一下图标),并非背景图的一部分。默认态没有灰卡、没有气泡。本设计以默认态为准。

## 目标 / 非目标

**目标**

- dmg 打开后窗口布局/配色/箭头/文件夹角标与 Chrome 默认安装窗口高度一致。
- 背景图不含任何文字(标签由 Finder 绘制)。
- 仅复用现有打包管线,不引入新依赖、不改 `package_release.py` 主流程。

**非目标**

- 不追求与 Chrome 字节级一致(Chrome 的 `chrome_dmg_background.png` / `chrome_dmg_dsstore` 是 Google 内部专有资源,公共检出中缺失,无法复用)。
- 不复刻"选中高亮气泡"(那是 Finder 选中态,非默认观感;经确认不需要)。
- 不改 app 图标本身(图标观感取决于 `branding/.../mac/app.icns`,与 dmg 布局无关)。
- 不改卷名(仍为 `Teleport`)、不改签名/公证/上传流程。

## 现状(将被替换/调整的部分)

- `scripts/gen_dmg_background.py`:程序化绘制横版渐变背景 + 文字 + 扁平箭头。**整体重写**。
- `scripts/dmg_settings.py`:横版 `window_rect=((220,220),(640,400))`、`icon_size=128`、`icon_locations` 左右排布(app 在左、Applications 在右)。**改为竖版参数**。
- `brand/dmg/background.{png,@2x.png,tiff}`:由脚本产出的提交物。**重新生成**。
- `scripts/package_release.py`:调用 `dmgbuild -s dmg_settings.py -D app=… -D background=brand/dmg/background.tiff [-D icon=…] Teleport <out.dmg>`。**无需改动**(传入文件不变,卷名不变)。

## 设计

三处改动,均在现有管线内。背景图**只画"非图元"的静态美术**(白底 + 卡片 + 箭头);app 图标、应用程序文件夹、别名角标、文字标签全部由 Finder 依据 `dmg_settings.py` 在背景之上绘制。两者坐标必须对齐。

### 1. `scripts/gen_dmg_background.py`(重写)

产出竖版背景,内容仅两层:

1. 纯白画布(尺寸 = dmg 窗口内容区,见下)。
2. 底部一块**圆角矩形卡片**(Teleport 岩蓝微调色),卡片上半部绘制一个**大白色块状下箭头**。

**不在背景中绘制**:app 图标、应用程序文件夹、别名角标、任何文字。

仍按现有约定输出 `@1x`/`@2x`/多分辨率 `.tiff`(LZW 压缩),供 Finder 选取清晰版本。

副作用收益:新背景**完全不含文字**,旧实现里 PingFang/STHeiti 缺失导致中文 tofu 的字体 fallback 隐患**随之消除**。

### 2. `scripts/dmg_settings.py`(改参数)

由横版改竖版,关键设定(数值为起点,实现期对照真实 Finder 渲染微调):

- `default_view = "icon-view"`(不变)。
- `window_rect`:竖版,宽 **480**、高 **约 500–540**,与背景图尺寸严格一致。
- `icon_size`:**128**(对齐 Chrome 大图标)。注意 dmgbuild 对窗口内所有图标用同一尺寸——app 与文件夹同大,正合 Chrome 观感。
- `icon_locations`:
  - `Teleport.app`:顶部居中白底区,约 `(240, 120)`(图标中心)。
  - 应用程序入口:下方卡片中心、正对白箭头下方,约 `(240, 395)`。
- **隐藏应用程序文件夹的文字标签**:把 `symlinks` 的可见名改为单个空格 `" "`(键名即 Finder 显示名),使其无标签,匹配 Chrome 默认态。
  - 备选/回退:若某些 macOS 版本下空格名渲染异常,保留 `"Applications"` 标签(仍整洁,可接受)。
- `text_size`:保持系统观感(约 13)。app 标签由 Finder 自动绘制在图标正下方(普通黑字)。

`icon_locations` 必须与背景图中卡片/箭头位置像素对齐:文件夹落在卡片中心、箭头指向文件夹、app 图标落在顶部白区。

### 3. `brand/dmg/background.{png,@2x.png,tiff}`(重新生成)

由 `gen_dmg_background.py` 产出并提交。`package_release.py` 已指向 `brand/dmg/background.tiff`,无需改路径。

## 关键参数(起点值,实现期微调)

坐标系:逻辑像素,原点为背景图左上角(即窗口内容区,不含标题栏)。

| 项 | 值(起点) |
| --- | --- |
| 背景/窗口内容尺寸 | 480 × 510(@2x = 960 × 1020) |
| app 图标中心 | (240, 120) |
| 应用程序入口中心 | (240, 395) |
| `icon_size` | 128 |
| 下方卡片矩形 | x∈[80, 400], y∈[262, 452](320 × 190),圆角半径 ≈ 26 |
| 白箭头 | 居中 x=240,占卡片上半部(竖杆 y≈284–322,箭头尖 y≈356),纯白块状 |

配色:

| 元素 | 颜色 |
| --- | --- |
| 窗口背景 | `#FFFFFF` |
| 下方卡片(岩蓝微调) | `rgb(214, 222, 238)` ≈ `#D6DEEE` |
| 下箭头 | `#FFFFFF` |
| app 标签文字 | Finder 系统绘制(黑) |

> 岩蓝微调色是相对 Chrome 淡紫卡片向 Teleport 品牌岩蓝系(`#0f172a`/`#1e293b`)的偏移,保留品牌辨识度。结构与 Chrome 完全一致。

## 与 Chrome 的预期差异(可接受)

- **app 图标美术**:取决于 `branding/.../mac/app.icns`(当前为太极占位图),非 dmg 布局问题。
- **下方卡片色**:刻意偏 Teleport 岩蓝,而非 Chrome 淡紫。
- **精确像素度量**:为近似值,实现期对照真实渲染微调。

## 验证

1. `uv run --with pillow python scripts/gen_dmg_background.py` 重新生成背景三件套,人工查看 `@2x.png` 构图。
2. 轻量预览(推荐先做):用一个临时合成脚本把"背景 + 真实 app.icns + 系统应用程序文件夹 + 别名角标 + 标签"按 `dmg_settings.py` 坐标叠出窗口预览图,与参照(Chrome 默认态)并排比对——无需完整打包即可校准坐标/配色。
3. 全链路(较重,需 `TELEPORT_CHROMIUM_DIR` + 已签名构建):`uv run python scripts/package_release.py --no-upload` 出本地 dmg → 打开 → 比对布局/配色/箭头/文件夹角标/无多余文字。
4. `uv run pytest` 保持通过(若新增可测的纯函数逻辑则补测;否则不强求)。

## 风险与取舍

- **空格名 symlink 隐藏标签**:需验证目标 macOS 版本下确实渲染为无标签;异常则回退保留 `"Applications"`。
- **像素对齐**:背景静态美术与 Finder 图元两套坐标必须对齐,靠预览图迭代校准。
- **`icon_size` 单值约束**:窗口内所有图标同尺寸——与 Chrome 观感一致,无碍。
- **TDD 范围**:`gen_dmg_background.py`/`dmg_settings.py` 属构建/工具脚本(非随产品发布的 C++ 产品代码),按项目约定不强制 TDD,仅在有价值的纯逻辑处务实补 pytest。

## 实现后记(精确对齐 Chrome 实测值)

落地阶段为做到"完全一样",直接读取**已挂载的 Chrome 安装卷**(`/Volumes/Google Chrome`)里的真实数据来标定几何(仅测量、未拷贝其专有美术):

- `.DS_Store`(经 `ds_store` 解析):窗口 `fwi0`/`fwvh` = **480×540**,`icvo` 图标尺寸 **128**,`icvt` 文字号 **12**,app `Iloc (240,122)`、Applications `Iloc (240,387)`;其 Applications symlink 同样命名为单个空格 `" "`(印证隐藏标签做法)。
- 背景像素测量:色块 bbox `(90,287)-(389,484)`、近直角(圆角弧仅约 2px);白箭头杆宽 23(`x229–251`)自 `y=287`(与色块顶边齐平)至 307,头部 `y307→332` 由宽 51 收成尖。

最终采用值(与 Chrome 一致,仅窗口高度按用户偏好 +16px = **556** 留更多底部留白,卡片色保留 B 岩蓝 `(214,222,238)` 而非 Chrome 淡紫):**所有几何/配色集中在 `scripts/dmg_layout.py`,该文件为唯一事实来源**,`dmg_settings.py` 同步并由 `scripts/tests/test_dmg_settings.py` 守护对齐。

验证用 `dmgbuild` 直接对现成 `Teleport.app` 套样式出 dmg(无需签名/公证),并以**全新卷名**挂载以绕开 Finder 对旧同名卷的窗口缓存(此前误判的"滚动条"即源于该缓存)。
