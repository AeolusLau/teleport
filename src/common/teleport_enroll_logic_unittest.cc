#include "teleport/common/teleport_enroll_logic.h"

#include <cstdint>
#include <string>
#include <vector>

#include "base/functional/bind.h"
#include "base/time/time.h"
#include "crypto/keypair.h"
#include "crypto/sign.h"
#include "teleport/common/server_identity.pb.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

constexpr char kSentinel[] = "TeleportServerIdentity";
constexpr int64_t kFuture = 4102444800;                     // 2100-01-01
const base::Time kNow = base::Time::FromTimeT(1750000000);  // ~2025-06

// Builds a wire container u32be(len(signed))||signed||signature from a signed
// ServerIdentityData, and returns it alongside the signing key's SPKI DER.
struct Container {
  std::vector<uint8_t> blob;
  std::vector<uint8_t> spki_der;
};
Container MakeContainer(const std::string& message_type,
                        const std::string& domain,
                        int64_t not_after_unix) {
  teleport::v1::ServerIdentityData msg;
  msg.set_message_type(message_type);
  msg.set_version(1);
  msg.set_domain(domain);
  msg.set_not_after_unix(not_after_unix);
  std::string serialized = msg.SerializeAsString();
  std::vector<uint8_t> signed_bytes(serialized.begin(), serialized.end());

  crypto::keypair::PrivateKey key =
      crypto::keypair::PrivateKey::GenerateRsa2048();
  std::vector<uint8_t> sig = crypto::sign::Sign(
      crypto::sign::SignatureKind::RSA_PKCS1_SHA256, key, signed_bytes);

  Container c;
  const uint32_t len = static_cast<uint32_t>(signed_bytes.size());
  c.blob = {static_cast<uint8_t>(len >> 24), static_cast<uint8_t>(len >> 16),
            static_cast<uint8_t>(len >> 8), static_cast<uint8_t>(len)};
  c.blob.insert(c.blob.end(), signed_bytes.begin(), signed_bytes.end());
  c.blob.insert(c.blob.end(), sig.begin(), sig.end());
  c.spki_der = key.ToSubjectPublicKeyInfo();
  return c;
}

// --- Phase 1: PlanServerIdentityFetch ---

TEST(TeleportConnectLogicTest, PlansValidDomain) {
  auto plan = PlanServerIdentityFetch("acme.internal");
  ASSERT_TRUE(plan);
  EXPECT_EQ(plan->canonical_domain, "acme.internal");
  EXPECT_EQ(plan->url,
            GURL("https://teleport.acme.internal/dm/server-identity"));
}

TEST(TeleportConnectLogicTest, PlansDomainWithPort) {
  auto plan = PlanServerIdentityFetch("acme.internal:8443");
  ASSERT_TRUE(plan);
  EXPECT_EQ(plan->canonical_domain, "acme.internal:8443");
  EXPECT_EQ(plan->url,
            GURL("https://teleport.acme.internal:8443/dm/server-identity"));
}

TEST(TeleportConnectLogicTest, CanonicalizesInput) {
  auto plan = PlanServerIdentityFetch("  ACME.Internal.  ");
  ASSERT_TRUE(plan);
  EXPECT_EQ(plan->canonical_domain, "acme.internal");
}

TEST(TeleportConnectLogicTest, RejectsMalformedInput) {
  EXPECT_FALSE(PlanServerIdentityFetch(""));
  EXPECT_FALSE(PlanServerIdentityFetch("https://acme.internal/x"));
  EXPECT_FALSE(PlanServerIdentityFetch("user@acme.internal"));
  EXPECT_FALSE(PlanServerIdentityFetch("acme.internal/path"));
}

// --- Phase 2: VerifyFetchedIdentity ---

TEST(TeleportConnectLogicTest, VerifiesAndBuildsEntry) {
  Container c = MakeContainer(kSentinel, "acme.internal", kFuture);
  EnrollVerifyResult r =
      VerifyFetchedIdentity(c.blob, "acme.internal", c.spki_der, kNow);
  EXPECT_EQ(r.status, EnrollStatus::kSuccess);
  ASSERT_TRUE(r.entry);
  EXPECT_EQ(r.entry->domain, "acme.internal");
  EXPECT_FALSE(r.entry->signed_bytes.empty());
  EXPECT_FALSE(r.entry->signature.empty());
}

TEST(TeleportConnectLogicTest, RejectsTruncatedContainer) {
  EnrollVerifyResult r = VerifyFetchedIdentity(
      std::vector<uint8_t>{0, 0, 0, 9, 0x01}, "acme.internal",
      std::vector<uint8_t>{0x01}, kNow);
  EXPECT_EQ(r.status, EnrollStatus::kMalformedResponse);
  EXPECT_FALSE(r.entry);
}

TEST(TeleportConnectLogicTest, RejectsBadSignature) {
  Container good = MakeContainer(kSentinel, "acme.internal", kFuture);
  Container other = MakeContainer(kSentinel, "acme.internal", kFuture);
  // Verify good's blob against other's key -> signature invalid.
  EnrollVerifyResult r =
      VerifyFetchedIdentity(good.blob, "acme.internal", other.spki_der, kNow);
  EXPECT_EQ(r.status, EnrollStatus::kBadSignature);
  EXPECT_FALSE(r.entry);
}

TEST(TeleportConnectLogicTest, RejectsWrongMessageType) {
  Container c = MakeContainer("NotTheSentinel", "acme.internal", kFuture);
  EnrollVerifyResult r =
      VerifyFetchedIdentity(c.blob, "acme.internal", c.spki_der, kNow);
  EXPECT_EQ(r.status, EnrollStatus::kWrongMessageType);
}

TEST(TeleportConnectLogicTest, RejectsDomainMismatch) {
  Container c = MakeContainer(kSentinel, "acme.internal", kFuture);
  EnrollVerifyResult r =
      VerifyFetchedIdentity(c.blob, "evil.example", c.spki_der, kNow);
  EXPECT_EQ(r.status, EnrollStatus::kDomainMismatch);
}

TEST(TeleportConnectLogicTest, RejectsExpired) {
  Container c = MakeContainer(kSentinel, "acme.internal", 1000000000);  // 2001
  EnrollVerifyResult r =
      VerifyFetchedIdentity(c.blob, "acme.internal", c.spki_der, kNow);
  EXPECT_EQ(r.status, EnrollStatus::kExpired);
}

// --- Persistence seam ---

TEST(TeleportConnectLogicTest, WriterSeamRunsRegisteredWriter) {
  std::string written_domain;
  SetServerIdentityEntryWriter(base::BindRepeating(
      [](std::string* out, const ServerIdentityEntry& e) {
        *out = e.domain;
        return true;
      },
      &written_domain));
  ServerIdentityEntry entry;
  entry.domain = "acme.internal";
  EXPECT_TRUE(WriteServerIdentityEntry(entry));
  EXPECT_EQ(written_domain, "acme.internal");
  // Reset so the global seam does not leak into other tests in this binary.
  SetServerIdentityEntryWriter(ServerIdentityEntryWriter());
}

TEST(TeleportConnectLogicTest, WriterSeamAbsentReturnsFalse) {
  SetServerIdentityEntryWriter(ServerIdentityEntryWriter());  // clear
  ServerIdentityEntry entry;
  entry.domain = "acme.internal";
  EXPECT_FALSE(WriteServerIdentityEntry(entry));
}

}  // namespace
}  // namespace teleport
