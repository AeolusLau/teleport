# 验证结论:规则语法与 host 校验(Task 3 Step 1,承重验证步)

- **验证对象**:`$TELEPORT_CHROMIUM_ROOT/151.0.7922/src`(M151,`CHROMIUM_VERSION=151.0.7922.76`)
- **验证方式**:纯源码 + 上游单测 + 上游 PSL 数据文件阅读,全部结论带 `file:line`
- **产出用途**:直接决定 Task 3 Step 2 的负例清单与 Step 4 `RejectHost()` 的判据

---

## ⚠️ 与 spec / 计划先前假设不符的四点(按重要性排序)

### A-1. spec §P3 的「**每次拷贝**都是字符串往返」在**当前推送路径上不成立**——但仍必须拒绝

spec §84 写:「`ProxyHostMatchingRules::operator=` 的实现是 `ParseFromString(rhs.ToString())`——**每次拷贝都是字符串往返**」。

**前半句为真,后半句的适用范围被高估了。** M151 的 mojo 序列化**不走**字符串往返:

`services/network/public/mojom/proxy_config.mojom:11-15`

```
// This corresponds to the string representation of `net::ProxyHostMatchingRules`.
struct ProxyHostMatchingRules {
  array<string> rules;      // ← 逐条一个 string,不是一整串
};
```

`services/network/public/cpp/proxy_config_mojom_traits.cc:17-25`(序列化,**逐条** `ToString()`)与 `:27-44`(反序列化,**逐条** `AddRuleFromString()`):

```cpp
  for (const auto& rule : r.rules()) { out.push_back(rule->ToString()); }
  ...
  for (const auto& rule : rules) {
    if (!out_proxy_bypass_rules->AddRuleFromString(rule)) { ... return false; }
  }
```

而网络服务侧 `NetworkServiceProxyDelegate` 只 `std::move` 存 `CustomProxyConfigPtr`、按 `const&` 读 `proxy_config_->rules`(`services/network/network_service_proxy_delegate.cc:207`、`:143`、`:219`),**全程无拷贝赋值**。我们自己的 `PushConfig()` 也是每次现 build 现 move(`src/browser/enterprise/teleport_tunnel_service.cc:361-362`)。

**所以:今天 `corp.example;.com` 不会在推送链路上裂开。** 但危险是**真实且潜伏**的:

- `net/proxy_resolution/proxy_host_matching_rules.cc:141-145`
  ```cpp
  ProxyHostMatchingRules& ProxyHostMatchingRules::operator=(
      const ProxyHostMatchingRules& rhs) {
    ParseFromString(rhs.ToString());
    return *this;
  }
  ```
  拷贝构造同样走它(`:130-133` `*this = rhs;`)。
- `net::ProxyConfig::ProxyRules` 的拷贝构造是 `= default`(`net/proxy_resolution/proxy_config.cc:56`),所以**任何一次按值传/存 `ProxyRules` 或 `ProxyConfig`**(包括生成的 `mojom::ProxyRules::Clone()`,见 `out/mac/arm64/dev/gen/services/network/public/mojom/proxy_config.mojom.h:1020-1031` 的 `mojo::Clone(bypass_rules)`)都会触发往返。
- 测试里一句 `auto rules = config->rules.bypass_rules;`(按值)就够触发。

**结论**:拒绝理由要**改写**——不是「首次拷贝必然裂开」,而是「这类 host 一旦被任意一次拷贝/克隆碰到就会裂成两条规则,而链路上有没有拷贝是**未来任何一次重构都能改变**的隐式属性」。判据保持不变(照拒),注释与 commit message 需按这个更准确的因果重写(spec §84 与计划 Step 4 骨架注释都要改)。

### A-2. 上游本来有一道防线,但它是**坏的**——不能指望

`net/base/scheme_host_port_matcher.cc:91-99`:

```cpp
std::string SchemeHostPortMatcher::ToString() const {
  std::string result;
  for (const auto& rule : rules_) {
    DCHECK(!rule->ToString().contains(kParseRuleListDelimiterList));
    result += rule->ToString();
    result.push_back(kPrintRuleListDelimiter);
  }
  return result;
}
```

`kParseRuleListDelimiterList` 是 `constexpr static char kParseRuleListDelimiterList[] = ",;"`(`net/base/scheme_host_port_matcher.h:39`),数组退化成 `const char*` 后命中 `std::string::contains(const charT* s)` 重载 ⇒ **这是子串查找 `",;"`,不是「含任一分隔符」**。`"corp.example;.com"` 不含子串 `,;`,DCHECK 稳稳通过。

顺带确认 DCHECK 在我们的 dev 构建里是**开着**的(`build/config/dcheck_always_on.gni:24-25`:`dcheck_always_on = (build_with_chromium && !is_official_build) || dcheck_is_configurable`,而 `src/gn/args/dev.mac.gn:12` 是 `is_official_build = false`)——即便如此,这道 DCHECK 也拦不住单分隔符。**上游没有为我们兜底,客户端必须自己拒。**

### A-3. 公共后缀:必须用 `INCLUDE_PRIVATE_REGISTRIES`,否则 `github.io` 漏网

计划 Step 2 的负例含 `github.io`。查上游 PSL 数据 `net/base/registry_controlled_domains/effective_tld_names.gperf`(标志位含义见 `:11` `// flags: 1: exception, 2: wildcard, 4: private`):

| 条目 | 行 | 标志 | 归类 |
|---|---|---|---|
| `co.uk, 0` | 1539 | 0 | ICANN |
| `com, 0` | 1562 | 0 | ICANN |
| `github.io, 4` | 3038 | **4 = private** | 私有 |
| `s3.amazonaws.com, 4` | 7567 | **4 = private** | 私有 |

`example` / `corp` / `local` / `internal` 均**不在**该文件中(grep 计数 0)。

⇒ 若用默认的 `EXCLUDE_PRIVATE_REGISTRIES`,`github.io` 与 `s3.amazonaws.com` **查不出来**,计划 Step 2 的 `RejectsPublicSuffixWildcards` 会红。**必须显式传 `INCLUDE_PRIVATE_REGISTRIES`。**

### A-4. `HostIsRegistryIdentifier()` 带 **`CHECK`(不是 `DCHECK`)**——调用顺序是承重的

`net/base/registry_controlled_domains/registry_controlled_domain.cc:586-598`:

```cpp
bool HostIsRegistryIdentifier(std::string_view canon_host,
                              PrivateRegistryFilter private_filter) {
  // The input is expected to be a valid, canonicalized hostname (not an IP address).
  CHECK(!canon_host.empty());
  url::CanonHostInfo host_info;
  std::string canonicalized = CanonicalizeHost(canon_host, &host_info);
  CHECK_EQ(canonicalized, canon_host);
  CHECK_EQ(host_info.family, url::CanonHostInfo::NEUTRAL);
  return GetRegistryLengthImpl(canon_host, EXCLUDE_UNKNOWN_REGISTRIES,
                               private_filter).is_registry_identifier;
}
```

三个 `CHECK` 在 release 也生效:**空串 / 非规范 host / IP 字面量传进去 = 浏览器进程直接崩**。而这个函数的输入正是「服务端下发的、未签名的」字符串(`TD-TUNNEL-BIND-RESPONSE-UNSIGNED`)——**顺序错一步就是一个远程可触发的 DoS**。判据里它**必须排在最后**,前面先把「非空 / 规范 / 非 IP」全部确认掉。

---

## 逐条回答

### Q1. `AddRuleFromString` 的真实调用链;`ParseRule` 是否是 `FromUntrimmedRawString` 的超集?

**调用链**:

```
ProxyHostMatchingRules::AddRuleFromString(raw)          proxy_host_matching_rules.cc:206-215
  └─ ParseRule(raw)                                     proxy_host_matching_rules.cc:107-122   (匿名 namespace)
       ├─ 命中 "<local>"      → BypassSimpleHostnamesRule      (:72-88,  常量 :32)
       ├─ 命中 "<-loopback>"  → SubtractImplicitBypassesRule   (:90-105, 常量 :25)
       └─ 否则 SchemeHostPortMatcherRule::FromUntrimmedRawString(raw_untrimmed)
                                                        scheme_host_port_matcher_rule.cc:32-101
  └─ 解析成功 → matcher_.AddAsLastRule(...)             scheme_host_port_matcher.cc:54-58
     解析失败 → 返回 false,规则被丢弃(不报错、不抛异常)
```

**是超集,`<local>` / `<-loopback>` 两条特殊语法确实只在 `ParseRule` 这一层。** 且比较是**大小写不敏感**的:

```cpp
  if (base::EqualsCaseInsensitiveASCII(raw, kBypassSimpleHostnames)) { ... }   // :114-116
  if (base::EqualsCaseInsensitiveASCII(raw, kSubtractImplicitBypasses)) { ... } // :117-119
```

两条特殊规则在**我们的 reverse 语义下**的实际后果(见 `2026-08-16-wildcard-matching.md` 的极性表):

- `<local>`:对**任何不含点且非 IP 字面量**的 host 返回 `kInclude`(`:80-85`)⇒ 在 `reverse_bypass=true` 下把**全部单标签内网主机名**送进隧道。这是注入面里最狠的一条。
- `<-loopback>`:返回 `kExclude`(`:98-102`)⇒ `Matches()` 走 `case kExclude: return reverse;` = `true` ⇒ DIRECT。在我们的配置里它「只是」把隐式保护改写一遍,危害不如 `<local>`,但同样是语法注入,一并拒。

### Q2. 哪些字符/序列会把一条 host 变成**另一种规则**?(完整枚举)

按 `FromUntrimmedRawString`(`scheme_host_port_matcher_rule.cc:32-101`)的处理顺序:

| # | 字符/序列 | 行 | 后果 |
|---|---|---|---|
| 0 | 前后 ASCII 空白(空格 `\t\n\v\f\r`) | :35-36 `base::TrimWhitespaceASCII` | 被静默剥掉;`"  "` ⇒ `nullptr`(单测 `proxy_host_matching_rules_unittest.cc:326`) |
| 1 | `://`(**串内任意位置**,不限开头) | :39-46 `raw.find("://")` | 前缀整段变 **scheme 限定**;scheme 为空 ⇒ `nullptr`。`"a.com://b"` ⇒ scheme=`a.com`, host=`b` |
| 2 | `/` | :53-62 | 整条变 **CIDR IP 段规则** `SchemeHostPortMatcherIPBlockRule`;`ParseCIDRBlock` 失败 ⇒ `nullptr` |
| 3 | **IP 字面量**(`ParseHostAndPort` + `AssignFromIPLiteral` 成功) | :64-76 | 变 **`SchemeHostPortMatcherIPHostRule`**,并且地址被**规范化**(见 Q4:`0x7f.0.0.1` / `2130706433` / `127.1` 全部变成 `127.0.0.1`) |
| 4 | `:`(取 **`rfind`**,最后一个冒号) | :79-88 | 尾部变**端口限定**;端口非法或 `> 0xFFFF` ⇒ `nullptr` |
| 5 | **前导 `.`** | :90-97 | 被**提升为通配**:`".google.com"` ⇒ `"*.google.com"`(上游单测 `proxy_host_matching_rules_unittest.cc:134-138` 逐字断言) |
| 6 | `*` / `?` | `base/strings/pattern.h:16-18` | `MatchPattern` 元字符:`*` = 0..n 个任意字符(**跨点**),`?` = **0 或 1** 个字符。`"*"` 单独一条 = 匹配一切(单测 `:174-183`) |
| 7 | `\` | `base/strings/pattern.cc:49-53` | `*` / `?` 的转义符 |
| 8 | `<local>` / `<-loopback>`(大小写不敏感,trim 后全等) | `proxy_host_matching_rules.cc:114-119` | 见 Q1 |
| 9 | `;` / `,` | — | **`ParseRule` 完全不处理**;它们只在 `ToString()`/`ParseFromString()` 往返时裂开(见 Q3) |
| 10 | `<` / `>`(不构成 `<local>` 时) | — | 留在 hostname pattern 里。`url_canon_host.cc:32` 中 `<`、`>` 的查表值是 `0`(非法),故**任何 URL 的 host 都不可能含它们** ⇒ 该规则永不匹配(哑规则,无害但也无用) |

**注意 #3 的隐蔽性**:`{"host":"0x7f.0.0.1"}` 不会被当成「奇怪的域名」,它会**变成一条精确匹配 `127.0.0.1` 的规则**,在 reverse 语义下把 loopback 流量真的送进 edge。而 `2026-08-16-wildcard-matching.md` Q3 已证明:**显式规则盖过隐式 loopback 保护**,上游的隐式规则救不了这一手。

另有一个次级风险点:`SchemeHostPortMatcherHostnamePatternRule` 构造函数里有 `DCHECK(!url::HostIsIPAddress(hostname_pattern))`(`scheme_host_port_matcher_rule.cc:122`,`url::HostIsIPAddress` 见 `url/url_util.cc:768-773`)。dev 构建 DCHECK 是开的(A-2),把「上游认为是 IP、但 `AssignFromIPLiteral` 没接住」的字符串喂进去就是一次 abort。判据把 IP 字面量整类拒掉,顺带关掉这个面。

### Q3. `operator=` 是否是 `ParseFromString(rhs.ToString())`?分隔符?含 `;`/`,` 的 host 会怎样?前导点片段变成什么?

**是。** `proxy_host_matching_rules.cc:141-145`(全文见 A-1),拷贝构造 `:130-133` 同样走它。

**`ToString()` 用 `;` 拼接**——`ProxyHostMatchingRules::ToString()`(`:227-229`)转发到 `SchemeHostPortMatcher::ToString()`(`net/base/scheme_host_port_matcher.cc:91-99`),后者在**每条规则后面**都 push 一个 `kPrintRuleListDelimiter`,该常量是 `';'`(`net/base/scheme_host_port_matcher.h:36`),所以末尾也有一个多余的 `;`。

**`ParseFromString()` 按 `,;` 两个字符切**——`proxy_host_matching_rules.cc:192-200`:

```cpp
void ProxyHostMatchingRules::ParseFromString(const std::string& raw) {
  Clear();
  base::StringTokenizer entries(raw, SchemeHostPortMatcher::kParseRuleListDelimiterList);
  while (entries.GetNext()) { AddRuleFromString(entries.token_piece()); }
}
```

`kParseRuleListDelimiterList[] = ",;"`(`scheme_host_port_matcher.h:39`)。`base::StringTokenizer` 默认 `options_ == 0`,不返回空 token(`base/strings/string_tokenizer.h:190-196`、`:296`),所以末尾那个多余 `;` 无害。

**⇒ `{"host":"corp.example;.com"}` 的完整命运**:

1. `AddRuleFromString("corp.example;.com")`:`;` 在 `url_canon_host.cc:32` 的查表里是**合法 host 字符**(`';'` → `';'`),没有 `://`、`/`、`:`,`AssignFromIPLiteral` 失败,不以 `.` 开头 ⇒ 生成**一条** `HostnamePatternRule("", "corp.example;.com", -1)`。此时无害。
2. 任意一次拷贝(`operator=` / 拷贝构造 / `mojo::Clone`):`ToString()` ⇒ `"corp.example;.com;"` ⇒ `ParseFromString` 切成 `"corp.example"` 和 `".com"` ⇒ **两条规则**。
3. `".com"` 命中前导点提升(`scheme_host_port_matcher_rule.cc:93-97`)⇒ **`"*.com"`**。

**在 `reverse_bypass=true` 下,`*.com` 意味着整个 `.com` 顶级域被送进隧道。** 这就是「前导点片段被映射成什么」的答案:**被提升为通配规则**,且因为 `*` 跨点,它覆盖 `.com` 下的**全部**主机。

同理 `{"host":"a,b.com"}`:`,` 同样是合法 host 字符(`url_canon_host.cc:30`),一次拷贝后裂成 `a` 与 `b.com` 两条。

### Q4. `GURL("https://"+host)` 往返逐字节比较,能拒掉什么?

判据形如 `GURL u("https://" + host); return u.is_valid() && u.GetHost() == host;`(`GetHost()` 见 `url/gurl.h:330`)。

| 输入 | 规范化后的 host | 往返能否拒掉 | 证据 |
|---|---|---|---|
| `Corp.Example`(大写) | `corp.example` | ✅ 能 | `url/url_canon_host.cc:34-36` 查表把 `A`–`Z` 直接映射成 `a`–`z`;`:277-282` 的注释「the lookup table tells us the canonical representation of that character (lower cased)」 |
| `内网.example`(IDN) | `xn--…​.example` | ✅ 能 | `url/url_canon_host.cc:296-341` `DoIdnHost` → `IDNToASCII`;上游用例 `url/url_canon_unittest.cc:510-511`(`M\xc3\x9cNCHEN` → `xn--mnchen-3ya`)、`:594-595`(中文 → `xn--6qqa088eba`) |
| `127.1` | `127.0.0.1` | ✅ 能 | `url/url_canon_ip.h:164-202` 允许 1–4 段;`:209-226` 把最后一段展开填满 |
| `0x7f.0.0.1` | `127.0.0.1` | ✅ 能 | `url/url_canon_ip.h:60-73` 识别 `0x` 十六进制 / 前导 `0` 八进制;上游用例 `url/url_canon_unittest.cc:846`(`0xC0.0Xa8.0x0.0x1` → `192.168.0.1`) |
| `2130706433` | `127.0.0.1` | ✅ 能 | 同上单段路径;上游用例 `url/url_canon_unittest.cc:869`(`0xC0a80001` → `192.168.0.1`) |
| **`corp.example.`(尾点)** | **`corp.example.`** | ❌ **不能** | 见下 |

**尾点(单独确认,结论与计划的怀疑一致)**:

- **IP 字面量**会被去尾点——`url/url_canon_ip.h:141-144`:
  ```cpp
    // Ignore terminal dot, if present.
    if (!host_view.empty() && host_view.back() == '.') {
      host_view = host_view.substr(0, host_view.length() - 1);
    }
  ```
  上游用例 `url/url_canon_unittest.cc:879`:`{"192.168.0.1.", …, "192.168.0.1", …, CanonHostInfo::IPV4, 4, "C0A80001"}` —— 尾点确实被吃掉。
- **普通域名不会**——`DoSimpleHost`(`url/url_canon_host.cc:241-292`)对 `.` 的查表值就是 `.`(`:30`),原样保留;`CanonicalizeIPAddress` 判定为非 IP 时也不会改写(`:539-561`)。

⇒ `GURL("https://corp.example./")` 的 `GetHost()` **就是** `"corp.example."`,逐字节相等 ⇒ **往返判据放行**。计划 Step 2 的 `RejectsNonCanonicalAndLocalHosts` 里这一条会漏,**必须补一条独立的尾点判据**。

尾点为什么必须拒(不是洁癖):`corp.example.` 与 `corp.example` 是同一个 DNS 名,但 `MatchPattern` 是纯字符串比较,规则 `corp.example.` 永远匹配不上用户真实访问产生的 host `corp.example` ⇒ 一条**看起来生效、实际永不生效**的路由;同时它还会让「edge/gate 排除」(Task 4)与「去重」(Task 5)按字符串比较时把同一主机当成两个。

**另外这些也被往返判据顺手拒掉**(都因为 host 组件被截断/改写):`0.0.0.0/0` → `0.0.0.0`;`corp.example:8080` → `corp.example`;`https://x` → 无效/`https`;`a@b.com` → `b.com`;`a?b.com` → `a`;`a\b.com` → `a`;`a#b` → `a`;`*` → `%2A`(`url_canon_host.cc:30` 的 `kEsc` + `:269-276`);`<local>` / `<-loopback>` → `<`/`>` 查表为 `0`,`DoSimpleHost` 转义后 `success=false` ⇒ host BROKEN ⇒ URL 无效(`:262-268`、`:562-565`)。

**往返判据拒不掉的三类**(必须另立判据):**尾点**、**`;` 与 `,`**(合法 host 字符,`url_canon_host.cc:30,32`)、**前导 `.`**(合法 host 字符,原样保留)。

### Q5. `IsLoopback()` / `IsLinkLocal()` / `IsZero()` 的覆盖面;`IsPubliclyRoutable()` 是否更合适;`localhost` 这类名字能否被 `AssignFromIPLiteral` 命中?

`net/base/ip_address.cc`:

| 方法 | 行 | 覆盖 |
|---|---|---|
| `IsLoopback()` | 259-274 | IPv4 `127.0.0.0/8`;IPv6 `::1`。**不含** IPv4-mapped 的 `::ffff:127.0.0.1` |
| `IsLinkLocal()` | 276-290 | IPv4 `169.254.0.0/16`;IPv4-mapped `::ffff:169.254.0.0/112`;IPv6 `fe80::/10` |
| `IsZero()` | 246-253 | 全零地址(`0.0.0.0` / `::`);空地址返回 `false` |
| `IsUniqueLocalIPv6()` | 292-295 | `fc00::/7` |
| **`IsPubliclyRoutable()`** | **224-231** | IPv4 见 `kReservedIPv4Ranges`(`:112-117`):`0/8, 10/8, 100.64/10, 127/8, 169.254/16, 172.16/12, 192.0.0/24, 192.0.2/24, 192.88.99/24, 192.168/16, 198.18/15, 198.51.100/24, 203.0.113/24, 224/3`;IPv6 只放行 `2000::/3` 与 `ff00::/8`,IPv4-mapped 递归到 IPv4 判定(`:134-158`) |

**`IsPubliclyRoutable()` 明显更合适**:计划 Step 2 的负例含 `10.0.0.5`,而 `IsLoopback() || IsLinkLocal() || IsZero()` 三个加起来**都盖不住 RFC1918 的 `10/8`**——那条测试会红。`IsPubliclyRoutable()` 一个函数覆盖 loopback + link-local + 全零 + 全部 RFC1918 + 多播 + IPv6 ULA(不在 `2000::/3` 内)。

**`localhost` 这类名字:`AssignFromIPLiteral` 命中不了(预期正确)。** `net/base/ip_address.h:273-280` → `internal::ParseIPLiteralToBytes`(`:130-154`):无冒号时只调 `url::IPv4AddressToNumber`,返回 `IPV4` 才算成功;`"localhost"` 的首字符不是数字,`IPv4ComponentToNumber` 返回 `NEUTRAL`(`url/url_canon_ip.h:98-106`)⇒ 整体 `NEUTRAL` ⇒ `false`。

**基于名字的 helper 存在,而且有两个,选对那个**:

- `net::HostStringIsLocalhost(std::string_view host)` —— **`NET_EXPORT`**,`net/base/url_util.h:216-224`,实现 `url_util.cc:472-477`:
  ```cpp
  bool HostStringIsLocalhost(std::string_view host) {
    IPAddress ip_address;
    if (ip_address.AssignFromIPLiteral(host)) return ip_address.IsLoopback();
    return IsLocalHostname(host);
  }
  ```
  一个调用同时盖住「IP 形态的 loopback」与「名字形态的 localhost 族」。
- `net::IsLocalHostname(std::string_view host)` —— 仅 `NET_EXPORT_PRIVATE`(`net/base/url_util.h:290`),实现 `url_util.cc:582-589`:去掉一个尾点后,`EqualsCaseInsensitiveASCII(host, "localhost")` 或 `EndsWith(".localhost")`(`:47-50` 的 `IsNormalizedLocalhostTLD`)。**它覆盖 `sub.localhost`**,这正是计划 Step 2 的负例之一。

⇒ 推荐 `HostStringIsLocalhost()`(公开导出,且是前者的超集)。

**顺带否掉一个诱人但错误的选项**:`net::IsHostnameNonUnique()`(`url_util.cc:417-466`)看起来一函数打尽「私有 IP + 非注册域名」,但它对**没有注册后缀的内网名**同样返回 `true`(`:459-465`)——`app.corp`、`corp.example` 全部会被它判为 non-unique 而误杀,**而这些正是本特性要路由的目标**。不能用。

### Q6. 两标签规则能否挡住 `co.uk` / `github.io` / `s3.amazonaws.com`?

**不能。** `co.uk` 是 2 个标签,`corp.example`(计划要求**放行**的合法内网域)也是 2 个标签;`s3.amazonaws.com` 是 3 个标签,`app.corp.example`(同样要放行)也是 3 个。**标签计数在这两组之间没有任何判别力。**

**正确 API 是 registry_controlled_domains**:

```cpp
net::registry_controlled_domains::HostIsRegistryIdentifier(
    host, net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES)
```

语义(`registry_controlled_domain.h:261-267` + 实现 `registry_controlled_domain.cc:586-598` → `GetRegistryLengthInTrimmedHost` `:179-249`):仅当**整个 host 恰好等于一条 PSL 后缀规则**时 `is_registry_identifier == true`(`:207-209` 的通配分支、`:243-246` 的普通分支)。未命中任何规则时(`:190-200`),由于 `HostIsRegistryIdentifier` 内部硬编码 `EXCLUDE_UNKNOWN_REGISTRIES`,返回 `false`。

对照计划的用例:

| host | PSL 命中 | `HostIsRegistryIdentifier(…, INCLUDE_PRIVATE)` | 期望 |
|---|---|---|---|
| `com` | `effective_tld_names.gperf:1562` | `true` | 拒 ✅ |
| `co.uk` | `:1539` | `true` | 拒 ✅ |
| `github.io` | `:3038`(private) | `true`(**仅当 INCLUDE_PRIVATE**) | 拒 ✅ |
| `s3.amazonaws.com` | `:7567`(private) | `true`(同上) | 拒 ✅ |
| `corp.example` | 无(`example` 不在表中) | `false` | 放行 ✅ |
| `app.corp.example` | 无 | `false` | 放行 ✅ |

**该判据只在 `include_subdomains == true` 时施加**:精确条目 `{"host":"com","port":443}`(无通配)只影响单个名字 `com`,而 `*.com` 才是灾难。计划 Step 2 的三个负例都带 `include_subdomains: true`,与此一致。

**重申 A-4 的顺序约束**:`HostIsRegistryIdentifier` 的三个 `CHECK` 在 release 也生效,**必须**在「非空 / 已确认规范 / 已确认非 IP」之后才调用。

### Q7. 纯 ASCII host 有没有长度上限?

**没有——上游一处也不查。**

`url/url_canon_host.cc:186-195`:

```cpp
// RFC1034 maximum FQDN length.
constexpr size_t kMaxHostLength = 253;
...
constexpr size_t kMaxHostBufferLength = kMaxHostLength * 5;
```

全仓 `grep -rn "kMaxHostLength" url/` 只有这两行;`kMaxHostBufferLength` 唯一使用点在 `DoIdnHost`(`:304-307`),即**只在非 ASCII / 含 `%` 的 IDN 路径**上生效。纯 ASCII 走 `DoSimpleHost`(`:241-292`),**通篇没有任何长度检查**。`url::kMaxURLChars = 2 * 1024 * 1024`(`url/url_constants.h:71`)是进程间传 URL 的上限,不是 host 上限。

`ProxyHostMatchingRules` / `SchemeHostPortMatcherRule` 侧同样没有长度检查。

⇒ 一条 100 KB 的 host 会被完整接受、完整存进规则表、每次 `Evaluate` 都跑一遍 `MatchPattern`(其 `SearchForChars` 是朴素子串搜索,`base/strings/pattern.cc:76-78` 的 TODO 自述为 naive)。**长度上限必须由我们自己加**,它同时是 Task 12「响应体预算」计算的输入。

**可复用的现成正判据**:`net::IsCanonicalizedHostCompliant()`(`NET_EXPORT`,`net/base/url_util.h:189-203`,实现 `url_util.cc:377-415`)一次性提供:

- 总长 ≤ 254(含可选尾点)(`:378-381`);
- 每个标签 ≤ 63、不得为空(`:396-404`、`:411-412`);
- 每字符只允许 `[a-z0-9]`、`-`、`_`(`:405-407`,`IsHostCharAlphanumeric` 在 `:41-45` **只认小写**,注释明说「uppercase characters have already been normalized」);
- 每个标签首字符必须是字母数字或 `-`/`_`(`:389-395`)⇒ **前导 `.` 直接被拒**;
- 最后一个标签必须以字母数字开头(`:414`)。

它一条就把 Q2 表里 #1–#8 的全部元字符、大写、非 ASCII、前导点、空标签、超长标签一起挡掉。**但它明确允许尾点**(`:378-379` 与头文件 `:197` 「Optional trailing dot after last component」),所以尾点仍需单独拒。

---

## 判据建议

### `RejectHost()` 参考实现骨架(顺序是承重的,不可重排)

```cpp
// This check compensates for a deliberate trust-domain downgrade: the routing
// table used to ride the signature-anchored policy channel and now rides an
// unsigned JSON body (TD-TUNNEL-BIND-RESPONSE-UNSIGNED). It is a coarse
// fail-safe, not a policy engine.
//
// AddRuleFromString parses a GRAMMAR, not a hostname: '://' makes a scheme
// rule, '/' a CIDR rule, ':' a port rule, a leading '.' is promoted to a
// wildcard, '*'/'?' are glob metacharacters, and "<local>"/"<-loopback>" are
// special rules. On top of that, ProxyHostMatchingRules' copy assignment is
// ParseFromString(ToString()) — ';' joins, ",;" splits — so a host carrying a
// list delimiter splits into two rules the moment anything copies the object,
// with a leading-dot fragment promoted to a wildcard. Whether the current push
// path happens to copy is not a property we can pin, so reject the grammar's
// metacharacters outright.
//
// ORDERING IS LOAD-BEARING: HostIsRegistryIdentifier() CHECK-crashes (not
// DCHECK) on empty, non-canonical, or IP-literal input, and its input here is
// attacker-influenced. It must run last.
std::optional<std::string> RejectHost(const std::string& host,
                                      bool include_subdomains) {
  // 1. Length. Upstream enforces NO limit on pure-ASCII hosts (kMaxHostLength
  //    in url_canon_host.cc is only used on the IDN path), so we must.
  if (host.empty() || host.size() > 253) return "host length out of range";

  // 2. Canonical-compliant hostname. Kills every rule-grammar metacharacter
  //    (';' ',' '/' ':' '<' '>' '*' '?' '\\' '@' '#' '%' whitespace), uppercase,
  //    non-ASCII, a leading dot, empty labels and >63-char labels in one call.
  if (!net::IsCanonicalizedHostCompliant(host))
    return "not a compliant canonical hostname";

  // 3. Trailing dot. IsCanonicalizedHostCompliant explicitly allows it and the
  //    GURL round-trip below preserves it for non-IP hosts, yet the rule would
  //    then never match the host users actually navigate to.
  if (host.back() == '.') return "trailing dot";

  // 4. IP literals. Rules built from these are canonicalised by net, so a
  //    non-canonical spelling silently becomes a different address.
  net::IPAddress ip;
  if (ip.AssignFromIPLiteral(host)) {
    if (include_subdomains) return "include_subdomains on an IP literal";
    if (!ip.IsPubliclyRoutable()) return "non-routable IP literal";
    return std::nullopt;   // 产品决策点,见下
  }

  // 5. localhost family by NAME (AssignFromIPLiteral never matches these).
  //    An explicit rule beats the implicit loopback bypass, so this is the only
  //    thing standing between a rogue entry and tunnelled loopback traffic.
  if (net::HostStringIsLocalhost(host)) return "localhost family";

  // 6. GURL byte-identity round-trip. Redundant with 2+3+4 for known inputs,
  //    kept as the catch-all for canonicalisation rules we have not enumerated.
  GURL probe(base::StrCat({"https://", host}));
  if (!probe.is_valid() || probe.GetHost() != host)
    return "host is not canonical";

  // 7. Public suffix — ONLY for wildcards, and ONLY with INCLUDE_PRIVATE_
  //    REGISTRIES (github.io / s3.amazonaws.com carry the private flag).
  //    Safe to call here: 1/2/3/6 guarantee non-empty + canonical, 4 guarantees
  //    non-IP — exactly what its three CHECKs demand.
  if (include_subdomains &&
      net::registry_controlled_domains::HostIsRegistryIdentifier(
          host, net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES)) {
    return "include_subdomains over a public suffix";
  }
  return std::nullopt;
}
```

### 需要产品拍板的两个点(不拍板就会写出一条没人能解释的判据)

1. **公网可路由的 IP 字面量放不放行?** 上面的骨架放行(`return std::nullopt`)。计划 Step 2 的负例只有非路由 IP(`10.0.0.5`、`169.254.1.1`),没有公网 IP 用例,所以两种选择都能让测试绿。若产品是「隧道只路由域名」,则把整个第 4 步改成无条件 `return "IP literal"`,并在 `docs/tech-debt.md` 记一条产品约束。
2. **RFC1918 被整类拒掉的代价**:`IsPubliclyRoutable()` 把 `10/8`、`172.16/12`、`192.168/16` 一并判为不可路由。企业内网应用**恰恰**常住在这些网段——但按本设计它们应当以**域名**形态登记(edge 负责解析),而不是以 IP 登记。这条取舍必须写进交付文档,否则第一个用 IP 登记内网应用的租户会得到一个「服务端路由正常、客户端永不路由」的静默漂移——正是本次改动宣称要关闭的那一类。

### 对计划 Step 2 测试清单的影响(逐条核对结论)

| 用例 | 被哪一步拒 | 备注 |
|---|---|---|
| `corp.example;.com` | 2 | 往返判据**拒不掉**(`;` 是合法 host 字符) |
| `a,b.com` | 2 | 同上 |
| `0.0.0.0/0` | 2(往返亦可) | |
| `corp.example:8080` | 2(往返亦可) | |
| `https://x` | 2(往返亦可) | |
| `<local>` / `<-loopback>` | 2(往返亦可) | |
| `*` | 2(往返亦可) | |
| `.corp.example` | 2 | 往返判据**拒不掉**(前导点是合法 host 字符) |
| `Corp.Example` | 2(往返亦可) | |
| **`corp.example.`** | **3** | **2 与 6 都放行**,必须靠独立的尾点判据 |
| `内网.example` | 2(往返亦可) | |
| `127.1` / `0x7f.0.0.1` / `2130706433` | 4(往返亦可) | 4 更早、更明确 |
| `localhost` / `sub.localhost` | 5 | 2/3/4/6 全部放行 |
| `10.0.0.5` / `169.254.1.1` | 4 | 需 `IsPubliclyRoutable()`,`IsLoopback\|\|IsLinkLocal\|\|IsZero` 盖不住 `10/8` |
| `com` / `co.uk` / `github.io`(带通配) | 7 | 需 `INCLUDE_PRIVATE_REGISTRIES`,标签计数无效 |
| `app.corp.example` / `corp.example`+通配 / `adminer.corp.example` | 全部放行 | `example` 不在 PSL 中 |

计划 Step 2 三个负例测试的 `skipped.size()` 期望值(9 / 10 / 3)与本判据一致,**无需改动断言**;需要改的是 Step 4 骨架注释里对 A-1 的因果表述,以及补齐尾点、`IsPubliclyRoutable`、`INCLUDE_PRIVATE_REGISTRIES`、调用顺序这四处此前未定的细节。

### GN 依赖提示

`net::IsCanonicalizedHostCompliant` / `HostStringIsLocalhost`(`net/base/url_util.h`)、`net::IPAddress`(`net/base/ip_address.h`)、`net::registry_controlled_domains::*`(`net/base/registry_controlled_domains/registry_controlled_domain.h`)均在 `//net` 内,而 `teleport_tunnel_logic` 这个 source_set 已经 `deps = [ …, "//net", … ]`(`src/BUILD.gn:94-95`),**无需新增 GN 依赖**。
