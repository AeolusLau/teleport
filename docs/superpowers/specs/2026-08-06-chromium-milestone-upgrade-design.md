# Chromium 基线升级设计（M148 → M151）

- 日期：2026-08-06
- 分支：`chore/chromium-151-upgrade`
- 状态：设计已确认，待评审

## 1. 背景与动机

本仓库是 Brave 式 Chromium overlay，上游基线钉在 `CHROMIUM_VERSION = 148.0.7778.180`。

升级的驱动力**不是想要新特性，而是安全支持已经断档**：

- 桌面 Chrome 的偶数里程碑进 Extended Stable，支持约 8 周（跨两个 4 周周期）。M148 是偶数里程碑，其 Extended Stable 窗口在 M150 上线（2026-06-30）时结束。
- 即当前基线**已脱离上游安全支持约 5 周**，且此后 M148 发布分支不再收任何修复。
- 上游一旦把 stable 切到新里程碑，旧发布分支即停止维护，所有安全修复只往新分支打。这是"必须跟里程碑"的根本原因。

截至 2026-08-06 的上游状态：

| 项 | 值 |
|---|---|
| 桌面 stable | `151.0.7922.76`（Mac / Windows 相同） |
| Extended Stable | M150（`150.0.7871.x`），窗口至 M152 上线 |
| M152 预计上线 | 2026-08-25 |

## 2. 目标与非目标

### 2.1 目标

1. 上游基线 M148 → **M151**，`CHROMIUM_VERSION` = `151.0.7922.76`（sync 前复核当时最新桌面 stable）
2. 105 个 patch 迁移到新基线并重新导出
3. `//teleport` overlay 源码修到可编译（上游 API 漂移）
4. 建立**可复用**的 rebase / 导出工具链与升级 runbook（此前仓库只有「应用 patch」的能力）
5. 建立上游发布跟踪机制（区分「打了 tag」与「真的发布」）
6. 验证到**能出 canary 包**（不发布）
7. `TELEPORT_VERSION` 从 `0.1.12.0` bump 到 `0.2.0.0`，标记底座跃迁

### 2.2 非目标

- **fairyland 侧不改代码**。vendored 的上游 proto 增量已实测为纯新增（见 §3.4），双向线兼容；fairyland 仅作为联调对端参与验证。
- 不实现 M151 新增的任何上游能力（MDM 证书挑战、扩展更新远程命令等）。
- 不清理存量技术债（TD-001..024），除非升级本身逼着改。
- 不发布 canary 版本到 OSS（`package.py` 不加 `--distribute`）。
- 不做 Windows / Linux 构建（`check_upstream_release.py` 会覆盖 Windows 版本查询，但不含构建）。

### 2.3 后续（不在本 spec 范围）

- 2026-08-25 M152 上线后的小步跃迁（复用本次工具链）
- `check_upstream_release.py` 接入 CI 定时任务（CI 尚未建立）
- Windows 客户端构建

## 3. 关键事实（实测数据）

以下均为在现有检出上实测所得，非估计。冲突分析使用本地已有的 `151.0.7922.97`；与拟钉的 `151.0.7922.76` 同属 `7922` 发布分支，仅差若干安全修复，结论等价。**G0 阶段将用实际钉住的版本复跑一次**。

### 3.1 Patch 迁移面

对 M151 树做 `git apply --cached --check` dry-run（临时索引，无需检出）：

| 结果 | 数量 |
|---|---|
| 干净适用 | 83 |
| 需三方合并（git 自动可解） | 20 |
| **真冲突（需人工重写）** | **2** |
| 合计 | 105 |

作为对照，对 M150 树的同一测试为 89 / 16 / **0**。选择 M151 多付的正是这 2 个冲突与 1 处 API 迁移，换来的是提前吃掉 M152 的主要重构迁移成本。

**G0 实测复核**（2026-08-06，Task 6）：以上数字基于本地已有的 `151.0.7922.97` 估算。在实际钉住的 `~/workspace/chromium/151.0.7922` 检出（`chrome/VERSION` 已核实为 `151.0.7922.76`，两套 PGO profile 齐全，`148.0.7778.180` 与 `151.0.7922.76` 两个 tag 均可解析）上，用临时索引（`GIT_INDEX_FILE`，未触碰工作树）对 `151.0.7922.76` 重跑同一 dry-run，结果为 **83 CLEAN / 20 3WAY / 2 CONFLICT**（105 补丁全数覆盖），与上表估算**完全一致**。两个 CONFLICT 与 §3.2 所列相同：`about_page.html.patch`、`status_box.html.patch`。经逐一核实，两者的补丁目标文件在 `151.0.7922.76` 树上均**不存在**（`git cat-file -e` 返回 missing）——均系上游「Lit 迁移」提交（`about_page.html` 见提交 `204e553199ff5`；`status_box.html` 见提交 `66fcae82b4862`）把原 Polymer `.html` 拆分为 `.ts` + `.html.ts` 所致，属于**重写**范畴（目标文件已迁形），而非需要合并同一行改动的**合并**范畴。结论：G0 通过，7922 分支内 `.76` 与 `.97` 两个 patch release 在补丁迁移面上结论等价，Task 7 可直接按 §3.2 的重写方案执行。

### 3.2 两个真冲突：上游 Lit 迁移

两个目标文件在 M151 被迁移为 Lit 模板形态，原文件不复存在：

| 旧路径（M148/M150） | 新形态（M151） | 我们的改动内容 |
|---|---|---|
| `chrome/browser/resources/settings/about_page/about_page.html` | `about_page.html.ts` | About 页版本展示、Sparkle check-for-updates、页脚链接 |
| `components/policy/resources/webui/status_box.html` | `status_box.html.ts` | `chrome://policy` 状态框品牌化 |

需按 Lit 模板形态重写这两个 patch。本仓库自有的 `src/browser/resources/enroll/enroll_app.html.ts` 即为同一形态，不是陌生工作。

### 3.3 Overlay 源码的 API 漂移

`//teleport` overlay 共引用 162 个头文件，其中上游头文件在 M151 的状态：

| 状态 | 数量 |
|---|---|
| 未变 | 84（对 M150 计） |
| 有改动 | 36（对 M150 计，M151 只多不少） |
| **移位 / 删除** | **3** |

已定位的确定性破坏，全部集中在 `src/browser/enterprise/teleport_voluntary_signin.{h,cc}`：

1. `chrome/browser/ui/browser_navigator.h` → `chrome/browser/ui/navigator/browser_navigator.h`
2. `chrome/browser/ui/browser_navigator_params.h` → `chrome/browser/ui/navigator/browser_navigator_params.h`
3. `chrome/browser/ui/browser_finder.h` 在 M151 **被整体删除**。`chrome::FindBrowserWithTab(wc)` 由 `GlobalBrowserCollection::GetInstance()->FindBrowserWithTab(wc)` 取代（`chrome/browser/ui/browser_window/public/global_browser_collection.h`），返回 `BrowserWindowInterface*` 而非 `Browser*`。这是上游 Browser 类解耦重构的一部分；`OpenVoluntaryEnrollmentTab(Browser*)` 的签名大概率需相应调整。

`global_browser_collection.h` 在 M150 上即已存在，故该迁移对未来里程碑同样有效。

**诚实说明**：上述 36 个「有改动」的头文件是否导致编译错误，**只有真编译才知道，无法预先枚举**。这是本次工作量的主要不确定性来源，验证设计（§7）必须把 G2 设计成迭代闸门而非一次性检查。

### 3.4 跨仓协议兼容性

fairyland 在 `proto/teleport/upstream/chromium/` 下 vendor 了上游 Chromium 的协议定义。M148 → M150 的差异：

| 文件 | 差异 |
|---|---|
| `device_management_backend.proto` | +44 行 |
| `chrome_device_policy.proto` | +2 行 |
| `reporting/record_constants.proto` | +3 行 |
| `policy_common_definitions.proto` | 无变化 |
| `reporting/record.proto` | 无变化 |

逐行核查确认**全部为新增**：新增 optional 字段（编号 42 / 14 / 15 / 5）、新增 `CertificateDetails` 与 `SignedCertificateDetails` 两个 message、新增远程命令枚举值 `BROWSER_EXTENSION_UPDATE_CHECK = 18`。**无字段删除、无编号变更、无已有字段语义变更** → 双向线兼容。

结论：新基线浏览器与现有 fairyland 服务端可直接互通，服务端无需改动。re-vendor 登记为后续待办（非阻断）。

### 3.5 免费项

以下被 patch 的上游文件在 M148 → M150 未发生变化，M151 需复核但风险低：

- `chrome/installer/mac/signing/` 下四个文件（`chromium_config.py` / `modification.py` / `parts.py` / `signing.py`）
- `build/apple/tweak_info_plist.py`
- `net/base/proxy_delegate.h`、`net/base/test_proxy_delegate.{h,cc}`、`services/network/network_service_proxy_delegate.{h,cc}` 等 Track T 隧道相关文件

即打包签名链与最新的隧道改造在本次升级中基本无成本。

## 4. 范围内的产出清单

| 类别 | 产出 |
|---|---|
| 版本 | `CHROMIUM_VERSION` → `151.0.7922.76`；`TELEPORT_VERSION` → `0.2.0.0` |
| Patch | 105 个 patch 重新导出；其中 2 个人工重写 |
| Overlay 源码 | `teleport_voluntary_signin.{h,cc}` API 迁移；其余按编译结果迭代修复 |
| 新脚本 | `scripts/rebase_overlay.py`、`scripts/export_patches.py`、`scripts/check_upstream_release.py` |
| 改脚本 | `scripts/_lib.py`（检出路径派生）、`scripts/sync.py`（旧基线 tag 可达）、`scripts/bootstrap.py`（`build` 链接重建） |
| 文档 | `docs/chromium-upgrade-runbook.md`（新增）；`CLAUDE.md`、`docs/tech-debt.md`（更新） |

## 5. 检出布局

### 5.1 路径派生规则

检出目录**按发布分支划分**，即版本号前三段（`MAJOR.MINOR.BUILD`）。BUILD 号唯一标识一条上游发布分支（`refs/branch-heads/<BUILD>`）。

```
CHROMIUM_VERSION  = 151.0.7922.76                       # 精确 pin，sync 目标，sync.py 校验
检出目录          = $TELEPORT_CHROMIUM_ROOT/151.0.7922   # 取前三段
                    默认 $TELEPORT_CHROMIUM_ROOT = ~/workspace/chromium
$TELEPORT_CHROMIUM_DIR                                   # 仍可整体覆盖（向后兼容 / CI）
```

`_lib.chromium_dir()` 由「默认 `<repo>/chromium`」改为上述派生。收益：

- 切分支时 `CHROMIUM_VERSION` 不同 → 自动指向对应检出，**「忘记 export `TELEPORT_CHROMIUM_DIR` 导致打到假路径」这一类坑从结构上消失**
- 不同基线的 worktree 天然隔离

**为什么按发布分支而非完整版本**：PATCH 级移动（如 `.76 → .132`）始终在同一发布分支内，`git fetch && git checkout` + `gclient sync` 增量即可，DEPS 基本不动、构建缓存基本全热。若按完整版本划分目录，一次安全补丁就会触发新建约 110 GB 检出加全量重编，代价与收益完全不成比例。

由此两类升级自然分层：

| 场景 | 动作 | 检出 |
|---|---|---|
| 安全补丁 `.76 → .132` | 改 `CHROMIUM_VERSION` → `sync.py` → `apply_patches.py` → 增量构建 | 同一检出 |
| 里程碑 `151 → 152` | 改 `CHROMIUM_VERSION` → 目录随之变为 M152 的发布分支号（该 BUILD 号在 M152 上线前不可知） → 新检出 + 完整 rebase 流程 | 新建，旧检出留作回退 |

### 5.2 旧检出的处置

现有 `<repo>/chromium`（271 GB，其中 `out/` 占 161 GB）**原地保留，不迁移**。

理由：Chromium 的 `out/` 目录含 GN 写入的绝对路径，**移动即废掉 161 GB 构建缓存**，等于失去「升级期间仍能构建 M148 发 hotfix」的应急能力——而这正是采用独立检出方案的核心理由。

为使派生路径规则对新旧基线一致成立，在 `~/workspace/chromium/148.0.7778` 建**符号链接**指向 `<repo>/chromium`。零成本，不搬动数据，不废缓存。

M151 出包验证通过后，再决定旧检出归档或删除。

### 5.3 链接与磁盘

- `<repo>/build → <checkout>/src/out` 在切换基线时需重建。当前 `_lib.create_dir_link()` 在链接指向不符时直接抛错，需为 `bootstrap.py` 增加重建路径。
- `<checkout>/src/teleport → <repo>/src` 由 `bootstrap.py` 创建，新检出照常。
- 磁盘账：新检出源码 + DEPS 约 110 GB，加 dev / release 两套构建输出；旧检出 271 GB 保留。峰值约 500–600 GB。当前可用 2.9 TiB。

## 6. 上游发布跟踪

### 6.1 版本号与发布模型（升级决策的基础）

Chromium 版本号四段的语义：

| 段 | 含义 |
|---|---|
| MAJOR | 里程碑 |
| MINOR | 早已恒为 0 |
| BUILD | **发布分支号**，一个里程碑一条（`refs/branch-heads/<BUILD>`） |
| PATCH | 在该分支**及其子分支**上的递增序号 |

关键在于：上游从发布分支上**再切子分支**（如 `7871_48`、`7871_183`），每条服务一个平台或一次 respin 轨道，各自从分叉点继续递增 PATCH。实测证据：

- `150.0.7871.131` **不是** `150.0.7871.150` 的祖先；`.150` 不是 `.175` 的祖先；`.189` 不是 `.206` 的祖先 —— 这些 tag 不在同一条线上
- tag 日期与编号不单调（`.131` 为 07-15，`.150` 反而是 07-13）
- commit 主题带 `[7871_48]`、`[7871_183]` 等子分支前缀

由此产生两个必须遵守的推论：

1. **仓库里有 tag ≠ 已发布**。大量 tag 是内部构建、其他平台 respin 或从未发布的候选。
2. **各平台发布的 PATCH 号本就不同**（实测 M151：Mac/Win `.76`、Linux `.75`、Android/WebView `.83`、iOS `.105`）。

### 6.2 桌面平台同线（决定了单一 pin 的正确性）

实测 M151 已发布版本序列：

| 平台 | 序列 |
|---|---|
| Mac | `.76` `.75` `.72` `.71` `.47` `.34` |
| Win64 | `.76` `.75` `.72` `.71` `.47` `.34`（**与 Mac 完全一致**） |
| Linux | `.75` `.71`（同序列的**子集**） |

结论：桌面三平台共用同一条发布线，Mac / Windows 拿全量，Linux 只推其中一部分。因此：

- **单一 `CHROMIUM_VERSION` 钉住全部桌面平台是正确的**，无需按平台分别钉。
- Linux 落后不构成问题：钉 `.76` 构建 Linux 完全合法（同一分支源码），只是比 Google 推给 Linux 用户的多带若干修复。

### 6.3 数据源

| 用途 | 源 |
|---|---|
| **程序判断「是否真的发布」** | Chrome VersionHistory API：`https://versionhistory.googleapis.com/v1/chrome/platforms/{mac,win64,linux}/channels/stable/versions`（官方、公开、无需鉴权，只列实际发布版本） |
| 安全定级 | Chrome Releases 博客 Atom feed：`https://chromereleases.googleblog.com/feeds/posts/default`（CVE 列表、严重级别、在野利用措辞） |
| ~~chromium/src tag 列表~~ | **禁止**用于发布判断（理由见 6.1） |

### 6.4 `scripts/check_upstream_release.py`

- 默认查询桌面平台 `["mac", "win64"]`，`linux` 作为参考信息一并输出
- 读 `CHROMIUM_VERSION` 取前三段得到当前发布分支
- 取桌面平台已发布版本的最大值，与当前 pin 比较，输出三选一结论：
  - **同分支有更新 PATCH** → 增量路径（同一检出）
  - **上游已切新 BUILD** → 旧分支停止维护，须走里程碑升级流程（新建检出）
  - 已是最新 → 无操作
- **假设守卫**：若 mac 与 win64 的最新版本不一致，显式告警交人判断（当前假设二者恒同）
- 可选增强：匹配博客 Atom feed，输出该版本 CVE 严重级别与建议响应档位

同时覆盖 Windows 的理由：成本接近零（API 仅差一个路径段），且现在就能校验「Mac/Win 同线」这一假设、一旦上游分叉立刻告警；推迟反而要重写脚本与 runbook。

### 6.5 跟进时机

| 触发 | 判据 | 响应 |
|---|---|---|
| 在野利用 0-day | 博客出现 "exploit … exists in the wild" | 立即跟，hotfix 通道，目标 24–48 小时出包 |
| Critical / High 修复 | 博客 CVE 列表含 Critical 或 High | 计划内跟，目标一周内 |
| 常规刷新 | 仅 Low / Medium 或无安全条目 | 攒到下次例行发版一起带 |
| 里程碑跃迁 | MAJOR 变化 | 走完整升级流程（不跟则再也拿不到安全修复） |

## 7. 迁移机制与工具链

### 7.1 核心流程

全部使用 git 自带能力（`git rebase` 内部的 `merge-ort` 三方合并、`git diff`、`git apply`），无第三方工具。

在新检出的 `src` 下：

```bash
git fetch origin tag 148.0.7778.180          # 确保旧基线对象可达
git checkout -b teleport/overlay-old 148.0.7778.180
python scripts/apply_patches.py               # 应用仓库现有的 M148 版 overlay
git add <精确路径集> && git commit -m "teleport overlay @148"
git rebase --onto 151.0.7922.76 148.0.7778.180
```

`git rebase` 对每个文件做标准三方合并：base = M148 上游文件，ours = M151 上游文件，theirs = 我们改过的版本。上游仅行号漂移或周边变动时**自动合并、零人工**；只有上游改到我们改的同一块才留冲突标记。冲突标记落在真实源码里，具备完整上下文、可编译、可跳转，优于逐个 patch 试 `.rej`。

**为何用 rebase 而非 merge**：`git merge <151 tag>` 的 merge base 会落到 `7778` 发布分支从主干的分叉点（实测 `77f495e`），M148 分支自身的修复也会被卷入合并，噪音大。`rebase --onto` 的 base 精确为 `148.0.7778.180`，参与合并的只有「我们的改动」×「M148→M151 上游 delta」两项，是最小且正确的三方。

### 7.2 两个必须处理的机制陷阱

**陷阱一：`--no-history` 会让整套方案失效。** `sync.py` 当前执行 `gclient sync --revision src@<v> --with_tags --no-history`。浅克隆的新检出**不含 M148 对象**，三方合并没有 base。必须保证旧基线 tag 可达（上述 `git fetch origin tag`，或去掉 `--no-history`）。现有检出是完整历史（1,734,969 commits），说明它并非经由此路径建立，该缺陷一直潜伏未暴露。

**陷阱二：`git add -A` 不可用。** `gclient sync` 后 `src` 下有大量 DEPS 子仓与生成物，虽多数被 `.gitignore` 覆盖但不可赌。改为**精确 add**，路径集完全已知：patches 覆盖的 105 个路径 + branding 覆盖的路径 + 生成物白名单。

### 7.3 `scripts/rebase_overlay.py`

封装 7.1 流程。参数为旧基线 tag 与新基线 tag，负责：fetch 旧 tag、建临时分支、应用 overlay、精确 commit、发起 rebase。冲突时停止并列出冲突文件清单，人工解决后 `git rebase --continue`。

### 7.4 `scripts/export_patches.py`

从 rebase 结果重新导出 patch 文件：对每个已有 patch 对应的上游路径执行 `git diff <新 tag> -- <path>`，写回同名 patch 文件。

**唯一难点是三类改动的分类**，且分类必须带安全阀：

| 类别 | 判定来源 | 处理 |
|---|---|---|
| patch 类 | `patches/**/*.patch` 反推路径（权威来源即 patches 目录本身） | 重新导出 |
| branding 类 | `branding/**` 反推路径 | 不导出（拷贝覆盖机制） |
| 生成物类 | 显式白名单：`chrome/VERSION`、`components/version_info/teleport_engine_version.h`、`branding_strings.py` 改写的 `chromium_strings.grd` 与中文 `.xtb` | 不导出 |

**安全阀**：`git status` 中出现不属于任何一类的改动 → 直接报错退出。否则会静默漏导出，要到下一次 `apply_patches.py` 才发现改动丢失。

导出后必须验证幂等。此处「干净检出」指**将检出工作树重置回钉住的上游 tag**（`git reset --hard 151.0.7922.76` 并清理未跟踪的 overlay 产物），而非新建第三个检出。在该状态下重跑 `apply_patches.py` 须全绿，且二次运行零变化。

### 7.5 现有脚本改动

| 脚本 | 改动 |
|---|---|
| `_lib.py` | `chromium_dir()` 改为从 `CHROMIUM_VERSION` 前三段派生（§5.1），新增 `TELEPORT_CHROMIUM_ROOT` |
| `sync.py` | 无改动 |
| `bootstrap.py` | `build` 链接指向不符时重建，而非抛错 |
| `rebase_overlay.py`（新建） | 保证旧基线 tag 可达（§7.2 陷阱一），见下方偏离说明 |

**与本节早先设计的一处有意偏离**：「保证旧基线 tag 可达」原计划放在 `sync.py`，实现期（Task 5）改放在 `rebase_overlay.py` 的 `ensure_tag()`。理由是这是**发起 rebase 的前置条件，而非 sync 的职责**——`sync.py` 只负责把树同步到 `CHROMIUM_VERSION` 钉住的版本；若把「fetch 一个与当前 pin 无关的历史 tag」塞进 `sync.py`，会模糊它的职责边界，且此后每次安全补丁跟进（`sync.py` 常规运行）都会白跑一次这个无关的 fetch。`ensure_tag()` 的做法——先 `rev-parse --verify` 确认 tag 已可达，不可达才 `git fetch origin tag <tag>`——详见 `scripts/rebase_overlay.py`。此段为 Task 5 落地后回填，原设计文本已按此更新。

## 8. 已知必修清单

### 8.1 Patch 人工重写（2 个）

见 §3.2。

### 8.2 Overlay 源码

`src/browser/enterprise/teleport_voluntary_signin.{h,cc}`，见 §3.3。其余按编译结果迭代修复。

### 8.3 上游构建 / 工具脚本 patch（高风险区）

dry-run 显示文本层可解，但**语义必须逐个复核**：

- `tools/gritsettings/resource_ids.spec` —— 资源 ID 分配，跨里程碑最易冲突；出错表现为 grit 构建报错或运行时资源错乱
- `components/policy/tools/generate_policy_source.py`、`tools/flags/generate_unexpire_flags.py` —— `MAJOR=0` 真值判断坑的修补；上游若重写该逻辑，**必须按同语义重解，禁止盲目接受三方合并结果**
- `tools/metrics/histograms/generate_expired_histograms_array.py`

### 8.4 打包 / 签名链

- `chrome/installer/mac/signing/` 四个 patch：M150 上游未变，M151 需复核
- PGO：两套 profile（Chrome 顶层 + V8 builtins）由新检出 `gclient sync` 经 `checkout_pgo_profiles=True` 拉取；`chrome_pgo_phase=2` 硬依赖二者，缺失导致构建**硬失败而非静默降级**，故 release 构建前显式校验存在
- Sparkle：`fetch_sparkle.py` 在新检出重跑（框架须真实拷贝进检出，符号链接会被 GN 原样拷进 `.app` 导致 dmg 内死链）

### 8.5 版本与 UA

- `CHROMIUM_VERSION` → `151.0.7922.76`
- `components/version_info/teleport_engine_version.h` 由 `apply_patches.py` 自动重生成 → **UA 变为 `Chrome/151.0.0.0`**（UA 恒为引擎版本，产品版本绝不进 UA）
- `TELEPORT_VERSION` → `0.2.0.0`；`assert_baked_version` 要求打包时烘焙版本与之一致

## 9. 验证与完成定义

分层闸门，每道通过才进下一道。

### G0 环境就绪

- 新检出建于 `~/workspace/chromium/151.0.7922`，sync 到 `151.0.7922.76`，`sync.py` 版本校验通过
- 旧基线 tag `148.0.7778.180` 在新检出内可达
- `~/workspace/chromium/148.0.7778` 符号链接指向 `<repo>/chromium` 已建立
- **用实际钉住的版本重跑 patch dry-run**，复核 §3.1 冲突清单

### G1 Patch 迁移完成

- rebase 无残留冲突
- `export_patches.py` 导出后，检出重置回 `151.0.7922.76` 再重放 `apply_patches.py` 全绿且幂等（二次运行零变化，定义见 §7.4）
- 分类安全阀报告「无未归类改动」
- `gen_policy_verification_key.py --check` 通过

### G2 编译绿

- 先单独编 `//teleport` 目标，快速暴露 API 漂移
- 再编全量 `chrome`
- `teleport_unittests` 目标可编

本闸门为**迭代闸门**，预期多轮修复。

### G3 单测绿

- `teleport_unittests` 全绿
- **被 patch 的上游单测必须真跑**（不能只看编译通过）：`user_agent_utils_unittest`、`http_network_transaction_unittest`、`network_service_proxy_delegate_unittest`、`browser_dm_token_storage_mac_unittest`，分布在 `unit_tests` / `net_unittests` / `services_unittests`，按 filter 点名执行
- `uv run pytest` 全绿（含新增脚本的测试）

### G4 GUI 冒烟（活体，dev 渠道）

在 `scripts/smoke_check.md` 基础上，本次特有项：

- `chrome://version` 显示产品版本 `0.2.0.0`，不泄漏 Chromium 版本号；UA 为 `Chrome/151.0.0.0`
- 启动 banner、品牌名、图标
- `teleport://` scheme 别名
- **About 页**（版本展示 / 检查更新 / 页脚链接）—— patch 被重写过，重点验证
- **`chrome://policy` 状态框**品牌化 —— patch 被重写过，重点验证
- 纳管全链路：自愿纳管入口 → enroll 页 → OIDC → 策略生效（对端运行 fairyland device-manager）
- 隧道（Track T）转发行为
- `--simulate-critical-update` 点亮升级角标

### G5 出包（完成定义终点）

- release PGO 构建通过
- `fetch_sparkle.py` 已在新检出执行
- `package.py --channel canary` 出包成功（签名 + 公证 + 样式 dmg）
- `assert_baked_version` 与 `TELEPORT_VERSION = 0.2.0.0` 一致
- **不加 `--distribute`**

### 测试策略

新增脚本按项目约定属工具脚本（「不强求 TDD，仅在有价值处务实地写 pytest」）。此处有价值的是 **`export_patches.py` 的三类分类逻辑与安全阀**——它是最易产生静默错误之处（漏导出即丢改动，且要到下次 apply 才暴露），必须有测试覆盖。`rebase_overlay.py` 的编排依赖真实 git 状态，不强求测试。

`check_upstream_release.py` 的版本比较与分支判定逻辑为纯函数，应有测试；网络请求部分不测。

## 10. 风险与回退

| 风险 | 缓解 |
|---|---|
| **36 个变动头文件潜藏的编译错误规模不可预估**（本次最大不确定性） | G2 设计为迭代闸门；先编 `//teleport` 单目标快速暴露，再编全量 |
| Lit 迁移的 2 个 patch 重写后行为不等价 | G4 将 About 页与 `chrome://policy` 单列为重点验证项 |
| `resource_ids.spec` 语义冲突导致资源 ID 碰撞 | 表现为 grit 构建报错或运行时资源错乱，由 G2 / G4 覆盖 |
| `MAJOR=0` 相关脚本 patch 的上游逻辑被重写 | 按同语义重解，禁止盲目接受三方合并结果；TD-015 已登记残余暴露面 |
| PGO profile 缺失导致 release 构建硬失败 | G5 前置显式校验两套 profile 存在 |
| 新检出 sync 耗时受网络影响 | G0 可与后续准备工作并行 |

**回退**：旧检出 `<repo>/chromium`（M148，构建缓存完整）原地保留，任何阶段可切回构建并发布 M148 包；分支合并前 `main` 不受影响。回退动作为 `CHROMIUM_VERSION` 改回 `148.0.7778.180`、`TELEPORT_VERSION` 改回 `0.1.12.0`，派生路径经 §5.2 的符号链接自动指向旧检出。

## 11. 文档与后续

### 11.1 新增

`docs/chromium-upgrade-runbook.md`（简体中文）：里程碑升级与安全补丁跟进两条路径的完整步骤。

### 11.2 更新 `CLAUDE.md`

- `CHROMIUM_VERSION` → `151.0.7922.76`
- 检出布局约定（`~/workspace/chromium/<MAJOR.MINOR.BUILD>`，路径由版本派生）
- 三个新脚本进入「仓库布局」与「构建与测试命令」章节
- 「patch 的创建 / 刷新 / 冲突处理工具链」从「待定 / 后续 phase」移出
- 修正已过时的 gotcha：`--disable-field-trial-config` 已是 no-op（构建期 GN arg `disable_fieldtrial_testing_config=true` 已关闭），文档仍写着需要传
- 新增 gotcha：仓库 tag ≠ 已发布；桌面 Mac / Win 同线、Linux 取子集

### 11.3 更新 `docs/tech-debt.md`

- TD-016 现状修订：不同基线的 worktree 已由路径派生天然隔离，**同基线 worktree 之间的共享检出污染仍然存在**，该条目不可关闭
- 若 patch 重解产生语义降级，登记新条目

### 11.4 后续（不在本 spec 范围）

- 2026-08-25 M152 上线后的小步跃迁，复用本次工具链
- `check_upstream_release.py` 接入 CI 定时任务
- fairyland 侧 vendored proto re-vendor 到新基线（非阻断）
- Windows / Linux 构建
