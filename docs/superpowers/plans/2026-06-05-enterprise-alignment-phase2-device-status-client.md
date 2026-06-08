# Phase 2 客户端实现计划 · 设备状态回报(teleport overlay)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已机器纳管的 Teleport 经策略开启并向 fairyland device-manager 上报 `ChromeDesktopReport`;客户端**默认零 patch**(原生 `ReportScheduler` 驱动),仅在确认上报路径被品牌门控时补一处薄 patch。

**Architecture:** 上报是 Chromium 原生能力(`ReportScheduler` + `UploadChromeDesktopReport`),由策略 `CloudReportingEnabled` 开启;该策略值由 device-manager 编进机器策略(服务端 plan)。客户端本计划=**验证 + 端到端活验**,外加一处条件 patch。

**Tech Stack:** Chromium M148 overlay;dev 构建 + docker.lima fairyland 栈。

**上位文档:** phase 权威 + 客户端 spec `docs/superpowers/specs/2026-06-05-enterprise-alignment-phase2-device-status-design.md`;服务端 plan(主要工作)fairyland `docs/superpowers/plans/2026-06-05-enterprise-alignment-phase2-device-status-server.md`。

**分支/worktree:** teleport `worktree-chrome-enterprise-alignment`。**前置**:fairyland server-plan 已落(device-manager 能 ingest `ChromeDesktopReport` + 机器策略可带 `CloudReportingEnabled`)。

---

## 关键事实(已核实于 M148 检出)
- 上报机制:`CloudPolicyClient::UploadChromeDesktopReport`(request_type = `request=` query 值 `chrome_desktop_report`,snake_case,`cloud_policy_constants.cc` 的 `kValueRequestChromeDesktopReport`;DM 协议),由 `components/enterprise/browser/reporting/report_scheduler.cc` 的 `ReportScheduler` 触发,门控于 pref `kCloudReportingEnabled`(策略 `CloudReportingEnabled`,默认 false、机器作用域、**策略本身无品牌门控**)。
- DM 端点:`UploadChromeDesktopReport` 走 `DeviceManagementService` 的 DM server URL = 已 patch 的 fairyland 默认值(Phase 0/1 `browser_policy_connector.cc` buildflag),无需再改。
- 已知:`browser_report_generator_unittest.cc` 有 `GOOGLE_CHROME_BRANDING` guard——需确认那是**断言差异**(branded vs not 的期望值)还是**运行时禁用**。

---

## Task 1: 核查上报路径非品牌门控(决定是否需 patch)

**Files:**
- 调查(只读):`chrome/browser/enterprise/reporting/*.cc`、`components/enterprise/browser/reporting/report_scheduler.cc`、报告生成器、`ReportingDelegateFactory` 注册点。
- 可能 Create: `patches/<mirror-path>.patch`(仅当确认被品牌门控)。

- [ ] **Step 1: 静态核查门控**

Run(在 chromium 检出):
```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
grep -rnE "GOOGLE_CHROME_BRANDING|is_chrome_branded|enable_chrome_enterprise" \
  chrome/browser/enterprise/reporting/ components/enterprise/browser/reporting/ \
  | grep -viE "unittest|browsertest" | head -30
# 报告基础设施初始化点(ReportScheduler/Generator 是否在非品牌构建创建)
grep -rnE "ReportScheduler|ReportingDelegateFactory|BrowserReportGenerator|InitializeReporting|kCloudReportingEnabled" \
  chrome/browser/enterprise/reporting/reporting_delegate_factory_*.cc chrome/browser/browser_process_impl.cc 2>/dev/null | head
```
判定:若 `ReportScheduler`/报告生成器的**创建/上报路径**被 `#if BUILDFLAG(GOOGLE_CHROME_BRANDING)` 包裹 → 需 patch 解门控;若仅单测里有 brand 分支(断言差异)→ 无需 patch。

- [ ] **Step 2: 动态验证(dev 构建)**

> 若 Step 1 判定「未门控」,本步用真构建确认(避免漏判)。前置:Task 2 的环境(机器纳管 + CloudReportingEnabled 下发)。在 Task 2 启动浏览器后,日志 grep:
```bash
grep -aiE "ReportScheduler|CloudReporting|ChromeDesktopReport|UploadReport|reporting" /tmp/teleport-phase2.log | head
```
期望:见 ReportScheduler 启用 + 触发上报。若**完全无**(且策略确已下发)→ 回 Step 1 判定门控、补 patch。

- [ ] **Step 3:(条件)补薄 patch 解门控**

仅当确认被品牌门控:在对应文件(如报告 delegate 工厂或 scheduler 创建处)patch 掉 `GOOGLE_CHROME_BRANDING` 门控(仿 Phase 1 `chrome_browser_cloud_management_controller.cc` 的非品牌分支返 true 手法),`patches/` 一文件一 patch + `git apply --reverse --check` 自检。**若无需 patch,跳过本步并记录「上报路径非品牌门控,零 patch」。**

- [ ] **Step 4: 提交(若有 patch)**

```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/chrome-enterprise-alignment
git add patches/...
git commit -m "feat(enterprise): enable CBCM browser reporting in unbranded build

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
若无 patch,本计划无 teleport 源码改动(仅验证 + e2e)。

---

## Task 2: 端到端活验(真浏览器 × device-manager)

**Files:** 无源码改动。前置:fairyland server-plan 全部完成 + Task 7 容器重建 + CloudReportingEnabled 已下发。

- [ ] **Step 1: 环境就绪**

- fairyland 栈 device-manager 跑新代码(server-plan Task 7)。
- 租户(`11111111-...`)机器 policy_assignment 已含 `cloud_reporting_enabled: true`(server-plan Task 7 Step 2)。
- 机器已纳管(Phase 1;若 DMToken 缓存被清,重启会重新 register)。

- [ ] **Step 2: 启动 dev 构建并拉策略 + 触发上报**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
rm -f /tmp/teleport-phase2.log
out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport --no-proxy-server \
  --user-data-dir=/tmp/teleport-phase2-profile \
  --enable-logging=stderr --v=1 \
  --vmodule='cloud_policy_client=2,*report*=2,device_management_service=2' \
  > /tmp/teleport-phase2.log 2>&1 &
```
浏览器启动 → 机器策略拉到 `CloudReportingEnabled=true` → `ReportScheduler` 启动首轮上报。`ReportScheduler` 启动后通常有首轮上报;若需更快,可在浏览器活动一会儿后观察。

- [ ] **Step 3: 客户端侧确认上报已发**

```bash
grep -aE "request=chrome_desktop_report|chrome_desktop_report|UploadChromeDesktopReport|dm.teleport.fairyland.io.*chrome_desktop_report" /tmp/teleport-phase2.log | head
```
期望:见 `?request=chrome_desktop_report` POST 到 `dm.teleport.fairyland.io`(携 `GoogleDMToken` + `deviceid`)。

- [ ] **Step 4: 服务端侧确认收到 + 控制台可见(见 server-plan Task 7 Step 4)**

```bash
docker.lima logs teleport-device-manager 2>&1 | grep -i "chrome_desktop_report" | tail
grpcurl -plaintext -import-path /Users/liulichao/workspace/fairyland/proto -proto teleport/v1/device_manager.proto \
  -d '{"tenant_id":"11111111-1111-1111-1111-111111111111"}' \
  localhost:19090 teleport.v1.DeviceManagerControlService/ListEnrolledDevices
```
期望:`ListEnrolledDevices` 该设备的 `browser_version`/`os_name`/`os_version`/`serial_number`/`last_report_at` 非空。

- [ ] **Step 5: 记录验证证据**

把客户端日志关键行 + `ListEnrolledDevices` 输出写进 PR/验证笔记。

---

## 完成标准(DoD)
- [ ] 上报路径门控判定明确:非门控(零 patch)或已补薄 patch。
- [ ] 端到端:dev 构建拉到 `CloudReportingEnabled` → 原生上报 `?request=chrome_desktop_report` 到 fairyland → device-manager ingest → `ListEnrolledDevices` 见版本/OS/序列号/last-seen。

## 风险 / 未决
- 上报触发时机:`ReportScheduler` 启动首轮 + 周期;活验可能需等待。可观察日志或让浏览器运行一段时间。
- 若品牌门控判定为「需 patch」,Task 1 Step 3 的薄 patch 是唯一客户端源码改动。
- DM 端点 TLS/路由:复用 Phase 1 已通的 Caddy 443 → device-manager 路径(`dm.teleport.fairyland.io`)。
