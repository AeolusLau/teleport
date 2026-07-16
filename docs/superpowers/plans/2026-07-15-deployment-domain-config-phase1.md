# 部署域名配置 Phase 1(纯客户端)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 6 处硬编码企业端点域名替换为「从单一基础域名 D 推导」,D 由五级来源解析器(本期实现 1/2/3/5 级)在启动早期解出;零 fairyland 改动,交付 dev 多栈切换、SaaS 零配置、私有化受管设备的客户端机制。

**Architecture:** 新增一个**最小依赖 target `teleport_deployment_config`**(只依赖 `//base` + `//url` + `:teleport_policy_buildflags`,**不依赖 `//content`**),使 `//components/policy` 能在不成环的前提下消费它(镜像现有 `teleport_policy_buildflags` 的隔离模式)。解析器把纯逻辑(规范化、JSON 解析、优先级选择)与不纯边缘(命令行 / CFPreferences / 文件读)分离,纯逻辑走 gtest TDD,边缘走冒烟。所有端点从 `DeploymentDomain()`(进程内缓存一次)推导。

**Tech Stack:** C++（Chromium M148 overlay，`//teleport` source_set + gtest）、GN、macOS（CFPreferences / stat）。

## Global Constraints

以下为 spec 的全局约束,每个 Task 隐含适用(值逐字取自 spec 与仓库 CLAUDE.md):

- **一文件一 patch**:每个 `.patch` 只改一个上游文件,文件名镜像其在 `chromium/src` 下的路径;同文件多处改动累加进同一 patch。禁止手改 hunk——改 patch 走「`apply_patches.py` → 编辑 `chromium/src/<file>` → `git -C chromium/src diff -- <path> > patches/<path>.patch` → 再 `apply_patches.py` 验证幂等」。
- **TDD 范围**:`//teleport` C++ 产品代码走 TDD(gtest);构建/工具脚本不强求。
- **信任是代码,不可配置**:策略验签根公钥永远烘焙,不进本子系统。
- **release 无后门**:命令行开关(第 1 级)整段 `#if !BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` 门控,release 二进制中不存在。
- **烘焙默认恒在**:解析器任一级失效即跳过 + 记 ERROR + 下探;第 5 级烘焙默认(dev=`fairyland.io`,release=`douan.cn`)保证 `DeploymentDomain()` 永不为空,浏览器永远能启动。
- **canonical 域名形式**:小写 ASCII punycode host + 可选 `:port`、无 trailing dot、无 scheme/path/query/userinfo;各级统一走硬化 `GURL` 解析,禁止裸字符串切分。
- **端口语义**:D 可含端口;端口参与 URL 构造与主机拼接,但 gate 后缀只取 host 部分(不含端口)。
- **构建/测试**(检出在仓库外时先 `export TELEPORT_CHROMIUM_DIR=/abs/path/to/chromium`):
  - 新增/删除 `src/` 文件或改 `src/BUILD.gn` 后:`gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'` 重新生成。
  - 改 `patches/` 后:`python scripts/apply_patches.py`(幂等)。
  - 跑单测:`autoninja -C out/mac/arm64/dev teleport_unittests && "$TELEPORT_CHROMIUM_DIR"/src/out/mac/arm64/dev/teleport_unittests --gtest_filter='<Filter>'`。
- **不改 gate 语义**:Phase 1 gate 保留「`.D` 后缀匹配」语义,仅把后缀从硬编码改为从 D 推导(host 部分)。精确主机白名单(spec D16 / §3.4a)依赖服务端在拦截页动态注入 OP host,属 Phase 2,**本期不做**。
- **不做第 4 级**:Local State 用户接受值(connect 页)属 Phase 2;本期 `SelectDeploymentDomain` 的第 4 级入参恒为 `nullopt`。

---

### Task 1: 脚手架 `teleport_deployment_config` target + 烘焙默认 + 缓存 getter

建立最小依赖 target 与只含第 5 级(烘焙默认)的 `DeploymentDomain()`,先跑通「返回烘焙默认、进程内缓存」的骨架,后续 Task 往里加级与推导。

**Files:**
- Create: `src/common/teleport_deployment_config.h`
- Create: `src/common/teleport_deployment_config.cc`
- Create: `src/common/teleport_deployment_config_unittest.cc`
- Modify: `src/BUILD.gn`（新增 `source_set("teleport_deployment_config")`;把新 unittest 源加入 `teleport_unittests`）

**Interfaces:**
- Produces:
  - `enum class teleport::DeploymentDomainSource { kCommandLine, kManagedPref, kMachineFile, kUserAccepted, kBakedDefault };`
  - `const std::string& teleport::DeploymentDomain();` — 缓存的基础域名 D,永不为空。
  - `teleport::DeploymentDomainSource teleport::DeploymentDomainSourceLevel();`
  - `std::string teleport::DeploymentDomainSourceLabel();` — 供 chrome://version 的人类可读来源标签。
  - `struct teleport::DeploymentResolution { std::string domain; DeploymentDomainSource source; };`

- [ ] **Step 1: Write the failing test**

创建 `src/common/teleport_deployment_config_unittest.cc`:

```cpp
#include "teleport/common/teleport_deployment_config.h"

#include "teleport/teleport_policy_buildflags.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// With no higher-priority source set (fresh process, no switch/pref/file),
// DeploymentDomain() must return the baked default for this build variant and
// report kBakedDefault as its source.
TEST(TeleportDeploymentConfigTest, FallsBackToBakedDefault) {
  EXPECT_FALSE(DeploymentDomain().empty());
  EXPECT_EQ(DeploymentDomainSourceLevel(), DeploymentDomainSource::kBakedDefault);
#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  EXPECT_EQ(DeploymentDomain(), "douan.cn");
#else
  EXPECT_EQ(DeploymentDomain(), "fairyland.io");
#endif
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: Write the header**

创建 `src/common/teleport_deployment_config.h`:

```cpp
#ifndef TELEPORT_COMMON_TELEPORT_DEPLOYMENT_CONFIG_H_
#define TELEPORT_COMMON_TELEPORT_DEPLOYMENT_CONFIG_H_

#include <string>

namespace teleport {

// Which source level supplied the effective deployment domain (for diagnostics).
enum class DeploymentDomainSource {
  kCommandLine,   // level 1 (dev builds only)
  kManagedPref,   // level 2
  kMachineFile,   // level 3
  kUserAccepted,  // level 4 (Phase 2; never selected in Phase 1)
  kBakedDefault,  // level 5
};

struct DeploymentResolution {
  std::string domain;
  DeploymentDomainSource source;
};

// The resolved base deployment domain D (e.g. "acme.internal" or
// "acme.internal:8443"). Resolved once on first call and cached for the process
// lifetime (D is immutable per process). Never empty — always falls back to the
// baked default for this build variant.
const std::string& DeploymentDomain();

// The source level that supplied DeploymentDomain(), for chrome://version.
DeploymentDomainSource DeploymentDomainSourceLevel();

// Human-readable label for DeploymentDomainSourceLevel() (e.g. "machine config
// file"), for the chrome://version diagnostic line.
std::string DeploymentDomainSourceLabel();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_DEPLOYMENT_CONFIG_H_
```

- [ ] **Step 3: Write minimal implementation (baked default only)**

创建 `src/common/teleport_deployment_config.cc`:

```cpp
#include "teleport/common/teleport_deployment_config.h"

#include "base/no_destructor.h"
#include "teleport/teleport_policy_buildflags.h"

namespace teleport {

namespace {

#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
constexpr char kBakedDefaultDomain[] = "douan.cn";
#else
constexpr char kBakedDefaultDomain[] = "fairyland.io";
#endif

// Resolve the deployment domain by descending the source precedence. Task 5
// prepends levels 1–3; for now only the baked default (level 5) exists.
DeploymentResolution ResolveUncached() {
  return {kBakedDefaultDomain, DeploymentDomainSource::kBakedDefault};
}

const DeploymentResolution& Cached() {
  static const base::NoDestructor<DeploymentResolution> resolution(
      ResolveUncached());
  return *resolution;
}

}  // namespace

const std::string& DeploymentDomain() {
  return Cached().domain;
}

DeploymentDomainSource DeploymentDomainSourceLevel() {
  return Cached().source;
}

std::string DeploymentDomainSourceLabel() {
  switch (DeploymentDomainSourceLevel()) {
    case DeploymentDomainSource::kCommandLine:
      return "command-line switch";
    case DeploymentDomainSource::kManagedPref:
      return "managed preference";
    case DeploymentDomainSource::kMachineFile:
      return "machine config file";
    case DeploymentDomainSource::kUserAccepted:
      return "user-accepted";
    case DeploymentDomainSource::kBakedDefault:
      return "built-in default";
  }
}

}  // namespace teleport
```

- [ ] **Step 4: Wire into `src/BUILD.gn`**

在 `src/BUILD.gn` 的 `config("sparkle_rpath")` 与 `buildflag_header("teleport_policy_buildflags")` 之后、`source_set("teleport")` 之前,新增:

```gn
# Minimal-dependency deployment-domain resolver + endpoint derivation. Deps only
# //base + //url (NOT //content), so //components/policy (browser_policy_connector)
# can consume the derived endpoints without a dependency cycle on :teleport —
# mirroring the teleport_policy_buildflags isolation above.
source_set("teleport_deployment_config") {
  sources = [
    "common/teleport_deployment_config.cc",
    "common/teleport_deployment_config.h",
  ]
  deps = [
    ":teleport_policy_buildflags",
    "//base",
    "//url",
  ]
  if (is_mac) {
    sources += [ "common/teleport_deployment_config_mac.mm" ]
  }
}
```

> 注:`_mac.mm` 在 Task 5 才创建。若本 Task 先构建,请暂不加 `if (is_mac)` 块,Task 5 再补;或先创建一个空的 `_mac.mm`(仅 `namespace teleport {}`)占位。推荐后者以保持 BUILD.gn 稳定——本步同时创建占位 `src/common/teleport_deployment_config_mac.mm`:
> ```cpp
> // Platform edges (command-line / CFPreferences / file) land here in Task 5.
> namespace teleport {}  // namespace teleport
> ```

在 `source_set("teleport")` 的 `deps` 列表加入 `":teleport_deployment_config"`(Task 7 起 `teleport_enterprise_urls.cc` 会用到)。

在 `test("teleport_unittests")` 的 `sources` 列表(按字母序,位于 `teleport_channel_unittest.cc` 之后合适处)加入:

```gn
    "common/teleport_deployment_config_unittest.cc",
```

并确保 `test("teleport_unittests")` 的 `deps` 含 `":teleport_deployment_config"`(新增一行 `":teleport_deployment_config",`)。

- [ ] **Step 5: Regenerate GN and run the test to verify it passes**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportDeploymentConfigTest.*'
```
Expected: `FallsBackToBakedDefault` PASS。

- [ ] **Step 6: Commit**

```bash
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_mac.mm \
        src/common/teleport_deployment_config_unittest.cc src/BUILD.gn
git commit -m "feat(deployment-config): scaffold resolver target with baked-default fallback"
```

---

### Task 2: `NormalizeDeploymentDomain`（硬化 GURL 规范化）

把任意候选域名字符串规范化为 canonical 形式或拒绝。这是所有来源级共用的输入闸门,也是身份验证域名比对(Phase 2)的基准。

**Files:**
- Modify: `src/common/teleport_deployment_config.h`（加声明)
- Modify: `src/common/teleport_deployment_config.cc`（加实现)
- Modify: `src/common/teleport_deployment_config_unittest.cc`（加测试)

**Interfaces:**
- Produces: `std::optional<std::string> teleport::NormalizeDeploymentDomain(std::string_view input);`
  - 返回 canonical `host[:port]`(小写 punycode host、无 trailing dot、无 scheme/path/query/fragment/userinfo);非法输入(空、含 `@`、含路径/query、多冒号、非法字符、IPv6 字面量)返回 `std::nullopt`。

- [ ] **Step 1: Write the failing tests**

在 `teleport_deployment_config_unittest.cc` 的匿名 namespace 内追加(并在文件顶部补 `#include <optional>`):

```cpp
TEST(TeleportDeploymentConfigNormalizeTest, AcceptsBareHost) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal"), "acme.internal");
}

TEST(TeleportDeploymentConfigNormalizeTest, LowercasesAndStripsTrailingDot) {
  EXPECT_EQ(NormalizeDeploymentDomain("ACME.Internal."), "acme.internal");
}

TEST(TeleportDeploymentConfigNormalizeTest, KeepsExplicitPort) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal:8443"), "acme.internal:8443");
}

TEST(TeleportDeploymentConfigNormalizeTest, ConvertsIdnToPunycode) {
  // "xn--" is the punycode ASCII form; a Unicode label must normalize to it.
  EXPECT_EQ(NormalizeDeploymentDomain("bücher.example"), "xn--bcher-kva.example");
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsUserinfo) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal:8443@evil.com"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsPathAndQuery) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal/enroll"), std::nullopt);
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal?x=1"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsScheme) {
  EXPECT_EQ(NormalizeDeploymentDomain("https://acme.internal"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsEmptyAndGarbage) {
  EXPECT_EQ(NormalizeDeploymentDomain(""), std::nullopt);
  EXPECT_EQ(NormalizeDeploymentDomain("   "), std::nullopt);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译失败(`NormalizeDeploymentDomain` 未声明)。

- [ ] **Step 3: Add declaration to header**

在 `teleport_deployment_config.h` 顶部加 `#include <optional>` 与 `#include <string_view>`,并在 `DeploymentDomainSourceLabel()` 声明之后加:

```cpp
// Normalize a candidate deployment domain to canonical form, or nullopt when the
// input is not a bare host[:port]. Canonical = lowercase ASCII (punycode) host +
// optional ":port", no trailing dot, no scheme/path/query/fragment/userinfo.
// Hardened against URL-parsing confusion (rejects userinfo, IPv6 literals, etc.).
std::optional<std::string> NormalizeDeploymentDomain(std::string_view input);
```

- [ ] **Step 4: Implement**

在 `teleport_deployment_config.cc` 加 include 与实现。文件顶部 include 区补:

```cpp
#include <optional>
#include <string_view>

#include "base/strings/string_util.h"
#include "url/gurl.h"
#include "url/third_party/mozilla/url_parse.h"
```

在匿名 namespace 外(或内后导出)加:

```cpp
std::optional<std::string> NormalizeDeploymentDomain(std::string_view input) {
  std::string trimmed(base::TrimWhitespaceASCII(input, base::TRIM_ALL));
  if (trimmed.empty()) {
    return std::nullopt;
  }
  // Parse via GURL with a synthetic https scheme, then re-extract host/port. Any
  // userinfo, path, query, or fragment means the input was not a bare host[:port].
  GURL url("https://" + trimmed);
  if (!url.is_valid() || !url.SchemeIs("https")) {
    return std::nullopt;
  }
  if (url.has_username() || url.has_password() || url.has_ref() ||
      url.has_query()) {
    return std::nullopt;
  }
  // Reject any non-root path (GURL synthesizes "/" for a bare host).
  if (url.path() != "/") {
    return std::nullopt;
  }
  const std::string host = url.host();  // GURL lowercases + punycodes the host.
  if (host.empty() || url.HostIsIPAddress()) {
    return std::nullopt;  // Deployment domains are named hosts, not IP literals.
  }
  std::string result = host;
  if (url.has_port()) {
    result += ":" + url.port();
  }
  return result;
}
```

> 说明:GURL 会把 host 小写化、把 IDN 转 punycode、剥除 trailing dot 的规范化由 `url::CanonicalizeHost` 处理;`has_username/has_password` 捕获 userinfo;合成 `https://` 后 `path()=="/"` 表示无路径。`HostIsIPAddress()` 拒绝 IPv4/IPv6 字面量(含 `[::1]` 类多冒号混淆)。

- [ ] **Step 5: Run to verify pass**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/teleport_unittests" \
  --gtest_filter='TeleportDeploymentConfigNormalizeTest.*'
```
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_unittest.cc
git commit -m "feat(deployment-config): hardened GURL-based domain normalization"
```

---

### Task 3: `SelectDeploymentDomain`（纯优先级选择器）

把「给定各级已读取候选 → 选最高优先级存在者」抽成纯函数,五级全排列可测,不触碰进程状态。

**Files:**
- Modify: `src/common/teleport_deployment_config.h`
- Modify: `src/common/teleport_deployment_config.cc`
- Modify: `src/common/teleport_deployment_config_unittest.cc`

**Interfaces:**
- Consumes: `DeploymentResolution`、`DeploymentDomainSource`（Task 1)。
- Produces:
  ```cpp
  DeploymentResolution teleport::SelectDeploymentDomain(
      std::optional<std::string> command_line,   // level 1 (nullopt in release)
      std::optional<std::string> managed_pref,    // level 2
      std::optional<std::string> machine_file,    // level 3
      std::optional<std::string> user_accepted,   // level 4 (nullopt in Phase 1)
      std::string baked_default);                 // level 5 (always present)
  ```

- [ ] **Step 1: Write the failing tests**

追加到 unittest:

```cpp
TEST(TeleportDeploymentConfigSelectTest, PrefersCommandLineOverAll) {
  auto r = SelectDeploymentDomain("cli.example", "pref.example", "file.example",
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "cli.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kCommandLine);
}

TEST(TeleportDeploymentConfigSelectTest, ManagedPrefBeatsFileAndBaked) {
  auto r = SelectDeploymentDomain(std::nullopt, "pref.example", "file.example",
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "pref.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kManagedPref);
}

TEST(TeleportDeploymentConfigSelectTest, FileBeatsBaked) {
  auto r = SelectDeploymentDomain(std::nullopt, std::nullopt, "file.example",
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "file.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kMachineFile);
}

TEST(TeleportDeploymentConfigSelectTest, FallsToBakedWhenAllAbsent) {
  auto r = SelectDeploymentDomain(std::nullopt, std::nullopt, std::nullopt,
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "baked.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kBakedDefault);
}

TEST(TeleportDeploymentConfigSelectTest, UserAcceptedSitsAboveBakedOnly) {
  auto r = SelectDeploymentDomain(std::nullopt, std::nullopt, std::nullopt,
                                  "user.example", "baked.example");
  EXPECT_EQ(r.domain, "user.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kUserAccepted);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译失败(`SelectDeploymentDomain` 未声明)。

- [ ] **Step 3: Add declaration**

在 header 的 `NormalizeDeploymentDomain` 声明后加:

```cpp
// Pure precedence selector: pick the highest-priority present candidate. Each
// argument is the already-read, already-normalized value from that source level
// (nullopt = level absent). baked_default is always present (level 5). Testable
// without touching process state.
DeploymentResolution SelectDeploymentDomain(
    std::optional<std::string> command_line,
    std::optional<std::string> managed_pref,
    std::optional<std::string> machine_file,
    std::optional<std::string> user_accepted,
    std::string baked_default);
```

- [ ] **Step 4: Implement**

在 `.cc` 加(匿名 namespace 外):

```cpp
DeploymentResolution SelectDeploymentDomain(
    std::optional<std::string> command_line,
    std::optional<std::string> managed_pref,
    std::optional<std::string> machine_file,
    std::optional<std::string> user_accepted,
    std::string baked_default) {
  if (command_line) {
    return {std::move(*command_line), DeploymentDomainSource::kCommandLine};
  }
  if (managed_pref) {
    return {std::move(*managed_pref), DeploymentDomainSource::kManagedPref};
  }
  if (machine_file) {
    return {std::move(*machine_file), DeploymentDomainSource::kMachineFile};
  }
  if (user_accepted) {
    return {std::move(*user_accepted), DeploymentDomainSource::kUserAccepted};
  }
  return {std::move(baked_default), DeploymentDomainSource::kBakedDefault};
}
```

- [ ] **Step 5: Run to verify pass**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/teleport_unittests" \
  --gtest_filter='TeleportDeploymentConfigSelectTest.*'
```
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_unittest.cc
git commit -m "feat(deployment-config): pure five-level precedence selector"
```

---

### Task 4: `ParseDeploymentConfigJson`（机器配置文件 JSON 解析)

把第 3 级机器文件的 JSON 内容解析为规范化后的 domain 或拒绝(缺字段/损坏/非法域名)。纯函数,不做文件 IO(IO 在 Task 5)。

**Files:**
- Modify: `src/common/teleport_deployment_config.h`
- Modify: `src/common/teleport_deployment_config.cc`
- Modify: `src/common/teleport_deployment_config_unittest.cc`
- Modify: `src/BUILD.gn`（`teleport_deployment_config` 的 deps 加 `//base` 已有;JSON 用 `base::JSONReader` 属 `//base`,无需新增 dep)

**Interfaces:**
- Consumes: `NormalizeDeploymentDomain`（Task 2)。
- Produces: `std::optional<std::string> teleport::ParseDeploymentConfigJson(std::string_view contents);`
  - 提取 `"domain"` 字段并经 `NormalizeDeploymentDomain` 规范化;缺失/非字符串/非法/JSON 损坏 → `nullopt`。

- [ ] **Step 1: Write the failing tests**

追加:

```cpp
TEST(TeleportDeploymentConfigJsonTest, ExtractsAndNormalizesDomain) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"domain":"ACME.Internal"})"),
            "acme.internal");
}

TEST(TeleportDeploymentConfigJsonTest, IgnoresReservedFields) {
  EXPECT_EQ(ParseDeploymentConfigJson(
                R"({"domain":"acme.internal","update_feed_url":"x"})"),
            "acme.internal");
}

TEST(TeleportDeploymentConfigJsonTest, RejectsMissingDomain) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"update_feed_url":"x"})"),
            std::nullopt);
}

TEST(TeleportDeploymentConfigJsonTest, RejectsNonStringDomain) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"domain":42})"), std::nullopt);
}

TEST(TeleportDeploymentConfigJsonTest, RejectsInvalidDomainValue) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"domain":"https://acme.internal/x"})"),
            std::nullopt);
}

TEST(TeleportDeploymentConfigJsonTest, RejectsMalformedJson) {
  EXPECT_EQ(ParseDeploymentConfigJson("{not json"), std::nullopt);
  EXPECT_EQ(ParseDeploymentConfigJson(""), std::nullopt);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译失败(未声明)。

- [ ] **Step 3: Add declaration**

header 追加:

```cpp
// Parse the machine config file JSON, returning the normalized "domain" value or
// nullopt (missing/non-string/invalid domain, or malformed JSON). Does no file IO.
std::optional<std::string> ParseDeploymentConfigJson(std::string_view contents);
```

- [ ] **Step 4: Implement**

`.cc` include 区补 `#include "base/json/json_reader.h"` 与 `#include "base/values.h"`;实现:

```cpp
std::optional<std::string> ParseDeploymentConfigJson(std::string_view contents) {
  std::optional<base::Value> value = base::JSONReader::Read(contents);
  if (!value || !value->is_dict()) {
    return std::nullopt;
  }
  const std::string* domain = value->GetDict().FindString("domain");
  if (!domain) {
    return std::nullopt;
  }
  return NormalizeDeploymentDomain(*domain);
}
```

- [ ] **Step 5: Run to verify pass**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/teleport_unittests" \
  --gtest_filter='TeleportDeploymentConfigJsonTest.*'
```
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_unittest.cc
git commit -m "feat(deployment-config): parse machine config file JSON to normalized domain"
```

---

### Task 5: 平台边缘（命令行 / 管控偏好 / 机器文件)+ 接入缓存解析器

实现三个不纯来源读取并接进 `ResolveUncached()`:第 1 级命令行(dev-only)、第 2 级管控偏好(强制 `CFPreferencesAppValueIsForced`)、第 3 级机器文件(`stat` 校验属主+权限)。文件信任闸门的**否定分支**(非 root-owned / 组写)可单测(测试文件属主非 root);肯定分支(root-owned 接受)走冒烟。

**Files:**
- Modify: `src/common/teleport_deployment_config.h`（导出可测的文件信任闸门)
- Modify: `src/common/teleport_deployment_config.cc`（`ResolveUncached()` 接入三级 + 跨平台文件信任逻辑)
- Create/Replace: `src/common/teleport_deployment_config_mac.mm`（CFPreferences IsForced 读 + 命令行读)
- Modify: `src/common/teleport_deployment_config_unittest.cc`

**Interfaces:**
- Consumes: `NormalizeDeploymentDomain`、`ParseDeploymentConfigJson`、`SelectDeploymentDomain`。
- Produces:
  - `bool teleport::IsMachineConfigFileTrusted(const base::FilePath& path);`（属主 uid==0 且非 group/world 可写;文件不存在返回 false)
  - `constexpr char teleport::kDeploymentConfigFilePath[] = "/Library/Teleport/DeploymentConfig.json";`
  - 内部(匿名 namespace,平台特化):`std::optional<std::string> ReadCommandLineDomain();`、`std::optional<std::string> ReadManagedPrefDomain();`、`std::optional<std::string> ReadMachineFileDomain();`

- [ ] **Step 1: Write the failing test（文件信任闸门否定分支)**

追加(顶部补 `#include "base/files/file_path.h"`、`#include "base/files/scoped_temp_dir.h"`、`#include "base/files/file_util.h"`):

```cpp
// A file owned by the (non-root) test user must be rejected: the machine config
// file is a root-only trust channel.
TEST(TeleportDeploymentConfigTrustTest, RejectsNonRootOwnedFile) {
  base::ScopedTempDir dir;
  ASSERT_TRUE(dir.CreateUniqueTempDir());
  base::FilePath path = dir.GetPath().AppendASCII("DeploymentConfig.json");
  ASSERT_TRUE(base::WriteFile(path, R"({"domain":"acme.internal"})"));
  // Test process runs as a non-root user, so the file is not uid==0-owned.
  EXPECT_FALSE(IsMachineConfigFileTrusted(path));
}

TEST(TeleportDeploymentConfigTrustTest, RejectsMissingFile) {
  base::ScopedTempDir dir;
  ASSERT_TRUE(dir.CreateUniqueTempDir());
  EXPECT_FALSE(
      IsMachineConfigFileTrusted(dir.GetPath().AppendASCII("nonexistent.json")));
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译失败(`IsMachineConfigFileTrusted` / `kDeploymentConfigFilePath` 未声明)。

- [ ] **Step 3: Add declarations to header**

header 顶部补 `#include "base/files/file_path.h"`;在 `ParseDeploymentConfigJson` 声明后加:

```cpp
// Absolute path of the machine-level deployment config file (level 3).
inline constexpr char kDeploymentConfigFilePath[] =
    "/Library/Teleport/DeploymentConfig.json";

// True iff path exists, is owned by uid 0 (root), and is not group/world
// writable. The machine config file is a root-only admin channel; a file that
// any non-root user could have planted or rewritten must not be trusted.
bool IsMachineConfigFileTrusted(const base::FilePath& path);
```

- [ ] **Step 4: Implement the trust gate + level wiring (cross-platform bits in .cc)**

`.cc` include 区补:

```cpp
#include <sys/stat.h>

#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/logging.h"
```

实现信任闸门(匿名 namespace 外):

```cpp
bool IsMachineConfigFileTrusted(const base::FilePath& path) {
  struct stat st;
  if (::lstat(path.value().c_str(), &st) != 0) {
    return false;  // Missing or unstattable.
  }
  if (!S_ISREG(st.st_mode)) {
    return false;  // Not a regular file (symlink/dir/device).
  }
  if (st.st_uid != 0) {
    return false;  // Must be root-owned.
  }
  if (st.st_mode & (S_IWGRP | S_IWOTH)) {
    return false;  // Must not be group/world writable.
  }
  return true;
}
```

替换 `ResolveUncached()` 为接入三级(`ReadCommandLineDomain`/`ReadManagedPrefDomain` 由 `_mac.mm` 提供,非 mac 平台在 `.cc` 用弱默认——本期 mac-only,`.cc` 提供 `#if !BUILDFLAG(IS_MAC)` 的 nullopt 桩):

```cpp
// Level 3 (cross-platform): read + trust-gate + parse the machine config file.
std::optional<std::string> ReadMachineFileDomain() {
  base::FilePath path(kDeploymentConfigFilePath);
  if (!IsMachineConfigFileTrusted(path)) {
    return std::nullopt;
  }
  std::string contents;
  if (!base::ReadFileToString(path, &contents)) {
    LOG(ERROR) << "[teleport-deployment] machine config file unreadable";
    return std::nullopt;
  }
  std::optional<std::string> domain = ParseDeploymentConfigJson(contents);
  if (!domain) {
    LOG(ERROR) << "[teleport-deployment] machine config file has no valid domain";
  }
  return domain;
}

DeploymentResolution ResolveUncached() {
  return SelectDeploymentDomain(
      ReadCommandLineDomain(), ReadManagedPrefDomain(), ReadMachineFileDomain(),
      /*user_accepted=*/std::nullopt, kBakedDefaultDomain);
}
```

在 `.cc` 为非 mac 平台补桩(mac 由 `_mac.mm` 提供真实实现),置于匿名 namespace:

```cpp
#if !BUILDFLAG(IS_MAC)
std::optional<std::string> ReadCommandLineDomain() { return std::nullopt; }
std::optional<std::string> ReadManagedPrefDomain() { return std::nullopt; }
#endif
```

include 区补 `#include "build/build_config.h"`（提供 `IS_MAC`）。

- [ ] **Step 5: Implement mac edges in `_mac.mm`**

替换 `src/common/teleport_deployment_config_mac.mm` 占位内容为:

```cpp
#include "teleport/common/teleport_deployment_config.h"

#import <Foundation/Foundation.h>

#include <optional>
#include <string>

#include "base/apple/foundation_util.h"
#include "base/apple/scoped_cftyperef.h"
#include "base/command_line.h"
#include "base/logging.h"
#include "base/strings/sys_string_conversions.h"
#include "teleport/common/teleport_enterprise_enrollment.h"  // kManagedPrefsBundleId
#include "teleport/teleport_policy_buildflags.h"

namespace teleport {

// Level 1: dev-only command-line switch. Compiled OUT of release binaries so it
// is not merely disabled but absent (Global Constraint: release has no backdoor).
std::optional<std::string> ReadCommandLineDomain() {
#if !BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  const base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();
  if (!cmd->HasSwitch("teleport-deployment-domain")) {
    return std::nullopt;
  }
  std::optional<std::string> d = NormalizeDeploymentDomain(
      cmd->GetSwitchValueASCII("teleport-deployment-domain"));
  if (!d) {
    LOG(ERROR) << "[teleport-deployment] --teleport-deployment-domain invalid";
  }
  return d;
#else
  return std::nullopt;
#endif
}

// Level 2: managed preference, read the SAME way the enrollment token is read
// (browser_dm_token_storage_mac.mm) — the configuration management system is not
// up this early, so read CFPreferences directly. CRITICAL: require
// CFPreferencesAppValueIsForced so that only an MDM-FORCED value is honored; a
// plain user-domain ~/Library/Preferences plist must NOT be trusted (else a
// non-privileged local user could inject a domain over the verified level-4
// entry — Global Constraint / spec D13).
std::optional<std::string> ReadManagedPrefDomain() {
  base::apple::ScopedCFTypeRef<CFStringRef> bundle_id(
      base::SysUTF8ToCFStringRef(kManagedPrefsBundleId));
  base::apple::ScopedCFTypeRef<CFStringRef> key(
      base::SysUTF8ToCFStringRef("DeploymentDomain"));
  base::apple::ScopedCFTypeRef<CFPropertyListRef> value(
      CFPreferencesCopyAppValue(key.get(), bundle_id.get()));
  if (!value ||
      !CFPreferencesAppValueIsForced(key.get(), bundle_id.get())) {
    return std::nullopt;
  }
  CFStringRef str = base::apple::CFCast<CFStringRef>(value.get());
  if (!str) {
    return std::nullopt;
  }
  std::optional<std::string> d =
      NormalizeDeploymentDomain(base::SysCFStringRefToUTF8(str));
  if (!d) {
    LOG(ERROR) << "[teleport-deployment] managed DeploymentDomain invalid";
  }
  return d;
}

}  // namespace teleport
```

在 `src/BUILD.gn` 的 `source_set("teleport_deployment_config")` deps 追加 `//content` 的替代——**注意不要引入 //content**;`base::CommandLine`、`base::apple::*` 均在 `//base`。`kManagedPrefsBundleId` 来自 `teleport_enterprise_enrollment.h`(在 `:teleport` source_set 内,会成环!)。**解决**:`kManagedPrefsBundleId` 是 header-only `inline constexpr`,直接 `#include "teleport/common/teleport_enterprise_enrollment.h"` 只取常量、不引入链接依赖;但 GN 的 `check` 可能要求显式 header 依赖。为避免环,**在 `_mac.mm` 内改为本地复制该常量**并加注释指向单一事实源:

```cpp
// Mirror of teleport::kManagedPrefsBundleId (teleport_enterprise_enrollment.h).
// Copied (not #included) to keep teleport_deployment_config free of a dep on the
// :teleport source_set (which pulls //content and would cycle with
// //components/policy). Keep in sync — both derive from the fixed base bundle id.
constexpr char kManagedPrefsBundleId[] = "cn.douan.Teleport";
```

并移除对 `teleport_enterprise_enrollment.h` 的 include。

- [ ] **Step 6: Run to verify pass (unit) + smoke note**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportDeploymentConfigTrustTest.*'
```
Expected: 否定分支 PASS。

冒烟(记入 `scripts/smoke_check.md`,不阻塞 commit):dev 构建加 `--teleport-deployment-domain=fairyland.test` 启动,`chrome://version`(Task 10 后)应显示来源 `command-line switch` + 域名 `fairyland.test`;root 写 `/Library/Teleport/DeploymentConfig.json` 后应显示来源 `machine config file`。

- [ ] **Step 7: Commit**

```bash
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_mac.mm \
        src/common/teleport_deployment_config_unittest.cc src/BUILD.gn
git commit -m "feat(deployment-config): platform edges — dev switch, forced managed pref, root-owned file gate"
```

---

### Task 6: 端点推导 helper（在最小 target 内)

把 D → 各端点 URL / 主机 / 后缀 的推导放进 `teleport_deployment_config`(供 `:teleport` 与 `//components/policy` 双方消费,不成环)。

**Files:**
- Modify: `src/common/teleport_deployment_config.h`
- Modify: `src/common/teleport_deployment_config.cc`
- Modify: `src/common/teleport_deployment_config_unittest.cc`

**Interfaces:**
- Consumes: `DeploymentDomain()`（Task 1)、`NormalizeDeploymentDomain`。
- Produces（全部基于 `DeploymentDomain()`):
  - `std::string teleport::DeploymentDeviceManagementServerUrl();` → `https://teleport.<D>/dm/devicemanagement/data/api`
  - `std::string teleport::DeploymentEncryptedReportingUrl();` → `https://teleport.<D>/dm/v1/record`
  - `std::string teleport::DeploymentRealtimeReportingUrl();` → `https://teleport.<D>/dm/v1/events`
  - `std::string teleport::DeploymentEnrollUrl();` → `https://teleport.<D>/enroll/start`
  - `std::string teleport::DeploymentRegisterHandlerUrl();` → `https://teleport.<D>/enroll/profile-enrollment/register-handler`
  - `std::string teleport::DeploymentTrustedRedirectHost();` → `https://teleport.<D>`
  - `std::string teleport::DeploymentEnrollmentDomainSuffix();` → `.<host-of-D>`（**不含端口**)

- [ ] **Step 1: Write the failing tests**

追加(顶部若无 `#include "teleport/teleport_policy_buildflags.h"` 已在):

```cpp
TEST(TeleportDeploymentDeriveTest, DerivesTeleportHostUrls) {
  // Uses the baked default (no source override in this test process).
  const std::string d = DeploymentDomain();
  EXPECT_EQ(DeploymentDeviceManagementServerUrl(),
            "https://teleport." + d + "/dm/devicemanagement/data/api");
  EXPECT_EQ(DeploymentEncryptedReportingUrl(),
            "https://teleport." + d + "/dm/v1/record");
  EXPECT_EQ(DeploymentRealtimeReportingUrl(),
            "https://teleport." + d + "/dm/v1/events");
  EXPECT_EQ(DeploymentEnrollUrl(), "https://teleport." + d + "/enroll/start");
  EXPECT_EQ(DeploymentRegisterHandlerUrl(),
            "https://teleport." + d + "/enroll/profile-enrollment/register-handler");
  EXPECT_EQ(DeploymentTrustedRedirectHost(), "https://teleport." + d);
}

TEST(TeleportDeploymentDeriveTest, SuffixIsHostOnlyWithLeadingDot) {
  // Suffix must start with a dot and never carry a port.
  const std::string suffix = DeploymentEnrollmentDomainSuffix();
  ASSERT_FALSE(suffix.empty());
  EXPECT_EQ('.', suffix.front());
  EXPECT_EQ(suffix.find(':'), std::string::npos);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译失败(推导函数未声明)。

- [ ] **Step 3: Add declarations**

header 追加(带简要注释,略):

```cpp
// Endpoint derivation from DeploymentDomain(). All live in this minimal target so
// //components/policy (browser_policy_connector) can consume them without a
// dependency cycle on :teleport.
std::string DeploymentDeviceManagementServerUrl();
std::string DeploymentEncryptedReportingUrl();
std::string DeploymentRealtimeReportingUrl();
std::string DeploymentEnrollUrl();
std::string DeploymentRegisterHandlerUrl();
std::string DeploymentTrustedRedirectHost();
std::string DeploymentEnrollmentDomainSuffix();
```

- [ ] **Step 4: Implement**

`.cc` 加(匿名 namespace 内一个 host helper + 匿名外的公开函数):

```cpp
namespace {
// "teleport." + D (D may include ":port"; the port stays at the tail, which is
// correct for host:port). Reconstructed from the normalized D.
std::string TeleportHost() {
  return "teleport." + DeploymentDomain();
}
// Host portion of D without any port, for the gate suffix.
std::string DomainHostOnly() {
  const std::string& d = DeploymentDomain();
  size_t colon = d.rfind(':');
  return colon == std::string::npos ? d : d.substr(0, colon);
}
}  // namespace

std::string DeploymentDeviceManagementServerUrl() {
  return "https://" + TeleportHost() + "/dm/devicemanagement/data/api";
}
std::string DeploymentEncryptedReportingUrl() {
  return "https://" + TeleportHost() + "/dm/v1/record";
}
std::string DeploymentRealtimeReportingUrl() {
  return "https://" + TeleportHost() + "/dm/v1/events";
}
std::string DeploymentEnrollUrl() {
  return "https://" + TeleportHost() + "/enroll/start";
}
std::string DeploymentRegisterHandlerUrl() {
  return "https://" + TeleportHost() +
         "/enroll/profile-enrollment/register-handler";
}
std::string DeploymentTrustedRedirectHost() {
  return "https://" + TeleportHost();
}
std::string DeploymentEnrollmentDomainSuffix() {
  return "." + DomainHostOnly();
}
```

> 注:`DomainHostOnly` 用 `rfind(':')` 安全,因为 canonical D 的 host 已是 punycode ASCII、不含冒号,唯一可能的冒号是端口分隔符。

- [ ] **Step 5: Run to verify pass**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/teleport_unittests" \
  --gtest_filter='TeleportDeploymentDeriveTest.*'
```
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc \
        src/common/teleport_deployment_config_unittest.cc
git commit -m "feat(deployment-config): derive all endpoints/suffix from base domain D"
```

---

### Task 7: 重构 `teleport_enterprise_urls.cc` 委托推导 + 重写其单测

把现有硬编码常量替换为委托到 Task 6 的推导函数;单测从「断言 buildflag 常量」重写为「断言从 D 推导」。

**Files:**
- Modify: `src/common/teleport_enterprise_urls.cc`
- Modify: `src/common/teleport_enterprise_urls.h`（更新注释,API 不变)
- Modify: `src/common/teleport_enterprise_urls_unittest.cc`（重写)

**Interfaces:**
- Consumes: Task 6 的 `Deployment*Url` / `DeploymentTrustedRedirectHost` / `DeploymentEnrollmentDomainSuffix`。
- Produces:(API 不变,现有 throttle patch 消费者无需改)
  - `EnterpriseEnrollUrl()`、`EnterpriseRegisterHandlerUrl()`、`EnterpriseTrustedRedirectHosts()`、`EnterpriseEnrollmentDomainSuffixes()`。

- [ ] **Step 1: Rewrite the unittest (failing against old impl)**

将 `teleport_enterprise_urls_unittest.cc` 整体替换为(去掉 buildflag 常量断言,改断言推导一致性):

```cpp
#include "teleport/common/teleport_enterprise_urls.h"

#include "teleport/common/teleport_deployment_config.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportEnterpriseUrlsTest, EnrollUrlsAreHttpsAndNonEmpty) {
  EXPECT_EQ(EnterpriseEnrollUrl().rfind("https://", 0), 0u);
  EXPECT_EQ(EnterpriseRegisterHandlerUrl().rfind("https://", 0), 0u);
}

// The enroll / register-handler / trusted-host URLs must be exactly the values
// derived from the resolved deployment domain D — no hardcoded per-build
// constant remains.
TEST(TeleportEnterpriseUrlsTest, DelegatesToDeploymentDerivation) {
  EXPECT_EQ(EnterpriseEnrollUrl(), DeploymentEnrollUrl());
  EXPECT_EQ(EnterpriseRegisterHandlerUrl(), DeploymentRegisterHandlerUrl());
  const auto hosts = EnterpriseTrustedRedirectHosts();
  ASSERT_EQ(hosts.size(), 1u);
  EXPECT_EQ(hosts[0], DeploymentTrustedRedirectHost());
}

TEST(TeleportEnterpriseUrlsTest, RegisterHandlerCarriesDispatchPath) {
  EXPECT_NE(EnterpriseRegisterHandlerUrl().find(
                "/profile-enrollment/register-handler"),
            std::string::npos);
}

TEST(TeleportEnterpriseUrlsTest, SuffixIsDerivedHostWithLeadingDot) {
  const auto suffixes = EnterpriseEnrollmentDomainSuffixes();
  ASSERT_EQ(suffixes.size(), 1u);
  EXPECT_EQ(suffixes[0], DeploymentEnrollmentDomainSuffix());
  EXPECT_EQ('.', suffixes[0].front());
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: Run to verify it fails**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译或链接失败(unittest 现 include `teleport_deployment_config.h`,但旧 `.cc` 仍返回硬编码;`DelegatesToDeploymentDerivation` 断言相等,旧实现下 `EnterpriseEnrollUrl()` 硬编码值与 `DeploymentEnrollUrl()` 推导值一致时**可能意外通过**——因此本步真正的失败点是 `teleport_enterprise_urls_unittest` 的 deps 尚未含 `teleport_deployment_config`。先确保 `src/BUILD.gn` 的 `test("teleport_unittests")` deps 已含 `":teleport_deployment_config"`(Task 1 已加),则编译通过、但为强制 TDD,先跳到 Step 3 改实现)。

> 若旧硬编码与推导恰好等值使测试假绿,以 Step 3 的实现替换为「唯一事实源」即完成红→绿的语义收敛;关键验收是 Step 5 全绿且无残留硬编码常量。

- [ ] **Step 3: Rewrite `teleport_enterprise_urls.cc` to delegate**

整体替换 `src/common/teleport_enterprise_urls.cc` 为:

```cpp
#include "teleport/common/teleport_enterprise_urls.h"

#include "teleport/common/teleport_deployment_config.h"

namespace teleport {

std::string EnterpriseEnrollUrl() {
  return DeploymentEnrollUrl();
}

std::string EnterpriseRegisterHandlerUrl() {
  return DeploymentRegisterHandlerUrl();
}

std::vector<std::string> EnterpriseTrustedRedirectHosts() {
  return {DeploymentTrustedRedirectHost()};
}

std::vector<std::string> EnterpriseEnrollmentDomainSuffixes() {
  return {DeploymentEnrollmentDomainSuffix()};
}

}  // namespace teleport
```

更新 `teleport_enterprise_urls.h` 顶部注释:把「baked per build via teleport_use_release_endpoints」改为「derived from the resolved deployment domain D (teleport_deployment_config.h)」;`EnterpriseEnrollmentDomainSuffixes` 注释的「dev=.fairyland.io, release=.douan.cn」改为「= .<host-of-D>」。移除对 `teleport_policy_buildflags.h` 的 include(不再需要)。

- [ ] **Step 4: Ensure BUILD.gn deps**

`src/BUILD.gn` 的 `source_set("teleport")` 的 `deps` 已在 Task 1 加 `":teleport_deployment_config"`。确认 `teleport_enterprise_urls.cc` 不再 include buildflag header 后,`:teleport` 仍保留 `":teleport_policy_buildflags"`(其它文件仍用)。

- [ ] **Step 5: Run to verify pass**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/teleport_unittests" \
  --gtest_filter='TeleportEnterpriseUrlsTest.*'
```
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add src/common/teleport_enterprise_urls.cc src/common/teleport_enterprise_urls.h \
        src/common/teleport_enterprise_urls_unittest.cc
git commit -m "refactor(enterprise-urls): delegate to deployment-domain derivation (single source of truth)"
```

---

### Task 8: 校验 gate 后缀现从 D 推导 + 加固 gate 单测

gate 经 `EnterpriseEnrollmentDomainSuffixes()` 取后缀,Task 7 后已从 D 推导。本 Task 加一条断言「gate 放行 `teleport.<D>` 与派生子域、拒绝无关域」以钉住后缀语义,防回归。

**Files:**
- Modify: `src/common/teleport_enrollment_gate_logic_unittest.cc`

**Interfaces:**
- Consumes: `IsEnrollmentFlowUrl`（现有)、`DeploymentDomain()`（Task 1)、`DeploymentEnrollmentDomainSuffix()`（Task 6)。

- [ ] **Step 1: Write the failing test**

在 `teleport_enrollment_gate_logic_unittest.cc` 追加(顶部补 `#include "teleport/common/teleport_deployment_config.h"`):

```cpp
// The gate suffix must now be derived from the resolved deployment domain D:
// teleport.<D> and any subdomain of <host-of-D> are enrollment-flow hosts;
// unrelated hosts are not. (Phase 1 keeps suffix semantics; exact-host
// whitelist is Phase 2.)
TEST(TeleportEnrollmentGateLogicTest, EnrollmentFlowUsesDerivedSuffix) {
  const std::string host_only = DeploymentEnrollmentDomainSuffix().substr(1);
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://teleport." + host_only + "/enroll/start")));
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://accounts." + host_only + "/login")));
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://" + host_only + "/")));  // apex
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://example.com/")));
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("http://teleport." + host_only + "/")));  // not https
}
```

- [ ] **Step 2: Run to verify it fails or passes**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
"$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev/teleport_unittests" \
  --gtest_filter='TeleportEnrollmentGateLogicTest.EnrollmentFlowUsesDerivedSuffix'
```
Expected: PASS(逻辑未变,后缀来源已切换)。若 FAIL,检查 gate 是否仍引用旧硬编码后缀。

- [ ] **Step 3: Confirm gate deps**

确认 `src/BUILD.gn` 的 `test("teleport_unittests")` deps 含 `":teleport_deployment_config"`(Task 1 已加)。gate_logic.cc 本身无需改(它调用 `EnterpriseEnrollmentDomainSuffixes()`,已委托推导)。

- [ ] **Step 4: Commit**

```bash
git add src/common/teleport_enrollment_gate_logic_unittest.cc
git commit -m "test(gate): pin enrollment-flow suffix to derived deployment domain"
```

---

### Task 9: 重构 `browser_policy_connector.cc.patch` 让 DM/上报 URL 从 D 推导

上游 `browser_policy_connector.cc` 现经 buildflag 烘焙三个 DM/上报 URL 常量;改为调用 Task 6 的推导函数。需让 `//components/policy/core/browser` 依赖 `//teleport:teleport_deployment_config`(不成环)。

**Files:**
- Modify: `patches/components/policy/core/browser/browser_policy_connector.cc.patch`（走 patch 工作流,不手改 hunk)
- Modify: `patches/components/policy/core/browser/BUILD.gn.patch`（新建或修改:给 `browser` target 加 `//teleport:teleport_deployment_config` dep)

**Interfaces:**
- Consumes: `teleport::DeploymentDeviceManagementServerUrl()`、`DeploymentEncryptedReportingUrl()`、`DeploymentRealtimeReportingUrl()`。

- [ ] **Step 1: Ensure current patches applied**

```bash
cd /Users/liulichao/workspace/teleport   # 或 worktree 根
python scripts/apply_patches.py
```
Expected: 全部已应用、幂等。

- [ ] **Step 2: Edit the checkout file directly (connector)**

编辑 `"$TELEPORT_CHROMIUM_DIR"/src/components/policy/core/browser/browser_policy_connector.cc`:

把当前(patch 后)的三段 `#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS) ... #else ... #endif` 常量定义,替换为**函数式取值**。具体做法:删除 `kDefaultDeviceManagementServerUrl`/`kDefaultEncryptedReportingServerUrl`/`kDefaultRealtimeReportingServerUrl` 三个 buildflag 分支常量,并把它们的**使用点**改为调用推导函数。

先在 include 区(已在的 `#include "teleport/teleport_policy_buildflags.h"` 处)追加:
```cpp
#include "teleport/common/teleport_deployment_config.h"
```
（若 `teleport_policy_buildflags.h` 不再被本文件其它处使用,可一并移除该 include。)

将三个常量定义整体替换为取值函数(放在原常量所在的匿名 namespace):
```cpp
// Teleport derives the device-management + reporting endpoints from the resolved
// deployment domain D (teleport_deployment_config.h) at call time, replacing the
// former buildflag-baked constants so private/air-gapped deployments can point at
// a customer domain without a rebuild.
std::string DefaultDeviceManagementServerUrl() {
  return teleport::DeploymentDeviceManagementServerUrl();
}
std::string DefaultEncryptedReportingServerUrl() {
  return teleport::DeploymentEncryptedReportingUrl();
}
std::string DefaultRealtimeReportingServerUrl() {
  return teleport::DeploymentRealtimeReportingUrl();
}
```

然后把原先引用 `kDefaultDeviceManagementServerUrl` / `kDefaultEncryptedReportingServerUrl` / `kDefaultRealtimeReportingServerUrl` 的**每一处**改为调用对应的 `Default*ServerUrl()` 函数。（用 `grep -n kDefault.*ServerUrl components/policy/core/browser/browser_policy_connector.cc` 定位全部使用点。)

- [ ] **Step 3: Regenerate the patch**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- components/policy/core/browser/browser_policy_connector.cc \
  > /Users/liulichao/workspace/teleport/patches/components/policy/core/browser/browser_policy_connector.cc.patch
```

- [ ] **Step 4: Add the GN dep (edit checkout BUILD.gn, regenerate patch)**

编辑 `"$TELEPORT_CHROMIUM_DIR"/src/components/policy/core/browser/BUILD.gn`,给编译 `browser_policy_connector.cc` 的 target(通常是 `source_set("browser")` 或 `component("browser")`)的 `deps` 加:
```gn
    "//teleport:teleport_deployment_config",
```
然后:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- components/policy/core/browser/BUILD.gn \
  > /Users/liulichao/workspace/teleport/patches/components/policy/core/browser/BUILD.gn.patch
```

- [ ] **Step 5: Verify idempotent apply + build chrome**

```bash
cd /Users/liulichao/workspace/teleport
python scripts/apply_patches.py    # 幂等、fail-fast
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev chrome
```
Expected:`apply_patches.py` 全绿;chrome 链接通过(证明无 //teleport ↔ //components/policy 依赖环)。若报环:确认 `teleport_deployment_config` target 的 deps 只有 `//base`/`//url`/`:teleport_policy_buildflags`,无 `//content`。

- [ ] **Step 6: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add patches/components/policy/core/browser/browser_policy_connector.cc.patch \
        patches/components/policy/core/browser/BUILD.gn.patch
git commit -m "refactor(policy-connector): derive DM + reporting URLs from deployment domain D"
```

---

### Task 10: `chrome://version` 诊断行(生效域名 + 来源)

在 `chrome://version` 增加一行 `Deployment domain: <D> (source: <label>)`,让支持工单第一问有标准答案。

**Files:**
- Modify: `patches/chrome/browser/ui/webui/version/version_ui.cc.patch`（走 patch 工作流)
- （复用 Task 1 的 `DeploymentDomain()` / `DeploymentDomainSourceLabel()`,无需新客户端 helper)

**Interfaces:**
- Consumes: `teleport::DeploymentDomain()`、`teleport::DeploymentDomainSourceLabel()`。

- [ ] **Step 1: Ensure patches applied**

```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py
```

- [ ] **Step 2: Edit checkout version_ui.cc**

编辑 `"$TELEPORT_CHROMIUM_DIR"/src/chrome/browser/ui/webui/version/version_ui.cc`:
include 区(已有 `#include "teleport/common/teleport_version.h"`)后追加:
```cpp
#include "teleport/common/teleport_deployment_config.h"
```
在 `VersionUI::AddVersionDetailStrings` 内、`html_source->AddString(version_ui::kVersion, teleport::GetDisplayVersion());` 之后追加一行,把生效域名+来源塞进一个可在 about://version 模板展示的字符串键。最小侵入做法:复用已有 `version_ui::kCommandLine` 之类的显示位不合适,故新增一个 teleport 专用字符串键并让模板渲染。**本期采用 append 到 informational suffix 之外的独立字段**——在 `AddString` 序列追加:
```cpp
  html_source->AddString(
      "teleportDeploymentDomain",
      teleport::DeploymentDomain() + " (source: " +
          teleport::DeploymentDomainSourceLabel() + ")");
```
并在 `patches/chrome/browser/resources/settings/...` 或 version WebUI 的 html/js 模板增加对应展示节点。

> 说明:`version_ui.cc` 只提供数据键;实际渲染需在 version WebUI 的前端模板(`chrome/browser/resources/version/` 下的 `about_version.html`/`.ts`)加一行 `<span>$i18n{teleportDeploymentDomain}</span>`。这是**另一个上游文件**,按一文件一 patch 新建 `patches/chrome/browser/resources/version/about_version.html.patch`(路径以检出实际为准,用 `ls "$TELEPORT_CHROMIUM_DIR"/src/chrome/browser/resources/version/` 确认文件名)。

- [ ] **Step 3: Edit the front-end template (checkout)**

`ls "$TELEPORT_CHROMIUM_DIR"/src/chrome/browser/resources/version/` 确认模板文件名,在版本信息表格区追加一行展示 `teleportDeploymentDomain`。参照该目录既有条目的 markup 风格插入(HTML `<tr>/<td>` 或 web component,视文件结构而定)。

- [ ] **Step 4: Regenerate both patches**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git diff -- chrome/browser/ui/webui/version/version_ui.cc \
  > /Users/liulichao/workspace/teleport/patches/chrome/browser/ui/webui/version/version_ui.cc.patch
# 前端模板(文件名以实际为准):
git diff -- chrome/browser/resources/version/about_version.html \
  > /Users/liulichao/workspace/teleport/patches/chrome/browser/resources/version/about_version.html.patch
```

- [ ] **Step 5: Apply + build + smoke**

```bash
cd /Users/liulichao/workspace/teleport && python scripts/apply_patches.py
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev chrome
```
冒烟(记入 `scripts/smoke_check.md`):启动后打开 `chrome://version`,应见 `Deployment domain: fairyland.io (source: built-in default)`;加 `--teleport-deployment-domain=fairyland.test` 重启应见 `fairyland.test (source: command-line switch)`。

- [ ] **Step 6: Commit**

```bash
cd /Users/liulichao/workspace/teleport
git add patches/chrome/browser/ui/webui/version/version_ui.cc.patch \
        patches/chrome/browser/resources/version/about_version.html.patch
git commit -m "feat(version-ui): show effective deployment domain + source on chrome://version"
```

---

### Task 11: §4.5 已 enroll + 换域检测(持久化 + 纯判定 + 重锁 gate + 诊断)

持久化 enroll 时的域名;启动时若 `resolved_D ≠ enrolled_domain` 则重锁 gate + 记 ERROR + chrome://version 标注。**破坏性重纳管动作(清 DM token 等)不在 Phase 1**(见计划开头的排序说明);Phase 1 只做「检测 + 重锁 + 告警」,重锁经既有 gate 通道(令该 profile 视为未 enroll)实现。

**Files:**
- Modify: `src/common/teleport_pref_names.h`（加 `kEnrolledDeploymentDomain`）
- Modify: `src/common/teleport_pref_names.cc`（无实体,header-only,保持)
- Create: `src/common/teleport_domain_migration.h` / `.cc` / `_unittest.cc`（纯判定 + 注册 pref）
- Modify: `src/BUILD.gn`（加新文件到 `:teleport` 与 `teleport_unittests`）

**Interfaces:**
- Consumes: `DeploymentDomain()`、`DeploymentDomainSource`。
- Produces:
  - `inline constexpr char teleport::prefs::kEnrolledDeploymentDomain[] = "teleport.enrollment.enrolled_domain";`（local_state string)
  - `bool teleport::ShouldRequireReenrollment(const std::string& enrolled_domain, const std::string& resolved_domain);`（纯:两者均非空且不等 → true)

- [ ] **Step 1: Write the failing test**

创建 `src/common/teleport_domain_migration_unittest.cc`:

```cpp
#include "teleport/common/teleport_domain_migration.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportDomainMigrationTest, NoReenrollWhenNeverEnrolled) {
  // Empty enrolled_domain = not yet enrolled; never trigger re-enrollment.
  EXPECT_FALSE(ShouldRequireReenrollment("", "acme.internal"));
}

TEST(TeleportDomainMigrationTest, NoReenrollWhenDomainUnchanged) {
  EXPECT_FALSE(ShouldRequireReenrollment("acme.internal", "acme.internal"));
}

TEST(TeleportDomainMigrationTest, ReenrollWhenDomainChanged) {
  EXPECT_TRUE(ShouldRequireReenrollment("acme.internal", "beta.internal"));
}

TEST(TeleportDomainMigrationTest, NoReenrollWhenResolvedEmpty) {
  // Defensive: an empty resolved domain (should never happen) must not trigger a
  // destructive re-enroll.
  EXPECT_FALSE(ShouldRequireReenrollment("acme.internal", ""));
}

}  // namespace
}  // namespace teleport
```

- [ ] **Step 2: Run to verify it fails**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译失败(未声明)。

- [ ] **Step 3: Add pref name + pure function**

`src/common/teleport_pref_names.h` 在 `kRequireEnrollmentToBrowse` 后加:

```cpp
// local_state string. The base deployment domain D that was in effect when this
// device/profile last completed managed enrollment. Compared at startup against
// the freshly resolved D; a mismatch means an admin channel re-pointed the
// deployment (management-domain migration) — see teleport_domain_migration.h.
inline constexpr char kEnrolledDeploymentDomain[] =
    "teleport.enrollment.enrolled_domain";
```

创建 `src/common/teleport_domain_migration.h`:

```cpp
#ifndef TELEPORT_COMMON_TELEPORT_DOMAIN_MIGRATION_H_
#define TELEPORT_COMMON_TELEPORT_DOMAIN_MIGRATION_H_

#include <string>

namespace teleport {

// Pure decision: true iff the device was previously enrolled against a domain
// (enrolled_domain non-empty) and the freshly resolved domain differs from it
// (resolved_domain non-empty and != enrolled_domain). An empty resolved_domain
// is treated defensively as "no change" so a resolution glitch never triggers a
// destructive re-enrollment.
bool ShouldRequireReenrollment(const std::string& enrolled_domain,
                               const std::string& resolved_domain);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_DOMAIN_MIGRATION_H_
```

创建 `src/common/teleport_domain_migration.cc`:

```cpp
#include "teleport/common/teleport_domain_migration.h"

namespace teleport {

bool ShouldRequireReenrollment(const std::string& enrolled_domain,
                               const std::string& resolved_domain) {
  if (enrolled_domain.empty() || resolved_domain.empty()) {
    return false;
  }
  return enrolled_domain != resolved_domain;
}

}  // namespace teleport
```

- [ ] **Step 4: Wire into BUILD.gn**

`src/BUILD.gn` 的 `source_set("teleport")` sources 加(按字母序):
```gn
    "common/teleport_domain_migration.cc",
    "common/teleport_domain_migration.h",
```
`test("teleport_unittests")` sources 加:
```gn
    "common/teleport_domain_migration_unittest.cc",
```

- [ ] **Step 5: Run to verify pass**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportDomainMigrationTest.*'
```
Expected: 全部 PASS。

- [ ] **Step 6: Commit (pure logic)**

```bash
git add src/common/teleport_pref_names.h src/common/teleport_domain_migration.h \
        src/common/teleport_domain_migration.cc \
        src/common/teleport_domain_migration_unittest.cc src/BUILD.gn
git commit -m "feat(domain-migration): pure re-enrollment decision + enrolled-domain pref"
```

- [ ] **Step 7: Wire persistence + startup check (patches)**

这一步把纯逻辑接到启动路径与 enroll 成功点(经 patch,一文件一 patch):
1. **注册 pref**:在注册 `kRequireEnrollmentToBrowse` 的同一 local_state 注册点(`RegisterEnrollmentGateLocalStatePrefs`,`src/browser/enterprise/teleport_enrollment_gate.cc`)追加 `registry->RegisterStringPref(prefs::kEnrolledDeploymentDomain, std::string());`。
2. **写入 enrolled_domain**:在机器 enroll 成功与 profile enroll 成功的落点(`teleport_oidc_inplace_registrar.cc` 的 `EnrollmentResult::kSuccess` 分支、及机器 CBCM enroll 成功处),`g_browser_process->local_state()->SetString(prefs::kEnrolledDeploymentDomain, teleport::DeploymentDomain());`。
3. **启动检测**:在启动早期(gate 初始化处,`teleport_startup.cc` 或 gate 的 local_state 就绪后)读 `kEnrolledDeploymentDomain`,若 `ShouldRequireReenrollment(enrolled, DeploymentDomain())`:`LOG(ERROR)` 记录迁移;把 chrome://version 的诊断字符串(Task 10)追加 `; domain changed from <old> (re-enrollment required)`;并令 gate 重锁——最小实现:清除该 profile 的 `ProfileManagementId`(使 `IsEnrolled` 返回 false),使 gate 按未 enroll 拦截。

> 破坏性动作边界:Phase 1 只清 profile 管理标记以重锁 gate(可逆、纯本地),**不清机器 DM token、不主动触发向新域的重注册流程**——后者需对新域 enroll 端到端可测,属 Phase 2(见计划开头排序说明与 spec §4.5)。

每处改动按一文件一 patch 生成/更新对应 `.patch`,`apply_patches.py` 验证幂等,`autoninja ... chrome` 通过。

- [ ] **Step 8: Commit (wiring)**

```bash
cd /Users/liulichao/workspace/teleport
git add patches/  # 仅本 Task 触及的 patch 文件
git commit -m "feat(domain-migration): persist enrolled domain + re-lock gate on admin-channel domain change"
```

---

## Self-Review(计划对照 spec)

**Spec 覆盖(Phase 1 范围)**:
- §3.1 resolver 子系统 → Task 1;§3.2 优先级(1/2/3/5 级)→ Task 3/5;D13 来源校验(IsForced / 文件属主权限)→ Task 5;§3.3 文件 schema → Task 4;§3.4 端点推导 → Task 6/7;§3.4 端口语义 → Task 2/6;§3.5 兜底列表推导 → Task 6/7(`DeploymentTrustedRedirectHost`);§3.6 时序(早期同步、缓存)→ Task 1/5;gate 后缀从 D 推导(保留后缀语义)→ Task 7/8;§4.2 硬化规范化 → Task 2;§4.5 检测+重锁+诊断 → Task 11;§5.3 chrome://version → Task 10;DM/上报 URL 推导 → Task 9;§6 客户端单测覆盖 → 各 Task 的 TDD。
- **明确不在 Phase 1**(Phase 2):第 4 级 Local State 条目、connect 页、深链接、server-identity 验证库、D16 gate 精确白名单 + 动态注入、§4.5 破坏性重纳管动作(清 DM token/重注册)。计划开头与 Task 8/11 已注明。

**占位符扫描**:无 TBD/TODO;每个 code step 均给出完整代码。唯一「以实际为准」项是 Task 10 的 version WebUI 前端模板文件名(`ls` 确认)——因该前端文件名随上游可能微调,已给出确认命令而非臆断路径。

**类型一致性**:`DeploymentResolution{domain, source}`、`DeploymentDomainSource` 枚举、`DeploymentDomain()`/`DeploymentDomainSourceLevel()`/`DeploymentDomainSourceLabel()`、`NormalizeDeploymentDomain`、`SelectDeploymentDomain`、`ParseDeploymentConfigJson`、`IsMachineConfigFileTrusted`、`Deployment*Url`/`DeploymentTrustedRedirectHost`/`DeploymentEnrollmentDomainSuffix`、`ShouldRequireReenrollment`、`kEnrolledDeploymentDomain` 在定义 Task 与消费 Task 间签名一致。
