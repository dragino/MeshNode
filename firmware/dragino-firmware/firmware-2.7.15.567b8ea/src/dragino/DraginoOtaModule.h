#pragma once

#if defined(DRAGINO_OTA_LAB)

#include "dragino/protobuf/draginoota.pb.h"
#include "mesh/ProtobufModule.h"

#define PRIVATE_DRAGINO_OTA_PORTNUM static_cast<meshtastic_PortNum>(289)

namespace dragino {

class DraginoOtaModule : public ProtobufModule<temeshtastic_DraginoOtaPacket>
{
  public:
    DraginoOtaModule();

  protected:
    bool handleReceivedProtobuf(const meshtastic_MeshPacket &mp, temeshtastic_DraginoOtaPacket *p) override;

  private:
    using OtaPacket = temeshtastic_DraginoOtaPacket;
    using DownlinkPacket = temeshtastic_DraginoOtaPacket_DownlinkPacket;
    using BeginRequest = temeshtastic_DraginoOtaPacket_DownlinkPacket_Begin;
    using ChunkRequest = temeshtastic_DraginoOtaPacket_DownlinkPacket_Chunk;
    using FinalizeRequest = temeshtastic_DraginoOtaPacket_DownlinkPacket_Finalize;
    using AbortRequest = temeshtastic_DraginoOtaPacket_DownlinkPacket_Abort;
    using RebootRequest = temeshtastic_DraginoOtaPacket_DownlinkPacket_Reboot;
    using StatusCode = temeshtastic_DraginoOtaPacket_StatusCode;
    using OtaState = temeshtastic_DraginoOtaPacket_State;

    void handleDownlink(const meshtastic_MeshPacket &mp, const DownlinkPacket &downlink);
    void handleBegin(const meshtastic_MeshPacket &mp, const BeginRequest &req);
    void handleChunk(const meshtastic_MeshPacket &mp, const ChunkRequest &req);
    void handleFinalize(const meshtastic_MeshPacket &mp, const FinalizeRequest &req);
    void handleAbort(const meshtastic_MeshPacket &mp, const AbortRequest &req);
    void handleGetStatus(const meshtastic_MeshPacket &mp);
    void handleReboot(const meshtastic_MeshPacket &mp, const RebootRequest &req);

    void resetSession();
    void sendAck(const meshtastic_MeshPacket &mp,
                 uint32_t sessionId,
                 uint32_t imageId,
                 uint32_t chunkIndex,
                 StatusCode status,
                 const char *message = nullptr);
    void sendStatus(const meshtastic_MeshPacket &mp);
    void sendUplink(const meshtastic_MeshPacket &mp, const OtaPacket &packet);

    bool isSessionMatch(uint32_t sessionId, uint32_t imageId) const;

    bool requestFromUpperComputer_ = false;
    OtaState state_ = temeshtastic_DraginoOtaPacket_State_STATE_IDLE;
    uint32_t sessionId_ = 0;
    uint32_t imageId_ = 0;
    uint32_t imageSize_ = 0;
    uint32_t imageCrc32_ = 0;
    uint32_t chunkSize_ = 0;
    uint32_t totalChunks_ = 0;
    uint32_t writtenSize_ = 0;
    uint32_t nextOffset_ = 0;
    uint32_t nextChunkIndex_ = 0;
    uint32_t lastError_ = 0;
};

extern DraginoOtaModule *draginoOtaModule;

} // namespace dragino

#endif // DRAGINO_OTA_LAB
