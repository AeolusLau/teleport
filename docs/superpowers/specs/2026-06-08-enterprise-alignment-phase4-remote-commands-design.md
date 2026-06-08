# Phase 4 设计 · Remote Commands(客户端侧)

- 状态:已评审(设计)
- 日期:2026-06-08
- 范围:跨 `teleport`(客户端)与 `fairyland`(服务端)两仓
- 本文归属:**子系统 phase 权威 + 客户端侧设计**。服务端侧(主要工作)见 fairyland 配对 spec(§8)。
- 上位文档:总纲 `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`(Phase 4)。
- 分支/worktree:`worktree-chrome-enterprise-alignment`。

> Phase 4「云管理进阶」之 **Remote Commands**(另一子系统 安全事件 Reporting 见配对 spec)。搭原生 `remote_commands` 通道,首条命令 `BROWSER_CLEAR_BROWSING_DATA`。**即时刷新推送本轮延后**(命令走轮询取);**CBCM 解绑(token 删除,走策略通道)本轮 Out**。

## 1. 目标

让控制台经 device-manager 向已纳管 Teleport 下发**远程命令**(首条 = 清浏览数据),浏览器原生取-验签-执行-回执,控制台见执行状态。客户端**零 patch**(原生 `remote_commands_service` + DM URL 已 Phase 0/1 重指)。

## 2. 范围边界

**In**
- 客户端:验证原生 `remote_commands_service` 在非品牌 CBCM 构建可用;命令验签走已缓存的 per-tenant 策略公钥;执行 `BROWSER_CLEAR_BROWSING_DATA`。
- 服务端(详见 fairyland spec):`request=remote_commands` 命令签发(`SignedData`,复用 per-tenant 策略密钥)+ 回执接收 + 队列 + 控制面 `IssueRemoteCommand`/`ListRemoteCommands`。

**Out**
- 即时刷新推送(命令走轮询取,本轮延后)。
- CBCM 解绑 / token 删除(走策略通道 PolicyData 字段,另议)。
- 其余 `DEVICE_*` 命令(ChromeOS,不适用)。

## 3. 关键决策(本轮已拍板)

1. **唯一浏览器原生命令 = `BROWSER_CLEAR_BROWSING_DATA`(12)**;搭可复用通道,未来命令即插即用。
2. **命令签名复用 per-tenant 策略密钥**:客户端验签用 `policy_signature_public_key()`(与策略下发同一把,`remote_commands_service.cc:271` 实证)→ 服务端复用 Phase 0/1 `Signer` + onboarder,**无新密钥、客户端零 patch**。
3. **proto 线格式**:vendor `DeviceRemoteCommandRequest/Response`、`RemoteCommand`、`SignedData`、`RemoteCommandResult` 子集(Phase 2 手法)。
4. **轮询取**:无 FCM 推送 → 命令在下次 refresh 取到(有延迟,可接受,文档化)。

## 4. 客户端设计(零 patch)

- **无新增 patch / 无新增 `//teleport` 源码**:`remote_commands_service` 是原生能力;命令验签用策略 fetch 已建立的 per-tenant 公钥;DM 端点 Phase 0/1 已重指 fairyland。
- **执行**:`BROWSER_CLEAR_BROWSING_DATA` 原生执行(清指定 profile 缓存+cookie)。

### 4.1 plan 阶段必须验证(客户端)
- **非品牌门控核查**:`remote_commands_service` / 命令通道在非品牌 CBCM 构建会创建并 fetch(似 Phase 2 门控核查)。
- **签名格式**:确认客户端 `VerifySignature(SignedData.data, policy_pub, sig, signature_type)` 的 `signature_type`(SHA1/SHA256)+ `data` 是否裹 PolicyData,供服务端对齐签名(e2e 实证;验签失败=命令被拒)。
- **取命令时机**:确认无推送下命令随 policy/commands refresh 取到(轮询)。
- **payload 格式**:`BROWSER_CLEAR_BROWSING_DATA` 的 payload JSON 精确字段(clear_cache/clear_cookies/profile)。

## 5. 协议 / 数据流(已核实于 M148)
```
admin: IssueRemoteCommand(tenant, device, CLEAR_BROWSING_DATA, payload) → 入队(unique_id)
浏览器(下次 refresh)→ ?request=remote_commands (last_command_unique_id, command_results[])
 → device-manager: 记回执 → 取新命令 → 序列化 RemoteCommand + 用 tenant 策略密钥签名 → secure_commands[SignedData]
 → 客户端验签(policy 公钥)→ 执行清数据 → 下次请求带 command_results 回执
控制台:ListRemoteCommands → state queued→sent→acked + result
```

## 6. 客户端 patch 总览 + 测试

| 客户端改动 | — |
|---|---|
| 无新增 patch、无新增 `//teleport` 源码 | 命令通道、验签、执行均原生;DM URL 已 Phase 0/1 重指 |

- 客户端无新增单测(零源码)。
- 端到端(dev + docker.lima):`IssueRemoteCommand` → 浏览器下次 fetch 取到 → 执行清数据 → 回执 → `ListRemoteCommands` 见 acked + result。**用真浏览器验签 + 执行**(承教训:签名/线格式靠 e2e 抓)。

## 7. 风险 / 未决
- 签名 `signature_type` + `SignedData.data` 裹层(§4.1 验证;验签失败=命令被拒)。
- `last_command_unique_id` high-water + `unique_id` 单调语义(错则重发/漏发)。
- `remote_commands_service` 非品牌门控核查。
- 无推送 → 命令延迟到下次 poll(文档化;推送通道见总纲 Phase 4 决策点)。

## 8. 跨仓协作
- **配对 spec(服务端,主要工作)**:fairyland `.../2026-06-08-enterprise-alignment-phase4-remote-commands-server-design.md`。
- **契约**:DM `remote_commands` 线协议 = vendor Chromium proto 子集;控制面 `IssueRemoteCommand`/`ListRemoteCommands` 在 fairyland `proto/teleport/v1`。
- 客户端零 patch;几乎全在 fairyland;契约先定,最后整体联调。

## 9. 参考
- 总纲:`.../2026-06-04-chrome-enterprise-alignment-design.md`(Phase 4)。
- 兄弟子系统:`.../2026-06-08-enterprise-alignment-phase4-security-reporting-design.md`。
- 签名/密钥复用:Phase 1(`Signer` + per-tenant key)。
- 配对(服务端):fairyland `.../2026-06-08-...-remote-commands-server-design.md`。
