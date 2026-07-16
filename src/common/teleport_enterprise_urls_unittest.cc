#include "teleport/common/teleport_enterprise_urls.h"

#include "teleport/common/teleport_deployment_config.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportEnterpriseUrlsTest, EnrollUrlsAreHttpsAndNonEmpty) {
  EXPECT_EQ(EnterpriseEnrollUrl().rfind("https://", 0), 0u);
  EXPECT_EQ(EnterpriseRegisterHandlerUrl().rfind("https://", 0), 0u);
}

// The enroll / register-handler / trusted-host URLs must be exactly the values
// derived from the resolved deployment domain D — no hardcoded per-build
// constant remains.
TEST(TeleportEnterpriseUrlsTest, DelegatesToDeploymentDerivation) {
  EXPECT_EQ(EnterpriseEnrollUrl(), DeploymentEnrollUrl());
  EXPECT_EQ(EnterpriseRegisterHandlerUrl(), DeploymentRegisterHandlerUrl());
  const auto hosts = EnterpriseTrustedRedirectHosts();
  ASSERT_EQ(hosts.size(), 1u);
  EXPECT_EQ(hosts[0], DeploymentTrustedRedirectHost());
}

TEST(TeleportEnterpriseUrlsTest, RegisterHandlerCarriesDispatchPath) {
  EXPECT_NE(EnterpriseRegisterHandlerUrl().find(
                "/profile-enrollment/register-handler"),
            std::string::npos);
}

TEST(TeleportEnterpriseUrlsTest, AllowedHostsAreTeleportAndAccountsOfD) {
  ClearInjectedEnrollmentHosts();
  const auto hosts = EnterpriseEnrollmentAllowedHosts();
  ASSERT_EQ(hosts.size(), 2u);
  EXPECT_EQ(hosts[0], TeleportHostFor(DeploymentDomain()));
  EXPECT_EQ(hosts[1], AccountsHostFor(DeploymentDomain()));
}

TEST(TeleportEnterpriseUrlsTest, InjectedHostsAppendToAllowedSet) {
  ClearInjectedEnrollmentHosts();
  AddInjectedEnrollmentHost("op.tenant.example");
  const auto hosts = EnterpriseEnrollmentAllowedHosts();
  ASSERT_EQ(hosts.size(), 3u);
  EXPECT_EQ(hosts[2], "op.tenant.example");
  ClearInjectedEnrollmentHosts();
  EXPECT_EQ(EnterpriseEnrollmentAllowedHosts().size(), 2u);
}

}  // namespace
}  // namespace teleport
