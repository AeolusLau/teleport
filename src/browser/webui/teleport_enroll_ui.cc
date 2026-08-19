#include "teleport/browser/webui/teleport_enroll_ui.h"

#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/containers/span.h"
#include "base/functional/bind.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/time/time.h"
#include "chrome/grit/enroll_resources.h"
#include "chrome/grit/enroll_resources_map.h"
#include "components/policy/core/common/cloud/cloud_policy_constants.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/common/url_constants.h"
#include "mojo/public/cpp/bindings/self_owned_receiver.h"
#include "net/base/net_errors.h"
#include "net/cert/cert_status_flags.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "services/network/public/mojom/url_response_head.mojom.h"
#include "teleport/common/teleport_enroll_logic.h"
#include "teleport/common/teleport_deployment_config.h"
#include "ui/webui/webui_util.h"
#include "url/gurl.h"

namespace teleport {

namespace {

// Cap the server-identity body; a signed identity blob is a few hundred bytes.
constexpr size_t kMaxBodyBytes = 64 * 1024;

const char* StatusToString(EnrollStatus status) {
  switch (status) {
    case EnrollStatus::kSuccess:
      return "kSuccess";
    case EnrollStatus::kInvalidDomainFormat:
      return "kInvalidDomainFormat";
    case EnrollStatus::kCannotConnect:
      return "kCannotConnect";
    case EnrollStatus::kTlsError:
      return "kTlsError";
    case EnrollStatus::kHttpError:
      return "kHttpError";
    case EnrollStatus::kRedirectBlocked:
      return "kRedirectBlocked";
    case EnrollStatus::kMalformedResponse:
      return "kMalformedResponse";
    case EnrollStatus::kBadSignature:
      return "kBadSignature";
    case EnrollStatus::kWrongMessageType:
      return "kWrongMessageType";
    case EnrollStatus::kUnsupportedVersion:
      return "kUnsupportedVersion";
    case EnrollStatus::kDomainMismatch:
      return "kDomainMismatch";
    case EnrollStatus::kExpired:
      return "kExpired";
    case EnrollStatus::kAlreadyEnrolled:
      return "kAlreadyEnrolled";
  }
}

// The §4.6 corp-managed lock: source level + the admin restrict signal (forced
// managed pref OR trusted machine config file), folded through the pure
// predicate.
bool IsEnrollPageLocked() {
  return IsDomainChangeLocked(DeploymentDomainSourceLevel(),
                              IsDomainChangeRestrictedByAdmin());
}

}  // namespace

// Browser-side PageHandler: fetch the candidate's signed identity, verify it
// against the baked root key, and (after an explicit Confirm) persist the entry.
class EnrollPageHandler : public enroll::mojom::PageHandler {
 public:
  EnrollPageHandler(
      mojo::PendingReceiver<enroll::mojom::PageHandler> receiver,
      content::WebUI* web_ui)
      : receiver_(this, std::move(receiver)), web_ui_(web_ui) {}
  EnrollPageHandler(const EnrollPageHandler&) = delete;
  EnrollPageHandler& operator=(const EnrollPageHandler&) = delete;
  ~EnrollPageHandler() override {
    // A stored Verify() response callback MUST be run (or the receiver closed)
    // before it is destroyed, or Mojo DCHECK-aborts ("callback was destroyed
    // without first either being run or its associated binding being closed").
    // This happens when the enroll tab is closed while the server-identity fetch
    // is still in flight: ~EnrollPageHandler tears down loader_ (cancelling the
    // fetch, so OnFetched never runs) and would drop pending_verify_callback_
    // un-run. Run it with a connection-failure result so teardown is clean; the
    // reply is delivered if the pipe is still up, or silently dropped if not.
    if (pending_verify_callback_) {
      std::move(pending_verify_callback_)
          .Run(MakeResult(EnrollStatus::kCannotConnect, pending_domain_));
    }
  }

  // enroll::mojom::PageHandler:
  void GetState(GetStateCallback callback) override {
    auto state = enroll::mojom::EnrollState::New();
    state->domain = DeploymentDomain();
    state->source = DeploymentDomainSourceLabel();
    state->locked = IsEnrollPageLocked();
    // Unbind is offered only for a user-accepted level-4 entry on an unlocked
    // (BYOD) page — clearing it falls D back to the baked default.
    state->can_unbind =
        DeploymentDomainSourceLevel() == DeploymentDomainSource::kUserAccepted &&
        !state->locked;
    std::move(callback).Run(std::move(state));
  }

  void Verify(const std::string& domain, VerifyCallback callback) override {
    // §4.6: refuse when the enroll page is locked (corp-managed device: higher-
    // priority admin source, forced restrict policy, or CBCM machine enrollment).
    // The page normally hides the form when locked (GetState -> read-only view),
    // so this is defense-in-depth. Levels 4/5 on a BYOD device stay writable —
    // re-pointing an already-enrolled BYOD browser is a legitimate domain change
    // handled by the §4.5 migration, not blocked here.
    if (IsEnrollPageLocked()) {
      std::move(callback).Run(
          MakeResult(EnrollStatus::kAlreadyEnrolled, domain));
      return;
    }

    std::optional<EnrollFetchPlan> plan = PlanServerIdentityFetch(domain);
    if (!plan) {
      std::move(callback).Run(
          MakeResult(EnrollStatus::kInvalidDomainFormat, domain));
      return;
    }
    pending_domain_ = plan->canonical_domain;
    pending_entry_.reset();
    pending_verify_callback_ = std::move(callback);

    net::NetworkTrafficAnnotationTag annotation =
        net::DefineNetworkTrafficAnnotation("teleport_enroll_server_identity",
                                            R"(
        semantics {
          sender: "Teleport Enroll Page"
          description: "Fetches the organization deployment's root-signed "
            "server-identity blob to verify a user-entered domain before "
            "accepting it as the deployment domain."
          trigger: "User enters/pastes a domain on teleport://enroll."
          data: "None (a plain GET; the response is a signed identity blob)."
          destination: OTHER
        }
        policy {
          cookies_allowed: NO
          setting: "Only reachable from the internal enroll page."
        })");
    auto request = std::make_unique<network::ResourceRequest>();
    request->url = plan->url;
    request->method = "GET";
    request->credentials_mode = network::mojom::CredentialsMode::kOmit;
    // Forbid following redirects: identity fetch must hit the named host itself.
    request->redirect_mode = network::mojom::RedirectMode::kError;
    loader_ = network::SimpleURLLoader::Create(std::move(request), annotation);
    loader_->SetTimeoutDuration(base::Seconds(10));
    scoped_refptr<network::SharedURLLoaderFactory> factory =
        web_ui_->GetWebContents()
            ->GetBrowserContext()
            ->GetDefaultStoragePartition()
            ->GetURLLoaderFactoryForBrowserProcess();
    loader_->DownloadToString(
        factory.get(),
        base::BindOnce(&EnrollPageHandler::OnFetched,
                       weak_factory_.GetWeakPtr()),
        kMaxBodyBytes);
  }

  void Confirm(ConfirmCallback callback) override {
    const bool ok =
        pending_entry_ && WriteServerIdentityEntry(*pending_entry_);
    std::move(callback).Run(ok);
  }

  void Unbind(UnbindCallback callback) override {
    // BYOD "disconnect": clear the level-4 entry so D falls back to the baked
    // default. Refused on a locked page (defense-in-depth; the unbind button is
    // only shown when can_unbind).
    const bool ok = !IsEnrollPageLocked() && ClearServerIdentityEntry();
    std::move(callback).Run(ok);
  }

  void Relaunch() override {
    // Restart so the resolver re-reads the just-persisted level-4 entry (D is
    // memoized per process). Routed through the relaunch seam because
    // chrome::AttemptRestart() lives in //chrome/browser.
    RequestRelaunch();
  }

 private:
  static enroll::mojom::VerifyResultPtr MakeResult(EnrollStatus status,
                                                    const std::string& domain) {
    return enroll::mojom::VerifyResult::New(StatusToString(status), domain);
  }

  void OnFetched(std::optional<std::string> body) {
    EnrollStatus status = EnrollStatus::kSuccess;
    const int net_error = loader_->NetError();
    int response_code = -1;
    if (loader_->ResponseInfo() && loader_->ResponseInfo()->headers) {
      response_code = loader_->ResponseInfo()->headers->response_code();
    }
    if (net_error != net::OK) {
      status = net::IsCertificateError(net_error) ? EnrollStatus::kTlsError
                                                  : EnrollStatus::kCannotConnect;
    } else if (response_code != 200) {
      status = EnrollStatus::kHttpError;
    } else if (!body) {
      status = EnrollStatus::kCannotConnect;
    } else {
      const std::vector<std::string> root_keys =
          policy::GetPolicyVerificationKeys();
      EnrollVerifyResult result =
          VerifyFetchedIdentity(base::as_byte_span(*body), pending_domain_,
                                root_keys, base::Time::Now());
      status = result.status;
      if (status == EnrollStatus::kSuccess) {
        pending_entry_ = std::move(result.entry);
      }
    }
    if (pending_verify_callback_) {
      std::move(pending_verify_callback_)
          .Run(MakeResult(status, pending_domain_));
    }
  }

  mojo::Receiver<enroll::mojom::PageHandler> receiver_;
  const raw_ptr<content::WebUI> web_ui_;
  std::string pending_domain_;
  std::optional<ServerIdentityEntry> pending_entry_;
  VerifyCallback pending_verify_callback_;
  std::unique_ptr<network::SimpleURLLoader> loader_;
  base::WeakPtrFactory<EnrollPageHandler> weak_factory_{this};
};

TeleportEnrollUIConfig::TeleportEnrollUIConfig()
    : content::WebUIConfig(content::kChromeUIScheme, kTeleportEnrollHost) {}

TeleportEnrollUIConfig::~TeleportEnrollUIConfig() = default;

std::unique_ptr<content::WebUIController>
TeleportEnrollUIConfig::CreateWebUIController(content::WebUI* web_ui,
                                              const GURL& url) {
  return std::make_unique<TeleportEnrollUI>(web_ui);
}

TeleportEnrollUI::TeleportEnrollUI(content::WebUI* web_ui)
    : ui::MojoWebUIController(web_ui) {
  content::WebUIDataSource* source = content::WebUIDataSource::CreateAndAdd(
      web_ui->GetWebContents()->GetBrowserContext(), kTeleportEnrollHost);
  webui::SetupWebUIDataSource(source, kEnrollResources,
                             IDR_ENROLL_ENROLL_HTML);
}

TeleportEnrollUI::~TeleportEnrollUI() = default;

void TeleportEnrollUI::BindInterface(
    mojo::PendingReceiver<enroll::mojom::PageHandlerFactory> receiver) {
  factory_receiver_.reset();
  factory_receiver_.Bind(std::move(receiver));
}

void TeleportEnrollUI::CreatePageHandler(
    mojo::PendingReceiver<enroll::mojom::PageHandler> handler) {
  page_handler_ =
      std::make_unique<EnrollPageHandler>(std::move(handler), web_ui());
}

WEB_UI_CONTROLLER_TYPE_IMPL(TeleportEnrollUI)

}  // namespace teleport
