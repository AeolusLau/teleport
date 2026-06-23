#include "teleport/common/teleport_enrollment_gate_logic.h"

#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"

namespace teleport {
namespace {

TEST(TeleportEnrollmentGateLogicTest, IsEnrollmentFlowUrl) {
  // All subhosts under the managed domain (dev=fairyland.io) are allowed.
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://enroll.teleport.fairyland.io/enroll")));
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://dadou.fairyland.io/authorize?x=1")));
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://accounts.fairyland.io/login")));
  // The apex domain itself is also allowed (exercises the host==apex branch).
  EXPECT_TRUE(IsEnrollmentFlowUrl(GURL("https://fairyland.io/path")));
  // Non-managed domains are not allowed.
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://example.com/")));
  // Domain-suffix spoofing attacks are rejected (host must truly end with the suffix).
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("https://fairyland.io.evil.com/")));
  // Non-https is not allowed.
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("http://enroll.teleport.fairyland.io/")));
  // Invalid URLs are not allowed.
  EXPECT_FALSE(IsEnrollmentFlowUrl(GURL("not a url")));
}

TEST(TeleportEnrollmentGateLogicTest, ShouldBlockNavigation) {
  const GURL web("https://example.com/");
  const GURL enroll("https://enroll.teleport.fairyland.io/enroll");
  const GURL internal("chrome://settings/");

  // Gate active + not enrolled + main frame + regular web URL → block.
  EXPECT_TRUE(ShouldBlockNavigation(true, false, true, web));
  // Enrollment flow URL → allow.
  EXPECT_FALSE(ShouldBlockNavigation(true, false, true, enroll));
  // chrome:// and other internal pages → allow (only http/https is intercepted).
  EXPECT_FALSE(ShouldBlockNavigation(true, false, true, internal));
  // Already enrolled → allow.
  EXPECT_FALSE(ShouldBlockNavigation(true, true, true, web));
  // Gate not active (policy off / non-regular profile) → allow.
  EXPECT_FALSE(ShouldBlockNavigation(false, false, true, web));
  // Sub-frame → allow (only main-frame navigations are intercepted).
  EXPECT_FALSE(ShouldBlockNavigation(true, false, false, web));
}

}  // namespace
}  // namespace teleport
