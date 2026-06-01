# 技术债登记

> 本文件登记已知但暂缓处理的技术债。每条记录写明:背景、影响、暂行处置、将来方向。处理完成后移到「已结清」或删除并在提交信息中说明。

## 未结清

### TD-001 缺少 Google API key 导致部分云端能力不可用

- **登记日期**:2026-05-31
- **背景**:Teleport 基于 Chromium 自研,构建时未配置 Google API key(`google_api_key` / `google_default_client_id` / `google_default_client_secret`;`src/gn/args/*.mac.gn` 均未设置)。Chromium 的一批云端功能依赖这些 key,缺失时启动会弹「Google API keys are missing. Some functionality of Teleport will be disabled.」提示。
- **当前处置**:已 patch 掉该启动提示(`patches/chrome/browser/ui/startup/infobar_utils.cc.patch`,commit `64d33a8`),避免新装首启被打扰。**提示消除 ≠ 功能恢复**,以下能力仍缺失。

#### 影响分类(基于 M148 源码核实)

判定依据:提示触发条件为 `chrome/browser/ui/startup/infobar_utils.cc` 的 `!google_apis::HasAPIKeyConfigured()`;但各功能是否真坏取决于自身有无兜底。

**A. 因缺 key 而失效 / 退化(理论上配上自有 key 可恢复)**

| 能力 | 源码位置 | 现状 |
|---|---|---|
| Google 整页翻译 | `components/translate/core/browser/translate_script.cc`、`translate_url_util.cc` | 请求带空 key,翻译脚本拉取/调用失败 |
| 密码泄露检测(「检查密码」)| `components/password_manager/core/browser/leak_detection/leak_detection_check_factory_impl.cc` | 安全类,失效 |
| 在线/增强拼写检查 | `components/spellcheck/browser/spelling_service_client.cc` | 仅在线档失效;本地 Hunspell 词典不受影响 |
| Autofill 众包字段识别 | `components/autofill/core/browser/crowdsourcing/autofill_crowdsourcing_manager.cc` | 表单填充仍可用(本地启发式),不查/不传众包数据 |

**B. 需 key 且第三方构建无论如何都拿不到授权(配 key 也无解)**

| 能力 | 说明 |
|---|---|
| Safe Browsing(恶意网址/下载防护)| `components/safe_browsing/**` 多处用 key;Google 仅授权官方 Chrome,个人 key 无效或被限流 |
| 账号登录 / Sync | 需 OAuth `client_id`/`client_secret`,同样仅授权官方 Chrome |
| Lens、Feed、Nearby Share 等 | 多为 Google 专有云服务或 ChromeOS 路径,桌面企业版基本用不到 |

**C. 不受影响(曾被高估,已核实正常)**

- 地址栏搜索建议:走搜索引擎自身 suggest 接口,空 key 占位也照常返回。
- 地理位置(macOS):走 CoreLocation,不经 Google。
- 基础拼写检查、普通浏览/搜索/音视频/扩展:不依赖这些 key。

#### 将来方向(待决策,不在本次范围)

- **B 类(Safe Browsing 等)**:不应依赖 Google,应由 fairyland 自有后端统一提供安全能力(恶意网址拦截、策略管控)。属产品核心方向,需单独立项设计。
- **A 类(翻译等)**:按企业需求取舍——
  - 若保留:评估能否合法获取/自建对应 API key 或替代服务(如自建翻译网关);
  - 若放弃:在产品层面明确禁用并隐藏入口,避免用户点了无反应。
- 决策落地前,A 类功能对用户呈现为「点了无效果」,需注意是否会造成困惑。

---

## 已结清

(暂无)
