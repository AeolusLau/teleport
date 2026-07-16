#ifndef TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_
#define TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_

#include <string>
#include <string_view>
#include <vector>

class GURL;

namespace teleport {

// True when url belongs to the enrollment flow — its host[:port] is an EXACT
// member of the enrollment-flow whitelist (teleport.<D>, accounts.<D>, and any
// server-injected per-tenant OP hosts). Only https is considered valid. §3.4a.
bool IsEnrollmentFlowUrl(const GURL& url);

// Parse an X-Teleport-Enroll-Allow-Hosts response-header value (comma-separated
// host[:port] entries) into the subset that is SAFE to add to the enrollment
// whitelist: each entry must be a strict subdomain of the deployment domain,
// i.e. end with deployment_suffix (= ".<host-of-D>") with a non-empty label in
// front, and contain only canonical host[:port] characters. This bounds the
// server's dynamic injection to OTHER hosts under the SAME trusted deployment
// domain D — a spoofed/compromised enroll response can never widen the gate to
// an unrelated external host. deployment_suffix must start with '.'.
std::vector<std::string> ParseInjectableEnrollmentHosts(
    std::string_view header_value,
    std::string_view deployment_suffix);

// Gate interception decision (pure function, easy to unit-test).
// Returns true = this navigation should be blocked.
//   should_gate    : this profile is subject to the gate (policy on + regular
//                    profile)
//   is_enrolled    : device has completed managed enrollment
//   is_main_frame  : main-frame navigation
//   url            : destination URL
bool ShouldBlockNavigation(bool should_gate,
                           bool is_enrolled,
                           bool is_main_frame,
                           const GURL& url);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_
