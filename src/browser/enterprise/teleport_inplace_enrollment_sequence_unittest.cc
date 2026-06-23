// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_inplace_enrollment_sequence.h"

#include <string>
#include <vector>

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Records the order of collaborator calls so a test can assert the sequence.
class RecordingSteps : public InPlaceEnrollmentSteps {
 public:
  bool ApplyManagedAttributes() override {
    calls.push_back("apply");
    applied_ = apply_succeeds;
    return apply_succeeds;
  }
  bool ManagedAttributesApplied() const override {
    calls.push_back("check");
    return applied_;
  }
  void FetchPolicy() override { calls.push_back("fetch"); }

  // Test knobs.
  bool apply_succeeds = true;

  // Mutable so the const ManagedAttributesApplied() can append.
  mutable std::vector<std::string> calls;

 private:
  bool applied_ = false;
};

TEST(InPlaceEnrollmentSequenceTest, AppliesAttributesBeforeFetchingPolicy) {
  RecordingSteps steps;
  EXPECT_TRUE(RunInPlaceEnrollmentSequence(steps));
  // Attributes are applied and verified BEFORE policy is fetched.
  EXPECT_EQ(steps.calls, (std::vector<std::string>{"apply", "check", "fetch"}));
}

TEST(InPlaceEnrollmentSequenceTest, DoesNotFetchWhenAttributesFail) {
  RecordingSteps steps;
  steps.apply_succeeds = false;
  EXPECT_FALSE(RunInPlaceEnrollmentSequence(steps));
  // Apply was attempted; policy fetch was never reached.
  ASSERT_FALSE(steps.calls.empty());
  EXPECT_EQ(steps.calls.front(), "apply");
  for (const std::string& call : steps.calls) {
    EXPECT_NE(call, "fetch");
  }
}

// A buggy collaborator that claims apply succeeded but never actually records
// the attributes must trip the hard invariant rather than silently fetching
// (which would hit the UserCloudPolicyManager bad-cast at runtime).
TEST(InPlaceEnrollmentSequenceDeathTest, ChecksAttributesAreActuallyApplied) {
  class LyingSteps : public InPlaceEnrollmentSteps {
   public:
    bool ApplyManagedAttributes() override { return true; }
    bool ManagedAttributesApplied() const override { return false; }
    void FetchPolicy() override { fetched = true; }
    bool fetched = false;
  };
  LyingSteps steps;
  EXPECT_DEATH_IF_SUPPORTED(RunInPlaceEnrollmentSequence(steps), "");
  EXPECT_FALSE(steps.fetched);
}

}  // namespace
}  // namespace teleport
