// Copyright 2026 BeanSec.
#ifndef TELEPORT_COMMON_TELEPORT_URL_SCHEME_H_
#define TELEPORT_COMMON_TELEPORT_URL_SCHEME_H_

class GURL;
namespace content {
class BrowserContext;
}

namespace teleport {

// Teleport-branded alias for content::kChromeUIScheme ("chrome").
inline constexpr char kTeleportScheme[] = "teleport";

// The chrome://chrome-urls directory page is presented under our brand host
// (teleport://teleport-urls): the rewrites below remap this host in addition to
// swapping the scheme. All other hosts keep their name.
inline constexpr char kChromeUrlsHost[] = "chrome-urls";
inline constexpr char kTeleportUrlsHost[] = "teleport-urls";

// Navigation rewrite: teleport://host/path... -> chrome://host/path...
// Returns true and rewrites |url| in place when its scheme is "teleport";
// returns false (|url| unchanged) otherwise. Signature matches
// content::BrowserURLHandler::URLHandler; |browser_context| is unused.
bool RewriteTeleportToChrome(GURL* url, content::BrowserContext* browser_context);

// Display rewrite: chrome://host/path... -> teleport://host/path...
// Returns true and rewrites |url| when its scheme is "chrome"; false otherwise.
bool RewriteChromeToTeleport(GURL* url, content::BrowserContext* browser_context);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_URL_SCHEME_H_
