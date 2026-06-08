# Phase 2 设计 · 设备状态回报(客户端侧)

- 状态:已评审(设计)
- 日期:2026-06-05
- 范围:跨 `teleport`(客户端)与 `fairyland`(服务端)两仓
- 本文归属:**Phase 2 phase 权威 + 客户端侧设计**。服务端侧见 fairyland 配对 spec(§8)。
- 上位文档:总纲 `docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md` 的 **Phase 2**。
- 分支/worktree:`worktree-chrome-enterprise-alignment`(teleport + fairyland 同名配对)。

> 本 phase 承接 Phase 1(设备级 CBCM 纳管已点亮并活验)。Phase 2 让已纳管设备**周期性向 device-manager 回报状态**,控制台可见 fleet。

## 1. 目标

让 device-manager 接收 Chrome CBCM 的**机器状态报告**(`ChromeDesktopReport`)并**全量存储最新快照**,控制面 gRPC 可见纳管设备的浏览器版本/渠道、OS、硬件标识、已装扩展、profile、策略生效态等;**客户端零 patch**——经策略面下发 `CloudReportingEnabled=true`,由 Chromium 原生 `ReportScheduler` 自动上报。

## 2. 范围边界

**In**
- 客户端:经机器策略下发 `CloudReportingEnabled=true`(实际值由 fairyland device-manager 编码进机器策略);验证非品牌构建上报路径可用且报告发往我们的 DM 端点。
- 服务端(详见 fairyland spec):`ChromeDesktopReport` ingest + 抽取确认字段存独立列(最新快照)+ `ListEnrolledDevices` 带上状态列。

**Out(后续 phase)**
- 安全事件 realtime reporting(`UploadSecurityEvent` → `chromereporting-pa` 端点,Phase 4)。
- Remote Commands、即时推送刷新(Phase 4)。
- 状态历史/审计归档(本轮仅最新快照)、富 fleet 控制台 UI。

## 3. 关键决策(本轮已拍板)
1. **客户端全量上报、服务端只留确认字段、其余丢弃**:浏览器原生上报完整 `ChromeDesktopReportRequest`;device-manager 只**抽取确定使用的标量字段存为独立列**,不存原始字节、不存 JSONB(避免按上游字节级 vendor 整个报告依赖闭包)。未抽取字段在解析时作为 unknown 字段被丢弃——这正是期望行为。
2. **仅最新快照**:每设备一行,新报告 upsert 覆盖旧的(YAGNI;够 fleet 当前态可见性)。
3. **确认字段列(fleet 清单)**:`browser_version`、`browser_channel`、`os_name`、`os_arch`、`os_version`、`device_manufacturer`、`device_model`、`serial_number`、`computer_name`、`last_report_at`。**本轮不收 list 型数据(扩展/profile/安全信号)**——它们不适合独立列;将来需要再扩列/拆子表(独立 phase)。
4. **设备键 = `dm_token_hash`**:报告 handler 从 `Authorization: GoogleDMToken` 的 DMToken 取哈希,与 `device_registrations`/控制面 `EnrolledDevice.id` 同键,使 `ListEnrolledDevices` 能直接带上状态列(Chrome 的 `deviceid` query 参数仅作校验/回退,不做键)。
5. **vendored proto 仅扩到被抽取字段**:只补 `ChromeDesktopReportRequest`(读 `browser_report`/`os_report`/`browser_device_identifier`/`device_model`/`brand_name`)、`BrowserReport`(`browser_version`/`channel`+`Channel` 枚举)、`OSReport`(`name`/`arch`/`version`/`device_manufacturer`/`device_model`)、`ChromeDesktopReportResponse{}` + 信封字段(`chrome_desktop_report_request=26` / `chrome_desktop_report_response=23`);`BrowserDeviceIdentifier` 已 vendored。字段号严格对齐上游以保线兼容。
6. **`GetEnrolledDevice` 详情 RPC 不再需要**:数据全在列里,`ListEnrolledDevices` 直接返回全部状态列。

## 4. 协议 / 数据流(已核实于 M148 检出)
- 上报机制 = Chromium 原生 `CloudPolicyClient::UploadChromeDesktopReport`,由 `components/enterprise/browser/reporting/report_scheduler.cc` 的 `ReportScheduler` 触发(启动首轮 + 周期),**门控于 pref `kCloudReportingEnabled`**(策略 `CloudReportingEnabled`,默认 false、机器作用域 `per_profile:false`、`dynamic_refresh:true`、**无品牌门控**)。
- 线协议:DM 协议,request_type(`request=` query 值)= **`chrome_desktop_report`**(snake_case,`cloud_policy_constants.cc` 的 `kValueRequestChromeDesktopReport`;`TYPE_CHROME_DESKTOP_REPORT` 是枚举标签,非线值。**e2e 实测纠正:计划早期误用 CamelCase**);body = `DeviceManagementRequest{ chrome_desktop_report_request }`;`Authorization: GoogleDMToken token=<机器 DMToken>`;带 `deviceid=<client_id>` query 参数。

```
浏览器(已机器纳管;机器策略含 CloudReportingEnabled=true)
 → ReportScheduler(启动首轮 + 周期)→ UploadChromeDesktopReport
 → POST https://dm.teleport.fairyland.io/devicemanagement/data/api?request=chrome_desktop_report&deviceid=<client_id>
    Authorization: GoogleDMToken token=<机器 DMToken>
    body: DeviceManagementRequest{ chrome_desktop_report_request: ChromeDesktopReportRequest{...} }
 → device-manager:DMToken→(tenant,device);解析报告→JSON;upsert device_reports;回 ack
控制台:ListEnrolledDevices(tenant) → 设备清单(每设备带状态列:版本/渠道/OS/型号/序列号/last-seen)
```

## 5. 客户端设计(零 patch)
- **无新增 patch / 无新增 `//teleport` 源码**:上报是原生能力,仅需经策略开启。`CloudReportingEnabled` 的值由 device-manager 编进机器策略(`BuildMachineSettings`,见 fairyland spec),客户端原生消费。
- **DM 端点**:已由 Phase 0/1 的 `browser_policy_connector.cc` buildflag 默认值指向 fairyland,无需再改——`UploadChromeDesktopReport` 走同一 DM server。

### 5.1 plan 阶段必须验证(客户端)
- **非品牌门控核查**:确认 `ReportScheduler` 创建 + `BrowserReportGenerator` 报告生成 + `UploadChromeDesktopReport` 在非品牌(`is_chrome_branded=false`)构建上**不被关闭**(单测里有 `GOOGLE_CHROME_BRANDING` guard,需确认那是断言差异而非运行时禁用)。若被门控,补一处薄 patch 解门控。
- **上报实达**:`?request=chrome_desktop_report` 实际 POST 到 `dm.teleport.fairyland.io`(dev),携机器 DMToken + deviceid。

## 6. 测试(客户端)
- 客户端无新增单测(零源码)。
- 端到端活验(dev 构建 + docker.lima):机器纳管 + 下发 `CloudReportingEnabled=true` → 触发/等待上报 → device-manager 收到 `ChromeDesktopReport`、`ListEnrolledDevices` 显示该设备的版本/渠道/OS/型号/序列号/last-seen。

## 7. 风险 / 未决
- 非品牌构建上报路径是否被品牌门控(§5.1 验证)。
- `ReportScheduler` 上报触发时机(启动首轮 + 周期);活验可能需等待或找触发点(如改 pref 触发 `OnReportEnabledPrefChanged`)。
- `deviceid` 关联:= register 时的 client_id,与 `device_registrations` 对齐(Phase 1 已确认 `deviceid` 写入 `policy_data.device_id`)。

## 8. 跨仓协作
- **配对 spec(服务端,主要工作)**:fairyland `docs/superpowers/specs/2026-06-05-enterprise-alignment-phase2-device-status-server-design.md`。
- **契约**:`ChromeDesktopReport` 线协议 = vendor 的 Chromium `device_management_backend.proto`(本轮按上游字段号补 `ChromeDesktopReport*` 子集 + 信封字段);控制面 `EnrolledDevice` 增强(加状态列)在 fairyland `proto/teleport/v1`。
- **执行**:客户端近零,几乎全在 fairyland;契约(EnrolledDevice 状态字段)先定,之后各自 plan + 实施,最后 docker.lima 整体联调。

## 9. 参考
- 总纲:`docs/superpowers/specs/2026-06-04-chrome-enterprise-alignment-design.md`。
- Phase 1:`docs/superpowers/specs/2026-06-04-enterprise-alignment-phase1-device-enrollment-design.md`(设备纳管 + deviceid 写入)。
- 能力盘点:`docs/research/2026-06-02-chromium-enterprise-modules.md`(§3 Cloud Management、§4 Reporting)。
