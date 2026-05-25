# 设计:仓库与构建基础(overlay 构建基础)

- 状态:已评审通过(brainstorming),待转 implementation plan
- 日期:2026-05-25
- 代号:teleport(闪现 / Teleport)
- 子项目:#1「仓库与构建基础」(企业安全浏览器整体拆解中的基石)

## 1. 背景与目标

teleport(闪现)是基于 Chromium 源码自研的企业安全浏览器。整体产品由多个相对独立的子系统组成(构建基础、策略控制面、安全管控功能、设备身份、分发更新),本 spec 只覆盖**第一个、也是基石的子系统:仓库与构建基础**。

目标:让本仓库能**从 overlay 出发,构建出一个带「闪现」品牌、并能加载自定义 `//teleport` 模块的 Chromium**。在此之上,后续的策略客户端、安全功能才有落脚点。

## 2. 范围(本里程碑的 definition of done)

**最小可行基础(单平台,先 macOS)**,跑通三件事:

1. **品牌化构建**:产品显示名为「闪现」,含图标与 macOS bundle 名替换;
2. **`//teleport` 加法模块编进 chrome**:一个 trivial 模块能被编译、链接进浏览器,启动时打印 banner,证明定制代码注入链路通;
3. **可重复的 patch 应用**:一个 Python 脚本能把 `patches/` 幂等地应用到上游检出。

**明确不在本里程碑(留后续 phase)**:

- Windows / Linux 构建(三端化);未来国产 OS(鸿蒙等)适配;
- CI(真实 Chromium 构建过重);
- patch 的「创建 / 刷新 / 冲突处理」工具链(本里程碑只做「应用」);
- 完整 rebrand(安装包、所有平台图标、闪屏、关于页文案细节等);
- 任何安全功能 / 策略逻辑。

> 注:链接机制(见 §5/§6)从一开始就按跨平台编写(POSIX symlink / Windows junction),但**构建与验证仅在 macOS 上做**;三端实际构建留后续 phase。

## 3. 关键约定(已确认决策)

| 决策 | 取值 |
|---|---|
| Chromium 集成方式 | 补丁 / 叠加层(overlay),**方案 A:Brave 式** |
| 上游基线版本 | **Chromium M148**(M150 非稳定);后续再升级 |
| 构建工具 | **Siso**(`autoninja` 自动调用);ccache 基本不需要 |
| 本里程碑平台 | **macOS(Apple Silicon)优先**;三端与国产 OS 后续 |
| 编排脚本语言 | **Python**(与 depot_tools/gclient 生态一致、跨平台) |
| 产品命名(两层) | **显示名 = 闪现**;**ASCII 标识符 = Teleport / teleport** |
| 模块标识 | GN 路径 `//teleport`;C++ 命名空间 `teleport::` |
| TDD 范围 | **产品代码(`//teleport`)尽量 TDD**;构建/工具脚本不强求 TDD |

## 4. 总体架构:Brave 式 overlay

核心模型:**定制以加法为主、改上游为辅**。

- chromium 源码签出到仓库内的 `chromium/`(gitignore);
- overlay 的**纯源码**放在仓库的 `src/`,构建期以符号名 `teleport` 链接进 `chromium/src/teleport`,成为加法模块 `//teleport`(独立 GN target,链进 `chrome`);
- 工具脚本、`patches/`、`branding/` 都留在仓库根,**不进**被链接的源码目录;
- **不得已的上游改动**走 `patches/`(文本 patch)或 `branding/`(资源覆盖)。

这样跟随上游升级时冲突面最小,定制代码保有独立 git 历史,被链接进 chromium 的目录是「干净的产品源码」。

## 5. 仓库布局

chromium 源码签出到仓库内的 `chromium/`;overlay 纯源码放在仓库的 `src/`,构建期以**符号名 `teleport`** 链接进 chromium(符号名对应 GN 的 `//teleport`,与仓库侧目录名 `src` 解耦);所有编译产物落在仓库根的 `build/<os>/<arch>/<build_type>/`。

```
teleport/                          # repo 根
├── CLAUDE.md
├── src/                           # overlay 纯源码 → 链接为 chromium/src/teleport(GN: //teleport)
│   ├── BUILD.gn                   #   定义 //teleport:teleport 加法模块
│   ├── browser/
│   │   ├── teleport_startup.h
│   │   ├── teleport_startup.cc    #   MVP trivial 证明:启动期打 banner
│   │   └── teleport_startup_unittest.cc   # 产品代码 → TDD
│   └── gn/
│       └── args/
│           └── dev.mac.gn         #   开发期 args 模板 → import("//teleport/gn/args/dev.mac.gn")
├── chromium/                      # chromium 检出(gitignore);.gclient 钉死 M148
│   └── src/                       #   chromium 源码
│       ├── teleport  → 链接 → <repo>/src     (符号名 teleport;symlink / Windows junction)
│       └── out/      # 真实目录,编译产物在此(autoninja 要求 out 在检出树内)
├── patches/                       # 文本 patch,按 chromium/src 路径镜像,一文件一 patch
│   └── <mirrored upstream path>.patch
├── branding/                      # 资源覆盖(整文件,含二进制图标)
│   └── <mirrored upstream path>
├── scripts/                       # Python 编排脚本
│   ├── bootstrap.py               #   签出 chromium、建两个链接(按 OS 选 symlink/junction)
│   ├── sync.py                    #   gclient sync 到固定 M148
│   ├── apply_patches.py           #   应用 patches/ + branding/ 覆盖(幂等)
│   └── tests/                     #   仅在有价值处务实地测,不为 TDD 而 TDD
├── build/                         # → 链接 → chromium/src/out(gitignore);产物访问入口 build/<os>/<arch>/<build_type>/
│   └── <os>/<arch>/<build_type>/  #   例:build/mac/arm64/release/
└── .gitignore                     # 忽略 chromium/、build/、__pycache__ 等
```

> 仓库侧有两个 `src`:`<repo>/src`(overlay 源码)与 `<repo>/chromium/src`(chromium 源码),路径不同、互不冲突,符合「src 放源码」的对称惯例。`chromium/` 与 `build/` 均 gitignore,git 不会扫入。

## 6. chromium 检出、链接与注入机制

- **检出位置**:默认仓库内 `chromium/`(`chromium/.gclient` 的 `src` solution → `chromium/src`),整个 `chromium/` gitignore。**可用 `$TELEPORT_CHROMIUM_DIR` 覆盖**——几百 GB 的检出不宜绑定在每个 worktree 里,用它指向稳定路径以跨分支/worktree 复用(脚本 `_lib.chromium_dir()` 读取)。
- **版本固定**:`chromium/.gclient` 或单独的版本文件钉死 M148 具体版本号;`sync.py` 据此 `gclient sync`,并校验同步后版本一致(不一致即报错)。
- **两个链接**(由 `bootstrap.py` 创建,目标都在同一 repo 根 = 同卷):
  1. `chromium/src/teleport` → `<repo>/src`(overlay 源码;**符号名为 `teleport`**,与目标目录名 `src` 解耦)
  2. `<repo>/build` → `chromium/src/out`(编译产物;**方向重要**:out 须留在检出树内,autoninja 靠从 out 向上找检出根)
  - **跨平台**:POSIX 用 `os.symlink`;**Windows 用目录联接 junction(`mklink /J`)**——无需管理员 / 开发者模式,同卷适配。对 GN/Siso 而言两者都只是普通目录路径。
  - **风险与退路(M148 实跑修正)**:`out` **不可**链接到检出树外——autoninja 从 out 目录向上查找检出根,故 `out` 留在 `chromium/src/out`(真实目录),由 `<repo>/build` 反向链接过去。源码目录链接进 `src`:`gn gen` 已验证可读取(✓);clang 经 symlink 实际编译待 `//teleport` 接入 chrome 后验证。若届时 GN/clang 介意源码链接,退路是把 `<repo>/src` 拷贝 / 受管检出成 `chromium/src/teleport` 真实目录,**只改源码挂载方式**,其余不变。
- **把 `//teleport` 编进 chrome**:用一个**最小上游 patch**——在 chrome 对应 target 的 `BUILD.gn` 增加一条对 `//teleport` 的依赖。
  - ⚠️ 确切的 `BUILD.gn` 文件与 target 名,在 implementation 阶段对照 **M148 真实源码确认**,本 spec 不臆断。

## 7. 两类 overlay 操作

| 类型 | 目录 | 应用方式 | 用于 |
|---|---|---|---|
| **文本 patch** | `patches/` | `git apply`(`chromium/src` 本身是 git 仓库) | 改上游源码:`BUILD.gn` 依赖、启动钩子、`BRANDING` 串、`Info.plist` 等 |
| **资源覆盖** | `branding/` | 整文件拷贝替换上游 | 二进制 / 整文件资源:app 图标(`.icns`)等 |

两类操作互相解耦、各自独立,均无顺序依赖。

## 8. patch 管理与顺序不变量

- **一文件一 patch(one-patch-per-file)不变量**:每个 `.patch` 只改一个上游文件,文件名镜像该文件在 `chromium/src` 下的路径。
- ⇒ **顺序无关**:各 patch 互不重叠,先后不影响结果。`apply_patches.py` 按路径**排序后确定性应用**(排序只为可复现,不为正确性)。
- 同一上游文件需要多处改动 → **累加进该文件那一个 patch**,不新增第二个,以维持不变量。
- 真出现跨文件强依赖排序(YAGNI,目前没有)→ 再引入显式 `series` 清单。
- **幂等**:刚 `sync` 的干净树能全部应用;已应用的树重复跑安全(检测已应用则跳过)。
- **fail-fast**:任一 patch / 覆盖失败,立刻明确报出是哪一个,不留半应用状态。

## 9. 品牌化(两层)

为避免触碰 Chromium「产品名进文件路径 / 产物名默认 ASCII」的假设,做**显示名 / 标识符**两层区分:

| 层 | 取值 | 体现处 |
|---|---|---|
| **用户可见显示名** | **闪现**(主名) | 关于页、应用菜单、窗口标题、macOS `CFBundleDisplayName`、本地化产品串 |
| **ASCII 标识符** | **Teleport / teleport** | bundle identifier、磁盘上 `.app` / 可执行名、文件路径、`//teleport` 模块与 `teleport::` 命名空间 |

- 磁盘上为 `Teleport.app`(ASCII),Finder/Dock 显示「闪现」。
- 实现方式:
  - 产品名串:patch `BRANDING` 文件相关字段(显示名)+ 本地化资源串;
  - bundle 名 / 标识符:patch macOS `Info.plist` 相关字段(`CFBundleDisplayName` 等);
  - 图标:把「闪现」图标放 `branding/`,经资源覆盖替换上游主题目录中的 macOS app 图标。
- ⚠️ 确切的 `BRANDING` 字段、`Info.plist` 键、图标资源路径,在 implementation 阶段对照 **M148 真实源码确认**。

## 10. `//teleport` 加法模块 + trivial 证明

- `src/BUILD.gn` 定义 `static_library("teleport")`(GN 标签 `//teleport:teleport`),本里程碑仅含 `browser/teleport_startup.{h,cc}`,命名空间 `teleport::`。
- **trivial 证明链路**(同时验证「模块编进去」+「patch 能应用」):
  1. 加法模块提供 `teleport::LogStartupBanner()`,启动期用 Chromium `LOG()` 打印形如 `[teleport] 闪现 overlay active (M148)` 的 banner;
  2. 一个**最小启动 patch**:在浏览器启动早期钩子(如 `ChromeBrowserMainParts` 的某早期阶段)插一行调用 `teleport::LogStartupBanner()`。
- 运行构建出的 chrome,日志出现该 banner = 整条「定制代码注入 + patch 应用」链路打通。
- ⚠️ 具体启动钩子函数 / 文件,在 implementation 阶段对照 M148 源码确认。

## 11. 构建流程(开发者视角)

```bash
python scripts/bootstrap.py        # 一次性:签出 chromium 到 chromium/、建 teleport 与 out 两个链接
python scripts/sync.py             # gclient sync 到固定 M148
python scripts/apply_patches.py    # 应用 patches/ 与 branding/ 覆盖
cd chromium/src
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/release chrome     # 经 autoninja → Siso
# 运行构建产物,观察 [teleport] banner 与「闪现」品牌
```

开发期 args 模板(`src/gn/args/dev.mac.gn`,即 `//teleport/gn/args/dev.mac.gn`)沿用社区惯例的快速开发配置(release + component build + 低 symbol level、关闭 official/remoteexec);具体值在 implementation 阶段确定并固化进模板。

**构建产物位置**:`gn gen out/<os>/<arch>/<build_type>` 把产物写到真实目录 `chromium/src/out/<os>/<arch>/<build_type>/`;仓库根 `build/` 反向链接到 `chromium/src/out`,故也可经 **`build/<os>/<arch>/<build_type>/`** 访问:

- 目标文件 `.o` → `build/<os>/<arch>/<build_type>/obj/...`(本模块在 `.../obj/teleport/...`);
- 动态库(macOS `.dylib` / Linux `.so`;component build 下数量较多)→ `build/<os>/<arch>/<build_type>/`;
- 可执行 / 应用包 → `build/<os>/<arch>/<build_type>/Chromium.app`(显示名「闪现」,磁盘 `Teleport.app`)。

`build/` 与 `chromium/` 均 gitignore。`out` 链接 + nested out 目录使产物按 `<os>/<arch>/<build_type>` 归类于仓库根,同时其物理路径仍是 Chromium 期望的 `src/out/...`(经链接),兼容性最佳。

## 12. 验证(= definition of done)

1. macOS 上 `autoninja -C out/mac/arm64/release chrome` 构建成功;
2. 启动浏览器,日志出现 `[teleport] 闪现 overlay active (M148)`;
3. 产品显示名为「闪现」(关于页 / 应用名 / 窗口标题);图标与 bundle 名已替换;磁盘为 `Teleport.app`;
4. 干净 `sync` 后 `apply_patches.py` 全部干净应用,且可重复幂等。

以上以一份**脚本化 smoke 检查清单**(grep 日志 + 校验产品名串 + 检查 patch 应用结果)固化;因真实构建过重,**本里程碑 smoke 检查先手动 / 脚本跑,CI 留后续**。

## 13. 测试与 TDD 策略

- **产品代码**(`//teleport` C++ 模块,如 `teleport::LogStartupBanner()`):**尽量 TDD**——先写 gtest 单测(`*_unittest.cc`,经 Chromium 测试框架运行)再实现。
- **构建 / 编排脚本**(`bootstrap.py` / `sync.py` / `apply_patches.py`):属构建工具,**不强求 TDD**;仅在确有价值处务实地测(如 `apply_patches.py` 的幂等 / fail-fast 逻辑,可用一个微型「假 chromium/src」git 仓库做 fixture 验证),否则不写。
- **端到端构建产物**:由第 12 节的 smoke 检查清单覆盖,不做单测。

## 14. 错误处理

- `bootstrap.py`:缺 depot_tools 时明确提示安装方式;链接已存在但指向错误目标时报错并提示修复;Windows 上 junction 创建失败(如跨卷)时明确报错。
- `sync.py`:同步后版本与钉死值不一致 → 报错中止。
- `apply_patches.py`:任一 patch / 覆盖失败 → fail-fast,报出具体项,不留半应用状态;重复运行幂等。

## 15. 实现期需对照 M148 源码确认的点

(本 spec 刻意不臆断版本相关的具体路径 / 名称)

- 把 `//teleport` 注入 chrome 依赖的具体 `BUILD.gn` 文件与 target;
- 浏览器启动早期钩子的具体函数 / 文件;
- `BRANDING` 文件位置与字段、macOS `Info.plist` 相关键;
- macOS app 图标资源在上游主题目录的具体路径;
- 开发期 `args.gn` 的具体取值;
- GN 是否接受「源码目录经 symlink/junction 链接进 `chromium/src`」(决定是否启用 §6 的真实检出退路)。

## 16. 后续 phase(超出本里程碑,供路线参考)

- 三端化(Windows / Linux)实际构建与验证;
- patch「创建 / 刷新 / 冲突处理」工具链;
- CI(构建缓存与产物策略);
- 完整 rebrand;
- 之后才是子系统 #2「策略控制面」等。
