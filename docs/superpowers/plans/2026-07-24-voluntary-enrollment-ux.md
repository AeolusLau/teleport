# 自愿纳管形态与 picker 强制纳管修复实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `RequireEnrollmentToBrowse` 成为强制纳管唯一开关(默认 false),gate ON 时经 picker 就地纳管、gate OFF 时经 profile 菜单自愿登录就地纳管,并结构性抑制所有 GAIA 面、清除历史死代码。

**Architecture:** 方案 A——把 teleport gate 谓词以「或」叠进上游 `IsForceSigninEnabled()`,单一开关驱动上游 force-signin 锁 + Layer-1 picker enrollment 机器;新增 profile 菜单登录入口在当前窗口开 tab 走 OIDC capture → 就地注册器;OIDC capture 改道谓词与 gate 解耦,自愿流复用上游披露对话框、picker 强制流免对话框;GAIA 面经 `CanEnableDiceForBuild()=false` 结构性钉死。

**Tech Stack:** Chromium M148 overlay、C++17、GN、gtest、Brave 式 patch(edit-live → `git -C chromium/src diff` → patch → `git checkout` → `apply_patches.py` 验证)、`policy::CloudPolicyClient`/`ProfileCloudPolicyManager`、ProfilePicker flow controller、`WebSigninInterceptor` 披露气泡、grd/xtb i18n。

## Global Constraints

- **平台**:仅 macOS(Apple Silicon)构建验证;所有 patch 的平台分支以 M148 现状为准。
- **上游基线**:`CHROMIUM_VERSION` = 148.0.7778.180,`TELEPORT_CHROMIUM_DIR` = `/Users/liulichao/workspace/teleport/chromium`(worktree 跑发布脚本须 export;本计划构建/测试不涉及发布)。
- **工作区**:worktree `.claude/worktrees/voluntary-enrollment-ux`(分支 `voluntary-enrollment-ux`);`chromium/src/teleport` 符号链接须指向本 worktree 的 `src`(执行前用 `python scripts/bootstrap.py --skip-sync` 确认,完成后按 finishing-a-development-branch 切回)。
- **patch 铁律**:一文件一 patch、文件名镜像 `chromium/src` 路径;扩展共享 patch 时**绝不先 `git checkout`**(会丢前序 hunk)——先 `apply_patches.py` 确保全应用 → 在含前序 hunk 的 live 文件上叠加 edit → `git -C chromium/src diff -- <path>` 重生累积 patch → `git checkout -- <path>` → `apply_patches.py` 验证幂等(期望 `overlay applied.`)。禁止手改 hunk。
- **提交**:一律从 worktree `git -C <worktree>` 提交;commit message 英文;每个 Task 末尾提交;结尾附 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- **文档**:Markdown 简体中文;代码/注释/commit 英文。
- **gate 谓词唯一事实源**:`teleport::RequireEnrollmentGateEnabled()`(会话冻结),所有消费点(gate/lock/guest/signin_util)委托它,禁止散落 `local_state->GetBoolean(kRequireEnrollmentToBrowse)`。
- **构建命令**:`cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome`(dev 增量,warm cache 快);gtest:`autoninja -C out/mac/arm64/dev teleport_unittests && out/mac/arm64/dev/teleport_unittests`;工具脚本:仓库根 `uv run pytest`。
- **无 GAIA 铁律**:任何路径不得把用户引向 accounts.google.com 登录;GAIA 面抑制不得依赖「构建无 OAuth key」的偶然性(§4.8 结构钉死)。

---

## 文件结构(创建/修改总览)

**新增 //teleport 源(编进 `//teleport` source_set 或 chrome/browser,见各 Task):**
- `src/common/teleport_signin_entry_logic.{h,cc,_unittest.cc}` — 纯函数 `ShouldShowTeleportSigninEntry(is_enrolled, is_regular_profile, is_web_app)`(gtest,进 `//teleport` source_set + unittests)。
- `src/browser/enterprise/teleport_force_signin.{h,cc}` — `RequireEnrollmentGateEnabled()`(会话冻结)+ `ResetRequireEnrollmentGateForTesting()`(编进 chrome/browser)。
- `src/browser/enterprise/teleport_voluntary_signin.{h,cc}` — 菜单登录 action + 自愿流披露对话框驱动(编进 chrome/browser/ui,见 Task 集)。

**修改的既有 //teleport 源:**
- `src/browser/enterprise/teleport_enrollment_gate.{h,cc}` — 默认翻转 + 谓词委托 + `MaybeHandleDomainMigration` re-lock + `PendingDomainMigrationFrom` 转正 + finalize/取消 helper。
- `src/browser/enterprise/teleport_oidc_inplace_registrar.cc` — 成功写 display-name/email prefs + 竞态守卫。
- `src/common/teleport_pref_names.h`、`teleport_enterprise_urls.{h,cc}` — 注释订正。
- `src/BUILD.gn` — 新增源与测试。

**上游 patch(新增):**
- `patches/chrome/browser/signin/signin_util.cc.patch` — force-signin OR gate。
- `patches/chrome/browser/policy/browser_signin_policy_handler.cc.patch` — kForced 去 GAIA 化。
- `patches/chrome/browser/profiles/profiles_state.cc.patch` — guest 两谓词点(**内容与 dfef774 删掉的旧版完全不同**)。
- `patches/chrome/browser/profiles/profile_window.cc.patch`、`patches/chrome/browser/ui/webui/signin/profile_picker_handler.cc.patch`(扩展) — guest 动作守卫 + HandleSelectNewAccount 重写。
- `patches/chrome/browser/signin/account_consistency_mode_manager.cc.patch` — `CanEnableDiceForBuild()=false`。
- `patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch`(扩展) — 菜单登录入口 + 已纳管 header + feature 区抑制。
- `patches/chrome/browser/resources/settings/people_page/people_page.html.patch`(或 ts) — dasherless 残留抑制。
- `patches/chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc.patch`(扩展) — finalize 新建 profile。
- `patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch`(扩展) — 改道解耦 + 披露 + 失败反馈。
- `patches/chrome/browser/ui/webui/version/version_ui.cc.patch`(扩展) — 调用 `PendingDomainMigrationFrom`。
- grd/xtb patch(新增) — 菜单串。
- 删除:`patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch`。

---

# Phase 0 — 谓词地基与默认翻转(TDD 纯逻辑先行)

## Task 0.1: `RequireEnrollmentGateEnabled()` 会话冻结谓词

**Files:**
- Create: `src/browser/enterprise/teleport_force_signin.h`
- Create: `src/browser/enterprise/teleport_force_signin.cc`
- Modify: `patches/chrome/browser/BUILD.gn.patch`(把两个新文件加入 `//chrome/browser` 编译列表,镜像既有 `teleport_enrollment_gate.cc` 的加法)

**Interfaces:**
- Produces: `bool teleport::RequireEnrollmentGateEnabled();`(会话内首次成功读取后冻结)、`void teleport::ResetRequireEnrollmentGateForTesting();`

- [ ] **Step 1: 创建 header**

```cpp
// src/browser/enterprise/teleport_force_signin.h
// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_FORCE_SIGNIN_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_FORCE_SIGNIN_H_

namespace teleport {

// Whether the Teleport enrollment gate requires managed enrollment before
// browsing. Reads local_state pref kRequireEnrollmentToBrowse, but — mirroring
// upstream signin_util::IsForceSigninEnabled()'s process-level cache and the
// BrowserSignin policy's dynamic_refresh:false — the value is FROZEN on first
// successful read for the rest of the session. Many upstream call sites
// CHECK/DCHECK that force-signin is a session constant; a live-reading predicate
// would crash them if the pref flipped mid-session.
//
// Fail-open: returns false (and does NOT cache) when g_browser_process /
// local_state is not yet available or the pref is unregistered, so an early
// caller can never CHECK-crash on an unregistered pref and never freezes a
// premature value.
bool RequireEnrollmentGateEnabled();

// Clears the frozen snapshot so a test can re-seed the pref. Test-only.
void ResetRequireEnrollmentGateForTesting();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_FORCE_SIGNIN_H_
```

- [ ] **Step 2: 创建实现**

```cpp
// src/browser/enterprise/teleport_force_signin.cc
// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_force_signin.h"

#include <optional>

#include "chrome/browser/browser_process.h"
#include "components/prefs/pref_service.h"
#include "teleport/common/teleport_pref_names.h"

namespace teleport {

namespace {
std::optional<bool>& GateSnapshot() {
  static std::optional<bool> snapshot;
  return snapshot;
}
}  // namespace

bool RequireEnrollmentGateEnabled() {
  std::optional<bool>& snapshot = GateSnapshot();
  if (snapshot.has_value()) {
    return *snapshot;
  }
  if (!g_browser_process) {
    return false;  // fail-open, do NOT cache
  }
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state ||
      !local_state->FindPreference(prefs::kRequireEnrollmentToBrowse)) {
    return false;  // fail-open, do NOT cache
  }
  snapshot = local_state->GetBoolean(prefs::kRequireEnrollmentToBrowse);
  return *snapshot;
}

void ResetRequireEnrollmentGateForTesting() {
  GateSnapshot().reset();
}

}  // namespace teleport
```

- [ ] **Step 3: 把两文件加入 chrome/browser 编译**

先 `python scripts/apply_patches.py`(确保全应用),然后编辑 live 文件 `chromium/src/chrome/browser/BUILD.gn`:在既有 teleport 源加入处(搜索 `teleport/browser/enterprise/teleport_enrollment_gate.cc`)紧邻添加两行:

```
    "//teleport/browser/enterprise/teleport_force_signin.cc",
    "//teleport/browser/enterprise/teleport_force_signin.h",
```

- [ ] **Step 4: 重生 patch 并验证幂等**

```bash
cd /Users/liulichao/workspace/teleport/chromium/src
git diff -- chrome/browser/BUILD.gn > /Users/liulichao/workspace/teleport/.claude/worktrees/voluntary-enrollment-ux/patches/chrome/browser/BUILD.gn.patch
git checkout -- chrome/browser/BUILD.gn
cd /Users/liulichao/workspace/teleport/.claude/worktrees/voluntary-enrollment-ux
python scripts/apply_patches.py
```
Expected: `overlay applied.`(无 fail)

- [ ] **Step 5: 编译冒烟**

Run: `cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome`
Expected: `The build has finished successfully.`(链接进 chrome，验证符号无缺）

- [ ] **Step 6: Commit**

```bash
git -C /Users/liulichao/workspace/teleport/.claude/worktrees/voluntary-enrollment-ux add src/browser/enterprise/teleport_force_signin.h src/browser/enterprise/teleport_force_signin.cc patches/chrome/browser/BUILD.gn.patch
git -C /Users/liulichao/workspace/teleport/.claude/worktrees/voluntary-enrollment-ux commit -m "feat(enrollment): session-frozen RequireEnrollmentGateEnabled predicate"
```

## Task 0.2: gate 默认翻转 + 谓词收口 + 注释订正

**Files:**
- Modify: `src/browser/enterprise/teleport_enrollment_gate.cc`(`ShouldGateProfile`/`ShouldLockProfile` 委托谓词;`RegisterEnrollmentGateLocalStatePrefs` 默认 false)
- Modify: `src/browser/enterprise/teleport_enrollment_gate.h`(注释)
- Modify: `src/common/teleport_pref_names.h`(注释)

**Interfaces:**
- Consumes: `teleport::RequireEnrollmentGateEnabled()`(Task 0.1)
- Produces: `ShouldGateProfile`/`ShouldLockProfile` 语义不变但读点收口;`kRequireEnrollmentToBrowse` 默认 false

- [ ] **Step 1: 改注册默认值**

`src/browser/enterprise/teleport_enrollment_gate.cc` 的 `RegisterEnrollmentGateLocalStatePrefs`:
```cpp
  registry->RegisterBooleanPref(prefs::kRequireEnrollmentToBrowse, false);
```

- [ ] **Step 2: 收口两处内联读**

`ShouldGateProfile` 尾部:
```cpp
bool ShouldGateProfile(Profile* profile) {
  if (!profile || profile->IsOffTheRecord() || !profile->IsRegularProfile()) {
    return false;
  }
  return RequireEnrollmentGateEnabled();
}
```
`ShouldLockProfile` 尾部(保留 entry 判空/未纳管条件,末项换谓词):
```cpp
bool ShouldLockProfile(ProfileAttributesEntry* entry) {
  if (!entry || !entry->GetProfileManagementId().empty()) {
    return false;
  }
  return RequireEnrollmentGateEnabled();
}
```
文件顶部 include 增加 `#include "teleport/browser/enterprise/teleport_force_signin.h"`;若 `g_browser_process`/`PrefService` 已不再直接使用可删对应 include(编译报未使用则删)。

- [ ] **Step 3: 订正注释**

`teleport_enrollment_gate.h` 的 `RegisterEnrollmentGateLocalStatePrefs` 注释「defaults to true = secure default」→ 改为:
```cpp
// Registers the gate's local_state prefs: kRequireEnrollmentToBrowse (defaults
// to false = BYOD-first; managed deployments opt in via policy/machine config)
// and kEnrolledDeploymentDomain (the domain D last enrolled against, §4.5).
```
`teleport_enrollment_gate.h` 的 `MaybeHandleDomainMigration`/`PendingDomainMigrationFrom` 注释里「re-locks … can never browse」条件化为「when the gate is enabled, re-locks …」。
`teleport_pref_names.h` 的 `kRequireEnrollmentToBrowse` 注释:
```cpp
// local_state bool. false (BYOD-first default) = browsing allowed without
// enrollment; true = unmanaged devices are force-signin-locked into the
// enrollment picker. Single source of truth for the enrollment gate.
```

- [ ] **Step 4: 编译**

Run: `autoninja -C out/mac/arm64/dev teleport_unittests`
Expected: 编译通过(现有 gate_logic 单测不读默认值,不受影响)。

- [ ] **Step 5: 跑现有 gtest 确认无回归**

Run: `out/mac/arm64/dev/teleport_unittests --gtest_filter=*EnrollmentGate*:*GateLogic*`
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git -C <worktree> add src/browser/enterprise/teleport_enrollment_gate.cc src/browser/enterprise/teleport_enrollment_gate.h src/common/teleport_pref_names.h
git -C <worktree> commit -m "feat(enrollment): flip gate default to false, delegate to frozen predicate"
```

## Task 0.3: 菜单显隐纯逻辑 `ShouldShowTeleportSigninEntry`(TDD)

**Files:**
- Create: `src/common/teleport_signin_entry_logic.h`
- Create: `src/common/teleport_signin_entry_logic.cc`
- Create: `src/common/teleport_signin_entry_logic_unittest.cc`
- Modify: `src/BUILD.gn`(`//teleport` source_set sources + `teleport_unittests` sources)

**Interfaces:**
- Produces: `bool teleport::ShouldShowTeleportSigninEntry(bool is_enrolled, bool is_regular_profile, bool is_web_app);`

- [ ] **Step 1: 写失败测试**

```cpp
// src/common/teleport_signin_entry_logic_unittest.cc
// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/common/teleport_signin_entry_logic.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportSigninEntryLogicTest, ShownForUnenrolledRegularNonWebApp) {
  EXPECT_TRUE(ShouldShowTeleportSigninEntry(
      /*is_enrolled=*/false, /*is_regular_profile=*/true, /*is_web_app=*/false));
}

TEST(TeleportSigninEntryLogicTest, HiddenWhenEnrolled) {
  EXPECT_FALSE(ShouldShowTeleportSigninEntry(true, true, false));
}

TEST(TeleportSigninEntryLogicTest, HiddenForNonRegularProfile) {
  EXPECT_FALSE(ShouldShowTeleportSigninEntry(false, false, false));
}

TEST(TeleportSigninEntryLogicTest, HiddenInWebApp) {
  EXPECT_FALSE(ShouldShowTeleportSigninEntry(false, true, true));
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: 创建 header + 实现**

```cpp
// src/common/teleport_signin_entry_logic.h
// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_COMMON_TELEPORT_SIGNIN_ENTRY_LOGIC_H_
#define TELEPORT_COMMON_TELEPORT_SIGNIN_ENTRY_LOGIC_H_

namespace teleport {

// Whether the profile menu should show the Teleport "Sign in" entry (a
// voluntary in-place enrollment CTA). Shown only for an unenrolled, regular
// (non-OTR/non-system) profile in a normal (non-web-app) browser window. An
// enrolled profile instead shows the "managed by" header; a web-app window's
// menu carries no feature buttons upstream, so it gets no entry either.
bool ShouldShowTeleportSigninEntry(bool is_enrolled,
                                   bool is_regular_profile,
                                   bool is_web_app);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_SIGNIN_ENTRY_LOGIC_H_
```
```cpp
// src/common/teleport_signin_entry_logic.cc
// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/common/teleport_signin_entry_logic.h"

namespace teleport {

bool ShouldShowTeleportSigninEntry(bool is_enrolled,
                                   bool is_regular_profile,
                                   bool is_web_app) {
  return !is_enrolled && is_regular_profile && !is_web_app;
}

}  // namespace teleport
```

- [ ] **Step 3: 接线 BUILD.gn**

`src/BUILD.gn`：在 `source_set("teleport")` 的 `sources` 列表(`teleport_enrollment_gate_logic.cc/.h` 附近)加:
```
    "common/teleport_signin_entry_logic.cc",
    "common/teleport_signin_entry_logic.h",
```
在 `test("teleport_unittests")` 的 `sources` 列表(`teleport_enrollment_gate_logic_unittest.cc` 附近)加:
```
    "common/teleport_signin_entry_logic_unittest.cc",
```

- [ ] **Step 4: 应用 overlay(src 改动经 symlink 生效)+ 构建测试确认先失败后通过**

先确认测试确实测到新代码:
```bash
cd <worktree> && python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter=TeleportSigninEntryLogicTest.*
```
Expected: 4 tests PASS。(TDD 红:若想验证红,先只加 unittest + header 声明不加实现,`autoninja` 链接失败;为节流合并为一次绿。)

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add src/common/teleport_signin_entry_logic.h src/common/teleport_signin_entry_logic.cc src/common/teleport_signin_entry_logic_unittest.cc src/BUILD.gn
git -C <worktree> commit -m "feat(enrollment): pure ShouldShowTeleportSigninEntry predicate + gtest"
```

---

# Phase 1 — force-signin 动态耦合(复活 Layer-1)

## Task 1.1: `IsForceSigninEnabled()` OR gate

**Files:**
- Create: `patches/chrome/browser/signin/signin_util.cc.patch`

**Interfaces:**
- Consumes: `teleport::RequireEnrollmentGateEnabled()`

- [ ] **Step 1: apply_patches 确保基线**

```bash
cd <worktree> && python scripts/apply_patches.py
```

- [ ] **Step 2: edit-live `chrome/browser/signin/signin_util.cc`**

在文件顶部 include 区加 `#include "teleport/browser/enterprise/teleport_force_signin.h"`。把 `IsForceSigninEnabled()` 的 `return` 改为(保持上游缓存结构不动,仅出口 OR):
```cpp
  return (g_is_force_signin_enabled_cache == ENABLE) ||
         teleport::RequireEnrollmentGateEnabled();
```
(上游 `else { return false; }` 早退不动——此时 teleport 快照也读不到 local_state,返回 false 一致。)

- [ ] **Step 3: 生成 patch + revert + 验证**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/signin/signin_util.cc > <worktree>/patches/chrome/browser/signin/signin_util.cc.patch
git checkout -- chrome/browser/signin/signin_util.cc
cd <worktree> && python scripts/apply_patches.py
```
Expected: `overlay applied.`

- [ ] **Step 4: 构建**

Run: `autoninja -C out/mac/arm64/dev chrome`
Expected: 成功。

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add patches/chrome/browser/signin/signin_util.cc.patch
git -C <worktree> commit -m "feat(enrollment): couple force-signin to enrollment gate predicate"
```

## Task 1.2: `BrowserSignin` kForced 去 GAIA 化

**Files:**
- Create: `patches/chrome/browser/policy/browser_signin_policy_handler.cc.patch`

- [ ] **Step 1: edit-live `chrome/browser/policy/browser_signin_policy_handler.cc`**

`ApplyPolicySettings` 的 `switch` 中删除 `kForced` case 对 `kForceBrowserSignin` 的写入,让它直接落到 `kEnabled`(仍设 `kSigninAllowedOnNextStartup=true`)。改为:
```cpp
    case BrowserSigninMode::kForced:
      // teleport: this product has no GAIA sign-in; the upstream Force mode
      // would force-signin-lock every profile into an unreachable Google login
      // dead-end. The enrollment gate (kRequireEnrollmentToBrowse) is the sole
      // source of forced enrollment, so Force is neutralized to Enable here.
      [[fallthrough]];
    case BrowserSigninMode::kEnabled:
```
(删掉原 `#if !BUILDFLAG(IS_CHROMEOS) prefs->SetValue(prefs::kForceBrowserSignin, true); #endif` 三行。)

- [ ] **Step 2: 生成 patch + revert + 验证**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/policy/browser_signin_policy_handler.cc > <worktree>/patches/chrome/browser/policy/browser_signin_policy_handler.cc.patch
git checkout -- chrome/browser/policy/browser_signin_policy_handler.cc
cd <worktree> && python scripts/apply_patches.py
```
Expected: `overlay applied.`

- [ ] **Step 3: 构建 + Commit**

```bash
autoninja -C out/mac/arm64/dev chrome   # 成功
git -C <worktree> add patches/chrome/browser/policy/browser_signin_policy_handler.cc.patch
git -C <worktree> commit -m "feat(enrollment): neutralize BrowserSignin=Forced (no GAIA in this product)"
```

---

# Phase 2 — guest 动态禁用(四点覆盖)

## Task 2.1: guest 两谓词点

**Files:**
- Create: `patches/chrome/browser/profiles/profiles_state.cc.patch`(**内容与 dfef774 删掉的旧版无关**)

- [ ] **Step 1: edit-live `chrome/browser/profiles/profiles_state.cc`**

顶部 include 加 `#include "teleport/browser/enterprise/teleport_force_signin.h"`。
① `IsGuestModeGloballyDisabledInternal()` 尾部:
```cpp
bool IsGuestModeGloballyDisabledInternal() {
  const PrefService* const pref_service = g_browser_process->local_state();
  DCHECK(pref_service);
  // teleport: gate ON force-disables guest — a Guest OTR profile is invisible to
  // the enrollment gate (ShouldGateProfile excludes OTR) and would be an escape
  // hatch to unmanaged browsing.
  if (teleport::RequireEnrollmentGateEnabled()) {
    return true;
  }
  return !pref_service->GetBoolean(prefs::kBrowserGuestModeEnabled);
}
```
② `IsGuestModeRequested(...)` 的 `if (command_line.HasSwitch(kGuest) || ...enforced)` 块内,在 `GetBoolean(kBrowserGuestModeEnabled)` 判定前插:
```cpp
    // teleport: --guest / BrowserGuestModeEnforced must not bypass the gate.
    if (teleport::RequireEnrollmentGateEnabled()) {
      if (show_warning) {
        LOG(WARNING) << "Guest mode disabled by Teleport enrollment gate.";
      }
      return false;
    }
```

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/profiles/profiles_state.cc > <worktree>/patches/chrome/browser/profiles/profiles_state.cc.patch
git checkout -- chrome/browser/profiles/profiles_state.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: `overlay applied.` + 构建成功。

- [ ] **Step 3: Commit**

```bash
git -C <worktree> add patches/chrome/browser/profiles/profiles_state.cc.patch
git -C <worktree> commit -m "feat(enrollment): gate-couple guest availability (two predicate points)"
```

## Task 2.2: guest 动作层 fail-closed 守卫

**Files:**
- Create: `patches/chrome/browser/profiles/profile_window.cc.patch`
- Modify: `patches/chrome/browser/ui/webui/signin/profile_picker_handler.cc.patch`(扩展)

- [ ] **Step 1: edit-live `chrome/browser/profiles/profile_window.cc`**

`profiles::SwitchToGuestProfile(...)` 函数体入口(顶部 include 加 `#include "chrome/browser/profiles/profiles_state.h"` 若未含)插:
```cpp
  // teleport: IDC_OPEN_GUEST_PROFILE is unconditionally enabled upstream; block
  // the action itself when guest is disabled (gate ON) rather than relying on
  // hidden buttons.
  if (!profiles::IsGuestModeEnabled()) {
    return;
  }
```

- [ ] **Step 2: edit-live `chrome/browser/ui/webui/signin/profile_picker_handler.cc`**

`ProfilePickerHandler::HandleLaunchGuestProfile(...)` 入口插同样守卫:
```cpp
  // teleport: the upstream TODO acknowledges this IPC does no server-side guest
  // policy check. Enforce it here (gate ON disables guest).
  if (!profiles::IsGuestModeEnabled()) {
    return;
  }
```
(该文件已有 teleport 头 include;若缺 `profiles_state.h` 则补。)

- [ ] **Step 3: 生成/扩展 patch + revert + 验证 + 构建**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/profiles/profile_window.cc > <worktree>/patches/chrome/browser/profiles/profile_window.cc.patch
git diff -- chrome/browser/ui/webui/signin/profile_picker_handler.cc > <worktree>/patches/chrome/browser/ui/webui/signin/profile_picker_handler.cc.patch
git checkout -- chrome/browser/profiles/profile_window.cc chrome/browser/ui/webui/signin/profile_picker_handler.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: `overlay applied.` + 构建成功。
（注意:profile_picker_handler.cc.patch 是**扩展**既有文件,重生前必须已 `apply_patches` 使前序 hunk 在场。)

- [ ] **Step 4: Commit**

```bash
git -C <worktree> add patches/chrome/browser/profiles/profile_window.cc.patch patches/chrome/browser/ui/webui/signin/profile_picker_handler.cc.patch
git -C <worktree> commit -m "feat(enrollment): fail-closed guest action guards (command + picker IPC)"
```

---

# Phase 3 — Path A 清除 + GAIA 结构性钉死

## Task 3.1: 删除 Path A 启动重定向 patch

**Files:**
- Delete: `patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch`

- [ ] **Step 1: 删除并验证幂等**

```bash
cd <worktree>
git rm patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch
python scripts/apply_patches.py
```
Expected: `overlay applied.`(该文件不再被 patch;`ShouldGateProfile`/`IsEnrolled`/`EnterpriseEnrollUrl` 其余使用点仍在,无孤儿。)

- [ ] **Step 2: 构建 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome   # 成功
git -C <worktree> commit -m "refactor(enrollment): remove Path-A startup enroll-tab redirect (dead under picker model)"
```

## Task 3.2: `CanEnableDiceForBuild()=false` 结构钉死

**Files:**
- Create: `patches/chrome/browser/signin/account_consistency_mode_manager.cc.patch`

- [ ] **Step 1: edit-live `chrome/browser/signin/account_consistency_mode_manager.cc`**

`CanEnableDiceForBuild()` 函数体开头插(在 `g_ignore_missing_oauth_client_for_testing` 判断之前,保留 testing 逃逸):
```cpp
  // teleport: this product ships no Google OAuth client and has no GAIA sign-in.
  // Pin DICE off structurally so the GAIA suppression across menu/settings/
  // picker/FRE never depends on the accidental "no key baked" fact.
  if (!g_ignore_missing_oauth_client_for_testing) {
    return false;
  }
```

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/signin/account_consistency_mode_manager.cc > <worktree>/patches/chrome/browser/signin/account_consistency_mode_manager.cc.patch
git checkout -- chrome/browser/signin/account_consistency_mode_manager.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: `overlay applied.` + 构建成功。

- [ ] **Step 3: 活体冒烟(结构钉死断言)**

启动 dev 构建全新 user-data-dir,打开 profile 菜单、`chrome://settings`、picker「添加」:确认无「Sign in」/「Google services settings」/GAIA 建号面。（此步与 Phase 3.3、Phase 4 完成后再统一在 §6 冒烟第 7 条复核;此处只需构建通过即可提交。）

- [ ] **Step 4: Commit**

```bash
git -C <worktree> add patches/chrome/browser/signin/account_consistency_mode_manager.cc.patch
git -C <worktree> commit -m "feat(enrollment): pin CanEnableDiceForBuild() false — structural GAIA suppression"
```

## Task 3.3: 设置页 dasherless 残留抑制

**Files:**
- Create: `patches/chrome/browser/resources/settings/people_page/people_page.html.patch`

- [ ] **Step 1: 定位 dasherless 通知**

Run: `grep -n "sync-not-allowed\|isDasherlessProfile\|SYNC_UNAVAILABLE_FOR_NON_GOOGLE" chromium/src/chrome/browser/resources/settings/people_page/people_page.html`
读出承载「isn't associated with Google」的 `<div id="sync-not-allowed">`(约 155-162 行)及其 `hidden` 绑定表达式。

- [ ] **Step 2: edit-live 隐藏该块**

在 `people_page.html` 该 `#sync-not-allowed` 节点的 `hidden$="[[...]]"` 绑定改为对 dasherless 恒真隐藏(最简:给该节点加 `hidden`)。若绑定复杂,改条件为 `hidden="[[isDasherlessProfile_]]"` 取反其显示条件——以「dasherless 时不渲染该 Google 文案」为准。具体表达式按 Step 1 读出的实际绑定订正,注释:
```html
<!-- teleport: our enrolled profiles are dasherless; suppress the upstream
     "isn't associated with Google … sync unavailable" notice (matches the
     profile-menu dasherless subtitle suppression). -->
```

- [ ] **Step 3: 生成 patch + revert + 验证 + 构建**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/resources/settings/people_page/people_page.html > <worktree>/patches/chrome/browser/resources/settings/people_page/people_page.html.patch
git checkout -- chrome/browser/resources/settings/people_page/people_page.html
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: `overlay applied.` + 构建成功。

- [ ] **Step 4: Commit**

```bash
git -C <worktree> add patches/chrome/browser/resources/settings/people_page/people_page.html.patch
git -C <worktree> commit -m "feat(enrollment): suppress dasherless 'not a Google account' notice in settings"
```

---

# Phase 4 — profile 菜单登录入口(核心 UI)

## Task 4.1: 新增品牌串(grd 英文源 + zh-CN xtb)

**Files:**
- Create/Modify: `patches/chrome/app/generated_resources.grd.patch`(新增 3 个 message:登录按钮、登录 subtitle、已纳管 header)
- Create/Modify: 对应 `patches/chrome/app/resources/generated_resources_zh-CN.xtb.patch`
- Modify: `scripts/branding_strings.py`(扩展生成新 message 的 xtb entry id 哈希)
- Modify/Create: `scripts/tests/test_branding_strings.py`(pytest 覆盖新增)

**Interfaces:**
- Produces: `IDS_TELEPORT_PROFILE_MENU_SIGNIN_BUTTON`、`IDS_TELEPORT_PROFILE_MENU_SIGNIN_SUBTITLE`、`IDS_TELEPORT_PROFILE_MENU_MANAGED_HEADER`

- [ ] **Step 1: 确认 grit id 哈希算法**

阅读 `scripts/branding_strings.py`,定位它计算既有 message 的 xtb `id`(grit fingerprint,通常 `grit.extern.FP.FingerPrint(message_content)` 或等价 64-bit)。抽出为可复用函数 `xtb_id_for(message_text: str) -> str`。

- [ ] **Step 2: 写 pytest(先失败)**

```python
# scripts/tests/test_branding_strings.py (新增用例)
def test_xtb_id_for_known_message():
    # 用一条已在仓库 grd/xtb 中成对存在的 message 验证哈希函数与 grit 一致
    # (从现有 generated_resources.grd 取一条 message 文本 + 其 zh-CN.xtb id)
    assert xtb_id_for("<已知英文文本>") == "<已知 xtb id>"
```
Run: `uv run pytest scripts/tests/test_branding_strings.py -k xtb_id_for -v` → 期望 FAIL（函数未抽出/未导出）。

- [ ] **Step 3: 实现抽出的哈希函数,pytest 转绿**

Run: `uv run pytest scripts/tests/test_branding_strings.py -k xtb_id_for -v` → PASS。

- [ ] **Step 4: edit-live 加 3 个 message 到 grd**

`chrome/app/generated_resources.grd` 合适分组内加(英文源文本;`闪现` 品牌名经既有 rebrand 管线在 chromium_strings 处理,这里用占位 `Teleport` 由 branding_strings 统一替换,或直接引用产品名 placeholder——按仓库既有 rebrand 约定):
```xml
<message name="IDS_TELEPORT_PROFILE_MENU_SIGNIN_BUTTON" desc="Profile menu button that starts Teleport enterprise enrollment sign-in.">
  Sign in
</message>
<message name="IDS_TELEPORT_PROFILE_MENU_SIGNIN_SUBTITLE" desc="Subtitle under the Teleport profile-menu sign-in button explaining managed enrollment.">
  Sign in to let your organization manage this browser
</message>
<message name="IDS_TELEPORT_PROFILE_MENU_MANAGED_HEADER" desc="Profile menu header shown for a Teleport-enrolled (managed) profile. $1 is the managing organization/domain.">
  Managed by <ph name="ORGANIZATION">$1<ex>example.com</ex></ph>
</message>
```

- [ ] **Step 5: 用哈希函数生成 zh-CN xtb 三条并 edit-live 加入 `generated_resources_zh-CN.xtb`**

```xml
<translation id="<xtb_id_for('Sign in')>">登录</translation>
<translation id="<xtb_id_for('Sign in to let your organization manage this browser')>">登录后由你的组织统一管理此浏览器</translation>
<translation id="<xtb_id_for('Managed by <ORGANIZATION>')>">由 <ph name="ORGANIZATION"/> 管理</translation>
```
（xtb 的 placeholder 表达按 grit 规范;id 用 Step 3 函数算准。）

- [ ] **Step 6: 生成两 patch + revert + 验证幂等**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/app/generated_resources.grd > <worktree>/patches/chrome/app/generated_resources.grd.patch
git diff -- chrome/app/resources/generated_resources_zh-CN.xtb > <worktree>/patches/chrome/app/resources/generated_resources_zh-CN.xtb.patch
git checkout -- chrome/app/generated_resources.grd chrome/app/resources/generated_resources_zh-CN.xtb
cd <worktree> && python scripts/apply_patches.py
```
Expected: `overlay applied.`(grit 编译 message 无 id 冲突。)

- [ ] **Step 7: 构建(grit 重编译)+ pytest 全绿 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome   # grit 通过、成功
cd <worktree> && uv run pytest -q   # 全绿
git -C <worktree> add patches/chrome/app/generated_resources.grd.patch patches/chrome/app/resources/generated_resources_zh-CN.xtb.patch scripts/branding_strings.py scripts/tests/test_branding_strings.py
git -C <worktree> commit -m "feat(i18n): add Teleport profile-menu sign-in/managed strings (grd + zh-CN xtb)"
```

## Task 4.2: 菜单登录 action helper

**Files:**
- Create: `src/browser/enterprise/teleport_voluntary_signin.h`
- Create: `src/browser/enterprise/teleport_voluntary_signin.cc`
- Modify: `patches/chrome/browser/ui/BUILD.gn.patch`(把两文件加入 `//chrome/browser/ui` 编译;该 target 已 dep `//teleport`)

**Interfaces:**
- Produces: `void teleport::OpenVoluntaryEnrollmentTab(Browser* browser);`（关闭菜单由调用方负责;此函数只在 browser 的当前窗口开 `EnterpriseEnrollUrl()` 前台 tab）

- [ ] **Step 1: 创建 header + 实现**

```cpp
// src/browser/enterprise/teleport_voluntary_signin.h
// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_VOLUNTARY_SIGNIN_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_VOLUNTARY_SIGNIN_H_

class Browser;

namespace teleport {

// Opens the Teleport enrollment start page (EnterpriseEnrollUrl()) in a new
// foreground tab of `browser`. The OIDC capture throttle then completes in-place
// enrollment (with the upstream managed-disclosure dialog, §4.7). Voluntary
// (gate-OFF) sign-in entry from the profile menu.
void OpenVoluntaryEnrollmentTab(Browser* browser);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_VOLUNTARY_SIGNIN_H_
```
```cpp
// src/browser/enterprise/teleport_voluntary_signin.cc
// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_voluntary_signin.h"

#include "chrome/browser/ui/browser.h"
#include "chrome/browser/ui/browser_navigator.h"
#include "chrome/browser/ui/browser_navigator_params.h"
#include "teleport/common/teleport_enterprise_urls.h"
#include "ui/base/page_transition_types.h"
#include "url/gurl.h"

namespace teleport {

void OpenVoluntaryEnrollmentTab(Browser* browser) {
  if (!browser) {
    return;
  }
  NavigateParams params(browser, GURL(EnterpriseEnrollUrl()),
                        ui::PAGE_TRANSITION_LINK);
  params.disposition = WindowOpenDisposition::NEW_FOREGROUND_TAB;
  Navigate(&params);
}

}  // namespace teleport
```

- [ ] **Step 2: 接线 ui/BUILD.gn**

edit-live `chrome/browser/ui/BUILD.gn`,在既有 teleport 源加入处(搜索 `teleport_version_updater` 或现有 `//teleport` 源列表)加两行:
```
    "//teleport/browser/enterprise/teleport_voluntary_signin.cc",
    "//teleport/browser/enterprise/teleport_voluntary_signin.h",
```
(此为**扩展** `ui/BUILD.gn.patch`——先 apply_patches 使前序 hunk 在场,再 diff 重生。)

- [ ] **Step 3: 生成/扩展 patch + revert + 验证 + 构建 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/BUILD.gn > <worktree>/patches/chrome/browser/ui/BUILD.gn.patch
git checkout -- chrome/browser/ui/BUILD.gn
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add src/browser/enterprise/teleport_voluntary_signin.h src/browser/enterprise/teleport_voluntary_signin.cc patches/chrome/browser/ui/BUILD.gn.patch
git -C <worktree> commit -m "feat(enrollment): OpenVoluntaryEnrollmentTab helper"
```

## Task 4.3: 菜单 `GetIdentitySectionParams` 分支(登录按钮 + 已纳管 header)

**Files:**
- Modify: `patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch`(扩展;现仅 dasherless subtitle 抑制 hunk)

**Interfaces:**
- Consumes: `teleport::ShouldShowTeleportSigninEntry`、`teleport::IsEnrolled`、`teleport::OpenVoluntaryEnrollmentTab`、`teleport::EnterpriseEnrollUrl`、`GetAccountManagerIdentity`、`prefs::kEnrolledDeploymentDomain`

- [ ] **Step 1: apply_patches 基线 + edit-live `profile_menu_view.cc`**

顶部 include 加:
```cpp
#include "teleport/browser/enterprise/teleport_enrollment_gate.h"
#include "teleport/browser/enterprise/teleport_voluntary_signin.h"
#include "teleport/common/teleport_pref_names.h"
#include "teleport/common/teleport_signin_entry_logic.h"
#include "components/prefs/pref_service.h"
```
在 `GetIdentitySectionParams` 中,**web-app early-return 之后、dasherless 抑制 hunk 之前**插入 teleport 分支。定位:上游 `if (web_app::AppBrowserController::IsWebApp(&browser())) { ... return params; }` 块之后。插入:
```cpp
  // teleport: replace the upstream GAIA signed-out / managed-badge logic with
  // the Teleport enrollment identity. Placed AFTER the web-app early-return
  // (PWA menus carry no CTA) and BEFORE the dasherless subtitle suppression
  // (which becomes a fallback for the enrolled-but-store-not-loaded window).
  {
    const bool is_enrolled = teleport::IsEnrolled(&profile());
    if (teleport::ShouldShowTeleportSigninEntry(
            is_enrolled, profile().IsRegularProfile(),
            web_app::AppBrowserController::IsWebApp(&browser()))) {
      params.subtitle = l10n_util::GetStringUTF16(
          IDS_TELEPORT_PROFILE_MENU_SIGNIN_SUBTITLE);
      params.button_text = l10n_util::GetStringUTF16(
          IDS_TELEPORT_PROFILE_MENU_SIGNIN_BUTTON);
      params.button_action = base::BindRepeating(
          [](base::WeakPtr<ProfileMenuView> menu) {
            if (!menu) {
              return;
            }
            Browser* browser = menu->browser_for_testing_or_real();
            menu->GetWidget()->CloseWithReason(
                views::Widget::ClosedReason::kUnspecified);
            teleport::OpenVoluntaryEnrollmentTab(browser);
          },
          weak_factory_.GetWeakPtr());
      return params;
    }
    if (is_enrolled) {
      std::u16string org = base::UTF8ToUTF16(
          policy::GetAccountManagerIdentity(&profile()).value_or(std::string()));
      if (org.empty()) {
        PrefService* local_state = g_browser_process->local_state();
        if (local_state) {
          org = base::UTF8ToUTF16(
              local_state->GetString(teleport::prefs::kEnrolledDeploymentDomain));
        }
      }
      params.header_string = l10n_util::GetStringFUTF16(
          IDS_TELEPORT_PROFILE_MENU_MANAGED_HEADER, org);
      params.header_image = ui::ImageModel::FromVectorIcon(
          GetManagedUiIcon(&profile()), ui::kColorIcon);
      params.header_action = base::BindRepeating(
          &ProfileMenuView::OnProfileManagementButtonClicked,
          base::Unretained(this));
      return params;
    }
  }
```
注:`browser_for_testing_or_real()` 是占位——实查 `ProfileMenuView` 是否已有 `browser()`/`browser_for_testing()` 访问器(`profile_menu_view.h`),用现成者;若 action 内拿 Browser 不便,改为在 bind 时捕获 `&browser()` 的 raw ptr 前先 `base::Unretained` 不安全,故用 `chrome::FindBrowserWithTab` 或菜单持有的 browser 引用——plan 执行时按 `profile_menu_view.h` 实际 API 定稿(菜单本身持有 `Browser& browser_`,可 `&browser()`)。**简化定稿**:action 直接 `teleport::OpenVoluntaryEnrollmentTab(&browser()); GetWidget()->CloseWithReason(...)`,`this` 用 `base::Unretained(this)`(菜单在气泡关闭前存活,同上游 `OnSigninButtonClicked` 范式)。
`GetAccountManagerIdentity` 需 include `#include "chrome/browser/enterprise/browser_management/management_service_factory.h"` 或其声明处(定位:`grep -rn "GetAccountManagerIdentity" chromium/src/chrome/browser/enterprise` 取实际头);若该 API 名不符,用 `policy::GetManagedBy(profile().GetCloudPolicyManager())`(评审给出的等价链)。

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/views/profiles/profile_menu_view.cc > <worktree>/patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch
git checkout -- chrome/browser/ui/views/profiles/profile_menu_view.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: `overlay applied.` + 构建成功。

- [ ] **Step 3: 活体冒烟(菜单不崩 + 按钮出现)**

启动 dev 全新 user-data-dir(gate OFF 默认)→ 打开 profile 菜单 → 见「登录」按钮 + subtitle,不崩(验证 subtitle CHECK 已满足)。

- [ ] **Step 4: Commit**

```bash
git -C <worktree> add patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch
git -C <worktree> commit -m "feat(enrollment): profile-menu Teleport sign-in entry + managed header"
```

## Task 4.4: feature 区抑制「Google services settings」行

**Files:**
- Modify: `patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch`(继续扩展)

- [ ] **Step 1: edit-live `MaybeBuildChromeAccountSettingsButtonWithSync`**

定位 `should_show_settings_button = 有账号 || !kSigninAllowed`(约 :1026-1032)。对 teleport regular profile 抑制 `!kSigninAllowed` 触发臂:
```cpp
  // teleport: with kSigninAllowed pinned false (§4.8) this button would appear
  // for every profile; our profiles have no Google services page, so drop it.
  if (teleport::ShouldGateProfileOrEnrolledRegular(&profile())) {
    return;
  }
```
其中判定用现成谓词组合(regular profile 即抑制):最简直接
```cpp
  if (profile().IsRegularProfile()) {
    return;
  }
```
(本产品所有 regular profile 都不该有 Google services 行;guest/system 不走此函数。)注释说明。

- [ ] **Step 2: 生成 patch(同一文件累积)+ revert + 验证 + 构建**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/views/profiles/profile_menu_view.cc > <worktree>/patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch
git checkout -- chrome/browser/ui/views/profiles/profile_menu_view.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: `overlay applied.` + 构建成功;菜单不再有「Google services settings」行。

- [ ] **Step 3: Commit**

```bash
git -C <worktree> add patches/chrome/browser/ui/views/profiles/profile_menu_view.cc.patch
git -C <worktree> commit -m "feat(enrollment): suppress Google-services-settings row in profile menu"
```

## Task 4.5: registrar 成功写 display-name/email prefs

**Files:**
- Modify: `src/browser/enterprise/teleport_oidc_inplace_registrar.cc`

- [ ] **Step 1: 在 `ApplyManagedAttributes` 成功路径写两 prefs**

定位注册器写 `SetProfileManagementId` / `SetDasherlessManagement(true)` 处(约 :155-180),追加(数据来自成员 `user_display_name_` / `user_email_`,若成员名不同按实读订正):
```cpp
  // teleport: mirror the upstream OIDC-managed profile's identity prefs so the
  // profile menu a11y title shows the managed identity instead of the "not
  // signed in" local-profile string.
  if (PrefService* prefs = profile_->GetPrefs()) {
    prefs->SetString(enterprise_signin::prefs::kProfileUserDisplayName,
                     user_display_name_);
    prefs->SetString(enterprise_signin::prefs::kProfileUserEmail, user_email_);
  }
```
include 加 `#include "chrome/browser/enterprise/signin/enterprise_signin_prefs.h"`(定位实际头:`grep -rn kProfileUserDisplayName chromium/src/chrome/browser/enterprise/signin`)。

- [ ] **Step 2: apply_patches + 构建 + Commit**

```bash
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add src/browser/enterprise/teleport_oidc_inplace_registrar.cc
git -C <worktree> commit -m "feat(enrollment): registrar writes profile display-name/email prefs"
```

---

# Phase 5 — OIDC capture 改道解耦 + 披露 + 失败反馈

## Task 5.1: 改道谓词与 gate 解耦(修 blocker B2)

**Files:**
- Modify: `patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch`(扩展)

- [ ] **Step 1: apply_patches 基线 + edit-live 两处改道条件**

把两处(URL 路径 :398 区、header 路径 :507 区)的
```cpp
if (teleport::ShouldGateProfile(profile) && !teleport::IsEnrolled(profile)) {
```
改为(解耦 gate,只看未纳管):
```cpp
if (!teleport::IsEnrolled(profile)) {
```
两处注释同步:强调「teleport 构建内凡命中 D 域 register-handler capture 一律就地纳管;上游 new-profile interceptor 在本产品不可达」。

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc > <worktree>/patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch
git checkout -- chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: `overlay applied.` + 成功。

- [ ] **Step 3: Commit**

```bash
git -C <worktree> add patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch
git -C <worktree> commit -m "fix(enrollment): decouple OIDC capture reroute from gate (voluntary flow reaches in-place registrar)"
```

## Task 5.2: 自愿 tab 流失败反馈(EnrollmentDone 兜底)

**Files:**
- Modify: `patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch`(继续扩展)

**背景:** 自愿 tab 流无 `EnrollmentDoneUserData` → `Take()` 返回 `DoNothing` → registrar 失败时零反馈。给 tab 流装一个「失败则导航到错误页」的 done 回调。

- [ ] **Step 1: edit-live**

在两处 reroute 调用点,把 `EnrollmentDoneUserData::Take(web_contents)` 的结果先探测是否为空(picker 流才装了它)。改为构造一个复合回调:若 UserData 存在用它(picker 流),否则用「tab 流失败导航到 enrollment 错误页」的回调:
```cpp
      content::WebContents* wc = navigation_handle()->GetWebContents();
      teleport::EnrollmentDoneCallback done =
          teleport::EnrollmentDoneUserData::HasCallback(wc)
              ? teleport::EnrollmentDoneUserData::Take(wc)
              : base::BindOnce(&teleport::OnVoluntaryEnrollmentDone,
                               wc->GetWeakPtr());
```
`teleport::OnVoluntaryEnrollmentDone(base::WeakPtr<WebContents>, EnrollmentResult)`:失败时 `LoadURL(EnrollmentErrorUrl())`(或就地 enroll 页错误锚点),成功 no-op(页面已在服务端成功页)。此函数放 `teleport_voluntary_signin.{h,cc}`(Task 4.2 文件),`EnrollmentErrorUrl()` 若无则复用 picker 流的错误 URL 常量;定位:`grep -rn "EnrollmentErrorUrl\|EnrollmentError" src/`。
`EnrollmentDoneUserData::HasCallback` 需在 Task 5.2a 补该静态方法(见下)。

- [ ] **Step 1a(前置): 给 EnrollmentDoneUserData 加 HasCallback**

`src/browser/enterprise/teleport_enrollment_done_user_data.{h,cc}` 加:
```cpp
  // True iff a callback is currently attached to `web_contents`.
  static bool HasCallback(content::WebContents* web_contents);
```
实现:`return FromWebContents(web_contents) != nullptr;`

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc > <worktree>/patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch
git checkout -- chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add patches/.../oidc_auth_response_capture_navigation_throttle.cc.patch src/browser/enterprise/teleport_enrollment_done_user_data.h src/browser/enterprise/teleport_enrollment_done_user_data.cc src/browser/enterprise/teleport_voluntary_signin.h src/browser/enterprise/teleport_voluntary_signin.cc
git -C <worktree> commit -m "feat(enrollment): voluntary tab flow failure feedback (error page on registrar failure)"
```

## Task 5.3(SPIKE + 落地): 自愿流复用上游披露对话框

**Files:**
- Modify: `patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch`(继续扩展)
- 可能 Modify: `src/browser/enterprise/teleport_voluntary_signin.{h,cc}`

**背景(spec §4.7):** 自愿流(有 Browser)在就地注册前弹上游 `WebSigninInterceptor` 披露气泡;picker 强制流(无 Browser)维持免对话框。判据 = `EnrollmentDoneUserData::HasCallback(wc)`(picker 装了→免对话框;未装→自愿流→弹对话框)。

- [ ] **Step 1: SPIKE — 确认披露气泡可在无 primary account 下驱动**

阅读 `chrome/browser/enterprise/signin/oidc_authentication_signin_interceptor.cc:186-217`(`BubbleParameters` 构造)与 `DiceWebSigninInterceptorDelegate::ShowOidcInterceptionDialog`。确认:①`BubbleParameters` 用 `AccountInfo()` 空账号 + `show_managed_disclaimer=true` 能构造;②对话框「继续」回调可绑到我们的 `EnrollCurrentProfileInPlace` 而非上游注册;③delegate 可从 profile 取得(`DiceWebSigninInterceptorFactory` 或直接 new `DiceWebSigninInterceptorDelegate`)。
**Go/No-Go:**
- GO:能构造 `BubbleParameters` + 拿到 delegate + 绑自定义 proceed 回调 → 落地 Step 2。
- No-Go(气泡机器对 `IdentityManager` primary account 有硬依赖 / delegate 无法脱离上游 interceptor 获取):**回退**——自愿流不弹浏览器对话框,披露改由服务端 enroll 页承载(§5.4 已授权),在 `EnterpriseEnrollUrl` 页文案要求写入 fairyland runbook,本 Task 仅提交 spike 结论注释 + TD 登记,不改代码。**回报证据后继续。**

- [ ] **Step 2(GO 才做): edit-live 在 reroute 前弹对话框**

自愿分支(`!HasCallback(wc)`)在调用 `EnrollCurrentProfileInPlace` 前,先经 delegate 弹披露气泡;proceed→`EnrollCurrentProfileInPlace(...)`;cancel→`Resume()`/`PROCEED` 不纳管、停原页。封装进 `teleport_voluntary_signin.cc` 的:
```cpp
void MaybeShowDisclosureThenEnroll(content::WebContents* wc,
                                   Profile* profile,
                                   ProfileManagementOidcTokens tokens,
                                   std::string issuer_id,
                                   std::string subject_id,
                                   std::string email);
```
气泡文案经 grd 覆写(上游 `IDS_*OIDC*` message 若需改就地纳管措辞,新增或覆写一条,走 Task 4.1 同款 grd/xtb 流程)。

- [ ] **Step 3: 生成 patch + revert + 验证 + 构建 + 活体冒烟**

构建后 gate OFF 菜单登录 → OIDC 全链 → **披露对话框出现**(就地纳管措辞)→ 接受 → 就地纳管(不新建 profile);拒绝 → 停原页。

- [ ] **Step 4: Commit**

```bash
git -C <worktree> add patches/.../oidc_auth_response_capture_navigation_throttle.cc.patch src/browser/enterprise/teleport_voluntary_signin.*
git -C <worktree> commit -m "feat(enrollment): reuse upstream managed-disclosure dialog in voluntary flow"
```

---

# Phase 6 — picker 新建即纳管(§4.6)

## Task 6.1: HandleSelectNewAccount teleport 分支(隐藏创建 → SwitchToEnrollment)

**Files:**
- Modify: `patches/chrome/browser/ui/webui/signin/profile_picker_handler.cc.patch`(扩展)

- [ ] **Step 1: apply_patches 基线 + edit-live 重写 HandleSelectNewAccount teleport 分支**

把现有 no-op 分支(`if (signin_util::IsForceSigninEnabled()) { OnResetPickerButtons(false); return; }`)改为 gate ON 时隐藏创建 + 进 enrollment step:
```cpp
  // teleport: under the enrollment gate, "Add profile" creates a hidden
  // (ephemeral+omitted, auto-locked) profile and routes it straight to the
  // GAIA-free Teleport enrollment step. Success finalizes it (Task 6.2); cancel
  // deletes it via ephemeral semantics (Task 6.3). The upstream GAIA new-profile
  // path is unreachable in this product.
  if (teleport::RequireEnrollmentGateEnabled()) {
    ProfileManager::CreateMultiProfileAsync(
        g_browser_process->profile_manager()->GetProfileAttributesStorage()
            .ChooseNameForNewProfile(),
        /*icon_index=*/0, /*is_hidden=*/true,
        base::BindOnce(&ProfilePickerHandler::OnNewProfileForEnrollmentCreated,
                       weak_factory_.GetWeakPtr()));
    return;
  }
```
新增回调 `OnNewProfileForEnrollmentCreated(Profile*)`:
```cpp
void ProfilePickerHandler::OnNewProfileForEnrollmentCreated(Profile* profile) {
  if (!profile) {
    OnResetPickerButtons(false);
    return;
  }
  ProfilePicker::SwitchToEnrollment(
      profile, base::BindOnce(&ProfilePickerHandler::OnResetPickerButtons,
                              weak_factory_.GetWeakPtr()));
}
```
(`CreateMultiProfileAsync` 精确签名以 M148 为准:`grep -n "CreateMultiProfileAsync" chromium/src/chrome/browser/profiles/profile_manager.h`;`ChooseNameForNewProfile` 同理定位实际 API。)`.h` patch 加回调声明。
**同步重写失实注释**(§4.6.8):删「add-person 默认 false 挡 tile / GAIA CHECK-fail」旧注释。

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/webui/signin/profile_picker_handler.cc > <worktree>/patches/.../profile_picker_handler.cc.patch
git diff -- chrome/browser/ui/webui/signin/profile_picker_handler.h > <worktree>/patches/.../profile_picker_handler.h.patch
git checkout -- chrome/browser/ui/webui/signin/profile_picker_handler.cc chrome/browser/ui/webui/signin/profile_picker_handler.h
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add patches/chrome/browser/ui/webui/signin/profile_picker_handler.cc.patch patches/chrome/browser/ui/webui/signin/profile_picker_handler.h.patch
git -C <worktree> commit -m "feat(enrollment): picker Add-profile creates hidden profile → enrollment step"
```

## Task 6.2: 成功 finalize(去 omitted/ephemeral/命名)

> **实现修正**:下方伪代码调 `SetLocalProfileName()` + 读 `local_state()` 的 `kForceEphemeralProfiles` 均未照抄——实际实现里 profile 已在创建时(`CreateMultiProfileAsync` 的 `ChooseNameForNewProfile()`)取好名,此处再调一次 `SetLocalProfileName` 反而会撞同一 entry 的已占用名、徒然改成下一个编号;`kForceEphemeralProfiles` 是 per-profile pref,正确读法是 `profile->GetPrefs()->GetBoolean(...)` 而非 `local_state()`(会命中未注册 pref)。实际 patch 只做 `SetIsOmitted(false)` + 条件性 `SetIsEphemeral(false)`,详见 `patches/chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc.patch` 内联注释。

**Files:**
- Modify: `patches/chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc.patch`(扩展 `OnEnrollmentSucceeded`)

- [ ] **Step 1: edit-live `OnEnrollmentSucceeded`**

在解锁前加「若是 picker 新增(omitted)则 finalize」:
```cpp
  // teleport: a picker-added profile was created hidden (ephemeral+omitted). On
  // enrollment success, finalize it (name + de-omit + de-ephemeral) so it
  // survives restart; the first (auto-created, non-ephemeral) profile skips this
  // and is just unlocked. Do NOT call upstream FinalizeNewProfileSetup — it
  // CHECK(HasPrimaryAccount) for dasherless under force-signin.
  if (entry->IsOmitted()) {
    entry->SetLocalProfileName(
        g_browser_process->profile_manager()->GetProfileAttributesStorage()
            .ChooseNameForNewProfile(),
        /*is_default_name=*/false);
    entry->SetIsOmitted(false);
    if (!g_browser_process->local_state()->GetBoolean(
            prefs::kForceEphemeralProfiles)) {
      entry->SetIsEphemeral(false);
    }
  }
```
(实际 setter/参数以 M148 `ProfileAttributesEntry` 为准:`grep -n "SetIsOmitted\|SetIsEphemeral\|SetLocalProfileName" chromium/src/chrome/browser/profiles/profile_attributes_entry.h`。)
**同步重写失实注释**「existing (non-omitted) profile; just unlock … not supported here」。

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc > <worktree>/patches/.../profile_picker_flow_controller.cc.patch
git checkout -- chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add patches/chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc.patch
git -C <worktree> commit -m "feat(enrollment): finalize picker-added profile on enrollment success (avoid silent deletion)"
```

## Task 6.3: 取消删除(UnregisterStep 释放 keepalive)

**Files:**
- Modify: `patches/chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc.patch`(继续扩展;或 `profile_management_flow_controller.cc` 的 pop 回调)

- [ ] **Step 1: edit-live 自定义 enrollment step 的 pop 闭包**

`SwitchToEnrollment` 装 step 时,给「返回 picker」的 pop 回调改为「先 `SwitchToStep(kProfilePicker)` 再 `UnregisterStep(kTeleportEnrollment)`」(注意 `CHECK_NE` 先切后删),使 provider keepalive 释放 → ephemeral profile 自动删目录。首 profile(非 ephemeral)不受影响。定位现有 `CreateSwitchToStepPopCallback` 用法,替换为自定义闭包(模式同上游 `HandleSignInCompleted`)。**失败 ≠ 取消**:失败仍走错误页重试(不改),仅显式返回触发删除。

- [ ] **Step 2: 生成 patch + revert + 验证 + 构建 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc > <worktree>/patches/.../profile_picker_flow_controller.cc.patch
git checkout -- chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add patches/chrome/browser/ui/views/profiles/profile_picker_flow_controller.cc.patch
git -C <worktree> commit -m "feat(enrollment): delete half-created profile on picker enrollment cancel"
```

## Task 6.4: registrar 竞态守卫(跳过已删/omitted 的 PersistEnrolledDomain)

**Files:**
- Modify: `src/browser/enterprise/teleport_oidc_inplace_registrar.cc`

- [ ] **Step 1: edit-live 终态回调前守卫**

在写 `PersistEnrolledDomain()` 前:
```cpp
  // teleport: if this profile was already scheduled for deletion (picker cancel
  // raced an in-flight registrar) or is still omitted, skip persisting the
  // global enrolled-domain — the profile is going away; leave a log breadcrumb.
  if (profile_->GetPath().empty() ||
      g_browser_process->profile_manager()->IsProfileDirectoryMarkedForDeletion(
          profile_->GetPath())) {
    LOG(WARNING) << "[teleport-enroll] profile scheduled for deletion; "
                    "skipping PersistEnrolledDomain (server orphan possible)";
    return;
  }
```
(`IsProfileDirectoryMarkedForDeletion` 精确名以 M148 为准:`grep -n "MarkedForDeletion\|ScheduleProfileForDeletion" chromium/src/chrome/browser/profiles/profile_manager.h`。)

- [ ] **Step 2: apply_patches + 构建 + Commit**

```bash
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add src/browser/enterprise/teleport_oidc_inplace_registrar.cc
git -C <worktree> commit -m "feat(enrollment): guard PersistEnrolledDomain against deleted/omitted profile race"
```

---

# Phase 7 — 换域迁移触发面修复(§4.9)

## Task 7.1: 运行期 re-lock

**Files:**
- Modify: `src/browser/enterprise/teleport_enrollment_gate.cc`(`MaybeHandleDomainMigration`)

- [ ] **Step 1: edit-live 迁移重置后 gate ON 则上锁**

`MaybeHandleDomainMigration` 里清 management id 之后加:
```cpp
  // teleport: gate ON — re-lock immediately so the now-unmanaged profile can't
  // keep browsing in a running window until the next restart. The throttle only
  // covers http(s) main-frame navigations; the lock is the reliable edge.
  if (RequireEnrollmentGateEnabled() && entry) {
    entry->LockForceSigninProfile(true);
  }
```
(`LockForceSigninProfile` 定位:`grep -n "LockForceSigninProfile" chromium/src/chrome/browser/profiles/profile_attributes_entry.h`。)

- [ ] **Step 2: apply_patches + 构建 + Commit**

```bash
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add src/browser/enterprise/teleport_enrollment_gate.cc
git -C <worktree> commit -m "fix(enrollment): re-lock profile on runtime domain migration (gate ON)"
```

## Task 7.2: 启动期迁移检查 + `PendingDomainMigrationFrom` 转正

**Files:**
- Modify: `src/browser/enterprise/teleport_enrollment_gate.{h,cc}`(启动钩子调用点)
- Modify: `patches/chrome/browser/ui/webui/version/version_ui.cc.patch`(改调 `PendingDomainMigrationFrom`)
- 可能 Modify: `patches/chrome/browser/chrome_browser_main.cc.patch` 或 profile 加载 patch(挂启动检查)

- [ ] **Step 1: 选启动挂点并调用 MaybeHandleDomainMigration**

定位现有 teleport 启动钩子(`chrome_browser_main.cc` 的 `PreMainMessageLoopRun` teleport banner 处,或 profile 首次加载点)。在 profile 可用后对已加载 profile 调 `MaybeHandleDomainMigration(profile)`,覆盖「换域后从不导航」用户。plan 执行时按最早可安全拿到 primary profile 的点定稿(优先 profile 加载完成回调,而非 banner——banner 早于 profile)。

- [ ] **Step 2: version_ui 改调 PendingDomainMigrationFrom(消除逻辑重复)**

edit-live `chrome/browser/ui/webui/version/version_ui.cc`:把内联重写的「读 kEnrolledDeploymentDomain + ShouldRequireReenrollment」替换为调用 `teleport::PendingDomainMigrationFrom()`,`PendingDomainMigrationFrom` 由死代码转正为唯一实现。

- [ ] **Step 3: 生成/更新 patch + revert + 验证 + 构建 + Commit**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/webui/version/version_ui.cc > <worktree>/patches/.../version_ui.cc.patch
# + 启动挂点所在文件的 diff
git checkout -- <touched files>
cd <worktree> && python scripts/apply_patches.py && cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
git -C <worktree> add src/browser/enterprise/teleport_enrollment_gate.cc src/browser/enterprise/teleport_enrollment_gate.h patches/chrome/browser/ui/webui/version/version_ui.cc.patch patches/<startup-hook>.patch
git -C <worktree> commit -m "fix(enrollment): startup-time migration check + PendingDomainMigrationFrom used by version_ui"
```

---

# Phase 8 — 死代码/注释/文档清理(§8)

## Task 8.1: 注释与文本订正(逐条)

**Files:** `src/common/teleport_enterprise_urls.{h,cc}`、`patches/.../oidc_auth_response_capture_navigation_throttle.cc.patch` 注释、`patches/.../version_ui.cc.patch` 注释(前几个 Task 未覆盖的残余)

- [ ] **Step 1: 订正 enterprise_urls 注释**

`teleport_enterprise_urls.{h,cc}` 的「injection … empty today / reserved for a future per-tenant OP … No-ops」改为反映现状:per-tenant OP 注入已实现并经 `X-Teleport-Enroll-Allow-Hosts` 响应头活体验证。

- [ ] **Step 2: apply_patches 验证幂等 + Commit**

```bash
cd <worktree> && python scripts/apply_patches.py
git -C <worktree> add src/common/teleport_enterprise_urls.h src/common/teleport_enterprise_urls.cc
git -C <worktree> commit -m "docs(comments): correct stale enterprise-urls injection comments"
```

## Task 8.2: 文档漂移修正

**Files:** `scripts/smoke_check.md`、`docs/deployment-domain-migration-runbook.md`、`docs/tech-debt.md`、`CLAUDE.md`(新增动态耦合 gotcha)

- [ ] **Step 1: smoke_check.md**

`--dump-dom` 挂起条目(约 :67)改为「仅 gate ON 时挂起;默认 gate OFF 不受影响」。

- [ ] **Step 2: runbook 条件化**

`docs/deployment-domain-migration-runbook.md` 全篇 gate-ON-默认叙述加「仅 gate ON」限定;`:54` 「清除机器级 CBCM DM token 为后续项」的失实表述改为「客户端迁移已 ClearDMToken(gate.cc),服务端孤儿记录清理为后续项」。补「BYOD 先设域后登录 + enroll 页披露文案」小节(跨仓要求)。

- [ ] **Step 3: tech-debt.md 登记新 TD**

新增/更新:gate 企业下发通道;settings guest 回显 desync;settings「Sync and Google services」死行 + `chrome://signin-*` 死壳目录清理;device-signals 同意位;迁移已开窗口关闭策略。TD-005 状态更新(菜单面已解)。

- [ ] **Step 4: CLAUDE.md 新增 gotcha**

在「关键 gotcha」加一条:强制纳管唯一开关 `kRequireEnrollmentToBrowse`(默认 false),经 `RequireEnrollmentGateEnabled()`(会话冻结)OR 进 `IsForceSigninEnabled()` 复活 Layer-1 picker enrollment;GAIA 面经 `CanEnableDiceForBuild()=false` 结构钉死;guest 四点覆盖;`BrowserSignin=Forced` 已去 GAIA 化。

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add scripts/smoke_check.md docs/deployment-domain-migration-runbook.md docs/tech-debt.md CLAUDE.md
git -C <worktree> commit -m "docs: sync smoke/runbook/tech-debt/CLAUDE for voluntary-enrollment model"
```

---

# Phase 9 — 集成验证(§6 活体冒烟矩阵)

## Task 9.1: 全量 gtest + pytest

- [ ] **Step 1: 跑全部单测**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && out/mac/arm64/dev/teleport_unittests
cd <worktree> && uv run pytest -q
```
Expected: gtest 全 PASS(含新 `TeleportSigninEntryLogicTest`);pytest 全绿(含新 branding_strings 用例)。`apply_patches.py` 幂等再验一次。

## Task 9.2: 活体冒烟矩阵(fairyland.ai 栈)

**前置:** fairyland-ai lima VM 运行、seed 用户就绪(如 `enroll-single@dadou.example`);启动命令 `open -n build/mac/arm64/dev/Teleport.app/ --args --user-data-dir=/tmp/enrollment --teleport-deployment-domain=fairyland.ai`(每次清 `/tmp/enrollment`)。

- [ ] **Step 1: 场景 1 — gate OFF 默认**

清目录启动 → 正常 NTP、无 enroll tab、无 FRE 登录窗、可任意浏览。

- [ ] **Step 2: 场景 2 + 3 — 菜单登录 + 披露 + 就地纳管**

未纳管菜单见「登录」(含 subtitle,不崩)→ 新 tab OIDC 全链 → 披露对话框(就地纳管措辞,GO 分支;No-Go 则服务端页披露)→ 接受 → 不新建 profile、`chrome://policy` 用户策略生效 → 菜单转「由 <机构> 管理」(与 ⋮「Managed by」、chrome://management 三表面同串)→ 断言拒绝对话框不纳管;断言 registrar 失败 tab 呈现错误页(非静默)。

- [ ] **Step 3: 场景 4 + 5 — gate ON picker**

手改 `/tmp/enrollment/Local State` 置 `teleport.enrollment.require_enrollment_to_browse=true` → 冷启动即锁进 picker → enrollment step 完成 → 解锁开窗;「添加」→ enrollment step,取消 → 返回 picker 且目录消失,完成 → profile 存活且重启仍在。

- [ ] **Step 4: 场景 6 — guest**

gate ON:profile 菜单/app 菜单/picker 无 guest 入口 **且 `--guest` 启动被拒**;gate OFF:guest 可用。

- [ ] **Step 5: 场景 7 — GAIA 表面集**

两态菜单、`chrome://settings` People 区(含已纳管后无「isn't associated with Google」)、picker 建号、头像按钮均无任何 GAIA/Google 品牌登录项;下发 `BrowserSignin=2`(手改 policy)→ 浏览器不锁死、正常可用。

- [ ] **Step 6: 场景 8 — 换域迁移**

enroll → 改 `--teleport-deployment-domain` → 重启 → 迁移日志 + `chrome://version`「changed from」+ gate ON 重锁/OFF 菜单回未纳管;运行期改域(不重启,经测试钩子)后新开窗口即锁(gate ON)。

- [ ] **Step 7: 冒烟结果记录**

把结果追加到 `scripts/smoke_check.md`(或新建 `docs/voluntary-enrollment-smoke.md`),失败项如实记录并回到对应 Task 修复(systematic-debugging)。

## Task 9.3: 请求代码评审 + 收尾

- [ ] **Step 1: requesting-code-review**

用 `superpowers:requesting-code-review` 对整分支 diff 做评审;confirmed 项修复。

- [ ] **Step 2: finishing-a-development-branch**

用 `superpowers:finishing-a-development-branch`:overlay symlink 切回主仓 `src`、rebase onto main + squash + ff、删 worktree(按仓库合并约定;是否 push 由用户定)。

---

## 自查(spec 覆盖对照)

- §4.1 默认翻转 + 会话冻结谓词 → Task 0.1/0.2 ✓
- §4.2 force-signin OR + BrowserSignin 去 GAIA 化 + 27 调用点(引用评审,不重核)→ Task 1.1/1.2 ✓
- §4.3 Path A 删除 + throttle 限定 → Task 3.1 ✓
- §4.4 guest 四点 → Task 2.1/2.2 ✓
- §4.5 菜单入口(subtitle 补齐 / header image / 机构名统一 / feature 区抑制 / 身份 prefs / i18n / 分支顺序)→ Task 4.1–4.5 ✓
- §4.6 picker 新建(隐藏创建 / finalize / 取消删除 / 竞态守卫)→ Task 6.1–6.4 ✓
- §4.7 改道解耦 + 失败反馈 + 披露对话框(spike+fallback)→ Task 5.1–5.3 ✓
- §4.8 GAIA 结构钉死 + settings 残留 → Task 3.2/3.3 ✓
- §4.9 运行期 re-lock + 启动检查 + PendingDomainMigrationFrom 转正 → Task 7.1/7.2 ✓
- §5 边界(锁/throttle 分工、三态、披露、GAIA 不变量)→ 分散于 Task 3.1/5.3/7.x + 冒烟 ✓
- §6 测试(gtest + pytest + 8 场景冒烟)→ Task 0.3/9.1/9.2 ✓
- §7 TD 登记 → Task 8.2 ✓
- §8 清理(删除 / 转正 / 注释订正 / 文档)→ Task 3.1/7.2/8.1/8.2 ✓
