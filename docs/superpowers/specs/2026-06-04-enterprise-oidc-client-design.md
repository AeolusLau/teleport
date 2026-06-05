# Teleport 企业账号客户端设计:Chromium overlay OIDC 纳管

- 状态:设计(评审中)
- 仓库:`teleport`(Chromium overlay 客户端)
- 权威归属:本 spec 为**客户端设计权威**。服务端设计权威在 `fairyland` 仓 `docs/superpowers/specs/2026-06-04-enterprise-oidc-server-design.md`,两份互相引用、各摘要对端相关内容、各自生成 plan。
- 上游父设计:`docs/superpowers/specs/2026-06-03-enterprise-account-system-design.md`(总体账号体系)。
- 关联:[[channel-side-by-side-feature]](buildflag/per-channel)。

> 本文覆盖**客户端**:Chromium M148 的企业 OIDC「受管 profile 纳管」throttle 契约,以及把端点/根钥指向我们 dev/release 的薄 patch。服务端(IdP / enroll-landing / device-manager / HPKE / 手机号认证 / slug 解析)见服务端 spec。

---

## 1. Chromium throttle 契约(M148 检出核实)

`OidcAuthResponseCaptureNavigationThrottle` 有两条截 token 路径,同时启用、**header 路径优先**。本设计采用 **header 路径**(现代、更安全,真 Chrome 实际采用):

- 浏览器请求 register-handler 页,响应头 `X-Profile-Registration-Payload` 携带 base64url 的 `ProfileRegistrationPayload` protobuf(`proto/teleport/upstream/chromium`):

```protobuf
message ProfileRegistrationPayload {
  optional string encrypted_user_information = 1; // Chrome 不解密,透传给 DM server
  optional string subject = 2;                    // 必填
  optional string issuer = 3;                     // 必填
  optional string email = 4;                      // 可选
}
```

- Chrome 校验 `issuer`/`subject`/`encrypted_user_information` **三者非空**即放行;**永不解密** `encrypted_user_information`,原样塞入发往 DM server 的头:`Authorization: GoogleDM3PAuth encrypted_user_information=<原值>`(无 oauth_token 时走此前缀)。
- DM 注册类型 `TYPE_OIDC_REGISTRATION`(`request=register_profile`),`DeviceRegisterRequest.type=USER`、`flavor=FLAVOR_USER_REGISTRATION`。
- 整条 OIDC 流程**未被 `is_chrome_branded` 门控**;`kOidcAuthProfileManagement`/`kEnableGenericOidcAuthProfileManagement`/`kOidcAuthHeaderInterception` 默认开;register-handler URL 命中 `teleport::EnterpriseRegisterHandlerUrl()` 即触发,响应体/状态码不限,只读头。
- **浏览器侧不验 id_token 签名**:仅本地解 JWT payload 取 `iss`/`sub`(去重用);真实性验签在 device-manager(见服务端 spec)。

---

## 2. 客户端 patch(薄 patch,常量收进 `//teleport`)

统一原则:所有 bake 的 endpoint/根钥由**一个 buildflag** 切 dev/release。

- **统一 buildflag**:`teleport_use_release_endpoints`(GN arg)→ `buildflag_header` 暴露 `TELEPORT_USE_RELEASE_ENDPOINTS`(叶子目标避 //content 环),一处同时选:验签根钥、DM URL、enroll URL、register-handler URL。`gn/args/dev.mac.gn`=false、`release.mac.gn`=true。
- **enterprise URLs**(`src/common/teleport_enterprise_urls.{h,cc}`):dev=fairyland.io、release=beansec.com。
  - enroll URL:`https://enroll.teleport.fairyland.io/enroll`(dev)。
  - register-handler:`https://enroll.teleport.fairyland.io/profile-enrollment/register-handler`(dev)。
  - 受信来源 host:generic-OIDC 开启时 throttle 跳过该校验,OP host 不 bake(每租户,运行时由服务端决定)。
- **DM server URL 默认值**(patch `components/policy/core/browser/browser_policy_connector.cc` 的 `kDefaultDeviceManagementServerUrl`,**不靠 `--device-management-url`**):dev=`https://dm.teleport.fairyland.io/devicemanagement/data/api`、release=`https://dm.teleport.beansec.com/...`。
- **验签根钥**:dev/release 双钥(`cloud_policy_constants.cc` patch + 同一 buildflag),dev 为 dev-root(配套服务端 dev 根签名器)。
- **OIDC 重指**:`oidc_auth_response_capture_navigation_throttle.cc` 的 enroll/register-handler/受信源常量改用 `teleport::Enterprise*`。

> 现状:上述 buildflag/URLs/DM patch/根钥双钥/OIDC 重指**均已实现并构建验证**(`teleport_unittests` 过;dev 整包已构建)。

---

## 3. 服务端流程摘要(权威见服务端 spec)

客户端依赖服务端如下,详见 `fairyland` 仓 `2026-06-04-enterprise-oidc-server-design.md`:
- **租户解析 = slug**(非邮箱):浏览器经 GPO/MDM 下发 slug 或用户手输 → enroll-landing `/start?tenant=<slug>`。
- enroll-landing 跑 per-tenant OP(`<slug>.fairyland.io`)的 code flow 拿真 id_token,**HPKE 封装**后置于 `X-Profile-Registration-Payload` 头。
- device-manager 收 `register_profile`,HPKE 解封 → 按 `iss=<slug>.fairyland.io` 取 per-tenant JWKS 验签 → 签发 user DMToken → 下发 per-tenant 签名策略;浏览器用 bake 的 dev 根钥验策略签名链。
- 认证:accounts 集中认证中心,**全局手机号**;per-tenant OP 委派登录给 accounts。

---

## 4. 测试与验收(客户端 + 端到端 capstone)

- **客户端单测**:`teleport_enterprise_urls` 覆盖 dev/release 双值;buildflag 选择正确(`teleport_unittests`)。
- **端到端验收(本轮目标 capstone)**:重建 Teleport.app(dev,bake dev 根钥 + fairyland.io endpoints)→ 起服务端栈(Caddy + accounts + per-tenant OP `dadou.fairyland.io` + enroll-landing + device-manager + seed 租户 dadou + 手机号测试用户)→ 浏览器 `/start?tenant=dadou`(slug)→ 跳 `dadou.fairyland.io` OP → 委派到 `accounts.fairyland.io` **手机号登录** → 回 OP 出 code → enroll-landing 换 id_token + HPKE + header 注入 → throttle 截 → 受管 profile 创建 → device-manager `register_profile` 200(DASHERLESS)→ 用户策略 200 且签名经 Chrome 验签链(验于 new_public_key + dev 根钥)→ 策略可见(HomepageLocation)。
- GUI 登录交互(输手机号/密码、确认受管 profile)由人工完成。

---

## 5. 工作分解(客户端 plan)

1. 统一 buildflag(`teleport_use_release_endpoints`)+ enterprise URLs dev/release + DM URL 默认值 patch ——**已实现(见本分支)**。
2. 检出一致化(符号链接重指 worktree src + 重应用全部 patch)——**已完成**。
3. 构建 Teleport.app(dev)——**已完成**(119M;`teleport_unittests` 过)。
4. 端到端联调 capstone(依赖服务端栈就绪;GUI 登录人工)——待服务端 IdP 重构 + infra 就绪后执行。

> 客户端的端点常量与服务端 dev 主机名(`*.teleport.fairyland.io`、`accounts.fairyland.io`、`<slug>.fairyland.io`)对齐;OP host 不 bake(运行时按 slug 决定)。
