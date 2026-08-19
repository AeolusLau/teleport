// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_SERVICE_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_SERVICE_H_

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "base/containers/circular_deque.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "base/values.h"
#include "components/keyed_service/core/keyed_service.h"
#include "components/prefs/pref_change_registrar.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "net/base/backoff_entry.h"
#include "net/base/host_port_pair.h"
#include "net/base/proxy_chain.h"
#include "net/http/http_response_headers.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "services/network/public/mojom/proxy_config.mojom.h"
#include "teleport/browser/enterprise/teleport_tunnel_logic.h"

class Profile;

namespace network {
class SharedURLLoaderFactory;
class SimpleURLLoader;
}  // namespace network

namespace teleport {

// The pure routing/config free functions (tunnel_internal::ParseRoutableOrigins
// / BuildTunnelProxyConfig) that this service composes live in the standalone
// teleport_tunnel_logic.{h,cc} so they are unit-testable outside chrome/browser
// (TD-TUNNEL-UNITTEST-WIRING); this header pulls them in above.

// Per-Profile browser-process service that establishes the Teleport access
// tunnel for a managed profile: it runs the single-hop bind (device-cert mTLS
// presented directly to the gate — see BeginBind in the .cc) to obtain a cnf
// tunnel token AND the routing table that comes back with it, and pushes a single
// `network::mojom::CustomProxyConfig` (selective routing + CONNECT-header
// injection) to this profile's NetworkContext. Bind failures are retried with a
// randomized exponential backoff. The cnf token lives in memory only — never
// persisted to disk, never logged. Because the cnf is short-lived (~10min
// server-side), every successful mint also arms a refresh loop (see
// ScheduleRefresh/OnRefresh below) that re-mints and re-pushes at TTL×0.8,
// well before the old token lapses; a refresh failure falls back to the very
// same bind_backoff_ exponential retry as the initial bind.
//
// The tunnel is a property of an ENROLLED PROFILE, not of an active console
// session: there is no session cookie or ticket in the bind path, so nothing
// here needs to survive/reconstruct a console origin across a restart. A
// restart re-establishes the tunnel once the managed AutoSelect policy has
// loaded and the profile is enrolled (has a DM token) — see PreconditionsMet.
class TeleportTunnelService
    : public KeyedService,
      public network::mojom::CustomProxyConnectionObserver {
 public:
  explicit TeleportTunnelService(Profile* profile);
  TeleportTunnelService(const TeleportTunnelService&) = delete;
  TeleportTunnelService& operator=(const TeleportTunnelService&) = delete;
  ~TeleportTunnelService() override;

  // Orchestration entry point: called once the managed profile is signed in and
  // its managed policy has been fetched. Runs the single-hop bind; on success it
  // adopts the routing table the response carries and pushes the
  // CustomProxyConfig. Idempotent (a second call while already started is a
  // no-op).
  //
  // The device certificate is NOT yet available at this point, despite what a
  // previous version of this comment claimed: provisioning only STARTS once the
  // provisioning policy pref lands, and then needs its own DMServer round trip
  // (docs/verification/2026-08-16-bind-preconditions.md section 0.1). Certificate
  // readiness is not observable in this build at all, so the bind itself is the
  // only probe and the backoff is what covers the gap.
  void Start();

  // Called by ProfileNetworkContextService (Task T4) while assembling this
  // profile's NetworkContextParams. Resets the client Remote and stamps a fresh
  // receiver onto `params`, and does the same for the CONNECT-result observer
  // remote. This is the ONLY channel to hot-push a CustomProxyConfig to a
  // profile's NetworkContext (the mojom has no runtime setter). A
  // network-service restart re-runs this with fresh pipes, so if a config was
  // already pushed it is RE-PUSHED here — otherwise the tunnel routing + token
  // would be silently lost across the restart.
  void BindProxyConfigClient(network::mojom::NetworkContextParams* params);

  // Everything the teleport://tunnel diagnostics page is allowed to see, as one
  // pull. Reached from the page's handler through the //teleport callback seam
  // (SetTunnelStateProvider), never by including this header from the WebUI
  // target — see teleport_tunnel_logic.h for why that include is impossible.
  //
  // The cnf token is not in it and must never be added; see TunnelStateSnapshot.
  tunnel_internal::TunnelStateSnapshot GetStateSnapshot() const;

  // Shortest gap between two accepted manual rebinds. Public so the test can
  // advance exactly this far rather than guessing.
  static constexpr base::TimeDelta kRebindMinInterval = base::Seconds(10);

  // The diagnostics page's "rebind now" button, reached through the
  // SetTunnelRebindRequester seam. Returns whether the request was ACCEPTED —
  // false when the read-gate is shut (nothing to authenticate with, or the
  // profile is not enrolled), while a bind is already outstanding, or within
  // kRebindMinInterval of the previous accepted one.
  //
  // Rate-limited, and precondition wake-ups deliberately are NOT: a wake-up can
  // only ever collapse into one pending bit because it never aborts an
  // outstanding bind, whereas this is an unbounded human-driven trigger on the
  // same gate. Pinned by WakeUpsAreNotRateLimitedButRebindIs.
  //
  // Does NOT reset bind_backoff_, matching wake-ups: pressing the button is a
  // request for one immediate attempt, not a claim that the gate recovered.
  bool Rebind();

  // KeyedService:
  void Shutdown() override;

  // network::mojom::CustomProxyConnectionObserver:
  //
  // Both of these are called for EVERY proxy chain on this profile's network
  // context, not just ours: NetworkServiceProxyDelegate gates its two
  // header-writing methods on IsInProxyConfig but neither of its two
  // observer-notifying ones
  // (docs/verification/2026-08-16-connect-attribution-patch.md section 5).
  // Filtering is therefore the observer's job, as upstream's own
  // PrefetchProxyConfigurator also does.
  void OnFallback(const net::ProxyChain& bad_chain, int net_error) override;
  void OnTunnelHeadersReceived(
      const net::ProxyChain& proxy_chain,
      uint64_t chain_index,
      const net::HostPortPair& endpoint,
      const scoped_refptr<net::HttpResponseHeaders>& response_headers) override;

  // Test seams.
  void SetUrlLoaderFactoryForTesting(
      scoped_refptr<network::SharedURLLoaderFactory> factory);
  void SetEdgePortForTesting(uint16_t port);
  // The origins currently routed through the tunnel, as adopted from the most
  // recent bind response.
  std::vector<tunnel_internal::RoutableOrigin> GetRoutableOriginsForTesting()
      const;
  // Entries the response carried that did not survive parsing/validation.
  std::vector<tunnel_internal::SkippedEntry> GetSkippedEntriesForTesting() const;
  // True while no well-formed table has EVER been adopted, as distinct from
  // having adopted an explicitly empty `[]`.
  bool RoutesUnavailableForTesting() const;
  // True when the most recent successful bind carried no usable
  // `routable_origins` array, so the table in force is one an earlier response
  // vouched for and nothing since has re-confirmed.
  bool RoutesHardStaleForTesting() const;
  const std::string& RoutesHardStaleReasonForTesting() const;
  bool RoutesStaleForTesting() const;
  bool RoutesTruncatedForTesting() const;
  int RoutesDroppedForTesting() const;
  const std::string& RoutesDigestForTesting() const;
  base::Time TokenExpiresAtForTesting() const;
  const std::string& LastBindErrorForTesting() const;
  // Whether a backoff retry is armed. Entering in-flight must clear it, or it
  // fires later and silently cancels the request that just went out.
  bool RetryTimerIsRunningForTesting() const;
  // Newest first, bounded to kMaxRecentConnects.
  std::vector<tunnel_internal::ConnectResult> GetRecentConnectsForTesting()
      const;
  // Diagnostics only. NEVER the re-push predicate — see BindProxyConfigClient.
  bool HavePushedConfigForTesting() const;

 private:
  // Edge proxy port. Prod = 443; dev value is decided by Piece 0-spike and set
  // via SetEdgePortForTesting / a future dev override — never hardcoded to 8444.
  static constexpr uint16_t kDefaultEdgeProxyPort = 443;

  // How many CONNECT results the diagnostics page can look back over. Bounded
  // because this list grows for the whole life of the browser process and is
  // pure diagnostics — a long session must not turn it into a leak.
  static constexpr size_t kMaxRecentConnects = 32;

  // Whether a bind request is outstanding, and whether something asked for
  // another one while it was. Three states, not a bool, because "a wake-up
  // arrived mid-flight" has to be remembered rather than acted on: acting on it
  // would mean destroying the outstanding SimpleURLLoader, which cancels the
  // request AND skips its callback (see BeginBind).
  enum class BindState {
    kIdle,
    kInFlight,
    kInFlightPending,
  };

  // The single entry point for "a bind should happen now" — startup, backoff
  // retry, pre-expiry refresh and precondition wake-ups all go through it.
  // While a bind is outstanding it records a pending request instead of
  // issuing one.
  void RequestBind();

  // Leaves the in-flight state at the end of a bind and issues the pending
  // follow-up, if any. Returns after the follow-up bind has been issued, so
  // callers must not touch bind state afterwards.
  void SettleBind();

  // BindClient: single-hop SimpleURLLoader request. Never call directly —
  // RequestBind() owns the in-flight guard.
  void BeginBind();
  // The SimpleURLLoader completion callback. It reads `loader_`'s NetError() and
  // ResponseInfo() BEFORE releasing it: a bind can fail with no body at all
  // (a cancelled client-certificate request, a gate 5xx), and the body alone
  // cannot tell those apart — which is what last_bind_error_ has to report.
  void OnTunnelToken(std::optional<std::string> response_body);
  void OnBindFailed(std::string reason);

  // Adopts the routing table (and its diagnostics-only metadata) out of a
  // successful bind response.
  //
  // Fails STALE, not closed, and the distinction is the whole point: an
  // explicitly empty `[]` is the server saying "this tenant has no apps" and
  // clears the table, while a missing or `null` field is the server failing to
  // speak the protocol and leaves the previous table exactly as it was, marked
  // hard-stale. Section 2's invariant is what makes that safe — the client
  // table is a routing HINT and the edge holds the authorization truth, so a
  // stale table can only produce a diagnosable 403/407 there. Clearing would
  // trade that for an undiagnosable "cannot connect" across every app at once,
  // on the say-so of a server that just demonstrated it is broken.
  void ApplyRoutingTable(const base::DictValue& body);

  // Records that a successful bind carried no usable table, preserving whatever
  // the last well-formed response left in force.
  void MarkRoutesHardStale(std::string reason);

  // RefreshLoop: the cnf is short-lived (~10min server-side) — a successful
  // mint (OnTunnelToken) arms `refresh_timer_` via ScheduleRefresh(delay) so
  // it fires at TTL×0.8, well before the token lapses. OnRefresh re-runs
  // BeginBind() to re-mint a fresh cnf and re-push the config; success
  // re-arms this same loop (OnTunnelToken calls ScheduleRefresh again), and a
  // refresh failure falls through to OnBindFailed's existing bind_backoff_
  // exponential retry — deliberately NOT a second, independent backoff.
  void ScheduleRefresh(base::TimeDelta delay);
  void OnRefresh();

  // The READ-GATE: are this profile's bind preconditions satisfied right now?
  // Reads both prefs rather than trusting notifications, because
  // PrefChangeRegistrar does not replay an already-present value at
  // registration time and this service is lazy-created from
  // ProfileNetworkContextService::ConfigureNetworkContextParamsInternal — it is
  // routinely born AFTER both prefs landed, in which case no notification will
  // ever arrive. A notification-only design is therefore strictly weaker.
  //
  // Deliberately NOT gated on device-certificate readiness: that is not
  // observable in this build at all (see
  // docs/verification/2026-08-16-bind-preconditions.md). Wake-ups cover the
  // POLICY precondition only; the certificate half is the backoff's job, with
  // the bind itself as the only real probe.
  bool PreconditionsMet() const;

  // Both precondition observers land here: re-run the read-gate and, if it is
  // open, start (first time) or request a wake-up bind (afterwards).
  void OnPreconditionSignal();

  // The constructor's deferred initial read-gate. Deliberately NOT
  // OnPreconditionSignal: that treats an open gate on an already-started
  // service as a wake-up, and the initial evaluation is not a CHANGE. The
  // first-enrollment registrar calls Start() directly, which for a
  // freshly-constructed service happens before this task runs — reading it as a
  // wake-up would issue a redundant second bind on every enrollment.
  void RunInitialReadGate();

  // ProxyConfigPusher: build + push the CustomProxyConfig over the mojo Remote.
  void PushConfig();

  scoped_refptr<network::SharedURLLoaderFactory> GetUrlLoaderFactory();

  const raw_ptr<Profile> profile_;

  // Selective-routing inputs: adopted wholesale from each successful bind
  // response and reused on every push.
  std::vector<tunnel_internal::RoutableOrigin> routable_origins_;

  // Entries of the last response that were rejected, kept so the diagnostics
  // page can show them. Silently dropping entries is the C-2 defect this whole
  // change replaces, so a rejection that nobody can see is not acceptable.
  std::vector<tunnel_internal::SkippedEntry> skipped_entries_;

  // True until some response actually carries a `routable_origins` ARRAY.
  // Distinct from "the array was empty": an empty table is the server saying
  // "this profile routes nothing", whereas never having received one means the
  // tunnel has no table to work from at all. There is no fallback for the
  // latter — the policy-derived derivation that used to stand in for one is
  // gone — so it routes nothing, and it says so rather than pretending the
  // server declared an empty tenant.
  bool routes_unavailable_ = true;

  // The last successful bind carried no usable `routable_origins` array, so
  // routable_origins_ (and the metadata below) still describe an EARLIER
  // response. Kept separate from the server's own `routes_stale` flag: that one
  // is the server telling us its own view is behind, this one is us telling the
  // operator that the server stopped telling us anything. The reason string is
  // meant to be shown prominently — the preserved table is only safe for as
  // long as somebody can see that it is being preserved.
  bool routes_hard_stale_ = false;
  std::string routes_hard_stale_reason_;

  // Server-supplied routing-table metadata. DIAGNOSTICS ONLY — by the cross-repo
  // contract none of these participate in a routing decision. All are
  // `omitempty` on the wire and therefore default to their zero value. They are
  // adopted and preserved TOGETHER with routable_origins_, so the digest always
  // describes the table actually in force.
  bool routes_stale_ = false;
  bool routes_truncated_ = false;
  int routes_dropped_ = 0;
  std::string routes_digest_;

  // When the currently held cnf lapses, per the response's `expires_in`. Null
  // when the server did not say. Drives both the refresh loop and the
  // diagnostics page, so the two can never disagree.
  base::Time token_expires_at_;

  // Diagnostics timeline. Wall-clock rather than TimeTicks because these are
  // rendered as instants on a page; null means "never happened".
  base::Time last_bind_attempt_at_;
  base::Time last_bind_success_at_;
  // When the armed timer is due. Recorded alongside each Start() of the
  // corresponding timer, and only reported while that timer is still running —
  // a stale "next attempt" is worse than none.
  base::Time next_refresh_at_;
  base::Time next_retry_at_;

  // When the last ACCEPTED manual rebind went out. TimeTicks, not Time: a rate
  // limit must not be defeatable by a wall-clock jump.
  base::TimeTicks last_manual_rebind_at_;

  // Why the most recent bind failed, in operator-readable form; empty after a
  // success. Sourced from the loader's own outcome rather than the body, since
  // the interesting failures have no body at all.
  std::string last_bind_error_;

  // cnf tunnel token — IN-MEMORY ONLY (never persisted, never logged).
  std::string cnf_token_;

  // The most recent CONNECT results on OUR proxy chain, newest at the front.
  // Diagnostics only.
  base::circular_deque<tunnel_internal::ConnectResult> recent_connects_;

  // Set once a config has actually gone out over the wire. DIAGNOSTICS ONLY —
  // it backs the page's "config pushed" row and nothing else. It is NOT the
  // re-push predicate; see BindProxyConfigClient for why using it as one was a
  // bug.
  bool have_pushed_config_ = false;
  bool started_ = false;

  BindState bind_state_ = BindState::kIdle;

  // Observes BOTH prefs the read-gate reads (the managed AutoSelect policy and
  // this profile's DM-token backup) so a bind can be woken as each lands —
  // observing only the first left a real gap when the token landed second.
  PrefChangeRegistrar pref_change_registrar_;

  uint16_t edge_port_ = kDefaultEdgeProxyPort;

  mojo::Remote<network::mojom::CustomProxyConfigClient> proxy_config_client_;

  // Receives CONNECT results from this profile's network context. Rebound
  // alongside proxy_config_client_ on every BindProxyConfigClient, since a
  // network-service restart invalidates both pipes together.
  mojo::Receiver<network::mojom::CustomProxyConnectionObserver>
      connection_observer_receiver_{this};

  // One in-flight bind request at a time — enforced by bind_state_, not merely
  // hoped for. Reassigning this while a request is outstanding cancels it and
  // skips its callback, which would strand the state machine silently.
  std::unique_ptr<network::SimpleURLLoader> loader_;

  net::BackoffEntry bind_backoff_;
  base::OneShotTimer retry_timer_;

  // Re-mint-before-expiry loop (see ScheduleRefresh/OnRefresh). Same
  // cancels-on-destruction safety as retry_timer_ (a bare OneShotTimer
  // member); Shutdown() also stops it explicitly, matching retry_timer_, for
  // consistency rather than necessity.
  base::OneShotTimer refresh_timer_;

  scoped_refptr<network::SharedURLLoaderFactory> url_loader_factory_for_testing_;

  base::WeakPtrFactory<TeleportTunnelService> weak_factory_{this};
};

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_SERVICE_H_
