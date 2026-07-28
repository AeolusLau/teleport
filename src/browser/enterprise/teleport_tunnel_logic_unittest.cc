// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_logic.h"

#include <optional>
#include <string>
#include <vector>

#include "base/values.h"
#include "net/base/proxy_server.h"
#include "net/http/http_request_headers.h"
#include "net/proxy_resolution/proxy_config.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// One managed AutoSelectCertificateForUrls list-pref entry (a JSON string), as
// the device-manager compiler emits it.
std::string AutoSelectEntry(const std::string& pattern) {
  return R"({"pattern":")" + pattern +
         R"(","filter":{"ISSUER":{"CN":"Teleport Device CA"}}})";
}

// --- Unit 1: RoutesDeriver -------------------------------------------------

TEST(TeleportTunnelRoutesDeriverTest, ExtractsOriginsAndExcludesEdgeAndGate) {
  base::ListValue entries;
  entries.Append(AutoSelectEntry("https://demoapp.example.com:443"));
  entries.Append(AutoSelectEntry("https://app2.example.com:443"));
  entries.Append(AutoSelectEntry("https://edge.fairyland.io:443"));  // excluded
  entries.Append(AutoSelectEntry("https://gate.fairyland.io:443"));  // excluded
  // Duplicate origin must be de-duplicated.
  entries.Append(AutoSelectEntry("https://demoapp.example.com:443"));

  std::vector<std::string> origins = tunnel_internal::DeriveRoutableOrigins(
      entries, "edge.fairyland.io", "gate.fairyland.io");

  EXPECT_EQ(origins,
            (std::vector<std::string>{"demoapp.example.com", "app2.example.com"}));
}

TEST(TeleportTunnelRoutesDeriverTest, SkipsMalformedEntries) {
  base::ListValue entries;
  entries.Append("not-json");
  entries.Append(R"({"no_pattern":true})");
  entries.Append(AutoSelectEntry("https://demoapp.example.com:443"));

  std::vector<std::string> origins = tunnel_internal::DeriveRoutableOrigins(
      entries, "edge.fairyland.io", "gate.fairyland.io");

  EXPECT_EQ(origins, (std::vector<std::string>{"demoapp.example.com"}));
}

// --- Unit 3: ProxyConfigPusher (config construction) -----------------------

TEST(TeleportTunnelProxyConfigTest, BuildsReverseBypassRoutingWithTokenHeader) {
  network::mojom::CustomProxyConfigPtr config =
      tunnel_internal::BuildTunnelProxyConfig(
          "edge.fairyland.io", /*edge_port=*/443,
          {"demoapp.example.com", "app2.example.com"}, "CNFTOKEN");

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
}

}  // namespace
}  // namespace teleport
