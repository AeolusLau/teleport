# Teleport 企业 OIDC 客户端实现 Plan(Chromium overlay)

> **状态**:本计划记录该 feature **客户端已落地实现**(`//teleport` enterprise-urls 组件 + `teleport_use_release_endpoints` buildflag + 6 个上游薄 patch + dev/release GN args)。Task 1–7 标 **【已实现】**;端到端联调 capstone(Task 8)依赖服务端栈,**待执行**;机器/CBCM 纳管的两个 patch 列入末尾 **【未实现 · 后续 phase】**。本计划与代码一一对应,作为已实现客户端的权威文档。

> **给执行体的说明**:必备子技能——用 `superpowers:subagent-driven-development`(推荐)或 `superpowers:executing-plans` 逐任务执行。步骤用 `- [ ]` 复选框跟踪。客户端 C++(`//teleport`)走 TDD(gtest);patch/构建/联调为务实的过程性任务。复现已实现部分时,patch 用「编辑检出文件 + `git diff` 重生成」产出,**不要手抄行号**(下文行号基于 2026-06-04 的 M148 检出,执行时以实际文件为准)。

---

**目标**:让 teleport overlay 复用 M148 内置的 **OIDC 受管 profile enrollment**(generic-OIDC / header 路径),把其端点与策略验签根钥从 Google 的硬编码值**重指向我们 dev/release 的 Fairyland Keystone / device-manager**,实现「客户 IdP 登录 → 受管 profile → 拉 per-tenant 签名策略」的用户级纳管闭环。所有 bake 的 dev/release 端点由**一个 buildflag** 统一切换。

**架构**:沿用 overlay「常量收进 `//teleport` + 上游薄 patch」。

- 新增一个 `//teleport` 常量件 `teleport_enterprise_urls`(h/cc/unittest)作为品牌化企业端点的单一事实来源(enroll URL / register-handler URL / 受信 redirect-source host)。
- 新增**一个统一 buildflag** `teleport_use_release_endpoints`(GN arg → `buildflag_header` 暴露 `TELEPORT_USE_RELEASE_ENDPOINTS`)。一处开关在**编译期**同时选三类 dev/release 端点:① 策略验签根公钥(`cloud_policy_constants.cc`);② 默认 DM server URL(`browser_policy_connector.cc`);③ enroll / register-handler URL(`teleport_enterprise_urls.cc`)。dev/release 是不同二进制,故无运行时 channel 逻辑、无 layering 注入。
- 6 个上游薄 patch:2 个开闭环(OIDC throttle 重指 + generic-OIDC 默认开),4 个接端点/根钥(cloud_policy_constants 双钥 + 其 BUILD.gn dep、browser_policy_connector DM URL + 其 BUILD.gn dep)。

> **设计权威**:`docs/superpowers/specs/2026-06-04-enterprise-oidc-client-design.md`(客户端 spec)。**上游父设计**:`docs/superpowers/specs/2026-06-03-enterprise-account-system-design.md`(总体账号体系)。**依赖服务端计划**:`fairyland` 仓 `docs/superpowers/plans/2026-06-04-enterprise-oidc-server-plan.md`(栈必须先就绪才能跑端到端 capstone)。

**技术栈**:Chromium M148 overlay(C++/Obj-C++、GN、gtest);GN `buildflag_header`;`patches/`(`git apply`,一文件一 patch);`scripts/apply_patches.py`。

---

## 前置说明(务必先读)

- **throttle 契约(M148 已核实)**:`OidcAuthResponseCaptureNavigationThrottle` 走 **header 路径**——浏览器请求 register-handler 页,响应头 `X-Profile-Registration-Payload` 携带 base64url 的 `ProfileRegistrationPayload`(`subject`/`issuer`/`encrypted_user_information` 三者非空即放行;Chrome **永不解密** `encrypted_user_information`,原样塞进发往 DM server 的头)。DM 注册类型 `TYPE_OIDC_REGISTRATION`(`request=register_profile`,`type=USER`、`flavor=FLAVOR_USER_REGISTRATION`)。整条 OIDC 流程**未被 `is_chrome_branded` 门控**;`kEnableGenericOidcAuthProfileManagement` 默认开后,register-handler URL 命中 `teleport::EnterpriseRegisterHandlerUrl()` 即触发,只读头、不验 id_token 签名(验签在 device-manager)。详见 spec §1。
- **patch 目标文件的 BUILD.gn dep**:OIDC throttle / features 由 `chrome/browser/BUILD.gn` 的 `static_library("browser")` 编译,该目标**已 deps `//teleport`**,故可直接 `#include "teleport/common/teleport_enterprise_urls.h"`,无需改其 BUILD.gn。但 `cloud_policy_constants.cc` 与 `browser_policy_connector.cc` 在 `//components/policy` 下、**不依赖 `//teleport`**,需各自 patch 其 BUILD.gn 加 `//teleport:teleport_policy_buildflags` dep(buildflag_header 是叶子目标,无 `//content` 依赖,**不成环**)。
- **渠道陷阱(为何一律改内置常量)**:`--device-management-url`、OIDC 额外 header URL 在 STABLE/BETA 经 `IsCommandLineSwitchSupported()` 被忽略;`--policy-verification-key` 仅 `CHECK_IS_TEST()`。故全部改走 patch 内置常量 + buildflag。
- **构建/符号链接坑**:`chromium/src/teleport` 符号链接默认指向**主工作树**的 `src/`。在本 feature worktree 里新增/改动 `//teleport` 源码后,需把符号链接重指到本 worktree 的 `src/`(见 Task 6),`autoninja` 才看得到。从 worktree 跑脚本必须 `export TELEPORT_CHROMIUM_DIR=...`,否则 `_lib` 默认到 `<worktree>/chromium` 假路径。

---

## 文件结构(改动总览)

```
src/teleport.gni                                          新增 arg: teleport_use_release_endpoints
src/BUILD.gn                                              buildflag_header("teleport_policy_buildflags")
                                                          + enterprise_urls 源码进 source_set / 单测
src/gn/args/dev.mac.gn                                    teleport_use_release_endpoints = false
src/gn/args/release.mac.gn                                teleport_use_release_endpoints = true
src/common/teleport_enterprise_urls.{h,cc,_unittest.cc}   品牌化企业端点单一事实源(dev/release 双值)

patches/chrome/browser/enterprise/profile_management/
  oidc_auth_response_capture_navigation_throttle.cc.patch  重指 enroll/register-handler/受信源 → teleport::
  profile_management_features.cc.patch                     generic-OIDC 默认开
patches/components/policy/core/common/
  cloud/cloud_policy_constants.cc.patch                    验签根公钥 dev/release 双钥(buildflag)
  BUILD.gn.patch                                           common_constants 加 buildflag dep
patches/components/policy/core/browser/
  browser_policy_connector.cc.patch                        默认 DM server URL dev/release 双值(buildflag)
  BUILD.gn.patch                                           internal source_set 加 buildflag dep
```

---

## Task 1:`teleport_enterprise_urls` 常量件(TDD)【已实现】

品牌化企业端点的单一事实源,供 patch 后的 OIDC throttle 消费。dev/release 双值由 `TELEPORT_USE_RELEASE_ENDPOINTS` 编译期二选一。

**Files:**
- Create: `src/common/teleport_enterprise_urls.h`
- Create: `src/common/teleport_enterprise_urls.cc`
- Test: `src/common/teleport_enterprise_urls_unittest.cc`
- Modify: `src/BUILD.gn`(见 Task 2 一并接入)

- [ ] **Step 1:写失败测试** `src/common/teleport_enterprise_urls_unittest.cc`——三条 gtest:
  - `EnrollUrlsAreHttpsAndNonEmpty`:`EnterpriseEnrollUrl()` / `EnterpriseRegisterHandlerUrl()` 均以 `https://` 起头。
  - `TrustedRedirectHostsAreHttpsAndNonEmpty`:`EnterpriseTrustedRedirectHosts()` 非空且每项 `https://` 起头。
  - `EnrollUrlMatchesEndpointBuildflag`:`#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` 断言 host 含 `teleport.beansec.com`;`#else` 断言含 `enroll.teleport.fairyland.io`;register-handler URL 恒含 `/profile-enrollment/register-handler` 路径。测试需 `#include "teleport/teleport_policy_buildflags.h"`。

- [ ] **Step 2:运行确认失败**(在被符号链接看到的 src 上):
  `autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests`
  Expected:编译失败(`teleport_enterprise_urls.h` not found)。

- [ ] **Step 3:写头 `teleport_enterprise_urls.h`**——`namespace teleport` 下三个 getter 声明:
  - `std::string EnterpriseEnrollUrl();` — Keystone OIDC 登录成功后回跳、携带 enrollment payload 的落地 URL(替换上游 `https://chromeenterprise.google/enroll`)。
  - `std::string EnterpriseRegisterHandlerUrl();` — header 拦截的 register-handler URL(替换上游 `…/profile-enrollment/register-handler`)。
  - `std::vector<std::string> EnterpriseTrustedRedirectHosts();` — 受信发起 OIDC enrollment 的 redirect-source host(替换上游硬编码 Entra host)。**注释须写明**:仅当 generic-OIDC 被强制关闭时 throttle 才查该名单;出货配置保持该 feature 开启(throttle 跳过此校验),故此名单是防御性 fallback、**非生产 enrollment 闸门**。

- [ ] **Step 4:写实现 `teleport_enterprise_urls.cc`**——`#include "teleport/teleport_policy_buildflags.h"`;匿名 namespace 内按 buildflag 二选一两套常量:
  ```cpp
  #if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  // Release: production beansec.com endpoints.
  constexpr char kEnrollUrl[] = "https://enroll.teleport.beansec.com/enroll";
  constexpr char kRegisterHandlerUrl[] =
      "https://enroll.teleport.beansec.com/profile-enrollment/register-handler";
  constexpr char kKeystoneOpHost[] = "https://id.beansec.com";
  #else
  // Dev: fairyland.io endpoints. The OP host is a sample value — under
  // generic-OIDC the trusted-redirect-host check is skipped by the throttle, so
  // it only serves as a placeholder.
  constexpr char kEnrollUrl[] = "https://enroll.teleport.fairyland.io/enroll";
  constexpr char kRegisterHandlerUrl[] =
      "https://enroll.teleport.fairyland.io/profile-enrollment/register-handler";
  constexpr char kKeystoneOpHost[] = "https://dadou.fairyland.io";
  #endif  // BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  ```
  三个 getter 直接返回对应常量(`EnterpriseTrustedRedirectHosts` 返回 `{kKeystoneOpHost}`)。
  > 说明:`dadou.fairyland.io` 是 dev 的 per-tenant OP **示例**值;generic-OIDC 开启下 throttle 跳过受信 host 校验,该值仅占位。OP host 不随租户 bake(每租户、运行时由服务端决定)。

- [ ] **Step 5:接入 `src/BUILD.gn`**(与 Task 2 的 buildflag 一并):`source_set("teleport")` 的 `sources` 加 `common/teleport_enterprise_urls.{cc,h}`;`test("teleport_unittests")` 的 `sources` 加 `common/teleport_enterprise_urls_unittest.cc`。

- [ ] **Step 6:运行确认通过**(留到 Task 5 构建后跑,或单独 build `teleport_unittests`):
  `… teleport_unittests --gtest_filter='*EnterpriseUrls*'` → PASS。

---

## Task 2:统一 buildflag `teleport_use_release_endpoints` + `buildflag_header`【已实现】

单一 release 位统管所有 bake 的 dev/release 端点(验签根钥 + DM URL + enroll/register-handler URL)。dev/release 是不同二进制,编译期二选一。

**Files:**
- Modify: `src/teleport.gni`
- Modify: `src/BUILD.gn`
- Modify: `src/gn/args/dev.mac.gn`、`src/gn/args/release.mac.gn`

- [ ] **Step 1:`teleport.gni`**——`declare_args()` 内加 `teleport_use_release_endpoints = false`。注释须写明它**一处统管**三类端点(根公钥 / DM URL / enroll+register-handler URL):false=dev(fairyland.io + `kDevPolicyKey` dev root-signer);true=release(beansec.com + `kReleasePolicyKey` 生产 KMS root,canary/beta/stable 共用一份 release 二进制)。

- [ ] **Step 2:`src/BUILD.gn`**——`import("//build/buildflag_header.gni")`;新增叶子目标
  ```gn
  buildflag_header("teleport_policy_buildflags") {
    header = "teleport_policy_buildflags.h"
    flags = [ "TELEPORT_USE_RELEASE_ENDPOINTS=$teleport_use_release_endpoints" ]
  }
  ```
  注释须写明:**单独成 target(不并入 `:teleport`)**,以便 `//components/policy` 能 dep 它而**不拉入 `//content` 成环**。把 `:teleport_policy_buildflags` 加进 `source_set("teleport")` 的 `deps`(供 `teleport_enterprise_urls.cc` include 该头)与 `test("teleport_unittests")` 的 `deps`(供单测 include)。

- [ ] **Step 3:`dev.mac.gn` / `release.mac.gn`**——分别加 `teleport_use_release_endpoints = false` / `= true`,各带注释说明 bake 的是 fairyland.io+dev 根钥 / beansec.com+KMS 根钥。release 注释须标注 `kReleasePolicyKey` 当前是 **throwaway placeholder**,首次真实 device-manager 部署前替换为生产 KMS 根公钥 DER(私钥绝不入库)。

- [ ] **Step 4:patch 一致性**:buildflag 名牵动两个 policy patch(Task 4/Task 5)——`teleport.gni` / `BUILD.gn` / 两 patch 的 `TELEPORT_USE_RELEASE_ENDPOINTS` 须保持一致。

- [ ] **Step 5:commit** `feat(enterprise): add teleport_enterprise_urls + teleport_use_release_endpoints buildflag`

---

## Task 3:patch OIDC 拦截 throttle 重指 Keystone【已实现】

**Files:**
- Modify(经 patch):`chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc`
- Create: `patches/chrome/browser/enterprise/profile_management/oidc_auth_response_capture_navigation_throttle.cc.patch`

- [ ] **Step 1:确保检出干净并已应用现有 patch**:`python scripts/apply_patches.py`。编辑目标文件:
  - 顶部 include 段加 `#include "teleport/common/teleport_enterprise_urls.h"`。
  - 删除匿名 namespace 里四个硬编码常量(`kEnrollmentFallbackUrl`、`kEntraLoginHost`、`kEntraMcasHost`、`kEnterpriseOidcRegisterUrl`,约 :41-54),换成一段注释说明这些值现由 `//teleport` 提供。
  - `CreateEnrollmentRedirectUrlMatcher()`:`AddAllowFiltersWithLimit(matcher.get(), {teleport::EnterpriseEnrollUrl()})`。
  - `CreateEnrollmentHeaderUrlMatcher()`:`allowed_urls({teleport::EnterpriseRegisterHandlerUrl()})`。
  - `CreateOidcEnrollmentUrlMatcher()`:`allowed_hosts = teleport::EnterpriseTrustedRedirectHosts();`(保留其后 `kOidcEnrollmentAuthSource` feature 追加 host 的逻辑)。

- [ ] **Step 2:生成 patch** —— `git diff <file> > patches/.../oidc_auth_response_capture_navigation_throttle.cc.patch`(目录不存在先 `mkdir -p`)。

- [ ] **Step 3:验证可干净应用** —— `git checkout -- <file>` 后 `git apply --check <patch>` → `OK`。

- [ ] **Step 4:commit** `feat(enterprise): repoint OIDC enrollment throttle at Fairyland Keystone`

---

## Task 4:patch 默认开启 generic-OIDC【已实现】

**Files:**
- Modify(经 patch):`chrome/browser/enterprise/profile_management/profile_management_features.cc`
- Create: `patches/chrome/browser/enterprise/profile_management/profile_management_features.cc.patch`

- [ ] **Step 1:编辑** —— 把 `kEnableGenericOidcAuthProfileManagement` 的默认态由 `FEATURE_DISABLED_BY_DEFAULT` 改为 `FEATURE_ENABLED_BY_DEFAULT`,加注释说明:默认开后官方构建走 generic-OIDC 路径(跳过上游 Entra 受信链校验、读 `state` 参数),无需每次启动加 `--enable-features`。

- [ ] **Step 2:生成 + 验证 patch**(同 Task 3 Step 2/3)。

- [ ] **Step 3:commit** `feat(enterprise): default-enable generic OIDC profile management`

---

## Task 5:patch 策略验签根公钥(dev/release 双钥)【已实现】

只有两把根公钥:`release`(canary/beta/stable 共用)+ `dev`;由同一 buildflag 编译期二选一,无运行时 channel 逻辑。

**Files:**
- Modify(经 patch):`components/policy/core/common/cloud/cloud_policy_constants.cc`
- Modify(经 patch):`components/policy/core/common/BUILD.gn`(`source_set("common_constants")` 加 dep)
- Create: `patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch`
- Create: `patches/components/policy/core/common/BUILD.gn.patch`

- [ ] **Step 1:编辑 `cloud_policy_constants.cc`**
  - 顶部加 `#include "teleport/teleport_policy_buildflags.h"`。
  - 删上游单值 `kPolicyVerificationKey[]`(:159-184)与 `kPolicyVerificationKeyHash`(:186),换成 `#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)` 二选一的 `kReleasePolicyKey[]`/`kDevPolicyKey[]`(各 294 字节 DER SubjectPublicKeyInfo)+ 各自的 `kPolicyVerificationKeyHash`(release `"1:a6d2a37bee6b696c"` / dev `"1:fa0a3bfb6c7a577c"`)。注释须标注:`kReleasePolicyKey` 当前为 **throwaway placeholder**,首次真实部署前替换为生产 KMS 根公钥 DER;两把私钥(KMS 根 / dev root-signer)**绝不入库**。
  - `GetPolicyVerificationKey()` 内同样 `#if BUILDFLAG(...)` 返回对应 key。
  > 两把公钥由服务端 `devmgr-keys`/KMS 导出:release 来自生产 KMS 根钥、dev 来自 dev root-signer 根钥。device-manager 用配套私钥签 `new_public_key_verification_data`,浏览器用 bake 的这把根钥验签策略链。

- [ ] **Step 2:编辑 `components/policy/core/common/BUILD.gn`** —— `source_set("common_constants")` 的 `deps` 加 `"//teleport:teleport_policy_buildflags"`。

- [ ] **Step 3:生成两 patch + 各自 `git apply --check`**(一文件一 patch)。

- [ ] **Step 4:commit** `feat(policy): bake dev/release verification root key via teleport_use_release_endpoints`

---

## Task 6:patch 默认 DM server URL(dev/release 双值)【已实现】

上游默认 DM URL 在 `browser_policy_connector.cc:37` 的 `kDefaultDeviceManagementServerUrl = "https://m.google.com/devicemanagement/data/api"`,经 `GetDeviceManagementUrl()` 读取(`--device-management-url` 仅特定渠道生效,故改默认值最稳)。

**Files:**
- Modify(经 patch):`components/policy/core/browser/browser_policy_connector.cc`
- Modify(经 patch):`components/policy/core/browser/BUILD.gn`(`source_set("internal")` 加 dep)
- Create: `patches/components/policy/core/browser/browser_policy_connector.cc.patch`
- Create: `patches/components/policy/core/browser/BUILD.gn.patch`

- [ ] **Step 1:编辑 `browser_policy_connector.cc`** —— 加 `#include "teleport/teleport_policy_buildflags.h"`;把 `kDefaultDeviceManagementServerUrl` 改为 buildflag 双值:
  ```cpp
  #if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  const char kDefaultDeviceManagementServerUrl[] =
      "https://dm.teleport.beansec.com/devicemanagement/data/api";
  #else
  const char kDefaultDeviceManagementServerUrl[] =
      "https://dm.teleport.fairyland.io/devicemanagement/data/api";
  #endif  // BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  ```
  保留 `GetDeviceManagementUrl()` 的 switch 覆盖路径不动(dev 可用)。

- [ ] **Step 2:编辑 `components/policy/core/browser/BUILD.gn`** —— `source_set("internal")` 的 `deps` 加 `"//teleport:teleport_policy_buildflags"`(buildflag_header 是叶子,不引入 `//content` 环)。

- [ ] **Step 3:生成两 patch + 各自 `git apply --check`**。

- [ ] **Step 4:commit** `feat(policy): bake default device-management URL (dev/release via buildflag)`

---

## Task 7:检出一致化 + 构建 Teleport.app(dev,过程性)【已实现】

把检出符号链接重指到本 worktree 的 `src/`、重应用全部 patch、构建 dev 整包并跑 `//teleport` 单测。检出不在 git 跟踪,**无 commit**;记录到联调笔记。

**Files:** 无(过程性)。

- [ ] **Step 1:设环境** —— `export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`(从 worktree 跑必须设)。

- [ ] **Step 2:符号链接重指本 worktree src**:
  ```bash
  ln -sfn /Users/liulichao/workspace/teleport/.claude/worktrees/enterprise-account/src \
          "$TELEPORT_CHROMIUM_DIR/src/teleport"
  ls -l "$TELEPORT_CHROMIUM_DIR/src/teleport"   # → 指向 worktree src
  ```

- [ ] **Step 3:复位上游被改文件 + 重应用全部 patch**(从本 worktree 跑):
  ```bash
  cd /Users/liulichao/workspace/teleport/.claude/worktrees/enterprise-account
  python scripts/apply_patches.py    # 幂等、fail-fast;应用 patches/ + branding/
  ```

- [ ] **Step 4:核实关键 patch 已落**:
  ```bash
  grep -n 'TELEPORT_USE_RELEASE_ENDPOINTS' "$TELEPORT_CHROMIUM_DIR/src/components/policy/core/common/cloud/cloud_policy_constants.cc"
  grep -n 'dm.teleport.fairyland.io'      "$TELEPORT_CHROMIUM_DIR/src/components/policy/core/browser/browser_policy_connector.cc"
  grep -n 'teleport_policy_buildflags'    "$TELEPORT_CHROMIUM_DIR/src/components/policy/core/common/BUILD.gn" "$TELEPORT_CHROMIUM_DIR/src/components/policy/core/browser/BUILD.gn"
  ```

- [ ] **Step 5:gn gen + 单测 + 构建**:
  ```bash
  cd "$TELEPORT_CHROMIUM_DIR/src"
  gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
  autoninja -C out/mac/arm64/dev teleport_unittests && \
    out/mac/arm64/dev/teleport_unittests --gtest_filter='*EnterpriseUrls*'   # PASS
  autoninja -C out/mac/arm64/dev chrome                                      # 产物 Teleport.app(~119M)
  ```
  产物在 `<repo>/build/mac/arm64/dev/Teleport.app`。记录构建结果到联调笔记。

---

## Task 8:端到端 OIDC 登录联调验收(capstone,过程性)【待执行 · 依赖服务端栈】

**前置**:fairyland 服务端计划已完成、栈起来(Caddy + accounts + per-tenant OP `dadou.fairyland.io` + enroll-landing + device-manager + seed 完成:租户 slug=`dadou`、teleport-enroll client、HPKE 公私钥分发、**全局手机号**测试用户 + 密码),`/etc/hosts` 各主机名已加。**GUI 登录(输手机号/密码、确认受管 profile)由人工完成。**

**Files:** 无(过程性);可把结果记入联调笔记或 `scripts/smoke_check.md` 企业账号小节。

- [ ] **Step 1:启栈 + 冒烟**(在 fairyland worktree):
  ```bash
  docker.lima compose -f docker-compose.control-plane.yml up -d
  curl -sf https://dadou.fairyland.io/.well-known/openid-configuration | jq .issuer
  curl -sf https://enroll.teleport.fairyland.io/healthz
  curl -sf https://dm.teleport.fairyland.io/healthz
  ```

- [ ] **Step 2:启动 Teleport.app(dev),以 slug 进 enroll-landing**(dev 构建已 `disable_fieldtrial_testing_config=true`,无需运行期再加 flag):
  ```bash
  "<repo>/build/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport" \
    --user-data-dir=/tmp/teleport-e2e \
    "https://enroll.teleport.fairyland.io/start?tenant=dadou"
  ```

- [ ] **Step 3:走 slug 解析 + 真登录** —— enroll-landing 经 `?tenant=dadou`(**slug**,非邮箱)解析租户 → 跳 per-tenant OP `dadou.fairyland.io/authorize` → OP 委派到 accounts 集中认证中心 **手机号登录**(输手机号 + 密码)→ 回 OP 出 code → enroll-landing `/callback` 换 id_token → HPKE 封装 → 302 到 `/profile-enrollment/register-handler`(带 `X-Profile-Registration-Payload` 头)。

- [ ] **Step 4:观察纳管 + 注册** —— throttle 截头 → 受管 profile 创建确认 → device-manager `register_profile` 200(DASHERLESS)。验证:device-manager 日志显示 header 路径命中 + HPKE 解封成功 + 按 `iss=dadou.fairyland.io` 取 per-tenant JWKS 验签成功 + `tenant_id=dadou`;浏览器出现受管 profile 窗口。

- [ ] **Step 5:验证策略下发** —— 用户策略 fetch 200,签名经 Chrome 验签链(`policy_data_signature` 验于 `new_public_key`、`new_public_key_verification_data_signature` 验于 bake 的 **dev 根钥**);策略可见(如 `HomepageLocation` 生效)。

- [ ] **Step 6:记录联调结果**(成功/失败 + 关键日志);失败则回到对应 Task 修复。

---

# 【未实现 · 机器/CBCM 纳管后续 phase】

> 以下两处 patch 属**设备级 CBCM(Chrome Browser Cloud Management)机器纳管**,与本轮已落地的**用户级 OIDC 受管 profile** 纳管正交。**本分支未实现**,列此以记录完整设计意图(见 system spec §13)。实现前需 fairyland device-manager 支持 `TYPE_BROWSER` 机器注册 + per-tenant `AuthServerAllowlist` 等浏览器级策略。

## 后续 Task A:patch CBCM `IsEnabled`(未实现)

**Files(预期):** `patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch`

- 目标:`ChromeBrowserCloudManagementController::IsEnabled()`(:98-106)非品牌分支由「需 `--enable-chrome-browser-cloud-management` switch」改为直接 `return true;`(我们的产品恒开机器纳管)。
- 验证:经 MDM 或本地 `defaults write <bundle-id> CloudManagementEnrollmentToken -string <tok>` 注入 per-tenant token;启动浏览器,确认在任何用户登录前向 device-manager `register`(`TYPE_BROWSER`)、拿机器 DMToken、拉浏览器级策略(`chrome://policy` 可见 `AuthServerAllowlist`)。

## 后续 Task B:patch macOS dm_token 存储(bundle id + 路径)(未实现)

**Files(预期):** `patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch`

- 目标:
  - `kBundleId`(:62,硬编码 `com.google.Chrome`)改为读运行时主 bundle id(`base::apple::MainBundle()` 的 `CFBundleIdentifier`),以适配 per-channel `com.beansec.Teleport*`。
  - 三处硬编码路径(`kDmTokenBaseDir` :45-46、`kEnrollmentTokenFilePath` :49-50、options 文件 :55-56)从 `Google/Chrome*` / `/Library/Google/Chrome/*` 改成我们的(`Teleport/…`、`/Library/Teleport/…`)。
- 验证:并入 Task A 的机器纳管端到端冒烟。

> 另:Apple Extensible SSO「搭车」对名单内客户 Web 应用透明 SSO（`AuthServerAllowlist` 名单 + Kerberos/联邦应用免二次登录）无品牌门控、**零 patch**,只需机器级策略下发后验证,亦归此后续 phase。

---

## 验收(本计划判据)

- **已实现部分**:`teleport_unittests` 全过(含 enterprise-urls dev/release 三测);`ls patches/` 下企业相关 6 个 patch(2 throttle/features + 2 cloud_policy_constants/其 BUILD.gn + 2 browser_policy_connector/其 BUILD.gn)`git apply --check` 干净;检出一致化后 dev 整包构建成功。
- **待执行**:端到端(Task 8)真浏览器 slug 解析(`/start?tenant=dadou`)→ per-tenant OP 手机号登录 → 受管 profile → device-manager header 路径注册 200 → 用户策略 200 且签名验签通过 → 策略生效。
- **后续 phase**:CBCM 机器纳管两 patch（Task A/B)+ SSO 搭车验证。

## 注意

- buildflag 名牵动两个 policy patch(`cloud_policy_constants.cc` + `browser_policy_connector.cc`)及其各自 BUILD.gn dep + `teleport.gni` + `src/BUILD.gn`;六处须一致。
- 两个 policy BUILD.gn 加 `//teleport:teleport_policy_buildflags` dep 时确认不引入 `//content` 环(buildflag_header 是叶子)。
- 检出符号链接方向、`TELEPORT_CHROMIUM_DIR`、`--disable-field-trial-config`/`disable_fieldtrial_testing_config` 等见仓库 CLAUDE.md gotcha。
- 联调依赖服务端栈就绪;两计划合并各自 main 由用户决定(GitLab Flow:rebase + squash + ff)。
