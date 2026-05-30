#include "teleport/common/teleport_channel.h"

#include "build/build_config.h"

namespace teleport {

version_info::Channel ChannelFromName(std::string_view name) {
  if (name == "canary")
    return version_info::Channel::CANARY;
  if (name == "beta")
    return version_info::Channel::BETA;
  if (name == "stable")
    return version_info::Channel::STABLE;
  return version_info::Channel::UNKNOWN;
}

#if !BUILDFLAG(IS_MAC)
// Non-mac platforms are a later phase; until they have a real channel source,
// report no channel (-> UNKNOWN) rather than guessing.
std::string ReadChannelNameFromBundle() {
  return std::string();
}
#endif

}  // namespace teleport
