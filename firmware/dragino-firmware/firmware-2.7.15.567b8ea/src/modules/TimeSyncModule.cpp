#include "TimeSyncModule.h"

#if defined(MESHTASTIC_EXCLUDE_GPS) && !defined(MESHTASTIC_EXCLUDE_TIMESYNC)

#include "MeshService.h"
#include "MeshTypes.h"
#include "RTC.h"
#include "Router.h"
#include "mesh/Channels.h"
#include "configuration.h"
#include "main.h"
#include "mesh/NodeDB.h"
#include <Throttle.h>

#ifdef DRAGINO
#include "dragino/PrivateConfig.h"
#endif

#ifdef ARCH_STM32WL
#include "platform/stm32wl/lowpower/Stm32RtcManager.h"
#endif

#define DEFAULT_SYNC_INTERVAL_MS (60 * 60 * 1000UL)  // 1 hour

TimeSyncModule *timeSyncModule;

#ifdef DRAGINO
static uint32_t getDraginoGatewayNodeId()
{
    return privateConfig.getPrimaryTrustedGateway();
}
#endif

TimeSyncModule::TimeSyncModule()
    : ProtobufModule("timesync", PRIVATE_TIMESYNC_PORTNUM, &meshtastic_Position_msg),
      concurrency::OSThread("TimeSync")
{
    isPromiscuous = true;
    syncIntervalMs = DEFAULT_SYNC_INTERVAL_MS;
}

bool TimeSyncModule::handleReceivedProtobuf(const meshtastic_MeshPacket &mp, meshtastic_Position *p)
{
    if (!p) {
        return false;
    }

#ifdef DRAGINO_GATEWAY
    bool isTimeRequest = mp.to == nodeDB->getNodeNum() && !isFromUs(&mp) && mp.decoded.want_response && p->time == 0;
    if (isTimeRequest) {
        prepareTimeResponse(mp);
        return true;
    }
#endif

    bool isLocal = isFromUs(&mp);
    
    if (p->time) {
        uint32_t senderId = getFrom(&mp);
        bool fromGateway = false;
#ifdef DRAGINO
        fromGateway = privateConfig.isTrustedTimeSource(senderId);
#endif
        trySetRtc(*p, isLocal, fromGateway);
    }
    
    return false;
}

#ifdef DRAGINO
bool TimeSyncModule::requestTimeFromGateway()
{
    if (!privateConfig.isEnrolled()) {
        LOG_WARN("TimeSyncModule: not enrolled, skip time request");
        return false;
    }

    uint32_t gatewayNodeId = getDraginoGatewayNodeId();
    if (gatewayNodeId == 0) {
        LOG_WARN("TimeSyncModule: no trusted gateway for time request");
        return false;
    }

    if (gatewayNodeId == nodeDB->getNodeNum()) {
        LOG_WARN("TimeSyncModule: invalid gateway node id=0x%08x", gatewayNodeId);
        return false;
    }

    meshtastic_Position req = meshtastic_Position_init_zero;
    req.location_source = meshtastic_Position_LocSource_LOC_INTERNAL;

    meshtastic_MeshPacket *packet = allocDataProtobuf(req);
    if (!packet) {
        LOG_WARN("TimeSyncModule: failed to allocate time request");
        return false;
    }

    packet->to = gatewayNodeId;
    packet->decoded.want_response = true;
    packet->want_ack = false;
    packet->priority = meshtastic_MeshPacket_Priority_RELIABLE;

    service->sendToMesh(packet, RX_SRC_LOCAL, true);
    LOG_INFO("TimeSyncModule: requested time from gateway 0x%08x", gatewayNodeId);
    return true;
}

bool TimeSyncModule::setTrustedTime(uint32_t epochSeconds)
{
    if (epochSeconds == 0) {
        LOG_WARN("TimeSyncModule: reject empty trusted time");
        return false;
    }

    meshtastic_Position p = meshtastic_Position_init_zero;
    p.time = epochSeconds;
    p.location_source = meshtastic_Position_LocSource_LOC_INTERNAL;
    return trySetRtc(p, false, true);
}

bool TimeSyncModule::shouldRequestTimeFromGateway(uint32_t staleSec) const
{
    if (!privateConfig.isEnrolled()) {
        return false;
    }

    if (getDraginoGatewayNodeId() == 0) {
        return false;
    }

    if (getRTCQuality() < RTCQualityDevice) {
        return true;
    }

    uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0 || lastTrustedTimeUpdateEpoch_ == 0) {
        return true;
    }

    if (nowEpoch < lastTrustedTimeUpdateEpoch_) {
        return true;
    }

    return (nowEpoch - lastTrustedTimeUpdateEpoch_) >= staleSec;
}
#endif

#ifdef DRAGINO_GATEWAY
void TimeSyncModule::prepareTimeResponse(const meshtastic_MeshPacket &req)
{
    uint32_t timeValue = getValidTime(RTCQualityDevice);
    if (timeValue == 0) {
        LOG_WARN("TimeSyncModule: no valid time, cannot reply to 0x%08x", getFrom(&req));
        return;
    }

    meshtastic_Position resp = meshtastic_Position_init_zero;
    resp.time = timeValue;
    resp.location_source = meshtastic_Position_LocSource_LOC_INTERNAL;

    myReply = allocDataProtobuf(resp);
    if (!myReply) {
        LOG_WARN("TimeSyncModule: failed to allocate time response");
        return;
    }

    LOG_INFO("TimeSyncModule: reply time=%lu to 0x%08x", timeValue, getFrom(&req));
}
#endif

int32_t TimeSyncModule::runOnce()
{
    uint32_t now = millis();
    
    if (now - lastTimeSync >= syncIntervalMs) {
        lastTimeSync = now;
        
        uint32_t timeValue = getValidTime(RTCQualityNTP);

/*
#ifdef ARCH_STM32WL
        if (timeValue == 0 && rtcManager.isValid()) {
            timeValue = getValidTime(RTCQualityDevice);
            LOG_DEBUG("TimeSyncModule: use device RTC time");
        }
#endif
*/     
        if (timeValue > 0) {

            /*
            meshtastic_Position p = meshtastic_Position_init_default;
            p.time = timeValue;
            p.location_source = meshtastic_Position_LocSource_LOC_INTERNAL;
            
            meshtastic_MeshPacket *packet = allocDataProtobuf(p);
            if (packet) {
                packet->to = NODENUM_BROADCAST;
                packet->priority = meshtastic_MeshPacket_Priority_BACKGROUND;
                // service->sendToMesh(packet, RX_SRC_LOCAL, true);
                LOG_INFO("TimeSyncModule: broadcast time=%lu", timeValue);
            }
            */
        }
    }
    
    return syncIntervalMs;
}

bool TimeSyncModule::trySetRtc(meshtastic_Position p, bool isLocal, bool fromTrustedSource)
{
    if (!isLocal && !fromTrustedSource) {
        LOG_DEBUG("Ignore time from untrusted node");
        return false;
    }
    
    bool forceUpdate = fromTrustedSource || shouldForceUpdate(p.time, isLocal);
    
    if (!forceUpdate && hasQualityTimesource() && !isLocal) {
        LOG_DEBUG("Ignore time from mesh, have quality time source");
        return false;
    }
    
    if (!isLocal && p.location_source < meshtastic_Position_LocSource_LOC_INTERNAL) {
        LOG_DEBUG("Ignore time from mesh, unknown source");
        return false;
    }
    
    struct timeval tv;
    tv.tv_sec = p.time;
    tv.tv_usec = 0;
    
    RTCQuality quality = isLocal ? RTCQualityNTP : RTCQualityFromNet;
    RTCSetResult result = perhapsSetRTC(quality, &tv, forceUpdate);
    
    if (result == RTCSetResultSuccess) {
        LOG_INFO("TimeSyncModule: set time from %s, quality=%s, epoch=%lu%s",
                 isLocal ? "local" : (fromTrustedSource ? "trusted" : "mesh"),
                 isLocal ? "NTP" : "FromNet",
                 p.time,
                 forceUpdate ? " (forced)" : "");

#ifdef DRAGINO
        if (fromTrustedSource) {
            lastTrustedTimeUpdateEpoch_ = p.time;
        }
#endif

#ifdef ARCH_STM32WL
        uint32_t timeOfDay = p.time % 86400;
        if (timeOfDay < 5 || timeOfDay > 86395) {
            LOG_WARN("TimeSyncModule: skip RTC write near midnight rollover (tod=%lu)", timeOfDay);
        } else {
            rtcManager.syncFromSystem();
            LOG_DEBUG("TimeSyncModule: synced to STM32 RTC");
        }
#endif
        return true;
    } else {
        LOG_DEBUG("TimeSyncModule: time update rejected (result=%d)", result);
        return false;
    }
}

bool TimeSyncModule::hasQualityTimesource()
{
    bool setFromPhoneOrNtpToday = lastSetFromPhoneNtpOrGps > 0 && 
        Throttle::isWithinTimespanMs(lastSetFromPhoneNtpOrGps, SEC_PER_DAY * 1000UL);
    
    // Only ignore network time if current time quality >= NTP
    bool hasHighQualityTime = getRTCQuality() >= RTCQualityNTP;
    
    return hasHighQualityTime || setFromPhoneOrNtpToday;
}

bool TimeSyncModule::shouldForceUpdate(uint32_t newTime, bool isLocal)
{
    // Only local phone/NTP/GPS updates should force-correct time drift.
    if (!isLocal) {
        return false;
    }
    
    uint32_t currentTime = getTime();
    if (currentTime == 0) {
        LOG_DEBUG("TimeSyncModule: no current time, force update");
        return true;
    }
    
    int32_t timeDiff = (int32_t)(newTime - currentTime);
    if (timeDiff < 0) {
        timeDiff = -timeDiff;
    }
    
    if (timeDiff > 10) {
        LOG_DEBUG("TimeSyncModule: time diff=%d sec, force update", timeDiff);
        return true;
    }
    
    LOG_DEBUG("TimeSyncModule: time diff=%d sec, ignore minor adjustment", timeDiff);
    return false;
}

#endif // MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_TIMESYNC
