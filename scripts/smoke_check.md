# 构建与冒烟检查清单(macOS / M148)

本清单对应 spec §12 的 definition of done。命令以 `chromium/src` 在仓库外、由 `$TELEPORT_CHROMIUM_DIR` 指定为例。

## 准备

```bash
export TELEPORT_CHROMIUM_DIR=/path/to/chromium      # 检出在仓库外时
python scripts/bootstrap.py --skip-sync             # 建链接(已 sync 过)
python scripts/apply_patches.py                     # 应用 4 个补丁 + 图标覆盖
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/release chrome           # 首次数小时
```

## 冒烟检查

| # | 命令 / 检查 | 期望 | 实测(148.0.7778.180) |
|---|---|---|---|
| 1 | `autoninja ... chrome` | 构建成功 | ✅ `The build has finished successfully.` |
| 2 | `ls out/mac/arm64/release/*.app` | `Teleport.app` + `Teleport Helper*.app`(ASCII) | ✅ |
| 3 | `PlistBuddy -c 'Print :CFBundleIdentifier' Teleport.app/Contents/Info.plist` | `org.teleport.Teleport` | ✅ |
| 4 | `cmp Teleport.app/Contents/Resources/app.icns branding/.../mac/app.icns` | 一致 | ✅ |
| 5 | `Teleport.app/Contents/MacOS/Teleport --version` | `Teleport 148.0.7778.180` | ✅ |
| 6 | 启动并抓 banner(见下) | `[teleport] 闪现 overlay active (M148)` | ✅ |
| 7 | `apply_patches.py` 重复运行 | 幂等、无报错 | ✅ |

### 抓启动 banner

直接 `--enable-logging=stderr` 经重定向可能抓不到(进程会重启/分离),用显式 `--log-file`:

```bash
BIN=out/mac/arm64/release/Teleport.app/Contents/MacOS/Teleport
"$BIN" --user-data-dir=/tmp/tp --no-first-run --no-default-browser-check \
       --disable-field-trial-config \
       --enable-logging --log-file=/tmp/tp.log --v=1 >/dev/null 2>&1 &
PID=$!; sleep 12; kill "$PID"; wait "$PID" 2>/dev/null
grep -a "\[teleport\]" /tmp/tp.log
# 期望:...INFO:../../teleport/browser/teleport_startup.cc:12] [teleport] 闪现 overlay active (M148)
```

> **dev 构建务必加 `--disable-field-trial-config`**:否则 `fieldtrial_testing_config.json` 会强开实验特性,部分未完成会崩溃(如 `UsePersistentCacheForCodeCache` 加载页面时经沙箱 SQLite VFS 的 WAL 路径命中 `NOTREACHED`)。亦可精确 `--disable-features=UsePersistentCacheForCodeCache`。

## 品牌全面替换冒烟(macOS,已验证)

应用 overlay 后增量构建(远快于首次)。`apply_patches.py` 会跑 `branding_strings.py`(rebrand grd + 重写 zh-CN/zh-TW xtb)。

| 检查 | 命令 / 期望 | 实测 |
|---|---|---|
| grit 预检 | `autoninja -C out/... chrome/app:branded_strings` 成功 | ✅ |
| bundle id | `PlistBuddy -c 'Print :CFBundleIdentifier' Teleport.app/Contents/Info.plist` = `com.beansec.Teleport` | ✅ |
| app 图标 | `cmp Teleport.app/Contents/Resources/app.icns branding/.../mac/app.icns` 一致 | ✅ |
| en 文案 | `strings .../en.lproj/locale.pak \| grep -i "BeanSec\|Teleport"` 出现 Teleport / BeanSec / "Make Teleport the default browser" | ✅ |
| 运行 | `Teleport --disable-field-trial-config …` 启动有 banner、0 FATAL | ✅ |
| 幂等 | `branding_strings.py` 二次运行 = 0 ids remapped | ✅ |

GUI 目视(`chrome://settings/help`、`chrome://version`):zh-CN 显示「闪现」「北京小豆数安科技有限公司」;en 显示 "Teleport"/"BeanSec";各处 product logo = 我方标记。

## 仍待人工确认 / 后续

- zh-CN/zh-TW 关于页文案与 logo 的 GUI 目视确认(自动检查已覆盖 en pak + bundle/icon + xtb 重写)。
- macOS 顶部菜单 / Finder 显示名当前为 `Teleport`(CFBundleDisplayName=PRODUCT_FULLNAME)。若要菜单也显示「闪现」,需单独覆盖 `CFBundleDisplayName`——后续细化。
- **纯 "Chrome"(非 "Chromium")文案残留**(如 "Chrome Apps"):本轮只替换 "Chromium";是否一并把 "Chrome"→Teleport 属后续决策(易过度替换)。
- Windows / Linux 构建、CI、Windows `.ico` / Linux 图标、正式 wordmark:后续 phase。
