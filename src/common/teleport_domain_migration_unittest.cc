#include "teleport/common/teleport_domain_migration.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportDomainMigrationTest, NoReenrollWhenNeverEnrolled) {
  // Empty enrolled_domain = not yet enrolled; never trigger re-enrollment.
  EXPECT_FALSE(ShouldRequireReenrollment("", "acme.internal"));
}

TEST(TeleportDomainMigrationTest, NoReenrollWhenDomainUnchanged) {
  EXPECT_FALSE(ShouldRequireReenrollment("acme.internal", "acme.internal"));
}

TEST(TeleportDomainMigrationTest, ReenrollWhenDomainChanged) {
  EXPECT_TRUE(ShouldRequireReenrollment("acme.internal", "beta.internal"));
}

TEST(TeleportDomainMigrationTest, NoReenrollWhenResolvedEmpty) {
  // Defensive: an empty resolved domain (should never happen) must not trigger a
  // destructive re-enroll.
  EXPECT_FALSE(ShouldRequireReenrollment("acme.internal", ""));
}

}  // namespace
}  // namespace teleport
