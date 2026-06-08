# Phase 4 设计 · 安全事件 Reporting(客户端侧)

- 状态:已评审(设计)
- 日期:2026-06-08
- 范围:跨 `teleport`(客户端)与 `fairyland`(服务端)两仓
- 本文归属:**子系统 phase 权威 + 客户端侧设计**。服务端侧(主要工作)见 fairyland 配对 spec(§8)。
- 上位文档:总纲 `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`(Phase 4)。
- 分支/worktree:`worktree-chrome-enterprise-alignment`。

> Phase 4「云管理进阶」拆为两个独立子系统:**安全事件 Reporting**(本文)+ **Remote Commands**(配对 spec)。**即时刷新推送本轮延后**(以 Chrome 自带轮询兜底,行为=刷新有延迟,文档化偏差)。

## 1. 目标

让已机器纳管的 Teleport 把**安全事件**(登录/扩展安装/危险下载等)经 Chrome 原生 realtime reporting 上报到 fairyland device-manager,存储 + 控制台可见。**客户端薄改动**:重指 reporting 端点(patch)+ 经 Phase 3 策略框架下发 `OnSecurityEventEnterpriseConnector` 启用。**不接内容送检(DLP 仍 Out)**。

## 2. 范围边界

**In**
- 客户端:patch reporting 端点默认值 → fairyland;经机器策略下发 `OnSecurityEventEnterpriseConnector` 启用上报;验证非品牌构建上报路径可用。
- 服务端(详见 fairyland spec):`UploadEventsRequest`(proto)ingest + 信封提取存 Postgres(EventSink 接缝)+ `ListSecurityEvents`。

**Out(后续/其他子系统)**
- 即时刷新推送(轮询兜底,本轮延后)。
- Remote Commands(配对子系统)。
- ERP(`/v1/record`)完整 ingest(本轮服务端仅 accept-drop)。
- DLP 内容送检。

## 3. 关键决策(本轮已拍板)

1. **proto 线格式**:realtime reporting M148 走 proto(`UploadEventsRequest` 含 `Event` oneof);Fairyland vendor 子集按上游字段号。**另有 deprecated JSON 路径,plan 核实走哪条**。
2. **扩展 device-manager** ingest(非新服务);DMToken 鉴权。
3. **EventSink 接缝 + Postgres sink**(信封列 + JSONB);生产路径(NATS JetStream→consumer→OLAP)文档化、本轮不实现。
4. **启用经 Phase 3 策略**:`OnSecurityEventEnterpriseConnector`(StringPolicyProto=701,JSON 值)加进 Phase 3 catalog 即可下发。

## 4. 客户端设计(薄 patch + 策略启用)

### 4.1 patch:reporting 端点重指
- `components/policy/core/browser/browser_policy_connector.cc`:`kDefaultRealtimeReportingServerUrl`(`/v1/events`)+ `kDefaultEncryptedReportingServerUrl`(`/v1/record`)默认值 → fairyland(用 `teleport::` 常量;stable/beta 忽略命令行 switch,故改默认值,延续 Phase 0/1 DM-URL 手法,薄 patch 引用 `teleport::` 常量)。

### 4.2 启用上报(零新源码,经 Phase 3 框架)
- Phase 3 catalog 新增 `OnSecurityEventEnterpriseConnector`(machine scope、string、mandatory),值为连接器 JSON 配置(启用哪些事件 + service provider)。device-manager 经机器策略下发该 string 策略,客户端原生 `RealtimeReportingClient` 据此启用。

### 4.3 plan 阶段必须验证(客户端)
- **非品牌门控核查**:`RealtimeReportingClient` 创建 + 上报路径在非品牌构建不被关闭(似 Phase 2;单测里若有 brand guard 确认是断言差异)。
- **proto vs deprecated JSON 路径**:确认 M148 实际走哪条(feature flag),据此 fairyland 解析。
- **上报实达**:安全事件 POST 到 `dm.teleport.fairyland.io` 的 reporting 路径(携机器 DMToken)。
- **端点路径/method/Content-Type** 精确(供 fairyland 注册端点)。

## 5. 协议 / 数据流(已核实于 M148)
```
浏览器(OnSecurityEventEnterpriseConnector 启用)→ 安全事件
 → RealtimeReportingClient.UploadSecurityEvent → POST UploadEventsRequest(proto)到 reporting 端点(GoogleDMToken)
 → device-manager: DMToken→(tenant,device);解析 events→信封+JSONB;EventSink(Postgres 追加)
控制台:ListSecurityEvents(tenant, 按 type/device/time 过滤)
```

## 6. 客户端 patch 总览 + 测试

| 目标文件 | 改动 | 类型 |
|---|---|---|
| `components/policy/core/browser/browser_policy_connector.cc` | reporting 两端点默认值 → fairyland(`teleport::` 常量) | 薄 patch |
| Phase 3 `catalog.go`(fairyland) | 加 `OnSecurityEventEnterpriseConnector` 条目 | 服务端目录 |

- 客户端无新增单测(端点重指 patch + 策略启用,零新 `//teleport` 源码)。
- 端到端(dev + docker.lima):下发连接器策略 → 触发一个易触发事件(扩展安装/登录)→ device-manager ingest 落库 → `ListSecurityEvents` 可见。

## 7. 风险 / 未决
- proto vs deprecated JSON 上报路径(§4.3 验证)。
- 哪些事件在 dev/非品牌构建实际触发(部分依赖 Safe Browsing);e2e 选最易触发者。
- reporting 端点路径/method 精确匹配(供服务端注册)。

## 8. 跨仓协作
- **配对 spec(服务端,主要工作)**:fairyland `.../2026-06-08-enterprise-alignment-phase4-security-reporting-server-design.md`。
- **契约**:DM reporting 线协议 = vendor Chromium reporting proto 子集;控制面 `ListSecurityEvents` 在 fairyland `proto/teleport/v1`。
- 客户端薄(端点 patch + Phase 3 策略启用);几乎全在 fairyland;契约先定,最后整体联调。

## 9. 参考
- 总纲:`.../2026-06-04-chrome-enterprise-alignment-design.md`(Phase 4)。
- 兄弟子系统:`.../2026-06-08-enterprise-alignment-phase4-remote-commands-design.md`。
- Phase 3 策略框架(启用上报的载体):`.../2026-06-07-enterprise-alignment-phase3-policy-framework-design.md`。
- 配对(服务端):fairyland `.../2026-06-08-...-security-reporting-server-design.md`。
