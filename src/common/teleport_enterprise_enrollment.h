#ifndef TELEPORT_COMMON_TELEPORT_ENTERPRISE_ENROLLMENT_H_
#define TELEPORT_COMMON_TELEPORT_ENTERPRISE_ENROLLMENT_H_

#include "base/functional/callback.h"

class GURL;

namespace teleport {

// Machine-level (CBCM) enrollment identity for macOS. We deliberately use a
// SINGLE FIXED base bundle id for every channel (stable/canary/beta), mirroring
// upstream Chrome's "explicitly com.google.Chrome, no matter what this app's
// bundle id is" behavior: machine enrollment is a whole-machine, channel-
// agnostic concept, so one MDM payload enrolls all channels. This is the value
// the patched browser_dm_token_storage_mac.mm reads managed prefs from and the
// plist (/Library/<id>.plist) CFPreferences resolves.
inline constexpr char kManagedPrefsBundleId[] = "com.beansec.Teleport";

// File fallbacks for the enrollment token / options (read when the managed
// preference is not forced). Mirror Chrome's /Library/Google/Chrome/... paths.
inline constexpr char kEnrollmentTokenFilePath[] =
    "/Library/Teleport/CloudManagementEnrollmentToken";
inline constexpr char kEnrollmentOptionsFilePath[] =
    "/Library/Teleport/CloudManagementEnrollmentOptions";

// Subdirectory under DIR_APP_DATA (a per-user path on macOS) where the
// machine-level DMToken is cached. Channel-agnostic (matches the single-base-id
// enrollment domain). Mirrors Chrome's "Google/Chrome Cloud Enrollment/".
inline constexpr char kDmTokenStorageDir[] = "Teleport/Cloud Enrollment/";

// Terminal outcome of the in-place OIDC enrollment flow (registrar → picker).
enum class EnrollmentResult {
  kSuccess,
  kRegistrationFailed,  // CloudPolicyClient registration / prerequisites failed
  kPolicyRejected,      // policy fetched but the store rejected it (validation)
  kTimeout,             // whole-flow watchdog fired
};

// Callback carrying the enrollment outcome from the self-owned in-place
// registrar back to the enrollment UI step.
using EnrollmentDoneCallback = base::OnceCallback<void(EnrollmentResult)>;

// URL the enrollment UI navigates to on failure: the enroll start page with a
// fixed error code the server renders as a banner (codes must stay in sync
// with fairyland enroll-landing's enrollErrorMessage). kSuccess maps to the
// plain enroll start URL.
GURL EnrollmentErrorUrl(EnrollmentResult result);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_ENTERPRISE_ENROLLMENT_H_
