#ifndef TELEPORT_COMMON_TELEPORT_VERSION_H_
#define TELEPORT_COMMON_TELEPORT_VERSION_H_

#include <string>

namespace teleport {

// The version string shown in the About page and chrome://version: the baked
// 4-segment product version (chrome/VERSION is generated from
// TELEPORT_VERSION at overlay time), with a "-dev" suffix on non-official
// builds. Never exposes the upstream Chromium version — the engine version
// exists only in the UA / UA-CH surface.
std::string GetDisplayVersion();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_VERSION_H_
