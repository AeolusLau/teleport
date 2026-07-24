// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/common/teleport_signin_entry_logic.h"

namespace teleport {

bool ShouldShowTeleportSigninEntry(bool is_enrolled,
                                   bool is_regular_profile,
                                   bool is_web_app) {
  return !is_enrolled && is_regular_profile && !is_web_app;
}

}  // namespace teleport
