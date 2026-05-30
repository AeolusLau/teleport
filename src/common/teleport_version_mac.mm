#include "teleport/common/teleport_version.h"

#import <Foundation/Foundation.h>

#include "base/strings/sys_string_conversions.h"
#include "components/version_info/version_info.h"

namespace teleport {

std::string GetDisplayVersion() {
  NSString* short_version = [[NSBundle mainBundle]
      objectForInfoDictionaryKey:@"CFBundleShortVersionString"];
  std::string bundle =
      short_version ? base::SysNSStringToUTF8(short_version) : std::string();
  return ResolveDisplayVersion(bundle,
                               std::string(version_info::GetVersionNumber()));
}

}  // namespace teleport
