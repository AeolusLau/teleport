// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_service.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "base/check.h"
#include "base/memory/scoped_refptr.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/test/bind.h"
#include "base/values.h"
#include "chrome/browser/enterprise/signin/enterprise_signin_prefs.h"
#include "chrome/test/base/testing_profile.h"
#include "components/content_settings/core/common/pref_names.h"
#include "components/prefs/pref_service.h"
#include "components/sync_preferences/testing_pref_service_syncable.h"
#include "content/public/test/browser_task_environment.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "net/base/host_port_pair.h"
#include "net/base/net_errors.h"
#include "net/base/proxy_chain.h"
#include "net/base/proxy_server.h"
#include "net/http/http_request_headers.h"
#include "net/http/http_response_headers.h"
#include "net/http/http_status_code.h"
#include "net/proxy_resolution/proxy_config.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/url_loader_completion_status.h"
#include "services/network/public/cpp/weak_wrapper_shared_url_loader_factory.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "services/network/public/mojom/url_response_head.mojom.h"
#include "services/network/test/test_url_loader_factory.h"
#include "testing/gmock/include/gmock/gmock.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"

namespace teleport {
namespace {

using ::testing::ElementsAre;
using ::testing::FieldsAre;
using ::testing::HasSubstr;
using ::testing::IsEmpty;

// One managed AutoSelectCertificateForUrls list-pref entry (a JSON string), as
// the device-manager compiler emits it.
std::string AutoSelectEntry(const std::string& pattern) {
  return R"({"pattern":")" + pattern +
         R"(","filter":{"ISSUER":{"CN":"Teleport Device CA"}}})";
}

// The bind response shape the pre-routing-table tests used: a bare token and
// nothing else. Tests that care about the routing table override it.
constexpr char kTokenOnlyBindResponse[] = R"({"tunnel_token":"CNF"})";

// The bind endpoint every test's single-hop request goes to (DeploymentDomain()
// falls back to the baked default in tests).
constexpr char kBindUrl[] = "https://gate.fairyland.io/tunnel/bind";

// AutoSelect patterns the device-manager compiler emits. Their content does not
// affect routing any more (the table comes from the bind response); the pref is
// still a bind PRECONDITION because it is what makes the network stack present
// the device certificate during the gate's mTLS handshake.
constexpr char kGateEntry[] = "https://gate.fairyland.io:443";
constexpr char kEdgeEntry[] = "https://edge.fairyland.io:443";

// Receives the CustomProxyConfig pushes the service makes over the receiver it
// stamps into NetworkContextParams. Stands in for the network service.
class FakeCustomProxyConfigClient
    : public network::mojom::CustomProxyConfigClient {
 public:
  explicit FakeCustomProxyConfigClient(
      mojo::PendingReceiver<network::mojom::CustomProxyConfigClient> receiver)
      : receiver_(this, std::move(receiver)) {}

  int push_count() const { return push_count_; }
  const network::mojom::CustomProxyConfigPtr& last_config() const {
    return last_config_;
  }

  // network::mojom::CustomProxyConfigClient:
  void OnCustomProxyConfigUpdated(
      network::mojom::CustomProxyConfigPtr proxy_config,
      OnCustomProxyConfigUpdatedCallback callback) override {
    ++push_count_;
    last_config_ = std::move(proxy_config);
    std::move(callback).Run();
  }

 private:
  mojo::Receiver<network::mojom::CustomProxyConfigClient> receiver_;
  int push_count_ = 0;
  network::mojom::CustomProxyConfigPtr last_config_;
};

// NOTE: the pure-logic units (RoutesDeriver / ProxyConfigPusher) moved to
// teleport_tunnel_logic_unittest.cc, which links the standalone
// :teleport_tunnel_logic source_set and IS wired into teleport_unittests. The
// BindClient fixture below still needs the full TeleportTunnelService (compiled
// into chrome/browser) + //content test_support, so it remains unwired here
// until that heavier harness lands (TD-TUNNEL-UNITTEST-WIRING).

// --- Unit 2: BindClient (single-hop request shape) --------------------------

class TeleportTunnelBindClientTest : public testing::Test {
 protected:
  // MOCK_TIME: the refresh-loop test (below) needs to fast-forward past
  // ScheduleRefresh's 8min delay without a real 8-minute sleep. Switching the
  // shared fixture to MOCK_TIME does not perturb the other tests in this
  // fixture — BeginBind()'s initial call is synchronous (from Start() or the
  // pref-observer path), not timer-scheduled, so they only ever need
  // RunUntilIdle(), which behaves the same under MOCK_TIME.
  // --- Shared harness -------------------------------------------------------
  // The tests above predate it and drive a locally constructed service with a
  // bespoke interceptor; everything from the bind-response routing table onward
  // uses these helpers instead.

  // The body every subsequent bind is answered with (HTTP 200 unless
  // SetBindStatus/SetBindNetError say otherwise).
  void SetBindResponse(std::string body) { bind_response_ = std::move(body); }
  void SetBindStatus(net::HttpStatusCode status) { bind_status_ = status; }
  // Fail the transport itself rather than the HTTP exchange -- the shape a
  // cancelled client-certificate request takes (no status line at all).
  void SetBindNetError(net::Error error) { bind_net_error_ = error; }

  // Answer only the NEXT bind with a gate 5xx; later binds succeed again.
  void FailNextBind() { fail_next_bind_ = true; }

  // Leave the next bind outstanding (no response at all) so a test can observe
  // what happens while a request really is in flight.
  void StallNextBind() { stall_next_bind_ = true; }

  void CompleteStalledBindWithFailure() {
    ASSERT_TRUE(url_loader_factory_.SimulateResponseForPendingRequest(
        GURL(kBindUrl), network::URLLoaderCompletionStatus(net::ERR_FAILED),
        network::mojom::URLResponseHead::New(), /*content=*/""));
  }

  // The DM-token backup the OIDC in-place registrar persists at
  // ApplyManagedAttributes(): a plain profile string pref, i.e. what "this
  // profile is enrolled" looks like on disk.
  void MarkProfileEnrolled() {
    profile_.GetPrefs()->SetString(
        enterprise_signin::prefs::kPolicyRecoveryToken, "dm-token-123");
  }

  // Managed store, never the user store: upstream's
  // content_settings::PolicyProvider observes this pref and
  // DCHECK(!HasUserSetting())s.
  void SetAutoSelectPolicy(const std::vector<std::string>& patterns) {
    base::ListValue entries;
    for (const std::string& pattern : patterns) {
      entries.Append(AutoSelectEntry(pattern));
    }
    profile_.GetTestingPrefService()->SetManagedPref(
        prefs::kManagedAutoSelectCertificateForUrls, std::move(entries));
  }

  bool RetryTimerIsRunning() const {
    return service_->RetryTimerIsRunningForTesting();
  }

  void CreateService() {
    CHECK(!service_);
    url_loader_factory_.SetInterceptor(base::BindLambdaForTesting(
        [this](const network::ResourceRequest& request) {
          bind_requests_.push_back(request);
          if (stall_next_bind_) {
            stall_next_bind_ = false;
            // Drop any response left over from an earlier bind, or this request
            // would be answered from the factory's per-URL cache immediately.
            url_loader_factory_.EraseResponse(request.url);
            return;
          }
          if (fail_next_bind_) {
            fail_next_bind_ = false;
            url_loader_factory_.AddResponse(request.url.spec(), /*content=*/"",
                                            net::HTTP_SERVICE_UNAVAILABLE);
            return;
          }
          if (bind_net_error_ != net::OK) {
            url_loader_factory_.AddResponse(
                request.url, network::mojom::URLResponseHead::New(),
                /*content=*/"",
                network::URLLoaderCompletionStatus(bind_net_error_));
            return;
          }
          url_loader_factory_.AddResponse(request.url.spec(), bind_response_,
                                          bind_status_);
        }));
    service_ = std::make_unique<TeleportTunnelService>(&profile_);
    service_->SetUrlLoaderFactoryForTesting(
        url_loader_factory_.GetSafeWeakWrapper());
  }

  void StartAndRunUntilIdle() {
    if (!service_) {
      CreateService();
    }
    service_->Start();
    RunUntilIdle();
  }

  void RunUntilIdle() { task_environment_.RunUntilIdle(); }

  // Stands in for ProfileNetworkContextService assembling this profile's
  // NetworkContextParams -- at startup, and again after a network-service
  // restart, which is the same call with a brand new pair of pipes.
  void BindNetworkContext() {
    auto params = network::mojom::NetworkContextParams::New();
    service_->BindProxyConfigClient(params.get());

    ASSERT_TRUE(params->custom_proxy_config_client_receiver);
    config_client_ = std::make_unique<FakeCustomProxyConfigClient>(
        std::move(params->custom_proxy_config_client_receiver));

    // Missing this remote is a compile-clean, silent failure: the CONNECT
    // results would simply never arrive and the diagnostics page would show an
    // empty list forever.
    ASSERT_TRUE(params->custom_proxy_connection_observer_remote);
    connection_observer_.reset();
    connection_observer_.Bind(
        std::move(params->custom_proxy_connection_observer_remote));
  }

  // The chain the pushed config actually routes through.
  net::ProxyChain EdgeProxyChain() const {
    return net::ProxyChain(net::ProxyServer::FromSchemeHostAndPort(
        net::ProxyServer::SCHEME_HTTPS, "edge.fairyland.io", 443));
  }
  net::ProxyChain OtherProxyChain() const {
    return net::ProxyChain(net::ProxyServer::FromSchemeHostAndPort(
        net::ProxyServer::SCHEME_HTTPS, "corp-proxy.example", 3128));
  }

  // Delivers a CONNECT result the way the network service does: over the
  // observer remote stamped into NetworkContextParams.
  void NotifyTunnelHeaders(const net::ProxyChain& chain,
                           const net::HostPortPair& endpoint,
                           int response_code) {
    connection_observer_->OnTunnelHeadersReceived(
        chain, /*chain_index=*/0, endpoint,
        base::MakeRefCounted<net::HttpResponseHeaders>(base::StrCat(
            {"HTTP/1.1 ", base::NumberToString(response_code), "\n\n"})));
  }

  TeleportTunnelService* service() { return service_.get(); }
  int bind_attempts() const { return static_cast<int>(bind_requests_.size()); }

  content::BrowserTaskEnvironment task_environment_{
      content::BrowserTaskEnvironment::TimeSource::MOCK_TIME};
  TestingProfile profile_;
  network::TestURLLoaderFactory url_loader_factory_;

  // Declared after `profile_` so the service is torn down first.
  std::unique_ptr<TeleportTunnelService> service_;
  std::unique_ptr<FakeCustomProxyConfigClient> config_client_;
  mojo::Remote<network::mojom::CustomProxyConnectionObserver>
      connection_observer_;
  std::vector<network::ResourceRequest> bind_requests_;
  std::string bind_response_{kTokenOnlyBindResponse};
  net::HttpStatusCode bind_status_ = net::HTTP_OK;
  net::Error bind_net_error_ = net::OK;
  bool fail_next_bind_ = false;
  bool stall_next_bind_ = false;
};

// Single-hop collapse (T8): Start() -> BeginBind() sends ONE request directly
// to the gate's /tunnel/bind — no bind-ticket hop, no Authorization header.
// The device certificate mTLS handshake (not exercised by TestURLLoaderFactory,
// which is a fake in-process factory) is the sole identity source.
TEST_F(TeleportTunnelBindClientTest, SingleHopBindSendsNoAuthorizationHeader) {
  std::vector<network::ResourceRequest> requests;
  url_loader_factory_.SetInterceptor(base::BindLambdaForTesting(
      [&](const network::ResourceRequest& request) {
        requests.push_back(request);
        url_loader_factory_.AddResponse(request.url.spec(),
                                        R"({"tunnel_token":"CNF"})");
      }));

  TeleportTunnelService service(&profile_);
  service.SetUrlLoaderFactoryForTesting(
      url_loader_factory_.GetSafeWeakWrapper());

  service.Start();
  task_environment_.RunUntilIdle();

  // Exactly one request: the single-hop bind at the gate.
  ASSERT_EQ(requests.size(), 1u);
  EXPECT_EQ(requests[0].url, GURL("https://gate.fairyland.io/tunnel/bind"));
  EXPECT_EQ(requests[0].method, "POST");
  // No cookie: the device cert mTLS handshake supplies identity, not a
  // session cookie.
  EXPECT_EQ(requests[0].credentials_mode,
            network::mojom::CredentialsMode::kOmit);
  // No ticket, so no Authorization (or any other) bearer header is sent.
  EXPECT_FALSE(requests[0].headers.GetHeader(
      net::HttpRequestHeaders::kAuthorization));
}

// --- Unit 5: RefreshLoop (re-mint before the cnf's short TTL expires) ------

// The refresh delay (kCnfRefreshDelay in the .cc, TTL×0.8 = 8min for the
// ~10min server-side cnf TTL) is not exported, so this test hardcodes the
// same 8min value; if the constant ever changes, this test's FastForwardBy
// argument must be updated alongside it.
//
// This fixture does not wire `BindProxyConfigClient`/a fake
// `network::mojom::CustomProxyConfigClient` receiver (see
// TD-TUNNEL-UNITTEST-WIRING in docs/tech-debt.md — this test file is not yet
// linked into a buildable target, and no fake for that mojo interface exists
// in this fork), so PushConfig()'s actual mojo send is not directly
// observable here. Instead this test proves "re-mint + re-push" through the
// HTTP-observable bind requests: in TeleportTunnelService::OnTunnelToken,
// `PushConfig()` and `ScheduleRefresh(kCnfRefreshDelay)` are two unconditional,
// sequential statements on the same success path (no branch between them) —
// so a THIRD bind request firing (after two FastForwardBy(8min) steps) is
// proof by construction that PushConfig() ran again with the second bind's
// fresh cnf, immediately before the loop re-armed itself for a third time.
TEST_F(TeleportTunnelBindClientTest,
       RefreshLoopReMintsAndRePushesBeforeTtlExpires) {
  std::vector<network::ResourceRequest> requests;
  url_loader_factory_.SetInterceptor(base::BindLambdaForTesting(
      [&](const network::ResourceRequest& request) {
        requests.push_back(request);
        url_loader_factory_.AddResponse(request.url.spec(),
                                        R"({"tunnel_token":"CNF"})");
      }));

  TeleportTunnelService service(&profile_);
  service.SetUrlLoaderFactoryForTesting(
      url_loader_factory_.GetSafeWeakWrapper());

  service.Start();
  task_environment_.RunUntilIdle();
  ASSERT_EQ(requests.size(), 1u);
  EXPECT_EQ(requests[0].url, GURL("https://gate.fairyland.io/tunnel/bind"));

  // Nothing fires before the refresh delay elapses.
  task_environment_.FastForwardBy(base::Minutes(7));
  EXPECT_EQ(requests.size(), 1u);

  // Crossing the 8min mark fires refresh_timer_ -> OnRefresh() -> BeginBind():
  // a second single-hop bind, identical in shape to the first (no ticket, no
  // Authorization header — it is the SAME BeginBind(), not a distinct path).
  task_environment_.FastForwardBy(base::Minutes(1));
  task_environment_.RunUntilIdle();
  ASSERT_EQ(requests.size(), 2u);
  EXPECT_EQ(requests[1].url, GURL("https://gate.fairyland.io/tunnel/bind"));
  EXPECT_EQ(requests[1].method, "POST");
  EXPECT_EQ(requests[1].credentials_mode,
            network::mojom::CredentialsMode::kOmit);
  EXPECT_FALSE(requests[1].headers.GetHeader(
      net::HttpRequestHeaders::kAuthorization));

  // A second refresh cycle: only fires if OnTunnelToken's success path
  // re-armed ScheduleRefresh after processing the SECOND bind's cnf — i.e.
  // the loop is self-sustaining, and PushConfig() ran again with the fresh
  // token from that second bind (see the fixture-level comment above).
  task_environment_.FastForwardBy(base::Minutes(8));
  task_environment_.RunUntilIdle();
  ASSERT_EQ(requests.size(), 3u);
}

// A bind FAILURE at refresh time must NOT start a second, independent backoff
// loop — it falls through to OnBindFailed(), which reuses bind_backoff_ (the
// exact same retry path the initial bind's failures use). This is observed
// indirectly: after the refresh's bind fails, the very next request is the
// bind_backoff_ retry (not a second timer firing on its own schedule).
TEST_F(TeleportTunnelBindClientTest, RefreshFailureReusesBindBackoff) {
  std::vector<network::ResourceRequest> requests;
  bool fail_next_response = false;
  url_loader_factory_.SetInterceptor(base::BindLambdaForTesting(
      [&](const network::ResourceRequest& request) {
        requests.push_back(request);
        if (fail_next_response) {
          url_loader_factory_.AddResponse(
              request.url.spec(), /*content=*/"", net::HTTP_INTERNAL_SERVER_ERROR);
        } else {
          url_loader_factory_.AddResponse(request.url.spec(),
                                          R"({"tunnel_token":"CNF"})");
        }
      }));

  TeleportTunnelService service(&profile_);
  service.SetUrlLoaderFactoryForTesting(
      url_loader_factory_.GetSafeWeakWrapper());

  service.Start();
  task_environment_.RunUntilIdle();
  ASSERT_EQ(requests.size(), 1u);

  // Arm the refresh's bind to fail.
  fail_next_response = true;
  task_environment_.FastForwardBy(base::Minutes(8));
  task_environment_.RunUntilIdle();
  ASSERT_EQ(requests.size(), 2u);

  // OnBindFailed() started retry_timer_ at bind_backoff_'s initial delay
  // (~1s, see kBindBackoffPolicy in the .cc) — NOT at another 8min refresh
  // delay. Let the next response succeed and confirm the retry fires well
  // before 8min elapses (a generous upper bound: initial_delay 1s x jitter
  // stays far under 5s).
  fail_next_response = false;
  task_environment_.FastForwardBy(base::Seconds(5));
  task_environment_.RunUntilIdle();
  ASSERT_EQ(requests.size(), 3u);
}

// --- Unit 4: startup auto-start (observe managed AutoSelect pref) ----------

// Reuses the AutoSelectEntry() helper declared at the top of this file.
//
// A profile that enrolled in a PRIOR browser session (kPolicyRecoveryToken —
// the DM-token backup teleport_oidc_inplace_registrar persists at
// ApplyManagedAttributes — is already set) auto-starts the tunnel once the
// managed AutoSelect policy lands, WITHOUT any explicit Start() call. This is
// bug #4's restart-survivable auto-start.
TEST_F(TeleportTunnelBindClientTest,
       AutoStartsWhenPolicyLandsAndProfileIsEnrolled) {
  profile_.GetPrefs()->SetString(
      enterprise_signin::prefs::kPolicyRecoveryToken, "dm-token-123");

  std::vector<network::ResourceRequest> requests;
  url_loader_factory_.SetInterceptor(base::BindLambdaForTesting(
      [&](const network::ResourceRequest& request) {
        requests.push_back(request);
        url_loader_factory_.AddResponse(request.url.spec(),
                                        R"({"tunnel_token":"CNF"})");
      }));

  TeleportTunnelService service(&profile_);
  service.SetUrlLoaderFactoryForTesting(
      url_loader_factory_.GetSafeWeakWrapper());

  // Nothing fires yet: the managed AutoSelect policy has not landed, even
  // though the profile is enrolled.
  task_environment_.RunUntilIdle();
  EXPECT_TRUE(requests.empty());

  // Simulate the managed policy landing asynchronously during startup — the
  // PrefChangeRegistrar observer re-runs the read-gate, which now finds both
  // conditions satisfied and calls Start() itself.
  base::ListValue entries;
  entries.Append(AutoSelectEntry("https://demoapp.example.com:443"));
  // The managed AutoSelect policy lands via the MANAGED pref store (as real
  // policy does): upstream content_settings::PolicyProvider also observes this
  // pref and DCHECK(!HasUserSetting())s, so a user-store SetList crashes it.
  profile_.GetTestingPrefService()->SetManagedPref(
      prefs::kManagedAutoSelectCertificateForUrls, std::move(entries));
  task_environment_.RunUntilIdle();

  ASSERT_EQ(requests.size(), 1u);
  EXPECT_EQ(requests[0].url, GURL("https://gate.fairyland.io/tunnel/bind"));
}

// A profile that has NEVER enrolled (no kPolicyRecoveryToken) must not
// auto-start even once the managed AutoSelect policy lands — the tunnel is a
// property of an enrolled profile, not of policy presence alone.
TEST_F(TeleportTunnelBindClientTest, DoesNotAutoStartWithoutEnrollment) {
  std::vector<network::ResourceRequest> requests;
  url_loader_factory_.SetInterceptor(base::BindLambdaForTesting(
      [&](const network::ResourceRequest& request) {
        requests.push_back(request);
      }));

  TeleportTunnelService service(&profile_);
  service.SetUrlLoaderFactoryForTesting(
      url_loader_factory_.GetSafeWeakWrapper());

  base::ListValue entries;
  entries.Append(AutoSelectEntry("https://demoapp.example.com:443"));
  // The managed AutoSelect policy lands via the MANAGED pref store (as real
  // policy does): upstream content_settings::PolicyProvider also observes this
  // pref and DCHECK(!HasUserSetting())s, so a user-store SetList crashes it.
  profile_.GetTestingPrefService()->SetManagedPref(
      prefs::kManagedAutoSelectCertificateForUrls, std::move(entries));
  task_environment_.RunUntilIdle();

  EXPECT_TRUE(requests.empty());
}

// --- Unit 6: the routing table is fed by the bind response ------------------

TEST_F(TeleportTunnelBindClientTest, UsesRoutingTableFromBindResponse) {
  SetBindResponse(R"({
    "tunnel_token":"CNF",
    "expires_in":600,
    "routable_origins":[
      {"host":"app.corp.example","port":443},
      {"host":"corp.example","port":443,"include_subdomains":true},
      {"host":"adminer.corp.example","port":8080,"blocked":true}
    ],
    "routes_digest":"abc"
  })");
  StartAndRunUntilIdle();

  EXPECT_THAT(
      service()->GetRoutableOriginsForTesting(),
      ElementsAre(FieldsAre("app.corp.example", 443, false, false),
                  FieldsAre("corp.example", 443, true, false),
                  FieldsAre("adminer.corp.example", 8080, false, true)));
  EXPECT_FALSE(service()->RoutesUnavailableForTesting());
  EXPECT_EQ(service()->RoutesDigestForTesting(), "abc");
  EXPECT_THAT(service()->GetSkippedEntriesForTesting(), IsEmpty());
}

TEST_F(TeleportTunnelBindClientTest, MissingRoutingTableYieldsEmptyNoFallback) {
  SetBindResponse(R"({"tunnel_token":"CNF","expires_in":600})");
  StartAndRunUntilIdle();

  EXPECT_THAT(service()->GetRoutableOriginsForTesting(), IsEmpty());
  // No fallback path exists: the pre-existing policy-derived derivation was
  // deleted outright (development phase, zero real users). With no earlier
  // table to preserve, "the server sent no table" still leaves us routing
  // nothing -- but it is flagged as a protocol violation either way.
  EXPECT_TRUE(service()->RoutesUnavailableForTesting());
  EXPECT_TRUE(service()->RoutesHardStaleForTesting());
  EXPECT_FALSE(service()->RoutesHardStaleReasonForTesting().empty());
}

// A bind that succeeds but carries no table is a PROTOCOL VIOLATION, and the
// previously adopted table must survive it. Clearing would trade a diagnosable
// 403/407 at the edge for an undiagnosable "cannot connect" across every app at
// once, and the design's section 2 invariant makes a stale table safe: the
// client table is only a hint, the edge is the authorization truth. This is the
// same fail-stale reasoning the server side applies to a cold start; the two
// halves of one failure surface cannot disagree about which way they fail.
TEST_F(TeleportTunnelBindClientTest,
       MissingTablePreservesAPreviouslyGoodOneAsHardStale) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,
          "routable_origins":[{"host":"app.corp.example","port":443}],
          "routes_digest":"d1"})");
  StartAndRunUntilIdle();
  ASSERT_EQ(service()->GetRoutableOriginsForTesting().size(), 1u);
  ASSERT_FALSE(service()->RoutesHardStaleForTesting());

  SetBindResponse(R"({"tunnel_token":"CNF","expires_in":600})");
  task_environment_.FastForwardBy(base::Minutes(9));  // past the refresh
  RunUntilIdle();

  ASSERT_EQ(bind_attempts(), 2);
  EXPECT_THAT(service()->GetRoutableOriginsForTesting(),
              ElementsAre(FieldsAre("app.corp.example", 443, false, false)));
  EXPECT_FALSE(service()->RoutesUnavailableForTesting());
  EXPECT_TRUE(service()->RoutesHardStaleForTesting());
  EXPECT_FALSE(service()->RoutesHardStaleReasonForTesting().empty());
  // The whole table snapshot is preserved together, metadata included: a digest
  // taken from a response that carried no table would describe nothing, and
  // pairing it with the preserved table would misreport what is in force.
  EXPECT_EQ(service()->RoutesDigestForTesting(), "d1");
}

// The distinction the preservation rule turns on: an explicit `[]` is the server
// SAYING "this tenant has no apps", which is information and must be obeyed.
TEST_F(TeleportTunnelBindClientTest, EmptyArrayClearsAPreviouslyGoodOne) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,
          "routable_origins":[{"host":"app.corp.example","port":443}]})");
  StartAndRunUntilIdle();
  ASSERT_EQ(service()->GetRoutableOriginsForTesting().size(), 1u);

  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,"routable_origins":[]})");
  task_environment_.FastForwardBy(base::Minutes(9));  // past the refresh
  RunUntilIdle();

  ASSERT_EQ(bind_attempts(), 2);
  EXPECT_THAT(service()->GetRoutableOriginsForTesting(), IsEmpty());
  EXPECT_FALSE(service()->RoutesUnavailableForTesting());
  EXPECT_FALSE(service()->RoutesHardStaleForTesting());
}

// Go marshals a nil slice as `null`, so `null` on the wire means "the server
// built no table at all" -- a protocol violation against a contract that says
// an empty result is sent as `[]`. It must not be silently read as "empty",
// and it must not clear the table either.
TEST_F(TeleportTunnelBindClientTest, NullRoutingTableIsAProtocolViolation) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,
          "routable_origins":[{"host":"app.corp.example","port":443}]})");
  StartAndRunUntilIdle();
  ASSERT_EQ(service()->GetRoutableOriginsForTesting().size(), 1u);

  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,"routable_origins":null})");
  task_environment_.FastForwardBy(base::Minutes(9));
  RunUntilIdle();

  ASSERT_EQ(bind_attempts(), 2);
  EXPECT_EQ(service()->GetRoutableOriginsForTesting().size(), 1u);
  EXPECT_FALSE(service()->RoutesUnavailableForTesting());
  // Reported rather than swallowed: the diagnostics page has to be able to tell
  // an operator that the server is speaking the protocol wrong. This is the one
  // condition the page must show prominently -- a preserved table is safe, but
  // only for as long as somebody knows it is being preserved.
  EXPECT_TRUE(service()->RoutesHardStaleForTesting());
  EXPECT_THAT(service()->RoutesHardStaleReasonForTesting(), HasSubstr("null"));
}

// A response that carries `routable_origins` as neither an array nor null (an
// object, a string) is the same class of violation and preserves the same way.
TEST_F(TeleportTunnelBindClientTest, NonArrayRoutingTableIsAProtocolViolation) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,"routable_origins":{"a":1}})");
  StartAndRunUntilIdle();

  EXPECT_TRUE(service()->RoutesHardStaleForTesting());
  EXPECT_FALSE(service()->RoutesHardStaleReasonForTesting().empty());
}

// Hard-stale is a statement about the LAST response, not a latch: a well-formed
// table clears it, or the page would keep warning about a server that recovered.
TEST_F(TeleportTunnelBindClientTest, AWellFormedTableClearsTheHardStaleFlag) {
  SetBindResponse(R"({"tunnel_token":"CNF","expires_in":600})");
  StartAndRunUntilIdle();
  ASSERT_TRUE(service()->RoutesHardStaleForTesting());

  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,
          "routable_origins":[{"host":"app.corp.example","port":443}]})");
  task_environment_.FastForwardBy(base::Minutes(9));
  RunUntilIdle();

  ASSERT_EQ(bind_attempts(), 2);
  EXPECT_FALSE(service()->RoutesHardStaleForTesting());
  EXPECT_TRUE(service()->RoutesHardStaleReasonForTesting().empty());
}

TEST_F(TeleportTunnelBindClientTest, EmptyArrayIsDistinctFromMissing) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,"routable_origins":[],
          "routes_digest":"z"})");
  StartAndRunUntilIdle();

  EXPECT_THAT(service()->GetRoutableOriginsForTesting(), IsEmpty());
  EXPECT_FALSE(service()->RoutesUnavailableForTesting());
  EXPECT_FALSE(service()->RoutesHardStaleForTesting());
  EXPECT_THAT(service()->GetSkippedEntriesForTesting(), IsEmpty());
  EXPECT_EQ(service()->RoutesDigestForTesting(), "z");
}

// Every omitempty field defaults to its zero value when absent -- the server
// omits them precisely because they are zero.
TEST_F(TeleportTunnelBindClientTest, OmittedFlagsDefaultToZero) {
  SetBindResponse(R"({"tunnel_token":"CNF","routable_origins":[]})");
  StartAndRunUntilIdle();

  EXPECT_FALSE(service()->RoutesStaleForTesting());
  EXPECT_FALSE(service()->RoutesTruncatedForTesting());
  EXPECT_EQ(service()->RoutesDroppedForTesting(), 0);
  EXPECT_EQ(service()->RoutesDigestForTesting(), "");
}

TEST_F(TeleportTunnelBindClientTest, SurfacesServerRouteFlags) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,
          "routes_stale":true,"routes_truncated":true,"routes_dropped":7,
          "routable_origins":[{"host":"app.corp.example","port":443}],
          "routes_digest":"deadbeef"})");
  StartAndRunUntilIdle();

  EXPECT_TRUE(service()->RoutesStaleForTesting());
  EXPECT_TRUE(service()->RoutesTruncatedForTesting());
  EXPECT_EQ(service()->RoutesDroppedForTesting(), 7);
  EXPECT_EQ(service()->RoutesDigestForTesting(), "deadbeef");
  // None of the four take part in routing (cross-repo contract): the table is
  // applied exactly as sent.
  EXPECT_EQ(service()->GetRoutableOriginsForTesting().size(), 1u);
}

// One bad row must not cost the tenant its whole table, but it must also not
// disappear: silently dropping entries is the C-2 defect this change replaces.
TEST_F(TeleportTunnelBindClientTest, RejectedEntriesReachTheDiagnostics) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","routable_origins":[
            {"host":"ok.corp.example","port":443},
            {"host":"0.0.0.0/0","port":443}]})");
  StartAndRunUntilIdle();

  ASSERT_EQ(service()->GetRoutableOriginsForTesting().size(), 1u);
  EXPECT_EQ(service()->GetRoutableOriginsForTesting()[0].host,
            "ok.corp.example");
  ASSERT_EQ(service()->GetSkippedEntriesForTesting().size(), 1u);
  EXPECT_THAT(service()->GetSkippedEntriesForTesting()[0].raw,
              HasSubstr("0.0.0.0/0"));
  EXPECT_FALSE(service()->GetSkippedEntriesForTesting()[0].reason.empty());
}

// `expires_in` is the server's statement of the cnf's lifetime, so the refresh
// loop has to follow it. Parsing it for the diagnostics page while re-minting
// on an unrelated fixed delay would let the page show an expiry the client is
// knowingly running past.
TEST_F(TeleportTunnelBindClientTest, RefreshFollowsServerAdvertisedExpiry) {
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":100,"routable_origins":[]})");
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);
  EXPECT_EQ(service()->TokenExpiresAtForTesting(),
            base::Time::Now() + base::Seconds(100));

  // TTL x 0.8 = 80s, not the 8min fallback.
  task_environment_.FastForwardBy(base::Seconds(79));
  EXPECT_EQ(bind_attempts(), 1);
  task_environment_.FastForwardBy(base::Seconds(2));
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 2);
}

// A gate 5xx and a cancelled client-certificate request both arrive as "no
// body". The failure reason has to come from the loader's own outcome, or the
// diagnostics page can only ever say "it didn't work".
TEST_F(TeleportTunnelBindClientTest, RecordsTheGateStatusCodeAsTheBindError) {
  SetBindResponse("");
  SetBindStatus(net::HTTP_SERVICE_UNAVAILABLE);
  StartAndRunUntilIdle();

  EXPECT_THAT(service()->LastBindErrorForTesting(), HasSubstr("503"));
}

// With no WebContents there is nothing to prompt on, so a client-certificate
// request is cancelled outright and no HTTP status is ever produced (see
// docs/verification/2026-08-16-bind-preconditions.md section 6.7).
TEST_F(TeleportTunnelBindClientTest, RecordsTheNetErrorWhenTheRequestIsCancelled) {
  SetBindNetError(net::ERR_SSL_CLIENT_AUTH_CERT_NEEDED);
  StartAndRunUntilIdle();

  EXPECT_THAT(service()->LastBindErrorForTesting(),
              HasSubstr("ERR_SSL_CLIENT_AUTH_CERT_NEEDED"));
}

TEST_F(TeleportTunnelBindClientTest, ASuccessfulBindClearsTheLastError) {
  SetBindStatus(net::HTTP_SERVICE_UNAVAILABLE);
  SetBindResponse("");
  StartAndRunUntilIdle();
  ASSERT_FALSE(service()->LastBindErrorForTesting().empty());

  SetBindStatus(net::HTTP_OK);
  SetBindResponse(kTokenOnlyBindResponse);
  task_environment_.FastForwardBy(base::Seconds(5));  // the backoff retry
  RunUntilIdle();

  ASSERT_EQ(bind_attempts(), 2);
  EXPECT_EQ(service()->LastBindErrorForTesting(), "");
}

// --- Unit 7: startup read-gate + precondition wake-ups ----------------------

TEST_F(TeleportTunnelBindClientTest, DoesNotAutoStartBeforePreconditionsReady) {
  SetAutoSelectPolicy({});  // managed store, empty
  MarkProfileEnrolled();
  CreateService();
  RunUntilIdle();

  EXPECT_EQ(bind_attempts(), 0);
}

// The load-bearing half of the design. PrefChangeRegistrar does NOT replay an
// already-present value at registration, and this service is lazy-created from
// ProfileNetworkContextService::ConfigureNetworkContextParamsInternal -- so for
// an already-enrolled profile at restart it is routinely born AFTER both prefs
// landed and no notification will ever arrive. A notification-only design is
// strictly weaker than reading the values, not equivalent to it.
TEST_F(TeleportTunnelBindClientTest, ReadGateBindsWhenBothPrefsPredateTheService) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  CreateService();
  RunUntilIdle();

  EXPECT_EQ(bind_attempts(), 1);
}

// A pending backoff must not delay a retry once a precondition lands: the
// backoff exists to space out attempts against an unchanged world, and a
// wake-up is evidence the world changed.
TEST_F(TeleportTunnelBindClientTest, WakeUpShortCircuitsBackoff) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  FailNextBind();
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);
  ASSERT_TRUE(RetryTimerIsRunning());

  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});
  RunUntilIdle();  // no clock advance: the retry timer cannot be what fired

  EXPECT_EQ(bind_attempts(), 2);
}

// Reassigning loader_ destroys the in-flight SimpleURLLoader, and per its
// header "the callback will not be called" -- so OnTunnelToken/OnBindFailed
// never run, the backoff is never informed, and the refresh loop is never
// re-armed: the tunnel goes quiet with nothing logged. Today the three call
// sites happen not to overlap; wake-ups make them overlap by design.
TEST_F(TeleportTunnelBindClientTest, WakeUpDoesNotCancelInFlightBind) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  StallNextBind();
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 1);  // still one: the in-flight bind was not aborted

  CompleteStalledBindWithFailure();
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 2);  // the pending wake-up fires immediately after
}

// Repeated wake-ups during one in-flight bind collapse into a single pending
// bit, so they cannot starve the bind by cancelling it over and over. This is
// why wake-ups need no minimum interval: the starvation the interval would have
// prevented is a consequence of cancelling, which no longer happens.
TEST_F(TeleportTunnelBindClientTest, RepeatedWakeUpsCollapseIntoOneRetry) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  StallNextBind();
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});
  SetAutoSelectPolicy({kGateEntry});
  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});
  RunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  CompleteStalledBindWithFailure();
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 2);  // exactly one follow-up, not three
}

// The read-gate reads two prefs but the registrar observed only one. The
// enrollment registrar's explicit Start() covers the common path, so the gap is
// narrow -- but observing both is cheaper than reasoning about when it isn't.
TEST_F(TeleportTunnelBindClientTest, EnrollmentTokenLandingAlsoWakesUp) {
  SetAutoSelectPolicy({kGateEntry});  // policy first
  CreateService();
  RunUntilIdle();
  ASSERT_EQ(bind_attempts(), 0);  // not enrolled yet

  MarkProfileEnrolled();  // DM token pref lands second
  RunUntilIdle();

  EXPECT_EQ(bind_attempts(), 1);
}

// Entering in-flight must stop an armed retry timer, or it fires later and
// cancels the request the wake-up just issued -- silently, per the header
// contract quoted above.
TEST_F(TeleportTunnelBindClientTest, EnteringInFlightStopsTheRetryTimer) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  FailNextBind();
  StartAndRunUntilIdle();
  ASSERT_TRUE(RetryTimerIsRunning());

  StallNextBind();
  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});  // wake-up
  RunUntilIdle();

  EXPECT_FALSE(RetryTimerIsRunning());
}

// --- Unit 9: CONNECT attribution + the network-context wiring ---------------

// NetworkServiceProxyDelegate forwards EVERY proxy chain's CONNECT result to
// the observer -- it has no IsInProxyConfig gate, unlike its two
// header-writing siblings (docs/verification/2026-08-16-connect-attribution
// -patch.md section 5). Without a filter here the diagnostics page would
// present an unrelated proxy's CONNECT as a tunnel result, which is precisely
// the "cannot see the derived state" failure the page exists to end. Upstream's
// own observer (PrefetchProxyConfigurator) filters the same way.
TEST_F(TeleportTunnelBindClientTest, RecentConnectsIgnoreOtherProxyChains) {
  StartAndRunUntilIdle();
  BindNetworkContext();

  // Delivered over the real mojo pipe stamped into NetworkContextParams, so
  // this also pins that the observer remote is actually wired up.
  NotifyTunnelHeaders(OtherProxyChain(), net::HostPortPair("x.corp", 443), 403);
  NotifyTunnelHeaders(EdgeProxyChain(), net::HostPortPair("app.corp", 443),
                      403);
  RunUntilIdle();

  auto recents = service()->GetRecentConnectsForTesting();
  ASSERT_EQ(recents.size(), 1u);
  EXPECT_EQ(recents[0].authority, "app.corp:443");
  EXPECT_EQ(recents[0].response_code, 403);
}

// Newest-first, bounded: a long-lived session must not accumulate an unbounded
// list, and the page shows the most recent attempts.
TEST_F(TeleportTunnelBindClientTest, RecentConnectsAreBoundedAndNewestFirst) {
  StartAndRunUntilIdle();
  BindNetworkContext();

  for (int i = 0; i < 40; ++i) {
    NotifyTunnelHeaders(
        EdgeProxyChain(),
        net::HostPortPair(base::StrCat({"app", base::NumberToString(i),
                                        ".corp"}),
                          443),
        200);
  }
  RunUntilIdle();

  auto recents = service()->GetRecentConnectsForTesting();
  ASSERT_FALSE(recents.empty());
  EXPECT_LE(recents.size(), 32u);
  EXPECT_EQ(recents.front().authority, "app39.corp:443");
}

// Regression anchor for the re-push predicate. It must stay
// `!cnf_token_.empty()`: have_pushed_config_ is NOT usable, because if the
// first PushConfig ran before any receiver was bound it silently no-op'd and
// left the flag false -- the old guard then never re-pushed, and tunnel routing
// was never applied at all. The flag survives only as the backing store for the
// diagnostics page's "config pushed" row, and must never become the predicate
// again.
TEST_F(TeleportTunnelBindClientTest, NetworkServiceRestartRepushesOnTokenPresence) {
  // The bind completes with no NetworkContext configured yet, which is the
  // ordering that left have_pushed_config_ false in the original defect.
  StartAndRunUntilIdle();
  ASSERT_FALSE(service()->HavePushedConfigForTesting());

  BindNetworkContext();
  RunUntilIdle();
  EXPECT_EQ(config_client_->push_count(), 1);

  // A network-service restart re-runs BindProxyConfigClient with a brand new
  // receiver. The config has to be pushed again or the tunnel silently stops
  // routing for the rest of the session.
  BindNetworkContext();
  RunUntilIdle();
  EXPECT_EQ(config_client_->push_count(), 1);  // a fresh client, freshly pushed
}

// --- Unit 11: the diagnostics snapshot + the manual rebind ------------------

// The snapshot is rendered by a WebUI page, i.e. a surface with a DevTools
// console attached. The cnf is an in-memory bearer credential, so it must not
// be in there under any spelling -- `has_token` (whether one is held) is the
// only thing the page needs. The HasSubstr assertion is not decoration: without
// it a serializer that emitted "{}" would pass this test forever.
TEST_F(TeleportTunnelBindClientTest, StateSnapshotNeverCarriesTheToken) {
  SetBindResponse(
      R"({"tunnel_token":"SUPERSECRETCNFVALUE","expires_in":600,
          "routable_origins":[{"host":"app.corp.example","port":443}],
          "routes_digest":"abc"})");
  StartAndRunUntilIdle();

  const tunnel_internal::TunnelStateSnapshot state =
      service()->GetStateSnapshot();
  ASSERT_TRUE(state.has_token);  // there IS a token; it just is not in here

  const std::string json =
      tunnel_internal::TunnelStateSnapshotToDebugJson(state);
  EXPECT_THAT(json, HasSubstr("app.corp.example"));
  EXPECT_EQ(json.find("SUPERSECRETCNFVALUE"), std::string::npos);
}

// Everything the page shows comes from one pull, so the pull has to actually
// carry it. A field the service tracks but the snapshot drops is invisible in
// exactly the way this page exists to fix.
TEST_F(TeleportTunnelBindClientTest, StateSnapshotCarriesTheDerivedState) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  SetBindResponse(
      R"({"tunnel_token":"CNF","expires_in":600,
          "routes_stale":true,"routes_truncated":true,"routes_dropped":3,
          "routable_origins":[
            {"host":"app.corp.example","port":443,"blocked":true},
            {"host":"0.0.0.0/0","port":443}],
          "routes_digest":"deadbeef"})");
  StartAndRunUntilIdle();
  BindNetworkContext();
  NotifyTunnelHeaders(EdgeProxyChain(), net::HostPortPair("app.corp", 443),
                      403);
  RunUntilIdle();

  const tunnel_internal::TunnelStateSnapshot state =
      service()->GetStateSnapshot();
  EXPECT_TRUE(state.enrolled);
  EXPECT_TRUE(state.auto_select_policy_present);
  EXPECT_TRUE(state.started);
  EXPECT_FALSE(state.bind_in_flight);
  EXPECT_TRUE(state.has_token);
  EXPECT_TRUE(state.config_pushed);
  EXPECT_FALSE(state.last_bind_attempt_at.is_null());
  EXPECT_FALSE(state.last_bind_success_at.is_null());
  EXPECT_EQ(state.token_expires_at, base::Time::Now() + base::Seconds(600));
  // TTL x 0.8 after the mint, which is also what the refresh loop is armed for
  // -- the page must never show an expiry the client knowingly runs past.
  EXPECT_EQ(state.next_refresh_at, base::Time::Now() + base::Seconds(480));
  EXPECT_TRUE(state.next_retry_at.is_null());
  EXPECT_EQ(state.last_bind_error, "");
  ASSERT_EQ(state.routable_origins.size(), 1u);
  EXPECT_EQ(state.routable_origins[0].host, "app.corp.example");
  EXPECT_TRUE(state.routable_origins[0].blocked);
  ASSERT_EQ(state.skipped_entries.size(), 1u);
  EXPECT_THAT(state.skipped_entries[0].raw, HasSubstr("0.0.0.0/0"));
  EXPECT_FALSE(state.skipped_entries[0].reason.empty());
  EXPECT_FALSE(state.routes_unavailable);
  EXPECT_FALSE(state.routes_hard_stale);
  EXPECT_TRUE(state.routes_stale);
  EXPECT_TRUE(state.routes_truncated);
  EXPECT_EQ(state.routes_dropped, 3);
  EXPECT_EQ(state.routes_digest, "deadbeef");
  EXPECT_EQ(state.edge_host, "edge.fairyland.io");
  EXPECT_EQ(state.edge_port, 443);
  EXPECT_EQ(state.gate_host, "gate.fairyland.io");
  ASSERT_EQ(state.recent_connects.size(), 1u);
  EXPECT_EQ(state.recent_connects[0].authority, "app.corp:443");
  EXPECT_EQ(state.recent_connects[0].response_code, 403);
}

// A failed bind has to leave the page something to act on: the reason, and when
// the next automatic attempt is due.
TEST_F(TeleportTunnelBindClientTest, StateSnapshotCarriesTheArmedRetry) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  SetBindResponse("");
  SetBindStatus(net::HTTP_SERVICE_UNAVAILABLE);
  StartAndRunUntilIdle();

  const tunnel_internal::TunnelStateSnapshot state =
      service()->GetStateSnapshot();
  EXPECT_FALSE(state.has_token);
  EXPECT_THAT(state.last_bind_error, HasSubstr("503"));
  EXPECT_FALSE(state.next_retry_at.is_null());
  EXPECT_TRUE(state.next_refresh_at.is_null());
  EXPECT_TRUE(state.last_bind_success_at.is_null());
}

TEST_F(TeleportTunnelBindClientTest, RebindIsRejectedWhenPreconditionsAreUnmet) {
  CreateService();
  RunUntilIdle();
  ASSERT_EQ(bind_attempts(), 0);

  // Neither precondition holds: the mTLS handshake could not authenticate and
  // the profile is not enrolled, so accepting would just burn a backoff step.
  EXPECT_FALSE(service()->Rebind());
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 0);
}

TEST_F(TeleportTunnelBindClientTest, RebindIsRejectedWhileABindIsInFlight) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  StallNextBind();
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  // Refused rather than queued: the button is a request for a FRESH result, and
  // one is already on its way. Queueing would also mean the page reports
  // "accepted" for work it did not cause.
  EXPECT_FALSE(service()->Rebind());
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 1);
}

TEST_F(TeleportTunnelBindClientTest, RebindIsRateLimited) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  ASSERT_TRUE(service()->Rebind());
  RunUntilIdle();
  ASSERT_EQ(bind_attempts(), 2);

  EXPECT_FALSE(service()->Rebind());  // within the minimum interval
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 2);

  task_environment_.FastForwardBy(TeleportTunnelService::kRebindMinInterval);
  EXPECT_TRUE(service()->Rebind());
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 3);
}

// The asymmetry established in task 7, pinned so a later "unify the two entry
// points" cleanup cannot quietly drop either half. Wake-ups need no interval:
// they never abort an outstanding bind, so any number of them during one flight
// collapses into a single pending bit. The manual button is an unbounded
// human-driven trigger on the same gate and does need one.
TEST_F(TeleportTunnelBindClientTest, WakeUpsAreNotRateLimitedButRebindIs) {
  MarkProfileEnrolled();
  SetAutoSelectPolicy({kGateEntry});
  StartAndRunUntilIdle();
  ASSERT_EQ(bind_attempts(), 1);

  // Two wake-ups back to back with no clock advance at all: both bind.
  SetAutoSelectPolicy({kGateEntry, kEdgeEntry});
  RunUntilIdle();
  SetAutoSelectPolicy({kGateEntry});
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 3);

  // The manual button, in the same instant, gets exactly one.
  EXPECT_TRUE(service()->Rebind());
  RunUntilIdle();
  ASSERT_EQ(bind_attempts(), 4);
  EXPECT_FALSE(service()->Rebind());
  RunUntilIdle();
  EXPECT_EQ(bind_attempts(), 4);
}

// NOTE: the regression test that pinned
// TD-TUNNEL-FIRSTACCESS-PROXYCONFIG-NOT-APPLIED
// (RoutableOriginsResyncWhenPolicyLandsAfterStart) is gone with the behaviour it
// pinned: the routing table is no longer derived from the managed AutoSelect
// policy at all, so "re-derive when the policy lands after Start()" has no
// subject. The defect class it guarded (a routing table captured empty and never
// corrected) moves to the bind response and is re-pinned there.

}  // namespace
}  // namespace teleport
