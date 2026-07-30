# 部署域名:私有化 BYOD 纳管 与 管理域迁移 Runbook

面向 IT / 交付 / 支持人员。配套实现见 spec `docs/superpowers/specs/2026-07-15-deployment-domain-config-design.md`(§4.2 connect 页、§4.5 换域迁移)与 `docs/superpowers/specs/2026-07-24-voluntary-enrollment-ux-design.md`(强制纳管 gate 的默认值与自愿纳管形态)。

> **强制纳管 gate 现状(务必先读)**:`kRequireEnrollmentToBrowse` 默认 **关闭**(BYOD-first,产品负责人已确认)。本文档下方多处「拦截无法上网」「重新上锁」等描述,**仅在组织显式开启该 gate 时成立**;gate 关闭(默认)时浏览器可正常浏览,纳管改为**自愿**——未纳管 profile 的菜单顶部有常驻「登录」入口,点击后在当前窗口新 tab 打开 enroll 页就地纳管,不阻断浏览、不强制跳转。下文逐条已标注适用的 gate 状态。

## 1. 术语

- **部署域名 D**:浏览器纳管所指向的组织服务器基础域名(如 `acme.internal`)。端点由 D 推导:`teleport.D/{dm,enroll}`、登录 `accounts.D`、per-tenant OP `<slug>.D`。
- **域名来源**(优先级从高到低,`chrome://version` 的「Deployment domain」行显示):
  1. dev 命令行开关(仅开发构建)
  2. 平台管控策略强制值(MDM `DeploymentDomain`,须 `IsForced`)
  3. 机器配置文件(`/Library/Teleport/DeploymentConfig.json`,root 属主)
  4. 用户接受条目(`teleport://connect` 页写入,根签名离线重验)
  5. 烘焙默认(SaaS)

## 2. 私有化 BYOD 自装纳管(无 MDM 的自带设备)

终端用户装通用包后(**以下按组织显式开启强制纳管 gate 描述**;gate 为本文档默认关闭时的行为见步骤后说明):

1. 启动 → 域名解析取烘焙默认(SaaS 域)→ **gate ON 时** enrollment gate 拦截,无法上网(gate 默认关闭时可正常浏览,见下)。
2. 按 IT 文档在地址栏**粘贴**组织提供的连接链接(web 内容无法跳转特权页,必须复制粘贴):
   ```
   teleport://connect?domain=acme.internal
   ```
3. connect 页自动向 `https://teleport.acme.internal/dm/server-identity` 拉取根签名身份 → 校验根签名 + 类型标签 + 域名匹配 + 未过期。
4. 通过 → 点「连接」→ 写入 level-4 自认证条目 → 提示「重启后生效」。
5. 重启 → resolver 离线重验条目 → D=acme.internal → **gate ON 时**跳 `teleport.acme.internal/enroll/start` → OIDC 登录(手机号/邮箱)→ profile 纳管 → 放行。

**connect 页只读的两种情形**(§4.2):
- 更高优先级来源(命令行 / MDM / 机器文件)已设 D:页面拒改并提示「此浏览器已完成纳管,如需更换请联系管理员」——受管设备的 D 由 admin 通道下发,BYOD 自助入口不生效。
- (level-4 / 烘焙默认下页面可写,即上面的自助纳管路径。)

> **gate 默认关闭(本产品当前默认)下的私有化 BYOD 路径**:步骤 1 不拦截、步骤 5 不自动跳转——用户可先正常浏览。IT 文档须显式引导「先完成 `teleport://connect` 设域,再从浏览器 profile 菜单点击顶部『登录』入口纳管」;产品不做 SaaS/私有化自动分流,若用户跳过设域直接点「登录」,纳管会针对当时已解析的 D(可能是烘焙默认 SaaS 域而非组织私有化域),需 IT 培训覆盖此陷阱。
>
> **受管披露文案(跨仓要求)**:自愿纳管(profile 菜单「登录」→ 常规浏览器窗口内新 tab)由客户端复用上游 OIDC 拦截确认对话框呈现「组织将管理此 profile」披露,无需服务端配合;但 gate ON 的强制纳管走 picker 内嵌 enroll 页,**没有 Browser 窗口可锚定该客户端对话框**,其披露责任落在**服务端 enroll 页自身携带的管理声明文案**上——这是对 fairyland 的跨仓交付要求,尚未在私有化交付文档中成文(见 §5 待补)。

## 3. 管理域迁移(§4.5):已纳管浏览器的 D 被改

### 何时触发

已纳管浏览器,**启动解析出的 D ≠ 纳管时的 D**。典型成因:
- MDM 推了错误/新的 `DeploymentDomain` 值;
- 组织做管理域迁移(如 `acme.internal` → `acme-eu.internal`);
- 机器配置文件被改。

### 浏览器的定义行为(自动)

1. 纳管成功时,浏览器已随管理状态持久化「纳管时的 D」。
2. 启动后首个导航前,检测到 `resolved_D ≠ enrolled_D`:
   - **重置该 profile 的纳管状态**(清除 management id)→ `IsEnrolled` 变 false(**无论 gate 是否开启,均执行**);
   - **仅当组织显式开启强制纳管 gate 时**,同步重新上锁(`LockForceSigninProfile`)→ 浏览被拦,跳转到**新 D** 的 `teleport.<新D>/enroll/start` 要求重新纳管;gate 关闭(默认)时不上锁,profile 回到「未纳管」态,菜单顶部重新出现「登录」入口供用户自愿针对新 D 重新纳管;
   - **不**以旧 DM token 半受管运行(旧 token 对新服务器是 DEVICE_NOT_FOUND,会静默失败——本行为消除该僵尸态)。
3. **可见 + 可诊断**:记 ERROR 日志;`chrome://version` 的「Deployment domain」行标注:
   ```
   <新D> (source: <来源>) — changed from <旧D> (re-enrollment required)
   ```
   该标注在重新纳管到新 D 成功前一直显示。

> 说明:客户端在迁移时**已经**调用 `policy::BrowserDMTokenStorage::Get()->ClearDMToken(...)` 清除本机缓存的**机器级(CBCM)DM token**(`teleport_enrollment_gate.cc`),避免用旧 D 签发的 token 对新 D 报 `DEVICE_NOT_FOUND` 静默失败;**后续项**是服务端(fairyland DM 服务)一侧对旧 D 上该机器 DM 记录的孤儿清理/吊销,客户端清除不等于服务端记录已回收。

### 终端用户会看到什么

- **gate ON**:上网被拦、跳到组织登录页(新 D),需按新 D 重新登录纳管一次;
- **gate OFF(默认)**:可继续浏览,profile 菜单顶部的「登录」入口重新出现,提示针对新 D 重新纳管(不强制、不阻断);
- 若新 D 尚不可达(MDM 推错值),会看到无法连接——见下。

### IT 侧协调清单

做管理域迁移时:

1. **先备好新 D 的服务端**(`teleport.<新D>` 可达、身份 blob 已签发、租户/OP 就位),再推 D 变更——避免终端「跳到新 D 却连不上」。
2. 经 admin 通道(MDM `DeploymentDomain` / 机器文件)下发**新 D**;确认 `IsForced`(MDM)或 root 属主 + 非组/全局可写(机器文件),否则不被采信。
3. 通知用户「下次启动需重新登录纳管一次」——**gate ON** 时这是强制的(不纳管无法浏览);**gate OFF(默认)**时这是自愿的,浏览器不阻断,需 IT 主动提醒用户点击菜单「登录」入口重新纳管。
4. 抽查 `chrome://version`:迁移期显示 `changed from <旧D>`;重新纳管成功后该标注消失、来源为新 D。
5. 若为**误推**:改回正确 D 即可;浏览器每次启动按当前解析值判定,改回后不再要求迁移。

### 排障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `chrome://version` 一直显示 `changed from <旧D>` | 尚未对新 D 完成重新纳管 | 引导用户在新 D 登录纳管;确认 `teleport.<新D>` 可达 |
| 跳到 `teleport.<新D>/enroll/start`(gate ON 自动跳转,或 gate OFF 用户点「登录」)但 NXDOMAIN/超时 | 新 D 服务端未就绪或 DNS 未配 | 先备好新 D 服务端再推 D 变更 |
| 推了新 D 但浏览器仍用旧 D | MDM 值非 `IsForced` / 机器文件属主或权限不符 | 按 §2 来源优先级与 D13 校验修正下发方式 |

## 4. 受管设备锁定 enroll 页(§4.6)

enroll 页的「自助换域/解绑」仅对 **BYOD** 开放。**公司设备禁止用户改域**,由两个显式信号判定(命中任一即只读展示当前绑定 + 「由你的组织管理,无法在此更改」,隐藏输入框与按钮):

| 设备形态 | 锁定信号 | IT 配置 |
|---|---|---|
| 私有化/气隙受管 | D 经管控偏好 / 机器文件下发(第 2/3 级) | 下发 D 即自动锁,无需额外配置 |
| SaaS 受管(D=官方默认,有 MDM) | 强制 managed pref `RestrictDeploymentDomainChange=true` | MDM 下发该布尔键(见下) |
| SaaS 受管(D=官方默认,无 MDM) | 机器文件 `restrict_domain_change:true` | 写 `/Library/Teleport/DeploymentConfig.json`(root 属主 + 644),与 forced managed pref 同为 level 4/5 加锁通道,OR 生效(见下) |
| 纯 BYOD | 以上皆无 | 可自助换域 / 解绑 |

> 锁定按**管理员显式声明**判定。**机器级 CBCM 纳管不作自动锁信号**(评估后否决,§4.6):故 CBCM 管理的 SaaS-默认域设备**必须**显式配 `RestrictDeploymentDomainChange`(或域名策略),否则用户可经 enroll 页改域(改后 §4.5 迁移会重纳管,不僵尸态,但等于脱管)。交付时务必对受管客户强调此项。

**`RestrictDeploymentDomainChange`(macOS managed pref)**:
- bundle id `cn.douan.Teleport`,键 `RestrictDeploymentDomainChange`,布尔,**必须 forced**(经 MDM / 配置描述文件下发;普通用户可写偏好不生效,与 `DeploymentDomain` 同一信任门)。
- 适用:使用 SaaS 官方默认域、但通过 MDM 管理设备、且不希望用户改域的租户。**与域名值解耦**——D 仍走烘焙默认,官方域名轮换自动跟随,无需在策略里钉死域名(优于「用域名策略钉官方域」)。

**`restrict_domain_change`(机器文件,无 MDM 的轻量通道)**:
- 与 `domain` 键同一文件 `/Library/Teleport/DeploymentConfig.json`、**同一信任门**(root 属主 + 非组/全局可写);解析走纯函数 `ParseDeploymentConfigFile`。机器文件在**启动期读取一次并进程级缓存**(与 `domain` 同一次 `CachedMachineFile()` 读,避免在 enroll 页的 UI 线程做阻塞文件 IO——那会 DCHECK abort),故**改动机器文件需重启浏览器生效**(与 `domain` 一致;forced managed pref 通道仍 live 生效)。`IsDomainChangeRestrictedByAdmin` 把机器文件 restrict 与 forced pref **OR**。
- 可独立于 `domain` 存在:`{"restrict_domain_change": true}`(不带 domain)让域名留在内置默认(level 5)、但锁定 enroll 页——正是无 MDM 的 SaaS-默认域受管设备所需。
- 设置(需 root,`sudo defaults write` 写不进该目录,直接落文件):
  ```bash
  printf '{"restrict_domain_change": true}\n' | sudo tee /Library/Teleport/DeploymentConfig.json >/dev/null
  sudo chown root:wheel /Library/Teleport/DeploymentConfig.json && sudo chmod 644 /Library/Teleport/DeploymentConfig.json
  ```
- ⚠️ 若同时写了**无效**的 `domain` 值(如带 scheme/path):设备静默落内置默认域并仍被锁(fail-closed),日志有 `WARNING: restrict_domain_change honored but no valid deployment domain`。交付时提示管理员核对 `domain` 为规范 `host[:port]` 形态。

## 5. 待补(后续)

- **fairyland 私有化交付规范 v1**(服务端):`teleport.<D>` 的 Caddyfile 模板化(已具备 `{$BASE_DOMAIN}` 参数化)、身份 blob 的签发/续订/交付(Phase 2a 已实现 mint + `/server-identity`)、根密钥仪式与气隙前置依赖的成文化;私有化交付前对策略验签链吊销/版本单调做 go/no-go 复核(spec §8.4)。交付文档需列 `RestrictDeploymentDomainChange` 锁域键(§4)、「BYOD 先设域后登录」IT 引导文案(§2)、以及 **enroll 页自身携带的受管披露文案**(§2 跨仓要求——gate ON 的 picker 强制纳管无 Browser 锚定客户端披露对话框,依赖服务端页面文案)。
- 机器级(CBCM)DM token 在 §4.5 迁移时的清除(当前迁移清 profile 管理态 + 客户端已 `ClearDMToken`;机器级 token 的完整清理待确认)。
