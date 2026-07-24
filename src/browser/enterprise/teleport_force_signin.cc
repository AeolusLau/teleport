// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_force_signin.h"

#include <optional>

#include "chrome/browser/browser_process.h"
#include "components/prefs/pref_service.h"
#include "teleport/common/teleport_pref_names.h"

namespace teleport {

namespace {
std::optional<bool>& GateSnapshot() {
  static std::optional<bool> snapshot;
  return snapshot;
}
}  // namespace

bool RequireEnrollmentGateEnabled() {
  std::optional<bool>& snapshot = GateSnapshot();
  if (snapshot.has_value()) {
    return *snapshot;
  }
  if (!g_browser_process) {
    return false;  // fail-open, do NOT cache
  }
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state ||
      !local_state->FindPreference(prefs::kRequireEnrollmentToBrowse)) {
    return false;  // fail-open, do NOT cache
  }
  snapshot = local_state->GetBoolean(prefs::kRequireEnrollmentToBrowse);
  return *snapshot;
}

void ResetRequireEnrollmentGateForTesting() {
  GateSnapshot().reset();
}

}  // namespace teleport
