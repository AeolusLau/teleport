# 验证结论:通配匹配语义(Task 2 Step 1)

- **验证对象**:`$TELEPORT_CHROMIUM_ROOT/151.0.7922/src`(M151,`CHROMIUM_VERSION=151.0.7922.76`)
- **验证方式**:纯源码 + 上游单测阅读,全部结论带 `file:line`
- **产出用途**:直接决定 Task 2 Step 2 的测试断言与 Step 4 的实现

---

## ⚠️ 头号结论:计划 Task 2 Step 2 的两个测试,**断言方向整体反了**

计划里写:

```cpp
// NOTE: `reverse` MUST be passed explicitly — its default is false, and a
// test that forgets it asserts the inverse semantics while still going green.
EXPECT_TRUE(rules.Matches(GURL("https://a.corp.example/"), /*reverse=*/true));
EXPECT_TRUE(rules.Matches(GURL("https://corp.example/"),   /*reverse=*/true));
EXPECT_FALSE(rules.Matches(GURL("https://evilcorp.example/"), /*reverse=*/true));
```

**这段注释把因果说反了,而且四个断言全部会红。** 真实语义是:

`ProxyHostMatchingRules::Matches(url, reverse)` 返回的是 **「这个 URL 应该 bypass 代理(走 DIRECT)吗」**,不是「这个 URL 命中了规则吗」。
在 `reverse_bypass = true` 的隧道白名单配置下,**命中规则 ⇒ `Matches()` 返回 `false`**(不 bypass ⇒ 走 edge 代理);**未命中 ⇒ 返回 `true`**(bypass ⇒ DIRECT)。

`net/proxy_resolution/proxy_host_matching_rules.cc:159-176`:

```cpp
bool ProxyHostMatchingRules::Matches(const GURL& url, bool reverse) const {
  switch (matcher_.Evaluate(url)) {
    case SchemeHostPortMatcherResult::kInclude:
      return !reverse;            // 命中 include 规则 + reverse=true ⇒ false
    case SchemeHostPortMatcherResult::kExclude:
      return reverse;
    case SchemeHostPortMatcherResult::kNoMatch:
      break;
  }
  // If none of the explicit rules matched, fall back to the implicit rules.
  bool matches_implicit = MatchesImplicitRules(url);
  if (matches_implicit) {
    return matches_implicit;
  }
  return reverse;                 // 未命中 + reverse=true ⇒ true
}
```

调用方证明它就是「是否 bypass」——`net/proxy_resolution/proxy_config.cc:60-70`:

```cpp
void ProxyConfig::ProxyRules::Apply(const GURL& url, ProxyInfo* result) const {
  if (empty()) { result->UseDirect(); return; }
  if (bypass_rules.Matches(url, reverse_bypass)) {
    result->UseDirectWithBypassedProxy();     // ← 返回 true = 不走代理
    return;
  }
  ...
```

上游单测直接给出反向语义的期望值(`net/proxy_resolution/proxy_config_unittest.cc:916-939`):

```cpp
rules.bypass_rules.AddRuleFromString(".com");
...
// Try with reversed bypass rules.
rules.reverse_bypass = true;
rules.Apply(GURL("http://example.org"), &result);
EXPECT_TRUE(result.is_direct_only());   // 未命中 → DIRECT
rules.Apply(GURL("http://example.com"), &result);
EXPECT_FALSE(result.is_direct());       // 命中   → 走代理
```

**推论(直接推翻计划的注释)**:

| 场景 | `Matches(url, /*reverse=*/false)` | `Matches(url, /*reverse=*/true)` | 真实隧道行为 |
|---|---|---|---|
| `a.corp.example` 命中 `*.corp.example` | `true` | **`false`** | 走 edge |
| `corp.example` 命中 `corp.example` | `true` | **`false`** | 走 edge |
| `evilcorp.example` 未命中 | `false` | **`true`** | DIRECT |

也就是说:**计划里那三条断言在「忘记传 `reverse`」时全绿,在「按计划正确传 `reverse=true`」时全红**——和注释宣称的完全相反。这条注释如果照抄进代码,会把下一个读代码的人钉死在错误心智模型上,必须改。

---

## 逐条回答

### Q1. 匹配函数是不是 `base::MatchPattern(url.GetHost(), hostname_pattern_)`?

**是。** `net/base/scheme_host_port_matcher_rule.cc:125-142`:

```cpp
SchemeHostPortMatcherResult SchemeHostPortMatcherHostnamePatternRule::Evaluate(
    const GURL& url) const {
  if (optional_port_ != -1 && url.EffectiveIntPort() != optional_port_) {
    return SchemeHostPortMatcherResult::kNoMatch;
  }
  if (!optional_scheme_.empty() && url.GetScheme() != optional_scheme_) {
    return SchemeHostPortMatcherResult::kNoMatch;
  }
  return base::MatchPattern(url.GetHost(), hostname_pattern_)
             ? SchemeHostPortMatcherResult::kInclude
             : SchemeHostPortMatcherResult::kNoMatch;
}
```

补充三点(都影响判据):

1. `url.GetHost()` 是 `std::string GetHost() const { return ComponentString(parsed_.host); }`(`url/gurl.h:330`),取的是**已规范化**的 host——ASCII 已小写、IDN 已 punycode 化、IP 字面量已规范拼写。
2. `hostname_pattern_` 在构造时被 `base::ToLowerASCII` 归一(`scheme_host_port_matcher_rule.cc:118-120`),所以规则里的大写会被吃掉;`ProxyHostMatchingRulesTest.ParseAndMatchBasicHost` 明确断言 `"wWw.gOogle.com"` → `"www.google.com"`(`net/proxy_resolution/proxy_host_matching_rules_unittest.cc:114-117`)。
3. IP 字面量走的是**另一个类** `SchemeHostPortMatcherIPHostRule`,同样用 `base::MatchPattern(url.GetHost(), ip_host_)`(`scheme_host_port_matcher_rule.cc:183-200`);CIDR 走第三个类 `SchemeHostPortMatcherIPBlockRule`(`:229-248`)。

`base::MatchPattern` 的语义(`base/strings/pattern.h:14-18`):

```
// The backslash character (\) is an escape character for * and ?.
// ? matches 0 or 1 character, while * matches 0 or more characters.
```

`*` **跨点**(它就是普通的「任意字符任意个数」,实现见 `base/strings/pattern.cc:97-112` 的 `EatWildcards` 返回 `-1` 表示无限距离 + `:34-90` 的 `SearchForChars`);`?` 是**0 或 1** 个字符(不是常见的「恰好 1 个」);`\` 转义 `*`/`?`(`pattern.cc:49-53`)。

### Q2. `*.corp.example` 是否匹配 `corp.example` 本身?

**不匹配。必须发两条规则。**

机制:`MatchPatternT`(`base/strings/pattern.cc:114-128`)吃掉前导 `*` 后,`SearchForChars` 必须在字符串里找到字面量 `.corp.example`,且模式耗尽时字符串也必须耗尽(`pattern.cc:35-40`:`if (*pattern == pattern_end) { if (*string == string_end) return true; }`)。`"corp.example"` 里不含 `".corp.example"`,故失败。

上游单测**逐字给出这个期望**(`net/proxy_resolution/proxy_host_matching_rules_unittest.cc:132-151`):

```cpp
rules.ParseFromString(".gOOgle.com");
EXPECT_EQ("*.google.com", rules.rules()[0]->ToString());
...
EXPECT_TRUE(rules.Matches(GURL("http://www.google.com")));
// Must be a strict "ends with" to work.
EXPECT_FALSE(rules.Matches(GURL("http://google.com")));       // ← 就是这一条
EXPECT_FALSE(rules.Matches(GURL("http://foo.google.com.baz.org")));
```

即 `*.google.com` 明确**不**匹配 `google.com`,并且因为模式必须匹配到串尾,也**不**匹配 `foo.google.com.baz.org`。

**反面提醒**:上游提供了 `SchemeHostPortMatcherHostnamePatternRule::GenerateSuffixMatchingRule()`(`scheme_host_port_matcher_rule.cc:158-167`),它生成的是 `"*" + hostname_pattern_`(**不带点**)。`*corp.example` 会匹配 `evilcorp.example`,是个典型陷阱——上游单测 `DoesNotUseSuffixMatching` 里的 `*foobar.com:80` 就是这种形状(`proxy_host_matching_rules_unittest.cc:301`)。**不要用它做「加通配」的捷径**;正确形状就是计划写的 `*.` + host 与 host 两条。

### Q3. `ProxyHostMatchingRules::Matches(url, reverse)` 的 `reverse` 默认值?

**默认 `false`。** `net/proxy_resolution/proxy_host_matching_rules.h:56-63`:

```cpp
  // Returns true if the bypass rules indicate that |url| should bypass the
  // proxy. Matching is done using both the explicit rules, as well as a
  // set of global implicit rules.
  //
  // If |reverse| is set to true then the bypass
  // rule list is inverted (this is almost equivalent to negating the result of
  // Matches(), except for implicit matches).
  bool Matches(const GURL& url, bool reverse = false) const;
```

计划担心的「忘记传 `reverse` 会静默测反」在**方向上是对的**(默认值确实是 `false`,漏传就换了一套语义),但计划给出的断言恰恰是「漏传才绿」的那一套。注意头文件自己也点明了 `reverse` **不是**单纯取反:隐式规则(localhost / link-local)是例外,见下。

**隐式规则(承重,别忽略)**——`proxy_host_matching_rules.cc:159-176` 的 fallback 段 + `:235-270` 的 `MatchesImplicitRules`:显式规则**全部未命中**时,`localhost` / `*.localhost` / `127.0.0.0/8` / `[::1]` / `[::ffff:127.x]` / `169.254/16` / `[fe80::]/10`(Windows 另加 `loopback`)恒返回 `true`,即**恒 DIRECT,`reverse` 也翻不动它**。

但反过来:**显式规则会盖过隐式规则**。`SchemeHostPortMatcher::Evaluate` 逆序遍历、遇到第一个非 `kNoMatch` 就短路返回(`net/base/scheme_host_port_matcher.cc:71-89`),而隐式规则只在 `kNoMatch` 之后才被查(`proxy_host_matching_rules.cc:168-175`)。**所以一条 `localhost` 或 `127.0.0.1` 规则会把 loopback 流量真的送进隧道**——隐式保护救不了我们,这必须靠 Task 3 的客户端判据挡(详见 `2026-08-16-rule-grammar.md`)。

### Q4. 裸 host 规则是否匹配任意 scheme、任意 port?

**是。** 两个门在 `optional_port_ == -1`、`optional_scheme_.empty()` 时都不生效(`scheme_host_port_matcher_rule.cc:127-135`),而裸 host 经 `FromUntrimmedRawString` 解析后正是 `scheme=""`、`port=-1`(`scheme_host_port_matcher_rule.cc:39-46`(无 `://` ⇒ scheme 空)、`:79-88`(无 `:` ⇒ port 保持 `-1`)、`:99-100`)。

上游单测(`proxy_host_matching_rules_unittest.cc:112-130`):

```cpp
rules.ParseFromString("wWw.gOogle.com");
// All of these match; port, scheme, and non-hostname components don't matter.
EXPECT_TRUE(rules.Matches(GURL("http://www.google.com")));
EXPECT_TRUE(rules.Matches(GURL("ftp://www.google.com:99")));
EXPECT_TRUE(rules.Matches(GURL("https://www.google.com:81")));
// Must be a strict host match to work.
EXPECT_FALSE(rules.Matches(GURL("http://foo.www.google.com")));
EXPECT_FALSE(rules.Matches(GURL("http://xxx.google.com")));
EXPECT_FALSE(rules.Matches(GURL("http://google.com")));
```

这正好**支持** design §3.1 的「按 host 捕获、端口无关」:未登记端口也会到 edge,从而产生一条拒绝记录,而不是静默走 DIRECT。计划 Task 2 Step 2 第二个测试的**意图**(8443 与 9443 都被捕获、`sub.app.corp` 不被捕获)是对的,只是断言极性要翻。

---

## 判据建议

### 1. 测试里不要直接断言 `Matches()`,断言「是否走隧道」

`Matches()` 的极性是这次踩坑的根源。推荐在测试文件里定义一个自解释的 helper,直接跑真实生效路径 `ProxyRules::Apply`(`net/proxy_resolution/proxy_config.cc:60-91`),这样极性错误在语义层面就不可能发生:

```cpp
// Reads as the question the product actually asks: "does this URL go to the
// edge?" net::ProxyHostMatchingRules::Matches() answers the INVERSE question
// ("should this URL bypass the proxy"), and under reverse_bypass its polarity
// flips again — asserting on it directly is how a green test ends up pinning
// the opposite of the intended behaviour.
bool RoutedThroughTunnel(const net::ProxyConfig::ProxyRules& rules,
                         const GURL& url) {
  net::ProxyInfo info;
  rules.Apply(url, &info);
  return !info.is_direct();
}
```

Task 2 Step 2 的两个测试改写为:

```cpp
TEST(TeleportTunnelProxyConfigTest, WildcardCoversBothRootAndSubdomain) {
  ...
  // 取整个 ProxyRules(不是 bypass_rules):Apply 的第一句是
  // `if (empty()) { result->UseDirect(); return; }`,而 empty() 就是
  // `type == Type::EMPTY`(net/proxy_resolution/proxy_config.h:52)。
  // BuildTunnelProxyConfig 已把 type 设为 PROXY_LIST 并填了 single_proxies
  // (src/browser/enterprise/teleport_tunnel_logic.cc:68-71),故这条前置成立。
  const auto& rules = config->rules;
  EXPECT_TRUE(RoutedThroughTunnel(rules, GURL("https://a.corp.example/")));
  EXPECT_TRUE(RoutedThroughTunnel(rules, GURL("https://corp.example/")));
  EXPECT_FALSE(RoutedThroughTunnel(rules, GURL("https://evilcorp.example/")));
}

TEST(TeleportTunnelProxyConfigTest, NonWildcardEmitsHostOnlyRule) {
  ...
  EXPECT_TRUE(RoutedThroughTunnel(rules, GURL("https://app.corp:8443/")));
  EXPECT_TRUE(RoutedThroughTunnel(rules, GURL("https://app.corp:9443/")));
  EXPECT_FALSE(RoutedThroughTunnel(rules, GURL("https://sub.app.corp/")));
}
```

若坚持直接用 `bypass_rules.Matches()`,则**唯一正确**的写法是全部取反并显式传 `reverse=true`:

```cpp
EXPECT_FALSE(rules.bypass_rules.Matches(GURL("https://a.corp.example/"),   /*reverse=*/true));
EXPECT_FALSE(rules.bypass_rules.Matches(GURL("https://corp.example/"),     /*reverse=*/true));
EXPECT_TRUE (rules.bypass_rules.Matches(GURL("https://evilcorp.example/"), /*reverse=*/true));
```

### 2. 规则产出判据(Step 4 实现)

```
对每条 RoutableOrigin:
  if (include_subdomains)  AddRuleFromString("*." + host);   // 只覆盖真子域
  AddRuleFromString(host);                                    // 覆盖根域本身
```

- **两条都必须发**:`*.H` 因 `MatchPattern` 要求 `H` 前必须有字面点,永不匹配 `H` 本身(证据见 Q2)。只发通配 = 把「整个通配域丢失」换成「通配域的根丢失」,是同一个 C-2 缺陷的安静版本。
- **禁止**用 `GenerateSuffixMatchingRule()` 或手写 `"*" + host`:那会匹配 `evil` + `H`。
- 两条规则的相对顺序**无所谓**:两条都是 `kInclude` 型,而 `SchemeHostPortMatcher::Evaluate` 的逆序短路只在混入 `kExclude` 型规则时才有语义(`net/base/scheme_host_port_matcher.cc:71-89`)。我们不产出 `kExclude` 规则,故顺序自由;**若将来引入 `<-loopback>` 之类的负规则,这条豁免立即失效**。
- 规则里**不要**带端口、不要带 scheme:裸 host 已是「任意 scheme、任意端口」,这正是 design §3.1 想要的捕获面(Q4)。

### 3. 给实现代码的注释(替换计划里那段错误注释)

```cpp
// BOTH rules are required, not belt-and-braces: matching is base::MatchPattern
// glob (scheme_host_port_matcher_rule.cc), and "*.corp.example" demands a
// literal dot before the suffix, so it does NOT match "corp.example" itself.
//
// Polarity warning for anyone writing tests against these rules: with
// reverse_bypass=true, ProxyHostMatchingRules::Matches() returns FALSE for the
// hosts we route and TRUE for the ones we do not — it answers "should this
// bypass the proxy", not "did this match". Assert through ProxyRules::Apply()
// instead of Matches() so the question and the answer stay aligned.
```
