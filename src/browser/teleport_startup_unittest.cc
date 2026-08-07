#include "teleport/browser/teleport_startup.h"

#include <string>

#include "components/version_info/teleport_engine_version.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Regression guard for staleness: the banner's milestone must be *derived*
// from the same single source of truth (CHROMIUM_VERSION, baked into
// TELEPORT_ENGINE_VERSION_MAJOR by generate_version.py) that the UA/UA-CH
// surface already uses, not a literal restated here. Asserting a hardcoded
// milestone number would recreate the exact staleness this test exists to
// catch across future baseline upgrades.
TEST(TeleportStartupTest, BannerIdentifiesOverlayAndMilestone) {
  const std::string banner = StartupBanner();
  EXPECT_NE(banner.find("teleport"), std::string::npos);
  EXPECT_NE(banner.find(TELEPORT_ENGINE_VERSION_MAJOR), std::string::npos);
}

}  // namespace
}  // namespace teleport
