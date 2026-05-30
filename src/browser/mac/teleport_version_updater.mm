// Provides VersionUpdater::Create() on macOS, backed by the teleport Sparkle
// updater. Compiled into the chrome/browser/ui target (NOT the //teleport
// source_set) so it can include chrome headers without a GN dependency cycle.
#include "chrome/browser/ui/webui/help/version_updater.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ptr_util.h"
#include "base/memory/weak_ptr.h"
#include "teleport/browser/mac/teleport_updater.h"

namespace {

class TeleportVersionUpdater : public VersionUpdater {
 public:
  TeleportVersionUpdater() = default;
  TeleportVersionUpdater(const TeleportVersionUpdater&) = delete;
  TeleportVersionUpdater& operator=(const TeleportVersionUpdater&) = delete;
  ~TeleportVersionUpdater() override = default;

  void CheckForUpdate(StatusCallback status_callback,
                      PromoteCallback promote_callback) override {
    // Sparkle has no per-user/system promotion; keep the promote UI hidden.
    promote_callback.Run(VersionUpdater::PROMOTE_HIDDEN);
    teleport::CheckForUpdateUserInitiated(base::BindRepeating(
        &TeleportVersionUpdater::OnStage, weak_factory_.GetWeakPtr(),
        status_callback));
  }

  void PromoteUpdater() override {}

 private:
  void OnStage(StatusCallback callback,
               teleport::UpdateStage stage,
               int progress,
               const std::u16string& message) {
    Status status = CHECKING;
    int reported_progress = 0;
    switch (stage) {
      case teleport::UpdateStage::kChecking:
        status = CHECKING;
        break;
      case teleport::UpdateStage::kDownloading:
        status = UPDATING;
        reported_progress = progress;
        break;
      case teleport::UpdateStage::kExtracting:
        status = UPDATING;
        break;
      case teleport::UpdateStage::kReadyToRelaunch:
        status = NEARLY_UPDATED;
        break;
      case teleport::UpdateStage::kUpToDate:
        status = UPDATED;
        break;
      case teleport::UpdateStage::kFailed:
        status = FAILED;
        break;
    }
    callback.Run(status, reported_progress, /*rollback=*/false,
                 /*powerwash=*/false, std::string(), /*update_size=*/0,
                 message);
  }

  base::WeakPtrFactory<TeleportVersionUpdater> weak_factory_{this};
};

}  // namespace

std::unique_ptr<VersionUpdater> VersionUpdater::Create(
    content::WebContents* /*web_contents*/) {
  return base::WrapUnique(new TeleportVersionUpdater());
}
