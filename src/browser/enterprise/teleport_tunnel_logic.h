// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_LOGIC_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_LOGIC_H_

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "base/functional/callback.h"
#include "base/time/time.h"
#include "base/values.h"
#include "net/base/proxy_chain.h"
#include "services/network/public/mojom/network_context.mojom.h"

// Forward declaration only. The seam below takes a BrowserContext*, but this
// target must stay free of //content/public/browser: adding it would make this
// source_set unlinkable from the lightweight `teleport_unittests`, which is the
// whole reason the pure logic lives here (TD-TUNNEL-UNITTEST-WIRING).
namespace content {
class BrowserContext;
}  // namespace content

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

// Cap on the ENTIRE bind response body, handed to
// network::SimpleURLLoader::DownloadToString. Exceeding it is NOT a truncation:
// the request fails with net::ERR_INSUFFICIENT_RESOURCES, so there is no token
// at all and the service falls into backoff.
//
// CROSS-REPO COUPLING, NO COMPILE-TIME PROTECTION. fairyland's
// products/teleport/gateway/internal/tunnelroutes mirrors this value as
// `clientBindBodyCapBytes` and derives its truncation budget from it. Raising
// this alone buys nothing (the server keeps truncating to the old budget);
// raising it without the server is invisible, because a truncated table still
// reports healthy. Move BOTH in the same batch, or neither. Both sides are
// pinned by a test; this side's is
// TeleportTunnelPayloadBudgetTest.WholeBodyCapIsTheNumberTheServerMirrors.
//
// Deliberately NOT configurable. A knob here would need a default, and a zero
// default would make every bind fail -- the mirror image of the server's own
// finding that a zero budget there ships a valid token beside an empty table.
// A constant has no uninitialised path at all, which is why it stays one.
inline constexpr size_t kMaxBindBodyBytes = 64 * 1024;

// The server's budget for the `routable_origins` array alone, recorded here so
// the client can assert the pair still closes (see the payload-budget test and
// docs/verification/2026-08-16-payload-budget.md). This is a MIRROR of
// fairyland's `defaultMaxBytes`, not an input to any client behaviour -- the
// client never truncates; it parses whatever arrives within the cap above.
inline constexpr size_t kServerRoutesBudgetBytes = 48 * 1024;

// One entry of the server-supplied routing table (see the group-A spec section 5).
// `include_subdomains` is a STRUCTURED field, never a string convention --
// that is the whole point of moving off the content-settings `[*.]` pattern
// whose GURL parse failure silently dropped every wildcard origin (C-2).
// `blocked` is DIAGNOSTICS ONLY: the server marks the address as having no
// route row of its own; the edge's own verdict is computed over a collapsed
// claimant set, so this flag must never be presented as "will certainly fail".
struct RoutableOrigin {
  std::string host;
  uint16_t port = 0;
  bool include_subdomains = false;
  bool blocked = false;

  // The service compares a freshly parsed table against the one it is holding
  // to decide whether a re-push is needed.
  friend bool operator==(const RoutableOrigin&, const RoutableOrigin&) = default;
};

// An entry that did not survive parsing/validation, kept so the diagnostics
// page can show it. Silently dropping entries is exactly the C-2 defect this
// whole change replaces, so every rejection must be reportable.
struct SkippedEntry {
  std::string raw;
  std::string reason;
};

// Parses the bind response's `routable_origins` array. Malformed entries are
// skipped and reported through `skipped` rather than failing the whole table:
// one bad row must not cost a tenant its entire routing table. Callers MUST
// surface `skipped`.
//
// `edge_host` / `gate_host` are HOST-ONLY (no port) and are excluded from the
// result -- including by any wildcard entry that would COVER them, which would
// otherwise route bind's own request into the edge and self-lock the tunnel.
std::vector<RoutableOrigin> ParseRoutableOrigins(
    const base::ListValue& entries,
    std::string_view edge_host,
    std::string_view gate_host,
    std::vector<SkippedEntry>* skipped);

// ProxyConfigPusher core: build the selective-routing + token-injecting
// CustomProxyConfig (see the P1d spec §3.1). `reverse_bypass=true` flips
// `bypass_rules` into a whitelist: ONLY `routable_origins` traverse the edge
// proxy, everything else (device-manager, cert supply, other sites) stays
// DIRECT. The cnf token rides the CONNECT via the `Proxy-Authorization` header.
network::mojom::CustomProxyConfigPtr BuildTunnelProxyConfig(
    std::string_view edge_host,
    uint16_t edge_port,
    const std::vector<RoutableOrigin>& routable_origins,
    std::string_view cnf_token);

// One CONNECT result observed on the tunnel, for the diagnostics page.
struct ConnectResult {
  base::Time time;
  // "host:port" of the origin the CONNECT was issued for -- the attribution
  // the upstream ProxyDelegate patch exists to provide. Without it a failure is
  // visible but unattributable.
  std::string authority;
  int response_code = 0;
};

// True when `proxy_chain` is exactly the single hop BuildTunnelProxyConfig
// routes through for this edge.
//
// The client MUST filter: NetworkServiceProxyDelegate forwards every proxy
// chain's CONNECT result to the observer, with no IsInProxyConfig gate (its two
// header-writing siblings have one; both of its observer-notifying methods do
// not -- docs/verification/2026-08-16-connect-attribution-patch.md section 5).
// Upstream's own observer, PrefetchProxyConfigurator, filters identically, so
// this is the established convention rather than a local defence.
//
// Shares its notion of "the edge hop" with BuildTunnelProxyConfig, so a change
// to how that hop is spelled cannot silently stop attributing our own CONNECTs.
bool IsEdgeProxyChain(const net::ProxyChain& proxy_chain,
                      std::string_view edge_host,
                      uint16_t edge_port);

// Everything the teleport://tunnel diagnostics page is allowed to see about a
// profile's tunnel, as one immutable pull.
//
// It deliberately carries NO cnf token and no field derived from one: the token
// is an in-memory bearer credential, and a diagnostics page is a rendering
// surface with a DevTools console attached. `has_token` is the only thing the
// page needs — whether a credential is held, never which one.
struct TunnelStateSnapshot {
  // --- the read-gate's two inputs, so a refused rebind can explain itself ---
  bool enrolled = false;
  bool auto_select_policy_present = false;

  // --- orchestration ---
  // The bind orchestration has begun for this profile (Start() ran). False
  // means the profile is not enrolled yet, or //chrome/browser never
  // registered the provider.
  bool started = false;
  bool bind_in_flight = false;
  // A cnf is currently held. NEVER the token itself; see above.
  bool has_token = false;
  // A CustomProxyConfig has actually gone out over the wire at least once.
  // Diagnostics only -- it is NOT the re-push predicate (see
  // TeleportTunnelService::BindProxyConfigClient for why that was a bug).
  bool config_pushed = false;

  // --- timing. A null base::Time means "never" / "not armed", never "now". ---
  base::Time last_bind_attempt_at;
  base::Time last_bind_success_at;
  // What the server said, not what the client guessed: the refresh loop is
  // driven by the same value, so the page cannot show an expiry the client is
  // knowingly running past.
  base::Time token_expires_at;
  base::Time next_refresh_at;
  base::Time next_retry_at;

  // Why the last bind failed, in operator-readable form. Empty after a success.
  std::string last_bind_error;

  // --- the routing table in force ---
  // Exactly as the last well-formed bind response left it.
  std::vector<RoutableOrigin> routable_origins;
  // Entries that response carried but that did not survive validation. Shown so
  // a rejection is never silent -- silent dropping is the C-2 defect this whole
  // change replaces.
  std::vector<SkippedEntry> skipped_entries;
  // No well-formed table has EVER been adopted. Distinct from having adopted an
  // explicitly empty one, and the page must word the two differently.
  bool routes_unavailable = true;
  // The last successful bind carried no usable table, so the one above is one an
  // earlier response vouched for and nothing since has re-confirmed. Preserving
  // it is only safe while somebody can see that it is being preserved, so this
  // has to be shown prominently.
  bool routes_hard_stale = false;
  std::string routes_hard_stale_reason;
  // Server-supplied metadata. DIAGNOSTICS ONLY by the cross-repo contract: none
  // of these participates in a routing decision.
  bool routes_stale = false;
  bool routes_truncated = false;
  int routes_dropped = 0;
  std::string routes_digest;

  // --- topology, so the page can show what "the tunnel" resolves to ---
  std::string edge_host;
  uint16_t edge_port = 0;
  std::string gate_host;

  // --- observed CONNECT results on our chain, newest first ---
  std::vector<ConnectResult> recent_connects;
};

// Serialises a snapshot for tests and VLOG.
//
// Its coverage is load-bearing: StateSnapshotNeverCarriesTheToken asserts the
// cnf does not appear in this output, so a field added to the struct but not
// added here silently weakens that assertion rather than failing anything.
// CoversEveryStringBearingField exists to make that visible.
std::string TunnelStateSnapshotToDebugJson(const TunnelStateSnapshot& state);

}  // namespace tunnel_internal

// Diagnostics seam. The tunnel page's handler is compiled into
// //chrome/browser/ui/webui and must NOT include teleport_tunnel_service.h:
// that header belongs to //chrome/browser:core, and :core already depends on
// //chrome/browser/ui/webui:configs, which depends on every page target, so the
// dep the include would need closes a GN cycle. `gn gen` reports that cycle
// outright -- it is NOT something gn check would have caught for us, and this
// tree does not pass `gn check` today anyway (28 pre-existing overlay
// violations across 19 files; see TD-OVERLAY-GN-CHECK-VIOLATIONS). The seam is
// therefore load-bearing on its own, with no static analysis behind it.
// //chrome/browser registers the providers at startup; the handler only calls
// the free functions. This is the same shape the enroll page uses for its
// Local State writes and its relaunch (see teleport_enroll_logic.h).
//
// The BrowserContext* parameter is load-bearing and cannot be dropped: the seam
// is process-global while TeleportTunnelService is per-profile, so without it
// the page would answer for whichever profile registered last.
using TunnelStateProvider =
    base::RepeatingCallback<tunnel_internal::TunnelStateSnapshot(
        content::BrowserContext*)>;
void SetTunnelStateProvider(TunnelStateProvider provider);
// Returns an empty snapshot when no provider is registered.
tunnel_internal::TunnelStateSnapshot GetTunnelStateSnapshot(
    content::BrowserContext* context);

// Manual "rebind now" from the diagnostics page. Returns whether the request
// was accepted; see TeleportTunnelService::Rebind for the refusal reasons.
using TunnelRebindRequester =
    base::RepeatingCallback<bool(content::BrowserContext*)>;
void SetTunnelRebindRequester(TunnelRebindRequester requester);
// Returns false when no requester is registered.
bool RequestTunnelRebind(content::BrowserContext* context);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_LOGIC_H_
