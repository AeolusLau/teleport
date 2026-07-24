#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_

#include <optional>
#include <string>

class Profile;
class PrefRegistrySimple;
class ProfileAttributesEntry;

namespace teleport {

// Whether this profile is subject to the enrollment gate: a regular
// (non-OTR/guest/system) profile while the local_state policy
// kRequireEnrollmentToBrowse is true.
bool ShouldGateProfile(Profile* profile);

// Entry-based predicate used in the ProfilePicker handler (where only the
// ProfileAttributesEntry is available, not a loaded Profile*): true when the
// profile is NOT yet enrolled (ProfileManagementId is empty) AND the local_state
// policy kRequireEnrollmentToBrowse is true. Keyed on the management id rather
// than CanBeManaged() so a never-signed-in dasherless profile still gates.
bool ShouldLockProfile(ProfileAttributesEntry* entry);

// Whether this profile has completed enrollment: ProfileManagementId is set
// AND the user cloud policy has been fetched.
bool IsEnrolled(Profile* profile);

// Registers the gate's local_state prefs: kRequireEnrollmentToBrowse (defaults
// to false = BYOD-first; managed deployments opt in via policy/machine config)
// and kEnrolledDeploymentDomain (the domain D last enrolled against, §4.5).
void RegisterEnrollmentGateLocalStatePrefs(PrefRegistrySimple* registry);

// --- §4.5 management-domain migration -------------------------------------
//
// Record the deployment domain the browser just enrolled against. Called on
// enrollment success so a later admin-channel domain change can be detected.
void PersistEnrolledDomain();

// If this profile is enrolled but the resolved deployment domain D no longer
// matches the domain it enrolled against (an admin channel — MDM / machine
// file — changed D on an already-enrolled browser), treat it as a management-
// domain migration: reset the profile's enrollment (clear its management id) so
// IsEnrolled() becomes false and, when the gate is enabled, re-locks, forcing a
// fresh enrollment against the new D instead of running in the half-managed
// zombie state (old DM token is DEVICE_NOT_FOUND against the new server).
// Idempotent + a no-op when not enrolled or D is unchanged. Called from the
// gate throttle before it evaluates a navigation, so a stale-enrolled profile
// can never browse when the gate is enabled.
void MaybeHandleDomainMigration(Profile* profile);

// The domain the browser enrolled against when a migration is pending (enrolled
// domain differs from the resolved D), else nullopt. Surfaced on chrome://version
// as "changed from <old> (re-enrollment required)".
std::optional<std::string> PendingDomainMigrationFrom();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_
