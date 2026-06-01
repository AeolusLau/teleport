# 打包流水线跳过"无变更"的重复公证设计

- **日期**:2026-06-01
- **范围**:`scripts/package.py` 及打包模块(`_package.py`、新增 `_package_state.py`)。让"已执行过且输入无变更"的昂贵步骤不再重复——核心诉求:跑过 `package.py --channel canary` 后,再跑 `package.py --channel canary --distribute` 时**不重新公证**(notarization 慢、分钟级)。
- **定位**:打包工具脚本层改动,纯性能优化 + 安全护栏;不改变发布逻辑本身,不涉及 C++/后端。

## 1. 背景与问题

分发渠道(canary)的打包流水线(`package.py` main):

```
build()                       # autoninja —— 已是增量,无变更则快
stamp_and_inject()            # plutil 戳 version + Sparkle 键 + TeleportChannel,快
stage_channel_icons()         # 拷贝图标,快
sign_app()                    # 经 sign_chrome.py 给 .app 签名,中等
build_styled_dmg():           #
  dmgbuild                    #   构建样式 dmg(lzma,~105MB),中等
  codesign --timestamp dmg    #   签 dmg,快
  notarytool submit --wait    #   ★ Apple 公证,慢(分钟级)
  stapler staple              #   订书,快
# --distribute 额外:generate_appcast -> upload_to_oss -> tag_and_push
```

`--distribute` 会把整条 `build→sign→dmg→公证` 重跑一遍再发布。即便代码毫无变化,**公证仍会重做**,这是主要痛点。

### 关键约束

- **`codesign --timestamp` 不确定**:每次重签都会从时间戳服务器取时间,字节都不同。因此**无法"只跳过公证、却重签重打 dmg"**——要省掉公证,就必须**复用上次已公证 + staple 的那个 dmg**(连带跳过 `sign_app` 与 `build_styled_dmg`)。
- **`generate_appcast` 会裁剪 `updates_dir`**(`dist/<channel>/`,只留当前 dmg、删其他文件)。因此"无变更"状态清单**不能放在该目录内**(会被删)。
- 目前流水线**无任何状态/清单设施**,需新增。

## 2. 目标与非目标

**目标**

1. 当**新构建后的 app 与上次成功打包时逐字节相同**、且已有一个**有效(已公证+staple)的目标 dmg** 时,跳过 `sign_app` + `build_styled_dmg`(含公证),直接复用该 dmg。
2. 安全第一:跳过是纯优化,**绝不**发出陈旧或未公证的包(fail-closed)。
3. 覆盖核心场景:`--channel canary` 之后的 `--channel canary --distribute` 不重新公证。

**非目标**

- 不为 `build()` 另加跳过(autoninja 本就增量)。
- 不缓存/跳过发布步骤(appcast / OSS 上传 / tag)——这些与"是否公证"无关,每次发布都要做。
- 不做跨机器共享缓存(状态是本机的)。

## 3. 安全模型(fail-closed)

**跳过仅当以下全部成立**,否则一律完整跑 `sign→dmg→公证→staple`:

1. 新构建 + stamp + stage 后的**未签名 app 的全内容 SHA-256** == 清单中记录的哈希;
2. 复用键的其余字段一致(version、channel、codesign identity、notary profile);
3. 目标 dmg 文件存在;
4. `stapler validate <dmg>` 通过(确认该 dmg 当前字节带有效公证票据)。

逐项风险与化解:

| 风险 | 化解 |
|---|---|
| 哈希漏判(app 变了但哈希相同) | 对 .app 内**所有常规文件的相对路径 + 大小 + 字节内容**算 SHA-256;任何真实改动都改哈希,SHA-256 碰撞密码学上不可能 → 哈希相同 ⟹ app 逐字节相同 |
| 复用的 dmg 与所测 app 不符 | 清单**原子绑定** "dmg ↔ app 哈希",仅在公证 + staple 成功后写;复用前 `stapler validate` 校验该 dmg 当前字节确有有效票据 |
| 签名配置变了(换证书 / notary profile)但代码没变 | identity、notary_profile、version、channel 一并纳入复用键 → 任一变化即不复用 |
| 发布未公证 / 陈旧包 | 复用前提即 `stapler validate` 通过;且 `--distribute` 上传前**再校验一次**目标 dmg。无有效 dmg → 不跳过 → 走完整公证 |
| 清单被删 / 过期 | 最坏只是"本可跳过却没跳"(多花时间);绝不会"本不该跳却跳了"(哈希必须与当前 app 一致才复用) |

**核心不变量**:跳过只可能让流程**更快**,worst case 是多做一次公证;绝不发出陈旧或未公证的包。另加 **`--force`** 一键绕过复用、强制重做。

## 4. 设计

### 4.1 新模块 `scripts/_package_state.py`

单一职责:计算 app 内容指纹、读写打包状态清单、给出复用判定。

- `app_content_digest(app: Path) -> str`
  遍历 `app` 下所有常规文件(`sorted` 相对路径),对 `(相对路径, 大小, 内容字节)` 逐一喂入一个 `hashlib.sha256`,返回 hex。符号链接按其指向路径文本入摘要(不解引用)。几秒级,远低于公证的分钟级。

- `state_path(repo_root, channel_name) -> Path`
  返回 `repo_root/dist/.package-state/<channel>.json`(在被裁剪的 `dist/<channel>/` 之外)。

- `reuse_key(version, channel_name, identity, notary_profile, app_digest) -> dict`
  组装复用键(纯数据)。

- `load_state(path) -> dict | None` / `write_state(path, key, dmg_name) -> None`
  JSON 读写;`write_state` 写入 `{**key, "dmg_name": dmg_name}`,父目录按需创建。

- `can_reuse(state, key, dmg_path) -> bool`
  纯逻辑:`state is not None` 且 `state` 的键字段全等于 `key` 且 `state["dmg_name"] == dmg_path.name` 且 `dmg_path.exists()`。(`stapler validate` 这一步有副作用,放在 `package.py` 调用层,见 4.2,以便单测 `can_reuse` 为纯函数。)

### 4.2 `package.py` 改动(分发渠道路径)

在检测到 identity 之后、现有"Build -> stamp -> stage -> sign -> dmg"序列处改为:

1. `build(out, channel)`;`stamp_and_inject(...)`;`stage_channel_icons(...)`(照旧,均快)。
2. 计算 `app_digest = _package_state.app_content_digest(app)`;
   `key = reuse_key(version, channel.name, cfg["codesign_identity"], cfg["notary_profile"], app_digest)`;
   `target_dmg = updates_dir / f"{file_prefix}-{version}.dmg"`(文件名由 `_package.dmg_names` + version 决定)。
3. **复用判定**:`reused = (not args.force) and can_reuse(load_state(state_path), key, target_dmg) and stapler_validate(target_dmg)`。
   - `reused` 为真:打印"reusing notarized dmg <name> (app unchanged); skipping sign + notarize",`target_dmg` 即现有文件,**跳过** `sign_app` 与 `build_styled_dmg`。
   - 否则:`sign_app(...)` → `target_dmg = build_styled_dmg(...)` → `write_state(state_path, key, target_dmg.name)`(仅在公证 + staple 成功后,即 `build_styled_dmg` 正常返回后)。
4. `--distribute` 上传前的最终闸:无论是否复用,都 `assert stapler_validate(target_dmg)`(已有的 `assert_not_published` 之后、`generate_appcast` 之前),失败则 `SystemExit`("target dmg failed stapler validate; refusing to publish")。

`stapler_validate(dmg) -> bool`:`xcrun stapler validate <dmg>` 返回码为 0 即真(放在 `_package.py` 或 `_package_state.py`;有副作用,不进 `can_reuse`)。

### 4.3 新增 CLI 参数

- `--force`:跳过复用判定,强制重新 sign + dmg + 公证 + staple(并刷新清单)。
- `--dry-run` 增强:在分发渠道 plan 中,先做复用判定,显示"reuse notarized dmg <name>(app unchanged)"或"re-notarize(app changed / no valid dmg)"。

### 4.4 dev 渠道

不涉及(dev 仅 build + stamp,无签名/公证)。不改。

## 5. 测试(TDD,pytest)

`scripts/tests/test_package_state.py`:

- `app_content_digest`:对临时目录构造的"app"算摘要;改一个文件内容/新增文件/改文件名 → 摘要变;不变 → 摘要稳定(重复调用相等)。
- `state` 读写往返:`write_state` 后 `load_state` 得到等价 dict;`load_state` 对不存在路径返回 `None`。
- `can_reuse` 分支:键全等 + dmg 存在 → True;version/channel/identity/notary_profile/app_digest 任一不同 → False;`state is None` → False;`dmg_name` 不符 → False;dmg 不存在 → False。

`scripts/tests/test_package_cli.py`(沿用现有 CLI 测试风格,mock `_build.build`、`_package.*`、`_package_state.*`、`stapler_validate`、`_publish.*`):

- 第一次 `--channel canary`:无清单 → 走完整 sign+dmg,`write_state` 被调用。
- 第二次 `--channel canary --distribute` 且 digest 不变 + dmg 存在 + stapler 通过:`sign_app`/`build_styled_dmg` **未被调用**,`generate_appcast`/`upload`/`tag` 被调用,且发布前 `stapler_validate` 被断言。
- digest 变化:复用不触发,完整重做。
- `--force`:即便可复用也完整重做。
- 发布前 `stapler_validate` 失败:`SystemExit`,不上传、不打 tag。

集成层(真实 notarytool 跳过)手动验证:连跑两次 `--channel canary` 第二次应秒过签名/公证段。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 复用了内容已变的包 | §3:全内容 SHA-256 + 键含签名配置;不符即不复用 |
| 发布未公证/陈旧包 | 复用需 `stapler validate` 通过;发布前再校验一次;fail-closed |
| 哈希全 app 太慢 | 几秒级,远低于公证;可接受。若日后嫌慢再优化为子集哈希(YAGNI,暂不做) |
| 清单与 dmg 不同步(手动删了 dmg) | `can_reuse` 检查 `dmg_path.exists()`;缺失即重做 |
| `dist/.package-state/` 被误纳入 git | 它在 `dist/` 下,而 `.gitignore` 已忽略 `/build` 等产物;确认 `dist/` 已被忽略,否则补一条 |

## 7. 落地顺序(TDD)

1. `_package_state.py` + `test_package_state.py`:digest、state 读写、`can_reuse`(纯逻辑,先红后绿)。
2. `stapler_validate` helper + 单测(mock subprocess)。
3. `package.py` 接入复用判定 + `--force` + 发布前最终闸;扩 `test_package_cli.py` 覆盖 §5 各 CLI 分支。
4. `--dry-run` 增强 + 其测试。
5. 确认 `dist/` 在 `.gitignore`(否则补);手动连跑两次 canary 验证第二次跳过公证。

## 8. 后续(不在本 spec)

- 跨机器/CI 共享公证缓存(本设计是本机清单)。
- 对 `sign_app` 单独做更细粒度跳过(当前随 dmg 复用一并跳过,已够)。
