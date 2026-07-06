#include "teleport/common/teleport_enterprise_enrollment.h"

#include <string_view>

#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"

namespace teleport {
namespace {

// Machine-level CBCM enrollment reads from a single FIXED base bundle id for
// all channels (mirrors Chrome's deliberate "com.google.Chrome no matter what"
// behavior), so one MDM payload enrolls every channel.
TEST(TeleportEnterpriseEnrollmentTest, ManagedPrefsBundleIdIsFixedBaseId) {
  EXPECT_EQ(std::string_view(kManagedPrefsBundleId), "cn.douan.Teleport");
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

namespace teleport {

TEST(TeleportEnterpriseEnrollment, ErrorUrlCarriesFailureCode) {
  EXPECT_EQ(EnrollmentErrorUrl(EnrollmentResult::kRegistrationFailed).query(),
            "error=registration_failed");
  EXPECT_EQ(EnrollmentErrorUrl(EnrollmentResult::kPolicyRejected).query(),
            "error=policy_rejected");
  EXPECT_EQ(EnrollmentErrorUrl(EnrollmentResult::kTimeout).query(),
            "error=timeout");
}

TEST(TeleportEnterpriseEnrollment, ErrorUrlStaysOnEnrollStart) {
  const GURL url = EnrollmentErrorUrl(EnrollmentResult::kPolicyRejected);
  EXPECT_TRUE(url.is_valid());
  EXPECT_EQ(url.path(), "/enroll/start");
  EXPECT_EQ(EnrollmentErrorUrl(EnrollmentResult::kSuccess).query(), "");
}

}  // namespace teleport
