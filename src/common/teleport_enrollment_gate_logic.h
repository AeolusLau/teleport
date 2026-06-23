#ifndef TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_
#define TELEPORT_COMMON_TELEPORT_ENROLLMENT_GATE_LOGIC_H_

class GURL;

namespace teleport {

// True when url belongs to the enrollment flow (allow-listed by managed domain
// suffix, covers enroll-landing / per-tenant OP / central accounts multi-host).
// Only https is considered valid.
bool IsEnrollmentFlowUrl(const GURL& url);

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
