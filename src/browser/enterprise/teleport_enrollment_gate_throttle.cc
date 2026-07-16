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
#include "net/http/http_response_headers.h"
#include "teleport/common/teleport_deployment_config.h"
#include "teleport/common/teleport_enterprise_urls.h"
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
  // A redirect RESPONSE (from the previous, allowed enrollment-flow host) may
  // carry the allow-hosts header that opens the redirect target — read it before
  // deciding whether to block the new URL.
  MaybeInjectAllowedHostsFromResponse();
  return CheckRequest();
}

content::NavigationThrottle::ThrottleCheckResult
TeleportEnrollmentGateThrottle::WillProcessResponse() {
  // The enroll/resume page (on teleport.<D>, allowed) carries the per-tenant OP
  // host in its response header; inject it here so the subsequent client-side
  // navigation to <slug>.<D>/authorize is allowed instead of blocked.
  MaybeInjectAllowedHostsFromResponse();
  return PROCEED;
}

void TeleportEnrollmentGateThrottle::MaybeInjectAllowedHostsFromResponse() {
  content::NavigationHandle* handle = navigation_handle();
  const net::HttpResponseHeaders* headers = handle->GetResponseHeaders();
  if (!headers) {
    return;
  }
  // The security control is ParseInjectableEnrollmentHosts, which bounds every
  // injected host to a STRICT SUBDOMAIN of the deployment domain D — so a
  // response can only ever widen the whitelist to another host under the same
  // trusted D (never an external host). This is why we can read the header on a
  // redirect response too, where handle->GetURL() is already the (still-blocked)
  // redirect TARGET rather than the enrollment host that issued the redirect.
  // The gate itself only ever lets the browser reach enrollment-flow hosts, so
  // in practice the header only arrives from teleport.<D> / accounts.<D>.
  const std::string suffix = DeploymentEnrollmentDomainSuffix();
  size_t iter = 0;
  std::string value;
  while (headers->EnumerateHeader(&iter, "X-Teleport-Enroll-Allow-Hosts",
                                  &value)) {
    for (const std::string& host :
         ParseInjectableEnrollmentHosts(value, suffix)) {
      AddInjectedEnrollmentHost(host);
    }
  }
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

  // §4.5: if an admin channel changed the deployment domain on an already-
  // enrolled profile, reset its enrollment here (before we read IsEnrolled
  // below) so the gate re-locks instead of letting it browse half-managed.
  MaybeHandleDomainMigration(profile);

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
