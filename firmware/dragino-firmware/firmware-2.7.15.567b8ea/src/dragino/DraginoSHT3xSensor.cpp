#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "DraginoSHT3xSensor.h"

namespace dragino {
DraginoSHT3xSensor *draginoSHT3xSensor = nullptr;
} // namespace dragino

#if DRAGINO_SHT3X_ENABLE

#include "DraginoHardware.h"
#include "sleep.h"

#include <Arduino.h>
#include <Wire.h>

#ifndef DRAGINO_SLEEP_DEBUG_TRACE
#define DRAGINO_SLEEP_DEBUG_TRACE 0
#endif

#ifndef DRAGINO_SHT3X_I2C_RELEASE_DELAY_MS
#define DRAGINO_SHT3X_I2C_RELEASE_DELAY_MS 5UL
#endif

#ifndef DRAGINO_SHT3X_POWER_OFF_SETTLE_MS
#define DRAGINO_SHT3X_POWER_OFF_SETTLE_MS 20UL
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

#ifndef DRAGINO_SHT3X_ADDR_PRIMARY
#define DRAGINO_SHT3X_ADDR_PRIMARY 0x44
#endif

#ifndef DRAGINO_SHT3X_ADDR_ALT
#define DRAGINO_SHT3X_ADDR_ALT 0x45
#endif

#ifndef DRAGINO_SHT3X_I2C_CLOCK_HZ
#define DRAGINO_SHT3X_I2C_CLOCK_HZ 100000
#endif

#ifndef DRAGINO_SHT3X_POWER_STABILIZE_MS
#define DRAGINO_SHT3X_POWER_STABILIZE_MS 20
#endif

#ifndef DRAGINO_SHT3X_MEASURE_WAIT_MS
#define DRAGINO_SHT3X_MEASURE_WAIT_MS 20
#endif

#ifndef DRAGINO_SHT3X_READ_RETRIES
#define DRAGINO_SHT3X_READ_RETRIES 3
#endif

#ifndef DRAGINO_SHT3X_SOFT_RESET_WAIT_MS
#define DRAGINO_SHT3X_SOFT_RESET_WAIT_MS 10
#endif

#ifndef DRAGINO_SHT3X_SERIAL_PRINT
#define DRAGINO_SHT3X_SERIAL_PRINT 0
#endif

namespace {

constexpr uint16_t kMeasureHighRepeatabilityNoClockStretch = 0x2400;
constexpr uint16_t kSoftReset = 0x30A2;
constexpr uint8_t kMeasurementBytes = 6;
constexpr uint8_t kCrcInit = 0xFF;
constexpr uint8_t kCrcPolynomial = 0x31;

enum class ReadStatus : uint8_t {
    Ok,
    NoAck,
    ShortRead,
    CrcFailed,
};

const char *statusName(ReadStatus status)
{
    switch (status) {
    case ReadStatus::Ok:
        return "ok";
    case ReadStatus::NoAck:
        return "no_ack";
    case ReadStatus::ShortRead:
        return "short_read";
    case ReadStatus::CrcFailed:
        return "crc";
    }
    return "unknown";
}

void sensorPowerOn()
{
    if (dragino::draginoHardware) {
        dragino::draginoHardware->sensorPowerOn();
        return;
    }

#ifdef EXTERNAL_SENSOR_CONTROL_PIN
    pinMode(EXTERNAL_SENSOR_CONTROL_PIN, OUTPUT);
    digitalWrite(EXTERNAL_SENSOR_CONTROL_PIN, HIGH);
    LOG_WARN("SHT3x: DraginoHardware unavailable, enabled sensor power directly");
#else
    LOG_WARN("SHT3x: no sensor power control pin");
#endif
}

void sensorPowerOff()
{
    if (dragino::draginoHardware) {
        dragino::draginoHardware->sensorPowerOff();
        return;
    }

#ifdef EXTERNAL_SENSOR_CONTROL_PIN
    // PA0 is POWER_5V on this board; do not pull it low during sleep shutdown.
#endif
}

uint8_t calculateCrc(const uint8_t *data, uint8_t length)
{
    uint8_t crc = kCrcInit;
    for (uint8_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; bit++) {
            if (crc & 0x80) {
                crc = (uint8_t)((crc << 1) ^ kCrcPolynomial);
            } else {
                crc = (uint8_t)(crc << 1);
            }
        }
    }
    return crc;
}

bool crcMatches(const uint8_t *data, uint8_t expected)
{
    return calculateCrc(data, 2) == expected;
}

bool writeCommand(uint8_t address, uint16_t command)
{
    Wire.beginTransmission(address);
    Wire.write((uint8_t)(command >> 8));
    Wire.write((uint8_t)(command & 0xFF));
    return Wire.endTransmission() == 0;
}

ReadStatus readMeasurementOnce(uint8_t address, dragino::DraginoSHT3xReading &reading)
{
    if (!writeCommand(address, kMeasureHighRepeatabilityNoClockStretch)) {
        return ReadStatus::NoAck;
    }

    delay(DRAGINO_SHT3X_MEASURE_WAIT_MS);

    uint8_t data[kMeasurementBytes] = {};
    Wire.requestFrom(address, kMeasurementBytes);

    uint8_t count = 0;
    while (Wire.available() && count < kMeasurementBytes) {
        data[count++] = (uint8_t)Wire.read();
    }
    while (Wire.available()) {
        (void)Wire.read();
    }

    if (count != kMeasurementBytes) {
        return ReadStatus::ShortRead;
    }

    if (!crcMatches(&data[0], data[2]) || !crcMatches(&data[3], data[5])) {
        return ReadStatus::CrcFailed;
    }

    const uint16_t rawTemp = ((uint16_t)data[0] << 8) | data[1];
    const uint16_t rawHum = ((uint16_t)data[3] << 8) | data[4];

    reading.tempCx10 = (int16_t)(-450 + (int32_t)((1750UL * rawTemp) / 65535UL));
    reading.humCx10 = (uint16_t)((1000UL * rawHum) / 65535UL);
    reading.address = address;

    return ReadStatus::Ok;
}

bool softReset(uint8_t address)
{
    if (!writeCommand(address, kSoftReset)) {
        return false;
    }
    delay(DRAGINO_SHT3X_SOFT_RESET_WAIT_MS);
    return true;
}

bool readAddress(uint8_t address, dragino::DraginoSHT3xReading &reading)
{
    for (uint8_t attempt = 1; attempt <= DRAGINO_SHT3X_READ_RETRIES; attempt++) {
        const ReadStatus status = readMeasurementOnce(address, reading);
        if (status == ReadStatus::Ok) {
            return true;
        }

        LOG_DEBUG("SHT3x: read failed addr=0x%02x attempt=%u/%u status=%s",
                  (unsigned)address,
                  (unsigned)attempt,
                  (unsigned)DRAGINO_SHT3X_READ_RETRIES,
                  statusName(status));
    }

    if (softReset(address)) {
        LOG_INFO("SHT3x: soft reset addr=0x%02x", (unsigned)address);
        const ReadStatus status = readMeasurementOnce(address, reading);
        if (status == ReadStatus::Ok) {
            return true;
        }

        LOG_DEBUG("SHT3x: read failed after reset addr=0x%02x status=%s",
                  (unsigned)address,
                  statusName(status));
    } else {
        LOG_DEBUG("SHT3x: soft reset failed addr=0x%02x", (unsigned)address);
    }

    return false;
}

bool readSensor(dragino::DraginoSHT3xReading &reading)
{
    reading = {};

    bool ok = readAddress((uint8_t)DRAGINO_SHT3X_ADDR_PRIMARY, reading);
    if (!ok && ((uint8_t)DRAGINO_SHT3X_ADDR_ALT != (uint8_t)DRAGINO_SHT3X_ADDR_PRIMARY)) {
        ok = readAddress((uint8_t)DRAGINO_SHT3X_ADDR_ALT, reading);
    }

    return ok;
}

int16_t averageSigned(int32_t sum, uint8_t count)
{
    if (count == 0) {
        return 0;
    }
    if (sum >= 0) {
        return (int16_t)((sum + (count / 2)) / count);
    }
    return (int16_t)((sum - (count / 2)) / count);
}

uint16_t averageUnsigned(uint32_t sum, uint8_t count)
{
    if (count == 0) {
        return 0;
    }
    return (uint16_t)((sum + (count / 2)) / count);
}

void printFixedTempCx10(int16_t value)
{
#if DRAGINO_SHT3X_SERIAL_PRINT && defined(DEBUG_PORT)
    const int16_t absValue = value < 0 ? (int16_t)-value : value;
    DEBUG_PORT.printf("%s%d.%d", value < 0 ? "-" : "", (int)(absValue / 10), (int)(absValue % 10));
#else
    (void)value;
#endif
}

void printFixedHumCx10(uint16_t value)
{
#if DRAGINO_SHT3X_SERIAL_PRINT && defined(DEBUG_PORT)
    DEBUG_PORT.printf("%u.%u", (unsigned)(value / 10), (unsigned)(value % 10));
#else
    (void)value;
#endif
}

int16_t absDiffSigned(int16_t lhs, int16_t rhs)
{
    const int32_t diff = (int32_t)lhs - (int32_t)rhs;
    return (int16_t)(diff < 0 ? -diff : diff);
}

uint16_t absDiffUnsigned(uint16_t lhs, uint16_t rhs)
{
    return lhs >= rhs ? (uint16_t)(lhs - rhs) : (uint16_t)(rhs - lhs);
}

} // namespace

namespace dragino {

DraginoSHT3xSensor::DraginoSHT3xSensor()
    : OSThread("DraginoSHT3xSensor", DRAGINO_SHT3X_SAMPLE_INTERVAL_MS)
{
    draginoSHT3xSensor = this;
    deepSleepObserver.observe(&notifyDeepSleep);
}

int32_t DraginoSHT3xSensor::runOnce()
{
    const uint32_t now = millis();

    if (!sampling_ && !startSampling(now)) {
        return DRAGINO_SHT3X_SAMPLE_INTERVAL_MS;
    }

    if (lastSampleMs_ != 0 &&
        (uint32_t)(now - lastSampleMs_) < (uint32_t)DRAGINO_SHT3X_SAMPLE_INTERVAL_MS) {
        return (int32_t)((uint32_t)DRAGINO_SHT3X_SAMPLE_INTERVAL_MS - (uint32_t)(now - lastSampleMs_));
    }

    lastSampleMs_ = now;
    if (!sampleOnce(now)) {
        updateFilteredReading(now);
        printSampleFailed();
    }

    return DRAGINO_SHT3X_SAMPLE_INTERVAL_MS;
}

bool DraginoSHT3xSensor::getFilteredReading(DraginoSHT3xReading &reading) const
{
    if (!hasFiltered_) {
        reading = {};
        return false;
    }

#if DRAGINO_SHT3X_STALE_READING_MS > 0
    if (lastValidSampleMs_ == 0 ||
        (uint32_t)(millis() - lastValidSampleMs_) > (uint32_t)DRAGINO_SHT3X_STALE_READING_MS) {
        reading = {};
        return false;
    }
#endif

    reading = filtered_;
    return true;
}

bool DraginoSHT3xSensor::hasStableReading() const
{
    DraginoSHT3xReading reading;
    return getFilteredReading(reading);
}

void DraginoSHT3xSensor::stopSampling()
{
    sleepDebugTrace("sht3x stop begin");
    const bool wasActive = sampling_;

    sampling_ = false;
    lastSampleMs_ = 0;
    lastValidSampleMs_ = 0;
    hasFiltered_ = false;

    if (wasActive) {
        LOG_INFO("SHT3x: sampling stopped");
    }
    sleepDebugTrace("sht3x stop end");
}

void DraginoSHT3xSensor::prepareForDeepSleep()
{
    sleepDebugTrace("sht3x prepare begin");
    stopSampling();

#if !MESHTASTIC_EXCLUDE_I2C
    // Wire.end();
#if defined(I2C_SDA) && defined(I2C_SCL)
    pinMode(I2C_SDA, INPUT_ANALOG);
    pinMode(I2C_SCL, INPUT_ANALOG);
#endif
    delay(DRAGINO_SHT3X_I2C_RELEASE_DELAY_MS);
    sleepDebugTrace("sht3x i2c release");
#endif

    sleepDebugTrace("sht3x PA0 off noop begin");
    sensorPowerOff();
    sleepDebugTrace("sht3x PA0 off noop returned");
    delay(DRAGINO_SHT3X_POWER_OFF_SETTLE_MS);
    sleepDebugTrace("sht3x PA0 kept on");
    sleepDebugTrace("sht3x prepare end");
}

void DraginoSHT3xSensor::resetPool()
{
    for (uint8_t i = 0; i < DRAGINO_SHT3X_FILTER_POOL_SIZE; i++) {
        pool_[i] = {};
    }
    poolCount_ = 0;
    poolNext_ = 0;
    lastSampleMs_ = 0;
    lastValidSampleMs_ = 0;
    filtered_ = {};
    hasFiltered_ = false;
    hasAcceptedReading_ = false;
    lastAcceptedReading_ = {};
    invalidSampleCount_ = 0;
    resetRecoverCount_ = 0;
}

bool DraginoSHT3xSensor::startSampling(uint32_t nowMs)
{
    (void)nowMs;

    if (sampling_) {
        return true;
    }

    sensorPowerOn();
    delay(DRAGINO_SHT3X_POWER_STABILIZE_MS);

    LOG_INFO("SHT3x: using Meshtastic Wire bus");
    Wire.setClock(DRAGINO_SHT3X_I2C_CLOCK_HZ);

    resetPool();
    sampling_ = true;

    LOG_INFO("SHT3x: sampling started interval=%lu ms window=%lu ms",
             (unsigned long)DRAGINO_SHT3X_SAMPLE_INTERVAL_MS,
             (unsigned long)DRAGINO_SHT3X_FILTER_WINDOW_MS);
    return true;
}

bool DraginoSHT3xSensor::sampleOnce(uint32_t nowMs)
{
    if (!sampling_ && !startSampling(nowMs)) {
        return false;
    }

    DraginoSHT3xReading raw;
    if (!readValidatedSensor(raw, nowMs)) {
        return false;
    }

    addReading(raw, nowMs);
    updateFilteredReading(nowMs);

    if (hasFiltered_) {
        printSample(raw, filtered_);
    }

    return true;
}

bool DraginoSHT3xSensor::readValidatedSensor(DraginoSHT3xReading &reading, uint32_t nowMs)
{
    (void)nowMs;

    if (!readSensor(reading)) {
        return false;
    }

#if DRAGINO_SHT3X_VALIDATE_ENABLE
    if (!isHardInvalidReading(reading) && !isSuspiciousReading(reading)) {
        acceptReading(reading);
        return true;
    }

    const bool firstHardInvalid = isHardInvalidReading(reading);
    const bool firstSuspicious = !firstHardInvalid && isSuspiciousReading(reading);
    LOG_WARN("SHT3x: %s reading tempCx10=%d humCx10=%u, reset and retry",
             firstHardInvalid ? "invalid" : "suspicious",
             (int)reading.tempCx10,
             (unsigned)reading.humCx10);

    if (reading.address != 0 && softReset(reading.address)) {
        delay(DRAGINO_SHT3X_ANOMALY_RESET_WAIT_MS);
        DraginoSHT3xReading retry;
        if (readSensor(retry)) {
            if (!isHardInvalidReading(retry)) {
                if (!isSuspiciousReading(retry) ||
                    (firstSuspicious && hasOnlyAcceptableLowHumiditySuspicion(retry))) {
                    reading = retry;
                    acceptReading(reading);
                    resetRecoverCount_++;
                    LOG_INFO("SHT3x: recovered after reset tempCx10=%d humCx10=%u",
                             (int)reading.tempCx10,
                             (unsigned)reading.humCx10);
                    return true;
                }
            }
            LOG_WARN("SHT3x: retry reading dropped tempCx10=%d humCx10=%u",
                     (int)retry.tempCx10,
                     (unsigned)retry.humCx10);
        }
    }

    invalidSampleCount_++;
    LOG_WARN("SHT3x: invalid reading dropped count=%lu tempCx10=%d humCx10=%u",
             (unsigned long)invalidSampleCount_,
             (int)reading.tempCx10,
             (unsigned)reading.humCx10);
    return false;
#else
    acceptReading(reading);
    return true;
#endif
}

bool DraginoSHT3xSensor::isHardInvalidReading(const DraginoSHT3xReading &reading) const
{
    if (reading.tempCx10 < (int16_t)DRAGINO_SHT3X_MIN_TEMP_CX10 ||
        reading.tempCx10 > (int16_t)DRAGINO_SHT3X_MAX_TEMP_CX10) {
        return true;
    }
    if (reading.humCx10 < (uint16_t)DRAGINO_SHT3X_MIN_HUM_CX10 ||
        reading.humCx10 > (uint16_t)DRAGINO_SHT3X_MAX_HUM_CX10) {
        return true;
    }
    return false;
}

bool DraginoSHT3xSensor::isSuspiciousReading(const DraginoSHT3xReading &reading) const
{
    return hasJumpSuspicion(reading) || hasHumidityEdgeSuspicion(reading);
}

bool DraginoSHT3xSensor::hasJumpSuspicion(const DraginoSHT3xReading &reading) const
{
    if (!hasAcceptedReading_) {
        return false;
    }

    if (absDiffSigned(reading.tempCx10, lastAcceptedReading_.tempCx10) >
        (int16_t)DRAGINO_SHT3X_MAX_TEMP_JUMP_CX10) {
        return true;
    }
    if (absDiffUnsigned(reading.humCx10, lastAcceptedReading_.humCx10) >
        (uint16_t)DRAGINO_SHT3X_MAX_HUM_JUMP_CX10) {
        return true;
    }
    return false;
}

bool DraginoSHT3xSensor::hasHumidityEdgeSuspicion(const DraginoSHT3xReading &reading) const
{
    return hasLowHumiditySuspicion(reading) ||
           reading.humCx10 >= (uint16_t)DRAGINO_SHT3X_MAX_HUM_CX10;
}

bool DraginoSHT3xSensor::hasLowHumiditySuspicion(const DraginoSHT3xReading &reading) const
{
    return reading.humCx10 < (uint16_t)DRAGINO_SHT3X_SUSPICIOUS_LOW_HUM_CX10;
}

bool DraginoSHT3xSensor::hasOnlyAcceptableLowHumiditySuspicion(const DraginoSHT3xReading &reading) const
{
    if (!hasLowHumiditySuspicion(reading)) {
        return false;
    }
    if (hasAcceptedReading_ &&
        absDiffSigned(reading.tempCx10, lastAcceptedReading_.tempCx10) >
            (int16_t)DRAGINO_SHT3X_MAX_TEMP_JUMP_CX10) {
        return false;
    }
    return reading.humCx10 <= (uint16_t)DRAGINO_SHT3X_MAX_HUM_CX10;
}

void DraginoSHT3xSensor::acceptReading(const DraginoSHT3xReading &reading)
{
    hasAcceptedReading_ = true;
    lastAcceptedReading_ = reading;
}

void DraginoSHT3xSensor::addReading(const DraginoSHT3xReading &reading, uint32_t nowMs)
{
    pool_[poolNext_].reading = reading;
    pool_[poolNext_].sampleMs = nowMs;
    pool_[poolNext_].valid = true;
    lastValidSampleMs_ = nowMs;

    poolNext_ = (uint8_t)((poolNext_ + 1) % DRAGINO_SHT3X_FILTER_POOL_SIZE);
    if (poolCount_ < DRAGINO_SHT3X_FILTER_POOL_SIZE) {
        poolCount_++;
    }
}

void DraginoSHT3xSensor::updateFilteredReading(uint32_t nowMs)
{
    int32_t tempSum = 0;
    uint32_t humSum = 0;
    uint8_t count = 0;

    for (uint8_t i = 0; i < DRAGINO_SHT3X_FILTER_POOL_SIZE; i++) {
        if (!pool_[i].valid) {
            continue;
        }
        if ((uint32_t)(nowMs - pool_[i].sampleMs) > (uint32_t)DRAGINO_SHT3X_FILTER_WINDOW_MS) {
            continue;
        }

        tempSum += pool_[i].reading.tempCx10;
        humSum += pool_[i].reading.humCx10;
        count++;
    }

    if (count == 0) {
        filtered_ = {};
        hasFiltered_ = false;
        return;
    }

#if DRAGINO_SHT3X_REQUIRE_FULL_POOL
    if (poolCount_ < DRAGINO_SHT3X_FILTER_POOL_SIZE || count < DRAGINO_SHT3X_FILTER_POOL_SIZE) {
        filtered_ = {};
        hasFiltered_ = false;
        return;
    }
#endif

    filtered_.tempCx10 = averageSigned(tempSum, count);
    filtered_.humCx10 = averageUnsigned(humSum, count);
    const uint8_t latestIndex =
        (uint8_t)((poolNext_ + DRAGINO_SHT3X_FILTER_POOL_SIZE - 1) % DRAGINO_SHT3X_FILTER_POOL_SIZE);
    filtered_.address = pool_[latestIndex].reading.address;
    hasFiltered_ = true;
}

void DraginoSHT3xSensor::printSample(const DraginoSHT3xReading &raw, const DraginoSHT3xReading &filtered) const
{
#if DRAGINO_SHT3X_SERIAL_PRINT && defined(DEBUG_PORT)
    DEBUG_PORT.printf("[SHT3x] addr=0x%02x raw=", (unsigned)raw.address);
    printFixedTempCx10(raw.tempCx10);
    DEBUG_PORT.printf("C/");
    printFixedHumCx10(raw.humCx10);
    DEBUG_PORT.printf("%%RH filtered=");
    printFixedTempCx10(filtered.tempCx10);
    DEBUG_PORT.printf("C/");
    printFixedHumCx10(filtered.humCx10);
    DEBUG_PORT.printf("%%RH pool=%u/%u\r\n",
                      (unsigned)poolCount_,
                      (unsigned)DRAGINO_SHT3X_FILTER_POOL_SIZE);
#else
    (void)raw;
    (void)filtered;
#endif
}

void DraginoSHT3xSensor::printSampleFailed() const
{
#if DRAGINO_SHT3X_SERIAL_PRINT && defined(DEBUG_PORT)
    DEBUG_PORT.printf("[SHT3x] read failed pool=%u/%u\r\n",
                      (unsigned)poolCount_,
                      (unsigned)DRAGINO_SHT3X_FILTER_POOL_SIZE);
#endif
}

int DraginoSHT3xSensor::notifyDeepSleepCb(void *unused)
{
    (void)unused;
    sleepDebugTrace("sht3x notify begin");
    prepareForDeepSleep();
    sleepDebugTrace("sht3x notify end");
    return 0;
}

} // namespace dragino

#else

namespace dragino {

DraginoSHT3xSensor::DraginoSHT3xSensor()
    : OSThread("DraginoSHT3xSensor", DRAGINO_SHT3X_SAMPLE_INTERVAL_MS)
{
    draginoSHT3xSensor = this;
}

int32_t DraginoSHT3xSensor::runOnce()
{
    return DRAGINO_SHT3X_SAMPLE_INTERVAL_MS;
}

bool DraginoSHT3xSensor::getFilteredReading(DraginoSHT3xReading &reading) const
{
    reading = {};
    return false;
}

bool DraginoSHT3xSensor::hasStableReading() const
{
    return false;
}

void DraginoSHT3xSensor::stopSampling()
{
}

void DraginoSHT3xSensor::prepareForDeepSleep()
{
}

int DraginoSHT3xSensor::notifyDeepSleepCb(void *unused)
{
    (void)unused;
    return 0;
}

} // namespace dragino

#endif // DRAGINO_SHT3X_ENABLE

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
