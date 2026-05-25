#ifndef TELEPORT_BROWSER_TELEPORT_STARTUP_H_
#define TELEPORT_BROWSER_TELEPORT_STARTUP_H_

namespace teleport {

// One-line banner identifying the teleport overlay build.
const char* StartupBanner();

// Logs the startup banner. Called from an early browser-startup hook.
void LogStartupBanner();

}  // namespace teleport

#endif  // TELEPORT_BROWSER_TELEPORT_STARTUP_H_
