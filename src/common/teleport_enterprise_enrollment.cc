#include "teleport/common/teleport_enterprise_enrollment.h"

#include <string>
#include <string_view>

#include "teleport/common/teleport_enterprise_urls.h"
#include "url/gurl.h"

namespace teleport {

GURL EnrollmentErrorUrl(EnrollmentResult result) {
  std::string_view code;
  switch (result) {
    case EnrollmentResult::kSuccess:
      return GURL(EnterpriseEnrollUrl());
    case EnrollmentResult::kRegistrationFailed:
      code = "registration_failed";
      break;
    case EnrollmentResult::kPolicyRejected:
      code = "policy_rejected";
      break;
    case EnrollmentResult::kTimeout:
      code = "timeout";
      break;
  }
  return GURL(EnterpriseEnrollUrl() + "?error=" + std::string(code));
}

}  // namespace teleport
