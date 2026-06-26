#pragma once

#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include <stdint.h>

#ifndef DRAGINO_SHT3X_ENABLE
#define DRAGINO_SHT3X_ENABLE 0
#endif

#ifndef DRAGINO_SENSOR_BUSINESS_DATA_ENABLE
#define DRAGINO_SENSOR_BUSINESS_DATA_ENABLE DRAGINO_SHT3X_ENABLE
#endif

#ifndef DRAGINO_SENSOR_INVALID_TEMP_CX10
#define DRAGINO_SENSOR_INVALID_TEMP_CX10 32767
#endif

#ifndef DRAGINO_SENSOR_INVALID_HUM_CX10
#define DRAGINO_SENSOR_INVALID_HUM_CX10 65535U
#endif

namespace dragino {

enum DraginoBusinessMessageType : uint8_t {
    DRAGINO_BUSINESS_MSG_SENSOR_DATA = 1,
};

enum DraginoBusinessSensorFlags : uint16_t {
    DRAGINO_SENSOR_HAS_UTC_TIME = 0x0001,
    DRAGINO_SENSOR_HAS_BATTERY_MV = 0x0002,
    DRAGINO_SENSOR_HAS_TEMP_CX10 = 0x0004,
    DRAGINO_SENSOR_HAS_HUM_CX10 = 0x0008,
};

struct __attribute__((packed)) DraginoBusinessSensorPayloadV1 {
    uint8_t version;
    uint8_t msgType;
    uint16_t flags;
    uint32_t utcTime;
    uint16_t batteryMv;
    int16_t tempCx10;
    uint16_t humCx10;
};

static_assert(sizeof(DraginoBusinessSensorPayloadV1) == 14, "Unexpected DraginoBusinessSensorPayloadV1 size");

class DraginoBusinessData
{
  public:
    bool isSensorBusinessDataEnabled() const;
    bool isSensorDataReady() const;
    bool sendTestSensorData(bool allowInvalidSensor = false);
    bool sendPreEnrollmentSensorData(bool allowInvalidSensor = false);

  private:
    uint32_t getGatewayNodeId() const;
};

extern DraginoBusinessData draginoBusinessData;

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
