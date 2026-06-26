#pragma once

#include "configuration.h"

#if defined(DRAGINO_GATEWAY)

#include "MeshModule.h"
#include <functional>
#include <stddef.h>
#include <stdint.h>

namespace dragino {

struct DraginoBusinessBridgeMessage {
    uint32_t from;
    uint32_t id;
    uint8_t channel;
    int32_t rxTime;
    const uint8_t *payload;
    size_t payloadSize;
};

using DraginoBusinessBridgeCallback = std::function<void(const DraginoBusinessBridgeMessage &msg)>;

class DraginoBusinessBridge : public MeshModule
{
  public:
    DraginoBusinessBridge();

    void setReceiveCallback(DraginoBusinessBridgeCallback cb);

  protected:
    bool wantPacket(const meshtastic_MeshPacket *p) override;
    ProcessMessage handleReceived(const meshtastic_MeshPacket &mp) override;

  private:
    uint32_t lastRxFrom_ = 0;
    uint32_t lastRxId_ = 0;
    DraginoBusinessBridgeCallback onReceive_;
};

extern DraginoBusinessBridge *draginoBusinessBridge;

} // namespace dragino

#endif // defined(DRAGINO_GATEWAY)
