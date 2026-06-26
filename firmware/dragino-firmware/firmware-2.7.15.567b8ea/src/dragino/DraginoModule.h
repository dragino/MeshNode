#pragma once


#include "concurrency/OSThread.h"
#include "meshtastic/mesh.pb.h"
#include "MeshModule.h"
#include "DraginoDefaultConfig.h"
#include <stdint.h>

namespace dragino{



struct DraginoModuleConfig {
    uint32_t sendIntervalMs = 60000;
    uint8_t defaultChannel = 0;
    meshtastic_PortNum defaultPort = meshtastic_PortNum_PRIVATE_APP;
    bool autoSendEnabled = false;
};


using AutoSendCallback = std::function<void()>;
using WakeupCallback = std::function<void()>;

enum WakeupState {
    WAKEUP_IDLE,
    WAKEUP_WAIT_STARTUP,
    WAKEUP_WAIT_RANDOM,
    WAKEUP_SENDING_TELEMETRY,
    WAKEUP_WAITING_GATEWAY,
    WAKEUP_PROCESSING_CMD,
    WAKEUP_WAIT_BT,
    WAKEUP_FINAL_WAIT,
    WAKEUP_READY_SLEEP
};

enum class DraginoWakeReason : uint8_t {
    None,
    Scheduled,
    Timer,
    Button,
    GatewayRequest,
    Unknown,
};

enum class FactoryDiscoveryState : uint8_t {
    Idle,
    WaitStartup,
    Sending,
    PostSendWait,
    ReadySleep,
};

enum class FactoryDiscoveryWakeReason : uint8_t {
    Boot,
    Timer,
    ButtonWake,
    ManualButton,
    Unknown,
};

struct WakeupCommConfig {
    uint32_t startupDelayMs = DRAGINO_DEFAULT_STARTUP_DELAY_MS;
    uint32_t gatewayTimeoutMs = DRAGINO_DEFAULT_GATEWAY_TIMEOUT_MS;
    uint32_t finalWaitMs = DRAGINO_DEFAULT_FINAL_WAIT_MS;
    uint32_t randomDelayMaxMs = DRAGINO_DEFAULT_RANDOM_DELAY_MAX_MS;
    uint32_t degradedActiveWindowMs = DRAGINO_DEGRADED_ACTIVE_WINDOW_MS;
    uint32_t factoryActiveWindowMs = DRAGINO_FACTORY_ACTIVE_WINDOW_MS;
};

class DraginoModule : private concurrency::OSThread
{
    public:
        DraginoModule();

        void setConfig(const DraginoModuleConfig& config);
        const DraginoModuleConfig& getConfig() const;

        void setAutoSendCallback(AutoSendCallback cb);
        void enableAutoSend(bool enable);
        void setSendInterval(uint32_t intervalMs);
        
        void setWakeupCallback(WakeupCallback cb);
        void applySyncWakeupConfig();
        
        void setWakeupCommConfig(const WakeupCommConfig& config);
        void onGatewayCommandReceived();
        void scheduleDataUpload(uint32_t delayMs);
        void requestConfigKeepAwake(uint32_t durationSec);
        void touchConfigKeepAwake();
        void requestManualUpload();
        void requestFactoryManualUpload();
        uint32_t randomDelay();

    protected:
        int32_t runOnce() override;

    private:
        DraginoModuleConfig config_;
        AutoSendCallback onAutoSend_;
        WakeupCallback onWakeup_;
        uint32_t lastSendTime_ = 0;
        
        WakeupState wakeupState_ = WAKEUP_IDLE;
        WakeupCommConfig draginoWakeupCommConfig_;
        uint32_t wakeupStartTime_ = 0;
        uint32_t wakeupStartupDelayMs_ = 0;
        uint32_t gatewayDeadline_ = 0;
        uint32_t finalWaitStart_ = 0;
        bool receivedGatewayCmd_ = false;
        bool uploadScheduled_ = false;
        uint32_t uploadDelay_ = 0;
        uint32_t uploadStartTime_ = 0;
        DraginoWakeReason activeWakeReason_ = DraginoWakeReason::None;
        bool manualUploadRequested_ = false;
        uint32_t manualUploadStartMs_ = 0;
        uint32_t businessRetryAtMs_ = 0;
        uint32_t configKeepAwakeUntilMs_ = 0;
        uint32_t configKeepAwakeDurationMs_ = 0;

        FactoryDiscoveryState factoryDiscoveryState_ = FactoryDiscoveryState::Idle;
        FactoryDiscoveryWakeReason factoryWakeReason_ = FactoryDiscoveryWakeReason::Boot;
        bool factoryEverStarted_ = false;
        bool factoryChallengeRotatedThisSession_ = false;
        bool factoryNeedNodeInfo_ = true;
        bool factoryNeedBusinessData_ = false;
        bool factoryBusinessDataSentThisSession_ = false;
        uint32_t factoryBusinessDataStartMs_ = 0;
        uint32_t factoryStateStartedMs_ = 0;
        uint32_t factoryNextSendMs_ = 0;
        uint32_t factoryPostSendDeadlineMs_ = 0;
        uint8_t factorySendTargetCount_ = 0;
        uint8_t factorySentCount_ = 0;
        uint8_t factoryJoinSinceNodeInfo_ = 0;
        uint32_t factoryLastIdentityMissingLogMs_ = 0;
        uint32_t factoryLastIdentityMissingPhoneMs_ = 0;
        
        // Degraded mode: RTC quality is insufficient.
        uint32_t randomDelayTarget_ = 0;

        bool degradedMode_ = false;
        
        void runWakeupStateMachine();
        void runFactoryMode();
        FactoryDiscoveryWakeReason consumeFactoryWakeReason();
        void startFactoryDiscoverySession(FactoryDiscoveryWakeReason reason);
        void resetFactoryDiscoverySession();
        void runFactoryDiscoveryStateMachine();
        bool ensureFactoryIdentityForDiscovery(uint32_t now);
        bool sendFactoryDiscoveryNodeInfo();
        bool sendFactoryDiscoveryJoinLock();
        bool sendFactoryDiscoveryBusinessData(bool allowInvalidSensor = false);
        bool finishFactoryDiscoverySendWindow(uint32_t now);
        void enterFactoryDiscoverySleep();
        const char *factoryWakeReasonName(FactoryDiscoveryWakeReason reason) const;
        void sendFactoryIdentityMissingPhoneWarning(uint32_t now);
        bool sendWakeupUpload(DraginoWakeReason reason, bool allowInvalidSensor = false);
        bool sendManualBusinessUpload(bool allowInvalidSensor = false);
        bool shouldRetryBusinessUpload(uint32_t startMs, uint32_t nowMs);
        void startGatewayWait();
        bool isConfigKeepAwakeActive(uint32_t nowMs) const;
        void expireConfigKeepAwakeIfNeeded(uint32_t nowMs);
        void savePendingNodeDbBeforeSleep();
        void refreshWakeupCommConfigFromPrivateConfig();
};

extern DraginoModule* draginoModule;



struct Message {
    uint32_t from;
    uint8_t channel;
    uint32_t id;
    const uint8_t* payload;
    size_t payloadSize;
    int32_t rxTime;
};

using ReceiveCallback = std::function<void(const Message& msg)>;

class DraginoModuleRadio : public MeshModule
{

    public:
        DraginoModuleRadio(meshtastic_PortNum port = meshtastic_PortNum_PRIVATE_APP);
    
        void setReceiveCallback(ReceiveCallback cb);

    protected:
        ProcessMessage handleReceived(const meshtastic_MeshPacket& mp) override;
        bool wantPacket(const meshtastic_MeshPacket* p) override;

    private:
        meshtastic_PortNum portNum_;
        uint32_t lastRxId_ = 0;
        ReceiveCallback onReceive_;


};

extern DraginoModuleRadio* draginoModuleRadio;







}
