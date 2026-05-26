// Copyright 2026 BeanSec.
#include "teleport/common/teleport_url_scheme.h"

#include <string_view>

#include "content/public/common/url_constants.h"
#include "url/gurl.h"

namespace teleport {

bool RewriteTeleportToChrome(GURL* url, content::BrowserContext* /*unused*/) {
  if (!url->SchemeIs(kTeleportScheme)) {
    return false;
  }
  GURL::Replacements replacements;
  replacements.SetSchemeStr(content::kChromeUIScheme);
  // teleport://teleport-urls is chrome://chrome-urls underneath.
  if (url->host() == kTeleportUrlsHost) {
    replacements.SetHostStr(kChromeUrlsHost);
  }
  *url = url->ReplaceComponents(replacements);
  return true;
}

bool RewriteChromeToTeleport(GURL* url, content::BrowserContext* /*unused*/) {
  if (!url->SchemeIs(content::kChromeUIScheme)) {
    return false;
  }
  GURL::Replacements replacements;
  replacements.SetSchemeStr(kTeleportScheme);
  // Present chrome://chrome-urls under our brand host teleport://teleport-urls.
  if (url->host() == kChromeUrlsHost) {
    replacements.SetHostStr(kTeleportUrlsHost);
  }
  *url = url->ReplaceComponents(replacements);
  return true;
}

}  // namespace teleport
