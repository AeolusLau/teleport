// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_COMMON_TELEPORT_SIGNIN_ENTRY_LOGIC_H_
#define TELEPORT_COMMON_TELEPORT_SIGNIN_ENTRY_LOGIC_H_

namespace teleport {

// Whether the profile menu should show the Teleport "Sign in" entry (a
// voluntary in-place enrollment CTA). Shown only for an unenrolled, regular
// (non-OTR/non-system) profile in a normal (non-web-app) browser window. An
// enrolled profile instead shows the "managed by" header; a web-app window's
// menu carries no feature buttons upstream, so it gets no entry either.
bool ShouldShowTeleportSigninEntry(bool is_enrolled,
                                   bool is_regular_profile,
                                   bool is_web_app);

}  // namespace teleport

#endif  // TELEPORT_COMMON_TELEPORT_SIGNIN_ENTRY_LOGIC_H_
