#include "teleport/common/teleport_enrollment_gate_logic.h"

#include <string>
#include <string_view>
#include <vector>

#include "teleport/common/teleport_enterprise_urls.h"
#include "url/gurl.h"

namespace teleport {

bool IsEnrollmentFlowUrl(const GURL& url) {
  if (!url.is_valid() || !url.SchemeIs("https")) {
    return false;
  }
  const std::string_view host = url.host();
  for (const std::string& suffix : EnterpriseEnrollmentDomainSuffixes()) {
    // host == apex (strip leading dot) or host ends with ".<domain>".
    std::string_view apex(suffix);
    apex.remove_prefix(1);  // strip leading '.'
    if (host == apex ||
        (host.size() > suffix.size() &&
         host.substr(host.size() - suffix.size()) == suffix)) {
      return true;
    }
  }
  return false;
}

bool ShouldBlockNavigation(bool should_gate,
                           bool is_enrolled,
                           bool is_main_frame,
                           const GURL& url) {
  if (!should_gate || is_enrolled) {
    return false;
  }
  if (!is_main_frame) {
    return false;
  }
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return false;  // Pass through chrome://, about:, and other internal pages.
  }
  return !IsEnrollmentFlowUrl(url);
}

}  // namespace teleport
