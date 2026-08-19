# `teleport://tunnel` 真机冒烟(Task 13 Step 1)

**结论:页面在真机上加载、经 Mojo 拉到真实快照并全量渲染,手动重绑按钮的往返也通。** 下面同时记录**三个把前几次尝试挡住的坑**,免得下一个人重踩。

---

## 1. 为什么必须手写 CDP 客户端

两条显而易见的路线在本环境都走不通:

- **`--headless=new --screenshot=<f> <url>`** —— **会忽略 URL 去截 NTP**。截出来的图看着像成功,内容却与被测页面无关。这是本轮第五个「验证什么都没验」的形状。
- **`screencapture`** —— 需要本会话没有的屏幕录制权限。

可行路线:开 `--remote-debugging-port`,用手写的 CDP 客户端 `Runtime.evaluate` 直接读渲染后的 DOM。

## 2. 三个坑(按踩到的顺序)

1. **DevTools 端口在启动后约 30 秒才起来,不是立刻。** 本机 `/Library/Teleport/CloudManagementEnrollmentToken` 存在,启动期的 CBCM 注册尝试打不通 DM server,`net::ERR_TIMED_OUT` 要等满 30s;`DevTools listening on ws://...` 排在它后面。**等 8~12 秒会得到「端口没起来」的假象**,并且 `--remote-debugging-port` 也**不会**打印任何拒绝原因(上游只在 policy / default-user-data-dir 两种拒绝时打印,超时不属于任何一种)。用 `--remote-debugging-port=0` + 轮询 `<udd>/DevToolsActivePort`,别用固定端口 + 固定 sleep。
   - 顺带确认:上游的 default-user-data-dir 限制**对本构建不生效**(`remote_debugging_server.cc:170-175`,该检查只在 `GOOGLE_CHROME_BRANDING` 下恒开,非品牌构建走一个仅供测试的开关),所以卡住的从来不是它。
2. **`/json/new` 现在要 `PUT`**,`GET` 返回 `405 Method Not Allowed`。
3. **WebSocket 握手默认被 403 拒**:`Rejected an incoming WebSocket connection from the http://127.0.0.1:<port> origin`。要么 `--remote-allow-origins=*`,要么客户端**不发 Origin 头**(websocket-client 的 `suppress_origin=True`)。后者更好:不用给浏览器多开一个口子。

另有一个读 DOM 的坑:页面是 Lit 组件,`document.body.textContent` 读不到内容,必须穿透 shadow root(`document.querySelector('tunnel-app').shadowRoot`)。自定义元素名是 **`tunnel-app`**(`tunnel_app.ts` 的 `static get is()`),不是 `teleport-tunnel-app`。

## 3. 配方

```bash
SCRATCH=/tmp/teleport-tunnel-smoke; rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"
"$HOME/workspace/chromium/151.0.7922/src/out/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport" \
  --user-data-dir="$SCRATCH/udd" --remote-debugging-port=0 --enable-logging=stderr \
  --no-first-run --no-default-browser-check about:blank >"$SCRATCH/stderr.log" 2>&1 &
# 轮询到文件出现(约 30s),再取端口:
PORT=$(sed -n '1p' "$SCRATCH/udd/DevToolsActivePort")
```

客户端(`uv run --with websocket-client python …`)要点:

```python
target = http_json(port, f"/json/new?{url}", method="PUT")          # 坑 2
ws = create_connection(target["webSocketDebuggerUrl"],
                       timeout=30, suppress_origin=True)             # 坑 3
send("Page.enable"); send("Runtime.enable"); time.sleep(4)           # 等 Mojo 往返
send("Runtime.evaluate", {"expression":
     "document.querySelector('tunnel-app').shadowRoot.textContent",  # 穿透 shadow root
     "returnByValue": True})
```

## 4. 实测结果(未纳管 profile,全新 user-data-dir)

`teleport://tunnel` 正确别名到 `chrome://tunnel/`,`document.title = "隧道诊断"`,shadow root 渲染出完整快照:

```
隧道诊断 此页面显示当前配置文件的接入隧道派生状态。所有内容均为 诊断信息;访问是否被允许由边缘节点判定,不由本页面决定。
概览  纳管状态 未纳管 / 证书选择策略 未下发 / 隧道编排 未启动 / 绑定请求 空闲 / 访问凭据 未持有 / 代理配置 尚未下发
      绑定入口(gate) gate.fairyland.io / 边缘节点(edge) edge.fairyland.io:443
时间线 最近一次绑定尝试 — / 最近一次绑定成功 — / 凭据到期 — / 下次自动刷新 — / 下次失败重试 — / 最近一次失败原因 —
生效的路由地址(0) 尚未收到任何良构的路由表。
被跳过的条目(0) 没有条目被跳过。
最近的 CONNECT 结果(0) 尚未观察到经由本隧道的 CONNECT。
刷新  立即重新绑定
```

**这条断言不是「页面加载了」而是「页面拿到了真数据」**:gate / edge 两个主机名是从部署配置派生的,而未注册 provider 时 `GetTunnelStateSnapshot()` 返回的是**空** `TunnelStateSnapshot`(两个主机名会是空串)。它们有值,证明 `//chrome/browser` 侧的 provider 确实注册了、seam 确实被调用、Mojo 往返确实完成——这正是 Task 10 勘误 (t) 指出「静态页证明不了任何东西」时要求的那个可检测失败模式(「永远 loading」)。

**手动重绑往返**:点击「立即重新绑定」后页面显示 `已拒绝:此配置文件尚未纳管。` —— 与 `TeleportTunnelBindClientTest.RebindIsRejectedWhenPreconditionsAreUnmet` 的判定一致,且证明 `rebind()` 的 Mojo 方法与拒绝原因的映射在真机上是通的。

## 5. 未覆盖(需要活的服务端,属联合验收)

已生效的路由表、被跳过条目的真实渲染、CONNECT 结果与 authority 的显示、到期时刻——都需要一个真的纳管 profile 与一个真的 gate。这四项在本计划末尾的「联合验收」清单里,不在本次单仓冒烟范围内。
