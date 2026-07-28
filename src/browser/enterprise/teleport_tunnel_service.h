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

#include "base/memory/raw_ptr.h"
#include "base/memory/scoped_refptr.h"
#include "base/memory/weak_ptr.h"
#include "base/timer/timer.h"
#include "base/values.h"
#include "components/keyed_service/core/keyed_service.h"
#include "components/prefs/pref_change_registrar.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "net/base/backoff_entry.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "services/network/public/mojom/proxy_config.mojom.h"
#include "teleport/browser/enterprise/teleport_tunnel_logic.h"

class Profile;

namespace network {
class SharedURLLoaderFactory;
class SimpleURLLoader;
}  // namespace network

namespace teleport {

// The pure routing/config free functions (tunnel_internal::DeriveRoutableOrigins
// / BuildTunnelProxyConfig) that this service composes now live in the standalone
// teleport_tunnel_logic.{h,cc} so they are unit-testable outside chrome/browser
// (TD-TUNNEL-UNITTEST-WIRING); this header pulls them in above.

// Per-Profile browser-process service that establishes the Teleport access
// tunnel for a managed profile: it derives the routable origins, runs the
// single-hop bind (device-cert mTLS presented directly to the gate — see
// BeginBind in the .cc) to obtain a cnf tunnel token, and pushes a single
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
// loaded and the profile is enrolled (has a DM token) — see
// MaybeAutoStartFromPrefs.
class TeleportTunnelService : public KeyedService {
 public:
  explicit TeleportTunnelService(Profile* profile);
  TeleportTunnelService(const TeleportTunnelService&) = delete;
  TeleportTunnelService& operator=(const TeleportTunnelService&) = delete;
  ~TeleportTunnelService() override;

  // Orchestration entry point: called once the managed profile is signed in and
  // the device certificate is present. Derives the routable origins, then runs
  // the single-hop bind; on success it pushes the CustomProxyConfig. Idempotent
  // (a second call while already started is a no-op).
  void Start();

  // Called by ProfileNetworkContextService (Task T4) while assembling this
  // profile's NetworkContextParams. Resets the client Remote and stamps a fresh
  // receiver onto `params`. This is the ONLY channel to hot-push a
  // CustomProxyConfig to a profile's NetworkContext (the mojom has no runtime
  // setter). A network-service restart re-runs this with a fresh receiver, so if
  // a config was already pushed it is RE-PUSHED here — otherwise the tunnel
  // routing + token would be silently lost across the restart.
  void BindProxyConfigClient(network::mojom::NetworkContextParams* params);

  // KeyedService:
  void Shutdown() override;

  // Test seams.
  void SetUrlLoaderFactoryForTesting(
      scoped_refptr<network::SharedURLLoaderFactory> factory);
  void SetEdgePortForTesting(uint16_t port);
  // The origins currently routed through the tunnel (kept in sync with the
  // managed AutoSelect pref). For asserting the first-enrollment re-sync.
  std::vector<std::string> GetRoutableOriginsForTesting() const;

 private:
  // Edge proxy port. Prod = 443; dev value is decided by Piece 0-spike and set
  // via SetEdgePortForTesting / a future dev override — never hardcoded to 8444.
  static constexpr uint16_t kDefaultEdgeProxyPort = 443;

  // BindClient: single-hop SimpleURLLoader request.
  void BeginBind();
  void OnTunnelToken(std::optional<std::string> response_body);
  void OnBindFailed();

  // RefreshLoop: the cnf is short-lived (~10min server-side) — a successful
  // mint (OnTunnelToken) arms `refresh_timer_` via ScheduleRefresh(delay) so
  // it fires at TTL×0.8, well before the token lapses. OnRefresh re-runs
  // BeginBind() to re-mint a fresh cnf and re-push the config; success
  // re-arms this same loop (OnTunnelToken calls ScheduleRefresh again), and a
  // refresh failure falls through to OnBindFailed's existing bind_backoff_
  // exponential retry — deliberately NOT a second, independent backoff.
  void ScheduleRefresh(base::TimeDelta delay);
  void OnRefresh();

  // Startup auto-start (bug fix): re-establish the tunnel across a browser
  // restart. Start() is otherwise triggered exactly once, at first enrollment
  // (teleport_oidc_inplace_registrar's OnEnrollmentComplete), so a restart
  // would otherwise leave an enrolled profile with no tunnel. Fires once the
  // managed AutoSelect policy has loaded (it lands asynchronously during
  // startup — see prefs::kManagedAutoSelectCertificateForUrls) AND the
  // profile is enrolled (has a persisted DM token — see the .cc for exactly
  // which pref backs this check). Bound to `pref_change_registrar_` so it
  // re-fires as the policy lands; a no-op once `started_` is set.
  void MaybeAutoStartFromPrefs();

  // The managed-AutoSelect pref observer. Before Start(): defers to
  // MaybeAutoStartFromPrefs (gate on policy present + enrolled). After Start():
  // re-derives routable_origins_ and re-pushes if it changed. That second role
  // is load-bearing on FIRST enrollment: the enrollment registrar
  // (teleport_oidc_inplace_registrar::MaybeStartTunnelService) calls Start()
  // unconditionally on policy-FETCH success, which can run BEFORE the fetched
  // policy propagates to this pref — so Start() may capture routable_origins_
  // EMPTY and, uncorrected, the tunnel routes nothing until a browser restart
  // (TD-TUNNEL-FIRSTACCESS-PROXYCONFIG-NOT-APPLIED). It also picks up a later
  // legitimate policy change (a web-app added/removed).
  void OnManagedAutoSelectPrefChanged();

  // ProxyConfigPusher: build + push the CustomProxyConfig over the mojo Remote.
  void PushConfig();

  // RoutesDeriver bound to this profile's managed AutoSelect pref.
  std::vector<std::string> DeriveRoutableOrigins() const;

  scoped_refptr<network::SharedURLLoaderFactory> GetUrlLoaderFactory();

  const raw_ptr<Profile> profile_;

  // Selective-routing inputs: derived at Start() and kept in sync with the
  // managed AutoSelect pref thereafter (see OnManagedAutoSelectPrefChanged);
  // reused on every push.
  std::vector<std::string> routable_origins_;

  // cnf tunnel token — IN-MEMORY ONLY (never persisted, never logged).
  std::string cnf_token_;

  // Set once a config has been pushed, so BindProxyConfigClient knows to re-push
  // after a network-service restart re-stamps a fresh receiver.
  bool have_pushed_config_ = false;
  bool started_ = false;

  // Observes the managed AutoSelect pref during startup so MaybeAutoStartFromPrefs
  // can re-establish the tunnel once policy lands (see the constructor).
  PrefChangeRegistrar pref_change_registrar_;

  uint16_t edge_port_ = kDefaultEdgeProxyPort;

  mojo::Remote<network::mojom::CustomProxyConfigClient> proxy_config_client_;

  // One in-flight bind request at a time.
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
