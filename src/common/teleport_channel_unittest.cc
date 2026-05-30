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
