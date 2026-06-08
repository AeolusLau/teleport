#include "teleport/common/teleport_enterprise_enrollment.h"

#include <string_view>

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Machine-level CBCM enrollment reads from a single FIXED base bundle id for
// all channels (mirrors Chrome's deliberate "com.google.Chrome no matter what"
// behavior), so one MDM payload enrolls every channel.
TEST(TeleportEnterpriseEnrollmentTest, ManagedPrefsBundleIdIsFixedBaseId) {
  EXPECT_EQ(std::string_view(kManagedPrefsBundleId), "com.beansec.Teleport");
}

TEST(TeleportEnterpriseEnrollmentTest,
     EnrollmentFilePathsUnderLibraryTeleport) {
  EXPECT_EQ(std::string_view(kEnrollmentTokenFilePath),
            "/Library/Teleport/CloudManagementEnrollmentToken");
  EXPECT_EQ(std::string_view(kEnrollmentOptionsFilePath),
            "/Library/Teleport/CloudManagementEnrollmentOptions");
}

TEST(TeleportEnterpriseEnrollmentTest, DmTokenStorageDirIsChannelAgnostic) {
  EXPECT_EQ(std::string_view(kDmTokenStorageDir), "Teleport/Cloud Enrollment/");
}

}  // namespace
}  // namespace teleport
