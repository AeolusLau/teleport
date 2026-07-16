#include "teleport/common/teleport_enrollment_gate_logic.h"

#include <string>
#include <string_view>
#include <vector>

#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "teleport/common/teleport_enterprise_urls.h"
#include "url/gurl.h"

namespace teleport {

namespace {

// A bare host[:port] uses only lowercase host chars + an optional numeric port.
bool IsCanonicalHostPort(std::string_view s) {
  for (char c : s) {
    if (!(base::IsAsciiLower(c) || base::IsAsciiDigit(c) || c == '.' ||
          c == '-' || c == ':')) {
      return false;
    }
  }
  return true;
}

// Cap injected hosts so a hostile header cannot bloat the whitelist unboundedly.
constexpr size_t kMaxInjectedHosts = 8;

}  // namespace

bool IsEnrollmentFlowUrl(const GURL& url) {
  if (!url.is_valid() || !url.SchemeIs("https")) {
    return false;
  }
  // Exact host[:port] membership (§3.4a): a request is part of the enrollment
  // flow only if its host equals one of the whitelisted hosts — NOT if it merely
  // shares the deployment domain's suffix. The former ".<D>" suffix wildcard let
  // ANY *.<D> host through, which is unacceptable once D can be a customer's own
  // internal domain. The default https port is omitted so it compares equal to a
  // portless allowed host; when D carries a :port it is present on both sides.
  std::string host_port(url.host());
  if (url.has_port()) {
    host_port += ":";
    host_port += url.port();
  }
  for (const std::string& allowed : EnterpriseEnrollmentAllowedHosts()) {
    if (host_port == allowed) {
      return true;
    }
  }
  return false;
}

bool ShouldBlockNavigation(bool should_gate,
                           bool is_enrolled,
                           bool is_main_frame,
                           const GURL& url) {
  if (!should_gate || is_enrolled) {
    return false;
  }
  if (!is_main_frame) {
    return false;
  }
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return false;  // Pass through chrome://, about:, and other internal pages.
  }
  return !IsEnrollmentFlowUrl(url);
}

std::vector<std::string> ParseInjectableEnrollmentHosts(
    std::string_view header_value,
    std::string_view deployment_suffix) {
  std::vector<std::string> out;
  // deployment_suffix must be at least ".x" for a strict subdomain to exist.
  if (deployment_suffix.size() < 2 || deployment_suffix.front() != '.') {
    return out;
  }
  for (std::string_view token :
       base::SplitStringPiece(header_value, ",", base::TRIM_WHITESPACE,
                              base::SPLIT_WANT_NONEMPTY)) {
    if (out.size() >= kMaxInjectedHosts) {
      break;
    }
    // Must be a canonical bare host[:port] (no scheme/path/userinfo/space/upper).
    if (!IsCanonicalHostPort(token)) {
      continue;
    }
    // Split an optional trailing :port off for the suffix check; the port stays
    // in the stored value so the gate's host[:port] comparison matches (a port
    // only ever appears when D itself carries one).
    std::string_view host = token;
    const size_t colon = token.rfind(':');
    if (colon != std::string_view::npos) {
      const std::string_view port = token.substr(colon + 1);
      if (port.empty() ||
          port.find_first_not_of("0123456789") != std::string_view::npos) {
        continue;  // non-numeric / empty port -> not a valid host:port
      }
      host = token.substr(0, colon);
    }
    // The host must be a STRICT subdomain of D: end with the suffix, with a
    // non-empty label in front (so the apex host-of-D itself is not injectable,
    // and only OTHER hosts under the same trusted deployment domain are added).
    if (host.size() <= deployment_suffix.size() ||
        host.substr(host.size() - deployment_suffix.size()) !=
            deployment_suffix) {
      continue;
    }
    out.emplace_back(token);
  }
  return out;
}

}  // namespace teleport
