#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_THROTTLE_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_THROTTLE_H_

#include "content/public/browser/navigation_throttle.h"

namespace content {
class NavigationThrottleRegistry;
}  // namespace content

namespace teleport {

// Blocks every non-enrollment web navigation on an unenrolled, gated profile and
// redirects the tab to the enroll landing page.
class TeleportEnrollmentGateThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit TeleportEnrollmentGateThrottle(
      content::NavigationThrottleRegistry& registry);
  TeleportEnrollmentGateThrottle(const TeleportEnrollmentGateThrottle&) = delete;
  TeleportEnrollmentGateThrottle& operator=(
      const TeleportEnrollmentGateThrottle&) = delete;
  ~TeleportEnrollmentGateThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillStartRequest() override;
  ThrottleCheckResult WillRedirectRequest() override;
  ThrottleCheckResult WillProcessResponse() override;
  const char* GetNameForLogging() override;

 private:
  ThrottleCheckResult CheckRequest();

  // Read the X-Teleport-Enroll-Allow-Hosts response header on an enrollment-flow
  // host (teleport.<D> / accounts.<D>) and add the strict-subdomain hosts it
  // lists to the enrollment whitelist, so the server can dynamically open the
  // per-tenant OP host (<slug>.<D>) it is about to redirect the browser to
  // (§3.4a). Bounded to subdomains of D by ParseInjectableEnrollmentHosts.
  void MaybeInjectAllowedHostsFromResponse();
};

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_THROTTLE_H_
