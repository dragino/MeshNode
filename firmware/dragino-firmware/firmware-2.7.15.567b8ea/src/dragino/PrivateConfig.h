#pragma once

#include <Arduino.h>
#include "dragino/protobuf/privateconfig.pb.h"
#include "DraginoDefaultConfig.h"

class PrivateConfigManager {
public:
    static PrivateConfigManager& instance();

    bool loadConfig();
    bool saveConfig();
    temeshtastic_PrivateConfig& getConfig() { return _config; }

    bool loadLabels();
    bool saveLabels();
    temeshtastic_DeviceLabels& getLabels() { return _labels; }

    bool addInfoLabel(uint32_t id, const char* key, const char* value);
    bool updateInfoLabel(uint32_t id, const char* value);
    bool deleteInfoLabel(uint32_t id);
    const temeshtastic_DeviceLabels_InfoLabel* findInfoLabel(uint32_t id);
    const temeshtastic_DeviceLabels_InfoLabel* findInfoLabelByKey(const char* key);
    void clearInfoLabels();

    bool loadAll();
    bool saveAll();
    bool resetAll();
    bool syncFactoryIdentityFromStorage(bool saveMirrorIfChanged = true);
    bool syncSecurityKeyFromFactoryIdentity(bool saveIfChanged = false);
    bool hasValidFactoryIdentity() const;

    // Sync wakeup config
    bool hasSyncWakeup();
    bool isSyncWakeupEnabled();
    temeshtastic_SyncWakeupConfig& getSyncWakeup();
    bool setSyncWakeup(const temeshtastic_SyncWakeupConfig& config);
    const temeshtastic_SyncWakeupConfig_WakeupWindow& getWakeupWindow();
    
    // Network config methods.
    bool hasNetworkConfig();
    bool hasCompanyConfig() { return hasNetworkConfig(); }
    bool isEnrolled();
    bool isPrivatized();
    bool isReadyForPrivateConfig();
    temeshtastic_NetWorkConfig& getNetworkConfigData();
    
    void setNetworkPublicKey(const uint8_t* pubkey);
    void setNetworkSeedNoSave(const uint8_t* seed, pb_size_t seedSize);
    void clearNetworkSeedNoSave();
    bool hasNetworkSeed() const;
    void setIsEnrolled(bool enrolled);
    void setLastChangeTimestamp(uint64_t timestamp);
    void setGatewayPublicKey(const uint8_t* pubkey);
    void setGatewayPublicKeyNoSave(const uint8_t* pubkey);
    uint32_t getPrimaryTrustedGateway() const;

    bool executeResetConfig(uint32_t reset_type);

    bool executeChangeNetworkKey(const uint8_t* new_pubkey, const uint8_t* new_seed, pb_size_t newSeedSize, uint64_t timestamp);

    // Trusted time source methods
    bool isTrustedTimeSource(uint32_t nodeId) const;
    bool addTrustedTimeSource(uint32_t nodeId);
    bool removeTrustedTimeSource(uint32_t nodeId);
    void clearTrustedTimeSources();
    bool addTrustedTimeSourceNoSave(uint32_t nodeId);
    bool removeTrustedTimeSourceNoSave(uint32_t nodeId);
    void clearTrustedTimeSourcesNoSave();

private:
    PrivateConfigManager();
    PrivateConfigManager(const PrivateConfigManager&) = delete;
    PrivateConfigManager& operator=(const PrivateConfigManager&) = delete;

    void initDefaultConfig();
    void initDefaultLabels();
    bool validateConfig();
    void applyDefaultWakeupWindowIfMissing();
    bool applyFactoryIdentityMirror(const temeshtastic_DeviceFactoryIdentity& identity, bool saveMirrorIfChanged);

    temeshtastic_PrivateConfig _config;
    temeshtastic_DeviceLabels _labels;

    static constexpr const char* configFile = "/prefs/private.proto";
    static constexpr const char* labelsFile = "/prefs/labels.proto";
};

extern PrivateConfigManager& privateConfig;
