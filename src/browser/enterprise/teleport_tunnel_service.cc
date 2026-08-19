// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_service.h"

#include "base/logging.h"  // VLOG(1) tunnel-routing observability

#include <algorithm>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/containers/flat_set.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/sequenced_task_runner.h"
#include "base/values.h"
#include "chrome/browser/enterprise/signin/enterprise_signin_prefs.h"
#include "chrome/browser/profiles/profile.h"
#include "components/content_settings/core/common/pref_names.h"
#include "components/prefs/pref_service.h"
#include "content/public/browser/storage_partition.h"
#include "net/base/net_errors.h"
#include "net/base/proxy_server.h"
#include "net/http/http_response_headers.h"
#include "net/http/http_request_headers.h"
#include "net/proxy_resolution/proxy_config.h"
#include "net/proxy_resolution/proxy_host_matching_rules.h"
#include "net/proxy_resolution/proxy_list.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "services/network/public/mojom/url_response_head.mojom.h"
#include "teleport/browser/enterprise/teleport_tunnel_logic.h"
#include "teleport/common/teleport_deployment_config.h"
#include "url/gurl.h"

namespace teleport {

namespace {

// Single-hop collapse (bind 流坍缩): the device certificate presented at the
// mTLS handshake with the gate IS the whole identity — no ticket, no cookie,
// no Authorization header.
constexpr char kBindPath[] = "/tunnel/bind";

// Randomized exponential backoff for a failed bind chain (§5.7.4): first retry
// ~1s, growing x2 with +/-25% jitter, capped at ~5min. always_use_initial_delay
// so even the first failure waits (avoids a tight loop if the token endpoint is
// briefly unreachable).
constexpr net::BackoffEntry::Policy kBindBackoffPolicy = {
    /*num_errors_to_ignore=*/0,
    /*initial_delay_ms=*/1000,
    /*multiply_factor=*/2.0,
    /*jitter_factor=*/0.25,
    /*maximum_backoff_ms=*/5 * 60 * 1000,
    /*entry_lifetime_ms=*/-1,
    /*always_use_initial_delay=*/true,
};

// Refresh-before-expiry FALLBACK delay, used only when the bind response omits
// `expires_in`. The cnf TTL is ~10min server-side, so 8min (TTL×0.8) leaves a
// comfortable margin. The cnf stays an opaque bearer token to this client (no
// local claim parsing of `exp` — the token shape is the server's to own); the
// lifetime comes from the response's own `expires_in` field instead.
constexpr base::TimeDelta kCnfRefreshDelay = base::Minutes(8);

// Fraction of the advertised lifetime at which the cnf is re-minted, and the
// floor under the resulting delay. The floor keeps an absurdly short advertised
// TTL from turning the refresh loop into a hot loop against the gate; a server
// advertising less than ~40s is misconfigured and the backoff will churn either
// way, so trading "token briefly lapses" for "we hammer the gate" is right.
constexpr double kCnfRefreshFraction = 0.8;
constexpr base::TimeDelta kMinCnfRefreshDelay = base::Seconds(30);

// "gate.<D>" (keeps a ":port" at the tail, mirroring EdgeHostFor / TeleportHostFor).
std::string GateHost() {
  return "gate." + DeploymentDomain();
}

// Turns the loader's own outcome into something an operator can act on. The
// two failures that matter most here — the client-certificate request being
// cancelled (no WebContents to prompt on, so the request is dropped outright)
// and a gate 5xx — BOTH arrive as "no body", so the body cannot distinguish
// them and the caller must consult NetError()/ResponseInfo() instead.
std::string DescribeBindFailure(int net_error,
                                int response_code,
                                bool had_body) {
  if (net_error != net::OK &&
      net_error != net::ERR_HTTP_RESPONSE_CODE_FAILURE) {
    return base::StrCat({"network error ", net::ErrorToShortString(net_error)});
  }
  if (response_code != 0 && response_code / 100 != 2) {
    return base::StrCat(
        {"gate returned HTTP ", base::NumberToString(response_code)});
  }
  return had_body ? "response is not a JSON object carrying tunnel_token"
                  : "empty response body";
}

// Re-mint delay for a cnf the server says lives `expires_in` seconds.
base::TimeDelta RefreshDelayFor(std::optional<int> expires_in) {
  if (!expires_in || *expires_in <= 0) {
    return kCnfRefreshDelay;
  }
  return std::max(base::Seconds(*expires_in) * kCnfRefreshFraction,
                  kMinCnfRefreshDelay);
}

std::string ValueToRaw(const base::Value& value) {
  std::string json;
  base::JSONWriter::Write(value, &json);
  return json;
}

}  // namespace

TeleportTunnelService::TeleportTunnelService(Profile* profile)
    : profile_(profile), bind_backoff_(&kBindBackoffPolicy) {
  // A managed profile that enrolled in a PRIOR browser session must re-establish
  // the access tunnel on this launch. The enrollment orchestration
  // (teleport_oidc_inplace_registrar) fires Start() exactly once, at first
  // enrollment, so without this a restart leaves an enrolled profile tunnel-less
  // (bug #4). The single-hop bind has no session/ticket precondition to
  // reconstruct — it needs the managed AutoSelect policy (cache-loaded early in
  // startup, but asynchronously) and this profile being enrolled.
  //
  // Observe BOTH prefs the read-gate reads. Observing only the AutoSelect pref
  // left a genuine hole: if the policy landed first and the DM token second,
  // the AutoSelect notification bounced off the still-empty token check and the
  // token's own arrival produced no notification at all — so the tunnel never
  // started for the rest of the session. Both observers share one entry point.
  //
  // The observers are bound via a weak ptr (not base::Unretained) so a pref
  // change racing between Shutdown() and destruction cannot re-enter a
  // torn-down service; Shutdown() also RemoveAll()s the registrar.
  pref_change_registrar_.Init(profile_->GetPrefs());
  pref_change_registrar_.Add(
      prefs::kManagedAutoSelectCertificateForUrls,
      base::BindRepeating(&TeleportTunnelService::OnPreconditionSignal,
                          weak_factory_.GetWeakPtr()));
  pref_change_registrar_.Add(
      enterprise_signin::prefs::kPolicyRecoveryToken,
      base::BindRepeating(&TeleportTunnelService::OnPreconditionSignal,
                          weak_factory_.GetWeakPtr()));
  // DEFER the initial read-gate off the ctor call stack: this service is
  // lazy-created from inside
  // ProfileNetworkContextService::ConfigureNetworkContextParamsInternal, and
  // for an already-enrolled profile at restart (both prefs already set)
  // OnPreconditionSignal would run Start()->BeginBind()->
  // GetDefaultStoragePartition() REENTRANTLY from within NetworkContext
  // configuration. Posting to the current sequence guarantees Start() can
  // never fire synchronously off this constructor. The pref-observer path
  // (later policy changes) is already async and stays as-is.
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE, base::BindOnce(&TeleportTunnelService::RunInitialReadGate,
                                weak_factory_.GetWeakPtr()));
}

TeleportTunnelService::~TeleportTunnelService() = default;

bool TeleportTunnelService::PreconditionsMet() const {
  PrefService* prefs = profile_->GetPrefs();
  // The managed AutoSelect policy no longer supplies the routing table, but it
  // is still a hard precondition of the BIND itself: it is what makes the
  // network stack offer the device certificate at the gate's mTLS handshake.
  // Without it the bind cannot authenticate, whatever else is ready.
  if (prefs->GetList(prefs::kManagedAutoSelectCertificateForUrls).empty()) {
    return false;
  }
  // The tunnel is a property of an ENROLLED profile (see the class doc
  // comment), not of an active console session — gate on "this profile has
  // enrolled" rather than a persisted console origin. kPolicyRecoveryToken is
  // the profile pref the OIDC in-place registrar backs up the DM token to at
  // ApplyManagedAttributes() (teleport_oidc_inplace_registrar.cc) — a plain
  // PrefRegistrySimple string pref, loaded synchronously with the rest of the
  // profile's prefs (unlike the managed policy pref above, it needs no separate
  // async wait).
  if (prefs->GetString(enterprise_signin::prefs::kPolicyRecoveryToken)
          .empty()) {
    return false;
  }
  // There is deliberately NO device-certificate clause here. Certificate
  // readiness is not observable in this build: GetManagedIdentity is
  // request/response and answers std::nullopt synchronously (then never fires
  // again) in exactly the window that matters, CertDatabase's
  // OnClientCertStoreChanged is never raised by the enterprise provisioning
  // path, the identity prefs have no writer in this build, and the provisioning
  // service exposes no observer at all — full evidence in
  // docs/verification/2026-08-16-bind-preconditions.md. Any proxy signal would
  // be a fake gate, so the bind is the only probe and the backoff carries that
  // half of the problem.
  return true;
}

void TeleportTunnelService::RunInitialReadGate() {
  // Already started — by the enrollment registrar's direct Start(), which for a
  // freshly-constructed service always beats this posted task. The initial
  // evaluation is not a precondition CHANGE, so there is nothing to wake up
  // for; falling through to OnPreconditionSignal would issue a second bind on
  // top of the one Start() just began.
  if (started_) {
    return;
  }
  OnPreconditionSignal();
}

void TeleportTunnelService::OnPreconditionSignal() {
  if (!PreconditionsMet()) {
    return;
  }
  if (!started_) {
    Start();
    return;
  }
  // Already started: this is a WAKE-UP. Ask for a bind rather than waiting out
  // whatever backoff is armed — the backoff spaces out attempts against an
  // unchanged world, and a precondition landing is evidence the world changed.
  //
  // Wake-ups are NOT rate-limited, and they do not need to be: RequestBind()
  // never aborts an outstanding bind, so however many arrive during one flight
  // they collapse into a single pending bit. The starvation a minimum interval
  // would have prevented was a consequence of aborting, which no longer
  // happens. A MANUAL rebind (the diagnostics page) is the case that does need
  // rate limiting, and that limit belongs on that entry point, not here.
  RequestBind();
}

void TeleportTunnelService::Start() {
  if (started_) {
    return;
  }
  started_ = true;
  VLOG(1) << "TeleportTunnel: Start; edge=" << DomainHostOnlyFor(EdgeHost())
          << ":" << edge_port_ << " gate=" << GateHost();
  RequestBind();
}

void TeleportTunnelService::BindProxyConfigClient(
    network::mojom::NetworkContextParams* params) {
  proxy_config_client_.reset();
  params->custom_proxy_config_client_receiver =
      proxy_config_client_.BindNewPipeAndPassReceiver();
  // Stamped from the same place as the config client, and rebound the same way:
  // a network-service restart invalidates both pipes together, and an observer
  // remote that is not re-stamped means CONNECT results simply stop arriving --
  // compile-clean, silent, and indistinguishable on the diagnostics page from
  // "nothing has been attempted".
  connection_observer_receiver_.reset();
  params->custom_proxy_connection_observer_remote =
      connection_observer_receiver_.BindNewPipeAndPassRemote();
  // REGRESSION ANCHOR (pinned by NetworkServiceRestartRepushesOnTokenPresence):
  // the predicate is `!cnf_token_.empty()`, and it must stay that way. It must
  // NOT be have_pushed_config_: if the FIRST PushConfig (from OnTunnelToken)
  // ran before any receiver was bound, it silently no-op'd and left
  // have_pushed_config_ false -- the old guard then never re-pushed to THIS (or
  // any later) network context, so the tunnel routing was never applied at all.
  // have_pushed_config_ survives only as the diagnostics page's "config pushed"
  // row; do not promote it back into this condition while tidying up. Any bound
  // receiver with a cnf in hand must receive the config. Mojo queues until
  // connected, so pushing now is safe even for a fresh receiver.
  VLOG(1) << "TeleportTunnel: BindProxyConfigClient; cnf_empty="
               << cnf_token_.empty() << " have_pushed=" << have_pushed_config_;
  if (!cnf_token_.empty()) {
    PushConfig();
  }
}

void TeleportTunnelService::OnFallback(const net::ProxyChain& bad_chain,
                                       int net_error) {
  // Same filtering duty as OnTunnelHeadersReceived below: this notification is
  // not gated on IsInProxyConfig either, so most of what arrives here belongs
  // to somebody else's proxy.
  if (!tunnel_internal::IsEdgeProxyChain(
          bad_chain, DomainHostOnlyFor(EdgeHost()), edge_port_)) {
    return;
  }
  // Not surfaced on the diagnostics page yet: the edge being marked bad shows
  // up there as the CONNECT failures that preceded it, which is the more
  // actionable form. Logged so the sequence is recoverable from a VLOG capture.
  VLOG(1) << "TeleportTunnel: edge proxy marked bad, net_error=" << net_error;
}

void TeleportTunnelService::OnTunnelHeadersReceived(
    const net::ProxyChain& proxy_chain,
    uint64_t chain_index,
    const net::HostPortPair& endpoint,
    const scoped_refptr<net::HttpResponseHeaders>& response_headers) {
  if (!tunnel_internal::IsEdgeProxyChain(
          proxy_chain, DomainHostOnlyFor(EdgeHost()), edge_port_)) {
    return;
  }
  tunnel_internal::ConnectResult result;
  result.time = base::Time::Now();
  // `endpoint` is what the upstream patch exists to deliver: the proxy chain
  // alone says a CONNECT failed, not which origin it failed for.
  result.authority = endpoint.ToString();
  result.response_code = response_headers ? response_headers->response_code()
                                          : 0;
  VLOG(1) << "TeleportTunnel: CONNECT " << result.authority << " -> "
          << result.response_code;
  recent_connects_.push_front(std::move(result));
  while (recent_connects_.size() > kMaxRecentConnects) {
    recent_connects_.pop_back();
  }
}

tunnel_internal::TunnelStateSnapshot TeleportTunnelService::GetStateSnapshot()
    const {
  tunnel_internal::TunnelStateSnapshot state;
  const PrefService* prefs = profile_->GetPrefs();
  // The read-gate's two inputs, reported separately from PreconditionsMet() so
  // a refused rebind can say WHICH one is missing.
  state.auto_select_policy_present =
      !prefs->GetList(prefs::kManagedAutoSelectCertificateForUrls).empty();
  state.enrolled =
      !prefs->GetString(enterprise_signin::prefs::kPolicyRecoveryToken).empty();

  state.started = started_;
  state.bind_in_flight = bind_state_ != BindState::kIdle;
  // Whether a credential is held, never which one: cnf_token_ itself must not
  // reach the snapshot, and StateSnapshotNeverCarriesTheToken pins that.
  state.has_token = !cnf_token_.empty();
  state.config_pushed = have_pushed_config_;

  state.last_bind_attempt_at = last_bind_attempt_at_;
  state.last_bind_success_at = last_bind_success_at_;
  state.token_expires_at = token_expires_at_;
  // Only report a due time while its timer is actually armed. Reporting the
  // last recorded value unconditionally would leave a "next attempt" in the
  // past sitting on the page after the attempt already happened.
  if (refresh_timer_.IsRunning()) {
    state.next_refresh_at = next_refresh_at_;
  }
  if (retry_timer_.IsRunning()) {
    state.next_retry_at = next_retry_at_;
  }
  state.last_bind_error = last_bind_error_;

  state.routable_origins = routable_origins_;
  state.skipped_entries = skipped_entries_;
  state.routes_unavailable = routes_unavailable_;
  state.routes_hard_stale = routes_hard_stale_;
  state.routes_hard_stale_reason = routes_hard_stale_reason_;
  state.routes_stale = routes_stale_;
  state.routes_truncated = routes_truncated_;
  state.routes_dropped = routes_dropped_;
  state.routes_digest = routes_digest_;

  state.edge_host = DomainHostOnlyFor(EdgeHost());
  state.edge_port = edge_port_;
  state.gate_host = DomainHostOnlyFor(GateHost());

  state.recent_connects.assign(recent_connects_.begin(),
                               recent_connects_.end());
  return state;
}

bool TeleportTunnelService::Rebind() {
  // Refuse rather than burn a backoff step on a bind that cannot possibly
  // authenticate. The snapshot reports both preconditions separately so the
  // page can say which one is missing instead of just "not now".
  if (!PreconditionsMet()) {
    return false;
  }
  // Refused, not queued: the button asks for a FRESH result and one is already
  // on its way, and queueing would report "accepted" for work the click did not
  // cause. RequestBind()'s pending bit exists for wake-ups, which have no
  // caller waiting on an answer.
  if (bind_state_ != BindState::kIdle) {
    return false;
  }
  const base::TimeTicks now = base::TimeTicks::Now();
  if (!last_manual_rebind_at_.is_null() &&
      now - last_manual_rebind_at_ < kRebindMinInterval) {
    return false;
  }
  last_manual_rebind_at_ = now;
  // An explicit operator action with the read-gate open is a legitimate way to
  // start a tunnel that never got going, so this is also the (rare) start path.
  started_ = true;
  RequestBind();
  return true;
}

void TeleportTunnelService::Shutdown() {
  // Stop observing the managed AutoSelect pref: a change landing between
  // Shutdown() and destruction must not re-enter this shut-down service (the
  // observer is weak-bound too — belt-and-suspenders).
  pref_change_registrar_.RemoveAll();
  retry_timer_.Stop();
  refresh_timer_.Stop();
  // Dropping the loader cancels any in-flight bind without running its
  // callback, so nothing will move the state machine out of kInFlight — do it
  // here so a shut-down service is left in a coherent state.
  loader_.reset();
  bind_state_ = BindState::kIdle;
  proxy_config_client_.reset();
  connection_observer_receiver_.reset();
  cnf_token_.clear();
  weak_factory_.InvalidateWeakPtrs();
}

void TeleportTunnelService::SetUrlLoaderFactoryForTesting(
    scoped_refptr<network::SharedURLLoaderFactory> factory) {
  url_loader_factory_for_testing_ = std::move(factory);
}

void TeleportTunnelService::SetEdgePortForTesting(uint16_t port) {
  edge_port_ = port;
}

std::vector<tunnel_internal::RoutableOrigin>
TeleportTunnelService::GetRoutableOriginsForTesting()
    const {
  return routable_origins_;
}

std::vector<tunnel_internal::SkippedEntry>
TeleportTunnelService::GetSkippedEntriesForTesting() const {
  return skipped_entries_;
}

bool TeleportTunnelService::RoutesUnavailableForTesting() const {
  return routes_unavailable_;
}

bool TeleportTunnelService::RoutesHardStaleForTesting() const {
  return routes_hard_stale_;
}

const std::string& TeleportTunnelService::RoutesHardStaleReasonForTesting()
    const {
  return routes_hard_stale_reason_;
}

bool TeleportTunnelService::RoutesStaleForTesting() const {
  return routes_stale_;
}

bool TeleportTunnelService::RoutesTruncatedForTesting() const {
  return routes_truncated_;
}

int TeleportTunnelService::RoutesDroppedForTesting() const {
  return routes_dropped_;
}

const std::string& TeleportTunnelService::RoutesDigestForTesting() const {
  return routes_digest_;
}

base::Time TeleportTunnelService::TokenExpiresAtForTesting() const {
  return token_expires_at_;
}

const std::string& TeleportTunnelService::LastBindErrorForTesting() const {
  return last_bind_error_;
}

bool TeleportTunnelService::RetryTimerIsRunningForTesting() const {
  return retry_timer_.IsRunning();
}

std::vector<tunnel_internal::ConnectResult>
TeleportTunnelService::GetRecentConnectsForTesting() const {
  return {recent_connects_.begin(), recent_connects_.end()};
}

bool TeleportTunnelService::HavePushedConfigForTesting() const {
  return have_pushed_config_;
}

void TeleportTunnelService::RequestBind() {
  if (bind_state_ != BindState::kIdle) {
    // A bind is already outstanding. Do NOT start another one: that would mean
    // reassigning loader_, and per SimpleURLLoader's header, "Deleting the
    // SimpleURLLoader before the callback is invoked will result in cancelling
    // the request, and the callback will not be called." Neither OnTunnelToken
    // nor OnBindFailed would run, so the backoff would never be informed and
    // the refresh loop would never re-arm — the tunnel would go quiet with no
    // log, no metric and no timer to recover it. Remember the request instead;
    // SettleBind() issues it the moment the current one finishes.
    bind_state_ = BindState::kInFlightPending;
    return;
  }
  BeginBind();
}

void TeleportTunnelService::SettleBind() {
  const bool had_pending = bind_state_ == BindState::kInFlightPending;
  bind_state_ = BindState::kIdle;
  if (had_pending) {
    // Something asked for a bind while this one was in flight. Issue it now,
    // ahead of whatever timer the just-finished attempt armed — this is the
    // backoff short-circuit, and BeginBind() stops that timer on its way in.
    RequestBind();
  }
}

void TeleportTunnelService::BeginBind() {
  CHECK(bind_state_ == BindState::kIdle);
  bind_state_ = BindState::kInFlight;
  last_bind_attempt_at_ = base::Time::Now();
  // Disarm both timers on the way in. An armed retry_timer_ that fires while
  // this request is outstanding would call RequestBind() -> pending, harmless
  // in itself, but leaving it armed also means a wake-up-issued bind inherits a
  // countdown started for a previous, already-superseded attempt. Same for the
  // refresh timer: exactly one of the three drivers may own the next bind.
  retry_timer_.Stop();
  refresh_timer_.Stop();

  // Single-hop collapse (bind 流坍缩): no tenant console origin, no session
  // cookie, no ticket precondition to check here — the device certificate
  // presented at the mTLS handshake with the gate (below) IS the whole
  // identity. Bind host derivation: the gate (GateHost(), "gate.<D>") is the
  // dedicated mTLS bind host — the device-manager compiler
  // emits this exact host's AutoSelect entry for the bind endpoint
  // (see products/teleport/device-manager: NewWebAppRepo's teleportHost
  // param is fed "gate."+OPDomainSuffix), and it is the only Ingress host
  // that routes /tunnel/bind with mandatory client-cert mTLS (see
  // infra/helm/fairyland/charts/teleport-gateway/templates/gate-mtls.yaml).
  net::NetworkTrafficAnnotationTag annotation =
      net::DefineNetworkTrafficAnnotation("teleport_tunnel_bind", R"(
      semantics {
        sender: "Teleport Tunnel Service"
        description: "Mints a cnf-bound tunnel access token directly off the "
          "managed profile's device certificate, presented via mTLS to the "
          "gate. Single hop: no session cookie, no bind ticket."
        trigger: "A managed Teleport profile has enrolled (device "
          "certificate + managed AutoSelect policy present)."
        data: "None in the body; the device certificate is presented at the "
          "TLS handshake by the network stack via the managed AutoSelect "
          "policy."
        destination: OTHER
      }
      policy {
        cookies_allowed: NO
        setting: "Managed Teleport browsers only."
      })");

  auto request = std::make_unique<network::ResourceRequest>();
  request->url = GURL(base::StrCat({"https://", GateHost(), kBindPath}));
  request->method = net::HttpRequestHeaders::kPostMethod;
  // No cookie, no Authorization header: the device cert mTLS handshake
  // (supplied by the network stack via the managed AutoSelect policy) is the
  // sole identity source.
  request->credentials_mode = network::mojom::CredentialsMode::kOmit;
  request->redirect_mode = network::mojom::RedirectMode::kError;

  loader_ = network::SimpleURLLoader::Create(std::move(request), annotation);
  loader_->SetTimeoutDuration(base::Seconds(30));
  loader_->AttachStringForUpload("{}", "application/json");
  loader_->DownloadToString(
      GetUrlLoaderFactory().get(),
      base::BindOnce(&TeleportTunnelService::OnTunnelToken,
                     weak_factory_.GetWeakPtr()),
      tunnel_internal::kMaxBindBodyBytes);
}

void TeleportTunnelService::OnTunnelToken(
    std::optional<std::string> response_body) {
  // Read the transport-level outcome BEFORE releasing the loader — this is the
  // only point at which it is still available, and it is the only thing that
  // can tell a cancelled client-certificate request apart from a gate 5xx.
  const int net_error = loader_ ? loader_->NetError() : net::ERR_UNEXPECTED;
  int response_code = 0;
  if (loader_ && loader_->ResponseInfo() && loader_->ResponseInfo()->headers) {
    response_code = loader_->ResponseInfo()->headers->response_code();
  }

  std::optional<base::DictValue> body;
  if (response_body) {
    body = base::JSONReader::ReadDict(*response_body, base::JSON_PARSE_RFC);
  }
  const std::string* token = body ? body->FindString("tunnel_token") : nullptr;
  if (!token || token->empty()) {
    OnBindFailed(DescribeBindFailure(net_error, response_code,
                                     response_body.has_value()));
    return;
  }
  loader_.reset();
  cnf_token_ = *token;
  last_bind_error_.clear();
  last_bind_success_at_ = base::Time::Now();
  bind_backoff_.InformOfRequest(/*succeeded=*/true);

  // `expires_in` is the server's statement of this cnf's lifetime; it drives
  // both the refresh loop and what the diagnostics page shows, so the two
  // cannot disagree about when the token lapses.
  const std::optional<int> expires_in = body->FindInt("expires_in");
  token_expires_at_ = (expires_in && *expires_in > 0)
                          ? base::Time::Now() + base::Seconds(*expires_in)
                          : base::Time();

  ApplyRoutingTable(*body);
  PushConfig();
  // Re-mint before this cnf expires (RefreshLoop). Re-arms on every
  // successful mint — initial bind AND every subsequent refresh — so the
  // loop is self-sustaining as long as binds keep succeeding.
  ScheduleRefresh(RefreshDelayFor(expires_in));
  SettleBind();
}

void TeleportTunnelService::ApplyRoutingTable(const base::DictValue& body) {
  // Read `routable_origins` BEFORE touching anything: on a protocol violation
  // the whole previous snapshot — table, skipped entries and metadata alike —
  // has to survive intact, and the metadata only describes a table that was
  // actually sent. Adopting the flags of a response that carried no table and
  // pairing them with a preserved table would misreport what is in force
  // (a digest for a table nobody sent).
  const base::Value* routes = body.Find("routable_origins");
  if (!routes || routes->is_none()) {
    // Absent, or explicitly `null`. Go marshals a nil slice as `null`, and the
    // contract says an empty result is sent as `[]`, so BOTH spellings mean the
    // server built no table — a protocol violation, not a second spelling of
    // "empty". Preserve; see the header for why fail-stale beats fail-closed.
    MarkRoutesHardStale(
        routes ? "the response carried routable_origins as null; the contract "
                 "sends an empty table as [], so null means the server built no "
                 "table at all (protocol violation)"
               : "the response carried no routable_origins field at all "
                 "(protocol violation)");
    return;
  }
  const base::ListValue* entries = routes->GetIfList();
  if (!entries) {
    MarkRoutesHardStale(base::StrCat(
        {"the response carried routable_origins as something other than an "
         "array (protocol violation): ",
         ValueToRaw(*routes)}));
    return;
  }

  // A well-formed table: adopt it wholesale, and with it the metadata that
  // describes it. Everything below is `omitempty` on the wire — absent means
  // the zero value, never "unknown" — and all four are DIAGNOSTICS ONLY: the
  // table is applied exactly as sent regardless of what they say.
  routes_hard_stale_ = false;
  routes_hard_stale_reason_.clear();
  routable_origins_.clear();
  skipped_entries_.clear();
  routes_stale_ = body.FindBool("routes_stale").value_or(false);
  routes_truncated_ = body.FindBool("routes_truncated").value_or(false);
  routes_dropped_ = body.FindInt("routes_dropped").value_or(0);
  const std::string* digest = body.FindString("routes_digest");
  routes_digest_ = digest ? *digest : std::string();
  routes_unavailable_ = false;
  routable_origins_ = tunnel_internal::ParseRoutableOrigins(
      *entries, DomainHostOnlyFor(EdgeHost()), DomainHostOnlyFor(GateHost()),
      &skipped_entries_);
  VLOG(1) << "TeleportTunnel: routing table applied; routable="
          << routable_origins_.size() << " skipped=" << skipped_entries_.size()
          << " digest=" << routes_digest_;
  for (const auto& o : routable_origins_) {
    VLOG(1) << "TeleportTunnel: routable origin=" << o.host << ":" << o.port
            << " include_subdomains=" << o.include_subdomains
            << " blocked=" << o.blocked;
  }
}

void TeleportTunnelService::MarkRoutesHardStale(std::string reason) {
  routes_hard_stale_ = true;
  routes_hard_stale_reason_ = std::move(reason);
  // Deliberately NOT clearing routable_origins_, skipped_entries_ or any of the
  // metadata: they still describe the last table the server actually vouched
  // for, which stays in force until a well-formed response replaces it.
  VLOG(1) << "TeleportTunnel: routing table is hard-stale ("
          << routes_hard_stale_reason_
          << "); keeping the previous table of " << routable_origins_.size()
          << " origin(s)";
}

void TeleportTunnelService::OnBindFailed(std::string reason) {
  last_bind_error_ = std::move(reason);
  VLOG(1) << "TeleportTunnel: bind failed: " << last_bind_error_;
  loader_.reset();
  bind_backoff_.InformOfRequest(/*succeeded=*/false);
  const base::TimeDelta retry_delay = bind_backoff_.GetTimeUntilRelease();
  next_retry_at_ = base::Time::Now() + retry_delay;
  retry_timer_.Start(FROM_HERE, retry_delay,
                     base::BindOnce(&TeleportTunnelService::RequestBind,
                                    weak_factory_.GetWeakPtr()));
  SettleBind();
}

void TeleportTunnelService::ScheduleRefresh(base::TimeDelta delay) {
  next_refresh_at_ = base::Time::Now() + delay;
  refresh_timer_.Start(FROM_HERE, delay,
                       base::BindOnce(&TeleportTunnelService::OnRefresh,
                                      weak_factory_.GetWeakPtr()));
}

void TeleportTunnelService::OnRefresh() {
  // Re-run the exact same single-hop bind used at initial Start(): re-mints a
  // fresh cnf and (via OnTunnelToken's success path) re-pushes the config and
  // re-arms this loop. A failure here falls through to OnBindFailed, which
  // reuses bind_backoff_'s existing exponential retry — there is
  // deliberately no second, independent backoff for refresh failures.
  RequestBind();
}

void TeleportTunnelService::PushConfig() {
  VLOG(1) << "TeleportTunnel: PushConfig; bound="
               << proxy_config_client_.is_bound()
               << " cnf_empty=" << cnf_token_.empty()
               << " routable=" << routable_origins_.size();
  if (!proxy_config_client_.is_bound() || cnf_token_.empty()) {
    return;
  }
  VLOG(1) << "TeleportTunnel: PushConfig APPLIED to network context";
  proxy_config_client_->OnCustomProxyConfigUpdated(
      tunnel_internal::BuildTunnelProxyConfig(
          DomainHostOnlyFor(EdgeHost()), edge_port_, routable_origins_,
          cnf_token_),
      base::DoNothing());
  have_pushed_config_ = true;
}

scoped_refptr<network::SharedURLLoaderFactory>
TeleportTunnelService::GetUrlLoaderFactory() {
  if (url_loader_factory_for_testing_) {
    return url_loader_factory_for_testing_;
  }
  return profile_->GetDefaultStoragePartition()
      ->GetURLLoaderFactoryForBrowserProcess();
}

}  // namespace teleport
