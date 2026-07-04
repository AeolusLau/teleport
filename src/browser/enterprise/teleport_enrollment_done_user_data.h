// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_DONE_USER_DATA_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_DONE_USER_DATA_H_

#include "base/functional/callback.h"
#include "content/public/browser/web_contents_user_data.h"
#include "teleport/common/teleport_enterprise_enrollment.h"

namespace content {
class WebContents;
}

namespace teleport {

// Carries the "enrollment completed" callback from the Teleport enrollment
// ProfilePicker step to the OIDC capture throttle, attached to the picker-hosted
// WebContents.
//
// The enrollment step (which hosts the OIDC enroll page on the locked profile)
// installs a closure whose body unlocks the profile and finishes the picker
// flow. The callback now carries the EnrollmentResult so the step can render a
// failure state. The OIDC capture throttle, after it captures the registration
// payload and reroutes it to the in-place registrar, takes this callback and
// hands it to the registrar as the on-done callback — so the profile is
// unlocked only once in-place enrollment has actually fetched policy
// (has_policy() == true).
class EnrollmentDoneUserData
    : public content::WebContentsUserData<EnrollmentDoneUserData> {
 public:
  ~EnrollmentDoneUserData() override;

  // Attaches `on_enrolled` to `web_contents`, replacing any previous callback.
  static void Set(content::WebContents* web_contents,
                  EnrollmentDoneCallback on_enrolled);

  // Moves out and returns the attached callback, or base::DoNothing() if none
  // is attached. Safe to call on any WebContents.
  static EnrollmentDoneCallback Take(content::WebContents* web_contents);

 private:
  friend class content::WebContentsUserData<EnrollmentDoneUserData>;

  EnrollmentDoneUserData(content::WebContents* web_contents,
                         EnrollmentDoneCallback on_enrolled);

  EnrollmentDoneCallback on_enrolled_;

  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_ENROLLMENT_DONE_USER_DATA_H_
