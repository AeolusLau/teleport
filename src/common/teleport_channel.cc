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
  // "staging" is a deployment ENVIRONMENT that borrows a channel slot (it drives
  // the bundle id suffix and data dir the same way a channel does). It still has
  // to report a channel version_info recognizes: staging exists to rehearse what
  // a release build does, and upstream gates a fair amount of behaviour on
  // `channel != STABLE`. Falling through to UNKNOWN would pair
  // is_official_build=true with a channel nothing upstream was written against,
  // and would silently disable the channel-alignment fix for the upgrade badge --
  // which is the visible end of the Sparkle path staging is meant to exercise.
  if (name == "staging")
    return version_info::Channel::CANARY;
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
