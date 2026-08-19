// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_service_factory.h"

#include <memory>

#include "base/functional/bind.h"
#include "chrome/browser/profiles/profile.h"
#include "content/public/browser/browser_context.h"
#include "teleport/browser/enterprise/teleport_tunnel_logic.h"
#include "teleport/browser/enterprise/teleport_tunnel_service.h"

namespace teleport {

namespace {

// Resolves a BrowserContext to this profile's service, or null. Null is the
// normal answer for an OTR/guest context: ProfileSelections below selects the
// original regular profile only, so GetServiceForBrowserContext hands back
// nothing rather than silently reporting some other profile's tunnel.
TeleportTunnelService* ServiceFor(content::BrowserContext* context) {
  Profile* profile = Profile::FromBrowserContext(context);
  if (!profile) {
    return nullptr;
  }
  return TeleportTunnelServiceFactory::GetForProfile(profile);
}

tunnel_internal::TunnelStateSnapshot SnapshotFor(
    content::BrowserContext* context) {
  TeleportTunnelService* service = ServiceFor(context);
  return service ? service->GetStateSnapshot()
                 : tunnel_internal::TunnelStateSnapshot();
}

bool RebindFor(content::BrowserContext* context) {
  TeleportTunnelService* service = ServiceFor(context);
  return service && service->Rebind();
}

}  // namespace

TeleportTunnelServiceFactory::TeleportTunnelServiceFactory()
    : ProfileKeyedServiceFactory(
          "TeleportTunnelService",
          ProfileSelections::Builder()
              .WithRegular(ProfileSelection::kOriginalOnly)
              .Build()) {
  // Register the teleport://tunnel diagnostics seam. This constructor runs once
  // per process, from EnsureBrowserContextKeyedServiceFactoriesBuilt() during
  // startup, which is strictly before any WebUI can be created — so the page
  // never observes the unregistered state in a real browser. The page's handler
  // is compiled into //chrome/browser/ui/webui and cannot reach this service
  // directly (GN cycle; see teleport_tunnel_logic.h), hence the callbacks.
  SetTunnelStateProvider(base::BindRepeating(&SnapshotFor));
  SetTunnelRebindRequester(base::BindRepeating(&RebindFor));
}

TeleportTunnelServiceFactory::~TeleportTunnelServiceFactory() = default;

// static
TeleportTunnelService* TeleportTunnelServiceFactory::GetForProfile(
    Profile* profile) {
  return static_cast<TeleportTunnelService*>(
      GetInstance()->GetServiceForBrowserContext(profile, /*create=*/true));
}

// static
TeleportTunnelServiceFactory* TeleportTunnelServiceFactory::GetInstance() {
  static base::NoDestructor<TeleportTunnelServiceFactory> instance;
  return instance.get();
}

std::unique_ptr<KeyedService>
TeleportTunnelServiceFactory::BuildServiceInstanceForBrowserContext(
    content::BrowserContext* context) const {
  return std::make_unique<TeleportTunnelService>(
      Profile::FromBrowserContext(context));
}

}  // namespace teleport
