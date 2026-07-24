// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_VOLUNTARY_SIGNIN_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_VOLUNTARY_SIGNIN_H_

#include <string>

#include "base/memory/weak_ptr.h"
#include "chrome/browser/profiles/profile_attributes_entry.h"  // ProfileManagementOidcTokens
#include "teleport/common/teleport_enterprise_enrollment.h"

class Browser;
class Profile;

namespace content {
class WebContents;
}

namespace teleport {

// Opens the Teleport enrollment start page (EnterpriseEnrollUrl()) in a new
// foreground tab of `browser`. The OIDC capture throttle then completes in-place
// enrollment (with the upstream managed-disclosure dialog, §4.7). Voluntary
// (gate-OFF) sign-in entry from the profile menu.
void OpenVoluntaryEnrollmentTab(Browser* browser);

// Enrollment-done callback for the voluntary (menu → enroll tab) flow. Unlike
// the ProfilePicker enrollment step, this flow never attaches an
// EnrollmentDoneUserData to the tab's WebContents, so without a fallback a
// registrar failure would give the user zero feedback. On failure, navigates
// `web_contents` to the enrollment error page (EnrollmentErrorUrl()); on
// success this is a no-op, since the tab is already showing the server's
// success/continue page. `web_contents` is weak so a tab closed before the
// registrar finishes is handled safely (no-op).
void OnVoluntaryEnrollmentDone(base::WeakPtr<content::WebContents> web_contents,
                               EnrollmentResult result);

// Voluntary-flow-only (§4.7 spike outcome: GO). Before enrolling `profile` in
// place from the captured OIDC tokens, shows the upstream managed-disclosure
// dialog — DiceWebSigninInterceptorDelegate::ShowOidcInterceptionDialog, the
// same "your organization will manage this profile" bubble the stock
// OidcAuthenticationSigninInterceptor shows before NEW-profile creation —
// anchored to the Browser hosting `wc`. The bubble is built with an empty
// AccountInfo() (dasherless has no primary account) and
// SigninInterceptionType::kEnterpriseOIDC, which the WebUI handler renders
// with zero IdentityManager account lookups (see
// ManagedUserProfileNoticeHandler::GetProfileInfoValue()'s kEnterpriseOIDC
// case). On accept, calls EnrollCurrentProfileInPlace(...) and threads
// OnVoluntaryEnrollmentDone as the done-callback; on cancel/decline, does
// nothing further, leaving `wc` on its current page, unenrolled. Falls back to
// enrolling with no dialog if `wc` has no Browser to anchor to (would
// otherwise null-deref inside the delegate) — narrow race, not the normal
// picker "no Browser" case, which never reaches this function.
void MaybeShowDisclosureThenEnroll(content::WebContents* wc,
                                   Profile* profile,
                                   ProfileManagementOidcTokens tokens,
                                   std::string issuer_id,
                                   std::string subject_id,
                                   std::string email);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_VOLUNTARY_SIGNIN_H_
