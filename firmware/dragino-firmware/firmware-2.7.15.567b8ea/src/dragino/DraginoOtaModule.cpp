#include "DraginoOtaModule.h"

#if defined(DRAGINO_OTA_LAB)

#include "MeshService.h"
#include "mesh/NodeDB.h"
#include <ErriezCRC32.h>
#include <string.h>

namespace dragino {

DraginoOtaModule *draginoOtaModule = nullptr;

namespace {

bool isLoRaTransport(const meshtastic_MeshPacket &mp)
{
    return mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA_ALT1 ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA_ALT2 ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_LORA_ALT3;
}

bool isRemoteTransport(const meshtastic_MeshPacket &mp)
{
    return isLoRaTransport(mp) ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_MQTT ||
           mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_MULTICAST_UDP;
}

bool isUpperComputerRequest(const meshtastic_MeshPacket &mp)
{
    return mp.from == 0 && !isRemoteTransport(mp);
}

void copyMessage(char *dest, size_t destSize, const char *message)
{
    if (!dest || destSize == 0) {
        return;
    }
    if (!message) {
        dest[0] = '\0';
        return;
    }

    strncpy(dest, message, destSize - 1);
    dest[destSize - 1] = '\0';
}

} // namespace

DraginoOtaModule::DraginoOtaModule()
    : ProtobufModule("DraginoOtaModule", PRIVATE_DRAGINO_OTA_PORTNUM, temeshtastic_DraginoOtaPacket_fields)
{
    draginoOtaModule = this;
}

bool DraginoOtaModule::handleReceivedProtobuf(const meshtastic_MeshPacket &mp, temeshtastic_DraginoOtaPacket *p)
{
    requestFromUpperComputer_ = false;
    ignoreRequest = false;

    if (!p) {
        LOG_ERROR("DraginoOta: decode failed");
        return false;
    }

    const uint32_t myNodeNum = nodeDB->getNodeNum();
    const bool isToMe = mp.to == myNodeNum;
    const bool isBroadcastDest = isBroadcast(mp.to);

    requestFromUpperComputer_ = isUpperComputerRequest(mp);
    if (requestFromUpperComputer_) {
        if (!isToMe && !isBroadcastDest) {
            LOG_DEBUG("DraginoOta: phone packet not for me, to=0x%x, my=0x%x", mp.to, myNodeNum);
            return true;
        }
    } else {
        if (mp.from == 0 && isRemoteTransport(mp)) {
            LOG_WARN("DraginoOta: reject remote from=0 packet");
            ignoreRequest = true;
            return true;
        }
        if (isFromUs(&mp)) {
            return true;
        }
        if (!isToMe && !isBroadcastDest) {
            LOG_DEBUG("DraginoOta: mesh packet not for me, to=0x%08x, my=0x%08x", mp.to, myNodeNum);
            return true;
        }
    }

    if (p->which_packet_type == temeshtastic_DraginoOtaPacket_uplink_packet_tag) {
        if (isToMe) {
            service->sendToPhone(packetPool.allocCopy(mp));
        }
        return true;
    }

    if (p->which_packet_type != temeshtastic_DraginoOtaPacket_downlink_packet_tag) {
        LOG_WARN("DraginoOta: unknown packet type=%d", p->which_packet_type);
        return true;
    }

    handleDownlink(mp, p->packet_type.downlink_packet);
    return true;
}

void DraginoOtaModule::handleDownlink(const meshtastic_MeshPacket &mp, const DownlinkPacket &downlink)
{
    switch (downlink.which_payload) {
    case temeshtastic_DraginoOtaPacket_DownlinkPacket_begin_tag:
        handleBegin(mp, downlink.payload.begin);
        break;
    case temeshtastic_DraginoOtaPacket_DownlinkPacket_chunk_tag:
        handleChunk(mp, downlink.payload.chunk);
        break;
    case temeshtastic_DraginoOtaPacket_DownlinkPacket_finalize_tag:
        handleFinalize(mp, downlink.payload.finalize);
        break;
    case temeshtastic_DraginoOtaPacket_DownlinkPacket_abort_tag:
        handleAbort(mp, downlink.payload.abort);
        break;
    case temeshtastic_DraginoOtaPacket_DownlinkPacket_get_status_tag:
        handleGetStatus(mp);
        break;
    case temeshtastic_DraginoOtaPacket_DownlinkPacket_reboot_tag:
        handleReboot(mp, downlink.payload.reboot);
        break;
    default:
        LOG_WARN("DraginoOta: unknown downlink payload=%d", downlink.which_payload);
        sendAck(mp,
                sessionId_,
                imageId_,
                nextChunkIndex_,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_UNSUPPORTED,
                "unsupported");
        break;
    }
}

void DraginoOtaModule::handleBegin(const meshtastic_MeshPacket &mp, const BeginRequest &req)
{
    if (req.session_id == 0 || req.image_id == 0 || req.image_size == 0 || req.chunk_size == 0 || req.total_chunks == 0) {
        lastError_ = temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_IMAGE;
        state_ = temeshtastic_DraginoOtaPacket_State_STATE_FAILED;
        sendAck(mp,
                req.session_id,
                req.image_id,
                0,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_IMAGE,
                "bad begin");
        return;
    }

    constexpr uint32_t maxChunkDataSize = sizeof(req.data.bytes);
    if (req.chunk_size > maxChunkDataSize) {
        lastError_ = temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_IMAGE;
        state_ = temeshtastic_DraginoOtaPacket_State_STATE_FAILED;
        sendAck(mp,
                req.session_id,
                req.image_id,
                0,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_IMAGE,
                "chunk too large");
        return;
    }

    resetSession();
    state_ = temeshtastic_DraginoOtaPacket_State_STATE_RECEIVING;
    sessionId_ = req.session_id;
    imageId_ = req.image_id;
    imageSize_ = req.image_size;
    imageCrc32_ = req.image_crc32;
    chunkSize_ = req.chunk_size;
    totalChunks_ = req.total_chunks;

    LOG_INFO("DraginoOta: begin session=0x%08x image=0x%08x size=%u chunk=%u total=%u",
             sessionId_,
             imageId_,
             imageSize_,
             chunkSize_,
             totalChunks_);
    sendAck(mp, sessionId_, imageId_, 0, temeshtastic_DraginoOtaPacket_StatusCode_STATUS_OK, "begin ok");
}

void DraginoOtaModule::handleChunk(const meshtastic_MeshPacket &mp, const ChunkRequest &req)
{
    if (!isSessionMatch(req.session_id, req.image_id)) {
        sendAck(mp,
                req.session_id,
                req.image_id,
                req.chunk_index,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_SESSION,
                "bad session");
        return;
    }

    if (state_ != temeshtastic_DraginoOtaPacket_State_STATE_RECEIVING) {
        sendAck(mp,
                req.session_id,
                req.image_id,
                req.chunk_index,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BUSY,
                "not receiving");
        return;
    }

    if (req.chunk_index != nextChunkIndex_ || req.offset != nextOffset_) {
        lastError_ = temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_OFFSET;
        sendAck(mp,
                req.session_id,
                req.image_id,
                req.chunk_index,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_OFFSET,
                "bad offset");
        return;
    }

    if (req.data.size == 0 || req.data.size > chunkSize_ || req.offset + req.data.size > imageSize_) {
        lastError_ = temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_IMAGE;
        sendAck(mp,
                req.session_id,
                req.image_id,
                req.chunk_index,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_IMAGE,
                "bad chunk");
        return;
    }

    const uint32_t actualCrc = crc32Buffer(req.data.bytes, req.data.size);
    if (actualCrc != req.chunk_crc32) {
        lastError_ = temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_CRC;
        sendAck(mp,
                req.session_id,
                req.image_id,
                req.chunk_index,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_CRC,
                "bad crc");
        return;
    }

    writtenSize_ += req.data.size;
    nextOffset_ += req.data.size;
    nextChunkIndex_++;
    lastError_ = 0;

    sendAck(mp,
            req.session_id,
            req.image_id,
            req.chunk_index,
            temeshtastic_DraginoOtaPacket_StatusCode_STATUS_OK,
            "chunk ok");
}

void DraginoOtaModule::handleFinalize(const meshtastic_MeshPacket &mp, const FinalizeRequest &req)
{
    if (!isSessionMatch(req.session_id, req.image_id)) {
        sendAck(mp,
                req.session_id,
                req.image_id,
                nextChunkIndex_,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_SESSION,
                "bad session");
        return;
    }

    if (writtenSize_ != imageSize_ || nextChunkIndex_ != totalChunks_) {
        lastError_ = temeshtastic_DraginoOtaPacket_StatusCode_STATUS_NOT_READY;
        sendAck(mp,
                req.session_id,
                req.image_id,
                nextChunkIndex_,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_NOT_READY,
                "not complete");
        return;
    }

    state_ = temeshtastic_DraginoOtaPacket_State_STATE_READY_TO_REBOOT;
    lastError_ = 0;
    LOG_INFO("DraginoOta: finalize session=0x%08x image=0x%08x crc=0x%08x", sessionId_, imageId_, imageCrc32_);
    sendAck(mp,
            req.session_id,
            req.image_id,
            nextChunkIndex_,
            temeshtastic_DraginoOtaPacket_StatusCode_STATUS_OK,
            "finalize ok");
}

void DraginoOtaModule::handleAbort(const meshtastic_MeshPacket &mp, const AbortRequest &req)
{
    if (!isSessionMatch(req.session_id, req.image_id)) {
        sendAck(mp,
                req.session_id,
                req.image_id,
                nextChunkIndex_,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_SESSION,
                "bad session");
        return;
    }

    resetSession();
    sendAck(mp,
            req.session_id,
            req.image_id,
            0,
            temeshtastic_DraginoOtaPacket_StatusCode_STATUS_OK,
            "abort ok");
}

void DraginoOtaModule::handleGetStatus(const meshtastic_MeshPacket &mp)
{
    sendStatus(mp);
}

void DraginoOtaModule::handleReboot(const meshtastic_MeshPacket &mp, const RebootRequest &req)
{
    if (!isSessionMatch(req.session_id, req.image_id)) {
        sendAck(mp,
                req.session_id,
                req.image_id,
                nextChunkIndex_,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_BAD_SESSION,
                "bad session");
        return;
    }

    if (state_ != temeshtastic_DraginoOtaPacket_State_STATE_READY_TO_REBOOT) {
        sendAck(mp,
                req.session_id,
                req.image_id,
                nextChunkIndex_,
                temeshtastic_DraginoOtaPacket_StatusCode_STATUS_NOT_READY,
                "not ready");
        return;
    }

    sendAck(mp,
            req.session_id,
            req.image_id,
            nextChunkIndex_,
            temeshtastic_DraginoOtaPacket_StatusCode_STATUS_UNSUPPORTED,
            "reboot disabled");
}

void DraginoOtaModule::resetSession()
{
    state_ = temeshtastic_DraginoOtaPacket_State_STATE_IDLE;
    sessionId_ = 0;
    imageId_ = 0;
    imageSize_ = 0;
    imageCrc32_ = 0;
    chunkSize_ = 0;
    totalChunks_ = 0;
    writtenSize_ = 0;
    nextOffset_ = 0;
    nextChunkIndex_ = 0;
    lastError_ = 0;
}

void DraginoOtaModule::sendAck(const meshtastic_MeshPacket &mp,
                               uint32_t sessionId,
                               uint32_t imageId,
                               uint32_t chunkIndex,
                               StatusCode status,
                               const char *message)
{
    OtaPacket packet = temeshtastic_DraginoOtaPacket_init_zero;
    packet.which_packet_type = temeshtastic_DraginoOtaPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_DraginoOtaPacket_UplinkPacket_ack_tag;

    auto &ack = packet.packet_type.uplink_packet.payload.ack;
    ack.session_id = sessionId;
    ack.image_id = imageId;
    ack.chunk_index = chunkIndex;
    ack.status = status;
    copyMessage(ack.message, sizeof(ack.message), message);

    sendUplink(mp, packet);
}

void DraginoOtaModule::sendStatus(const meshtastic_MeshPacket &mp)
{
    OtaPacket packet = temeshtastic_DraginoOtaPacket_init_zero;
    packet.which_packet_type = temeshtastic_DraginoOtaPacket_uplink_packet_tag;
    packet.packet_type.uplink_packet.which_payload = temeshtastic_DraginoOtaPacket_UplinkPacket_status_tag;

    auto &status = packet.packet_type.uplink_packet.payload.status;
    status.session_id = sessionId_;
    status.image_id = imageId_;
    status.state = state_;
    status.image_size = imageSize_;
    status.written_size = writtenSize_;
    status.next_offset = nextOffset_;
    status.last_error = lastError_;

    sendUplink(mp, packet);
}

void DraginoOtaModule::sendUplink(const meshtastic_MeshPacket &mp, const OtaPacket &packet)
{
    meshtastic_MeshPacket *reply = allocDataProtobuf(packet);
    if (!reply) {
        LOG_WARN("DraginoOta: failed to allocate uplink");
        return;
    }

    if (requestFromUpperComputer_) {
        ignoreRequest = true;
        service->sendToPhone(reply);
        requestFromUpperComputer_ = false;
    } else {
        if (mp.pki_encrypted) {
            reply->pki_encrypted = true;
        }
        myReply = reply;
    }
}

bool DraginoOtaModule::isSessionMatch(uint32_t sessionId, uint32_t imageId) const
{
    return sessionId_ != 0 && imageId_ != 0 && sessionId == sessionId_ && imageId == imageId_;
}

} // namespace dragino

#endif // DRAGINO_OTA_LAB
