// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_FORCE_SIGNIN_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_FORCE_SIGNIN_H_

namespace teleport {

// Whether the Teleport enrollment gate requires managed enrollment before
// browsing. Reads local_state pref kRequireEnrollmentToBrowse, but — mirroring
// upstream signin_util::IsForceSigninEnabled()'s process-level cache and the
// BrowserSignin policy's dynamic_refresh:false — the value is FROZEN on first
// successful read for the rest of the session. Many upstream call sites
// CHECK/DCHECK that force-signin is a session constant; a live-reading predicate
// would crash them if the pref flipped mid-session.
//
// Fail-open: returns false (and does NOT cache) when g_browser_process /
// local_state is not yet available or the pref is unregistered, so an early
// caller can never CHECK-crash on an unregistered pref and never freezes a
// premature value.
bool RequireEnrollmentGateEnabled();

// Clears the frozen snapshot so a test can re-seed the pref. Test-only.
void ResetRequireEnrollmentGateForTesting();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_FORCE_SIGNIN_H_
