# 机器文件 restrict_domain_change 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让机器配置文件 `/Library/Teleport/DeploymentConfig.json` 承载一个可选布尔键 `restrict_domain_change`，作为 §4.6 corp-managed 域变更锁的第二条下发通道（与现有 forced managed pref 通道 OR）。

**Architecture:** 把机器文件的全部 JSON 解析逻辑收进一个纯函数 `ParseDeploymentConfigFile`（返回 `{domain, domain_key_present, restrict_domain_change}` 结构体），`ParseDeploymentConfigJson` 退化为薄 shim（行为/返回值不变）。新增读取器 `ReadMachineFileRestrict` 过同一信任门读取，`IsDomainChangeRestrictedByAdmin` 把它与 forced-pref 通道 OR，在唯一接缝 `IsEnrollPageLocked()` 消费。纯新增加锁信号：域名解析与「level 1/2/3 恒锁」规则不变。

**Tech Stack:** C++（`//teleport` overlay，Chromium M148），gtest，`base::JSONReader` / `base::Value::Dict`。

## Global Constraints

- 产品代码（`//teleport` C++）走 TDD（gtest）；本特性可 hermetic 测试的面**仅** `ParseDeploymentConfigFile` 纯函数——受信读取器（匿名 namespace + 硬编码 `/Library` 路径 + `uid==0` 门、测试进程非 root）**无法单测其受信正路径**，仅活体验证。
- 一文件一 patch 仅适用于**上游文件**；本特性改的全是 `//teleport` overlay 源码（`src/` 下），直接编辑源文件，无 patch。
- JSON 键 `restrict_domain_change`（snake_case，防御式：缺省/非布尔/损坏 JSON → false）。
- 不改动域名来源解析（level 1–5）行为/取值；不改「level 1/2/3 恒锁」规则；不存在解锁语义（只 OR、只加锁）。
- 代码/注释/提交信息用英文；文档用简体中文。
- 修改已有 patch 的工作流不适用（无 patch 改动）。构建前 `export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`。

---

### Task 1: 纯解析器 `ParseDeploymentConfigFile` + `ParseDeploymentConfigJson` shim

**Files:**
- Modify: `src/common/teleport_deployment_config.h`（声明结构体 + `ParseDeploymentConfigFile`）
- Modify: `src/common/teleport_deployment_config.cc:229-240`（新增 `ParseDeploymentConfigFile`，`ParseDeploymentConfigJson` 改 shim）
- Test: `src/common/teleport_deployment_config_unittest.cc`（新增 `TeleportDeploymentConfigFileTest`；现有 `TeleportDeploymentConfigJsonTest` 保持不变、须全绿）

**Interfaces:**
- Produces:
  - `struct teleport::DeploymentConfigFields { std::optional<std::string> domain; bool domain_key_present = false; bool restrict_domain_change = false; };`
  - `DeploymentConfigFields teleport::ParseDeploymentConfigFile(std::string_view contents);`
  - `std::optional<std::string> teleport::ParseDeploymentConfigJson(std::string_view)`（签名不变，内部委托）

- [ ] **Step 1: 写失败测试**

在 `src/common/teleport_deployment_config_unittest.cc` 的 `namespace teleport { namespace {` 内，`TeleportDeploymentConfigJsonTest` 测试组附近，新增：

```cpp
TEST(TeleportDeploymentConfigFileTest, RestrictOnlyNoDomain) {
  DeploymentConfigFields f =
      ParseDeploymentConfigFile(R"({"restrict_domain_change":true})");
  EXPECT_TRUE(f.restrict_domain_change);
  EXPECT_FALSE(f.domain.has_value());
  EXPECT_FALSE(f.domain_key_present);
}

TEST(TeleportDeploymentConfigFileTest, RestrictFalseAndMissingAreFalse) {
  EXPECT_FALSE(
      ParseDeploymentConfigFile(R"({"restrict_domain_change":false})")
          .restrict_domain_change);
  EXPECT_FALSE(ParseDeploymentConfigFile(R"({})").restrict_domain_change);
}

TEST(TeleportDeploymentConfigFileTest, RestrictNonBoolIsFalse) {
  EXPECT_FALSE(
      ParseDeploymentConfigFile(R"({"restrict_domain_change":"true"})")
          .restrict_domain_change);
}

TEST(TeleportDeploymentConfigFileTest, DomainPresentValid) {
  DeploymentConfigFields f = ParseDeploymentConfigFile(R"({"domain":"acme.io"})");
  EXPECT_EQ(f.domain, "acme.io");
  EXPECT_TRUE(f.domain_key_present);
  EXPECT_FALSE(f.restrict_domain_change);
}

TEST(TeleportDeploymentConfigFileTest, DomainPresentButInvalidFlagsPresence) {
  DeploymentConfigFields f =
      ParseDeploymentConfigFile(R"({"domain":"https://bad/x"})");
  EXPECT_FALSE(f.domain.has_value());
  EXPECT_TRUE(f.domain_key_present);  // drives the invalid-domain error log
}

TEST(TeleportDeploymentConfigFileTest, DomainNonStringFlagsPresence) {
  DeploymentConfigFields f = ParseDeploymentConfigFile(R"({"domain":42})");
  EXPECT_FALSE(f.domain.has_value());
  EXPECT_TRUE(f.domain_key_present);  // key exists (wrong type) -> still an error
}

TEST(TeleportDeploymentConfigFileTest, DomainAndRestrictTogether) {
  DeploymentConfigFields f = ParseDeploymentConfigFile(
      R"({"domain":"acme.io","restrict_domain_change":true})");
  EXPECT_EQ(f.domain, "acme.io");
  EXPECT_TRUE(f.domain_key_present);
  EXPECT_TRUE(f.restrict_domain_change);
}

TEST(TeleportDeploymentConfigFileTest, MalformedAndNonDictAreAllDefault) {
  DeploymentConfigFields f1 = ParseDeploymentConfigFile("{not json");
  EXPECT_FALSE(f1.domain_key_present);
  EXPECT_FALSE(f1.restrict_domain_change);
  DeploymentConfigFields f2 = ParseDeploymentConfigFile("[1,2,3]");
  EXPECT_FALSE(f2.domain_key_present);
  EXPECT_FALSE(f2.restrict_domain_change);
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests
```

Expected: 编译失败——`ParseDeploymentConfigFile` / `DeploymentConfigFields` 未声明。

- [ ] **Step 3: 声明结构体 + 函数（header）**

在 `src/common/teleport_deployment_config.h` 中，`ParseDeploymentConfigJson` 声明（约 93-94 行 `// Parse the machine config file JSON...`）**之前**插入：

```cpp
// Parsed fields of the level-3 machine config file. `domain` is the normalized
// value (nullopt when the "domain" key is absent OR present-but-invalid);
// `domain_key_present` distinguishes those two so a restrict-only file does not
// trip the invalid-domain error log. `restrict_domain_change` is the §4.6 lock
// opt-in (false when the key is absent or non-boolean).
struct DeploymentConfigFields {
  std::optional<std::string> domain;
  bool domain_key_present = false;
  bool restrict_domain_change = false;
};

// Pure parser for the machine config file JSON. Does no file IO. All parsing
// logic lives here (fully unit-testable); the readers below are thin trust-gated
// wrappers. Non-dict / malformed JSON yields all-default fields.
DeploymentConfigFields ParseDeploymentConfigFile(std::string_view contents);
```

- [ ] **Step 4: 实现 `ParseDeploymentConfigFile` + shim（cc）**

在 `src/common/teleport_deployment_config.cc` 中，把现有 `ParseDeploymentConfigJson`（约 229-240 行）整体替换为：

```cpp
DeploymentConfigFields ParseDeploymentConfigFile(std::string_view contents) {
  DeploymentConfigFields fields;
  std::optional<base::Value> value =
      base::JSONReader::Read(contents, base::JSON_PARSE_RFC);
  if (!value || !value->is_dict()) {
    return fields;  // all defaults
  }
  const base::Value::Dict& dict = value->GetDict();
  // A "domain" key of ANY type marks presence (so a wrong-typed value still
  // logs as an admin error, matching the pre-refactor behavior); only a string
  // value is normalized into an actual domain.
  if (const base::Value* domain_val = dict.Find("domain")) {
    fields.domain_key_present = true;
    if (const std::string* domain_str = domain_val->GetIfString()) {
      fields.domain = NormalizeDeploymentDomain(*domain_str);
    }
  }
  fields.restrict_domain_change =
      dict.FindBool("restrict_domain_change").value_or(false);
  return fields;
}

std::optional<std::string> ParseDeploymentConfigJson(std::string_view contents) {
  return ParseDeploymentConfigFile(contents).domain;
}
```

- [ ] **Step 5: 运行测试确认通过**

```bash
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportDeploymentConfig*'
```

Expected: PASS——新增 8 个 `TeleportDeploymentConfigFileTest` 全绿，且现有 `TeleportDeploymentConfigJsonTest`（`ExtractsAndNormalizesDomain`/`IgnoresReservedFields`/`RejectsMissingDomain`/`RejectsNonStringDomain`/`RejectsInvalidDomainValue`/`RejectsMalformedJson`/`RejectsNonDictJson`）全部保持绿（shim 行为等价）。

- [ ] **Step 6: 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/force-signin-policy-gate
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc src/common/teleport_deployment_config_unittest.cc
git commit -m "feat(deployment): struct parser for machine config file (domain + restrict)

Fold all machine-config JSON parsing into a hermetic ParseDeploymentConfigFile
returning {domain, domain_key_present, restrict_domain_change}.
ParseDeploymentConfigJson becomes a thin shim over it (signature and return
values unchanged; existing tests stay green). domain_key_present lets a
later reader distinguish an intentional restrict-only file from an invalid
domain.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 读取器 + 合并函数 + WebUI 接缝

**Files:**
- Modify: `src/common/teleport_deployment_config.h`（声明 `IsDomainChangeRestrictedByAdmin`）
- Modify: `src/common/teleport_deployment_config.cc:55-71`（`ReadMachineFileDomain` 改用结构体 + 精确日志；新增 `ReadMachineFileRestrict`；新增 `IsDomainChangeRestrictedByAdmin`）
- Modify: `src/browser/webui/teleport_enroll_ui.cc:75-78`（`IsEnrollPageLocked` 换用合并函数）

**Interfaces:**
- Consumes: `DeploymentConfigFields`, `ParseDeploymentConfigFile`（Task 1）；`IsMachineConfigFileTrusted`, `kDeploymentConfigFilePath`, `ReadRestrictDomainChangeForced`, `IsDomainChangeLocked`, `DeploymentDomainSourceLevel`（既有）
- Produces: `bool teleport::IsDomainChangeRestrictedByAdmin();`

> 说明：本 Task 的读取器（`ReadMachineFileRestrict` / 改后的 `ReadMachineFileDomain` / `IsDomainChangeRestrictedByAdmin`）**受信正路径无法单测**（匿名 namespace + 硬编码 `/Library` 路径 + 非 root 测试进程）。锁谓词 `IsDomainChangeLocked` 的组合矩阵已由现有测试 `HigherPrioritySourceLocks`/`UserAcceptedAndBakedDefaultUnlockedWhenUnmanaged`/`RestrictPolicyLocksBakedDefault` 完整覆盖，本 Task 不改该谓词、无需新增其测试。Task 的验收 = 编译通过 + 现有 gtest 全绿 + Task 4 活体验证。

- [ ] **Step 1: 声明合并函数（header）**

在 `src/common/teleport_deployment_config.h` 中，`ReadRestrictDomainChangeForced()` 声明（约 58 行）**之后**插入：

```cpp
// True iff an admin has restricted domain change via EITHER channel: the forced
// managed pref (ReadRestrictDomainChangeForced) OR a trusted machine config file
// carrying "restrict_domain_change": true. Only ever locks (OR of two opt-ins);
// there is no unlock path. Consumed by the enroll page (§4.6).
bool IsDomainChangeRestrictedByAdmin();
```

- [ ] **Step 2: 改 `ReadMachineFileDomain` + 新增 `ReadMachineFileRestrict`（cc）**

在 `src/common/teleport_deployment_config.cc` 中，把现有 `ReadMachineFileDomain`（约 54-71 行）整体替换为下面两个函数：

```cpp
// Level 3 (cross-platform): read + trust-gate + parse the machine config file's
// deployment domain. Logs an error only when a "domain" key is present but does
// not yield a valid domain (a real admin mistake); a restrict-only file (no
// "domain" key) is a legitimate state and stays quiet.
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
  DeploymentConfigFields fields = ParseDeploymentConfigFile(contents);
  if (fields.domain_key_present && !fields.domain) {
    LOG(ERROR) << "[teleport-deployment] machine config file has an invalid "
                  "domain value";
  }
  return fields.domain;
}

// §4.6 corp-managed lock, machine-file channel: read + trust-gate + parse the
// "restrict_domain_change" boolean. Same trust gate as the domain read; absent /
// untrusted / unreadable -> false. Warns when it honors restrict:true on a file
// whose domain did not resolve (device stays on the default domain, locked).
bool ReadMachineFileRestrict() {
  base::FilePath path(kDeploymentConfigFilePath);
  if (!IsMachineConfigFileTrusted(path)) {
    return false;
  }
  std::string contents;
  if (!base::ReadFileToString(path, &contents)) {
    return false;
  }
  DeploymentConfigFields fields = ParseDeploymentConfigFile(contents);
  if (fields.restrict_domain_change && !fields.domain) {
    LOG(WARNING) << "[teleport-deployment] restrict_domain_change honored but "
                    "no valid deployment domain in machine config file; the "
                    "device stays on the resolved (likely default) domain";
  }
  return fields.restrict_domain_change;
}
```

- [ ] **Step 3: 新增 `IsDomainChangeRestrictedByAdmin`（cc）**

在 `src/common/teleport_deployment_config.cc` 中，`IsDomainChangeLocked`（约 130 行）**之后**新增（放在 `teleport` 命名空间内、非匿名 namespace，因为要导出）：

```cpp
bool IsDomainChangeRestrictedByAdmin() {
  return ReadRestrictDomainChangeForced() || ReadMachineFileRestrict();
}
```

- [ ] **Step 4: 改 WebUI 接缝**

在 `src/browser/webui/teleport_enroll_ui.cc` 中，把 `IsEnrollPageLocked()`（约 75-78 行）改为：

```cpp
// The §4.6 corp-managed lock: source level + the admin restrict signal (forced
// managed pref OR trusted machine config file), folded through the pure
// predicate.
bool IsEnrollPageLocked() {
  return IsDomainChangeLocked(DeploymentDomainSourceLevel(),
                              IsDomainChangeRestrictedByAdmin());
}
```

- [ ] **Step 5: 编译 + 全量 gtest**

```bash
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests
```

Expected: 编译通过；`SUCCESS: all tests passed.`（含现有锁矩阵测试 `HigherPrioritySourceLocks`/`RestrictPolicyLocksBakedDefault`/`UserAcceptedAndBakedDefaultUnlockedWhenUnmanaged` 全绿——INV2/INV3 背书）。

- [ ] **Step 6: 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/force-signin-policy-gate
git add src/common/teleport_deployment_config.h src/common/teleport_deployment_config.cc src/browser/webui/teleport_enroll_ui.cc
git commit -m "feat(deployment): machine-file restrict_domain_change as a §4.6 lock channel

ReadMachineFileRestrict reads the trusted machine config file's
restrict_domain_change bool; IsDomainChangeRestrictedByAdmin ORs it with the
existing forced-managed-pref channel. The enroll page's single lock seam
IsEnrollPageLocked consumes the combined signal, so all three consumers
(read-only display, write guard, unbind guard) benefit uniformly.
ReadMachineFileDomain now logs an error only for a present-but-invalid domain,
not for a legitimate restrict-only file. Additive lock only; domain resolution
and the level-1/2/3 always-lock rule are unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 文档更新（runbook + CLAUDE.md）

**Files:**
- Modify: `docs/deployment-domain-migration-runbook.md`（§4 锁定表加机器文件行）
- Modify: `CLAUDE.md`（deployment-domain gotcha 补充机器文件 restrict 键）

- [ ] **Step 1: 更新 runbook 锁定表**

在 `docs/deployment-domain-migration-runbook.md` 的 §4 锁定表中，`RestrictDeploymentDomainChange`（MDM managed pref）那一行**之后**，新增一行说明机器文件通道：

```markdown
| SaaS 受管(D=官方默认，无 MDM) | 机器文件 `restrict_domain_change:true` | 写入 `/Library/Teleport/DeploymentConfig.json`(root 属主 + 644，非组/全局可写)，与 forced managed pref 同为 level 4/5 加锁通道，OR 生效 |
```

并在该表下方补一段：

```markdown
**机器文件 `restrict_domain_change`（无 MDM 的轻量通道）**：与 `domain` 键同一文件、同一信任门（root 属主 + 非组/全局可写）。可独立于 `domain` 存在——`{"restrict_domain_change": true}`（不带 domain）会让域名留在内置默认(level 5)、但锁定 enroll 页。注意：若同时写了无效的 `domain` 值，设备会静默落默认域并仍被锁（fail-closed），日志有 WARNING；交付时提示管理员核对域名规范形态。
```

- [ ] **Step 2: 更新 CLAUDE.md gotcha**

在 `CLAUDE.md` 的 deployment-domain-config gotcha 段（提及 `RestrictDeploymentDomainChange` 与机器文件 `DeploymentConfig.json` 处）补一句：

```markdown
机器文件 `/Library/Teleport/DeploymentConfig.json` 除 `domain` 外亦承载可选布尔键 `restrict_domain_change`（§4.6 锁的第二条通道，与 forced managed pref `RestrictDeploymentDomainChange` OR；同一信任门）；解析走 `ParseDeploymentConfigFile`(纯函数,返回 {domain, domain_key_present, restrict})，`ReadMachineFileRestrict` 在锁检查时 live 读、不缓存，`IsDomainChangeRestrictedByAdmin` 合并两通道，唯一接缝 `IsEnrollPageLocked`。
```

- [ ] **Step 3: 提交**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/force-signin-policy-gate
git add docs/deployment-domain-migration-runbook.md CLAUDE.md
git commit -m "docs(deployment): document machine-file restrict_domain_change channel

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 集成构建 + 活体验证

**Files:** 无（仅构建与运行时验证）

- [ ] **Step 1: 全量构建 chrome + gtest**

```bash
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
cd "$TELEPORT_CHROMIUM_DIR/src"
autoninja -C out/mac/arm64/dev chrome teleport_unittests && \
  ./out/mac/arm64/dev/teleport_unittests | tail -2
```

Expected: 构建成功；`SUCCESS: all tests passed.`

- [ ] **Step 2: 活体验证 restrict-only 机器文件（无 sudo cp）**

需要 root 写 `/Library/Teleport/DeploymentConfig.json`（信任门要 root 属主）。请求用户在输入框执行（`!` 前缀）：

```
! printf '{"restrict_domain_change": true}\n' | sudo tee /Library/Teleport/DeploymentConfig.json >/dev/null && sudo chown root:wheel /Library/Teleport/DeploymentConfig.json && sudo chmod 644 /Library/Teleport/DeploymentConfig.json && ls -l /Library/Teleport/DeploymentConfig.json
```

- [ ] **Step 3: 启动浏览器（全新 profile）经 CDP 断言**

```bash
SCRATCH=/private/tmp/claude-501/-Users-liulichao-workspace-teleport/ae7045f2-0f3d-44e6-ac22-3981d86db8dc/scratchpad
rm -rf "$SCRATCH/restrict-udd"
/Users/liulichao/workspace/teleport/chromium/src/out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport \
  --user-data-dir="$SCRATCH/restrict-udd" --remote-debugging-port=9340 \
  --no-first-run --no-default-browser-check "chrome://version" >/dev/null 2>&1 &
```

用 CDP（`suppress_origin=True`，见既往会话脚本）读 `chrome://version` 的部署域名行，并打开 `teleport://enroll` 读 `state.locked`：
- Expected `chrome://version`：`Deployment domain  fairyland.io (source: built-in default)`（INV1——restrict 不改域名/来源）。
- Expected enroll 页：`locked=true`（表单只读）。
- Expected 启动日志：**无** `has no valid domain` ERROR（§4.2 日志修正；可在启动 stderr 中确认）。

- [ ] **Step 4: 反向对照 —— restrict:false 不锁**

```
! printf '{"restrict_domain_change": false}\n' | sudo tee /Library/Teleport/DeploymentConfig.json >/dev/null && sudo killall cfprefsd 2>/dev/null; echo set-false
```

重启浏览器（新 profile），enroll 页 `locked=false`（表单可编辑）——确认无解锁反转、restrict:false 只是不贡献锁。

- [ ] **Step 5: 清理**

```
! sudo rm -f /Library/Teleport/DeploymentConfig.json
```

```bash
SCRATCH=/private/tmp/claude-501/-Users-liulichao-workspace-teleport/ae7045f2-0f3d-44e6-ac22-3981d86db8dc/scratchpad
pkill -f "restrict-udd"; rm -rf "$SCRATCH/restrict-udd"
```

- [ ] **Step 6: 记录验证结果**

在本计划文件末尾追加一节「验证结果」，记录 gtest 通过数、CDP 断言结果、日志观察。无需提交（或与收尾一起提交）。

---

## 验证结果

- **单测**：`teleport_unittests` 全量 `SUCCESS: all tests passed.`（含新增 8 个 `TeleportDeploymentConfigFileTest` + 7 个 `TeleportDeploymentConfigJsonTest` shim 回归 + 既有锁矩阵 `HigherPrioritySourceLocks`/`RestrictPolicyLocksBakedDefault`/`UserAcceptedAndBakedDefaultUnlockedWhenUnmanaged`）。构建 `chrome + teleport_unittests` 成功、0 error。
- **实现期发现并修复的 bug（systematic-debugging）**：初版 `ReadMachineFileRestrict` 在 UI 线程（enroll 页 Mojo `GetState`）做阻塞文件 IO → `DCHECK: !tls_blocking_disallowed` abort（一打开 `chrome://enroll` 即崩）。修复：折进启动期 `CachedMachineFile()`（`base::NoDestructor`，随域名解析在允许阻塞的启动期读一次）；UI 线程只读缓存。commit `2adfa08`。
- **活体验证(CDP + shadow DOM 探针 + stderr)**：
  - restrict-only 文件 `{"restrict_domain_change":true}`（root:644）→ `chrome://version` 域名 `fairyland.io (source: built-in default)`(INV1 ✓)；`chrome://enroll` 影子 DOM 含 `此设置由你的组织管理`(锁定视图 ✓)、无可编辑表单；stderr `WARNING: restrict_domain_change honored`(后端采纳 ✓)；无崩溃。
  - 反向 `{"restrict_domain_change":false}`（重启，因缓存）→ `chrome://enroll` 显示可编辑「连接到组织服务器」表单、无 managed-note(未锁 ✓)；无 restrict WARNING(不贡献锁、无解锁反转 ✓)。
