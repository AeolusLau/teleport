#ifndef TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_
#define TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_

namespace teleport::prefs {

// local_state bool. true (secure default) = unmanaged devices cannot browse.
inline constexpr char kRequireEnrollmentToBrowse[] =
    "teleport.enrollment.require_enrollment_to_browse";

// local_state string. The base deployment domain D that was in effect when this
// device/profile last completed managed enrollment. Compared at startup against
// the freshly resolved D; a mismatch means an admin channel re-pointed the
// deployment (management-domain migration) — see teleport_domain_migration.h.
inline constexpr char kEnrolledDeploymentDomain[] =
    "teleport.enrollment.enrolled_domain";

// local_state dict. The user-accepted deployment domain (level 4) as a
// self-authenticating entry {domain, identity, signature} the resolver
// re-verifies offline against the baked root key at every startup. Written by
// the teleport://enroll page after a successful server-identity verification.
inline constexpr char kServerIdentityEntry[] =
    "teleport.deployment.server_identity_entry";

}  // namespace teleport::prefs

#endif  // TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_
