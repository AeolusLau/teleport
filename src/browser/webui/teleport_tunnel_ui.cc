#include "teleport/browser/webui/teleport_tunnel_ui.h"

#include <memory>
#include <utility>

#include "base/memory/raw_ptr.h"
#include "base/time/time.h"
#include "chrome/grit/tunnel_resources.h"
#include "chrome/grit/tunnel_resources_map.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/common/url_constants.h"
#include "teleport/browser/enterprise/teleport_tunnel_logic.h"
#include "ui/webui/webui_util.h"
#include "url/gurl.h"

namespace teleport {

// Browser-side PageHandler: a pure read of the tunnel state through the
// //teleport seam. It holds no tunnel state of its own and never touches the
// service directly.
class TunnelPageHandler : public tunnel::mojom::PageHandler {
 public:
  TunnelPageHandler(mojo::PendingReceiver<tunnel::mojom::PageHandler> receiver,
                    content::WebUI* web_ui)
      : receiver_(this, std::move(receiver)), web_ui_(web_ui) {}
  TunnelPageHandler(const TunnelPageHandler&) = delete;
  TunnelPageHandler& operator=(const TunnelPageHandler&) = delete;
  ~TunnelPageHandler() override = default;

  // tunnel::mojom::PageHandler:
  void GetState(GetStateCallback callback) override {
    const tunnel_internal::TunnelStateSnapshot snapshot =
        GetTunnelStateSnapshot(BrowserContext());

    auto state = tunnel::mojom::TunnelState::New();
    state->enrolled = snapshot.enrolled;
    state->auto_select_policy_present = snapshot.auto_select_policy_present;
    state->started = snapshot.started;
    state->bind_in_flight = snapshot.bind_in_flight;
    state->has_token = snapshot.has_token;
    state->config_pushed = snapshot.config_pushed;
    state->last_bind_attempt_ms = ToMs(snapshot.last_bind_attempt_at);
    state->last_bind_success_ms = ToMs(snapshot.last_bind_success_at);
    state->token_expires_ms = ToMs(snapshot.token_expires_at);
    state->next_refresh_ms = ToMs(snapshot.next_refresh_at);
    state->next_retry_ms = ToMs(snapshot.next_retry_at);
    state->last_bind_error = snapshot.last_bind_error;
    state->routes_unavailable = snapshot.routes_unavailable;
    state->routes_hard_stale = snapshot.routes_hard_stale;
    state->routes_hard_stale_reason = snapshot.routes_hard_stale_reason;
    state->routes_stale = snapshot.routes_stale;
    state->routes_truncated = snapshot.routes_truncated;
    state->routes_dropped = snapshot.routes_dropped;
    state->routes_digest = snapshot.routes_digest;
    state->edge_host = snapshot.edge_host;
    state->edge_port = snapshot.edge_port;
    state->gate_host = snapshot.gate_host;

    for (const tunnel_internal::RoutableOrigin& origin :
         snapshot.routable_origins) {
      state->routable_origins.push_back(tunnel::mojom::RoutableOrigin::New(
          origin.host, origin.port, origin.include_subdomains,
          origin.blocked));
    }
    for (const tunnel_internal::SkippedEntry& entry :
         snapshot.skipped_entries) {
      state->skipped_entries.push_back(
          tunnel::mojom::SkippedEntry::New(entry.raw, entry.reason));
    }
    for (const tunnel_internal::ConnectResult& result :
         snapshot.recent_connects) {
      state->recent_connects.push_back(tunnel::mojom::ConnectResult::New(
          ToMs(result.time), result.authority, result.response_code));
    }
    std::move(callback).Run(std::move(state));
  }

  void Rebind(RebindCallback callback) override {
    std::move(callback).Run(RequestTunnelRebind(BrowserContext()));
  }

 private:
  // The seam is process-global while the service is per-profile, so the context
  // is what selects whose tunnel is being reported or rebound.
  content::BrowserContext* BrowserContext() {
    return web_ui_->GetWebContents()->GetBrowserContext();
  }

  // 0 stands for "never" / "not armed". base::Time's own null is not
  // representable as a JS date, and a null rendered as the epoch would read as
  // 1970 on the page.
  static double ToMs(base::Time time) {
    return time.is_null() ? 0.0
                          : time.InMillisecondsFSinceUnixEpochIgnoringNull();
  }

  mojo::Receiver<tunnel::mojom::PageHandler> receiver_;
  const raw_ptr<content::WebUI> web_ui_;
};

TeleportTunnelUIConfig::TeleportTunnelUIConfig()
    : content::WebUIConfig(content::kChromeUIScheme, kTeleportTunnelHost) {}

TeleportTunnelUIConfig::~TeleportTunnelUIConfig() = default;

std::unique_ptr<content::WebUIController>
TeleportTunnelUIConfig::CreateWebUIController(content::WebUI* web_ui,
                                              const GURL& url) {
  return std::make_unique<TeleportTunnelUI>(web_ui);
}

TeleportTunnelUI::TeleportTunnelUI(content::WebUI* web_ui)
    : ui::MojoWebUIController(web_ui) {
  content::WebUIDataSource* source = content::WebUIDataSource::CreateAndAdd(
      web_ui->GetWebContents()->GetBrowserContext(), kTeleportTunnelHost);
  webui::SetupWebUIDataSource(source, kTunnelResources,
                              IDR_TUNNEL_TUNNEL_HTML);
}

TeleportTunnelUI::~TeleportTunnelUI() = default;

void TeleportTunnelUI::BindInterface(
    mojo::PendingReceiver<tunnel::mojom::PageHandlerFactory> receiver) {
  factory_receiver_.reset();
  factory_receiver_.Bind(std::move(receiver));
}

void TeleportTunnelUI::CreatePageHandler(
    mojo::PendingReceiver<tunnel::mojom::PageHandler> handler) {
  page_handler_ =
      std::make_unique<TunnelPageHandler>(std::move(handler), web_ui());
}

WEB_UI_CONTROLLER_TYPE_IMPL(TeleportTunnelUI)

}  // namespace teleport
