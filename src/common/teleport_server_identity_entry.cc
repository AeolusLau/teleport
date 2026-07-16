#include "teleport/common/teleport_server_identity_entry.h"

#include "base/base64.h"

namespace teleport {

namespace {
constexpr char kDomainKey[] = "domain";
constexpr char kIdentityKey[] = "identity";
constexpr char kSignatureKey[] = "signature";
}  // namespace

ServerIdentityEntry::ServerIdentityEntry() = default;
ServerIdentityEntry::~ServerIdentityEntry() = default;
ServerIdentityEntry::ServerIdentityEntry(const ServerIdentityEntry&) = default;
ServerIdentityEntry& ServerIdentityEntry::operator=(const ServerIdentityEntry&) =
    default;

base::DictValue EncodeServerIdentityEntry(const ServerIdentityEntry& entry) {
  base::DictValue dict;
  dict.Set(kDomainKey, entry.domain);
  dict.Set(kIdentityKey, base::Base64Encode(entry.signed_bytes));
  dict.Set(kSignatureKey, base::Base64Encode(entry.signature));
  return dict;
}

std::optional<ServerIdentityEntry> DecodeServerIdentityEntry(
    const base::DictValue& dict) {
  const std::string* domain = dict.FindString(kDomainKey);
  const std::string* identity = dict.FindString(kIdentityKey);
  const std::string* signature = dict.FindString(kSignatureKey);
  if (!domain || !identity || !signature || domain->empty()) {
    return std::nullopt;
  }
  std::string signed_str;
  std::string sig_str;
  if (!base::Base64Decode(*identity, &signed_str) ||
      !base::Base64Decode(*signature, &sig_str)) {
    return std::nullopt;
  }
  if (signed_str.empty() || sig_str.empty()) {
    return std::nullopt;
  }
  ServerIdentityEntry entry;
  entry.domain = *domain;
  entry.signed_bytes.assign(signed_str.begin(), signed_str.end());
  entry.signature.assign(sig_str.begin(), sig_str.end());
  return entry;
}

}  // namespace teleport
