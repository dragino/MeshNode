#pragma once

#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "MeshModule.h"
#include "Router.h"
#include "meshtastic/mesh.pb.h"
#include <functional>

namespace dragino {

enum GatewayCommandType : uint8_t {
    GW_CMD_NONE = 0,
    GW_CMD_REQUEST_TELEMETRY = 1,
    GW_CMD_SET_CONFIG = 2,
    GW_CMD_SYNC_TIME = 3,
    GW_CMD_REBOOT = 4
};

using GatewayCommandCallback = std::function<void(GatewayCommandType cmd, const uint8_t* data, size_t len)>;

class DraginoWakeupComm : public MeshModule {
public:
    DraginoWakeupComm();
    
    void setCommandCallback(GatewayCommandCallback cb);
    void sendTelemetry();
    void sendPrivateConfig();
    
protected:
    ProcessMessage handleReceived(const meshtastic_MeshPacket& mp) override;
    bool wantPacket(const meshtastic_MeshPacket* p) override;
    
    meshtastic_MeshPacket* allocDataPacket() {
        meshtastic_MeshPacket* p = router->allocForSending();
        p->decoded.portnum = WAKEUP_PORT;
        return p;
    }

private:
    uint32_t lastRxId_ = 0;
    GatewayCommandCallback onCommand_;
    
    static constexpr meshtastic_PortNum WAKEUP_PORT = (meshtastic_PortNum)288;
};

extern DraginoWakeupComm* draginoWakeupComm;

}

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
