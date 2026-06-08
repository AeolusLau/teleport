# Phase 4 客户端实现计划 · 安全事件 Reporting(teleport overlay)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已纳管 Teleport 把安全事件经 Chrome 原生 realtime reporting 上报到 fairyland——**薄 patch**(重指 reporting 端点默认值)+ 经 Phase 3 策略下发 `OnSecurityEventEnterpriseConnector` 启用,端到端活验。

**Architecture:** reporting 是原生能力(`RealtimeReportingClient`),由连接器策略启用、上报到 reporting server URL。客户端仅:① patch 两个 reporting URL 默认值 → fairyland(`teleport::` 常量);② 经服务端下发连接器策略启用;③ e2e。

**Tech Stack:** Chromium M148 overlay;dev 构建 + docker.lima fairyland 栈。

**上位文档:** phase 权威 + 客户端 spec `docs/superpowers/specs/2026-06-08-enterprise-alignment-phase4-security-reporting-design.md`;服务端 plan(主要工作)fairyland `.../plans/2026-06-08-...-security-reporting-server.md`。

**分支/worktree:** teleport `worktree-chrome-enterprise-alignment`。**前置**:fairyland server-plan 已落(reporting ingest 端点 + `OnSecurityEventEnterpriseConnector` catalog 条目)。

---

## 关键事实(已核实于 M148)
- reporting 两端点默认值在 `components/policy/core/browser/browser_policy_connector.cc`:`kDefaultRealtimeReportingServerUrl`(`.../v1/events`,行 ~53)+ `kDefaultEncryptedReportingServerUrl`(`.../v1/record`,行 ~50),均 `chromereporting-pa.googleapis.com`。stable/beta 忽略命令行 switch → 改**默认值**(延续 Phase 0/1 DM-URL 手法)。
- teleport 已有 `patches/components/policy/core/browser/browser_policy_connector.cc.patch`(Phase 0/1 的 DM URL)。**一文件一 patch**:reporting URL 改动累加进这同一个 patch 文件。
- 启用上报 = 下发 `OnSecurityEventEnterpriseConnector`(StringPolicyProto=701,JSON 值),经 Phase 3 `SetTenantPolicy`(server-plan 已加 catalog 条目)。
- `RealtimeReportingClient` 上报路径疑似非品牌门控(Task 2 核查,似 Phase 2)。

---

## Task 1: patch reporting 端点默认值 → fairyland

**Files:** Modify `patches/components/policy/core/browser/browser_policy_connector.cc.patch`(累加);可能 Modify `src/common/teleport_*`(若放 `teleport::` 常量)

- [ ] **Step 1: 定常量值**

确定 fairyland reporting 端点(与 server-plan Task 4 注册的路径一致,经同一 Caddy host)。如:realtime = `https://dm.teleport.fairyland.io/v1/events`、encrypted = `https://dm.teleport.fairyland.io/v1/record`。(与 server-plan 实测路径对齐。)

- [ ] **Step 2: 扩 patch(改两默认值)**

在 chromium 检出编辑 `browser_policy_connector.cc` 的 `kDefaultRealtimeReportingServerUrl` + `kDefaultEncryptedReportingServerUrl` 值 → fairyland URL(引用 `teleport::` 常量或直接内置常量,与现有 DM-URL patch 同风格)。`git diff` 重生成累加进 `browser_policy_connector.cc.patch`;`git checkout --` 还原检出;`python scripts/apply_patches.py`(幂等)。`git apply --reverse --check`(从检出目录)自检 REVERSE-OK。

- [ ] **Step 3: 构建 + Commit**

`autoninja -C out/mac/arm64/dev chrome`(暖缓存);commit patch。

---

## Task 2: 非品牌门控核查(决定是否需额外 patch)

- [ ] **Step 1: 静态核查**

Run(chromium 检出):
```bash
grep -rnE 'GOOGLE_CHROME_BRANDING|is_chrome_branded' \
  chrome/browser/enterprise/connectors/reporting/realtime_reporting_client*.cc \
  chrome/browser/enterprise/connectors/reporting/realtime_reporting_client_factory.cc \
  | grep -viE 'unittest|browsertest' | head
```
判定:若 `RealtimeReportingClient` 创建/上报路径被 `#if BUILDFLAG(GOOGLE_CHROME_BRANDING)` 包裹 → 需薄 patch 解门控;若仅单测 brand 分支 → 无需(记「非品牌门控,零额外 patch」)。

- [ ] **Step 2: 动态确认(Task 3 e2e 时)**

若静态判「未门控」,e2e 启动后日志 grep 确认 reporting client 启用 + 上报触发。若静态判「门控」→ 补薄 patch(仿 Phase 1 `chrome_browser_cloud_management_controller.cc` 非品牌返 true 手法),累加进对应 patch。Commit(若有)。

---

## Task 3: 端到端活验(真浏览器 × device-manager)

**Files:** 无源码改动。前置:fairyland server-plan 全部完成 + device-manager 跑分支码(Phase 2 override)+ 机器已纳管。

- [ ] **Step 1: 环境就绪 + 下发连接器策略**

device-manager 跑分支码(`docker.lima compose ... -f docker-compose.phase2-worktree.override.yml ... up -d --force-recreate teleport-device-manager`)。经 Phase 3 admin API 下发连接器策略(machine scope),启用安全事件上报:
```bash
PROTO=/Users/liulichao/workspace/fairyland/.claude/worktrees/chrome-enterprise-alignment/proto
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d '{"tenant_id":"11111111-1111-1111-1111-111111111111","scope":"machine","name":"OnSecurityEventEnterpriseConnector","value":"[{\"service_provider\":\"google\",\"enabled_event_names\":[\"browserExtensionInstallEvent\"]}]","mode":"mandatory"}' \
  localhost:19090 teleport.v1.DeviceManagerControlService/SetTenantPolicy
```
> 连接器 JSON 的精确字段(`service_provider`/`enabled_event_names`/`enabled_opt_in_events`)e2e 阶段按真浏览器接受的格式微调(承教训:e2e 定;先试上述,看 chrome://policy 是否生效)。

- [ ] **Step 2: 启动浏览器 + 触发事件**

启动 dev 构建(机器纳管 profile)+ `--enable-logging=stderr --v=1 --vmodule='*reporting*=2,realtime_reporting_client=2'`。chrome://policy 确认 `OnSecurityEventEnterpriseConnector` 已下发。**触发一个事件**:安装一个扩展(对应 `browserExtensionInstallEvent`),或换其它已启用且易触发的事件。

- [ ] **Step 3: 客户端侧确认上报已发**

```bash
grep -aiE 'realtime_reporting|UploadSecurityEvent|/v1/events|UploadEventsRequest|reporting' /tmp/teleport-phase4-reporting.log | head
```
期望:见上报 POST 到 `dm.teleport.fairyland.io` 的 reporting 路径(携 GoogleDMToken)。

- [ ] **Step 4: 服务端侧确认 ingest + 控制面可见**

```bash
docker.lima logs teleport-device-manager 2>&1 | grep -iE 'security|reporting|UploadEvents' | tail
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d '{"tenant_id":"11111111-1111-1111-1111-111111111111","limit":20}' \
  localhost:19090 teleport.v1.DeviceManagerControlService/ListSecurityEvents
```
期望:`ListSecurityEvents` 含刚触发的事件(event_type、payload、received_at)。

- [ ] **Step 5: 记录证据**

客户端日志关键行 + `ListSecurityEvents` 输出写进验证笔记。关浏览器只 kill 主 PID(勿 `pkill -f <profile>`)。

---

## 完成标准(DoD)
- [ ] reporting 两端点默认值 → fairyland(累加进 browser_policy_connector.cc patch);门控判定明确(零额外 patch 或薄 patch)。
- [ ] 端到端:下发连接器策略 → 触发事件 → 上报到 fairyland → device-manager ingest → `ListSecurityEvents` 可见。
- [ ] 证据归档。

## 风险 / 未决
- 连接器策略 JSON 精确格式(e2e 定)。
- 哪些事件 dev/非品牌构建实际触发(选最易触发者;扩展安装通常可靠)。
- proto vs deprecated JSON 上报路径(server-plan Task 1 已定;此处只验上报实达)。
- reporting 端点路径需与 server-plan 注册一致(同 Caddy host)。

## 参考
- phase 权威 + 客户端 spec:`.../specs/2026-06-08-enterprise-alignment-phase4-security-reporting-design.md`。
- 服务端 plan:fairyland `.../plans/2026-06-08-...-security-reporting-server.md`。
- Phase 0/1 DM-URL patch 范式:`patches/components/policy/core/browser/browser_policy_connector.cc.patch`。
- Phase 3 SetTenantPolicy + override 技巧:仓库记忆 + `docs/policy-admin.md`(fairyland)。
