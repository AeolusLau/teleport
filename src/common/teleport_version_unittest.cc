#include "teleport/common/teleport_version.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportVersionTest, ReturnsBundleVersionWhenStamped) {
  EXPECT_EQ("0.1.3", ResolveDisplayVersion("0.1.3", "148.0.7778.180"));
}

TEST(TeleportVersionTest, FallsBackToDevWhenUnstamped) {
  // Unstamped build: bundle short version still equals the Chromium version.
  EXPECT_EQ("0.0.0-dev",
            ResolveDisplayVersion("148.0.7778.180", "148.0.7778.180"));
}

TEST(TeleportVersionTest, FallsBackToDevWhenEmpty) {
  EXPECT_EQ("0.0.0-dev", ResolveDisplayVersion("", "148.0.7778.180"));
}

}  // namespace
}  // namespace teleport
