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
}

void CheckForUpdatesNow() {
  StartMacUpdater();
  [g_controller checkForUpdates:nil];
}

}  // namespace teleport
