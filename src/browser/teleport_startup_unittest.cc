#include "teleport/browser/teleport_startup.h"

#include <string>

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportStartupTest, BannerIdentifiesOverlayAndMilestone) {
  const std::string banner = StartupBanner();
  EXPECT_NE(banner.find("teleport"), std::string::npos);
  EXPECT_NE(banner.find("M148"), std::string::npos);
}

}  // namespace
}  // namespace teleport
