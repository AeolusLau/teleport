#include "teleport/common/teleport_deployment_config.h"

#include <optional>

#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/files/scoped_temp_dir.h"
#include "teleport/teleport_policy_buildflags.h"
#include "base/functional/bind.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// A file owned by the (non-root) test user must be rejected: the machine config
// file is a root-only trust channel.
TEST(TeleportDeploymentConfigTrustTest, RejectsNonRootOwnedFile) {
  base::ScopedTempDir dir;
  ASSERT_TRUE(dir.CreateUniqueTempDir());
  base::FilePath path = dir.GetPath().AppendASCII("DeploymentConfig.json");
  ASSERT_TRUE(base::WriteFile(path, R"({"domain":"acme.internal"})"));
  // Test process runs as a non-root user, so the file is not uid==0-owned.
  EXPECT_FALSE(IsMachineConfigFileTrusted(path));
}

TEST(TeleportDeploymentConfigTrustTest, RejectsMissingFile) {
  base::ScopedTempDir dir;
  ASSERT_TRUE(dir.CreateUniqueTempDir());
  EXPECT_FALSE(
      IsMachineConfigFileTrusted(dir.GetPath().AppendASCII("nonexistent.json")));
}

// With no higher-priority source set (fresh process, no switch/pref/file),
// DeploymentDomain() must return the baked default for this build variant and
// report kBakedDefault as its source.
TEST(TeleportDeploymentConfigTest, FallsBackToBakedDefault) {
  EXPECT_FALSE(DeploymentDomain().empty());
  EXPECT_EQ(DeploymentDomainSourceLevel(), DeploymentDomainSource::kBakedDefault);
#if BUILDFLAG(TELEPORT_USE_RELEASE_ENDPOINTS)
  EXPECT_EQ(DeploymentDomain(), "douan.cn");
#else
  EXPECT_EQ(DeploymentDomain(), "fairyland.io");
#endif
}

// The chrome://version diagnostic line renders DeploymentDomainSourceLabel()
// verbatim (see version_ui.cc); pin its exact text for the baked-default case
// so that consumer doesn't silently drift from what support docs quote.
TEST(TeleportDeploymentConfigTest, SourceLabelForBakedDefault) {
  EXPECT_EQ(DeploymentDomainSourceLevel(), DeploymentDomainSource::kBakedDefault);
  EXPECT_EQ(DeploymentDomainSourceLabel(), "built-in default");
}

TEST(TeleportDeploymentConfigNormalizeTest, AcceptsBareHost) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal"), "acme.internal");
}

TEST(TeleportDeploymentConfigNormalizeTest, LowercasesAndStripsTrailingDot) {
  EXPECT_EQ(NormalizeDeploymentDomain("ACME.Internal."), "acme.internal");
}

TEST(TeleportDeploymentConfigNormalizeTest, KeepsExplicitPort) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal:8443"), "acme.internal:8443");
}

TEST(TeleportDeploymentConfigNormalizeTest, ConvertsIdnToPunycode) {
  // "xn--" is the punycode ASCII form; a Unicode label must normalize to it.
  EXPECT_EQ(NormalizeDeploymentDomain("bücher.example"), "xn--bcher-kva.example");
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsUserinfo) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal:8443@evil.com"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsPathAndQuery) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal/enroll"), std::nullopt);
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal?x=1"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsScheme) {
  EXPECT_EQ(NormalizeDeploymentDomain("https://acme.internal"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsEmptyAndGarbage) {
  EXPECT_EQ(NormalizeDeploymentDomain(""), std::nullopt);
  EXPECT_EQ(NormalizeDeploymentDomain("   "), std::nullopt);
}

// Embedded whitespace/control bytes are caught by the INPUT guard before GURL
// can mangle them: a space would otherwise be percent-encoded into the host and
// a tab silently stripped, either way fabricating a host the caller never typed.
TEST(TeleportDeploymentConfigNormalizeTest, RejectsEmbeddedWhitespace) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme .internal"), std::nullopt);
  EXPECT_EQ(NormalizeDeploymentDomain("acme\t.internal"), std::nullopt);
}

// Regression pins for already-correct behavior (IP literals rejected, multiple
// trailing dots stripped to the bare host).
TEST(TeleportDeploymentConfigNormalizeTest, RejectsIpv4Literal) {
  EXPECT_EQ(NormalizeDeploymentDomain("192.168.1.1"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsIpv6Literal) {
  EXPECT_EQ(NormalizeDeploymentDomain("[::1]"), std::nullopt);
}

TEST(TeleportDeploymentConfigNormalizeTest, StripsMultipleTrailingDots) {
  EXPECT_EQ(NormalizeDeploymentDomain("acme.internal.."), "acme.internal");
}

TEST(TeleportDeploymentConfigNormalizeTest, RejectsNonCanonicalHostBytes) {
  // A backtick is neither a control char nor a space, so it passes the input
  // guard; GURL keeps it as a literal byte in a still-valid host rather than
  // stripping it. Because a backtick is outside the canonical [a-z0-9.-] set,
  // the OUTPUT charset guard is what rejects this — the only case that
  // exercises the output gate's rejection branch (verified: input gate does not
  // catch it, GURL host retains the literal 0x60 byte).
  EXPECT_EQ(NormalizeDeploymentDomain("ac`me.internal"), std::nullopt);
}

TEST(TeleportDeploymentConfigSelectTest, PrefersCommandLineOverAll) {
  auto r = SelectDeploymentDomain("cli.example", "pref.example", "file.example",
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "cli.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kCommandLine);
}

TEST(TeleportDeploymentConfigSelectTest, ManagedPrefBeatsFileAndBaked) {
  auto r = SelectDeploymentDomain(std::nullopt, "pref.example", "file.example",
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "pref.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kManagedPref);
}

TEST(TeleportDeploymentConfigSelectTest, FileBeatsBaked) {
  auto r = SelectDeploymentDomain(std::nullopt, std::nullopt, "file.example",
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "file.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kMachineFile);
}

TEST(TeleportDeploymentConfigSelectTest, FallsToBakedWhenAllAbsent) {
  auto r = SelectDeploymentDomain(std::nullopt, std::nullopt, std::nullopt,
                                  std::nullopt, "baked.example");
  EXPECT_EQ(r.domain, "baked.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kBakedDefault);
}

TEST(TeleportDeploymentConfigSelectTest, UserAcceptedSitsAboveBakedOnly) {
  auto r = SelectDeploymentDomain(std::nullopt, std::nullopt, std::nullopt,
                                  "user.example", "baked.example");
  EXPECT_EQ(r.domain, "user.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kUserAccepted);
}

TEST(TeleportDeploymentConfigSelectTest, CommandLineBeatsUserAccepted) {
  auto r = SelectDeploymentDomain("cli.example", std::nullopt, std::nullopt,
                                  "user.example", "baked.example");
  EXPECT_EQ(r.domain, "cli.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kCommandLine);
}

TEST(TeleportDeploymentConfigSelectTest, ManagedPrefBeatsUserAccepted) {
  auto r = SelectDeploymentDomain(std::nullopt, "pref.example", std::nullopt,
                                  "user.example", "baked.example");
  EXPECT_EQ(r.domain, "pref.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kManagedPref);
}

TEST(TeleportDeploymentConfigSelectTest, MachineFileBeatsUserAccepted) {
  auto r = SelectDeploymentDomain(std::nullopt, std::nullopt, "file.example",
                                  "user.example", "baked.example");
  EXPECT_EQ(r.domain, "file.example");
  EXPECT_EQ(r.source, DeploymentDomainSource::kMachineFile);
}

TEST(TeleportDeploymentConfigJsonTest, ExtractsAndNormalizesDomain) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"domain":"ACME.Internal"})"),
            "acme.internal");
}

TEST(TeleportDeploymentConfigJsonTest, IgnoresReservedFields) {
  EXPECT_EQ(ParseDeploymentConfigJson(
                R"({"domain":"acme.internal","update_feed_url":"x"})"),
            "acme.internal");
}

TEST(TeleportDeploymentConfigJsonTest, RejectsMissingDomain) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"update_feed_url":"x"})"),
            std::nullopt);
}

TEST(TeleportDeploymentConfigJsonTest, RejectsNonStringDomain) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"domain":42})"), std::nullopt);
}

TEST(TeleportDeploymentConfigJsonTest, RejectsInvalidDomainValue) {
  EXPECT_EQ(ParseDeploymentConfigJson(R"({"domain":"https://acme.internal/x"})"),
            std::nullopt);
}

TEST(TeleportDeploymentConfigJsonTest, RejectsMalformedJson) {
  EXPECT_EQ(ParseDeploymentConfigJson("{not json"), std::nullopt);
  EXPECT_EQ(ParseDeploymentConfigJson(""), std::nullopt);
}

TEST(TeleportDeploymentConfigJsonTest, RejectsNonDictJson) {
  EXPECT_EQ(ParseDeploymentConfigJson("[1,2,3]"), std::nullopt);       // top-level array
  EXPECT_EQ(ParseDeploymentConfigJson("\"just-a-string\""), std::nullopt);  // top-level string
  EXPECT_EQ(ParseDeploymentConfigJson("42"), std::nullopt);            // top-level number
}

TEST(TeleportDeploymentDeriveTest, DerivesTeleportHostUrls) {
  // Uses the baked default (no source override in this test process).
  const std::string d = DeploymentDomain();
  EXPECT_EQ(DeploymentDeviceManagementServerUrl(),
            "https://teleport." + d + "/dm/devicemanagement/data/api");
  EXPECT_EQ(DeploymentEncryptedReportingUrl(),
            "https://teleport." + d + "/dm/v1/record");
  EXPECT_EQ(DeploymentRealtimeReportingUrl(),
            "https://teleport." + d + "/dm/v1/events");
  EXPECT_EQ(DeploymentEnrollUrl(), "https://teleport." + d + "/enroll/start");
  EXPECT_EQ(DeploymentRegisterHandlerUrl(),
            "https://teleport." + d + "/enroll/profile-enrollment/register-handler");
  EXPECT_EQ(DeploymentTrustedRedirectHost(), "https://teleport." + d);
}

TEST(TeleportDeploymentDeriveTest, SuffixIsHostOnlyWithLeadingDot) {
  // Suffix must start with a dot and never carry a port.
  const std::string suffix = DeploymentEnrollmentDomainSuffix();
  ASSERT_FALSE(suffix.empty());
  EXPECT_EQ('.', suffix.front());
  EXPECT_EQ(suffix.find(':'), std::string::npos);
  EXPECT_EQ(DeploymentEnrollmentDomainSuffix(), "." + DeploymentDomain());
}

// Direct coverage of the port-handling seam: DeploymentDomain() has no port in
// the test process, so exercise the branch through the parameterized helpers.
TEST(TeleportDeploymentDeriveTest, TeleportHostForPreservesPort) {
  EXPECT_EQ(TeleportHostFor("acme.internal:8443"), "teleport.acme.internal:8443");
  EXPECT_EQ(TeleportHostFor("acme.internal"), "teleport.acme.internal");
}

TEST(TeleportDeploymentDeriveTest, DomainHostOnlyForStripsPort) {
  EXPECT_EQ(DomainHostOnlyFor("acme.internal:8443"), "acme.internal");
  EXPECT_EQ(DomainHostOnlyFor("acme.internal"), "acme.internal");
}

// Level-4 injection seam: ReadUserAcceptedDomain runs the registered reader, or
// returns nullopt when none is registered.
TEST(TeleportDeploymentConfigUserAcceptedTest, UnregisteredReturnsNullopt) {
  SetUserAcceptedDomainReader({});  // ensure unregistered
  EXPECT_EQ(ReadUserAcceptedDomain(), std::nullopt);
}

TEST(TeleportDeploymentConfigUserAcceptedTest, RegisteredReaderIsUsed) {
  SetUserAcceptedDomainReader(base::BindRepeating(
      [] { return std::optional<std::string>("user.example"); }));
  EXPECT_EQ(ReadUserAcceptedDomain(), std::optional<std::string>("user.example"));
  SetUserAcceptedDomainReader({});  // reset so other tests see no reader
}

// --- Corp-managed lock predicate (spec §4.6) ---

// A higher-priority admin source (levels 1/2/3) always locks the enroll page,
// regardless of the restrict policy input.
TEST(TeleportDomainLockTest, HigherPrioritySourceLocks) {
  for (auto source : {DeploymentDomainSource::kCommandLine,
                      DeploymentDomainSource::kManagedPref,
                      DeploymentDomainSource::kMachineFile}) {
    EXPECT_TRUE(IsDomainChangeLocked(source, /*restrict_change_forced=*/false));
  }
}

// Levels 4/5 with no restrict policy are writable (BYOD self-service).
TEST(TeleportDomainLockTest, UserAcceptedAndBakedDefaultUnlockedWhenUnmanaged) {
  EXPECT_FALSE(IsDomainChangeLocked(DeploymentDomainSource::kUserAccepted,
                                    /*restrict_change_forced=*/false));
  EXPECT_FALSE(IsDomainChangeLocked(DeploymentDomainSource::kBakedDefault,
                                    /*restrict_change_forced=*/false));
}

// The dedicated restrict policy locks even the baked-default SaaS case.
TEST(TeleportDomainLockTest, RestrictPolicyLocksBakedDefault) {
  EXPECT_TRUE(IsDomainChangeLocked(DeploymentDomainSource::kBakedDefault,
                                   /*restrict_change_forced=*/true));
  EXPECT_TRUE(IsDomainChangeLocked(DeploymentDomainSource::kUserAccepted,
                                   /*restrict_change_forced=*/true));
}


}  // namespace
}  // namespace teleport
