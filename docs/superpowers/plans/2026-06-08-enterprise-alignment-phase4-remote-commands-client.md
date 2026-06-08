# Phase 4 客户端实现计划 · Remote Commands(teleport overlay)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已纳管 Teleport 经原生 `remote_commands` 通道取到控制台下发的命令、验签执行、回执——**客户端零 patch**,端到端活验 `BROWSER_CLEAR_BROWSING_DATA`。

**Architecture:** `remote_commands_service` 是原生能力;命令验签用策略 fetch 已建立的 per-tenant 公钥;DM 端点 Phase 0/1 已重指 fairyland。客户端=**验证 + e2e**,外加(仅当门控)一处薄 patch。

**Tech Stack:** Chromium M148 overlay;dev 构建 + docker.lima fairyland 栈。

**上位文档:** phase 权威 + 客户端 spec `.../specs/2026-06-08-enterprise-alignment-phase4-remote-commands-design.md`;服务端 plan(主要工作)fairyland `.../plans/2026-06-08-...-remote-commands-server.md`。

**分支/worktree:** teleport `worktree-chrome-enterprise-alignment`。**前置**:fairyland server-plan 已落(`?request=remote_commands` 命令签发 + `IssueRemoteCommand`)。

---

## 关键事实(已核实于 M148)
- 命令通道原生:`components/policy/core/common/remote_commands/remote_commands_service.cc` fetch `?request=remote_commands`、验签(`VerifySignature(SignedData.data, policy_signature_public_key, signature, type)`)、执行、回执。
- 浏览器级命令仅 `BROWSER_CLEAR_BROWSING_DATA=12`。
- 验签公钥 = 策略 fetch 建立的 per-tenant 公钥 → 服务端用同密钥签(server-plan),客户端原生验签,**零 patch**。
- 无 FCM 推送 → 命令随 policy/commands refresh 取(轮询,延后推送)。

---

## Task 1: 非品牌门控核查(决定是否需 patch)

- [ ] **Step 1: 静态核查 remote_commands_service 创建**

Run(chromium 检出):
```bash
grep -rnE 'GOOGLE_CHROME_BRANDING|is_chrome_branded|RemoteCommands(Service|Factory)|remote_commands' \
  chrome/browser/policy/ components/policy/core/common/remote_commands/ \
  | grep -viE 'unittest|browsertest' | grep -iE 'brand|create|factory|init' | head
# CBCM 浏览器是否注册 remote commands invalidator/service
grep -rnE 'CreateRemoteCommands|remote_commands|RemoteCommandsService' \
  components/policy/core/common/cloud/machine_level_user_cloud_policy_manager.cc \
  components/enterprise/browser/controller/*.cc 2>/dev/null | head
```
判定:remote_commands_service 在非品牌 CBCM 构建是否创建并 fetch。若被品牌门控 → 薄 patch 解门控(仿 Phase 1 手法);否则记「非品牌门控,零 patch」。

- [ ] **Step 2:(条件)薄 patch + Commit**

仅当确认门控:patch 对应创建点,累加进 `patches/`(一文件一 patch + REVERSE-OK 自检)。无需则跳过并记录。

---

## Task 2: 端到端活验(真浏览器 × device-manager)

**Files:** 无源码改动(除非 Task 1 有 patch)。前置:fairyland server-plan 完成 + device-manager 跑分支码 + 机器纳管 + **已成功拉过一次策略**(客户端缓存了 per-tenant 验签公钥)。

- [ ] **Step 1: 环境就绪 + 下发命令**

device-manager 跑分支码。经控制面下发清数据命令:
```bash
PROTO=/Users/liulichao/workspace/fairyland/.claude/worktrees/chrome-enterprise-alignment/proto
SVC=teleport.v1.DeviceManagerControlService
# device 的 dm_token_hash 可从 ListEnrolledDevices 取(= EnrolledDevice.id)
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d '{"tenant_id":"11111111-1111-1111-1111-111111111111"}' localhost:19090 $SVC/ListEnrolledDevices
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d '{"tenant_id":"11111111-1111-1111-1111-111111111111","dm_token_hash":"<DEVICE_ID>","command_type":"BROWSER_CLEAR_BROWSING_DATA","payload":"{\"clear_cache\":true,\"clear_cookies\":true}"}' \
  localhost:19090 $SVC/IssueRemoteCommand
```
> payload JSON 精确字段按真浏览器接受格式微调(e2e 定;先试 clear_cache/clear_cookies)。

- [ ] **Step 2: 触发客户端取命令**

启动 dev 构建(机器纳管 profile)+ `--enable-logging=stderr --v=1 --vmodule='*remote_command*=2,cloud_policy_client=2,device_management_service=2'`。命令随 refresh 取(无推送)——可重启浏览器或等轮询触发一次 policy/commands fetch。

- [ ] **Step 3: 客户端侧确认取到 + 验签 + 执行**

```bash
grep -aiE 'remote_command|request=remote_commands|SignedData|signature|ClearBrowsingData|secure command' /tmp/teleport-phase4-rc.log | head
```
期望:见 `?request=remote_commands` fetch → 取到 secure command → **验签通过**(无 "signature verification failed")→ 执行清数据。**若验签失败** → server-plan Task 2 的 `SignedData.data` 裹层判断有误,回 server-plan 修正(裸 RemoteCommand vs 裹 PolicyData)。

- [ ] **Step 4: 服务端侧确认回执 + 控制面状态**

```bash
grpcurl -plaintext -import-path $PROTO -proto teleport/v1/device_manager.proto \
  -d '{"tenant_id":"11111111-1111-1111-1111-111111111111","dm_token_hash":"<DEVICE_ID>"}' \
  localhost:19090 $SVC/ListRemoteCommands
```
期望:命令 `state` 轮转到 `acked`,`result_code=RESULT_SUCCESS`。

- [ ] **Step 5: 记录证据**

客户端日志(取到/验签/执行)+ `ListRemoteCommands`(acked + result)写进验证笔记。关浏览器只 kill 主 PID。

---

## 完成标准(DoD)
- [ ] 门控判定明确(零 patch 或薄 patch)。
- [ ] 端到端:`IssueRemoteCommand` → 浏览器取到 → **验签通过** → 执行清数据 → 回执 → `ListRemoteCommands` 见 acked + RESULT_SUCCESS。
- [ ] 证据归档(尤其验签通过——锁住服务端签名格式与 Chrome 一致)。

## 风险 / 未决
- **验签**:`SignedData.data` 裹层 + signature_type 必须与 Chrome 验签路径一致(验签失败=命令被拒;e2e 是最终裁判,回 server-plan Task 2)。
- `remote_commands_service` 非品牌门控核查(Task 1)。
- 无推送 → 命令延迟到下次 poll(文档化)。
- payload JSON 精确字段(e2e 定)。

## 参考
- phase 权威 + 客户端 spec:`.../specs/2026-06-08-enterprise-alignment-phase4-remote-commands-design.md`。
- 服务端 plan:fairyland `.../plans/2026-06-08-...-remote-commands-server.md`。
- 门控解法范式:Phase 1 `chrome_browser_cloud_management_controller.cc` patch。
- override 技巧 + 关浏览器注意:仓库记忆(Phase 2/3 e2e)。
