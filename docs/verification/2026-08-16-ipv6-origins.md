# IPv6 origin 的归宿(Task 12 Step 0)

**结论:选 (b) 不支持,且服务端已落地。客户端无需任何改动 —— 现有 host 校验本就拒绝一切含 `:` 的形态,两侧是构造性一致,不是巧合。**

本文只记录**客户端侧的后果与一致性论证**。决定本身在服务端已经作出并发布,不在此重开。

---

## 1. 决定与它的理由(服务端已落地)

计划给的是二选一:(a) 契约规定 IPv6 的 `host` 在 wire 上带方括号、客户端放行;(b) 服务端投影侧显式拒绝并计入 drop 计数,客户端不特判。

服务端选了 **(b)**,并且**没有**用「服务端静默丢弃」的方式实现——那正是计划要求避免的形状。它给 IPv6 单列了一个**分类 drop 原因**:

- `products/teleport/gateway/internal/tunnelroutes/project.go:56` —— `DropReasonIPv6Origin DropReason = "ipv6_origin"`
- 同文件 `project.go:198-204` —— `parseRoute()` **在通用校验之前**先判 IPv6:

  ```go
  // Classify IPv6 before the general validator so the reason survives:
  // ValidateAuthority folds every rejection into one sentinel, and IPv6 is
  // the one rejection that is a product limit rather than a corrupt value.
  // SplitHostPort strips the brackets, so a residual ':' is the tell.
  if h, _, err := net.SplitHostPort(key); err == nil && strings.Contains(h, ":") {
      return RoutableOrigin{}, DropReasonIPv6Origin, false
  }
  ```

顺序是承重的:`ValidateAuthority` 把所有拒绝折叠成一个 sentinel,先跑它会让「这是产品限制」退化成「这条数据是坏的」。先分类再校验,原因才活得下来,并进入 `routes_dropped` 计数与审计事件。

理由(服务端侧的判断,此处仅复述):device-manager 的**写入面**与 edge 的 **authority 校验**都已经拒 IPv6,所以客户端就算路由过去,edge 也必然拒——(a) 会造出一条「客户端愿意路由、edge 保证拒绝」的路径,比不路由更糟。

## 2. 客户端侧的后果:已经一致,而且是构造性的

`ParseRoutableOrigins` 的 host 校验里**没有**、也**不需要** IPv6 分支。IPv6 的每一种拼法都带 `:`(带端口/带方括号的还带 `[` `]`),而校验第 2 步一次性拦掉:

- `src/browser/enterprise/teleport_tunnel_logic.cc:89` —— `if (!net::IsCanonicalizedHostCompliant(host)) return "not a compliant canonical hostname";`

`net::IsCanonicalizedHostCompliant` 只接受 `[a-z0-9\-._]` 构成的合规 ASCII 主机名,`:`/`[`/`]` 一律不在其中。因此:

| wire 上的 host | 客户端结果 | 拦在哪一步 |
|---|---|---|
| `::1` | 拒 | 第 2 步 |
| `[::1]` | 拒 | 第 2 步 |
| `2001:db8::1` | 拒 | 第 2 步 |
| `[2001:db8::1]` | 拒 | 第 2 步 |
| `fe80::1` | 拒 | 第 2 步 |
| `::ffff:10.0.0.5`(IPv4-mapped) | 拒 | 第 2 步 |
| `[2001:db8::1]:8443` | 拒 | 第 2 步 |

七种拼法由 `TeleportRoutableOriginValidationTest.RejectsIpv6LiteralsInEverySpelling` 钉住,**断言的是拒绝原因而不只是条数**——因为「拒绝发生在哪一步」正是本文的结论:客户端没有专门的 IPv6 检查,一致性来自主机名合规性这一条更强的判据。将来若有人加了专门的 IPv6 分支,该测试会红,并把人指回本文。

## 3. 我主动去找的不一致,以及没找到

任务要求:「若客户端其实会做出不一致的行为,要大声说出来」。逐条查过:

1. **`::ffff:10.0.0.5` 会不会被 RFC1918 放行规则捞回来?** 不会。`RejectHost` 的 IP 字面量分支(`teleport_tunnel_logic.cc:115-127`,`net::IPAddress::AssignFromIPLiteral`)排在第 4 步,而第 2 步已经先把它拒了。**顺序在这里第二次成为承重**——上一轮为 `HostIsRegistryIdentifier` 的三个 `CHECK` 已经确认过一次。
2. **诊断页会不会把它显示成静默丢弃?** 不会。被拒条目连同原因进 `skipped_entries`,`teleport://tunnel` 会显示。客户端这侧同样**没有静默**。
3. **服务端已经不发了,客户端的判据算不算死代码?** 不算。bind 响应是未签名的 JSON(`TD-TUNNEL-BIND-RESPONSE-UNSIGNED`),客户端判据是**独立**的 fail-safe,不能假设发送方守约。
4. **中间没有第三个消费者。** 客户端只在 `ParseRoutableOrigins` 一处消费 `routable_origins`(`teleport_tunnel_service.cc` 唯一调用点),没有第二条绕过校验的路径。

**结论:没有发现不一致。** 客户端无代码改动;新增的只有那条回归测试与本文。

## 4. 记入技术债

`docs/tech-debt.md` 的 `TD-TUNNEL-BIND-RESPONSE-UNSIGNED` 已按计划要求补记这条产品约束(IPv6 origin 不支持,两侧一致,服务端有分类 drop 计数)。
