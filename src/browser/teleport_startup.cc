#include "teleport/browser/teleport_startup.h"

#include <string>

#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/strings/stringprintf.h"
#include "components/version_info/teleport_engine_version.h"

namespace teleport {

const char* StartupBanner() {
  // Derived (not restated) from CHROMIUM_VERSION via the generated engine
  // header, the same single source of truth the UA/UA-CH surface uses. This
  // makes the banner's milestone structurally incapable of going stale across
  // future baseline upgrades; see teleport_startup_unittest.cc.
  static const base::NoDestructor<std::string> banner(base::StringPrintf(
      "[teleport] 闪现 overlay active (M%s)", TELEPORT_ENGINE_VERSION_MAJOR));
  return banner->c_str();
}

void LogStartupBanner() {
  LOG(INFO) << StartupBanner();
}

}  // namespace teleport
