#include "teleport/common/teleport_channel.h"

#import <Foundation/Foundation.h>

#include "base/strings/sys_string_conversions.h"

namespace teleport {

std::string ReadChannelNameFromBundle() {
  NSString* channel = [[NSBundle mainBundle]
      objectForInfoDictionaryKey:@"TeleportChannel"];
  return channel ? base::SysNSStringToUTF8(channel) : std::string();
}

}  // namespace teleport
