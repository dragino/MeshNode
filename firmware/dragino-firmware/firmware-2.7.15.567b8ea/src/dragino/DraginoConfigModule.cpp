#include "DraginoConfigModule.h"
#include "DraginoBootControlPage.h"
#include "PrivateConfig.h"
#include "DraginoModule.h"
#include "DraginoDefaultConfig.h"
#include "DraginoPeriodicNodeInfo.h"
#include "DraginoRolePolicy.h"
#include "configuration.h"
#include "main.h"
#include "MeshService.h"
#include "mesh/Channels.h"
#include "mesh/CryptoEngine.h"
#include "mesh/MeshTypes.h"
#include "mesh/NodeDB.h"
#include <string.h>

#if defined(DRAGINO_REMOTENODE)
#include "FactoryIdentityManager.h"
#if !MESHTASTIC_EXCLUDE_NODEINFO
#include "modules/NodeInfoModule.h"
#endif
#if defined(MESHTASTIC_EXCLUDE_GPS) && !defined(MESHTASTIC_EXCLUDE_TIMESYNC)
#include "modules/TimeSyncModule.h"
#endif
#endif

#if defined(DRAGINO_REMOTENODE) || defined(DRAGINO_GATEWAY)
#include <SHA256.h>
#endif

namespace dragino {

DraginoConfigModule *draginoConfigModule = nullptr;

namespace {

bool isValidPrivateChannelName(const char *name)
{
    return name != nullptr && name[0] != '\0';
}

#if defined(DRAGINO_REMOTENODE) && !MESHTASTIC_EXCLUDE_NODEINFO
void sendControlledNodeInfo(uint32_t dest, const char *reason)
{
    if (!nodeInfoModule) {
        LOG_WARN("Dragino NodeInfo: module unavailable, skip %s", reason);
        return;
    }

    if (dest == 0) {
        dest = NODENUM_BROADCAST;
    }

    LOG_INFO("Dragino NodeInfo: send after %s to 0x%08x", reason, dest);
    nodeInfoModule->sendOurNodeInfo(dest, false, 0, true);
}
#else
void sendControlledNodeInfo(uint32_t, const char *) {}
#endif

void scheduleResetConfigReboot(const char *reason)
{
    rebootAtMsec = millis() + DRAGINO_RESET_CONFIG_REBOOT_DELAY_MS;
    runASAP = true;
    LOG_INFO("DraginoConfig: reboot scheduled after reset config in %u ms, reason=%s",
             DRAGINO_RESET_CONFIG_REBOOT_DELAY_MS,
             reason ? reason : "unknown");
}

#if defined(DRAGINO_REMOTENODE)
void syncOwnerNameFromFactoryIdentity()
{
    auto &identity = privateConfig.getConfig().factory_identity;
    if (!privateConfig.getConfig().has_factory_identity || identity.sn[0] == '\0') {
        return;
    }
    if (strcmp(owner.long_name, identity.sn) == 0) {
        return;
    }

    strncpy(owner.long_name, identity.sn, sizeof(owner.long_name) - 1);
    owner.long_name[sizeof(owner.long_name) - 1] = '\0';
    snprintf(owner.id, sizeof(owner.id), "!%08x", nodeDB->getNodeNum());
    service->reloadOwner(false);
    nodeDB->saveToDisk(SEGMENT_DEVICESTATE | SEGMENT_NODEDATABASE);
    LOG_INFO("Dragino NodeInfo: owner name synced to %s", owner.long_name);
}
#else
void syncOwnerNameFromFactoryIdentity() {}
#endif

#if defined(DRAGINO_REMOTENODE)
void applyPostJoinWakeupDefault()
{
    privateConfig.getConfig().has_sync_wakeup = true;
    auto &sync = privateConfig.getSyncWakeup();
    sync.enabled = true;
    sync.strategy = temeshtastic_SyncWakeupConfig_WakeupStrategy_STRATEGY_FIXED;
    sync.has_fixed_wakeup = true;
    sync.fixed_wakeup.interval_min = DRAGINO_POST_JOIN_WAKEUP_INTERVAL_MIN;
    sync.fixed_wakeup.align_minute = DRAGINO_DEFAULT_WAKEUP_ALIGN_MINUTE;
    sync.fixed_wakeup.offset_sec = DRAGINO_DEFAULT_WAKEUP_OFFSET_SEC;
    sync.has_scheduled_wakeup = false;
    privateConfig.getWakeupWindow();
}

void setTrustedTimeFromJoinNetwork(uint64_t timestamp)
{
#if defined(MESHTASTIC_EXCLUDE_GPS) && !defined(MESHTASTIC_EXCLUDE_TIMESYNC)
    if (timestamp > 0xffffffffULL) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 timestamp too large for RTC=%llu", timestamp);
        return;
    }
    if (!timeSyncModule) {
        LOG_WARN("DraginoConfig: TimeSyncModule unavailable, skip JoinNetWorkV2 time sync");
        return;
    }
    if (!timeSyncModule->setTrustedTime((uint32_t)timestamp)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 trusted time sync rejected");
    }
#else
    (void)timestamp;
    LOG_WARN("DraginoConfig: TimeSyncModule disabled, skip JoinNetWorkV2 time sync");
#endif
}
#endif

bool isValidKeySize(pb_size_t size)
{
    return size == 32;
}

bool isValidAuthCodeSize(pb_size_t size)
{
    return size == 32;
}

bool isValidNetworkSeedSize(pb_size_t size)
{
    return size >= DRAGINO_JOIN_V2_NETWORK_SEED_MIN_SIZE && size <= DRAGINO_JOIN_V2_NETWORK_SEED_MAX_SIZE;
}

#if defined(DRAGINO_REMOTENODE)
bool elapsedSince(uint32_t startMs, uint32_t nowMs, uint32_t intervalMs)
{
    return (uint32_t)(nowMs - startMs) >= intervalMs;
}

bool isJoinIdentityReady(const temeshtastic_DeviceFactoryIdentity &identity)
{
    return identity.status == temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID ||
           identity.status == temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED;
}

temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus normalizedFactoryIdentityStatus(
    temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus status)
{
    if (status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID &&
        status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED) {
        return temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID;
    }
    return status;
}

bool sameFactoryIdentityCore(const temeshtastic_DeviceFactoryIdentity &lhs,
                             const temeshtastic_DeviceFactoryIdentity &rhs)
{
    if (lhs.factory_version != rhs.factory_version || lhs.dev_eui_hi != rhs.dev_eui_hi ||
        lhs.dev_eui_lo != rhs.dev_eui_lo || lhs.manufacturing_timestamp != rhs.manufacturing_timestamp) {
        return false;
    }

    if (normalizedFactoryIdentityStatus(lhs.status) != normalizedFactoryIdentityStatus(rhs.status)) {
        return false;
    }

    if (strncmp(lhs.sn, rhs.sn, sizeof(lhs.sn)) != 0) {
        return false;
    }

    if (lhs.device_private_key.size != rhs.device_private_key.size ||
        memcmp(lhs.device_private_key.bytes, rhs.device_private_key.bytes, lhs.device_private_key.size) != 0) {
        return false;
    }

    if (lhs.legacy_app_key.size != rhs.legacy_app_key.size ||
        memcmp(lhs.legacy_app_key.bytes, rhs.legacy_app_key.bytes, lhs.legacy_app_key.size) != 0) {
        return false;
    }

    return true;
}

bool buildFactoryIdentityForWrite(const temeshtastic_DeviceFactoryIdentity &requested,
                                  temeshtastic_DeviceFactoryIdentity &identity,
                                  temeshtastic_PrivateConfigPacket_OperationResult_Status &errorStatus,
                                  const char *&errorMessage)
{
    temeshtastic_DeviceFactoryIdentity currentIdentity = temeshtastic_DeviceFactoryIdentity_init_zero;
    bool hasBaseIdentity = privateConfig.getConfig().has_factory_identity &&
                           factoryIdentity.validate(privateConfig.getConfig().factory_identity);
    if (hasBaseIdentity) {
        currentIdentity = privateConfig.getConfig().factory_identity;
    } else {
        hasBaseIdentity = factoryIdentity.load(currentIdentity);
    }

    if (hasBaseIdentity) {
        if (requested.sn[0] != '\0' &&
            currentIdentity.sn[0] != '\0' &&
            strncmp(requested.sn, currentIdentity.sn, sizeof(currentIdentity.sn)) != 0) {
            errorStatus = temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED;
            errorMessage = "SN is immutable";
            return false;
        }

        identity = currentIdentity;
        if (requested.sn[0] != '\0' && identity.sn[0] == '\0') {
            strncpy(identity.sn, requested.sn, sizeof(identity.sn) - 1);
            identity.sn[sizeof(identity.sn) - 1] = '\0';
        }
        if (requested.dev_eui_hi != 0 || requested.dev_eui_lo != 0) {
            identity.dev_eui_hi = requested.dev_eui_hi;
            identity.dev_eui_lo = requested.dev_eui_lo;
        }
        if (requested.device_private_key.size != 0) {
            identity.device_private_key = requested.device_private_key;
        }
        if (requested.legacy_app_key.size != 0) {
            identity.legacy_app_key = requested.legacy_app_key;
        }
    } else {
        identity = requested;
    }

    if (identity.dev_eui_hi == 0 && identity.dev_eui_lo == 0) {
        errorStatus = temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT;
        errorMessage = "factory identity missing DevEUI";
        return false;
    }
    if (identity.device_private_key.size != 32) {
        errorStatus = temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_SIZE;
        errorMessage = "factory identity invalid key size";
        return false;
    }
    if (!factoryIdentity.normalize(identity)) {
        errorStatus = temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT;
        errorMessage = "factory identity invalid";
        return false;
    }

    return true;
}
#endif

bool isLoRaTransport(const meshtastic_MeshPacket &mp)
{
    return mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA_ALT1 ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA_ALT2 ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA_ALT3;
}

bool isRemoteTransport(const meshtastic_MeshPacket &mp)
{
    return isLoRaTransport(mp) ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_MQTT ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_MULTICAST_UDP;
}

bool isUpperComputerRequest(const meshtastic_MeshPacket &mp)
{
    return mp.from == 0 && !isRemoteTransport(mp);
}

bool isPreEnrollmentRemoteDownlinkAllowed(const temeshtastic_PrivateConfigPacket_DownlinkPacket &downlink)
{
    if (downlink.which_payload != temeshtastic_PrivateConfigPacket_DownlinkPacket_set_network_config_tag) {
        return false;
    }

    switch (downlink.payload.set_network_config.which_payload) {
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_join_network_v2_tag:
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_get_join_lock_advertise_tag:
        return true;

    default:
        return false;
    }
}

bool isTrustedGatewayBroadcastWrite(const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig &req)
{
    return req.which_payload == temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig_add_trusted_gateway_tag ||
           req.which_payload == temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig_remove_trusted_gateway_tag;
}

bool isAllowedNetworkConfigBroadcast(const temeshtastic_PrivateConfigPacket_SetNetWorkConfig &req)
{
    switch (req.which_payload) {
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_gateway_announce_tag:
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_change_network_key_tag:
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_reset_network_config_tag:
        return true;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_trusted_gateway_config_tag:
        return isTrustedGatewayBroadcastWrite(req.payload.trusted_gateway_config);

    default:
        return false;
    }
}

bool isAllowedSyncWakeupBroadcast(const temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig &req)
{
    return req.which_payload == temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig_config_tag ||
           req.which_payload == temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig_keep_awake_tag;
}

bool isAllowedPrivateConfigBroadcast(const temeshtastic_PrivateConfigPacket_DownlinkPacket &downlink)
{
    switch (downlink.which_payload) {
    case temeshtastic_PrivateConfigPacket_DownlinkPacket_set_network_config_tag:
        return isAllowedNetworkConfigBroadcast(downlink.payload.set_network_config);

    case temeshtastic_PrivateConfigPacket_DownlinkPacket_set_sync_wakeup_config_tag:
        return isAllowedSyncWakeupBroadcast(downlink.payload.set_sync_wakeup_config);

    default:
        return false;
    }
}

bool hasInfoLabelId(uint32_t labelId)
{
    return labelId == 0 || privateConfig.findInfoLabel(labelId) != nullptr;
}

bool isPrivateConfigBroadcast(const meshtastic_MeshPacket &mp)
{
    return !isUpperComputerRequest(mp) && mp.to == NODENUM_BROADCAST &&
           mp.channel == DRAGINO_CHANNEL_PRIVATE_CONFIG;
}

bool isPkiAdminPacket(const meshtastic_MeshPacket &mp)
{
    if (!mp.pki_encrypted || mp.public_key.size != 32) {
        return false;
    }

    pb_size_t count = config.security.admin_key_count;
    if (count > 3) {
        count = 3;
    }

    for (pb_size_t i = 0; i < count; i++) {
        if (config.security.admin_key[i].size == 32 &&
            memcmp(mp.public_key.bytes, config.security.admin_key[i].bytes, 32) == 0) {
            return true;
        }
    }

    return false;
}

bool isPkiFromKey(const meshtastic_MeshPacket &mp, const uint8_t *publicKey)
{
    return mp.pki_encrypted && mp.public_key.size == 32 && publicKey != nullptr &&
           memcmp(mp.public_key.bytes, publicKey, 32) == 0;
}

bool isAuthorizedConfigWriter(const meshtastic_MeshPacket &mp)
{
    return isUpperComputerRequest(mp) || isPkiAdminPacket(mp);
}

bool isPrivateConfigWriter(const meshtastic_MeshPacket &mp)
{
#if defined(DRAGINO_REMOTENODE)
    return isUpperComputerRequest(mp) || privateConfig.isTrustedTimeSource(mp.from);
#else
    return isUpperComputerRequest(mp);
#endif
}

bool isTrustedGatewayCommand(const meshtastic_MeshPacket &mp)
{
#if defined(DRAGINO_REMOTENODE)
    return privateConfig.isTrustedTimeSource(mp.from);
#else
    (void)mp;
    return false;
#endif
}

bool canKeepAwakeRequest(const meshtastic_MeshPacket &mp, bool broadcastWrite)
{
#if defined(DRAGINO_REMOTENODE)
    return broadcastWrite || isAuthorizedConfigWriter(mp) || privateConfig.isTrustedTimeSource(mp.from);
#else
    (void)mp;
    return broadcastWrite;
#endif
}

void touchConfigKeepAwakeLease()
{
    if (draginoModule) {
        draginoModule->touchConfigKeepAwake();
    }
}

BootUpgradeReason mapBootloaderReason(temeshtastic_PrivateConfigPacket_EnterBootloader_BootloaderReason reason)
{
    switch (reason) {
    case temeshtastic_PrivateConfigPacket_EnterBootloader_BootloaderReason_BOOTLOADER_REASON_SERIAL:
        return BootUpgradeReason::SerialUart;

    case temeshtastic_PrivateConfigPacket_EnterBootloader_BootloaderReason_BOOTLOADER_REASON_BLUETOOTH:
        return BootUpgradeReason::Bluetooth;

    case temeshtastic_PrivateConfigPacket_EnterBootloader_BootloaderReason_BOOTLOADER_REASON_UPPER_COMPUTER:
        return BootUpgradeReason::UpperComputer;

    case temeshtastic_PrivateConfigPacket_EnterBootloader_BootloaderReason_BOOTLOADER_REASON_TEST:
        return BootUpgradeReason::Test;

    default:
        return BootUpgradeReason::Unknown;
    }
}

uint32_t normalizeBootloaderRebootDelay(uint32_t requestedDelayMs, bool fromUpperComputer)
{
    constexpr uint32_t kMinDelayMs = 1000;
    constexpr uint32_t kMaxDelayMs = 60000;

    uint32_t delayMs = requestedDelayMs;
    if (delayMs == 0) {
        delayMs = fromUpperComputer ? 1500 : 5000;
    }
    if (delayMs < kMinDelayMs) {
        delayMs = kMinDelayMs;
    }
    if (delayMs > kMaxDelayMs) {
        delayMs = kMaxDelayMs;
    }
    return delayMs;
}

void applyChannelConfig(uint8_t index, const char *name, const uint8_t *psk, pb_size_t pskSize)
{
    meshtastic_Channel ch = channels.getByIndex(index);
    ch.index = index;
    ch.role = (index == DRAGINO_CHANNEL_PRIMARY) ? meshtastic_Channel_Role_PRIMARY : meshtastic_Channel_Role_SECONDARY;
    ch.has_settings = true;
    strncpy(ch.settings.name, name ? name : "", sizeof(ch.settings.name) - 1);
    ch.settings.name[sizeof(ch.settings.name) - 1] = '\0';
    ch.settings.psk.size = pskSize > sizeof(ch.settings.psk.bytes) ? sizeof(ch.settings.psk.bytes) : pskSize;
    memcpy(ch.settings.psk.bytes, psk, ch.settings.psk.size);
    channels.setChannel(ch);
}

#if defined(DRAGINO_REMOTENODE) || defined(DRAGINO_GATEWAY)
void deriveJoinV2ChannelPsk(const char *label, const uint8_t *seed, pb_size_t seedSize, uint8_t output[32])
{
    SHA256 hash;
    hash.reset();
    hash.update(label, strlen(label));
    hash.update(seed, seedSize);
    hash.finalize(output, 32);
}
#endif

#if defined(DRAGINO_REMOTENODE)
void putLe32(uint8_t output[4], uint32_t value)
{
    output[0] = (uint8_t)(value & 0xff);
    output[1] = (uint8_t)((value >> 8) & 0xff);
    output[2] = (uint8_t)((value >> 16) & 0xff);
    output[3] = (uint8_t)((value >> 24) & 0xff);
}

void putLe64(uint8_t output[8], uint64_t value)
{
    for (size_t i = 0; i < 8; i++) {
        output[i] = (uint8_t)((value >> (8 * i)) & 0xff);
    }
}

void hmacSha256(const uint8_t *key, size_t keyLen, const uint8_t *data, size_t dataLen, uint8_t output[32])
{
    uint8_t keyBlock[64] = {};
    uint8_t innerHash[32] = {};
    uint8_t ipad[64];
    uint8_t opad[64];

    if (keyLen > sizeof(keyBlock)) {
        SHA256 keyHash;
        keyHash.reset();
        keyHash.update(key, keyLen);
        keyHash.finalize(keyBlock, sizeof(innerHash));
    } else if (keyLen > 0) {
        memcpy(keyBlock, key, keyLen);
    }

    for (size_t i = 0; i < sizeof(keyBlock); i++) {
        ipad[i] = keyBlock[i] ^ 0x36;
        opad[i] = keyBlock[i] ^ 0x5c;
    }

    SHA256 inner;
    inner.reset();
    inner.update(ipad, sizeof(ipad));
    inner.update(data, dataLen);
    inner.finalize(innerHash, sizeof(innerHash));

    SHA256 outer;
    outer.reset();
    outer.update(opad, sizeof(opad));
    outer.update(innerHash, sizeof(innerHash));
    outer.finalize(output, 32);
}

bool constantTimeEquals(const uint8_t *lhs, const uint8_t *rhs, size_t len)
{
    uint8_t diff = 0;
    for (size_t i = 0; i < len; i++) {
        diff |= lhs[i] ^ rhs[i];
    }
    return diff == 0;
}

size_t appendJoinV2AuthData(uint8_t *output,
                            size_t outputSize,
                            const temeshtastic_DeviceFactoryIdentity &identity,
                            const uint8_t joinChallenge[16],
                            const meshtastic_MeshPacket &mp,
                            const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2 &req)
{
    size_t offset = 0;

    auto append = [&](const void *data, size_t len) {
        if (offset + len > outputSize) {
            return false;
        }
        memcpy(output + offset, data, len);
        offset += len;
        return true;
    };

    const uint8_t seedSize = req.network_seed.size;
    uint8_t devEuiHiLe[4];
    uint8_t devEuiLoLe[4];
    uint8_t targetNodeLe[4];
    uint8_t gatewayNodeLe[4];
    uint8_t timestampLe[8];

    putLe32(devEuiHiLe, identity.dev_eui_hi);
    putLe32(devEuiLoLe, identity.dev_eui_lo);
    putLe32(targetNodeLe, nodeDB->getNodeNum());
    putLe32(gatewayNodeLe, mp.from);
    putLe64(timestampLe, req.timestamp);

    return append(DRAGINO_JOIN_V2_DOMAIN, strlen(DRAGINO_JOIN_V2_DOMAIN)) &&
                   append(identity.sn, sizeof(identity.sn)) &&
                   append(devEuiHiLe, sizeof(devEuiHiLe)) &&
                   append(devEuiLoLe, sizeof(devEuiLoLe)) &&
                   append(joinChallenge, 16) &&
                   append(targetNodeLe, sizeof(targetNodeLe)) &&
                   append(gatewayNodeLe, sizeof(gatewayNodeLe)) &&
                   append(mp.public_key.bytes, 32) &&
                   append(req.network_public_key.bytes, 32) &&
                   append(&seedSize, sizeof(seedSize)) &&
                   append(req.network_seed.bytes, req.network_seed.size) &&
                   append(timestampLe, sizeof(timestampLe))
               ? offset
               : 0;
}

bool verifyJoinNetworkV2AuthCode(const temeshtastic_DeviceFactoryIdentity &identity,
                                 const uint8_t joinChallenge[16],
                                 const meshtastic_MeshPacket &mp,
                                 const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2 &req)
{
    static constexpr size_t authDataMaxSize = sizeof(DRAGINO_JOIN_V2_DOMAIN) - 1 + 20 + 4 + 4 + 16 + 4 + 4 + 32 + 32 + 1 +
                                              DRAGINO_JOIN_V2_NETWORK_SEED_MAX_SIZE + 8;
    uint8_t authData[authDataMaxSize];
    const size_t authDataSize = appendJoinV2AuthData(authData, sizeof(authData), identity, joinChallenge, mp, req);
    if (authDataSize == 0) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 auth data overflow");
        return false;
    }

    uint8_t expected[32];
    hmacSha256(identity.device_private_key.bytes,
               identity.device_private_key.size,
               authData,
               authDataSize,
               expected);
    return constantTimeEquals(expected, req.auth_code.bytes, sizeof(expected));
}

size_t appendChangeAdminAuthData(uint8_t *output,
                                 size_t outputSize,
                                 const temeshtastic_DeviceFactoryIdentity &identity,
                                 const temeshtastic_NetWorkConfig &networkConfig,
                                 const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin &req)
{
    size_t offset = 0;

    auto append = [&](const void *data, size_t len) {
        if (offset + len > outputSize) {
            return false;
        }
        memcpy(output + offset, data, len);
        offset += len;
        return true;
    };

    uint8_t devEuiHiLe[4];
    uint8_t devEuiLoLe[4];
    uint8_t targetNodeLe[4];
    uint8_t newGatewayNodeLe[4];
    uint8_t timestampLe[8];

    putLe32(devEuiHiLe, identity.dev_eui_hi);
    putLe32(devEuiLoLe, identity.dev_eui_lo);
    putLe32(targetNodeLe, nodeDB->getNodeNum());
    putLe32(newGatewayNodeLe, req.new_gateway_node_id);
    putLe64(timestampLe, req.timestamp);

    return append(DRAGINO_CHANGE_ADMIN_DOMAIN, strlen(DRAGINO_CHANGE_ADMIN_DOMAIN)) &&
                   append(identity.sn, sizeof(identity.sn)) &&
                   append(devEuiHiLe, sizeof(devEuiHiLe)) &&
                   append(devEuiLoLe, sizeof(devEuiLoLe)) &&
                   append(targetNodeLe, sizeof(targetNodeLe)) &&
                   append(networkConfig.network_public_key.bytes, 32) &&
                   append(newGatewayNodeLe, sizeof(newGatewayNodeLe)) &&
                   append(req.new_gateway_public_key.bytes, 32) &&
                   append(timestampLe, sizeof(timestampLe))
               ? offset
               : 0;
}

bool verifyChangeAdminAuthCode(const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin &req)
{
    if (!isValidAuthCodeSize(req.auth_code.size)) {
        return false;
    }

    if (!privateConfig.syncFactoryIdentityFromStorage(false)) {
        return false;
    }

    const auto &identity = privateConfig.getConfig().factory_identity;
    const auto &networkConfig = privateConfig.getNetworkConfigData();
    if (!isJoinIdentityReady(identity) || identity.device_private_key.size != 32 ||
        networkConfig.network_public_key.size != 32) {
        return false;
    }

    static constexpr size_t authDataMaxSize = sizeof(DRAGINO_CHANGE_ADMIN_DOMAIN) - 1 + 20 + 4 + 4 + 4 + 32 + 4 + 32 + 8;
    uint8_t authData[authDataMaxSize];
    const size_t authDataSize = appendChangeAdminAuthData(authData, sizeof(authData), identity, networkConfig, req);
    if (authDataSize == 0) {
        LOG_WARN("DraginoConfig: ChangeAdmin auth data overflow");
        return false;
    }

    uint8_t expected[32];
    hmacSha256(identity.device_private_key.bytes,
               identity.device_private_key.size,
               authData,
               authDataSize,
               expected);
    return constantTimeEquals(expected, req.auth_code.bytes, sizeof(expected));
}

bool verifyGatewayAnnounceAuthCode(const temeshtastic_NetWorkConfig &networkConfig,
                                   const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce &req)
{
    if (!isValidNetworkSeedSize(networkConfig.network_seed.size) || !isValidAuthCodeSize(req.auth_code.size)) {
        return false;
    }

    static constexpr size_t authDataSize = sizeof(DRAGINO_GATEWAY_ANNOUNCE_DOMAIN) - 1 + 32;
    uint8_t authData[authDataSize];
    memcpy(authData, DRAGINO_GATEWAY_ANNOUNCE_DOMAIN, sizeof(DRAGINO_GATEWAY_ANNOUNCE_DOMAIN) - 1);
    memcpy(authData + sizeof(DRAGINO_GATEWAY_ANNOUNCE_DOMAIN) - 1, req.network_public_key.bytes, 32);

    uint8_t expected[32];
    hmacSha256(networkConfig.network_seed.bytes,
               networkConfig.network_seed.size,
               authData,
               sizeof(authData),
               expected);
    return constantTimeEquals(expected, req.auth_code.bytes, sizeof(expected));
}
#endif

} // namespace

DraginoConfigModule::DraginoConfigModule()
    : ProtobufModule("DraginoConfigModule",
                     PRIVATE_DRAGINO_CONFIG_PORTNUM,
                     temeshtastic_PrivateConfigPacket_fields)
{
    draginoConfigModule = this;
    applyAndSaveRemoteNodeEnrollmentRolePolicy("boot");
}

bool DraginoConfigModule::handleReceivedProtobuf(const meshtastic_MeshPacket &mp,
                                             temeshtastic_PrivateConfigPacket *p)
{
    ignoreRequest = false;
    requestFromUpperComputer_ = false;

    if (!p) {
        LOG_ERROR("PrivateConfigPacket decode failed");
        return false;
    }

    uint32_t myNodeNum = nodeDB->getNodeNum();
    bool isToMe = (mp.to == myNodeNum);
    bool isBroadcast = (mp.to == NODENUM_BROADCAST);
    bool isFromUpperComputer = isUpperComputerRequest(mp);
    bool isRemote = isRemoteTransport(mp);

    if (isFromUpperComputer) {
        if (!isToMe && !isBroadcast) {
            LOG_DEBUG("DraginoConfig: phone packet not for me, to=0x%x, my=0x%x", mp.to, myNodeNum);
            return true;
        }
        requestFromUpperComputer_ = true;
    } else {
        if (mp.from == 0 && isRemote) {
            LOG_WARN("DraginoConfig: reject remote from=0 packet");
            ignoreRequest = true;
            return true;
        }
        if (isFromUs(&mp)) {
            return true;
        }
        if (!isToMe && !isBroadcast) {
            LOG_DEBUG("DraginoConfig: mesh packet not for me, to=0x%08x, my=0x%08x", mp.to, myNodeNum);
            return true;
        }
        requestFromUpperComputer_ = false;
    }

    if (p->which_packet_type == temeshtastic_PrivateConfigPacket_uplink_packet_tag) {
        bool forwardToPhone = isToMe;
#if defined(DRAGINO_GATEWAY)
        const auto &uplink = p->packet_type.uplink_packet;
        forwardToPhone = forwardToPhone ||
                         (isBroadcast &&
                          uplink.which_payload == temeshtastic_PrivateConfigPacket_UplinkPacket_join_lock_advertise_tag);
#endif
        if (forwardToPhone) {
            service->sendToPhone(packetPool.allocCopy(mp));
        }
        return true;
    }

    if (p->which_packet_type != temeshtastic_PrivateConfigPacket_downlink_packet_tag) {
        LOG_WARN("DraginoConfig: unknown packet type=%d", p->which_packet_type);
        return true;
    }

#if defined(DRAGINO_REMOTENODE)
    const auto &downlink = p->packet_type.downlink_packet;
    if (!isFromUpperComputer && !privateConfig.isEnrolled() && !isPreEnrollmentRemoteDownlinkAllowed(downlink)) {
        LOG_WARN("DraginoConfig: ignore remote downlink before enrollment payload=%d network_payload=%d",
                 downlink.which_payload,
                 downlink.which_payload == temeshtastic_PrivateConfigPacket_DownlinkPacket_set_network_config_tag
                     ? downlink.payload.set_network_config.which_payload
                     : 0);
        ignoreRequest = true;
        return true;
    }

    if (!isFromUpperComputer && isBroadcast && privateConfig.isEnrolled() && mp.channel != DRAGINO_CHANNEL_PRIVATE_CONFIG) {
        LOG_WARN("DraginoConfig: reject enrolled broadcast downlink on channel %u, expected channel %u",
                 (unsigned)mp.channel, (unsigned)DRAGINO_CHANNEL_PRIVATE_CONFIG);
        ignoreRequest = true;
        return true;
    }

    if (isPrivateConfigBroadcast(mp) && privateConfig.isEnrolled()) {
        ignoreRequest = true;

        if (!isAllowedPrivateConfigBroadcast(downlink)) {
            LOG_WARN("DraginoConfig: ignore unsupported private config broadcast payload=%d network_payload=%d sync_payload=%d",
                     downlink.which_payload,
                     downlink.which_payload == temeshtastic_PrivateConfigPacket_DownlinkPacket_set_network_config_tag
                         ? downlink.payload.set_network_config.which_payload
                         : 0,
                     downlink.which_payload == temeshtastic_PrivateConfigPacket_DownlinkPacket_set_sync_wakeup_config_tag
                         ? downlink.payload.set_sync_wakeup_config.which_payload
                         : 0);
            return true;
        }

        if (!hasInfoLabelId(p->label_id)) {
            LOG_INFO("DraginoConfig: ignore private config broadcast label_id=%u, no local label match",
                     (unsigned)p->label_id);
            return true;
        }
    }
#endif

#if defined(DRAGINO_GATEWAY)
    if (!isFromUpperComputer) {
        LOG_WARN("DraginoConfig: gateway ignores mesh downlink command");
        return true;
    }
#endif

    handleDownlink(mp, p->packet_type.downlink_packet);
    return true;
}

void DraginoConfigModule::handleDownlink(const meshtastic_MeshPacket &mp,
                                    const temeshtastic_PrivateConfigPacket_DownlinkPacket &downlink)
{
    switch (downlink.which_payload) {
    case temeshtastic_PrivateConfigPacket_DownlinkPacket_set_factory_identity_tag:
        handleFactoryIdentity(mp, downlink.payload.set_factory_identity);
        break;

    case temeshtastic_PrivateConfigPacket_DownlinkPacket_set_network_config_tag:
        handleNetworkConfig(mp, downlink.payload.set_network_config);
        break;

    case temeshtastic_PrivateConfigPacket_DownlinkPacket_set_sync_wakeup_config_tag:
        handleSyncWakeupConfig(mp, downlink.payload.set_sync_wakeup_config);
        break;

    case temeshtastic_PrivateConfigPacket_DownlinkPacket_set_info_label_config_tag:
        handleInfoLabelConfig(mp, downlink.payload.set_info_label_config);
        break;

    case temeshtastic_PrivateConfigPacket_DownlinkPacket_enter_bootloader_tag:
        handleEnterBootloader(mp, downlink.payload.enter_bootloader);
        break;

    default:
        LOG_WARN("DraginoConfig: unknown downlink payload=%d", downlink.which_payload);
        break;
    }
}

void DraginoConfigModule::handleFactoryIdentity(const meshtastic_MeshPacket &mp,
                                           const temeshtastic_PrivateConfigPacket_SetDeviceFactoryIdentity &req)
{
    switch (req.which_payload) {
    case temeshtastic_PrivateConfigPacket_SetDeviceFactoryIdentity_get_factory_identity_tag:
#if defined(DRAGINO_REMOTENODE)
        if (!requestFromUpperComputer_) {
            LOG_WARN("DraginoConfig: reject remote factory identity read");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_GET_FACTORY_IDENTITY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED);
            return;
        }
        sendFactoryIdentityUplink(requestFromUpperComputer_);
#else
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
#endif
        break;

    case temeshtastic_PrivateConfigPacket_SetDeviceFactoryIdentity_factory_identity_tag: {
#if defined(DRAGINO_REMOTENODE)
        if (!requestFromUpperComputer_) {
            LOG_WARN("DraginoConfig: reject factory identity write from mesh");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED);
            return;
        }

        temeshtastic_DeviceFactoryIdentity requestedIdentity = req.payload.factory_identity;

        temeshtastic_DeviceFactoryIdentity identityToWrite = temeshtastic_DeviceFactoryIdentity_init_zero;
        temeshtastic_PrivateConfigPacket_OperationResult_Status errorStatus =
            temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNKNOWN;
        const char *errorMessage = nullptr;
        if (!buildFactoryIdentityForWrite(requestedIdentity, identityToWrite, errorStatus, errorMessage)) {
            LOG_WARN("DraginoConfig: %s", errorMessage ? errorMessage : "factory identity invalid");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                               errorStatus,
                               0,
                               requestedIdentity.manufacturing_timestamp,
                               errorMessage);
            return;
        }

        temeshtastic_DeviceFactoryIdentity currentIdentity = temeshtastic_DeviceFactoryIdentity_init_zero;
        bool hasCurrentIdentity = privateConfig.getConfig().has_factory_identity &&
                                  factoryIdentity.validate(privateConfig.getConfig().factory_identity);
        if (hasCurrentIdentity) {
            currentIdentity = privateConfig.getConfig().factory_identity;
        } else {
            hasCurrentIdentity = factoryIdentity.load(currentIdentity);
        }

        if (hasCurrentIdentity && sameFactoryIdentityCore(currentIdentity, identityToWrite)) {
            LOG_INFO("DraginoConfig: factory identity unchanged");
            if (!privateConfig.syncFactoryIdentityFromStorage(true)) {
                LOG_WARN("DraginoConfig: factory identity mirror sync failed");
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED);
                return;
            }
            syncOwnerNameFromFactoryIdentity();
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NO_CHANGE,
                               0,
                               identityToWrite.manufacturing_timestamp,
                               "factory identity unchanged");
            return;
        }
        privateConfig.getConfig().has_factory_identity = true;
        privateConfig.getConfig().factory_identity = identityToWrite;
        if (privateConfig.saveConfig()) {
            privateConfig.syncSecurityKeyFromFactoryIdentity(true);
            syncOwnerNameFromFactoryIdentity();
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                               0,
                               identityToWrite.manufacturing_timestamp,
                               "factory identity mirror updated");
        } else {
            LOG_WARN("DraginoConfig: factory identity mirror save failed");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED);
        }
#else
        LOG_WARN("DraginoConfig: factory identity write unsupported in this firmware");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SET_FACTORY_IDENTITY,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
#endif
        break;
    }

    default:
        LOG_WARN("DraginoConfig: unknown factory identity payload=%d", req.which_payload);
        break;
    }
}

void DraginoConfigModule::handleNetworkConfig(const meshtastic_MeshPacket &mp,
                                         const temeshtastic_PrivateConfigPacket_SetNetWorkConfig &req)
{
    switch (req.which_payload) {
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_get_network_config_tag:
        sendNetworkConfigUplink(mp);
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_get_join_lock_advertise_tag:
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
        sendJoinLockAdvertiseUplink(mp);
#else
        LOG_WARN("DraginoConfig: get JoinLockAdvertise is remote-node only");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED,
                           0,
                           0,
                           "get join lock unsupported");
#endif
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_channel12_config_tag:
        handleChannel12Config(mp, req.payload.channel12_config);
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_join_network_v2_tag:
#if defined(DRAGINO_REMOTENODE) || defined(DRAGINO_GATEWAY)
        handleJoinNetworkV2(mp, req.payload.join_network_v2);
#else
        LOG_WARN("DraginoConfig: JoinNetWorkV2 is remote-node only");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
#endif
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_change_admin_tag:
        handleChangeAdmin(mp, req.payload.change_admin);
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_reset_network_config_tag:
        handleResetNetworkConfig(mp, req.payload.reset_network_config);
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_change_network_key_tag:
        handleChangeNetworkKey(mp, req.payload.change_network_key);
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_trusted_gateway_config_tag:
        handleTrustedGatewayConfig(mp, req.payload.trusted_gateway_config);
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_gateway_announce_tag:
        handleGatewayAnnounce(mp, req.payload.gateway_announce);
        break;

    default:
        LOG_WARN("DraginoConfig: unknown network config payload=%d", req.which_payload);
        break;
    }
}

void DraginoConfigModule::handleChannel12Config(const meshtastic_MeshPacket &mp,
                                           const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config &req)
{
    const bool broadcastWrite = isPrivateConfigBroadcast(mp);
#if !defined(DRAGINO_GATEWAY)
    if (!privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: reject channel config before network access");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANNEL12_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE);
        }
        return;
    }
#endif
    if (!broadcastWrite && privateConfig.isEnrolled() && !isPrivateConfigWriter(mp)) {
        LOG_WARN("DraginoConfig: reject unauthorized channel config");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANNEL12_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED);
        return;
    }
    if (!isValidPrivateChannelName(req.channel1_name) || !isValidPrivateChannelName(req.channel2_name)) {
        LOG_WARN("DraginoConfig: channel name missing");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANNEL12_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
        }
        return;
    }
    if (req.psk1.size < 16 || req.psk2.size < 16) {
        LOG_WARN("DraginoConfig: channel PSK too short");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANNEL12_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_SIZE);
        }
        return;
    }
    if (pendingResetNetworkConfig_) {
        LOG_WARN("DraginoConfig: reject channel config, reset pending");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANNEL12_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE);
        }
        return;
    }

    uint32_t gatewayNodeId = privateConfig.getPrimaryTrustedGateway();
    uint64_t opTimestamp = privateConfig.getNetworkConfigData().last_change_timestamp;
    pendingChangeNetworkKey_ = false;
    pendingChangeNetworkKeyApplyAtMs_ = 0;
    pendingChangeNetworkKeyTimestamp_ = 0;
    pendingNetworkSeedSize_ = 0;
    memset(pendingNetworkPublicKey_, 0, sizeof(pendingNetworkPublicKey_));
    memset(pendingNetworkSeed_, 0, sizeof(pendingNetworkSeed_));

    if (broadcastWrite) {
        if (!applyChannel12Config(req)) {
            LOG_WARN("DraginoConfig: channel12 broadcast apply failed");
            return;
        }
        LOG_INFO("DraginoConfig: channel12 broadcast applied");
        return;
    }

    pendingChannel12Config_ = true;
    pendingChannel12ApplyAtMs_ = millis() + DRAGINO_CHANNEL12_APPLY_DELAY_MS;
    pendingChannel12ConfigData_ = req;
    LOG_INFO("DraginoConfig: channel12 config scheduled in %u ms", DRAGINO_CHANNEL12_APPLY_DELAY_MS);
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANNEL12_CONFIG,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_PENDING_CHANNEL12,
                       gatewayNodeId,
                       opTimestamp,
                       "channel12 scheduled");
}

bool DraginoConfigModule::applyChannel12Config(
    const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config &req)
{
    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_CONFIG, req.channel1_name, req.psk1.bytes, req.psk1.size);
    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_FUNCTION, req.channel2_name, req.psk2.bytes, req.psk2.size);
    channels.onConfigChanged();

    if (!nodeDB->saveToDisk(SEGMENT_CHANNELS)) {
        LOG_WARN("DraginoConfig: failed to save channel config");
        return false;
    }

    LOG_INFO("DraginoConfig: channel 1/2 config applied");
    touchConfigKeepAwakeLease();
    return true;
}

void DraginoConfigModule::processPendingPrivateConfigActions()
{
    processPendingChannel12Config();
    processPendingResetNetworkConfig();
    processPendingChangeNetworkKey();
}

void DraginoConfigModule::processPendingChannel12Config()
{
    if (!pendingChannel12Config_) {
        return;
    }

    const uint32_t now = millis();
    if ((int32_t)(now - pendingChannel12ApplyAtMs_) < 0) {
        return;
    }

    const auto pending = pendingChannel12ConfigData_;
    pendingChannel12Config_ = false;
    pendingChannel12ApplyAtMs_ = 0;
    pendingChannel12ConfigData_ = temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config_init_zero;

    if (!applyChannel12Config(pending)) {
        LOG_WARN("DraginoConfig: delayed channel12 config apply failed");
        return;
    }
    LOG_INFO("DraginoConfig: delayed channel12 config applied");
}

void DraginoConfigModule::handleJoinNetworkV2(
    const meshtastic_MeshPacket &mp,
    const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2 &req)
{
#if defined(DRAGINO_GATEWAY) && !defined(DRAGINO_REMOTENODE)
    if (!requestFromUpperComputer_) {
        LOG_WARN("DraginoConfig: gateway rejects mesh JoinNetWorkV2 command");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED,
                           0,
                           req.timestamp);
        return;
    }
    if (!isValidNetworkSeedSize(req.network_seed.size)) {
        LOG_WARN("DraginoConfig: gateway JoinNetWorkV2 invalid seed size=%u", req.network_seed.size);
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_SIZE,
                           0,
                           req.timestamp);
        return;
    }

    uint8_t psk1[32];
    uint8_t psk2[32];
    deriveJoinV2ChannelPsk(DRAGINO_JOIN_V2_CHANNEL1_LABEL, req.network_seed.bytes, req.network_seed.size, psk1);
    deriveJoinV2ChannelPsk(DRAGINO_JOIN_V2_CHANNEL2_LABEL, req.network_seed.bytes, req.network_seed.size, psk2);

    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_CONFIG, DRAGINO_DEFAULT_PRIVATE_CONFIG_CHANNEL_NAME, psk1, sizeof(psk1));
    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_FUNCTION, DRAGINO_DEFAULT_PRIVATE_FUNCTION_CHANNEL_NAME, psk2, sizeof(psk2));
    channels.onConfigChanged();

    if (!nodeDB->saveToDisk(SEGMENT_CHANNELS)) {
        LOG_WARN("DraginoConfig: gateway JoinNetWorkV2 failed to save channels");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED,
                           0,
                           req.timestamp);
        return;
    }

    LOG_INFO("DraginoConfig: gateway channel PSK derived from network seed");
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                       0,
                       req.timestamp,
                       "gateway seed channels saved");
#elif defined(DRAGINO_REMOTENODE)
    if (privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: already enrolled, reject JoinNetWorkV2");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_ALREADY_ENROLLED,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (!isLoRaTransport(mp)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 requires mesh PKI source");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (mp.to != nodeDB->getNodeNum() || isBroadcast(mp.to)) {
        LOG_WARN("DraginoConfig: reject JoinNetWorkV2 not addressed to this node");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (mp.from == 0 || isBroadcast(mp.from)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 invalid gateway node id");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (!mp.pki_encrypted || mp.public_key.size != 32) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 requires PKI packet with gateway public key");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (!isValidKeySize(req.network_public_key.size) ||
        !isValidNetworkSeedSize(req.network_seed.size) ||
        !isValidAuthCodeSize(req.auth_code.size)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 invalid sizes network=%u seed=%u auth=%u",
                 req.network_public_key.size, req.network_seed.size, req.auth_code.size);
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_SIZE,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (req.timestamp == 0) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 missing timestamp");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (!privateConfig.syncFactoryIdentityFromStorage(false)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 factory identity unavailable");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE,
                           mp.from,
                           req.timestamp);
        return;
    }

    const auto &identity = privateConfig.getConfig().factory_identity;
    if (!isJoinIdentityReady(identity) || identity.device_private_key.size != 32) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 factory identity incomplete");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE,
                           mp.from,
                           req.timestamp);
        return;
    }

    ensureJoinChallenge();
    if (!verifyJoinNetworkV2AuthCode(identity, joinChallenge_, mp, req)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 auth code rejected");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_BAD_AUTH_CODE,
                           mp.from,
                           req.timestamp);
        return;
    }

    uint8_t psk1[32];
    uint8_t psk2[32];
    deriveJoinV2ChannelPsk(DRAGINO_JOIN_V2_CHANNEL1_LABEL, req.network_seed.bytes, req.network_seed.size, psk1);
    deriveJoinV2ChannelPsk(DRAGINO_JOIN_V2_CHANNEL2_LABEL, req.network_seed.bytes, req.network_seed.size, psk2);

    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_CONFIG, DRAGINO_DEFAULT_PRIVATE_CONFIG_CHANNEL_NAME, psk1, sizeof(psk1));
    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_FUNCTION, DRAGINO_DEFAULT_PRIVATE_FUNCTION_CHANNEL_NAME, psk2, sizeof(psk2));
    channels.onConfigChanged();

    privateConfig.setNetworkPublicKey(req.network_public_key.bytes);
    privateConfig.setNetworkSeedNoSave(req.network_seed.bytes, req.network_seed.size);
    privateConfig.setGatewayPublicKeyNoSave(mp.public_key.bytes);
    privateConfig.setLastChangeTimestamp(req.timestamp);
    privateConfig.getNetworkConfigData().is_single_gateway = true;
    privateConfig.clearTrustedTimeSourcesNoSave();
    privateConfig.addTrustedTimeSourceNoSave(mp.from);
    applyPostJoinWakeupDefault();

    if (!nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_CHANNELS)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 failed to save config/channels");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED,
                           mp.from,
                           req.timestamp);
        return;
    }
    if (!privateConfig.saveConfig()) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 failed to save private config");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED,
                           mp.from,
                           req.timestamp);
        return;
    }

    const int roleSaveMask = applyRemoteNodeEnrollmentRolePolicy("join-network-v2");
    if (roleSaveMask && !nodeDB->saveToDisk(roleSaveMask)) {
        LOG_WARN("DraginoConfig: JoinNetWorkV2 failed to save role policy");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED,
                           mp.from,
                           req.timestamp);
        return;
    }

    if (!nodeDB->isFavorite(mp.from)) {
        nodeDB->set_favorite(true, mp.from);
    }

    setTrustedTimeFromJoinNetwork(req.timestamp);
    if (draginoModule) {
        draginoModule->applySyncWakeupConfig();
    }

    LOG_INFO("DraginoConfig: JoinNetWorkV2 committed, gateway=0x%08x", mp.from);
    sendControlledNodeInfo(mp.from, "join-network-v2");
    draginoPeriodicNodeInfo.resetSchedule("join-network-v2");
    clearJoinChallenge();
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                       mp.from,
                       req.timestamp,
                       "join-network-v2 committed");
#else
    (void)req;
    LOG_WARN("DraginoConfig: JoinNetWorkV2 unsupported in this firmware");
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
#endif
}

void DraginoConfigModule::handleChangeAdmin(const meshtastic_MeshPacket &mp,
                                       const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin &req)
{
#if !defined(DRAGINO_REMOTENODE)
    (void)req;
    LOG_WARN("DraginoConfig: change admin is remote-node only");
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
    return;
#else
    if (!privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: not enrolled, cannot change admin");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
        return;
    }
    if (req.new_gateway_node_id == 0 || isBroadcast(req.new_gateway_node_id)) {
        LOG_WARN("DraginoConfig: invalid new gateway node id");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }
    if (req.timestamp == 0) {
        LOG_WARN("DraginoConfig: missing change admin timestamp");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }
    if (req.timestamp <= privateConfig.getNetworkConfigData().last_change_timestamp) {
        LOG_WARN("DraginoConfig: stale change admin timestamp");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_STALE_NONCE,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }
    if (!isValidKeySize(req.new_gateway_public_key.size)) {
        LOG_WARN("DraginoConfig: invalid change admin sizes");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_SIZE,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }
    if (!isUpperComputerRequest(mp) && !isPkiFromKey(mp, req.new_gateway_public_key.bytes)) {
        LOG_WARN("DraginoConfig: change admin packet is not from new gateway key");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }
    if (!isValidAuthCodeSize(req.auth_code.size)) {
        LOG_WARN("DraginoConfig: invalid change admin auth size");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_SIZE,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }
    if (!verifyChangeAdminAuthCode(req)) {
        LOG_WARN("DraginoConfig: change admin auth code rejected");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_BAD_AUTH_CODE,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }

    auto &networkConfig = privateConfig.getNetworkConfigData();
    for (pb_size_t i = 0; i < networkConfig.trusted_gateway_sources_count; i++) {
        if (nodeDB->isFavorite(networkConfig.trusted_gateway_sources[i])) {
            nodeDB->set_favorite(false, networkConfig.trusted_gateway_sources[i]);
        }
    }

    privateConfig.setGatewayPublicKeyNoSave(req.new_gateway_public_key.bytes);
    privateConfig.setLastChangeTimestamp(req.timestamp);
    privateConfig.clearTrustedTimeSourcesNoSave();
    if (!privateConfig.addTrustedTimeSourceNoSave(req.new_gateway_node_id)) {
        LOG_WARN("DraginoConfig: change admin add trusted gateway failed");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }

    const bool configSaved = privateConfig.saveConfig();
    const bool dbSaved = nodeDB->saveToDisk(SEGMENT_CONFIG);
    if (!configSaved || !dbSaved) {
        LOG_WARN("DraginoConfig: change admin save failed config=%d db=%d", configSaved, dbSaved);
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED,
                           req.new_gateway_node_id,
                           req.timestamp);
        return;
    }

    if (!nodeDB->isFavorite(req.new_gateway_node_id)) {
        nodeDB->set_favorite(true, req.new_gateway_node_id);
    }

    LOG_INFO("DraginoConfig: admin changed to 0x%08x", req.new_gateway_node_id);
    touchConfigKeepAwakeLease();
    sendControlledNodeInfo(req.new_gateway_node_id, "gateway-change");
    draginoPeriodicNodeInfo.resetSchedule("gateway-change");
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_ADMIN,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                       req.new_gateway_node_id,
                       req.timestamp,
                       "admin changed");
#endif
}

void DraginoConfigModule::handleResetNetworkConfig(
    const meshtastic_MeshPacket &mp,
    const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig &req)
{
#if !defined(DRAGINO_REMOTENODE)
    (void)req;
    LOG_WARN("DraginoConfig: reset network config is remote-node only");
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_RESET_NETWORK_CONFIG,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
    return;
#else
    const bool broadcastWrite = isPrivateConfigBroadcast(mp);
    if (!privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: not enrolled, cannot reset network");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_RESET_NETWORK_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
        }
        return;
    }
    if (!broadcastWrite && !isPrivateConfigWriter(mp)) {
        LOG_WARN("DraginoConfig: reject unauthorized reset network");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_RESET_NETWORK_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED,
                           0,
                           req.timestamp);
        return;
    }
    if (req.reset_type == temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ResetType_RESET_TYPE_NONE) {
        LOG_WARN("DraginoConfig: invalid reset type");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_RESET_NETWORK_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                               0,
                               req.timestamp);
        }
        return;
    }
    if (req.timestamp == 0) {
        LOG_WARN("DraginoConfig: missing reset timestamp");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_RESET_NETWORK_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                               0,
                               req.timestamp);
        }
        return;
    }
    if (req.timestamp <= privateConfig.getNetworkConfigData().last_change_timestamp) {
        LOG_WARN("DraginoConfig: stale reset timestamp");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_RESET_NETWORK_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_STALE_NONCE,
                               0,
                               req.timestamp);
        }
        return;
    }

    pendingChannel12Config_ = false;
    pendingChannel12ApplyAtMs_ = 0;
    pendingChannel12ConfigData_ = temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config_init_zero;
    pendingChangeNetworkKey_ = false;
    pendingChangeNetworkKeyApplyAtMs_ = 0;
    pendingChangeNetworkKeyTimestamp_ = 0;
    pendingNetworkSeedSize_ = 0;
    memset(pendingNetworkPublicKey_, 0, sizeof(pendingNetworkPublicKey_));
    memset(pendingNetworkSeed_, 0, sizeof(pendingNetworkSeed_));

    if (broadcastWrite) {
        if (!privateConfig.executeResetConfig(req.reset_type)) {
            LOG_WARN("DraginoConfig: reset config save failed");
            return;
        }
        LOG_INFO("DraginoConfig: reset network broadcast applied");
        scheduleResetConfigReboot("broadcast");
        return;
    }

    pendingResetNetworkConfig_ = true;
    pendingResetNetworkApplyAtMs_ = millis() + DRAGINO_RESET_NETWORK_APPLY_DELAY_MS;
    pendingResetNetworkType_ = req.reset_type;
    LOG_INFO("DraginoConfig: reset network scheduled in %u ms", DRAGINO_RESET_NETWORK_APPLY_DELAY_MS);
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_RESET_NETWORK_CONFIG,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                       0,
                       req.timestamp,
                       "reset scheduled");
#endif
}

void DraginoConfigModule::processPendingResetNetworkConfig()
{
#if defined(DRAGINO_REMOTENODE)
    if (!pendingResetNetworkConfig_) {
        return;
    }

    const uint32_t now = millis();
    if ((int32_t)(now - pendingResetNetworkApplyAtMs_) < 0) {
        return;
    }

    const uint32_t resetType = pendingResetNetworkType_;
    pendingResetNetworkConfig_ = false;
    pendingResetNetworkApplyAtMs_ = 0;
    pendingResetNetworkType_ = 0;

    if (!privateConfig.executeResetConfig(resetType)) {
        LOG_WARN("DraginoConfig: delayed reset config save failed");
        return;
    }
    LOG_INFO("DraginoConfig: delayed reset network applied");
    scheduleResetConfigReboot("delayed");
#endif
}

void DraginoConfigModule::handleChangeNetworkKey(const meshtastic_MeshPacket &mp,
                                            const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey &req)
{
    const bool broadcastWrite = isPrivateConfigBroadcast(mp);
    if (!privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: not enrolled, cannot change network key");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_NETWORK_KEY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
        }
        return;
    }
    if (!broadcastWrite && !isPrivateConfigWriter(mp)) {
        LOG_WARN("DraginoConfig: reject unauthorized change network key");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_NETWORK_KEY,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED,
                           0,
                           req.timestamp);
        return;
    }
    if (req.timestamp == 0) {
        LOG_WARN("DraginoConfig: missing change network key timestamp");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_NETWORK_KEY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT,
                               0,
                               req.timestamp);
        }
        return;
    }
    if (req.timestamp <= privateConfig.getNetworkConfigData().last_change_timestamp) {
        LOG_WARN("DraginoConfig: stale change network key timestamp");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_NETWORK_KEY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_STALE_NONCE,
                               0,
                               req.timestamp);
        }
        return;
    }
    if (!isValidKeySize(req.new_network_public_key.size) || !isValidNetworkSeedSize(req.new_network_seed.size)) {
        LOG_WARN("DraginoConfig: invalid change network key sizes public=%u seed=%u",
                 req.new_network_public_key.size, req.new_network_seed.size);
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_NETWORK_KEY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_SIZE,
                               0,
                               req.timestamp);
        }
        return;
    }
    if (pendingResetNetworkConfig_) {
        LOG_WARN("DraginoConfig: reject change network key, reset pending");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_NETWORK_KEY,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE,
                               0,
                               req.timestamp);
        }
        return;
    }

    pendingChannel12Config_ = false;
    pendingChannel12ApplyAtMs_ = 0;
    pendingChannel12ConfigData_ = temeshtastic_PrivateConfigPacket_SetNetWorkConfig_Channel12Config_init_zero;

    if (broadcastWrite) {
        if (!applyChangeNetworkKey(req.new_network_public_key.bytes,
                                   req.new_network_seed.bytes,
                                   req.new_network_seed.size,
                                   req.timestamp)) {
            LOG_WARN("DraginoConfig: change network key broadcast apply failed");
            return;
        }
        LOG_INFO("DraginoConfig: change network key broadcast applied");
        return;
    }

    pendingChangeNetworkKey_ = true;
    pendingChangeNetworkKeyApplyAtMs_ = millis() + DRAGINO_CHANGE_NETWORK_KEY_APPLY_DELAY_MS;
    pendingChangeNetworkKeyTimestamp_ = req.timestamp;
    memcpy(pendingNetworkPublicKey_, req.new_network_public_key.bytes, sizeof(pendingNetworkPublicKey_));
    pendingNetworkSeedSize_ = req.new_network_seed.size;
    memcpy(pendingNetworkSeed_, req.new_network_seed.bytes, pendingNetworkSeedSize_);
    if (pendingNetworkSeedSize_ < sizeof(pendingNetworkSeed_)) {
        memset(pendingNetworkSeed_ + pendingNetworkSeedSize_, 0, sizeof(pendingNetworkSeed_) - pendingNetworkSeedSize_);
    }

    LOG_INFO("DraginoConfig: change network key scheduled in %u ms", DRAGINO_CHANGE_NETWORK_KEY_APPLY_DELAY_MS);
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_CHANGE_NETWORK_KEY,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                       0,
                       req.timestamp,
                       "network key change scheduled");
}

bool DraginoConfigModule::applyChangeNetworkKey(const uint8_t *newNetworkPublicKey,
                                                const uint8_t *newNetworkSeed,
                                                pb_size_t newNetworkSeedSize,
                                                uint64_t timestamp)
{
    uint8_t psk1[32];
    uint8_t psk2[32];
    deriveJoinV2ChannelPsk(DRAGINO_JOIN_V2_CHANNEL1_LABEL, newNetworkSeed, newNetworkSeedSize, psk1);
    deriveJoinV2ChannelPsk(DRAGINO_JOIN_V2_CHANNEL2_LABEL, newNetworkSeed, newNetworkSeedSize, psk2);
    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_CONFIG, DRAGINO_DEFAULT_PRIVATE_CONFIG_CHANNEL_NAME, psk1, sizeof(psk1));
    applyChannelConfig(DRAGINO_CHANNEL_PRIVATE_FUNCTION, DRAGINO_DEFAULT_PRIVATE_FUNCTION_CHANNEL_NAME, psk2, sizeof(psk2));
    channels.onConfigChanged();

    if (!nodeDB->saveToDisk(SEGMENT_CHANNELS | SEGMENT_CONFIG)) {
        LOG_WARN("DraginoConfig: change network key channel save failed");
        return false;
    }

    if (!privateConfig.executeChangeNetworkKey(newNetworkPublicKey,
                                               newNetworkSeed,
                                               newNetworkSeedSize,
                                               timestamp)) {
        LOG_WARN("DraginoConfig: change network key save failed");
        return false;
    }

    touchConfigKeepAwakeLease();
    LOG_INFO("DraginoConfig: network key changed");
    return true;
}

void DraginoConfigModule::processPendingChangeNetworkKey()
{
    if (!pendingChangeNetworkKey_) {
        return;
    }

    const uint32_t now = millis();
    if ((int32_t)(now - pendingChangeNetworkKeyApplyAtMs_) < 0) {
        return;
    }

    uint8_t newNetworkPublicKey[32];
    uint8_t newNetworkSeed[32];
    const pb_size_t newNetworkSeedSize = pendingNetworkSeedSize_;
    const uint64_t timestamp = pendingChangeNetworkKeyTimestamp_;
    memcpy(newNetworkPublicKey, pendingNetworkPublicKey_, sizeof(newNetworkPublicKey));
    memcpy(newNetworkSeed, pendingNetworkSeed_, sizeof(newNetworkSeed));

    pendingChangeNetworkKey_ = false;
    pendingChangeNetworkKeyApplyAtMs_ = 0;
    pendingChangeNetworkKeyTimestamp_ = 0;
    pendingNetworkSeedSize_ = 0;
    memset(pendingNetworkPublicKey_, 0, sizeof(pendingNetworkPublicKey_));
    memset(pendingNetworkSeed_, 0, sizeof(pendingNetworkSeed_));

    if (!applyChangeNetworkKey(newNetworkPublicKey, newNetworkSeed, newNetworkSeedSize, timestamp)) {
        LOG_WARN("DraginoConfig: delayed change network key apply failed");
        return;
    }
    LOG_INFO("DraginoConfig: delayed change network key applied");
}

void DraginoConfigModule::handleTrustedGatewayConfig(
    const meshtastic_MeshPacket &mp,
    const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig &req)
{
    const bool broadcastWrite = isPrivateConfigBroadcast(mp);
    if (!privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: not enrolled, cannot change trusted gateway config");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
        }
        return;
    }
    if (broadcastWrite && !isTrustedGatewayBroadcastWrite(req)) {
        LOG_WARN("DraginoConfig: ignore trusted gateway broadcast payload=%d", req.which_payload);
        return;
    }
    if (!broadcastWrite && !isPrivateConfigWriter(mp)) {
        LOG_WARN("DraginoConfig: reject unauthorized trusted gateway config");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED);
        return;
    }

    if (req.which_payload == temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig_get_trusted_gateway_list_tag) {
        if (broadcastWrite) {
            LOG_WARN("DraginoConfig: ignore trusted gateway list broadcast");
            return;
        }
        sendNetworkConfigUplink(mp);
        return;
    }
    if (pendingResetNetworkConfig_) {
        LOG_WARN("DraginoConfig: reject trusted gateway config, reset pending");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE);
        }
        return;
    }

    auto &networkConfig = privateConfig.getNetworkConfigData();
    uint32_t gatewayToAdd = 0;
    uint32_t gatewayToRemove = 0;

    switch (req.which_payload) {
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig_add_trusted_gateway_tag:
        if (req.payload.add_trusted_gateway == 0 || isBroadcast(req.payload.add_trusted_gateway)) {
            LOG_WARN("DraginoConfig: invalid trusted gateway add node id");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
            }
            return;
        }
        gatewayToAdd = req.payload.add_trusted_gateway;
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig_remove_trusted_gateway_tag:
        if (req.payload.remove_trusted_gateway == 0 || isBroadcast(req.payload.remove_trusted_gateway)) {
            LOG_WARN("DraginoConfig: invalid trusted gateway remove node id");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
            }
            return;
        }
        gatewayToRemove = req.payload.remove_trusted_gateway;
        break;

    default:
        LOG_WARN("DraginoConfig: unknown trusted gateway payload=%d", req.which_payload);
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
        }
        return;
    }

    bool changed = networkConfig.is_single_gateway != req.is_single_gateway;
    networkConfig.is_single_gateway = req.is_single_gateway;
    if (gatewayToAdd != 0) {
        changed = privateConfig.addTrustedTimeSourceNoSave(gatewayToAdd) || changed;
    }
    if (gatewayToRemove != 0) {
        changed = privateConfig.removeTrustedTimeSourceNoSave(gatewayToRemove) || changed;
    }

    if (!changed) {
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NO_CHANGE);
        } else {
            LOG_INFO("DraginoConfig: trusted gateway broadcast no change");
        }
        return;
    }

    if (!privateConfig.saveConfig()) {
        LOG_WARN("DraginoConfig: trusted gateway config save failed");
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED);
        }
        return;
    }
    touchConfigKeepAwakeLease();
    if (broadcastWrite) {
        LOG_INFO("DraginoConfig: trusted gateway broadcast applied");
        return;
    }
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                       privateConfig.getPrimaryTrustedGateway(),
                       privateConfig.getNetworkConfigData().last_change_timestamp,
                       "trusted gateway config saved");
}

void DraginoConfigModule::handleGatewayAnnounce(
    const meshtastic_MeshPacket &mp,
    const temeshtastic_PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce &req)
{
#if !defined(DRAGINO_REMOTENODE)
    (void)req;
    LOG_WARN("DraginoConfig: gateway announce is remote-node only");
    if (!isPrivateConfigBroadcast(mp)) {
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
    }
    return;
#else
    const bool broadcastWrite = isPrivateConfigBroadcast(mp);
    if (!broadcastWrite) {
        LOG_WARN("DraginoConfig: gateway announce must be private config broadcast");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_TRUSTED_GATEWAY_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
        return;
    }

    if (!privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: ignore gateway announce before enrollment");
        return;
    }
    if (mp.from == 0 || isBroadcast(mp.from)) {
        LOG_WARN("DraginoConfig: ignore gateway announce invalid source=0x%08x", mp.from);
        return;
    }
    if (!isValidKeySize(req.network_public_key.size) || !isValidAuthCodeSize(req.auth_code.size)) {
        LOG_WARN("DraginoConfig: ignore gateway announce invalid sizes network=%u auth=%u",
                 req.network_public_key.size, req.auth_code.size);
        return;
    }

    auto &networkConfig = privateConfig.getNetworkConfigData();
    if (networkConfig.network_public_key.size != 32 || !privateConfig.hasNetworkSeed()) {
        LOG_WARN("DraginoConfig: ignore gateway announce, local network identity incomplete");
        return;
    }
    if (!constantTimeEquals(networkConfig.network_public_key.bytes, req.network_public_key.bytes, 32)) {
        LOG_WARN("DraginoConfig: ignore gateway announce, network key mismatch");
        return;
    }
    if (!verifyGatewayAnnounceAuthCode(networkConfig, req)) {
        LOG_WARN("DraginoConfig: ignore gateway announce, auth rejected");
        return;
    }

    const bool wasTrusted = privateConfig.isTrustedTimeSource(mp.from);
    if (!wasTrusted && !privateConfig.addTrustedTimeSourceNoSave(mp.from)) {
        LOG_WARN("DraginoConfig: gateway announce trusted gateway list full, source=0x%08x", mp.from);
        return;
    }
    bool changed = networkConfig.is_single_gateway || !wasTrusted;
    networkConfig.is_single_gateway = false;
    if (!changed) {
        LOG_INFO("DraginoConfig: gateway announce unchanged, source=0x%08x", mp.from);
        return;
    }
    if (!privateConfig.saveConfig()) {
        LOG_WARN("DraginoConfig: gateway announce save failed, source=0x%08x", mp.from);
        return;
    }

    LOG_INFO("DraginoConfig: gateway announce accepted, source=0x%08x", mp.from);
#endif
}

void DraginoConfigModule::handleSyncWakeupConfig(const meshtastic_MeshPacket &mp,
                                            const temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig &req)
{
    const bool broadcastWrite = isPrivateConfigBroadcast(mp);

    switch (req.which_payload) {
    case temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig_get_sync_wakeup_config_tag:
        sendSyncWakeupUplink();
        break;

    case temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig_config_tag:
        if (!privateConfig.isEnrolled()) {
            LOG_WARN("DraginoConfig: reject unauthorized sync wakeup config");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
            }
            return;
        }
        if (!broadcastWrite && !isPrivateConfigWriter(mp)) {
            LOG_WARN("DraginoConfig: reject unauthorized sync wakeup config");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED);
            }
            return;
        }
        if (!privateConfig.setSyncWakeup(req.payload.config)) {
            LOG_WARN("DraginoConfig: sync wakeup save failed");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED);
            }
            return;
        }
        if (draginoModule) {
            draginoModule->applySyncWakeupConfig();
        }
        touchConfigKeepAwakeLease();
        if (broadcastWrite) {
            LOG_INFO("DraginoConfig: sync wakeup broadcast applied");
            return;
        }
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                           0,
                           privateConfig.getNetworkConfigData().last_change_timestamp,
                           "sync wakeup saved");
        break;

    case temeshtastic_PrivateConfigPacket_SetSyncWakeupConfig_keep_awake_tag:
        if (!privateConfig.isEnrolled()) {
            LOG_WARN("DraginoConfig: reject keep awake before enrollment");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
            }
            return;
        }
        if (!canKeepAwakeRequest(mp, broadcastWrite)) {
            LOG_WARN("DraginoConfig: reject unauthorized keep awake");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED);
            }
            return;
        }
        if (!draginoModule) {
            LOG_WARN("DraginoConfig: keep awake ignored, DraginoModule unavailable");
            if (!broadcastWrite) {
                sendOperationResult(mp,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                                   temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE);
            }
            return;
        }
        draginoModule->requestConfigKeepAwake(req.payload.keep_awake.duration_sec);
        if (broadcastWrite) {
            LOG_INFO("DraginoConfig: keep awake broadcast applied duration=%u sec",
                     req.payload.keep_awake.duration_sec);
            return;
        }
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                           0,
                           privateConfig.getNetworkConfigData().last_change_timestamp,
                           "keep awake updated");
        break;

    default:
        LOG_WARN("DraginoConfig: unknown sync wakeup payload=%d", req.which_payload);
        if (!broadcastWrite) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_SYNC_WAKEUP_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
        }
        break;
    }
}

void DraginoConfigModule::handleInfoLabelConfig(const meshtastic_MeshPacket &mp,
                                           const temeshtastic_PrivateConfigPacket_SetInfoLabelConfig &req)
{
    switch (req.which_payload) {
    case temeshtastic_PrivateConfigPacket_SetInfoLabelConfig_get_info_label_config_tag:
        sendLabelsUplink();
        break;

    case temeshtastic_PrivateConfigPacket_SetInfoLabelConfig_set_info_label_tag: {
        if (!privateConfig.isEnrolled()) {
            LOG_WARN("DraginoConfig: reject unauthorized info label config");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
            return;
        }
        if (!isPrivateConfigWriter(mp)) {
            LOG_WARN("DraginoConfig: reject unauthorized info label config");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED);
            return;
        }
        const auto &set = req.payload.set_info_label;
        if (!set.has_info_label) {
            LOG_WARN("DraginoConfig: set info label missing label");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
            return;
        }

        bool success = false;
        switch (set.action) {
        case temeshtastic_PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabelAction_ADD:
            success = privateConfig.addInfoLabel(set.info_label.id, set.info_label.key, set.info_label.value);
            break;

        case temeshtastic_PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabelAction_UPDATE:
            success = privateConfig.updateInfoLabel(set.info_label.id, set.info_label.value);
            break;

        case temeshtastic_PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabelAction_DELETE:
            success = privateConfig.deleteInfoLabel(set.info_label.id);
            break;

        default:
            LOG_WARN("DraginoConfig: unknown info label action=%d", set.action);
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
            return;
        }

        if (!success) {
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NO_CHANGE);
            return;
        }
        if (!privateConfig.saveLabels()) {
            LOG_WARN("DraginoConfig: info label save failed");
            sendOperationResult(mp,
                               temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                               temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED);
            return;
        }
        touchConfigKeepAwakeLease();
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                           0,
                           privateConfig.getNetworkConfigData().last_change_timestamp,
                           "info label saved");
        break;
    }

    default:
        LOG_WARN("DraginoConfig: unknown info label payload=%d", req.which_payload);
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_INFO_LABEL_CONFIG,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_ARGUMENT);
        break;
    }
}

void DraginoConfigModule::handleEnterBootloader(const meshtastic_MeshPacket &mp,
                                           const temeshtastic_PrivateConfigPacket_EnterBootloader &req)
{
#if !defined(DRAGINO_REMOTENODE) || !defined(DRAGINO_STM32) || !defined(ARCH_STM32WL)
    (void)req;
    LOG_WARN("DraginoConfig: enter bootloader is unsupported in this firmware");
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_ENTER_BOOTLOADER,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_UNSUPPORTED);
    return;
#else
    const bool fromUpperComputer = requestFromUpperComputer_;
    const bool fromTrustedGateway = isTrustedGatewayCommand(mp);

    if (!fromUpperComputer && !privateConfig.isEnrolled()) {
        LOG_WARN("DraginoConfig: not enrolled, cannot enter bootloader remotely");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_ENTER_BOOTLOADER,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_ENROLLED);
        return;
    }

    if (!fromUpperComputer && !fromTrustedGateway) {
        LOG_WARN("DraginoConfig: reject unauthorized enter bootloader request from 0x%08x", mp.from);
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_ENTER_BOOTLOADER,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_NOT_AUTHORIZED,
                           privateConfig.getPrimaryTrustedGateway());
        return;
    }

    BootUpgradeReason reason = mapBootloaderReason(req.reason);
    if (reason == BootUpgradeReason::Unknown && fromUpperComputer) {
        reason = BootUpgradeReason::UpperComputer;
    }

    if (!requestBootloaderUpgrade(reason)) {
        LOG_WARN("DraginoConfig: failed to set bootloader request flag");
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_ENTER_BOOTLOADER,
                           temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_SAVE_FAILED,
                           fromTrustedGateway ? mp.from : privateConfig.getPrimaryTrustedGateway());
        return;
    }

    const uint32_t delayMs = normalizeBootloaderRebootDelay(req.delay_ms, fromUpperComputer);
    const uint32_t gatewayNodeId = fromTrustedGateway ? mp.from : privateConfig.getPrimaryTrustedGateway();

    LOG_INFO("DraginoConfig: bootloader reboot scheduled in %u ms, reason=%u, source=0x%08x",
             (unsigned)delayMs,
             (unsigned)static_cast<uint32_t>(reason),
             mp.from);
    sendOperationResult(mp,
                       temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_ENTER_BOOTLOADER,
                       temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_OK,
                       gatewayNodeId,
                       0,
                       "bootloader reboot scheduled");

    rebootAtMsec = millis() + delayMs;
    runASAP = true;
#endif
}

void DraginoConfigModule::sendFactoryIdentityUplink(bool includePrivateKey)
{
#if defined(DRAGINO_REMOTENODE)
    privateConfig.syncFactoryIdentityFromStorage(false);

    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    packet.which_packet_type = temeshtastic_PrivateConfigPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_PrivateConfigPacket_UplinkPacket_factory_identity_tag;
    packet.packet_type.uplink_packet.payload.factory_identity = privateConfig.getConfig().factory_identity;
    if (!includePrivateKey) {
        packet.packet_type.uplink_packet.payload.factory_identity.device_private_key.size = 0;
        memset(packet.packet_type.uplink_packet.payload.factory_identity.device_private_key.bytes,
               0,
               sizeof(packet.packet_type.uplink_packet.payload.factory_identity.device_private_key.bytes));
        packet.packet_type.uplink_packet.payload.factory_identity.legacy_app_key.size = 0;
        memset(packet.packet_type.uplink_packet.payload.factory_identity.legacy_app_key.bytes,
               0,
               sizeof(packet.packet_type.uplink_packet.payload.factory_identity.legacy_app_key.bytes));
    }
    sendUplink(packet);
#else
    (void)includePrivateKey;
#endif
}

void DraginoConfigModule::sendNetworkConfigUplink(const meshtastic_MeshPacket &mp)
{
    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    packet.which_packet_type = temeshtastic_PrivateConfigPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_PrivateConfigPacket_UplinkPacket_network_config_tag;
    packet.packet_type.uplink_packet.payload.network_config = privateConfig.getNetworkConfigData();

    auto &networkConfig = packet.packet_type.uplink_packet.payload.network_config;
    const bool fullView = requestFromUpperComputer_;
    const bool trustedView = fullView || isPrivateConfigWriter(mp);

    if (!fullView) {
        networkConfig.network_seed.size = 0;
        memset(networkConfig.network_seed.bytes, 0, sizeof(networkConfig.network_seed.bytes));
    }
    if (!trustedView) {
        networkConfig.is_single_gateway = false;
        networkConfig.trusted_gateway_sources_count = 0;
        networkConfig.last_change_timestamp = 0;
    }

    sendUplink(packet);
}

void DraginoConfigModule::sendSyncWakeupUplink()
{
    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    packet.which_packet_type = temeshtastic_PrivateConfigPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_PrivateConfigPacket_UplinkPacket_sync_wakeup_config_tag;
    packet.packet_type.uplink_packet.payload.sync_wakeup_config = privateConfig.getSyncWakeup();
    sendUplink(packet);
}

void DraginoConfigModule::sendLabelsUplink()
{
    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    packet.which_packet_type = temeshtastic_PrivateConfigPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_PrivateConfigPacket_UplinkPacket_device_labels_tag;
    packet.packet_type.uplink_packet.payload.device_labels = privateConfig.getLabels();
    sendUplink(packet);
}

void DraginoConfigModule::sendOperationResult(const meshtastic_MeshPacket &mp,
                                         temeshtastic_PrivateConfigPacket_OperationResult_Operation operation,
                                         temeshtastic_PrivateConfigPacket_OperationResult_Status status,
                                         uint32_t gatewayNodeId,
                                         uint64_t operationTimestamp,
                                         const char *message)
{
    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    packet.which_packet_type = temeshtastic_PrivateConfigPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_PrivateConfigPacket_UplinkPacket_operation_result_tag;

    auto &result = packet.packet_type.uplink_packet.payload.operation_result;
    result.operation = operation;
    result.status = status;
    result.request_id = mp.id;
    result.target_node_id = nodeDB->getNodeNum();
    result.source_node_id = mp.from;
    result.gateway_node_id = gatewayNodeId;
    result.operation_timestamp = operationTimestamp;
    if (message != nullptr) {
        strncpy(result.message, message, sizeof(result.message) - 1);
        result.message[sizeof(result.message) - 1] = '\0';
    }

    sendUplink(packet);
}

bool DraginoConfigModule::sendJoinLockAdvertise(bool force)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (privateConfig.isEnrolled()) {
        clearJoinChallenge();
        return false;
    }

    uint32_t now = millis();
    if (!force && lastJoinAdvertiseMs_ != 0 &&
        !elapsedSince(lastJoinAdvertiseMs_, now, DRAGINO_JOIN_ADVERTISE_INTERVAL_MS)) {
        return false;
    }

    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    if (!buildJoinLockAdvertisePacket(packet, true)) {
        return false;
    }

    meshtastic_MeshPacket *p = allocDataProtobuf(packet);
    if (!p) {
        LOG_WARN("DraginoConfig: failed to allocate join advertise");
        return false;
    }

    p->to = NODENUM_BROADCAST;
    p->want_ack = false;
    p->decoded.want_response = false;
    p->priority = meshtastic_MeshPacket_Priority_BACKGROUND;

    service->sendToMesh(p, RX_SRC_LOCAL, true);
    lastJoinAdvertiseMs_ = now;
    LOG_INFO("DraginoConfig: join lock advertised");
    return true;
#else
    (void)force;
    return false;
#endif
}

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
void DraginoConfigModule::rotateJoinChallengeForDiscovery()
{
    if (privateConfig.isEnrolled()) {
        clearJoinChallenge();
        return;
    }

    regenerateJoinChallenge();
    LOG_INFO("DraginoConfig: join challenge rotated for factory discovery");
}
#endif

void DraginoConfigModule::sendUplink(const temeshtastic_PrivateConfigPacket &packet)
{
    meshtastic_MeshPacket *p = allocDataProtobuf(packet);
    if (!p) {
        LOG_WARN("DraginoConfig: failed to allocate uplink");
        return;
    }

    if (requestFromUpperComputer_) {
        ignoreRequest = true;
        service->sendToPhone(p);
        requestFromUpperComputer_ = false;
    } else {
        if (currentRequest && currentRequest->pki_encrypted) {
            p->pki_encrypted = true;
        }
        myReply = p;
    }
}

#if defined(DRAGINO_REMOTENODE)
#if defined(DRAGINO_STM32)
bool DraginoConfigModule::buildJoinLockAdvertisePacket(temeshtastic_PrivateConfigPacket &packet, bool updateThrottleOnFailure)
{
    if (privateConfig.isEnrolled()) {
        clearJoinChallenge();
        LOG_WARN("DraginoConfig: join advertise skipped, already enrolled");
        return false;
    }

    const uint32_t now = millis();
    if (!privateConfig.syncFactoryIdentityFromStorage(false)) {
        if (updateThrottleOnFailure) {
            lastJoinAdvertiseMs_ = now;
        }
        LOG_WARN("DraginoConfig: join advertise skipped, factory identity unavailable");
        return false;
    }

    const auto &identity = privateConfig.getConfig().factory_identity;
    if (!isJoinIdentityReady(identity) || identity.device_private_key.size != 32) {
        if (updateThrottleOnFailure) {
            lastJoinAdvertiseMs_ = now;
        }
        LOG_WARN("DraginoConfig: join advertise skipped, factory identity incomplete");
        return false;
    }

    ensureJoinChallenge();

    memset(&packet, 0, sizeof(packet));
    packet.which_packet_type = temeshtastic_PrivateConfigPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_PrivateConfigPacket_UplinkPacket_join_lock_advertise_tag;

    auto &advertise = packet.packet_type.uplink_packet.payload.join_lock_advertise;
    advertise.join_challenge.size = 16;
    memcpy(advertise.join_challenge.bytes, joinChallenge_, 16);
    advertise.dev_eui_hi = identity.dev_eui_hi;
    advertise.dev_eui_lo = identity.dev_eui_lo;
    strncpy(advertise.sn, identity.sn, sizeof(advertise.sn) - 1);
    advertise.sn[sizeof(advertise.sn) - 1] = '\0';
    return true;
}

void DraginoConfigModule::sendJoinLockAdvertiseUplink(const meshtastic_MeshPacket &mp)
{
    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    if (!buildJoinLockAdvertisePacket(packet, false)) {
        const auto status = privateConfig.isEnrolled()
                                ? temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_ALREADY_ENROLLED
                                : temeshtastic_PrivateConfigPacket_OperationResult_Status_STATUS_INVALID_STATE;
        sendOperationResult(mp,
                           temeshtastic_PrivateConfigPacket_OperationResult_Operation_OPERATION_JOIN_NETWORK_V2,
                           status,
                           0,
                           0,
                           "join lock unavailable");
        return;
    }

    sendUplink(packet);
    LOG_INFO("DraginoConfig: join lock sent to requester");
}
#endif

void DraginoConfigModule::ensureJoinChallenge()
{
    uint32_t now = millis();
    if (!hasJoinChallenge_ || elapsedSince(joinChallengeGeneratedMs_, now, DRAGINO_JOIN_CHALLENGE_TTL_MS)) {
        regenerateJoinChallenge();
    }
}

void DraginoConfigModule::regenerateJoinChallenge()
{
    for (size_t i = 0; i < sizeof(joinChallenge_); i += sizeof(uint32_t)) {
        uint32_t value = ((uint32_t)random(0x10000L) << 16) | (uint32_t)random(0x10000L);
        value ^= nodeDB->getNodeNum();
        value ^= millis() + (uint32_t)(i * 2654435761UL);
        memcpy(joinChallenge_ + i, &value, sizeof(value));
    }

    joinChallengeGeneratedMs_ = millis();
    hasJoinChallenge_ = true;
    lastJoinAdvertiseMs_ = 0;
}

void DraginoConfigModule::clearJoinChallenge()
{
    hasJoinChallenge_ = false;
    memset(joinChallenge_, 0, sizeof(joinChallenge_));
    joinChallengeGeneratedMs_ = 0;
    lastJoinAdvertiseMs_ = 0;
}
#endif

}
