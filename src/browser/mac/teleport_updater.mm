#import "teleport/browser/mac/teleport_updater.h"

#import <Foundation/Foundation.h>
#import <Sparkle/Sparkle.h>

#include <string>

#include "base/no_destructor.h"
#include "teleport/browser/mac/teleport_sparkle_user_driver.h"
#include "teleport/common/teleport_feed_url.h"

namespace teleport {
namespace {

bool FeedIsSecure() {
  NSString* feed =
      [[NSBundle mainBundle] objectForInfoDictionaryKey:@"SUFeedURL"];
  return feed != nil && IsSecureFeedUrl(std::string([feed UTF8String]));
}

// Single Sparkle updater + headless user driver shared by background and
// user-initiated checks. Lives for the process lifetime.
class SparkleUpdater {
 public:
  static SparkleUpdater& Get() {
    static base::NoDestructor<SparkleUpdater> instance;
    return *instance;
  }

  void Start() {
    if (started_ || !FeedIsSecure()) {
      return;
    }
    driver_ = [[TeleportSparkleUserDriver alloc] init];
    if (ready_callback_) {
      [driver_ setReadyCallback:ready_callback_];
    }
    updater_ = [[SPUUpdater alloc] initWithHostBundle:NSBundle.mainBundle
                                    applicationBundle:NSBundle.mainBundle
                                           userDriver:driver_
                                             delegate:nil];
    NSError* error = nil;
    if (![updater_ startUpdater:&error]) {
      updater_ = nil;
      driver_ = nil;
      return;
    }
    started_ = true;
    // Kick a silent check now, on top of Sparkle's scheduled interval.
    [driver_ setStatusSink:teleport::UpdateStatusSink()];
    [updater_ checkForUpdatesInBackground];
  }

  void CheckUserInitiated(UpdateStatusSink sink) {
    Start();
    if (!started_) {
      return;
    }
    [driver_ setStatusSink:std::move(sink)];
    [updater_ checkForUpdates];
  }

  bool InstallPendingAndRelaunch() {
    if (driver_ && [driver_ hasPendingUpdate]) {
      [driver_ installPendingUpdateAndRelaunch];
      return true;
    }
    return false;
  }

  void SetReadyCallback(UpdateReadyCallback callback) {
    ready_callback_ = std::move(callback);
    if (driver_) {
      [driver_ setReadyCallback:ready_callback_];
    }
  }

 private:
  friend class base::NoDestructor<SparkleUpdater>;
  SparkleUpdater() = default;

  bool started_ = false;
  // Explicitly __strong: this C++ class (held by a NoDestructor singleton) must
  // retain the updater and driver for the process lifetime so the background
  // Sparkle session and the held relaunch reply stay alive.
  SPUUpdater* __strong updater_ = nil;
  TeleportSparkleUserDriver* __strong driver_ = nil;
  UpdateReadyCallback ready_callback_;
};

}  // namespace

void StartMacUpdater() {
  SparkleUpdater::Get().Start();
}

void CheckForUpdatesNow() {
  SparkleUpdater::Get().CheckUserInitiated(teleport::UpdateStatusSink());
}

void CheckForUpdateUserInitiated(UpdateStatusSink sink) {
  SparkleUpdater::Get().CheckUserInitiated(std::move(sink));
}

bool InstallPendingUpdateAndRelaunchIfReady() {
  return SparkleUpdater::Get().InstallPendingAndRelaunch();
}

void SetUpdateReadyCallback(UpdateReadyCallback callback) {
  SparkleUpdater::Get().SetReadyCallback(std::move(callback));
}

}  // namespace teleport
