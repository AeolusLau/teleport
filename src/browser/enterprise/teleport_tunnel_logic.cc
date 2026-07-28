// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_logic.h"

#include <optional>
#include <utility>

#include "base/containers/flat_set.h"
#include "base/json/json_reader.h"
#include "base/strings/strcat.h"
#include "net/base/proxy_server.h"
#include "net/http/http_request_headers.h"
#include "net/proxy_resolution/proxy_config.h"
#include "net/proxy_resolution/proxy_host_matching_rules.h"
#include "net/proxy_resolution/proxy_list.h"
#include "url/gurl.h"

namespace teleport {
namespace tunnel_internal {

std::vector<std::string> DeriveRoutableOrigins(
    const base::ListValue& auto_select_entries,
    std::string_view edge_host,
    std::string_view gate_host) {
  std::vector<std::string> origins;
  base::flat_set<std::string> seen;
  for (const base::Value& entry : auto_select_entries) {
    if (!entry.is_string()) {
      continue;
    }
    std::optional<base::DictValue> parsed = base::JSONReader::ReadDict(
        entry.GetString(), base::JSON_ALLOW_TRAILING_COMMAS);
    if (!parsed) {
      continue;
    }
    const std::string* pattern = parsed->FindString("pattern");
    if (!pattern) {
      continue;
    }
    // The device-manager compiler emits patterns in "https://host:port" form,
    // which GURL parses cleanly; anything else (e.g. a bare content-settings
    // wildcard) is skipped rather than mis-parsed.
    GURL url(*pattern);
    if (!url.is_valid() || !url.has_host()) {
      continue;
    }
    std::string host(url.host());
    if (host == edge_host || host == gate_host) {
      continue;  // edge/gate AutoSelect entries are not tunnel-routing origins.
    }
    if (seen.insert(host).second) {
      origins.push_back(std::move(host));
    }
  }
  return origins;
}

network::mojom::CustomProxyConfigPtr BuildTunnelProxyConfig(
    std::string_view edge_host,
    uint16_t edge_port,
    const std::vector<std::string>& routable_origins,
    std::string_view cnf_token) {
  network::mojom::CustomProxyConfigPtr config =
      network::mojom::CustomProxyConfig::New();

  net::ProxyConfig::ProxyRules rules;
  rules.type = net::ProxyConfig::ProxyRules::Type::PROXY_LIST;
  rules.single_proxies.SetSingleProxyServer(
      net::ProxyServer::FromSchemeHostAndPort(net::ProxyServer::SCHEME_HTTPS,
                                              edge_host, edge_port));
  for (const std::string& origin : routable_origins) {
    rules.bypass_rules.AddRuleFromString(origin);
  }
  // Whitelist semantics: with reverse_bypass, only the origins in `bypass_rules`
  // route through `single_proxies` (edge); everything else is DIRECT.
  rules.reverse_bypass = true;
  config->rules = std::move(rules);

  // CONNECT-header injection: the cnf token rides every CONNECT to the edge
  // proxy. Header name is Proxy-Authorization (private_ai's precedent injects a
  // plain Authorization header — same mechanism, different name/value).
  config->connect_tunnel_headers.SetHeader(
      "Proxy-Authorization", base::StrCat({"Bearer ", cnf_token}));
  config->should_override_existing_config = true;
  // Route non-idempotent methods (POST/PUT/…) through the tunnel too: the edge
  // is a blind L4 splice that handles any method, and a managed origin must be
  // reachable for its writes, not just idempotent GETs. Without this the default
  // (false) sends POST/etc. to the managed origin DIRECT — bypassing the tunnel
  // and failing, since the origin is reachable only via the edge (spec P1d §3.1).
  config->allow_non_idempotent_methods = true;
  return config;
}

}  // namespace tunnel_internal
}  // namespace teleport
