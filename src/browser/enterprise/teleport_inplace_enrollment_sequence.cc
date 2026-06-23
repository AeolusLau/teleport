// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_inplace_enrollment_sequence.h"

#include "base/check.h"

namespace teleport {

bool RunInPlaceEnrollmentSequence(InPlaceEnrollmentSteps& steps) {
  if (!steps.ApplyManagedAttributes()) {
    return false;
  }
  // Hard invariant: the dasherless managed attributes must be in place before
  // FetchPolicy(), or the OIDC fetch bad-casts our ProfileCloudPolicyManager.
  CHECK(steps.ManagedAttributesApplied());
  steps.FetchPolicy();
  return true;
}

}  // namespace teleport
