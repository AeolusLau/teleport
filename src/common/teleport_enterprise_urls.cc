#include "teleport/common/teleport_enterprise_urls.h"

#include "teleport/teleport_policy_buildflags.h"

namespace teleport {

namespace {
// Branded enterprise endpoints. Single source of truth consumed by the patched
// upstream OIDC enrollment throttle. Baked per build via the
// teleport_use_release_endpoints buildflag (switch-based overrides are
// channel/test-gated upstream and unreliable on STABLE/BETA).
#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
// Release: production douan.cn endpoints.
constexpr char kEnrollUrl[] = "https://enroll.teleport.douan.cn/start";
constexpr char kRegisterHandlerUrl[] =
    "https://enroll.teleport.douan.cn/profile-enrollment/register-handler";
constexpr char kKeystoneOpHost[] = "https://id.douan.cn";
constexpr char kEnrollmentDomainSuffix[] = ".douan.cn";
#else
// Dev: fairyland.io endpoints. The OP host is a sample value — under
// generic-OIDC the trusted-redirect-host check is skipped by the throttle, so
// it only serves as a placeholder.
constexpr char kEnrollUrl[] = "https://enroll.teleport.fairyland.io/start";
constexpr char kRegisterHandlerUrl[] =
    "https://enroll.teleport.fairyland.io/profile-enrollment/register-handler";
constexpr char kKeystoneOpHost[] = "https://dadou.fairyland.io";
constexpr char kEnrollmentDomainSuffix[] = ".fairyland.io";
#endif  // BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
}  // namespace

std::string EnterpriseEnrollUrl() {
  return kEnrollUrl;
}

std::string EnterpriseRegisterHandlerUrl() {
  return kRegisterHandlerUrl;
}

std::vector<std::string> EnterpriseTrustedRedirectHosts() {
  return {kKeystoneOpHost};
}

std::vector<std::string> EnterpriseEnrollmentDomainSuffixes() {
  return {kEnrollmentDomainSuffix};
}

}  // namespace teleport
