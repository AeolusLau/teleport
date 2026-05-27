# 闪现 / Teleport — dogfood 安装指南(macOS Apple Silicon)

> 仅适用于 Apple Silicon(M 系列)Mac。安装包已用 Developer ID 签名并经 Apple 公证。

## 首次安装

1. 下载安装包(最新版):
   <https://fairyland-distribution.oss-cn-beijing.aliyuncs.com/dogfood/e6251e01d822b9394301aad1af5ff0a5/Teleport-0.1.0.dmg>
   （版本号会随发布递增,以分发渠道公布的链接为准。）
2. 打开下载的 `.dmg`,把 **Teleport** 拖入「应用程序 / Applications」。
3. 首次打开:在「应用程序」里**右键点 Teleport → 打开 →** 在弹窗里再点「打开」。
   - 因为已公证,通常直接放行;若系统仍提示「来自身份不明的开发者」,用这个右键方式即可。

## 自动升级

- 装好后**无需再手动下载**。有新版本时,Teleport 会弹出「有可用更新」提示,点「更新」后自动下载、校验,并在重启时完成升级。
- 升级包同样经过 EdDSA 签名 + Developer ID 代码签名双重校验,确保来源可信、未被篡改。
- 安装在 `/Applications` 时,升级安装可能弹一次管理员密码(属正常)。

## 反馈

dogfood 阶段如遇崩溃、升级失败或其他问题,请附上版本号(关于页可见)反馈给团队。
