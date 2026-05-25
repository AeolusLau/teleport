#include "teleport/browser/teleport_startup.h"

#include "base/logging.h"

namespace teleport {

const char* StartupBanner() {
  return "[teleport] 闪现 overlay active (M148)";
}

void LogStartupBanner() {
  LOG(INFO) << StartupBanner();
}

}  // namespace teleport
