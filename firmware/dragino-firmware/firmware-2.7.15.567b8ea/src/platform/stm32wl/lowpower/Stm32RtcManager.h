#pragma once

#include "stm32rtc/STM32LowPower.h"
#include "stm32rtc/STM32RTC.h"
#include <time.h>

#ifndef DRAGINO_STM32_STOP_RESUME
#define DRAGINO_STM32_STOP_RESUME 0
#endif

#ifndef DRAGINO_STM32_STOP_RESUME_FALLBACK_RESET
#define DRAGINO_STM32_STOP_RESUME_FALLBACK_RESET 1
#endif

#ifndef DRAGINO_STM32_STOP_RESUME_TRACE
#define DRAGINO_STM32_STOP_RESUME_TRACE 0
#endif

namespace meshtastic {
namespace stm32 {

struct StopResumeWakeInfo {
    bool valid = false;
    bool foreverSleep = false;
    bool wokeByButton = false;
    bool wokeByTimer = false;
    bool buttonGateAccepted = false;
    bool hardwareRecovered = false;
    bool bluetoothRecovered = false;
    bool radioRecovered = false;
    uint32_t requestedSleepMs = 0;
    uint32_t sleptMs = 0;
    uint32_t stopSuspendedMs = 0;
    uint32_t gateAwakeMs = 0;
    uint32_t buttonGateRejectedCount = 0;
    time_t rtcBefore = 0;
    time_t rtcAfter = 0;
};

class RtcManager {
public:
    static RtcManager& instance();

    void begin();
    void deepSleep(uint32_t ms);
    void deepSleepForever();  // No RTC timer; wake only by button.

    void syncFromSystem();
    bool syncToSystem();
    bool isValid();
    bool didStopResumeWake() const { return _lastStopResumeWake.valid; }
    const StopResumeWakeInfo& lastStopResumeWake() const { return _lastStopResumeWake; }
    void clearStopResumeWake() { _lastStopResumeWake.valid = false; }

private:
    RtcManager();
    RtcManager(const RtcManager&) = delete;
    void operator=(const RtcManager&) = delete;
    time_t readEpochUtc();
    bool stopResumeSleep(uint32_t ms, bool foreverSleep);

    STM32RTC& _rtc;
    bool _initialized = false;
    StopResumeWakeInfo _lastStopResumeWake;
};

} // namespace stm32
} // namespace meshtastic

extern meshtastic::stm32::RtcManager& rtcManager;
