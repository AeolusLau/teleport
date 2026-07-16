#include "teleport/common/teleport_domain_migration.h"

namespace teleport {

bool ShouldRequireReenrollment(const std::string& enrolled_domain,
                               const std::string& resolved_domain) {
  if (enrolled_domain.empty() || resolved_domain.empty()) {
    return false;
  }
  return enrolled_domain != resolved_domain;
}

}  // namespace teleport
