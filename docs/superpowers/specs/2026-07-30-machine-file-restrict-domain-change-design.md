# 机器文件承载 restrict_domain_change 设计（machine-file-restrict）

- 日期：2026-07-30
- 状态：设计已获用户口头批准，待写入 spec 复核
- 范围：纯客户端（teleport 仓，仅 `//teleport` overlay + 一处 WebUI 接缝）；fairyland 零改动
- 落点：当前分支 `worktree-force-signin-policy-gate`（作为独立 commit；改动文件与本分支已有的 force-signin 工作不重叠）
- 前置事实来源（均按 M148 检出实证核对）：
  - `src/common/teleport_deployment_config.{h,cc,_mac.mm}`：五级域名解析 + 机器文件读取 + 信任门 + `IsDomainChangeLocked` 纯谓词
  - `src/browser/webui/teleport_enroll_ui.cc:75`：`IsEnrollPageLocked()` 唯一锁计算点，被 `:112`（只读显示）/`:128`（写入拒绝）/`:190`（解绑拒绝）三处消费
  - spec `docs/superpowers/specs/2026-07-15-deployment-domain-config-design.md` §4.6（corp-managed lock）

## 1. 背景与问题

部署域名的「§4.6 corp-managed lock」（enroll 页是否禁止用户改域）当前由两个信号决定（`IsDomainChangeLocked(source, restrict_change_forced)`）：

1. **域名来源级别**：level 1/2/3（命令行 / MDM forced pref / 机器文件）→ **恒锁**（域名来自管理员通道，管理员拥有它）；
2. **专用 restrict 信号**：level 4/5（用户已接受 / 内置默认）→ 仅当 `RestrictDeploymentDomainChange` 这个 **forced managed pref** 为真时才锁。

`RestrictDeploymentDomainChange` 现有的唯一用途，是锁定「域名是内置默认（level 5）、没配任何域名策略」的 SaaS 受管设备（该设备用默认域，不存在 level 1/2/3 域名来源，故只能靠这个专用布尔加锁）。它当前**只能经 forced managed pref 一条通道**下发——在无 MDM 的私有化环境里，这意味着必须 `sudo cp` 一份受管 plist（`/Library/Managed Preferences/…`），操作笨重，且与本环境已在使用的轻量管理员通道（机器文件 `/Library/Teleport/DeploymentConfig.json`）割裂。

**问题**：机器文件目前只承载 `domain` 一个键（`ParseDeploymentConfigJson` 只 `FindString("domain")`）。管理员想在同一个机器文件里**显式声明** restrict 意图，而不必额外走 forced managed pref。

## 2. 目标 / 非目标

**目标**

- G1：机器文件 `/Library/Teleport/DeploymentConfig.json` 新增可选布尔键 `restrict_domain_change`，作为 §4.6 锁的**第二条下发通道**。
- G2：与现有 forced managed pref 通道**并列**，任一为真即锁（OR 语义）。
- G3：过**同一个** `IsMachineConfigFileTrusted` 信任门（root 属主 + 非组/全局可写），信任级别与 `domain` 键、与 forced pref 一致。

**非目标（YAGNI 边界）**

- NG1：**不改变域名来源解析的行为/取值**（level 1–5）。`restrict_domain_change` 只影响锁决策，绝不影响域名值，也**不让**「只有 restrict、没有 domain 的机器文件」被当作 level 3 域名来源。注：`ParseDeploymentConfigJson` 内部会退化为薄 shim（委托给 §4.1 的结构体解析器再取 `.domain`），但其**公开契约与返回值逐一不变**，现有单测（`RejectsMissingDomain`/`IgnoresReservedFields` 等）全部保持绿——这是「行为不变」而非「代码字面不动」。
- NG2：**不改动**「level 1/2/3 域名来源恒锁」规则。这是「选项一：纯新增信号」的核心约束——本特性只在 level 4/5 场景下新增一条加锁通道，不引入任何解锁/覆盖语义。
- NG3：**不**把纳管 gate 开关 `RequireEnrollmentToBrowse` 塞进本文件（那是另一个信号，已由本分支的平台策略通道方案 `BrowserSignin=Force` 覆盖，见 TD-017）。本次严格只加 `restrict_domain_change`。

## 3. JSON schema

机器文件新增一个可选布尔键（与现有 `domain` 键同为小写；命名 `restrict_domain_change` 镜像 pref 名 `RestrictDeploymentDomainChange` 的 snake_case，自解释）：

```jsonc
// 仅 restrict，无 domain：域名留在内置默认(level 5)，但 enroll 页锁定
{ "restrict_domain_change": true }

// 老行为不变：level 3 域名来源，照旧自动锁（restrict 缺省不影响）
{ "domain": "acme.io" }

// 两者并存：restrict 冗余但无害（level 3 本就恒锁）
{ "domain": "acme.io", "restrict_domain_change": true }
```

**取值规则**（防御式）：键缺省 / 值非布尔 / JSON 损坏 → 一律解析为 `false`。

## 4. 架构与改动

改动收敛在 config 模块的「解析 / 读取 / 合并」三层（§4.1–4.3，全部位于 `//teleport`），外加一处 WebUI 接缝（§4.4）。

### 4.1 纯解析器 `ParseDeploymentConfigFile`（结构体）+ `ParseDeploymentConfigJson` shim

- 位置：`src/common/teleport_deployment_config.{h,cc}`。
- 结构体：
  ```cpp
  struct DeploymentConfigFields {
    std::optional<std::string> domain;   // normalized; nullopt if key absent OR invalid
    bool domain_key_present = false;     // true if a "domain" key existed (even if invalid)
    bool restrict_domain_change = false; // "restrict_domain_change" bool; false if absent/non-bool
  };
  DeploymentConfigFields ParseDeploymentConfigFile(std::string_view contents);
  ```
- 逻辑：解析 JSON dict（`JSON_PARSE_RFC`，非 dict/损坏 → 全默认值）。domain 经 `FindString("domain")`：键存在则 `domain_key_present=true`，值再过 `NormalizeDeploymentDomain`（失败则 `domain=nullopt`）。restrict 经 `FindBool("restrict_domain_change").value_or(false)`（缺省/非布尔 → false）。
- shim：`ParseDeploymentConfigJson(contents)` 退化为 `return ParseDeploymentConfigFile(contents).domain;`——**公开签名与返回值不变**，现有 domain 单测全绿（NG1）。
- 设计意图：把**全部**解析逻辑收进一个纯函数，`domain_key_present` 使读取器能精确区分「域名键缺省（restrict-only，合法）」与「域名键存在但无效（管理员打错，应报错）」。纯函数完整可 TDD（这是本特性真正的 hermetic 测试面，见 §6）。

### 4.2 读取器 `ReadMachineFileDomain`（改）+ `ReadMachineFileRestrict`（新）

机器文件在**启动期读取一次并进程级缓存**——`CachedMachineFile()`（匿名 namespace，`base::NoDestructor`）过**同一** `IsMachineConfigFileTrusted` 信任门、读文件、调 `ParseDeploymentConfigFile` 一次，`domain` 与 `restrict` 都从这一次缓存解析取。两个读取器退化为薄取值器：

- `ReadMachineFileDomain`（改）：`return CachedMachineFile().domain;`。**日志修正**——把现有对「域名缺省」无条件的 `LOG(ERROR) "...has no valid domain"` 改为仅当 `domain_key_present && !domain`（域名键存在但无效，真管理员错误）时报 ERROR；`domain_key_present==false`（restrict-only 合法文件）**不报**，消除本特性引入的每启动误报。日志在缓存读时（启动期）触发一次。
- `ReadMachineFileRestrict`（新）：`return CachedMachineFile().restrict_domain_change;`。restrict:true 而 domain 缺省/无效时（设备将落默认域）在缓存读时 `LOG(WARNING)` 一行，便于诊断评审指出的「打错域名却锁住」footgun。
- **为何缓存（关键约束，实现期活体验证发现）**：`IsDomainChangeRestrictedByAdmin` 由 enroll 页的 Mojo `GetState` 在 **UI 线程**调用，而 UI 线程**禁止阻塞文件 IO**（`base::ReadFileToString` 会命中 `DCHECK: !tls_blocking_disallowed` 而 abort）。域名读之所以安全，正因它在启动期（`DeploymentDomain()→Cached()→ResolveUncached()`，允许阻塞）读一次并缓存；restrict 折进同一次缓存读即同样安全，且顺带把文件从「domain + restrict 各读一次」减为一次。**代价**：机器文件 restrict 变为启动期快照，改动需**重启生效**（与 `domain` 一致）；forced-pref 通道（`ReadRestrictDomainChangeForced()`，CFPreferences 经 cfprefsd，非阻塞文件 IO）仍每次 live 读。

### 4.3 合并函数 `IsDomainChangeRestrictedByAdmin`（方案 A）

- 位置：`src/common/teleport_deployment_config.{h,cc}`（导出，供 WebUI 消费）。
- 签名：`bool IsDomainChangeRestrictedByAdmin()`。
- 逻辑：`return ReadRestrictDomainChangeForced() || ReadMachineFileRestrict();`
- 设计意图：把「restrict 有两条下发通道」这一事实收在 config 模块内。`ReadRestrictDomainChangeForced()`（平台 forced pref，mac 在 `_mac.mm`、其余 stub 返回 false）与 `ReadMachineFileRestrict()`（跨平台机器文件）在此 OR。`IsDomainChangeLocked(source, restrict)` **保持纯函数**（注入 bool，可测），不变。
- 只 OR、只加锁：任一通道为 true 即锁；无论哪条通道，值为 false 都只是「不贡献锁」，**不存在解锁语义**（信任模型见 §5 INV3）。

### 4.4 WebUI 接缝（唯一一处改动）

`src/browser/webui/teleport_enroll_ui.cc` 的 `IsEnrollPageLocked()`：

```cpp
// 改动前
bool IsEnrollPageLocked() {
  return IsDomainChangeLocked(DeploymentDomainSourceLevel(),
                              ReadRestrictDomainChangeForced());
}
// 改动后
bool IsEnrollPageLocked() {
  return IsDomainChangeLocked(DeploymentDomainSourceLevel(),
                              IsDomainChangeRestrictedByAdmin());
}
```

`IsEnrollPageLocked()` 是唯一锁计算点，三处消费（`:112` 只读显示 / `:128` 写入拒绝 / `:190` 解绑拒绝）自动一致受益，无需分别改动。

写入路径锁强制的传递性（评审指出，非本特性引入）：`Confirm()`（`:180` 附近）本身无显式锁检查，靠 `pending_entry_` 非空——而 `pending_entry_` 只可能由已过 `:128` 锁门的 `Verify()` 设置。当前正确，但强制是**经 `Verify()` 传递**而非直接。本特性只改 `IsEnrollPageLocked()` 的输入、不动这三处调用点，传递性关系不受影响；后续若有重构以别的路径设置 `pending_entry_`，需重新审视 `Confirm()` 是否要加直接锁检查。

## 5. 关键不变量

由「选项一：纯新增信号」保证，实现与评审均以此为验收基线：

- **INV1**：域名解析（level 1–5 与来源标签）完全不变。构造「只有 restrict、无 domain」的机器文件后，`DeploymentDomain()` 仍解析为 level 4/5，`chrome://version` 来源标签不显示 "machine config file"。
- **INV2**：level 1/2/3 恒锁规则不变。restrict 仅在 level 4/5 时生效（`IsDomainChangeLocked` 现有逻辑天然如此——1/2/3 分支直接 return true，不看 restrict）。
- **INV3**：forced managed pref 通道原样保留；两通道 OR，任一为真即锁；两者皆假则不锁。
- **INV4**：信任门统一。未过 `IsMachineConfigFileTrusted`（非 root 属主 / 组或全局可写 / 非常规文件 / 缺失）→ `ReadMachineFileRestrict` 返回 false，与 domain 读取的 fail-closed 行为一致。

## 6. 测试

**可 hermetic 单测的面（纯函数，走严格 TDD）**——本特性的全部新解析逻辑都收在 `ParseDeploymentConfigFile` 里，故这是真正的可测面。置于 `src/common/teleport_deployment_config_unittest.cc`：

- `ParseDeploymentConfigFile`：
  - `{"restrict_domain_change": true}` → `restrict=true`，`domain=nullopt`，`domain_key_present=false`
  - `{"restrict_domain_change": false}` / 缺键 `{}` → `restrict=false`
  - 非布尔 `{"restrict_domain_change": "true"}`（字符串）→ `restrict=false`
  - `{"domain":"acme.io"}` → `domain="acme.io"`，`domain_key_present=true`，`restrict=false`
  - `{"domain":"https://bad/x"}`（无效域名）→ `domain=nullopt`，`domain_key_present=true`（用于日志区分）
  - 并存 `{"domain":"acme.io","restrict_domain_change":true}` → 两者皆取到
  - 损坏 JSON / 非 dict（`[1,2]`）→ 全默认值
- `ParseDeploymentConfigJson` shim 回归：现有全部 domain 单测保持绿（验证 shim 行为等价）。
- `IsDomainChangeLocked` 组合矩阵（纯谓词，补充语义确认）：level 5 + restrict=true → 锁；level 5 + restrict=false → 不锁；level 3 + restrict=false → 仍锁（INV2）。

**不可 hermetic 单测的面（诚实声明）**：`ReadMachineFileRestrict` / `ReadMachineFileDomain` / `IsDomainChangeRestrictedByAdmin` 的**受信正路径无法单测**——它们在匿名 namespace、读硬编码的 `/Library/...` 路径，且 `IsMachineConfigFileTrusted` 要求 `uid==0` 属主，而单测进程非 root，无法构造受信夹具（这正是既有姊妹函数 `ReadMachineFileDomain` 零单测的原因；现有信任夹具 `RejectsNonRootOwnedFile`/`RejectsMissingFile` 只覆盖 untrusted/absent 分支）。故受信正路径**仅活体验证，不做单测**——这是本特性测试策略的明确边界，不假装用 gtest 覆盖。

**活体验证（无 sudo cp）**：写 `{"restrict_domain_change":true}`（无 domain）到机器文件、root 属主 644，重启浏览器 →
- `chrome://version` 域名仍为默认、来源 "built-in default"（INV1）；
- enroll 页锁定（`state->locked=true` → 表单只读，`Verify` 写入被 `:128` 拒）；
- 启动日志**无** "has no valid domain" ERROR 误报（§4.2 日志修正）。

## 7. 文档更新

- `docs/deployment-domain-migration-runbook.md` §4 锁定表：新增「机器文件 `restrict_domain_change:true`」一行，与 forced managed pref 并列为 level 4/5 加锁通道。
- `CLAUDE.md` deployment-domain gotcha：补充机器文件除 `domain` 外亦承载 `restrict_domain_change` 布尔键（同一信任门）。
- 本 spec 提交入库。

## 8. 风险与权衡

- **无效域名 + restrict:true 的 footgun**（评审指出）：管理员在机器文件里把域名打错（如 `"https://bad/x"`）→ `NormalizeDeploymentDomain` 失败 → 域名静默落**内置默认 SaaS 域**，而 restrict:true **锁住** enroll 页 → 设备被钉在错误默认域、用户无自助更正入口。属 fail-closed（可接受），但意外性高。缓解：§4.2 的 `ReadMachineFileRestrict` 在此情形 `LOG(WARNING)`；`ReadMachineFileDomain` 亦对 `domain_key_present && !domain` `LOG(ERROR)`；`chrome://version` 来源显示 "built-in default" 也是诊断面。交付文档需提示管理员核对域名规范形态。
- **UI 线程阻塞 IO（实现期活体验证发现，已修）**：初版让 `ReadMachineFileRestrict` 在每次锁检查 live 读文件，但 `IsEnrollPageLocked` 经 Mojo `GetState` 在 UI 线程执行，`base::ReadFileToString` 命中 `DCHECK: !tls_blocking_disallowed` → enroll 页一打开即 abort。修复：折进启动期 `CachedMachineFile()`（见 §4.2），UI 线程只读缓存。代价是 restrict 改动需重启（与 domain 一致），非 live——这是与初始设计的偏离，但初始的 live-读设计不可行（会崩）。
- **命名一致性**：JSON 用 snake_case `restrict_domain_change`，pref 用 PascalCase `RestrictDeploymentDomainChange`，两套命名分别贴合各自载体的既有约定（JSON 现有键 `domain` 小写；CFPreferences 键 PascalCase）。文档需同时列出，避免混淆。
- **跨平台**：机器文件读取器全在跨平台 `.cc`（`IsMachineConfigFileTrusted` 用 POSIX `lstat`）。当前仅构建 mac，与现有 `ReadMachineFileDomain` 同构，无新增平台分支。
