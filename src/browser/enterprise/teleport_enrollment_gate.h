#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_

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

// Registers the gate's local_state pref (defaults to true = secure default).
void RegisterEnrollmentGateLocalStatePrefs(PrefRegistrySimple* registry);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_GATE_H_
