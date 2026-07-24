// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/common/teleport_signin_entry_logic.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportSigninEntryLogicTest, ShownForUnenrolledRegularNonWebApp) {
  EXPECT_TRUE(ShouldShowTeleportSigninEntry(
      /*is_enrolled=*/false, /*is_regular_profile=*/true, /*is_web_app=*/false));
}

TEST(TeleportSigninEntryLogicTest, HiddenWhenEnrolled) {
  EXPECT_FALSE(ShouldShowTeleportSigninEntry(true, true, false));
}

TEST(TeleportSigninEntryLogicTest, HiddenForNonRegularProfile) {
  EXPECT_FALSE(ShouldShowTeleportSigninEntry(false, false, false));
}

TEST(TeleportSigninEntryLogicTest, HiddenInWebApp) {
  EXPECT_FALSE(ShouldShowTeleportSigninEntry(false, true, true));
}

}  // namespace
}  // namespace teleport
