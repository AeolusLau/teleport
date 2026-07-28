// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_service.h"

#include <algorithm>
#include <optional>
#include <string>
#include <vector>

#include "base/test/bind.h"
#include "base/values.h"
#include "chrome/browser/enterprise/signin/enterprise_signin_prefs.h"
#include "chrome/test/base/testing_profile.h"
#include "components/content_settings/core/common/pref_names.h"
#include "components/prefs/pref_service.h"
#include "components/sync_preferences/testing_pref_service_syncable.h"
#include "content/public/test/browser_task_environment.h"
#include "net/base/proxy_server.h"
#include "net/http/http_request_headers.h"
#include "net/http/http_status_code.h"
#include "net/proxy_resolution/proxy_config.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/weak_wrapper_shared_url_loader_factory.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "services/network/test/test_url_loader_factory.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"

namespace teleport {
namespace {

// One managed AutoSelectCertificateForUrls list-pref entry (a JSON string), as
// the device-manager compiler emits it.
std::string AutoSelectEntry(const std::string& pattern) {
  return R"({"pattern":")" + pattern +
         R"(","filter":{"ISSUER":{"CN":"Teleport Device CA"}}})";
}

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
  content::BrowserTaskEnvironment task_environment_{
      content::BrowserTaskEnvironment::TimeSource::MOCK_TIME};
  TestingProfile profile_;
  network::TestURLLoaderFactory url_loader_factory_;
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
  // PrefChangeRegistrar observer re-invokes MaybeAutoStartFromPrefs, which now
  // finds both conditions satisfied and calls Start() itself.
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

// Regression (TD-TUNNEL-FIRSTACCESS-PROXYCONFIG-NOT-APPLIED): the enrollment
// registrar (teleport_oidc_inplace_registrar::MaybeStartTunnelService) calls
// Start() unconditionally on policy-FETCH success, which can precede the
// AutoSelect pref propagating. Start() then captures NO routable origins, so the
// pushed CustomProxyConfig routes nothing and the app falls through to the
// browser's ordinary proxy (DIRECT / a system HTTP proxy) until a restart. The
// pref observer must re-derive once the policy lands, recovering routing WITHOUT
// a restart. Verified live via chrome://net-export: pre-fix the app CONNECTs to
// the system proxy (or DIRECT-NAME_NOT_RESOLVED); post-restart it CONNECTs to
// edge.<domain>:443 → 200.
TEST_F(TeleportTunnelBindClientTest,
       RoutableOriginsResyncWhenPolicyLandsAfterStart) {
  profile_.GetPrefs()->SetString(
      enterprise_signin::prefs::kPolicyRecoveryToken, "dm-token-123");
  url_loader_factory_.SetInterceptor(base::BindLambdaForTesting(
      [&](const network::ResourceRequest& request) {
        url_loader_factory_.AddResponse(request.url.spec(),
                                        R"({"tunnel_token":"CNF"})");
      }));

  TeleportTunnelService service(&profile_);
  service.SetUrlLoaderFactoryForTesting(
      url_loader_factory_.GetSafeWeakWrapper());

  // The registrar fires Start() BEFORE the managed AutoSelect policy lands.
  service.Start();
  task_environment_.RunUntilIdle();
  // Bug shape: routable origins captured empty (the policy pref was not set yet).
  EXPECT_TRUE(service.GetRoutableOriginsForTesting().empty());

  // The fetched policy now propagates to the managed pref (the app + edge/gate,
  // as the device-manager compiler emits it). Managed pref store: real policy
  // lands here, and content_settings::PolicyProvider DCHECKs on a user setting.
  base::ListValue entries;
  entries.Append(AutoSelectEntry("https://demoapp.example.com:443"));
  entries.Append(AutoSelectEntry("https://edge.fairyland.io:443"));
  entries.Append(AutoSelectEntry("https://gate.fairyland.io:443"));
  profile_.GetTestingPrefService()->SetManagedPref(
      prefs::kManagedAutoSelectCertificateForUrls, std::move(entries));
  task_environment_.RunUntilIdle();

  // Fix: the pref observer re-derived the routable origins (edge/gate excluded)
  // — the app is now routed through the tunnel without a browser restart.
  const std::vector<std::string> origins =
      service.GetRoutableOriginsForTesting();
  EXPECT_FALSE(origins.empty());
  EXPECT_TRUE(std::any_of(
      origins.begin(), origins.end(), [](const std::string& o) {
        return o.find("demoapp.example.com") != std::string::npos;
      }));
}

}  // namespace
}  // namespace teleport
