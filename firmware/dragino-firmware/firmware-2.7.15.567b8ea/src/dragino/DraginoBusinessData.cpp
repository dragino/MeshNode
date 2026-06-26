#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "DraginoBusinessData.h"
#include "DraginoBusinessCommon.h"
#include "PrivateConfig.h"
#include "DraginoDefaultConfig.h"
#include "DraginoSender.h"
#include "DraginoSHT3xSensor.h"
#include "MeshTypes.h"
#include "PowerStatus.h"
#include "RTC.h"
#include "power.h"

namespace dragino {

DraginoBusinessData draginoBusinessData;

namespace {

bool sensorBusinessDataEnabled()
{
#if DRAGINO_SENSOR_BUSINESS_DATA_ENABLE
    return true;
#else
    return false;
#endif
}

uint16_t readBatteryMv()
{
    if (::power) {
        ::power->readPowerStatus();
    }

    if (!::powerStatus || !::powerStatus->getHasBattery()) {
        return 0;
    }

    const int batteryMv = ::powerStatus->getBatteryVoltageMv();
    if (batteryMv <= 0 || batteryMv > 65535) {
        return 0;
    }

    return (uint16_t)batteryMv;
}

bool buildSensorPayload(DraginoBusinessSensorPayloadV1 &payload, bool allowInvalidSensor)
{
    payload = {};
    payload.version = 1;
    payload.msgType = DRAGINO_BUSINESS_MSG_SENSOR_DATA;
    payload.utcTime = getValidTime(RTCQualityDevice);
    payload.flags = 0;
    if (payload.utcTime > 0) {
        payload.flags |= DRAGINO_SENSOR_HAS_UTC_TIME;
    }

    const uint16_t batteryMv = readBatteryMv();
    if (batteryMv > 0) {
        payload.flags |= DRAGINO_SENSOR_HAS_BATTERY_MV;
        payload.batteryMv = batteryMv;
    } else {
        LOG_WARN("BusinessData: battery voltage unavailable, send without batteryMv");
    }

#if DRAGINO_SHT3X_ENABLE
    DraginoSHT3xReading sht3xReading;
    if (draginoSHT3xSensor && draginoSHT3xSensor->getFilteredReading(sht3xReading)) {
        payload.flags |= DRAGINO_SENSOR_HAS_TEMP_CX10 | DRAGINO_SENSOR_HAS_HUM_CX10;
        payload.tempCx10 = sht3xReading.tempCx10;
        payload.humCx10 = sht3xReading.humCx10;
    } else if (allowInvalidSensor) {
        payload.tempCx10 = DRAGINO_SENSOR_INVALID_TEMP_CX10;
        payload.humCx10 = DRAGINO_SENSOR_INVALID_HUM_CX10;
        LOG_WARN("BusinessData: SHT3x invalid after timeout, send invalid sensor payload");
    } else {
        LOG_INFO("BusinessData: SHT3x stable reading not ready, defer send");
        return false;
    }
#endif

    return true;
}

bool queueSensorPayload(const DraginoBusinessSensorPayloadV1 &payload, const SendOptions &opts, const char *mode)
{
    bool ok = sender.send(reinterpret_cast<const uint8_t *>(&payload), sizeof(payload), opts);
    if (ok) {
        LOG_INFO("BusinessData: queued sensor utc=%lu mode=%s to 0x%08x channel=%u, %u bytes",
                 (unsigned long)payload.utcTime,
                 mode,
                 (unsigned)opts.to,
                 (unsigned)opts.channel,
                 (unsigned)sizeof(payload));
    } else {
        LOG_WARN("BusinessData: failed to queue sensor utc=%lu mode=%s to 0x%08x channel=%u",
                 (unsigned long)payload.utcTime,
                 mode,
                 (unsigned)opts.to,
                 (unsigned)opts.channel);
    }
    return ok;
}

} // namespace

bool DraginoBusinessData::isSensorBusinessDataEnabled() const
{
    return sensorBusinessDataEnabled();
}

bool DraginoBusinessData::isSensorDataReady() const
{
    if (!sensorBusinessDataEnabled()) {
        return true;
    }

#if DRAGINO_SHT3X_ENABLE
    return draginoSHT3xSensor && draginoSHT3xSensor->hasStableReading();
#else
    return true;
#endif
}

uint32_t DraginoBusinessData::getGatewayNodeId() const
{
    return privateConfig.getPrimaryTrustedGateway();
}

bool DraginoBusinessData::sendTestSensorData(bool allowInvalidSensor)
{
    if (!sensorBusinessDataEnabled()) {
        LOG_INFO("BusinessData: sensor business data disabled, skip send");
        return false;
    }

    if (!privateConfig.isReadyForPrivateConfig()) {
        LOG_WARN("BusinessData: private network not ready, skip send");
        return false;
    }

    const auto &networkConfig = privateConfig.getNetworkConfigData();
    const bool singleGateway = networkConfig.is_single_gateway;
    const uint32_t gateway = getGatewayNodeId();
    if (singleGateway && gateway == 0) {
        LOG_WARN("BusinessData: no gateway node id, skip send");
        return false;
    }

    DraginoBusinessSensorPayloadV1 payload;
    if (!buildSensorPayload(payload, allowInvalidSensor)) {
        return false;
    }

    SendOptions opts;
    opts.to = singleGateway ? gateway : NODENUM_BROADCAST;
    if (!singleGateway) {
        opts.channel = DRAGINO_CHANNEL_PRIVATE_FUNCTION;
    }
    opts.hopLimit = 3;
    opts.wantAck = false;
    opts.wantResponse = false;
    opts.portnum = DRAGINO_BUSINESS_DATA_PORTNUM;
    opts.priority = meshtastic_MeshPacket_Priority_RELIABLE;

    return queueSensorPayload(payload, opts, singleGateway ? "single" : "multi");
}

bool DraginoBusinessData::sendPreEnrollmentSensorData(bool allowInvalidSensor)
{
    if (!sensorBusinessDataEnabled()) {
        LOG_INFO("BusinessData: sensor business data disabled, skip pre-enrollment send");
        return false;
    }

    if (privateConfig.isReadyForPrivateConfig()) {
        return sendTestSensorData(allowInvalidSensor);
    }
    if (privateConfig.isEnrolled()) {
        LOG_WARN("BusinessData: enrolled but private network not ready, skip pre-enrollment send");
        return false;
    }

    DraginoBusinessSensorPayloadV1 payload;
    if (!buildSensorPayload(payload, allowInvalidSensor)) {
        return false;
    }

    SendOptions opts;
    opts.to = NODENUM_BROADCAST;
    opts.channel = DRAGINO_CHANNEL_PRIMARY;
    opts.hopLimit = 3;
    opts.wantAck = false;
    opts.wantResponse = false;
    opts.portnum = DRAGINO_BUSINESS_DATA_PORTNUM;
    opts.priority = meshtastic_MeshPacket_Priority_RELIABLE;

    return queueSensorPayload(payload, opts, "pre-enrollment");
}

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
