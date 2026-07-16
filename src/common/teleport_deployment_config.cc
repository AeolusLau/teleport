#include "teleport/common/teleport_deployment_config.h"

#include <sys/stat.h>

#include <optional>
#include <string_view>

#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/json/json_reader.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/strings/string_util.h"
#include "base/values.h"
#include "build/build_config.h"
#include "teleport/teleport_policy_buildflags.h"
#include "url/gurl.h"

namespace teleport {

// Level 1 (dev-only) / level 2 (managed pref) readers. Declared here (not in
// the public header — they are an internal wiring detail of ResolveUncached()
// below, not part of the public API) with ORDINARY (non-anonymous-namespace)
// linkage: the mac definitions live in a SEPARATE translation unit
// (teleport_deployment_config_mac.mm) and must bind to these exact symbols at
// link time, which an internal-linkage (anonymous-namespace) declaration could
// never satisfy across translation units.
std::optional<std::string> ReadCommandLineDomain();
std::optional<std::string> ReadManagedPrefDomain();

// Other platforms are not yet supported (Phase 1 is mac-only); always report
// the source absent. Compiled out on mac, where teleport_deployment_config_mac.mm
// supplies the real bodies for the declarations above.
#if !BUILDFLAG(IS_MAC)
std::optional<std::string> ReadCommandLineDomain() {
  return std::nullopt;
}
std::optional<std::string> ReadManagedPrefDomain() {
  return std::nullopt;
}
bool ReadRestrictDomainChangeForced() {
  return false;
}
#endif

namespace {

#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
constexpr char kBakedDefaultDomain[] = "douan.cn";
#else
constexpr char kBakedDefaultDomain[] = "fairyland.io";
#endif

// Level 3 (cross-platform): read + trust-gate + parse the machine config file.
std::optional<std::string> ReadMachineFileDomain() {
  base::FilePath path(kDeploymentConfigFilePath);
  if (!IsMachineConfigFileTrusted(path)) {
    return std::nullopt;
  }
  std::string contents;
  if (!base::ReadFileToString(path, &contents)) {
    LOG(ERROR) << "[teleport-deployment] machine config file unreadable";
    return std::nullopt;
  }
  std::optional<std::string> domain = ParseDeploymentConfigJson(contents);
  if (!domain) {
    LOG(ERROR)
        << "[teleport-deployment] machine config file has no valid domain";
  }
  return domain;
}

// Resolve the deployment domain by descending the source precedence: level 1
// (dev-only command line) > level 2 (managed pref) > level 3 (machine file) >
// level 4 (user-accepted, Phase 2 — always nullopt here) > level 5 (baked
// default).
// Registered by the //chrome/browser side (SetUserAcceptedDomainReader). A
// NoDestructor holds the callback so it survives for the process lifetime.
UserAcceptedDomainReader& MutableUserAcceptedReader() {
  static base::NoDestructor<UserAcceptedDomainReader> reader;
  return *reader;
}

DeploymentResolution ResolveUncached() {
  return SelectDeploymentDomain(
      ReadCommandLineDomain(), ReadManagedPrefDomain(), ReadMachineFileDomain(),
      ReadUserAcceptedDomain(), kBakedDefaultDomain);
}

const DeploymentResolution& Cached() {
  static const base::NoDestructor<DeploymentResolution> resolution(
      ResolveUncached());
  return *resolution;
}

}  // namespace

void SetUserAcceptedDomainReader(UserAcceptedDomainReader reader) {
  MutableUserAcceptedReader() = std::move(reader);
}

std::optional<std::string> ReadUserAcceptedDomain() {
  const UserAcceptedDomainReader& reader = MutableUserAcceptedReader();
  return reader ? reader.Run() : std::nullopt;
}

const std::string& DeploymentDomain() {
  return Cached().domain;
}

DeploymentDomainSource DeploymentDomainSourceLevel() {
  return Cached().source;
}

std::string DeploymentDomainSourceLabel() {
  switch (DeploymentDomainSourceLevel()) {
    case DeploymentDomainSource::kCommandLine:
      return "command-line switch";
    case DeploymentDomainSource::kManagedPref:
      return "managed preference";
    case DeploymentDomainSource::kMachineFile:
      return "machine config file";
    case DeploymentDomainSource::kUserAccepted:
      return "user-accepted";
    case DeploymentDomainSource::kBakedDefault:
      return "built-in default";
  }
}

bool IsDomainChangeLocked(DeploymentDomainSource source,
                          bool restrict_change_forced) {
  switch (source) {
    case DeploymentDomainSource::kCommandLine:
    case DeploymentDomainSource::kManagedPref:
    case DeploymentDomainSource::kMachineFile:
      // Domain came from a higher-priority admin channel: admin owns it.
      return true;
    case DeploymentDomainSource::kUserAccepted:
    case DeploymentDomainSource::kBakedDefault:
      break;
  }
  // Level 4/5: locked only by the explicit dedicated restrict policy.
  return restrict_change_forced;
}

std::optional<std::string> NormalizeDeploymentDomain(std::string_view input) {
  std::string trimmed(base::TrimWhitespaceASCII(input, base::TRIM_ALL));
  if (trimmed.empty()) {
    return std::nullopt;
  }
  // Reject any embedded ASCII control character or space before parsing. GURL
  // would otherwise *silently strip* tab/LF/CR (per the URL spec) or
  // percent-encode a space into the host, both of which fabricate a host the
  // caller never typed. A bare host[:port] contains none of these. (Non-ASCII
  // IDN bytes are >= 0x80 and unaffected: IsAsciiControl returns false for them,
  // so "bücher.example" still reaches GURL's punycode path.)
  for (char c : trimmed) {
    if (base::IsAsciiControl(c) || c == ' ') {
      return std::nullopt;
    }
  }
  // Parse via GURL with a synthetic https scheme, then re-extract host/port. Any
  // userinfo, path, query, or fragment means the input was not a bare host[:port].
  GURL url("https://" + trimmed);
  if (!url.is_valid() || !url.SchemeIs("https")) {
    return std::nullopt;
  }
  if (url.has_username() || url.has_password() || url.has_ref() ||
      url.has_query()) {
    return std::nullopt;
  }
  // Reject any non-root path (GURL synthesizes "/" for a bare host).
  if (url.path() != "/") {
    return std::nullopt;
  }
  // GURL::host() lowercases + punycodes the host. Note: in this Chromium
  // version host()/port()/path() return std::string_view (LIFETIME_BOUND to
  // `url`), not std::string, so materialize before `url` goes out of scope.
  std::string_view host = url.host();
  // GURL's host canonicalization permits (but does not strip) a trailing dot
  // (the DNS absolute-name root label) — trim it here so the "no trailing
  // dot" canonical-form invariant holds unconditionally.
  while (!host.empty() && host.back() == '.') {
    host.remove_suffix(1);
  }
  if (host.empty() || url.HostIsIPAddress()) {
    return std::nullopt;  // Deployment domains are named hosts, not IP literals.
  }
  // Enforce the canonical host charset directly: lowercase [a-z0-9.-] only
  // (punycode "xn--" labels stay within this set). This catches illegal host
  // bytes that pass the input guard (not control/space) yet GURL leaves inside
  // a valid host — e.g. a backtick, which GURL keeps as a literal byte rather
  // than rejecting. The port is validated separately by GURL.
  for (char c : host) {
    if (!(base::IsAsciiLower(c) || base::IsAsciiDigit(c) || c == '.' ||
          c == '-')) {
      return std::nullopt;
    }
  }
  std::string result(host);
  if (url.has_port()) {
    result += ":";
    result += url.port();
  }
  return result;
}

DeploymentResolution SelectDeploymentDomain(
    std::optional<std::string> command_line,
    std::optional<std::string> managed_pref,
    std::optional<std::string> machine_file,
    std::optional<std::string> user_accepted,
    std::string baked_default) {
  if (command_line) {
    return {std::move(*command_line), DeploymentDomainSource::kCommandLine};
  }
  if (managed_pref) {
    return {std::move(*managed_pref), DeploymentDomainSource::kManagedPref};
  }
  if (machine_file) {
    return {std::move(*machine_file), DeploymentDomainSource::kMachineFile};
  }
  if (user_accepted) {
    return {std::move(*user_accepted), DeploymentDomainSource::kUserAccepted};
  }
  return {std::move(baked_default), DeploymentDomainSource::kBakedDefault};
}

std::optional<std::string> ParseDeploymentConfigJson(std::string_view contents) {
  std::optional<base::Value> value =
      base::JSONReader::Read(contents, base::JSON_PARSE_RFC);
  if (!value || !value->is_dict()) {
    return std::nullopt;
  }
  const std::string* domain = value->GetDict().FindString("domain");
  if (!domain) {
    return std::nullopt;
  }
  return NormalizeDeploymentDomain(*domain);
}

bool IsMachineConfigFileTrusted(const base::FilePath& path) {
  struct stat st;
  if (::lstat(path.value().c_str(), &st) != 0) {
    return false;  // Missing or unstattable.
  }
  if (!S_ISREG(st.st_mode)) {
    return false;  // Not a regular file (symlink/dir/device).
  }
  if (st.st_uid != 0) {
    return false;  // Must be root-owned.
  }
  if (st.st_mode & (S_IWGRP | S_IWOTH)) {
    return false;  // Must not be group/world writable.
  }
  return true;
}

std::string TeleportHostFor(std::string_view d) {
  // Straight prefix concat: the "teleport." label goes in front of D. When D
  // carries a ":port" it is already at D's tail, so the port stays at the tail
  // of the result — correct for host:port order.
  return "teleport." + std::string(d);
}

std::string AccountsHostFor(std::string_view d) {
  return "accounts." + std::string(d);
}

std::string DomainHostOnlyFor(std::string_view d) {
  // Return the host without any ":port" (the leading dot for the gate suffix is
  // added by DeploymentEnrollmentDomainSuffix, not here). Canonical D has no
  // internal colon, so the only colon is the port separator.
  size_t colon = d.rfind(':');
  return std::string(colon == std::string_view::npos ? d : d.substr(0, colon));
}

std::string DeploymentDeviceManagementServerUrl() {
  return "https://" + TeleportHostFor(DeploymentDomain()) +
         "/dm/devicemanagement/data/api";
}

std::string DeploymentEncryptedReportingUrl() {
  return "https://" + TeleportHostFor(DeploymentDomain()) + "/dm/v1/record";
}

std::string DeploymentRealtimeReportingUrl() {
  return "https://" + TeleportHostFor(DeploymentDomain()) + "/dm/v1/events";
}

std::string DeploymentEnrollUrl() {
  return "https://" + TeleportHostFor(DeploymentDomain()) + "/enroll/start";
}

std::string DeploymentRegisterHandlerUrl() {
  return "https://" + TeleportHostFor(DeploymentDomain()) +
         "/enroll/profile-enrollment/register-handler";
}

std::string DeploymentTrustedRedirectHost() {
  return "https://" + TeleportHostFor(DeploymentDomain());
}

std::string DeploymentEnrollmentDomainSuffix() {
  return "." + DomainHostOnlyFor(DeploymentDomain());
}

}  // namespace teleport
