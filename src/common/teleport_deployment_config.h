#ifndef TELEPORT_COMMON_TELEPORT_DEPLOYMENT_CONFIG_H_
#define TELEPORT_COMMON_TELEPORT_DEPLOYMENT_CONFIG_H_

#include <optional>
#include <string>
#include <string_view>

#include "base/files/file_path.h"
#include "base/functional/callback.h"

namespace teleport {

// Which source level supplied the effective deployment domain (for diagnostics).
enum class DeploymentDomainSource {
  kCommandLine,   // level 1 (dev builds only)
  kManagedPref,   // level 2
  kMachineFile,   // level 3
  kUserAccepted,  // level 4 (Phase 2; never selected in Phase 1)
  kBakedDefault,  // level 5
};

struct DeploymentResolution {
  std::string domain;
  DeploymentDomainSource source;
};

// The resolved base deployment domain D (e.g. "acme.internal" or
// "acme.internal:8443"). Resolved once on first call and cached for the process
// lifetime (D is immutable per process). Never empty — always falls back to the
// baked default for this build variant.
const std::string& DeploymentDomain();

// The source level that supplied DeploymentDomain(), for chrome://version.
DeploymentDomainSource DeploymentDomainSourceLevel();

// Human-readable label for DeploymentDomainSourceLevel() (e.g. "machine config
// file"), for the chrome://version diagnostic line.
std::string DeploymentDomainSourceLabel();

// Corp-managed lock (spec §4.6): whether the user is forbidden from changing the
// deployment domain via the enroll page. Locked by EXPLICIT admin declaration
// only — the domain came from a higher-priority admin channel (levels 1/2/3), OR
// an admin forced the dedicated RestrictDeploymentDomainChange policy. Levels 4/5
// (user-accepted / baked default) with neither signal stay writable (BYOD
// self-service). Inputs are read at the call site and injected, so the predicate
// is pure and testable. (Machine CBCM-enrollment is deliberately NOT a lock
// signal — see spec §4.6: it is redundant with the explicit signals in real
// corp flows and its machine-state coupling is surprising/fragile.)
bool IsDomainChangeLocked(DeploymentDomainSource source,
                          bool restrict_change_forced);

// Whether an MDM has FORCED the dedicated RestrictDeploymentDomainChange boolean
// managed pref to true (read the same forced-only way as the level-2 domain, so
// a plain user-writable pref cannot self-lock or spoof management). Used by the
// enroll page to lock a SaaS-managed device whose domain is the baked default
// (no domain policy) — decoupled from the domain value, survives official-domain
// rotation. False on non-mac / when unset.
bool ReadRestrictDomainChangeForced();

// True iff an admin has restricted domain change via EITHER channel: the forced
// managed pref (ReadRestrictDomainChangeForced) OR a trusted machine config file
// carrying "restrict_domain_change": true. Only ever locks (OR of two opt-ins);
// there is no unlock path. Consumed by the enroll page (§4.6).
bool IsDomainChangeRestrictedByAdmin();

// Level 4 (user-accepted, from the teleport://enroll page) is read via an
// injected callback so this //base+//url leaf never depends on //crypto, the
// server-identity proto, or Local State (all of which live in heavier targets /
// //chrome/browser). The //chrome/browser side registers a reader that reads the
// stored entry and re-verifies it offline against the baked root key; if no
// reader is registered, level 4 is absent. Register BEFORE the first
// DeploymentDomain() call (early startup) — the result is memoized per process.
using UserAcceptedDomainReader =
    base::RepeatingCallback<std::optional<std::string>()>;
void SetUserAcceptedDomainReader(UserAcceptedDomainReader reader);

// Runs the registered reader (nullopt when none is registered). Consumed by the
// resolver's level-4 slot; exposed for testing the injection seam.
std::optional<std::string> ReadUserAcceptedDomain();

// Normalize a candidate deployment domain to canonical form, or nullopt when the
// input is not a bare host[:port]. Canonical = lowercase ASCII (punycode) host +
// optional ":port", no trailing dot, no scheme/path/query/fragment/userinfo.
// Hardened against URL-parsing confusion (rejects userinfo, IPv6 literals, etc.).
std::optional<std::string> NormalizeDeploymentDomain(std::string_view input);

// Level-1 policy as a pure function: decide what the command-line switch should
// yield, given whether this build accepts the override at all, whether the
// switch was present, and its raw value.
//
// Split out of ReadCommandLineDomain() so that all three environment settings
// are testable from a single dev binary. A test binary is built for exactly one
// environment, so the branch a release build takes — refuse the override — was
// otherwise unreachable by any test, which made the one setting the isolation
// argument rests on the one setting nothing could cover.
std::optional<std::string> SelectCommandLineDomain(bool allows_override,
                                                   bool switch_present,
                                                   std::string_view switch_value);

// Pure precedence selector: pick the highest-priority present candidate. Each
// argument is the already-read, already-normalized value from that source level
// (nullopt = level absent). baked_default is always present (level 5). Testable
// without touching process state.
DeploymentResolution SelectDeploymentDomain(
    std::optional<std::string> command_line,
    std::optional<std::string> managed_pref,
    std::optional<std::string> machine_file,
    std::optional<std::string> user_accepted,
    std::string baked_default);

// Parsed fields of the level-3 machine config file. `domain` is the normalized
// value (nullopt when the "domain" key is absent OR present-but-invalid);
// `domain_key_present` distinguishes those two so a restrict-only file does not
// trip the invalid-domain error log. `restrict_domain_change` is the §4.6 lock
// opt-in (false when the key is absent or non-boolean).
struct DeploymentConfigFields {
  DeploymentConfigFields();
  DeploymentConfigFields(const DeploymentConfigFields&);
  DeploymentConfigFields(DeploymentConfigFields&&);
  DeploymentConfigFields& operator=(const DeploymentConfigFields&);
  DeploymentConfigFields& operator=(DeploymentConfigFields&&);
  ~DeploymentConfigFields();

  std::optional<std::string> domain;
  bool domain_key_present = false;
  bool restrict_domain_change = false;
};

// Pure parser for the machine config file JSON. Does no file IO. All parsing
// logic lives here (fully unit-testable); the readers are thin trust-gated
// wrappers. Non-dict / malformed JSON yields all-default fields.
DeploymentConfigFields ParseDeploymentConfigFile(std::string_view contents);

// Parse the machine config file JSON, returning the normalized "domain" value or
// nullopt (missing/non-string/invalid domain, or malformed JSON). Does no file IO.
// Thin shim over ParseDeploymentConfigFile (kept for existing callers/tests).
std::optional<std::string> ParseDeploymentConfigJson(std::string_view contents);

// Absolute path of the machine-level deployment config file (level 3).
// macOS/POSIX only, and narrow-char: base::FilePath::StringType is std::wstring
// on Windows, so this does not even convert there. The level-3 channel is
// compiled out off POSIX -- see CachedMachineFile() for why a Windows path is
// not the missing piece.
inline constexpr char kDeploymentConfigFilePath[] =
    "/Library/Teleport/DeploymentConfig.json";

// True iff path exists, is owned by uid 0 (root), and is not group/world
// writable. The machine config file is a root-only admin channel; a file that
// any non-root user could have planted or rewritten must not be trusted.
//
// POSIX only. On other platforms (Windows) this always returns false: the
// equivalent check is a DACL one, and until that exists the machine-file
// channel is unavailable rather than approximated. See TD-040.
bool IsMachineConfigFileTrusted(const base::FilePath& path);

// Build "teleport.<d>" (d may include ":port"; the port stays at the tail).
// Exposed for direct testing of the port-handling path (the zero-arg derivation
// helpers read the process-cached DeploymentDomain(), which has no port in tests).
std::string TeleportHostFor(std::string_view d);

// Build "edge.<d>" (same port handling as TeleportHostFor: a ":port" already
// at D's tail stays at the tail of the result). This is the tunnel service's
// edge proxy HOST only — the edge proxy PORT (443 prod / dev per Piece 0) is
// deliberately not baked in here; the caller supplies it separately when
// constructing the net::ProxyServer (see TeleportTunnelService).
std::string EdgeHostFor(std::string_view d);

// Convenience: EdgeHostFor(DeploymentDomain()).
std::string EdgeHost();

// Build "accounts.<d>" (same port handling as TeleportHostFor). This is the
// fixed universal login/account-plane host of the current fairyland topology
// (tenant chosen via select_tenant on the shared host, not a per-tenant OP
// subdomain), so the enrollment-gate exact-host whitelist derives it from D.
std::string AccountsHostFor(std::string_view d);

// Host portion of d without any ":port" (for the gate suffix). d is canonical
// (punycode ASCII host, no internal colon), so the only colon is the port sep.
std::string DomainHostOnlyFor(std::string_view d);

// Endpoint derivation from DeploymentDomain(). All live in this minimal target so
// //components/policy (browser_policy_connector) can consume them without a
// dependency cycle on :teleport.
std::string DeploymentDeviceManagementServerUrl();
std::string DeploymentEncryptedReportingUrl();
std::string DeploymentRealtimeReportingUrl();
std::string DeploymentEnrollUrl();
std::string DeploymentRegisterHandlerUrl();
std::string DeploymentTrustedRedirectHost();
std::string DeploymentEnrollmentDomainSuffix();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_DEPLOYMENT_CONFIG_H_
