#pragma once

#include <stdint.h>

namespace dragino {

class DraginoPeriodicNodeInfo {
  public:
    void resetSchedule(const char *reason);
    void maybeSend(const char *wakeContext, uint32_t remainingAwakeMs = UINT32_MAX);

  private:
    struct State {
        uint32_t magic;
        uint16_t version;
        uint16_t reserved;
        uint32_t nextNodeInfoAtSec;
        uint32_t lastNodeInfoSentSec;
        uint32_t checksum;
    };

    void ensureLoaded();
    bool loadState();
    bool saveState();
    bool isStateValid(const State &state) const;
    bool hasUnreasonableFutureTarget(uint32_t nowSec) const;
    uint32_t computeNextNodeInfoAt(uint32_t nowSec) const;
    uint32_t computeChecksum(const State &state) const;
    void scheduleNext(uint32_t nowSec, const char *reason);

    bool loaded_ = false;
    State state_ = {};
};

extern DraginoPeriodicNodeInfo draginoPeriodicNodeInfo;

} // namespace dragino
