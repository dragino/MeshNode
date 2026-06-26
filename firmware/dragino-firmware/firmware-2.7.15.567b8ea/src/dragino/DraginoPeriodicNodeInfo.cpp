#include "DraginoPeriodicNodeInfo.h"

#include "DraginoDefaultConfig.h"
#include "PrivateConfig.h"
#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
#include "FSCommon.h"
#include "MeshTypes.h"
#include "RTC.h"
#include "SPILock.h"
#include "mesh/NodeDB.h"
#if !MESHTASTIC_EXCLUDE_NODEINFO
#include "modules/NodeInfoModule.h"
#endif
#include <Arduino.h>
#include <stddef.h>
#include <string.h>
#endif

namespace dragino {

DraginoPeriodicNodeInfo draginoPeriodicNodeInfo;

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
namespace {

constexpr const char *kStateFile = "/prefs/periodic_nodeinfo.bin";
constexpr uint32_t kStateMagic = 0x3146494eUL;
constexpr uint16_t kStateVersion = 1;
constexpr uint32_t kFutureSlackSec = 7UL * 24UL * 60UL * 60UL;

uint32_t fnv1a(const uint8_t *data, size_t len)
{
    uint32_t hash = 2166136261UL;
    for (size_t i = 0; i < len; i++) {
        hash ^= data[i];
        hash *= 16777619UL;
    }
    return hash;
}

uint32_t retrySec()
{
    return DRAGINO_PERIODIC_NODEINFO_RETRY_SEC > 0 ? DRAGINO_PERIODIC_NODEINFO_RETRY_SEC
                                                   : DRAGINO_PERIODIC_NODEINFO_MIN_SEC;
}

} // namespace
#endif

void DraginoPeriodicNodeInfo::resetSchedule(const char *reason)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
    ensureLoaded();

    if (!privateConfig.isEnrolled()) {
        state_ = {};
        state_.magic = kStateMagic;
        state_.version = kStateVersion;
        (void)saveState();
        LOG_INFO("Dragino NodeInfo: periodic schedule cleared before enrollment, reason=%s",
                 reason ? reason : "unknown");
        return;
    }

    const uint32_t nowSec = getValidTime(RTCQualityDevice);
    if (nowSec == 0) {
        state_ = {};
        state_.magic = kStateMagic;
        state_.version = kStateVersion;
        (void)saveState();
        LOG_WARN("Dragino NodeInfo: periodic schedule reset deferred, RTC invalid, reason=%s",
                 reason ? reason : "unknown");
        return;
    }

    scheduleNext(nowSec, reason);
#else
    (void)reason;
#endif
}

void DraginoPeriodicNodeInfo::maybeSend(const char *wakeContext, uint32_t remainingAwakeMs)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
#if MESHTASTIC_EXCLUDE_NODEINFO
    (void)wakeContext;
    (void)remainingAwakeMs;
    return;
#else
    if (!privateConfig.isEnrolled()) {
        return;
    }

    const uint32_t nowSec = getValidTime(RTCQualityDevice);
    if (nowSec == 0) {
        LOG_DEBUG("Dragino NodeInfo: periodic skip, RTC invalid, context=%s",
                  wakeContext ? wakeContext : "unknown");
        return;
    }

    ensureLoaded();
    if (!isStateValid(state_) || state_.nextNodeInfoAtSec == 0 || hasUnreasonableFutureTarget(nowSec)) {
        scheduleNext(nowSec, "state-init");
        return;
    }

    if (nowSec < state_.nextNodeInfoAtSec) {
        LOG_DEBUG("Dragino NodeInfo: periodic not due, context=%s due_in=%lu sec",
                  wakeContext ? wakeContext : "unknown",
                  (unsigned long)(state_.nextNodeInfoAtSec - nowSec));
        return;
    }

    if (remainingAwakeMs <= DRAGINO_PERIODIC_NODEINFO_TX_GUARD_MS) {
        LOG_DEBUG("Dragino NodeInfo: periodic due but sleep guard holds, context=%s remaining=%lu ms guard=%lu ms",
                  wakeContext ? wakeContext : "unknown",
                  (unsigned long)remainingAwakeMs,
                  (unsigned long)DRAGINO_PERIODIC_NODEINFO_TX_GUARD_MS);
        return;
    }

    if (!nodeInfoModule) {
        state_.lastNodeInfoSentSec = 0;
        state_.nextNodeInfoAtSec = nowSec + retrySec();
        (void)saveState();
        LOG_WARN("Dragino NodeInfo: module unavailable, retry in %lu sec",
                 (unsigned long)retrySec());
        return;
    }

    LOG_INFO("Dragino NodeInfo: periodic broadcast, context=%s next_was=%lu now=%lu",
             wakeContext ? wakeContext : "unknown",
             (unsigned long)state_.nextNodeInfoAtSec,
             (unsigned long)nowSec);
    nodeInfoModule->sendOurNodeInfo(NODENUM_BROADCAST, false, 0, false);

    state_.lastNodeInfoSentSec = nowSec;
    scheduleNext(nowSec, "sent");
#endif
#else
    (void)wakeContext;
    (void)remainingAwakeMs;
#endif
}

void DraginoPeriodicNodeInfo::ensureLoaded()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
    if (loaded_) {
        return;
    }
    if (!loadState()) {
        state_ = {};
        state_.magic = kStateMagic;
        state_.version = kStateVersion;
    }
    loaded_ = true;
#endif
}

bool DraginoPeriodicNodeInfo::loadState()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
#ifdef FSCom
    concurrency::LockGuard g(spiLock);
    File f = FSCom.open(kStateFile, FILE_O_READ);
    if (!f) {
        return false;
    }

    if (f.size() != sizeof(State)) {
        f.close();
        return false;
    }

    State loaded = {};
    const int bytesRead = f.read(&loaded, sizeof(loaded));
    f.close();
    if (bytesRead != (int)sizeof(loaded)) {
        return false;
    }
    if (!isStateValid(loaded)) {
        LOG_WARN("Dragino NodeInfo: invalid periodic state, reschedule");
        return false;
    }

    state_ = loaded;
    return true;
#else
    return false;
#endif
#else
    return false;
#endif
}

bool DraginoPeriodicNodeInfo::saveState()
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
#ifdef FSCom
    state_.magic = kStateMagic;
    state_.version = kStateVersion;
    state_.reserved = 0;
    state_.checksum = computeChecksum(state_);

    concurrency::LockGuard g(spiLock);
    FSCom.mkdir("/prefs");
    (void)FSCom.remove(kStateFile);
    File f = FSCom.open(kStateFile, FILE_O_WRITE);
    if (!f) {
        LOG_WARN("Dragino NodeInfo: failed to open periodic state for write");
        return false;
    }
    const size_t written = f.write(reinterpret_cast<const uint8_t *>(&state_), sizeof(state_));
    f.flush();
    f.close();
    if (written != sizeof(state_)) {
        LOG_WARN("Dragino NodeInfo: failed to write periodic state");
        return false;
    }
    return true;
#else
    return false;
#endif
#else
    return false;
#endif
}

bool DraginoPeriodicNodeInfo::isStateValid(const State &state) const
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
    return state.magic == kStateMagic && state.version == kStateVersion &&
           state.checksum == computeChecksum(state);
#else
    (void)state;
    return false;
#endif
}

bool DraginoPeriodicNodeInfo::hasUnreasonableFutureTarget(uint32_t nowSec) const
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
    if (state_.nextNodeInfoAtSec <= nowSec) {
        return false;
    }
    const uint32_t maxAheadSec = DRAGINO_PERIODIC_NODEINFO_MAX_SEC + kFutureSlackSec;
    return (state_.nextNodeInfoAtSec - nowSec) > maxAheadSec;
#else
    (void)nowSec;
    return false;
#endif
}

uint32_t DraginoPeriodicNodeInfo::computeNextNodeInfoAt(uint32_t nowSec) const
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
    const uint32_t minSec = DRAGINO_PERIODIC_NODEINFO_MIN_SEC;
    const uint32_t maxSec = DRAGINO_PERIODIC_NODEINFO_MAX_SEC;
    const uint32_t spanSec = maxSec - minSec;
    uint32_t jitterSec = 0;

    if (spanSec > 0) {
        const uint32_t bound = spanSec + 1;
        const uint32_t randomPart = (uint32_t)random((long)bound);
        const uint32_t nodePart = nodeDB ? nodeDB->getNodeNum() * 2654435761UL : 0;
        jitterSec = (randomPart + nodePart + millis()) % bound;
    }

    return nowSec + minSec + jitterSec;
#else
    return nowSec;
#endif
}

uint32_t DraginoPeriodicNodeInfo::computeChecksum(const State &state) const
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
    return fnv1a(reinterpret_cast<const uint8_t *>(&state), offsetof(State, checksum));
#else
    (void)state;
    return 0;
#endif
}

void DraginoPeriodicNodeInfo::scheduleNext(uint32_t nowSec, const char *reason)
{
#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_PERIODIC_NODEINFO_ENABLE
    state_.nextNodeInfoAtSec = computeNextNodeInfoAt(nowSec);
    (void)saveState();
    LOG_INFO("Dragino NodeInfo: periodic next in %lu sec, reason=%s",
             (unsigned long)(state_.nextNodeInfoAtSec - nowSec),
             reason ? reason : "unknown");
#else
    (void)nowSec;
    (void)reason;
#endif
}

} // namespace dragino
