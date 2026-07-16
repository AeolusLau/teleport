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

// Level 1: dev-only command-line switch. Compiled OUT of release binaries so it
// is not merely disabled but absent (Global Constraint: release has no backdoor).
std::optional<std::string> ReadCommandLineDomain() {
#if !BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  const base::CommandLine* cmd = base::CommandLine::ForCurrentProcess();
  if (!cmd->HasSwitch("teleport-deployment-domain")) {
    return std::nullopt;
  }
  std::optional<std::string> d = NormalizeDeploymentDomain(
      cmd->GetSwitchValueASCII("teleport-deployment-domain"));
  if (!d) {
    LOG(ERROR) << "[teleport-deployment] --teleport-deployment-domain invalid";
  }
  return d;
#else
  return std::nullopt;
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
