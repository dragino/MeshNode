#pragma once

#include "dragino/protobuf/privateconfig.pb.h"
#include <functional>

namespace dragino {

class DraginoWakeupScheduler {
public:
    static DraginoWakeupScheduler& instance();
    
    void init();
    
    uint32_t calcNextWakeupMs(bool allowGatewayTimeRequest = true);
    
    const char* getCurrentStrategyDesc();
    
    void getCurrentTimeSlotInfo(uint32_t& intervalMin, uint32_t& alignMinute);
    
    void onConfigChanged();
    void onWakeSessionStart();

    bool isRtcQualitySufficient();
private:
    DraginoWakeupScheduler() = default;
    
    uint32_t calcFixedStrategyMs();
    uint32_t calcScheduledStrategyMs();
    
    int findCurrentTimeSlot();
    int findNextTimeSlot(uint32_t currentHour);
    
    void maybeRequestGatewayTime();

    uint32_t calcAlignWakeupMs(uint32_t intervalMin, uint32_t alignMinute, uint32_t offsetSec);
    
    uint32_t getCurrentHour();
    uint32_t getTodaySeconds();

    bool timeRequestSentThisWake_ = false;
    bool timeRequestDelayStarted_ = false;
    uint32_t timeRequestDelayStartMs_ = 0;
    uint32_t lastLowRtcWarnMs_ = 0;
    
};

extern DraginoWakeupScheduler& draginoWakeupScheduler;

}
