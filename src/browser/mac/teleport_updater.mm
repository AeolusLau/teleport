#import "teleport/browser/mac/teleport_updater.h"

#import <Foundation/Foundation.h>
#import <Sparkle/Sparkle.h>

#include <string>

#include "teleport/common/teleport_feed_url.h"

namespace teleport {
namespace {

// Global objects under ARC are __strong by default, so this retains.
SPUStandardUpdaterController* g_controller = nil;

bool FeedIsSecure() {
  NSString* feed =
      [[NSBundle mainBundle] objectForInfoDictionaryKey:@"SUFeedURL"];
  return feed != nil && IsSecureFeedUrl(std::string([feed UTF8String]));
}

}  // namespace

void StartMacUpdater() {
  if (g_controller != nil || !FeedIsSecure()) {
    return;
  }
  g_controller = [[SPUStandardUpdaterController alloc]
      initWithStartingUpdater:YES
              updaterDelegate:nil
           userDriverDelegate:nil];
  // Kick off a silent check now, on top of Sparkle's hourly scheduled check
  // (SUScheduledCheckInterval). The scheduler only fires when the interval has
  // elapsed since the last check, so without this a relaunch within the hour
  // would not check at all. checkForUpdatesInBackground shows no UI and honors
  // SUEnableAutomaticChecks (set in Info.plist at packaging time).
  [g_controller.updater checkForUpdatesInBackground];
}

void CheckForUpdatesNow() {
  StartMacUpdater();
  [g_controller checkForUpdates:nil];
}

}  // namespace teleport
