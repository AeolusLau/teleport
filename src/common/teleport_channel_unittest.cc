#include "teleport/common/teleport_channel.h"

#include "components/version_info/channel.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportChannelTest, MapsCanaryToCanary) {
  EXPECT_EQ(version_info::Channel::CANARY, ChannelFromName("canary"));
}

TEST(TeleportChannelTest, MapsBetaToBeta) {
  EXPECT_EQ(version_info::Channel::BETA, ChannelFromName("beta"));
}

TEST(TeleportChannelTest, MapsStableToStable) {
  EXPECT_EQ(version_info::Channel::STABLE, ChannelFromName("stable"));
}

// staging is an ENVIRONMENT borrowing a channel slot, so it must report a real
// channel rather than falling through to UNKNOWN. CANARY is the honest answer:
// staging is a pre-release build that should take every non-stable code path
// release's canary takes, so the rehearsal exercises the same branches. Leaving
// it UNKNOWN would produce is_official_build=true paired with a channel
// version_info does not know, a combination nothing upstream has been written
// against.
TEST(TeleportChannelTest, MapsStagingToCanary) {
  EXPECT_EQ(version_info::Channel::CANARY, ChannelFromName("staging"));
}

TEST(TeleportChannelTest, MapsEmptyToUnknown) {
  EXPECT_EQ(version_info::Channel::UNKNOWN, ChannelFromName(""));
}

TEST(TeleportChannelTest, MapsDevToUnknown) {
  EXPECT_EQ(version_info::Channel::UNKNOWN, ChannelFromName("dev"));
}

TEST(TeleportChannelTest, MapsGarbageToUnknown) {
  EXPECT_EQ(version_info::Channel::UNKNOWN, ChannelFromName("nonsense"));
}

}  // namespace
}  // namespace teleport
