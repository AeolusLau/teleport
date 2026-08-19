# 部署环境三态化 Phase 2:密钥治理与根集合验签 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把策略验签信任锚从"每档一把根"升级为"每档一个根集合"(release = 主根 + 休眠恢复根),补齐评审发现的全部 6 个验签点,并让 `gen_policy_verification_key.py` 能区分占位根与真实根。

**Architecture:** `cloud_policy_constants` 新增 `GetPolicyVerificationKeys()`(返回本档全部受信根)与 `IsKnownVerificationKey()`(集合成员判定);`CloudPolicyValidatorBase` 的单值成员 `verification_key_` 改为 `verification_keys_`,4 处验签调用改为"集合中任一通过即通过";两个 policy store 的 key-rotation 判定从"是否等于主根"改为"是否属于当前集合"——这样恢复根签发的缓存不会在每次启动触发全量重拉,而真正被移除的旧根仍会正确触发轮换。overlay 的两个 server-identity 调用点按 verdict 聚合规则遍历。

**Tech Stack:** C++17 (Chromium M151) / gtest / Python 3.13 + pytest (uv) / OpenSSL(仅用于生成一次性占位公钥)

## Global Constraints

- **spec 权威**:`docs/superpowers/specs/2026-08-10-deployment-env-tristate-design.md`(v2)§4.2、§4.6。
- **第三态字面值 `release`**;buildflag 为 `TELEPORT_ENV_IS_RELEASE` / `TELEPORT_ENV_IS_STAGING`(Phase 1 已落地)。
- **文档中文,代码/注释/commit 英文**。
- **一文件一 patch**,文件名镜像 `chromium/src` 下路径。
- **修改已有 patch 的标准工作流**(禁止手改 hunk):`apply_patches.py` → 编辑 `$CR/<file>` → `git -C "$CR" diff -- <path> > patches/<path>.patch` → 再跑 `apply_patches.py` 验证幂等。其中 `CR=~/workspace/chromium/151.0.7922/src`。
- **本 Phase 不触碰品牌重写的三个例外路径**,无需 `--skip-branding` 树。
- **git 命令一律用 `git -C <worktree>`**,不依赖 shell cwd(cwd 会被 harness 重置到主 worktree,曾导致命令跑到 main 分支上)。
- 每个任务结束时工作树干净,`uv run pytest` 与 `teleport_unittests` 全绿。
- **占位私钥一律丢弃**,只保留公钥;任何私钥都不得写入仓库或 scratchpad 之外的位置。

---

### Task 5: 占位根公钥 + 密钥生成器多档参数化

**Files:**
- Create: `keys/staging-policy-root.pub.pem`
- Create: `keys/release-policy-root.pub.pem`
- Create: `keys/release-policy-recovery-root.pub.pem`
- Modify: `scripts/gen_policy_verification_key.py`
- Modify: `scripts/tests/test_gen_policy_verification_key.py`

**Interfaces:**
- Produces: `ENVS: dict[str, tuple[RootSpec, ...]]`,`RootSpec(symbol: str, pem: str, derives_hash: bool)`;`load_pub_der(path)`、`key_hash(der)`(已存在);新增 `placeholder_fingerprints() -> dict[str, str]`、`run_check(env: str | None, require_real: bool)`。Task 6 消费 `ENVS` 定义的符号名。

- [ ] **Step 1: 提取现有 release 占位根的公钥,并生成两把新占位公钥**

现有 `kReleasePolicyKey` 已是占位,先把它还原成 PEM 以便纳入统一管理:

```bash
W=/Users/liulichao/workspace/teleport/.worktrees/aliyun-first-deploy
S=/private/tmp/claude-501/-Users-liulichao-workspace-teleport/2c4f0db0-136e-487f-b89f-feb888cef03d/scratchpad
mkdir -p "$S/keys"
# 1) 从 patch 中抽出 kReleasePolicyKey 的 DER 并写成 PEM
uv run python - <<'PY'
import re, base64, pathlib
patch = pathlib.Path("patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch").read_text()
m = re.search(r"kReleasePolicyKey\[\] = \{(.*?)\};", patch, re.S)
der = bytes(int(t, 16) for t in re.findall(r"0x([0-9a-fA-F]{2})", m.group(1)))
b64 = base64.b64encode(der).decode()
lines = "\n".join(b64[i:i+64] for i in range(0, len(b64), 64))
pathlib.Path("keys/release-policy-root.pub.pem").write_text(
    "-----BEGIN PUBLIC KEY-----\n" + lines + "\n-----END PUBLIC KEY-----\n")
print("release placeholder DER bytes:", len(der))
PY
# 2) 生成两把新的一次性占位密钥,只保留公钥,私钥立即销毁
for name in staging-policy-root release-policy-recovery-root; do
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$S/keys/$name.key" 2>/dev/null
  openssl rsa -in "$S/keys/$name.key" -pubout -out "keys/$name.pub.pem" 2>/dev/null
  rm -f "$S/keys/$name.key"
done
ls -l keys/
```

Expected:`keys/` 下 4 个 `.pub.pem`(dev 那把已存在)。三把占位公钥的私钥半边**不存在于任何地方**——这正是它们必须被 fail-closed 挡住的原因。

- [ ] **Step 2: 写失败的测试(多档 + 占位检测)**

追加到 `scripts/tests/test_gen_policy_verification_key.py`:

```python
def test_envs_cover_all_three_environments():
    assert set(g.ENVS) == {"dev", "staging", "release"}


def test_release_has_two_roots_exactly_one_deriving_the_hash():
    roots = g.ENVS["release"]
    assert len(roots) == 2
    assert [r.derives_hash for r in roots] == [True, False]


def test_dev_and_staging_are_single_root():
    for env in ("dev", "staging"):
        assert len(g.ENVS[env]) == 1
        assert g.ENVS[env][0].derives_hash


def test_every_vendored_pem_is_loadable_and_294_bytes():
    for env, roots in g.ENVS.items():
        for r in roots:
            der = g.load_pub_der(g.REPO / "keys" / r.pem)
            assert len(der) == 294, f"{env}/{r.pem} is {len(der)} bytes"


def test_placeholder_fingerprints_cover_the_three_placeholder_roots():
    fps = g.placeholder_fingerprints()
    for env, roots in g.ENVS.items():
        for r in roots:
            der = g.load_pub_der(g.REPO / "keys" / r.pem)
            fp = g.der_fingerprint(der)
            if env == "dev":
                assert fp not in fps, "the dev root is real, not a placeholder"
            else:
                assert fp in fps, f"{r.pem} must be registered as a placeholder"


def test_require_real_rejects_a_placeholder_env():
    # staging/release still ship placeholders, so --require-real must refuse.
    with pytest.raises(SystemExit, match="placeholder"):
        g.run_check(env="staging", require_real=True)
    with pytest.raises(SystemExit, match="placeholder"):
        g.run_check(env="release", require_real=True)


def test_require_real_accepts_the_dev_root():
    g.run_check(env="dev", require_real=True)  # must not raise
```

- [ ] **Step 3: 运行,确认失败**

```bash
W=/Users/liulichao/workspace/teleport/.worktrees/aliyun-first-deploy
cd "$W" && uv run pytest scripts/tests/test_gen_policy_verification_key.py -q 2>&1 | tail -5
```

Expected:多个 `AttributeError: module has no attribute 'ENVS'` 之类的失败。

- [ ] **Step 4: 参数化 `gen_policy_verification_key.py`**

用下面内容替换 `PUB_PEM` 常量与 `patch_dev_key()` / `run_check()` / `main()`(保留 `load_pub_der`、`key_hash`、`c_array_lines`):

```python
@dataclass(frozen=True)
class RootSpec:
    symbol: str        # C array symbol name inside the patch
    pem: str           # filename under keys/
    derives_hash: bool # kPolicyVerificationKeyHash is derived from this root


# Which roots each environment bakes, and under what symbol. release carries a
# dormant recovery root in addition to the primary one: baking a second public
# key is cheap and IRREVERSIBLE -- a client that shipped without it can never be
# taught to trust it -- so it goes in from the first release build. Only the
# primary derives kPolicyVerificationKeyHash, which is what the client reports
# to the server.
ENVS: dict[str, tuple[RootSpec, ...]] = {
    "dev": (RootSpec("kDevPolicyKey", "dev-policy-root.pub.pem", True),),
    "staging": (RootSpec("kStagingPolicyKey", "staging-policy-root.pub.pem", True),),
    "release": (
        RootSpec("kReleasePolicyKey", "release-policy-root.pub.pem", True),
        RootSpec("kReleasePolicyRecoveryKey",
                 "release-policy-recovery-root.pub.pem", False),
    ),
}


def der_fingerprint(der: bytes) -> str:
    """Full SHA-256 of the DER SPKI, hex. Distinct from key_hash(), which is the
    truncated form the wire protocol uses."""
    return hashlib.sha256(der).hexdigest()


def placeholder_fingerprints() -> dict[str, str]:
    """Fingerprint -> human note, for every root known to be a THROWAWAY
    PLACEHOLDER whose private half was discarded at generation time.

    This list is why --require-real can exist. Without it, --check is happy as
    long as the PEM and the patch agree, which they do perfectly well for a
    placeholder -- so the only thing standing between a placeholder and a signed,
    notarized, published build would be a human remembering to flip a GN arg.
    """
    return {
        "PLACEHOLDER_RELEASE_FP": "release primary placeholder (pre-KMS ceremony)",
        "PLACEHOLDER_RECOVERY_FP": "release recovery placeholder (pre-offline ceremony)",
        "PLACEHOLDER_STAGING_FP": "staging placeholder (pre-DKMS export)",
    }
```

**注意**:`PLACEHOLDER_*_FP` 三个字面量必须替换为 Step 1 生成的真实指纹。用下面命令取值后回填:

```bash
uv run python -c "
import scripts.gen_policy_verification_key as g
for n in ('release-policy-root','release-policy-recovery-root','staging-policy-root'):
    print(n, g.der_fingerprint(g.load_pub_der(g.REPO/'keys'/(n+'.pub.pem'))))
"
```

patch 解析改为显式映射 + 同分支校验:

```python
def patch_key(spec: RootSpec, patch_path: Path = PATCH) -> bytes:
    """The DER bytes baked for `spec` in the patch text."""
    text = patch_path.read_text()
    m = re.search(rf"{spec.symbol}\[\] = \{{(.*?)\}};", text, re.S)
    if not m:
        raise SystemExit(f"{spec.symbol} block not found in {patch_path}")
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9a-fA-F]{2})", m.group(1)))


def patch_hash_for(spec: RootSpec, patch_path: Path = PATCH) -> str:
    """The kPolicyVerificationKeyHash that belongs to `spec`'s preprocessor
    branch: the first one after the key block, having first confirmed no branch
    delimiter sits in between. The positional search alone would silently pick
    up a neighbouring branch's hash if the block order ever changed."""
    text = patch_path.read_text()
    m = re.search(rf"{spec.symbol}\[\] = \{{.*?\}};", text, re.S)
    if not m:
        raise SystemExit(f"{spec.symbol} block not found in {patch_path}")
    rest = text[m.end():]
    hm = re.search(r'kPolicyVerificationKeyHash\[\] = "([^"]+)"', rest)
    if not hm:
        raise SystemExit(f"no kPolicyVerificationKeyHash after {spec.symbol}")
    if re.search(r"^\+?#(elif|else|endif)\b", rest[:hm.start()], re.M):
        raise SystemExit(
            f"{spec.symbol}'s hash lookup crossed a preprocessor branch — the "
            f"patch layout changed; fix patch_hash_for()")
    return hm.group(1)
```

`run_check` 与 `main`:

```python
def run_check(env: str | None = None, require_real: bool = False) -> None:
    envs = [env] if env else list(ENVS)
    problems: list[str] = []
    for e in envs:
        for spec in ENVS[e]:
            der = load_pub_der(REPO / "keys" / spec.pem)
            if patch_key(spec) != der:
                problems.append(f"{e}: {spec.symbol} bytes != {spec.pem}")
            if spec.derives_hash and patch_hash_for(spec) != key_hash(der):
                problems.append(
                    f"{e}: kPolicyVerificationKeyHash != hash of {spec.pem}")
            if require_real:
                fp = der_fingerprint(der)
                note = placeholder_fingerprints().get(fp)
                if note:
                    problems.append(
                        f"{e}: {spec.pem} is still a PLACEHOLDER ({note}); "
                        f"vendor the real KMS public key before claiming it")
    if problems:
        raise SystemExit(
            "policy verification key drift:\n  - " + "\n  - ".join(problems)
            + "\nRegenerate with scripts/gen_policy_verification_key.py.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify patch matches keys")
    ap.add_argument("--env", choices=sorted(ENVS), help="limit to one environment")
    ap.add_argument("--require-real", action="store_true",
                    help="additionally fail if any checked root is a known placeholder")
    args = ap.parse_args()
    if args.check or args.require_real:
        run_check(env=args.env, require_real=args.require_real)
        scope = args.env or "all environments"
        print(f"policy verification keys OK ({scope})")
        return
    for e in ([args.env] if args.env else list(ENVS)):
        print(f"// --- {e} ---")
        for spec in ENVS[e]:
            der = load_pub_der(REPO / "keys" / spec.pem)
            print(f"const uint8_t {spec.symbol}[] = {{")
            print(c_array_lines(der))
            if spec.derives_hash:
                print(f'const char kPolicyVerificationKeyHash[] = "{key_hash(der)}";')
```

需要 `import hashlib`(已有)与 `from dataclasses import dataclass`(新增)。

- [ ] **Step 5: 运行测试(此时 patch 尚无 staging/recovery 符号,预期部分失败)**

```bash
cd "$W" && uv run pytest scripts/tests/test_gen_policy_verification_key.py -q 2>&1 | tail -5
```

Expected:`ENVS`/指纹相关用例通过;`patch_key` 相关用例因 patch 里还没有 `kStagingPolicyKey` / `kReleasePolicyRecoveryKey` 而失败——**这是预期的**,Task 6 补上后转绿。为保持"每个任务结束全绿"的纪律,本任务先用 `pytest.mark.xfail(reason=...)` 标注这两条与 patch 内容耦合的用例,Task 6 结束时移除标注。

> **例外说明**:CLAUDE.md 禁止跳过测试。这里用的是 `xfail`(预期失败,仍然执行且一旦通过会报 XPASS),不是 skip,且在同一 Phase 内的下一个任务即移除。若 Task 6 未在同一分支完成,该标注即为未完成信号。

- [ ] **Step 6: 提交**

```bash
W=/Users/liulichao/workspace/teleport/.worktrees/aliyun-first-deploy
git -C "$W" add keys/ scripts/
git -C "$W" commit -m "feat(keys): vendor per-env placeholder roots and parameterize the key generator

--check only ever proved that the PEM and the patch agree, which a placeholder
satisfies perfectly. --require-real adds a fingerprint list of the roots whose
private halves were discarded at generation, so 'this is a real KMS key' becomes
machine-checkable instead of resting on someone remembering to flip a GN arg.

The hash lookup also stops relying on position alone: it now refuses to cross a
preprocessor branch, so a future reordering fails loudly instead of silently
pairing a key with a neighbouring branch's hash."
```

---

### Task 6: 四把根进 patch + `GetPolicyVerificationKeys()` / `IsKnownVerificationKey()`

**Files:**
- Modify: `patches/components/policy/core/common/cloud/cloud_policy_constants.cc.patch`
- Create: `patches/components/policy/core/common/cloud/cloud_policy_constants.h.patch`
- Modify: `scripts/tests/test_gen_policy_verification_key.py`(移除 Task 5 的 xfail)

**Interfaces:**
- Produces: `std::vector<std::string> policy::GetPolicyVerificationKeys()`、`bool policy::IsKnownVerificationKey(std::string_view key)`,均带 `POLICY_EXPORT`。Task 7/8/9 消费。

- [ ] **Step 1: 应用现有 patch,取得可编辑的检出树**

```bash
W=/Users/liulichao/workspace/teleport/.worktrees/aliyun-first-deploy
cd "$W" && unset TELEPORT_CHROMIUM_DIR && python scripts/apply_patches.py 2>&1 | tail -2
```

- [ ] **Step 2: 在检出树中把 `cloud_policy_constants.cc` 改为三分支四根**

`CR=~/workspace/chromium/151.0.7922/src`,编辑 `$CR/components/policy/core/common/cloud/cloud_policy_constants.cc`,把现有的 `#if BUILDFLAG(TELEPORT_ENV_IS_RELEASE) ... #else ... #endif` 密钥块整体替换为下述结构(密钥字节由 `gen_policy_verification_key.py` 生成,勿手抄):

```cpp
#if BUILDFLAG(TELEPORT_ENV_IS_RELEASE)
const uint8_t kReleasePolicyKey[] = { /* generated */ };
// Dormant recovery root: baked from the first release build because baking a
// public key is irreversible — a client shipped without it can never be taught
// to trust it. It does NOT make a rotation seamless on its own (the server also
// has to re-endorse existing tenants, see the design spec 4.3), and it does not
// revoke the primary root: a client trusts every key in this set equally, so
// removing a compromised root still requires shipping a new client.
const uint8_t kReleasePolicyRecoveryKey[] = { /* generated */ };
const char kPolicyVerificationKeyHash[] = "1:...";   // primary only
#elif BUILDFLAG(TELEPORT_ENV_IS_STAGING)
const uint8_t kStagingPolicyKey[] = { /* generated */ };
const char kPolicyVerificationKeyHash[] = "1:...";
#else
const uint8_t kDevPolicyKey[] = { /* generated */ };
const char kPolicyVerificationKeyHash[] = "1:...";
#endif
```

访问器:

```cpp
std::vector<std::string> GetPolicyVerificationKeys() {
  const auto as_string = [](const uint8_t* p, size_t n) {
    return std::string(reinterpret_cast<const char*>(p), n);
  };
#if BUILDFLAG(TELEPORT_ENV_IS_RELEASE)
  return {as_string(kReleasePolicyKey, sizeof(kReleasePolicyKey)),
          as_string(kReleasePolicyRecoveryKey, sizeof(kReleasePolicyRecoveryKey))};
#elif BUILDFLAG(TELEPORT_ENV_IS_STAGING)
  return {as_string(kStagingPolicyKey, sizeof(kStagingPolicyKey))};
#else
  return {as_string(kDevPolicyKey, sizeof(kDevPolicyKey))};
#endif
}

// The primary root — what kPolicyVerificationKeyHash is derived from and what
// gets recorded on disk alongside a cached signing key.
std::string GetPolicyVerificationKey() {
  return GetPolicyVerificationKeys().front();
}

bool IsKnownVerificationKey(std::string_view key) {
  for (const std::string& k : GetPolicyVerificationKeys()) {
    if (k == key) {
      return true;
    }
  }
  return false;
}
```

生成密钥字节:

```bash
cd "$W" && uv run python scripts/gen_policy_verification_key.py --env release
uv run python scripts/gen_policy_verification_key.py --env staging
uv run python scripts/gen_policy_verification_key.py --env dev
```

- [ ] **Step 3: 新建 `cloud_policy_constants.h` 的 patch**

在 `$CR/components/policy/core/common/cloud/cloud_policy_constants.h` 的 `GetPolicyVerificationKey()` 声明处加入:

```cpp
// Public half of the verification key that is used to verify that policy
// signing keys are originating from DM server. This is the PRIMARY root; see
// GetPolicyVerificationKeys() for the full trusted set.
POLICY_EXPORT std::string GetPolicyVerificationKey();

// Every root this build trusts, primary first. release carries a dormant
// recovery root as a second element; dev and staging carry one element. A
// signature is accepted when ANY element verifies it.
POLICY_EXPORT std::vector<std::string> GetPolicyVerificationKeys();

// Whether `key` (a DER SubjectPublicKeyInfo) is one of the trusted roots.
POLICY_EXPORT bool IsKnownVerificationKey(std::string_view key);
```

需要 `#include <string_view>` 与 `#include <vector>`。

> 顺带给 `GetPolicyVerificationKey()` 补上 `POLICY_EXPORT`(上游遗漏)。它此前已被 `chrome/browser` 侧的 overlay 代码在 component build 下调用且工作正常,但依赖的是同 component 内联可见性,不是契约。

- [ ] **Step 4: 生成两个 patch 并验证幂等**

```bash
CR=~/workspace/chromium/151.0.7922/src
for f in cloud_policy_constants.cc cloud_policy_constants.h; do
  git -C "$CR" diff -- "components/policy/core/common/cloud/$f" \
    > "$W/patches/components/policy/core/common/cloud/$f.patch"
done
cd "$W" && python scripts/apply_patches.py 2>&1 | tail -2
python scripts/apply_patches.py 2>&1 | tail -1
```

Expected:两次均 `overlay applied.`。

- [ ] **Step 5: 移除 Task 5 的 xfail 标注,跑全量 pytest**

```bash
cd "$W" && uv run pytest -q 2>&1 | tail -3
```

Expected:全绿,无 XPASS。

- [ ] **Step 6: 构建验证(dev 档只有一把根,集合退化为单元素)**

```bash
cd ~/workspace/chromium/151.0.7922/src && autoninja -C out/mac/arm64/dev teleport_unittests 2>&1 | tail -2
```

- [ ] **Step 7: 提交**

```bash
git -C "$W" add patches/ scripts/
git -C "$W" commit -m "feat(policy): bake a per-environment set of verification roots

GetPolicyVerificationKeys() returns every root this build trusts and
IsKnownVerificationKey() answers set membership; GetPolicyVerificationKey()
keeps returning the primary, which is what derives the wire hash and what gets
recorded next to a cached signing key.

release bakes a dormant recovery root alongside the primary. Baking a public key
is irreversible in the direction that matters -- a client shipped without one can
never be taught to trust it -- so it goes in from the first release build even
though the ceremony that gives it a real value has not happened yet."
```

---

### Task 7: validator 的 4 处验签改为集合遍历

**Files:**
- Create: `patches/components/policy/core/common/cloud/cloud_policy_validator.h.patch`
- Create: `patches/components/policy/core/common/cloud/cloud_policy_validator.cc.patch`

**Interfaces:**
- Consumes: Task 6 的 `GetPolicyVerificationKeys()`
- Produces: `CloudPolicyValidatorBase::verification_keys_`(`std::vector<std::string>`)、静态方法 `GetCurrentPolicyVerificationKeys()`

**为什么两个函数都必须改**:`CheckNewPublicKeyVerificationSignature()` 只覆盖首次下发;`CheckCachedKey()` 经 `user_cloud_policy_store.cc:326` 在**每次启动**加载磁盘缓存时运行。只改前者,恢复根启用后首次 fetch 能过,但下次启动就会以 `VALIDATION_BAD_KEY_VERIFICATION_SIGNATURE` 丢弃缓存策略——恰好摧毁双根存在的理由。

- [ ] **Step 1: 改 header**

`$CR/components/policy/core/common/cloud/cloud_policy_validator.h`:
- `static std::optional<std::string> GetCurrentPolicyVerificationKey();` → `static std::vector<std::string> GetCurrentPolicyVerificationKeys();`
- `std::optional<std::string> verification_key_;` → `std::vector<std::string> verification_keys_;`(注释说明:空表示 ChromeOS 测试镜像下的显式禁用)

- [ ] **Step 2: 改构造与静态方法(`.cc` 约 305-331 行)**

```cpp
      verification_keys_(GetCurrentPolicyVerificationKeys()),
```

```cpp
// static
std::vector<std::string>
CloudPolicyValidatorBase::GetCurrentPolicyVerificationKeys() {
  const base::CommandLine* command_line =
      base::CommandLine::ForCurrentProcess();
#if BUILDFLAG(IS_CHROMEOS)
  if (command_line->HasSwitch(switches::kDisablePolicyKeyVerification)) {
    // Empty set = verification disabled (ChromeOS test images only);
    // GetPolicyVerificationKeys() is otherwise never empty.
    return {};
  }
#endif  // BUILDFLAG(IS_CHROMEOS)
  if (command_line->HasSwitch(switches::kPolicyVerificationKey)) {
    CHECK_IS_TEST();
    std::string decoded_key;
    CHECK(base::Base64Decode(
        command_line->GetSwitchValueASCII(switches::kPolicyVerificationKey),
        &decoded_key));
    return {decoded_key};
  }
  return GetPolicyVerificationKeys();
}
```

保留原 `#if BUILDFLAG(IS_CHROMEOS)` 分支的实际条件与注释语义(照抄现有代码,勿臆造 switch 名——先 `sed -n 305,332p` 读准)。

- [ ] **Step 3: `CheckNewPublicKeyVerificationSignature()` 改遍历**

```cpp
bool CloudPolicyValidatorBase::CheckNewPublicKeyVerificationSignature() {
#if BUILDFLAG(IS_CHROMEOS)
  // Skip verification if the key set is empty (disabled via command line).
  if (verification_keys_.empty()) {
    return true;
  }
#endif  // BUILDFLAG(IS_CHROMEOS)

  if (policy_->has_new_public_key_verification_data() &&
      policy_->has_new_public_key_verification_data_signature() &&
      CheckPublicKeyVerificationData(
          policy_->new_public_key_verification_data(),
          policy_->new_public_key())) {
    for (const std::string& key : verification_keys_) {
      if (VerifySignature(policy_->new_public_key_verification_data(), key,
                          policy_->new_public_key_verification_data_signature(),
                          em::PolicyFetchRequest::SHA256_RSA)) {
        UMA_HISTOGRAM_ENUMERATION(kMetricKeySignatureVerification,
                                  MetricKeySignatureVerification::kSuccess);
        VLOG_POLICY(1, POLICY_FETCHING)
            << PolicyTypeLogPrefix(policy_type_, settings_entity_id_)
            << "Signature verification succeeded";
        return true;
      }
    }
  }
  // ... 原有的失败日志与 deprecated 回退保持结构,回退处同样遍历 ...
}
```

deprecated 回退处(原 `.cc:487` 的 `CheckVerificationKeySignatureDeprecated(policy_->new_public_key(), verification_key_.value(), ...)`)同样改为遍历集合,任一通过即通过。

- [ ] **Step 4: `CheckCachedKey()` 改遍历(两处)**

`.cc:634` 的空检查改 `verification_keys_.empty()`;`:639` 的新式验签与 `:657` 的 deprecated 回退各自遍历集合。

- [ ] **Step 5: 生成 patch 并验证幂等 + 构建**

```bash
CR=~/workspace/chromium/151.0.7922/src
for f in cloud_policy_validator.h cloud_policy_validator.cc; do
  git -C "$CR" diff -- "components/policy/core/common/cloud/$f" \
    > "$W/patches/components/policy/core/common/cloud/$f.patch"
done
cd "$W" && python scripts/apply_patches.py 2>&1 | tail -1
cd ~/workspace/chromium/151.0.7922/src && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -2
```

Expected:构建成功。dev 档集合是单元素,行为与改造前等价。

- [ ] **Step 6: 提交**

```bash
git -C "$W" commit -am "feat(policy): verify policy keys against the whole trusted root set

Both verification paths iterate now, not just the first-fetch one. CheckCachedKey
runs on every startup via UserCloudPolicyStore, so leaving it single-key would
have meant a recovery-root rotation survives exactly one session: the first fetch
verifies, and the next launch rejects the cached key it just wrote. That is the
precise failure the second root exists to prevent."
```

---

### Task 8: policy store 的 key-rotation 判定改为集合成员判定

**Files:**
- Create: `patches/components/policy/core/common/cloud/user_cloud_policy_store.cc.patch`
- Create: `patches/components/policy/core/common/cloud/machine_level_user_cloud_policy_store.cc.patch`

**Interfaces:**
- Consumes: Task 6 的 `IsKnownVerificationKey()`

**设计取舍(与 spec §4.2 的"记录实际验过的那把"等价但更简单)**:写盘继续记录**主根**(`GetPolicyVerificationKey()`),读盘的轮换判定从"是否等于主根"改为"**是否属于当前信任集合**"。效果相同而无需让 store 知道 validator 用了哪把:
- 恢复根启用、磁盘记录仍是主根 → 主根仍在集合内 → **不触发**轮换(避免全网重拉风暴);
- 主根将来被移除、磁盘记录的是它 → 不在集合内 → **触发**轮换(正确)。

- [ ] **Step 1: 改 `user_cloud_policy_store.cc:262-264`**

```cpp
      if (key && (!key->has_verification_key() ||
                  !IsKnownVerificationKey(key->verification_key()))) {
        // The cached key was endorsed by a root this build no longer trusts, so
        // we're doing a key rotation - make sure we request a new key from the
        // server on our next fetch. Membership, not equality: a build that
        // trusts both a primary and a recovery root must not treat a cache
        // endorsed by either one as stale, or every launch would re-fetch.
        doing_key_rotation = true;
```

- [ ] **Step 2: `machine_level_user_cloud_policy_store.cc:238` 写盘保持不变**

确认该处仍是 `GetPolicyVerificationKey()`(主根),仅在有等价轮换判定时才需改动。**读一遍上下文确认它是否也有轮换判定**;若有,按 Step 1 同样处理;若无,本文件不生成 patch,并在提交信息中说明。

- [ ] **Step 3: 生成 patch、验证幂等、构建**

```bash
CR=~/workspace/chromium/151.0.7922/src
git -C "$CR" diff -- components/policy/core/common/cloud/user_cloud_policy_store.cc \
  > "$W/patches/components/policy/core/common/cloud/user_cloud_policy_store.cc.patch"
cd "$W" && python scripts/apply_patches.py 2>&1 | tail -1
cd ~/workspace/chromium/151.0.7922/src && autoninja -C out/mac/arm64/dev chrome 2>&1 | tail -2
```

- [ ] **Step 4: 提交**

---

### Task 9: overlay 两个 server-identity 调用点 + verdict 聚合 + 单测

**Files:**
- Modify: `src/common/teleport_enroll_logic.h`
- Modify: `src/common/teleport_enroll_logic.cc`
- Modify: `src/browser/teleport_deployment_level4.cc`
- Modify: `src/browser/webui/teleport_enroll_ui.cc`
- Modify: `src/common/teleport_enroll_logic_unittest.cc`

**Interfaces:**
- Produces: `ServerIdentityVerdict teleport::VerifyAgainstRootSet(base::span<const uint8_t> signed_bytes, base::span<const uint8_t> signature, const std::vector<std::string>& root_keys, std::string_view candidate_domain, base::Time now)`
- **不改** `src/common/teleport_server_identity.{h,cc}`:它是刻意保持纯净、不依赖 `//components/policy` 的 leaf(根密钥作参数注入),集合遍历属于调用侧策略。

**verdict 聚合规则(spec §4.2)**:`VerifyServerIdentityDetailed` 返回**第一个**失败原因,且签名检查排在最前。因此朴素的"取最后一次 verdict"会把"恢复根签名正确但已过期"报成 `kBadSignature`,把排障引向错误方向——而验签失败的历史表现正是静默卡死(2026-07-04 事故)。规则:

1. 任一根返回 `kValid` → `kValid`;
2. 否则,若存在**非 `kBadSignature`** 的 verdict(签名过了、字段没过)→ 返回该 verdict;
3. 全部 `kBadSignature` → `kBadSignature`。

- [ ] **Step 1: 写失败的测试**

追加到 `src/common/teleport_enroll_logic_unittest.cc`(注意必须写在 `namespace teleport` 内部):

```cpp
// Root-set aggregation: a blob signed by the SECOND root must verify, and the
// reported reason must come from the root whose signature actually matched.
TEST(TeleportVerifyAgainstRootSetTest, AcceptsSignatureFromSecondRoot) {
  // fixture: blob signed by root B, set = {A, B}
  EXPECT_EQ(VerifyAgainstRootSet(kSignedByB, kSigB, {kRootA, kRootB},
                                 kFixtureDomain, kFixtureNow),
            ServerIdentityVerdict::kValid);
}

TEST(TeleportVerifyAgainstRootSetTest, RejectsWhenNoRootMatches) {
  EXPECT_EQ(VerifyAgainstRootSet(kSignedByB, kSigB, {kRootA},
                                 kFixtureDomain, kFixtureNow),
            ServerIdentityVerdict::kBadSignature);
}

// The aggregation rule that matters: an expired blob signed by the recovery
// root must report kExpired, not kBadSignature. Reporting the signature as bad
// would send an operator hunting a key problem that does not exist.
TEST(TeleportVerifyAgainstRootSetTest, ReportsFieldFailureNotSignatureFailure) {
  EXPECT_EQ(VerifyAgainstRootSet(kSignedByB, kSigB, {kRootA, kRootB},
                                 kFixtureDomain, kFixtureWayLater),
            ServerIdentityVerdict::kExpired);
}

TEST(TeleportVerifyAgainstRootSetTest, EmptySetRejects) {
  EXPECT_EQ(VerifyAgainstRootSet(kSignedByB, kSigB, {}, kFixtureDomain,
                                 kFixtureNow),
            ServerIdentityVerdict::kBadSignature);
}
```

**fixture 来源**:复用 `teleport_server_identity_joint_unittest.cc` 已有的 dev 根 fixture 作为 `kRootB`/`kSignedByB`/`kSigB`;`kRootA` 用 `keys/staging-policy-root.pub.pem` 的 DER(Task 5 已 vendored,它不会验过 dev 根签的 blob,正是需要的"不匹配的根")。先读那个 joint 测试确认常量名与生成方式。

- [ ] **Step 2: 运行确认失败** → `use of undeclared identifier 'VerifyAgainstRootSet'`

- [ ] **Step 3: 实现聚合函数**(`teleport_enroll_logic.{h,cc}`)

```cpp
ServerIdentityVerdict VerifyAgainstRootSet(
    base::span<const uint8_t> signed_bytes,
    base::span<const uint8_t> signature,
    const std::vector<std::string>& root_keys,
    std::string_view candidate_domain,
    base::Time now) {
  ServerIdentityVerdict best = ServerIdentityVerdict::kBadSignature;
  for (const std::string& key : root_keys) {
    ServerIdentityVerdict v = VerifyServerIdentityDetailed(
        signed_bytes, signature, base::as_byte_span(key), candidate_domain, now);
    if (v == ServerIdentityVerdict::kValid) {
      return v;
    }
    // A non-signature verdict means THIS root's signature checked out and a
    // later field did not — strictly more informative than another root's
    // kBadSignature, and the reason an operator actually needs.
    if (v != ServerIdentityVerdict::kBadSignature) {
      best = v;
    }
  }
  return best;
}
```

- [ ] **Step 4: 两个调用点改用它**

`teleport_deployment_level4.cc:63-67`、`teleport_enroll_ui.cc:223-226`:把 `policy::GetPolicyVerificationKey()` 换成 `policy::GetPolicyVerificationKeys()`,并调用 `VerifyAgainstRootSet`(enroll 侧经 `VerifyFetchedIdentity` 的集合重载)。

- [ ] **Step 5: 测试与构建全绿** → **Step 6: 提交**

---

## Phase 2 完成定义

1. 四把根(dev 1 / staging 1 / release 2)全部 vendored 并烤进 patch;`--check` 覆盖全部,`--require-real` 对占位档 fail-closed。
2. spec §4.2 表中**全部 6 个验签点**改造完毕。
3. verdict 聚合按规则实现,"恢复根签名 + 已过期"报 `kExpired` 而非 `kBadSignature`(有单测钉死)。
4. key-rotation 判定改为集合成员判定,恢复根启用不触发全量重拉。
5. `uv run pytest` 全绿(无 skip/xfail 残留);`teleport_unittests` 全绿;`apply_patches.py` 幂等;dev chrome 构建通过。

**不属于 Phase 2**:渠道注册表与发布链、EdDSA 分环境、`IsCommandLineSwitchSupported()` 的 release 消除(全部 Phase 3)。
