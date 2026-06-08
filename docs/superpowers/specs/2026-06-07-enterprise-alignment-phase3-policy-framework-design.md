# Phase 3 设计 · 策略框架用起来(客户端侧)

- 状态:已评审(设计)
- 日期:2026-06-07
- 范围:跨 `teleport`(客户端)与 `fairyland`(服务端)两仓
- 本文归属:**Phase 3 phase 权威 + 客户端侧设计**。服务端侧(本 phase 主要工作)见 fairyland 配对 spec(§8)。
- 上位文档:总纲 `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md` 的 **Phase 3**。
- 分支/worktree:`worktree-chrome-enterprise-alignment`(teleport + fairyland 同名配对)。

> 承接 Phase 1(机器 CBCM 纳管已点亮活验)、Phase 2(设备状态回报已活验)。Phase 3 把**策略编码从 4 条硬编码扩展成目录驱动的可运营体系**(重头在 fairyland),并让管理员经控制面配置策略、端到端下发到已纳管设备,`chrome://policy` 正确展示来源/级别/冲突且无 Google 穿帮。

## 1. 目标

把策略框架真正用起来:服务端建**策略目录(catalog)+ admin gRPC 配置 API + 注册表驱动编码**(详见 fairyland spec);客户端**近零 patch**——`chrome://policy` 品牌 sweep + 端到端验证云策略下发、mandatory/recommended 级别展示、与 Platform 策略的合并/冲突展示正确。

## 2. 范围边界

**In**
- 客户端:`chrome://policy` 企业串品牌 sweep(清扫 "Chrome"/"Google" 企业措辞,如 "Chrome Browser Cloud Management");端到端活验目录驱动下发链路。
- 服务端(详见 fairyland spec):策略目录 + 通用 payload + 注册表编码 + admin gRPC API(`ListPolicyCatalog`/`Get`/`Set`/`Remove` TenantPolicies),据目录强校验,支持 mandatory + recommended。

**Out(后续 phase)**
- Web 控制台 UI(本轮 admin gRPC API 为主,grpcurl 驱动;Web 面后置独立轮)。
- 通用反射映射全量 1000+ 策略(本轮目录驱动 + 精选种子集,加策略=加注册条目)。
- Data Controls / Watermark 等控件簇策略(Phase 5/6)。

## 3. 关键决策(本轮已拍板)

1. **目录驱动注册表**(服务端):catalog 是校验 schema + 编码器 + scope + 允许 mode 的单一事实源;加一条策略 = 加一个注册条目,不再「改 4 处」。
2. **通用 payload(policy map)**:`policy_assignments.payload` 从命名字段 → `{ domain, username, policies: { <PolicyName>: { value, mode } } }`。
3. **支持 mandatory + recommended**:目录条目声明允许 mode;编码器据此设 `PolicyOptions.Mode`;`chrome://policy` 原生展示 level。
4. **配置面 = admin gRPC API(本轮不做 Web UI)**:沿用前两 phase grpcurl 驱动节奏。
5. **首批种子集 = 安全/认证 + 浏览器 UX/主页**:覆盖 String/Bool/Integer(enum)/StringList 四种 PolicyProto 包装型。
6. **客户端近零 patch**:云策略 fetch、mandatory/recommended 级别、来源/冲突展示均为 Chrome 原生能力(已核实于 M148);客户端仅品牌 sweep + e2e。

## 4. 客户端设计(近零 patch)

### 4.1 无新增功能 patch / 无新增 `//teleport` 源码

- 云策略下发链路 Phase 1 已点亮:机器 `register_browser` → 机器 DMToken → `?request=policy` 拉签名 `CloudPolicySettings` → 客户端原生消费。Phase 3 只是让服务端**编码更多策略字段 + 支持 recommended mode**,客户端原生解析,无需改动。
- mandatory/recommended:Chrome 原生按 `PolicyOptions.Mode` 区分 enforced vs recommended,`chrome://policy` 原生展示 "Mandatory"/"Recommended" level——无客户端改动。
- 与 Platform(MDM Configuration Profile)策略的合并/冲突:Chrome 原生 `PolicyService` 合并多来源,`chrome://policy` 原生展示来源(Cloud / Platform)+ 冲突标记——无客户端改动。

### 4.2 chrome://policy 品牌 sweep(唯一客户端改动)

- 复用既有 `branding_strings.py` + `.grd/.xtb` rebrand 路径,清扫 `chrome://policy` 页面与相关字符串里的企业措辞:`IDS_POLICY_*` 中暴露 "Chrome" / "Google" / "Chrome Browser Cloud Management" 等。
- 两层品牌不变:磁盘标识 `Teleport`、应用内显示 `闪现`。
- 若个别串只能经 `.grd` message 覆盖(非 branding_strings.py sweep 范围),按既有 per-capability 收口补最小 patch;**保留 plan 阶段实测确认实际暴露的串清单**(承 Phase 1 教训:管理面字符串要真机肉眼扫,自动 grep 易漏 WebUI 渲染串)。

### 4.3 plan 阶段必须验证(客户端)

- **下发实达**:admin API 配的策略(machine + user + 一条 recommended)经 `?request=policy` 实际下发,`chrome://policy` 可见且值正确。
- **level 展示**:recommended 策略在 `chrome://policy` 显 "Recommended"、mandatory 显 "Mandatory"。
- **来源/冲突**:云策略来源显 "Cloud";若同时有 Platform 策略,合并/冲突展示正确。
- **品牌**:`chrome://policy`(及 `chrome://management`,Phase 1 已 sweep)无 Google 穿帮。

## 5. 协议 / 数据流(已核实于 M148 检出)

```
admin(grpcurl)→ device-manager: SetTenantPolicy(tenant, scope, name, value, mode)
 → 据 Catalog 校验 → policy_assignments.payload.policies[name] = {value, mode}

浏览器(已机器纳管)→ ?request=policy (GoogleDMToken)   [Phase 1 既有]
 → device-manager: BuildSettings(scope, policies) 注册表编码 → 签名 CloudPolicySettings → status=0
 → 客户端原生消费;chrome://policy 展示 来源=Cloud、level=Mandatory/Recommended、合并/冲突
```

## 6. 客户端 patch 总览

| 目标 | 改动 | 类型 |
|---|---|---|
| `chrome://policy` 企业串 | 品牌 sweep(`.grd/.xtb` + branding_strings.py;残留串最小 patch) | 字符串/品牌 |

> 无新增功能 patch、无新增 `//teleport` 源码。功能全在 fairyland(目录 + API + 编码)。

## 7. 测试(客户端)

- 客户端无新增单测(零功能源码;品牌 sweep 走既有 rebrand 校验)。
- 端到端活验(dev 构建 + docker.lima):admin API 配策略(覆盖 string/bool/int_enum/string_list + mandatory/recommended)→ 等待/触发 policy fetch → `chrome://policy` 验证值、level、来源、合并/冲突、品牌。

## 8. 跨仓协作

- **配对 spec(服务端,主要工作)**:fairyland `docs/superpowers/specs/2026-06-07-enterprise-alignment-phase3-policy-framework-server-design.md`。
- **契约**:DM 线协议 = vendor 的 Chromium `cloud_policy.proto`(本轮按上游字段号补 `CloudPolicySettings` 种子集子集);控制面 admin 策略配置 API 在 fairyland `proto/teleport/v1`。
- **执行**:客户端近零,几乎全在 fairyland;契约(目录 + admin API + vendored 字段)先定,之后各自 plan + 实施,最后 docker.lima 整体联调。

## 9. 风险 / 未决

- `chrome://policy` 实际暴露的企业品牌串清单(plan 阶段真机肉眼扫确认)。
- recommended 策略客户端行为:个别上游策略 `can_be_recommended:false`,强发 recommended 可能被忽略/降级(服务端目录据上游约束限制 `AllowedModes`,见 fairyland spec)。
- 合并/冲突场景需构造 Platform 策略(`.mobileconfig` 或 managed pref)与云策略同 key 才能验证冲突展示;若本轮不具备 MDM 环境,至少验证云策略单来源 + level 展示。

## 10. 参考

- 总纲:`docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`(Phase 3)。
- Phase 1:`.../2026-06-04-enterprise-alignment-phase1-device-enrollment-design.md`(纳管 + 签名策略下发)。
- Phase 2:`.../2026-06-05-enterprise-alignment-phase2-device-status-design.md`(设备状态回报)。
- 配对(服务端):fairyland `.../2026-06-07-enterprise-alignment-phase3-policy-framework-server-design.md`。
