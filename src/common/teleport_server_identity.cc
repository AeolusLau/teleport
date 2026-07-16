#include "teleport/common/teleport_server_identity.h"

#include "crypto/signature_verifier.h"
#include "teleport/common/server_identity.pb.h"

namespace teleport {

namespace {
constexpr char kExpectedMessageType[] = "TeleportServerIdentity";
constexpr uint32_t kSupportedVersion = 1;
}  // namespace

ServerIdentityParts::ServerIdentityParts() = default;
ServerIdentityParts::~ServerIdentityParts() = default;
ServerIdentityParts::ServerIdentityParts(ServerIdentityParts&&) = default;
ServerIdentityParts& ServerIdentityParts::operator=(ServerIdentityParts&&) =
    default;

std::optional<ServerIdentityParts> ParseServerIdentityContainer(
    base::span<const uint8_t> blob) {
  if (blob.size() < 4) {
    return std::nullopt;
  }
  const uint32_t len = (uint32_t{blob[0]} << 24) | (uint32_t{blob[1]} << 16) |
                       (uint32_t{blob[2]} << 8) | uint32_t{blob[3]};
  if (static_cast<size_t>(len) + 4 > blob.size()) {
    return std::nullopt;  // length prefix overruns the buffer
  }
  ServerIdentityParts parts;
  parts.signed_bytes.assign(blob.begin() + 4, blob.begin() + 4 + len);
  parts.signature.assign(blob.begin() + 4 + len, blob.end());
  if (parts.signature.empty()) {
    return std::nullopt;  // no signature bytes
  }
  return parts;
}

ServerIdentityVerdict VerifyServerIdentityDetailed(
    base::span<const uint8_t> signed_bytes,
    base::span<const uint8_t> signature,
    base::span<const uint8_t> root_key_der,
    std::string_view candidate_domain,
    base::Time now) {
  // 1) Root signature over signed_bytes (RSA_PKCS1_SHA256), the same primitive
  //    CloudPolicyValidatorBase::VerifySignature uses for the policy chain.
  crypto::SignatureVerifier verifier;
  if (!verifier.VerifyInit(crypto::SignatureVerifier::RSA_PKCS1_SHA256,
                           signature, root_key_der)) {
    return ServerIdentityVerdict::kBadSignature;
  }
  verifier.VerifyUpdate(signed_bytes);
  if (!verifier.VerifyFinal()) {
    return ServerIdentityVerdict::kBadSignature;
  }
  // 2) Parse + field checks (message_type discriminator, version, domain,
  //    expiry). The signature above already binds these exact bytes.
  teleport::v1::ServerIdentityData data;
  if (!data.ParseFromArray(signed_bytes.data(),
                           static_cast<int>(signed_bytes.size()))) {
    return ServerIdentityVerdict::kMalformed;
  }
  if (data.message_type() != kExpectedMessageType) {
    return ServerIdentityVerdict::kWrongMessageType;
  }
  if (data.version() != kSupportedVersion) {
    return ServerIdentityVerdict::kUnsupportedVersion;
  }
  if (data.domain() != candidate_domain) {
    return ServerIdentityVerdict::kDomainMismatch;
  }
  if (now >= base::Time::FromTimeT(static_cast<time_t>(data.not_after_unix()))) {
    return ServerIdentityVerdict::kExpired;
  }
  return ServerIdentityVerdict::kValid;
}

bool VerifyServerIdentity(base::span<const uint8_t> signed_bytes,
                          base::span<const uint8_t> signature,
                          base::span<const uint8_t> root_key_der,
                          std::string_view candidate_domain,
                          base::Time now) {
  return VerifyServerIdentityDetailed(signed_bytes, signature, root_key_der,
                                      candidate_domain, now) ==
         ServerIdentityVerdict::kValid;
}

}  // namespace teleport
