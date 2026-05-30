// No-op updater implementation for builds with the Sparkle updater disabled
// (teleport_enable_updater=false, e.g. dev). Lets chrome call the updater entry
// points unconditionally without linking Sparkle.
#include "teleport/browser/mac/teleport_updater.h"

namespace teleport {

void StartMacUpdater() {}
void CheckForUpdatesNow() {}
void CheckForUpdateUserInitiated(UpdateStatusSink) {}
bool InstallPendingUpdateAndRelaunchIfReady() {
  return false;
}
void SetUpdateReadyCallback(UpdateReadyCallback) {}

}  // namespace teleport
