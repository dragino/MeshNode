#include "Stm32RtcManager.h"
#include "RtcConfig.h"
#include "DebugConfiguration.h"
#include "configuration.h"
#include "concurrency/OSThread.h"
#include "dragino/DraginoWatchdog.h"
#include "gps/RTC.h"
#include "mesh/RadioInterface.h"
#include <Wire.h>
#include <time.h>
#include <SPI.h>

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
#include "dragino/DraginoBluetooth.h"
#include "dragino/DraginoBootControlPage.h"
#include "dragino/DraginoHardware.h"
#include "dragino/DraginoSleepWakeGate.h"
#endif

#include "Stm32wlLowPower.h"

#if DRAGINO_STM32_STOP_RESUME && defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
extern RadioInterface *rIf;

#ifndef DRAGINO_SLEEP_WAKE_TIMER_MARGIN_MS
#define DRAGINO_SLEEP_WAKE_TIMER_MARGIN_MS 250UL
#endif

namespace {

void stopResumeTrace(const char *message)
{
#if DRAGINO_STM32_STOP_RESUME_TRACE
    Serial.begin(SERIAL_BAUD);
    Serial.print("[STOPRESUME] ");
    Serial.println(message);
    Serial.flush();
#else
    (void)message;
#endif
}

void stopResumeTraceValue(const char *label, uint32_t value)
{
#if DRAGINO_STM32_STOP_RESUME_TRACE
    Serial.begin(SERIAL_BAUD);
    Serial.print("[STOPRESUME] ");
    Serial.print(label);
    Serial.print("=");
    Serial.println(value);
    Serial.flush();
#else
    (void)label;
    (void)value;
#endif
}

uint32_t rtcElapsedMs(time_t beforeEpoch, uint32_t beforeSubMs, time_t afterEpoch, uint32_t afterSubMs)
{
    int64_t delta = ((int64_t)afterEpoch - (int64_t)beforeEpoch) * 1000;
    delta += (int64_t)afterSubMs - (int64_t)beforeSubMs;

    if (delta <= 0) {
        return 0;
    }
    if (delta > UINT32_MAX) {
        return UINT32_MAX;
    }
    return (uint32_t)delta;
}

uint32_t chooseSleptMs(uint32_t requestedMs, bool foreverSleep, bool wokeByButton, uint32_t rtcMs)
{
    if (foreverSleep) {
        return rtcMs;
    }
    if (wokeByButton && rtcMs > 0) {
        return rtcMs;
    }
    if (requestedMs > 0) {
        return requestedMs;
    }
    return rtcMs;
}

uint32_t remainingSleepMs(uint32_t requestedMs, bool foreverSleep, uint32_t elapsedMs)
{
    if (foreverSleep) {
        return 0;
    }
    if (elapsedMs >= requestedMs) {
        return 0;
    }
    return requestedMs - elapsedMs;
}

bool timerWakeDue(uint32_t requestedMs, bool foreverSleep, uint32_t elapsedMs)
{
    if (foreverSleep) {
        return false;
    }
    if (elapsedMs >= requestedMs) {
        return true;
    }
    return (requestedMs - elapsedMs) <= DRAGINO_SLEEP_WAKE_TIMER_MARGIN_MS;
}

bool wakeButtonActive()
{
#ifdef WAKEUP_BUTTON_PIN
    pinMode(WAKEUP_BUTTON_PIN, INPUT_PULLUP);
    return digitalRead(WAKEUP_BUTTON_PIN) == LOW;
#else
    return false;
#endif
}

} // namespace
#endif

namespace meshtastic {
namespace stm32 {

RtcManager &RtcManager::instance()
{
    static RtcManager inst;
    return inst;
}

RtcManager::RtcManager() : _rtc(STM32RTC::getInstance()) {}

void RtcManager::begin()
{
    if (_initialized) {
        return;
    }

    _rtc.setClockSource(STM32RTC::LSE_CLOCK);
    _rtc.begin(false, STM32RTC::HOUR_24);
    LowPower.begin();

    LOG_INFO("STM32RTC initialized, clock source: LSE");

    if (isValid()) {
        if (syncToSystem()) {
            LOG_INFO("RTC time restored to system");
        } else {
            LOG_WARN("RTC had a valid-looking value, but restore to system was rejected");
        }
    } else {
        LOG_WARN("RTC time invalid, will be set when network time received");
    }

    _initialized = true;
}

void RtcManager::deepSleep(uint32_t ms)
{
    // Do not overwrite the hardware RTC right before sleep.
    // syncFromSystem();

    LOG_INFO("Entering deep sleep for %lu ms", ms);

#if DRAGINO_STM32_STOP_RESUME && defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (stopResumeSleep(ms, false)) {
        return;
    }
#endif

#if HAS_WIRE
    // Wire.end();

    // SPI.end();
#endif

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (!dragino::ensureBootloaderWillJumpAppOnNormalReset()) {
        LOG_WARN("BootControl: failed to clear bootloader request before sleep");
    }
    if (dragino::draginoBluetooth) {
        dragino::draginoBluetooth->shutdown();
    }
    if (dragino::draginoHardware) {
        dragino::draginoHardware->Turn_off();
    }
#endif

    // Enter the same STOP2 preparation used by the reference LoRa project.
    lp_prepare_all();
    dragino::watchdog::prepareForSleep();

#ifdef WAKEUP_BUTTON_PIN
    LowPower.attachInterruptWakeup(WAKEUP_BUTTON_PIN, nullptr, FALLING, DEEP_SLEEP_MODE);
#endif

    LowPower.deepSleep(ms);
    dragino::watchdog::afterStopWake();
    // lp_raw_stop2_forever();

    // STOP wake continues from the next instruction, so reboot to restore the full runtime state.
    dragino::watchdog::feedNow();
    NVIC_SystemReset();
}

void RtcManager::deepSleepForever()
{
    // Do not overwrite the hardware RTC right before an indefinite sleep.
    // syncFromSystem();

    LOG_INFO("Entering deep sleep (button wakeup only)");

#if DRAGINO_STM32_STOP_RESUME && defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (stopResumeSleep(0, true)) {
        return;
    }
#endif

#if HAS_WIRE
    // Wire.end();

    // SPI.end();
#endif

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    if (!dragino::ensureBootloaderWillJumpAppOnNormalReset()) {
        LOG_WARN("BootControl: failed to clear bootloader request before forever sleep");
    }
    if (dragino::draginoBluetooth) {
        dragino::draginoBluetooth->shutdown();
    }
    if (dragino::draginoHardware) {
        dragino::draginoHardware->Turn_off();
    }
#endif

    // Keep the forever-sleep path identical to the timed sleep path.
    lp_prepare_all();
    dragino::watchdog::prepareForSleep();

#ifdef WAKEUP_BUTTON_PIN
    LowPower.attachInterruptWakeup(WAKEUP_BUTTON_PIN, nullptr, FALLING, DEEP_SLEEP_MODE);
#endif

    // No RTC alarm, wake only from the configured external source.
    LowPower.deepSleep(0);
    dragino::watchdog::afterStopWake();

    // STOP wake continues from here as well, so restore by rebooting cleanly.
    dragino::watchdog::feedNow();
    NVIC_SystemReset();
}

bool RtcManager::stopResumeSleep(uint32_t ms, bool foreverSleep)
{
#if DRAGINO_STM32_STOP_RESUME && defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
    StopResumeWakeInfo info;
    uint32_t rtcBeforeSubMs = 0;
    uint32_t rtcAfterSubMs = 0;
    uint32_t totalStopSuspendedMs = 0;
    uint32_t totalGateAwakeMs = 0;

    info.valid = true;
    info.foreverSleep = foreverSleep;
    info.requestedSleepMs = ms;
    info.rtcBefore = _rtc.getEpoch(&rtcBeforeSubMs);
    _lastStopResumeWake = info;

    stopResumeTrace(foreverSleep ? "enter forever" : "enter timed");
    stopResumeTraceValue("requested_ms", ms);

    if (!dragino::ensureBootloaderWillJumpAppOnNormalReset()) {
        LOG_WARN("BootControl: failed to clear bootloader request before STOP-resume sleep");
    }
    if (dragino::draginoBluetooth) {
        dragino::draginoBluetooth->shutdown();
    }
    if (dragino::draginoHardware) {
        dragino::draginoHardware->Turn_off();
    }

    while (true) {
#if DRAGINO_STM32_SLEEP_WAKE_GATE
        if (info.buttonGateRejectedCount > 0 && dragino::draginoHardware) {
            dragino::draginoHardware->Turn_off();
        }
        dragino::DraginoSleepWakeGate::prepareForSleep();
#endif

        uint32_t loopStartSubMs = 0;
        time_t loopStartRtc = _rtc.getEpoch(&loopStartSubMs);
        uint32_t wallElapsedMs = rtcElapsedMs(info.rtcBefore, rtcBeforeSubMs, loopStartRtc, loopStartSubMs);
        uint32_t remainingMs = remainingSleepMs(ms, foreverSleep, wallElapsedMs);

        if (!foreverSleep && remainingMs == 0) {
            info.wokeByTimer = true;
            break;
        }

        lp_prepare_all();
        dragino::watchdog::prepareForSleep();

#ifdef WAKEUP_BUTTON_PIN
        LowPower.attachInterruptWakeup(WAKEUP_BUTTON_PIN, nullptr, FALLING, DEEP_SLEEP_MODE);
#endif

        uint32_t stopBeforeSubMs = 0;
        time_t stopBeforeRtc = _rtc.getEpoch(&stopBeforeSubMs);
        LowPower.deepSleep(foreverSleep ? 0 : remainingMs);

        lp_resume_after_stop2_core();
        dragino::watchdog::afterStopWake();

        uint32_t stopAfterSubMs = 0;
        time_t stopAfterRtc = _rtc.getEpoch(&stopAfterSubMs);
        uint32_t stopElapsedMs = rtcElapsedMs(stopBeforeRtc, stopBeforeSubMs, stopAfterRtc, stopAfterSubMs);
        totalStopSuspendedMs += stopElapsedMs;

        wallElapsedMs = rtcElapsedMs(info.rtcBefore, rtcBeforeSubMs, stopAfterRtc, stopAfterSubMs);
        bool buttonNow = wakeButtonActive();
        bool timerDue = timerWakeDue(ms, foreverSleep, wallElapsedMs);

        if (timerDue) {
            info.wokeByTimer = true;
            info.wokeByButton = buttonNow;
            break;
        }

#if DRAGINO_STM32_SLEEP_WAKE_GATE
        dragino::DraginoSleepWakeGate::Context gateContext;
        gateContext.foreverSleep = foreverSleep;
        gateContext.deadlineRemainingMs = remainingSleepMs(ms, foreverSleep, wallElapsedMs);
        gateContext.buttonCurrentlyPressed = buttonNow;

        stopResumeTrace("button gate begin");
        auto gate = dragino::DraginoSleepWakeGate::run(gateContext);
        totalGateAwakeMs += gate.activeMs;

        if (gate.result == dragino::SleepWakeGateResult::AcceptWake) {
            info.wokeByButton = true;
            info.buttonGateAccepted = true;
            stopResumeTrace("button gate accepted");
            break;
        }

        uint32_t gateAfterSubMs = 0;
        time_t gateAfterRtc = _rtc.getEpoch(&gateAfterSubMs);
        wallElapsedMs = rtcElapsedMs(info.rtcBefore, rtcBeforeSubMs, gateAfterRtc, gateAfterSubMs);

        if (gate.result == dragino::SleepWakeGateResult::TimerExpired ||
            timerWakeDue(ms, foreverSleep, wallElapsedMs)) {
            info.wokeByTimer = true;
            stopResumeTrace("button gate timer");
            break;
        }

        info.buttonGateRejectedCount++;
        stopResumeTrace("button gate rejected");
        stopResumeTraceValue("remaining_ms", remainingSleepMs(ms, foreverSleep, wallElapsedMs));
        continue;
#else
        info.wokeByButton = buttonNow || foreverSleep || !timerDue;
        break;
#endif
    }

    info.rtcAfter = _rtc.getEpoch(&rtcAfterSubMs);
    info.sleptMs = chooseSleptMs(ms, foreverSleep, info.wokeByButton,
                                 rtcElapsedMs(info.rtcBefore, rtcBeforeSubMs, info.rtcAfter, rtcAfterSubMs));
    info.stopSuspendedMs = totalStopSuspendedMs;
    info.gateAwakeMs = totalGateAwakeMs;
    lp_compensate_hal_tick(info.stopSuspendedMs);

    info.hardwareRecovered = true;
    if (dragino::draginoHardware) {
        info.hardwareRecovered = dragino::draginoHardware->resumeAfterStop();
    }

    stopResumeTrace("resume peripherals done");

    syncToSystem();

    info.bluetoothRecovered = true;
    if (dragino::draginoBluetooth) {
        dragino::draginoBluetooth->resumeAfterStop(info.wokeByButton);
    }

    lp_resume_subghz();
    if (rIf) {
        stopResumeTrace("radio reconfigure begin");
        bool reportedRadioRecovered = rIf->reconfigure();
#if defined(ARCH_STM32WL)
        // STM32WL currently uses SX126xInterface::reconfigure(), whose implementation
        // returns RADIOLIB_ERR_NONE (0) on success. Treat a completed call as recovered.
        info.radioRecovered = true;
        if (!reportedRadioRecovered) {
            LOG_DEBUG("STOP-resume: STM32WL radio reconfigure returned false-compatible success");
        }
#else
        info.radioRecovered = reportedRadioRecovered;
#endif
        stopResumeTrace("radio reconfigure end");
    }

    concurrency::mainDelay.interrupt();
    _lastStopResumeWake = info;

    stopResumeTrace("woke");
    stopResumeTraceValue("slept_ms", info.sleptMs);
    stopResumeTraceValue("stop_ms", info.stopSuspendedMs);
    stopResumeTraceValue("gate_ms", info.gateAwakeMs);
    stopResumeTraceValue("button", info.wokeByButton ? 1 : 0);
    stopResumeTraceValue("timer", info.wokeByTimer ? 1 : 0);
    stopResumeTraceValue("gate", info.buttonGateAccepted ? 1 : 0);
    stopResumeTraceValue("hardware", info.hardwareRecovered ? 1 : 0);
    stopResumeTraceValue("radio", info.radioRecovered ? 1 : 0);

    if ((!info.hardwareRecovered || !info.radioRecovered) && DRAGINO_STM32_STOP_RESUME_FALLBACK_RESET) {
        LOG_WARN("STOP-resume failed, fallback reset: hardware=%d radio=%d",
                 info.hardwareRecovered ? 1 : 0,
                 info.radioRecovered ? 1 : 0);
        stopResumeTrace("fallback reset");
        dragino::watchdog::feedNow();
        NVIC_SystemReset();
    }

    return true;
#else
    (void)ms;
    (void)foreverSleep;
    return false;
#endif
}

void RtcManager::syncFromSystem()
{
    uint32_t epoch = getTime(false);
    if (epoch > 1700000000) {
        _rtc.setEpoch((time_t)epoch, 0);
        LOG_DEBUG("Synced system time to STM32 RTC: epoch=%lu", epoch);
    }
}

time_t RtcManager::readEpochUtc()
{
    uint8_t weekDay = 0;
    uint8_t day = 0;
    uint8_t month = 0;
    uint8_t year = 0;
    uint8_t hours = 0;
    uint8_t minutes = 0;
    uint8_t seconds = 0;
    uint32_t subSeconds = 0;

    // STM32 HAL requires reading time before date to unlock shadow registers
    // and get a coherent snapshot across reset/wakeup.
    _rtc.getTime(&hours, &minutes, &seconds, &subSeconds);
    _rtc.getDate(&weekDay, &day, &month, &year);
    (void)weekDay;
    (void)subSeconds;

    struct tm t = {};
    t.tm_isdst = -1;
    t.tm_wday = 0;
    t.tm_yday = 0;
    t.tm_year = year + 100;
    t.tm_mon = month - 1;
    t.tm_mday = day;
    t.tm_hour = hours;
    t.tm_min = minutes;
    t.tm_sec = seconds;

    time_t epoch = gm_mktime(&t);
    LOG_DEBUG("Read STM32 RTC raw date/time: %02u-%02u-%02u %02u:%02u:%02u -> epoch=%ld",
              (unsigned)(t.tm_year + 1900), (unsigned)(t.tm_mon + 1), (unsigned)t.tm_mday,
              (unsigned)t.tm_hour, (unsigned)t.tm_min, (unsigned)t.tm_sec,
              (long)epoch);
    return epoch;
}

bool RtcManager::syncToSystem()
{
    // time_t epoch = readEpochUtc();
    time_t epoch = _rtc.getEpoch();

#ifdef BUILD_EPOCH
    if (epoch <= BUILD_EPOCH) {
#else
    if (epoch <= 1700000000) {
#endif
        LOG_DEBUG("STM32 RTC epoch is invalid during restore: epoch=%ld", (long)epoch);
        return false;
    }

    struct timeval tv;
    tv.tv_sec = epoch;
    tv.tv_usec = 0;

    RTCSetResult result = perhapsSetRTC(RTCQualityDevice, &tv);
    if (result == RTCSetResultSuccess) {
        LOG_DEBUG("Synced STM32 RTC to system: epoch=%ld", (long)epoch);
        return true;
    }

    LOG_DEBUG("STM32 RTC restore rejected: epoch=%ld, result=%d", (long)epoch, (int)result);
    return false;
}

bool RtcManager::isValid()
{
    // time_t epoch = readEpochUtc();
    time_t epoch = _rtc.getEpoch();
#ifdef BUILD_EPOCH
    return (epoch > BUILD_EPOCH);
#else
    return (epoch > 1700000000);
#endif
}

} // namespace stm32
} // namespace meshtastic

meshtastic::stm32::RtcManager &rtcManager = meshtastic::stm32::RtcManager::instance();
