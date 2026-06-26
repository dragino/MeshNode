#include "configuration.h"

#if defined(DRAGINO_GATEWAY)

#include "DraginoBusinessBridge.h"
#include "DraginoBusinessCommon.h"
#include "MeshTypes.h"

namespace dragino {

DraginoBusinessBridge *draginoBusinessBridge = nullptr;

DraginoBusinessBridge::DraginoBusinessBridge()
    : MeshModule("DraginoBusinessBridge")
{
    draginoBusinessBridge = this;
}

void DraginoBusinessBridge::setReceiveCallback(DraginoBusinessBridgeCallback cb)
{
    onReceive_ = cb;
}

bool DraginoBusinessBridge::wantPacket(const meshtastic_MeshPacket *p)
{
    return p->decoded.portnum == DRAGINO_BUSINESS_DATA_PORTNUM;
}

ProcessMessage DraginoBusinessBridge::handleReceived(const meshtastic_MeshPacket &mp)
{
    if (isFromUs(&mp)) {
        return ProcessMessage::CONTINUE;
    }

    if (!isToUs(&mp) && !isBroadcast(mp.to)) {
        LOG_DEBUG("BusinessBridge: ignore non-directed packet to 0x%08x", (unsigned)mp.to);
        return ProcessMessage::CONTINUE;
    }

    uint32_t from = getFrom(&mp);
    if (from == lastRxFrom_ && mp.id == lastRxId_) {
        return ProcessMessage::CONTINUE;
    }
    lastRxFrom_ = from;
    lastRxId_ = mp.id;

    if (mp.decoded.payload.size == 0) {
        return ProcessMessage::CONTINUE;
    }

    LOG_INFO("BusinessBridge: received raw payload from 0x%08x, channel=%u, id=0x%08x, len=%u", (unsigned)from,
             (unsigned)mp.channel, (unsigned)mp.id, (unsigned)mp.decoded.payload.size);

    if (onReceive_) {
        DraginoBusinessBridgeMessage msg = {};
        msg.from = from;
        msg.id = mp.id;
        msg.channel = mp.channel;
        msg.rxTime = mp.rx_time;
        msg.payload = mp.decoded.payload.bytes;
        msg.payloadSize = mp.decoded.payload.size;
        onReceive_(msg);
    }

    return ProcessMessage::CONTINUE;
}

} // namespace dragino

#endif // defined(DRAGINO_GATEWAY)
