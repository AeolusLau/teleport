#ifndef TELEPORT_BROWSER_TELEPORT_DEPLOYMENT_LEVEL4_H_
#define TELEPORT_BROWSER_TELEPORT_DEPLOYMENT_LEVEL4_H_

#include <optional>
#include <string>

class PrefRegistrySimple;

namespace teleport {

// Reads the level-4 user-accepted deployment domain from Local State and
// re-verifies it OFFLINE against the baked policy-verification root key
// (message_type / domain / expiry), returning the normalized domain or nullopt.
// Compiled into //chrome/browser (needs g_browser_process + the baked key), NOT
// the //base+//url deployment-config leaf — the leaf consumes this only through
// the injected UserAcceptedDomainReader callback.
std::optional<std::string> ReadVerifiedUserAcceptedDomain();

// Registers the level-4 Local State dict pref and wires ReadVerifiedUserAccepted
// Domain in as the leaf's UserAcceptedDomainReader. Called from
// browser_prefs.cc's RegisterLocalState — early enough that the reader is
// registered before the first DeploymentDomain() resolution.
void RegisterServerIdentityLevel4(PrefRegistrySimple* registry);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_TELEPORT_DEPLOYMENT_LEVEL4_H_
