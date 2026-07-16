#include "teleport/browser/teleport_deployment_level4.h"

#include <cstdint>
#include <vector>

#include "base/containers/span.h"
#include "base/functional/bind.h"
#include "base/time/time.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/lifetime/application_lifetime.h"
#include "components/policy/core/common/cloud/cloud_policy_constants.h"
#include "components/prefs/pref_registry_simple.h"
#include "components/prefs/pref_service.h"
#include "teleport/common/teleport_enroll_logic.h"
#include "teleport/common/teleport_deployment_config.h"
#include "teleport/common/teleport_pref_names.h"
#include "teleport/common/teleport_server_identity.h"
#include "teleport/common/teleport_server_identity_entry.h"

namespace teleport {

namespace {

// Persist a verified entry to the Local State kServerIdentityEntry pref. Runs on
// the UI thread (the enroll handler calls it after an explicit confirm click).
// Registered as the enroll-page writer seam so the WebUI target never reaches
// into g_browser_process itself.
bool WriteEntryToLocalState(const ServerIdentityEntry& entry) {
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state) {
    return false;
  }
  local_state->SetDict(prefs::kServerIdentityEntry,
                       EncodeServerIdentityEntry(entry));
  return true;
}

// Clear the level-4 kServerIdentityEntry pref (enroll page "unbind"). D falls
// back to the baked default on next start. Registered as the clearer seam.
bool ClearEntryFromLocalState() {
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state) {
    return false;
  }
  local_state->ClearPref(prefs::kServerIdentityEntry);
  return true;
}

}  // namespace

std::optional<std::string> ReadVerifiedUserAcceptedDomain() {
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state) {
    return std::nullopt;
  }
  std::optional<ServerIdentityEntry> entry =
      DecodeServerIdentityEntry(local_state->GetDict(prefs::kServerIdentityEntry));
  if (!entry) {
    return std::nullopt;
  }
  // Baked policy-verification root key (DER SubjectPublicKeyInfo), the same trust
  // anchor the policy chain uses. Injected here rather than baked into the leaf.
  const std::string root_key = policy::GetPolicyVerificationKey();
  if (!VerifyServerIdentity(entry->signed_bytes, entry->signature,
                            base::as_byte_span(root_key), entry->domain,
                            base::Time::Now())) {
    return std::nullopt;
  }
  return NormalizeDeploymentDomain(entry->domain);
}

void RegisterServerIdentityLevel4(PrefRegistrySimple* registry) {
  registry->RegisterDictionaryPref(prefs::kServerIdentityEntry);
  SetUserAcceptedDomainReader(
      base::BindRepeating(&ReadVerifiedUserAcceptedDomain));
  // The enroll page (chrome://enroll) persists a verified entry through this
  // seam so its WebUI target stays free of g_browser_process / chrome/browser.
  SetServerIdentityEntryWriter(base::BindRepeating(&WriteEntryToLocalState));
  // The enroll page's "unbind" button clears the entry through this seam.
  SetServerIdentityEntryClearer(base::BindRepeating(&ClearEntryFromLocalState));
  // The enroll page's "restart" button relaunches through this seam
  // (chrome::AttemptRestart lives in //chrome/browser).
  SetRelaunchHandler(base::BindRepeating(&chrome::AttemptRestart));
}

}  // namespace teleport
