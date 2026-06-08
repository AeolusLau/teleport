# Phase 5 Client (Idle + Data Controls) Implementation Plan — teleport

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the teleport browser enforce `IdleTimeout`/`IdleTimeoutActions` and `DataControlsRules` (clipboard/print) delivered via machine CBCM, with branded warn/block + idle dialogs, verified live.

**Architecture:** These are upstream Chrome built-in policies with built-in handlers/enforcement — the overlay vendors no client proto. Phase 0 already confirmed (spec §3) that Idle and Data Controls enforcement are NOT brand-gated, so the expected client change is near-zero: verify enforcement reaches our unbranded machine-CBCM build, brand the dialogs (grd sweep + patch any hardcoded-string leak), and prove it end-to-end.

**Tech Stack:** Chromium M148 overlay (`//teleport`), GN/Siso, machine CBCM, fairyland device-manager (dev stack), `branding_strings.py`.

**Prerequisite:** The fairyland Phase 5 **server plan** must be implemented and the dev-stack `teleport-device-manager` restarted onto it (so the 3 policies can be set via admin gRPC). See that plan's self-review note for the restart command.

**Reused e2e harness (from P3/P4, all confirmed working):**
- User-data-dir: `/tmp/teleport-e2e` (machine-enrolled to tenant `11111111-1111-1111-1111-111111111111`; DMToken persists in `~/Library/Application Support/Teleport/Cloud Enrollment`).
- Binary: `<repo>/build/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport`.
- Set policies: `grpcurl -plaintext -import-path proto -proto teleport/v1/device_manager.proto -d '{...}' 127.0.0.1:19090 teleport.v1.DeviceManagerControlService/SetTenantPolicies` (run from the fairyland worktree).
- **Build gotcha:** any edit to `chrome/browser/**` requires `touch <file>` + rebuild, then `grep -c <marker> out/mac/arm64/dev/libchrome_dll.dylib` to confirm the relink (dev is a component build).
- **Policy-cache timing:** machine policy applies ~5s after launch; relaunch once to cache, then the cached policy is present synchronously at startup (the "warm cache" pattern).

---

### Task 1: Confirm enforcement reachability (static, no code change)

**Files:** read-only investigation in `chromium/src`.

- [ ] **Step 1: Confirm Idle service is unconditional on desktop**

Run (in `chromium/src`):
```bash
sed -n '54,56p' chrome/browser/enterprise/idle/idle_service_factory.cc
```
Expected: `ServiceIsCreatedWithBrowserContext() const { return true; }` — IdleService is created with every profile, no brand gate. Confirms IdleTimeout/IdleTimeoutActions drive actions once the prefs are set.

- [ ] **Step 2: Confirm Data Controls rules service consumes machine-scope policy**

Run:
```bash
grep -n "kDataControlsRulesScopePref\|kDataControlsRulesPref\|POLICY_SCOPE_MACHINE\|GetVerdict\|GetPrintVerdict" chromium/src/components/enterprise/data_controls/core/browser/rules_service_base.cc
```
Expected: the rules pref + scope pref drive `RulesServiceBase`; clipboard + `GetPrintVerdict` are the desktop verdict surfaces. Confirms `DataControlsRules` (machine scope, scope pref = MACHINE) is consumed — same shape proven for the P4 reporting connector.

- [ ] **Step 3: Record findings (no patch expected)**

Keep the findings for the final e2e summary (Task 6) — no code change in this task. If either Step 1 or Step 2 reveals an unexpected brand/feature gate, STOP and surface it (mirror the P4 reporting investigation) before proceeding — the plan assumes no gate.

- [ ] **Step 4: No commit** (investigation only).

---

### Task 2: Build + verify policy delivery

**Files:** none (uses existing build + dev stack).

- [ ] **Step 1: Ensure overlay patches applied + build is current**

Run (repo root): `python scripts/apply_patches.py` then
`cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome`
Expected: build succeeds (warm cache, fast).

- [ ] **Step 2: Set the 3 policies on tenant 1111 (machine scope)**

From the fairyland worktree, run a single `SetTenantPolicies` carrying all three (the cross-policy guard requires IdleTimeout alongside IdleTimeoutActions):
```bash
grpcurl -plaintext -import-path proto -proto teleport/v1/device_manager.proto -d '{
  "tenant_id":"11111111-1111-1111-1111-111111111111","scope":"machine",
  "policies":[
    {"name":"IdleTimeout","value":1,"mode":"mandatory"},
    {"name":"IdleTimeoutActions","value":["clear_browsing_history","clear_cookies_and_other_site_data"],"mode":"mandatory"},
    {"name":"DataControlsRules","value":"[{\"name\":\"block-copy\",\"sources\":{\"urls\":[\"example.com\"]},\"restrictions\":[{\"class\":\"CLIPBOARD\",\"level\":\"BLOCK\"}]},{\"name\":\"warn-print\",\"sources\":{\"urls\":[\"*\"]},\"restrictions\":[{\"class\":\"PRINTING\",\"level\":\"WARN\"}]}]","mode":"mandatory"}
  ]}' 127.0.0.1:19090 teleport.v1.DeviceManagerControlService/SetTenantPolicies
```
Expected: `{}` (success). NOTE: `SetTenantPolicies` is a full-replace for the machine scope — include any other machine policies you want to keep (e.g. re-add the demo policies if the e2e environment relies on them).

- [ ] **Step 2.5: Warm the policy cache**

Launch once (~12s) and quit so the new policy is fetched + cached:
```bash
"<repo>/build/mac/arm64/dev/Teleport.app/Contents/MacOS/Teleport" --user-data-dir=/tmp/teleport-e2e --no-first-run --no-default-browser-check about:blank &
sleep 12; pkill -9 -f "MacOS/Teleport"
```

- [ ] **Step 3: Verify chrome://policy shows all three**

Relaunch and open `chrome://policy` (or read the running browser's policy via the page). Confirm `IdleTimeout`=1, `IdleTimeoutActions`=[...], `DataControlsRules`=<json> all appear with Level=Mandatory, Source=Cloud, Status=OK.
Expected: three rows present and OK. (Visual / user-assisted check — call the operator if a GUI inspection is needed.)

- [ ] **Step 4: No commit** (verification only).

---

### Task 3: Idle e2e (live)

**Files:** none.

- [ ] **Step 1: Relaunch with cached Idle policy + a clean idle window**

Launch with logging; do not touch input:
```bash
rm -f /tmp/teleport-idle.log
"<repo>/.../MacOS/Teleport" --user-data-dir=/tmp/teleport-e2e --enable-logging=stderr \
  --vmodule='*idle*=1' --no-first-run --no-default-browser-check about:blank >/tmp/teleport-idle.log 2>&1 &
```

- [ ] **Step 2: Wait out the idle timeout (~1 min) and observe the action**

After ≥60s idle, expect the idle bubble/dialog and the configured actions to run (browsing history + cookies cleared). Verify in the log:
```bash
grep -iE "idle|IdleService|RunAction|clear" /tmp/teleport-idle.log | grep -vi verbose | tail -20
```
Expected: idle-timeout fired + clear actions executed (no crash). Confirm the idle bubble appeared (visual — call the operator if needed).

- [ ] **Step 3: Stop browser**

`pkill -9 -f "MacOS/Teleport"`

- [ ] **Step 4: No commit** (verification only). Record the observed behavior for the final e2e summary.

---

### Task 4: Data Controls e2e (live) + locate the dialog strings

**Files:** none (this task discovers the branding surface for Task 5).

- [ ] **Step 1: Relaunch and trigger a clipboard BLOCK**

Launch, navigate to a page under the rule's `sources.urls` (e.g. an `example.com` page), and attempt to copy selected text. Expect a BLOCK (copy prevented) and a Data Controls notice/dialog.
```bash
"<repo>/.../MacOS/Teleport" --user-data-dir=/tmp/teleport-e2e --enable-logging=stderr \
  --vmodule='*data_controls*=1,*rules_service*=1' --no-first-run --no-default-browser-check "https://example.com" >/tmp/teleport-dc.log 2>&1 &
```
Then attempt copy (visual/operator). Verify verdict in log:
```bash
grep -iE "data_controls|verdict|BLOCK|clipboard" /tmp/teleport-dc.log | grep -vi verbose | tail -20
```
Expected: a BLOCK verdict logged for the clipboard action.

- [ ] **Step 2: Trigger a print WARN**

Invoke print (Cmd+P) on any page (rule `warn-print` matches `*`). Expect a WARN dialog allowing proceed/cancel.

- [ ] **Step 3: Capture the dialog product-name strings**

Note the exact text shown in the block/warn dialog and the idle bubble. Identify the grd message IDs:
```bash
cd chromium/src
grep -rn "IDS_DATA_CONTROLS\|IDS_DEEP_SCANNING\|IDS_ENTERPRISE_DATA" components/enterprise/data_controls/ chrome/browser/ui/ | grep -i "title\|message\|block\|warn" | head
grep -rn "IDS_IDLE_TIMEOUT\|IDS_PROFILE_IDLE" out/mac/arm64/dev/gen/ chrome/ | head
```
Expected: the message IDs backing the observed dialogs. Record whether they contain a product-name placeholder (`$1`/`IDS_PRODUCT_NAME`) or a hardcoded "Chrome"/"Chromium".

- [ ] **Step 4: No commit** (discovery). Hand the identified message IDs to Task 5.

---

### Task 5: Brand the dialogs

**Files (conditional on Task 4 findings):**
- Possibly modify: `branding/` grd/xtb sweep is handled by `scripts/branding_strings.py` (product-name substitution).
- Possibly create: `patches/<mirrored path>.patch` for a hardcoded C++/string leak (mirror the Phase 3 `kChromePoliciesName` precedent).

- [ ] **Step 1: Run the branding sweep + rebuild**

Run (repo root): `python scripts/branding_strings.py` then rebuild:
```bash
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
```
Expected: product-name strings in grd/xtb become 闪现; dialogs that use `IDS_PRODUCT_NAME`/`$1` are auto-branded.

- [ ] **Step 2: Re-trigger the dialogs and check for residual "Chrome"/"Chromium"**

Repeat Task 4 Steps 1-2. If the dialog now shows 闪现, branding is done — skip to Step 4.

- [ ] **Step 3: Patch a hardcoded-string leak (only if Step 2 still shows Chrome/Chromium)**

If a dialog string is a hardcoded C++ literal (not a branded grd message) — the Phase 3 `kChromePoliciesName` situation — create a one-file patch mirroring the upstream path, e.g. `patches/<path under chromium/src>.patch`, replacing the literal with the branded product name. Then:
```bash
python scripts/apply_patches.py
touch <the edited .cc>          # force component relink
cd "$TELEPORT_CHROMIUM_DIR/src" && autoninja -C out/mac/arm64/dev chrome
grep -c "<branded marker>" out/mac/arm64/dev/libchrome_dll.dylib   # confirm relink
```
Re-trigger the dialog; confirm it shows 闪现.

- [ ] **Step 4: Commit (only if a patch was created)**

```bash
git add patches/ branding/
git commit -m "feat(phase5): brand Idle + Data Controls dialogs"
```
If branding was fully covered by `branding_strings.py` with no new patch (the likely case), there is nothing to commit beyond what that script already manages — note "branding covered by grd sweep, no residual patch" in the e2e summary.

---

### Task 6: Final e2e summary

- [ ] **Step 1: Write the e2e summary**

Record (in the branch's e2e notes / PR body): chrome://policy shows the 3 policies (Task 2); idle timeout fired its actions + bubble (Task 3); clipboard BLOCK + print WARN dialogs enforced and branded (Tasks 4-5). Note any patch created (or that branding was grd-sweep-only).

- [ ] **Step 2: No code commit** (summary only; lives in the PR).

---

## Self-Review Notes

- **Spec coverage:** §5.1 verify Idle → Task 1+3; §5.2 verify Data Controls → Task 1+4; §5.3 branding → Task 5; §5.4 no client proto → stated (architecture); §6 e2e (delivery/idle/data-controls) → Tasks 2/3/4. All covered.
- **No-patch expectation:** Tasks 1-4 are verification/e2e; the only conditional code change is the Task 5 branding patch, gated on an observed leak (matches the spec's "near-zero patch" + "patch only if hardcoded leak").
- **Ordering dependency:** server plan must land + device-manager restarted before Task 2 (stated in Prerequisite).
- **Build gotcha + warm-cache + visual checks** are called out where they bite (Tasks 2.5, 5.3); GUI-dependent steps flag operator assistance.
