#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "DraginoWakeupComm.h"
#include "DraginoModule.h"
#include "mesh/NodeDB.h"
#include "MeshService.h"
#include "PowerStatus.h"
#include "RTC.h"
#include "PrivateConfig.h"
#include "dragino/protobuf/privateconfig.pb.h"
#include "mesh/generated/meshtastic/telemetry.pb.h"
#include "DraginoConfigModule.h"
namespace dragino {

DraginoWakeupComm* draginoWakeupComm = nullptr;

DraginoWakeupComm::DraginoWakeupComm() 
    : MeshModule("DraginoWakeupComm") {
    draginoWakeupComm = this;
}

void DraginoWakeupComm::setCommandCallback(GatewayCommandCallback cb) {
    onCommand_ = cb;
}

bool DraginoWakeupComm::wantPacket(const meshtastic_MeshPacket* p) {
    return p->decoded.portnum == WAKEUP_PORT;
}

ProcessMessage DraginoWakeupComm::handleReceived(const meshtastic_MeshPacket& mp) {
    if (isFromUs(&mp)) {
        return ProcessMessage::CONTINUE;
    }
    
    if (mp.id == lastRxId_) {
        return ProcessMessage::CONTINUE;
    }
    lastRxId_ = mp.id;
    
    if (mp.decoded.payload.size == 0) {
        return ProcessMessage::CONTINUE;
    }
    
    const uint8_t* data = mp.decoded.payload.bytes;
    size_t len = mp.decoded.payload.size;
    
    GatewayCommandType cmd = (GatewayCommandType)data[0];
    
    LOG_INFO("WakeupComm: received cmd=%d from %u", cmd, mp.from);
    
    // Notify DraginoModule
    if (draginoModule) {
        draginoModule->onGatewayCommandReceived();
    }
    
    // Invoke callback
    if (onCommand_) {
        onCommand_(cmd, len > 1 ? &data[1] : nullptr, len > 1 ? len - 1 : 0);
    }
    
    // TODO: Handle specific commands
    switch (cmd) {
    case GW_CMD_REQUEST_TELEMETRY:
        LOG_INFO("WakeupComm: gateway requests telemetry");
        if (draginoModule) {
            draginoModule->scheduleDataUpload(draginoModule->randomDelay());
        }
        break;
        
    case GW_CMD_SET_CONFIG:
        LOG_INFO("WakeupComm: gateway sets config");
        // TODO: Parse and apply config
        break;
        
    case GW_CMD_SYNC_TIME:
        LOG_INFO("WakeupComm: gateway syncs time");
        // TODO: Sync time from gateway
        break;
        
    case GW_CMD_REBOOT:
        LOG_INFO("WakeupComm: gateway requests reboot");
        NVIC_SystemReset();
        break;
        
    default:
        LOG_WARN("WakeupComm: unknown cmd=%d", cmd);
        break;
    }
    
    return ProcessMessage::CONTINUE;
}

void DraginoWakeupComm::sendTelemetry() {
    LOG_INFO("WakeupComm: sending telemetry");

    meshtastic_Telemetry t = meshtastic_Telemetry_init_zero;
    t.which_variant = meshtastic_Telemetry_device_metrics_tag;
    t.time = getValidTime(RTCQualityFromNet);
    t.variant.device_metrics = meshtastic_DeviceMetrics_init_zero;
    t.variant.device_metrics.has_battery_level = true;
    t.variant.device_metrics.battery_level = powerStatus->getBatteryChargePercent();
    t.variant.device_metrics.has_voltage = true;
    t.variant.device_metrics.voltage = powerStatus->getBatteryVoltageMv() / 1000.0f;

    meshtastic_MeshPacket *p = allocDataPacket();
    p->decoded.portnum = meshtastic_PortNum_TELEMETRY_APP;

    size_t encodedSize = pb_encode_to_bytes(
        p->decoded.payload.bytes,
        sizeof(p->decoded.payload.bytes),
        meshtastic_Telemetry_fields,
        &t
    );

    if (encodedSize > 0) {
        p->decoded.payload.size = encodedSize;
        service->sendToMesh(p);
        LOG_INFO("WakeupComm: sent telemetry, %u bytes", encodedSize);
    } else {
        LOG_WARN("WakeupComm: failed to encode telemetry");
        packetPool.release(p);
    }
}

void DraginoWakeupComm::sendPrivateConfig() {
    temeshtastic_PrivateConfig report = privateConfig.getConfig();
    report.network_config.network_public_key.size = 0;
    report.network_config.network_seed.size = 0;
    memset(report.network_config.network_seed.bytes, 0, sizeof(report.network_config.network_seed.bytes));

    temeshtastic_PrivateConfigPacket packet = temeshtastic_PrivateConfigPacket_init_zero;
    packet.which_packet_type = temeshtastic_PrivateConfigPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_PrivateConfigPacket_UplinkPacket_network_config_tag;
    packet.packet_type.uplink_packet.payload.network_config = report.network_config;

    meshtastic_MeshPacket *p = allocDataPacket();
    p->decoded.portnum = PRIVATE_DRAGINO_CONFIG_PORTNUM;

    size_t encodedSize = pb_encode_to_bytes(
        p->decoded.payload.bytes,
        sizeof(p->decoded.payload.bytes),
        temeshtastic_PrivateConfigPacket_fields,
        &packet
    );

    if (encodedSize > 0) {
        p->decoded.payload.size = encodedSize;
        service->sendToMesh(p);
        LOG_INFO("WakeupComm: sent PrivateConfig report, %u bytes", encodedSize);
    } else {
        LOG_WARN("WakeupComm: failed to encode PrivateConfig report");
        packetPool.release(p);
    }
}

}

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
