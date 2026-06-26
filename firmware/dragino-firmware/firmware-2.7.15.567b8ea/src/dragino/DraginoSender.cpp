#include "DraginoSender.h"
#include "Router.h"
#include "MeshService.h"

namespace dragino
{

Sender sender;

bool Sender::send(const uint8_t* data, size_t len, const SendOptions& opts)
{
    if (!data || len == 0) {
        LOG_ERROR("dragino::Sender: Invalid data or length");
        return false;
    }

    if (!router) {
        LOG_ERROR("dragino::Sender: Router not ready");
        return false;
    }

    if (len > meshtastic_Constants_DATA_PAYLOAD_LEN) {
        LOG_ERROR("dragino::Sender: Data too large (max %d)", meshtastic_Constants_DATA_PAYLOAD_LEN);
        return false;
    }
    
    if (!service) {
        LOG_ERROR("dragino::Sender: Service not ready");
        return false;
    }
    
    meshtastic_MeshPacket* p = router->allocForSending();
    if (!p) {
        LOG_ERROR("dragino::Sender: Failed to allocate packet");
        return false;
    }

    fillPacket(p, data, len, opts);
    
    service->sendToMesh(p, RX_SRC_LOCAL, true);
    return true;

}


bool Sender::sendTo(uint32_t to, const uint8_t* data, size_t len, uint8_t channel) {
    SendOptions opts;
    opts.to = to;
    opts.channel = channel;
    opts.wantAck = false;
    opts.wantResponse = false;
    return send(data, len, opts);
}


bool Sender::broadcast(const uint8_t* data, size_t len, uint8_t channel) {
    SendOptions opts;
    opts.to = NODENUM_BROADCAST;
    opts.channel = channel;
    return send(data, len, opts);
}

void Sender::fillPacket(meshtastic_MeshPacket* p, const uint8_t* data, size_t len, const SendOptions& opts) {
    bool directed = !isBroadcast(opts.to);
    p->to = opts.to;
    p->channel = opts.channel;
    p->hop_limit = opts.hopLimit;
    p->want_ack = directed && opts.wantAck;
    p->decoded.want_response = directed && opts.wantResponse;
    p->decoded.portnum = opts.portnum;
    p->priority = opts.priority;
    
    memcpy(p->decoded.payload.bytes, data, len);
    p->decoded.payload.size = len;
}





}


