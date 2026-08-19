# 部署环境三态化设计 · 对抗性评审决策点

- 日期:2026-08-10
- 关联 spec:`2026-08-10-deployment-env-tristate-design.md`(v1,commit `a595d8d` + `e805293`)
- 评审方式:4 个并行对抗性子代理,视角分别为 ①威胁模型 ②跨仓契约一致性 ③实现可行性 ④交付与运维
- 状态:**待决策**——A 组未定则 v2 无法动笔

## 0. 评审裁决记录

**§2.6「canary `--device-management-url` 缺陷」是误判,已裁决推翻。**

`patches/chrome/browser/policy/chrome_browser_policy_connector.cc.patch:26-28` 把 `DeviceManagementServiceConfiguration` 的三个 URL 构造参数改成 `std::string()`;`patches/chrome/browser/policy/device_management_service_configuration.cc.patch` 让三个 getter 在空值时回落到 `teleport::Deployment*Url()`。因此含 `GetUrlOverride` 的 `BrowserPolicyConnector::GetDeviceManagementUrl()` **在桌面 DM 路径上不再被调用**,该 switch 对端点无效;`GetUrlOverride` 的其余消费者(`GetFileStorageServerUploadUrl`)在 M151 仅 ChromeOS 编译。

误判成因:只验证了门控函数 `IsCommandLineSwitchSupported()` 返回 true,未验证门后调用链是否仍连通。四个评审代理中有两个复现了同样的错误,一个追到了调用链。

**推论**:真正的端点控制面是 deployment domain 的 level 2/3/4,而它们在 prod 下全部保留,且被 v1 spec §3 明确列为非目标。§2.6 / §4.4 / §10.5 三节须按此重写。

---

## A 组 · 阻断性决策(未定则 v2 无法动笔)

### A1 · 双根机制:承诺"无缝切换",还是承诺"有损切换"?

**问题**:v1 §4.2/§4.3 承诺"主根泄露后服务端切恢复根,存量客户端无感"。服务端代码不支持这个承诺。

**证据**
- `fairyland/products/teleport/device-manager/internal/policy/onboard.go:124-153` — `EnsureVerification` 幂等:命中 `tenant_policy_verifications` 即原样返回,仅 `ErrVerificationNotFound` 才重签。
- `migrations/002_tenant_signing_keys.up.sql:18-25` — 背书表以 `(tenant_id, domain)` 为主键持久化,**无根标识列、无版本列**。
- 全仓唯一重签手段是 `scripts/mint-dev-policy-root.sh:37` 的 `DELETE FROM tenant_policy_verifications;`,**dev-only**,生产无等价物。
- `cmd/root-signer/main.go:164-167` — `ROOT_KEY_ID` 单值 env,`makeSignHandler(be, keyID)` 绑死一把。

叠加的第二个冲突——**恢复根宿主两侧定义相反**:
- 本 spec §4.1 写「prod KMS `teleport-root`」;
- `fairyland/docs/superpowers/specs/2026-07-04-teleport-policy-root-trust-anchor-design.md:63` 写「离线仪式生成,私钥冷存,**从不接触任何在线系统**」;
- `fairyland/infra/opentofu/modules/kms/main.tf` 只声明**一把** `teleport_root`;master design T5 交付物是「每环境一把公钥」,**不产出恢复根公钥** ⇒ v1 §6「替换 `keys/*.pem` 即可」对这把根不成立。

**选项**

| | 方案 | 代价 |
|---|---|---|
| **a** | 服务端补齐无缝能力:背书表加 `root_key_id` 列 + 读路径不匹配即重签 + root-signer 双 key 配置面 + 恢复根进 KMS | 服务端 migration + 代码;**推翻 2026-07-04 的"永不触网"**,恢复根的离线性丧失 |
| **b** | 客户端照烤两把公钥(不可逆的廉价保险),但**不承诺无缝**;切换 = 停机 + 全量重签背书,写进事故 runbook | 承诺下调;服务端仍需一个非 `DELETE FROM` 的生产重签机制,但不必双 key 在线 |
| **c** | 本轮不做双根,prod 单根,推迟到密钥仪式立项 | 最省;但烤公钥不可逆——存量客户端将永远只信一把根,补不上 |

**推荐 b**。理由:烤第二把公钥是廉价且**不可撤销**的保险,该做;而"切换是否无缝"是独立问题,当前服务端架构给不了,不该在客户端 spec 里承诺。c 的代价是真实的(2026-07-04 spec §4.2 要求"自第一个 release 构建起双公钥烘焙"正是因为不可逆)。

---

### A2 · 升级签名链(Sparkle EdDSA)是否分环境?

**问题**:F6 的隔离只覆盖策略链。升级链是**第二条独立信任链**,当前跨环境共用。三个评审代理独立发现此条。

**证据**
- `docs/superpowers/specs/2026-05-26-macos-canary-channel-design.md:149` — 既有裁定原文:「所有通道**共用一把 EdDSA 密钥**(最简)」;同文件 `:182` 把"stable 是否单独一把"列为未决。
- `scripts/_publish.py:88-93` — `generate_appcast` 不传 `--account` / `--ed-key-file`,恒用 keychain 中唯一一把。
- `scripts/_config.py:16` — `SPARKLE_KEYS = ("public_ed_key", "feed_url")`,只有公钥,无私钥选择位。

**失败场景**:v1 §1 自述 staging「故意更弱(ciMock / mock IdP / e2e 持 token)」,而 staging 发布机持有 prod 客户端接受的升级签名能力 + 同一 Developer ID。升级链投递任意代码,后果重于策略。唯一屏障是 bundle id 不匹配——行为性屏障,非密码学边界。

**选项**

| | 方案 | 代价 |
|---|---|---|
| **a** | staging 独立 EdDSA 密钥对(`generate_keys` 再生一把;`_publish.py` 传 `--ed-key-file`;`_config.py` 增私钥选择键);Developer ID 仍共用并登记 | 小(脚本 + 一次密钥生成);需复核 CLAUDE.md「绝不同时换 Developer ID 和 EdDSA」的轮换纪律在两把下的表述 |
| **b** | 共用一把,在 §8 显式登记「升级链不受 F6 隔离保护」 | 零成本;但 §1 立论"staging 失陷对 prod 零影响"必须改写为"仅策略链零影响" |
| **c** | staging 退回内部直发,不走真实 appcast/OSS | 零密钥风险;但测不到 Sparkle 链路,与"同构演练"目标冲突 |

**推荐 a**。理由:成本很小而消除的是最重的一条通道;b 会让 §1 的立论只剩一半,c 直接放弃了 staging 存在的主要价值之一。

---

### A3 · env 与 channel 两个轴:现在拆,还是继续用 channel 冒充 env?

**问题**:v1 §4.5 把 staging 建模为一个 channel 名并登记为"取舍"。评审指出这不是可登记的取舍,而是会产出一个前所未有的构建组合。

**证据**
- `src/common/teleport_channel.cc:7-15` — `ChannelFromName` 只认 `canary`/`beta`/`stable`,其余 → `version_info::Channel::UNKNOWN`;`src/common/teleport_channel_unittest.cc:30` 显式 pin 了这个行为。
- `scripts/_package.py:80-82` — channel 名原样写进 Info.plist 的 `TeleportChannel` 键。
- v1 §5 改动清单**没有** `src/common/teleport_channel.cc`。

**后果**:staging 包运行时 `chrome::GetChannel()` 恒为 `UNKNOWN` ⇒ ①上游一批 `channel != STABLE` 的门在 staging 下行为与 prod 的任何渠道都不同,"逐字相同的演练"演的不是同一个东西;②既有 channel-alignment 特性(修升级角标时序)在 staging 上失效,而升级角标正是 staging 要演练的 Sparkle 链路的可见终点;③`IsCommandLineSwitchSupported()` 在 staging 恒 true 是**碰巧**对了,不是设计出来的。

**选项**

| | 方案 | 代价 |
|---|---|---|
| **a** | 不拆轴,但把 `staging` 显式加进 `ChannelFromName` 并映射到 `CANARY` | 小;但 bundle id 后缀与 `TeleportChannel` 键仍由同一个名驱动,env↔channel 的耦合保留 |
| **b** | 现在拆:产物身份 = env × channel,bundle id 用 env 后缀(`cn.douan.Teleport.staging`)、`TeleportChannel` 仍写 `canary` | 中;打破 CLAUDE.md「channel 名是 bundle id 后缀与 `TeleportChannel` 键的单一事实源」这条既有约定,需同步更新该约定 |

**推荐 a**,并在 §8 把"将来 staging 需要多渠道时必须拆轴"升级为硬性前置条件(而非"取舍")。理由:b 的收益在只有一个 staging 渠道时无法兑现,却要立刻改一条既有的单一事实源约定。

---

### A4 · staging 与 prod 的版本序列与 tag

**问题**:v1 §4.5 定"staging 不打 tag",评审指出这会让重复发布护栏归零,且共用 `TELEPORT_VERSION` 有可区分性问题。

**证据**
- `scripts/_publish.py:62-74` — `assert_not_published` 只有 `tag_exists` + `assert_publishable` 两道闸;`:63-68` docstring 明写前提「**we always tag on publish**」。
- `scripts/_publish.py:15-20` — `fetch_live_appcast` 对**任何** `Exception` 返回 `None`;`scripts/_release.py:61-66` — `appcast_xml` 为 None 时 `assert_publishable` 直接 return ⇒ 两道闸可同时失效。
- `scripts/_publish.py:102-112` — `ossutil cp -f` + `--cache-control ... immutable`,覆盖不可恢复。
- `scripts/_publish.py:54-59` — `tag_exists` 读**仓库全局** tag,与渠道无关 ⇒ prod 先发 `v0.2.0.0` 后,同版本的 staging 演练会被拒。
- `scripts/_package.py:37-45` — `assert_baked_version` 只校验版本串,**不校验环境配置**。

**选项**

| | 方案 | 代价 |
|---|---|---|
| **a** | 共用 `TELEPORT_VERSION`,tag 命名空间化(`staging/v<四段>`),staging **照常打 tag**;并在 Info.plist 烙环境标识解决可区分性 | 小;`tag_exists` 需按渠道命名空间查询 |
| **b** | staging 独立版本序列 | 需拆 `TELEPORT_VERSION` 单一事实源,与既有约定冲突 |

**推荐 a**。"撞名"是 v1 自设的伪约束——命名空间即可共存;而"先 staging 演练同一个包、再原样发 prod"这个工作流只有在 a 下才成立。另需附带修复:`fetch_live_appcast` 必须区分 404(首发)与其它异常,后者硬失败。

---

### A5 · staging 是否开启 PGO?

**问题**:v1 §3 目标 3 要求"与 prod 逐字相同的流水线",隐含 staging 也 `chrome_pgo_phase=2`。评审给出了实测成本。

**证据**:实测 `out/mac/arm64/release` = **118 GB**,`out/mac/arm64/dev` = 17 GB;`src/gn/args/{dev,release}.mac.gn` 均 `use_remoteexec = false` ⇒ 两个 out 目录是彼此独立的 ninja 图,**零对象复用**;且 staging↔prod 的差异落在 `//components/policy`(改一字节即大范围重编)。

**选项**

| | 方案 | 代价 |
|---|---|---|
| **a** | staging 开 PGO,逐字同构 | 每次发版两次全量 official+PGO 构建 + 额外 ~118 GB 磁盘 |
| **b** | staging 关 PGO | 砍掉大半时间与磁盘;放弃"逐字相同",性能特征不同(但 staging 的目的是演练分发与信任链,非性能) |

**推荐 b**,并在 §3 目标 3 把"逐字相同"精确化为"签名/公证/dmg/appcast/Sparkle 链路相同,优化配置不同"。理由:PGO 影响的是代码生成,不影响本特性要验证的任何一条链路;付全价买不到对应的保真度。

---

### A6 · 占位密钥期间的构建通道

**问题**:v1 §10-1 要求 staging/prod 档 `gn gen` **必须**因占位密钥报错,§10-5 又要求验证 prod 二进制里没有 switch,§7 还要求交叉否定 e2e 同时构建两个变体——**互相矛盾**,且这条不可验证的 DoD 正是"临时覆盖并遗留在 args.gn"的诱因(TD-026 已演过一遍,`docs/tech-debt.md:271`)。

**证据**
- `src/teleport.gni:34-36` — 断言在 `gn gen` 阶段 fail,拿不到任何 staging/prod 二进制。
- 实测 `~/workspace/chromium/151.0.7922/src/out/mac/arm64/release/args.gn` **此刻仍含** `teleport_use_release_endpoints = false` —— TD-026 的临时覆盖至今活在磁盘上。

**选项**(可组合)

| | 方案 |
|---|---|
| **a** | 给"可构建但不可发布"一条**具名合法通道**:`teleport_policy_key_placeholder_ack=true` → 产物 Info.plist 烙 `TeleportUnpublishable=YES` → `package.py --distribute` 前置硬拒 |
| **b** | §10-5 降级为可在 buildflag 展开 + 单测层完成的判定;§7 的交叉否定 e2e 明确标注"阻塞于 T5,不属本轮 DoD" |
| **c** | 允许 staging 档先以「**dev 根 + staging 域**」组合跑通一次完整的签名/公证/dmg/appcast/OSS/Sparkle 演练 |

**推荐 a + b + c 全取**。c 尤其有价值:否则 `[channel.staging]` / `staging.mac.gn` / staging 全发布路径在本轮合入后**从未被真实执行过一次**,数月后 T5 落地时第一次真跑就是"首次执行 + 要出真包"。

---

## B 组 · 需知情裁定(可接受为风险,但不得沉默略过)

### B1 · MDM 平台策略读取域跨环境共用

`patches/chrome/browser/policy/chrome_browser_policy_connector.cc.patch` 把读取域钉死为 `cn.douan.Teleport`(`src/common/teleport_deployment_config_mac.mm:25`),服务端 master design 把这写成特性(「一份 MDM payload 配全变体」)。但 QA 机并排安装 prod + staging 时:一条 forced `DeploymentDomain=staging.douan.cn` 会**同时**命中 prod 客户端(level 2 优先级高于 level 4/5),且 `CloudManagementEnrollmentToken` 只有一个槽位,两环境的纳管 token 无法共存。

**选项**:①保持共用 + 明令禁止并排安装;②给 staging 独立 managed-prefs 域(打破"一份 payload 配全变体")。**倾向 ①**,但必须写进 §4.5 与 QA 手册。

### B2 · `staging.douan.cn` 与 `douan.cn` same-site

`cn` 是 TLD、`douan.cn` 可注册 ⇒ staging 与 `teleport.douan.cn` / `accounts.douan.cn` **same-site**。威胁模型自设 staging 会失陷,而失陷的 staging 可设 `Domain=.douan.cn` cookie、可作 SameSite=Lax/None 的同站来源、可命中任何 `*.douan.cn` 形式的 CORS/重定向白名单。这条与策略根无关,§2.5「数学上的零」不覆盖它。

**选项**:①迁到独立可注册域(服务端已部署 `staging.douan.cn` 且 T4 证书已签,成本高);②保持并登记残余风险;③服务端在 cookie/CORS 层加硬隔离。**倾向 ② + ③**。

### B3 · 主根泄露窗口内 level-4 是完整接管路径

`src/browser/teleport_deployment_level4.cc:56-69` — 只要 blob 能被根集合中任一把验过,`data.domain()` 即成为 `DeploymentDomain()`,进而驱动 DM / reporting / enroll / OIDC 可信重定向宿主 / 隧道 edge + cnf bearer token。BYOD 默认态下 enroll 页未锁(`src/browser/webui/teleport_enroll_ui.cc:121-135` + `teleport_deployment_config.cc:161-175`),用户可输入任意域。

⇒ prod 主根泄露后,攻击者签一个 `ServerIdentityData{domain=evil.example}`、社工诱导 BYOD 用户 enroll,即可接管该客户端全部端点,**无需网络位置、无需 MDM 权限、无需 root**。受管设备因 level 2/3 优先 + `IsDomainChangeLocked` 免疫——这个不对称性 v1 未写。

v1 §8-T1 的残余风险论证("攻击者仍需私钥")对 staging 成立,对"根已泄露"这个前提**不成立**。

**选项**:①把 level-4 blob 的可接受 domain 限制为编译期锚定的后缀(与私有化客户用自有域名的能力冲突);②登记为已知风险 + 量化 Sparkle 收敛时间;③blob 增加 domain 约束字段。**倾向 ②**,①与私有化交付直接冲突。

---

## C 组 · 无需决策,v2 直接修订

**事实性错误(spec 写错了)**

| 位置 | 错误 | 实情 |
|---|---|---|
| §2.6 / §4.4 / §10.5 | canary switch 缺陷 | 已裁决推翻,见 §0 |
| §4.3 | 整段论证 | 前提有误:存量客户端集合中本就有两把根,服务端用活跃根签名即可,**无需改 hash 语义**;而 v1 的改法反而把 hash 变成客户端可控的降级选择器(持泄露主根者恒发主根 hash → 服务端按契约继续用主根签) |
| §4.1 | "两个派生量正交" | 二者都是同一 env 字符串的函数,完全相关 |
| §4.1 | "`buildflag_header` 只支持布尔/整数" | 支持字符串(`build/buildflag_header.gni:38`);真正约束是 `#if` 不能比较字符串 |
| §4.5 | "经 fairyland 侧确认"的访问模型 B / IP 白名单 | 服务端仓库零书面依据、零 IaC(无 `acl` / `source_cidr_ip`);staging OSS 分发桶亦不存在 |
| §9 | "T5 未开工" | secret-manager/RRSA 半边已 staging 实测通过(`a4dbce8`);未开工的是 KMS 签名后端 + 仪式 + 公钥导出 |
| §4.1 | 第三态命名 `prod` | 服务端 master design:76 写 `release`,两仓已漂移,须统一 |
| §4.4 | `teleport_deployment_config_mac.mm:31` | 该注释实际在 `:29-30`,`:31` 是函数签名行 |

**验签面漏点(§4.2 / §5 补全)**
- `cloud_policy_validator.cc:639/657` 的 `CheckCachedKey()` —— 第二个**活跃**验签点,经 `user_cloud_policy_store.cc:326` 每次启动都走。漏改 ⇒ 恢复根启用后**重启即丢策略**,恰好摧毁双根的存在理由。
- `user_cloud_policy_store.cc:110/264`、`machine_level_user_cloud_policy_store.cc:238` —— 把根写进磁盘 `PolicySigningKey.verification_key` 并用于轮换判定。漏改 ⇒ 升级后全网策略拉取风暴,或缓存签名密钥永不轮换。需定义"根集合下应记录哪把"(建议记录**实际验过的那把**)。
- `src/common/teleport_enroll_logic.{h,cc}`(`:69` / `.cc:78` 的 `VerifyFetchedIdentity`)同样只接受单根,v1 §5 未列。
- **verdict 聚合语义未定义**:应先定位签名通过的那把、再返回该把的真实 verdict;全部签名失败才报 `kBadSignature`。否则"恢复根签名 + 已过期"会被误报为签名错误,给出错误排障方向。
- §5 还需新增 `cloud_policy_constants.h.patch`(声明 `GetPolicyVerificationKeys()`);若集合下沉为 validator 成员,还需 `cloud_policy_validator.h.patch`。v1 "无新注入点"这句自我保证须删除。

**GN / 守卫(§4.1 / §4.5)**
- **墓碑 arg 必备**:实测 GN 对未声明 build arg **只告警、退出码 0**。直接重命名会让 `docs/chromium-upgrade-runbook.md:303`、`docs/tech-debt.md:270-273`、CI、肌肉记忆里的 `teleport_use_release_endpoints=<x>` 静默失效并回落默认档。须保留 `declare_args()` 中的旧名 + 紧跟 `assert(!teleport_use_release_endpoints, "renamed to ...")` 使其硬失败。
- **守卫判定轴必须改**:`scripts/_build.py:116-118` 按文本正则匹配赋值行,而正常 `gn gen` 生成的 args.gn 只有一行 `import(...)` ⇒ `actual is None` 早退、零保护。改为查询生效值(`gn args <out> --list=teleport_deployment_env --short`,已实测可行)或校验 `import()` 模板名;并覆盖 `teleport_*_key_is_real` 这一族覆盖。
- **§4.4 修法打错层**:`GetUrlOverride` 是泛型的(`const char* flag`),关不掉单个 switch;而 `IsCommandLineSwitchSupported()` 另有三个消费者(`binary_upload_request.cc:438`、`user_cloud_signin_restriction_policy_fetcher.cc:252`、`chrome_enterprise_url_lookup_service_factory.cc:129`)。应改为在**已存在**的 `chrome_browser_policy_connector.cc.patch` 里让该函数在 prod 档 `return false`——单点、根因、真正的既有 patch 扩档。
- **`TELEPORT_IS_RELEASE_FORM` 无 C++ 消费者**(official/PGO/Sparkle/签名全部在 args 模板里独立显式设置),且 env 与 form 绑死会**移除 TD-026 的逃生口**。要么独立成 `declare_args()` 允许覆盖,要么从 buildflag 列表删除并在 §8 登记逃生口的替代做法。
- **`gn check` 风险**:`browser_policy_connector.cc` 要用 buildflag,但 `patches/components/policy/core/browser/BUILD.gn.patch` 只加了 `teleport_deployment_config` dep,而后者不 include buildflag 头;chromium `.gn:84-92` 未设 `check_targets` ⇒ 全量 header check 生效,会报 "Include not allowed"。

**测试(§7)**
- **档位单测不可执行**:`teleport_deployment_config_unittest.cc:39-43` 是 `#if`/`#else`,一个二进制只编译一档,而 `teleport_unittests` 只在 dev out 构建。须把档位判定下沉为纯函数 seam(照既有 `teleport_enrollment_gate_logic` / `teleport_enroll_logic` 模式,让 `ReadCommandLineDomain()` 的策略部分接受 `bool allows_override` 参数),三态才能在同一 dev 二进制内全部可测。
- `--check` 无法区分占位与真根:`gen_policy_verification_key.py:72-90` 只做三方一致性比对,对占位值同样返回绿色;且 `patch_dev_key():66` 的 hash 定位靠"key 块之后第一个 hash"的位置启发式,prod 两把 key + 一个 hash 时必然错位。须改为显式 key↔符号映射表 + 占位指纹清单 + `--require-real <env>` 硬失败,并接进 `package.py --distribute` 前置。

**发布链其它**
- `scripts/package.py`(`assert_on_main:184`、`tag_and_push:229`)不在 `_publish.py` 内,§4.5 要放宽必须改这里;`assert_clean_tree` 须明确**保留**,并把 `git rev-parse HEAD` 写进 Info.plist 或 `_package_state` 台账作为 staging 的最低 provenance(否则从特性分支发出的 staging 包零 provenance)。
- **渠道配置自洽校验**:`_config.py:29-33` 的 `merged = {**shared, **channels[channel]}` 允许把 `feed_url` 写在顶层套到所有渠道;`_publish.py:85-87` 会先清空 updates_dir 再 `cp -f`,一个漏改的 `oss_upload_target` 就能把 staging 的 appcast 覆盖到 prod 前缀。须断言三个 URL 键均含渠道名、前缀一致、且不得出现在 shared 区。
- **新增 §11 事故处置**:现有流水线**机制上不支持回滚**(重发 N-1 被 `assert_publishable` 拒、重发 N 被 `tag_exists` 拒、OSS 无 bucket versioning、appcast 只列最新版且 Sparkle 的 `--versions` 未使用)。须覆盖:staging 根泄露处置(§4.1 定 staging 单根 ⇒ 必须显式承认"全量重发 staging 客户端")、误发到 prod 前缀的发现手段(发布后回读 appcast 校验 URL/签名/bundle id)与撤回手段。
- **§8 新增"半成品长期滞留"风险**:T5 未排期 ⇒ staging 全发布路径在本轮合入后从未真实执行过一次;TD-026 已演示过这个模式的后果(`docs/tech-debt.md:271`:"只是因为期间没有发过版,所以没人注意到")。降险措施见 A6-c。
- §5 改动清单还漏:`scripts/tests/test_package_cli.py:366-372`、`docs/tech-debt.md`、`docs/chromium-upgrade-runbook.md`(后两者含将失效的 TD-026 命令)、`src/common/teleport_channel.cc`。

---

## D 组 · 需 fairyland 侧补的跨仓待办

1. **存量租户背书重签机制**(A1 的服务端半边):背书表加根标识列 + 读路径不匹配即重签 + 生产根切换 runbook(不能是停机 `DELETE FROM`)。**两侧此前均未提到。**
2. **恢复根的宿主与产出方**:归属哪条轨、进不进 KMS、T5 是否产出其公钥。
3. **`verification_key_hash` 门**:device-manager 当前**零行实现**,且 `internal/keygen/keygen.go:179-185` 的注释明写该值「ADVISORY only / NOT load-bearing / Neither side validates」——实现者会照注释继续无视。须写进 T5 完成定义 + 新增配置面(本环境可接受 hash 集合)+ 订正该注释。
4. **"串环境立刻在握手层报错"是空头**:`internal/httpserver/server_identity_handler.go:5-20` 的 `/server-identity` 是**无参 GET**,不携带 hash;hash 仅存在于 policy fetch(`cloud_policy_client.cc:797`),时序上排在 server-identity 验签之后。v1 §4.3 承诺的诊断收益不存在,应改落到客户端侧:`ServerIdentityVerdict::kBadSignature` 必须 fail-loud 呈现到 enroll 页。
5. **`device-manager/README.md:103`** 的根轮换条目(「必须同步发布内嵌新根公钥的客户端」)与双根无缝切换直接矛盾,自 2026-07-04 提出双根后未更新 ⇒ 根泄露当天运维会走岔。
6. **root-signer 的 KMS 后端**:`internal/rootsigner/kms.go:17-35` 的 TODO 给的是 **regional** SDK 配方,对 DKMS 专属实例不适用(与公钥导出撞同一堵墙),须改用 DKMS 网关 SDK + AAP 客户端证书;`master-design.md:65` 另已裁定 `KMSSigner` stub 应删除,该 stub 是残留误导。
7. **staging 的访问白名单与 OSS 分发桶**:两者在服务端 IaC 中均不存在(`modules/oss/main.tf:3-5` 只有 app/backup/geoip 三桶)。
8. **§10-6 的可验证性**:跨仓契约的镜像记录目前只存在于一棵**未提交**的工作树,DoD 应改为"已提交"并附 commit 号。
9. **三态字面值统一**:服务端写 `release`,客户端写 `prod`。
