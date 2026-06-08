# Phase 3 客户端实现计划 · 策略框架用起来(teleport overlay)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 客户端**近零 patch**——把 `chrome://policy` UI 外壳暴露的 Chrome/Google 企业品牌串收口为 Teleport/闪现,并端到端活验 fairyland 目录驱动策略下发(值/level/来源展示正确)。

**Architecture:** 云策略 fetch、mandatory/recommended 级别、来源/冲突展示均为 Chrome 原生能力(Phase 1 已点亮链路);Phase 3 服务端只是编码更多策略字段 + 支持 recommended,客户端原生消费。唯一客户端改动 = `chrome://policy` 页面外壳串的针对性品牌 patch(**不** rebrand 海量 per-policy 描述文档)。

**Tech Stack:** Chromium M148 overlay;`components/policy_strings.grdp`(+ zh `.xtb`);dev 构建 + docker.lima fairyland 栈。

**上位文档:** phase 权威 + 客户端 spec `docs/superpowers/specs/2026-06-07-enterprise-alignment-phase3-policy-framework-design.md`;服务端 plan(主要工作)fairyland `docs/superpowers/plans/2026-06-07-enterprise-alignment-phase3-policy-framework-server.md`。

**分支/worktree:** teleport `worktree-chrome-enterprise-alignment`。**前置**:fairyland server-plan 已落(device-manager 能经 admin API 配策略 + 目录驱动编码下发)。

---

## 关键事实(已核实于 M148 检出)

- **零功能 patch**:云策略下发链路 Phase 1 已活验(机器 `register_browser` → DMToken → `?request=policy` → 签名 `CloudPolicySettings` → 客户端原生消费);Phase 3 服务端加策略字段 + recommended mode,客户端**原生解析,无需改动**。
- **mandatory/recommended**:Chrome 原生按 `PolicyOptions.Mode` 区分 enforced vs recommended,`chrome://policy` 原生展示 "Mandatory"/"Recommended" level——无客户端改动。
- **chrome://policy 文案位置**:`components/policy_strings.grdp`。其中**绝大多数是 per-policy 描述文档**(含大量 "Google Chrome",是文档面,**不 rebrand**);只有少量 **UI 外壳串**(页面标题、状态框标签、来源/scope 标签如 "Chrome Browser Cloud Management")需收口。
- **现有 branding sweep 不覆盖此处**:`scripts/branding_strings.py` 只扫 `chromium_strings.grd` 且 `_CHROME_KEEP` **故意保留** "Chrome Browser Cloud Management"。故本 phase 走**针对性 .grdp patch**(一文件一 patch,镜像 `components/policy_strings.grdp` 路径),不扩 branding_strings.py。
- **Phase 1 已有 policy patch**:`patches/components/policy/...`(`status_box.html.patch`、`machine_level_user_cloud_policy_status_provider.cc.patch` 等)。chrome://policy 渲染已不崩。
- **教训(Phase 1)**:点亮的管理面要**真机肉眼扫**——自动 grep 漏 WebUI 渲染串。故 Task 1 先开真页面枚举,再针对性 patch。
- **构建**:`cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome`(暖缓存约分钟级,见仓库记忆);apply_patches 幂等。
- **跑分支服务端**:用 Phase 2 的 compose override 技巧让 docker.lima 的 `teleport-device-manager` 跑 worktree 分支码(不扰 seed 数据);见 server-plan / Phase 2 文档。

---

## Task 1: chrome://policy 品牌 sweep(枚举 → 针对性 patch)

**Files:**
- 调查(只读 + 真机):`chrome://policy` 渲染页面、`components/policy_strings.grdp`
- Create(按枚举结果):`patches/components/policy_strings.grdp.patch`
- 可能 Modify:对应 zh `.xtb`(若外壳串有中文翻译条目)

- [ ] **Step 1: 构建并打开 chrome://policy,枚举暴露的 Chrome/Google 外壳串**

前置:apply_patches 幂等应用,dev `chrome` 已构建。启动(机器已纳管,见 Phase 1):

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport --no-proxy-server \
  --user-data-dir=/tmp/teleport-phase3-profile --enable-logging=stderr --v=1 &
```

在浏览器打开 `chrome://policy`。**肉眼枚举** UI 外壳上出现 "Chrome"/"Google" 的位置(预期候选:页面标题/副标题、status box 的 "Chrome Browser Cloud Management" 标签、"Policies apply to..." 说明、Reload/Export 区的措辞)。把每条实际文案记成清单。**只记 UI 外壳串,不记 per-policy 描述列。**

- [ ] **Step 2: 定位每条外壳串的 grdp message name**

对清单每条文案,在 grdp 里反查 message name:

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
grep -nE 'Chrome Browser Cloud Management|name="IDS_POLICY_(HEADER|DM_STATUS|STATUS|SHOW|FILTER|LABEL)' \
  components/policy_strings.grdp | head -40
# 对每条肉眼文案精确定位:
grep -n '<exact visible substring>' components/policy_strings.grdp
```

产出:`{message name → 现文案 → 目标文案}` 映射(英文外壳串改 "Chrome"/"Chrome Browser Cloud Management" → "Teleport"/"Teleport 云管理" 等;品牌规则同既有两层品牌:磁盘标识 Teleport、应用内显示 闪现)。

- [ ] **Step 3: 应用最小修改并生成 patch**

直接编辑 `components/policy_strings.grdp` 的目标 message 体(仅 Step 2 清单内的外壳串),然后用仓库既有方式抽成 patch(镜像路径 `patches/components/policy_strings.grdp.patch`):

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
git -C "$TELEPORT_CHROMIUM_DIR/src" diff -- components/policy_strings.grdp \
  > /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment/patches/components/policy_strings.grdp.patch
```

> 一文件一 patch:本 patch 只改 `policy_strings.grdp`。若某外壳串有 zh `.xtb` 翻译条目需同步,另起 `patches/components/policy_strings_zh-CN.xtb.patch`(独立文件、独立 patch)。

- [ ] **Step 4: 自检 patch 可逆 + 重新应用**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
git apply --reverse --check -p1 --directory="$TELEPORT_CHROMIUM_DIR/src" patches/components/policy_strings.grdp.patch && echo "REVERSE-OK"
python scripts/apply_patches.py   # 幂等重应用全量 overlay
```
Expected: `REVERSE-OK`;apply_patches 无冲突。

- [ ] **Step 5: 重建并真机验证收口**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport --no-proxy-server \
  --user-data-dir=/tmp/teleport-phase3-profile &
```
打开 `chrome://policy`,确认 Step 1 清单的每条外壳串已收口、无 Chrome/Google 穿帮;per-policy 描述列保持原状(预期、不动)。

- [ ] **Step 6: Commit**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
git add patches/components/policy_strings.grdp.patch   # + 可能的 xtb patch
git commit -m "feat(enterprise): brand chrome://policy UI shell strings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

> 若 Step 1 枚举发现 chrome://policy 外壳**已无** Chrome/Google 穿帮(Phase 1 的 status_box patch 已覆盖),则本 task 无 patch:记录「chrome://policy 外壳串已洁净,零 patch」并跳到 Task 2。

---

## Task 2: 端到端活验(目录驱动下发 → chrome://policy)

**Files:** 无源码改动。前置:fairyland server-plan 全部完成 + device-manager 跑分支码 + 机器已纳管。

- [ ] **Step 1: 环境就绪(device-manager 跑分支码)**

按 Phase 2 override 技巧让 docker.lima 的 `teleport-device-manager` 跑 worktree 分支码(目录注册表 + admin API),不扰 seed:

```bash
cd /Users/liulichao/workspace/fairyland
docker.lima compose -f docker-compose.control-plane.yml \
  -f docker-compose.phase2-worktree.override.yml \
  --project-directory /Users/liulichao/workspace/fairyland \
  up -d --no-deps --force-recreate teleport-device-manager
docker.lima logs teleport-device-manager 2>&1 | tail -20   # 确认启动 + migrate
```

- [ ] **Step 2: 经 admin API 配置 machine 策略(覆盖 string_list + int_enum + recommended)**

```bash
PROTO=/Users/liulichao/workspace/fairyland/proto
SVC=teleport.v1.DeviceManagerControlService
TENANT=11111111-1111-1111-1111-111111111111

# 目录可见
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  localhost:19090 $SVC/ListPolicyCatalog | head -40

# string_list (mandatory)
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d "{\"tenant_id\":\"$TENANT\",\"scope\":\"machine\",\"name\":\"URLBlocklist\",\"value\":[\"evil.example.com\"],\"mode\":\"mandatory\"}" \
  localhost:19090 $SVC/SetTenantPolicy

# int_enum (recommended)
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d "{\"tenant_id\":\"$TENANT\",\"scope\":\"machine\",\"name\":\"SafeBrowsingProtectionLevel\",\"value\":2,\"mode\":\"recommended\"}" \
  localhost:19090 $SVC/SetTenantPolicy

# 重设 Phase 1/2 既有策略以防迁移回归
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d "{\"tenant_id\":\"$TENANT\",\"scope\":\"machine\",\"name\":\"CloudReportingEnabled\",\"value\":true,\"mode\":\"mandatory\"}" \
  localhost:19090 $SVC/SetTenantPolicy

# 回读确认
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d "{\"tenant_id\":\"$TENANT\",\"scope\":\"machine\"}" \
  localhost:19090 $SVC/GetTenantPolicies
```
Expected:`ListPolicyCatalog` 列出 11 条;`Set*` 均 200;`GetTenantPolicies` 回读到 URLBlocklist/SafeBrowsingProtectionLevel/CloudReportingEnabled。

- [ ] **Step 3: 重启浏览器拉策略**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
rm -f /tmp/teleport-phase3.log
out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport --no-proxy-server \
  --user-data-dir=/tmp/teleport-phase3-profile \
  --enable-logging=stderr --v=1 --vmodule='cloud_policy_client=2,device_management_service=2' \
  > /tmp/teleport-phase3.log 2>&1 &
```
(机器策略 status=0 carrying 新字段;若 DMToken 已缓存则直接 fetch policy。)

- [ ] **Step 4: chrome://policy 验证值 + level + 来源**

打开 `chrome://policy`,确认:
- `URLBlocklist` = `["evil.example.com"]`,level = **Mandatory**,来源 = **Cloud**(或 Platform/Cloud 合并视来源);
- `SafeBrowsingProtectionLevel` = `2`,level = **Recommended**;
- `CloudReportingEnabled` = `true`(Phase 2 不回归);
- 各策略 source/scope 展示正确,**无 Chrome/Google 穿帮**(Task 1 收口生效)。

日志旁证:
```bash
grep -aiE "request=policy|Policy fetch succeeded|status = 0|URLBlocklist|SafeBrowsing" /tmp/teleport-phase3.log | head
```

- [ ] **Step 5: (可选)冲突/合并验证**

若具备 MDM 环境:推一条同名 Platform 策略(`.mobileconfig` 到 `com.beansec.Teleport` 域,如 `URLBlocklist`)与云策略冲突,确认 `chrome://policy` 展示双来源 + 冲突标记 + 生效优先级正确。无 MDM 环境则跳过(记录「云策略单来源 + level 已验,冲突展示待 MDM 环境」)。

- [ ] **Step 6: 记录验证证据**

把 `GetTenantPolicies` 输出 + `chrome://policy` 截图/文案 + 日志关键行写进 PR/验证笔记。**关闭浏览器只 kill 主进程 PID**(勿 `pkill -f <profile>`,会 SIGTERM 子进程触发 footer teardown DCHECK,见仓库记忆)。

---

## 完成标准(DoD)

- [ ] `chrome://policy` UI 外壳串无 Chrome/Google 穿帮(针对性 .grdp patch,或确认已洁净零 patch);per-policy 描述文档保持原状。
- [ ] 端到端:admin API 配 machine 策略(string_list mandatory + int_enum recommended + 既有 bool)→ 原生下发 → `chrome://policy` 见值 + 正确 level(Mandatory/Recommended)+ 来源(Cloud);Phase 1/2 既有策略不回归。
- [ ] 验证证据归档。

## 风险 / 未决

- chrome://policy 实际暴露的外壳串清单只能真机枚举(Task 1 Step 1);可能 Phase 1 已基本覆盖 → 本轮零 patch。
- recommended 客户端行为:个别策略上游 `can_be_recommended:false`,强发 recommended 可能被忽略;服务端目录已据常识限制 `AllowedModes`,e2e 若发现降级回填服务端条目。
- 冲突/合并展示需 MDM 环境构造 Platform 策略;无环境则本轮只验云策略单来源 + level。

## 参考

- phase 权威 + 客户端 spec:`docs/superpowers/specs/2026-06-07-enterprise-alignment-phase3-policy-framework-design.md`。
- 服务端 plan(主要工作):fairyland `docs/superpowers/plans/2026-06-07-enterprise-alignment-phase3-policy-framework-server.md`。
- Phase 1 policy patches:`patches/components/policy/...`。
- override 技巧 + 关浏览器注意:仓库记忆(Phase 2 e2e)。
