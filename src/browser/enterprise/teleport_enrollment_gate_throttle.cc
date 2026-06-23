#include "teleport/browser/enterprise/teleport_enrollment_gate_throttle.h"

#include <memory>

#include "base/functional/bind.h"
#include "base/location.h"
#include "base/memory/weak_ptr.h"
#include "base/task/sequenced_task_runner.h"
#include "chrome/browser/profiles/profile.h"
#include "content/public/browser/navigation_controller.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/navigation_throttle_registry.h"
#include "content/public/browser/web_contents.h"
#include "teleport/browser/enterprise/teleport_enrollment_gate.h"
#include "teleport/common/teleport_enrollment_gate_logic.h"
#include "teleport/common/teleport_enterprise_urls.h"
#include "ui/base/page_transition_types.h"
#include "url/gurl.h"

namespace teleport {

// static
void TeleportEnrollmentGateThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  registry.AddThrottle(
      std::make_unique<TeleportEnrollmentGateThrottle>(registry));
}

TeleportEnrollmentGateThrottle::TeleportEnrollmentGateThrottle(
    content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

TeleportEnrollmentGateThrottle::~TeleportEnrollmentGateThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
TeleportEnrollmentGateThrottle::WillStartRequest() {
  return CheckRequest();
}

content::NavigationThrottle::ThrottleCheckResult
TeleportEnrollmentGateThrottle::WillRedirectRequest() {
  return CheckRequest();
}

const char* TeleportEnrollmentGateThrottle::GetNameForLogging() {
  return "TeleportEnrollmentGateThrottle";
}

content::NavigationThrottle::ThrottleCheckResult
TeleportEnrollmentGateThrottle::CheckRequest() {
  content::NavigationHandle* handle = navigation_handle();
  content::WebContents* web_contents = handle->GetWebContents();
  if (!web_contents) {
    return PROCEED;
  }
  Profile* profile =
      Profile::FromBrowserContext(web_contents->GetBrowserContext());

  if (!ShouldBlockNavigation(ShouldGateProfile(profile), IsEnrolled(profile),
                             handle->IsInPrimaryMainFrame(), handle->GetURL())) {
    return PROCEED;
  }

  // Starting a navigation synchronously inside a NavigationThrottle callback is
  // an anti-pattern, so post it. Returning CANCEL_AND_IGNORE destroys this
  // throttle before the task runs, so bind the task to the WebContents (not
  // `this`): it becomes a no-op if the tab is gone before it runs.
  content::NavigationController::LoadURLParams params(
      (GURL(EnterpriseEnrollUrl())));
  params.transition_type = ui::PAGE_TRANSITION_AUTO_TOPLEVEL;
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(
          [](base::WeakPtr<content::WebContents> web_contents,
             content::NavigationController::LoadURLParams params) {
            if (web_contents) {
              web_contents->GetController().LoadURLWithParams(params);
            }
          },
          web_contents->GetWeakPtr(), std::move(params)));
  return ThrottleCheckResult(CANCEL_AND_IGNORE);
}

}  // namespace teleport
