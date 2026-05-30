#ifndef TELEPORT_COMMON_TELEPORT_CHANNEL_H_
#define TELEPORT_COMMON_TELEPORT_CHANNEL_H_

#include <string>
#include <string_view>

#include "components/version_info/channel.h"

namespace teleport {

// Maps a TeleportChannel Info.plist string to a runtime release channel.
// "canary"->CANARY, "beta"->BETA, "stable"->STABLE; anything else (empty,
// "dev", or an unrecognized value) maps to UNKNOWN -- the honest value for a
// from-source / unstamped build. Pure; separated for testing.
version_info::Channel ChannelFromName(std::string_view name);

// Reads the main bundle's TeleportChannel key (stamped at packaging time),
// returning "" when absent. On non-mac platforms this is a stub returning ""
// until those platforms grow a real channel source.
std::string ReadChannelNameFromBundle();

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_CHANNEL_H_
