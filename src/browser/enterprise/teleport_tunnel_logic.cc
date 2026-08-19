// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_logic.h"

#include <cstdint>
#include <optional>
#include <utility>

#include "base/check.h"
#include "base/containers/flat_map.h"
#include "base/json/json_writer.h"
#include "base/no_destructor.h"
#include "base/strings/pattern.h"
#include "base/strings/strcat.h"
#include "base/strings/string_util.h"
#include "net/base/ip_address.h"
#include "net/base/proxy_server.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "net/base/url_util.h"
#include "net/http/http_request_headers.h"
#include "net/proxy_resolution/proxy_config.h"
#include "net/proxy_resolution/proxy_host_matching_rules.h"
#include "net/proxy_resolution/proxy_list.h"
#include "url/gurl.h"

namespace teleport {
namespace tunnel_internal {

namespace {

// RFC1034's maximum FQDN length. net::IsCanonicalizedHostCompliant() happens to
// enforce the same bound today; keeping it explicit anchors the per-entry byte
// budget the bind-response size cap is derived from, and does not rely on that
// coincidence holding.
constexpr size_t kMaxHostLength = 253;

std::string EntryToRaw(const base::Value& entry) {
  std::string json;
  base::JSONWriter::Write(entry, &json);
  return json;
}

// The single spelling of "the edge hop", shared by the config the service
// pushes and the filter it applies to incoming CONNECT results. Keeping one
// definition is what stops the two from drifting apart -- a drift whose only
// symptom would be a permanently empty CONNECT list on the diagnostics page.
net::ProxyServer EdgeProxyServer(std::string_view edge_host,
                                 uint16_t edge_port) {
  return net::ProxyServer::FromSchemeHostAndPort(
      net::ProxyServer::SCHEME_HTTPS, edge_host, edge_port);
}

// Returns a rejection reason, or nullopt if `host` may become a routing rule.
//
// This check compensates for a deliberate trust-domain downgrade: the routing
// table used to ride the signature-anchored policy channel and now rides an
// unsigned JSON body (TD-TUNNEL-BIND-RESPONSE-UNSIGNED). It is a coarse
// fail-safe, not a policy engine.
//
// net::ProxyHostMatchingRules::AddRuleFromString parses a GRAMMAR, not a
// hostname: '://' makes a scheme rule, '/' a CIDR rule, ':' a port rule, a
// leading '.' is promoted to a wildcard, '*'/'?' are glob metacharacters, and
// "<local>"/"<-loopback>" are special rules ("<local>" alone would route every
// single-label intranet name into the edge). On top of that,
// ProxyHostMatchingRules' copy assignment is ParseFromString(ToString()) --
// ToString() joins with ';', ParseFromString() splits on ",;" -- so a host
// carrying a list delimiter splits into two rules the moment anything copies
// the object, with a leading-dot fragment promoted to a wildcard. The current
// push path happens not to copy (the mojo traits serialize rule-by-rule), but
// that is not a property we can pin against a future refactor, and upstream's
// own guard is broken: SchemeHostPortMatcher::ToString()'s DCHECK tests for the
// SUBSTRING ",;" rather than for either delimiter. So reject the grammar's
// metacharacters outright.
//
// ORDERING IS LOAD-BEARING: HostIsRegistryIdentifier() CHECK-crashes (not
// DCHECK) on empty, non-canonical, or IP-literal input, and its input here is
// server-supplied and unsigned. It must run last.
std::optional<std::string> RejectHost(const std::string& host,
                                      bool include_subdomains) {
  // 1. Length.
  if (host.empty() || host.size() > kMaxHostLength) {
    return "host length out of range";
  }

  // 2. Canonical-compliant hostname. Kills every rule-grammar metacharacter
  //    (';' ',' '/' ':' '<' '>' '*' '?' '\\' '@' '#' '%' whitespace), uppercase,
  //    non-ASCII, a leading dot, empty labels and >63-char labels in one call.
  if (!net::IsCanonicalizedHostCompliant(host)) {
    return "not a compliant canonical hostname";
  }

  // 3. Trailing dot. IsCanonicalizedHostCompliant explicitly allows it and the
  //    GURL round-trip below preserves it for non-IP hosts (only IP literals get
  //    the dot stripped), yet base::MatchPattern is a plain string comparison,
  //    so the rule would never match the host users actually navigate to -- a
  //    route that looks configured and can never fire.
  if (host.back() == '.') {
    return "trailing dot";
  }

  // 4. IP literals. An IP rule is built from the CANONICALISED address, so a
  //    non-canonical spelling would show one address in diagnostics and route
  //    another ("010.0.0.5" is 8.0.0.5, not 10.0.0.5). Reject any spelling that
  //    is not the canonical one, then reject the addresses that would either
  //    export this machine or turn the rule into a catch-all.
  //
  //    RFC1918 ranges are deliberately ALLOWED (see the plan's decision):
  //    intranet apps on 10/8, 172.16/12 and 192.168/16 are the target scenario,
  //    and reaching an internal address is not authorisation -- the edge is the
  //    arbiter. net::IPAddress::IsPubliclyRoutable() would have rejected them
  //    all. Note an explicit rule BEATS the implicit loopback bypass, so
  //    loopback/link-local/unspecified must be rejected here or a rogue entry
  //    really would tunnel this machine's own services.
  net::IPAddress ip;
  if (ip.AssignFromIPLiteral(host)) {
    if (ip.ToString() != host) {
      return "non-canonical IP literal";
    }
    if (include_subdomains) {
      return "include_subdomains on an IP literal";
    }
    if (ip.IsLoopback() || ip.IsLinkLocal() || ip.IsZero()) {
      return "non-routable IP literal";
    }
    return std::nullopt;
  }

  // 5. The localhost family by NAME. AssignFromIPLiteral never matches these
  //    ("localhost" is not an IP literal), and neither does anything above.
  //    net::IsHostnameNonUnique() would have covered it but also kills
  //    "app.corp" and every other suffix-less intranet name, so it is unusable
  //    here.
  if (net::HostStringIsLocalhost(host)) {
    return "localhost family";
  }

  // 6. GURL byte-identity round-trip. Redundant with 2+3+4 for every input we
  //    enumerated; kept as the catch-all for canonicalisation rules we have not.
  GURL probe(base::StrCat({"https://", host}));
  if (!probe.is_valid() || probe.GetHost() != host) {
    return "host is not canonical";
  }

  // 7. Public suffix -- ONLY for wildcards, and ONLY with
  //    INCLUDE_PRIVATE_REGISTRIES: "github.io" and "s3.amazonaws.com" carry the
  //    private flag and are invisible to the default filter. Label counting is
  //    no substitute: "co.uk" and "corp.example" both have two labels and only
  //    the first must be refused. Safe to call here -- steps 1/2/3/6 guarantee
  //    non-empty and canonical, step 4 guarantees non-IP, which is exactly what
  //    its three CHECKs demand.
  if (include_subdomains &&
      net::registry_controlled_domains::HostIsRegistryIdentifier(
          host, net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES)) {
    return "include_subdomains over a public suffix";
  }
  return std::nullopt;
}

// Normalises a reserved (edge/gate) host for comparison against an entry host.
// Entry hosts are already ASCII-lowercase, trailing-dot-free and canonical
// (RejectHost guarantees it); the reserved hosts come from deployment config and
// are not validated anywhere, so they are the side that needs normalising.
std::string NormalizeReservedHost(std::string_view reserved) {
  std::string out = base::ToLowerASCII(reserved);
  while (!out.empty() && out.back() == '.') {
    out.pop_back();
  }
  return out;
}

// True when the rules this entry would emit capture `reserved`.
//
// Routing either the edge or the gate through the tunnel self-locks the client.
// Equality is not enough: matching is glob and '*' crosses dots, so ANY wildcard
// at or above the deployment domain captures the gate -- moving the gate deeper
// does not help (docs/verification/2026-08-16-edge-gate-coverage.md).
//
// KNOWN COST: hitting the coverage branch drops the ENTIRE wildcard entry, so
// every app under that domain loses routing. Chromium's rule syntax has no
// negation, so "route *.D except gate/edge" is inexpressible. The primary
// defence is therefore the server's write path refusing such registrations;
// this is the fail-safe half.
bool CoversReservedHost(const RoutableOrigin& origin, std::string_view reserved) {
  const std::string target = NormalizeReservedHost(reserved);
  if (target.empty()) {
    return false;
  }
  if (origin.host == target) {
    return true;
  }
  return origin.include_subdomains &&
         base::MatchPattern(target, base::StrCat({"*.", origin.host}));
}

}  // namespace

std::vector<RoutableOrigin> ParseRoutableOrigins(
    const base::ListValue& entries,
    std::string_view edge_host,
    std::string_view gate_host,
    std::vector<SkippedEntry>* skipped) {
  CHECK(skipped);
  std::vector<RoutableOrigin> out;
  // (host, port) -> index into `out`, so a repeat can fold into the entry that
  // is already there instead of appending a second copy.
  base::flat_map<std::pair<std::string, uint16_t>, size_t> first_index;
  for (const base::Value& entry : entries) {
    const base::DictValue* dict = entry.GetIfDict();
    if (!dict) {
      skipped->push_back({EntryToRaw(entry), "entry is not an object"});
      continue;
    }
    const std::string* host = dict->FindString("host");
    if (!host || host->empty()) {
      skipped->push_back({EntryToRaw(entry), "missing or empty host"});
      continue;
    }
    std::optional<int> port = dict->FindInt("port");
    if (!port) {
      skipped->push_back({EntryToRaw(entry), "missing port"});
      continue;
    }
    if (*port < 1 || *port > 65535) {
      skipped->push_back({EntryToRaw(entry), "port out of range"});
      continue;
    }
    const bool include_subdomains =
        dict->FindBool("include_subdomains").value_or(false);
    if (std::optional<std::string> reason =
            RejectHost(*host, include_subdomains)) {
      skipped->push_back({EntryToRaw(entry), *reason});
      continue;
    }
    RoutableOrigin origin;
    origin.host = *host;
    origin.port = static_cast<uint16_t>(*port);
    origin.include_subdomains = include_subdomains;
    origin.blocked = dict->FindBool("blocked").value_or(false);
    // Gate before edge: a wildcard over the deployment domain covers BOTH, and
    // only one reason can be reported. Routing the gate is the fatal one --
    // bind's own POST would then need the cnf token this very bind is trying to
    // obtain, and the tunnel never starts.
    if (CoversReservedHost(origin, gate_host)) {
      skipped->push_back({EntryToRaw(entry), "entry covers the gate host"});
      continue;
    }
    if (CoversReservedHost(origin, edge_host)) {
      skipped->push_back({EntryToRaw(entry), "entry covers the edge host"});
      continue;
    }
    // De-duplicate on (host, port), preserving first-seen order, and UNION the
    // flags rather than letting the first entry win. Two apps may legitimately
    // share a host while disagreeing on include_subdomains -- nothing pins them
    // the way scheme consistency is pinned -- and first-wins would silently
    // strand the wildcard app's subdomains. A duplicate is not an error, so it
    // is folded in rather than reported as skipped.
    auto [it, inserted] =
        first_index.insert({{origin.host, origin.port}, out.size()});
    if (!inserted) {
      RoutableOrigin& existing = out[it->second];
      existing.include_subdomains |= origin.include_subdomains;
      existing.blocked |= origin.blocked;
      continue;
    }
    out.push_back(std::move(origin));
  }
  return out;
}

network::mojom::CustomProxyConfigPtr BuildTunnelProxyConfig(
    std::string_view edge_host,
    uint16_t edge_port,
    const std::vector<RoutableOrigin>& routable_origins,
    std::string_view cnf_token) {
  network::mojom::CustomProxyConfigPtr config =
      network::mojom::CustomProxyConfig::New();

  net::ProxyConfig::ProxyRules rules;
  rules.type = net::ProxyConfig::ProxyRules::Type::PROXY_LIST;
  rules.single_proxies.SetSingleProxyServer(
      EdgeProxyServer(edge_host, edge_port));
  for (const RoutableOrigin& origin : routable_origins) {
    if (origin.include_subdomains) {
      // BOTH rules are required, not belt-and-braces: matching is
      // base::MatchPattern glob (net/base/scheme_host_port_matcher_rule.cc),
      // and "*.corp.example" demands a literal dot before the suffix, so it
      // does NOT match "corp.example" itself. Emitting only the wildcard trades
      // "the whole wildcard domain is lost" for "the wildcard domain's root is
      // lost" -- the same C-2 defect, quieter.
      //
      // Do NOT reach for GenerateSuffixMatchingRule() or a hand-rolled
      // "*" + host: those omit the dot, so "*corp.example" would also capture
      // "evilcorp.example".
      //
      // Polarity warning for anyone writing tests against these rules: with
      // reverse_bypass=true, ProxyHostMatchingRules::Matches() returns FALSE
      // for the hosts we route and TRUE for the ones we do not -- it answers
      // "should this bypass the proxy", not "did this match". Assert through
      // ProxyRules::Apply() instead of Matches() so the question and the answer
      // stay aligned.
      rules.bypass_rules.AddRuleFromString(base::StrCat({"*.", origin.host}));
    }
    // Port-agnostic on purpose (design section 3.1): a bare host rule matches
    // any scheme and any port, so an unregistered port still reaches the edge
    // and produces a denial record instead of silently going DIRECT.
    rules.bypass_rules.AddRuleFromString(origin.host);
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
  // Mirror the cnf token onto forward-proxy (http://) requests —
  // connect_tunnel_headers covers only CONNECT, so http backends would
  // otherwise reach the edge without it.
  config->forward_proxy_headers.SetHeader(
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

bool IsEdgeProxyChain(const net::ProxyChain& proxy_chain,
                      std::string_view edge_host,
                      uint16_t edge_port) {
  // Whole-chain equality, not "does it contain our host": a multi-hop chain
  // that happens to pass through the edge is not the tunnel we configured, and
  // attributing its CONNECT results to the tunnel would be a lie of exactly the
  // kind the diagnostics page exists to stop telling.
  return proxy_chain ==
         net::ProxyChain(EdgeProxyServer(edge_host, edge_port));
}

std::string TunnelStateSnapshotToDebugJson(const TunnelStateSnapshot& state) {
  // Times go out as milliseconds since the Unix epoch, with 0 for "never" --
  // the same encoding the mojom uses, so the page and this debug view cannot
  // drift apart in what they call "unset".
  const auto ms = [](base::Time t) {
    return t.is_null() ? 0.0 : t.InMillisecondsFSinceUnixEpochIgnoringNull();
  };

  base::DictValue root;
  root.Set("enrolled", state.enrolled);
  root.Set("auto_select_policy_present", state.auto_select_policy_present);
  root.Set("started", state.started);
  root.Set("bind_in_flight", state.bind_in_flight);
  root.Set("has_token", state.has_token);
  root.Set("config_pushed", state.config_pushed);
  root.Set("last_bind_attempt_at", ms(state.last_bind_attempt_at));
  root.Set("last_bind_success_at", ms(state.last_bind_success_at));
  root.Set("token_expires_at", ms(state.token_expires_at));
  root.Set("next_refresh_at", ms(state.next_refresh_at));
  root.Set("next_retry_at", ms(state.next_retry_at));
  root.Set("last_bind_error", state.last_bind_error);
  root.Set("routes_unavailable", state.routes_unavailable);
  root.Set("routes_hard_stale", state.routes_hard_stale);
  root.Set("routes_hard_stale_reason", state.routes_hard_stale_reason);
  root.Set("routes_stale", state.routes_stale);
  root.Set("routes_truncated", state.routes_truncated);
  root.Set("routes_dropped", state.routes_dropped);
  root.Set("routes_digest", state.routes_digest);
  root.Set("edge_host", state.edge_host);
  root.Set("edge_port", int{state.edge_port});
  root.Set("gate_host", state.gate_host);

  base::ListValue origins;
  for (const RoutableOrigin& origin : state.routable_origins) {
    base::DictValue entry;
    entry.Set("host", origin.host);
    entry.Set("port", int{origin.port});
    entry.Set("include_subdomains", origin.include_subdomains);
    entry.Set("blocked", origin.blocked);
    origins.Append(std::move(entry));
  }
  root.Set("routable_origins", std::move(origins));

  base::ListValue skipped;
  for (const SkippedEntry& entry : state.skipped_entries) {
    base::DictValue item;
    item.Set("raw", entry.raw);
    item.Set("reason", entry.reason);
    skipped.Append(std::move(item));
  }
  root.Set("skipped_entries", std::move(skipped));

  base::ListValue connects;
  for (const ConnectResult& result : state.recent_connects) {
    base::DictValue item;
    item.Set("time", ms(result.time));
    item.Set("authority", result.authority);
    item.Set("response_code", result.response_code);
    connects.Append(std::move(item));
  }
  root.Set("recent_connects", std::move(connects));

  std::string json;
  base::JSONWriter::Write(root, &json);
  return json;
}

}  // namespace tunnel_internal

namespace {

// Function-local statics rather than file-scope globals: the seam is registered
// once during browser startup and read from the UI thread afterwards, and a
// function-local static has a guaranteed-ordered first initialization.
TunnelStateProvider& MutableStateProvider() {
  static base::NoDestructor<TunnelStateProvider> provider;
  return *provider;
}

TunnelRebindRequester& MutableRebindRequester() {
  static base::NoDestructor<TunnelRebindRequester> requester;
  return *requester;
}

}  // namespace

void SetTunnelStateProvider(TunnelStateProvider provider) {
  MutableStateProvider() = std::move(provider);
}

tunnel_internal::TunnelStateSnapshot GetTunnelStateSnapshot(
    content::BrowserContext* context) {
  const TunnelStateProvider& provider = MutableStateProvider();
  return provider ? provider.Run(context)
                  : tunnel_internal::TunnelStateSnapshot();
}

void SetTunnelRebindRequester(TunnelRebindRequester requester) {
  MutableRebindRequester() = std::move(requester);
}

bool RequestTunnelRebind(content::BrowserContext* context) {
  const TunnelRebindRequester& requester = MutableRebindRequester();
  return requester ? requester.Run(context) : false;
}

}  // namespace teleport
