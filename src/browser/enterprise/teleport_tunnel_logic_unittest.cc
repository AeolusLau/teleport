// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_logic.h"

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/check_op.h"
#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/values.h"
#include "net/base/proxy_chain.h"
#include "net/base/proxy_server.h"
#include "net/http/http_request_headers.h"
#include "net/proxy_resolution/proxy_config.h"
#include "net/proxy_resolution/proxy_info.h"
#include "net/proxy_resolution/proxy_list.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"

namespace teleport {
namespace {

// --- Unit 3: ProxyConfigPusher (config construction) -----------------------

TEST(TeleportTunnelProxyConfigTest, BuildsReverseBypassRoutingWithTokenHeader) {
  const std::vector<tunnel_internal::RoutableOrigin> origins = {
      {"demoapp.example.com", 443, /*include_subdomains=*/false,
       /*blocked=*/false},
      {"app2.example.com", 443, /*include_subdomains=*/false,
       /*blocked=*/false},
  };
  network::mojom::CustomProxyConfigPtr config =
      tunnel_internal::BuildTunnelProxyConfig("edge.fairyland.io",
                                              /*edge_port=*/443, origins,
                                              "CNFTOKEN");

  ASSERT_TRUE(config);

  // reverse_bypass = whitelist: only the origins route through edge.
  EXPECT_TRUE(config->rules.reverse_bypass);
  EXPECT_EQ(config->rules.type, net::ProxyConfig::ProxyRules::Type::PROXY_LIST);
  EXPECT_TRUE(config->should_override_existing_config);
  // Non-idempotent methods (POST/PUT/…) must route through the tunnel too, or a
  // managed origin's writes bypass the edge and fail (spec P1d §3.1).
  EXPECT_TRUE(config->allow_non_idempotent_methods);

  // single_proxies contains the edge proxy (HTTPS, :443).
  ASSERT_FALSE(config->rules.single_proxies.IsEmpty());
  const net::ProxyServer& edge = config->rules.single_proxies.First().First();
  EXPECT_TRUE(edge.is_https());
  EXPECT_EQ(edge.GetHost(), "edge.fairyland.io");
  EXPECT_EQ(edge.GetPort(), 443);

  // bypass_rules carries each routable origin.
  const std::string bypass = config->rules.bypass_rules.ToString();
  EXPECT_NE(bypass.find("demoapp.example.com"), std::string::npos);
  EXPECT_NE(bypass.find("app2.example.com"), std::string::npos);

  // The cnf token rides the CONNECT via Proxy-Authorization.
  std::optional<std::string> header =
      config->connect_tunnel_headers.GetHeader("Proxy-Authorization");
  ASSERT_TRUE(header);
  EXPECT_EQ(*header, "Bearer CNFTOKEN");

  // The same cnf token also rides non-tunneled forward-proxy (http://) requests
  // so plaintext HTTP backends reach the edge authenticated.
  std::optional<std::string> forward_header =
      config->forward_proxy_headers.GetHeader("Proxy-Authorization");
  ASSERT_TRUE(forward_header);
  EXPECT_EQ(*forward_header, "Bearer CNFTOKEN");
}

}  // namespace
}  // namespace teleport

namespace teleport::tunnel_internal {
namespace {

// Builds a `routable_origins` array the way the bind response carries it.
// NOTE: M151 renamed base::Value::List/Dict to base::ListValue/base::DictValue
// and grew JSONReader::ReadList(), so this is not the base::Value::List +
// TakeList() spelling the plan drafted against M148.
base::ListValue MakeEntries(std::string_view json) {
  std::optional<base::ListValue> list =
      base::JSONReader::ReadList(json, base::JSON_PARSE_RFC);
  CHECK(list);
  return std::move(*list);
}

// The deployment's reserved hosts, host-only (no port) as the service passes
// them. Every ParseRoutableOrigins() call in this file goes through these two so
// the exclusion argument is never accidentally the host under test.
constexpr char kTestEdgeHost[] = "edge.d.example";
constexpr char kTestGateHost[] = "gate.d.example";

TEST(TeleportRoutableOriginParseTest, ParsesWellFormedEntries) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"app.corp","port":443},
        {"host":"corp.example","port":443,"include_subdomains":true},
        {"host":"adminer.corp","port":8080,"blocked":true}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  ASSERT_EQ(out.size(), 3u);
  EXPECT_EQ(out[0].host, "app.corp");
  EXPECT_EQ(out[0].port, 443);
  EXPECT_FALSE(out[0].include_subdomains);
  EXPECT_FALSE(out[0].blocked);
  EXPECT_TRUE(out[1].include_subdomains);
  EXPECT_TRUE(out[2].blocked);
  EXPECT_EQ(out[2].port, 8080);
  EXPECT_TRUE(skipped.empty());
}

TEST(TeleportRoutableOriginParseTest, SkipsMalformedAndReportsReason) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"ok.corp","port":443},
        "not-an-object",
        {"port":443},
        {"host":"","port":443},
        {"host":"noport.corp"},
        {"host":"badport.corp","port":0},
        {"host":"badport2.corp","port":70000}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  ASSERT_EQ(out.size(), 1u);
  EXPECT_EQ(out[0].host, "ok.corp");
  EXPECT_EQ(skipped.size(), 6u);
  for (const auto& s : skipped) {
    EXPECT_FALSE(s.raw.empty());
    EXPECT_FALSE(s.reason.empty());
  }
}

TEST(TeleportRoutableOriginParseTest, EmptyListYieldsEmptyResult) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(MakeEntries("[]"), kTestEdgeHost,
                                  kTestGateHost, &skipped);
  EXPECT_TRUE(out.empty());
  EXPECT_TRUE(skipped.empty());
}

TEST(TeleportRoutableOriginValidationTest, RejectsRuleGrammarInjection) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"corp.example;.com","port":443},
        {"host":"a,b.com","port":443},
        {"host":"0.0.0.0/0","port":443},
        {"host":"corp.example:8080","port":443},
        {"host":"https://x","port":443},
        {"host":"<local>","port":443},
        {"host":"<-loopback>","port":443},
        {"host":"*","port":443},
        {"host":".corp.example","port":443}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  EXPECT_TRUE(out.empty());
  EXPECT_EQ(skipped.size(), 9u);
}

TEST(TeleportRoutableOriginValidationTest, RejectsNonCanonicalAndLocalHosts) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"Corp.Example","port":443},
        {"host":"corp.example.","port":443},
        {"host":"内网.example","port":443},
        {"host":"127.1","port":443},
        {"host":"0x7f.0.0.1","port":443},
        {"host":"2130706433","port":443},
        {"host":"010.0.0.5","port":443},
        {"host":"localhost","port":8080},
        {"host":"sub.localhost","port":8080},
        {"host":"0.0.0.0","port":8080},
        {"host":"169.254.1.1","port":80}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  EXPECT_TRUE(out.empty());
  EXPECT_EQ(skipped.size(), 11u);
}

// IPv6 origins are a PRODUCT LIMIT, settled on the server side: fairyland's
// projection classifies them as their own drop reason (DropReasonIPv6Origin)
// rather than folding them into "malformed", because device-manager's write
// path and the edge's authority validation both refuse them -- an IPv6 route
// the client did tunnel would be denied at the edge anyway.
//
// This test pins the CLIENT half of that agreement. There is no dedicated IPv6
// branch here and there does not need to be: every spelling of an IPv6 literal
// carries ':' (and the bracketed form '[' / ']'), none of which survives
// net::IsCanonicalizedHostCompliant. The two sides therefore agree by
// construction rather than by coincidence -- which is exactly why the reason is
// asserted rather than just the count. If a dedicated IPv6 rejection is ever
// added, this test fails and points at
// docs/verification/2026-08-16-ipv6-origins.md, which must be updated with it.
TEST(TeleportRoutableOriginValidationTest, RejectsIpv6LiteralsInEverySpelling) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"::1","port":443},
        {"host":"[::1]","port":443},
        {"host":"2001:db8::1","port":443},
        {"host":"[2001:db8::1]","port":443},
        {"host":"fe80::1","port":443},
        {"host":"::ffff:10.0.0.5","port":443},
        {"host":"[2001:db8::1]:8443","port":8443}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  EXPECT_TRUE(out.empty());
  ASSERT_EQ(skipped.size(), 7u);
  for (const SkippedEntry& entry : skipped) {
    EXPECT_EQ(entry.reason, "not a compliant canonical hostname") << entry.raw;
  }
}

// PRODUCT DECISION (plan's corrections section): RFC1918 literals are ALLOWED.
// The verification findings proposed IsPubliclyRoutable(), which would reject
// 10/8, 172.16/12 and 192.168/16 wholesale -- but intranet apps living on those
// ranges are this product's target scenario, and per the design's invariants
// routing is not authorization (the edge is the arbiter). What this check has to
// stop is "send EVERYTHING to the edge" and "export the LOCAL machine", not
// "reach an internal address".
TEST(TeleportRoutableOriginValidationTest, AcceptsRfc1918IpLiterals) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"10.0.0.5","port":8080},
        {"host":"192.168.1.10","port":443},
        {"host":"172.16.3.4","port":443}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  EXPECT_EQ(out.size(), 3u);
  EXPECT_TRUE(skipped.empty());
}

TEST(TeleportRoutableOriginValidationTest, RejectsOverlongHost) {
  // Upstream enforces no length limit of its own on a pure-ASCII host on the
  // rule side (kMaxHostLength in url/url_canon_host.cc is consulted only on the
  // IDN path), so the bound has to come from us. It also fixes the worst-case
  // per-entry byte count that the response-size budget is computed from.
  std::string host;
  for (int i = 0; i < 6; ++i) {
    host += std::string(50, 'a') + ".";
  }
  host += "example";  // ~313 chars
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([{"host":")" + host + R"(","port":443}])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  EXPECT_TRUE(out.empty());
  ASSERT_EQ(skipped.size(), 1u);
}

TEST(TeleportRoutableOriginValidationTest, RejectsPublicSuffixWildcards) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"com","port":443,"include_subdomains":true},
        {"host":"co.uk","port":443,"include_subdomains":true},
        {"host":"github.io","port":443,"include_subdomains":true}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  EXPECT_TRUE(out.empty());
  EXPECT_EQ(skipped.size(), 3u);
}

TEST(TeleportRoutableOriginValidationTest, AcceptsLegitimateIntranetHosts) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"app.corp.example","port":443},
        {"host":"corp.example","port":443,"include_subdomains":true},
        {"host":"adminer.corp.example","port":8080}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  EXPECT_EQ(out.size(), 3u);
  EXPECT_TRUE(skipped.empty());
}

TEST(TeleportRoutableOriginExclusionTest, ExcludesEdgeAndGateExactly) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"gate.d.example","port":443},
        {"host":"edge.d.example","port":443},
        {"host":"GATE.D.EXAMPLE","port":443},
        {"host":"app.d.example","port":443}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  ASSERT_EQ(out.size(), 1u);
  EXPECT_EQ(out[0].host, "app.d.example");
  EXPECT_EQ(skipped.size(), 3u);
}

// The self-lock vector: a wildcard over the deployment domain covers the gate,
// so bind's own POST would be routed into the edge -- which needs a cnf token
// bind has not obtained yet. Host equality cannot see this; coverage can.
TEST(TeleportRoutableOriginExclusionTest, ExcludesWildcardCoveringGate) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"d.example","port":443,"include_subdomains":true}
      ])"),
      "edge.tp.d.example", "gate.tp.d.example", &skipped);

  EXPECT_TRUE(out.empty());
  ASSERT_EQ(skipped.size(), 1u);
  EXPECT_NE(skipped[0].reason.find("gate"), std::string::npos);
}

TEST(TeleportRoutableOriginDedupTest, DeduplicatesAndUnionsWildcardFlag) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"sso.corp.example","port":443},
        {"host":"sso.corp.example","port":443,"include_subdomains":true},
        {"host":"sso.corp.example","port":443}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);

  ASSERT_EQ(out.size(), 1u);
  // Two apps may legitimately share a host while disagreeing on the flag --
  // nothing pins it the way scheme consistency is pinned. First-wins would
  // silently strand the wildcard app's subdomains, so the flag is unioned.
  EXPECT_TRUE(out[0].include_subdomains);
  EXPECT_TRUE(skipped.empty());
}

TEST(TeleportRoutableOriginDedupTest, DistinctPortsAreDistinctEntries) {
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(
      MakeEntries(R"([
        {"host":"app.corp.example","port":443},
        {"host":"app.corp.example","port":8443}
      ])"),
      kTestEdgeHost, kTestGateHost, &skipped);
  EXPECT_EQ(out.size(), 2u);
}

// --- the cross-repo byte budget -------------------------------------------

// kMaxBindBodyBytes is one half of a cross-repo pair that has NO compile-time
// protection. fairyland's tunnelroutes package mirrors it verbatim as
// `clientBindBodyCapBytes` and derives its truncation budget `defaultMaxBytes`
// (48 KiB) from it. Moving this number WITHOUT moving the server's in the same
// batch does not fail anything: the server just keeps truncating to a stale
// budget while every status field still reads healthy.
//
// This test is the client-side tripwire. Whoever changes the constant has to
// change this line, and this comment is what tells them the server moves too.
// The arithmetic, and the decision NOT to raise it, are in
// docs/verification/2026-08-16-payload-budget.md.
TEST(TeleportTunnelPayloadBudgetTest, WholeBodyCapIsTheNumberTheServerMirrors) {
  EXPECT_EQ(kMaxBindBodyBytes, 64u * 1024u);
  EXPECT_EQ(kServerRoutesBudgetBytes, 48u * 1024u);
  // Upstream refuses a larger bound outright:
  // SimpleURLLoader::kMaxBoundedStringDownloadSize = 5 * 1024 * 1024
  // (services/network/public/cpp/simple_url_loader.h:110). Spelled as a literal
  // rather than included, so this target keeps its //base + //net + mojom-only
  // dependency set (TD-TUNNEL-UNITTEST-WIRING).
  EXPECT_LE(kMaxBindBodyBytes, size_t{5} * 1024 * 1024);
}

// The closure proof behind that decision: fill the SERVER's whole array budget
// with realistically-shaped entries, wrap it in the rest of the response, and
// show that (a) the budget holds enough origins for a real tenant and (b) the
// whole body still fits under the client cap. If it did not fit, the failure
// mode is not a truncated table -- it is ERR_INSUFFICIENT_RESOURCES on the
// whole request, i.e. no token at all and permanent backoff.
TEST(TeleportTunnelPayloadBudgetTest, ServerBudgetHoldsARealTenantAndStillFits) {
  // A deliberately unflattering entry shape: a 40-character FQDN (longer than
  // typical intranet names), a 4-digit port, and BOTH optional flags present so
  // the server's `omitempty` saves nothing. Per entry this is
  // 19 (framing) + 40 (host) + 4 (port) + 26 (include_subdomains) +
  // 15 (blocked) = 104 bytes, plus one separating comma.
  const auto host_at = [](size_t i) {
    std::string suffix = base::NumberToString(i);
    // 40 chars total: "app" + zero-padded index + ".apps.corp.example.com".
    const std::string tail = ".apps.corp.example.com";  // 22 chars
    std::string label = "app" + std::string(15 - suffix.size(), '0') + suffix;
    std::string host = label + tail;
    CHECK_EQ(host.size(), 40u);
    return host;
  };

  std::string array = "[";
  size_t entries = 0;
  for (;; ++entries) {
    std::string entry =
        base::StrCat({"{\"host\":\"", host_at(entries),
                      "\",\"port\":8443,\"include_subdomains\":true,"
                      "\"blocked\":true}"});
    // Mirrors fairyland's truncateToBudget accounting: the two brackets are
    // charged up front, each entry after the first also pays its comma.
    const size_t need = entry.size() + (entries == 0 ? 0 : 1);
    if (array.size() + need + 1 > kServerRoutesBudgetBytes) {
      break;
    }
    if (entries > 0) {
      array += ",";
    }
    array += entry;
  }
  array += "]";
  ASSERT_LE(array.size(), kServerRoutesBudgetBytes);

  // The decision this test exists to justify: 48 KiB is not a tight fit for a
  // plausible large tenant. Two web apps per declared address is already
  // generous, so ~470 addresses covers an enterprise with hundreds of
  // internally published applications -- with the pessimistic entry shape
  // above, and no cap on entry count anywhere else in the system. The measured
  // value is 468; the floor is stated loosely so a small framing change does
  // not fail the test, but a budget change does.
  EXPECT_GE(entries, 450u);

  // The rest of the body, sized well past reality: an RS256 JWT over a 2048-bit
  // key is ~0.8 KiB, so 4 KiB is a 5x margin on the single largest field.
  const std::string body = base::StrCat(
      {"{\"tunnel_token\":\"", std::string(4096, 'x'),
       "\",\"expires_in\":600,\"routes_stale\":true,\"routes_truncated\":true,"
       "\"routes_dropped\":65535,\"routes_digest\":\"",
       std::string(64, 'a'), "\",\"routable_origins\":", array, "}"});
  EXPECT_LE(body.size(), kMaxBindBodyBytes)
      << "a full-budget response must fit, or bind fails outright";

  // And a full-budget table has to survive parsing, not merely arrive.
  std::vector<SkippedEntry> skipped;
  auto out = ParseRoutableOrigins(MakeEntries(array), kTestEdgeHost,
                                  kTestGateHost, &skipped);
  EXPECT_EQ(out.size(), entries);
  EXPECT_TRUE(skipped.empty());
}

// Asserts the semantics we actually care about, via the same entry point the
// network stack uses: does this URL end up on the edge proxy, or DIRECT?
//
// Do NOT assert on net::ProxyHostMatchingRules::Matches() instead. It answers
// the INVERSE question ("should this URL bypass the proxy"), and under
// reverse_bypass its polarity flips again, so a rule HIT returns false. Going
// through ProxyRules::Apply() keeps the question and the answer aligned
// (docs/verification/2026-08-16-wildcard-matching.md).
::testing::AssertionResult GoesThroughTunnel(
    const network::mojom::CustomProxyConfigPtr& config,
    std::string_view url) {
  net::ProxyInfo info;
  config->rules.Apply(GURL(std::string(url)), &info);
  return info.is_direct()
             ? (::testing::AssertionFailure() << url << " went DIRECT")
             : ::testing::AssertionSuccess();
}

TEST(TeleportTunnelProxyConfigTest, WildcardCoversBothRootAndSubdomain) {
  std::vector<RoutableOrigin> origins;
  origins.push_back({"corp.example", 443, /*include_subdomains=*/true, false});
  auto config = BuildTunnelProxyConfig("edge.d", 443, origins, "tok");

  EXPECT_TRUE(GoesThroughTunnel(config, "https://a.corp.example/"));
  EXPECT_TRUE(GoesThroughTunnel(config, "https://corp.example/"));  // the root
  EXPECT_FALSE(GoesThroughTunnel(config, "https://evilcorp.example/"));
}

TEST(TeleportTunnelProxyConfigTest, NonWildcardEmitsHostOnlyRule) {
  std::vector<RoutableOrigin> origins;
  origins.push_back({"app.corp", 8443, /*include_subdomains=*/false, false});
  auto config = BuildTunnelProxyConfig("edge.d", 443, origins, "tok");

  // Capture is by host, port-agnostic (design section 3.1): an unregistered
  // port must still reach the edge so it produces a denial record that origin
  // discovery can surface. Narrowing here would make misconfiguration silent.
  EXPECT_TRUE(GoesThroughTunnel(config, "https://app.corp:8443/"));
  EXPECT_TRUE(GoesThroughTunnel(config, "https://app.corp:9443/"));
  EXPECT_FALSE(GoesThroughTunnel(config, "https://sub.app.corp/"));
}

TEST(TeleportTunnelProxyConfigTest, UnlistedHostsGoDirect) {
  std::vector<RoutableOrigin> origins;
  origins.push_back({"app.corp", 443, false, false});
  auto config = BuildTunnelProxyConfig("edge.d", 443, origins, "tok");

  EXPECT_FALSE(GoesThroughTunnel(config, "https://www.example.com/"));
}

// --- CONNECT attribution: which chain's results are ours -------------------

// NetworkServiceProxyDelegate does NOT gate the observer notification on
// IsInProxyConfig (its two header-writing siblings do; both of its
// observer-notifying methods do not -- see
// docs/verification/2026-08-16-connect-attribution-patch.md section 5). So
// every CONNECT on this profile's network context is reported to us, and the
// filter is ours to apply. Getting it wrong would let the diagnostics page
// present some unrelated proxy's CONNECT as a tunnel result, which is exactly
// the "cannot see the derived state" failure the page exists to end.
TEST(TeleportTunnelEdgeChainTest, MatchesOnlyTheConfiguredEdgeChain) {
  const auto chain_for = [](net::ProxyServer::Scheme scheme,
                            std::string_view host, uint16_t port) {
    return net::ProxyChain(
        net::ProxyServer::FromSchemeHostAndPort(scheme, host, port));
  };

  EXPECT_TRUE(IsEdgeProxyChain(
      chain_for(net::ProxyServer::SCHEME_HTTPS, "edge.d.example", 443),
      "edge.d.example", 443));
  EXPECT_FALSE(IsEdgeProxyChain(
      chain_for(net::ProxyServer::SCHEME_HTTPS, "other.d.example", 443),
      "edge.d.example", 443));
  EXPECT_FALSE(IsEdgeProxyChain(
      chain_for(net::ProxyServer::SCHEME_HTTPS, "edge.d.example", 8443),
      "edge.d.example", 443));
  // Scheme is part of the identity: an http:// proxy on the same host:port is a
  // different hop, and a CONNECT through it is not our tunnel.
  EXPECT_FALSE(IsEdgeProxyChain(
      chain_for(net::ProxyServer::SCHEME_HTTP, "edge.d.example", 443),
      "edge.d.example", 443));
  EXPECT_FALSE(IsEdgeProxyChain(net::ProxyChain::Direct(), "edge.d.example",
                                443));
}

// The config and the filter must be built from one source, or a change to how
// the edge hop is spelled would silently stop attributing our own CONNECTs.
TEST(TeleportTunnelEdgeChainTest, AgreesWithTheChainTheConfigRoutesThrough) {
  auto config = BuildTunnelProxyConfig("edge.d.example", 8443, {}, "tok");
  ASSERT_FALSE(config->rules.single_proxies.IsEmpty());

  EXPECT_TRUE(IsEdgeProxyChain(config->rules.single_proxies.First(),
                               "edge.d.example", 8443));
}

}  // namespace
}  // namespace teleport::tunnel_internal

// --- The diagnostics snapshot serializer ------------------------------------

namespace teleport::tunnel_internal {
namespace {

// The debug JSON is what StateSnapshotNeverCarriesTheToken searches, so its
// coverage IS that test's strength: a field added to the snapshot but not here
// silently weakens the assertion. This test is the reminder.
TEST(TeleportTunnelSnapshotDebugTest, CoversEveryStringBearingField) {
  TunnelStateSnapshot state;
  state.enrolled = true;
  state.auto_select_policy_present = true;
  state.started = true;
  state.bind_in_flight = true;
  state.has_token = true;
  state.config_pushed = true;
  state.last_bind_attempt_at = base::Time::UnixEpoch() + base::Seconds(1);
  state.last_bind_success_at = base::Time::UnixEpoch() + base::Seconds(2);
  state.token_expires_at = base::Time::UnixEpoch() + base::Seconds(3);
  state.next_refresh_at = base::Time::UnixEpoch() + base::Seconds(4);
  state.next_retry_at = base::Time::UnixEpoch() + base::Seconds(5);
  state.last_bind_error = "BIND_ERROR_MARKER";
  state.routable_origins.push_back({"ORIGIN_MARKER", 443, true, true});
  state.skipped_entries.push_back({"RAW_MARKER", "REASON_MARKER"});
  state.routes_unavailable = true;
  state.routes_hard_stale = true;
  state.routes_hard_stale_reason = "HARDSTALE_MARKER";
  state.routes_stale = true;
  state.routes_truncated = true;
  state.routes_dropped = 9;
  state.routes_digest = "DIGEST_MARKER";
  state.edge_host = "EDGE_MARKER";
  state.edge_port = 8443;
  state.gate_host = "GATE_MARKER";
  state.recent_connects.push_back(
      {base::Time::UnixEpoch() + base::Seconds(6), "AUTHORITY_MARKER", 403});

  const std::string json = TunnelStateSnapshotToDebugJson(state);
  for (const char* marker :
       {"BIND_ERROR_MARKER", "ORIGIN_MARKER", "RAW_MARKER", "REASON_MARKER",
        "HARDSTALE_MARKER", "DIGEST_MARKER", "EDGE_MARKER", "GATE_MARKER",
        "AUTHORITY_MARKER"}) {
    EXPECT_NE(json.find(marker), std::string::npos) << marker;
  }
}

}  // namespace
}  // namespace teleport::tunnel_internal

// --- The diagnostics seam ---------------------------------------------------
//
// The tunnel page's handler is compiled into //chrome/browser/ui/webui, which
// cannot depend on //chrome/browser:core (that edge closes a GN cycle through
// webui:configs), so it reaches the per-profile service through these
// process-global callbacks instead. These tests pin the two properties the
// handler relies on: an unregistered seam answers safely, and a registered one
// is handed the BrowserContext that selects the profile.

namespace teleport {
namespace {

// A stand-in address: the seam only ever forwards the pointer, so the tests
// never dereference it and no real BrowserContext is needed.
content::BrowserContext* FakeContext() {
  return reinterpret_cast<content::BrowserContext*>(0x1234);
}

class TeleportTunnelSeamTest : public testing::Test {
 protected:
  // The seam is process-global; leaving a test's callback registered would leak
  // into every later test in this binary.
  void TearDown() override {
    SetTunnelStateProvider(TunnelStateProvider());
    SetTunnelRebindRequester(TunnelRebindRequester());
  }
};

TEST_F(TeleportTunnelSeamTest, UnregisteredSeamAnswersSafely) {
  // //chrome/browser registers the providers during startup; a page opened
  // before that (or in a build where the registration was dropped) must get an
  // empty snapshot and a refused rebind, never a crash.
  const tunnel_internal::TunnelStateSnapshot state =
      GetTunnelStateSnapshot(FakeContext());
  EXPECT_FALSE(state.started);
  EXPECT_FALSE(state.has_token);
  EXPECT_TRUE(state.routable_origins.empty());
  EXPECT_FALSE(RequestTunnelRebind(FakeContext()));
}

TEST_F(TeleportTunnelSeamTest, RegisteredProviderReceivesTheBrowserContext) {
  // The signature MUST carry the context: the seam is process-global while the
  // service it reaches is per-profile, so a context-free seam would answer for
  // whichever profile happened to register last.
  content::BrowserContext* seen = nullptr;
  SetTunnelStateProvider(base::BindRepeating(
      [](content::BrowserContext** seen, content::BrowserContext* context) {
        *seen = context;
        tunnel_internal::TunnelStateSnapshot state;
        state.started = true;
        return state;
      },
      &seen));

  EXPECT_TRUE(GetTunnelStateSnapshot(FakeContext()).started);
  EXPECT_EQ(seen, FakeContext());
}

TEST_F(TeleportTunnelSeamTest, RegisteredRebindRequesterReceivesTheContext) {
  content::BrowserContext* seen = nullptr;
  SetTunnelRebindRequester(base::BindRepeating(
      [](content::BrowserContext** seen, content::BrowserContext* context) {
        *seen = context;
        return true;
      },
      &seen));

  EXPECT_TRUE(RequestTunnelRebind(FakeContext()));
  EXPECT_EQ(seen, FakeContext());
}

}  // namespace
}  // namespace teleport
