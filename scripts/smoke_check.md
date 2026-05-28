# 构建与冒烟检查清单(macOS / M148)

本清单对应 spec §12 的 definition of done。命令以 `chromium/src` 在仓库外、由 `$TELEPORT_CHROMIUM_DIR` 指定为例。

## 准备

```bash
export TELEPORT_CHROMIUM_DIR=/path/to/chromium      # 检出在仓库外时
python scripts/bootstrap.py --skip-sync             # 建链接(已 sync 过)
python scripts/apply_patches.py                     # 应用 4 个补丁 + 图标覆盖
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev chrome           # 首次数小时
```

## 冒烟检查

| # | 命令 / 检查 | 期望 | 实测(148.0.7778.180) |
|---|---|---|---|
| 1 | `autoninja ... chrome` | 构建成功 | ✅ `The build has finished successfully.` |
| 2 | `ls out/mac/arm64/dev/*.app` | `Teleport.app` + `Teleport Helper*.app`(ASCII) | ✅ |
| 3 | `PlistBuddy -c 'Print :CFBundleIdentifier' Teleport.app/Contents/Info.plist` | `org.teleport.Teleport` | ✅ |
| 4 | `cmp Teleport.app/Contents/Resources/app.icns branding/.../mac/app.icns` | 一致 | ✅ |
| 5 | `Teleport.app/Contents/MacOS/Teleport --version` | `Teleport 148.0.7778.180` | ✅ |
| 6 | 启动并抓 banner(见下) | `[teleport] 闪现 overlay active (M148)` | ✅ |
| 7 | `apply_patches.py` 重复运行 | 幂等、无报错 | ✅ |

### 抓启动 banner

直接 `--enable-logging=stderr` 经重定向可能抓不到(进程会重启/分离),用显式 `--log-file`:

```bash
BIN=out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport
"$BIN" --user-data-dir=/tmp/tp --no-first-run --no-default-browser-check \
       --disable-field-trial-config \
       --enable-logging --log-file=/tmp/tp.log --v=1 >/dev/null 2>&1 &
PID=$!; sleep 12; kill "$PID"; wait "$PID" 2>/dev/null
grep -a "\[teleport\]" /tmp/tp.log
# 期望:...INFO:../../teleport/browser/teleport_startup.cc:12] [teleport] 闪现 overlay active (M148)
```

> **dev 构建务必加 `--disable-field-trial-config`**:否则 `fieldtrial_testing_config.json` 会强开实验特性,部分未完成会崩溃(如 `UsePersistentCacheForCodeCache` 加载页面时经沙箱 SQLite VFS 的 WAL 路径命中 `NOTREACHED`)。亦可精确 `--disable-features=UsePersistentCacheForCodeCache`。

## dev 构建已知崩溃(非 overlay 问题,正式构建无)

dev args `is_official_build=false` 会令 `dcheck_always_on` 与 `enable_expensive_dchecks` 默认 true,把上游一批「重型自检」断言编进来。已知会在正常浏览中误触发、abort 渲染进程("页面崩溃" / Aw Snap)的:

- **`ng_shape_cache.h:243` 的 `DCHECK_EQ(*cached_result, *other_shape_result)`** —— 字体 shaping 缓存的一致性自检。CJK 文本(如 baidu)在字体 fallback 解析上有不确定性,缓存结果(仅存无 fallback 的)与重算结果的字体引用对不上而触发(两次 dump 字形完全一致,差异在 `ToString` 不打印的字段);属上游已知脆弱点 `crbug.com/486945341`。栈顶常是 JS 读 `Element::innerText` → 强制同步 layout → shaping。**编译期 `#if EXPENSIVE_DCHECKS_ARE_ON()` 守卫,运行时 `--disable-features` / `--disable-field-trial-config` 关不掉**。
  - 处置:`gn/args/dev.mac.gn` 已设 `enable_expensive_dchecks = false`(只关重型自检,保留普通 DCHECK)。改该 arg 后需重新 `gn gen` + 增量构建(改 buildflag → 一波较大增量重编,非从头);验证:重跑 baidu 反复搜索,不再出现 `ng_shape_cache.h:243` 的 FATAL。
- **`UsePersistentCacheForCodeCache`** —— 见上「抓启动 banner」note:由 `fieldtrial_testing_config.json` 强开,经沙箱 SQLite VFS 的 WAL 路径命中 `NOTREACHED`。这个是运行时 feature,加 `--disable-field-trial-config`(或精确 `--disable-features=UsePersistentCacheForCodeCache`)即可关。

> 共同点:均为上游在「非 official + DCHECK」构建下才暴露的问题,与 overlay 无关(`patches/`、`src/` 未碰 shaping/font/dcheck;崩溃栈无 `teleport::` 帧),stable/official 构建均不出现。

## 品牌全面替换冒烟(macOS,已验证)

应用 overlay 后增量构建(远快于首次)。`apply_patches.py` 会跑 `branding_strings.py`(rebrand grd + 重写 zh-CN/zh-TW xtb)。

| 检查 | 命令 / 期望 | 实测 |
|---|---|---|
| grit 预检 | `autoninja -C out/... chrome/app:branded_strings` 成功 | ✅ |
| bundle id | `PlistBuddy -c 'Print :CFBundleIdentifier' Teleport.app/Contents/Info.plist` = `com.beansec.Teleport` | ✅ |
| 菜单显示名 | `PlistBuddy -c 'Print :CFBundleDisplayName' Teleport.app/Contents/Info.plist` = `闪现` | ✅ |
| 版权 | `grep COPYRIGHT chrome/app/theme/chromium/BRANDING` 含 `BeanSec` | ✅ |
| app 图标 | `cmp Teleport.app/Contents/Resources/app.icns branding/.../mac/app.icns` 一致 | ✅ |
| en 文案 | `strings .../en.lproj/locale.pak \| grep -i "BeanSec\|Teleport"` 出现 Teleport / BeanSec / "Make Teleport the default browser" | ✅ |
| 运行 | `Teleport --disable-field-trial-config …` 启动有 banner、0 FATAL | ✅ |
| 幂等 | `branding_strings.py` 二次运行 = 0 ids remapped | ✅ |

GUI 目视(`chrome://settings/help`、`chrome://version`):zh-CN 显示「闪现」「北京小豆数安科技有限公司」;en 显示 "Teleport"/"BeanSec";各处 product logo = 我方标记。

## 仍待人工确认 / 后续

- zh-CN/zh-TW 关于页文案与 logo 的 GUI 目视确认(自动检查已覆盖 en pak + bundle/icon + xtb 重写)。
- **纯 "Chrome"(非 "Chromium")文案残留**(如 "Chrome Apps"):本轮只替换 "Chromium";是否一并把 "Chrome"→Teleport 属后续决策(易过度替换)。
- Windows / Linux 构建、CI、Windows `.ico` / Linux 图标、正式 wordmark:后续 phase。

## teleport:// scheme 别名

启动:`open -n out/mac/arm64/dev/Teleport.app --args --disable-field-trial-config`。

| # | 检查 | 期望 |
|---|---|---|
| 1 | gtest `teleport_unittests --gtest_filter='TeleportUrlScheme*'` | 6 个全过 |
| 2 | 输入 `teleport://settings`、`teleport://version`、`teleport://history` | 能打开,内容与 chrome:// 版本一致 |
| 3 | 输入 `chrome://settings` | 能打开,地址栏显示 `teleport://settings` |
| 4 | 点击页面内部 `chrome://` 链接 / 打开 `chrome://` 书签 | 地址栏显示 `teleport://`;复制地址栏 URL 得到 `teleport://` |
| 5 | `teleport://teleport-urls`(或 `chrome://chrome-urls`) | 打开 URL 目录页,地址栏显 `teleport://teleport-urls`;列表标签显 `teleport://`,点击可达 |
| 6 | DevTools / `chrome://inspect` 远程调试 | 仍正常(未别名 `devtools://`) |
| 7 | 新标签页 | 地址栏仍为空 |

> 已知限制(本期不做):`teleport://help` 不会重定向到 `settings/help`(短路跳过 `HandleWebUI` 的 host 改写),改用 `teleport://settings/help`;地址栏以外的 URL 显示面(页面信息气泡、状态栏)、chrome-urls 以外的页内 `chrome://` 文本均为后续增量。

## dogfood 渠道包 + Sparkle 自动升级(macOS,已端到端验证)

前置见 `CLAUDE.md` 的「渠道包/自动升级」段(Developer ID 证书、notarytool profile、EdDSA 密钥、`scripts/release_config.local.toml`)。发布后用公网 URL 校验,不依赖本地构建产物。

| # | 命令 / 检查 | 期望 | 实测 |
|---|---|---|---|
| 1 | `uv run python scripts/package_release.py`(`TELEPORT_CHROMIUM_DIR` 已设) | 构建→签名→公证→样式dmg→appcast→上传,末尾 `published <ver>` | ✅ |
| 2 | `curl -fsSI <feed>/Teleport-<ver>.dmg` | HTTP 200,`Cache-Control: ...immutable`,~110MB(ULMO) | ✅ |
| 3 | 下载后 `spctl -a -t install <dmg>` | `accepted` + `source=Notarized Developer ID` | ✅ |
| 4 | `xcrun stapler validate <dmg>` | `The validate action worked!` | ✅ |
| 5 | 挂载后 `defaults read .../Teleport.app/Contents/Info SUFeedURL/SUPublicEDKey/CFBundleVersion` | feed URL / 公钥 / semver 正确 | ✅ |
| 6 | 挂载,Finder 窗口 | 背景图(中文正常)、左 Teleport.app、右**命名的** Applications、卷图标 | ✅ |
| 7 | 从 dmg 内 `Teleport.app/Contents/MacOS/Teleport --version` | `Teleport 148.0.7778.180`(框架+Sparkle 加载,无崩溃) | ✅ |
| 8 | `curl -fsS <feed>/appcast.xml \| grep sparkle:version` | 仅列最新版,无 `<sparkle:deltas>` | ✅ |

### 升级闭环(v1→v2,已实测 0.1.0→0.1.1)

1. 发布 v1(如 0.1.0)+ v2(bump `TELEPORT_VERSION`,如 0.1.1)到 OSS;appcast 最新=v2,两个 dmg 均在。
2. 清理后装 v1:`rm -rf /Applications/Teleport.app && defaults delete com.beansec.Teleport`;下载 `Teleport-0.1.0.dmg` 拖入 /Applications,右键打开;`defaults read .../Info CFBundleShortVersionString` = `0.1.0`。
3. 运行 v1 → `SUEnableAutomaticChecks` 自动检查 → 弹「有新版本 0.1.1 可用」。(未接「检查更新」菜单;不弹则 `defaults delete com.beansec.Teleport SULastCheckTime` 后重启强制检查。)
4. 点「更新」→ 下载 v2 → EdDSA + 代码签名校验 → 重启安装(/Applications 可能弹一次管理员密码)。
5. 确认:`defaults read /Applications/Teleport.app/Contents/Info CFBundleShortVersionString` = `0.1.1`。✅ 实测通过。

> 排错:升级失败看 Console.app 搜 `Sparkle`;崩溃于框架加载(`no LC_RPATH's found`)= rpath 丢失;公证失败看 `notarytool log <uuid>`。
