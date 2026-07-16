#include "teleport/common/teleport_enroll_logic.h"

#include <utility>

#include "base/no_destructor.h"
#include "teleport/common/teleport_deployment_config.h"
#include "teleport/common/teleport_server_identity.h"

namespace teleport {

namespace {

// Registered by //chrome/browser (level-4 wiring) to persist the entry to Local
// State. A NoDestructor holds it for the process lifetime.
ServerIdentityEntryWriter& MutableEntryWriter() {
  static base::NoDestructor<ServerIdentityEntryWriter> writer;
  return *writer;
}

// Registered by //chrome/browser to run chrome::AttemptRestart().
RelaunchHandler& MutableRelaunchHandler() {
  static base::NoDestructor<RelaunchHandler> handler;
  return *handler;
}

// Registered by //chrome/browser to clear the level-4 kServerIdentityEntry pref.
ServerIdentityEntryClearer& MutableEntryClearer() {
  static base::NoDestructor<ServerIdentityEntryClearer> clearer;
  return *clearer;
}

// Map a verification verdict onto the enroll-page status vocabulary.
EnrollStatus StatusForVerdict(ServerIdentityVerdict verdict) {
  switch (verdict) {
    case ServerIdentityVerdict::kValid:
      return EnrollStatus::kSuccess;
    case ServerIdentityVerdict::kBadSignature:
      return EnrollStatus::kBadSignature;
    case ServerIdentityVerdict::kMalformed:
      return EnrollStatus::kMalformedResponse;
    case ServerIdentityVerdict::kWrongMessageType:
      return EnrollStatus::kWrongMessageType;
    case ServerIdentityVerdict::kUnsupportedVersion:
      return EnrollStatus::kUnsupportedVersion;
    case ServerIdentityVerdict::kDomainMismatch:
      return EnrollStatus::kDomainMismatch;
    case ServerIdentityVerdict::kExpired:
      return EnrollStatus::kExpired;
  }
}

}  // namespace

EnrollVerifyResult::EnrollVerifyResult() = default;
EnrollVerifyResult::~EnrollVerifyResult() = default;
EnrollVerifyResult::EnrollVerifyResult(EnrollVerifyResult&&) = default;
EnrollVerifyResult& EnrollVerifyResult::operator=(EnrollVerifyResult&&) =
    default;

std::optional<EnrollFetchPlan> PlanServerIdentityFetch(
    std::string_view raw_input) {
  std::optional<std::string> domain = NormalizeDeploymentDomain(raw_input);
  if (!domain) {
    return std::nullopt;
  }
  EnrollFetchPlan plan;
  plan.canonical_domain = *domain;
  // Same teleport.<D> derivation the resolver uses; port (if any) stays at the
  // tail of the host, ahead of the path.
  plan.url = GURL("https://" + TeleportHostFor(plan.canonical_domain) +
                  "/dm/server-identity");
  if (!plan.url.is_valid()) {
    return std::nullopt;
  }
  return plan;
}

EnrollVerifyResult VerifyFetchedIdentity(base::span<const uint8_t> body,
                                          std::string_view canonical_domain,
                                          base::span<const uint8_t> root_key_der,
                                          base::Time now) {
  EnrollVerifyResult result;
  std::optional<ServerIdentityParts> parts = ParseServerIdentityContainer(body);
  if (!parts) {
    result.status = EnrollStatus::kMalformedResponse;
    return result;
  }
  ServerIdentityVerdict verdict = VerifyServerIdentityDetailed(
      parts->signed_bytes, parts->signature, root_key_der, canonical_domain,
      now);
  result.status = StatusForVerdict(verdict);
  if (verdict == ServerIdentityVerdict::kValid) {
    ServerIdentityEntry entry;
    entry.domain = std::string(canonical_domain);
    entry.signed_bytes = std::move(parts->signed_bytes);
    entry.signature = std::move(parts->signature);
    result.entry = std::move(entry);
  }
  return result;
}

void SetServerIdentityEntryWriter(ServerIdentityEntryWriter writer) {
  MutableEntryWriter() = std::move(writer);
}

bool WriteServerIdentityEntry(const ServerIdentityEntry& entry) {
  const ServerIdentityEntryWriter& writer = MutableEntryWriter();
  return writer ? writer.Run(entry) : false;
}

void SetServerIdentityEntryClearer(ServerIdentityEntryClearer clearer) {
  MutableEntryClearer() = std::move(clearer);
}

bool ClearServerIdentityEntry() {
  const ServerIdentityEntryClearer& clearer = MutableEntryClearer();
  return clearer ? clearer.Run() : false;
}

void SetRelaunchHandler(RelaunchHandler handler) {
  MutableRelaunchHandler() = std::move(handler);
}

void RequestRelaunch() {
  const RelaunchHandler& handler = MutableRelaunchHandler();
  if (handler) {
    handler.Run();
  }
}

}  // namespace teleport
