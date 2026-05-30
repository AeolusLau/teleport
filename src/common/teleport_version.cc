#include "teleport/common/teleport_version.h"

#include "build/build_config.h"

namespace teleport {

std::string ResolveDisplayVersion(const std::string& bundle_short_version,
                                  const std::string& chromium_version) {
  if (bundle_short_version.empty() ||
      bundle_short_version == chromium_version) {
    return "0.0.0-dev";
  }
  return bundle_short_version;
}

#if !BUILDFLAG(IS_MAC)
// Non-mac platforms are a later phase; until they have a real version source,
// return the placeholder rather than leaking the Chromium version.
std::string GetDisplayVersion() {
  return "0.0.0-dev";
}
#endif

}  // namespace teleport
