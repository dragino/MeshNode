#pragma once


#include "MeshTypes.h"
#include "meshtastic/mesh.pb.h"

namespace dragino
{

struct SendOptions{
    uint32_t to = NODENUM_BROADCAST;
    uint8_t channel = 0;
    uint8_t hopLimit = 3;
    bool wantAck = false;
    bool wantResponse = false;
    meshtastic_PortNum portnum = meshtastic_PortNum_TEXT_MESSAGE_APP;
    meshtastic_MeshPacket_Priority priority = meshtastic_MeshPacket_Priority_RELIABLE;
};


class Sender
{
    private:
         void fillPacket(meshtastic_MeshPacket* p, const uint8_t* data, size_t len, const SendOptions& opts);
    public:
        bool send(const uint8_t* data, size_t len, const SendOptions& opts = {});
        bool sendTo(uint32_t to, const uint8_t* data, size_t len, uint8_t channel = 0);
        bool broadcast(const uint8_t* data, size_t len, uint8_t channel = 0);
};

extern Sender sender;


}



