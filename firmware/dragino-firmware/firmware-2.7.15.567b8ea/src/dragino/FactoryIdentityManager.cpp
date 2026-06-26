#include "FactoryIdentityManager.h"
#include "DraginoDefaultConfig.h"
#include "DraginoInternalFlash.h"
#include "configuration.h"
#include <SHA256.h>
#include <stddef.h>
#include <string.h>

#if defined(DRAGINO_REMOTENODE)

#if defined(ARCH_STM32WL) && defined(DRAGINO_FACTORY_IDENTITY_RESERVED)
#include "stm32wlxx_hal_flash.h"
#define DRAGINO_FACTORY_IDENTITY_STM32_STORAGE 1
#endif

namespace dragino {

namespace {

constexpr uint32_t FACTORY_IDENTITY_MAGIC = 0x44474649UL; // "DGFI"
constexpr uint16_t FACTORY_IDENTITY_STORAGE_VERSION_V2 = 2;
constexpr uint16_t FACTORY_IDENTITY_STORAGE_VERSION_V3 = 3;
constexpr uint16_t FACTORY_IDENTITY_STORAGE_VERSION_V4 = 4;
constexpr uint16_t LEGACY_LORAWAN_IDENTITY_VERSION = 1;
constexpr uint16_t LEGACY_LORAWAN_IDENTITY_SIZE = 92;
constexpr uint16_t LEGACY_DERIVE_ALG_VERSION_V1 = 0;
constexpr uint16_t LEGACY_LORAWAN_KEY_DERIVE_SIZE = 32;
constexpr uint32_t FACTORY_IDENTITY_V4_FLAG_LEGACY_CRC_VALID = 1UL << 0;
constexpr uint32_t FACTORY_IDENTITY_V4_FLAG_LOCKED = 1UL << 1;
constexpr char PRIVATE_KEY_DERIVE_DOMAIN[] = "DGFI-LA66S-MESH-PRIVATEKEY-V1";

#pragma pack(push, 1)
struct FactoryIdentityHeader {
    uint32_t magic;
    uint16_t storageVersion;
    uint16_t recordSize;
};

struct FactoryIdentityRecordV2 {
    uint32_t magic;
    uint16_t storageVersion;
    uint16_t recordSize;
    uint32_t factoryVersion;
    char sn[20];
    uint32_t devEuiHi;
    uint32_t devEuiLo;
    uint8_t devicePrivateKeySize;
    uint8_t devicePrivateKey[32];
    uint64_t manufacturingTimestamp;
    uint32_t identityStatus;
    uint32_t identityCrc;
    uint32_t recordCrc;
};

struct LegacyLoRaWanIdentityRecord {
    uint16_t legacyVersion;
    uint16_t legacySize;
    uint16_t deriveAlgVersion;
    uint16_t reserved;
    uint32_t legacyFlags;
    uint8_t devEui[8];
    uint8_t appEui[8];
    uint8_t appKey[16];
    uint8_t devAddr[4];
    uint8_t nwkSKey[16];
    uint8_t appSKey[16];
    uint8_t uuid1[4];
    uint8_t uuid2[4];
    uint32_t legacyCrc;
};

struct FactoryIdentityRecordV3 {
    uint32_t magic;
    uint16_t storageVersion;
    uint16_t recordSize;
    uint32_t factoryVersion;
    char sn[20];
    uint32_t devEuiHi;
    uint32_t devEuiLo;
    uint8_t devicePrivateKeySize;
    uint8_t devicePrivateKey[32];
    uint8_t reserved[7];
    uint64_t manufacturingTimestamp;
    uint32_t identityStatus;
    uint32_t identityCrc;
    LegacyLoRaWanIdentityRecord legacy;
    uint32_t recordCrc;
};

struct LegacyLoRaWanKeyPage {
    uint8_t devEui[8];
    uint8_t appEui[8];
    uint8_t appKey[16];
    uint8_t devAddr[4];
    uint8_t nwkSKey[16];
    uint8_t appSKey[16];
    uint8_t uuid1[4];
    uint8_t uuid2[4];
    uint8_t reserved[52];
};

struct FactoryIdentityRecordV4 {
    uint32_t magic;
    uint16_t storageVersion;
    uint16_t recordSize;
    uint32_t factoryVersion;
    uint32_t flags;
    uint32_t legacyKeyAddr;
    uint16_t legacyKeySize;
    uint16_t legacyLayoutVersion;
    uint16_t deriveAlgVersion;
    uint16_t reserved0;
    uint32_t legacyKeyCrc;
    uint64_t manufacturingTimestamp;
    uint32_t identityStatus;
    uint8_t reserved[16];
    uint32_t recordCrc;
};
#pragma pack(pop)

static_assert(sizeof(LegacyLoRaWanIdentityRecord) == LEGACY_LORAWAN_IDENTITY_SIZE,
              "LegacyLoRaWanIdentityRecord layout must match bootloader");
static_assert(sizeof(FactoryIdentityRecordV3) == 192, "FactoryIdentityRecordV3 layout must match bootloader");
static_assert(sizeof(LegacyLoRaWanKeyPage) == 128, "LegacyLoRaWanKeyPage layout must match legacy key page");
static_assert(sizeof(FactoryIdentityRecordV4) == 64, "FactoryIdentityRecordV4 layout must match reference marker");

#if defined(DRAGINO_FACTORY_IDENTITY_STM32_STORAGE)
static_assert(sizeof(FactoryIdentityRecordV3) <= FLASH_PAGE_SIZE, "FactoryIdentityRecord must fit in one STM32 flash page");
static_assert(sizeof(FactoryIdentityRecordV4) <= FLASH_PAGE_SIZE, "FactoryIdentityRecordV4 must fit in one STM32 flash page");
#endif

uint32_t crc32Update(uint32_t crc, const void *data, size_t len)
{
    const uint8_t *bytes = static_cast<const uint8_t *>(data);
    for (size_t i = 0; i < len; i++) {
        crc ^= bytes[i];
        for (uint8_t bit = 0; bit < 8; bit++) {
            crc = (crc >> 1) ^ (0xEDB88320UL & (0UL - (crc & 1UL)));
        }
    }
    return crc;
}

uint32_t crc32BufferLocal(const void *data, size_t len)
{
    return crc32Update(0xFFFFFFFFUL, data, len) ^ 0xFFFFFFFFUL;
}

template <typename T> uint32_t crc32AppendValue(uint32_t crc, const T &value)
{
    return crc32Update(crc, &value, sizeof(value));
}

bool isAllZero(const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        if (data[i] != 0) {
            return false;
        }
    }
    return true;
}

bool isAllValue(const uint8_t *data, size_t len, uint8_t value)
{
    for (size_t i = 0; i < len; i++) {
        if (data[i] != value) {
            return false;
        }
    }
    return true;
}

bool isBlankFactoryField(const uint8_t *data, size_t len)
{
    return isAllZero(data, len) || isAllValue(data, len, 0xFF);
}

uint32_t computeIdentityCrc(const temeshtastic_DeviceFactoryIdentity &identity)
{
    uint32_t crc = 0xFFFFFFFFUL;
    crc = crc32AppendValue(crc, identity.factory_version);
    crc = crc32Update(crc, identity.sn, sizeof(identity.sn));
    crc = crc32AppendValue(crc, identity.dev_eui_hi);
    crc = crc32AppendValue(crc, identity.dev_eui_lo);
    crc = crc32AppendValue(crc, identity.device_private_key.size);
    crc = crc32Update(crc, identity.device_private_key.bytes, identity.device_private_key.size);
    crc = crc32AppendValue(crc, identity.legacy_app_key.size);
    crc = crc32Update(crc, identity.legacy_app_key.bytes, identity.legacy_app_key.size);
    crc = crc32AppendValue(crc, identity.manufacturing_timestamp);
    return crc ^ 0xFFFFFFFFUL;
}

void copyLegacyAppKey(temeshtastic_DeviceFactoryIdentity &identity, const uint8_t appKey[16])
{
    identity.legacy_app_key.size = sizeof(identity.legacy_app_key.bytes);
    memcpy(identity.legacy_app_key.bytes, appKey, sizeof(identity.legacy_app_key.bytes));
}

bool normalizeIdentity(const temeshtastic_DeviceFactoryIdentity &input, temeshtastic_DeviceFactoryIdentity &output)
{
    memset(&output, 0, sizeof(output));
    output.factory_version = input.factory_version;
    output.dev_eui_hi = input.dev_eui_hi;
    output.dev_eui_lo = input.dev_eui_lo;
    output.manufacturing_timestamp = input.manufacturing_timestamp;
    output.status = input.status;

    for (size_t i = 0; i < sizeof(output.sn) - 1 && input.sn[i] != '\0'; i++) {
        output.sn[i] = input.sn[i];
    }

    output.device_private_key.size = input.device_private_key.size;
    if (output.device_private_key.size <= sizeof(output.device_private_key.bytes)) {
        memcpy(output.device_private_key.bytes, input.device_private_key.bytes, output.device_private_key.size);
    }

    output.legacy_app_key.size = input.legacy_app_key.size;
    if (output.legacy_app_key.size <= sizeof(output.legacy_app_key.bytes)) {
        memcpy(output.legacy_app_key.bytes, input.legacy_app_key.bytes, output.legacy_app_key.size);
    }

    if (output.dev_eui_hi == 0 && output.dev_eui_lo == 0) {
        LOG_WARN("FactoryIdentity: DevEUI missing");
        return false;
    }
    if (output.device_private_key.size != 32) {
        LOG_WARN("FactoryIdentity: device_private_key size invalid: %u", output.device_private_key.size);
        return false;
    }
    if (isAllZero(output.device_private_key.bytes, 32)) {
        LOG_WARN("FactoryIdentity: device_private_key is blank");
        return false;
    }
    if (output.legacy_app_key.size != sizeof(output.legacy_app_key.bytes)) {
        LOG_WARN("FactoryIdentity: legacy_app_key size invalid: %u", output.legacy_app_key.size);
        return false;
    }
    if (isBlankFactoryField(output.legacy_app_key.bytes, sizeof(output.legacy_app_key.bytes))) {
        LOG_WARN("FactoryIdentity: legacy_app_key is blank");
        return false;
    }

    if (output.status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID &&
        output.status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED) {
        output.status = temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID;
    }

    output.identity_crc = computeIdentityCrc(output);
    return true;
}

uint32_t computeRecordCrcV2(const FactoryIdentityRecordV2 &record)
{
    return crc32BufferLocal(&record, offsetof(FactoryIdentityRecordV2, recordCrc));
}

uint32_t computeLegacyCrc(const LegacyLoRaWanIdentityRecord &record)
{
    return crc32BufferLocal(&record, offsetof(LegacyLoRaWanIdentityRecord, legacyCrc));
}

uint32_t computeRecordCrcV3(const FactoryIdentityRecordV3 &record)
{
    return crc32BufferLocal(&record, offsetof(FactoryIdentityRecordV3, recordCrc));
}

uint32_t computeRecordCrcV4(const FactoryIdentityRecordV4 &record)
{
    return crc32BufferLocal(&record, offsetof(FactoryIdentityRecordV4, recordCrc));
}

uint32_t be32FromBytes(const uint8_t bytes[4])
{
    return ((uint32_t)bytes[0] << 24) |
           ((uint32_t)bytes[1] << 16) |
           ((uint32_t)bytes[2] << 8) |
           (uint32_t)bytes[3];
}

void derivePrivateKeyFromDevEuiAppKey(const uint8_t devEui[8], const uint8_t appKey[16], uint8_t output[32])
{
    SHA256 hash;
    hash.reset();
    hash.update(PRIVATE_KEY_DERIVE_DOMAIN, strlen(PRIVATE_KEY_DERIVE_DOMAIN));
    hash.update(devEui, 8);
    hash.update(appKey, 16);
    hash.finalize(output, 32);
}

void derivePrivateKeyFromLegacy(const LegacyLoRaWanIdentityRecord &legacy, uint8_t output[32])
{
    derivePrivateKeyFromDevEuiAppKey(legacy.devEui, legacy.appKey, output);
}

void recordV2ToIdentity(const FactoryIdentityRecordV2 &record, temeshtastic_DeviceFactoryIdentity &identity)
{
    memset(&identity, 0, sizeof(identity));
    identity.factory_version = record.factoryVersion;
    memcpy(identity.sn, record.sn, sizeof(identity.sn));
    identity.sn[sizeof(identity.sn) - 1] = '\0';
    identity.dev_eui_hi = record.devEuiHi;
    identity.dev_eui_lo = record.devEuiLo;
    identity.device_private_key.size = record.devicePrivateKeySize;
    memcpy(identity.device_private_key.bytes, record.devicePrivateKey, sizeof(record.devicePrivateKey));
    identity.manufacturing_timestamp = record.manufacturingTimestamp;
    identity.status = static_cast<temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus>(record.identityStatus);
    identity.identity_crc = record.identityCrc;
}

void recordV3ToIdentity(const FactoryIdentityRecordV3 &record, temeshtastic_DeviceFactoryIdentity &identity)
{
    memset(&identity, 0, sizeof(identity));
    identity.factory_version = record.factoryVersion;
    memcpy(identity.sn, record.sn, sizeof(identity.sn));
    identity.sn[sizeof(identity.sn) - 1] = '\0';

    identity.dev_eui_hi = record.devEuiHi;
    identity.dev_eui_lo = record.devEuiLo;
    if (identity.dev_eui_hi == 0 && identity.dev_eui_lo == 0) {
        identity.dev_eui_hi = be32FromBytes(record.legacy.devEui);
        identity.dev_eui_lo = be32FromBytes(record.legacy.devEui + 4);
    }

    identity.device_private_key.size = 32;
    derivePrivateKeyFromLegacy(record.legacy, identity.device_private_key.bytes);
    copyLegacyAppKey(identity, record.legacy.appKey);
    identity.manufacturing_timestamp = record.manufacturingTimestamp;
    identity.status = static_cast<temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus>(record.identityStatus);
    if (identity.status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID &&
        identity.status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED) {
        identity.status = temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID;
    }
    identity.identity_crc = computeIdentityCrc(identity);
}

temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus normalizeRecordStatus(
    uint32_t status,
    bool locked)
{
    temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus typedStatus =
        static_cast<temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus>(status);

    if (typedStatus == temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID ||
        typedStatus == temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED) {
        return typedStatus;
    }

    return locked ? temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED
                  : temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID;
}

void legacyKeyPageToIdentity(const LegacyLoRaWanKeyPage &legacy,
                             uint32_t factoryVersion,
                             uint64_t manufacturingTimestamp,
                             temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus status,
                             temeshtastic_DeviceFactoryIdentity &identity)
{
    memset(&identity, 0, sizeof(identity));
    identity.factory_version = factoryVersion;
    identity.dev_eui_hi = be32FromBytes(legacy.devEui);
    identity.dev_eui_lo = be32FromBytes(legacy.devEui + 4);
    identity.device_private_key.size = 32;
    derivePrivateKeyFromDevEuiAppKey(legacy.devEui, legacy.appKey, identity.device_private_key.bytes);
    copyLegacyAppKey(identity, legacy.appKey);
    identity.manufacturing_timestamp = manufacturingTimestamp;
    identity.status = status;
    identity.identity_crc = computeIdentityCrc(identity);
}

void recordV4ToIdentity(const FactoryIdentityRecordV4 &record,
                        const LegacyLoRaWanKeyPage &legacy,
                        temeshtastic_DeviceFactoryIdentity &identity)
{
    const bool locked = (record.flags & FACTORY_IDENTITY_V4_FLAG_LOCKED) != 0;
    legacyKeyPageToIdentity(legacy,
                            record.factoryVersion,
                            record.manufacturingTimestamp,
                            normalizeRecordStatus(record.identityStatus, locked),
                            identity);
}

void setStatusOnly(temeshtastic_DeviceFactoryIdentity &identity,
                   temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus status)
{
    memset(&identity, 0, sizeof(identity));
    identity.status = status;
}

template <typename T> bool isRecordErased(const T &record)
{
    const uint8_t *bytes = reinterpret_cast<const uint8_t *>(&record);
    for (size_t i = 0; i < sizeof(record); i++) {
        if (bytes[i] != 0xFF) {
            return false;
        }
    }
    return true;
}

bool validateV3Record(const FactoryIdentityRecordV3 &record)
{
    if (record.magic != FACTORY_IDENTITY_MAGIC ||
        record.storageVersion != FACTORY_IDENTITY_STORAGE_VERSION_V3 ||
        record.recordSize != sizeof(FactoryIdentityRecordV3)) {
        return false;
    }

    if (record.recordCrc != computeRecordCrcV3(record)) {
        return false;
    }

    if (record.legacy.legacyVersion != LEGACY_LORAWAN_IDENTITY_VERSION ||
        record.legacy.legacySize != sizeof(LegacyLoRaWanIdentityRecord) ||
        record.legacy.deriveAlgVersion != LEGACY_DERIVE_ALG_VERSION_V1) {
        return false;
    }

    if (record.legacy.legacyCrc != computeLegacyCrc(record.legacy)) {
        return false;
    }

    if (isBlankFactoryField(record.legacy.devEui, sizeof(record.legacy.devEui)) ||
        isBlankFactoryField(record.legacy.appKey, sizeof(record.legacy.appKey))) {
        return false;
    }

    return true;
}

bool validateLegacyKeyPage(const LegacyLoRaWanKeyPage &legacy)
{
    return !isBlankFactoryField(legacy.devEui, sizeof(legacy.devEui)) &&
           !isBlankFactoryField(legacy.appKey, sizeof(legacy.appKey));
}

bool validateV4RecordShape(const FactoryIdentityRecordV4 &record)
{
    if (record.magic != FACTORY_IDENTITY_MAGIC ||
        record.storageVersion != FACTORY_IDENTITY_STORAGE_VERSION_V4 ||
        record.recordSize != sizeof(FactoryIdentityRecordV4)) {
        return false;
    }

    if (record.legacyKeyAddr != DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS) {
        return false;
    }

    if (record.legacyKeySize < LEGACY_LORAWAN_KEY_DERIVE_SIZE ||
        record.legacyKeySize > sizeof(LegacyLoRaWanKeyPage)) {
        return false;
    }

    if (record.legacyLayoutVersion != DRAGINO_FACTORY_IDENTITY_LEGACY_LAYOUT_VERSION ||
        record.deriveAlgVersion != DRAGINO_FACTORY_IDENTITY_DERIVE_ALG_VERSION) {
        return false;
    }

    return true;
}

const char *factoryHeaderStateName(const FactoryIdentityHeader &header)
{
    const uint8_t *bytes = reinterpret_cast<const uint8_t *>(&header);
    if (isAllValue(bytes, sizeof(header), 0xFF)) {
        return "ERASED";
    }
    if (isAllZero(bytes, sizeof(header))) {
        return "BLANK_ZERO";
    }
    if (header.magic != FACTORY_IDENTITY_MAGIC) {
        return "MAGIC_MISMATCH";
    }
    if (header.storageVersion != FACTORY_IDENTITY_STORAGE_VERSION_V2 &&
        header.storageVersion != FACTORY_IDENTITY_STORAGE_VERSION_V3 &&
        header.storageVersion != FACTORY_IDENTITY_STORAGE_VERSION_V4) {
        return "UNSUPPORTED_VERSION";
    }
    return "PRESENT";
}

const char *v4RecordShapeStateName(const FactoryIdentityRecordV4 &record)
{
    if (record.magic != FACTORY_IDENTITY_MAGIC) {
        return "MAGIC_MISMATCH";
    }
    if (record.storageVersion != FACTORY_IDENTITY_STORAGE_VERSION_V4) {
        return "VERSION_MISMATCH";
    }
    if (record.recordSize != sizeof(FactoryIdentityRecordV4)) {
        return "SIZE_MISMATCH";
    }
    if (record.legacyKeyAddr != DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS) {
        return "LEGACY_ADDR_MISMATCH";
    }
    if (record.legacyKeySize < LEGACY_LORAWAN_KEY_DERIVE_SIZE ||
        record.legacyKeySize > sizeof(LegacyLoRaWanKeyPage)) {
        return "LEGACY_SIZE_INVALID";
    }
    if (record.legacyLayoutVersion != DRAGINO_FACTORY_IDENTITY_LEGACY_LAYOUT_VERSION) {
        return "LEGACY_LAYOUT_MISMATCH";
    }
    if (record.deriveAlgVersion != DRAGINO_FACTORY_IDENTITY_DERIVE_ALG_VERSION) {
        return "DERIVE_ALG_MISMATCH";
    }
    return "OK";
}

const char *factoryFieldStateName(const uint8_t *data, size_t len)
{
    if (isAllZero(data, len)) {
        return "blank_zero";
    }
    if (isAllValue(data, len, 0xFF)) {
        return "blank_ff";
    }
    return "present";
}

const char *legacyKeyPageStateName(const LegacyLoRaWanKeyPage &legacy)
{
    const uint8_t *bytes = reinterpret_cast<const uint8_t *>(&legacy);
    if (isAllValue(bytes, sizeof(legacy), 0xFF)) {
        return "ERASED";
    }
    if (isAllZero(bytes, sizeof(legacy))) {
        return "BLANK_ZERO";
    }
    if (isBlankFactoryField(legacy.devEui, sizeof(legacy.devEui))) {
        return "DEV_EUI_BLANK";
    }
    if (isBlankFactoryField(legacy.appKey, sizeof(legacy.appKey))) {
        return "APP_KEY_BLANK";
    }
    return "VALID";
}

#if defined(DRAGINO_FACTORY_IDENTITY_STM32_STORAGE)

uint32_t factoryIdentityFlashAddress()
{
#if defined(DRAGINO_FACTORY_IDENTITY_FLASH_ADDRESS)
    return DRAGINO_FACTORY_IDENTITY_FLASH_ADDRESS;
#else
    return FLASH_END_ADDR - FLASH_PAGE_SIZE + 1U;
#endif
}

bool readLegacyKeyPage(uint32_t address, uint16_t size, LegacyLoRaWanKeyPage &legacy)
{
    if (address != DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS ||
        size < LEGACY_LORAWAN_KEY_DERIVE_SIZE ||
        size > sizeof(LegacyLoRaWanKeyPage)) {
        return false;
    }

    memset(&legacy, 0, sizeof(legacy));
    return internalFlash::read(address, &legacy, size);
}

bool eraseFactoryIdentityPage()
{
    const uint32_t address = factoryIdentityFlashAddress();
    if (!internalFlash::erasePage(address)) {
        LOG_WARN("FactoryIdentity: erase failed addr=0x%08x", (unsigned)address);
        return false;
    }

    return true;
}

bool programFactoryIdentityRecord(const FactoryIdentityRecordV4 &record)
{
    const uint32_t address = factoryIdentityFlashAddress();
    static_assert((sizeof(record) % sizeof(uint64_t)) == 0, "FactoryIdentityRecordV4 must be doubleword aligned");

    if (!internalFlash::programDoublewords(address, &record, sizeof(record))) {
        LOG_WARN("FactoryIdentity: program failed addr=0x%08x", (unsigned)address);
        return false;
    }

    return true;
}

bool buildFactoryIdentityRecordV4(const temeshtastic_DeviceFactoryIdentity &identity,
                                  const LegacyLoRaWanKeyPage &legacy,
                                  FactoryIdentityRecordV4 &record)
{
    memset(&record, 0, sizeof(record));
    record.magic = FACTORY_IDENTITY_MAGIC;
    record.storageVersion = FACTORY_IDENTITY_STORAGE_VERSION_V4;
    record.recordSize = sizeof(FactoryIdentityRecordV4);
    record.factoryVersion = identity.factory_version != 0 ? identity.factory_version : FACTORY_IDENTITY_STORAGE_VERSION_V4;
    record.flags = FACTORY_IDENTITY_V4_FLAG_LEGACY_CRC_VALID;
    record.legacyKeyAddr = DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS;
    record.legacyKeySize = DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_SIZE;
    record.legacyLayoutVersion = DRAGINO_FACTORY_IDENTITY_LEGACY_LAYOUT_VERSION;
    record.deriveAlgVersion = DRAGINO_FACTORY_IDENTITY_DERIVE_ALG_VERSION;
    record.legacyKeyCrc = crc32BufferLocal(&legacy, record.legacyKeySize);
    record.manufacturingTimestamp = identity.manufacturing_timestamp;
    record.identityStatus = normalizeRecordStatus(identity.status, false);
    if (record.identityStatus == temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED) {
        record.flags |= FACTORY_IDENTITY_V4_FLAG_LOCKED;
    }
    record.recordCrc = computeRecordCrcV4(record);
    return true;
}

FactoryIdentityManager::ReadStatus readLegacyAutodetect(temeshtastic_DeviceFactoryIdentity &identity)
{
#if DRAGINO_FACTORY_IDENTITY_LEGACY_AUTODETECT
    LegacyLoRaWanKeyPage legacy = {};
    if (!readLegacyKeyPage(DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS,
                           DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_SIZE,
                           legacy) ||
        !validateLegacyKeyPage(legacy)) {
        setStatusOnly(identity, temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_EMPTY);
        return FactoryIdentityManager::ReadStatus::EMPTY;
    }

    legacyKeyPageToIdentity(legacy,
                            FACTORY_IDENTITY_STORAGE_VERSION_V4,
                            0,
                            temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID,
                            identity);
    LOG_INFO("FactoryIdentity: legacy identity loaded addr=0x%08x dev_eui=%02x%02x%02x%02x%02x%02x%02x%02x",
             (unsigned)DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS,
             (unsigned)legacy.devEui[0], (unsigned)legacy.devEui[1], (unsigned)legacy.devEui[2], (unsigned)legacy.devEui[3],
             (unsigned)legacy.devEui[4], (unsigned)legacy.devEui[5], (unsigned)legacy.devEui[6], (unsigned)legacy.devEui[7]);
    return FactoryIdentityManager::ReadStatus::OK;
#else
    setStatusOnly(identity, temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_EMPTY);
    return FactoryIdentityManager::ReadStatus::EMPTY;
#endif
}

void setStatusFromReadStatus(temeshtastic_DeviceFactoryIdentity &identity,
                             FactoryIdentityManager::ReadStatus status)
{
    switch (status) {
    case FactoryIdentityManager::ReadStatus::EMPTY:
        setStatusOnly(identity, temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_EMPTY);
        break;
    case FactoryIdentityManager::ReadStatus::CRC_ERROR:
        setStatusOnly(identity, temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_CRC_ERROR);
        break;
    case FactoryIdentityManager::ReadStatus::INVALID_FORMAT:
        setStatusOnly(identity, temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_INVALID_FORMAT);
        break;
    default:
        setStatusOnly(identity, temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_EMPTY);
        break;
    }
}

FactoryIdentityManager::ReadStatus readLegacyOrStatus(temeshtastic_DeviceFactoryIdentity &identity,
                                                      FactoryIdentityManager::ReadStatus statusIfMissing,
                                                      const char *markerReason)
{
    temeshtastic_DeviceFactoryIdentity legacyIdentity = temeshtastic_DeviceFactoryIdentity_init_zero;
    FactoryIdentityManager::ReadStatus legacyStatus = readLegacyAutodetect(legacyIdentity);
    if (legacyStatus == FactoryIdentityManager::ReadStatus::OK) {
        identity = legacyIdentity;
        LOG_INFO("FactoryIdentity: using legacy identity at 0x%08x, marker=%s",
                 (unsigned)DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS,
                 markerReason ? markerReason : "ignored");
        return FactoryIdentityManager::ReadStatus::OK;
    }

    setStatusFromReadStatus(identity, statusIfMissing);
    return statusIfMissing;
}

#endif

} // namespace

FactoryIdentityManager &FactoryIdentityManager::instance()
{
    static FactoryIdentityManager manager;
    return manager;
}

FactoryIdentityManager::ReadStatus FactoryIdentityManager::read(temeshtastic_DeviceFactoryIdentity &identity) const
{
#if defined(DRAGINO_FACTORY_IDENTITY_STM32_STORAGE)
    FactoryIdentityManager::ReadStatus legacyStatus = readLegacyAutodetect(identity);
    if (legacyStatus == ReadStatus::OK) {
        return ReadStatus::OK;
    }

#if !DRAGINO_FACTORY_IDENTITY_MARKER_READ_COMPAT
    return legacyStatus;
#else
    FactoryIdentityHeader header = {};
    if (!internalFlash::read(factoryIdentityFlashAddress(), &header, sizeof(header))) {
        return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "marker_read_failed");
    }

    if (isRecordErased(header)) {
        return readLegacyOrStatus(identity, ReadStatus::EMPTY, "marker_erased");
    }

    if (header.magic != FACTORY_IDENTITY_MAGIC) {
        return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "marker_magic_mismatch");
    }

    if (header.storageVersion == FACTORY_IDENTITY_STORAGE_VERSION_V2) {
        FactoryIdentityRecordV2 record = {};
        if (!internalFlash::read(factoryIdentityFlashAddress(), &record, sizeof(record))) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v2_read_failed");
        }

        if (record.recordSize != sizeof(FactoryIdentityRecordV2)) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v2_size_mismatch");
        }
        if (record.recordCrc != computeRecordCrcV2(record)) {
            return readLegacyOrStatus(identity, ReadStatus::CRC_ERROR, "v2_crc_error");
        }

        recordV2ToIdentity(record, identity);
        if (!validate(identity)) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v2_identity_invalid");
        }
        return ReadStatus::OK;
    }

    if (header.storageVersion == FACTORY_IDENTITY_STORAGE_VERSION_V3) {
        FactoryIdentityRecordV3 record = {};
        if (!internalFlash::read(factoryIdentityFlashAddress(), &record, sizeof(record))) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v3_read_failed");
        }

        if (!validateV3Record(record)) {
            return readLegacyOrStatus(identity, ReadStatus::CRC_ERROR, "v3_record_invalid");
        }

        recordV3ToIdentity(record, identity);
        if (!validate(identity)) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v3_identity_invalid");
        }
        return ReadStatus::OK;
    }

    if (header.storageVersion == FACTORY_IDENTITY_STORAGE_VERSION_V4) {
        FactoryIdentityRecordV4 record = {};
        if (!internalFlash::read(factoryIdentityFlashAddress(), &record, sizeof(record))) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v4_read_failed");
        }

        if (!validateV4RecordShape(record)) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v4_shape_invalid");
        }
        if (record.recordCrc != computeRecordCrcV4(record)) {
            return readLegacyOrStatus(identity, ReadStatus::CRC_ERROR, "v4_crc_error");
        }

        LegacyLoRaWanKeyPage legacy = {};
        if (!readLegacyKeyPage(record.legacyKeyAddr, record.legacyKeySize, legacy) ||
            !validateLegacyKeyPage(legacy)) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v4_legacy_invalid");
        }

        if ((record.flags & FACTORY_IDENTITY_V4_FLAG_LEGACY_CRC_VALID) != 0 &&
            record.legacyKeyCrc != crc32BufferLocal(&legacy, record.legacyKeySize)) {
            return readLegacyOrStatus(identity, ReadStatus::CRC_ERROR, "v4_legacy_crc_error");
        }

        recordV4ToIdentity(record, legacy, identity);
        if (!validate(identity)) {
            return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "v4_identity_invalid");
        }
        return ReadStatus::OK;
    }

    return readLegacyOrStatus(identity, ReadStatus::INVALID_FORMAT, "marker_version_unsupported");
#endif
#else
    setStatusOnly(identity, temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_EMPTY);
    return ReadStatus::UNSUPPORTED_PLATFORM;
#endif
}

bool FactoryIdentityManager::load(temeshtastic_DeviceFactoryIdentity &identity) const
{
    return read(identity) == ReadStatus::OK;
}

bool FactoryIdentityManager::normalize(temeshtastic_DeviceFactoryIdentity &identity) const
{
    temeshtastic_DeviceFactoryIdentity normalized = temeshtastic_DeviceFactoryIdentity_init_zero;
    if (!normalizeIdentity(identity, normalized)) {
        return false;
    }
    identity = normalized;
    return true;
}

bool FactoryIdentityManager::validate(const temeshtastic_DeviceFactoryIdentity &identity) const
{
    if (identity.status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_VALID &&
        identity.status != temeshtastic_DeviceFactoryIdentity_FactoryIdentityStatus_FACTORY_IDENTITY_LOCKED) {
        return false;
    }
    if (identity.sn[sizeof(identity.sn) - 1] != '\0') {
        return false;
    }
    if (identity.dev_eui_hi == 0 && identity.dev_eui_lo == 0) {
        return false;
    }
    if (identity.device_private_key.size != 32 || isAllZero(identity.device_private_key.bytes, 32)) {
        return false;
    }
    if (identity.legacy_app_key.size != sizeof(identity.legacy_app_key.bytes) ||
        isBlankFactoryField(identity.legacy_app_key.bytes, sizeof(identity.legacy_app_key.bytes))) {
        return false;
    }
    return identity.identity_crc == computeIdentityCrc(identity);
}

const char *FactoryIdentityManager::statusName(ReadStatus status) const
{
    switch (status) {
    case ReadStatus::OK:
        return "OK";
    case ReadStatus::EMPTY:
        return "EMPTY";
    case ReadStatus::CRC_ERROR:
        return "CRC_ERROR";
    case ReadStatus::INVALID_FORMAT:
        return "INVALID_FORMAT";
    case ReadStatus::UNSUPPORTED_PLATFORM:
        return "UNSUPPORTED_PLATFORM";
    case ReadStatus::WRITE_FAILED:
        return "WRITE_FAILED";
    }
    return "UNKNOWN";
}

void FactoryIdentityManager::logStorageDiagnostics(ReadStatus status) const
{
#if defined(DRAGINO_FACTORY_IDENTITY_STM32_STORAGE)
    const uint32_t markerAddress = factoryIdentityFlashAddress();
    FactoryIdentityHeader header = {};
    if (!internalFlash::read(markerAddress, &header, sizeof(header))) {
        LOG_WARN("FactoryIdentity: marker read failed addr=0x%08x", (unsigned)markerAddress);
    }

    LOG_INFO("FactoryIdentity: marker addr=0x%08x read_status=%s state=%s magic=0x%08x version=%u size=%u",
             (unsigned)markerAddress,
             statusName(status),
             factoryHeaderStateName(header),
             (unsigned)header.magic,
             (unsigned)header.storageVersion,
             (unsigned)header.recordSize);

    if (header.magic == FACTORY_IDENTITY_MAGIC &&
        header.storageVersion == FACTORY_IDENTITY_STORAGE_VERSION_V4) {
        FactoryIdentityRecordV4 record = {};
        if (!internalFlash::read(markerAddress, &record, sizeof(record))) {
            LOG_WARN("FactoryIdentity: marker v4 read failed addr=0x%08x", (unsigned)markerAddress);
            return;
        }

        const char *shapeState = v4RecordShapeStateName(record);
        const bool shapeOk = strcmp(shapeState, "OK") == 0;
        const uint32_t computedRecordCrc = computeRecordCrcV4(record);
        LOG_INFO("FactoryIdentity: marker v4 shape=%s record_crc=%s stored=0x%08x computed=0x%08x flags=0x%08x",
                 shapeState,
                 shapeOk && record.recordCrc == computedRecordCrc ? "OK" : "BAD",
                 (unsigned)record.recordCrc,
                 (unsigned)computedRecordCrc,
                 (unsigned)record.flags);
        LOG_INFO("FactoryIdentity: marker v4 legacy_ref addr=0x%08x size=%u layout=%u derive_alg=%u legacy_crc=0x%08x",
                 (unsigned)record.legacyKeyAddr,
                 (unsigned)record.legacyKeySize,
                 (unsigned)record.legacyLayoutVersion,
                 (unsigned)record.deriveAlgVersion,
                 (unsigned)record.legacyKeyCrc);
    }

    LegacyLoRaWanKeyPage legacy = {};
    const bool legacyRead = readLegacyKeyPage(DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS,
                                              DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_SIZE,
                                              legacy);
    const bool legacyValid = legacyRead && validateLegacyKeyPage(legacy);

    LOG_INFO("FactoryIdentity: legacy addr=0x%08x size=%u read=%s state=%s valid=%u",
             (unsigned)DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS,
             (unsigned)DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_SIZE,
             legacyRead ? "OK" : "FAILED",
             legacyRead ? legacyKeyPageStateName(legacy) : "UNREADABLE",
             legacyValid ? 1U : 0U);

    if (legacyRead) {
        LOG_INFO("FactoryIdentity: legacy dev_eui=%02x%02x%02x%02x%02x%02x%02x%02x app_eui=%02x%02x%02x%02x%02x%02x%02x%02x dev_addr=%02x%02x%02x%02x",
                 (unsigned)legacy.devEui[0], (unsigned)legacy.devEui[1], (unsigned)legacy.devEui[2], (unsigned)legacy.devEui[3],
                 (unsigned)legacy.devEui[4], (unsigned)legacy.devEui[5], (unsigned)legacy.devEui[6], (unsigned)legacy.devEui[7],
                 (unsigned)legacy.appEui[0], (unsigned)legacy.appEui[1], (unsigned)legacy.appEui[2], (unsigned)legacy.appEui[3],
                 (unsigned)legacy.appEui[4], (unsigned)legacy.appEui[5], (unsigned)legacy.appEui[6], (unsigned)legacy.appEui[7],
                 (unsigned)legacy.devAddr[0], (unsigned)legacy.devAddr[1], (unsigned)legacy.devAddr[2], (unsigned)legacy.devAddr[3]);
        LOG_INFO("FactoryIdentity: legacy field_state app_key=%s nwkskey=%s appskey=%s uuid1=%s uuid2=%s",
                 factoryFieldStateName(legacy.appKey, sizeof(legacy.appKey)),
                 factoryFieldStateName(legacy.nwkSKey, sizeof(legacy.nwkSKey)),
                 factoryFieldStateName(legacy.appSKey, sizeof(legacy.appSKey)),
                 factoryFieldStateName(legacy.uuid1, sizeof(legacy.uuid1)),
                 factoryFieldStateName(legacy.uuid2, sizeof(legacy.uuid2)));
    }
#else
    LOG_INFO("FactoryIdentity: storage diagnostics unavailable, read_status=%s", statusName(status));
#endif
}

bool FactoryIdentityManager::write(const temeshtastic_DeviceFactoryIdentity &identity)
{
#if defined(DRAGINO_FACTORY_IDENTITY_STM32_STORAGE) && defined(DRAGINO_FACTORY_FIRMWARE) && \
    DRAGINO_FACTORY_IDENTITY_MARKER_WRITE_ENABLE
    LegacyLoRaWanKeyPage legacy = {};
    if (!readLegacyKeyPage(DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS,
                           DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_SIZE,
                           legacy) ||
        !validateLegacyKeyPage(legacy)) {
        LOG_WARN("FactoryIdentity: legacy key page invalid, refuse v4 marker write");
        return false;
    }

    FactoryIdentityRecordV4 record = {};
    buildFactoryIdentityRecordV4(identity, legacy, record);

    if (!eraseFactoryIdentityPage()) {
        return false;
    }

    if (!programFactoryIdentityRecord(record)) {
        LOG_WARN("FactoryIdentity: v4 marker write verify failed");
        return false;
    }

    LOG_INFO("FactoryIdentity: v4 marker written at 0x%08x, legacy=0x%08x",
             (unsigned)factoryIdentityFlashAddress(),
             (unsigned)DRAGINO_FACTORY_IDENTITY_LEGACY_KEY_ADDRESS);
    return true;
#else
    (void)identity;
    LOG_WARN("FactoryIdentity: internal flash marker write disabled");
    return false;
#endif
}

FactoryIdentityManager &factoryIdentity = FactoryIdentityManager::instance();

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE)
