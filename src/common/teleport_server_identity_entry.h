#ifndef TELEPORT_COMMON_TELEPORT_SERVER_IDENTITY_ENTRY_H_
#define TELEPORT_COMMON_TELEPORT_SERVER_IDENTITY_ENTRY_H_

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "base/values.h"

namespace teleport {

// The level-4 self-authenticating deployment-domain entry as stored in Local
// State: the accepted base domain plus the exact root-signed bytes + signature
// that proved it, so the resolver can re-verify offline at startup.
struct ServerIdentityEntry {
  ServerIdentityEntry();
  ~ServerIdentityEntry();
  ServerIdentityEntry(const ServerIdentityEntry&);
  ServerIdentityEntry& operator=(const ServerIdentityEntry&);

  std::string domain;
  std::vector<uint8_t> signed_bytes;
  std::vector<uint8_t> signature;
};

// Encode entry as a Local State dict {domain, identity(b64), signature(b64)}.
base::DictValue EncodeServerIdentityEntry(const ServerIdentityEntry& entry);

// Decode a Local State dict back to an entry, or nullopt when a field is
// missing, the domain is empty, or a base64 field is invalid/empty. This does
// NOT verify the signature — that is the resolver's offline re-verification step.
std::optional<ServerIdentityEntry> DecodeServerIdentityEntry(
    const base::DictValue& dict);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_SERVER_IDENTITY_ENTRY_H_
