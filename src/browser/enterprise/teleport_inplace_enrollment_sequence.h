// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_INPLACE_ENROLLMENT_SEQUENCE_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_INPLACE_ENROLLMENT_SEQUENCE_H_

namespace teleport {

// Collaborators the in-place OIDC registrar drives after the CloudPolicyClient
// has registered. Abstracted behind an interface so the ORDERING INVARIANT —
// the dasherless managed attributes MUST be applied before policy is fetched —
// can be unit-tested without any chrome/browser internals.
//
// Why the order matters: a dasherless profile is a ProfileCloudPolicyManager.
// FetchPolicyForOidcUser's InitializeCloudPolicyManager path static_casts the
// profile's policy manager to UserCloudPolicyManager unless SetDasherlessManagement
// has already been recorded. Fetching before the attributes are applied is a
// latent bad-cast; this sequence makes the order impossible to get wrong.
class InPlaceEnrollmentSteps {
 public:
  virtual ~InPlaceEnrollmentSteps() = default;

  // Records the managed attributes on the target profile (management id, OIDC
  // tokens, dasherless flag, recovery prefs). Returns false if they could not be
  // applied (e.g. the profile attributes entry vanished), in which case the
  // sequence aborts WITHOUT fetching policy.
  virtual bool ApplyManagedAttributes() = 0;

  // True iff the dasherless managed attributes are now in place (dasherless flag
  // set AND OIDC tokens non-empty). Checked as a hard invariant before fetching.
  virtual bool ManagedAttributesApplied() const = 0;

  // Resets any GAIA policy management and starts the OIDC user policy fetch.
  // Only ever called after ApplyManagedAttributes() succeeded and
  // ManagedAttributesApplied() holds.
  virtual void FetchPolicy() = 0;
};

// Runs the post-registration sequence in the one valid order:
//   ApplyManagedAttributes() -> CHECK(ManagedAttributesApplied()) -> FetchPolicy()
// Returns false (and does NOT fetch) when ApplyManagedAttributes() fails, so the
// caller can abort. CHECK-fails if attributes report success but are not actually
// in place (turns the latent bad-cast into an explicit, debuggable abort).
bool RunInPlaceEnrollmentSequence(InPlaceEnrollmentSteps& steps);

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_INPLACE_ENROLLMENT_SEQUENCE_H_
