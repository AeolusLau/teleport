#include "teleport/common/teleport_server_identity_entry.h"

#include <cstdint>
#include <vector>

#include "base/values.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

TEST(TeleportServerIdentityEntryTest, EncodeDecodeRoundTrips) {
  ServerIdentityEntry e;
  e.domain = "acme.internal";
  e.signed_bytes = {0x01, 0x02, 0x03};
  e.signature = {0xAA, 0xBB};

  std::optional<ServerIdentityEntry> out =
      DecodeServerIdentityEntry(EncodeServerIdentityEntry(e));
  ASSERT_TRUE(out);
  EXPECT_EQ(out->domain, "acme.internal");
  EXPECT_EQ(out->signed_bytes, (std::vector<uint8_t>{0x01, 0x02, 0x03}));
  EXPECT_EQ(out->signature, (std::vector<uint8_t>{0xAA, 0xBB}));
}

TEST(TeleportServerIdentityEntryTest, RejectsMissingFields) {
  base::DictValue d;
  d.Set("domain", "acme.internal");  // identity + signature absent
  EXPECT_FALSE(DecodeServerIdentityEntry(d));
}

TEST(TeleportServerIdentityEntryTest, RejectsBadBase64) {
  base::DictValue d;
  d.Set("domain", "acme.internal");
  d.Set("identity", "!!!not-base64");
  d.Set("signature", "qqs=");
  EXPECT_FALSE(DecodeServerIdentityEntry(d));
}

TEST(TeleportServerIdentityEntryTest, RejectsEmptyDomain) {
  base::DictValue d;
  d.Set("domain", "");
  d.Set("identity", "AQID");  // base64 of {1,2,3}
  d.Set("signature", "qqs=");
  EXPECT_FALSE(DecodeServerIdentityEntry(d));
}

TEST(TeleportServerIdentityEntryTest, RejectsEmptyDecodedFields) {
  base::DictValue d;
  d.Set("domain", "acme.internal");
  d.Set("identity", "");  // decodes to empty
  d.Set("signature", "qqs=");
  EXPECT_FALSE(DecodeServerIdentityEntry(d));
}

}  // namespace
}  // namespace teleport
