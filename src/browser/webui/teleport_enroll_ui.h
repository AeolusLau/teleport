#ifndef TELEPORT_BROWSER_WEBUI_TELEPORT_ENROLL_UI_H_
#define TELEPORT_BROWSER_WEBUI_TELEPORT_ENROLL_UI_H_

#include <memory>

#include "content/public/browser/webui_config.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "teleport/browser/webui/enroll.mojom.h"
#include "ui/webui/mojo_web_ui_controller.h"

namespace content {
class WebUI;
class WebUIController;
}  // namespace content

class GURL;

namespace teleport {

// Host of the enroll page: teleport://enroll (rewritten to chrome://enroll by
// teleport_url_scheme). Private-deployment BYOD users paste a deep link here to
// point the browser at their organization's server (level-4 self-authenticating
// domain acceptance, spec §4.2). Compiled into //chrome/browser/ui/webui, not
// the //teleport source_set (a WebUIController pulls chrome/content headers).
inline constexpr char kTeleportEnrollHost[] = "enroll";

class EnrollPageHandler;

class TeleportEnrollUIConfig : public content::WebUIConfig {
 public:
  TeleportEnrollUIConfig();
  ~TeleportEnrollUIConfig() override;

  std::unique_ptr<content::WebUIController> CreateWebUIController(
      content::WebUI* web_ui,
      const GURL& url) override;
};

class TeleportEnrollUI : public ui::MojoWebUIController,
                          public enroll::mojom::PageHandlerFactory {
 public:
  explicit TeleportEnrollUI(content::WebUI* web_ui);
  TeleportEnrollUI(const TeleportEnrollUI&) = delete;
  TeleportEnrollUI& operator=(const TeleportEnrollUI&) = delete;
  ~TeleportEnrollUI() override;

  // Bound via RegisterWebUIControllerInterfaceBinder in
  // chrome_browser_interface_binders_webui.
  void BindInterface(
      mojo::PendingReceiver<enroll::mojom::PageHandlerFactory> receiver);

 private:
  // enroll::mojom::PageHandlerFactory:
  void CreatePageHandler(
      mojo::PendingReceiver<enroll::mojom::PageHandler> handler) override;

  std::unique_ptr<EnrollPageHandler> page_handler_;
  mojo::Receiver<enroll::mojom::PageHandlerFactory> factory_receiver_{this};

  WEB_UI_CONTROLLER_TYPE_DECL();
};

}  // namespace teleport

#endif  // TELEPORT_BROWSER_WEBUI_TELEPORT_ENROLL_UI_H_
