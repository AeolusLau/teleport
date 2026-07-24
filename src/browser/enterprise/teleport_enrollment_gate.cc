#include "teleport/browser/enterprise/teleport_enrollment_gate.h"

#include <string>

#include "base/functional/callback_helpers.h"
#include "base/logging.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/enterprise/signin/enterprise_signin_prefs.h"
#include "components/enterprise/browser/controller/browser_dm_token_storage.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/profiles/profile_attributes_entry.h"
#include "chrome/browser/profiles/profile_attributes_storage.h"
#include "chrome/browser/profiles/profile_manager.h"
#include "components/policy/core/common/cloud/cloud_policy_core.h"
#include "components/policy/core/common/cloud/cloud_policy_manager.h"
#include "components/policy/core/common/cloud/cloud_policy_store.h"
#include "components/prefs/pref_registry_simple.h"
#include "components/prefs/pref_service.h"
#include "teleport/browser/enterprise/teleport_force_signin.h"
#include "teleport/common/teleport_deployment_config.h"
#include "teleport/common/teleport_domain_migration.h"
#include "teleport/common/teleport_pref_names.h"

namespace teleport {

bool ShouldGateProfile(Profile* profile) {
  if (!profile || profile->IsOffTheRecord() || !profile->IsRegularProfile()) {
    return false;
  }
  return RequireEnrollmentGateEnabled();
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
  return RequireEnrollmentGateEnabled();
}

void RegisterEnrollmentGateLocalStatePrefs(PrefRegistrySimple* registry) {
  registry->RegisterBooleanPref(prefs::kRequireEnrollmentToBrowse, false);
  registry->RegisterStringPref(prefs::kEnrolledDeploymentDomain, std::string());
}

void PersistEnrolledDomain() {
  PrefService* local_state = g_browser_process->local_state();
  if (local_state) {
    local_state->SetString(prefs::kEnrolledDeploymentDomain,
                           DeploymentDomain());
  }
}

void MaybeHandleDomainMigration(Profile* profile) {
  // Only an actually-enrolled profile can be migrated; when not enrolled the
  // gate already blocks, so there is nothing to reset. This also makes the call
  // idempotent: once we reset below, IsEnrolled() is false and this returns.
  if (!IsEnrolled(profile)) {
    return;
  }
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state) {
    return;
  }
  const std::string enrolled =
      local_state->GetString(prefs::kEnrolledDeploymentDomain);
  if (!ShouldRequireReenrollment(enrolled, DeploymentDomain())) {
    return;
  }
  // Management-domain migration: an admin channel changed D on an already-
  // enrolled browser. Reset this profile's enrollment so the gate re-locks and
  // a fresh enrollment runs against the new D — never a half-managed zombie.
  ProfileManager* pm = g_browser_process->profile_manager();
  ProfileAttributesEntry* entry =
      pm ? pm->GetProfileAttributesStorage().GetProfileAttributesWithPath(
               profile->GetPath())
         : nullptr;
  if (entry) {
    entry->SetProfileManagementId(std::string());
  }
  // Clear the cached MACHINE (CBCM) DM token too: it was issued by the OLD D's
  // device-management server and is DEVICE_NOT_FOUND against the new one, so a
  // stale token would keep failing machine policy fetches. Clearing lets CBCM
  // re-register against the new D with the enrollment token.
  policy::BrowserDMTokenStorage::Get()->ClearDMToken(base::DoNothing());
  // Also clear the enterprise-signin identity prefs written by the OIDC
  // registrar (profile display name / email, see teleport_inplace_enrollment_
  // sequence.cc): the migration above resets the management id + DM token but
  // leaves these behind, which would otherwise keep showing a stale managed
  // identity in the profile menu for a now-unenrolled profile.
  if (PrefService* prefs = profile->GetPrefs()) {
    prefs->ClearPref(enterprise_signin::prefs::kProfileUserDisplayName);
    prefs->ClearPref(enterprise_signin::prefs::kProfileUserEmail);
  }
  LOG(ERROR) << "[teleport-migration] deployment domain changed from '"
             << enrolled << "' to '" << DeploymentDomain()
             << "' — profile enrollment + machine DM token reset, "
                "re-enrollment required";
  // teleport: gate ON — re-lock immediately so the now-unmanaged profile can't
  // keep browsing in a running window until the next restart. The throttle
  // only covers http(s) main-frame navigations; the lock is the reliable edge.
  if (RequireEnrollmentGateEnabled() && entry) {
    entry->LockForceSigninProfile(true);
  }
}

std::optional<std::string> PendingDomainMigrationFrom() {
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state) {
    return std::nullopt;
  }
  const std::string enrolled =
      local_state->GetString(prefs::kEnrolledDeploymentDomain);
  if (!ShouldRequireReenrollment(enrolled, DeploymentDomain())) {
    return std::nullopt;
  }
  return enrolled;
}

}  // namespace teleport
