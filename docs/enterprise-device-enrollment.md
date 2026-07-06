# Teleport 设备纳管(机器级 CBCM)下发与验证

> 适用:macOS(Apple Silicon)。本文覆盖**设备级纳管**(无用户、登录前):MDM 下发 enrollment token → 启动即机器注册 → 拉取并应用浏览器级策略。用户级 OIDC 纳管见账号体系文档。

## 1. 原理

- Teleport 复用 Chromium 的 **CBCM(Chrome Browser Cloud Management)**:启动时读取受管偏好里的 enrollment token,向 device-manager `register_browser`,换取**机器 DMToken**,再拉取 `google/chrome/machine-level-user` 作用域的签名策略。
- **单一固定基础域**:Teleport 所有渠道(stable/canary/beta)的机器纳管都读取固定 bundle id **`cn.douan.Teleport`** 与固定路径 **`/Library/Teleport/`**——机器级纳管是整机维度、与渠道无关,**一份 MDM 配置即可纳管所有渠道**(对齐 Chrome 固定 `com.google.Chrome` 的设计)。
- DM 服务端点由构建期 buildflag 决定(dev=`teleport.fairyland.io/dm`,release=生产域),命令行覆盖在 stable/beta 渠道会被忽略,故走内置默认。
- 机器纳管**默认启用**(非品牌构建已 patch `IsEnabled()` 返回 true);**是否真正注册取决于有没有 enrollment token**——无 token 时控制器静默 no-op,不外联。

## 2. 下发 enrollment token

### 2.1 生产:MDM Configuration Profile(推荐)

向受管偏好域 **`cn.douan.Teleport`** 推送(payload type `com.apple.ManagedClient.preferences`):

| 键 | 类型 | 说明 |
|---|---|---|
| `CloudManagementEnrollmentToken` | String | per-tenant enrollment token(见 §3) |
| `CloudManagementEnrollmentMandatory` | String(可选) | 值 `Mandatory` 时,纳管失败将阻断启动 |

样例 `.mobileconfig`(payload 片段):

```xml
<key>PayloadType</key>            <string>com.apple.ManagedClient.preferences</string>
<key>PayloadContent</key>
<dict>
  <key>cn.douan.Teleport</key>
  <dict>
    <key>Forced</key>
    <array>
      <dict>
        <key>mcx_preference_settings</key>
        <dict>
          <key>CloudManagementEnrollmentToken</key>
          <string>＜你的 enrollment token＞</string>
          <!-- 可选:强制纳管 -->
          <key>CloudManagementEnrollmentMandatory</key>
          <string>Mandatory</string>
        </dict>
      </dict>
    </array>
  </dict>
</dict>
```

> 受管偏好必须是 **forced**(`CFPreferencesAppValueIsForced`);普通 `defaults write` 写到用户域不会被识别。

### 2.2 文件兜底(dev / 手工验证)

当受管偏好未设置时,客户端回退读取文件路径(需 root):

```bash
sudo mkdir -p /Library/Teleport
printf '%s' '＜你的 enrollment token＞' | sudo tee /Library/Teleport/CloudManagementEnrollmentToken >/dev/null
# 可选:强制纳管选项
printf '%s' 'Mandatory' | sudo tee /Library/Teleport/CloudManagementEnrollmentOptions >/dev/null
```

## 3. 生成 enrollment token(控制面 gRPC)

device-manager 控制面服务 `teleport.v1.DeviceManagerControlService`:

| RPC | 入参 | 出参 |
|---|---|---|
| `CreateEnrollmentToken` | `{tenant_id(UUID), label}` | `{id, token(明文,仅此一次返回), created_at}` |
| `ListEnrollmentTokens` | `{tenant_id}` | token 元数据(不含明文) |
| `RevokeEnrollmentToken` | `{id}` | — |
| `ListEnrolledDevices` | `{tenant_id}` | 已纳管设备 |

> `tenant_id` 是 **UUID**(非 slug);明文 token 只在创建响应里出现一次,服务端只存哈希。

dev 栈(docker.lima)示例(gRPC 经 host 端口 `19090`,无 reflection,带 proto 调用):

```bash
grpcurl -plaintext \
  -import-path ＜fairyland＞/proto -proto teleport/v1/device_manager.proto \
  -d '{"tenant_id":"＜tenant-uuid＞","label":"macos-fleet"}' \
  localhost:19090 teleport.v1.DeviceManagerControlService/CreateEnrollmentToken
```

## 4. 验证

启动 dev 构建(无需 `--disable-field-trial-config`;本机有代理时加 `--no-proxy-server`):

```bash
out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport --no-proxy-server \
  --enable-logging=stderr --v=1 \
  --vmodule='*dm_token*=2,*cloud_management*=2,cloud_policy_client=2,cloud_policy_validator=2'
```

预期(已实测,2026-06-05):

1. 日志:`Enrollment token = ＜token＞` → `Creating machine level user cloud policy manager` → `request=register_browser` 到 `teleport.fairyland.io`(路径 `/dm/devicemanagement/data/api`,头 `authorization: GoogleEnrollmentToken token=…`)→ `Client registration succeeded` + `DMToken = …`。
2. 日志:`[machine-level-user] Signature verification succeeded` → `Policy validation complete: status = 0` → `Policy fetch succeeded`(策略签名经内置根验签钥校验通过)。
3. 机器 DMToken 缓存落 **`~/Library/Application Support/Teleport/Cloud Enrollment/`**(非 Google 路径)。
4. `chrome://policy`:`google/chrome/machine-level-user` 作用域、来源 **Cloud**、Status OK(如样例 `AuthServerAllowlist`)。
5. `chrome://management`:显示「Your browser is managed by …」,受管说明文案为 Teleport 品牌(无 Chrome/Chromium 穿帮)。

## 5. 与用户级 OIDC 纳管的关系

- **机器级(本文)**:登录前、无用户,`google/chrome/machine-level-user` 浏览器级策略。
- **用户级(OIDC)**:登录后,`google/chrome/user` 用户级策略 + 受管 profile。
- 两者各自独立的 DMToken 与策略作用域,可并存,互不干扰。

## 6. 相关实现

- 客户端 patch:`patches/components/enterprise/browser/controller/chrome_browser_cloud_management_controller.cc.patch`(`IsEnabled()` 非品牌返回 true)、`patches/chrome/browser/policy/browser_dm_token_storage_mac.mm.patch`(固定基础域 + `/Library/Teleport/` 路径)。
- 常量:`src/common/teleport_enterprise_enrollment.h`(`kManagedPrefsBundleId` / 路径 / DMToken 存储子目录)。
- 设计:`docs/superpowers/specs/2026-06-04-enterprise-alignment-phase1-device-enrollment-design.md`。
