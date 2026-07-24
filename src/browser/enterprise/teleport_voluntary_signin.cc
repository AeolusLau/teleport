// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_voluntary_signin.h"

#include <memory>
#include <utility>

#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/signin/web_signin_interceptor.h"
#include "chrome/browser/ui/browser.h"
#include "chrome/browser/ui/browser_finder.h"
#include "chrome/browser/ui/browser_navigator.h"
#include "chrome/browser/ui/browser_navigator_params.h"
#include "chrome/browser/ui/signin/dice_web_signin_interceptor_delegate.h"
#include "chrome/browser/ui/webui/signin/signin_utils.h"
#include "components/signin/public/identity_manager/account_info.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/web_contents.h"
#include "teleport/browser/enterprise/teleport_oidc_inplace_registrar.h"
#include "teleport/common/teleport_enterprise_enrollment.h"
#include "teleport/common/teleport_enterprise_urls.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/base/page_transition_types.h"
#include "url/gurl.h"

namespace teleport {

namespace {

// Self-owned controller for the voluntary-flow managed-disclosure dialog
// (spike Task 5.3, spec §4.7 — GO). Reuses
// DiceWebSigninInterceptorDelegate::ShowOidcInterceptionDialog, the same
// Browser-anchored "kEnterpriseOIDC" bubble the upstream
// OidcAuthenticationSigninInterceptor shows before NEW-profile creation, to
// disclose management before enrolling the CURRENT profile in place. Deletes
// itself once the dialog fully closes (accept, decline, or the tab/dialog
// being torn down).
class VoluntaryDisclosureController {
 public:
  VoluntaryDisclosureController(content::WebContents* wc,
                                 Profile* profile,
                                 ProfileManagementOidcTokens tokens,
                                 std::string issuer_id,
                                 std::string subject_id,
                                 std::string email)
      : web_contents_(wc->GetWeakPtr()),
        profile_(profile),
        tokens_(std::move(tokens)),
        issuer_id_(std::move(issuer_id)),
        subject_id_(std::move(subject_id)),
        email_(std::move(email)),
        delegate_(std::make_unique<DiceWebSigninInterceptorDelegate>()) {
    // Empty AccountInfo() for both accounts: dasherless OIDC has no GAIA
    // primary account to look up, and kEnterpriseOIDC's WebUI handler never
    // dereferences these (see ManagedUserProfileNoticeHandler::
    // GetProfileInfoValue()'s kEnterpriseOIDC case, which uses static strings
    // and never calls IdentityManager::FindExtendedAccountInfoByAccountId()).
    WebSigninInterceptor::Delegate::BubbleParameters bubble_parameters(
        WebSigninInterceptor::SigninInterceptionType::kEnterpriseOIDC,
        AccountInfo(), AccountInfo(), SkColor(),
        /*show_link_data_option=*/false, /*show_managed_disclaimer=*/true);
    bubble_handle_ = delegate_->ShowOidcInterceptionDialog(
        wc, bubble_parameters,
        base::BindOnce(&VoluntaryDisclosureController::OnUserChoice,
                       weak_factory_.GetWeakPtr()),
        base::BindOnce(&VoluntaryDisclosureController::OnDialogClosed,
                       weak_factory_.GetWeakPtr()),
        base::BindRepeating(&VoluntaryDisclosureController::OnRetry,
                            weak_factory_.GetWeakPtr()));
  }

  VoluntaryDisclosureController(const VoluntaryDisclosureController&) = delete;
  VoluntaryDisclosureController& operator=(
      const VoluntaryDisclosureController&) = delete;

 private:
  // First of the dialog's three callbacks: fired once when the user clicks
  // proceed or cancel. `done_callback` must be run exactly once to report the
  // outcome back to the WebUI; `retry_callback` is unused here (it only
  // surfaces if we signal SIGNIN_TIMEOUT, which we never do — in-place
  // enrollment has no separate retry affordance in this flow).
  void OnUserChoice(signin::SigninChoice choice,
                     signin::SigninChoiceOperationDoneCallback done_callback,
                     signin::SigninChoiceOperationRetryCallback retry_callback) {
    if (choice != signin::SIGNIN_CHOICE_NEW_PROFILE || !web_contents_) {
      // Declined, or the tab closed while the dialog was up: leave the page
      // as-is, no enrollment. SIGNIN_SILENT_SUCCESS makes the WebUI handler
      // invoke the dialog-closed closure immediately with no extra UI state.
      std::move(done_callback)
          .Run(signin::SigninChoiceOperationResult::SIGNIN_SILENT_SUCCESS,
               signin::SigninChoiceErrorType::kNoError);
      return;
    }
    EnrollCurrentProfileInPlace(
        profile_, tokens_, issuer_id_, subject_id_, email_,
        base::BindOnce(&VoluntaryDisclosureController::OnEnrollmentDone,
                       weak_factory_.GetWeakPtr(), std::move(done_callback)));
  }

  void OnEnrollmentDone(signin::SigninChoiceOperationDoneCallback done_callback,
                        EnrollmentResult result) {
    OnVoluntaryEnrollmentDone(web_contents_, result);
    std::move(done_callback)
        .Run(result == EnrollmentResult::kSuccess
                 ? signin::SigninChoiceOperationResult::SIGNIN_CONFIRM_SUCCESS
                 : signin::SigninChoiceOperationResult::SIGNIN_ERROR,
             signin::SigninChoiceErrorType::kNoError);
  }

  // Never invoked in practice: only reachable if we signaled SIGNIN_TIMEOUT
  // above, which we never do. Wired anyway so the 3-callback API is fully
  // satisfied rather than left dangling on a DoNothing().
  void OnRetry() {}

  void OnDialogClosed() { delete this; }

  base::WeakPtr<content::WebContents> web_contents_;
  raw_ptr<Profile> profile_;
  ProfileManagementOidcTokens tokens_;
  std::string issuer_id_;
  std::string subject_id_;
  std::string email_;
  std::unique_ptr<WebSigninInterceptor::Delegate> delegate_;
  std::unique_ptr<ScopedWebSigninInterceptionBubbleHandle> bubble_handle_;
  base::WeakPtrFactory<VoluntaryDisclosureController> weak_factory_{this};
};

}  // namespace

void OpenVoluntaryEnrollmentTab(Browser* browser) {
  if (!browser) {
    return;
  }
  NavigateParams params(browser, GURL(EnterpriseEnrollUrl()),
                        ui::PAGE_TRANSITION_LINK);
  params.disposition = WindowOpenDisposition::NEW_FOREGROUND_TAB;
  Navigate(&params);
}

void OnVoluntaryEnrollmentDone(base::WeakPtr<content::WebContents> web_contents,
                               EnrollmentResult result) {
  if (result == EnrollmentResult::kSuccess) {
    // The tab is already showing the server's success/continue page; nothing
    // to do.
    return;
  }
  if (!web_contents) {
    // Tab was closed before the registrar finished; nothing to navigate.
    return;
  }
  LOG(ERROR) << "[teleport-enroll] voluntary tab enrollment failed (result="
             << static_cast<int>(result) << "); navigating to error page";
  content::NavigationController::LoadURLParams params(
      EnrollmentErrorUrl(result));
  params.transition_type = ui::PAGE_TRANSITION_AUTO_TOPLEVEL;
  web_contents->GetController().LoadURLWithParams(params);
}

void MaybeShowDisclosureThenEnroll(content::WebContents* wc,
                                   Profile* profile,
                                   ProfileManagementOidcTokens tokens,
                                   std::string issuer_id,
                                   std::string subject_id,
                                   std::string email) {
  if (!wc || !chrome::FindBrowserWithTab(wc)) {
    // No Browser to anchor the dialog to. Not the normal picker case (this
    // function is only called from the voluntary/menu-tab branch); a narrow
    // race (e.g. the browser window closing mid-flow) would otherwise
    // null-deref inside OidcEnterpriseSigninInterceptionHandle's constructor
    // (`browser->AsWeakPtr()` on a null Browser*). Fall back to enrolling
    // directly, no dialog, rather than crash.
    LOG(WARNING) << "[teleport-enroll] no Browser for voluntary enrollment "
                    "tab; skipping managed-disclosure dialog";
    EnrollCurrentProfileInPlace(
        profile, tokens, issuer_id, subject_id, email,
        base::BindOnce(&OnVoluntaryEnrollmentDone,
                       wc ? wc->GetWeakPtr()
                          : base::WeakPtr<content::WebContents>()));
    return;
  }
  // Self-owned; deletes itself once the dialog closes (see OnDialogClosed()).
  new VoluntaryDisclosureController(wc, profile, std::move(tokens),
                                     std::move(issuer_id),
                                     std::move(subject_id), std::move(email));
}

}  // namespace teleport
