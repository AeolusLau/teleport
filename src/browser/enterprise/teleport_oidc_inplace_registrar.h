#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_OIDC_INPLACE_REGISTRAR_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_OIDC_INPLACE_REGISTRAR_H_

#include <string>

#include "base/functional/callback_forward.h"

class Profile;
struct ProfileManagementOidcTokens;

namespace teleport {

// Registers `profile` in place as a dasherless OIDC-managed profile from
// captured OIDC tokens, then fetches its user policy. Runs `on_done` once the
// profile's ProfileCloudPolicyManager store has_policy() is true (or drops it
// on failure). Self-owned: the helper deletes itself when finished. Must be
// called on the UI thread.
void EnrollCurrentProfileInPlace(
    Profile* profile,
    const ProfileManagementOidcTokens& oidc_tokens,
    const std::string& issuer_id,
    const std::string& subject_id,
    const std::string& email,
    base::OnceClosure on_done);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_OIDC_INPLACE_REGISTRAR_H_
