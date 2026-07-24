// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_enrollment_done_user_data.h"

#include <utility>

#include "base/functional/callback_helpers.h"
#include "content/public/browser/web_contents.h"
#include "teleport/common/teleport_enterprise_enrollment.h"

namespace teleport {

EnrollmentDoneUserData::EnrollmentDoneUserData(content::WebContents* web_contents,
                                               EnrollmentDoneCallback on_enrolled)
    : content::WebContentsUserData<EnrollmentDoneUserData>(*web_contents),
      on_enrolled_(std::move(on_enrolled)) {}

EnrollmentDoneUserData::~EnrollmentDoneUserData() = default;

// static
void EnrollmentDoneUserData::Set(content::WebContents* web_contents,
                                 EnrollmentDoneCallback on_enrolled) {
  // CreateForWebContents is a no-op if already present, so remove first to allow
  // replacing the closure.
  web_contents->RemoveUserData(UserDataKey());
  EnrollmentDoneUserData::CreateForWebContents(web_contents,
                                               std::move(on_enrolled));
}

// static
EnrollmentDoneCallback EnrollmentDoneUserData::Take(
    content::WebContents* web_contents) {
  EnrollmentDoneUserData* data =
      EnrollmentDoneUserData::FromWebContents(web_contents);
  if (!data || data->on_enrolled_.is_null()) {
    return base::DoNothing();
  }
  EnrollmentDoneCallback closure = std::move(data->on_enrolled_);
  // Drop the now-empty UserData so it does not linger on the WebContents.
  // NOTE: this deletes `data`; do not touch it afterwards.
  web_contents->RemoveUserData(UserDataKey());
  return closure;
}

// static
bool EnrollmentDoneUserData::HasCallback(content::WebContents* web_contents) {
  return EnrollmentDoneUserData::FromWebContents(web_contents) != nullptr;
}

WEB_CONTENTS_USER_DATA_KEY_IMPL(EnrollmentDoneUserData);

}  // namespace teleport
