#ifndef TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_

namespace teleport {

// Starts the Sparkle updater once on the main thread. Reads SUFeedURL /
// SUPublicEDKey from the main bundle (injected at packaging time). No-op if
// the feed is missing or not https. Idempotent.
void StartMacUpdater();

// User-initiated check, for the "Check for Updates…" menu item.
void CheckForUpdatesNow();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_UPDATER_H_
