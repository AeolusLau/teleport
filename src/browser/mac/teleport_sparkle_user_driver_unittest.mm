#import "teleport/browser/mac/teleport_sparkle_user_driver.h"

#include <string>

#include "base/test/bind.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Captures the two channels the driver feeds: the About-page status sink and
// the "ready" callback that lights the toolbar/menu upgrade badge.
struct Sinks {
  int ready_calls = 0;
  std::string ready_version = "<unset>";
  int stage_calls = 0;
  UpdateStage last_stage = UpdateStage::kUpToDate;
};

TeleportSparkleUserDriver* MakeDriver(Sinks* sinks) {
  TeleportSparkleUserDriver* driver = [[TeleportSparkleUserDriver alloc] init];
  [driver setReadyCallback:base::BindLambdaForTesting(
                               [sinks](const std::string& version) {
                                 ++sinks->ready_calls;
                                 sinks->ready_version = version;
                               })];
  [driver setStatusSink:base::BindLambdaForTesting(
                            [sinks](UpdateStage stage, int /*progress*/,
                                    const std::u16string& /*message*/) {
                              ++sinks->stage_calls;
                              sinks->last_stage = stage;
                            })];
  return driver;
}

// Re-surfacing a staged update (About page reopened, or an update staged in a
// prior session) must light the toolbar/menu badge, not just the About page.
TEST(TeleportSparkleUserDriverTest, ResurfaceStagedStateFiresReadyCallback) {
  Sinks sinks;
  TeleportSparkleUserDriver* driver = MakeDriver(&sinks);

  [driver resurfaceStagedStateToSink];

  // About-page sink sees the staged state.
  EXPECT_EQ(sinks.last_stage, UpdateStage::kReadyToRelaunch);
  // And the menu bridge fires so the app-menu upgrade badge lights up.
  EXPECT_EQ(sinks.ready_calls, 1);
}

// Sparkle resuming an already-staged update jumps straight to "ready to
// relaunch" without re-emitting showUpdateFoundWithAppcastItem, so the internal
// pending-version is empty. The menu bridge must still fire in that case.
TEST(TeleportSparkleUserDriverTest,
     ReadyToRelaunchFiresCallbackWithoutPriorAppcastFound) {
  Sinks sinks;
  TeleportSparkleUserDriver* driver = MakeDriver(&sinks);

  [driver showReadyToInstallAndRelaunch:^(SPUUserUpdateChoice /*choice*/){
  }];

  EXPECT_EQ(sinks.last_stage, UpdateStage::kReadyToRelaunch);
  EXPECT_EQ(sinks.ready_calls, 1);
}

}  // namespace
}  // namespace teleport
