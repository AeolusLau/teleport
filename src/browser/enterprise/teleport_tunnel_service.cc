// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_service.h"

#include "base/logging.h"  // VLOG(1) tunnel-routing observability

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/containers/flat_set.h"
#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/json/json_reader.h"
#include "base/strings/strcat.h"
#include "base/task/sequenced_task_runner.h"
#include "base/values.h"
#include "chrome/browser/enterprise/signin/enterprise_signin_prefs.h"
#include "chrome/browser/profiles/profile.h"
#include "components/content_settings/core/common/pref_names.h"
#include "components/prefs/pref_service.h"
#include "content/public/browser/storage_partition.h"
#include "net/base/proxy_server.h"
#include "net/http/http_request_headers.h"
#include "net/proxy_resolution/proxy_config.h"
#include "net/proxy_resolution/proxy_host_matching_rules.h"
#include "net/proxy_resolution/proxy_list.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "teleport/browser/enterprise/teleport_tunnel_logic.h"
#include "teleport/common/teleport_deployment_config.h"
#include "url/gurl.h"

namespace teleport {

namespace {

// A cnf token response is a tiny JSON object.
constexpr size_t kMaxBindBodyBytes = 64 * 1024;

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

// Refresh-before-expiry delay: the cnf TTL is ~10min server-side (the source
// of truth for the actual lifetime), so refresh at TTL×0.8 = 8min leaves a
// comfortable margin. The cnf is an opaque bearer token to this client (no
// local claim parsing of `exp` — the token shape is the server's to own), so
// this is a fixed constant rather than a value computed from the token
// itself; deliberately shorter than a computed remaining-lifetime would be.
constexpr base::TimeDelta kCnfRefreshDelay = base::Minutes(8);

// "gate.<D>" (keeps a ":port" at the tail, mirroring EdgeHostFor / TeleportHostFor).
std::string GateHost() {
  return "gate." + DeploymentDomain();
}

// Read `field` (a string) out of a JSON object response body, or nullopt.
std::optional<std::string> ParseJsonStringField(
    const std::optional<std::string>& body,
    std::string_view field) {
  if (!body) {
    return std::nullopt;
  }
  std::optional<base::DictValue> dict = base::JSONReader::ReadDict(*body, base::JSON_PARSE_RFC);
  if (!dict) {
    return std::nullopt;
  }
  const std::string* value = dict->FindString(field);
  if (!value) {
    return std::nullopt;
  }
  return *value;
}

}  // namespace

TeleportTunnelService::TeleportTunnelService(Profile* profile)
    : profile_(profile), bind_backoff_(&kBindBackoffPolicy) {
  // A managed profile that enrolled in a PRIOR browser session must re-establish
  // the access tunnel on this launch. The enrollment orchestration
  // (teleport_oidc_inplace_registrar) fires Start() exactly once, at first
  // enrollment, so without this a restart leaves an enrolled profile tunnel-less
  // (bug #4). The single-hop bind has no session/ticket precondition to
  // reconstruct — it needs only the managed AutoSelect policy (cache-loaded
  // early in startup, but asynchronously) and this profile being enrolled (see
  // MaybeAutoStartFromPrefs), so observe the policy pref:
  // OnManagedAutoSelectPrefChanged gates the auto-start on both conditions
  // BEFORE Start(), and keeps routable_origins_ in sync (re-derive + re-push)
  // AFTER Start() — the latter is what recovers a first-enrollment Start() that
  // raced ahead of the policy pref, without needing a browser restart.
  //
  // The observer is bound via a weak ptr (not base::Unretained) so a pref
  // change racing between Shutdown() and destruction cannot re-enter a
  // torn-down service; Shutdown() also RemoveAll()s the registrar.
  pref_change_registrar_.Init(profile_->GetPrefs());
  pref_change_registrar_.Add(
      prefs::kManagedAutoSelectCertificateForUrls,
      base::BindRepeating(&TeleportTunnelService::OnManagedAutoSelectPrefChanged,
                          weak_factory_.GetWeakPtr()));
  // DEFER the initial check off the ctor call stack: this service is
  // lazy-created from inside
  // ProfileNetworkContextService::ConfigureNetworkContextParamsInternal, and
  // for an already-enrolled profile at restart (both prefs already set)
  // MaybeAutoStartFromPrefs would run Start()->BeginBind()->
  // GetDefaultStoragePartition() REENTRANTLY from within NetworkContext
  // configuration. Posting to the current sequence guarantees Start() can
  // never fire synchronously off this constructor. The pref-observer path
  // (later policy changes) is already async and stays as-is.
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&TeleportTunnelService::MaybeAutoStartFromPrefs,
                     weak_factory_.GetWeakPtr()));
}

TeleportTunnelService::~TeleportTunnelService() = default;

void TeleportTunnelService::MaybeAutoStartFromPrefs() {
  if (started_) {
    return;
  }
  PrefService* prefs = profile_->GetPrefs();
  // Start() captures the managed AutoSelect list (DeriveRoutableOrigins); defer
  // until the policy is present so that first capture is non-empty. (After
  // Start(), OnManagedAutoSelectPrefChanged keeps routable_origins_ in sync.)
  // The pref observer re-invokes this when the cache-loaded policy lands.
  if (prefs->GetList(prefs::kManagedAutoSelectCertificateForUrls).empty()) {
    return;
  }
  // The tunnel is a property of an ENROLLED profile (see the class doc
  // comment), not of an active console session — gate auto-start on "this
  // profile has enrolled" rather than a persisted console origin.
  // kPolicyRecoveryToken is the profile pref the OIDC in-place registrar
  // backs up the DM token to at ApplyManagedAttributes()
  // (teleport_oidc_inplace_registrar.cc) — a plain PrefRegistrySimple string
  // pref, so it is already loaded synchronously with the rest of the
  // profile's prefs (unlike the managed policy pref above, it needs no
  // separate async wait).
  if (prefs->GetString(enterprise_signin::prefs::kPolicyRecoveryToken)
          .empty()) {
    return;
  }
  // Leave the observer registered: after Start(), OnManagedAutoSelectPrefChanged
  // keeps routable_origins_ in sync with later policy changes (removing an
  // observer from within its own callback is also avoided). Cleared on
  // Shutdown() when the registrar is torn down.
  Start();
}

void TeleportTunnelService::OnManagedAutoSelectPrefChanged() {
  if (!started_) {
    // Before Start(): gate the auto-start on (policy present + enrolled). When
    // both hold, Start() captures routable_origins_ from the now-populated pref.
    MaybeAutoStartFromPrefs();
    return;
  }
  // After Start(): the enrollment registrar
  // (teleport_oidc_inplace_registrar::MaybeStartTunnelService) calls Start()
  // unconditionally on policy-FETCH success, which can run BEFORE the fetched
  // policy propagates to prefs::kManagedAutoSelectCertificateForUrls — so
  // Start() may have captured routable_origins_ EMPTY. Left uncorrected, the
  // pushed CustomProxyConfig routes nothing and the browser sends the app to
  // its ordinary proxy resolution (DIRECT, or e.g. a system HTTP proxy), which
  // fails — the "first access after fresh enrollment breaks until a full
  // restart" defect (TD-TUNNEL-FIRSTACCESS-PROXYCONFIG-NOT-APPLIED). The policy
  // may also legitimately change later (a web-app added/removed). Either way,
  // re-derive and, if it changed, re-push so routing reflects the current
  // policy. PushConfig() no-ops until a receiver is bound AND a cnf is held (and
  // is re-driven from BindProxyConfigClient/OnTunnelToken), so re-pushing here
  // is safe even before the bind completes.
  std::vector<std::string> derived = DeriveRoutableOrigins();
  if (derived == routable_origins_) {
    return;
  }
  routable_origins_ = std::move(derived);
  PushConfig();
}

void TeleportTunnelService::Start() {
  if (started_) {
    return;
  }
  started_ = true;
  routable_origins_ = DeriveRoutableOrigins();
  VLOG(1) << "TeleportTunnel: Start; routable_origins="
               << routable_origins_.size()
               << " edge=" << DomainHostOnlyFor(EdgeHost()) << ":" << edge_port_
               << " gate=" << GateHost();
  for (const auto& o : routable_origins_) {
    VLOG(1) << "TeleportTunnel: routable origin=" << o;
  }
  BeginBind();
}

void TeleportTunnelService::BindProxyConfigClient(
    network::mojom::NetworkContextParams* params) {
  proxy_config_client_.reset();
  params->custom_proxy_config_client_receiver =
      proxy_config_client_.BindNewPipeAndPassReceiver();
  // Re-push whenever we already hold a cnf. This must NOT be gated on
  // have_pushed_config_: if the FIRST PushConfig (from OnTunnelToken) ran before
  // any receiver was bound, it silently no-op'd and left have_pushed_config_
  // false — the old guard then never re-pushed to THIS (or any later) network
  // context, so the tunnel routing was never applied. Any bound receiver with a
  // cnf in hand must receive the config. Mojo queues until connected, so pushing
  // now is safe even for a fresh receiver.
  VLOG(1) << "TeleportTunnel: BindProxyConfigClient; cnf_empty="
               << cnf_token_.empty() << " have_pushed=" << have_pushed_config_;
  if (!cnf_token_.empty()) {
    PushConfig();
  }
}

void TeleportTunnelService::Shutdown() {
  // Stop observing the managed AutoSelect pref: a change landing between
  // Shutdown() and destruction must not re-enter this shut-down service (the
  // observer is weak-bound too — belt-and-suspenders).
  pref_change_registrar_.RemoveAll();
  retry_timer_.Stop();
  refresh_timer_.Stop();
  loader_.reset();
  proxy_config_client_.reset();
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

std::vector<std::string> TeleportTunnelService::GetRoutableOriginsForTesting()
    const {
  return routable_origins_;
}

void TeleportTunnelService::BeginBind() {
  // Single-hop collapse (bind 流坍缩): no tenant console origin, no session
  // cookie, no ticket precondition to check here — the device certificate
  // presented at the mTLS handshake with the gate (below) IS the whole
  // identity. Bind host derivation: the gate (GateHost(), "gate.<D>") is the
  // SAME dedicated mTLS bind host this client already derives edge routing
  // from (see DeriveRoutableOrigins below) — the device-manager compiler
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
      kMaxBindBodyBytes);
}

void TeleportTunnelService::OnTunnelToken(
    std::optional<std::string> response_body) {
  std::optional<std::string> token =
      ParseJsonStringField(response_body, "tunnel_token");
  if (!token) {
    OnBindFailed();
    return;
  }
  loader_.reset();
  cnf_token_ = std::move(*token);
  bind_backoff_.InformOfRequest(/*succeeded=*/true);
  PushConfig();
  // Re-mint before this cnf expires (RefreshLoop). Re-arms on every
  // successful mint — initial bind AND every subsequent refresh — so the
  // loop is self-sustaining as long as binds keep succeeding.
  ScheduleRefresh(kCnfRefreshDelay);
}

void TeleportTunnelService::OnBindFailed() {
  loader_.reset();
  bind_backoff_.InformOfRequest(/*succeeded=*/false);
  retry_timer_.Start(FROM_HERE, bind_backoff_.GetTimeUntilRelease(),
                     base::BindOnce(&TeleportTunnelService::BeginBind,
                                    weak_factory_.GetWeakPtr()));
}

void TeleportTunnelService::ScheduleRefresh(base::TimeDelta delay) {
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
  BeginBind();
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

std::vector<std::string> TeleportTunnelService::DeriveRoutableOrigins() const {
  PrefService* prefs = profile_->GetPrefs();
  if (!prefs) {
    return {};
  }
  // Host-only forms (no port) to match a pattern's GURL host().
  const std::string edge_host = DomainHostOnlyFor(EdgeHost());
  const std::string gate_host = DomainHostOnlyFor(GateHost());
  return tunnel_internal::DeriveRoutableOrigins(
      prefs->GetList(prefs::kManagedAutoSelectCertificateForUrls), edge_host,
      gate_host);
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
