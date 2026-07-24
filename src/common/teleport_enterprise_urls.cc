#include "teleport/common/teleport_enterprise_urls.h"

#include "base/no_destructor.h"
#include "teleport/common/teleport_deployment_config.h"

namespace teleport {

namespace {

// Runtime-injected enrollment-flow hosts: per-tenant OP hosts the server
// signals via the X-Teleport-Enroll-Allow-Hosts response header on the
// intercept page (§3.4a), live-verified end to end. A NoDestructor holds
// them for the process lifetime.
std::vector<std::string>& MutableInjectedHosts() {
  static base::NoDestructor<std::vector<std::string>> hosts;
  return *hosts;
}

}  // namespace

std::string EnterpriseEnrollUrl() {
  return DeploymentEnrollUrl();
}

std::string EnterpriseRegisterHandlerUrl() {
  return DeploymentRegisterHandlerUrl();
}

std::vector<std::string> EnterpriseTrustedRedirectHosts() {
  return {DeploymentTrustedRedirectHost()};
}

std::vector<std::string> EnterpriseEnrollmentAllowedHosts() {
  const std::string& d = DeploymentDomain();
  std::vector<std::string> hosts = {TeleportHostFor(d), AccountsHostFor(d)};
  const std::vector<std::string>& injected = MutableInjectedHosts();
  hosts.insert(hosts.end(), injected.begin(), injected.end());
  return hosts;
}

void AddInjectedEnrollmentHost(const std::string& host) {
  MutableInjectedHosts().push_back(host);
}

void ClearInjectedEnrollmentHosts() {
  MutableInjectedHosts().clear();
}

}  // namespace teleport
