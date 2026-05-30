#ifndef TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_

#include <string>

#include "base/functional/callback.h"

namespace teleport {

// Coarse update lifecycle stages surfaced to the About page UI.
enum class UpdateStage {
  kChecking,
  kDownloading,      // `progress` is 0..100
  kExtracting,
  kReadyToRelaunch,  // staged; awaiting install + relaunch
  kUpToDate,
  kFailed,           // `message` carries an error string
};

// Reports progress of a user-initiated check to the About page. `progress` is
// meaningful only for kDownloading; `message` only for kFailed.
using UpdateStatusSink =
    base::RepeatingCallback<void(UpdateStage stage,
                                 int progress,
                                 const std::u16string& message)>;

// Fired once when an update finishes staging and is ready to install on
// relaunch (background OR user-initiated). `version` is the appcast
// CFBundleVersion string. Used by the chrome-side bridge to light the
// toolbar/menu upgrade indicator.
using UpdateReadyCallback =
    base::RepeatingCallback<void(const std::string& version)>;

// Starts the Sparkle updater once on the main thread and kicks a silent
// background check. Reads SUFeedURL / SUPublicEDKey from the main bundle
// (injected at packaging time). No-op if the feed is missing or not https.
// Idempotent.
void StartMacUpdater();

// User-initiated check, for the legacy "Check for Updates…" menu item.
void CheckForUpdatesNow();

// Begins a user-initiated check that reports progress to `sink` (the About
// page). Starts the updater if needed. No-op if the feed is not secure.
void CheckForUpdateUserInitiated(UpdateStatusSink sink);

// If a staged update is ready, ask Sparkle to install it and relaunch now,
// returning true. Otherwise return false (the caller should do a normal
// relaunch). Must be called on the main thread.
bool InstallPendingUpdateAndRelaunchIfReady();

// Registers the callback fired when an update becomes ready. Set once at
// startup by the chrome-side BuildState bridge.
void SetUpdateReadyCallback(UpdateReadyCallback callback);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
