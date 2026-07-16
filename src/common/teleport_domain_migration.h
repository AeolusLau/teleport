#ifndef TELEPORT_COMMON_TELEPORT_DOMAIN_MIGRATION_H_
#define TELEPORT_COMMON_TELEPORT_DOMAIN_MIGRATION_H_

#include <string>

namespace teleport {

// Pure decision: true iff the device was previously enrolled against a domain
// (enrolled_domain non-empty) and the freshly resolved domain differs from it
// (resolved_domain non-empty and != enrolled_domain). An empty resolved_domain
// is treated defensively as "no change" so a resolution glitch never triggers a
// destructive re-enrollment.
bool ShouldRequireReenrollment(const std::string& enrolled_domain,
                               const std::string& resolved_domain);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_DOMAIN_MIGRATION_H_
