# Windows 构建环境搭建

> 本文覆盖 **Windows 桌面端**的 overlay 构建。macOS 路径见 `CLAUDE.md` 与
> `docs/superpowers/specs/2026-05-25-overlay-build-foundation-design.md`。
>
> **当前阶段**:P1「让 `chrome.exe` 编出来」**已达成,并于 2026-08-23 在真实 x64
> Windows 10 上验证**:沙箱开启下页面正常渲染,关于页显示 `0.2.0.1-dev` /「闪现」,
> `teleport_unittests` 169/169。两点环境相关的坑另见 TD-041(ARM64 构建机上的沙箱
> 异常,环境特有)与 TD-042(便携解压包需授 AppContainer ACL,已确证修法有效)。
> 渠道包、签名、安装包、自动升级
> 均**不在**本阶段范围内(Windows 侧尚无任何等价物,见文末「已知差距」)。

## 1. 目标架构

同一份检出同时服务两个 target:

| out 目录 | GN args 模板 | 用途 |
|---|---|---|
| `out/win-x64-dev` | `//teleport/gn/args/dev.win.x64.gn` | **企业实装架构**,产物即将来要发的东西 |
| `out/win-arm64-dev` | `//teleport/gn/args/dev.win.arm64.gn` | ARM64 宿主上原生运行,冒烟测试快 |

两者共用 `dev.win.gni` 里的全部架构无关参数,各自只覆盖 `target_cpu`(与
`staging.mac.gn` 链式 import `release.mac.gn` 是同一个理由:复制模板一定会漂移,
而漂移看起来只是「两个文件不一致」,没有任何东西标明哪边是对的)。

⚠️ **out 目录名必须正好在 `out/` 下一层**(`out/win-x64-dev` 可以,`out/win/x64/dev`
不行)。Chromium 把 MIDL 的生成产物签进仓库(`third_party/win_build_output/midl/…`),
构建期重跑一遍 midl.exe 再与基线**逐字节比对**;midl.exe 会把 `.idl` 的路径原样写进
生成文件的注释,基线里是 `../../third_party/…`,即假定 out 目录是 `out/<名字>`。
多分几层就变成 `../../../../third_party/…`,于是每个 MIDL target 都失败,报错是
「midl.exe output different from files in …」外加一段只有注释行不同的 diff——完全
指不到目录深度上去。macOS 不跑 MIDL,所以那边的 `out/mac/arm64/dev` 分层没事。

⚠️ **两个 out 目录 = 两次全量编译**。CLAUDE.md 的「跨 out 目录零编译复用是结构性的」
gotcha(无 RBE 时 `autoninja` 会给 siso 加 `--offline`,缓存读写整条跳过)是在 macOS 上
测出来的。Windows 侧**决定不复核**(2026-08-22):即便本地缓存可用,收益也只在「同一份
args 再开一个 out 目录」这种少见场景,不值得为验证它专门跑一轮构建。按「没有缓存」规划
时间即可。

## 2. 前置条件

### 2.1 通用

| 项 | 要求 | 备注 |
|---|---|---|
| 磁盘 | ≥ 200 GB 空闲,NTFS | 检出约 30 GB;每个 dev out 目录数十 GB |
| 内存 | ≥ 16 GB(推荐 32 GB+) | |
| Visual Studio | **2026(18.x)** 或 2022 | M151 的 `build/vs_toolchain.py` 已认 `'2026': 'VC145'` |
| VS 组件 | `Microsoft.VisualStudio.Workload.NativeDesktop`、`Microsoft.VisualStudio.Component.VC.ATLMFC` | ARM64 宿主另加 `VC.Tools.ARM64`、`VC.MFC.ARM64` |
| Windows SDK | `10.0.26100`(`vs_toolchain.py` 的 `SDK_VERSION`) | 需含 **Debugging Tools for Windows** |
| depot_tools | 已 clone 并在 PATH 最前 | |
| uv | 仓库脚本统一用 uv(`requires-python>=3.13`) | |
| **开发者模式** | **建议开**(设置 → 系统 → 开发者选项) | 见 §3:overlay 注入链接必须是真符号链接,建它需 `SeCreateSymbolicLinkPrivilege`;不开则需提权建一次 |

### 2.2 环境变量(用户级,一次设定)

```powershell
[Environment]::SetEnvironmentVariable('DEPOT_TOOLS_WIN_TOOLCHAIN','0','User')  # 用本机 VS,不拉 Google 内部工具链
[Environment]::SetEnvironmentVariable('TELEPORT_CHROMIUM_ROOT','D:\workspace\chromium','User')
# 并把 depot_tools 前置进用户 PATH
```

`TELEPORT_CHROMIUM_ROOT` 必须指向大容量卷:检出路径按发布分支派生为
`$TELEPORT_CHROMIUM_ROOT\<MAJOR.MINOR.BUILD>`(当前 `D:\workspace\chromium\151.0.7922`),
默认值 `~/workspace/chromium` 在 Windows 上会落到系统盘。

**不要**设 `TELEPORT_CHROMIUM_DIR`——它覆盖一切派生规则(见 CLAUDE.md 同名 gotcha)。

### 2.3 git 配置(**必须**,否则 patch 全线失败)

```powershell
git config --global core.autocrlf false   # depot_tools 也这么要求
git config --global core.filemode false
git config --global core.fscache true
git config --global core.preloadindex true
git config --global core.longpaths true
```

本仓库已有 `.gitattributes`(`* text=auto eol=lf`)兜底工作区行尾,但 chromium
检出不受它保护,`core.autocrlf=false` 仍是硬要求。若本机在设这些之前就已经 clone
过本仓库,工作区可能已是 CRLF——参见 §5「行尾」。

### 2.4 ARM64 宿主专项:`Debuggers\x64`

**症状**:`gn gen` 失败于

```
Exception: dbghelp.dll not found in "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\dbghelp.dll"
```

**为什么两个 target 都会踩**:Chromium 除了目标工具链,总是额外实例化一套
x64 宿主工具链(`win_clang_x64`),而 `vs_toolchain.py:_CopyDebugger()` 对**每套**
工具链都按 `Debuggers\<target_cpu>` 取 dbghelp/dbgcore/symsrv。所以哪怕
`target_cpu="arm64"`(arm64 那份我们有),x64 那份照样缺不得。

**为什么缺**:SDK 安装器按**宿主架构**过滤载荷,ARM64 机器上只装
`Debuggers\arm64`。Chromium 官方文档给的办法是「从另一台机器拷贝
`Debuggers\x64` 目录过来」。

**无需第二台机器的办法**(本仓库实际用的):从微软 SDK 载荷 CDN 直接取那个 MSI,
`msiexec /a` 展开(administrative install:只解包、不安装),再拷进 SDK。

```powershell
# 1) MSI + 它 Media 表引用的外部 cab(cab 名可直接在 MSI 字节里扫 [0-9a-f]{32}\.cab)
#    载荷基址可从 SDK 安装日志里取:%TEMP%\windowssdk\*.log 中搜 "download from:"
$base = 'https://download.microsoft.com/download/dba6f26e-0fb0-43bd-be9a-e3e24becb4a3/KIT_BUNDLE_WINDOWSSDK_MEDIACREATION/Installers'
Invoke-WebRequest "$base/X64%20Debuggers%20And%20Tools-x64_en-us.msi" -OutFile '<layout>\Installers\X64 Debuggers And Tools-x64_en-us.msi'
# ...同目录补齐 18 个 cab...

# 2) 展开(不需要管理员)
msiexec /a "<layout>\Installers\X64 Debuggers And Tools-x64_en-us.msi" /qn TARGETDIR=<stage>

# 3) 拷进 SDK(**需要管理员**)
Copy-Item "<stage>\Windows Kits\10\Debuggers\x64\*" 'C:\Program Files (x86)\Windows Kits\10\Debuggers\x64' -Recurse -Force
```

> 那个 MSI 里的 `dbghelp.dll` PE machine 应为 `0x8664`(AMD64)。校验一下再拷:
> 拷错架构会让错误从「文件缺失」变成更难查的「加载失败」。

顺手把长路径也开了(**需要管理员**,Chromium 的 `out/gen/third_party/blink/...`
很容易越过 260 字符):

```powershell
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1 -Type DWord
```

## 3. 引导与构建

```powershell
$env:DEPOT_TOOLS_WIN_TOOLCHAIN='0'

# 一次性:建检出 + gclient sync + 建两个链接
uv run python scripts/bootstrap.py            # 首次完整 sync,数小时
# 已同步过则:uv run python scripts/bootstrap.py --skip-sync

# 应用 overlay(幂等)
uv run python scripts/apply_patches.py

# 工具脚本单测(仓库根)
uv run pytest
```

两条链接的**类型不同**,这不是风格问题:

- `<chromium>\src\teleport` → `<repo>\src`(GN 模块 `//teleport`):**必须是真符号链接**。
  构建系统要走进去,而 **siso 不穿越目录联接(junction)**。用 junction 的话,`gn gen`
  会完美解析、报出全部 ~31.5k targets,然后 siso 在编译任何东西之前死于:

  ```
  error in depfile "out/win-x64-dev/build.ninja.d": deps input
  "../../../../teleport/BUILD.gn" not exist: store resolve next dir teleport failed
  ```

  这条错误里没有任何字眼指向链接类型或权限。换成 `mklink /D` 的真符号链接
  (reparse tag `0xa0000003` → `0xa000000c`)siso 立刻正常——siso 是 Go 写的,Go 对
  这两种 reparse point 的语义历来不同。因此 `create_dir_link()` 在
  `traversed_by_build=True` 时**只建符号链接,建不了就当场硬失败**并给出两条出路,
  绝不回退到 junction:回退等于拿一个当场的清晰错误,换上面那个又晚又费解的。

- `<repo>\build` → `<chromium>\src\out`:构建系统从不走进去,继续用**免权限的
  junction**。为它要求提权是只有成本、没有收益的。

建符号链接的权限**只在创建时需要**,建好之后所有人都能非提权使用。所以两条路都行:
开开发者模式(推荐,一劳永逸),或提权跑一次:

```powershell
cmd /c mklink /D "D:\workspace\chromium\151.0.7922\src\teleport" "D:\workspace\teleport\src"
```

然后 `gn gen` + 构建(在检出根执行):

```powershell
Set-Location D:\workspace\chromium\151.0.7922\src
gn gen out/win-x64-dev   --args='import("//teleport/gn/args/dev.win.x64.gn")'
gn gen out/win-arm64-dev --args='import("//teleport/gn/args/dev.win.arm64.gn")'

autoninja -C out/win-x64-dev teleport_unittests   # 见下方警告:这不是小目标
.\out\win-x64-dev\teleport_unittests.exe
autoninja -C out/win-x64-dev chrome
```

> ⚠️ **`teleport_unittests` 不是「小目标」**。它自己只有 18 个测试 TU,但 `:teleport`
> 依赖 `//content/public/common`,把整个浏览器底座连同图形栈(dawn/swiftshader/skia/
> spirv-tools)、perfetto、mojo 一起拖进闭包;加上 `//net`(→ boringssl/icu)与
> `//base/test`,实测约 **45,800 个构建步骤**,大约是 `chrome` 的七八成——先编它几乎
> 省不下时间。要几分钟内确认「我们的 C++ 在 clang-cl 下编得过」,直接编我们自己的
> 目标文件(35 个 TU,不链接闭包):
>
> ```powershell
> autoninja -C out/win-arm64-dev obj/teleport/teleport/teleport_startup.obj  # 等等
> ```

> PowerShell 传 `--args=...` 时,内层双引号会被吞掉(报
> `Invalid token ... Comments should start with #`)。用 `--%` 停止解析,或者
> 直接在 bash/cmd 里跑这条命令。

## 4. 与 macOS 的差异一览

| 方面 | macOS | Windows |
|---|---|---|
| 注入链接 | 符号链接 | **同样必须是符号链接**(siso 不认 junction);建它需开发者模式或一次提权 |
| `build/` 便利链接 | 符号链接 | 目录联接(免权限);git 把它当普通目录,报 `?? x/` 带尾斜杠 |
| depot_tools 调用 | `gclient`/`gn`/`autoninja` | 必须解析到 `.bat`(见 `_lib.depot_tool()`) |
| 打包 | `package.py` 全链路 | **无**。`package.py` 的 dev 分支写死 `Teleport.app`,Windows 上不可用 |
| 自动升级 | Sparkle | **无** |
| 渠道身份 | `channel_customize` + bundle id | **无** |

## 5. 行尾(踩过的坑)

Git for Windows 默认 `core.autocrlf=true`,于是 clone 出来的工作区**整棵树都是
CRLF**,而索引仍是 LF——`git status` 干干净净,什么都看不出来。后果是
`patches/*.patch` 在磁盘上是 CRLF,而 chromium 检出是 LF:

- `git apply` 既不能正向应用,也不能 `--reverse --check`;
- `apply_patches.py` 正是用后者判定「已应用」,于是它在一棵**完全正常**的树上
  报 `patch does not apply cleanly`。

现在有两道防线:

1. 仓库根 `.gitattributes` 的 `* text=auto eol=lf`——把工作区行尾钉死,不再依赖
   每个人的 `core.autocrlf`;
2. `_lib.write_text_lf()`——所有**生成进检出**的文件(`chrome/VERSION`、引擎版本头、
   品牌重写后的 grd/xtb、导出的 patch)都走它。`Path.write_text()` 以
   `newline=None` 打开,会把换行翻译成 `os.linesep`,在 Windows 上即 CRLF。

若本机在 `.gitattributes` 落地前就 clone 过,一次性归一化:

```bash
git ls-files --eol   # 出现 w/crlf 即需处理
git add --renormalize .
```

## 6. 已知差距(P1 之外)

P1 只保证「编得出来」。以下 macOS 侧已有、Windows 侧还没有的能力,均登记在
`docs/tech-debt.md`:

- **渠道来源**:`ReadChannelNameFromBundle()` 在非 mac 返回空串 → 渠道恒为
  `UNKNOWN`。Windows 的对应物应是注册表/安装目录。
- **DM token 存储**:只有 `browser_dm_token_storage_mac.mm` 的 patch,缺 `_win`。
- **用户数据目录 / 平台策略读取域**:mac 走 `chrome_paths_mac.mm` +
  `CrProductDirName`,Windows 走 `install_static` + 注册表,尚未核对。
- **图标与品牌资源**:`branding/` 下只有 mac 的 `.icns` / `Assets.xcassets`,
  Windows 的 `.ico` 未生成(`generate_icons.py` 只出 icns)。
- **平台编解码器**:`dev.win.gni` 只开 `proprietary_codecs` + `ffmpeg_branding`,
  没有照搬 mac 的 `enable_platform_*`(那些在 Windows 上走 MediaFoundation,
  是另一条从未编过的代码路径)。
- **打包 / 签名 / 分发 / 自动升级**:整条链路缺失。
- **`branding_strings.py` 的 grit 目标平台**写死 `darwin`,Windows 构建下
  `<if expr="is_win">` 分支的 id 重映射因此可能不准(影响的是 zh 翻译完整性,
  不影响编译)。
