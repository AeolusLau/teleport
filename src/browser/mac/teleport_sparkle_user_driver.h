#ifndef TELEPORT_BROWSER_MAC_TELEPORT_SPARKLE_USER_DRIVER_H_
#define TELEPORT_BROWSER_MAC_TELEPORT_SPARKLE_USER_DRIVER_H_

#import <Foundation/Foundation.h>
#import <Sparkle/Sparkle.h>

#include "teleport/browser/mac/teleport_updater.h"

// A headless SPUUserDriver: it never shows Sparkle's own windows. Instead it
// auto-advances the update (download -> extract -> stage), reports progress to
// an optional status sink (the About page), fires a "ready" callback to drive
// the chrome upgrade indicator, and holds the final install+relaunch reply so
// it can be triggered later from chrome::AttemptRelaunch().
@interface TeleportSparkleUserDriver : NSObject <SPUUserDriver>

// Set/cleared by the updater for each user-initiated check. May be null for
// silent background checks.
- (void)setStatusSink:(teleport::UpdateStatusSink)sink;

// Set once at startup.
- (void)setReadyCallback:(teleport::UpdateReadyCallback)callback;

// True if an update is staged and the install+relaunch reply is held.
- (BOOL)hasPendingUpdate;

// Invokes the held reply to install + relaunch. No-op if none pending.
- (void)installPendingUpdateAndRelaunch;

@end

#endif  // TELEPORT_BROWSER_MAC_TELEPORT_SPARKLE_USER_DRIVER_H_
