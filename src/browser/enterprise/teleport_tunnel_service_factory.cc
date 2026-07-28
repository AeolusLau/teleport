// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#include "teleport/browser/enterprise/teleport_tunnel_service_factory.h"

#include <memory>

#include "chrome/browser/profiles/profile.h"
#include "teleport/browser/enterprise/teleport_tunnel_service.h"

namespace teleport {

TeleportTunnelServiceFactory::TeleportTunnelServiceFactory()
    : ProfileKeyedServiceFactory(
          "TeleportTunnelService",
          ProfileSelections::Builder()
              .WithRegular(ProfileSelection::kOriginalOnly)
              .Build()) {}

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
