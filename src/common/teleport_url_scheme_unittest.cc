// Copyright 2026 The Teleport Authors
#include "teleport/common/teleport_url_scheme.h"

#include "testing/gtest/include/gtest/gtest.h"
#include "url/gurl.h"
#include "url/url_util.h"

namespace teleport {
namespace {

// teleport:// must be a standard (SCHEME_WITH_HOST) scheme for GURL to parse
// host/path; register it for the duration of the test.
class TeleportUrlSchemeTest : public testing::Test {
 public:
  TeleportUrlSchemeTest() {
    // |scoped_registry_| (declared below) is constructed before this body runs
    // by C++ member-init order, so the scheme registry is modifiable here.
    url::AddStandardScheme(kTeleportScheme, url::SCHEME_WITH_HOST);
    // "chrome" must be standard too so host_piece() parses for the host remap.
    url::AddStandardScheme("chrome", url::SCHEME_WITH_HOST);
  }

 private:
  url::ScopedSchemeRegistryForTests scoped_registry_;
};

TEST_F(TeleportUrlSchemeTest, ForwardRewritesSchemeOnly) {
  GURL url("teleport://settings/passwords?q=1#frag");
  EXPECT_TRUE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_EQ(url.spec(), "chrome://settings/passwords?q=1#frag");
}

TEST_F(TeleportUrlSchemeTest, ReverseRewritesSchemeOnly) {
  GURL url("chrome://settings/passwords?q=1#frag");
  EXPECT_TRUE(RewriteChromeToTeleport(&url, nullptr));
  EXPECT_EQ(url.spec(), "teleport://settings/passwords?q=1#frag");
}

TEST_F(TeleportUrlSchemeTest, RoundTrip) {
  GURL url("teleport://version/");
  EXPECT_TRUE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_TRUE(RewriteChromeToTeleport(&url, nullptr));
  EXPECT_EQ(url.spec(), "teleport://version/");
}

TEST_F(TeleportUrlSchemeTest, ForwardIsNoOpForChrome) {
  GURL url("chrome://settings/");
  EXPECT_FALSE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_EQ(url.spec(), "chrome://settings/");
}

TEST_F(TeleportUrlSchemeTest, ReverseIsNoOpForNonChrome) {
  for (const char* spec :
       {"chrome-untrusted://foo/", "devtools://devtools/bundled/x.html",
        "https://example.com/", "chrome-extension://abc/x.html"}) {
    GURL url(spec);
    EXPECT_FALSE(RewriteChromeToTeleport(&url, nullptr)) << spec;
    EXPECT_EQ(url.spec(), GURL(spec).spec()) << spec;
  }
}

TEST_F(TeleportUrlSchemeTest, HostOnlyNoPath) {
  GURL url("teleport://version");
  EXPECT_TRUE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_EQ(url.spec(), "chrome://version/");
}

TEST_F(TeleportUrlSchemeTest, ReverseRemapsChromeUrlsHost) {
  GURL url("chrome://chrome-urls/");
  EXPECT_TRUE(RewriteChromeToTeleport(&url, nullptr));
  EXPECT_EQ(url.spec(), "teleport://teleport-urls/");
}

TEST_F(TeleportUrlSchemeTest, ForwardRemapsTeleportUrlsHost) {
  GURL url("teleport://teleport-urls/");
  EXPECT_TRUE(RewriteTeleportToChrome(&url, nullptr));
  EXPECT_EQ(url.spec(), "chrome://chrome-urls/");
}

TEST_F(TeleportUrlSchemeTest, OnlyTheChromeUrlsHostIsRemapped) {
  GURL url("chrome://settings/");
  EXPECT_TRUE(RewriteChromeToTeleport(&url, nullptr));
  EXPECT_EQ(url.spec(), "teleport://settings/");  // host preserved
}

}  // namespace
}  // namespace teleport
