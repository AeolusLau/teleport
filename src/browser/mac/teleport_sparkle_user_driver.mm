#import "teleport/browser/mac/teleport_sparkle_user_driver.h"

#include "base/strings/sys_string_conversions.h"

@implementation TeleportSparkleUserDriver {
  teleport::UpdateStatusSink _sink;
  teleport::UpdateReadyCallback _readyCallback;
  void (^_relaunchReply)(SPUUserUpdateChoice);
  std::string _pendingVersion;
  uint64_t _expectedLength;
  uint64_t _receivedLength;
}

- (void)setStatusSink:(teleport::UpdateStatusSink)sink {
  _sink = std::move(sink);
}

- (void)setReadyCallback:(teleport::UpdateReadyCallback)callback {
  _readyCallback = std::move(callback);
}

- (BOOL)hasPendingUpdate {
  return _relaunchReply != nil;
}

- (void)installPendingUpdateAndRelaunch {
  if (_relaunchReply) {
    void (^reply)(SPUUserUpdateChoice) = _relaunchReply;
    _relaunchReply = nil;
    reply(SPUUserUpdateChoiceInstall);
  }
}

- (void)resurfaceStagedStateToSink {
  [self reportStage:teleport::UpdateStage::kReadyToRelaunch
           progress:0
            message:u""];
}

- (void)reportStage:(teleport::UpdateStage)stage
           progress:(int)progress
            message:(const std::u16string&)message {
  if (_sink) {
    _sink.Run(stage, progress, message);
  }
}

#pragma mark - SPUUserDriver

- (void)showUpdatePermissionRequest:(SPUUpdatePermissionRequest*)request
                              reply:(void (^)(SUUpdatePermissionResponse*))reply {
  reply([[SUUpdatePermissionResponse alloc] initWithAutomaticUpdateChecks:YES
                                                        sendSystemProfile:NO]);
}

- (void)showUserInitiatedUpdateCheckWithCancellation:(void (^)(void))cancellation {
  [self reportStage:teleport::UpdateStage::kChecking progress:0 message:u""];
}

- (void)showUpdateFoundWithAppcastItem:(SUAppcastItem*)appcastItem
                                 state:(SPUUserUpdateState*)state
                                 reply:(void (^)(SPUUserUpdateChoice))reply {
  _pendingVersion = base::SysNSStringToUTF8(appcastItem.versionString);
  if (appcastItem.informationOnlyUpdate) {
    reply(SPUUserUpdateChoiceDismiss);
    return;
  }
  reply(SPUUserUpdateChoiceInstall);  // proceed to download/extract
}

- (void)showUpdateReleaseNotesWithDownloadData:(SPUDownloadData*)downloadData {
}

- (void)showUpdateReleaseNotesFailedToDownloadWithError:(NSError*)error {
}

- (void)showUpdateNotFoundWithError:(NSError*)error
                    acknowledgement:(void (^)(void))acknowledgement {
  [self reportStage:teleport::UpdateStage::kUpToDate progress:0 message:u""];
  acknowledgement();
}

- (void)showUpdaterError:(NSError*)error
         acknowledgement:(void (^)(void))acknowledgement {
  [self reportStage:teleport::UpdateStage::kFailed
           progress:0
            message:base::SysNSStringToUTF16(error.localizedDescription)];
  acknowledgement();
}

- (void)showDownloadInitiatedWithCancellation:(void (^)(void))cancellation {
  _expectedLength = 0;
  _receivedLength = 0;
}

- (void)showDownloadDidReceiveExpectedContentLength:(uint64_t)expectedContentLength {
  _expectedLength = expectedContentLength;
}

- (void)showDownloadDidReceiveDataOfLength:(uint64_t)length {
  _receivedLength += length;
  int progress = 0;
  if (_expectedLength > 0) {
    progress = static_cast<int>((_receivedLength * 100) / _expectedLength);
    if (progress > 100) {
      progress = 100;
    }
  }
  [self reportStage:teleport::UpdateStage::kDownloading
           progress:progress
            message:u""];
}

- (void)showDownloadDidStartExtractingUpdate {
  [self reportStage:teleport::UpdateStage::kExtracting progress:0 message:u""];
}

- (void)showExtractionReceivedProgress:(double)progress {
  [self reportStage:teleport::UpdateStage::kExtracting progress:0 message:u""];
}

- (void)showReadyToInstallAndRelaunch:(void (^)(SPUUserUpdateChoice))reply {
  _relaunchReply = [reply copy];
  [self reportStage:teleport::UpdateStage::kReadyToRelaunch
           progress:0
            message:u""];
  if (_readyCallback && !_pendingVersion.empty()) {
    _readyCallback.Run(_pendingVersion);
  }
}

- (void)showInstallingUpdateWithApplicationTerminated:(BOOL)applicationTerminated
                          retryTerminatingApplication:(void (^)(void))retry {
}

- (void)showUpdateInstalledAndRelaunched:(BOOL)relaunched
                         acknowledgement:(void (^)(void))acknowledgement {
  acknowledgement();
}

- (void)dismissUpdateInstallation {
}

@end
