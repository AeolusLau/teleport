#ifndef TELEPORT_COMMON_TELEPORT_VERSION_H_
#define TELEPORT_COMMON_TELEPORT_VERSION_H_

#include <string>

namespace teleport {

// The version string shown in the About page and chrome://version. On macOS
// this is the bundle's CFBundleShortVersionString (stamped to TELEPORT_VERSION
// at packaging time). Never exposes the upstream Chromium version number.
std::string GetDisplayVersion();

// Pure resolver behind GetDisplayVersion(), separated for testing.
// `bundle_short_version` is the app bundle's CFBundleShortVersionString;
// `chromium_version` is version_info::GetVersionNumber(). Returns a "0.0.0-dev"
// placeholder when the bundle was not stamped with a Teleport version (i.e. it
// still equals the compiled-in Chromium version, or is empty) so the Chromium
// version is never displayed.
std::string ResolveDisplayVersion(const std::string& bundle_short_version,
                                  const std::string& chromium_version);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_VERSION_H_
