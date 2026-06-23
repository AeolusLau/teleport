# 企业纳管门禁 实现计划(路径 A,第一轮)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让未完成 OIDC 纳管的 profile 无法访问互联网——一个 //teleport 导航门禁 throttle 拦截一切非纳管导航并导回 enroll 页,直到该 profile 完成纳管(`ProfileManagementId` 已写 且 用户云策略已拉到)。

**Architecture:** 纯逻辑(URL 白名单 + 拦截决策)放在 `//teleport` source_set 做 TDD;需要 chrome 头的 Profile glue 与 NavigationThrottle 经 `chrome/browser/BUILD.gn` patch 编进 chrome target(避免 GN 依赖环,与既有 `teleport_update_buildstate` 同模式);门禁由 local_state pref `kTeleportRequireEnrollmentToBrowse`(默认 true,安全默认)驱动。第一轮复用既有 dasherless OIDC 纳管,不锁多 profile、不做就地纳管。

**Tech Stack:** Chromium M148 overlay、C++、GN、gtest(`teleport_unittests`)、`content::NavigationThrottle`、`policy::CloudPolicyManager`。

**上游 spec:** `docs/superpowers/specs/2026-06-11-enterprise-enrollment-gate-design.md`

---

## 关键事实(M148 检出已核实,实现时照用)

- **判定谓词**:
  - `ProfileAttributesEntry* entry = g_browser_process->profile_manager()->GetProfileAttributesStorage().GetProfileAttributesWithPath(profile->GetPath());`(`profile_attributes_storage.h:113`,未找到返回 nullptr)
  - `entry->GetProfileManagementId()` → `std::string`(`profile_attributes_entry.h:233`;dasherless OIDC 纳管落地时写入,空 = 未纳管)
  - `profile->GetCloudPolicyManager()`(`profile.h:349`,合一 user/profile 两类)→ `->core()->store()->has_policy()`(`cloud_policy_store.h:93`)。dasherless 走 `ProfileCloudPolicyManager`,合一 getter 覆盖。
- **NavigationThrottle(M148 registry 形态)**:基类构造 `explicit NavigationThrottle(content::NavigationThrottleRegistry&)`;静态工厂 `static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry)`;`registry.AddThrottle(std::make_unique<T>(registry))`;`WillStartRequest()/WillRedirectRequest()` 返回 `ThrottleCheckResult`;主框架判断 `navigation_handle()->IsInMainFrame()`;取 URL `navigation_handle()->GetURL()`;取 profile `Profile::FromBrowserContext(navigation_handle()->GetWebContents()->GetBrowserContext())`。
- **注册点**:`chrome/browser/chrome_content_browser_client_navigation_throttles.cc` 的 `CreateAndAddChromeThrottlesForNavigation()`,在 `ManagedProfileRequiredNavigationThrottle::MaybeCreateAndAdd(registry);`(约 447 行,`#if BUILDFLAG(IS_LINUX)||IS_MAC||IS_WIN` 块内)之后插一行。
- **导回 enroll 模式**(参照 `profile_management_navigation_throttle.cc`):**先 PostTask 再 LoadURL**(同步导航会析构 throttle),返回 `CANCEL_AND_IGNORE`:
  ```cpp
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(&T::NavigateToEnroll, weak_factory_.GetWeakPtr()));
  // NavigateToEnroll: web_contents->GetController().LoadURLWithParams(
  //     content::NavigationController::LoadURLParams(GURL(EnterpriseEnrollUrl())));
  ```
- **启动导向点**:`chrome/browser/ui/startup/startup_browser_creator_impl.cc` 的 `StartupBrowserCreatorImpl::DetermineStartupTabs()`(570–659);`StartupTab{GURL}`,`StartupTabs = std::vector<StartupTab>`,member `profile_` 可用。
- **pref 注册点**:`chrome/browser/prefs/browser_prefs.cc` 的 `RegisterLocalState(...)`(`kBrowserAddPersonEnabled` 同类 local_state bool,默认 true,见 `profiles_state.cc:84`)。
- **编译归属(GN 依赖环规避)**:需要 chrome 头的文件(glue + throttle)经 `patches/chrome/browser/BUILD.gn.patch` 加进 `static_library("browser")` 的 `sources`(既有 patch 已用此法加 `teleport_update_buildstate`);纯逻辑文件进 `src/BUILD.gn` 的 `source_set("teleport")`。`chrome/browser` deps `//teleport`,故 chrome 侧 glue 可调 `teleport::` 纯逻辑。
- **多主机纳管流程**:纳管跨 enroll-landing(`enroll.teleport.<域>`)→ per-tenant OP(`<slug>.<域>`)→ 中央 `accounts.<域>`。故白名单**按纳管域后缀**放行(`.fairyland.io` dev / `.beansec.com` release),而非三个精确 URL,否则中途 OP/accounts 跳转会被门禁误挡。

---

## 文件结构

**进 `//teleport` source_set(纯逻辑,TDD):**
- `src/common/teleport_pref_names.{h,cc}` — pref 名常量。
- `src/common/teleport_enrollment_gate_logic.{h,cc}` — `IsEnrollmentFlowUrl(GURL)`、`ShouldBlockNavigation(...)`(纯函数,仅依赖 `//url` + `teleport_enterprise_urls`)。
- `src/common/teleport_enrollment_gate_logic_unittest.cc` — gtest。
- `src/common/teleport_enterprise_urls.{h,cc}` — **扩展**:新增 `EnterpriseEnrollmentDomainSuffixes()`。
- `src/common/teleport_enterprise_urls_unittest.cc` — **扩展**:覆盖新函数。

**编进 chrome target(经 `chrome/browser/BUILD.gn` patch,需 chrome 头):**
- `src/browser/enterprise/teleport_enrollment_gate.{h,cc}` — `ShouldGateProfile(Profile*)`、`IsEnrolled(Profile*)`、`RegisterEnrollmentGateLocalStatePrefs(PrefRegistrySimple*)`。
- `src/browser/enterprise/teleport_enrollment_gate_throttle.{h,cc}` — `TeleportEnrollmentGateThrottle`。

**上游 patch:**
- `patches/chrome/browser/BUILD.gn.patch` — **扩展**:加 4 个源文件进 `sources`。
- `patches/chrome/browser/chrome_content_browser_client_navigation_throttles.cc.patch` — **新增**:注册 throttle。
- `patches/chrome/browser/prefs/browser_prefs.cc.patch` — **新增**:注册 pref。
- `patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch` — **新增**:启动导向。
- `src/BUILD.gn` — **修改**:加纯逻辑源文件 + unittest。

**TDD 边界:** 纯逻辑(`IsEnrollmentFlowUrl`/`ShouldBlockNavigation`/`EnterpriseEnrollmentDomainSuffixes`)全量 gtest;chrome 侧 glue/throttle/patch 经构建 + §8.2 端到端活验(无 chrome test_support 不强行单测,符合本轮合规级 + 分支评估定位)。

---

## Task 1: 纯逻辑脚手架 + BUILD 接好(让测试能编)

**Files:**
- Create: `src/common/teleport_pref_names.h`, `src/common/teleport_pref_names.cc`
- Create: `src/common/teleport_enrollment_gate_logic.h`, `src/common/teleport_enrollment_gate_logic.cc`
- Create: `src/common/teleport_enrollment_gate_logic_unittest.cc`
- Modify: `src/BUILD.gn`

- [ ] **Step 1: 建 pref 名常量**

`src/common/teleport_pref_names.h`:
```cpp
#ifndef TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_
#define TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_

namespace teleport::prefs {

// local_state bool. true(默认,安全默认)= 未纳管不可上网。
inline constexpr char kRequireEnrollmentToBrowse[] =
    "teleport.enrollment.require_enrollment_to_browse";

}  // namespace teleport::prefs

#endif  // TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_
```

`src/common/teleport_pref_names.cc`:
```cpp
#include "teleport/common/teleport_pref_names.h"
// Header-only constants; TU mirrors layout of other //teleport common files.
namespace teleport::prefs {}  // namespace teleport::prefs
```

- [ ] **Step 2: 建纯逻辑头**

`src/common/teleport_enrollment_gate_logic.h`:
```cpp
#ifndef TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_
#define TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_

class GURL;

namespace teleport {

// True 当 url 属于纳管流程(按纳管域后缀放行,覆盖 enroll-landing /
// per-tenant OP / 中央 accounts 多主机)。仅 https 视为有效。
bool IsEnrollmentFlowUrl(const GURL& url);

// 门禁拦截决策(纯函数,便于单测)。返回 true = 应拦截此次导航。
//   should_gate    : 该 profile 受门禁(策略 on + 常规 profile)
//   is_enrolled    : 已完成纳管
//   is_main_frame  : 主框架导航
//   url            : 目标 URL
bool ShouldBlockNavigation(bool should_gate,
                           bool is_enrolled,
                           bool is_main_frame,
                           const GURL& url);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_
```

- [ ] **Step 3: 建纯逻辑空实现(先编过,逻辑下一 task 红绿)**

`src/common/teleport_enrollment_gate_logic.cc`:
```cpp
#include "teleport/common/teleport_enrollment_gate_logic.h"

#include "url/gurl.h"

namespace teleport {

bool IsEnrollmentFlowUrl(const GURL& url) {
  return false;
}

bool ShouldBlockNavigation(bool should_gate,
                           bool is_enrolled,
                           bool is_main_frame,
                           const GURL& url) {
  return false;
}

}  // namespace teleport
```

- [ ] **Step 4: 建空测试文件**

`src/common/teleport_enrollment_gate_logic_unittest.cc`:
```cpp
#include "teleport/common/teleport_enrollment_gate_logic.h"

#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"

namespace teleport {
namespace {

TEST(TeleportEnrollmentGateLogicTest, Scaffold) {
  EXPECT_FALSE(ShouldBlockNavigation(false, false, true, GURL("https://x/")));
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 5: 注册进 `src/BUILD.gn`**

在 `source_set("teleport")` 的 `sources` 加(保持字母序就近插入):
```gn
    "common/teleport_enrollment_gate_logic.cc",
    "common/teleport_enrollment_gate_logic.h",
    "common/teleport_pref_names.cc",
    "common/teleport_pref_names.h",
```
在 `test("teleport_unittests")` 的 `sources` 加:
```gn
    "common/teleport_enrollment_gate_logic_unittest.cc",
```

- [ ] **Step 6: 编译并跑空测试**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportEnrollmentGateLogicTest.*'
```
Expected: PASS(1 test)。

- [ ] **Step 7: Commit**

```bash
git add src/common/teleport_pref_names.* src/common/teleport_enrollment_gate_logic.* \
        src/common/teleport_enrollment_gate_logic_unittest.cc src/BUILD.gn
git commit -m "feat(enrollment-gate): scaffold pure gate logic + pref name"
```

---

## Task 2: 纳管域后缀(`EnterpriseEnrollmentDomainSuffixes`)

**Files:**
- Modify: `src/common/teleport_enterprise_urls.h`, `src/common/teleport_enterprise_urls.cc`
- Modify: `src/common/teleport_enterprise_urls_unittest.cc`

- [ ] **Step 1: 写失败测试**

在 `src/common/teleport_enterprise_urls_unittest.cc` 加:
```cpp
TEST(TeleportEnterpriseUrlsTest, EnrollmentDomainSuffixesNonEmpty) {
  const auto suffixes = teleport::EnterpriseEnrollmentDomainSuffixes();
  ASSERT_FALSE(suffixes.empty());
  // 每条以点开头,作为 host 后缀匹配用。
  for (const auto& s : suffixes) {
    EXPECT_EQ('.', s.front());
  }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests 2>&1 | tail -5
```
Expected: 编译失败(`EnterpriseEnrollmentDomainSuffixes` 未声明)。

- [ ] **Step 3: 加声明**

`src/common/teleport_enterprise_urls.h` 的 `namespace teleport` 内加:
```cpp
// 纳管流程涉及的域后缀(host 以此结尾即视为纳管流程,覆盖 enroll-landing /
// per-tenant OP / 中央 accounts 多主机)。dev=fairyland.io、release=beansec.com。
std::vector<std::string> EnterpriseEnrollmentDomainSuffixes();
```

- [ ] **Step 4: 加实现**

`src/common/teleport_enterprise_urls.cc` 的 buildflag 分支区加常量,并加函数:
```cpp
// 在 #if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS) 分支:
constexpr char kEnrollmentDomainSuffix[] = ".beansec.com";
// 在 #else 分支:
constexpr char kEnrollmentDomainSuffix[] = ".fairyland.io";

// 在 namespace teleport 内:
std::vector<std::string> EnterpriseEnrollmentDomainSuffixes() {
  return {kEnrollmentDomainSuffix};
}
```
确认文件已 `#include <string>` 与 `<vector>`(`EnterpriseTrustedRedirectHosts` 已返回 `std::vector<std::string>`,故应已具备)。

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportEnterpriseUrlsTest.*'
```
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/common/teleport_enterprise_urls.* src/common/teleport_enterprise_urls_unittest.cc
git commit -m "feat(enrollment-gate): add enterprise enrollment domain suffixes"
```

---

## Task 3: TDD `IsEnrollmentFlowUrl`

**Files:**
- Modify: `src/common/teleport_enrollment_gate_logic.cc`
- Modify: `src/common/teleport_enrollment_gate_logic_unittest.cc`

- [ ] **Step 1: 写失败测试**

替换 `Scaffold` 测试为:
```cpp
TEST(TeleportEnrollmentGateLogicTest, IsEnrollmentFlowUrl) {
  // 纳管域(dev=fairyland.io)下的各主机均放行。
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://enroll.teleport.fairyland.io/enroll")));
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://dadou.fairyland.io/authorize?x=1")));
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://accounts.fairyland.io/login")));
  // 非纳管域不放行。
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://example.com/")));
  // 域后缀伪造攻击不放行(host 必须真正以后缀结尾)。
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://fairyland.io.evil.com/")));
  // 非 https 不放行。
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("http://enroll.teleport.fairyland.io/")));
  // 无效 URL 不放行。
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("not a url")));
}
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='*IsEnrollmentFlowUrl*'
```
Expected: FAIL(当前恒返回 false,放行用例不过)。

- [ ] **Step 3: 实现**

`teleport_enrollment_gate_logic.cc` 顶部加 include,改 `IsEnrollmentFlowUrl`:
```cpp
#include "teleport/common/teleport_enrollment_gate_logic.h"

#include <string>
#include <string_view>
#include <vector>

#include "teleport/common/teleport_enterprise_urls.h"
#include "url/gurl.h"

namespace teleport {

bool IsEnrollmentFlowUrl(const GURL& url) {
  if (!url.is_valid() || !url.SchemeIs("https")) {
    return false;
  }
  const std::string host = url.host();
  for (const std::string& suffix : EnterpriseEnrollmentDomainSuffixes()) {
    // host == apex(去掉前导点)或 host 以 ".<域>" 结尾。
    std::string_view apex(suffix);
    apex.remove_prefix(1);  // 去掉前导 '.'
    if (host == apex ||
        (host.size() > suffix.size() &&
         std::string_view(host).substr(host.size() - suffix.size()) == suffix)) {
      return true;
    }
  }
  return false;
}
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='*IsEnrollmentFlowUrl*'
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/common/teleport_enrollment_gate_logic.cc src/common/teleport_enrollment_gate_logic_unittest.cc
git commit -m "feat(enrollment-gate): implement IsEnrollmentFlowUrl (domain-suffix allowlist)"
```

---

## Task 4: TDD `ShouldBlockNavigation`

**Files:**
- Modify: `src/common/teleport_enrollment_gate_logic.cc`
- Modify: `src/common/teleport_enrollment_gate_logic_unittest.cc`

- [ ] **Step 1: 写失败测试**

加:
```cpp
TEST(TeleportEnrollmentGateLogicTest, ShouldBlockNavigation) {
  const GURL web("https://example.com/");
  const GURL enroll("https://enroll.teleport.fairyland.io/enroll");
  const GURL internal("chrome://settings/");

  // 受门禁 + 未纳管 + 主框架 + 普通 web URL → 拦。
  EXPECT_TRUE(ShouldBlockNavigation(true, false, true, web));
  // 纳管流程 URL → 放行。
  EXPECT_FALSE(ShouldBlockNavigation(true, false, true, enroll));
  // chrome:// 等内部页 → 放行(只拦 http/https)。
  EXPECT_FALSE(ShouldBlockNavigation(true, false, true, internal));
  // 已纳管 → 放行。
  EXPECT_FALSE(ShouldBlockNavigation(true, true, true, web));
  // 未受门禁(策略 off / 非常规 profile)→ 放行。
  EXPECT_FALSE(ShouldBlockNavigation(false, false, true, web));
  // 子框架 → 放行(只拦主框架)。
  EXPECT_FALSE(ShouldBlockNavigation(true, false, false, web));
}
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='*ShouldBlockNavigation*'
```
Expected: FAIL。

- [ ] **Step 3: 实现**

改 `ShouldBlockNavigation`:
```cpp
bool ShouldBlockNavigation(bool should_gate,
                           bool is_enrolled,
                           bool is_main_frame,
                           const GURL& url) {
  if (!should_gate || is_enrolled) {
    return false;
  }
  if (!is_main_frame) {
    return false;
  }
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return false;  // 放行 chrome://、about: 等内部页。
  }
  return !IsEnrollmentFlowUrl(url);
}
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportEnrollmentGateLogicTest.*'
```
Expected: PASS(全部)。

- [ ] **Step 5: Commit**

```bash
git add src/common/teleport_enrollment_gate_logic.cc src/common/teleport_enrollment_gate_logic_unittest.cc
git commit -m "feat(enrollment-gate): implement ShouldBlockNavigation decision"
```

---

## Task 5: Profile glue(`ShouldGateProfile` / `IsEnrolled` / pref 注册)

> 编进 chrome target(需 chrome 头);不进 `//teleport` source_set。本 task 经构建验证,无独立单测。

**Files:**
- Create: `src/browser/enterprise/teleport_enrollment_gate.h`, `src/browser/enterprise/teleport_enrollment_gate.cc`
- Modify: `patches/chrome/browser/BUILD.gn.patch`

- [ ] **Step 1: 写头**

`src/browser/enterprise/teleport_enrollment_gate.h`:
```cpp
#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_

class Profile;
class PrefRegistrySimple;

namespace teleport {

// 该 profile 是否受纳管门禁:常规(非 OTR/guest/system)profile
// 且 local_state 策略 kRequireEnrollmentToBrowse 为 true。
bool ShouldGateProfile(Profile* profile);

// 该 profile 是否已完成纳管:ProfileManagementId 已写 且 用户云策略已拉到。
bool IsEnrolled(Profile* profile);

// 注册门禁 local_state pref(默认 true=安全默认)。
void RegisterEnrollmentGateLocalStatePrefs(PrefRegistrySimple* registry);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_
```

- [ ] **Step 2: 写实现**

`src/browser/enterprise/teleport_enrollment_gate.cc`:
```cpp
#include "teleport/browser/enterprise/teleport_enrollment_gate.h"

#include "chrome/browser/browser_process.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/profiles/profile_attributes_entry.h"
#include "chrome/browser/profiles/profile_attributes_storage.h"
#include "chrome/browser/profiles/profile_manager.h"
#include "components/policy/core/common/cloud/cloud_policy_core.h"
#include "components/policy/core/common/cloud/cloud_policy_manager.h"
#include "components/policy/core/common/cloud/cloud_policy_store.h"
#include "components/prefs/pref_registry_simple.h"
#include "components/prefs/pref_service.h"
#include "teleport/common/teleport_pref_names.h"

namespace teleport {

bool ShouldGateProfile(Profile* profile) {
  if (!profile || profile->IsOffTheRecord() || !profile->IsRegularProfile()) {
    return false;
  }
  PrefService* local_state = g_browser_process->local_state();
  return local_state &&
         local_state->GetBoolean(prefs::kRequireEnrollmentToBrowse);
}

bool IsEnrolled(Profile* profile) {
  if (!profile) {
    return false;
  }
  ProfileManager* pm = g_browser_process->profile_manager();
  if (!pm) {
    return false;
  }
  ProfileAttributesEntry* entry =
      pm->GetProfileAttributesStorage().GetProfileAttributesWithPath(
          profile->GetPath());
  if (!entry || entry->GetProfileManagementId().empty()) {
    return false;
  }
  policy::CloudPolicyManager* manager = profile->GetCloudPolicyManager();
  return manager && manager->core() && manager->core()->store() &&
         manager->core()->store()->has_policy();
}

void RegisterEnrollmentGateLocalStatePrefs(PrefRegistrySimple* registry) {
  registry->RegisterBooleanPref(prefs::kRequireEnrollmentToBrowse, true);
}

}  // namespace teleport
```

- [ ] **Step 3: 加进 `chrome/browser/BUILD.gn` patch 的 sources**

编辑 `patches/chrome/browser/BUILD.gn.patch`,在 `static_library("browser")` 的**通用 `sources`**(非 mac 专属块)加一个 hunk,插入:
```gn
      "//teleport/browser/enterprise/teleport_enrollment_gate.cc",
      "//teleport/browser/enterprise/teleport_enrollment_gate.h",
```
> 提示:找到 `sources = [` 开头的通用列表,就近插入并保持 diff 上下文 3 行。`apply_patches.py` 幂等校验,改完先 `python scripts/apply_patches.py` 再构建。注意此 patch 已存在(加 `//teleport` dep 与 mac buildstate),为同文件追加 hunk。

- [ ] **Step 4: 应用 patch 并构建 chrome(验证编译,glue 此时未被调用但需编过)**

Run:
```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -15
```
Expected: 构建成功(glue 编进 chrome,无未引用报错——非 static 函数不会因未调用而报错)。

- [ ] **Step 5: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add src/browser/enterprise/teleport_enrollment_gate.* patches/chrome/browser/BUILD.gn.patch
git commit -m "feat(enrollment-gate): profile predicates + local_state pref registration"
```

---

## Task 6: 门禁 throttle

**Files:**
- Create: `src/browser/enterprise/teleport_enrollment_gate_throttle.h`, `src/browser/enterprise/teleport_enrollment_gate_throttle.cc`
- Modify: `patches/chrome/browser/BUILD.gn.patch`

- [ ] **Step 1: 写头**

`src/browser/enterprise/teleport_enrollment_gate_throttle.h`:
```cpp
#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_THROTTLE_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_THROTTLE_H_

#include "base/memory/weak_ptr.h"
#include "content/public/browser/navigation_throttle.h"

namespace content {
class NavigationThrottleRegistry;
}  // namespace content

namespace teleport {

// 未纳管 profile 上拦截一切非纳管 web 导航,导回 enroll 落地页。
class TeleportEnrollmentGateThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit TeleportEnrollmentGateThrottle(
      content::NavigationThrottleRegistry& registry);
  TeleportEnrollmentGateThrottle(const TeleportEnrollmentGateThrottle&) = delete;
  TeleportEnrollmentGateThrottle& operator=(
      const TeleportEnrollmentGateThrottle&) = delete;
  ~TeleportEnrollmentGateThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillStartRequest() override;
  ThrottleCheckResult WillRedirectRequest() override;
  const char* GetNameForLogging() override;

 private:
  ThrottleCheckResult CheckRequest();
  void NavigateToEnroll();

  base::WeakPtrFactory<TeleportEnrollmentGateThrottle> weak_factory_{this};
};

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_THROTTLE_H_
```

- [ ] **Step 2: 写实现**

`src/browser/enterprise/teleport_enrollment_gate_throttle.cc`:
```cpp
#include "teleport/browser/enterprise/teleport_enrollment_gate_throttle.h"

#include <memory>

#include "base/functional/bind.h"
#include "base/location.h"
#include "base/task/sequenced_task_runner.h"
#include "chrome/browser/profiles/profile.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/web_contents.h"
#include "net/base/net_errors.h"
#include "teleport/browser/enterprise/teleport_enrollment_gate.h"
#include "teleport/common/teleport_enrollment_gate_logic.h"
#include "teleport/common/teleport_enterprise_urls.h"
#include "ui/base/page_transition_types.h"
#include "url/gurl.h"

namespace teleport {

// static
void TeleportEnrollmentGateThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  registry.AddThrottle(
      std::make_unique<TeleportEnrollmentGateThrottle>(registry));
}

TeleportEnrollmentGateThrottle::TeleportEnrollmentGateThrottle(
    content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

TeleportEnrollmentGateThrottle::~TeleportEnrollmentGateThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
TeleportEnrollmentGateThrottle::WillStartRequest() {
  return CheckRequest();
}

content::NavigationThrottle::ThrottleCheckResult
TeleportEnrollmentGateThrottle::WillRedirectRequest() {
  return CheckRequest();
}

const char* TeleportEnrollmentGateThrottle::GetNameForLogging() {
  return "TeleportEnrollmentGateThrottle";
}

content::NavigationThrottle::ThrottleCheckResult
TeleportEnrollmentGateThrottle::CheckRequest() {
  content::NavigationHandle* handle = navigation_handle();
  content::WebContents* web_contents = handle->GetWebContents();
  if (!web_contents) {
    return PROCEED;
  }
  Profile* profile =
      Profile::FromBrowserContext(web_contents->GetBrowserContext());

  if (!ShouldBlockNavigation(ShouldGateProfile(profile), IsEnrolled(profile),
                             handle->IsInMainFrame(), handle->GetURL())) {
    return PROCEED;
  }

  // 先 PostTask 再 LoadURL:同步导航会析构 throttle。
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&TeleportEnrollmentGateThrottle::NavigateToEnroll,
                     weak_factory_.GetWeakPtr()));
  return ThrottleCheckResult(CANCEL_AND_IGNORE);
}

void TeleportEnrollmentGateThrottle::NavigateToEnroll() {
  content::WebContents* web_contents = navigation_handle()->GetWebContents();
  if (!web_contents) {
    return;
  }
  content::NavigationController::LoadURLParams params(
      GURL(EnterpriseEnrollUrl()));
  params.transition_type = ui::PAGE_TRANSITION_AUTO_TOPLEVEL;
  web_contents->GetController().LoadURLWithParams(params);
}

}  // namespace teleport
```

- [ ] **Step 3: 加进 `chrome/browser/BUILD.gn` patch 的 sources**

同 Task 5 Step 3,追加:
```gn
      "//teleport/browser/enterprise/teleport_enrollment_gate_throttle.cc",
      "//teleport/browser/enterprise/teleport_enrollment_gate_throttle.h",
```

- [ ] **Step 4: 应用并构建**

Run:
```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -15
```
Expected: 构建成功。

- [ ] **Step 5: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add src/browser/enterprise/teleport_enrollment_gate_throttle.* patches/chrome/browser/BUILD.gn.patch
git commit -m "feat(enrollment-gate): navigation throttle that redirects to enroll"
```

---

## Task 7: 注册 throttle

**Files:**
- Create: `patches/chrome/browser/chrome_content_browser_client_navigation_throttles.cc.patch`

- [ ] **Step 1: 手改上游文件以生成 patch**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/chrome_content_browser_client_navigation_throttles.cc`:
1. 顶部 include 区(其它 throttle include 旁)加:
   ```cpp
   #include "teleport/browser/enterprise/teleport_enrollment_gate_throttle.h"
   ```
2. 在 `ManagedProfileRequiredNavigationThrottle::MaybeCreateAndAdd(registry);`(约 447 行)**之后**加:
   ```cpp
     teleport::TeleportEnrollmentGateThrottle::MaybeCreateAndAdd(registry);
   ```

- [ ] **Step 2: 生成一文件一 patch**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/chrome_content_browser_client_navigation_throttles.cc \
  > /Users/liulichao/workspace/teleport/patches/chrome/browser/chrome_content_browser_client_navigation_throttles.cc.patch
git checkout -- chrome/browser/chrome_content_browser_client_navigation_throttles.cc
```
> patch 文件名镜像上游路径(CLAUDE.md「一文件一 patch」)。

- [ ] **Step 3: 经 apply_patches 重放并构建**

Run:
```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -15
```
Expected: 构建成功(throttle 已注册进导航链)。

- [ ] **Step 4: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add patches/chrome/browser/chrome_content_browser_client_navigation_throttles.cc.patch
git commit -m "feat(enrollment-gate): register gate throttle in chrome navigation throttles"
```

---

## Task 8: 注册 pref(browser_prefs)

**Files:**
- Create: `patches/chrome/browser/prefs/browser_prefs.cc.patch`

- [ ] **Step 1: 手改上游文件**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/prefs/browser_prefs.cc`:
1. include 区加:
   ```cpp
   #include "teleport/browser/enterprise/teleport_enrollment_gate.h"
   ```
2. 在 `void RegisterLocalState(PrefRegistrySimple* registry) {` 函数体内(随便一处既有 `registry->Register...` 旁)加:
   ```cpp
     teleport::RegisterEnrollmentGateLocalStatePrefs(registry);
   ```
   > 确认形参名(若不是 `registry` 用实际名)。`RegisterLocalState` 在本文件,grep `void RegisterLocalState(` 定位。

- [ ] **Step 2: 生成 patch**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/prefs/browser_prefs.cc \
  > /Users/liulichao/workspace/teleport/patches/chrome/browser/prefs/browser_prefs.cc.patch
git checkout -- chrome/browser/prefs/browser_prefs.cc
```

- [ ] **Step 3: 重放并构建**

Run:
```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -15
```
Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add patches/chrome/browser/prefs/browser_prefs.cc.patch
git commit -m "feat(enrollment-gate): register RequireEnrollmentToBrowse local_state pref (default true)"
```

---

## Task 9: 启动导向(未纳管时首页 = enroll)

**Files:**
- Create: `patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch`

- [ ] **Step 1: 手改上游文件**

编辑 `$TELEPORT_CHROMIUM_DIR/src/chrome/browser/ui/startup/startup_browser_creator_impl.cc`:
1. include 区加:
   ```cpp
   #include "teleport/browser/enterprise/teleport_enrollment_gate.h"
   #include "teleport/common/teleport_enterprise_urls.h"
   ```
2. 在 `StartupBrowserCreatorImpl::DetermineStartupTabs(...)` 函数体**最前面**(构造 tabs 之前)加:
   ```cpp
     // teleport: 未纳管 profile 启动只开 enroll 页;门禁 throttle 兜底其余导航。
     if (teleport::ShouldGateProfile(profile_) &&
         !teleport::IsEnrolled(profile_)) {
       StartupTabs enroll_tabs;
       enroll_tabs.emplace_back(GURL(teleport::EnterpriseEnrollUrl()));
       return enroll_tabs;
     }
   ```
   > 用 grep `StartupBrowserCreatorImpl::DetermineStartupTabs` 定位;确认返回类型为 `StartupTabs`、member 名为 `profile_`(若不同按实际改)。`StartupTab` 构造取 `const GURL&`。

- [ ] **Step 2: 生成 patch**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/startup/startup_browser_creator_impl.cc \
  > /Users/liulichao/workspace/teleport/patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch
git checkout -- chrome/browser/ui/startup/startup_browser_creator_impl.cc
```

- [ ] **Step 3: 重放并构建**

Run:
```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -15
```
Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add patches/chrome/browser/ui/startup/startup_browser_creator_impl.cc.patch
git commit -m "feat(enrollment-gate): startup redirects unenrolled profile to enroll page"
```

---

## Task 10: 全量构建 + 端到端活验(spec §8.2 步骤 1–4)

**Files:** 无(验证 task)

- [ ] **Step 1: 全 patch + 全单测**

Run:
```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py && uv run pytest -q
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests
```
Expected: 全部 PASS。

- [ ] **Step 2: 构建 dev 包**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: 成功;产物在 `<repo>/build/mac/arm64/dev/Teleport.app`。

- [ ] **Step 3: 端到端活验(人工 GUI,对照 spec §8.2)**

起 [[enterprise-account-system]] 服务端栈 + seed 租户(dadou),全新 profile 启动 Teleport.app,逐条确认:
1. 启动即落 enroll 页;地址栏手敲 `https://example.com` 被弹回 enroll(门禁生效)。
2. 完成手机号登录 + 受管 profile 纳管。
3. device-manager `register_profile` 200(DASHERLESS)+ 用户策略 200 拉到。
4. 纳管后:可正常访问任意网站;重启浏览器(含断网)仍放行(凭持久化纳管态)。

> 第一轮**不**验「策略置 false 放开未登录」(§8.2 步骤 5)——该项依赖 Task 11(策略映射),属迭代 1b。

- [ ] **Step 4: 记录结果,决定下一步**

把活验结果(通过/问题)记入分支提交说明或 spec 附注。据效果决定是否进迭代 1b(策略映射 + 多 profile 锁 + 就地纳管)。

---

## 迭代 1b(前瞻,**待第一轮活验后再细化为 bite-sized**)

> 第一轮以 pref 默认 true 驱动门禁,已端到端可评估。1b 让门禁可被租户经 CBCM/Keystone **放开**(`RequireEnrollmentToBrowse=false`),完成 spec §8.2 步骤 5。

- **企业策略 → pref 映射**:
  - 新增策略模板 YAML(仿 `Miscellaneous/BrowserAddPersonEnabled.yaml` 格式,`type: main`、`schema: boolean`、`default: true`、`per_profile: false`),放入合适 group。
  - 在 `components/policy/resources/templates/policies.yaml` 追加下一个空闲 id → `RequireEnrollmentToBrowse`(生成 `key::kRequireEnrollmentToBrowse`)。
  - 在 `chrome/browser/policy/configuration_policy_handler_list_factory.cc` 加一条 `SimplePolicyHandler{ key::kRequireEnrollmentToBrowse, prefs::kRequireEnrollmentToBrowse, base::Value::Type::BOOLEAN }`(patch)。
  - 去掉 Task 8 的独立 pref 注册改由 policy handler 对应 pref(或保留默认 + handler 覆盖,plan 1b 阶段定)。
  - fairyland:策略目录(catalog)加 `RequireEnrollmentToBrowse`(machine scope)一条目(见 `2026-06-07-...phase3-policy-framework-design.md`)。
  - 活验 §8.2 步骤 5:置 false 下发 → 未纳管也可直接上网。
- **多 profile 锁**:`AllowMultipleProfiles` 策略(默认 off)+ patch `ProfileManager::CanCreateProfileAtPath()` 硬禁第 2 个 profile。
- **就地纳管**:把 OIDC 新建-profile 改就地(`ConvertSourceProfileIntoManagedProfile()`),仅当锁多 profile 时需要。

---

### 1b 加固 backlog(迭代 1 终审记录)

迭代 1 整体终审(SHIP)记录的残留项,均**非阻塞**、合规威胁模型下可接受,留待 1b 加固:

1. **session restore 绕过 Layer 1(UX)**:用户开了「继续上次浏览」时,session restore 独立于 `DetermineStartupTabs` 的早返回恢复旧 tab(`startup_browser_creator_impl.cc` 的 `MaybeAsyncRestore`/`SYNCHRONOUS_RESTORE`,由 `SessionStartupPref` 控)。安全边界仍由 throttle 守住(每个恢复 tab 的导航被重定向到 enroll),但会闪现 N 个 enroll tab。1b 可在门控时清 `SessionStartupPref` / 跳过同步 restore。
2. **prerender / fenced-frame 主框架未覆盖**:throttle 用 `IsInPrimaryMainFrame()`,prerender 根帧与 `<fencedframe>` 主框架返回 false,门控期可后台预取跨源内容(激活前不展示)。与上游 `ManagedProfileRequiredNavigationThrottle` 同款取舍。1b 视需要扩展覆盖。
3. **整域放行面宽**:未纳管时可浏览 `.fairyland.io`/`.beansec.com` 下任意主机(spec 已认可)。该域下若有 open-redirect/用户内容主机,门控期可达。1b 可收窄到精确 enroll/OP/accounts 主机集。

另两个非阻塞 Minor(迭代 1 保留原样):`ShouldGateProfile` 的 `IsOffTheRecord()` 被 `!IsRegularProfile()` 覆盖、冗余;启动用 `LaunchResult::kNormally`(热启动下 `kWithGivenUrls` 语义略准)。

## Self-Review(对照 spec)

- **spec §2 In(第一轮)**:策略默认 on(Task 8 pref 默认 true;策略映射移 1b 但默认行为已是 on)✓;throttle(Task 6/7)✓;启动导向(Task 9)✓;判定谓词(Task 5)✓;复用既有 OIDC(未改 OIDC 代码)✓;macOS 活验(Task 10)✓;gtest(Task 1–4)✓。
- **spec §2 Out**:多 profile 锁 / 就地纳管 / forced-signin 锁 / GPO / 周期重查——均未出现在 Task 1–10,1b 仅前瞻 ✓。
- **spec §7 假设**:假设 2(纳管谓词 accessor)已在 Task 5 钉死(`GetProfileManagementId` + `GetCloudPolicyManager()->core()->store()->has_policy()`)✓;假设 1/3/4(策略拉取不走导航层、注册点时序、多主机白名单)由 Task 7/10 活验 + Task 3 的域后缀白名单覆盖 ✓。
- **占位符扫描**:无 TODO/TBD;每步含实际代码/命令。Task 7/8/9 的「确认形参名/member 名」是 patch 生成前的就地核对,非占位(已给 grep 定位法)。
- **类型/命名一致**:`prefs::kRequireEnrollmentToBrowse`、`ShouldGateProfile`/`IsEnrolled`/`ShouldBlockNavigation`/`IsEnrollmentFlowUrl`/`EnterpriseEnrollmentDomainSuffixes`/`TeleportEnrollmentGateThrottle` 全程一致 ✓。
- **范围细化**:策略映射(spec §6 + §8.2 步骤 5)移至迭代 1b——这是对 spec 的一处务实拆分(让核心门禁先可评估),已在 Task 10/1b 显式标注。
