# Phase 1 实现计划 · 设备纳管点亮 + 企业管理面品牌化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Teleport 非品牌 macOS 构建上点亮 Chrome 企业版的设备级 CBCM 纳管(MDM 下发 enrollment token → 启动即机器注册 → 浏览器级签名策略生效),并确认企业管理面(`chrome://management`)品牌正确、无 Google 穿帮。

**Architecture:** 两个薄上游 patch(CBCM `IsEnabled()` 非品牌返回 true + macOS `browser_dm_token_storage_mac.mm` 把 enrollment 读取重指到单一固定基础域 `com.beansec.Teleport` 与 `/Library/Teleport/` 路径,对齐 Chrome 的固定 id 语义),可变常量收进新的 `//teleport` 源码件 `teleport_enterprise_enrollment`(走 gtest)。服务端复用账号体系已活验的机器 `register_browser` + 机器级签名策略下发,本 phase 不动服务端。管理面字符串品牌已由 `branding_strings.py` 覆盖,本 phase 只做受管态验证 + 捕获残留。

**Tech Stack:** Chromium M148 overlay(GN `//teleport` source_set + `test("teleport_unittests")`)、`git apply` 文本 patch、`scripts/apply_patches.py`、`autoninja`/`gn`、docker.lima fairyland 栈(device-manager)。

**上位文档:** spec `docs/superpowers/specs/2026-06-04-enterprise-alignment-phase1-device-enrollment-design.md`;总纲 `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`。

**分支/worktree:** `worktree-chrome-enterprise-alignment`(`<repo>/.claude/worktrees/chrome-enterprise-alignment`)。

---

## 关键事实(实现前必读,已核实于 M148 检出)

- **检出位置**:`$TELEPORT_CHROMIUM_DIR`(本机 = `/Users/liulichao/workspace/teleport/chromium`),其 `src/teleport` 是指向**某个 teleport 工作树的 `src/`** 的符号链接。**从 worktree 构建 overlay 改动前,必须把该 symlink 指向本 worktree 的 `src/`**(Task 0)。
- **overlay 源码件**:`src/common/teleport_enterprise_urls.{h,cc,_unittest.cc}` 是同类常量件的范例(header guard `TELEPORT_COMMON_*`、`namespace teleport`、`#include "teleport/common/..."`);在 `src/BUILD.gn` 的 `source_set("teleport")` 与 `test("teleport_unittests")` 两处 `sources` 注册。
- **patch 制法**:直接编辑 `chromium/src` 下目标文件 → 构建验证 → `git -C "$TELEPORT_CHROMIUM_DIR/src" diff -- <file> > patches/<mirror-path>.patch`。一文件一 patch,路径镜像 `chromium/src` 下路径。`apply_patches.py` 幂等。
- **运行 dev 构建不再加 `--disable-field-trial-config`**(已由 GN arg `disable_fieldtrial_testing_config=true` 构建期关掉;见项目记忆 `no-disable-field-trial-config-flag`)。
- **dev 构建的 DM 端点默认已指向 fairyland dev**(账号体系 buildflag `teleport_use_release_endpoints=false` → `dm.teleport.fairyland.io`,经 docker.lima + `--resolve`/`/etc/hosts` 联通本地 device-manager)。
- **目标文件确切现状**:
  - `components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc` 的 `IsEnabled()`(~:99-106):非品牌分支 `return CommandLine...HasSwitch(kEnableChromeBrowserCloudManagement);`。
  - `chrome/browser/policy/browser_dm_token_storage_mac.mm`:`kDmTokenBaseDir`(:45 `"Google/Chrome Cloud Enrollment/"`)、`kEnrollmentTokenFilePath`(:49-50 `/Library/Google/Chrome/CloudManagementEnrollmentToken`)、`kEnrollmentOptionsFilePath`(:55-56 `/Library/Google/Chrome/CloudManagementEnrollmentOptions`)、`kBundleId`(:62 `CFSTR("com.google.Chrome")`,被 :124/:130/:158/:161 使用);`kEnrollmentTokenPolicyName`/`kEnrollmentMandatoryOptionPolicyName` 是标准 MDM 策略键名,**保持不变**。

---

## 文件结构(本 phase 触碰)

- **新建** `src/common/teleport_enterprise_enrollment.h` — 固定基础 bundle id + enrollment 文件路径 + DMToken 存储子目录常量(`namespace teleport`)。
- **新建** `src/common/teleport_enterprise_enrollment.cc` — 仅 include 头(常量是 header-only `inline constexpr`;留 .cc 占位以对齐既有件结构并便于将来加逻辑)。
- **新建** `src/common/teleport_enterprise_enrollment_unittest.cc` — gtest 断言常量值。
- **改** `src/BUILD.gn` — 两处 `sources` 注册新件。
- **新建** `patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch` — CBCM 启用。
- **新建** `patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch` — enrollment 读取重指 + include teleport 常量。
- **可能新建** `patches/...`(若 Task 7 发现管理面残留 Chrome 串需 patch)。
- **新建** `docs/enterprise-device-enrollment.md` — MDM 下发 + 验证文档。

---

## Task 0: 工作树构建接线(把 overlay symlink 指向本 worktree)

**Files:** 无源码改动(环境接线)。

- [ ] **Step 1: 确认在 worktree 内,且 chromium 检出可见**

Run:
```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
ls -l "$TELEPORT_CHROMIUM_DIR/src/teleport"   # 当前 symlink 指向(可能是 main 的 src）
```
Expected: 列出 `chromium/src/teleport` 现状。

- [ ] **Step 2: 把 `src/teleport` + `build` 链接重指到本 worktree**

Run:
```bash
python scripts/bootstrap.py --skip-sync
ls -l "$TELEPORT_CHROMIUM_DIR/src/teleport"
readlink "$TELEPORT_CHROMIUM_DIR/src/teleport"
```
Expected: `chromium/src/teleport` 现在解析到 `<worktree>/src`;`build → chromium/src/out`。

- [ ] **Step 3: 应用现有 overlay(幂等,确认基线干净)**

Run:
```bash
python scripts/apply_patches.py
```
Expected: 打印逐个 `apply patches/...` 与 `overlay branding/` + `overlay applied.`,无报错(账号体系的 4 个既有 patch 也会重新应用/已应用)。

> 完成 Phase 1 后切回 main 工作时,在 main 检出再跑一次 `python scripts/bootstrap.py --skip-sync` 把 symlink 指回 main 的 `src/`。

---

## Task 1: `//teleport` enrollment 常量件(TDD)

**Files:**
- Create: `src/common/teleport_enterprise_enrollment.h`
- Create: `src/common/teleport_enterprise_enrollment.cc`
- Test: `src/common/teleport_enterprise_enrollment_unittest.cc`
- Modify: `src/BUILD.gn`(两处 `sources`)

- [ ] **Step 1: 写失败测试**

Create `src/common/teleport_enterprise_enrollment_unittest.cc`:
```cpp
#include "teleport/common/teleport_enterprise_enrollment.h"

#include <string_view>

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Machine-level CBCM enrollment reads from a single FIXED base bundle id for
// all channels (mirrors Chrome's deliberate "com.google.Chrome no matter what"
// behavior), so one MDM payload enrolls every channel.
TEST(TeleportEnterpriseEnrollmentTest, ManagedPrefsBundleIdIsFixedBaseId) {
  EXPECT_EQ(std::string_view(kManagedPrefsBundleId), "com.beansec.Teleport");
}

TEST(TeleportEnterpriseEnrollmentTest, EnrollmentFilePathsUnderLibraryTeleport) {
  EXPECT_EQ(std::string_view(kEnrollmentTokenFilePath),
            "/Library/Teleport/CloudManagementEnrollmentToken");
  EXPECT_EQ(std::string_view(kEnrollmentOptionsFilePath),
            "/Library/Teleport/CloudManagementEnrollmentOptions");
}

TEST(TeleportEnterpriseEnrollmentTest, DmTokenStorageDirIsChannelAgnostic) {
  EXPECT_EQ(std::string_view(kDmTokenStorageDir), "Teleport/Cloud Enrollment/");
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: 注册到 BUILD.gn(否则编不出测试)**

Modify `src/BUILD.gn` — 在 `source_set("teleport")` 的 `sources` 列表(`common/teleport_enterprise_urls.*` 之后)插入:
```gn
    "common/teleport_enterprise_enrollment.cc",
    "common/teleport_enterprise_enrollment.h",
```
在 `test("teleport_unittests")` 的 `sources` 列表(`common/teleport_enterprise_urls_unittest.cc` 之后)插入:
```gn
    "common/teleport_enterprise_enrollment_unittest.cc",
```

- [ ] **Step 3: 运行测试,确认因缺头/缺符号而失败**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests
```
Expected: 编译失败(`teleport/common/teleport_enterprise_enrollment.h` 不存在)。

> 若 `out/mac/arm64/dev` 尚不存在,先 `gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'`。

- [ ] **Step 4: 写头文件**

Create `src/common/teleport_enterprise_enrollment.h`:
```cpp
#ifndef TELEPORT_COMMON_TELEPORT_ENTERPRISE_ENROLLMENT_H_
#define TELEPORT_COMMON_TELEPORT_ENTERPRISE_ENROLLMENT_H_

namespace teleport {

// Machine-level (CBCM) enrollment identity for macOS. We deliberately use a
// SINGLE FIXED base bundle id for every channel (stable/canary/beta), mirroring
// upstream Chrome's "explicitly com.google.Chrome, no matter what this app's
// bundle id is" behavior: machine enrollment is a whole-machine, channel-
// agnostic concept, so one MDM payload enrolls all channels. This is the value
// the patched browser_dm_token_storage_mac.mm reads managed prefs from and the
// plist (/Library/<id>.plist) CFPreferences resolves.
inline constexpr char kManagedPrefsBundleId[] = "com.beansec.Teleport";

// File fallbacks for the enrollment token / options (read when the managed
// preference is not forced). Mirror Chrome's /Library/Google/Chrome/... paths.
inline constexpr char kEnrollmentTokenFilePath[] =
    "/Library/Teleport/CloudManagementEnrollmentToken";
inline constexpr char kEnrollmentOptionsFilePath[] =
    "/Library/Teleport/CloudManagementEnrollmentOptions";

// Per-user subdirectory under DIR_APP_DATA where the obtained machine DMToken
// is cached. Channel-agnostic (matches the single-base-id enrollment domain).
// Mirrors Chrome's "Google/Chrome Cloud Enrollment/".
inline constexpr char kDmTokenStorageDir[] = "Teleport/Cloud Enrollment/";

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_ENTERPRISE_ENROLLMENT_H_
```

- [ ] **Step 5: 写 .cc 占位(对齐既有件结构)**

Create `src/common/teleport_enterprise_enrollment.cc`:
```cpp
#include "teleport/common/teleport_enterprise_enrollment.h"

// Constants are header-only (inline constexpr). This translation unit exists to
// mirror the layout of the other //teleport common components and to host any
// future non-constant enrollment helpers.

namespace teleport {}  // namespace teleport
```

- [ ] **Step 6: 运行测试,确认通过**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportEnterpriseEnrollmentTest.*'
```
Expected: 3 个测试 PASS。

- [ ] **Step 7: 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
git add src/common/teleport_enterprise_enrollment.h \
        src/common/teleport_enterprise_enrollment.cc \
        src/common/teleport_enterprise_enrollment_unittest.cc \
        src/BUILD.gn
git commit -m "feat(enterprise): add //teleport enrollment constants (fixed base id + paths)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: patch ① — CBCM `IsEnabled()` 非品牌返回 true

**Files:**
- Edit (checkout): `chromium/src/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc`
- Create (patch): `patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch`

- [ ] **Step 1: 编辑检出文件**

在 `chromium/src/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc` 的 `IsEnabled()` 里,把非品牌分支替换为无条件 true:
```cpp
// static
bool ChromeBrowserCloudManagementController::IsEnabled() {
#if BUILDFLAG(GOOGLE_CHROME_BRANDING)
  return true;
#else
  // Teleport is an enterprise browser: machine-level cloud management is always
  // available in our unbranded build, without requiring the
  // --enable-chrome-browser-cloud-management switch (which is unreliable across
  // channels). Whether the browser actually enrolls remains gated on the
  // presence of an enrollment token — CreatePolicyManager() returns early and
  // the controller no-ops when no token is configured.
  return true;
#endif
}
```

- [ ] **Step 2: 确认仍能编译该 target**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev components/enterprise/browser/controller
```
Expected: 编译通过(若该精确 target 名不可用,跳过,留待 Task 5 的整包构建一并验证)。

- [ ] **Step 3: 捕获为 patch**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment/patches/components/enterprise/browser/controller
git diff -- components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc \
  > /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment/patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch
```

- [ ] **Step 4: 校验 patch 可逆向/正向应用(幂等性自检)**

Run:
```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
git -C "$TELEPORT_CHROMIUM_DIR/src" apply --reverse --check \
  patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch && echo "REVERSE-OK (applies cleanly)"
```
Expected: `REVERSE-OK`(说明 patch 与检出一致、可被 apply_patches 正向重放)。

- [ ] **Step 5: 提交 patch**

```bash
git add patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch
git commit -m "feat(enterprise): patch CBCM IsEnabled() true in unbranded build

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: patch ② — macOS enrollment 读取重指到 Teleport 域/路径

**Files:**
- Edit (checkout): `chromium/src/chrome/browser/policy/browser_dm_token_storage_mac.mm`
- Create (patch): `patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch`

- [ ] **Step 1: 加 include(teleport 常量 + 转换/NoDestructor 依赖)**

在 `browser_dm_token_storage_mac.mm` 顶部 include 区(其它 `#include` 之间,按字母序就近)加入:
```cpp
#include "base/no_destructor.h"
#include "base/strings/sys_string_conversions.h"
#include "teleport/common/teleport_enterprise_enrollment.h"
```
(文件已使用 `base::apple::ScopedCFTypeRef`,其头已在;若编译报缺 `base/apple/foundation_util.h` 再补。)

- [ ] **Step 2: 把 `kBundleId` 字面量改为基于 teleport 常量的进程级单例**

将:
```cpp
// Explicitly access the "com.google.Chrome" bundle ID, no matter what this
// app's bundle ID actually is. All channels of Chrome should obey the same
// policies.
const CFStringRef kBundleId = CFSTR("com.google.Chrome");
```
替换为:
```cpp
// Explicitly access a SINGLE FIXED base bundle id (teleport::
// kManagedPrefsBundleId), no matter what this app's bundle id actually is. All
// channels of Teleport (stable/canary/beta) obey the same machine-level
// policies, so one MDM payload enrolls every channel — mirroring upstream
// Chrome's fixed-"com.google.Chrome" behavior.
CFStringRef ManagedPrefsBundleId() {
  static const base::NoDestructor<base::apple::ScopedCFTypeRef<CFStringRef>>
      bundle_id(base::SysUTF8ToCFStringRef(teleport::kManagedPrefsBundleId));
  return bundle_id->get();
}
```
然后把该文件内所有 `kBundleId` 使用处(`GetEnrollmentTokenFromPolicy` ~:124/:130、`IsEnrollmentMandatoryByPolicy` ~:158/:161)改为 `ManagedPrefsBundleId()`。

- [ ] **Step 3: 把三处硬编码路径改为引用 teleport 常量**

将:
```cpp
const char kDmTokenBaseDir[] =
    FILE_PATH_LITERAL("Google/Chrome Cloud Enrollment/");
```
改为:
```cpp
const char* const kDmTokenBaseDir = teleport::kDmTokenStorageDir;
```
将:
```cpp
const char kEnrollmentTokenFilePath[] =
    FILE_PATH_LITERAL("/Library/Google/Chrome/CloudManagementEnrollmentToken");
```
改为:
```cpp
const char* const kEnrollmentTokenFilePath =
    teleport::kEnrollmentTokenFilePath;
```
将:
```cpp
const char kEnrollmentOptionsFilePath[] = FILE_PATH_LITERAL(
    "/Library/Google/Chrome/CloudManagementEnrollmentOptions");
```
改为:
```cpp
const char* const kEnrollmentOptionsFilePath =
    teleport::kEnrollmentOptionsFilePath;
```

- [ ] **Step 4: 更新读策略文件路径的注释(:118 附近)**

把 `// Get the enrollment token from policy file: /Library/com.google.Chrome.plist.` 改为
`// Get the enrollment token from policy file: /Library/com.beansec.Teleport.plist.`
(CFPreferences 依 `ManagedPrefsBundleId()` 自动解析该 plist,无需路径常量。)

- [ ] **Step 5: 编译验证(.mm 能解析 teleport 头与转换)**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev chrome/browser/policy 2>/dev/null || \
  echo "(target 名不通用,留待 Task 5 整包构建验证)"
```
Expected: 通过,或留待 Task 5。

- [ ] **Step 6: 捕获为 patch**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
mkdir -p /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment/patches/chrome/browser/policy
git diff -- chrome/browser/policy/browser_dm_token_storage_mac.mm \
  > /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment/patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch
```

- [ ] **Step 7: 幂等性自检 + 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
git -C "$TELEPORT_CHROMIUM_DIR/src" apply --reverse --check \
  patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch && echo "REVERSE-OK"
git add patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch
git commit -m "feat(enterprise): patch macOS enrollment read to fixed Teleport domain/paths

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 整包构建 + apply_patches 幂等回归

**Files:** 无(集成验证)。

- [ ] **Step 1: 干净重放 overlay(确认两 patch 与既有 overlay 共存幂等)**

Run:
```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
python scripts/apply_patches.py
```
Expected: 列出包含两个新 patch 的全部 `apply`,`overlay applied.` 无报错。

- [ ] **Step 2: 构建 chrome(dev)**

Run:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev chrome
```
Expected: 构建成功(增量;若首次则较久)。产物 `out/mac/arm64/dev/Teleport.app`(亦在 `<repo>/build/mac/arm64/dev/`)。

- [ ] **Step 3: 跑 //teleport 单测回归**

Run:
```bash
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests
```
Expected: 全绿(含 Task 1 的 3 个新测试)。

- [ ] **Step 4: 提交(若 apply_patches 改动了被跟踪文件则无;通常此步无改动)**

无文件改动则跳过提交。

---

## Task 5: 端到端活验 — 机器纳管 + 浏览器级策略

**Files:** 无源码改动(对 docker.lima fairyland 栈联调)。

- [ ] **Step 1: 起 fairyland device-manager 栈**

Run(在 fairyland 仓 / 其 worktree,按账号体系 e2e 须知):
```bash
cd /Users/liulichao/workspace/fairyland
docker.lima compose up -d teleport-device-manager teleport-root-signer   # + 依赖(caddy/db/keystone)
docker.lima logs teleport-device-manager --tail=20   # 确认无 "failed to build"
```
Expected: device-manager 起来,日志含 "policy signing wired (per-tenant keys + root signer)"。

- [ ] **Step 2: 生成一个 per-tenant 机器 enrollment token**

读 `proto/teleport/v1` 找控制面方法(账号体系已用 `CreateEnrollmentToken` gRPC),用 grpcurl 取 token(确认服务/方法/端口后填入):
```bash
# 模板 —— 按 proto 实际 service/method/port 调整:
docker.lima exec teleport-device-manager grpcurl -plaintext \
  -d '{"tenant_id":"<tenant>","kind":"BROWSER"}' \
  localhost:<grpc_port> teleport.v1.DeviceManagerControl/CreateEnrollmentToken
```
Expected: 返回一个 enrollment token 串。记为 `<TOKEN>`。

> 若已有 seed 出的样例 token,可直接复用,跳过本步。

- [ ] **Step 3: 模拟 MDM 下发 — 写 enrollment token 文件**

Run:
```bash
sudo mkdir -p /Library/Teleport
printf '%s' '<TOKEN>' | sudo tee /Library/Teleport/CloudManagementEnrollmentToken >/dev/null
```
Expected: 文件写入(机器级路径,需 sudo;真 MDM 走 Configuration Profile,见 Task 7)。

- [ ] **Step 4: 启动 dev 构建并观察机器注册**

Run:
```bash
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport" \
  --no-proxy-server --enable-logging --v=1 \
  --vmodule='cloud_policy_client=2,browser_dm_token_storage*=2,cloud_policy_validator=2' \
  2>&1 | tee /tmp/teleport-phase1.log
```
Expected(日志):读到 enrollment token(来自 `/Library/Teleport/...`)→ `register`(type=TYPE_BROWSER, `Authorization: GoogleEnrollmentToken`)HTTP 200 → 拿到机器 DMToken → 浏览器级 `policy` fetch 200 + 验签通过。

- [ ] **Step 5: 浏览器内核对**

在浏览器:
- 打开 `chrome://policy` → 见 Cloud(机器级 `google/chrome/machine-level-user`)来源的策略(如 device-manager 下发的样例 `AuthServerAllowlist`),Status OK。
- 打开 `chrome://management` → 显示「Your browser is managed by …」+ 受管说明文案为 Teleport 品牌(非 Chrome/Chromium)。

Expected: 两页均符合;DMToken 缓存落 `~/Library/Application Support/Teleport/Cloud Enrollment/`(非 Google 路径)。

- [ ] **Step 5b: 验证 macOS Platform 策略路径(spec §4.4,经 forced 受管偏好)**

上面 Step 3 走的是**文件兜底**路径。本步验证**受管偏好(forced)**路径——它同时覆盖 `BaseBundleID()`→`com.beansec.Teleport` 域解析与 `PolicyLoaderMac` 读平台策略两件事。装一个最小 Configuration Profile(或写 `/Library/Managed Preferences/` 受管域),把 enrollment token 设为 forced,并附带一条平台策略(如 `HomepageLocation`)到 `com.beansec.Teleport` 域:
```bash
# 用一个临时 .mobileconfig(payload domain = com.beansec.Teleport,含
# CloudManagementEnrollmentToken + HomepageLocation),装载后重启 Teleport:
sudo profiles install -path /tmp/teleport-managed.mobileconfig   # 真机/测试机
```
打开 `chrome://policy`:确认 ① enrollment 经 forced 受管偏好被读到(机器纳管照常 200);② `HomepageLocation` 以 **Platform**(非 Cloud)来源显示、Status OK。
Expected: enrollment via forced managed pref 生效;平台策略以 Platform 来源生效 → 证明 `BaseBundleID()` 域解析与 `PolicyLoaderMac` 在我们构建无品牌门控、开箱可用。

> 若测试机不便装 Configuration Profile,记录为「文件路径已验证;受管偏好路径理论一致(同一 `ManagedPrefsBundleId()`/`CFPreferencesAppValueIsForced`),留真机回归」,并在 Task 7 文档中给出 .mobileconfig 样例。

- [ ] **Step 6: 记录验证证据**

把 `/tmp/teleport-phase1.log` 关键行 + 两页观察写进 PR 描述 / 验证笔记(本 phase 无单测覆盖的行为以此活验为准)。

---

## Task 6: 残留状态核查(空 token / 并存)

**Files:** 无源码改动(行为核实;若发现 bug 则回到对应 Task 修)。

- [ ] **Step 1: 空 token 不误纳管**

移除 token 后重启,确认无误注册:
```bash
sudo rm -f /Library/Teleport/CloudManagementEnrollmentToken
# 重启 Teleport,grep 日志
grep -iE "enrollment token|register" /tmp/teleport-phase1b.log || echo "no enrollment attempted (expected)"
```
Expected: 无 enrollment token → 不发起 register(`IsEnabled()=true` 但 controller no-op)。

- [ ] **Step 2: 与用户 OIDC 纳管并存**

在已机器纳管的浏览器里走一遍账号体系的用户 OIDC 登录(`/start?tenant=<slug>`),确认机器级(`machine-level-user`)与用户级(`user`)两套 DMToken/策略各自生效、互不干扰(`chrome://policy` 两 scope 并列、Status 均 OK)。
Expected: 两条纳管路径并存正常。

- [ ] **Step 3: 数据目录无冲突**

确认固定基础域 enrollment 不与 per-channel 数据目录(`CrProductDirName`,如 `Teleport Canary`)冲突:DMToken 缓存在固定 `Teleport/Cloud Enrollment/`,profile 数据仍各渠道独立。
Expected: 无冲突。

> 本 Task 不产出提交;发现问题回到 Task 2/3 修正后重跑 Task 4–5。

---

## Task 7: 管理面品牌受管态验证 + MDM 文档

**Files:**
- 可能 Create: `patches/...`(若发现可见的残留 "Chrome"/"Chromium" 串)
- Create: `docs/enterprise-device-enrollment.md`

- [ ] **Step 1: 受管态扫描可见的残留品牌**

在已机器纳管的浏览器,逐一查看并截图:`chrome://management`、`chrome://policy`、工具栏「⋮ 受管」图标 tooltip / 应用菜单「由组织管理」项。记录任何仍显示 "Chrome" / "Chromium" / "Google Chrome" 的可见文案。

> 已知:`management_strings.grdp` 的受管说明已由 `branding_strings.py` 品牌化为 Teleport(可复现)。`branding_strings.py` 的 `sweep_chrome` 默认关,故 "Chrome Browser Cloud Management" / "Chrome Enterprise Core/Connectors" 等被**刻意保留**——若这些出现在上述受管面且不希望露出,在本步记录。

- [ ] **Step 2: 对每个残留项决策并落地**

对每个确认要改的可见串,二选一:
- 若属 `branding_strings.py` 已覆盖文件的遗漏 → 在该脚本的目标/规则里补(并加 `scripts/tests/test_branding_strings.py` 用例),重跑 `apply_patches.py` 验证。
- 若属脚本不覆盖的独立串 → 加一文件一 patch(镜像路径)。
然后 `python scripts/apply_patches.py` + 重建 + 复看该面。

> 若 Step 1 未发现需改项(管理面已全品牌),本 Task 仅产出文档(Step 3),并在 PR 注明「受管态管理面品牌已由既有 branding sweep 覆盖,无新增改动」。

- [ ] **Step 3: 写 MDM 下发 + 验证文档**

Create `docs/enterprise-device-enrollment.md`(简体中文),涵盖:
- 设备纳管原理(固定基础域 `com.beansec.Teleport`、所有渠道共享一份配置、对齐 Chrome 的固定 id)。
- MDM Configuration Profile 下发 `CloudManagementEnrollmentToken`(及可选 `CloudManagementEnrollmentMandatory`)到受管偏好域 `com.beansec.Teleport` 的样例 plist。
- 文件兜底路径 `/Library/Teleport/CloudManagementEnrollmentToken`(dev/手工验证用,需管理员权限)。
- 验证步骤(`chrome://policy` 看 Cloud 机器级来源、`chrome://management` 看品牌)。
- 与用户 OIDC 纳管的关系(机器级登录前、用户级登录后,两套并存)。

- [ ] **Step 4: 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
git add docs/enterprise-device-enrollment.md patches/ scripts/ 2>/dev/null
git commit -m "docs(enterprise): device-enrollment MDM guide + managed-state branding check

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 完成标准(Definition of Done)

- [ ] `//teleport` enrollment 常量件 + gtest 绿。
- [ ] 两个 patch 入库、`apply_patches.py` 幂等重放无报错、整包 dev 构建成功。
- [ ] e2e:MDM/文件下发 enrollment token → 机器 `register_browser` 200 → 机器 DMToken → 浏览器级签名策略 fetch 200 + 应用;`chrome://policy` 见机器级 Cloud 来源、`chrome://management` 品牌正确。
- [ ] 空 token 不误纳管;机器级与用户级纳管并存正常;DMToken 缓存落 Teleport 路径(非 Google)。
- [ ] 受管态管理面无非预期的 "Chrome/Chromium" 可见穿帮(残留已 patch 或确认无)。
- [ ] MDM 下发 + 验证文档落地。

## 风险与回退

- **整包构建耗时**:首次数小时;尽量增量。Task 2/3 的单 target 编译若 target 名不通用,可跳过、统一在 Task 4 验证。
- **patch 漂移**:patch 由检出 diff 捕获,`git apply --reverse --check` 自检确保可被 `apply_patches.py` 重放;若上游基线变动需刷新 patch(本 phase 钉死 M148)。
- **worktree symlink**:Phase 1 期间 `chromium/src/teleport` 指向本 worktree;完成切回 main 前在 main 检出重跑 `bootstrap.py --skip-sync` 指回。
- **grpc/seed 取 token**:Task 5 Step 2 的 service/method/port 需按 `proto/teleport/v1` 实际核对(账号体系已有 `CreateEnrollmentToken`)。
```
