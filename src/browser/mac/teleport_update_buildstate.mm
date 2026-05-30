#include "teleport/browser/mac/teleport_update_buildstate.h"

#include <optional>
#include <string>

#include "base/functional/bind.h"
#include "base/version.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/upgrade_detector/build_state.h"
#include "teleport/browser/mac/teleport_updater.h"

namespace teleport {
namespace {

void OnUpdateReady(const std::string& version) {
  if (!g_browser_process) {
    return;
  }
  BuildState* build_state = g_browser_process->GetBuildState();
  if (!build_state) {
    return;
  }
  base::Version parsed(version);
  build_state->SetUpdate(
      BuildState::UpdateType::kNormalUpdate,
      parsed.IsValid() ? parsed : base::Version(), std::nullopt);
}

}  // namespace

void InstallUpdateReadyBuildStateBridge() {
  SetUpdateReadyCallback(base::BindRepeating(&OnUpdateReady));
}

}  // namespace teleport
