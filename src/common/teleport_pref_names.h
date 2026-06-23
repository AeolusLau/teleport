#ifndef TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_
#define TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_

namespace teleport::prefs {

// local_state bool. true (secure default) = unmanaged devices cannot browse.
inline constexpr char kRequireEnrollmentToBrowse[] =
    "teleport.enrollment.require_enrollment_to_browse";

}  // namespace teleport::prefs

#endif  // TELEPORT_COMMON_TELEPORT_PREF_NAMES_H_
