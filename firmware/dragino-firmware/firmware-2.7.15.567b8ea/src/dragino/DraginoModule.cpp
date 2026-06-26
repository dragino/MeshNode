#include "DraginoModule.h"
#include "DraginoWakeupScheduler.h"
#include "PrivateConfig.h"
#include "sleep.h"
#include "mesh/NodeDB.h"
#include <Arduino.h>
#include <stdio.h>
#include <string.h>

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
#include "DraginoConfigModule.h"
#include "DraginoPeriodicNodeInfo.h"
#include "DraginoWakeupComm.h"
#include "DraginoBluetooth.h"
#include "DraginoBusinessData.h"
#include "DraginoNodeDbSave.h"
#include "DraginoSHT3xSensor.h"
#include "FactoryIdentityManager.h"
#include "Router.h"
#include "mesh/MeshService.h"
#if !MESHTASTIC_EXCLUDE_NODEINFO
#include "modules/NodeInfoModule.h"
#endif
#endif

#if defined(ARCH_STM32WL)
#include "platform/stm32wl/lowpower/Stm32RtcManager.h"
#endif

namespace dragino{

#ifndef DRAGINO_SLEEP_DEBUG_TRACE
#define DRAGINO_SLEEP_DEBUG_TRACE 0
#endif

static void sleepDebugTrace(const char *message)
{
#if DRAGINO_SLEEP_DEBUG_TRACE
    Serial.begin(SERIAL_BAUD);
    Serial.print("[SLPDBG] ");
    Serial.println(message);
    Serial.flush();
#else
    (void)message;
#endif
}


DraginoModule* draginoModule = nullptr;

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
static constexpr bool shouldSaveNodeDbBeforeSleep()
{
#if DRAGINO_SAVE_NODEDB_BEFORE_SLEEP
    return true;
#else
    return false;
#endif
}

static bool elapsedSince(uint32_t startMs, uint32_t nowMs, uint32_t intervalMs)
{
    return (uint32_t)(nowMs - startMs) >= intervalMs;
}

static bool deadlineActive(uint32_t deadlineMs, uint32_t nowMs)
{
    return deadlineMs != 0 && (int32_t)(deadlineMs - nowMs) > 0;
}

static bool deadlineBefore(uint32_t lhsMs, uint32_t rhsMs)
{
    return lhsMs == 0 || (int32_t)(lhsMs - rhsMs) < 0;
}

static uint32_t remainingUntilDeadline(uint32_t deadlineMs, uint32_t nowMs)
{
    if (deadlineMs == 0 || (int32_t)(deadlineMs - nowMs) <= 0) {
        return 0;
    }
    return deadlineMs - nowMs;
}

static void shutdownBluetoothBeforeSleep()
{
    if (draginoBluetooth) {
        sleepDebugTrace("bluetooth shutdown before sleep begin");
        draginoBluetooth->prepareForSleep();
        sleepDebugTrace("bluetooth shutdown before sleep end");
    }
}

static const char *wakeReasonName(DraginoWakeReason reason)
{
    switch (reason) {
    case DraginoWakeReason::None:
        return "none";
    case DraginoWakeReason::Scheduled:
        return "scheduled";
    case DraginoWakeReason::Timer:
        return "timer";
    case DraginoWakeReason::Button:
        return "button";
    case DraginoWakeReason::GatewayRequest:
        return "gateway";
    case DraginoWakeReason::Unknown:
        return "unknown";
    }
    return "unknown";
}

static DraginoWakeReason consumeStopResumeWakeReason()
{
#if defined(ARCH_STM32WL)
    if (!rtcManager.didStopResumeWake()) {
        return DraginoWakeReason::None;
    }

    auto wakeInfo = rtcManager.lastStopResumeWake();
    rtcManager.clearStopResumeWake();

    if (wakeInfo.buttonGateAccepted || wakeInfo.wokeByButton) {
        return DraginoWakeReason::Button;
    }
    if (wakeInfo.wokeByTimer) {
        return DraginoWakeReason::Timer;
    }
    return DraginoWakeReason::Unknown;
#else
    return DraginoWakeReason::None;
#endif
}
#endif

DraginoModule::DraginoModule() : concurrency::OSThread("DraginoModule", 1000) {
    draginoModule = this;
}

void DraginoModule::setConfig(const DraginoModuleConfig& config) {
    config_ = config;
}

const DraginoModuleConfig& DraginoModule::getConfig() const {
    return config_;
}

void DraginoModule::setAutoSendCallback(AutoSendCallback cb) {
    onAutoSend_ = cb;
}

void DraginoModule::enableAutoSend(bool enable) {
    config_.autoSendEnabled = enable;
}

void DraginoModule::setSendInterval(uint32_t intervalMs) {
    config_.sendIntervalMs = intervalMs;
}

void DraginoModule::setWakeupCallback(WakeupCallback cb) {
    onWakeup_ = cb;
}

void DraginoModule::applySyncWakeupConfig() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    refreshWakeupCommConfigFromPrivateConfig();
    draginoWakeupScheduler.onConfigChanged();
#endif
}

void DraginoModule::setWakeupCommConfig(const WakeupCommConfig& config) {
    draginoWakeupCommConfig_ = config;
}

void DraginoModule::onGatewayCommandReceived() {
    receivedGatewayCmd_ = true;
}

void DraginoModule::scheduleDataUpload(uint32_t delayMs) {
    uploadScheduled_ = true;
    uploadDelay_ = delayMs;
    uploadStartTime_ = millis();
}

void DraginoModule::requestConfigKeepAwake(uint32_t durationSec)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    uint32_t now = millis();
    if (durationSec == 0) {
        configKeepAwakeUntilMs_ = 0;
        configKeepAwakeDurationMs_ = 0;
        if (wakeupState_ == WAKEUP_WAITING_GATEWAY) {
            gatewayDeadline_ = now;
        }
        setIntervalFromNow(0);
        concurrency::mainDelay.interrupt();
        LOG_INFO("Wakeup: config keep awake canceled");
        return;
    }

    if (durationSec > DRAGINO_CONFIG_KEEP_AWAKE_MAX_SEC) {
        durationSec = DRAGINO_CONFIG_KEEP_AWAKE_MAX_SEC;
    }

    configKeepAwakeDurationMs_ = durationSec * 1000UL;
    configKeepAwakeUntilMs_ = now + configKeepAwakeDurationMs_;
    if (wakeupState_ == WAKEUP_IDLE ||
        wakeupState_ == WAKEUP_WAIT_BT ||
        wakeupState_ == WAKEUP_FINAL_WAIT ||
        wakeupState_ == WAKEUP_READY_SLEEP) {
        wakeupState_ = WAKEUP_WAITING_GATEWAY;
    }
    if (wakeupState_ == WAKEUP_WAITING_GATEWAY && deadlineBefore(gatewayDeadline_, configKeepAwakeUntilMs_)) {
        gatewayDeadline_ = configKeepAwakeUntilMs_;
    }

    setIntervalFromNow(0);
    concurrency::mainDelay.interrupt();
    LOG_INFO("Wakeup: config keep awake requested for %u sec", durationSec);
#else
    (void)durationSec;
#endif
}

void DraginoModule::touchConfigKeepAwake()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    uint32_t now = millis();
    if (!isConfigKeepAwakeActive(now)) {
        return;
    }

    if (configKeepAwakeDurationMs_ == 0) {
        return;
    }

    configKeepAwakeUntilMs_ = now + configKeepAwakeDurationMs_;
    if (wakeupState_ == WAKEUP_WAITING_GATEWAY) {
        gatewayDeadline_ = configKeepAwakeUntilMs_;
    }
    setIntervalFromNow(0);
    concurrency::mainDelay.interrupt();
    LOG_INFO("Wakeup: config keep awake touched");
#endif
}

void DraginoModule::requestManualUpload() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (!privateConfig.isEnrolled()) {
        LOG_INFO("Wakeup: manual upload ignored before enrollment");
        return;
    }

    manualUploadRequested_ = true;
    setIntervalFromNow(0);
    concurrency::mainDelay.interrupt();
    LOG_INFO("Wakeup: manual upload requested by button");
#endif
}

void DraginoModule::requestFactoryManualUpload() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (privateConfig.isEnrolled()) {
        requestManualUpload();
        return;
    }

    LOG_INFO("Factory discovery: manual upload requested before enrollment");
    resetFactoryDiscoverySession();
    startFactoryDiscoverySession(FactoryDiscoveryWakeReason::ManualButton);
    setIntervalFromNow(0);
    concurrency::mainDelay.interrupt();
#endif
}

uint32_t DraginoModule::randomDelay() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    uint32_t maxDelayMs = draginoWakeupCommConfig_.randomDelayMaxMs;
    if (maxDelayMs == 0) {
        maxDelayMs = DRAGINO_DEFAULT_RANDOM_DELAY_MAX_MS;
    }
    if (maxDelayMs == 0) {
        return 0;
    }

    uint32_t nodePart = (nodeDB->getNodeNum() & 0xFFFF) * 9973UL;
    uint32_t timePart = millis();
    uint32_t randomPart = (uint32_t)random((long)maxDelayMs);
    return (nodePart + timePart + randomPart) % maxDelayMs;
#else
    return 0;
#endif
}

int32_t DraginoModule::runOnce() {
    
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

    if (draginoConfigModule) {
        draginoConfigModule->processPendingPrivateConfigActions();
    }

    // Factory mode uses standalone logic before enrollment and skips the SyncWakeup state machine.
    if (!privateConfig.isEnrolled()) {
        runFactoryMode();
        return 100;
    }

    runWakeupStateMachine();
    return 100; 
#endif
    return 100; 
}

void DraginoModule::runWakeupStateMachine() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    uint32_t nowMs = millis();
    expireConfigKeepAwakeIfNeeded(nowMs);

    DraginoWakeReason newWakeReason = DraginoWakeReason::None;
    if (wakeupState_ == WAKEUP_IDLE) {
        newWakeReason = consumeStopResumeWakeReason();
        if (newWakeReason != DraginoWakeReason::None) {
            draginoWakeupScheduler.onWakeSessionStart();
            LOG_INFO("Wakeup: STOP-resume reason=%s", wakeReasonName(newWakeReason));
        }
    }

    refreshWakeupCommConfigFromPrivateConfig();
    uint32_t sleepMs = draginoWakeupScheduler.calcNextWakeupMs();

    degradedMode_ = !draginoWakeupScheduler.isRtcQualitySufficient();
    bool manualUploadRequested = manualUploadRequested_;
    manualUploadRequested_ = false;

    if (sleepMs == 0) {
        if (manualUploadRequested) {
            LOG_INFO("Wakeup: immediate manual business upload");
            if (!sendManualBusinessUpload()) {
                nowMs = millis();
                if (manualUploadStartMs_ == 0) {
                    manualUploadStartMs_ = nowMs;
                }
                if (!shouldRetryBusinessUpload(manualUploadStartMs_, nowMs)) {
                    LOG_WARN("Wakeup: immediate manual sensor timeout, send invalid business upload");
                    if (sendManualBusinessUpload(true)) {
                        draginoPeriodicNodeInfo.maybeSend("immediate-manual-upload-timeout");
                    }
                    manualUploadStartMs_ = 0;
                } else {
                    manualUploadRequested_ = true;
                }
            } else {
                manualUploadStartMs_ = 0;
                draginoPeriodicNodeInfo.maybeSend("immediate-manual-upload");
            }
        } else if (newWakeReason != DraginoWakeReason::None) {
            LOG_INFO("Wakeup: immediate upload reason=%s", wakeReasonName(newWakeReason));
            if (sendWakeupUpload(newWakeReason)) {
                draginoPeriodicNodeInfo.maybeSend("immediate-wakeup-upload");
            }
        }

        if (config_.autoSendEnabled && onAutoSend_) {
            uint32_t now = millis();
            if (now - lastSendTime_ >= config_.sendIntervalMs) {
                lastSendTime_ = now;
                onAutoSend_();
            }
        }
        return;
    }

    if (manualUploadRequested) {
        activeWakeReason_ = DraginoWakeReason::Button;
        LOG_INFO("Wakeup: manual upload request consumed");
        if (sendManualBusinessUpload()) {
            manualUploadStartMs_ = 0;
            startGatewayWait();
            draginoPeriodicNodeInfo.maybeSend("manual-upload", remainingUntilDeadline(gatewayDeadline_, millis()));
        } else if (manualUploadStartMs_ != 0 &&
                   !shouldRetryBusinessUpload(manualUploadStartMs_, millis())) {
            LOG_WARN("Wakeup: manual sensor timeout, send invalid business upload");
            const bool uploaded = sendManualBusinessUpload(true);
            manualUploadStartMs_ = 0;
            startGatewayWait();
            if (uploaded) {
                draginoPeriodicNodeInfo.maybeSend("manual-upload-timeout", remainingUntilDeadline(gatewayDeadline_, millis()));
            }
        } else {
            if (manualUploadStartMs_ == 0) {
                manualUploadStartMs_ = millis();
            }
            manualUploadRequested_ = true;
        }
        return;
    }
    
    switch (wakeupState_) {
    
    case WAKEUP_IDLE:
        activeWakeReason_ = (newWakeReason != DraginoWakeReason::None)
                                ? newWakeReason
                                : DraginoWakeReason::Scheduled;
        receivedGatewayCmd_ = false;
        uploadScheduled_ = false;
        wakeupState_ = WAKEUP_WAIT_STARTUP;
        wakeupStartTime_ = millis();
        wakeupStartupDelayMs_ = draginoWakeupCommConfig_.startupDelayMs;
        if (wakeupStartupDelayMs_ == 0) {
            wakeupStartupDelayMs_ = DRAGINO_DEFAULT_STARTUP_DELAY_MS;
        }
        if (activeWakeReason_ == DraginoWakeReason::Button) {
            wakeupStartupDelayMs_ = DRAGINO_BUTTON_WAKE_UPLOAD_DELAY_MS;
            if (DRAGINO_BUTTON_WAKE_UPLOAD_RANDOM_MAX_MS > 0) {
                wakeupStartupDelayMs_ += (uint32_t)random((long)DRAGINO_BUTTON_WAKE_UPLOAD_RANDOM_MAX_MS);
            }
        }
        LOG_INFO("Wakeup: waiting startup delay %u ms (reason=%s)",
                 wakeupStartupDelayMs_,
                 wakeReasonName(activeWakeReason_));
        break;
        
    case WAKEUP_WAIT_STARTUP:
        if (millis() - wakeupStartTime_ >= wakeupStartupDelayMs_) {
            if (activeWakeReason_ == DraginoWakeReason::Button) {
                wakeupState_ = WAKEUP_SENDING_TELEMETRY;
                wakeupStartTime_ = millis();
                businessRetryAtMs_ = 0;
                LOG_INFO("Wakeup: manual wake startup done, sending upload");
            } else {
                uint32_t delayMs = randomDelay();
                wakeupState_ = WAKEUP_WAIT_RANDOM;
                randomDelayTarget_ = millis() + delayMs;
                LOG_INFO("Wakeup: startup done, random delay %u ms", delayMs);
            }
        }
        break;

    case WAKEUP_WAIT_RANDOM:
        if (millis() >= randomDelayTarget_) {
            wakeupState_ = WAKEUP_SENDING_TELEMETRY;
            wakeupStartTime_ = millis();
            businessRetryAtMs_ = 0;
            LOG_INFO("Wakeup: random delay done, sending upload");
        }
        break;
        
    case WAKEUP_SENDING_TELEMETRY:
        nowMs = millis();
        if (businessRetryAtMs_ != 0 && (int32_t)(nowMs - businessRetryAtMs_) < 0) {
            break;
        }
        if (sendWakeupUpload(activeWakeReason_)) {
            businessRetryAtMs_ = 0;
            startGatewayWait();
            draginoPeriodicNodeInfo.maybeSend("scheduled-upload", remainingUntilDeadline(gatewayDeadline_, millis()));
        } else if (!shouldRetryBusinessUpload(wakeupStartTime_, nowMs)) {
            businessRetryAtMs_ = 0;
            LOG_WARN("Wakeup: sensor timeout, send invalid business upload");
            const bool uploaded = sendWakeupUpload(activeWakeReason_, true);
            startGatewayWait();
            if (uploaded) {
                draginoPeriodicNodeInfo.maybeSend("scheduled-upload-timeout", remainingUntilDeadline(gatewayDeadline_, millis()));
            }
        } else {
            businessRetryAtMs_ = nowMs + DRAGINO_SENSOR_DATA_READY_RETRY_MS;
        }
        break;
        
    case WAKEUP_WAITING_GATEWAY:
        nowMs = millis();
        if (isConfigKeepAwakeActive(nowMs) && deadlineBefore(gatewayDeadline_, configKeepAwakeUntilMs_)) {
            gatewayDeadline_ = configKeepAwakeUntilMs_;
        }
        if (receivedGatewayCmd_) {
            receivedGatewayCmd_ = false;
            wakeupState_ = WAKEUP_PROCESSING_CMD;
            LOG_INFO("Wakeup: processing command");
        } else if (!isConfigKeepAwakeActive(nowMs) && millis() >= gatewayDeadline_) {
            wakeupState_ = WAKEUP_WAIT_BT;
            LOG_INFO("Wakeup: gateway timeout, waiting BT");
        } else {
            draginoPeriodicNodeInfo.maybeSend("gateway-wait", remainingUntilDeadline(gatewayDeadline_, nowMs));
        }
        break;
        
    case WAKEUP_PROCESSING_CMD:
        if (uploadScheduled_) {
            if (millis() - uploadStartTime_ >= uploadDelay_) {
                nowMs = millis();
                if (businessRetryAtMs_ != 0 && (int32_t)(nowMs - businessRetryAtMs_) < 0) {
                    break;
                }
                if (sendWakeupUpload(DraginoWakeReason::GatewayRequest)) {
                    businessRetryAtMs_ = 0;
                    uploadScheduled_ = false;
                    wakeupState_ = WAKEUP_WAIT_BT;
                    draginoPeriodicNodeInfo.maybeSend("gateway-request-upload", draginoWakeupCommConfig_.finalWaitMs);
                    LOG_INFO("Wakeup: scheduled data uploaded, waiting BT");
                } else if (!shouldRetryBusinessUpload(uploadStartTime_, nowMs)) {
                    businessRetryAtMs_ = 0;
                    uploadScheduled_ = false;
                    wakeupState_ = WAKEUP_WAIT_BT;
                    LOG_WARN("Wakeup: gateway-requested sensor timeout, send invalid business upload");
                    if (sendWakeupUpload(DraginoWakeReason::GatewayRequest, true)) {
                        draginoPeriodicNodeInfo.maybeSend("gateway-request-upload-timeout",
                                                          draginoWakeupCommConfig_.finalWaitMs);
                    }
                } else {
                    businessRetryAtMs_ = nowMs + DRAGINO_SENSOR_DATA_READY_RETRY_MS;
                }
            }
        } else {
            wakeupState_ = WAKEUP_WAIT_BT;
        }
        break;
        
    case WAKEUP_WAIT_BT:
        if (isConfigKeepAwakeActive(millis())) {
            wakeupState_ = WAKEUP_WAITING_GATEWAY;
            gatewayDeadline_ = configKeepAwakeUntilMs_;
            LOG_INFO("Wakeup: config keep awake active, continue gateway wait");
            break;
        }
        if (!draginoBluetooth || draginoBluetooth->canSleep()) {
            wakeupState_ = WAKEUP_FINAL_WAIT;
            finalWaitStart_ = millis();
        } else {
            draginoBluetooth->shutdown();
            wakeupState_ = WAKEUP_FINAL_WAIT;
            finalWaitStart_ = millis();
        }
        break;

    case WAKEUP_FINAL_WAIT:
        if (isConfigKeepAwakeActive(millis())) {
            wakeupState_ = WAKEUP_WAITING_GATEWAY;
            gatewayDeadline_ = configKeepAwakeUntilMs_;
            LOG_INFO("Wakeup: config keep awake active, skip final sleep");
            break;
        }
        if (millis() - finalWaitStart_ >= draginoWakeupCommConfig_.finalWaitMs) {
            wakeupState_ = WAKEUP_READY_SLEEP;
        } else {
            const uint32_t elapsedMs = millis() - finalWaitStart_;
            draginoPeriodicNodeInfo.maybeSend("final-wait", draginoWakeupCommConfig_.finalWaitMs - elapsedMs);
        }
        break;
        
    case WAKEUP_READY_SLEEP:
        if (isConfigKeepAwakeActive(millis())) {
            wakeupState_ = WAKEUP_WAITING_GATEWAY;
            gatewayDeadline_ = configKeepAwakeUntilMs_;
            LOG_INFO("Wakeup: config keep awake active, sleep delayed");
            break;
        }
        wakeupState_ = WAKEUP_IDLE;
        activeWakeReason_ = DraginoWakeReason::None;
        wakeupStartupDelayMs_ = 0;
        businessRetryAtMs_ = 0;
        manualUploadStartMs_ = 0;
        sleepMs = draginoWakeupScheduler.calcNextWakeupMs(false);
        LOG_INFO("Wakeup: sleeping for %u sec (%u min)", sleepMs / 1000, sleepMs / 60000);
        savePendingNodeDbBeforeSleep();
#if DRAGINO_AUTO_SLEEP_ENABLE
        shutdownBluetoothBeforeSleep();
        doDeepSleep(sleepMs, true, !shouldSaveNodeDbBeforeSleep());
#endif
        break;
    }
#endif
}

bool DraginoModule::sendWakeupUpload(DraginoWakeReason reason, bool allowInvalidSensor) {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    LOG_INFO("Wakeup: sending upload reason=%s", wakeReasonName(reason));

    if (draginoBusinessData.isSensorBusinessDataEnabled() &&
        !allowInvalidSensor &&
        !draginoBusinessData.isSensorDataReady()) {
        LOG_INFO("Wakeup: defer upload, sensor data not stable");
        return false;
    }

    if (draginoBusinessData.isSensorBusinessDataEnabled() &&
        !draginoBusinessData.sendTestSensorData(allowInvalidSensor)) {
        return false;
    }

    if (draginoWakeupComm) {
        draginoWakeupComm->sendTelemetry();
        // draginoWakeupComm->sendPrivateConfig();
    }
    if (onWakeup_) {
        onWakeup_();
    }
    return true;
#else
    (void)reason;
    (void)allowInvalidSensor;
    return true;
#endif
}

bool DraginoModule::sendManualBusinessUpload(bool allowInvalidSensor)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    LOG_INFO("Wakeup: sending manual business upload");
    if (!draginoBusinessData.isSensorBusinessDataEnabled()) {
        return true;
    }
    if (!allowInvalidSensor && !draginoBusinessData.isSensorDataReady()) {
        LOG_INFO("Wakeup: defer manual business upload, sensor data not stable");
        return false;
    }
    return draginoBusinessData.sendTestSensorData(allowInvalidSensor);
#else
    (void)allowInvalidSensor;
    return true;
#endif
}

bool DraginoModule::shouldRetryBusinessUpload(uint32_t startMs, uint32_t nowMs)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    return (uint32_t)(nowMs - startMs) < (uint32_t)DRAGINO_SENSOR_DATA_READY_TIMEOUT_MS;
#else
    (void)startMs;
    (void)nowMs;
    return false;
#endif
}

bool DraginoModule::isConfigKeepAwakeActive(uint32_t nowMs) const
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    return deadlineActive(configKeepAwakeUntilMs_, nowMs);
#else
    (void)nowMs;
    return false;
#endif
}

void DraginoModule::expireConfigKeepAwakeIfNeeded(uint32_t nowMs)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (configKeepAwakeUntilMs_ != 0 && !isConfigKeepAwakeActive(nowMs)) {
        configKeepAwakeUntilMs_ = 0;
        configKeepAwakeDurationMs_ = 0;
        LOG_INFO("Wakeup: config keep awake expired");
    }
#else
    (void)nowMs;
#endif
}

void DraginoModule::startGatewayWait() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    wakeupState_ = WAKEUP_WAITING_GATEWAY;
    uint32_t timeout = degradedMode_
        ? draginoWakeupCommConfig_.degradedActiveWindowMs
        : draginoWakeupCommConfig_.gatewayTimeoutMs;
    uint32_t now = millis();
    gatewayDeadline_ = now + timeout;
    if (isConfigKeepAwakeActive(now) && deadlineBefore(gatewayDeadline_, configKeepAwakeUntilMs_)) {
        gatewayDeadline_ = configKeepAwakeUntilMs_;
    }
    LOG_INFO("Wakeup: waiting gateway response %u ms (degraded=%d)", timeout, degradedMode_);
#endif
}

void DraginoModule::savePendingNodeDbBeforeSleep() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (shouldSaveNodeDbBeforeSleep()) {
        return;
    }

    if (!dragino::isNodeDbSavePending()) {
        return;
    }

    LOG_INFO("Wakeup: saving pending NodeDB before sleep");
    if (nodeDB->saveToDisk(SEGMENT_NODEDATABASE)) {
        dragino::clearNodeDbSavePending();
    } else {
        LOG_WARN("Wakeup: failed to save pending NodeDB before sleep");
    }
#endif
}

void DraginoModule::runFactoryMode() {
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    refreshWakeupCommConfigFromPrivateConfig();

    if (privateConfig.isEnrolled()) {
        resetFactoryDiscoverySession();
        return;
    }

    if (factoryDiscoveryState_ == FactoryDiscoveryState::Idle) {
        startFactoryDiscoverySession(consumeFactoryWakeReason());
    }

    runFactoryDiscoveryStateMachine();
#endif
}

FactoryDiscoveryWakeReason DraginoModule::consumeFactoryWakeReason()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
#if defined(ARCH_STM32WL)
    if (rtcManager.didStopResumeWake()) {
        auto wakeInfo = rtcManager.lastStopResumeWake();
        rtcManager.clearStopResumeWake();

        if (wakeInfo.buttonGateAccepted || wakeInfo.wokeByButton) {
            return FactoryDiscoveryWakeReason::ButtonWake;
        }
        if (wakeInfo.wokeByTimer) {
            return FactoryDiscoveryWakeReason::Timer;
        }
        return FactoryDiscoveryWakeReason::Unknown;
    }
#endif

    if (!factoryEverStarted_) {
        return FactoryDiscoveryWakeReason::Boot;
    }

    return FactoryDiscoveryWakeReason::Unknown;
#else
    return FactoryDiscoveryWakeReason::Unknown;
#endif
}

void DraginoModule::startFactoryDiscoverySession(FactoryDiscoveryWakeReason reason)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    factoryEverStarted_ = true;
    factoryWakeReason_ = reason;
    factoryDiscoveryState_ = FactoryDiscoveryState::WaitStartup;
    factoryChallengeRotatedThisSession_ = false;
    factoryNeedNodeInfo_ = true;
    factoryNeedBusinessData_ = false;
    factoryBusinessDataSentThisSession_ = false;
    factoryBusinessDataStartMs_ = 0;
    factorySentCount_ = 0;
    factoryJoinSinceNodeInfo_ = 0;

    uint32_t delayMs = DRAGINO_FACTORY_DISCOVERY_WAKE_DELAY_MS;
    switch (reason) {
    case FactoryDiscoveryWakeReason::Boot:
        factorySendTargetCount_ = DRAGINO_FACTORY_DISCOVERY_BOOT_BURST_COUNT;
        delayMs = DRAGINO_FACTORY_DISCOVERY_BOOT_DELAY_MS;
        break;
    case FactoryDiscoveryWakeReason::ButtonWake:
        factorySendTargetCount_ = DRAGINO_FACTORY_DISCOVERY_BUTTON_SEND_COUNT;
        break;
    case FactoryDiscoveryWakeReason::ManualButton:
        factorySendTargetCount_ = DRAGINO_FACTORY_DISCOVERY_BUTTON_SEND_COUNT;
        delayMs = 0;
        break;
    case FactoryDiscoveryWakeReason::Timer:
    case FactoryDiscoveryWakeReason::Unknown:
    default:
        factorySendTargetCount_ = DRAGINO_FACTORY_DISCOVERY_TIMER_SEND_COUNT;
        break;
    }

    if (factorySendTargetCount_ == 0) {
        factorySendTargetCount_ = 1;
    }

    factoryStateStartedMs_ = millis();
    factoryNextSendMs_ = factoryStateStartedMs_ + delayMs;

    LOG_INFO("Factory discovery: start reason=%s target=%u delay=%u ms interval=%u ms",
             factoryWakeReasonName(reason),
             factorySendTargetCount_,
             delayMs,
             DRAGINO_FACTORY_DISCOVERY_MESSAGE_INTERVAL_MS);
#else
    (void)reason;
#endif
}

void DraginoModule::resetFactoryDiscoverySession()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    factoryDiscoveryState_ = FactoryDiscoveryState::Idle;
    factoryWakeReason_ = FactoryDiscoveryWakeReason::Unknown;
    factoryChallengeRotatedThisSession_ = false;
    factoryNeedNodeInfo_ = true;
    factoryNeedBusinessData_ = false;
    factoryBusinessDataSentThisSession_ = false;
    factoryBusinessDataStartMs_ = 0;
    factoryStateStartedMs_ = 0;
    factoryNextSendMs_ = 0;
    factoryPostSendDeadlineMs_ = 0;
    factorySendTargetCount_ = 0;
    factorySentCount_ = 0;
    factoryJoinSinceNodeInfo_ = 0;
#endif
}

void DraginoModule::runFactoryDiscoveryStateMachine()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    const uint32_t now = millis();

    if (privateConfig.isEnrolled()) {
        LOG_INFO("Factory discovery: enrolled, stop discovery");
        resetFactoryDiscoverySession();
        return;
    }

    switch (factoryDiscoveryState_) {
    case FactoryDiscoveryState::WaitStartup:
        if ((int32_t)(now - factoryNextSendMs_) < 0) {
            return;
        }

        if (!ensureFactoryIdentityForDiscovery(now)) {
            factoryNextSendMs_ = now + DRAGINO_FACTORY_IDENTITY_MISSING_RETRY_MS;
            return;
        }

#if DRAGINO_FACTORY_DISCOVERY_ROTATE_CHALLENGE_PER_SESSION
        if (!factoryChallengeRotatedThisSession_ && draginoConfigModule) {
            draginoConfigModule->rotateJoinChallengeForDiscovery();
            factoryChallengeRotatedThisSession_ = true;
        }
#endif

        factoryDiscoveryState_ = FactoryDiscoveryState::Sending;
        factoryNextSendMs_ = now;
        break;

    case FactoryDiscoveryState::Sending:
        if ((int32_t)(now - factoryNextSendMs_) < 0) {
            return;
        }

        if (factoryNeedNodeInfo_) {
            if (sendFactoryDiscoveryNodeInfo()) {
                factoryNeedNodeInfo_ = false;
                factoryJoinSinceNodeInfo_ = 0;
                LOG_INFO("Factory discovery: NodeInfo sent, next message slot in %u ms",
                         DRAGINO_FACTORY_DISCOVERY_MESSAGE_INTERVAL_MS);
                if (finishFactoryDiscoverySendWindow(now)) {
                    return;
                }
            } else {
                LOG_WARN("Factory discovery: NodeInfo send skipped, retry next slot");
            }
            factoryNextSendMs_ = now + DRAGINO_FACTORY_DISCOVERY_MESSAGE_INTERVAL_MS;
            return;
        }

#if DRAGINO_FACTORY_MANUAL_SEND_BUSINESS_DATA
        if (factoryNeedBusinessData_) {
            if (!sendFactoryDiscoveryBusinessData()) {
                if (factoryBusinessDataStartMs_ == 0) {
                    factoryBusinessDataStartMs_ = now;
                }
                if (shouldRetryBusinessUpload(factoryBusinessDataStartMs_, now)) {
                    factoryNextSendMs_ = now + DRAGINO_SENSOR_DATA_READY_RETRY_MS;
                    LOG_INFO("Factory discovery: defer manual business data, retry in %u ms",
                             DRAGINO_SENSOR_DATA_READY_RETRY_MS);
                    return;
                }
                LOG_WARN("Factory discovery: sensor timeout, send invalid business data");
                (void)sendFactoryDiscoveryBusinessData(true);
            }
            factoryNeedBusinessData_ = false;
            factoryBusinessDataSentThisSession_ = true;
            factoryBusinessDataStartMs_ = 0;
            factoryPostSendDeadlineMs_ = now + DRAGINO_FACTORY_DISCOVERY_BUTTON_WAIT_MS;
            factoryDiscoveryState_ = FactoryDiscoveryState::PostSendWait;
            LOG_INFO("Factory discovery: manual business data sent, post-send wait %u ms",
                     DRAGINO_FACTORY_DISCOVERY_BUTTON_WAIT_MS);
            return;
        }
#endif

        if (sendFactoryDiscoveryJoinLock()) {
            factorySentCount_++;
            factoryJoinSinceNodeInfo_++;
            LOG_INFO("Factory discovery: join advertise %u/%u",
                     factorySentCount_,
                     factorySendTargetCount_);
        }

        if (DRAGINO_FACTORY_DISCOVERY_NODEINFO_EVERY_JOINLOCKS > 0 &&
            factoryJoinSinceNodeInfo_ >= DRAGINO_FACTORY_DISCOVERY_NODEINFO_EVERY_JOINLOCKS) {
            factoryNeedNodeInfo_ = true;
            factoryNextSendMs_ = now + DRAGINO_FACTORY_DISCOVERY_MESSAGE_INTERVAL_MS;
            return;
        }

        if (finishFactoryDiscoverySendWindow(now)) {
            return;
        }

        factoryNextSendMs_ = now + DRAGINO_FACTORY_DISCOVERY_MESSAGE_INTERVAL_MS;
        return;

    case FactoryDiscoveryState::PostSendWait:
        if ((int32_t)(now - factoryPostSendDeadlineMs_) < 0) {
            return;
        }
        factoryDiscoveryState_ = FactoryDiscoveryState::ReadySleep;
        break;

    case FactoryDiscoveryState::ReadySleep:
        enterFactoryDiscoverySleep();
        return;

    case FactoryDiscoveryState::Idle:
    default:
        factoryDiscoveryState_ = FactoryDiscoveryState::Idle;
        return;
    }
#endif
}

bool DraginoModule::ensureFactoryIdentityForDiscovery(uint32_t now)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (!privateConfig.hasValidFactoryIdentity()) {
        privateConfig.syncFactoryIdentityFromStorage(false);
    }
    if (!privateConfig.hasValidFactoryIdentity()) {
        sendFactoryIdentityMissingPhoneWarning(now);
        if (factoryLastIdentityMissingLogMs_ == 0 ||
            elapsedSince(factoryLastIdentityMissingLogMs_, now, 30 * 1000UL)) {
            LOG_WARN("Factory discovery: disabled, factory identity missing");
            factoryLastIdentityMissingLogMs_ = now;
        }
        return false;
    }

    factoryLastIdentityMissingLogMs_ = 0;
    factoryLastIdentityMissingPhoneMs_ = 0;
    return true;
#else
    (void)now;
    return false;
#endif
}

bool DraginoModule::sendFactoryDiscoveryNodeInfo()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
#if !MESHTASTIC_EXCLUDE_NODEINFO
    if (nodeInfoModule) {
        LOG_INFO("Factory discovery: broadcast NodeInfo");
        nodeInfoModule->sendOurNodeInfo(NODENUM_BROADCAST, false, 0, true);
        return true;
    }
    LOG_WARN("Factory discovery: NodeInfoModule unavailable");
#endif
#endif
    return false;
}

bool DraginoModule::sendFactoryDiscoveryJoinLock()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (!draginoConfigModule) {
        LOG_WARN("Factory discovery: DraginoConfigModule unavailable");
        return false;
    }
    return draginoConfigModule->sendJoinLockAdvertise(true);
#else
    return false;
#endif
}

bool DraginoModule::sendFactoryDiscoveryBusinessData(bool allowInvalidSensor)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    LOG_INFO("Factory discovery: send business data before enrollment");
    if (!draginoBusinessData.isSensorBusinessDataEnabled()) {
        return true;
    }
    if (!allowInvalidSensor && !draginoBusinessData.isSensorDataReady()) {
        LOG_INFO("Factory discovery: defer business data, sensor data not stable");
        return false;
    }
    return draginoBusinessData.sendPreEnrollmentSensorData(allowInvalidSensor);
#else
    (void)allowInvalidSensor;
    return true;
#endif
}

bool DraginoModule::finishFactoryDiscoverySendWindow(uint32_t now)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (factorySentCount_ < factorySendTargetCount_) {
        return false;
    }

#if DRAGINO_FACTORY_MANUAL_SEND_BUSINESS_DATA
    if (factoryWakeReason_ == FactoryDiscoveryWakeReason::ManualButton &&
        !factoryBusinessDataSentThisSession_) {
        factoryNeedBusinessData_ = true;
        factoryNextSendMs_ = now + DRAGINO_FACTORY_DISCOVERY_MESSAGE_INTERVAL_MS;
        LOG_INFO("Factory discovery: manual business data scheduled in %u ms",
                 DRAGINO_FACTORY_DISCOVERY_MESSAGE_INTERVAL_MS);
        return true;
    }
#endif

    uint32_t waitMs = DRAGINO_FACTORY_DISCOVERY_POST_SEND_WAIT_MS;
    if (factoryWakeReason_ == FactoryDiscoveryWakeReason::ButtonWake ||
        factoryWakeReason_ == FactoryDiscoveryWakeReason::ManualButton) {
        waitMs = DRAGINO_FACTORY_DISCOVERY_BUTTON_WAIT_MS;
    }

    factoryPostSendDeadlineMs_ = now + waitMs;
    factoryDiscoveryState_ = FactoryDiscoveryState::PostSendWait;
    sleepDebugTrace("factory post-send wait armed");
    LOG_INFO("Factory discovery: post-send wait %u ms", waitMs);
    return true;
#else
    (void)now;
    return false;
#endif
}

void DraginoModule::enterFactoryDiscoverySleep()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    sleepDebugTrace("factory sleep enter");
    LOG_INFO("Factory discovery: sleeping for %u sec",
             DRAGINO_FACTORY_DISCOVERY_SLEEP_MS / 1000);

    factoryDiscoveryState_ = FactoryDiscoveryState::Idle;
    factoryWakeReason_ = FactoryDiscoveryWakeReason::Unknown;
    factoryChallengeRotatedThisSession_ = false;
    factoryNeedNodeInfo_ = true;
    factoryNeedBusinessData_ = false;
    factoryBusinessDataSentThisSession_ = false;
    factoryBusinessDataStartMs_ = 0;
    factorySentCount_ = 0;
    factorySendTargetCount_ = 0;
    factoryJoinSinceNodeInfo_ = 0;

    sleepDebugTrace("factory before save nodedb");
    savePendingNodeDbBeforeSleep();
#if DRAGINO_AUTO_SLEEP_ENABLE
    shutdownBluetoothBeforeSleep();
    sleepDebugTrace("factory before doDeepSleep");
    doDeepSleep(DRAGINO_FACTORY_DISCOVERY_SLEEP_MS,
                true,
                !shouldSaveNodeDbBeforeSleep());
#endif
#endif
}

const char *DraginoModule::factoryWakeReasonName(FactoryDiscoveryWakeReason reason) const
{
    switch (reason) {
    case FactoryDiscoveryWakeReason::Boot:
        return "boot";
    case FactoryDiscoveryWakeReason::Timer:
        return "timer";
    case FactoryDiscoveryWakeReason::ButtonWake:
        return "button";
    case FactoryDiscoveryWakeReason::ManualButton:
        return "manual-button";
    case FactoryDiscoveryWakeReason::Unknown:
    default:
        return "unknown";
    }
}

void DraginoModule::sendFactoryIdentityMissingPhoneWarning(uint32_t now)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (factoryLastIdentityMissingPhoneMs_ != 0 &&
        !elapsedSince(factoryLastIdentityMissingPhoneMs_,
                      now,
                      DRAGINO_FACTORY_IDENTITY_WARNING_TO_PHONE_INTERVAL_MS)) {
        return;
    }
    factoryLastIdentityMissingPhoneMs_ = now;

    if (!router || !service) {
        return;
    }

    temeshtastic_DeviceFactoryIdentity identity = temeshtastic_DeviceFactoryIdentity_init_zero;
    auto status = factoryIdentity.read(identity);

    meshtastic_MeshPacket *p = router->allocForSending();
    if (!p) {
        return;
    }

    p->to = nodeDB->getNodeNum();
    p->channel = 0;
    p->want_ack = false;
    p->decoded.portnum = meshtastic_PortNum_TEXT_MESSAGE_APP;

    char text[128] = {};
    snprintf(text,
             sizeof(text),
             "[Dragino] FactoryIdentity missing: status=%s legacy=0x%08x",
             factoryIdentity.statusName(status),
             (unsigned)DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS);

    size_t len = strlen(text);
    if (len > sizeof(p->decoded.payload.bytes)) {
        len = sizeof(p->decoded.payload.bytes);
    }
    memcpy(p->decoded.payload.bytes, text, len);
    p->decoded.payload.size = len;

    service->sendToPhone(p);
#else
    (void)now;
#endif
}

void DraginoModule::refreshWakeupCommConfigFromPrivateConfig()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    const auto &window = privateConfig.getWakeupWindow();
    draginoWakeupCommConfig_.startupDelayMs = window.startup_delay_sec * 1000UL;
    draginoWakeupCommConfig_.randomDelayMaxMs = window.random_delay_max_sec * 1000UL;
    draginoWakeupCommConfig_.gatewayTimeoutMs = window.gateway_wait_sec * 1000UL;
    draginoWakeupCommConfig_.finalWaitMs = window.final_wait_sec * 1000UL;
    draginoWakeupCommConfig_.degradedActiveWindowMs = window.degraded_window_sec * 1000UL;
    draginoWakeupCommConfig_.factoryActiveWindowMs = window.factory_window_sec * 1000UL;
#endif
}














DraginoModuleRadio::DraginoModuleRadio(meshtastic_PortNum port) 
    : MeshModule("DraginoModuleRadio"), portNum_(port) {
    draginoModuleRadio = this;
}

void DraginoModuleRadio::setReceiveCallback(ReceiveCallback cb) {
    onReceive_ = cb;
}
bool DraginoModuleRadio::wantPacket(const meshtastic_MeshPacket* p) {
    return p->decoded.portnum == portNum_;
}
ProcessMessage DraginoModuleRadio::handleReceived(const meshtastic_MeshPacket& mp) {
    // Ignore packets sent by ourselves.
    if (isFromUs(&mp)) {
        return ProcessMessage::CONTINUE;
    }
    
    // Drop duplicate packets.
    if (mp.id == lastRxId_) {
        return ProcessMessage::CONTINUE;
    }
    lastRxId_ = mp.id;
    
    // Ignore empty payloads.
    if (mp.decoded.payload.size == 0) {
        return ProcessMessage::CONTINUE;
    }
    
    // Notify the receive callback.
    if (onReceive_) {
        Message msg;
        msg.from = mp.from;
        msg.channel = mp.channel;
        msg.id = mp.id;
        msg.payload = mp.decoded.payload.bytes;
        msg.payloadSize = mp.decoded.payload.size;
        msg.rxTime = mp.rx_time;
        
        onReceive_(msg);
    }
    
    return ProcessMessage::CONTINUE;
}


DraginoModuleRadio* draginoModuleRadio = nullptr;














}
