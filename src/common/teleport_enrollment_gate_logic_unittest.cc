#include "teleport/common/teleport_enrollment_gate_logic.h"

#include "teleport/common/teleport_deployment_config.h"
#include "teleport/common/teleport_enterprise_urls.h"
#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"

namespace teleport {
namespace {

// §3.4a: only the EXACT enrollment-flow hosts derived from D are allowed —
// teleport.<D> and accounts.<D>. Arbitrary subdomains of <D> are NOT (the
// wildcard that this replaces would expose every *.<D> internal site to the
// unenrolled browser). D here is the baked dev default.
TEST(TeleportEnrollmentGateLogicTest, IsEnrollmentFlowUrlExactHosts) {
  ClearInjectedEnrollmentHosts();
  const std::string d = DeploymentDomain();
  const std::string teleport_host = TeleportHostFor(d);  // teleport.<D>
  const std::string accounts_host = AccountsHostFor(d);  // accounts.<D>

  // The two whitelisted hosts are allowed.
  EXPECT_TRUE(
      IsEnrollmentFlowUrl(GURL("https://" + teleport_host + "/enroll/start")));
  EXPECT_TRUE(
      IsEnrollmentFlowUrl(GURL("https://" + accounts_host + "/login")));

  // An ARBITRARY subdomain of D is NO LONGER allowed (the security fix).
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://evil." + d + "/authorize")));
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://dadou." + d + "/x")));
  // The apex domain itself is not an enrollment host.
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://" + d + "/path")));
  // Unrelated + suffix-spoof hosts are not allowed.
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://example.com/")));
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://" + d + ".evil.com/")));
  // Non-https / invalid.
  EXPECT_FALSE(
      IsEnrollmentFlowUrl(GURL("http://" + teleport_host + "/enroll/")));
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("not a url")));
}

// A runtime-injected host (future per-tenant OP) joins the allowed set.
TEST(TeleportEnrollmentGateLogicTest, InjectedHostBecomesEnrollmentFlowUrl) {
  const std::string d = DeploymentDomain();
  const std::string op_host = "op-slug." + d;
  ClearInjectedEnrollmentHosts();
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://" + op_host + "/authorize")));
  AddInjectedEnrollmentHost(op_host);
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://" + op_host + "/authorize")));
  ClearInjectedEnrollmentHosts();
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://" + op_host + "/authorize")));
}

// The server-injection header may only ever widen the whitelist to strict
// subdomains of the SAME trusted deployment domain (§3.4a).
TEST(TeleportEnrollmentGateLogicTest, ParseInjectableEnrollmentHosts) {
  const std::string_view suffix = ".acme.internal";
  // Valid per-tenant OP hosts (strict subdomains) are accepted, incl. a list.
  EXPECT_EQ(ParseInjectableEnrollmentHosts("dadou.acme.internal", suffix),
            (std::vector<std::string>{"dadou.acme.internal"}));
  EXPECT_EQ(
      ParseInjectableEnrollmentHosts("dadou.acme.internal, op.acme.internal",
                                     suffix),
      (std::vector<std::string>{"dadou.acme.internal", "op.acme.internal"}));
  // The apex host-of-D itself is NOT a strict subdomain -> rejected.
  EXPECT_TRUE(
      ParseInjectableEnrollmentHosts("acme.internal", suffix).empty());
  // External / suffix-spoof / scheme / path / userinfo / uppercase -> rejected.
  EXPECT_TRUE(ParseInjectableEnrollmentHosts("evil.com", suffix).empty());
  EXPECT_TRUE(
      ParseInjectableEnrollmentHosts("acme.internal.evil.com", suffix).empty());
  EXPECT_TRUE(ParseInjectableEnrollmentHosts("https://dadou.acme.internal",
                                             suffix)
                  .empty());
  EXPECT_TRUE(
      ParseInjectableEnrollmentHosts("dadou.acme.internal/x", suffix).empty());
  EXPECT_TRUE(
      ParseInjectableEnrollmentHosts("a@dadou.acme.internal", suffix).empty());
  EXPECT_TRUE(
      ParseInjectableEnrollmentHosts("Dadou.acme.internal", suffix).empty());
  // A subdomain with an explicit port is accepted (host:port form).
  EXPECT_EQ(
      ParseInjectableEnrollmentHosts("dadou.acme.internal:8443", suffix),
      (std::vector<std::string>{"dadou.acme.internal:8443"}));
  // Empty / malformed suffix -> nothing injectable.
  EXPECT_TRUE(
      ParseInjectableEnrollmentHosts("dadou.acme.internal", "").empty());
}

TEST(TeleportEnrollmentGateLogicTest, ShouldBlockNavigation) {
  const GURL web("https://example.com/");
  const GURL enroll("https://teleport.fairyland.io/enroll/start");
  const GURL internal("chrome://settings/");

  // Gate active + not enrolled + main frame + regular web URL → block.
  EXPECT_TRUE(ShouldBlockNavigation(true, false, true, web));
  // Enrollment flow URL → allow.
  EXPECT_FALSE(ShouldBlockNavigation(true, false, true, enroll));
  // chrome:// and other internal pages → allow (only http/https is intercepted).
  EXPECT_FALSE(ShouldBlockNavigation(true, false, true, internal));
  // Already enrolled → allow.
  EXPECT_FALSE(ShouldBlockNavigation(true, true, true, web));
  // Gate not active (policy off / non-regular profile) → allow.
  EXPECT_FALSE(ShouldBlockNavigation(false, false, true, web));
  // Sub-frame → allow (only main-frame navigations are intercepted).
  EXPECT_FALSE(ShouldBlockNavigation(true, false, false, web));
}

}  // namespace
}  // namespace teleport
