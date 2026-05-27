#ifndef TELEPORT_COMMON_TELEPORT_FEED_URL_H_
#define TELEPORT_COMMON_TELEPORT_FEED_URL_H_

#include <string_view>

namespace teleport {

// True only for an https:// URL. The updater refuses to start with anything
// else (defense-in-depth alongside the EdDSA appcast signature).
bool IsSecureFeedUrl(std::string_view url);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_FEED_URL_H_
