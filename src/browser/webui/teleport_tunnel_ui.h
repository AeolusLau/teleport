#ifndef TELEPORT_BROWSER_WEBUI_TELEPORT_TUNNEL_UI_H_
#define TELEPORT_BROWSER_WEBUI_TELEPORT_TUNNEL_UI_H_

#include <memory>

#include "content/public/browser/webui_config.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "teleport/browser/webui/tunnel.mojom.h"
#include "ui/webui/mojo_web_ui_controller.h"

namespace content {
class WebUI;
class WebUIController;
}  // namespace content

class GURL;

namespace teleport {

// Host of the tunnel diagnostics page: teleport://tunnel (rewritten to
// chrome://tunnel by teleport_url_scheme). It is the first surface on which the
// tunnel's DERIVED state — the routing table the gate actually sent, what was
// rejected, when the credential lapses, what the edge answered — is visible at
// all. Compiled into //chrome/browser/ui/webui, not the //teleport source_set
// (a WebUIController pulls chrome/content headers), and it reaches the
// per-profile TeleportTunnelService only through the //teleport callback seam
// in teleport_tunnel_logic.h: a direct dependency on //chrome/browser:core
// would close a GN cycle through //chrome/browser/ui/webui:configs.
inline constexpr char kTeleportTunnelHost[] = "tunnel";

class TunnelPageHandler;

class TeleportTunnelUIConfig : public content::WebUIConfig {
 public:
  TeleportTunnelUIConfig();
  ~TeleportTunnelUIConfig() override;

  std::unique_ptr<content::WebUIController> CreateWebUIController(
      content::WebUI* web_ui,
      const GURL& url) override;
};

class TeleportTunnelUI : public ui::MojoWebUIController,
                         public tunnel::mojom::PageHandlerFactory {
 public:
  explicit TeleportTunnelUI(content::WebUI* web_ui);
  TeleportTunnelUI(const TeleportTunnelUI&) = delete;
  TeleportTunnelUI& operator=(const TeleportTunnelUI&) = delete;
  ~TeleportTunnelUI() override;

  // Bound via RegisterWebUIControllerInterfaceBinder in
  // chrome_browser_interface_binders_webui_parts_desktop. Without that
  // registration the page still loads and still compiles clean — it simply
  // hangs forever on its first Mojo call.
  void BindInterface(
      mojo::PendingReceiver<tunnel::mojom::PageHandlerFactory> receiver);

 private:
  // tunnel::mojom::PageHandlerFactory:
  void CreatePageHandler(
      mojo::PendingReceiver<tunnel::mojom::PageHandler> handler) override;

  std::unique_ptr<TunnelPageHandler> page_handler_;
  mojo::Receiver<tunnel::mojom::PageHandlerFactory> factory_receiver_{this};

  WEB_UI_CONTROLLER_TYPE_DECL();
};

}  // namespace teleport

#endif  // TELEPORT_BROWSER_WEBUI_TELEPORT_TUNNEL_UI_H_
