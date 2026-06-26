#pragma once

#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "Observer.h"
#include "concurrency/OSThread.h"

#include <stdint.h>

#ifndef DRAGINO_SHT3X_ENABLE
#define DRAGINO_SHT3X_ENABLE 0
#endif

#if DRAGINO_SHT3X_ENABLE && !defined(DRAGINO_SENSOR_PROFILE_SHT3X)
#error "DRAGINO_SHT3X_ENABLE requires DRAGINO_SENSOR_PROFILE_SHT3X"
#endif

#if DRAGINO_SHT3X_ENABLE && MESHTASTIC_EXCLUDE_I2C
#error "DRAGINO_SHT3X_ENABLE requires MESHTASTIC_EXCLUDE_I2C=0"
#endif

#if DRAGINO_SHT3X_ENABLE && (!defined(I2C_SDA) || !defined(I2C_SCL))
#error "DRAGINO_SHT3X_ENABLE requires I2C_SDA and I2C_SCL"
#endif

#if DRAGINO_SHT3X_ENABLE && !defined(EXTERNAL_SENSOR_CONTROL_PIN)
#error "DRAGINO_SHT3X_ENABLE requires EXTERNAL_SENSOR_CONTROL_PIN"
#endif

#ifndef DRAGINO_SHT3X_SAMPLE_INTERVAL_MS
#define DRAGINO_SHT3X_SAMPLE_INTERVAL_MS 200UL
#endif

#ifndef DRAGINO_SHT3X_FILTER_WINDOW_MS
#define DRAGINO_SHT3X_FILTER_WINDOW_MS 10000UL
#endif

#ifndef DRAGINO_SHT3X_FILTER_POOL_SIZE
#define DRAGINO_SHT3X_FILTER_POOL_SIZE 20
#endif

#ifndef DRAGINO_SHT3X_REQUIRE_FULL_POOL
#define DRAGINO_SHT3X_REQUIRE_FULL_POOL 1
#endif

#ifndef DRAGINO_SHT3X_STALE_READING_MS
#define DRAGINO_SHT3X_STALE_READING_MS 2000UL
#endif

#ifndef DRAGINO_SHT3X_VALIDATE_ENABLE
#define DRAGINO_SHT3X_VALIDATE_ENABLE 1
#endif

#ifndef DRAGINO_SHT3X_MIN_TEMP_CX10
#define DRAGINO_SHT3X_MIN_TEMP_CX10 (-400)
#endif

#ifndef DRAGINO_SHT3X_MAX_TEMP_CX10
#define DRAGINO_SHT3X_MAX_TEMP_CX10 1250
#endif

#ifndef DRAGINO_SHT3X_MIN_HUM_CX10
#define DRAGINO_SHT3X_MIN_HUM_CX10 0
#endif

#ifndef DRAGINO_SHT3X_MAX_HUM_CX10
#define DRAGINO_SHT3X_MAX_HUM_CX10 1000
#endif

#ifndef DRAGINO_SHT3X_MAX_TEMP_JUMP_CX10
#define DRAGINO_SHT3X_MAX_TEMP_JUMP_CX10 300
#endif

#ifndef DRAGINO_SHT3X_MAX_HUM_JUMP_CX10
#define DRAGINO_SHT3X_MAX_HUM_JUMP_CX10 200
#endif

#ifndef DRAGINO_SHT3X_SUSPICIOUS_LOW_HUM_CX10
#define DRAGINO_SHT3X_SUSPICIOUS_LOW_HUM_CX10 200
#endif

#ifndef DRAGINO_SHT3X_ANOMALY_RESET_WAIT_MS
#define DRAGINO_SHT3X_ANOMALY_RESET_WAIT_MS 50UL
#endif

#if DRAGINO_SHT3X_FILTER_POOL_SIZE < 1
#error "DRAGINO_SHT3X_FILTER_POOL_SIZE must be at least 1"
#endif

namespace dragino {

struct DraginoSHT3xReading {
    int16_t tempCx10 = 0;
    uint16_t humCx10 = 0;
    uint8_t address = 0;
};

class DraginoSHT3xSensor : private concurrency::OSThread
{
  public:
    DraginoSHT3xSensor();

    bool getFilteredReading(DraginoSHT3xReading &reading) const;
    bool hasStableReading() const;
    void stopSampling();

  protected:
    int32_t runOnce() override;

  private:
    struct TimedReading {
        DraginoSHT3xReading reading = {};
        uint32_t sampleMs = 0;
        bool valid = false;
    };

    bool startSampling(uint32_t nowMs);
    bool sampleOnce(uint32_t nowMs);
    bool readValidatedSensor(DraginoSHT3xReading &reading, uint32_t nowMs);
    bool isHardInvalidReading(const DraginoSHT3xReading &reading) const;
    bool isSuspiciousReading(const DraginoSHT3xReading &reading) const;
    bool hasJumpSuspicion(const DraginoSHT3xReading &reading) const;
    bool hasHumidityEdgeSuspicion(const DraginoSHT3xReading &reading) const;
    bool hasLowHumiditySuspicion(const DraginoSHT3xReading &reading) const;
    bool hasOnlyAcceptableLowHumiditySuspicion(const DraginoSHT3xReading &reading) const;
    void acceptReading(const DraginoSHT3xReading &reading);
    void resetPool();
    void addReading(const DraginoSHT3xReading &reading, uint32_t nowMs);
    void updateFilteredReading(uint32_t nowMs);
    void printSample(const DraginoSHT3xReading &raw, const DraginoSHT3xReading &filtered) const;
    void printSampleFailed() const;
    void prepareForDeepSleep();
    int notifyDeepSleepCb(void *unused = nullptr);

    TimedReading pool_[DRAGINO_SHT3X_FILTER_POOL_SIZE] = {};
    uint8_t poolCount_ = 0;
    uint8_t poolNext_ = 0;
    uint32_t lastSampleMs_ = 0;
    uint32_t lastValidSampleMs_ = 0;
    DraginoSHT3xReading filtered_ = {};
    bool hasFiltered_ = false;
    bool sampling_ = false;
    bool hasAcceptedReading_ = false;
    DraginoSHT3xReading lastAcceptedReading_ = {};
    uint32_t invalidSampleCount_ = 0;
    uint32_t resetRecoverCount_ = 0;

    CallbackObserver<DraginoSHT3xSensor, void *> deepSleepObserver =
        CallbackObserver<DraginoSHT3xSensor, void *>(this, &DraginoSHT3xSensor::notifyDeepSleepCb);
};

extern DraginoSHT3xSensor *draginoSHT3xSensor;

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
