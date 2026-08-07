# Chromium 基线升级 Runbook

> 本文档的对象是**几周/几个月后做下一次升级、且没有本次会话上下文的人**。所有命令按本次(M148 148.0.7778.180 → M151 151.0.7922.76)实际验证过的顺序记录;凡未在本次实际跑过的步骤(主要是路径 A 的具体命令),会明确标注「未在本次验证,按脚本设计给出」。
>
> 背景与决策依据见 `docs/superpowers/specs/2026-08-06-chromium-milestone-upgrade-design.md`(设计);过程与踩坑的第一手记录见执行计划 `docs/superpowers/plans/2026-08-06-chromium-milestone-upgrade.md` 与 SDD 台账 `.superpowers/sdd/2026-08-06-chromium-milestone-upgrade/progress.md`。

## 0. 判定入口:先跑一个脚本,再决定走哪条路径

```bash
uv run python scripts/check_upstream_release.py
```

这个脚本查的是 Chrome VersionHistory API(`https://versionhistory.googleapis.com/v1/chrome/platforms/{mac,win64,linux}/channels/stable/versions`)—— 只列**真正发布过**的版本。它比对 `CHROMIUM_VERSION` 与桌面平台(mac、win64)已发布的最新版本,给出三选一结论:

- **已是最新** → 无操作。
- **同发布分支有更新 PATCH**(如 `.76 → .132`)→ 走**路径 A:安全补丁跟进**。
- **上游已切到新发布分支**(`MAJOR` 或 `BUILD` 变了)→ 走**路径 B:里程碑升级**。

脚本还会告警两种需要人判断的情况:mac 与 win64 报告的最新版本不一致(「桌面同线」假设被打破),或某个桌面平台完全没拿到数据(结论只基于单一平台,尚未真正比对过)。**不要用 `chromium/src` 的 tag 列表做这个判断**——见 §5 「上游 tag ≠ 已发布」。

严重度不在这个 API 里,查 Chrome Releases 博客 Atom feed(`https://chromereleases.googleblog.com/feeds/posts/default`)确认 CVE 等级与「在野利用」措辞,再决定响应节奏(见下表)。

### 跟进时机表

| 触发 | 判据 | 响应 |
|---|---|---|
| 在野利用 0-day | 博客出现 "exploit … exists in the wild" | 立即跟,hotfix 通道,目标 24–48 小时出包 |
| Critical / High 修复 | 博客 CVE 列表含 Critical 或 High | 计划内跟,目标一周内 |
| 常规刷新 | 仅 Low / Medium 或无安全条目 | 攒到下次例行发版一起带 |
| 里程碑跃迁 | `check_upstream_release.py` 报 "Upstream moved to a new release branch" | 走路径 B(不跟则再也拿不到该分支的安全修复) |

---

## 路径 A:安全补丁跟进(同一发布分支,复用检出)

同一 `MAJOR.MINOR.BUILD` 内的 PATCH 移动(如 `.76 → .132`),DEPS 基本不动、构建缓存基本全热,复用现有检出即可,**不新建**。

> 本次会话走的是路径 B,以下命令未在本次实际执行过;按脚本设计与 CLAUDE.md 既有工作流给出,与路径 B 中已验证的 `sync.py` / `apply_patches.py` 行为一致。

```bash
unset TELEPORT_CHROMIUM_DIR                      # 见 §5 环境变量陷阱

# 1. 改版本 pin(只改 PATCH,MAJOR.MINOR.BUILD 不变 → 检出目录不变)
printf '151.0.7922.132\n' > CHROMIUM_VERSION

# 2. 同步到新 PATCH(复用同一检出,DEPS 增量拉取)
uv run python scripts/sync.py

# 3. 重新应用 overlay(幂等;patch 若与新 PATCH 冲突会在此处报错,极少见——同分支内上游只发安全修复,不做结构重构)
uv run python scripts/apply_patches.py

# 4. 增量构建(远快于全新检出的全量构建)
cd "$(uv run python -c 'import sys; sys.path.insert(0,"scripts"); from _lib import chromium_src; print(chromium_src())')/.."/src 2>/dev/null || true
# 或直接:cd <chromium_root>/<release_branch>/src
autoninja -C out/mac/arm64/dev chrome
autoninja -C out/mac/arm64/dev teleport_unittests

# 5. 单测(见 §4 的三个假绿陷阱,同样适用于路径 A)
./out/mac/arm64/dev/teleport_unittests
cd /path/to/teleport/repo && uv run pytest

# 6. 出包(dev 验证或直接走 canary/release)
uv run python scripts/package.py --channel canary
```

路径 A 唯一需要警惕的:如果 `check_upstream_release.py` 报的其实是里程碑跃迁而误当成路径 A 处理,`sync.py` 会在版本校验环节直接失败(`chrome/VERSION` 与 `CHROMIUM_VERSION` 的 `MAJOR.MINOR.BUILD` 不一致),不会静默出错。

---

## 路径 B:里程碑升级(新检出 + 完整 rebase)

`MAJOR` 或 `BUILD` 变化意味着上游**换了一条发布分支**,旧分支停止接收修复。检出目录按发布分支派生(`$TELEPORT_CHROMIUM_ROOT/<MAJOR.MINOR.BUILD>`,见 §5),换分支自动落到新目录,旧检出原地不动。

### B0. 新建检出:`git clone --local` 硬链接技巧(省掉 66 GB 重复下载)

Chromium 的 `src` 仓库本身(不含 DEPS 第三方子仓)打包对象约 **66–68 GB**(本次实测:M148 检出 `git count-objects -v` 报 `size-pack: 68662550` KiB ≈ 65.5 GB)。如果新检出走 `gclient sync` 从零开始拉,这 66 GB 要从 `chromium.googlesource.com` 完整重新下载一遍——纯粹的网络与时间浪费,因为新旧基线绝大部分历史是共享的。

**做法:先用本地硬链接 clone 把 `src` 的 git 对象库"复制"过去,再让 gclient 接手做 DEPS 与工作树同步。**

```bash
unset TELEPORT_CHROMIUM_DIR                                                          # 见 §5 环境变量陷阱
export TELEPORT_CHROMIUM_ROOT="${TELEPORT_CHROMIUM_ROOT:-$HOME/workspace/chromium}"  # 显式建立,下面命令按字面展开这个变量才不会踩空(见 §5)

mkdir -p "$TELEPORT_CHROMIUM_ROOT"/151.0.7922      # 按新发布分支号建目录
git clone --local /path/to/old-checkout/src \
                  "$TELEPORT_CHROMIUM_ROOT"/151.0.7922/src

cd "$TELEPORT_CHROMIUM_ROOT"/151.0.7922/src
git fetch origin tag 151.0.7922.76                 # 拉新基线 tag 及其增量对象(只这一部分走网络)
git checkout 151.0.7922.76

# 之后正常走项目的 gclient 编排:
cd "$TELEPORT_CHROMIUM_ROOT"/151.0.7922
# 在此目录写 .gclient(bootstrap.py 的 ensure_gclient 会做这件事,幂等)
uv run python scripts/bootstrap.py           # 会调用 sync.py 做 gclient sync(DEPS 子仓、PGO profile 等)
```

**为什么这样做是安全的**:

- Git 对象(pack 里的每个 blob/tree/commit)是**内容寻址、不可变**的——一旦写入就不会被原地修改;`git gc`/`git repack` 只会**新建**打包文件,旧文件被替换前不会被就地改写。因此对同一份对象文件建硬链接,两个检出各自读写互不干扰,不存在"改一边另一边跟着坏"的风险。
- `git clone --local`(默认模式,未加 `--shared`)是**独立**的克隆——它给新仓库建自己的完整 `.git`(自己的 refs、HEAD、config),硬链接只是省了物理拷贝这一步。这与 `--shared`/alternates 模式不同:alternates 让新仓库长期依赖源仓库的 objects 目录存在,源仓库后续被 `prune`/删除会直接打穿新仓库;硬链接 clone 没有这个长期依赖,源检出可以照常继续被使用、gc、甚至(将来)删除,不影响新检出。
- **本次已实测验证**:比对新旧检出的 pack 文件,文件名相同的几个 pack **inode 号完全一致**(如 `pack-3b8430ad….pack` 在两个检出里都是 inode `3846408`),证明确实是硬链接而非重新下载;新检出额外多出一个 pack(仅含 M148→M151 增量提交的新对象),这部分才是本次真正走网络拉取的内容。

**这一步与陷阱一(见 §5)的关系**:项目的 `sync.py` 默认执行 `gclient sync --revision src@<v> --with_tags --no-history`。如果让 `bootstrap.py`/`sync.py` **从零**创建检出(即 `src/.git` 尚不存在),`--no-history` 会做浅克隆,新检出压根不含 M148 的对象,后面 `rebase_overlay.py` 的三方合并直接没有 base 可用。**先用 `git clone --local` 把完整历史(含旧基线 tag)灌好,`src/.git` 已经存在且历史完整之后,再走 `gclient sync` 的 `--no-history` 就不再触发浅克隆行为**(它只影响"从无到有"的初始拉取,不会截断一个已有完整历史的仓库)。这正是本次新检出最终验证为「完整历史(1,734,969 commits)」、旧基线 tag 全程可达的原因。

**磁盘账**:新检出源码 + DEPS 约 110 GB,dev + release 两套构建输出另计;旧检出(含 161 GB 构建缓存)原样保留。峰值约 500–600 GB,升级前确认磁盘余量。

### G0. 环境就绪

```bash
unset TELEPORT_CHROMIUM_DIR        # 见 §5——这是本次会话每个新 shell 的第一条命令,不是可选项
export TELEPORT_CHROMIUM_ROOT="${TELEPORT_CHROMIUM_ROOT:-$HOME/workspace/chromium}"  # 同样是每个新 shell 都要建立,后面命令按字面展开(见 §5)

uv run python scripts/bootstrap.py --skip-sync     # 建链接:<checkout>/src/teleport -> <repo>/src、<repo>/build -> <checkout>/src/out
```

验证清单(全部应能直接核实,不放过任何一项):

- `chrome/VERSION` 精确等于 `CHROMIUM_VERSION` 的四段
- 两套 PGO profile 都在(`chrome/build/pgo_profiles/*.profdata` 与 `v8/tools/builtins-pgo/profiles/x64.profile`)——release 构建硬依赖,缺则构建期硬失败
- 旧基线 tag 与新基线 tag 都能 `git rev-parse --verify refs/tags/<tag>` 解出
- `<repo>/build` 与 `<checkout>/src/teleport` 两个链接方向正确(`build` 指进检出,不可反向;见 §5)
- **用实际钉住的版本重跑一次 patch dry-run**,不要用别的 PATCH 号的历史数据替代:

```bash
cd "$TELEPORT_CHROMIUM_ROOT"/<release_branch>/src
export GIT_INDEX_FILE=/tmp/idx_dryrun
git read-tree <onto-tag>
for p in $(find /path/to/teleport/repo/patches -name '*.patch' | sort); do
  if git apply --cached --check "$p" 2>/dev/null; then echo "CLEAN $p"
  elif git apply --cached --check --3way "$p" 2>/dev/null; then echo "3WAY $p"
  else echo "CONFLICT $p"; fi
done
unset GIT_INDEX_FILE
```

**这个 dry-run 只用于摸个大致底,不能当作 rebase 冲突量的预测——见 §5「dry-run 与 rebase 是两种不同粒度的探测」。**

### G1. Patch 迁移:`rebase_overlay.py` + 解冲突 + `export_patches.py`

```bash
uv run python scripts/rebase_overlay.py --from-tag 148.0.7778.180 --onto-tag 151.0.7922.76
```

这个脚本做的事(封装了 §7.1 的完整流程,细节见脚本内的 docstring):

1. 检查检出干净(允许 `bootstrap.py` 自己植入的 `teleport` 符号链接与 `fetch_sparkle.py` 植入的 Sparkle 拷贝这两类"注入产物",其余任何未提交改动都拒绝执行)。
2. 确保旧基线 tag 可达(不可达则 `git fetch origin tag <old-tag>`)。
3. `git checkout -B teleport/overlay-rebase <old-tag>`,以 `--skip-branding` 跑一次 `apply_patches.py`(**`--skip-branding` 是硬性要求,不是可选优化**——`branding_strings.py` 会重写约 60 个 grd/grdp/xtb 路径,其中 3 个同时也是手写 patch 的目标;如果不跳过,重导出时会把品牌重写的内容一起烤进 patch 文件,下一次 `apply_patches.py` 就会对着一个已经改过名的 grd 再改一遍,`transform_en_grd` 的幂等性会让 id 重映射算出空结果,对应的中文 `.xtb` 静默失去重键,退回英文)。
4. 精确 `git add` 上述路径集(patch 覆盖的路径 ∪ branding 覆盖的路径 ∪ 版本生成物白名单),`git commit`。
5. `git rebase --onto <new-tag> <old-tag>`。

冲突时脚本会打印冲突文件清单并退出码 2,提示接下来跑 `export_patches.py` 的确切命令。冲突落在真实源码里(带完整上下文、可编译、可跳转),不是逐个 patch 试 `.rej`。解决方式:

- **纯上下文漂移**(行号变了、周边代码重排)→ 自动合并,不会出现在冲突列表里。
- **目标文件被上游删除/重命名**(如本次 Lit 迁移把 `.html` 拆成 `.html.ts` + `.ts` + `.css`)→ 这不是文本合并,是"重新表达同一个意图"的工作:先用 `git log --follow --diff-filter=D` 找到删除提交,确认替代文件是什么形态,再对着新形态重写等价改动;逐条列出原 patch 的每一个 hunk 意图,确认新 patch 一一对应,不要漏、不要顺手夹带无关清理。
- **上游对同一处做了结构性重构**(如本次 `static_library("browser")` → `source_set("browser")` 拆分)→ 需要判断改动该落在新结构的哪个位置,记录选了什么、否决了什么,以及为什么。
- **枚举值/资源 ID 撞车**(如本次 `ProfileManagementFlowController::Step` 新增值与我们的自定义值重号)→ 换成上游未占用的值(**建议选一个远高于当前上游最大值的预留值**,减少下次升级再撞车的概率;本次改成 12,已知 M152 大概率再撞,教训见 §5)。
- **上游脚本改了真值判断逻辑**(如 `MAJOR=0` 相关的两个 codegen patch)→ **禁止盲目接受三方合并结果**,必须逐条按原语义重新核对,自动合并成功不代表语义仍然正确。

冲突全部解决、`git rebase --continue` 到底之后:

```bash
uv run python scripts/export_patches.py --tag 151.0.7922.76
```

`export_patches.py` 把每个 patch 目标路径的 `git diff <new-tag> -- <path>` 重新写回 `patches/<path>.patch`,并对**所有**改动路径做三分类校验(patch / branding / 生成物 / 注入产物,详见脚本 docstring),分类不到的一律硬报错拒绝导出——这是防止某处改动被静默漏导出的安全阀,不能放宽。

导出后必须验证幂等,**不要用 `git clean -fdx`**(见 §5):

```bash
git checkout -q -f <new-tag>
rm -f components/version_info/teleport_engine_version.h   # 生成物,checkout 不会清
git status --porcelain -- . | grep -v '^?? teleport$'     # 应为空(排除 bootstrap 植入的符号链接)

# 连跑三次,工作树 diff 的 SHA-256 必须完全一致,变化数收敛到 0
uv run python scripts/apply_patches.py   # x3
```

`git add -A` **在同步过的树上不可用**——`gclient sync` 后 `src` 下有大量 DEPS 子仓与生成物,虽多数被 `.gitignore` 覆盖但不可赌;`tracked_overlay_paths()` 用的是精确路径集(patch 覆盖的路径 ∪ branding 覆盖的路径 ∪ 版本生成物白名单),不是通配。

顺带检查:`branding/` 下的整文件覆盖如果对应的上游路径被改名(本次是 3 个图标文件 `*.icon → *_old.icon` 的重命名),`export_patches.py` 的安全阀会报「未分类改动」——逐一 diff 确认新旧文件内容逐字节相同后,`git mv` 到新路径即可,**不要放宽安全阀**去绕过这个检查。

### G2. 编译到绿

```bash
cd "$TELEPORT_CHROMIUM_ROOT"/<release_branch>/src

# 先编 //teleport 单目标,快速暴露 overlay 自身对上游 API 的漂移(比全量快得多)
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport

# 再编全量 chrome
autoninja -C out/mac/arm64/dev chrome
autoninja -C out/mac/arm64/dev teleport_unittests
```

这是**迭代闸门**,预期多轮修复。修复原则(照搬 CLAUDE.md 既有工作流):

- overlay 自有源码(`src/**`)直接改,不影响任何 patch。
- **patch 打进去的上游代码**:直接编辑检出里的文件,改完用 `git -C <checkout>/src diff <new-tag> -- <path> > patches/<path>.patch` 重新生成对应 patch 文件——**禁止手改 `.patch` 文件本身**。
- **三个例外路径**,重生成前必须确认检出树是用 `apply_patches.py --skip-branding` 建的(普通 `apply_patches.py` 会先应用这份手写 patch、再跑品牌重写,`git diff` 出来的内容会把品牌重写一起烤进 patch,下一次正常运行 `apply_patches.py` 就会对着已改名的 grd 再重写一次,`transform_en_grd` 幂等导致 id 重映射算出空结果,对应 zh-CN/zh-TW `.xtb` 静默失去重键退回英文——即 `export_patches.py` 的 `branding_pass_has_run()` 安全阀专门要挡的那类问题;这里是手工路径,没有脚本化安全阀,只能靠遵守这条规则):
  - `chrome/app/generated_resources.grd`
  - `chrome/app/resources/generated_resources_zh-CN.xtb`
  - `chrome/app/settings_strings.grdp`
- 每修好一个独立问题就提交一次,不要攒成一个大提交,方便回溯每处改动对应的具体错误。

**规模参考(本次实测,写入 §6 作为下次的预期基准)**:overlay 引用了 36 个在 M148→M150 之间已发生变动的上游头文件,这是升级前能预估的**不确定性上限**,不是实际损伤——本次首次全量构建跑到 31165/34680 个编译步骤时只停在**一个**失败步骤;overlay 源码层面的真实破损是**两个文件**(`src/browser/enterprise/teleport_voluntary_signin.{h,cc}`,跟随 `chrome::FindBrowserWithTab` 迁移到 `GlobalBrowserCollection` 的 API 改名)。另外两处失败是上游自身的问题,不是 overlay 头文件漂移导致,按上面「patch 打进去的上游代码」的方式各修一个:

- `media/formats/dts/dts_util.cc` 缺 `<array>` include——上游 C++20 header-modules 迁移漏迁了一个 macOS 从不构建(默认 `enable_platform_dts_audio=false`)的文件,但本项目的 `dev.mac.gn`/`release.mac.gn` 都显式把这个开关打开(继承 M148 的 DTS 解封装能力),于是踩中了上游这个只有我们会触发的漏洞。**处置方式是补一个 patch 加上缺失的 include,而不是把 GN 开关关掉**——关掉开关虽然能让编译过,但会静默丢掉 M148 就有的 DTS 解封装能力,违反「基线升级必须保持行为不变」的原则。
- M151 把 `ProfilePickerToolbar::SetNativeToolbarVisible` 拆成了三个按钮粒度的独立 setter,需要把纳管步骤原来调用的旧接口重新映射到正确的新 setter(`SetNativeToolbarSigninButtonsVisible`)——**这里存在一个容易选错的陷阱**:这个 setter 名字具有误导性,它会把返回按钮(Back button)和"不登录"按钮一起隐藏;如果因为"我们是 GAIA-free 场景不需要登录按钮"就避开它,会连返回按钮也一起隐藏,把用户困在纳管步骤里出不去。判断依据:上游同级的其它步骤调用的是同一个 setter、`CHECK(sign_in_back_button_)` 证明返回按钮总是存在、"不登录"按钮那一半本身有空指针保护——编译能过不代表这里选对了,**这类"编译只能证明符号存在,不能证明选对了正确的调用"的情况必须留给 G4 GUI 冒烟去验证**,不能在编译通过后就当作已解决。

### G3. 单测绿——三个「假绿」陷阱,务必照单核对

`teleport_unittests` 本身没有陷阱,正常跑:

```bash
autoninja -C out/mac/arm64/dev teleport_unittests && ./out/mac/arm64/dev/teleport_unittests
```

**被 patch 覆盖的上游单测则不同——本次会话原计划里给的三条 filter 命令,有两条产生了「假绿」(退出码 0、打印 SUCCESS,但实际执行的用例数是 0 或与预期完全无关)。记住这条规则:任何 filter 在写进文档或脚本之前,必须先用 `--gtest_list_tests` 核对它真的匹配到了预期的用例,再核对实际执行的用例数,绝不能只看退出码。**

三个真实案例(全部本次实测):

1. **`unit_tests --gtest_filter='*UserAgent*'`**——这条命令确实跑出了绿色结果,但匹配到的全是名字里偶然带 "UserAgent" 字样、与我们的补丁毫无关系的用例(如 `GetUserPopulationForProfileTest.PopulatesUserAgent`)。我们真正要验证的 `UserAgentUtilsTest` 其实**不在 `unit_tests` 里**——它测的文件在 `components/` 下,属于 `components_unittests` 二进制。
2. **`net_unittests --gtest_filter='HttpNetworkTransactionTest.*'`**——这条命令匹配**零个**用例:该测试套件用 `INSTANTIATE_TEST_SUITE_P(All, HttpNetworkTransactionTest, ...)` 参数化,gtest 里的真实用例名带 `All/` 前缀(`All/HttpNetworkTransactionTest.<TestName>/<index>`)。裸的 `HttpNetworkTransactionTest.*` 匹配不到任何东西,gtest 打印 "No matching tests to run",紧接着打印 "SUCCESS: all tests passed",退出码 0——**零测试执行,却是一条看起来完全正常的绿色输出**。
3. **`components_unittests`(无参数直接跑)**——这个二进制的启动器(`base::TestLauncher`)在预检阶段会因为两个与我们无关的、上游遗留的未实例化参数化套件(`UninstantiatedParameterizedTestSuite<AutofillMergeTest>`、`<HeuristicClassificationTests>`)直接 abort 整个进程,**跑不出任何一个测试**。必须加 `--single-process-tests` 绕过这个预检,加了之后套件才能正常跑。

**三条里两条静默假绿,这不是巧合,而是同一类风险的三次命中:一个测试命令"看起来对"(文件名匹配套件名的直觉、退出码 0)和它"实际验证了什么"是两件独立的事,只能靠 `--gtest_list_tests` 加实际执行计数核实,不能靠经验或直觉。**

本次最终验证过、可以直接照抄的命令(带来源说明,方便下次升级按同样方法定位新的正确命令,而不是照抄这份可能已经过时的文本):

```bash
cd "$TELEPORT_CHROMIUM_ROOT"/<release_branch>/src
autoninja -C out/mac/arm64/dev unit_tests net_unittests services_unittests components_unittests

./out/mac/arm64/dev/unit_tests --gtest_filter='*BrowserDMTokenStorageMac*'
# 5/5 —— patches/chrome/browser/policy/browser_dm_token_storage_mac_unittest.cc.patch

./out/mac/arm64/dev/services_unittests --gtest_filter='*NetworkServiceProxyDelegate*'
# 3/3 —— patches/services/network/network_service_proxy_delegate_unittest.cc.patch

./out/mac/arm64/dev/net_unittests --gtest_filter='All/HttpNetworkTransactionTest.ForwardProxy*'
# 12/12(4 个参数化用例 x 3 组实例化)—— patches/net/http/http_network_transaction_unittest.cc.patch,
# Track T 转发代理请求头注入

./out/mac/arm64/dev/components_unittests --gtest_filter='UserAgentUtilsTest.*' --single-process-tests
# 23/23 —— patches/components/embedder_support/user_agent_utils_unittest.cc.patch
# --single-process-tests 是必需项,不是可选优化,见上面陷阱 3
```

跑 `net_unittests`/`unit_tests` 等**完整**上游套件(而非只跑我们的补丁覆盖 filter)时,还会撞到 §5 的「out 目录深度陷阱」——凡是加载源码树测试数据的上游用例都会失败,与本次升级无关,是这套项目 out 目录布局的固有问题,处置办法见 §5。

最后照常跑工具脚本自身的单测:

```bash
cd /path/to/teleport/repo && uv run pytest
```

### G4. GUI 冒烟(活体,dev 渠道)

在 `scripts/smoke_check.md` 既有清单基础上,里程碑升级的重点补充项:

- `chrome://version` 显示的产品版本正确、不泄漏 Chromium 版本号,UA 变为新引擎版本(如 `Chrome/151.0.0.0`)
- **凡是本次因为 Lit 迁移被重写过的 patch,必须重点人工验证**——编译通过只证明代码能跑,不证明改造后的行为与迁移前等价(本次是 About 页与 `chrome://policy` 状态框)
- **凡是编译期只证明了"符号存在"、行为选择靠人工判断的改动,必须重点人工验证**(本次是纳管步骤里的 picker 返回按钮,见 G2 的说明)
- zh-TW 等非主力语言的本地化字符串要抽查显示的是产品名而不是静默回退到英文——这是「品牌 id 重映射空跑」的典型静默症状(见 TD-016 关联的 export/branding 安全阀设计初衷)
- 纳管全链路(自愿登录入口 → enroll 页 → OIDC → 策略生效)需要对端跑 fairyland 服务端(`fairyland-test` 走 k3s 部署,不是 `docker.lima`——fairyland 已从 docker 迁移到 k3s,如果 CLAUDE.md/文档写的还是 docker 路径,以 fairyland 仓当前实际部署方式为准)
- 隧道(Track T)转发代理行为、`--simulate-critical-update` 升级角标点亮

**本次会话的诚实状态:G4 是 PARTIAL,不是 PASS。** 自动化能核实的部分(UA 引擎版本正确、纳管后端可达)已核实;**GUI 逐项点击验证被 macOS keychain 弹窗阻塞**——每次用全新 `--user-data-dir` 启动 headless 浏览器都会触发 Safe Storage keychain 访问弹窗(patch 过的 `keychain_password_mac.mm` 路径),必须人工点「允许」才能继续,自动化跑不下去。剩余项(About 页、`chrome://policy` 状态框、picker 返回按钮、zh-TW 显示、启动 banner/品牌、纳管端到端、升级角标等)按用户指示推迟给人工点击验证完成,**不得在完成前把 G4 报告为 PASS**。

冒烟结果按惯例写入 `scripts/smoke_check.md` 的新章节。

### G5. release 构建与出包

```bash
unset TELEPORT_CHROMIUM_DIR                                                          # 见 §5——新 shell(例如签名/公证需要人工在场,常与 G0-G4 不在同一 shell)先确认
export TELEPORT_CHROMIUM_ROOT="${TELEPORT_CHROMIUM_ROOT:-$HOME/workspace/chromium}"  # 同上,下面命令按字面展开

cd /path/to/teleport/repo
uv run python scripts/fetch_sparkle.py       # 必须在 release 构建之前跑,见下面的顺序说明

cd "$TELEPORT_CHROMIUM_ROOT"/<release_branch>/src
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn")'
autoninja -C out/mac/arm64/release chrome chrome/installer/mac   # 两个 target 都要——见下面「打包需要 chrome/installer/mac」

cd /path/to/teleport/repo
uv run python scripts/package.py --channel canary   # 不加 --distribute
```

**`fetch_sparkle.py` 必须在 release 构建之前跑,不是之后。** `release.mac.gn` 打开 `teleport_enable_updater`,Sparkle 框架是**链接期依赖**;如果构建先跑、`fetch_sparkle.py` 后跑,链接阶段直接失败,而不是产出一个能用的二进制再补链接。本次计划的原始步骤顺序反了,是实际执行时才发现并纠正的。

**打包需要 `chrome/installer/mac`,不只是 `chrome`。** `scripts/_build.py` 里 canary 渠道的 `targets = ("chrome", "chrome/installer/mac")`——后者才产出 `Teleport Packaging` 目录(内含 `sign_chrome.py`/`build_props_config.py`,`_package.py:sign_app()` 的入口)。手动 `autoninja` 时如果只编了 `chrome`,`package.py` 会在 `stage_channel_icons` 一步因为这个目录不存在而失败,且**这个 out 目录事后再也无法单独补编 `chrome/installer/mac`**——见下面 TD-026 段落,任何新 target 的 `gn gen` 重新解析都会重新命中 KMS 断言。用 `uv run python scripts/package.py --channel canary`(不加 `--skip-build`)走全自动路径,`_build.build()` 自动传两个 target,不会漏。

**已知的、与本次升级无关的预置阻断项——不要在没确认前提的情况下尝试绕过它:**

`gn gen` 对 release 配置会命中一个**故意设计的 fail-closed 断言**(`src/teleport.gni:34-36`):`teleport_use_release_endpoints=true` 要求 `teleport_release_policy_key_is_real=true`,而生产 KMS 根密钥**按设计从不入库**。这不是本次升级引入的问题——`main` 分支的 `src/gn/args/release.mac.gn` 与本分支在这个文件上**零差异**,该断言随 commit `1adc884`(纳管强制锁 Layer 1 特性)一起落地,而检出里最后一次成功的 release 产物早于这次提交。**结论:自那次提交合入以来,`main` 上就没有能构建出正式 release 的能力,只是因为期间没有发过版所以没人注意到。**

处置方式(本次做法,供参考):**没有**设置 `teleport_release_policy_key_is_real=true`——那样做等于烤进一把占位密钥,恰好是这道防线存在的目的要阻止的事。改为在 `gn gen` 的 `--args` 里额外加一行覆盖(不改动已提交的 `release.mac.gn` 文件本身),只把 `teleport_use_release_endpoints` 设为 `false`,以验证本次升级需要证明的部分——PGO、Sparkle 链接、签名、公证、dmg 出包在 M151 上依然工作:

```bash
gn gen out/mac/arm64/release --args='import("//teleport/gn/args/release.mac.gn") teleport_use_release_endpoints=false'
```

**这样产出的 .app/dmg 不是可发布的 canary 包**(内置的是 dev 端点),**绝不能当作正式产物报告**。生产 KMS 密钥问题本身超出一次基线升级的范围,已登记为 `docs/tech-debt.md` 的独立条目,需要走密钥管理的正常流程解决,不属于升级 runbook 能处理的事。

**这个 override 会在 `<out>/args.gn` 里留下文字痕迹,`assert_release_endpoints_consistent`(`scripts/_build.py`)据此把关,但只在真正 `--distribute` 时才拦下来。** 该函数按**发布意图**(是否传了 `--distribute`)而不是按渠道是否"可发布"来决定行为:
- `--distribute` + `args.gn` 里的显式 override 与渠道模板不一致 → **硬失败**(`SystemExit`,不可绕过、不可用改参数的方式强行通过)——这是这道闸门存在的全部意义,任何时候都不能弱化。
- 不带 `--distribute`(例如上面这条本条 G5 用来验证机制的 `package.py --channel canary`,或 `--skip-build` 组合——`--skip-build` 本身已经硬拒绝和 `--distribute` 同时出现,见 `scripts/package.py`)+ 同样的 override 不一致 → 只打印一条具名 `WARNING`(点出具体的 override 值、期望值,并声明产物不可发布),然后正常继续——这正是本条 G5 用来验证签名/公证/dmg 机制、但产物本身不可发布的合法场景。

也就是说,**先用上面的 override 跑 `gn gen`(留下痕迹),再跑不带 `--distribute` 的 `package.py --channel canary` 做机制验证,是被允许的**——`assert_release_endpoints_consistent` 会打印警告但不会拦截;真正会被拦截的只有紧接着再跑一次 `--distribute` 这一动作本身。

验证产物:

```bash
ls -lh "$TELEPORT_CHROMIUM_ROOT"/<release_branch>/src/out/mac/arm64/release/*.dmg
codesign -dv --verbose=4 <签名后的 .app 路径> 2>&1 | grep -E 'Identifier|TeamIdentifier|Timestamp'
spctl -a -vv <签名后的 .app 路径>
xcrun stapler validate <dmg 路径>
```

---

## 踩过的坑(汇总速查)

### `gclient sync --no-history` 会让三方合并失去 base

`sync.py` 默认执行 `gclient sync --revision src@<v> --with_tags --no-history`。这对**复用同一检出**的路径 A 完全没问题——同分支内的增量同步不需要历史。但对路径 B 的**新检出**,如果放任 `bootstrap.py`/`sync.py` 从零开始建这个检出,`--no-history` 会做浅克隆,新检出根本不包含旧基线的对象,`rebase_overlay.py` 的三方合并(`git rebase --onto`)没有 base 可用,直接失败。**解法见 §B0**:先用 `git clone --local` 把完整历史(含旧基线 tag)灌好,再让 `gclient sync` 接手——一个已有完整历史的仓库不会被 `--no-history` 截断。

### `git add -A` 在同步过的树上不可用

`gclient sync` 之后 `src` 下有大量 DEPS 子仓与构建生成物,虽然大部分被 `.gitignore` 覆盖,但**不能赌**它们全被覆盖。`rebase_overlay.py`/`export_patches.py` 用的是从 `patches/` + `branding/` + 版本生成物白名单反推出的精确路径集,不是通配符。

### `out/` 目录不能移动

GN 生成的构建文件里带绝对路径,搬家会废掉整个构建缓存。检出内 `<checkout>/src/out` 是唯一合法位置,`<repo>/build` 只能作为指**进**检出内部的符号链接(方向不可反),不能反过来把 `out` 挪到仓库里再链接回去。旧基线检出(M148,`<repo>/chromium`,含 161 GB 暖构建缓存)因为这个原因**原地保留、绝不迁移**,作为升级期间仍能给旧基线发 hotfix 的应急能力——这正是采用「新检出」而不是「原地升级」方案的核心理由之一。

### 全程不要用 `git clean -fdx`

对 chromium 检出这类几百 GB、混杂 DEPS 子仓/生成物/构建缓存的树,`git clean -fdx` 的爆炸半径不可控。幂等验证(见 G1)用的是 `git checkout -q -f <tag>` + 手工清掉少数几个已知生成物路径,不是无差别清树。

### 旧检出是回退底座,任何阶段都不能碰

整个升级期间,旧基线检出必须保持**只读**(本次只用 `sed`/`grep`/`git show` 之类的只读命令读取 M148 已应用态,从未写入)。回退动作就是把 `CHROMIUM_VERSION`/`TELEPORT_VERSION` 改回旧值,派生路径规则会自动指回旧检出,旧检出的构建缓存原样可用。这个保证只在旧检出真的没被碰过的前提下成立。

### dry-run 与 `rebase --onto` 是两种不同粒度的探测,不能互相预测

G0 阶段用「对每个 patch 单独跑 `git apply --3way --check`」估算冲突量,这个方法**只检查该 patch 自己触碰到的 hunk**。真正的 `git rebase --onto` 是对**每个改动过的文件做整文件三方合并**,参与合并的是"我们的改动" x "旧基线→新基线的完整上游 delta"——它看到的上下文远大于单个 patch 的 hunk 范围。

本次实测:dry-run 估算「2 个真冲突」,真正的 rebase 停在「**15 个冲突文件 / 17 个冲突 hunk**」。这不是 dry-run 测错了——它测的东西本来就和 rebase 不是一回事,两者只是恰好在"预测会不会顺利"这个粗粒度问题上经常给出相近的印象。**结论:任何一次未来升级的工作量估算,都不能拿逐 patch dry-run 的冲突计数当作 rebase 实际冲突量的代理指标。** 想要更准的量级预估,唯一办法是真的跑一次 `rebase_overlay.py`。

### 测试命令的假绿陷阱

见 G3 完整展开。核心规则:**任何 `--gtest_filter` 在被信任之前,必须过 `--gtest_list_tests` 核对匹配到的用例名,以及实际执行的用例计数——退出码 0 不是证据,gtest 对"零匹配"和"全部通过"打印的收尾文案几乎无法用肉眼区分。**

### out 目录深度陷阱:上游测试加载源码树数据全部失败

Chromium 的 `base_paths_mac.mm` 里 `DIR_SRC_TEST_DATA_ROOT` 的解析方式是**从可执行文件所在目录往上走恰好两层**(上游注释原文:"Unit tests execute two levels deep from the source root")。标准 Chromium 用 `out/Default`,离 `src` 正好两层,这个假设成立。**本项目用 `out/mac/arm64/dev`,离 `src` 四层**,两层往上落到的是 `<src>/out/mac`,而不是 `<src>`——任何调用 `GetTestCertsDirectory()` 之类接口、需要从源码树加载测试数据(证书、fixture 文件等)的上游用例,**全部**会失败(空指针/文件不存在),因为路径解析到了错误的位置。

这不是 M151 引入的回归,是这套项目的 out 目录布局与上游假设从一开始就不匹配的固有问题——只是因为「跑上游单测」在本项目里此前从未真正做过(见 `docs/tech-debt.md` 的 `TD-UPSTREAM-UT-CI-BASELINE`),才一直没暴露。`CR_SOURCE_ROOT` 环境变量帮不上忙(macOS 的实现路径根本不读它);建一个离 `src` 两层的符号链接也没用(`FILE_EXE` 的解析会穿透符号链接算真实路径,层数按真实路径算)。

本次会话验证过的临时绕过方法:在 `out/mac/` 下建一个指向 `<src>/net` 的符号链接(`<src>/out/mac/net -> <src>/net`),让两层解析路径恰好落在一个能找到 `net/` 测试数据的位置。验证方式:此前 100% 失败的一个上游用例(需要加载测试证书)在建好这个符号链接后变成 3/3 通过。这个符号链接建在 gitignore 覆盖的 `out/` 目录下,不会污染 `git status`,也不会触发 `export_patches.py` 的安全阀。**这只是这一轮验证用的绕过手段,不是正式修复**——正式修复(拉平 out 目录层级,或者包一层测试 runner 自己纠正工作目录)工作量超出一次基线升级的范围,已登记为 `docs/tech-debt.md` 的独立条目。

### 环境变量陷阱:`$TELEPORT_CHROMIUM_DIR` 会覆盖一切路径派生,`$TELEPORT_CHROMIUM_ROOT` 又需要显式导出

`$TELEPORT_CHROMIUM_DIR` 一旦被设置,会**整体覆盖**按 `CHROMIUM_VERSION` 派生检出路径的规则(见 §5 的路径派生说明)。如果这个变量还残留指向旧基线的路径(比如上一次会话/上一个 shell 遗留下来的),所有脚本都会悄悄地对着旧检出操作,而不是报错——**这个坑不会主动提醒你**。

反过来,本文档里大量命令直接按字面展开 `$TELEPORT_CHROMIUM_ROOT`(如 `cd "$TELEPORT_CHROMIUM_ROOT"/<release_branch>/src`)。这个变量的默认值 `~/workspace/chromium` **只存在于 `scripts/_lib.py` 内部**——Python 脚本自己会用这个默认值,但 shell 并不知道,一个从未设置过它的 shell 里 `$TELEPORT_CHROMIUM_ROOT` 直接展开为空串,`cd ""/151.0.7922/src` 之类的命令会失败或(更危险)悄悄作用在错误的相对路径上。所以两个变量要一起处理:一个确认为空,一个显式建立。每个新开的 shell、每次执行本 runbook 里的任何命令之前,先跑:

```bash
unset TELEPORT_CHROMIUM_DIR
echo "TELEPORT_CHROMIUM_DIR=$TELEPORT_CHROMIUM_DIR"   # 必须是空

export TELEPORT_CHROMIUM_ROOT="${TELEPORT_CHROMIUM_ROOT:-$HOME/workspace/chromium}"
echo "TELEPORT_CHROMIUM_ROOT=$TELEPORT_CHROMIUM_ROOT"   # 本文档后续命令都按字面展开它,必须先导出
```

本文档每个新 shell 首次出现命令的地方(§B0、G0、G5)都重复了这一对命令,直接照抄该处开头即可,不需要跳回这里。

---

## 检出路径派生规则(参考)

检出目录按**发布分支**(版本号前三段 `MAJOR.MINOR.BUILD`)划分,不按完整四段版本:

```
CHROMIUM_VERSION  = 151.0.7922.76
检出目录          = $TELEPORT_CHROMIUM_ROOT/151.0.7922      # 取前三段
                    默认 $TELEPORT_CHROMIUM_ROOT = ~/workspace/chromium
$TELEPORT_CHROMIUM_DIR                                       # 仍可整体覆盖(向后兼容 / CI),见上面的环境变量陷阱
```

**为什么按发布分支而不是完整版本**:PATCH 级移动(路径 A)始终在同一发布分支内,复用检出、DEPS 基本不动;里程碑跃迁(路径 B)的 `BUILD` 号必然变化,天然落到新目录,旧检出自动被绕开。若按完整四段版本划分,一次安全补丁都会触发新建约 110 GB 检出加全量重编,代价与收益完全不成比例。

`_lib.chromium_dir()` 是这条规则的唯一实现;换分支时因为 `CHROMIUM_VERSION` 变了,路径自动跟着变,**不会再出现"忘记 export 环境变量导致打到假路径"这类问题**(仍然可能因为 `$TELEPORT_CHROMIUM_DIR` 显式设置而覆盖,见上一节)。

## 上游 tag ≠ 已发布

`chromium/src` 仓库里的 git tag **不能**用来判断某个版本是否真的对外发布过。上游从每条发布分支(`refs/branch-heads/<BUILD>`)上**再切子分支**(如 `7871_48`、`7871_183`),每条子分支服务一个平台或一次 respin 轨道,各自从分叉点继续独立递增 PATCH 号。实测证据:`150.0.7871.131` 不是 `150.0.7871.150` 的祖先,commit 主题带 `[7871_48]`、`[7871_183]` 这类子分支前缀,tag 日期与编号也不单调。

两个推论:

1. **仓库里存在的 tag 远多于真正发布过的版本**——大量 tag 是内部构建、其他平台的 respin、或从未推送给用户的候选版本。判断「是否真的发布」必须用 Chrome VersionHistory API(`scripts/check_upstream_release.py` 已经这样做),不能扫 tag 列表。
2. **各平台发布的 PATCH 号本来就不同**。实测 M151:Mac/Win64 `.76`,Linux `.75`,Android/WebView `.83`,iOS `.105`——这是正常状态,不是哪个平台"落后"。

## 桌面 Mac/Win 同线、Linux 取子集——单一 pin 为什么对全部桌面平台都正确

实测 M151 已发布版本序列:

| 平台 | 序列 |
|---|---|
| Mac | `.76` `.75` `.72` `.71` `.47` `.34` |
| Win64 | `.76` `.75` `.72` `.71` `.47` `.34`(与 Mac 完全一致)|
| Linux | `.75` `.71`(同一序列的**子集**)|

桌面三平台共用同一条发布线,Mac/Windows 拿到全量 PATCH,Linux 只推其中一部分。所以:

- **单一 `CHROMIUM_VERSION` 钉住全部桌面平台是正确的**,不需要按平台分别维护 pin。
- Linux 相对落后不构成问题——钉住 Mac/Win 的最新 PATCH 去构建 Linux 完全合法(同一分支源码),只是比 Google 实际推给 Linux 用户的版本多带了若干个还没轮到 Linux 的修复,不存在"版本不匹配"的问题。
- 一旦 `check_upstream_release.py` 报告 mac 与 win64 的最新版本不一致,说明这个「桌面同线」假设被打破了,需要人工判断分别怎么跟。

---

## 本次(M148 148.0.7778.180 → M151 151.0.7922.76)实测数据:下次升级的预期基准

| 项 | 数据 |
|---|---|
| 旧检出 `src` git 对象大小 | ~65.5 GB(`git count-objects -v` 的 `size-pack`),`git clone --local` 硬链接省下的即这部分 |
| Overlay patch 总数 | 105 → 107(69 个重写、33 个原样保留、5 个新建、3 个因目标文件被上游删除而删除;第 5 个新建是 G2 编译到绿阶段补的 `media/formats/dts/dts_util.cc.patch`,晚于 G1 的 rebase/export,不在当时 106 的统计里;终审复核独立确认为 107) |
| 逐 patch dry-run 估算冲突 | 83 CLEAN / 20 3WAY / 2 CONFLICT(共 105 个 patch) |
| **真实 `rebase --onto` 冲突**(与上一行不可互相预测,见「踩过的坑」) | **15 个冲突文件 / 17 个冲突 hunk** |
| Overlay 源码(`src/**`)因上游 API 变化需要真正修复的文件数 | **2 个**(`teleport_voluntary_signin.{h,cc}`) |
| 全量构建规模 | 34,680 个编译步骤;首次全量构建在 31165/34680 处停下时,只有**一个**失败步骤是上游/overlay 代码问题(另需一个 patch 修上游自身的头文件缺失) |
| G0(环境就绪) | PASS |
| G1(patch 迁移 + 幂等) | PASS(三次 `apply_patches.py` 工作树 diff SHA-256 完全一致) |
| G2(编译到绿) | PASS(`teleport_unittests` 目标可编,全量 `chrome` 构建成功) |
| G3(单测绿) | PASS —— `teleport_unittests` 136/136;`UserAgentUtilsTest` 23/23(`components_unittests --single-process-tests`);`BrowserDMTokenStorageMacTest` 5/5(`unit_tests`);`NetworkServiceProxyDelegateTest` 3/3(`services_unittests`);Track T 转发代理 4 个用例 12/12(`net_unittests`);`uv run pytest` 288/288,0 skipped |
| G4(GUI 冒烟) | **PARTIAL**——自动化可核实项已通过(UA 引擎版本正确、纳管后端可达);人工逐项点击验证因 macOS keychain 弹窗阻塞自动化流程,按用户指示推迟,不得报告为 PASS |
| G5(release 构建 + 出包) | **PARTIAL PASS**——release 构建(带 `teleport_use_release_endpoints=false` 的机制验证包,非可发布 canary)已**成功完成**:解析后的 args 已核实 `chrome_pgo_phase=2`(PGO 真正生效)、`teleport_enable_updater=true`、`is_official_build=true`、`enable_update_notifications=true`,产出 `Teleport.app`(版本 `0.2.0.0`),`Sparkle.framework` 以真实 3.0M 目录(而非会在 dmg 里变死链的符号链接)嵌入。签名 / 公证 / 样式 dmg 三步因需要人工在场处理 keychain 弹窗而未做。真正可发布的 release 因生产 KMS 密钥缺失而结构性受阻,登记为独立技术债(TD-026),不属于升级本身的范畴 |

**读这张表时的注意事项**:「dry-run 估算冲突」与「真实 rebase 冲突」两行刻意并排放,提醒下一次升级的人不要把前者当后者的预测值用;「全量构建规模」与「真正需要修复的文件数」两行说明 overlay 引用的 36 个已变动上游头文件是**不确定性上限**而不是实际损伤的量级,过度悲观地预估工作量同样会误导排期。

## 参考材料

- 设计:`docs/superpowers/specs/2026-08-06-chromium-milestone-upgrade-design.md`
- 实施计划:`docs/superpowers/plans/2026-08-06-chromium-milestone-upgrade.md`
- 执行台账(第一手踩坑记录,比本文档更细):`.superpowers/sdd/2026-08-06-chromium-milestone-upgrade/progress.md`
- 冒烟检查清单:`scripts/smoke_check.md`
- 技术债:`docs/tech-debt.md`
