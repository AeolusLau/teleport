#include "teleport/common/teleport_feed_url.h"

namespace teleport {

bool IsSecureFeedUrl(std::string_view url) {
  constexpr std::string_view kHttps = "https://";
  return url.size() > kHttps.size() && url.substr(0, kHttps.size()) == kHttps;
}

}  // namespace teleport
