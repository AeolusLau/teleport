# CONNECT 归因上游 patch:签名、调用点、实现者与 patch 面

> 本文是 A 组计划 **Task 8 Step 1** 与 **Task 9 Step 1** 的承重验证产出。
> 全部结论均带 `file:line`,由源码与**已构建的 `out/` 目录**共同判定,不接受推断。

**取证基准**

| 项 | 值 |
|---|---|
| 检出 | `/Users/liulichao/workspace/chromium/151.0.7922/src`,`git describe` = `151.0.7922.76`(HEAD `031bfd60f544a`) |
| 检出状态 | **已应用 overlay**(`git status` 在 `net/`+`services/` 下正好 9 个 modified 文件,即 `be430f1` 那批)。**下文所有行号都是「上游 + 现有 overlay」之后的行号**,即 Task 8 Step 2 将要编辑的那棵树 |
| 构建产物 | `/Users/liulichao/workspace/chromium/151.0.7922/src/out/mac/arm64/dev`(Siso;`ninja -t query` 不可用,故「是否在构建里」用 **`obj/` 下的 `.o` 是否存在** + `gn refs` 双证) |
| 仓库 | `/Users/liulichao/workspace/teleport`(patches)与 worktree `/Users/liulichao/workspace/teleport/.worktrees/tunnel-webapp-compat`(取证期间 HEAD 由 `eb4d241` 前进到 `6f8cae9`,均为 plan 文档提交;Task 1–13 的实现代码尚未落地) |

---

## ⚠️ 执行期勘误(2026-08-16,Task 8 落地时发现,本文自身有一条结论是错的)

### 勘误 1:默认实现**不能**内联写在头里 ⇒ patch 文件从 10 个变 **11** 个

本文 §7「命名建议」写:「**新方法不需要新增任何 include**,默认体可以内联写在头里 ⇒ **`net/base/proxy_delegate.cc` 不必进 patch 清单**(若偏好放 `.cc`,`CanFalloverToNextProxyOverride` 就是同文件先例,代价 +1 个 patch 文件)」。

**「偏好」是错的措辞——这是硬约束。** 按本文的形状内联写进头里,构建**直接失败**:

```
../../../../net/base/proxy_delegate.h:128:40: error:
  [chromium-style] virtual methods with non-empty bodies shouldn't be declared inline.
```

chromium-style clang 插件禁止**非空**虚函数体内联在头里。`be430f1` 的 `OnBeforeForwardProxyRequest` 之所以能内联,是因为它的默认体是**空的**(`{}`);我们这个默认体要转发,非空,所以必须落 `.cc`——本文自己引的 `CanFalloverToNextProxyOverride` 先例(`net/base/proxy_delegate.cc:14-18`)才是唯一可行形状,不是备选。

⇒ **patch 清单实际是 11 个文件**(A 侧 5:2 改 3 新),`patches/net/base/proxy_delegate.cc.patch` 是本次新建的第 6 个净新增上游文件。下次里程碑升级在这条线上多 **6** 个潜在冲突点,不是 5 个。

### 勘误 2:主动加了两个 include(本文说「不需要新增 include」)

本文 §7 与「四条硬约束」第 4 条说 `HostPortPair` 经 `proxy_delegate.h:16 → proxy_chain.h:17 → host_port_pair.h:28` 已是完整类型,**不需要**新增 include。这条**事实成立**(不加也能编)。但落地时仍然显式加了 `net/base/host_port_pair.h`(头)与 `<utility>` + `net/base/host_port_pair.h`(`.cc`):依赖一条**传递** include 意味着上游哪天在 `proxy_chain.h` 里改用前向声明,我们的 patch 就会在下一次里程碑升级时莫名其妙编不过,而症状离原因很远。代价为零(该头本来就在编译单元里),收益是把隐式依赖变显式。

### 确认成立的部分(执行后复核)

- §1 的四参签名与 `CompletionOnceCallback` 契约:**成立**,默认体按 `std::move(callback)` 原样转发;
- §3「非破坏性形状下另外 8 个 `ProxyDelegate` 实现者一个都不用动」:**成立**,`net_unittests` / `services_unittests` 全绿且 `patches/` 下没有为它们新增任何文件;
- §2.4「不改 `quic_proxy_datagram_client_socket.cc`」:**成立**,它继续走旧的四参纯虚;`NetworkServiceProxyDelegate` 保留旧 override 并以**空 `HostPortPair`** 通知 observer,故 MASQUE 路径行为不变(只是 authority 为空),由新增用例 `OnTunnelHeadersReceivedWithoutEndpointStillObserved` 钉住;
- §8 的构建判据:**成立且必要**。`chrome` 绿之后 `services_unittests` 才抓到 `TestCustomProxyConnectionObserver`;`net_unittests` 是唯一能证明默认转发在**异步**路径上不挂死的地方——`HttpProxyType/HttpProxyConnectJobTest`(111)、`VersionIncludeStreamDependencySequence/QuicProxyClientSocketTest`(78)、`All/SpdyProxyClientSocketTest`(76)、`*QuicProxyDatagramClientSocket*`(38)全绿,其中前三个套件经 `TestProxyDelegate::MakeOnTunnelHeadersReceivedCompleteAsync()` 真正跑了 `ERR_IO_PENDING` + 回调恢复状态机的那条路。

> **顺带一条测试执行的坑**:`net_unittests` 的这些套件都是**参数化**的,真名带前缀(`HttpProxyType/HttpProxyConnectJobTest.*` 等)。用 `--gtest_filter='HttpProxyConnectJobTest.*'` 匹配到 **0 个用例**时,gtest runner 照样打印 `SUCCESS: all tests passed.` —— 一个零用例的假绿。**跑上游套件必须核对实际执行条数**,不能只看 SUCCESS。

---

## ⚠️ 与计划/spec 冲突的结论(先读这一节)

### 冲突 1(与 **plan**):「一处非破坏性上游 patch」不成立,最少 **6 个** patch 文件,其中 **3 个是被迫的破坏性改动**

计划正文 line 7 写:「CONNECT 归因经**一处非破坏性**上游 patch 取得目的地」。

实测:`net::ProxyDelegate` 侧确实可以做到非破坏性(§7 有先例),但**目的地必须穿过 mojom 才能到达浏览器进程**,而 mojom 侧的接口方法签名改动会**强制**改掉 `network::mojom::CustomProxyConnectionObserver` 的全部实现者。其中 `PrefetchProxyConfigurator` 在 `//content/browser:browser` 里(§4),**就在我们的 `chrome` 构建路径上**。所以「一处」「非破坏性」两个词同时不成立。

spec §3.4 约束 2 本身是**对的**(「mojom 侧的破坏性改动可以接受,但 plan 必须先枚举全部实现者」)——是 **plan 的 Architecture 一行摘要**把它压缩错了。修 plan,不用修 spec。

### 冲突 2(与 **plan**):Task 8 Step 4 的 `for f in ...` 文件清单**漏了至少 3 个必改文件**

计划 Task 8 Step 4 的 `for f in ...` 循环列了 7 个文件(它自己加了一句「实际文件清单以 Step 1 结论为准」——本文即那份结论,按 §8 的清单替换整个循环)。实测缺:

| 缺失文件 | 为什么必须有 |
|---|---|
| `net/quic/quic_proxy_datagram_client_socket.cc` | 这是**第 4 个**调用点(§2.4),计划只数了 3 个 |
| `content/browser/preloading/prefetch/prefetch_proxy_configurator.h` / `.cc` | mojom 接口的**生产实现者**,改 mojom 方法签名后不改它就编不过 `chrome`(§4) |
| `services/network/network_service_proxy_delegate_unittest.cc` | 内含 `TestCustomProxyConnectionObserver`,同上(§4);该文件**已有** patch,是扩写不是新建 |

### 冲突 3(与 **plan**):Task 8 Step 3 的验收判据 `autoninja chrome` **证不出**它想证的事

计划 Task 8 Step 3 期望「编译通过,且未触及 cronet / mock / fake delegate」,手段只有 `autoninja -C out/mac/arm64/dev chrome`。

- `autoninja -C out/mac/arm64/dev chrome` **根本不编译** `//net:net_unittests`、`//net:test_support`、`//services:services_unittests` —— 所以它既不能证明「fake/mock/test delegate 没被破坏」,也**抓不到** `services/network/network_service_proxy_delegate_unittest.cc` 的破坏(§3、§4)。
- 但它**能**抓到 `prefetch_proxy_configurator` 的破坏(在 `//content/browser:browser` 里)。
- cronet 部分**成立且更强**:cronet 的源文件连 GN 图都不在(§3)。

正确判据见 §8 末尾。

### 无冲突,确认(Task 9 Step 1)

Task 9 Step 1 的预期结论**成立**:`NetworkServiceProxyDelegate::OnTunnelHeadersReceived` **没有** `IsInProxyConfig` 门控,而两个 header 注入兄弟方法**都有**(§5)。⇒ **客户端必须自己按代理链过滤**。
补一条计划未提的精度:`OnFallback` 也**没有**门控——即真正的分界不是「这一个没有」,而是「**写 header 的门控、通知 observer 的不门控**」,共 2v2。

---

## 1. `net::ProxyDelegate::OnTunnelHeadersReceived` 的完整签名

`net/base/proxy_delegate.h:106-117`:

```cpp
  // Called when the response headers for the proxy tunnel request have been
  // received. Allows the delegate to override the net error code of the tunnel
  // request. Returning OK causes the standard tunnel response handling to be
  // performed. `proxy_index` identifies the proxy, within `proxy_chain`, that
  // we're receiving response headers from. Implementations should make sure
  // they can trust said proxy before making decisions based on
  // `response_headers`.
  virtual Error OnTunnelHeadersReceived(
      const ProxyChain& proxy_chain,
      size_t proxy_index,
      const HttpResponseHeaders& response_headers,
      CompletionOnceCallback callback) = 0;
```

| 项 | 结论 | 证据 |
|---|---|---|
| 参数个数 | **4 个** | `proxy_delegate.h:114-117` |
| 参数 1 | `const ProxyChain& proxy_chain` | `:114` |
| 参数 2 | `size_t proxy_index` | `:115` |
| 参数 3 | `const HttpResponseHeaders& response_headers` | `:116` |
| 参数 4 | **`CompletionOnceCallback callback`** ← **上一轮漏的就是这个** | `:117` |
| 返回类型 | `net::Error`(枚举,非 `int`) | `:113` |
| 是否纯虚 | **是**,`= 0;` | `:117` |
| 目的地参数 | **没有**。只有代理链 + 链内下标 | `:114-115` |

### `ERR_IO_PENDING` 的含义(以及为什么漏掉 `callback` 是致命的)

注意:**这个方法的头部注释里没有写 `ERR_IO_PENDING` 语义**(写了的是它上面的 `OnBeforeTunnelRequest`,`proxy_delegate.h:89-98`)。所以下面的契约是从**调用点与既有实现**里取证的,不是从注释里读来的:

1. `TestProxyDelegate::OnTunnelHeadersReceived` 在异步模式下 **`on_tunnel_headers_received_callback_ = std::move(callback); return ERR_IO_PENDING;`** —— `net/base/test_proxy_delegate.cc:215-222`;
2. 调用点把返回值直接当成状态机的 `rv` 往上抛:`HttpProxyClientSocket::DoProcessResponseHeaders` 返回它(`net/http/http_proxy_client_socket.cc:479-482`),`DoLoop` 的循环条件是 `while (rv != ERR_IO_PENDING && ...)`(`:334`),`Connect()` 见到 `ERR_IO_PENDING` 就挂起并保存外部 callback(`:102-103`);
3. 传进去的 `callback` **就是** `base::BindOnce(&HttpProxyClientSocket::OnIOComplete, weak_factory_.GetWeakPtr())`(`:481-482`),而 `OnIOComplete(int result)` 会 `DoLoop(result)` 恢复状态机(`:259-263`);
4. 下一状态 `DoProcessResponseHeadersComplete(int result)` 上来就 `DCHECK_NE(ERR_IO_PENDING, result)`(`:489`)。

**结论**:返回 `ERR_IO_PENDING` ⇒ 实现方**承诺**日后异步地、恰好一次地用最终 `net::Error`(**不得再是 `ERR_IO_PENDING`**)调用 `callback`;在此之前整条 CONNECT 状态机是挂起的。

⇒ **任何"默认实现转发给旧方法"的写法都必须 `std::move(callback)` 原样传递**。丢掉它 = 具体 delegate 一旦走异步路径,这条 CONNECT 就**永久挂死**(既不完成也不失败,只等一个永远不会来的回调)。这正是上一轮的漏参会造成的后果。

返回 `OK` ⇒ 按标准隧道响应流程继续(`proxy_delegate.h:107-109`)。返回其它错误码 ⇒ 覆盖隧道请求的 net error。

---

## 2. 全部调用点(生产代码 4 处),及各自能否取到目的地

全树 grep(排除 `out/`)只有 4 处 `proxy_delegate_->OnTunnelHeadersReceived(`。全部 4 个 `.o` 都在我们的构建里(`obj/net/net/*.o`)。

### 2.1 `net/http/http_proxy_client_socket.cc:478-483` — HTTP/1.1 CONNECT

```cpp
  if (proxy_delegate_) {
    return proxy_delegate_->OnTunnelHeadersReceived(
        proxy_chain_, proxy_chain_index_, *response_.headers,
        base::BindOnce(&HttpProxyClientSocket::OnIOComplete,
                       weak_factory_.GetWeakPtr()));
  }
```

**目的地:有,现成的。** `const HostPortPair endpoint_;` — `net/http/http_proxy_client_socket.h:170`(注释 `:168-169`:"The hostname and port of the endpoint");构造参数 `:49`。
`.o`:`obj/net/net/http_proxy_client_socket.o`。

### 2.2 `net/spdy/spdy_proxy_client_socket.cc:504-509` — HTTP/2 CONNECT

**目的地:有。** `const HostPortPair endpoint_;` — `net/spdy/spdy_proxy_client_socket.h:179`;构造参数 `:55`。
`.o`:`obj/net/net/spdy_proxy_client_socket.o`。

### 2.3 `net/quic/quic_proxy_client_socket.cc:462-467` — HTTP/3 CONNECT

**目的地:有。** `const HostPortPair endpoint_;` — `net/quic/quic_proxy_client_socket.h:156`;构造参数 `:42`。
`.o`:`obj/net/net/quic_proxy_client_socket.o`。

### 2.4 `net/quic/quic_proxy_datagram_client_socket.cc:551-556` — MASQUE CONNECT-UDP ⚠️ **这一处没有 endpoint**

```cpp
  // TODO(crbug.com/326437102): Add case for Proxy Authentication.
  if (proxy_delegate_) {
    return proxy_delegate_->OnTunnelHeadersReceived(
        proxy_chain(), proxy_chain_index(), *response_.headers,
        base::BindOnce(&QuicProxyDatagramClientSocket::OnIOComplete,
                       weak_factory_.GetWeakPtr()));
  }
```

**目的地:类里没有 `HostPortPair`。** 成员只有:

- `GURL url_;` — `net/quic/quic_proxy_datagram_client_socket.h:229`,注释 `:226-228` 说明它是 URI Template 展开后的结果,`target_host`/`target_port` 已被替换进去;
- `const ProxyChain proxy_chain_;` — `:233`;注意本类**连 `proxy_chain_index_` 成员都没有**,`proxy_chain_index()` 是算出来的:`return proxy_chain_.length() - 1;`(`:183`)。

**真正的目的地在上一帧**——`QuicSessionPool::CreateSessionOnProxyStream`,`net/quic/quic_session_pool.cc:1939-1949`:

```cpp
  const quic::QuicServerId& server_id = key.server_id();          // :1939
  ...
  GURL url(base::StringPrintf("https://%s:%d/.well-known/masque/udp/%s/%d/",
                              last_proxy.GetHost().c_str(),
                              last_proxy.GetPort(), server_id.host().c_str(),   // :1944
                              server_id.port()));                               // :1945

  auto socket = std::make_unique<QuicProxyDatagramClientSocket>(               // :1947
      url, key.session_key().proxy_chain(), user_agent, net_log,
      proxy_delegate_);
```

即真目的地 = `key.server_id().host()` / `.port()`,被**编码进 URL 路径段**后才交给 socket。要在 socket 里恢复它,只有两条路:① 反解 `url_.path()`;② 给构造函数**新增一个 `HostPortPair` 参数**(要连带改 `.h` 与 `quic_session_pool.cc`,**+2 个 patch 文件**)。

**建议:这一处不改**(§8 已按此出清单)。理由:我们的 edge 是 HTTPS CONNECT 正向代理,CONNECT-UDP/MASQUE 不在隧道路径上;而 spec §3.4 约束 4 明确把「每多 patch 一个上游文件 = 下次里程碑升级多一个冲突点」当作决策依据。不改它 = 它继续调旧的 4 参纯虚方法(**这正是非破坏性形状允许的**,旧方法保留),代价只是 CONNECT-UDP 的通知不带 authority。
`.o`:`obj/net/net/quic_proxy_datagram_client_socket.o`。

### 2.5 非调用点(澄清,防止再次误计)

以下 grep 命中**不是** `ProxyDelegate` 的调用点,别算进来:

- `content/browser/preloading/prefetch/prefetch_proxy_configurator.cc:124` — 是 **mojom** 接口的实现(§4);
- `components/cronet/cronet_context.cc:896,901`、`cronet_context_adapter.cc:185` — cronet 自己的 `Callback` 接口(`components/cronet/cronet_context.h:129`),且整块不在我们构建里(§3);
- `net/base/test_proxy_delegate.cc:107` 的 `VerifyOnTunnelHeadersReceived` 等 = 测试断言 helper。

---

## 3. `net::ProxyDelegate` 的全部实现者(9 个)与「是否在我们构建里」

判定方法:先全树 grep `public (net::)?ProxyDelegate` + 全部 `OnTunnelHeadersReceived` override;再用 `out/mac/arm64/dev/obj` 下的 `.o` 判定是否在构建里;`gn refs` 作为第二证据。
检出是完整树(`ios/ android_webview/ chromecast/ headless/ fuchsia_web/` 均在;仅 `weblayer/` 不存在),所以这个清单是全的。

| # | 实现者 | 声明位置 | `.o` 是否存在 | GN target | 在我们构建里? |
|---|---|---|---|---|---|
| 1 | `NetworkServiceProxyDelegate` | `services/network/network_service_proxy_delegate.h:29-30` | ✅ `obj/services/network/network_service/network_service_proxy_delegate.o` | `//services/network:network_service` | **是(生产路径,必改)** |
| 2 | `CronetProxyDelegate` | `components/cronet/cronet_proxy_delegate.h:29` | ❌ `find obj -iname '*cronet*'` = **0 个文件** | `gn refs` 回 `The input matches no targets, configs, or files.` | **否——连 GN 图都不在** |
| 3 | `TestProxyDelegate` | `net/base/test_proxy_delegate.h:31`(override 在 `:134`) | ✅ `obj/net/net_unittests/test_proxy_delegate.o` | `//net:net_unittests` | **是**(已编译过) |
| 4 | `FakeProxyDelegate` | `net/base/fake_proxy_delegate.h:27`(override 在 `:45`) | ✅ `obj/net/net_unittests/fake_proxy_delegate.o` | `//net:net_unittests` | **是**(已编译过) |
| 5 | `MockProxyDelegate` | `net/base/mock_proxy_delegate.h:30`(`MOCK_METHOD` 在 `:61`) | ✅ `obj/net/test_support/mock_proxy_delegate.o` | `//net:test_support` | **是**(已编译过) |
| 6 | `TestProxyDelegateForIpProtection`(继承 #3) | `net/http/http_stream_factory_job_controller_unittest.cc:226`(override 在 `:245-254`) | ✅ `obj/net/net_unittests/http_stream_factory_job_controller_unittest.o` | `//net:net_unittests` | **是** |
| 7 | `TestResolveProxyDelegate` | `net/proxy_resolution/configured_proxy_resolution_service_unittest.cc:243`(override 在 `:290`) | ✅ `obj/net/net_unittests/configured_proxy_resolution_service_unittest.o` | `//net:net_unittests` | **是** |
| 8 | `TestProxyFallbackProxyDelegate` | `net/proxy_resolution/configured_proxy_resolution_service_unittest.cc:310`(override 在 `:337`) | ✅ 同上 `.o` | `//net:net_unittests` | **是** |
| 9 | `TestProxyDelegateWithProxyInfo` | `net/websockets/websocket_end_to_end_test.cc:438`(override 在 `:478`) | ✅ `obj/net/net_unittests/websocket_end_to_end_test.o` | `//net:net_unittests` | **是** |

**血量修正**:实现者是 **9 个**,不是 3 个。其中 **8 个在我们的构建目录里已经有 `.o`**,唯一真正出局的是 cronet(#2)。
⇒ 如果把纯虚 `OnTunnelHeadersReceived` 直接改签名(破坏性做法),要连带改 **8 个**位置。这正是必须走非破坏性形状(§7、§8)的原因;走了非破坏性形状后,这 8 个**一个都不用动**。

`gn refs` 原始输出:
- `//net/base/fake_proxy_delegate.cc` → `//net:net_unittests`
- `//net/base/test_proxy_delegate.cc` → `//net:net_unittests`
- `//net/base/mock_proxy_delegate.cc` → `//net:test_support`
- `//components/cronet/cronet_proxy_delegate.cc` → `The input matches no targets, configs, or files.`

---

## 4. mojom 侧:哪个文件、哪个方法、全部实现者

**文件**:`services/network/public/mojom/network_context.mojom`
**接口**:`CustomProxyConnectionObserver`,声明于 `:150`
**方法**:`:159-161`

```
interface CustomProxyConnectionObserver {          // :150
  OnFallback(ProxyChain bad_chain, int32 net_error);    // :155

  // Called when the response headers for the proxy tunnel request have been
  // received.
  OnTunnelHeadersReceived(ProxyChain proxy_chain,        // :159
                          uint64 chain_index,            // :160
                          HttpResponseHeaders response_headers);  // :161
};
```

remote 挂载点:`NetworkContextParams.custom_proxy_connection_observer_remote`,`:464-465`(与我们已在用的 `custom_proxy_config_client_receiver` `:458-459` 相邻)。
唯一的调用方:`services/network/network_service_proxy_delegate.cc:190-193`。

### 全部实现者(**注意路径 —— 上一轮把这个写错了**)

| # | 实现者 | **精确源码路径** | `.o` | GN target | 在我们构建里? |
|---|---|---|---|---|---|
| 1 | `PrefetchProxyConfigurator` | **`content/browser/preloading/prefetch/prefetch_proxy_configurator.h:26`**;override 声明 `:66-69`,定义 **`content/browser/preloading/prefetch/prefetch_proxy_configurator.cc:124-127`** | ✅ `obj/content/browser/browser/prefetch_proxy_configurator.o` | `//content/browser:browser` | **是 —— 而且在 `chrome` 的编译路径上,改 mojom 就必须改它** |
| 2 | `TestCustomProxyConnectionObserver` | `services/network/network_service_proxy_delegate_unittest.cc:56-57`;override `:74` | ✅ `obj/services/network/tests/network_service_proxy_delegate_unittest.o` | `//services/network:tests` → `//services:services_unittests` | **是** |
| — | (将来)`TeleportTunnelService` | worktree `src/browser/enterprise/teleport_tunnel_service.{h,cc}`,Task 9 新增 | — | overlay,经 `chrome/browser` 编入 | 我们自己加的第 3 个 |

注意 `prefetch_proxy_configurator` 的目录是 **`content/browser/preloading/prefetch/`**(有 `preloading/` 这一层),不是 `content/browser/prefetch/`。

**相关但不同建的**:`content/browser/preloading/prefetch/prefetch_proxy_configurator_unittest.cc` 直接调 `configurator()->OnTunnelHeadersReceived(...)` 共 4 处(`:169,185,201,221`)。它属于 `//content/test:content_unittests`,**`obj/` 下没有它的 `.o`(未在本 out 目录编译过)**。按「`.o` 判定」它不在我们构建里;但它在 GN 图里,谁要是编 `content_unittests` 就会炸。**记为已知欠账,不进本次 patch 清单**(改它 = 多一个上游 patch 文件 + 多一个升级冲突点,而我们从不编这个 target)。

### mojom 侧为什么**注定**是破坏性的

Mojo 生成的 C++ 接口基类里,每个方法都是**纯虚**的。因此:
- 改现有方法的参数列表 ⇒ 两个实现者的 `override` 签名对不上 ⇒ 编译错误;
- **新加一个方法**(比如 `OnTunnelHeadersReceivedWithEndpoint(...)`)⇒ 两个实现者变成抽象类 ⇒ 一样编译错误。

⇒ **没有非破坏性的 mojom 改法**(除非另起一个全新 interface 并新增一路 remote 到 `NetworkContextParams`,那要多 patch 更多上游文件,更贵)。这与 §1 的冲突 1 是同一件事。
好消息:`HostPortPair` 这个 mojom 类型**已经可用**——`network_param.mojom:17` 定义(`struct HostPortPair { string host; uint16 port; }`,`net::HostPortPair` 的 typemap 镜像),而 `network_context.mojom:54` 已经 `import` 了 `network_param.mojom`(该文件 `:1660,:1668,:1819` 已在用它)。**不需要新增 import**。

---

## 5. `NetworkServiceProxyDelegate` 的 `IsInProxyConfig` 门控:三个方法并排(Task 9 Step 1)

`services/network/network_service_proxy_delegate.cc`,四个方法原样并列:

```cpp
void NetworkServiceProxyDelegate::OnFallback(const net::ProxyChain& bad_chain,   // :153
                                             int net_error) {
  if (observer_) {                                                               // :155  ← 无门控
    observer_->OnFallback(bad_chain, net_error);
  }
}

void NetworkServiceProxyDelegate::OnBeforeForwardProxyRequest(                   // :160
    const net::ProxyChain& proxy_chain,
    net::HttpRequestHeaders* extra_headers) {
  if (IsInProxyConfig(proxy_chain)) {                                            // :166  ← 有门控
    MergeRequestHeaders(extra_headers, proxy_config_->forward_proxy_headers);
  }
}

base::expected<net::HttpRequestHeaders, net::Error>
NetworkServiceProxyDelegate::OnBeforeTunnelRequest(                              // :172
    const net::ProxyChain& proxy_chain,
    size_t proxy_index,
    OnBeforeTunnelRequestCallback callback) {
  net::HttpRequestHeaders extra_headers;
  if (IsInProxyConfig(proxy_chain)) {                                            // :177  ← 有门控
    MergeRequestHeaders(&extra_headers, proxy_config_->connect_tunnel_headers);
  }
  return extra_headers;
}

net::Error NetworkServiceProxyDelegate::OnTunnelHeadersReceived(                 // :183
    const net::ProxyChain& proxy_chain,
    size_t proxy_index,
    const net::HttpResponseHeaders& response_headers,
    net::CompletionOnceCallback callback) {
  if (observer_) {                                                               // :188  ← 无门控!
    // Copy the response headers since mojo expects a ref counted object.
    observer_->OnTunnelHeadersReceived(                                          // :190
        proxy_chain, proxy_index,
        base::MakeRefCounted<net::HttpResponseHeaders>(
            response_headers.raw_headers()));
  }
  return net::OK;
}
```

`IsInProxyConfig` 本体在 `:211-224`(`proxy_chain.is_single_proxy() && RulesContainsProxy(...)`)。

| 方法 | 行 | 干什么 | `IsInProxyConfig` |
|---|---|---|---|
| `OnFallback` | `:153-158` | 转发给 observer | **无** |
| `OnBeforeForwardProxyRequest` | `:160-169` | 往请求写 header | **有**(`:166`) |
| `OnBeforeTunnelRequest` | `:171-181` | 往 CONNECT 写 header | **有**(`:177`) |
| `OnTunnelHeadersReceived` | `:183-196` | 转发给 observer | **无**(`:188`) |

**结论(确认 Task 9 Step 1 的预期)**:`OnTunnelHeadersReceived` **没有**代理链过滤。该 network context 上**任何**代理链的 CONNECT 结果都会原样推给我们的 observer。
⇒ `TeleportTunnelService` 收到通知后**必须自己先比对代理链**(与自己下发的 edge chain 比),否则 `teleport://tunnel` 会把无关代理的 CONNECT 当作隧道结果展示。
**精度修正**:真正的规律不是「两个兄弟有、这个没有」,而是「**写 header 的两个有门控,通知 observer 的两个都没有**」——`OnFallback` 同样无门控,过滤责任同样在客户端。

**上游自己也是这么做的**(强力旁证):唯一的既有 mojom 实现者 `PrefetchProxyConfigurator::OnTunnelHeadersReceived` 一进函数就自己过滤代理链 —— `content/browser/preloading/prefetch/prefetch_proxy_configurator.cc:130-132`:

```cpp
  if (proxy_chain != prefetch_proxy_chain_) {
    return;
  }
```

即「observer 侧自行按代理链过滤」是这条通知的**既定使用约定**,不是我们独有的补丁式防御。

顺带确认(Task 9 的接线不需要新 patch):`TeleportTunnelService::BindProxyConfigClient(network::mojom::NetworkContextParams* params)` 已存在于 worktree `src/browser/enterprise/teleport_tunnel_service.cc:215-218`,且已由**现有** patch `patches/chrome/browser/net/profile_network_context_service.cc.patch:34` 调用。observer remote 只需在这个已有函数体里多填一个 `params->custom_proxy_connection_observer_remote`(`network_context.mojom:464-465`)——**overlay 内改动,零新增 patch**。

---

## 6. `be430f1` 的先例形状

`git log`(`/Users/liulichao/workspace/teleport`):`be430f1 feat(teleport): forward-proxy header injection for HTTP-backend tunnel (client Track T)`,父提交 `4898899`。

**共 9 个 patch 文件 + 2 个 overlay 源文件,全部是新增(`git show --numstat` 显示 9 个文件的 deletions 均为 0,且 `git cat-file -e be430f1^:<path>` 均不存在)**:

| patch 文件 | 行数 | 角色 |
|---|---|---|
| `patches/net/base/proxy_delegate.h.patch` | +21 | **新虚函数本体** |
| `patches/net/http/http_network_transaction.cc.patch` | +41 | 唯一调用点 |
| `patches/services/network/network_service_proxy_delegate.h.patch` | +14 | 生产实现者(声明) |
| `patches/services/network/network_service_proxy_delegate.cc.patch` | +22 | 生产实现者(定义) |
| `patches/services/network/public/mojom/network_context.mojom.patch` | +19 | mojom **结构体加字段** |
| `patches/net/base/test_proxy_delegate.h.patch` | +34 | 测试(**自愿**) |
| `patches/net/base/test_proxy_delegate.cc.patch` | +22 | 测试(**自愿**) |
| `patches/net/http/http_network_transaction_unittest.cc.patch` | +237 | 测试 |
| `patches/services/network/network_service_proxy_delegate_unittest.cc.patch` | +39 | 测试 |

### 形状要点(可直接抄的部分)

**a) 新虚函数写成「非纯虚 + 空默认实现」,内联在头里,零 include 增量。** `patches/net/base/proxy_delegate.h.patch` 的全部内容就是一个 hunk:

```cpp
+  // ... Default is a no-op so existing ProxyDelegate subclasses are
+  // unaffected.
+  virtual void OnBeforeForwardProxyRequest(const ProxyChain& proxy_chain,
+                                           HttpRequestHeaders* extra_headers) {}
```

现在它活在 `net/base/proxy_delegate.h:84-85`。因为默认体存在,**全部 8 个其它实现者一个都没改**——`patches/` 里既没有 `fake_proxy_delegate`、`mock_proxy_delegate`,也没有那 4 个 unittest 内联 delegate 的 patch。这就是"非破坏性"的实证。

**b) 被改的 `test_proxy_delegate.{h,cc}` 是自愿的,不是被迫的。** 它加的是**测试观测能力**(计数器 `on_before_forward_proxy_request_call_count_`、可选 header 注入),不是为了修编译错误——`test_proxy_delegate.h.patch` 的三个 hunk 全是新增 getter / override / 计数器成员。

**c) ⚠️ 但它的 mojom 改动**与我们这次**不是同一类**:`network_context.mojom.patch` 加的是 **`struct CustomProxyConfig` 的一个字段**(`forward_proxy_headers`,现 `network_context.mojom:146`)。给 mojom struct 加字段对实现者是无感的;**给 mojom interface 改方法签名不是**。所以 **`be430f1` 只能作为 `ProxyDelegate` 侧的先例,不能作为 mojom 侧的先例**——mojom 侧这次没有先例,是新增的破坏面(§4)。

---

## 7. 非纯虚新方法的默认实现,能否合法调用同类的既有纯虚函数?

**能,无条件合法。** C++ 里只有两种情况调纯虚是 UB:① 用**限定名**直接调(`Base::Pure()`);② 在**基类构造/析构期间**调。经由正常虚派发、在对象已构造完成后调用,总是解析到派生类 override。我们的默认体是在对象完全构造之后由调用点触发的普通成员函数调用,两条都不沾。

### 先例

**同一个文件里:没有。** `net/base/proxy_delegate.h` / `.cc` 里的三个默认实现全是"什么都不做":
- `CanFalloverToNextProxyOverride` — 声明 `proxy_delegate.h:52-54`,定义 `net/base/proxy_delegate.cc:14-18`,`return std::nullopt;`;
- `OnBeforeForwardProxyRequest` — `proxy_delegate.h:84-85`,空体(我们自己加的);
- `OnStreamCreationAttempted` — `proxy_delegate.h:127-129`,空体。

**同一个库(`//net`)里:有,而且是**与我们这次一模一样的「新的富 API 默认转发给旧的纯虚」形状**:

1. **`net::CookieStore`(最贴切)** — `net/cookies/cookie_store.h:105` 是纯虚 `virtual void GetAllCookiesAsync(GetAllCookiesCallback callback) = 0;`;`:116` 是**非纯虚**的 `virtual void GetAllCookiesWithAccessSemanticsAsync(...)`;其默认实现在 `net/cookies/cookie_store.cc:20-34`,注释写着 "Default implementation which returns a default vector of UNKNOWN CookieAccessSemantics.",最后一行 **`:33` `GetAllCookiesAsync(std::move(adapted_callback));`** —— 非纯虚的默认体调用本类纯虚,**并且把 callback 适配后 `std::move` 传下去**。这正是我们要做的事(含 callback 转手)。

2. **`net::ServerSocket`** — `net/socket/server_socket.h:37-39` 纯虚 `Listen(...) = 0`;`:43-45` 非纯虚 `virtual int ListenWithAddressAndPort(...)`;定义 `net/socket/server_socket.cc:17-27`,末尾 `:25-26` `return Listen(IPEndPoint(ip_address, port), backlog, /*ipv6_only=*/std::nullopt);` —— **参数更少的重载默认转发给参数更多的纯虚**,与我们方向相反但机制相同。

3. **`net::NetworkChangeNotifier`** — `net/base/network_change_notifier.cc:903`、`:917` 两个非纯虚默认体都调本类纯虚 `GetCurrentConnectionType()`。

**同一目录(`net/base/`)里**还有 NVI 版:`NetworkDelegate::NotifyBeforeURLRequest`(`net/base/network_delegate.cc:29-40`,末行 `:39`)调用本类纯虚 `OnBeforeURLRequest`(`net/base/network_delegate.h:186-193`,`= 0`)。

### 命名建议

`HostPortPair` 在 `proxy_delegate.h` 里**已经是完整类型**:`proxy_delegate.h:16` 包含 `net/base/proxy_chain.h`,后者 `net/base/proxy_chain.h:17` 包含 `net/base/host_port_pair.h`(`HostPortPair` 定义在 `:28`)。**新方法不需要新增任何 include**,默认体可以内联写在头里 ⇒ **`net/base/proxy_delegate.cc` 不必进 patch 清单**(若偏好放 `.cc`,`CanFalloverToNextProxyOverride` 就是同文件先例,代价 +1 个 patch 文件)。

建议用**不同的方法名**而不是同名重载。同名重载在本例其实是安全的(全部 4 个调用点都经 `ProxyDelegate*` 静态类型调用,派生类的 name hiding 影响不到派发),但不同名可以:① 完全免掉 name-hiding 这一类推理;② `grep` 得出来谁走新路径谁走旧路径;③ 让 patch 意图在 diff 里自明。

---

## 8. 我们这次需要的**精确 patch 文件清单**

图例:**[新]** = `patches/` 下尚不存在,本次新建;**[改]** = `be430f1` 已建立,本次在同一文件上追加 hunk。

### A. `ProxyDelegate` 侧 —— 非破坏性(4 个文件)

| # | patch 文件 | 状态 | 改什么 |
|---|---|---|---|
| A1 | `patches/net/base/proxy_delegate.h.patch` | **[改]** | 新增非纯虚 `OnTunnelHeadersReceivedForEndpoint(...)`,内联默认体转发给现有 4 参纯虚(`std::move(callback)` 必须原样传)。旧纯虚**保留不动** |
| A2 | `patches/net/http/http_proxy_client_socket.cc.patch` | **[新]** | `:478-483` 改调新方法,传 `endpoint_` |
| A3 | `patches/net/spdy/spdy_proxy_client_socket.cc.patch` | **[新]** | `:504-509` 同上 |
| A4 | `patches/net/quic/quic_proxy_client_socket.cc.patch` | **[新]** | `:462-467` 同上 |

**A 侧不需要动的**(非破坏性形状的直接收益,共 8 个实现者):`net/base/test_proxy_delegate.{h,cc}`、`net/base/fake_proxy_delegate.{h,cc}`、`net/base/mock_proxy_delegate.h`、`net/http/http_stream_factory_job_controller_unittest.cc`、`net/proxy_resolution/configured_proxy_resolution_service_unittest.cc`、`net/websockets/websocket_end_to_end_test.cc`、`components/cronet/*`。

**刻意不做**:`net/quic/quic_proxy_datagram_client_socket.cc`(§2.4)。做了要连带 `.h` + `net/quic/quic_session_pool.cc`,**+3 个文件**,换来 MASQUE CONNECT-UDP 的归因——不在隧道路径上,不值。记为已知欠账。

### B. mojom 侧 —— 破坏性(4 个文件,其中 3 个是被强制的)

| # | patch 文件 | 状态 | 改什么 | 是否被迫 |
|---|---|---|---|---|
| B1 | `patches/services/network/public/mojom/network_context.mojom.patch` | **[改]** | `CustomProxyConnectionObserver.OnTunnelHeadersReceived`(`:159-161`)加 `HostPortPair endpoint` 参数。`HostPortPair` 已由 `:54` import 好,**不加 import** | 主动 |
| B2 | `patches/services/network/network_service_proxy_delegate.h.patch` | **[改]** | 声明新的 `OnTunnelHeadersReceivedForEndpoint(...)` override(**旧的 4 参 override 必须保留**,否则类变抽象) | 被迫 |
| B3 | `patches/services/network/network_service_proxy_delegate.cc.patch` | **[改]** | 实现新 override,把 endpoint 一并推给 observer(`:183-196` 那段的富版本);旧 override 保留为不带 endpoint 的转发 | 被迫 |
| B4 | `patches/content/browser/preloading/prefetch/prefetch_proxy_configurator.h.patch` | **[新]** | override 签名跟随(`:65-68`) | **被迫**(否则 `chrome` 编不过) |
| B5 | `patches/content/browser/preloading/prefetch/prefetch_proxy_configurator.cc.patch` | **[新]** | 定义签名跟随(`:124`);新参数忽略即可 | **被迫** |
| B6 | `patches/services/network/network_service_proxy_delegate_unittest.cc.patch` | **[改]** | `TestCustomProxyConnectionObserver` override 跟随(`:74`)+ 新增断言 | **被迫** |

### C. 非 patch 改动(overlay 内,`src/`)

- `src/browser/enterprise/teleport_tunnel_service.{h,cc}` —— 实现 `network::mojom::CustomProxyConnectionObserver`;在**已有**的 `BindProxyConfigClient`(`:215`)里顺手填 `params->custom_proxy_connection_observer_remote`;收到通知先按代理链过滤(§5)再入环形缓冲。
- `src/BUILD.gn` —— 若新增文件则登记。
- **`patches/chrome/browser/net/profile_network_context_service.cc.patch` 不用动**(已在调 `BindProxyConfigClient`)。

### 合计

**10 个 patch 文件**(A 侧 4:1 改 3 新;B 侧 6:4 改 2 新)+ overlay 源码。
其中**上游文件净新增到 patch 面的只有 5 个**(A2/A3/A4/B4/B5),其余 5 个是往已有 patch 里追加 hunk —— 就这条 tunnel/proxy 线而言,受影响的上游文件数从 `be430f1` 建立的 9 个涨到 14 个,即下次里程碑升级在这条线上多 5 个潜在冲突点(spec §3.4 约束 4 的成本口径)。

### 正确的构建验收判据(替换 plan Task 8 Step 3)

```bash
cd "$TELEPORT_CHROMIUM_ROOT/151.0.7922/src"
autoninja -C out/mac/arm64/dev chrome                # 覆盖 A1–A4、B1–B5(prefetch 在 //content/browser:browser)
autoninja -C out/mac/arm64/dev services_unittests    # 唯一能抓到 B6 的 target(//services/network:tests)
autoninja -C out/mac/arm64/dev net_unittests         # 证明 A 侧真的没破 test/fake/mock/4 个内联 delegate
autoninja -C out/mac/arm64/dev teleport_unittests    # overlay 自测
```

只跑 `chrome` **不能**证明「未触及 mock / fake delegate」——那三个 target 根本不在 `chrome` 的依赖里(§3)。cronet 无需验证:它连 GN 图都不在。
`content_unittests` **不跑**(见 §4 的已知欠账)。

---

## 结论:patch 文件清单

```
# A. ProxyDelegate 侧 —— 非破坏性(旧纯虚保留,新虚函数带默认转发实现)
[改] patches/net/base/proxy_delegate.h.patch
[新] patches/net/http/http_proxy_client_socket.cc.patch
[新] patches/net/spdy/spdy_proxy_client_socket.cc.patch
[新] patches/net/quic/quic_proxy_client_socket.cc.patch

# B. mojom 侧 —— 破坏性(B4/B5/B6 是被强制的,不改就编不过)
[改] patches/services/network/public/mojom/network_context.mojom.patch
[改] patches/services/network/network_service_proxy_delegate.h.patch
[改] patches/services/network/network_service_proxy_delegate.cc.patch
[新] patches/content/browser/preloading/prefetch/prefetch_proxy_configurator.h.patch
[新] patches/content/browser/preloading/prefetch/prefetch_proxy_configurator.cc.patch
[改] patches/services/network/network_service_proxy_delegate_unittest.cc.patch

# C. 非 patch(overlay 源码,worktree 内)
     src/browser/enterprise/teleport_tunnel_service.{h,cc}(+ src/BUILD.gn)

# 明确不做(已知欠账,理由见 §2.4 / §4)
  ✗ net/quic/quic_proxy_datagram_client_socket.{h,cc} + net/quic/quic_session_pool.cc
  ✗ content/browser/preloading/prefetch/prefetch_proxy_configurator_unittest.cc
  ✗ net/base/{test,fake,mock}_proxy_delegate.*(非破坏性形状下无须改)
  ✗ components/cronet/*(不在 GN 图里)
```

## 结论:新虚函数的完整签名

`net/base/proxy_delegate.h`,插在现有 `OnTunnelHeadersReceived`(`:113-117`)**之前**,旧的纯虚**原样保留**:

```cpp
  // Called when the response headers for the proxy tunnel request have been
  // received, with the tunnel's destination. `endpoint` is the host and port
  // the CONNECT was issued for -- the proxy-chain-only overload below cannot
  // report it, which leaves an embedder unable to attribute a tunnel failure
  // to the origin that caused it. `proxy_chain`, `proxy_index`,
  // `response_headers`, `callback` and the return value all carry exactly the
  // same contract as OnTunnelHeadersReceived(); in particular, returning
  // ERR_IO_PENDING means `callback` will be run asynchronously with the final
  // error. The default implementation forwards to OnTunnelHeadersReceived()
  // and drops `endpoint`, so existing ProxyDelegate subclasses are unaffected.
  virtual Error OnTunnelHeadersReceivedForEndpoint(
      const ProxyChain& proxy_chain,
      size_t proxy_index,
      const HostPortPair& endpoint,
      const HttpResponseHeaders& response_headers,
      CompletionOnceCallback callback) {
    return OnTunnelHeadersReceived(proxy_chain, proxy_index, response_headers,
                                   std::move(callback));
  }
```

**四条硬约束,少一条就是 bug:**

1. **`CompletionOnceCallback callback` 必须在参数表里,且必须 `std::move` 原样转发。** 契约是「返回 `ERR_IO_PENDING` ⇒ 稍后异步调 `callback` 恰好一次」(证据链见 §1)。上一轮漏掉它 ⇒ 具体 delegate 走异步路径时 CONNECT 状态机永久挂起。
2. **返回类型是 `net::Error`**,不是 `int`;`OK` = 按标准流程继续(`proxy_delegate.h:107-109`)。
3. **非纯虚**(有默认体)⇒ §3 表里另外 8 个实现者一行都不用改。旧的 4 参纯虚**必须保留 `= 0`**,否则非破坏性立刻失效。
4. **不需要新增 include**:`HostPortPair` 经 `proxy_delegate.h:16` → `net/base/proxy_chain.h:17` → `net/base/host_port_pair.h:28` 已是完整类型。

对应的 mojom 侧签名(`services/network/public/mojom/network_context.mojom:159-161` 替换为):

```
  OnTunnelHeadersReceived(ProxyChain proxy_chain,
                          uint64 chain_index,
                          HostPortPair endpoint,
                          HttpResponseHeaders response_headers);
```

(`HostPortPair` 定义于 `services/network/public/mojom/network_param.mojom:17`,已由 `network_context.mojom:54` import,无需新增 import。)
