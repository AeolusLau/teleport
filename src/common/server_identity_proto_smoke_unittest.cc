#include "teleport/common/server_identity.pb.h"

#include <string>

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Proves the ServerIdentityData proto compiles into the client and round-trips
// through serialize/parse — the wire contract shared with fairyland.
TEST(ServerIdentityProtoTest, RoundTrips) {
  teleport::v1::ServerIdentityData msg;
  msg.set_message_type("TeleportServerIdentity");
  msg.set_version(1);
  msg.set_domain("acme.internal");
  msg.set_not_after_unix(4102444800);
  std::string bytes = msg.SerializeAsString();

  teleport::v1::ServerIdentityData parsed;
  ASSERT_TRUE(parsed.ParseFromString(bytes));
  EXPECT_EQ(parsed.message_type(), "TeleportServerIdentity");
  EXPECT_EQ(parsed.version(), 1u);
  EXPECT_EQ(parsed.domain(), "acme.internal");
  EXPECT_EQ(parsed.not_after_unix(), 4102444800);
}

}  // namespace
}  // namespace teleport
