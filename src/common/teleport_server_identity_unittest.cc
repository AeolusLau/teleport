#include "teleport/common/teleport_server_identity.h"

#include <cstdint>
#include <string>
#include <vector>

#include "base/time/time.h"
#include "crypto/keypair.h"
#include "crypto/sign.h"
#include "teleport/common/server_identity.pb.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

constexpr char kSentinel[] = "TeleportServerIdentity";
constexpr int64_t kFuture = 4102444800;  // 2100-01-01
const base::Time kNow = base::Time::FromTimeT(1750000000);  // ~2025-06

// Signs a ServerIdentityData with a fresh RSA key; returns signed_bytes,
// signature, and the SPKI DER of the signing key's public half.
struct Signed {
  std::vector<uint8_t> signed_bytes;
  std::vector<uint8_t> signature;
  std::vector<uint8_t> spki_der;
};
Signed MakeSigned(const std::string& message_type,
                  const std::string& domain,
                  int64_t not_after_unix) {
  teleport::v1::ServerIdentityData msg;
  msg.set_message_type(message_type);
  msg.set_version(1);
  msg.set_domain(domain);
  msg.set_not_after_unix(not_after_unix);
  std::string serialized = msg.SerializeAsString();

  crypto::keypair::PrivateKey key = crypto::keypair::PrivateKey::GenerateRsa2048();
  Signed s;
  s.signed_bytes.assign(serialized.begin(), serialized.end());
  s.signature = crypto::sign::Sign(crypto::sign::SignatureKind::RSA_PKCS1_SHA256,
                                   key, s.signed_bytes);
  s.spki_der = key.ToSubjectPublicKeyInfo();
  return s;
}

TEST(TeleportServerIdentityTest, VerifiesValidBlob) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  EXPECT_TRUE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                   "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsWrongMessageType) {
  Signed s = MakeSigned("NotTheSentinel", "acme.internal", kFuture);
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsDomainMismatch) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "evil.example", kNow));
}

TEST(TeleportServerIdentityTest, RejectsExpired) {
  Signed s = MakeSigned(kSentinel, "acme.internal", 1000000000);  // 2001, past
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsTamperedSignature) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  s.signature[0] ^= 0xFF;
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsWrongKey) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  Signed other = MakeSigned(kSentinel, "acme.internal", kFuture);  // different key
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, other.spki_der,
                                    "acme.internal", kNow));
}

// --- Detailed verdict (classified reasons for the enroll page, §4.2) ---

TEST(TeleportServerIdentityDetailedTest, ValidReturnsValid) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  EXPECT_EQ(VerifyServerIdentityDetailed(s.signed_bytes, s.signature, s.spki_der,
                                         "acme.internal", kNow),
            ServerIdentityVerdict::kValid);
}

TEST(TeleportServerIdentityDetailedTest, BadSignatureFromTamper) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  s.signature[0] ^= 0xFF;
  EXPECT_EQ(VerifyServerIdentityDetailed(s.signed_bytes, s.signature, s.spki_der,
                                         "acme.internal", kNow),
            ServerIdentityVerdict::kBadSignature);
}

TEST(TeleportServerIdentityDetailedTest, BadSignatureFromWrongKey) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  Signed other = MakeSigned(kSentinel, "acme.internal", kFuture);
  EXPECT_EQ(VerifyServerIdentityDetailed(s.signed_bytes, s.signature,
                                         other.spki_der, "acme.internal", kNow),
            ServerIdentityVerdict::kBadSignature);
}

TEST(TeleportServerIdentityDetailedTest, WrongMessageType) {
  Signed s = MakeSigned("NotTheSentinel", "acme.internal", kFuture);
  EXPECT_EQ(VerifyServerIdentityDetailed(s.signed_bytes, s.signature, s.spki_der,
                                         "acme.internal", kNow),
            ServerIdentityVerdict::kWrongMessageType);
}

TEST(TeleportServerIdentityDetailedTest, DomainMismatch) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  EXPECT_EQ(VerifyServerIdentityDetailed(s.signed_bytes, s.signature, s.spki_der,
                                         "evil.example", kNow),
            ServerIdentityVerdict::kDomainMismatch);
}

TEST(TeleportServerIdentityDetailedTest, Expired) {
  Signed s = MakeSigned(kSentinel, "acme.internal", 1000000000);  // 2001
  EXPECT_EQ(VerifyServerIdentityDetailed(s.signed_bytes, s.signature, s.spki_der,
                                         "acme.internal", kNow),
            ServerIdentityVerdict::kExpired);
}

TEST(TeleportServerIdentityDetailedTest, MalformedProtoButValidSignature) {
  // Sign arbitrary non-proto bytes: the signature verifies, but ParseFromArray
  // fails -> kMalformed. 0x08 0x08 is truncated (field 1 varint w/o payload).
  crypto::keypair::PrivateKey key =
      crypto::keypair::PrivateKey::GenerateRsa2048();
  std::vector<uint8_t> junk = {0x08};  // dangling varint tag, unparseable
  std::vector<uint8_t> sig = crypto::sign::Sign(
      crypto::sign::SignatureKind::RSA_PKCS1_SHA256, key, junk);
  EXPECT_EQ(VerifyServerIdentityDetailed(junk, sig, key.ToSubjectPublicKeyInfo(),
                                         "acme.internal", kNow),
            ServerIdentityVerdict::kMalformed);
}

TEST(TeleportServerIdentityContainerTest, RoundTripsContainer) {
  std::vector<uint8_t> blob = {0, 0, 0, 3, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE};
  auto parts = ParseServerIdentityContainer(blob);
  ASSERT_TRUE(parts);
  EXPECT_EQ(parts->signed_bytes, (std::vector<uint8_t>{0xAA, 0xBB, 0xCC}));
  EXPECT_EQ(parts->signature, (std::vector<uint8_t>{0xDD, 0xEE}));
}

TEST(TeleportServerIdentityContainerTest, RejectsTruncated) {
  EXPECT_FALSE(ParseServerIdentityContainer(
      std::vector<uint8_t>{0, 0, 0, 9, 0x01}));       // len > data
  EXPECT_FALSE(ParseServerIdentityContainer(std::vector<uint8_t>{0, 0}));  // <4
  EXPECT_FALSE(ParseServerIdentityContainer(
      std::vector<uint8_t>{0, 0, 0, 3, 0xAA, 0xBB, 0xCC}));  // no signature
}

}  // namespace
}  // namespace teleport
