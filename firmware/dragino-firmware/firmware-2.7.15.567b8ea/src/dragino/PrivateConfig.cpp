#include "PrivateConfig.h"
#include "DraginoRolePolicy.h"
#include "mesh/NodeDB.h"
#include "mesh/Channels.h"
#include "mesh/CryptoEngine.h"
#include "FSCommon.h"
#include "configuration.h"
#include "SPILock.h"
#include <string.h>

#if defined(DRAGINO_REMOTENODE)
#include "FactoryIdentityManager.h"
#endif

static bool isValidNetworkSeedSize(pb_size_t size)
{
    return size >= DRAGINO_JOIN_V2_NETWORK_SEED_MIN_SIZE && size <= DRAGINO_JOIN_V2_NETWORK_SEED_MAX_SIZE;
}

PrivateConfigManager& PrivateConfigManager::instance()
{
    static PrivateConfigManager inst;
    return inst;
}

PrivateConfigManager::PrivateConfigManager()
{
    initDefaultConfig();
    initDefaultLabels();
}

void PrivateConfigManager::initDefaultConfig()
{
    memset(&_config, 0, sizeof(_config));
    _config.private_version = 0x20260515;

    _config.has_sync_wakeup = true;
    _config.sync_wakeup.enabled = DRAGINO_DEFAULT_WAKEUP_ENABLED;
    _config.sync_wakeup.strategy = temeshtastic_SyncWakeupConfig_WakeupStrategy_STRATEGY_FIXED;
    _config.sync_wakeup.has_fixed_wakeup = true;
    _config.sync_wakeup.fixed_wakeup.interval_min = DRAGINO_DEFAULT_WAKEUP_INTERVAL_MIN;
    _config.sync_wakeup.fixed_wakeup.align_minute = DRAGINO_DEFAULT_WAKEUP_ALIGN_MINUTE;
    _config.sync_wakeup.fixed_wakeup.offset_sec = DRAGINO_DEFAULT_WAKEUP_OFFSET_SEC;
    _config.sync_wakeup.has_scheduled_wakeup = false;
    applyDefaultWakeupWindowIfMissing();
}

void PrivateConfigManager::initDefaultLabels()
{
    memset(&_labels, 0, sizeof(_labels));

    _labels.info_labels_count = 2;

    _labels.info_labels[0].id = 1;
    strncpy(_labels.info_labels[0].key, "organization", sizeof(_labels.info_labels[0].key) - 1);
    strncpy(_labels.info_labels[0].value, "dragino", sizeof(_labels.info_labels[0].value) - 1);

    _labels.info_labels[1].id = 2;
    strncpy(_labels.info_labels[1].key, "DataTime", sizeof(_labels.info_labels[1].key) - 1);
    strncpy(_labels.info_labels[1].value, "0x1773220759", sizeof(_labels.info_labels[1].value) - 1);
}

void PrivateConfigManager::applyDefaultWakeupWindowIfMissing()
{
    _config.sync_wakeup.has_wakeup_window = true;
    auto &window = _config.sync_wakeup.wakeup_window;

    if (window.startup_delay_sec == 0)
        window.startup_delay_sec = DRAGINO_DEFAULT_STARTUP_DELAY_MS / 1000;
    if (window.random_delay_max_sec == 0)
        window.random_delay_max_sec = DRAGINO_DEFAULT_RANDOM_DELAY_MAX_MS / 1000;
    if (window.gateway_wait_sec == 0)
        window.gateway_wait_sec = DRAGINO_DEFAULT_GATEWAY_TIMEOUT_MS / 1000;
    if (window.final_wait_sec == 0)
        window.final_wait_sec = DRAGINO_DEFAULT_FINAL_WAIT_MS / 1000;
    if (window.degraded_window_sec == 0)
        window.degraded_window_sec = DRAGINO_DEGRADED_ACTIVE_WINDOW_MS / 1000;
    if (window.factory_window_sec == 0)
        window.factory_window_sec = DRAGINO_FACTORY_ACTIVE_WINDOW_MS / 1000;
}

bool PrivateConfigManager::validateConfig()
{
    bool fixed = false;

    if (_config.private_version == 0) {
        _config.private_version = 0x20260515;
        fixed = true;
    }

    if (_config.has_network_config && _config.network_config.network_public_key.size != 32) {
        LOG_WARN("Validation: invalid network key, clearing network config");
        memset(&_config.network_config, 0, sizeof(_config.network_config));
        _config.has_network_config = false;
        fixed = true;
    }

    if (_config.has_network_config && !isValidNetworkSeedSize(_config.network_config.network_seed.size)) {
        LOG_WARN("Validation: invalid network seed, clearing network config");
        memset(&_config.network_config, 0, sizeof(_config.network_config));
        _config.has_network_config = false;
        fixed = true;
    }

    if (!_config.has_sync_wakeup) {
        _config.has_sync_wakeup = true;
        _config.sync_wakeup.enabled = DRAGINO_DEFAULT_WAKEUP_ENABLED;
        _config.sync_wakeup.strategy = temeshtastic_SyncWakeupConfig_WakeupStrategy_STRATEGY_FIXED;
        _config.sync_wakeup.has_fixed_wakeup = true;
        _config.sync_wakeup.fixed_wakeup.interval_min = DRAGINO_DEFAULT_WAKEUP_INTERVAL_MIN;
        _config.sync_wakeup.fixed_wakeup.align_minute = DRAGINO_DEFAULT_WAKEUP_ALIGN_MINUTE;
        _config.sync_wakeup.fixed_wakeup.offset_sec = DRAGINO_DEFAULT_WAKEUP_OFFSET_SEC;
        fixed = true;
    }

    if (!_config.sync_wakeup.has_wakeup_window ||
        _config.sync_wakeup.wakeup_window.startup_delay_sec == 0 ||
        _config.sync_wakeup.wakeup_window.gateway_wait_sec == 0 ||
        _config.sync_wakeup.wakeup_window.final_wait_sec == 0 ||
        _config.sync_wakeup.wakeup_window.degraded_window_sec == 0 ||
        _config.sync_wakeup.wakeup_window.factory_window_sec == 0) {
        applyDefaultWakeupWindowIfMissing();
        fixed = true;
    }

    if (fixed) {
        saveConfig();
    }

    return !fixed;
}

bool PrivateConfigManager::loadConfig()
{
    initDefaultConfig();

#ifdef FSCom
    LoadFileResult result = nodeDB->loadProto(configFile,
                                              temeshtastic_PrivateConfig_size,
                                              sizeof(temeshtastic_PrivateConfig),
                                              temeshtastic_PrivateConfig_fields,
                                              &_config);

    if (result == LOAD_SUCCESS) {
        LOG_INFO("Loaded private config");
    } else {
        LOG_INFO("Private config not found, saving defaults");
        saveConfig();
    }

    validateConfig();
#if defined(DRAGINO_REMOTENODE)
    syncFactoryIdentityFromStorage(true);
#endif
    return true;
#else
    return false;
#endif
}

bool PrivateConfigManager::saveConfig()
{
#ifdef FSCom
    spiLock->lock();
    FSCom.mkdir("/prefs");
    spiLock->unlock();
#endif

    bool result = nodeDB->saveProto(configFile,
                                    temeshtastic_PrivateConfig_size,
                                    temeshtastic_PrivateConfig_fields,
                                    &_config,
                                    true);

    if (result) {
        LOG_INFO("Saved private config");
    } else {
        LOG_ERROR("Failed to save private config");
    }

    return result;
}

bool PrivateConfigManager::loadLabels()
{
    initDefaultLabels();

#ifdef FSCom
    LoadFileResult result = nodeDB->loadProto(labelsFile,
                                              temeshtastic_DeviceLabels_size,
                                              sizeof(temeshtastic_DeviceLabels),
                                              temeshtastic_DeviceLabels_fields,
                                              &_labels);

    if (result == LOAD_SUCCESS) {
        LOG_INFO("Loaded device labels");
    } else {
        LOG_INFO("Device labels not found, saving defaults");
        saveLabels();
    }
    return true;
#else
    return false;
#endif
}

bool PrivateConfigManager::saveLabels()
{
#ifdef FSCom
    spiLock->lock();
    FSCom.mkdir("/prefs");
    spiLock->unlock();
#endif

    bool result = nodeDB->saveProto(labelsFile,
                                    temeshtastic_DeviceLabels_size,
                                    temeshtastic_DeviceLabels_fields,
                                    &_labels,
                                    true);

    if (result) {
        LOG_INFO("Saved device labels");
    } else {
        LOG_ERROR("Failed to save device labels");
    }

    return result;
}

bool PrivateConfigManager::loadAll()
{
    return loadConfig() && loadLabels();
}

bool PrivateConfigManager::applyFactoryIdentityMirror(const temeshtastic_DeviceFactoryIdentity &identity,
                                                      bool saveMirrorIfChanged)
{
#if defined(DRAGINO_REMOTENODE)
    if (!dragino::factoryIdentity.validate(identity)) {
        return false;
    }

    bool changed = !_config.has_factory_identity ||
                   memcmp(&_config.factory_identity, &identity, sizeof(identity)) != 0;

    _config.has_factory_identity = true;
    _config.factory_identity = identity;

    syncSecurityKeyFromFactoryIdentity(saveMirrorIfChanged);

    if (changed) {
        LOG_INFO("FactoryIdentity: private config mirror updated");
        if (saveMirrorIfChanged) {
            return saveConfig();
        }
    }

    return true;
#else
    (void)identity;
    (void)saveMirrorIfChanged;
    return false;
#endif
}

bool PrivateConfigManager::syncSecurityKeyFromFactoryIdentity(bool saveIfChanged)
{
#if defined(DRAGINO_REMOTENODE) && !MESHTASTIC_EXCLUDE_PKI
    if (!_config.has_factory_identity || !dragino::factoryIdentity.validate(_config.factory_identity)) {
        return false;
    }

    const auto &identity = _config.factory_identity;
    if (identity.device_private_key.size != 32) {
        return false;
    }

    uint8_t publicKey[32] = {};
    uint8_t privateKey[32] = {};
    memcpy(privateKey, identity.device_private_key.bytes, sizeof(privateKey));

#if !MESHTASTIC_EXCLUDE_PKI_KEYGEN
    if (!crypto->regeneratePublicKey(publicKey, privateKey)) {
        LOG_WARN("FactoryIdentity: failed to derive security public key");
        return false;
    }
#else
    LOG_WARN("FactoryIdentity: cannot derive public key when PKI keygen is excluded");
    return false;
#endif

    bool changed = !config.has_security ||
                   config.security.private_key.size != 32 ||
                   config.security.public_key.size != 32 ||
                   memcmp(config.security.private_key.bytes, identity.device_private_key.bytes, 32) != 0 ||
                   memcmp(config.security.public_key.bytes, publicKey, 32) != 0 ||
                   owner.public_key.size != 32 ||
                   memcmp(owner.public_key.bytes, publicKey, 32) != 0;

    config.has_security = true;
    config.security.private_key.size = 32;
    memcpy(config.security.private_key.bytes, identity.device_private_key.bytes, 32);
    config.security.public_key.size = 32;
    memcpy(config.security.public_key.bytes, publicKey, 32);
    owner.public_key.size = 32;
    memcpy(owner.public_key.bytes, publicKey, 32);
    crypto->setDHPrivateKey(config.security.private_key.bytes);

    if (changed) {
        LOG_INFO("FactoryIdentity: security key synced from factory identity");
        if (saveIfChanged && nodeDB) {
            nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_DEVICESTATE | SEGMENT_NODEDATABASE);
        }
    }

    return true;
#else
    (void)saveIfChanged;
    return false;
#endif
}

bool PrivateConfigManager::hasValidFactoryIdentity() const
{
#if defined(DRAGINO_REMOTENODE)
    return _config.has_factory_identity && dragino::factoryIdentity.validate(_config.factory_identity);
#else
    return false;
#endif
}

bool PrivateConfigManager::syncFactoryIdentityFromStorage(bool saveMirrorIfChanged)
{
#if defined(DRAGINO_REMOTENODE)
    if (_config.has_factory_identity && dragino::factoryIdentity.validate(_config.factory_identity)) {
        syncSecurityKeyFromFactoryIdentity(saveMirrorIfChanged);
        return true;
    }

    temeshtastic_DeviceFactoryIdentity identity = temeshtastic_DeviceFactoryIdentity_init_zero;
    dragino::FactoryIdentityManager::ReadStatus status = dragino::factoryIdentity.read(identity);

    if (status == dragino::FactoryIdentityManager::ReadStatus::OK) {
        return applyFactoryIdentityMirror(identity, saveMirrorIfChanged);
    }

    LOG_INFO("FactoryIdentity: storage read status=%s", dragino::factoryIdentity.statusName(status));
    dragino::factoryIdentity.logStorageDiagnostics(status);
    if (status == dragino::FactoryIdentityManager::ReadStatus::UNSUPPORTED_PLATFORM) {
        return false;
    }
    bool changed = !_config.has_factory_identity ||
                   memcmp(&_config.factory_identity, &identity, sizeof(identity)) != 0;

    _config.has_factory_identity = true;
    _config.factory_identity = identity;

    if (changed) {
        if (saveMirrorIfChanged) {
            saveConfig();
        }
    }
    return false;
#else
    (void)saveMirrorIfChanged;
    return false;
#endif
}

bool PrivateConfigManager::saveAll()
{
    return saveConfig() && saveLabels();
}

bool PrivateConfigManager::resetAll()
{
    initDefaultConfig();
#if defined(DRAGINO_REMOTENODE)
    syncFactoryIdentityFromStorage(false);
#endif

    initDefaultLabels();
    return saveAll();
}

bool PrivateConfigManager::addInfoLabel(uint32_t id, const char *key, const char *value)
{
    if (_labels.info_labels_count >= 10) {
        return false;
    }

    temeshtastic_DeviceLabels_InfoLabel *label = &_labels.info_labels[_labels.info_labels_count++];
    label->id = id;
    strncpy(label->key, key, sizeof(label->key) - 1);
    strncpy(label->value, value, sizeof(label->value) - 1);
    return true;
}

bool PrivateConfigManager::updateInfoLabel(uint32_t id, const char *value)
{
    for (pb_size_t i = 0; i < _labels.info_labels_count; i++) {
        if (_labels.info_labels[i].id == id) {
            strncpy(_labels.info_labels[i].value, value, sizeof(_labels.info_labels[i].value) - 1);
            return true;
        }
    }
    return false;
}

bool PrivateConfigManager::deleteInfoLabel(uint32_t id)
{
    for (pb_size_t i = 0; i < _labels.info_labels_count; i++) {
        if (_labels.info_labels[i].id == id) {
            for (pb_size_t j = i; j < _labels.info_labels_count - 1; j++) {
                _labels.info_labels[j] = _labels.info_labels[j + 1];
            }
            _labels.info_labels_count--;
            return true;
        }
    }
    return false;
}

const temeshtastic_DeviceLabels_InfoLabel *PrivateConfigManager::findInfoLabel(uint32_t id)
{
    for (pb_size_t i = 0; i < _labels.info_labels_count; i++) {
        if (_labels.info_labels[i].id == id) {
            return &_labels.info_labels[i];
        }
    }
    return nullptr;
}

const temeshtastic_DeviceLabels_InfoLabel *PrivateConfigManager::findInfoLabelByKey(const char *key)
{
    for (pb_size_t i = 0; i < _labels.info_labels_count; i++) {
        if (strcmp(_labels.info_labels[i].key, key) == 0) {
            return &_labels.info_labels[i];
        }
    }
    return nullptr;
}

void PrivateConfigManager::clearInfoLabels()
{
    _labels.info_labels_count = 0;
}

bool PrivateConfigManager::hasSyncWakeup()
{
    return _config.has_sync_wakeup;
}

bool PrivateConfigManager::isSyncWakeupEnabled()
{
    return _config.has_sync_wakeup && _config.sync_wakeup.enabled;
}

temeshtastic_SyncWakeupConfig &PrivateConfigManager::getSyncWakeup()
{
    return _config.sync_wakeup;
}

bool PrivateConfigManager::setSyncWakeup(const temeshtastic_SyncWakeupConfig &syncConfig)
{
    _config.has_sync_wakeup = true;
    _config.sync_wakeup = syncConfig;
    applyDefaultWakeupWindowIfMissing();
    return saveConfig();
}

const temeshtastic_SyncWakeupConfig_WakeupWindow &PrivateConfigManager::getWakeupWindow()
{
    applyDefaultWakeupWindowIfMissing();
    return _config.sync_wakeup.wakeup_window;
}

bool PrivateConfigManager::hasNetworkConfig()
{
    return _config.has_network_config && _config.network_config.network_public_key.size == 32;
}

bool PrivateConfigManager::isEnrolled()
{
    return hasNetworkConfig();
}

bool PrivateConfigManager::isPrivatized()
{
    extern Channels channels;
    const char *ch1Name = channels.getByIndex(DRAGINO_CHANNEL_PRIVATE_CONFIG).settings.name;
    const char *ch2Name = channels.getByIndex(DRAGINO_CHANNEL_PRIVATE_FUNCTION).settings.name;
    return (ch1Name[0] != '\0') && (ch2Name[0] != '\0');
}

bool PrivateConfigManager::isReadyForPrivateConfig()
{
    return isEnrolled() && isPrivatized();
}

temeshtastic_NetWorkConfig &PrivateConfigManager::getNetworkConfigData()
{
    return _config.network_config;
}

void PrivateConfigManager::setNetworkPublicKey(const uint8_t *pubkey)
{
    _config.has_network_config = true;
    _config.network_config.network_public_key.size = 32;
    memcpy(_config.network_config.network_public_key.bytes, pubkey, 32);
}

void PrivateConfigManager::setNetworkSeedNoSave(const uint8_t *seed, pb_size_t seedSize)
{
    _config.has_network_config = true;
    if (!seed || !isValidNetworkSeedSize(seedSize)) {
        clearNetworkSeedNoSave();
        return;
    }

    _config.network_config.network_seed.size = seedSize;
    memcpy(_config.network_config.network_seed.bytes, seed, seedSize);
    if (seedSize < sizeof(_config.network_config.network_seed.bytes)) {
        memset(_config.network_config.network_seed.bytes + seedSize,
               0,
               sizeof(_config.network_config.network_seed.bytes) - seedSize);
    }
}

void PrivateConfigManager::clearNetworkSeedNoSave()
{
    _config.network_config.network_seed.size = 0;
    memset(_config.network_config.network_seed.bytes, 0, sizeof(_config.network_config.network_seed.bytes));
}

bool PrivateConfigManager::hasNetworkSeed() const
{
    return _config.has_network_config && isValidNetworkSeedSize(_config.network_config.network_seed.size);
}

void PrivateConfigManager::setIsEnrolled(bool enrolled)
{
    if (enrolled) {
        _config.has_network_config = true;
        return;
    }

    memset(&_config.network_config, 0, sizeof(_config.network_config));
    _config.has_network_config = false;
}

void PrivateConfigManager::setLastChangeTimestamp(uint64_t timestamp)
{
    _config.network_config.last_change_timestamp = timestamp;
}

void PrivateConfigManager::setGatewayPublicKey(const uint8_t *pubkey)
{
    setGatewayPublicKeyNoSave(pubkey);
    nodeDB->saveToDisk(SEGMENT_CONFIG);
}

void PrivateConfigManager::setGatewayPublicKeyNoSave(const uint8_t *pubkey)
{
    config.security.admin_key[0].size = 32;
    memcpy(config.security.admin_key[0].bytes, pubkey, 32);
    config.security.admin_key_count = 1;
}

static void clearPrivateChannel(uint8_t index)
{
    meshtastic_Channel ch = channels.getByIndex(index);
    memset(&ch.settings, 0, sizeof(ch.settings));
    ch.has_settings = false;
    ch.role = meshtastic_Channel_Role_DISABLED;
    channels.setChannel(ch);
}

uint32_t PrivateConfigManager::getPrimaryTrustedGateway() const
{
    if (!_config.has_network_config || _config.network_config.trusted_gateway_sources_count == 0) {
        return 0;
    }

    uint32_t gateway = _config.network_config.trusted_gateway_sources[0];
    if (gateway == 0 || gateway == NODENUM_BROADCAST) {
        return 0;
    }
    return gateway;
}

bool PrivateConfigManager::executeResetConfig(uint32_t reset_type)
{
    LOG_INFO("Executing reset config, type=%d", reset_type);

    for (pb_size_t i = 0; i < _config.network_config.trusted_gateway_sources_count; i++) {
        if (nodeDB->isFavorite(_config.network_config.trusted_gateway_sources[i])) {
            nodeDB->set_favorite(false, _config.network_config.trusted_gateway_sources[i]);
        }
    }

    switch (reset_type) {
    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ResetType_RESET_TYPE_FACTORY:
        initDefaultConfig();
#if defined(DRAGINO_REMOTENODE)
        syncFactoryIdentityFromStorage(false);
#endif
        break;

    case temeshtastic_PrivateConfigPacket_SetNetWorkConfig_ResetType_RESET_TYPE_NETWORK:
        memset(&_config.network_config, 0, sizeof(_config.network_config));
        _config.has_network_config = false;
        break;

    default:
        LOG_WARN("Unknown reset type: %d", reset_type);
        return false;
    }

    memset(config.security.admin_key, 0, sizeof(config.security.admin_key));
    config.security.admin_key_count = 0;
    clearPrivateChannel(DRAGINO_CHANNEL_PRIVATE_CONFIG);
    clearPrivateChannel(DRAGINO_CHANNEL_PRIVATE_FUNCTION);
    channels.onConfigChanged();
    const int roleSaveMask = dragino::applyRemoteNodeEnrollmentRolePolicy("reset-network");
    const bool configSaved = saveConfig();
    const bool dbSaved = nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_CHANNELS | roleSaveMask);
    LOG_INFO("Reset config completed");
    return configSaved && dbSaved;
}

bool PrivateConfigManager::executeChangeNetworkKey(const uint8_t *new_pubkey,
                                                   const uint8_t *new_seed,
                                                   pb_size_t newSeedSize,
                                                   uint64_t timestamp)
{
    _config.has_network_config = true;
    _config.network_config.network_public_key.size = 32;
    memcpy(_config.network_config.network_public_key.bytes, new_pubkey, 32);
    setNetworkSeedNoSave(new_seed, newSeedSize);
    _config.network_config.last_change_timestamp = timestamp;
    const bool saved = saveConfig();
    LOG_INFO("Network key changed");
    return saved;
}

bool PrivateConfigManager::isTrustedTimeSource(uint32_t nodeId) const
{
    for (pb_size_t i = 0; i < _config.network_config.trusted_gateway_sources_count; i++) {
        if (_config.network_config.trusted_gateway_sources[i] == nodeId) {
            return true;
        }
    }
    return false;
}

bool PrivateConfigManager::addTrustedTimeSource(uint32_t nodeId)
{
    bool updated = addTrustedTimeSourceNoSave(nodeId);
    if (updated) {
        saveConfig();
    }
    return updated;
}

bool PrivateConfigManager::removeTrustedTimeSource(uint32_t nodeId)
{
    bool updated = removeTrustedTimeSourceNoSave(nodeId);
    if (updated) {
        saveConfig();
    }
    return updated;
}

void PrivateConfigManager::clearTrustedTimeSources()
{
    clearTrustedTimeSourcesNoSave();
    saveConfig();
}

bool PrivateConfigManager::addTrustedTimeSourceNoSave(uint32_t nodeId)
{
    if (nodeId == 0 || nodeId == NODENUM_BROADCAST) {
        return false;
    }
    if (isTrustedTimeSource(nodeId)) {
        return true;
    }
    if (_config.network_config.trusted_gateway_sources_count >= 4) {
        return false;
    }

    _config.has_network_config = true;
    _config.network_config.trusted_gateway_sources[_config.network_config.trusted_gateway_sources_count++] = nodeId;
    return true;
}

bool PrivateConfigManager::removeTrustedTimeSourceNoSave(uint32_t nodeId)
{
    for (pb_size_t i = 0; i < _config.network_config.trusted_gateway_sources_count; i++) {
        if (_config.network_config.trusted_gateway_sources[i] == nodeId) {
            for (pb_size_t j = i; j < _config.network_config.trusted_gateway_sources_count - 1; j++) {
                _config.network_config.trusted_gateway_sources[j] = _config.network_config.trusted_gateway_sources[j + 1];
            }
            _config.network_config.trusted_gateway_sources_count--;
            return true;
        }
    }
    return false;
}

void PrivateConfigManager::clearTrustedTimeSourcesNoSave()
{
    _config.network_config.trusted_gateway_sources_count = 0;
}

PrivateConfigManager& privateConfig = PrivateConfigManager::instance();
