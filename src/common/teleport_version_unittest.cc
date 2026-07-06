#include "teleport/common/teleport_version.h"

#include <string>

#include "components/version_info/version_info.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// The display version is the baked product version (chrome/VERSION is
// generated from TELEPORT_VERSION at overlay time) — never the engine version.
TEST(TeleportVersionTest, DisplaysBakedProductVersion) {
  const std::string version = GetDisplayVersion();
  EXPECT_EQ(version.rfind(std::string(version_info::GetVersionNumber()), 0), 0u)
      << version;
  EXPECT_EQ(version.find("7778"), std::string::npos) << version;
}

TEST(TeleportVersionTest, DevSuffixTracksOfficialBuildFlag) {
  const std::string expected =
      std::string(version_info::GetVersionNumber()) +
      (version_info::IsOfficialBuild() ? "" : "-dev");
  EXPECT_EQ(expected, GetDisplayVersion());
}

}  // namespace
}  // namespace teleport
