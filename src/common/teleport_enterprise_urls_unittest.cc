#include "teleport/common/teleport_enterprise_urls.h"

#include "teleport/teleport_policy_buildflags.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// The enroll landing + register-handler URLs must always be https — they are
// patched into the upstream OIDC enrollment throttle, which our managed-profile
// security model trusts.
TEST(TeleportEnterpriseUrlsTest, EnrollUrlsAreHttpsAndNonEmpty) {
  EXPECT_EQ(EnterpriseEnrollUrl().rfind("https://", 0), 0u);
  EXPECT_EQ(EnterpriseRegisterHandlerUrl().rfind("https://", 0), 0u);
}

TEST(TeleportEnterpriseUrlsTest, TrustedRedirectHostsAreHttpsAndNonEmpty) {
  const auto hosts = EnterpriseTrustedRedirectHosts();
  ASSERT_FALSE(hosts.empty());
  for (const auto& host : hosts) {
    EXPECT_EQ(host.rfind("https://", 0), 0u) << host;
  }
}

// The enroll / register-handler hosts are baked per build via
// teleport_use_release_endpoints: release points at beansec.com, dev at
// fairyland.io. The register-handler URL must always carry the
// /profile-enrollment/register-handler path the device-manager dispatches on.
TEST(TeleportEnterpriseUrlsTest, EnrollUrlMatchesEndpointBuildflag) {
  const std::string enroll = EnterpriseEnrollUrl();
  const std::string reg = EnterpriseRegisterHandlerUrl();
#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  EXPECT_NE(enroll.find("teleport.beansec.com"), std::string::npos) << enroll;
  EXPECT_NE(reg.find("teleport.beansec.com"), std::string::npos) << reg;
#else
  EXPECT_NE(enroll.find("enroll.teleport.fairyland.io"), std::string::npos)
      << enroll;
  EXPECT_NE(reg.find("enroll.teleport.fairyland.io"), std::string::npos) << reg;
#endif
  EXPECT_NE(reg.find("/profile-enrollment/register-handler"),
            std::string::npos)
      << reg;
}

TEST(TeleportEnterpriseUrlsTest, EnrollmentDomainSuffixesNonEmpty) {
  const auto suffixes = EnterpriseEnrollmentDomainSuffixes();
  ASSERT_FALSE(suffixes.empty());
  // Each suffix starts with a dot, for use as a host suffix matcher.
  for (const auto& s : suffixes) {
    EXPECT_EQ('.', s.front());
  }
  // The suffix is baked per build via teleport_use_release_endpoints, mirroring
  // EnrollUrlMatchesEndpointBuildflag: release=beansec.com, dev=fairyland.io.
#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  EXPECT_EQ(suffixes[0], ".beansec.com");
#else
  EXPECT_EQ(suffixes[0], ".fairyland.io");
#endif
}

}  // namespace
}  // namespace teleport
