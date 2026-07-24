#include "teleport/browser/enterprise/teleport_oidc_inplace_registrar.h"

#include <memory>
#include <string>
#include <vector>

#include "base/feature_list.h"
#include "base/functional/bind.h"
#include "base/logging.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/utf_string_conversions.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/enterprise/profile_management/profile_management_features.h"
#include "chrome/browser/enterprise/signin/enterprise_signin_prefs.h"
#include "chrome/browser/enterprise/signin/user_policy_oidc_signin_service.h"
#include "chrome/browser/enterprise/signin/user_policy_oidc_signin_service_factory.h"
#include "chrome/browser/policy/chrome_browser_policy_connector.h"
#include "chrome/browser/profiles/keep_alive/profile_keep_alive_types.h"
#include "chrome/browser/profiles/keep_alive/scoped_profile_keep_alive.h"
#include "chrome/browser/profiles/nuke_profile_directory_utils.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/profiles/profile_attributes_entry.h"
#include "chrome/browser/profiles/profile_attributes_storage.h"
#include "chrome/browser/profiles/profile_manager.h"
#include "components/account_id/account_id.h"
#include "components/policy/core/common/cloud/cloud_policy_client.h"
#include "components/policy/core/common/cloud/cloud_policy_client_registration_helper.h"
#include "components/policy/core/common/cloud/cloud_policy_core.h"
#include "components/policy/core/common/cloud/cloud_policy_store.h"
#include "components/policy/core/common/cloud/device_management_service.h"
#include "components/policy/core/common/cloud/profile_cloud_policy_manager.h"
#include "components/policy/proto/device_management_backend.pb.h"
#include "components/prefs/pref_service.h"
#include "content/public/browser/storage_partition.h"
#include "teleport/browser/enterprise/teleport_enrollment_gate.h"
#include "teleport/browser/enterprise/teleport_inplace_enrollment_sequence.h"
#include "teleport/common/teleport_enterprise_enrollment.h"

namespace teleport {

namespace {

using policy::CloudPolicyClient;
using policy::CloudPolicyClientRegistrationHelper;
using policy::UserPolicyOidcSigninService;
using policy::UserPolicyOidcSigninServiceFactory;
using profile_management::features::kOidcAuthStubClientId;
using profile_management::features::kOidcAuthStubDmToken;
using profile_management::features::kOidcAuthStubUserEmail;
using profile_management::features::kOidcAuthStubUserName;
using profile_management::features::kOidcEnrollRegistrationTimeout;

// Upper bound on the WHOLE in-place enrollment (registration + policy fetch).
// Without it, a phase that never invokes its callback (hung network / server)
// would leak the self-owned registrar forever.
constexpr base::TimeDelta kInPlaceEnrollmentTimeout = base::Seconds(90);

// Returns the ProfileAttributesEntry for `profile`, or nullptr if unavailable.
ProfileAttributesEntry* GetEntry(Profile* profile) {
  ProfileManager* profile_manager = g_browser_process->profile_manager();
  if (!profile_manager) {
    return nullptr;
  }
  return profile_manager->GetProfileAttributesStorage()
      .GetProfileAttributesWithPath(profile->GetPath());
}

// Self-owned helper that clones the registration sequence of
// OidcAuthenticationSigninInterceptor but registers the CURRENT profile in
// place (no Browser-anchored consent dialog, no new profile). It owns the
// CloudPolicyClient + CloudPolicyClientRegistrationHelper and deletes itself
// when the work is finished (success, failure, or timeout).
//
// The post-registration tail (apply managed attributes -> fetch policy) is
// driven through RunInPlaceEnrollmentSequence so the ordering invariant is
// enforced by the unit-tested sequencer rather than ad-hoc here.
class TeleportOidcInPlaceRegistrar : public InPlaceEnrollmentSteps {
 public:
  TeleportOidcInPlaceRegistrar(Profile* profile,
                               const ProfileManagementOidcTokens& oidc_tokens,
                               const std::string& issuer_id,
                               const std::string& subject_id,
                               const std::string& email,
                               EnrollmentDoneCallback on_done)
      : profile_(profile),
        oidc_tokens_(oidc_tokens),
        issuer_id_(issuer_id),
        subject_id_(subject_id),
        email_(email),
        on_done_(std::move(on_done)) {}

  TeleportOidcInPlaceRegistrar(const TeleportOidcInPlaceRegistrar&) = delete;
  TeleportOidcInPlaceRegistrar& operator=(const TeleportOidcInPlaceRegistrar&) =
      delete;

  // Kicks off the registration. Mirrors interceptor StartOidcRegistration
  // (~line 326-363).
  void Start() {
    VLOG(1) << "[teleport-enroll] registration start";

    // Hold our OWN keep-alive on the profile for the entire async lifetime. The
    // registrar is self-owned and decoupled from the picker; without this, if the
    // picker is abandoned mid-flight the profile could be destroyed and the
    // registration/policy callbacks would dereference a freed Profile.
    profile_keep_alive_ = std::make_unique<ScopedProfileKeepAlive>(
        profile_.get(), ProfileKeepAliveOrigin::kProfileCreationFlow);

    // Bound the WHOLE flow (registration + policy fetch). delete this destroys the
    // CloudPolicyClient + registration helper, cancelling their pending callbacks,
    // so firing during registration is safe (no Unretained UAF).
    enrollment_timeout_timer_.Start(
        FROM_HERE, kInPlaceEnrollmentTimeout,
        base::BindOnce(&TeleportOidcInPlaceRegistrar::OnEnrollmentTimeout,
                       base::Unretained(this)));

    policy::DeviceManagementService* device_management_service =
        g_browser_process->browser_policy_connector()
            ->device_management_service();
    device_management_service->ScheduleInitialization(0);

    // Use the stable management id as the CloudPolicyClient device id, mirroring
    // the interceptor which passes a preset profile id here.
    client_ = std::make_unique<CloudPolicyClient>(
        ManagementId(), device_management_service,
        g_browser_process->shared_url_loader_factory(),
        CloudPolicyClient::DeviceDMTokenCallback());

    registration_helper_ =
        std::make_unique<CloudPolicyClientRegistrationHelper>(
            client_.get(),
            enterprise_management::DeviceRegisterRequest::BROWSER,
            enterprise_management::DeviceRegisterRequest::
                FLAVOR_USER_REGISTRATION);

    base::TimeDelta timeout_duration =
        base::FeatureList::IsEnabled(
            profile_management::features::kOidcEnrollmentTimeout)
            ? kOidcEnrollRegistrationTimeout.Get()
            : base::TimeDelta();

    // Unretained is safe: `this` owns `registration_helper_`.
    registration_helper_->StartRegistrationWithOidcTokens(
        oidc_tokens_.auth_token, oidc_tokens_.id_token, std::string(),
        oidc_tokens_.state, timeout_duration, oidc_tokens_.is_token_encrypted,
        base::BindOnce(&TeleportOidcInPlaceRegistrar::OnClientRegistered,
                       base::Unretained(this)));
  }

  // InPlaceEnrollmentSteps: records the managed attributes on the CURRENT
  // profile, in the order the upstream creator + delegate use them
  // (ManagedProfileCreator::OnProfileAdded sets the id, then
  // OidcManagedProfileCreationDelegate sets the OIDC tokens + dasherless flag).
  bool ApplyManagedAttributes() override {
    if (!entry_) {
      return false;
    }
    entry_->SetProfileManagementId(ManagementId());

    ProfileManagementOidcTokens tokens_with_name = oidc_tokens_;
    tokens_with_name.identity_name = base::UTF8ToUTF16(user_display_name_);
    entry_->SetProfileManagementOidcTokens(tokens_with_name);

    // Teleport is dasherless-only: every profile is a ProfileCloudPolicyManager,
    // so dasher_based MUST resolve false in UserPolicyOidcSigninService. Hardcode
    // true (do NOT derive from the client's third_party_identity_type).
    entry_->SetDasherlessManagement(true);

    // Backup copy of the dm token / client id for policy recovery, mirroring
    // interceptor ~line 595-598.
    profile_->GetPrefs()->SetString(
        enterprise_signin::prefs::kPolicyRecoveryToken, dm_token_);
    profile_->GetPrefs()->SetString(
        enterprise_signin::prefs::kPolicyRecoveryClientId, client_id_);

    // Mirror the upstream OIDC-managed profile's identity prefs (see
    // OidcManagedProfileCreationDelegate::OnManagedProfileInitialized) so the
    // profile menu shows the managed identity instead of the "not signed in"
    // local-profile string.
    if (PrefService* prefs = profile_->GetPrefs()) {
      if (!user_display_name_.empty()) {
        prefs->SetString(enterprise_signin::prefs::kProfileUserDisplayName,
                          user_display_name_);
      }
      if (!user_email_.empty()) {
        prefs->SetString(enterprise_signin::prefs::kProfileUserEmail,
                          user_email_);
      }
    }

    VLOG(1) << "[teleport-enroll] attributes-set: management_id+oidc_tokens"
               "+dasherless(true)";
    return true;
  }

  // InPlaceEnrollmentSteps: true iff the dasherless managed attributes are in
  // place (dasherless flag set AND OIDC tokens non-empty).
  bool ManagedAttributesApplied() const override {
    if (!entry_ || !entry_->IsDasherlessManagement()) {
      return false;
    }
    ProfileManagementOidcTokens stored =
        entry_->GetProfileManagementOidcTokens();
    return (stored.is_token_encrypted || !stored.auth_token.empty()) &&
           !stored.id_token.empty();
  }

  // InPlaceEnrollmentSteps: resets GAIA policy management and starts the OIDC
  // user policy fetch. The overall timeout (started in Start()) bounds this too.
  void FetchPolicy() override {
    VLOG(1) << "[teleport-enroll] policy-fetch-start";
    oidc_signin_service_->ResetGaiaPolicyManagement();
    oidc_signin_service_->FetchPolicyForOidcUser(
        AccountId(), dm_token_, client_id_, user_email_,
        /*user_affiliation_ids=*/std::vector<std::string>(),
        base::TimeTicks::Now(), /*switch_to_entry=*/false,
        profile_->GetDefaultStoragePartition()
            ->GetURLLoaderFactoryForBrowserProcess(),
        base::BindOnce(&TeleportOidcInPlaceRegistrar::OnPolicyFetchComplete,
                       weak_factory_.GetWeakPtr()));
  }

 private:
  // Runs the enrollment-outcome callback exactly once, then self-destructs.
  // Every terminal path funnels through here so the UI step always learns the
  // outcome (success unlock or visible failure state).
  void RunDoneAndDelete(EnrollmentResult result) {
    if (on_done_) {
      std::move(on_done_).Run(result);
    }
    // Run() may indirectly delete other objects; nothing below may touch members.
    delete this;
  }

  // Stable management id derived from issuer + subject. We do NOT use the
  // interceptor's ProfileIdService-preset id because that path is geared toward
  // a freshly created profile (it pairs a generated GUID with the device id to
  // pre-compute the NEW profile's id). For in-place enrollment the current
  // profile already exists; an iss/sub-derived id is stable across re-runs and
  // unique per managed user, which is all the gate needs (a non-empty
  // ProfileManagementId).
  std::string ManagementId() const {
    return "iss:" + issuer_id_ + ",sub:" + subject_id_;
  }

  // Mirrors interceptor OnClientRegistered (~line 366-466), minus the
  // consent-dialog / new-profile branches. Validates the registration result,
  // captures the registration outputs, then runs the apply-then-fetch sequence.
  void OnClientRegistered(CloudPolicyClient::Result result) {
    if (!result.IsSuccess()) {
      LOG(ERROR) << "[teleport-enroll] registration FAILED net_error="
                 << result.GetNetError()
                 << " dm_status=" << client_->last_dm_status();
      // The gate stays locked; the step renders the failure.
      RunDoneAndDelete(EnrollmentResult::kRegistrationFailed);
      return;
    }

    dm_token_ = kOidcAuthStubDmToken.Get().empty() ? client_->dm_token()
                                                   : kOidcAuthStubDmToken.Get();
    client_id_ = kOidcAuthStubClientId.Get().empty()
                     ? client_->client_id()
                     : kOidcAuthStubClientId.Get();
    user_email_ = email_;
    if (user_email_.empty()) {
      user_email_ = kOidcAuthStubUserEmail.Get().empty()
                        ? client_->oidc_user_email()
                        : kOidcAuthStubUserEmail.Get();
    }
    user_display_name_ = kOidcAuthStubUserName.Get().empty()
                             ? client_->oidc_user_display_name()
                             : kOidcAuthStubUserName.Get();

    VLOG(1) << "[teleport-enroll] registration SUCCESS dm_token="
            << (dm_token_.empty() ? "<empty>" : "<present>");

    if (dm_token_.empty()) {
      LOG(ERROR) << "[teleport-enroll] empty dm_token; aborting";
      RunDoneAndDelete(EnrollmentResult::kRegistrationFailed);
      return;
    }

    entry_ = GetEntry(profile_);
    if (!entry_) {
      LOG(ERROR) << "[teleport-enroll] no profile attributes entry; aborting";
      RunDoneAndDelete(EnrollmentResult::kRegistrationFailed);
      return;
    }

    oidc_signin_service_ =
        UserPolicyOidcSigninServiceFactory::GetForProfile(profile_);
    if (!oidc_signin_service_) {
      LOG(ERROR) << "[teleport-enroll] no OIDC signin service; aborting";
      RunDoneAndDelete(EnrollmentResult::kRegistrationFailed);
      return;
    }

    // Apply managed attributes, then fetch policy — in that order, enforced by
    // the unit-tested sequencer. On attribute failure, abort without fetching
    // (a fetch before the dasherless attrs are set bad-casts our policy manager).
    if (!RunInPlaceEnrollmentSequence(*this)) {
      LOG(ERROR) << "[teleport-enroll] managed-attribute application failed; aborting";
      RunDoneAndDelete(EnrollmentResult::kRegistrationFailed);
      return;
    }
    // FetchPolicy() is now in flight; OnPolicyFetchComplete or OnEnrollmentTimeout
    // finishes the flow.
  }

  void OnPolicyFetchComplete(bool success) {
    enrollment_timeout_timer_.Stop();
    policy::ProfileCloudPolicyManager* manager =
        profile_->GetProfileCloudPolicyManager();
    policy::CloudPolicyCore* core = manager ? manager->core() : nullptr;
    policy::CloudPolicyStore* store = core ? core->store() : nullptr;
    policy::CloudPolicyClient* client = core ? core->client() : nullptr;
    const bool has_policy = store && store->has_policy();
    if (has_policy) {
      VLOG(1) << "[teleport-enroll] policy fetch succeeded";
      // teleport: the picker may have cancelled and released its keep-alive on
      // this half-created profile while enrollment was still in flight (see
      // ProfilePickerFlowController::PopTeleportEnrollmentStep). If the profile
      // is already scheduled for deletion (or somehow has no path), don't
      // persist the GLOBAL enrolled-domain for it -- that would leave a stale
      // local_state domain unbacked by any surviving enrolled profile, plus a
      // server-side orphan. The orphan is known/acceptable residue (same pool
      // as machine DM-token cleanup); log and skip the persist, but still run
      // the normal success teardown so this self-owned registrar doesn't leak.
      if (profile_->GetPath().empty() ||
          IsProfileDirectoryMarkedForDeletion(profile_->GetPath())) {
        LOG(WARNING) << "[teleport-enroll] profile scheduled for deletion; "
                        "skipping PersistEnrolledDomain (server orphan possible)";
        RunDoneAndDelete(EnrollmentResult::kSuccess);
        return;
      }
      // Record the deployment domain we enrolled against so a later admin-
      // channel domain change is detected as a migration (§4.5).
      PersistEnrolledDomain();
      RunDoneAndDelete(EnrollmentResult::kSuccess);
      return;
    }
    LOG(ERROR) << "[teleport-enroll] policy REJECTED: success=" << success
               << " store_status="
               << (store ? static_cast<int>(store->status()) : -1)
               << " validation_status="
               << (store ? static_cast<int>(store->validation_status()) : -1)
               << " client_dm_status="
               << (client ? static_cast<int>(client->last_dm_status()) : -1);
    RunDoneAndDelete(EnrollmentResult::kPolicyRejected);
  }

  void OnEnrollmentTimeout() {
    LOG(WARNING) << "[teleport-enroll] enrollment timed out; profile stays "
                    "locked, surfacing failure to the enroll step";
    RunDoneAndDelete(EnrollmentResult::kTimeout);
  }

  raw_ptr<Profile> profile_;
  const ProfileManagementOidcTokens oidc_tokens_;
  const std::string issuer_id_;
  const std::string subject_id_;
  const std::string email_;
  EnrollmentDoneCallback on_done_;

  // Captured in OnClientRegistered before the apply-then-fetch sequence runs.
  std::string dm_token_;
  std::string client_id_;
  std::string user_email_;
  std::string user_display_name_;
  raw_ptr<ProfileAttributesEntry> entry_ = nullptr;
  raw_ptr<UserPolicyOidcSigninService> oidc_signin_service_ = nullptr;

  // Keeps `profile_` alive across the whole async flow (the registrar is
  // self-owned and not tied to the picker's keep-alive).
  std::unique_ptr<ScopedProfileKeepAlive> profile_keep_alive_;
  std::unique_ptr<CloudPolicyClient> client_;
  std::unique_ptr<CloudPolicyClientRegistrationHelper> registration_helper_;
  base::OneShotTimer enrollment_timeout_timer_;

  base::WeakPtrFactory<TeleportOidcInPlaceRegistrar> weak_factory_{this};
};

}  // namespace

void EnrollCurrentProfileInPlace(
    Profile* profile,
    const ProfileManagementOidcTokens& oidc_tokens,
    const std::string& issuer_id,
    const std::string& subject_id,
    const std::string& email,
    EnrollmentDoneCallback on_done) {
  // Self-owned: deletes itself on completion.
  (new TeleportOidcInPlaceRegistrar(profile, oidc_tokens, issuer_id, subject_id,
                                    email, std::move(on_done)))
      ->Start();
}

}  // namespace teleport
