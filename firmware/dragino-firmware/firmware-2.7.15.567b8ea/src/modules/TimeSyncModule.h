#pragma once

#include "configuration.h"
#include "ProtobufModule.h"
#include "concurrency/OSThread.h"

// Private time synchronization port number (256-511 range for private applications)
#define PRIVATE_TIMESYNC_PORTNUM ((meshtastic_PortNum)286)

/**
 * Lightweight time synchronization module
 * Extracted from PositionModule, handles only time sync functionality
 * 
 * This module is only instantiated when GPS is excluded (MESHTASTIC_EXCLUDE_GPS)
 * to save flash space on constrained devices.
 * 
 * Uses private port number to avoid interference with standard Meshtastic nodes.
 */
class TimeSyncModule : public ProtobufModule<meshtastic_Position>, private concurrency::OSThread
{
public:
    TimeSyncModule();

#ifdef DRAGINO
    bool requestTimeFromGateway();
    bool setTrustedTime(uint32_t epochSeconds);
    bool shouldRequestTimeFromGateway(uint32_t staleSec) const;
#endif

protected:
    virtual bool handleReceivedProtobuf(const meshtastic_MeshPacket &mp, meshtastic_Position *p) override;
    virtual int32_t runOnce() override;

private:
#ifdef DRAGINO_GATEWAY
    void prepareTimeResponse(const meshtastic_MeshPacket &req);
#endif

    bool trySetRtc(meshtastic_Position p, bool isLocal, bool fromTrustedSource);
    bool shouldForceUpdate(uint32_t newTime, bool isLocal);
    bool hasQualityTimesource();
    
    uint32_t lastTimeSync = 0;
    uint32_t syncIntervalMs;
#ifdef DRAGINO
    uint32_t lastTrustedTimeUpdateEpoch_ = 0;
#endif
};

extern TimeSyncModule *timeSyncModule;
