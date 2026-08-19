# 部署环境三态化 Phase 1:GN 骨架与档位 seam 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把客户端的后端环境选择从布尔 `teleport_use_release_endpoints` 升级为三态 `teleport_deployment_env = dev|staging|release`,并把档位判定下沉为可在单一 dev 二进制中全测的纯函数。

**Architecture:** GN 层用一个 string arg + 枚举断言,派生出三个布尔 buildflag(`#if` 无法对字符串求值);旧布尔保留为墓碑 arg 并断言其未被设置(GN 对未声明 arg 只告警且退出码 0,直接删名会让存量覆盖静默失效)。C++ 侧现有三处 `BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` 消费者改用新 flag;`ReadCommandLineDomain()` 的策略部分抽为跨平台纯函数 `SelectCommandLineDomain()`,使"release 档不接受命令行域覆盖"这一行为可被单测覆盖——它在 release 二进制里本身编不出来。

**Tech Stack:** GN / C++17 (Chromium M151) / gtest / Python 3.13 + pytest (uv)

## Global Constraints

- **spec 权威**:`docs/superpowers/specs/2026-08-10-deployment-env-tristate-design.md`(v2)。本计划实现其 §4.1、§4.4 的 level-1 部分、§7 的 seam 部分。
- **第三态字面值是 `release`**,不是 `prod`(与 `release.mac.gn`、`out/mac/arm64/release` 及服务端 master design 用词一致)。枚举恒为 `dev | staging | release`。
- **文档语言**:Markdown 中文;代码、注释、commit message 一律英文。
- **一文件一 patch**:每个 `.patch` 只改一个上游文件,文件名镜像其在 `chromium/src` 下的路径。
- **修改已有 patch 的标准工作流**(禁止手改 hunk):
  1. `python scripts/apply_patches.py` 确保全部已应用
  2. 直接编辑 `$CR/<file>`(`CR=~/workspace/chromium/151.0.7922/src`)
  3. `git -C "$CR" diff -- <path> > patches/<path>.patch` 重生成
  4. 再跑一次 `python scripts/apply_patches.py` 验证幂等
- **本 Phase 不触碰品牌重写的三个例外路径**(`generated_resources.grd` / `generated_resources_zh-CN.xtb` / `settings_strings.grdp`),故**不需要** `--skip-branding` 树。
- **overlay symlink** 已指向本 worktree 的 `src/`(`~/workspace/chromium/151.0.7922/src/teleport`)。
- 每个任务结束时工作树必须干净(已 commit)。

---

### Task 1: GN 三态 arg、墓碑 arg 与 fail-closed 断言

**Files:**
- Modify: `src/teleport.gni:5-38`

**Interfaces:**
- Produces: GN 作用域变量 `teleport_deployment_env`(string)、`teleport_env_is_release`(bool)、`teleport_env_is_staging`(bool)、`teleport_allows_domain_override`(bool)、`teleport_policy_key_placeholder_ack`(bool)、`teleport_staging_policy_key_is_real`(bool)、`teleport_release_policy_key_is_real`(bool)。Task 2 与 Phase 3 均消费这些名字。

- [ ] **Step 1: 用最小 GN 工程验证枚举断言与墓碑断言的行为**

先证明机制成立再改真代码。在 scratchpad 建最小工程:

```bash
S=/private/tmp/claude-501/-Users-liulichao-workspace-teleport/2c4f0db0-136e-487f-b89f-feb888cef03d/scratchpad/gntest
mkdir -p "$S/tp/gn/args"
cat > "$S/.gn" <<'EOF'
buildconfig = "//build/BUILDCONFIG.gn"
EOF
mkdir -p "$S/build"
cat > "$S/build/BUILDCONFIG.gn" <<'EOF'
set_default_toolchain("//build/toolchain:dummy")
EOF
mkdir -p "$S/build/toolchain"
cat > "$S/build/toolchain/BUILD.gn" <<'EOF'
toolchain("dummy") {
  tool("stamp") { command = "touch {{output}}" }
}
EOF
cat > "$S/tp/teleport.gni" <<'EOF'
declare_args() {
  teleport_deployment_env = "dev"
  teleport_use_release_endpoints = false
}
assert(!teleport_use_release_endpoints,
       "teleport_use_release_endpoints was replaced by teleport_deployment_env")
assert(teleport_deployment_env == "dev" || teleport_deployment_env == "staging" ||
       teleport_deployment_env == "release",
       "teleport_deployment_env must be dev|staging|release, got: $teleport_deployment_env")
EOF
cat > "$S/BUILD.gn" <<'EOF'
import("//tp/teleport.gni")
group("root") { }
EOF
GN=~/workspace/chromium/151.0.7922/src/buildtools/mac/gn
"$GN" gen "$S/out/bad-enum" --root="$S" --args='teleport_deployment_env="stagng"' 2>&1 | tail -3
"$GN" gen "$S/out/tombstone" --root="$S" --args='teleport_use_release_endpoints=true' 2>&1 | tail -3
"$GN" gen "$S/out/ok" --root="$S" --args='teleport_deployment_env="staging"' 2>&1 | tail -2
```

Expected:前两条各自 `ERROR at ... Assertion failed` 且**非零退出**;第三条 `Done.`。

- [ ] **Step 2: 改写 `src/teleport.gni` 的 `declare_args()` 与断言块**

把 `teleport_use_release_endpoints` 的声明与注释整体替换为下面内容(保留其上的 `teleport_enable_updater`、其下的 `teleport_sparkle_dir` 不动):

```gn
  # Which backend environment this binary is built for. Exactly one environment's
  # trust material — the policy verification root(s) and the default deployment
  # domain — is baked in; the others are not merely disabled but ABSENT from the
  # binary. That absence is the whole point: F6 (fairyland master design 2.5)
  # requires that a staging compromise cannot mint anything a release client
  # trusts, and only "the material is not in the binary" delivers that as a
  # certainty rather than as a runtime check. See the design spec 2.5.
  #   "dev"     - fairyland.io + the committed dev root; local and CI only.
  #   "staging" - staging.douan.cn + the staging KMS root; official build form.
  #   "release" - douan.cn + the release KMS root(s); official build form.
  teleport_deployment_env = "dev"

  # Tombstone for the pre-tristate boolean. GN only WARNS about build args it
  # does not recognize and still exits 0, so deleting this name outright would
  # let a stale `teleport_use_release_endpoints=<x>` override -- several are
  # written down in docs/chromium-upgrade-runbook.md and docs/tech-debt.md, and
  # one is still sitting in out/mac/arm64/release/args.gn -- silently no-op.
  #
  # The default is the STRING sentinel "unset", not false, so that BOTH values
  # trip the assert below. `=false` is in fact the more dangerous of the two:
  # the documented TD-026 workaround is `teleport_use_release_endpoints=false`
  # layered onto the release template, meaning "release build form, dev
  # endpoints". Post-migration that override does nothing while the template's
  # teleport_deployment_env="release" still applies -- so the operator would get
  # the real release endpoints baked in while believing they got dev ones. A
  # boolean tombstone defaulting to false cannot detect that case at all.
  teleport_use_release_endpoints = "unset"

  # Safety interlocks: each environment's baked policy root is a THROWAWAY
  # PLACEHOLDER until the real KMS public key is vendored. Flip only after
  # replacing keys/<env>-policy-root.pub.pem and passing
  # `gen_policy_verification_key.py --check --require-real <env>`.
  teleport_staging_policy_key_is_real = false
  teleport_release_policy_key_is_real = false

  # Named escape hatch for "I know the roots are placeholders; I only want to
  # exercise the build/sign/package machinery." It stamps TeleportUnpublishable
  # into the app's Info.plist, which package.py --distribute refuses outright.
  # It exists so that validating the pipeline is an explicit, greppable,
  # self-disarming act rather than an ad-hoc `gn gen` override left behind in
  # args.gn forever -- which is exactly how TD-026 played out.
  teleport_policy_key_placeholder_ack = false
```

然后把文件末尾原有的那条 `assert(!teleport_use_release_endpoints || ...)` 整体替换为:

```gn
assert(teleport_use_release_endpoints == "unset",
       "teleport_use_release_endpoints was replaced by teleport_deployment_env " +
           "(\"dev\" | \"staging\" | \"release\"). Update whatever set it -- a " +
           "stale override is silently ignored, so the build would bake whatever " +
           "environment the args template selected, not the one you asked for.")

assert(teleport_deployment_env == "dev" || teleport_deployment_env == "staging" ||
           teleport_deployment_env == "release",
       "teleport_deployment_env must be dev|staging|release, got: " +
           teleport_deployment_env)

teleport_env_is_release = teleport_deployment_env == "release"
teleport_env_is_staging = teleport_deployment_env == "staging"

# The level-1 --teleport-deployment-domain switch is compiled OUT of release
# builds (design spec 4.4). staging keeps it: staging exists to be poked at, and
# the switch can only change the endpoint, never the trust anchor.
teleport_allows_domain_override = !teleport_env_is_release

# A build that bakes an environment's endpoints must also bake that
# environment's REAL policy root -- never a placeholder, whose private half is
# either discarded or (for the pre-existing release placeholder) unknown. A
# leaked placeholder private key would validate forged policy, and real
# KMS-signed policy would fail validation. Keep this fail-closed; the ack arg
# above is the only sanctioned way past it, and it disarms distribution.
assert(!teleport_env_is_staging || teleport_staging_policy_key_is_real ||
           teleport_policy_key_placeholder_ack,
       "teleport_deployment_env=\"staging\" requires " +
           "teleport_staging_policy_key_is_real=true (the real staging KMS root " +
           "must be vendored first), or teleport_policy_key_placeholder_ack=true " +
           "for an explicitly unpublishable build.")

assert(!teleport_env_is_release || teleport_release_policy_key_is_real ||
           teleport_policy_key_placeholder_ack,
       "teleport_deployment_env=\"release\" requires " +
           "teleport_release_policy_key_is_real=true (the real release KMS root " +
           "must be vendored first), or teleport_policy_key_placeholder_ack=true " +
           "for an explicitly unpublishable build.")
```

- [ ] **Step 3: 验证三档 `gn gen` 行为符合预期**

```bash
CR=~/workspace/chromium/151.0.7922/src
cd "$CR"
gn gen out/mac/arm64/tri-dev --args='import("//teleport/gn/args/dev.mac.gn")' 2>&1 | tail -3
```

Expected:此时 `dev.mac.gn` 仍写着旧 arg,应命中**墓碑断言**并失败。这正是墓碑机制起作用的证据——记录下来,Task 3 修完模板后再跑通。

- [ ] **Step 4: 提交**

```bash
git add src/teleport.gni
git commit -m "build: replace the release-endpoints boolean with a deployment-env tristate

GN only warns about unrecognized build args and still exits 0, so the old
teleport_use_release_endpoints name stays declared as a tombstone with an
assert -- otherwise the overrides recorded in the upgrade runbook and tech-debt
notes (and the one still sitting in out/mac/arm64/release/args.gn) would
quietly select dev instead of failing.

Adds a named placeholder-ack escape hatch so that exercising the build
machinery against placeholder keys is an explicit, self-disarming act rather
than an ad-hoc gn gen override left behind forever, which is how TD-026 went."
```

---

### Task 2: buildflag 展开为三个布尔,并迁移三处 C++ 消费者

**Files:**
- Modify: `src/BUILD.gn:24-27`
- Modify: `src/common/teleport_deployment_config.cc:47-52`
- Modify: `src/common/teleport_deployment_config_mac.mm:31-47`
- Modify: `src/common/teleport_deployment_config_unittest.cc:36-44`
- Modify: `patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch`

**Interfaces:**
- Consumes: Task 1 的 `teleport_env_is_release` / `teleport_env_is_staging` / `teleport_allows_domain_override`
- Produces: buildflag 宏 `TELEPORT_ENV_IS_RELEASE`、`TELEPORT_ENV_IS_STAGING`、`TELEPORT_ALLOWS_DOMAIN_OVERRIDE`(头文件 `teleport/teleport_policy_buildflags.h`)。Phase 2 的验签 patch 与 Phase 3 均消费。

> **执行顺序修正**:Step 6 的构建验证要求 `dev.mac.gn` 已迁移到新 arg,否则 `gn gen` 会命中 Task 1 的墓碑断言。故 **Task 3 Step 1(dev/release 模板迁移)必须先于本任务的 Step 6 执行**,并与本任务同批提交——两者构成一次原子的可构建变更。

- [ ] **Step 1: 展开 buildflag_header**

`src/BUILD.gn` 中把 `flags = [...]` 一行替换为:

```gn
  # Three booleans rather than one string: BUILDFLAG() values are used in #if,
  # and the preprocessor cannot compare strings. (buildflag_header itself does
  # support string values -- see build/buildflag_header.gni -- they are just
  # unusable in the conditional we need.) dev is the both-false case.
  flags = [
    "TELEPORT_ENV_IS_RELEASE=$teleport_env_is_release",
    "TELEPORT_ENV_IS_STAGING=$teleport_env_is_staging",
    "TELEPORT_ALLOWS_DOMAIN_OVERRIDE=$teleport_allows_domain_override",
  ]
```

- [ ] **Step 2: 迁移 `teleport_deployment_config.cc` 的默认域为三分支**

把 `kBakedDefaultDomain` 的 `#if/#else/#endif` 块替换为:

```cpp
#if BUILDFLAG(TELEPORT_ENV_IS_RELEASE)
constexpr char kBakedDefaultDomain[] = "douan.cn";
#elif BUILDFLAG(TELEPORT_ENV_IS_STAGING)
constexpr char kBakedDefaultDomain[] = "staging.douan.cn";
#else
constexpr char kBakedDefaultDomain[] = "fairyland.io";
#endif
```

- [ ] **Step 3: 迁移 mac 侧的 level-1 gate**

`teleport_deployment_config_mac.mm` 中,把 `ReadCommandLineDomain()` 里的 `#if !BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` 改为 `#if BUILDFLAG(TELEPORT_ALLOWS_DOMAIN_OVERRIDE)`,并把首行注释改写为:

```cpp
// Level 1: command-line switch, compiled OUT of release builds so it is not
// merely disabled but absent (design spec 4.4). staging keeps it: staging
// exists to be poked at, and the switch can only redirect the endpoint, never
// the trust anchor -- a staging binary aimed at an attacker's server still
// cannot be handed policy that verifies.
```

- [ ] **Step 4: 迁移单测的档位预期为三分支**

`teleport_deployment_config_unittest.cc` 的 `FallsBackToBakedDefault` 中:

```cpp
#if BUILDFLAG(TELEPORT_ENV_IS_RELEASE)
  EXPECT_EQ(DeploymentDomain(), "douan.cn");
#elif BUILDFLAG(TELEPORT_ENV_IS_STAGING)
  EXPECT_EQ(DeploymentDomain(), "staging.douan.cn");
#else
  EXPECT_EQ(DeploymentDomain(), "fairyland.io");
#endif
```

- [ ] **Step 5: 迁移 patch 中的 buildflag 名(仅改条件,不动密钥)**

按 Global Constraints 的标准 patch 工作流,把 `cloud_policy_constants.cc` 中的两处 `#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` 改为 `#if BUILDFLAG(TELEPORT_ENV_IS_RELEASE)`,两处 `#endif` 的尾注释同步改名。**本任务不新增密钥、不改结构**——四把根与 `GetPolicyVerificationKeys()` 属 Phase 2。

```bash
CR=~/workspace/chromium/151.0.7922/src
python scripts/apply_patches.py
# 编辑 "$CR/components/policy/core/common/cloud/cloud_policy_constants.cc"
git -C "$CR" diff -- components/policy/core/common/cloud/cloud_policy_constants.cc \
  > patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch
python scripts/apply_patches.py
```

Expected:第二次 `apply_patches.py` 无报错(幂等)。

- [ ] **Step 6: 构建并运行 overlay 单测**

```bash
CR=~/workspace/chromium/151.0.7922/src
cd "$CR" && autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportDeployment*'
```

Expected:全部 PASS(dev 档,默认域 `fairyland.io`)。

- [ ] **Step 7: 提交**

```bash
git add src/BUILD.gn src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_mac.mm \
        src/common/teleport_deployment_config_unittest.cc \
        patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch
git commit -m "build: expand the env buildflag into three booleans and migrate consumers

BUILDFLAG values feed #if, and the preprocessor cannot compare strings, so the
tristate becomes TELEPORT_ENV_IS_RELEASE / TELEPORT_ENV_IS_STAGING (dev being
the both-false case) plus TELEPORT_ALLOWS_DOMAIN_OVERRIDE, which is what the
level-1 gate actually wants to ask about.

The policy-constants patch only renames its condition here; the four roots and
the key-set accessor land in phase 2."
```

---

### Task 3: staging args 模板(链式 import)与 dev/release 模板迁移

**Files:**
- Create: `src/gn/args/staging.mac.gn`
- Modify: `src/gn/args/dev.mac.gn:57`
- Modify: `src/gn/args/release.mac.gn:60`

**Interfaces:**
- Consumes: Task 1 的 `teleport_deployment_env`
- Produces: 三份 args 模板,供 Phase 3 的 `CHANNELS` 注册表按名引用(`dev.mac.gn` / `staging.mac.gn` / `release.mac.gn`)

- [ ] **Step 1: 迁移 dev 与 release 模板**

`dev.mac.gn` 中 `teleport_use_release_endpoints = false` 那一行(含其上注释)替换为:

```gn
# Bake the dev fairyland.io endpoints + the committed dev policy root.
teleport_deployment_env = "dev"
```

`release.mac.gn` 中对应行(含其上注释块)替换为:

```gn
# Bake the production douan.cn endpoints + the release KMS verification root(s).
# All release channels (canary/beta/stable) share these values.
# NOTE: kReleasePolicyKey is still a throwaway placeholder -- teleport.gni's
# fail-closed assert blocks this build until the real KMS root is vendored.
teleport_deployment_env = "release"
```

- [ ] **Step 2: 创建 staging 模板,以链式 import 复用 release**

```gn
# Staging channel build args for the teleport overlay on macOS (Apple Silicon).
#
# Chain-imports release.mac.gn rather than copying it: the whole point of the
# staging variant is that it is byte-for-byte the same pipeline as release
# (official + PGO + Sparkle + Developer ID signing + notarization + styled dmg)
# with only the baked trust material and endpoints differing. A copied 60-line
# template would drift from release the first time either is touched, and the
# drift would be invisible -- it would look like two files that merely disagree.
#
# Everything below the import is the deliberate difference.
import("//teleport/gn/args/release.mac.gn")

# staging.douan.cn + the staging KMS verification root. NOT the release root:
# under F6 each environment owns its own teleport-root, so a release binary
# cannot verify staging-signed policy and vice versa. That mutual failure IS
# the isolation, and the cross-negative e2e in the spec proves it.
teleport_deployment_env = "staging"

# Distinct out dir from release so the two never share a ninja graph. They
# differ in //components/policy, which re-links most of the browser, so a
# shared dir would mean a full rebuild on every channel switch.
```

**注意**:out 目录由 `_build.py` 的 `CHANNELS` 决定(Phase 3),不在 args 模板里设置。上面最后一段注释保留为说明,不加任何 arg。

- [ ] **Step 3: 验证三份模板均可 `gn gen`(staging/release 应命中 fail-closed 断言)**

```bash
CR=~/workspace/chromium/151.0.7922/src
cd "$CR"
gn gen out/mac/arm64/tri-dev --args='import("//teleport/gn/args/dev.mac.gn")' 2>&1 | tail -2
gn gen out/mac/arm64/tri-staging --args='import("//teleport/gn/args/staging.mac.gn")' 2>&1 | tail -3
gn gen out/mac/arm64/tri-ack --args='import("//teleport/gn/args/staging.mac.gn") teleport_policy_key_placeholder_ack=true' 2>&1 | tail -2
```

Expected:
- dev → `Done.`
- staging → `Assertion failed` 且提到 `teleport_staging_policy_key_is_real`(**这是预期行为**,不是故障)
- ack → `Done.`(具名逃生口生效)

- [ ] **Step 4: 验证链式 import 的覆盖语义确实生效**

```bash
CR=~/workspace/chromium/151.0.7922/src
cd "$CR"
gn args out/mac/arm64/tri-ack --list=teleport_deployment_env --short
gn args out/mac/arm64/tri-ack --list=chrome_pgo_phase --short
gn args out/mac/arm64/tri-ack --list=teleport_enable_updater --short
```

Expected:`teleport_deployment_env = "staging"`(覆盖生效)、`chrome_pgo_phase = 2`、`teleport_enable_updater = true`(两者从 release 继承)。这三行同时证明了"staging 与 release 同一条流水线、仅信任材料不同"。

- [ ] **Step 5: 清理临时 out 目录并提交**

```bash
CR=~/workspace/chromium/151.0.7922/src
rm -rf "$CR"/out/mac/arm64/tri-dev "$CR"/out/mac/arm64/tri-staging "$CR"/out/mac/arm64/tri-ack
git add src/gn/args/
git commit -m "build: add the staging args template and migrate dev/release to the tristate

staging chain-imports release.mac.gn instead of copying it. The variant's whole
purpose is to be the same pipeline as release with different trust material, and
a copied template would drift the first time either side is touched -- silently,
since the result would just look like two files that disagree.

Verified that the override lands (teleport_deployment_env=staging) while PGO and
the updater are inherited, and that both official templates hit the fail-closed
key assert until the real KMS roots are vendored."
```

---

### Task 4: 档位判定下沉为纯函数 seam,并补齐三档单测

**Files:**
- Modify: `src/common/teleport_deployment_config.h`(公开 API 区,`NormalizeDeploymentDomain` 声明之后)
- Modify: `src/common/teleport_deployment_config.cc`
- Modify: `src/common/teleport_deployment_config_mac.mm`
- Modify: `src/common/teleport_deployment_config_unittest.cc`

**Interfaces:**
- Produces: `std::optional<std::string> teleport::SelectCommandLineDomain(bool allows_override, bool switch_present, std::string_view switch_value)` —— Phase 2/3 不消费,但它是 spec §7"三态在同一 dev 二进制内全部可测"的落点。

**为什么需要这个 seam**:现有档位测试是 `#if`/`#else`,一个二进制只编译一档;而 `teleport_unittests` 只在 dev out 构建,`TELEPORT_ALLOWS_DOMAIN_OVERRIDE=false` 那一档**永远编不出来**。把策略抽成接受 `bool` 参数的纯函数后,三档行为可在 dev 二进制里全部覆盖,buildflag 只剩唯一一个调用点。

- [ ] **Step 1: 写失败的测试**

追加到 `src/common/teleport_deployment_config_unittest.cc`:

```cpp
// The level-1 policy, exercised at all three settings from one dev binary.
// The buildflag itself is unreachable here (a test binary is built for exactly
// one environment), which is precisely why the decision lives in a pure
// function that takes the flag as a parameter.
TEST(TeleportDeploymentCommandLineTest, IgnoredWhenOverrideNotAllowed) {
  // The release setting: even a well-formed switch value must be ignored.
  EXPECT_EQ(SelectCommandLineDomain(/*allows_override=*/false,
                                    /*switch_present=*/true, "acme.internal"),
            std::nullopt);
}

TEST(TeleportDeploymentCommandLineTest, AbsentSwitchYieldsNullopt) {
  EXPECT_EQ(SelectCommandLineDomain(/*allows_override=*/true,
                                    /*switch_present=*/false, ""),
            std::nullopt);
}

TEST(TeleportDeploymentCommandLineTest, NormalizesAcceptedValue) {
  EXPECT_EQ(SelectCommandLineDomain(/*allows_override=*/true,
                                    /*switch_present=*/true, "ACME.Internal."),
            "acme.internal");
}

TEST(TeleportDeploymentCommandLineTest, RejectsMalformedValue) {
  EXPECT_EQ(SelectCommandLineDomain(/*allows_override=*/true,
                                    /*switch_present=*/true, "not a domain"),
            std::nullopt);
}
```

- [ ] **Step 2: 运行测试,确认因未定义而失败**

```bash
CR=~/workspace/chromium/151.0.7922/src
cd "$CR" && autoninja -C out/mac/arm64/dev teleport_unittests 2>&1 | tail -20
```

Expected:编译失败,`error: use of undeclared identifier 'SelectCommandLineDomain'`。

- [ ] **Step 3: 声明纯函数**

`teleport_deployment_config.h` 中 `NormalizeDeploymentDomain` 声明之后加入:

```cpp
// Level-1 policy as a pure function: decide what the command-line switch should
// yield, given whether this build accepts the override at all, whether the
// switch was present, and its raw value. Split out from ReadCommandLineDomain()
// so all three environment settings are testable from a single dev binary --
// a test binary is built for exactly one environment, so the buildflag branch
// that release takes is otherwise unreachable by any test.
std::optional<std::string> SelectCommandLineDomain(bool allows_override,
                                                   bool switch_present,
                                                   std::string_view switch_value);
```

- [ ] **Step 4: 实现纯函数**

`teleport_deployment_config.cc` 中 `NormalizeDeploymentDomain` 的定义之后加入:

```cpp
std::optional<std::string> SelectCommandLineDomain(bool allows_override,
                                                   bool switch_present,
                                                   std::string_view switch_value) {
  if (!allows_override || !switch_present) {
    return std::nullopt;
  }
  std::optional<std::string> d = NormalizeDeploymentDomain(switch_value);
  if (!d) {
    LOG(ERROR) << "[teleport-deployment] --teleport-deployment-domain invalid";
  }
  return d;
}
```

- [ ] **Step 5: 让 mac 侧改为调用它,同时保住"编译期消除"语义**

`teleport_deployment_config_mac.mm` 的 `ReadCommandLineDomain()` 整体替换为:

```cpp
std::optional<std::string> ReadCommandLineDomain() {
#if BUILDFLAG(TELEPORT_ALLOWS_DOMAIN_OVERRIDE)
  const base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();
  const bool present = cmd->HasSwitch("teleport-deployment-domain");
  return SelectCommandLineDomain(
      /*allows_override=*/true, present,
      present ? cmd->GetSwitchValueASCII("teleport-deployment-domain")
              : std::string());
#else
  // Release: the switch-reading code is not compiled at all, so the capability
  // is absent rather than disabled. Routing through the same pure function
  // keeps the two branches honest about returning the same type.
  return SelectCommandLineDomain(/*allows_override=*/false,
                                 /*switch_present=*/false, std::string_view());
#endif
}
```

- [ ] **Step 6: 运行测试,确认全部通过**

```bash
CR=~/workspace/chromium/151.0.7922/src
cd "$CR" && autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportDeployment*'
```

Expected:全部 PASS,含 4 条新增的 `TeleportDeploymentCommandLineTest.*`。

- [ ] **Step 7: 验证 dev 档运行时行为无回归**

```bash
CR=~/workspace/chromium/151.0.7922/src
cd "$CR" && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -3
./out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport \
  --teleport-deployment-domain=acme.internal --version 2>&1 | tail -2
```

Expected:构建成功;`--version` 正常输出(此步验证 seam 重构没有破坏启动路径)。

- [ ] **Step 8: 提交**

```bash
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_mac.mm \
        src/common/teleport_deployment_config_unittest.cc
git commit -m "refactor: make the level-1 domain-override policy a testable pure function

A test binary is built for exactly one environment, so the branch release takes
was unreachable by any test -- the setting that matters most for the isolation
argument was the one setting nothing could cover. SelectCommandLineDomain takes
the flag as a parameter, so all three settings are exercised from the dev
binary, while the mac caller keeps the #if so release still does not compile the
switch-reading code at all."
```

---

## Phase 1 完成定义

1. `teleport_deployment_env` 三态生效;旧布尔名被设置时**硬失败**(非仅告警)。
2. 三份 args 模板齐备;`staging.mac.gn` 经链式 import 继承 PGO 与 updater,仅覆盖环境。
3. staging/release 档 `gn gen` 因占位密钥 fail-closed 报错;`teleport_policy_key_placeholder_ack=true` 是唯一放行通道。
4. dev 档构建与运行与现状等价,`teleport_unittests` 全绿。
5. 档位策略三档均被单测覆盖(不再受"一个二进制只编译一档"限制)。

**不属于 Phase 1**:四把根与 `GetPolicyVerificationKeys()`(Phase 2)、渠道注册表与发布链(Phase 3)、`IsCommandLineSwitchSupported()` 的 release 消除(Phase 3,与其余三个消费者同源处理)。
