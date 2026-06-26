#pragma once

#include "DraginoBuildConfig.h"
#include "mesh/ProtobufModule.h"
#include "dragino/protobuf/privateconfig.pb.h"

#define PRIVATE_DRAGINO_CONFIG_PORTNUM static_cast<meshtastic_PortNum>(287)

namespace dragino {

class DraginoConfigModule : public ProtobufModule<temeshtastic_PrivateConfigPacket>
{
public:
    DraginoConfigModule();
    bool sendJoinLockAdvertise(bool force = false);
    void processPendingPrivateConfigActions();
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    void rotateJoinChallengeForDiscovery();
#endif

protected:
    bool handleReceivedProtobuf(const meshtastic_MeshPacket &mp,
                                temeshtastic_PrivateConfigPacket *p) override;

private:
    void handleDownlink(const meshtastic_MeshPacket &mp,
                        const temeshtastic_PrivateConfigPacket_DownlinkPacket &downlink);

    void handleFactoryIdentity(const meshtastic_MeshPacket &mp,
                               const temeshtastic_PrivateConfigPacket_SetDeviceFactoryIdentity &req);
    void handleNetworkConfig(const meshtastic_MeshPacket &mp,
                             const temeshtastic_PrivateConfigPacket_SetNetWorkConfig &req);
    void handleSyncWakeupConfig(const meshtastic_MeshPacket &mp,
                                const temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig &req);
    void handleInfoLabelConfig(const meshtastic_MeshPacket &mp,
                               const temeshtastic_PrivateConfigPacket_SetInfoLabelConfig &req);
    void handleEnterBootloader(const meshtastic_MeshPacket &mp,
                               const temeshtastic_PrivateConfigPacket_EnterBootloader &req);

    void handleChannel12Config(const meshtastic_MeshPacket &mp,
                               const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config &req);
    void handleJoinNetworkV2(const meshtastic_MeshPacket &mp,
                             const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2 &req);
    void handleChangeAdmin(const meshtastic_MeshPacket &mp,
                           const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin &req);
    void handleResetNetworkConfig(const meshtastic_MeshPacket &mp,
                                  const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig &req);
    void handleChangeNetworkKey(const meshtastic_MeshPacket &mp,
                                const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey &req);
    void handleTrustedGatewayConfig(const meshtastic_MeshPacket &mp,
                                    const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig &req);
    void handleGatewayAnnounce(const meshtastic_MeshPacket &mp,
                               const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce &req);

    void sendFactoryIdentityUplink(bool includePrivateKey);
    void sendNetworkConfigUplink(const meshtastic_MeshPacket &mp);
    void sendSyncWakeupUplink();
    void sendLabelsUplink();
    void sendOperationResult(const meshtastic_MeshPacket &mp,
                             temeshtastic_PrivateConfigPacket_OperationResult_Operation operation,
                             temeshtastic_PrivateConfigPacket_OperationResult_Status status,
                             uint32_t gatewayNodeId = 0,
                             uint64_t operationTimestamp = 0,
                             const char *message = nullptr);
    void sendUplink(const temeshtastic_PrivateConfigPacket &packet);

    bool applyChannel12Config(const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config &req);
    bool applyChangeNetworkKey(const uint8_t *newNetworkPublicKey,
                               const uint8_t *newNetworkSeed,
                               pb_size_t newNetworkSeedSize,
                               uint64_t timestamp);
    void processPendingChannel12Config();
    void processPendingResetNetworkConfig();
    void processPendingChangeNetworkKey();

    bool requestFromUpperComputer_ = false;

    bool pendingChannel12Config_ = false;
    uint32_t pendingChannel12ApplyAtMs_ = 0;
    temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config pendingChannel12ConfigData_ =
        temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config_init_zero;

    bool pendingResetNetworkConfig_ = false;
    uint32_t pendingResetNetworkApplyAtMs_ = 0;
    uint32_t pendingResetNetworkType_ = 0;

    bool pendingChangeNetworkKey_ = false;
    uint32_t pendingChangeNetworkKeyApplyAtMs_ = 0;
    uint64_t pendingChangeNetworkKeyTimestamp_ = 0;
    uint8_t pendingNetworkPublicKey_[32] = {};
    uint8_t pendingNetworkSeed_[32] = {};
    pb_size_t pendingNetworkSeedSize_ = 0;

#if defined(DRAGINO_REMOTENODE)
#if defined(DRAGINO_STM32)
    bool buildJoinLockAdvertisePacket(temeshtastic_PrivateConfigPacket &packet, bool updateThrottleOnFailure);
    void sendJoinLockAdvertiseUplink(const meshtastic_MeshPacket &mp);
#endif
    void ensureJoinChallenge();
    void regenerateJoinChallenge();
    void clearJoinChallenge();

    bool hasJoinChallenge_ = false;
    uint8_t joinChallenge_[16] = {};
    uint32_t joinChallengeGeneratedMs_ = 0;
    uint32_t lastJoinAdvertiseMs_ = 0;
#endif
};

extern DraginoConfigModule *draginoConfigModule;

}
