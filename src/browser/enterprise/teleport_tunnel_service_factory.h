// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license.

#ifndef TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_SERVICE_FACTORY_H_
#define TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_SERVICE_FACTORY_H_

#include "base/no_destructor.h"
#include "chrome/browser/profiles/profile_keyed_service_factory.h"

class Profile;

namespace teleport {

class TeleportTunnelService;

// Singleton that owns all TeleportTunnelServices and creates/deletes them as
// Profiles are created/shutdown. Mirrors
// policy::UserPolicyOidcSigninServiceFactory: one service per original
// (non-OTR/guest/system) profile.
//
// GetForProfile() force-creates the service on first call
// (GetServiceForBrowserContext(..., /*create=*/true)) rather than relying on
// ServiceIsCreatedWithBrowserContext(), because the T4 network-context wiring
// (ProfileNetworkContextService::ConfigureNetworkContextParamsInternal) already
// calls GetForProfile() on every profile's NetworkContext (re-)configuration —
// that call site is the de facto eager-creation trigger.
class TeleportTunnelServiceFactory : public ProfileKeyedServiceFactory {
 public:
  // Returns the TeleportTunnelServiceFactory singleton.
  static TeleportTunnelServiceFactory* GetInstance();

  // Returns the TeleportTunnelService instance for `profile`.
  static TeleportTunnelService* GetForProfile(Profile* profile);

  TeleportTunnelServiceFactory(const TeleportTunnelServiceFactory&) = delete;
  TeleportTunnelServiceFactory& operator=(const TeleportTunnelServiceFactory&) =
      delete;

 protected:
  // BrowserContextKeyedServiceFactory:
  std::unique_ptr<KeyedService> BuildServiceInstanceForBrowserContext(
      content::BrowserContext* context) const override;

 private:
  friend base::NoDestructor<TeleportTunnelServiceFactory>;

  TeleportTunnelServiceFactory();
  ~TeleportTunnelServiceFactory() override;
};

}  // namespace teleport

#endif  // TELEPORT_BROWSER_ENTERPRISE_TELEPORT_TUNNEL_SERVICE_FACTORY_H_
