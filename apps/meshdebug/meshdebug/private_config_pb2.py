"""
Runtime protobuf definitions for Dragino privateconfig.proto.

This module intentionally avoids a protoc build step.  It mirrors the current
firmware protocol used on PRIVATE_CONFIG_APP (port 287):

    PrivateConfigPacket.downlink_packet / uplink_packet

Only field numbers and wire types matter for interoperability with firmware.
The helper encoders below build packets using the current protocol while keeping
some legacy function names available so the old debug UI can fail clearly
instead of sending obsolete company/request/response packets.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2 as _dpb2
from google.protobuf import descriptor_pool as _pool_mod
from google.protobuf.message_factory import GetMessages as _GetMessages

_BOOL = _dpb2.FieldDescriptorProto.TYPE_BOOL
_UINT32 = _dpb2.FieldDescriptorProto.TYPE_UINT32
_UINT64 = _dpb2.FieldDescriptorProto.TYPE_UINT64
_INT32 = _dpb2.FieldDescriptorProto.TYPE_INT32
_BYTES = _dpb2.FieldDescriptorProto.TYPE_BYTES
_STRING = _dpb2.FieldDescriptorProto.TYPE_STRING
_MSG = _dpb2.FieldDescriptorProto.TYPE_MESSAGE
_ENUM = _dpb2.FieldDescriptorProto.TYPE_ENUM
_OPT = _dpb2.FieldDescriptorProto.LABEL_OPTIONAL
_RPT = _dpb2.FieldDescriptorProto.LABEL_REPEATED


def _field(msg, name, number, ftype, label=_OPT, type_name=None, oneof_index=None):
    f = msg.field.add()
    f.name = name
    f.number = number
    f.type = ftype
    f.label = label
    if type_name:
        f.type_name = type_name
    if oneof_index is not None:
        f.oneof_index = oneof_index
    return f


def _enum_val(enum, name, number):
    v = enum.value.add()
    v.name = name
    v.number = number


def _add_enum(fdp, name, values):
    enum = fdp.enum_type.add()
    enum.name = name
    for value_name, value_number in values:
        _enum_val(enum, value_name, value_number)
    return enum


def _add_msg(fdp, name):
    msg = fdp.message_type.add()
    msg.name = name
    return msg


def _build_fdp() -> _dpb2.FileDescriptorProto:
    fdp = _dpb2.FileDescriptorProto()
    fdp.name = "temeshtastic/privateconfig_runtime.proto"
    fdp.package = "temeshtastic"
    fdp.syntax = "proto3"

    _add_enum(
        fdp,
        "DeviceFactoryIdentity_FactoryIdentityStatus",
        [
            ("FACTORY_IDENTITY_EMPTY", 0),
            ("FACTORY_IDENTITY_VALID", 1),
            ("FACTORY_IDENTITY_CRC_ERROR", 2),
            ("FACTORY_IDENTITY_INVALID_FORMAT", 3),
            ("FACTORY_IDENTITY_LOCKED", 4),
        ],
    )
    _add_enum(
        fdp,
        "SyncWakeupConfig_WakeupStrategy",
        [
            ("STRATEGY_FIXED", 0),
            ("STRATEGY_SCHEDULED", 1),
        ],
    )
    _add_enum(
        fdp,
        "PrivateConfigPacket_SetNetWorkConfig_ResetType",
        [
            ("RESET_TYPE_NONE", 0),
            ("RESET_TYPE_FACTORY", 1),
            ("RESET_TYPE_NETWORK", 2),
        ],
    )
    _add_enum(
        fdp,
        "PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabelAction",
        [
            ("ADD", 0),
            ("UPDATE", 1),
            ("DELETE", 2),
        ],
    )
    _add_enum(
        fdp,
        "PrivateConfigPacket_OperationResult_Operation",
        [
            ("OPERATION_UNKNOWN", 0),
            ("OPERATION_SET_FACTORY_IDENTITY", 1),
            ("OPERATION_GET_FACTORY_IDENTITY", 2),
            ("OPERATION_CHANNEL12_CONFIG", 3),
            ("OPERATION_JOIN_NETWORK_V2", 4),
            ("OPERATION_CHANGE_ADMIN", 5),
            ("OPERATION_RESET_NETWORK_CONFIG", 6),
            ("OPERATION_CHANGE_NETWORK_KEY", 7),
            ("OPERATION_TRUSTED_GATEWAY_CONFIG", 8),
            ("OPERATION_SYNC_WAKEUP_CONFIG", 9),
            ("OPERATION_INFO_LABEL_CONFIG", 10),
            ("OPERATION_ENTER_BOOTLOADER", 11),
        ],
    )
    _add_enum(
        fdp,
        "PrivateConfigPacket_EnterBootloader_BootloaderReason",
        [
            ("BOOTLOADER_REASON_UNKNOWN", 0),
            ("BOOTLOADER_REASON_SERIAL", 1),
            ("BOOTLOADER_REASON_BLUETOOTH", 2),
            ("BOOTLOADER_REASON_UPPER_COMPUTER", 3),
            ("BOOTLOADER_REASON_TEST", 4),
        ],
    )
    _add_enum(
        fdp,
        "PrivateConfigPacket_OperationResult_Status",
        [
            ("STATUS_UNKNOWN", 0),
            ("STATUS_OK", 1),
            ("STATUS_NO_CHANGE", 2),
            ("STATUS_PENDING_CHANNEL12", 3),
            ("STATUS_ALREADY_ENROLLED", 4),
            ("STATUS_NOT_ENROLLED", 5),
            ("STATUS_NOT_AUTHORIZED", 6),
            ("STATUS_BAD_AUTH_CODE", 7),
            ("STATUS_STALE_NONCE", 8),
            ("STATUS_INVALID_STATE", 9),
            ("STATUS_INVALID_SIZE", 10),
            ("STATUS_INVALID_ARGUMENT", 11),
            ("STATUS_SAVE_FAILED", 12),
            ("STATUS_UNSUPPORTED", 13),
        ],
    )

    msg = _add_msg(fdp, "JoinLockAdvertise")
    _field(msg, "join_challenge", 1, _BYTES)
    _field(msg, "dev_eui_hi", 2, _UINT32)
    _field(msg, "dev_eui_lo", 3, _UINT32)
    _field(msg, "sn", 4, _STRING)

    msg = _add_msg(fdp, "DeviceFactoryIdentity")
    _field(msg, "factory_version", 1, _UINT32)
    _field(msg, "sn", 2, _STRING)
    _field(msg, "dev_eui_hi", 3, _UINT32)
    _field(msg, "dev_eui_lo", 4, _UINT32)
    _field(msg, "device_private_key", 5, _BYTES)
    _field(msg, "manufacturing_timestamp", 6, _UINT64)
    _field(
        msg,
        "status",
        7,
        _ENUM,
        type_name=".temeshtastic.DeviceFactoryIdentity_FactoryIdentityStatus",
    )
    _field(msg, "identity_crc", 8, _UINT32)
    _field(msg, "legacy_app_key", 9, _BYTES)

    msg = _add_msg(fdp, "NetWorkConfig")
    _field(msg, "network_public_key", 1, _BYTES)
    _field(msg, "last_change_timestamp", 2, _UINT64)
    _field(msg, "is_single_gateway", 3, _BOOL)
    _field(msg, "trusted_gateway_sources", 4, _UINT32, label=_RPT)
    _field(msg, "network_seed", 5, _BYTES)

    msg = _add_msg(fdp, "SyncWakeupConfig_TimeSlot")
    _field(msg, "start_hour", 1, _UINT32)
    _field(msg, "end_hour", 2, _UINT32)
    _field(msg, "interval_min", 3, _UINT32)
    _field(msg, "align_minute", 4, _UINT32)

    msg = _add_msg(fdp, "SyncWakeupConfig_FixedWakeup")
    _field(msg, "interval_min", 1, _UINT32)
    _field(msg, "align_minute", 2, _UINT32)
    _field(msg, "offset_sec", 3, _UINT32)

    msg = _add_msg(fdp, "SyncWakeupConfig_ScheduledWakeup")
    _field(msg, "offset_sec", 1, _UINT32)
    _field(
        msg,
        "time_slots",
        2,
        _MSG,
        label=_RPT,
        type_name=".temeshtastic.SyncWakeupConfig_TimeSlot",
    )

    msg = _add_msg(fdp, "SyncWakeupConfig_WakeupWindow")
    _field(msg, "startup_delay_sec", 1, _UINT32)
    _field(msg, "random_delay_max_sec", 2, _UINT32)
    _field(msg, "gateway_wait_sec", 3, _UINT32)
    _field(msg, "final_wait_sec", 4, _UINT32)
    _field(msg, "degraded_window_sec", 5, _UINT32)
    _field(msg, "factory_window_sec", 6, _UINT32)

    msg = _add_msg(fdp, "SyncWakeupConfig")
    _field(msg, "enabled", 1, _BOOL)
    _field(
        msg,
        "strategy",
        2,
        _ENUM,
        type_name=".temeshtastic.SyncWakeupConfig_WakeupStrategy",
    )
    _field(
        msg,
        "fixed_wakeup",
        3,
        _MSG,
        type_name=".temeshtastic.SyncWakeupConfig_FixedWakeup",
    )
    _field(
        msg,
        "scheduled_wakeup",
        4,
        _MSG,
        type_name=".temeshtastic.SyncWakeupConfig_ScheduledWakeup",
    )
    _field(
        msg,
        "wakeup_window",
        5,
        _MSG,
        type_name=".temeshtastic.SyncWakeupConfig_WakeupWindow",
    )

    msg = _add_msg(fdp, "DeviceLabels_InfoLabel")
    _field(msg, "id", 1, _UINT32)
    _field(msg, "key", 2, _STRING)
    _field(msg, "value", 3, _STRING)

    msg = _add_msg(fdp, "DeviceLabels")
    _field(
        msg,
        "info_labels",
        1,
        _MSG,
        label=_RPT,
        type_name=".temeshtastic.DeviceLabels_InfoLabel",
    )

    msg = _add_msg(fdp, "PrivateConfig")
    _field(msg, "factory_identity", 1, _MSG, type_name=".temeshtastic.DeviceFactoryIdentity")
    _field(msg, "network_config", 2, _MSG, type_name=".temeshtastic.NetWorkConfig")
    _field(msg, "sync_wakeup", 3, _MSG, type_name=".temeshtastic.SyncWakeupConfig")
    _field(msg, "device_labels", 4, _MSG, type_name=".temeshtastic.DeviceLabels")
    _field(msg, "private_version", 5, _UINT32)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetDeviceFactoryIdentity")
    msg.oneof_decl.add().name = "payload"
    _field(msg, "get_factory_identity", 1, _BOOL, oneof_index=0)
    _field(
        msg,
        "factory_identity",
        2,
        _MSG,
        type_name=".temeshtastic.DeviceFactoryIdentity",
        oneof_index=0,
    )

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig_Channel12Config")
    _field(msg, "channel1_name", 1, _STRING)
    _field(msg, "psk1", 2, _BYTES)
    _field(msg, "channel2_name", 3, _STRING)
    _field(msg, "psk2", 4, _BYTES)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2")
    _field(msg, "network_public_key", 1, _BYTES)
    _field(msg, "network_seed", 2, _BYTES)
    _field(msg, "timestamp", 3, _UINT64)
    _field(msg, "auth_code", 4, _BYTES)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey")
    _field(msg, "new_network_public_key", 1, _BYTES)
    _field(msg, "timestamp", 2, _UINT64)
    _field(msg, "auth_code", 3, _BYTES)
    _field(msg, "new_network_seed", 4, _BYTES)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin")
    _field(msg, "new_gateway_public_key", 1, _BYTES)
    _field(msg, "new_gateway_node_id", 2, _UINT32)
    _field(msg, "timestamp", 3, _UINT64)
    _field(msg, "auth_code", 4, _BYTES)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig")
    _field(
        msg,
        "reset_type",
        1,
        _ENUM,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_ResetType",
    )
    _field(msg, "timestamp", 2, _UINT64)
    _field(msg, "auth_code", 3, _BYTES)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig")
    msg.oneof_decl.add().name = "payload"
    _field(msg, "is_single_gateway", 1, _BOOL)
    _field(msg, "get_trusted_gateway_list", 2, _BOOL, oneof_index=0)
    _field(msg, "add_trusted_gateway", 3, _UINT32, oneof_index=0)
    _field(msg, "remove_trusted_gateway", 4, _UINT32, oneof_index=0)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce")
    _field(msg, "network_public_key", 1, _BYTES)
    _field(msg, "auth_code", 2, _BYTES)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetNetWorkConfig")
    msg.oneof_decl.add().name = "payload"
    _field(msg, "get_network_config", 1, _BOOL, oneof_index=0)
    _field(
        msg,
        "channel12_config",
        2,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_Channel12Config",
        oneof_index=0,
    )
    _field(
        msg,
        "change_network_key",
        3,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey",
        oneof_index=0,
    )
    _field(
        msg,
        "change_admin",
        4,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin",
        oneof_index=0,
    )
    _field(
        msg,
        "reset_network_config",
        5,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "trusted_gateway_config",
        6,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "join_network_v2",
        7,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2",
        oneof_index=0,
    )
    _field(msg, "get_join_lock_advertise", 8, _BOOL, oneof_index=0)
    _field(
        msg,
        "gateway_announce",
        9,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce",
        oneof_index=0,
    )

    msg = _add_msg(fdp, "PrivateConfigPacket_SetSyncWakeupConfig_KeepAwakeRequest")
    _field(msg, "duration_sec", 1, _UINT32)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetSyncWakeupConfig")
    msg.oneof_decl.add().name = "payload"
    _field(msg, "get_sync_wakeup_config", 1, _BOOL, oneof_index=0)
    _field(
        msg,
        "config",
        2,
        _MSG,
        type_name=".temeshtastic.SyncWakeupConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "keep_awake",
        3,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetSyncWakeupConfig_KeepAwakeRequest",
        oneof_index=0,
    )

    msg = _add_msg(fdp, "PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabel")
    _field(msg, "id", 1, _UINT32)
    _field(msg, "key", 2, _STRING)
    _field(msg, "value", 3, _STRING)

    msg = _add_msg(fdp, "PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel")
    _field(
        msg,
        "action",
        1,
        _ENUM,
        type_name=".temeshtastic.PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabelAction",
    )
    _field(
        msg,
        "info_label",
        2,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabel",
    )

    msg = _add_msg(fdp, "PrivateConfigPacket_SetInfoLabelConfig")
    msg.oneof_decl.add().name = "payload"
    _field(msg, "get_info_label_config", 1, _BOOL, oneof_index=0)
    _field(
        msg,
        "set_info_label",
        2,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel",
        oneof_index=0,
    )

    msg = _add_msg(fdp, "PrivateConfigPacket_EnterBootloader")
    _field(
        msg,
        "reason",
        1,
        _ENUM,
        type_name=".temeshtastic.PrivateConfigPacket_EnterBootloader_BootloaderReason",
    )
    _field(msg, "delay_ms", 2, _UINT32)
    _field(msg, "auth_code", 3, _BYTES)

    msg = _add_msg(fdp, "PrivateConfigPacket_DownlinkPacket")
    msg.oneof_decl.add().name = "payload"
    _field(
        msg,
        "set_factory_identity",
        1,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetDeviceFactoryIdentity",
        oneof_index=0,
    )
    _field(
        msg,
        "set_network_config",
        2,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetNetWorkConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "set_sync_wakeup_config",
        3,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetSyncWakeupConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "set_info_label_config",
        4,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_SetInfoLabelConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "enter_bootloader",
        5,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_EnterBootloader",
        oneof_index=0,
    )

    msg = _add_msg(fdp, "PrivateConfigPacket_OperationResult")
    _field(
        msg,
        "operation",
        1,
        _ENUM,
        type_name=".temeshtastic.PrivateConfigPacket_OperationResult_Operation",
    )
    _field(
        msg,
        "status",
        2,
        _ENUM,
        type_name=".temeshtastic.PrivateConfigPacket_OperationResult_Status",
    )
    _field(msg, "request_id", 3, _UINT32)
    _field(msg, "target_node_id", 4, _UINT32)
    _field(msg, "source_node_id", 5, _UINT32)
    _field(msg, "gateway_node_id", 6, _UINT32)
    _field(msg, "operation_timestamp", 7, _UINT64)
    _field(msg, "message", 8, _STRING)

    msg = _add_msg(fdp, "PrivateConfigPacket_UplinkPacket")
    msg.oneof_decl.add().name = "payload"
    _field(
        msg,
        "factory_identity",
        1,
        _MSG,
        type_name=".temeshtastic.DeviceFactoryIdentity",
        oneof_index=0,
    )
    _field(
        msg,
        "network_config",
        2,
        _MSG,
        type_name=".temeshtastic.NetWorkConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "sync_wakeup_config",
        3,
        _MSG,
        type_name=".temeshtastic.SyncWakeupConfig",
        oneof_index=0,
    )
    _field(
        msg,
        "device_labels",
        4,
        _MSG,
        type_name=".temeshtastic.DeviceLabels",
        oneof_index=0,
    )
    _field(
        msg,
        "join_lock_advertise",
        5,
        _MSG,
        type_name=".temeshtastic.JoinLockAdvertise",
        oneof_index=0,
    )
    _field(
        msg,
        "operation_result",
        6,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_OperationResult",
        oneof_index=0,
    )

    msg = _add_msg(fdp, "PrivateConfigPacket")
    msg.oneof_decl.add().name = "packet_type"
    _field(
        msg,
        "downlink_packet",
        1,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_DownlinkPacket",
        oneof_index=0,
    )
    _field(
        msg,
        "uplink_packet",
        2,
        _MSG,
        type_name=".temeshtastic.PrivateConfigPacket_UplinkPacket",
        oneof_index=0,
    )
    _field(msg, "label_id", 3, _UINT32)

    return fdp


def _register():
    pool = _pool_mod.DescriptorPool()
    return _GetMessages([_build_fdp()], pool=pool)


_classes = _register()


def _cls(name):
    return _classes[f"temeshtastic.{name}"]


JoinLockAdvertise = _cls("JoinLockAdvertise")
DeviceFactoryIdentity = _cls("DeviceFactoryIdentity")
NetWorkConfig = _cls("NetWorkConfig")
SyncWakeupConfig_TimeSlot = _cls("SyncWakeupConfig_TimeSlot")
SyncWakeupConfig_FixedWakeup = _cls("SyncWakeupConfig_FixedWakeup")
SyncWakeupConfig_ScheduledWakeup = _cls("SyncWakeupConfig_ScheduledWakeup")
SyncWakeupConfig_WakeupWindow = _cls("SyncWakeupConfig_WakeupWindow")
SyncWakeupConfig = _cls("SyncWakeupConfig")
DeviceLabels_InfoLabel = _cls("DeviceLabels_InfoLabel")
DeviceLabels = _cls("DeviceLabels")
PrivateConfig = _cls("PrivateConfig")

PrivateConfigPacket_SetDeviceFactoryIdentity = _cls("PrivateConfigPacket_SetDeviceFactoryIdentity")
PrivateConfigPacket_SetNetWorkConfig_Channel12Config = _cls(
    "PrivateConfigPacket_SetNetWorkConfig_Channel12Config"
)
PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2 = _cls(
    "PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2"
)
PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey = _cls(
    "PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey"
)
PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin = _cls(
    "PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin"
)
PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig = _cls(
    "PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig"
)
PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig = _cls(
    "PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig"
)
PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce = _cls(
    "PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce"
)
PrivateConfigPacket_SetNetWorkConfig = _cls("PrivateConfigPacket_SetNetWorkConfig")
PrivateConfigPacket_SetSyncWakeupConfig_KeepAwakeRequest = _cls(
    "PrivateConfigPacket_SetSyncWakeupConfig_KeepAwakeRequest"
)
PrivateConfigPacket_SetSyncWakeupConfig = _cls("PrivateConfigPacket_SetSyncWakeupConfig")
PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabel = _cls(
    "PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabel"
)
PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel = _cls(
    "PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel"
)
PrivateConfigPacket_SetInfoLabelConfig = _cls("PrivateConfigPacket_SetInfoLabelConfig")
PrivateConfigPacket_EnterBootloader = _cls("PrivateConfigPacket_EnterBootloader")
PrivateConfigPacket_DownlinkPacket = _cls("PrivateConfigPacket_DownlinkPacket")
PrivateConfigPacket_OperationResult = _cls("PrivateConfigPacket_OperationResult")
PrivateConfigPacket_UplinkPacket = _cls("PrivateConfigPacket_UplinkPacket")
PrivateConfigPacket = _cls("PrivateConfigPacket")

RESET_TYPE_NONE = 0
RESET_TYPE_FACTORY = 1
RESET_TYPE_NETWORK = 2

BOOTLOADER_REASON_UNKNOWN = 0
BOOTLOADER_REASON_SERIAL = 1
BOOTLOADER_REASON_BLUETOOTH = 2
BOOTLOADER_REASON_UPPER_COMPUTER = 3
BOOTLOADER_REASON_TEST = 4

# Legacy constants kept so old UI imports do not fail.  They are not valid in
# the current firmware protocol.
RESET_TYPE_COMPANY = RESET_TYPE_NETWORK
RESET_TYPE_ADMIN = RESET_TYPE_NETWORK


def _require_len(name: str, value: bytes, size: int) -> bytes:
    if len(value) != size:
        raise ValueError(f"{name} must be {size} bytes, got {len(value)}")
    return value


def _require_len_range(name: str, value: bytes, min_size: int, max_size: int) -> bytes:
    if not min_size <= len(value) <= max_size:
        raise ValueError(f"{name} must be {min_size}-{max_size} bytes, got {len(value)}")
    return value


def _packet_with_downlink(field_name: str, message, label_id: int = 0) -> bytes:
    pkt = PrivateConfigPacket()
    getattr(pkt.downlink_packet, field_name).CopyFrom(message)
    if label_id:
        pkt.label_id = label_id & 0xFFFF_FFFF
    return pkt.SerializeToString()


def encode_get_factory_identity() -> bytes:
    req = PrivateConfigPacket_SetDeviceFactoryIdentity()
    req.get_factory_identity = True
    return _packet_with_downlink("set_factory_identity", req)


def encode_set_factory_identity(factory_identity) -> bytes:
    req = PrivateConfigPacket_SetDeviceFactoryIdentity()
    req.factory_identity.CopyFrom(factory_identity)
    return _packet_with_downlink("set_factory_identity", req)


def encode_get_network_config() -> bytes:
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.get_network_config = True
    return _packet_with_downlink("set_network_config", req)


def encode_get_join_lock_advertise() -> bytes:
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.get_join_lock_advertise = True
    return _packet_with_downlink("set_network_config", req)


def encode_network_access(*args, **kwargs) -> bytes:
    raise ValueError("NetworkAccess was removed. Use JoinNetWorkV2.")


def encode_signed_network_access(*args, **kwargs) -> bytes:
    raise ValueError("NetworkAccess was removed. Use JoinNetWorkV2.")


def encode_channel12_config(
    channel1_name: str,
    psk1: bytes,
    channel2_name: str,
    psk2: bytes,
) -> bytes:
    cfg = PrivateConfigPacket_SetNetWorkConfig_Channel12Config(
        channel1_name=channel1_name,
        psk1=_require_len_range("psk1", psk1, 16, 32),
        channel2_name=channel2_name,
        psk2=_require_len_range("psk2", psk2, 16, 32),
    )
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.channel12_config.CopyFrom(cfg)
    return _packet_with_downlink("set_network_config", req)


def encode_join_network_v2(
    network_public_key: bytes,
    network_seed: bytes,
    timestamp: int,
    auth_code: bytes,
) -> bytes:
    join = PrivateConfigPacket_SetNetWorkConfig_JoinNetWorkV2(
        network_public_key=_require_len("network_public_key", network_public_key, 32),
        network_seed=_require_len_range("network_seed", network_seed, 16, 32),
        timestamp=timestamp & 0xFFFF_FFFF_FFFF_FFFF,
        auth_code=_require_len("auth_code", auth_code, 32),
    )
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.join_network_v2.CopyFrom(join)
    return _packet_with_downlink("set_network_config", req)


def encode_signed_join_network_v2(
    device_private_key: bytes,
    sn: str,
    dev_eui: str,
    join_challenge: bytes,
    target_node_id: int,
    gateway_node_id: int,
    gateway_public_key: bytes,
    network_public_key: bytes,
    network_seed: bytes,
    timestamp: int,
) -> bytes:
    """Build JoinNetWorkV2 and generate the HMAC auth_code accepted by firmware."""
    from meshdebug.pki_crypto import hmac_join_network_v2

    auth_code = hmac_join_network_v2(
        device_private_key=device_private_key,
        sn=sn,
        dev_eui=dev_eui,
        join_challenge=join_challenge,
        target_node_id=target_node_id,
        gateway_node_id=gateway_node_id,
        gateway_public_key=gateway_public_key,
        network_public_key=network_public_key,
        network_seed=network_seed,
        timestamp=timestamp,
    )
    return encode_join_network_v2(
        network_public_key=network_public_key,
        network_seed=network_seed,
        timestamp=timestamp,
        auth_code=auth_code,
    )


def encode_change_network_key(
    new_network_public_key: bytes,
    timestamp: int,
    auth_code: bytes = b"",
    new_network_seed: bytes = b"",
    label_id: int = 0,
) -> bytes:
    if not auth_code:
        auth_code = b"\x00" * 32
    change = PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey(
        new_network_public_key=_require_len("new_network_public_key", new_network_public_key, 32),
        timestamp=timestamp & 0xFFFF_FFFF_FFFF_FFFF,
        auth_code=_require_len("auth_code", auth_code, 32),
        new_network_seed=_require_len_range("new_network_seed", new_network_seed, 16, 32),
    )
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.change_network_key.CopyFrom(change)
    return _packet_with_downlink("set_network_config", req, label_id=label_id)


def encode_change_global_key(
    new_global_public_key: bytes,
    timestamp: int,
    signature: bytes = b"",
    new_network_seed: bytes = b"",
    label_id: int = 0,
) -> bytes:
    return encode_change_network_key(
        new_global_public_key,
        timestamp,
        signature[:32] if signature else b"",
        new_network_seed=new_network_seed,
        label_id=label_id,
    )


def encode_change_admin(
    new_gw_pub: bytes,
    new_gw_node_id: int,
    timestamp: int,
    auth_code: bytes,
) -> bytes:
    change = PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin(
        new_gateway_public_key=_require_len("new_gateway_public_key", new_gw_pub, 32),
        new_gateway_node_id=new_gw_node_id & 0xFFFF_FFFF,
        timestamp=timestamp & 0xFFFF_FFFF_FFFF_FFFF,
        auth_code=_require_len("auth_code", auth_code, 32),
    )
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.change_admin.CopyFrom(change)
    return _packet_with_downlink("set_network_config", req)


def encode_reset_network_config(
    reset_type: int,
    timestamp: int,
    auth_code: bytes = b"",
    label_id: int = 0,
) -> bytes:
    if not auth_code:
        auth_code = b"\x00" * 32
    reset = PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig(
        reset_type=reset_type,
        timestamp=timestamp & 0xFFFF_FFFF_FFFF_FFFF,
        auth_code=_require_len("auth_code", auth_code, 32),
    )
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.reset_network_config.CopyFrom(reset)
    return _packet_with_downlink("set_network_config", req, label_id=label_id)


def encode_enter_bootloader(
    reason: int = BOOTLOADER_REASON_UPPER_COMPUTER,
    delay_ms: int = 0,
    auth_code: bytes = b"",
) -> bytes:
    if len(auth_code) > 32:
        raise ValueError(f"auth_code must be 0-32 bytes, got {len(auth_code)}")
    req = PrivateConfigPacket_EnterBootloader(
        reason=reason,
        delay_ms=delay_ms & 0xFFFF_FFFF,
        auth_code=auth_code,
    )
    return _packet_with_downlink("enter_bootloader", req)


def encode_trusted_gateway_config(
    is_single_gateway: bool,
    get_list: bool = False,
    add_gateway: int | None = None,
    remove_gateway: int | None = None,
    label_id: int = 0,
) -> bytes:
    cfg = PrivateConfigPacket_SetNetWorkConfig_TrustedGatewayConfig(
        is_single_gateway=is_single_gateway
    )
    selected = sum([bool(get_list), add_gateway is not None, remove_gateway is not None])
    if selected != 1:
        raise ValueError("select exactly one trusted gateway operation")
    if get_list:
        cfg.get_trusted_gateway_list = True
    elif add_gateway is not None:
        cfg.add_trusted_gateway = add_gateway & 0xFFFF_FFFF
    else:
        cfg.remove_trusted_gateway = remove_gateway & 0xFFFF_FFFF

    req = PrivateConfigPacket_SetNetWorkConfig()
    req.trusted_gateway_config.CopyFrom(cfg)
    return _packet_with_downlink("set_network_config", req, label_id=label_id)


def encode_gateway_announce(
    network_public_key: bytes,
    network_seed: bytes = b"",
    auth_code: bytes = b"",
    label_id: int = 0,
) -> bytes:
    if not auth_code:
        from meshdebug.pki_crypto import hmac_gateway_announce

        auth_code = hmac_gateway_announce(network_seed, network_public_key)
    announce = PrivateConfigPacket_SetNetWorkConfig_GatewayAnnounce(
        network_public_key=_require_len("network_public_key", network_public_key, 32),
        auth_code=_require_len("auth_code", auth_code, 32),
    )
    req = PrivateConfigPacket_SetNetWorkConfig()
    req.gateway_announce.CopyFrom(announce)
    return _packet_with_downlink("set_network_config", req, label_id=label_id)


def encode_get_sync_wakeup_config() -> bytes:
    req = PrivateConfigPacket_SetSyncWakeupConfig()
    req.get_sync_wakeup_config = True
    return _packet_with_downlink("set_sync_wakeup_config", req)


def encode_set_sync_wakeup(
    enabled: bool,
    interval_min: int,
    align_minute: int,
    offset_sec: int,
    strategy: int = 0,
    scheduled_slots: list[tuple[int, int, int, int]] | None = None,
    scheduled_offset_sec: int | None = None,
    startup_delay_sec: int = 0,
    random_delay_max_sec: int = 0,
    gateway_wait_sec: int = 0,
    final_wait_sec: int = 0,
    degraded_window_sec: int = 0,
    factory_window_sec: int = 0,
    label_id: int = 0,
) -> bytes:
    cfg = SyncWakeupConfig(enabled=enabled, strategy=strategy)
    cfg.fixed_wakeup.interval_min = interval_min
    cfg.fixed_wakeup.align_minute = align_minute
    cfg.fixed_wakeup.offset_sec = offset_sec

    if scheduled_slots:
        if len(scheduled_slots) > 4:
            raise ValueError(f"scheduled_slots max 4, got {len(scheduled_slots)}")
        cfg.scheduled_wakeup.offset_sec = (
            offset_sec if scheduled_offset_sec is None else scheduled_offset_sec
        )
        for start_hour, end_hour, slot_interval, slot_align in scheduled_slots:
            if not 0 <= start_hour <= 23:
                raise ValueError(f"start_hour must be 0-23, got {start_hour}")
            if not 0 <= end_hour <= 23:
                raise ValueError(f"end_hour must be 0-23, got {end_hour}")
            if not 1 <= slot_interval <= 1440:
                raise ValueError(f"interval_min must be 1-1440, got {slot_interval}")
            if not 0 <= slot_align <= 59:
                raise ValueError(f"align_minute must be 0-59, got {slot_align}")
            slot = cfg.scheduled_wakeup.time_slots.add()
            slot.start_hour = start_hour
            slot.end_hour = end_hour
            slot.interval_min = slot_interval
            slot.align_minute = slot_align

    if any(
        [
            startup_delay_sec,
            random_delay_max_sec,
            gateway_wait_sec,
            final_wait_sec,
            degraded_window_sec,
            factory_window_sec,
        ]
    ):
        cfg.wakeup_window.startup_delay_sec = startup_delay_sec
        cfg.wakeup_window.random_delay_max_sec = random_delay_max_sec
        cfg.wakeup_window.gateway_wait_sec = gateway_wait_sec
        cfg.wakeup_window.final_wait_sec = final_wait_sec
        cfg.wakeup_window.degraded_window_sec = degraded_window_sec
        cfg.wakeup_window.factory_window_sec = factory_window_sec

    req = PrivateConfigPacket_SetSyncWakeupConfig()
    req.config.CopyFrom(cfg)
    return _packet_with_downlink("set_sync_wakeup_config", req, label_id=label_id)


def encode_keep_awake(duration_sec: int, label_id: int = 0) -> bytes:
    req = PrivateConfigPacket_SetSyncWakeupConfig()
    req.keep_awake.CopyFrom(
        PrivateConfigPacket_SetSyncWakeupConfig_KeepAwakeRequest(
            duration_sec=duration_sec & 0xFFFF_FFFF,
        )
    )
    return _packet_with_downlink("set_sync_wakeup_config", req, label_id=label_id)


def encode_get_info_label_config() -> bytes:
    req = PrivateConfigPacket_SetInfoLabelConfig()
    req.get_info_label_config = True
    return _packet_with_downlink("set_info_label_config", req)


def encode_set_info_label(
    action: int,
    label_id: int = 0,
    key: str = "",
    value: str = "",
) -> bytes:
    info = PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabel(
        id=label_id,
        key=key,
        value=value,
    )
    set_label = PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel(
        action=action,
        info_label=info,
    )
    req = PrivateConfigPacket_SetInfoLabelConfig()
    req.set_info_label.CopyFrom(set_label)
    return _packet_with_downlink("set_info_label_config", req)


def encode_get_config() -> bytes:
    """Legacy name: current protocol exposes network config separately."""
    return encode_get_network_config()


def encode_get_sync_wakeup() -> bytes:
    return encode_get_sync_wakeup_config()


def encode_get_info_labels() -> bytes:
    return encode_get_info_label_config()


def encode_reset_config(
    reset_type: int,
    timestamp: int,
    auth_code: bytes = b"",
    label_id: int = 0,
) -> bytes:
    return encode_reset_network_config(reset_type, timestamp, auth_code, label_id=label_id)


def encode_change_company_key(
    new_company_pub: bytes,
    timestamp: int,
    signature: bytes = b"",
    new_network_seed: bytes = b"",
    label_id: int = 0,
) -> bytes:
    return encode_change_global_key(
        new_company_pub,
        timestamp,
        signature,
        new_network_seed=new_network_seed,
        label_id=label_id,
    )


def encode_set_company_key(*args, **kwargs) -> bytes:
    raise ValueError(
        "set_company_key is obsolete. Use NetworkAccess followed by Channel12Config."
    )


def encode_set_admin_key(*args, **kwargs) -> bytes:
    raise ValueError("set_admin_key is obsolete. Use ChangeAdmin in SetNetWorkConfig.")


def encode_set_device_name(*args, **kwargs) -> bytes:
    raise ValueError("set_device_name is not part of the current Dragino private protocol.")


# Legacy class aliases.  They are intentionally not real current messages, but
# keeping names avoids import-time failures in older helper code.
CompanyConfig = NetWorkConfig
PrivateConfigPacket_Request = PrivateConfigPacket_DownlinkPacket
PrivateConfigPacket_Response = PrivateConfigPacket_UplinkPacket
PrivateConfigPacket_ChangeAdminRequest = PrivateConfigPacket_SetNetWorkConfig_ChangeAdmin
PrivateConfigPacket_ResetConfigRequest = PrivateConfigPacket_SetNetWorkConfig_ResetNetworkConfig
PrivateConfigPacket_ChangeCompanyKeyRequest = PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey
PrivateConfigPacket_SetNetWorkConfig_ChangeGlobalKey = PrivateConfigPacket_SetNetWorkConfig_ChangeNetworkKey
PrivateConfigPacket_SetInfoLabel_InfoLabel = (
    PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel_InfoLabel
)
PrivateConfigPacket_SetInfoLabel = PrivateConfigPacket_SetInfoLabelConfig_SetInfoLabel
