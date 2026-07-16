#ifndef TELEPORT_COMMON_TELEPORT_ENROLL_LOGIC_H_
#define TELEPORT_COMMON_TELEPORT_ENROLL_LOGIC_H_

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

#include "base/containers/span.h"
#include "base/functional/callback.h"
#include "base/time/time.h"
#include "teleport/common/teleport_server_identity_entry.h"
#include "url/gurl.h"

namespace teleport {

// Classified outcome surfaced to the enroll page (§4.2). The pure logic here
// determines the input-format and verification statuses; the fetch-layer
// statuses (kCannotConnect / kTlsError / kHttpError / kRedirectBlocked) and the
// kAlreadyEnrolled state constraint are set by the //chrome/browser handler that
// performs the network fetch and inspects enrollment state.
enum class EnrollStatus {
  kSuccess,              // verified; entry ready to persist
  kInvalidDomainFormat,  // input is not a bare host[:port] (pure)
  kCannotConnect,        // network unreachable / DNS failure (handler)
  kTlsError,             // TLS handshake / certificate failure (handler)
  kHttpError,            // non-200 response (handler)
  kRedirectBlocked,      // server attempted a redirect; we forbid following (handler)
  kMalformedResponse,    // container/proto unparseable (pure)
  kBadSignature,         // root signature over signed_bytes invalid (pure)
  kWrongMessageType,     // message_type != "TeleportServerIdentity" (pure)
  kUnsupportedVersion,   // (pure)
  kDomainMismatch,       // signed domain != the domain we asked for (pure)
  kExpired,              // not_after passed (pure)
  kAlreadyEnrolled,      // an enrollment already exists; page is read-only (handler)
};

// The plan for fetching a candidate deployment's signed identity.
struct EnrollFetchPlan {
  std::string canonical_domain;  // normalized D (lowercase punycode host[:port])
  GURL url;                      // https://teleport.<D>/dm/server-identity
};

// Phase 1 (pure): normalize the raw `?domain=` input and build the
// server-identity URL for it. Returns nullopt when the input is not a bare
// host[:port] (the handler maps that to kInvalidDomainFormat). The URL is built
// from the canonical host via the same teleport.<D> derivation the resolver uses.
std::optional<EnrollFetchPlan> PlanServerIdentityFetch(
    std::string_view raw_input);

// The result of verifying a fetched server-identity body.
struct EnrollVerifyResult {
  EnrollVerifyResult();
  ~EnrollVerifyResult();
  EnrollVerifyResult(EnrollVerifyResult&&);
  EnrollVerifyResult& operator=(EnrollVerifyResult&&);

  EnrollStatus status = EnrollStatus::kMalformedResponse;
  // Set iff status == kSuccess: the entry to write to Local State (level 4).
  std::optional<ServerIdentityEntry> entry;
};

// Phase 2 (pure): given the fetched response body, the canonical domain we asked
// for, the baked root key DER, and the current time, split the wire container,
// verify the root signature + type tag + domain + expiry, and (on success) build
// the ServerIdentityEntry to persist. Fetch-layer errors are classified by the
// caller, not here. The root key DER is INJECTED so this stays free of
// //components/policy.
EnrollVerifyResult VerifyFetchedIdentity(base::span<const uint8_t> body,
                                          std::string_view canonical_domain,
                                          base::span<const uint8_t> root_key_der,
                                          base::Time now);

// Persistence seam: the enroll handler lives in the //chrome/browser/ui/webui
// layer and must NOT reach into g_browser_process to write Local State (that
// would drag chrome/browser into this WebUI target). Instead //chrome/browser
// registers a writer that persists the verified entry to the Local State
// kServerIdentityEntry pref — mirroring the level-4 reader-injection seam. The
// writer returns true on a successful write. WriteServerIdentityEntry runs the
// registered writer (false when none is registered).
using ServerIdentityEntryWriter =
    base::RepeatingCallback<bool(const ServerIdentityEntry&)>;
void SetServerIdentityEntryWriter(ServerIdentityEntryWriter writer);
bool WriteServerIdentityEntry(const ServerIdentityEntry& entry);

// Clear seam: the enroll page's "unbind" button removes the level-4
// kServerIdentityEntry pref so D falls back to the baked default. Same
// registration pattern as the writer; returns true on success. No-op / false
// when unregistered.
using ServerIdentityEntryClearer = base::RepeatingCallback<bool()>;
void SetServerIdentityEntryClearer(ServerIdentityEntryClearer clearer);
bool ClearServerIdentityEntry();

// Relaunch seam: the enroll page's "restart" button must call
// chrome::AttemptRestart(), which lives in the monolithic //chrome/browser
// target this WebUI target cannot depend on. //chrome/browser registers the
// handler; the enroll handler invokes RequestRelaunch(). No-op if unregistered.
using RelaunchHandler = base::RepeatingCallback<void()>;
void SetRelaunchHandler(RelaunchHandler handler);
void RequestRelaunch();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_ENROLL_LOGIC_H_
