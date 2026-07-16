#ifndef TELEPORT_COMMON_TELEPORT_ENTERPRISE_URLS_H_
#define TELEPORT_COMMON_TELEPORT_ENTERPRISE_URLS_H_

#include <string>
#include <vector>

namespace teleport {

// These four functions are thin delegates onto the endpoint-derivation
// helpers in teleport_deployment_config.h: all values are derived from the
// resolved deployment domain D (single source of truth), not baked per build
// via a buildflag. Kept as a stable, throttle-patch-facing API so upstream
// callers never need to change when the derivation logic evolves.

// URL that Keystone redirects the browser to after a successful OIDC sign-in,
// carrying the enrollment payload. Replaces upstream
// "https://chromeenterprise.google/enroll" in the OIDC enrollment throttle.
std::string EnterpriseEnrollUrl();

// Header-interception register-handler URL. Replaces upstream
// "https://chromeenterprise.google/profile-enrollment/register-handler".
std::string EnterpriseRegisterHandlerUrl();

// Redirect-source hosts trusted to initiate OIDC enrollment. Replaces the
// upstream hardcoded Entra hosts. Derived from the resolved deployment domain
// D — the same teleport.<D> host used for the enroll / register-handler URLs
// (the enrollment host is consolidated onto teleport.<D>; there is no
// separate per-build Keystone OP host anymore). Only consulted when
// generic-OIDC profile management is force-disabled; the shipped config keeps
// that feature enabled (so the throttle skips this check), making this list a
// defensive fallback, not the production enrollment gate.
std::vector<std::string> EnterpriseTrustedRedirectHosts();

// Exact host[:port] whitelist of the enrollment-flow hosts (§3.4a). Replaces the
// former ".<host-of-D>" suffix wildcard, which — once D can be a customer's own
// internal domain (e.g. acme.internal) — would open EVERY *.acme.internal site
// to the unenrolled browser and defeat "enroll before browsing". The set is:
//   - teleport.<D>  (enroll-landing / register-handler / DM: one host)
//   - accounts.<D>  (the fixed universal login springboard of the current
//                    fairyland topology; tenant is chosen via select_tenant on
//                    this shared host, not a per-tenant OP subdomain)
//   - any hosts injected at runtime via AddInjectedEnrollmentHost (reserved for
//     a future per-tenant OP topology, server-signalled through the intercept
//     page; empty today).
// Each entry is a canonical "host[:port]" (port present only when D carries one).
std::vector<std::string> EnterpriseEnrollmentAllowedHosts();

// Runtime injection seam for additional enrollment-flow hosts (future per-tenant
// OP hosts the server signals via the gate intercept page). No-ops for the
// current topology; the static teleport.<D>/accounts.<D> pair already covers it.
void AddInjectedEnrollmentHost(const std::string& host);
void ClearInjectedEnrollmentHosts();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_ENTERPRISE_URLS_H_
