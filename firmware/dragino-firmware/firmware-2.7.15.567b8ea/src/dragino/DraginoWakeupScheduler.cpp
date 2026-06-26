#include "DraginoWakeupScheduler.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "PrivateConfig.h"
#include "gps/RTC.h"
#include "configuration.h"

#if defined(DRAGINO) && defined(MESHTASTIC_EXCLUDE_GPS) && !defined(MESHTASTIC_EXCLUDE_TIMESYNC)
#include "modules/TimeSyncModule.h"
#endif

#ifndef DRAGINO_TIME_REQUEST_STARTUP_DELAY_MS
#define DRAGINO_TIME_REQUEST_STARTUP_DELAY_MS DRAGINO_DEFAULT_STARTUP_DELAY_MS
#endif

#ifndef DRAGINO_TIME_REQUEST_STALE_SEC
#define DRAGINO_TIME_REQUEST_STALE_SEC (6UL * 60UL * 60UL)
#endif

namespace dragino {

DraginoWakeupScheduler& DraginoWakeupScheduler::instance() {
    static DraginoWakeupScheduler inst;
    return inst;
}

void DraginoWakeupScheduler::init() {
    onConfigChanged();
}

void DraginoWakeupScheduler::onConfigChanged() {
    timeRequestSentThisWake_ = false;
    timeRequestDelayStarted_ = false;
    timeRequestDelayStartMs_ = 0;
    lastLowRtcWarnMs_ = 0;

    if (!privateConfig.hasSyncWakeup()) {
        LOG_INFO("Sync wakeup: not configured");
        return;
    }
    
    auto& sync = privateConfig.getSyncWakeup();
    LOG_INFO("Sync wakeup: enabled=%d, strategy=%d", 
             sync.enabled, sync.strategy);
    
    if (sync.strategy == temeshtastic_SyncWakeupConfig_WakeupStrategy_STRATEGY_FIXED) {
        if (sync.has_fixed_wakeup) {
            LOG_INFO("  Fixed: interval=%umin, align=%u, offset=%us",
                     sync.fixed_wakeup.interval_min, 
                     sync.fixed_wakeup.align_minute, 
                     sync.fixed_wakeup.offset_sec);
        }
    } else {
        if (sync.has_scheduled_wakeup) {
            LOG_INFO("  Scheduled: %u time slots", sync.scheduled_wakeup.time_slots_count);
            for (pb_size_t i = 0; i < sync.scheduled_wakeup.time_slots_count; i++) {
                auto& slot = sync.scheduled_wakeup.time_slots[i];
                LOG_INFO("    Slot %u: %02u:00-%02u:00, interval=%umin, align=%u",
                         i, slot.start_hour, slot.end_hour, 
                         slot.interval_min, slot.align_minute);
            }
        }
    }
}

void DraginoWakeupScheduler::onWakeSessionStart()
{
    timeRequestSentThisWake_ = false;
    timeRequestDelayStarted_ = false;
    timeRequestDelayStartMs_ = 0;
}

uint32_t DraginoWakeupScheduler::calcNextWakeupMs(bool allowGatewayTimeRequest) {
    if (!privateConfig.isEnrolled()) {
        return 0;
    }
    
    if (!privateConfig.isPrivatized()) {
        return 0;
    }
    
    if (!privateConfig.isSyncWakeupEnabled()) {
        return 0;
    }

    if (allowGatewayTimeRequest) {
        maybeRequestGatewayTime();
    }

    // When RTC quality is insufficient, aligned wakeup cannot be calculated; use a fixed 1-hour interval.
    if (!isRtcQualitySufficient()) {
        uint32_t nowMs = millis();
        if (nowMs - lastLowRtcWarnMs_ >= 5000) {
            lastLowRtcWarnMs_ = nowMs;
            LOG_WARN("RTC quality too low for aligned wakeup, using fixed 1h interval");
        }
        return DRAGINO_DEGRADED_WAKEUP_INTERVAL_MS;
    }
    
    lastLowRtcWarnMs_ = 0;

    auto& sync = privateConfig.getSyncWakeup();
    
    if (sync.strategy == temeshtastic_SyncWakeupConfig_WakeupStrategy_STRATEGY_FIXED) {
        return calcFixedStrategyMs();
    } else {
        return calcScheduledStrategyMs();
    }
}

uint32_t DraginoWakeupScheduler::calcFixedStrategyMs() {
    auto& sync = privateConfig.getSyncWakeup();
    
    if (!sync.has_fixed_wakeup) {
        return 3600000;
    }
    
    return calcAlignWakeupMs(
        sync.fixed_wakeup.interval_min, 
        sync.fixed_wakeup.align_minute, 
        sync.fixed_wakeup.offset_sec
    );
}

uint32_t DraginoWakeupScheduler::calcScheduledStrategyMs() {
    // TODO: Scheduled strategy not yet implemented, using fixed strategy
    static uint32_t lastWarnMs = 0;
    uint32_t now = millis();
    if (now - lastWarnMs >= 5000) {
        lastWarnMs = now;
        LOG_WARN("Scheduled strategy not implemented, using fixed");
    }
    return calcFixedStrategyMs();
}

uint32_t DraginoWakeupScheduler::calcAlignWakeupMs(uint32_t intervalMin, uint32_t alignMinute, uint32_t offsetSec) {
    if (intervalMin == 0) intervalMin = 60;
    if (alignMinute >= 60) alignMinute = 0;

    uint32_t todaySec = getTodaySeconds();

    uint32_t intervalSec = intervalMin * 60;
    uint32_t alignSec = alignMinute * 60;

    uint32_t nextAlign = alignSec;
    while (nextAlign <= todaySec) {
        nextAlign += intervalSec;
    }

    // Wake slightly early.
    const uint32_t EARLY_WAKEUP_SEC = 30;
    if (nextAlign >= EARLY_WAKEUP_SEC) {
        nextAlign -= EARLY_WAKEUP_SEC;
    }

    // Check whether the early wake time falls into the midnight rollover guard window.
    // Guard window: 23:59:50 to 00:00:10.
    const uint32_t MIDNIGHT_GUARD_SEC = 10;
    uint32_t wakeupTod = nextAlign % 86400;
    if (wakeupTod < MIDNIGHT_GUARD_SEC || wakeupTod > (86400 - MIDNIGHT_GUARD_SEC)) {
        // Still inside the rollover window; shift earlier to get outside it.
        uint32_t safeOffset = (wakeupTod < MIDNIGHT_GUARD_SEC)
            ? (MIDNIGHT_GUARD_SEC + wakeupTod)   // Just after midnight; move back before 23:59:50.
            : (86400 - wakeupTod + MIDNIGHT_GUARD_SEC);  // Close to midnight.
        nextAlign -= safeOffset;
        LOG_DEBUG("Wakeup shifted -%lus to avoid midnight rollover", safeOffset);
    }

    uint32_t sleepMs = (nextAlign - todaySec) * 1000;
    sleepMs += offsetSec * 1000;

    if (sleepMs < 1000) {
        sleepMs = intervalSec * 1000;
    }

    static uint32_t lastLogMs = 0;
    uint32_t nowMs = millis();
    if (nowMs - lastLogMs >= 5000) {
        lastLogMs = nowMs;
        LOG_DEBUG("Calc wakeup: interval=%umin, align=%u, offset=%us, early=%us, sleep=%ums",
                  intervalMin, alignMinute, offsetSec, EARLY_WAKEUP_SEC, sleepMs);
    }

    return sleepMs;
}

int DraginoWakeupScheduler::findCurrentTimeSlot() {
    auto& sync = privateConfig.getSyncWakeup();
    
    if (!sync.has_scheduled_wakeup) return -1;
    
    uint32_t currentHour = getCurrentHour();
    
    for (pb_size_t i = 0; i < sync.scheduled_wakeup.time_slots_count; i++) {
        auto& slot = sync.scheduled_wakeup.time_slots[i];
        if (slot.start_hour <= slot.end_hour) {
            if (currentHour >= slot.start_hour && currentHour < slot.end_hour) {
                return i;
            }
        } else {
            if (currentHour >= slot.start_hour || currentHour < slot.end_hour) {
                return i;
            }
        }
    }
    return -1;
}

int DraginoWakeupScheduler::findNextTimeSlot(uint32_t currentHour) {
    auto& sync = privateConfig.getSyncWakeup();
    
    if (!sync.has_scheduled_wakeup) return -1;
    
    int earliestIdx = -1;
    uint32_t earliestHour = 25;
    
    for (pb_size_t i = 0; i < sync.scheduled_wakeup.time_slots_count; i++) {
        auto& slot = sync.scheduled_wakeup.time_slots[i];
        if (slot.start_hour > currentHour && slot.start_hour < earliestHour) {
            earliestIdx = i;
            earliestHour = slot.start_hour;
        }
    }
    
    if (earliestIdx < 0) {
        earliestHour = 25;
        for (pb_size_t i = 0; i < sync.scheduled_wakeup.time_slots_count; i++) {
            auto& slot = sync.scheduled_wakeup.time_slots[i];
            if (slot.start_hour < earliestHour) {
                earliestIdx = i;
                earliestHour = slot.start_hour;
            }
        }
    }
    
    return earliestIdx;
}

bool DraginoWakeupScheduler::isRtcQualitySufficient()
{
    return getRTCQuality() >= RTCQualityDevice;
}

void DraginoWakeupScheduler::maybeRequestGatewayTime()
{
    if (timeRequestSentThisWake_) {
        return;
    }

#if defined(DRAGINO) && defined(MESHTASTIC_EXCLUDE_GPS) && !defined(MESHTASTIC_EXCLUDE_TIMESYNC)
    if (!timeSyncModule) {
        LOG_WARN("Wakeup: TimeSyncModule not available");
        return;
    }

    if (!timeSyncModule->shouldRequestTimeFromGateway(DRAGINO_TIME_REQUEST_STALE_SEC)) {
        return;
    }
#else
    LOG_WARN("Wakeup: TimeSyncModule disabled, cannot request gateway time");
    timeRequestSentThisWake_ = true;
    return;
#endif

    uint32_t now = millis();
    if (!timeRequestDelayStarted_) {
        timeRequestDelayStarted_ = true;
        timeRequestDelayStartMs_ = now;

        if ((uint32_t)DRAGINO_TIME_REQUEST_STARTUP_DELAY_MS > 0) {
            LOG_INFO("Wakeup: delaying gateway time request %u ms", (uint32_t)DRAGINO_TIME_REQUEST_STARTUP_DELAY_MS);
            return;
        }
    }

    if ((uint32_t)(now - timeRequestDelayStartMs_) < (uint32_t)DRAGINO_TIME_REQUEST_STARTUP_DELAY_MS) {
        return;
    }

    timeRequestSentThisWake_ = true;

#if defined(DRAGINO) && defined(MESHTASTIC_EXCLUDE_GPS) && !defined(MESHTASTIC_EXCLUDE_TIMESYNC)
    if (!timeSyncModule->requestTimeFromGateway()) {
        LOG_WARN("Wakeup: gateway time request failed");
    }
#endif
}

uint32_t DraginoWakeupScheduler::getCurrentHour() {
    return (getTime() % 86400) / 3600;
}

uint32_t DraginoWakeupScheduler::getTodaySeconds() {
    return getTime() % 86400;
}

const char* DraginoWakeupScheduler::getCurrentStrategyDesc() {
    if (!privateConfig.hasSyncWakeup()) return "Not configured";
    
    auto& sync = privateConfig.getSyncWakeup();
    if (!sync.enabled) return "Disabled";
    
    return (sync.strategy == temeshtastic_SyncWakeupConfig_WakeupStrategy_STRATEGY_FIXED) 
        ? "Fixed interval" : "Scheduled";
}

void DraginoWakeupScheduler::getCurrentTimeSlotInfo(uint32_t& intervalMin, uint32_t& alignMinute) {
    intervalMin = 60;
    alignMinute = 0;
    
    if (!privateConfig.isSyncWakeupEnabled()) return;
    
    auto& sync = privateConfig.getSyncWakeup();
    if (sync.strategy == temeshtastic_SyncWakeupConfig_WakeupStrategy_STRATEGY_FIXED) {
        if (sync.has_fixed_wakeup) {
            intervalMin = sync.fixed_wakeup.interval_min;
            alignMinute = sync.fixed_wakeup.align_minute;
        }
    } else if (sync.has_scheduled_wakeup) {
        int slotIdx = findCurrentTimeSlot();
        if (slotIdx >= 0) {
            intervalMin = sync.scheduled_wakeup.time_slots[slotIdx].interval_min;
            alignMinute = sync.scheduled_wakeup.time_slots[slotIdx].align_minute;
        }
    }
}

DraginoWakeupScheduler& draginoWakeupScheduler = DraginoWakeupScheduler::instance();

}

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
