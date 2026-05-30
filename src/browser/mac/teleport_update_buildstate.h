#ifndef TELEPORT_BROWSER_MAC_TELEPORT_UPDATE_BUILDSTATE_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_UPDATE_BUILDSTATE_H_

namespace teleport {

// Registers the "update ready" callback so a staged Sparkle update lights the
// toolbar app-menu upgrade indicator (via BuildState). Call once at startup,
// before StartMacUpdater(). Compiled into chrome/browser so it can touch
// BuildState without a GN dependency cycle on //teleport.
void InstallUpdateReadyBuildStateBridge();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_UPDATE_BUILDSTATE_H_
