// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_LOGIC_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_LOGIC_H_

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "base/values.h"
#include "services/network/public/mojom/network_context.mojom.h"

namespace teleport {

// The pure, dependency-light routing/config units of the tunnel service, split
// out of teleport_tunnel_service.{h,cc}. The service itself is compiled into the
// monolithic chrome/browser (via patches/chrome/browser/BUILD.gn.patch) and so
// its symbols are not linkable by the lightweight `teleport_unittests`; these
// free functions, by contrast, touch only //base + //net + //services/network
// mojom + //url (no Profile, no network service, no chrome/browser), so they
// live in the standalone :teleport_tunnel_logic source_set and can be
// unit-tested directly (TD-TUNNEL-UNITTEST-WIRING). Mirrors
// components/private_ai's `internal::CreateCustomProxyConfig`.
namespace tunnel_internal {

// RoutesDeriver: extract the routable origins from the managed
// AutoSelectCertificateForUrls list-pref entries. Each entry is a JSON string
// `{"pattern":"https://host:port","filter":{...}}` (see
// content_settings_policy_provider.cc). Parses `pattern`, takes its host, and
// EXCLUDES the edge and gate hosts (those AutoSelect entries exist for the
// browser->edge / browser->gate mTLS handshakes, not for tunnel routing). Hosts
// are de-duplicated, order preserved. `edge_host` / `gate_host` are host-only
// (no port) because a pattern's GURL host() carries no port.
std::vector<std::string> DeriveRoutableOrigins(
    const base::ListValue& auto_select_entries,
    std::string_view edge_host,
    std::string_view gate_host);

// ProxyConfigPusher core: build the selective-routing + token-injecting
// CustomProxyConfig (see the P1d spec §3.1). `reverse_bypass=true` flips
// `bypass_rules` into a whitelist: ONLY `routable_origins` traverse the edge
// proxy, everything else (device-manager, cert supply, other sites) stays
// DIRECT. The cnf token rides the CONNECT via the `Proxy-Authorization` header.
network::mojom::CustomProxyConfigPtr BuildTunnelProxyConfig(
    std::string_view edge_host,
    uint16_t edge_port,
    const std::vector<std::string>& routable_origins,
    std::string_view cnf_token);

}  // namespace tunnel_internal
}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_LOGIC_H_
