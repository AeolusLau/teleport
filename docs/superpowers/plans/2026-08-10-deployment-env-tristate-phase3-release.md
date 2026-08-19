# 部署环境三态化 Phase 3:渠道、发布链与后门消除 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 staging 成为一个可构建、可签名、可发布、且与 release 产物身份完全隔离的渠道;把发布守卫从"文本比对"升级为"查询生效值";补齐 EdDSA 分环境与 tag 命名空间;并把 release 档的命令行后门做编译期消除。

**Architecture:** `gn args --list --short` 成为构建配置的唯一事实源——文本正则看不见 `import()` 链和命令行覆盖,而正常 `gn gen` 产出的 args.gn 恰恰只有一行 import。`teleport_policy_key_placeholder_ack` 经 Info.plist 的 `TeleportUnpublishable` 传导到 `--distribute` 的硬拒,使"可构建但不可发布"成为具名且自我解除的状态。tag 按渠道命名空间化,staging 因此恢复"已发布"检测能力而不与 release 撞名。

**Tech Stack:** Python 3.13 + pytest (uv) / GN / C++17 (Chromium M151) / Sparkle generate_appcast / ossutil

## Global Constraints

- **spec 权威**:`docs/superpowers/specs/2026-08-10-deployment-env-tristate-design.md`(v2)§4.4、§4.5、§4.6、§6。
- **git 命令一律 `git -C <worktree>`**,不依赖 shell cwd(cwd 会被重置到主 worktree)。
- **修改已有 patch 的标准工作流**(禁止手改 hunk):`apply_patches.py` → 编辑 `$CR/<file>` → `git -C "$CR" diff -- <path> > patches/<path>.patch` → 再跑 `apply_patches.py` 验证幂等。`CR=~/workspace/chromium/151.0.7922/src`。
- **`gn args --list` 未知 arg 时退出码仍为 0**,只在 stdout 输出 `ERROR Unknown build argument.`。任何解析都必须校验 `name = value` 形状,不得依赖退出码。
- 每个任务结束时工作树干净,`uv run pytest` 与 `teleport_unittests` 全绿。
- 涉及真实签名/公证/上传的步骤**本计划一律不执行**(需要凭据与网络);它们由 §6-c 的演练在人工在场时进行。

---

### Task 10: `staging` 渠道名映射到 `Channel::CANARY`

**Files:** Modify `src/common/teleport_channel.cc`、`src/common/teleport_channel_unittest.cc`

**为什么必须做**:`ChannelFromName` 目前只认 canary/beta/stable,其余落 `UNKNOWN`。而 `_package.py` 会把 channel 名原样写进 Info.plist 的 `TeleportChannel` 键,于是 staging 包会产出 `is_official_build=true` + `Channel::UNKNOWN` 这个前所未有的组合:上游一批 `channel != STABLE` 的门在 staging 下与 release 的任何渠道都不同,且既有 channel-alignment 特性(修升级角标时序)在 staging 上失效——而升级角标正是 staging 要演练的 Sparkle 链路的可见终点。

- [ ] **Step 1: 写失败的测试**

```cpp
// staging is an ENVIRONMENT that borrows a channel slot, so it must report a
// real channel rather than falling through to UNKNOWN. CANARY is the honest
// answer: staging is a pre-release build that should take every non-stable code
// path release's canary takes, so the rehearsal exercises the same branches.
TEST(TeleportChannelTest, MapsStagingToCanary) {
  EXPECT_EQ(version_info::Channel::CANARY, ChannelFromName("staging"));
}
```

- [ ] **Step 2: 运行确认失败**(`UNKNOWN != CANARY`)
- [ ] **Step 3: 实现** —— `ChannelFromName` 增加 `if (name == "staging") return version_info::Channel::CANARY;`,并加注释说明它是环境借用渠道槽位。
- [ ] **Step 4: 构建 + 跑 `teleport_unittests --gtest_filter='TeleportChannel*'`,全绿**
- [ ] **Step 5: 提交**

---

### Task 11: release 档的命令行后门编译期消除

**Files:** Modify `patches/chrome/browser/policy/chrome_browser_policy_connector.cc.patch`;新增 `patches/components/policy/core/common/cloud/cloud_policy_validator.cc.patch` 的一处改动(该 patch 已存在,扩档)

**修法必须打在根因层**:v1 曾提议在 `GetUrlOverride` 内消除,但它是泛型的(`const char* flag`),关不掉单个 switch;而同一个 `IsCommandLineSwitchSupported()` 另有三个消费者(`binary_upload_request.cc:438`、`user_cloud_signin_restriction_policy_fetcher.cc:252`、`chrome_enterprise_url_lookup_service_factory.cc:129`)。在该函数上做 release 档 `return false` 是单点、根因、且覆盖全部同源开关。

- [ ] **Step 1: `chrome_browser_policy_connector.cc` 的 `IsCommandLineSwitchSupported()` 加 release 档短路**

```cpp
bool ChromeBrowserPolicyConnector::IsCommandLineSwitchSupported() const {
#if BUILDFLAG(TELEPORT_ENV_IS_RELEASE)
  // Teleport: release builds accept no enterprise-endpoint overrides at all.
  // This is the single gate for all of them -- --device-management-url,
  // --realtime-reporting-url, --encrypted-reporting-url,
  // --cloud-binary-upload-service-url and --secure-connect-api-url all consult
  // it -- so closing it here closes the family, not one member.
  //
  // Defensive rather than corrective: our own connector patch already routes DM
  // endpoints around GetUrlOverride entirely, so --device-management-url is
  // already inert on desktop. The point is that a future upstream refactor that
  // reconnects that path must not silently re-open the door.
  return false;
#else
  ...原有实现...
#endif
}
```

需要在该文件 include `teleport/teleport_policy_buildflags.h`,并确认 `chrome/browser/policy/BUILD.gn` 已 dep `//teleport:teleport_policy_buildflags`(若未 dep,新增 `patches/chrome/browser/policy/BUILD.gn.patch`)。

- [ ] **Step 2: `--policy-verification-key` 在 release 档编译掉**

`cloud_policy_validator.cc` 的 `GetCurrentPolicyVerificationKeys()` 中,把读取该 switch 的整段包进 `#if !BUILDFLAG(TELEPORT_ENV_IS_RELEASE)`。它前置 `CHECK_IS_TEST()`,而出货二进制里 `g_this_is_a_test` 恒 false,故传入即 `CHECK` 失败崩溃——是一行命令的本地 DoS。

- [ ] **Step 3: 生成 patch、验证幂等、dev 构建通过**(dev 档行为不变)
- [ ] **Step 4: 提交**

---

### Task 12: 渠道注册表新增 staging + 守卫改查生效值

**Files:** Modify `scripts/_build.py`、`scripts/tests/test_build.py`

**为什么必须改判定轴**:现有守卫按文本正则匹配 args.gn 中的赋值行,而正常 `gn gen` 产出的 args.gn **只有一行 `import(...)`** ⇒ `actual is None` 早退、零保护。它要防的"配置不符的构建走到签名→公证→上传→打 tag"因此从未真正被拦住过。

- [ ] **Step 1: 写失败的测试**

```python
def test_effective_gn_arg_parses_a_string_value(monkeypatch):
    monkeypatch.setattr(_build.subprocess, "run", lambda *a, **k: _Done(
        'teleport_deployment_env = "staging"\n'))
    assert _build.effective_gn_arg("out/x", "teleport_deployment_env") == "staging"


def test_effective_gn_arg_parses_a_bool_value(monkeypatch):
    monkeypatch.setattr(_build.subprocess, "run", lambda *a, **k: _Done(
        "teleport_policy_key_placeholder_ack = true\n"))
    assert _build.effective_gn_arg(
        "out/x", "teleport_policy_key_placeholder_ack") == "true"


def test_effective_gn_arg_treats_unknown_arg_as_absent(monkeypatch):
    """gn exits 0 and prints an ERROR banner for an unknown arg, so the parser
    must validate the shape rather than trust the exit code."""
    monkeypatch.setattr(_build.subprocess, "run", lambda *a, **k: _Done(
        "ERROR Unknown build argument.\n"))
    assert _build.effective_gn_arg("out/x", "no_such_arg") is None


def test_guard_catches_import_only_args_gn_pointing_at_another_env(
        tmp_path, monkeypatch):
    """The case the old text-matching guard could not see at all: args.gn
    contains only an import line, and that template is the wrong environment."""
    (tmp_path / "out/x").mkdir(parents=True)
    (tmp_path / "out/x/args.gn").write_text(
        'import("//teleport/gn/args/staging.mac.gn")\n')
    monkeypatch.setattr(_build, "chromium_src", lambda: tmp_path)
    monkeypatch.setattr(_build, "effective_gn_arg",
                        lambda out, arg: "staging" if "env" in arg else "false")
    with pytest.raises(SystemExit, match="teleport_deployment_env"):
        _build.assert_release_endpoints_consistent(
            "out/x", _build.resolve_channel("canary"), distributing=True)
```

`_Done` 是一个最小的 `subprocess.CompletedProcess` 替身:`class _Done: def __init__(self, out): self.stdout = out; self.returncode = 0`。

- [ ] **Step 2: 实现 `effective_gn_arg`**

```python
_GN_ARG_VALUE_RE = re.compile(r'^\s*(\w+)\s*=\s*"?([^"\n]*)"?\s*$')


def effective_gn_arg(out: str, arg: str) -> str | None:
    """The value GN actually resolves for `arg` in <out>, or None if unset.

    Queries gn rather than reading args.gn as text. Text cannot see through an
    import() chain, and a normal `gn gen` writes args.gn containing exactly one
    import line -- so a text matcher finds nothing to compare and skips the
    check entirely, which is how the previous guard came to protect nothing.

    gn exits 0 even for an unknown argument (it prints an ERROR banner to
    stdout), so the return shape is validated instead of the exit code.
    """
    r = subprocess.run(
        [str(gn_bin()), "args", str(chromium_src() / out), f"--list={arg}",
         "--short"],
        capture_output=True, text=True, check=False,
    )
    m = _GN_ARG_VALUE_RE.match(r.stdout.strip())
    if not m or m.group(1) != arg:
        return None
    return m.group(2)
```

`gn_bin()` 返回 `chromium_src() / "buildtools/mac/gn"`。

- [ ] **Step 3: 守卫改用它**

`assert_release_endpoints_consistent` 中 `actual` 改为 `effective_gn_arg(out, "teleport_deployment_env")`,`expected` 仍从模板文本取(模板是我们自己的文件,一定含显式赋值)。`actual is None` 的语义从"没有覆盖,信任"变为"gn 查不到,异常"——应视为不一致并报错。

- [ ] **Step 4: `CHANNELS` 新增 staging**

```python
    "staging": Channel(
        "staging", "out/mac/arm64/staging", True,
        ("chrome", "chrome/installer/mac"), "staging.mac.gn",
    ),
```

- [ ] **Step 5: 全量 pytest 绿 → Step 6: 提交**

---

### Task 13: 占位密钥构建标记为不可发布

**Files:** Modify `scripts/_package.py`、`scripts/package.py`、`scripts/tests/test_package_cli.py`

- [ ] **Step 1: 写失败的测试**

```python
def test_distribute_refuses_a_placeholder_ack_build(tmp_path, monkeypatch):
    """A build made through the placeholder escape hatch must never publish.
    The hatch exists so that exercising the pipeline is explicit and
    self-disarming -- if --distribute could still run, it would just be the
    TD-026 override with extra steps."""
    monkeypatch.setattr(package._build, "effective_gn_arg",
                        lambda out, arg: "true" if "placeholder_ack" in arg else "release")
    with pytest.raises(SystemExit, match="TeleportUnpublishable|placeholder"):
        package.main(["--channel", "canary", "--distribute"])
```

- [ ] **Step 2: 打包期写入 Info.plist 标记**

`_package.py` 在 stamp Sparkle 键的同处,查询 `effective_gn_arg(out, "teleport_policy_key_placeholder_ack")`;为 `"true"` 时写入 `TeleportUnpublishable = "YES"`。

- [ ] **Step 3: `--distribute` 前置硬拒**

`package.py` 在 `assert_on_main()` 之前查询同一个 arg,为 `"true"` 时 `SystemExit`,消息说明:该构建烤的是占位根,只能用于验证流水线机制,不可发布。

- [ ] **Step 4: pytest 绿 → Step 5: 提交**

---

### Task 14: Sparkle EdDSA 分环境

**Files:** Modify `scripts/_config.py`、`scripts/_publish.py`、`scripts/release_config.local.toml.example`、`scripts/tests/test_config.py`(如无则新建)

**为什么**:F6 的隔离只覆盖策略链。升级链是第二条独立信任链,当前所有渠道共用一把 EdDSA(`2026-05-26` spec:149),而 `generate_appcast` 不传 `--account`,恒用 keychain 中唯一那把。于是 staging 发布机——按设计"故意更弱"——持有 release 客户端接受的升级签名能力,而升级链投递的是任意代码。

- [ ] **Step 1: 写失败的测试**

```python
def test_sparkle_keys_include_a_signing_account():
    assert "ed_key_account" in _config.SPARKLE_KEYS


def test_duplicate_public_ed_key_across_channels_is_rejected(tmp_path):
    """Two channels sharing an EdDSA public key means they share the private
    one, which puts a release-accepted signing capability on the staging
    release machine. Config is where that must be caught: nothing downstream
    can tell the two apart."""
    cfg = tmp_path / "release_config.local.toml"
    cfg.write_text(
        'notary_profile = "p"\n'
        '[channel.canary]\npublic_ed_key = "SAME"\ned_key_account = "a"\n'
        'feed_url = "https://x/canary/appcast.xml"\n'
        '[channel.staging]\npublic_ed_key = "SAME"\ned_key_account = "b"\n'
        'feed_url = "https://x/staging/appcast.xml"\n')
    with pytest.raises(SystemExit, match="public_ed_key"):
        _config.assert_channel_keys_distinct(cfg)
```

- [ ] **Step 2: 实现**
- `SPARKLE_KEYS = ("public_ed_key", "ed_key_account", "feed_url")`
- 新增 `assert_channel_keys_distinct(path)`:加载全部 `[channel.*]`,若任意两个渠道的 `public_ed_key` 相同则 `SystemExit`
- `generate_appcast(..., ed_key_account: str)` 传 `--account <account>`(私钥留在 keychain,不落盘)
- `.example` 增加 `ed_key_account` 并注释说明 staging 必须用独立账户

- [ ] **Step 3: `package.py` 在发布前调用 `assert_channel_keys_distinct`**
- [ ] **Step 4: pytest 绿 → Step 5: 提交**

---

### Task 15: tag 命名空间化 + feed 抓取的异常区分

**Files:** Modify `scripts/_publish.py`、`scripts/package.py`、`scripts/tests/test_publish.py`(如无则新建)

**为什么**:`assert_not_published` 的 docstring 明写前提"we always tag on publish"。若 staging 不打 tag,重复发布护栏只剩 feed 一条;而 `fetch_live_appcast` 对**任何**异常返回 `None`、`assert_publishable` 随即 no-op ⇒ 两道闸可同时失效,叠加 `ossutil cp -f --cache-control immutable` 就是不可恢复的覆盖。

- [ ] **Step 1: 写失败的测试**

```python
def test_tag_name_is_namespaced_per_channel():
    assert _publish.tag_name("0.2.0.0", "canary") == "v0.2.0.0"
    assert _publish.tag_name("0.2.0.0", "staging") == "staging/v0.2.0.0"


def test_staging_and_release_can_hold_the_same_version():
    """The workflow this enables: rehearse a version on staging, then ship the
    same version to release. A shared tag namespace makes that impossible --
    the release publish would be refused as already-tagged."""
    assert _publish.tag_name("0.2.0.0", "staging") != _publish.tag_name("0.2.0.0", "canary")


def test_fetch_live_appcast_returns_none_only_for_404(monkeypatch):
    def raise_404(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(_publish.urllib.request, "urlopen", raise_404)
    assert _publish.fetch_live_appcast("https://x/appcast.xml") is None


def test_fetch_live_appcast_reraises_other_failures(monkeypatch):
    """A network blip must not be read as 'no feed yet'. That misreading
    disarms assert_publishable, and with staging behind an IP allowlist a
    blocked publisher is a realistic way to reach it."""
    def raise_timeout(url):
        raise TimeoutError("connection timed out")
    monkeypatch.setattr(_publish.urllib.request, "urlopen", raise_timeout)
    with pytest.raises(SystemExit, match="appcast"):
        _publish.fetch_live_appcast("https://x/appcast.xml")
```

- [ ] **Step 2: 实现** —— `tag_name(version, channel)`、`tag_exists(version, channel)`、`assert_not_published(version, channel, appcast_xml)`、`tag_and_push(version, channel, remote)` 全部带 channel;`fetch_live_appcast` 只对 HTTP 404 返回 `None`,其余异常 `SystemExit`。
- [ ] **Step 3: `package.py` 调用点同步传 channel;staging 放宽 `assert_on_main` 但保留 `assert_clean_tree`**
- [ ] **Step 4: pytest 绿 → Step 5: 提交**

---

### Task 16: 渠道配置自洽校验 + staging provenance

**Files:** Modify `scripts/_config.py`、`scripts/_package.py`、`scripts/tests/test_config.py`

- [ ] **Step 1: 写失败的测试**

```python
def test_channel_urls_must_contain_the_channel_name(tmp_path):
    """The failure this prevents: copying [channel.canary] to [channel.staging]
    and missing one key. If the missed key is oss_upload_target, the publish
    wipes the release prefix's appcast and replaces it with staging's -- and
    generate_appcast has already deleted the local copies by then."""
    ...
    with pytest.raises(SystemExit, match="oss_upload_target"):
        _config.assert_channel_urls_self_consistent(cfg, "staging")


def test_url_keys_must_not_live_in_the_shared_section(tmp_path):
    ...
    with pytest.raises(SystemExit, match="shared"):
        _config.assert_channel_urls_self_consistent(cfg, "staging")
```

- [ ] **Step 2: 实现 `assert_channel_urls_self_consistent`** —— 断言 `feed_url` / `download_base_url` / `oss_upload_target` 三者均含渠道名、彼此前缀一致,且不出现在 shared 区。
- [ ] **Step 3: provenance** —— `_package.py` 把 `git rev-parse HEAD` 写进 Info.plist 的 `TeleportSourceRevision`。staging 允许非 main 发布,没有 tag 之外的来源记录会让"staging 0.2.0.0 有问题"无法回溯到 commit。
- [ ] **Step 4: pytest 绿 → Step 5: 提交**

---

### Task 17: 文档同步

**Files:** Modify `CLAUDE.md`、`docs/tech-debt.md`、`docs/chromium-upgrade-runbook.md`

- [ ] **Step 1: `CLAUDE.md`** —— 三态 arg 与墓碑、staging 渠道与 out 目录、四把根与 `--require-real`、EdDSA 分环境、tag 命名空间、placeholder-ack 通道;并更新「渠道并排共存」一节(staging 的 bundle id / 数据目录 / Channel 映射)。
- [ ] **Step 2: `docs/tech-debt.md`** —— TD-026 的变通命令改为新 arg 名;登记 R4 的"切换机制未定"与 R7 的"半成品滞留"。
- [ ] **Step 3: `docs/chromium-upgrade-runbook.md`:303** —— 失效的 `teleport_use_release_endpoints=false` 命令改为 `teleport_policy_key_placeholder_ack=true`(具名通道取代临时覆盖)。
- [ ] **Step 4: 提交**

---

## Phase 3 完成定义

1. `staging` 映射到 `Channel::CANARY`,有单测钉死。
2. release 档不含任何企业端点覆盖开关与 `--policy-verification-key`;`grep -la` 验证 `libpolicy_component.dylib` 中 `teleport-deployment-domain` 字符串在 release 档消失(dev 档存在)。
3. 守卫按 `gn args --list` 的生效值判定,`test_build.py` 覆盖"args.gn 只有一行别的 env 的 import"用例。
4. `teleport_policy_key_placeholder_ack=true` 的产物带 `TeleportUnpublishable`,`--distribute` 硬拒。
5. staging 持独立 EdDSA 账户,跨渠道 `public_ed_key` 重复时 fail-closed。
6. tag 按渠道命名空间;`fetch_live_appcast` 只对 404 返回 None。
7. 渠道 URL 三键自洽校验生效;staging 产物带 commit provenance。
8. `uv run pytest` 全绿、`teleport_unittests` 全绿、`apply_patches.py` 幂等、dev chrome 构建通过。
9. 三份文档同步。

**不属于 Phase 3**(spec §6-c / §9):真实签名/公证/OSS 上传的演练发布——需要凭据与人工在场;`--require-real` 接进 `--distribute` 前置的接线在 Task 13 一并完成,但真实发布仍阻塞于 T5。
