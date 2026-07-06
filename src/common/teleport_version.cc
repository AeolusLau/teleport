#include "teleport/common/teleport_version.h"

#include "components/version_info/version_info.h"

namespace teleport {

std::string GetDisplayVersion() {
  std::string version(version_info::GetVersionNumber());
  if (!version_info::IsOfficialBuild()) {
    version += "-dev";
  }
  return version;
}

}  // namespace teleport
