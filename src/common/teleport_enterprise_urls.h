#ifndef TELEPORT_COMMON_TELEPORT_ENTERPRISE_URLS_H_
#define TELEPORT_COMMON_TELEPORT_ENTERPRISE_URLS_H_

#include <string>
#include <vector>

namespace teleport {

// URL that Keystone redirects the browser to after a successful OIDC sign-in,
// carrying the enrollment payload. Replaces upstream
// "https://chromeenterprise.google/enroll" in the OIDC enrollment throttle.
std::string EnterpriseEnrollUrl();

// Header-interception register-handler URL. Replaces upstream
// "https://chromeenterprise.google/profile-enrollment/register-handler".
std::string EnterpriseRegisterHandlerUrl();

// Redirect-source hosts trusted to initiate OIDC enrollment. Replaces the
// upstream hardcoded Entra hosts. Our Keystone OP host(s). Only consulted when
// generic-OIDC profile management is force-disabled; the shipped config keeps
// that feature enabled (so the throttle skips this check), making this list a
// defensive fallback, not the production enrollment gate.
std::vector<std::string> EnterpriseTrustedRedirectHosts();

// Domain suffixes that cover all enrollment-flow hosts (enroll-landing,
// per-tenant OP, central accounts). A request host ending with one of these
// suffixes is considered part of the managed enrollment flow.
// dev=.fairyland.io, release=.beansec.com.
std::vector<std::string> EnterpriseEnrollmentDomainSuffixes();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_ENTERPRISE_URLS_H_
