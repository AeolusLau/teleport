#include "teleport/common/teleport_deployment_config.h"

#import <Foundation/Foundation.h>

#include <optional>
#include <string>

#include "base/apple/foundation_util.h"
#include "base/apple/scoped_cftyperef.h"
#include "base/command_line.h"
#include "base/logging.h"
#include "base/strings/sys_string_conversions.h"
#include "teleport/teleport_policy_buildflags.h"

namespace teleport {

namespace {

// Mirror of teleport::kManagedPrefsBundleId (teleport_enterprise_enrollment.h,
// in the :teleport source_set). Copied (not #included) to keep
// teleport_deployment_config free of a dependency on :teleport, which pulls
// //content and would create a cycle with //components/policy (which depends
// on teleport_deployment_config for endpoint derivation). Keep in sync — both
// derive from the fixed base bundle id.
constexpr char kManagedPrefsBundleId[] = "cn.douan.Teleport";

}  // namespace

// Level 1: command-line switch, compiled OUT of release builds so it is not
// merely disabled but absent (Global Constraint: release has no backdoor).
// staging keeps it: staging exists to be poked at, and the switch can only
// redirect the endpoint, never the trust anchor — a staging binary aimed at an
// attacker's server still cannot be handed policy that verifies.
std::optional<std::string> ReadCommandLineDomain() {
#if BUILDFLAG(TELEPORT_ALLOWS_DOMAIN_OVERRIDE)
  const base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();
  const bool present = cmd->HasSwitch("teleport-deployment-domain");
  return SelectCommandLineDomain(
      /*allows_override=*/true, present,
      present ? cmd->GetSwitchValueASCII("teleport-deployment-domain")
              : std::string());
#else
  // Release: the switch-reading code is not compiled at all, so the capability
  // is absent rather than disabled. Routing the answer through the same pure
  // function keeps both branches honest about what they return.
  return SelectCommandLineDomain(/*allows_override=*/false,
                                 /*switch_present=*/false, std::string_view());
#endif
}

// Level 2: managed preference, read the SAME way the enrollment token is read
// (browser_dm_token_storage_mac.mm) — the configuration management system is not
// up this early, so read CFPreferences directly. CRITICAL: require
// CFPreferencesAppValueIsForced so that only an MDM-FORCED value is honored; a
// plain user-domain ~/Library/Preferences plist must NOT be trusted (else a
// non-privileged local user could inject a domain over the verified level-4
// entry — Global Constraint / spec D13).
std::optional<std::string> ReadManagedPrefDomain() {
  base::apple::ScopedCFTypeRef<CFStringRef> bundle_id(
      base::SysUTF8ToCFStringRef(kManagedPrefsBundleId));
  base::apple::ScopedCFTypeRef<CFStringRef> key(
      base::SysUTF8ToCFStringRef("DeploymentDomain"));
  base::apple::ScopedCFTypeRef<CFPropertyListRef> value(
      CFPreferencesCopyAppValue(key.get(), bundle_id.get()));
  if (!value ||
      !CFPreferencesAppValueIsForced(key.get(), bundle_id.get())) {
    return std::nullopt;
  }
  CFStringRef str = base::apple::CFCast<CFStringRef>(value.get());
  if (!str) {
    return std::nullopt;
  }
  std::optional<std::string> d =
      NormalizeDeploymentDomain(base::SysCFStringRefToUTF8(str));
  if (!d) {
    LOG(ERROR) << "[teleport-deployment] managed DeploymentDomain invalid";
  }
  return d;
}

// §4.6 corp-managed lock: dedicated boolean policy, read forced-only (same trust
// gate as the level-2 domain) so a plain user-writable pref cannot self-lock.
bool ReadRestrictDomainChangeForced() {
  base::apple::ScopedCFTypeRef<CFStringRef> bundle_id(
      base::SysUTF8ToCFStringRef(kManagedPrefsBundleId));
  base::apple::ScopedCFTypeRef<CFStringRef> key(
      base::SysUTF8ToCFStringRef("RestrictDeploymentDomainChange"));
  base::apple::ScopedCFTypeRef<CFPropertyListRef> value(
      CFPreferencesCopyAppValue(key.get(), bundle_id.get()));
  if (!value || !CFPreferencesAppValueIsForced(key.get(), bundle_id.get())) {
    return false;
  }
  CFBooleanRef b = base::apple::CFCast<CFBooleanRef>(value.get());
  return b && CFBooleanGetValue(b);
}

}  // namespace teleport
