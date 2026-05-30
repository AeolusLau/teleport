#include "teleport/common/teleport_feed_url.h"

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportFeedUrlTest, AcceptsHttps) {
  EXPECT_TRUE(IsSecureFeedUrl("https://example.com/canary/tok/appcast.xml"));
}

TEST(TeleportFeedUrlTest, RejectsHttp) {
  EXPECT_FALSE(IsSecureFeedUrl("http://example.com/appcast.xml"));
}

TEST(TeleportFeedUrlTest, RejectsEmptyAndBareScheme) {
  EXPECT_FALSE(IsSecureFeedUrl(""));
  EXPECT_FALSE(IsSecureFeedUrl("https://"));
}

}  // namespace
}  // namespace teleport
