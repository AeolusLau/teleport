#include "teleport/browser/enterprise/teleport_enrollment_gate.h"

#include "chrome/browser/browser_process.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/profiles/profile_attributes_entry.h"
#include "chrome/browser/profiles/profile_attributes_storage.h"
#include "chrome/browser/profiles/profile_manager.h"
#include "components/policy/core/common/cloud/cloud_policy_core.h"
#include "components/policy/core/common/cloud/cloud_policy_manager.h"
#include "components/policy/core/common/cloud/cloud_policy_store.h"
#include "components/prefs/pref_registry_simple.h"
#include "components/prefs/pref_service.h"
#include "teleport/common/teleport_pref_names.h"

namespace teleport {

bool ShouldGateProfile(Profile* profile) {
  if (!profile || profile->IsOffTheRecord() || !profile->IsRegularProfile()) {
    return false;
  }
  PrefService* local_state = g_browser_process->local_state();
  return local_state &&
         local_state->GetBoolean(prefs::kRequireEnrollmentToBrowse);
}

bool IsEnrolled(Profile* profile) {
  if (!profile) {
    return false;
  }
  ProfileManager* pm = g_browser_process->profile_manager();
  if (!pm) {
    return false;
  }
  ProfileAttributesEntry* entry =
      pm->GetProfileAttributesStorage().GetProfileAttributesWithPath(
          profile->GetPath());
  if (!entry || entry->GetProfileManagementId().empty()) {
    return false;
  }
  policy::CloudPolicyManager* manager = profile->GetCloudPolicyManager();
  return manager && manager->core() && manager->core()->store() &&
         manager->core()->store()->has_policy();
}

bool ShouldLockProfile(ProfileAttributesEntry* entry) {
  if (!entry || !entry->GetProfileManagementId().empty()) {
    // Unknown entry, or already enrolled (management id set).
    return false;
  }
  PrefService* local_state = g_browser_process->local_state();
  return local_state &&
         local_state->GetBoolean(prefs::kRequireEnrollmentToBrowse);
}

void RegisterEnrollmentGateLocalStatePrefs(PrefRegistrySimple* registry) {
  registry->RegisterBooleanPref(prefs::kRequireEnrollmentToBrowse, true);
}

}  // namespace teleport
