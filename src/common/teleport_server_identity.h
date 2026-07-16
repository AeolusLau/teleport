#ifndef TELEPORT_COMMON_TELEPORT_SERVER_IDENTITY_H_
#define TELEPORT_COMMON_TELEPORT_SERVER_IDENTITY_H_

#include <cstdint>
#include <optional>
#include <string_view>
#include <vector>

#include "base/containers/span.h"
#include "base/time/time.h"

namespace teleport {

// The two halves of the /server-identity wire container.
struct ServerIdentityParts {
  ServerIdentityParts();
  ~ServerIdentityParts();
  ServerIdentityParts(ServerIdentityParts&&);
  ServerIdentityParts& operator=(ServerIdentityParts&&);

  std::vector<uint8_t> signed_bytes;
  std::vector<uint8_t> signature;
};

// Split the wire container u32be(len)||signed_bytes||signature. Returns nullopt
// when the buffer is shorter than 4 bytes, the length prefix overruns it, or no
// signature bytes remain.
std::optional<ServerIdentityParts> ParseServerIdentityContainer(
    base::span<const uint8_t> blob);

// Classified outcome of server-identity verification. The enroll page (§4.2)
// surfaces a distinct message per reason; the resolver's level-4 re-verification
// only cares whether it is kValid.
enum class ServerIdentityVerdict {
  kValid,
  kBadSignature,       // root signature over signed_bytes did not verify
  kMalformed,          // signed_bytes is not a parseable ServerIdentityData
  kWrongMessageType,   // message_type != "TeleportServerIdentity"
  kUnsupportedVersion,
  kDomainMismatch,     // domain != candidate_domain
  kExpired,            // now >= not_after_unix
};

// Verify signed_bytes' root signature (RSA_PKCS1_SHA256) against root_key_der
// (a DER SubjectPublicKeyInfo), then parse it as ServerIdentityData and require:
// message_type == "TeleportServerIdentity", a supported version, domain ==
// candidate_domain, and now < not_after_unix. Returns the FIRST failing reason
// (checks in that order), or kValid when all hold. The root key DER is INJECTED
// (not read from the baked constant) so this lib stays free of //components/policy
// and is testable with any key.
ServerIdentityVerdict VerifyServerIdentityDetailed(
    base::span<const uint8_t> signed_bytes,
    base::span<const uint8_t> signature,
    base::span<const uint8_t> root_key_der,
    std::string_view candidate_domain,
    base::Time now);

// Boolean convenience wrapper: true iff VerifyServerIdentityDetailed == kValid.
// Consumed by the resolver's level-4 re-verification, which needs no reason.
bool VerifyServerIdentity(base::span<const uint8_t> signed_bytes,
                          base::span<const uint8_t> signature,
                          base::span<const uint8_t> root_key_der,
                          std::string_view candidate_domain,
                          base::Time now);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_SERVER_IDENTITY_H_
