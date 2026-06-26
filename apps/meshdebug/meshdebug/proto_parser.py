"""
meshdebug/proto_parser.py
将 FromRadio protobuf 对象解析为可 JSON 序列化的 dict。

核心函数:
    parse_from_radio(from_radio, raw_hex, received_utc) -> dict

支持标准所有 payload_variant，以及自定义 PortNum：
    286  CUSTOM_POSITION_APP  —— payload 解析为 mesh_pb2.Position
"""

import logging
import struct
from datetime import datetime
from typing import Any, Optional

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from meshtastic import mesh_pb2, portnums_pb2

logger = logging.getLogger(__name__)

# Routing.Error 错误码名称映射
_ROUTING_ERRORS: dict[int, str] = {
    0:  "SUCCESS",
    1:  "NO_ROUTE",
    2:  "GOT_NAK",
    3:  "TIMEOUT",
    4:  "NO_INTERFACE",
    5:  "MAX_RETRANSMIT",
    6:  "NO_CHANNEL",
    7:  "TOO_LARGE",
    8:  "NO_RESPONSE",
    9:  "DUTY_CYCLE_LIMIT",
    32: "BAD_REQUEST",
    33: "NOT_AUTHORIZED",
}

# 端口 288 网关命令名称
_GATEWAY_CMD_NAMES: dict[int, str] = {
    0: "GW_CMD_NONE",
    1: "GW_CMD_REQUEST_TELEMETRY",
    2: "GW_CMD_SET_CONFIG",
    3: "GW_CMD_SYNC_TIME",
    4: "GW_CMD_REBOOT",
}

_PRIVATE_CONFIG_OPERATION_NAMES: dict[int, str] = {
    0: "UNKNOWN",
    1: "SET_FACTORY_IDENTITY",
    2: "GET_FACTORY_IDENTITY",
    3: "CHANNEL12_CONFIG",
    4: "JOIN_NETWORK_V2",
    5: "CHANGE_ADMIN",
    6: "RESET_NETWORK_CONFIG",
    7: "CHANGE_NETWORK_KEY",
    8: "TRUSTED_GATEWAY_CONFIG",
    9: "SYNC_WAKEUP_CONFIG",
    10: "INFO_LABEL_CONFIG",
    11: "ENTER_BOOTLOADER",
}

_PRIVATE_CONFIG_STATUS_NAMES: dict[int, str] = {
    0: "UNKNOWN",
    1: "OK",
    2: "NO_CHANGE",
    3: "PENDING_CHANNEL12",
    4: "ALREADY_ENROLLED",
    5: "NOT_ENROLLED",
    6: "NOT_AUTHORIZED",
    7: "BAD_AUTH_CODE",
    8: "STALE_NONCE",
    9: "INVALID_STATE",
    10: "INVALID_SIZE",
    11: "INVALID_ARGUMENT",
    12: "SAVE_FAILED",
    13: "UNSUPPORTED",
}

# ─── 自定义 PortNum 扩展表（用户二创） ───────────────────────────────────────

# int → 显示名称
CUSTOM_PORTNUM_NAMES: dict[int, str] = {
    286: "CUSTOM_POSITION_APP",
    287: "PRIVATE_CONFIG_APP",
    288: "WAKEUP_COMM_APP",
    290: "DRAGINO_BUSINESS_DATA_APP",
}

# int → 解析用的 protobuf 类（延迟初始化，避免导入错误影响启动）
CUSTOM_PORTNUM_PROTO: dict[int, Any] = {
    286: mesh_pb2.Position,
}

# ─── 标准 PortNum → proto 类映射（延迟初始化） ───────────────────────────────

_STD_PORTNUM_PROTO: Optional[dict] = None


def _get_std_proto_map() -> dict:
    global _STD_PORTNUM_PROTO
    if _STD_PORTNUM_PROTO is None:
        from meshtastic import admin_pb2, telemetry_pb2

        _STD_PORTNUM_PROTO = {
            "POSITION_APP":     mesh_pb2.Position,
            "NODEINFO_APP":     mesh_pb2.User,
            "ROUTING_APP":      mesh_pb2.Routing,
            "WAYPOINT_APP":     mesh_pb2.Waypoint,
            "TRACEROUTE_APP":   mesh_pb2.RouteDiscovery,
            "NEIGHBORINFO_APP": mesh_pb2.NeighborInfo,
            "ADMIN_APP":        admin_pb2.AdminMessage,
            "TELEMETRY_APP":    telemetry_pb2.Telemetry,
        }
    return _STD_PORTNUM_PROTO


# PortNum 里属于 UTF-8 明文的类型
_TEXT_PORTNUMS = {
    "TEXT_MESSAGE_APP",
    "TEXT_MESSAGE_COMPRESSED_APP",
    "DETECTION_SENSOR_APP",
    "ALERT_APP",
    "RANGE_TEST_APP",
    "REPLY_APP",
}


# ─── PortNum 整数 → 名称 ──────────────────────────────────────────────────────

def portnum_to_name(portnum_int: int) -> str:
    """将 PortNum 整数值转为可读名称，自定义值优先。"""
    if portnum_int in CUSTOM_PORTNUM_NAMES:
        return CUSTOM_PORTNUM_NAMES[portnum_int]
    try:
        return portnums_pb2.PortNum.Name(portnum_int)
    except ValueError:
        return f"PORTNUM_{portnum_int}"


# ─── 内层 payload 解码 ────────────────────────────────────────────────────────

def _get_private_config_packet_cls():
    """延迟导入 PrivateConfigPacket，避免启动时 protobuf 注册失败影响主程序。"""
    try:
        from meshdebug.private_config_pb2 import PrivateConfigPacket
        return PrivateConfigPacket
    except Exception as exc:
        logger.warning("private_config_pb2 导入失败: %s", exc)
        return None


def _decode_private_config(payload: bytes) -> Optional[dict]:
    """解析端口 287 的 PrivateConfigPacket payload。"""
    cls = _get_private_config_packet_cls()
    if cls is None:
        return {"raw_hex": payload.hex()}
    try:
        msg = cls()
        msg.ParseFromString(payload)
        d = MessageToDict(
            msg,
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=False,
        )
        _annotate_private_config(msg, d)
        return d
    except (DecodeError, Exception) as exc:
        logger.debug("PrivateConfigPacket 解析失败: %s", exc)
        return {"parse_error": str(exc), "raw_hex": payload.hex()}


def _annotate_private_config(msg, d: dict) -> None:
    """Add debug-friendly fields for the current Dragino private protocol."""
    if msg.label_id:
        d["label_id"] = msg.label_id
        d["label_id_hex"] = f"0x{msg.label_id:08X}"

    packet_type = msg.WhichOneof("packet_type")
    if not packet_type:
        return
    d["_packet_type"] = packet_type

    if packet_type == "uplink_packet":
        uplink = msg.uplink_packet
        payload_type = uplink.WhichOneof("payload")
        d["_payload_type"] = payload_type or ""
        if payload_type == "join_lock_advertise":
            adv = uplink.join_lock_advertise
            block = d.setdefault("uplink_packet", {}).setdefault("join_lock_advertise", {})
            block["join_challenge_hex"] = bytes(adv.join_challenge).hex()
            block["dev_eui"] = f"{adv.dev_eui_hi:08X}{adv.dev_eui_lo:08X}"
        elif payload_type == "factory_identity":
            identity = uplink.factory_identity
            block = d.setdefault("uplink_packet", {}).setdefault("factory_identity", {})
            block["device_private_key_hex"] = bytes(identity.device_private_key).hex()
            block["legacy_app_key_hex"] = bytes(identity.legacy_app_key).hex()
            block["dev_eui"] = f"{identity.dev_eui_hi:08X}{identity.dev_eui_lo:08X}"
        elif payload_type == "network_config":
            network = uplink.network_config
            block = d.setdefault("uplink_packet", {}).setdefault("network_config", {})
            block["network_public_key_hex"] = bytes(network.network_public_key).hex()
            block["network_seed_hex"] = bytes(network.network_seed).hex()
        elif payload_type == "operation_result":
            result = uplink.operation_result
            block = d.setdefault("uplink_packet", {}).setdefault("operation_result", {})
            block["operation_name"] = _PRIVATE_CONFIG_OPERATION_NAMES.get(result.operation, str(result.operation))
            block["status_name"] = _PRIVATE_CONFIG_STATUS_NAMES.get(result.status, str(result.status))
            block["request_id_hex"] = f"0x{result.request_id:08X}"
            block["target_node_id_text"] = f"!{result.target_node_id:08x}"
            block["source_node_id_text"] = f"!{result.source_node_id:08x}"
            block["gateway_node_id_text"] = f"!{result.gateway_node_id:08x}"

    elif packet_type == "downlink_packet":
        downlink = msg.downlink_packet
        payload_type = downlink.WhichOneof("payload")
        d["_payload_type"] = payload_type or ""
        if payload_type == "set_factory_identity":
            factory_req = downlink.set_factory_identity
            factory_payload = factory_req.WhichOneof("payload")
            d["_factory_payload_type"] = factory_payload or ""
            block = d.setdefault("downlink_packet", {}).setdefault("set_factory_identity", {})
            if factory_payload == "factory_identity":
                identity = factory_req.factory_identity
                block["device_private_key_hex"] = bytes(identity.device_private_key).hex()
                block["legacy_app_key_hex"] = bytes(identity.legacy_app_key).hex()
                block["dev_eui"] = f"{identity.dev_eui_hi:08X}{identity.dev_eui_lo:08X}"
        elif payload_type == "set_network_config":
            network_req = downlink.set_network_config
            network_payload = network_req.WhichOneof("payload")
            d["_network_payload_type"] = network_payload or ""
            block = d.setdefault("downlink_packet", {}).setdefault("set_network_config", {})
            if network_payload == "channel12_config":
                ch = network_req.channel12_config
                ch_block = block.setdefault("channel12_config", {})
                ch_block["psk1_hex"] = bytes(ch.psk1).hex()
                ch_block["psk2_hex"] = bytes(ch.psk2).hex()
            elif network_payload == "join_network_v2":
                join = network_req.join_network_v2
                join_block = block.setdefault("join_network_v2", {})
                join_block["network_public_key_hex"] = bytes(join.network_public_key).hex()
                join_block["network_seed_hex"] = bytes(join.network_seed).hex()
                join_block["auth_code_hex"] = bytes(join.auth_code).hex()
            elif network_payload == "get_join_lock_advertise":
                block["get_join_lock_advertise"] = True
            elif network_payload == "change_network_key":
                change = network_req.change_network_key
                change_block = block.setdefault("change_network_key", {})
                change_block["new_network_public_key_hex"] = bytes(change.new_network_public_key).hex()
                change_block["new_network_seed_hex"] = bytes(change.new_network_seed).hex()
                change_block["auth_code_hex"] = bytes(change.auth_code).hex()
            elif network_payload == "change_admin":
                change = network_req.change_admin
                change_block = block.setdefault("change_admin", {})
                change_block["new_gateway_public_key_hex"] = bytes(change.new_gateway_public_key).hex()
                change_block["auth_code_hex"] = bytes(change.auth_code).hex()
            elif network_payload == "reset_network_config":
                reset = network_req.reset_network_config
                reset_block = block.setdefault("reset_network_config", {})
                reset_block["auth_code_hex"] = bytes(reset.auth_code).hex()
            elif network_payload == "trusted_gateway_config":
                trusted = network_req.trusted_gateway_config
                trusted_block = block.setdefault("trusted_gateway_config", {})
                trusted_block["payload"] = trusted.WhichOneof("payload") or ""
                if trusted.WhichOneof("payload") == "add_trusted_gateway":
                    trusted_block["add_trusted_gateway_text"] = f"!{trusted.add_trusted_gateway:08x}"
                elif trusted.WhichOneof("payload") == "remove_trusted_gateway":
                    trusted_block["remove_trusted_gateway_text"] = f"!{trusted.remove_trusted_gateway:08x}"
            elif network_payload == "gateway_announce":
                announce = network_req.gateway_announce
                announce_block = block.setdefault("gateway_announce", {})
                announce_block["network_public_key_hex"] = bytes(announce.network_public_key).hex()
                announce_block["auth_code_hex"] = bytes(announce.auth_code).hex()
        elif payload_type == "set_sync_wakeup_config":
            sync_req = downlink.set_sync_wakeup_config
            sync_payload = sync_req.WhichOneof("payload")
            d["_sync_wakeup_payload_type"] = sync_payload or ""
            block = d.setdefault("downlink_packet", {}).setdefault("set_sync_wakeup_config", {})
            if sync_payload == "keep_awake":
                block["keep_awake"] = {
                    "duration_sec": sync_req.keep_awake.duration_sec,
                }
        elif payload_type == "enter_bootloader":
            req = downlink.enter_bootloader
            block = d.setdefault("downlink_packet", {}).setdefault("enter_bootloader", {})
            block["auth_code_hex"] = bytes(req.auth_code).hex()


def _private_config_summary(parsed: dict) -> str:
    packet_type = parsed.get("_packet_type")
    payload_type = parsed.get("_payload_type")

    if packet_type == "downlink_packet":
        if payload_type == "set_factory_identity":
            factory_payload = parsed.get("_factory_payload_type") or "?"
            if factory_payload == "factory_identity":
                identity = parsed.get("downlink_packet", {}).get("set_factory_identity", {})
                sn = identity.get("factory_identity", {}).get("sn", "") or identity.get("sn", "")
                dev_eui = identity.get("dev_eui", "")
                suffix = " ".join(part for part in [f"sn={sn}" if sn else "", dev_eui] if part)
                return f"downlink:set_factory_identity.write {suffix}".strip()
            return f"downlink:set_factory_identity.{factory_payload}"
        if payload_type == "set_network_config":
            network_payload = parsed.get("_network_payload_type") or "?"
            return f"downlink:{payload_type}.{network_payload}"
        return f"downlink:{payload_type or '?'}"

    if packet_type == "uplink_packet":
        if payload_type == "join_lock_advertise":
            adv = parsed.get("uplink_packet", {}).get("join_lock_advertise", {})
            sn = adv.get("sn", "")
            dev_eui = adv.get("dev_eui", "")
            suffix = " ".join(part for part in [f"sn={sn}" if sn else "", dev_eui] if part)
            return f"uplink:join_lock_advertise {suffix}".strip()
        if payload_type == "operation_result":
            result = parsed.get("uplink_packet", {}).get("operation_result", {})
            operation = result.get("operation_name") or result.get("operation") or "?"
            status = result.get("status_name") or result.get("status") or "?"
            return f"uplink:operation_result {operation}/{status}"
        return f"uplink:{payload_type or '?'}"

    if "request" in parsed:
        req = parsed["request"]
        op = next((k for k in req if k != "status"), "?")
        return f"legacy-request:{op}"
    if "response" in parsed:
        rsp = parsed["response"]
        field = next(iter(rsp), "?")
        return f"legacy-response:{field}"
    return ""


def _decode_wakeup_comm(payload: bytes) -> dict:
    """解析端口 288 的网关命令 payload（1 字节命令 + 可选数据）。"""
    if not payload:
        return {"cmd_type": 0, "cmd_name": "GW_CMD_NONE"}
    cmd = payload[0]
    result = {
        "cmd_type": cmd,
        "cmd_name": _GATEWAY_CMD_NAMES.get(cmd, f"UNKNOWN_{cmd}"),
    }
    if len(payload) > 1:
        result["extra_hex"] = payload[1:].hex()
    return result


def _decode_business_data(payload: bytes) -> dict:
    """Decode Dragino port 290 DraginoBusinessSensorPayloadV1."""
    if len(payload) != 14:
        return {
            "parse_error": f"unexpected business payload length: {len(payload)}",
            "raw_hex": payload.hex(),
        }

    version, msg_type, flags, utc_time, battery_mv, temp_cx10, hum_cx10 = struct.unpack(
        "<BBHIHhH", payload
    )
    has_utc_time = bool(flags & 0x0001)
    has_battery_mv = bool(flags & 0x0002)
    has_temp_cx10 = bool(flags & 0x0004)
    has_hum_cx10 = bool(flags & 0x0008)
    return {
        "version": version,
        "msg_type": msg_type,
        "flags": flags,
        "flags_hex": f"0x{flags:04x}",
        "utc_time": utc_time,
        "battery_mv": battery_mv,
        "temp_cx10": temp_cx10,
        "temperature_c": temp_cx10 / 10.0 if has_temp_cx10 else None,
        "hum_cx10": hum_cx10,
        "humidity_percent": hum_cx10 / 10.0 if has_hum_cx10 else None,
        "temperature_status": "valid" if has_temp_cx10 else "invalid",
        "humidity_status": "valid" if has_hum_cx10 else "invalid",
        "has_utc_time": has_utc_time,
        "has_battery_mv": has_battery_mv,
        "has_temp_cx10": has_temp_cx10,
        "has_hum_cx10": has_hum_cx10,
    }


def decode_app_payload(portnum_int: int, portnum_name: str, payload: bytes) -> Optional[dict]:
    """
    将 MeshPacket.decoded.payload 解析成 dict。

    Parameters
    ----------
    portnum_int  : PortNum 整数值（用于查自定义表）
    portnum_name : PortNum 名称字符串（用于查标准表）
    payload      : 原始 payload bytes
    """
    if not payload:
        return None

    # 端口 287: PrivateConfigPacket (protobuf)
    if portnum_int == 287:
        return _decode_private_config(payload)

    # 端口 288: 网关命令（原始字节，非 protobuf）
    if portnum_int == 288:
        return _decode_wakeup_comm(payload)

    if portnum_int == 290:
        return _decode_business_data(payload)

    # 1. 自定义 PortNum proto 类
    custom_cls = CUSTOM_PORTNUM_PROTO.get(portnum_int)
    if custom_cls is not None:
        try:
            msg = custom_cls()
            msg.ParseFromString(payload)
            return MessageToDict(
                msg,
                preserving_proto_field_name=True,
                always_print_fields_with_no_presence=False,
            )
        except (DecodeError, Exception) as exc:
            logger.debug("自定义 payload 解析失败 portnum=%d: %s", portnum_int, exc)
            return {"parse_error": str(exc), "raw_hex": payload.hex()}

    # 2. 文本类
    if portnum_name in _TEXT_PORTNUMS:
        try:
            return {"text": payload.decode("utf-8")}
        except UnicodeDecodeError:
            return {"raw_hex": payload.hex()}

    # 3. 标准 proto 类
    proto_cls = _get_std_proto_map().get(portnum_name)
    if proto_cls is not None:
        try:
            msg = proto_cls()
            msg.ParseFromString(payload)
            return MessageToDict(
                msg,
                preserving_proto_field_name=True,
                always_print_fields_with_no_presence=False,
            )
        except (DecodeError, Exception) as exc:
            logger.debug("payload 解析失败 portnum=%s: %s", portnum_name, exc)
            return {"parse_error": str(exc), "raw_hex": payload.hex()}

    # 4. 未知类型：保留 hex
    return {"raw_hex": payload.hex()}


# ─── MeshPacket 解析 ──────────────────────────────────────────────────────────

def parse_mesh_packet(packet: mesh_pb2.MeshPacket) -> dict:
    """解析 MeshPacket，含内层 payload 可读格式。"""
    d: dict[str, Any] = MessageToDict(
        packet,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=False,
    )

    from_num = getattr(packet, "from")
    to_num   = packet.to

    # 移除 MessageToDict 输出的十进制整数，只保留十六进制字符串
    d.pop("from", None)
    d.pop("to", None)
    d["from_id"] = f"!{from_num:08x}"
    d["to_id"]   = "broadcast" if to_num == 0xFFFF_FFFF else f"!{to_num:08x}"

    # 显式写入跳数字段（即使为 0 也输出）
    d["hop_start"]    = packet.hop_start               # 发送时原始跳数限制
    d["hop_limit"]    = packet.hop_limit               # 当前剩余可跳数
    d["hops_traveled"] = max(0, packet.hop_start - packet.hop_limit)  # 已经过的跳数

    pv = packet.WhichOneof("payload_variant")
    if pv == "decoded":
        pnum_int  = packet.decoded.portnum
        pnum_name = portnum_to_name(pnum_int)
        inner     = decode_app_payload(pnum_int, pnum_name, packet.decoded.payload)

        decoded_block = d.get("decoded", {})
        # 修正：portnum 为整数值，portnum_name 为字符串名（MessageToDict 给出的是字符串枚举，移除）
        decoded_block.pop("portnum", None)
        decoded_block["portnum"]      = pnum_int   # 整数，如 67
        decoded_block["portnum_name"] = pnum_name  # 字符串，如 "TELEMETRY_APP"
        if inner is not None:
            decoded_block["payload_parsed"] = inner
        if packet.decoded.payload:
            decoded_block["payload_hex"] = packet.decoded.payload.hex()
        decoded_block.pop("payload", None)   # 移除 base64，已用 hex 替代
        d["decoded"] = decoded_block

    elif pv == "encrypted":
        d["encrypted_hex"] = packet.encrypted.hex()
        d.pop("encrypted", None)

    return d


# ─── 主解析函数 ───────────────────────────────────────────────────────────────

def parse_from_radio(
    from_radio: mesh_pb2.FromRadio,
    raw_hex: str,
    received_utc: datetime,
) -> dict:
    """
    将 FromRadio 对象解析为可 JSON 序列化的 dict。

    Returns
    -------
    {
      "id":          int,
      "variant":     str,
      "received_at": str  (ISO 8601 UTC, 毫秒精度),
      "raw_hex":     str,
      "summary":     str  (列表一行显示的简短文字),
      "data":        dict | None,
    }
    """
    variant: str = from_radio.WhichOneof("payload_variant") or "(none)"
    ts_str = received_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    result: dict[str, Any] = {
        "id":          from_radio.id,
        "variant":     variant,
        "received_at": ts_str,
        "raw_hex":     raw_hex,
        "summary":     "",
        "data":        None,
    }

    try:
        if variant == "packet":
            data = parse_mesh_packet(from_radio.packet)
            result["data"] = data
            portnum  = data.get("decoded", {}).get("portnum_name", "encrypted")
            from_id  = data.get("from_id", "?")
            to_id    = data.get("to_id", "?")
            txt_dict = data.get("decoded", {}).get("payload_parsed", {})
            if isinstance(txt_dict, dict) and "text" in txt_dict:
                preview = txt_dict["text"][:40].replace("\n", " ")
                result["summary"] = f'{portnum}  {from_id} → {to_id}  "{preview}"'
            elif (
                portnum == "PRIVATE_CONFIG_APP"
                and isinstance(txt_dict, dict)
                and "_packet_type" in txt_dict
            ):
                op = _private_config_summary(txt_dict)
                suffix = f"  [{op}]" if op else ""
                result["summary"] = f"{portnum}  {from_id} -> {to_id}{suffix}"
            elif portnum == "PRIVATE_CONFIG_APP" and isinstance(txt_dict, dict):
                # 提取有意义的操作描述
                if "request" in txt_dict:
                    req = txt_dict["request"]
                    op = next((k for k in req if k != "status"), "?")
                    result["summary"] = f"{portnum}  {from_id} → {to_id}  [{op}]"
                elif "response" in txt_dict:
                    rsp = txt_dict["response"]
                    field = next(iter(rsp), "?")
                    result["summary"] = f"{portnum}  {from_id} → {to_id}  [resp:{field}]"
                else:
                    result["summary"] = f"{portnum}  {from_id} → {to_id}"
            elif portnum == "DRAGINO_BUSINESS_DATA_APP" and isinstance(txt_dict, dict):
                batt = txt_dict.get("battery_mv", "?")
                temp = txt_dict.get("temperature_c")
                hum = txt_dict.get("humidity_percent")
                temp_text = "invalid" if temp is None else f"{temp}C"
                hum_text = "invalid" if hum is None else f"{hum}%"
                result["summary"] = (
                    f"{portnum}  {from_id} -> {to_id}  "
                    f"batt={batt}mV temp={temp_text} hum={hum_text}"
                )
            elif portnum == "WAKEUP_COMM_APP" and isinstance(txt_dict, dict):
                cmd_name = txt_dict.get("cmd_name", "?")
                result["summary"] = f"{portnum}  {from_id} → {to_id}  [{cmd_name}]"
            else:
                result["summary"] = f"{portnum}  {from_id} → {to_id}"

        elif variant == "my_info":
            d = MessageToDict(from_radio.my_info, preserving_proto_field_name=True)
            node_num = from_radio.my_info.my_node_num
            d["node_id"] = f"!{node_num:08x}"
            result["data"]    = d
            result["summary"] = f"本机节点 {d['node_id']}"

        elif variant == "node_info":
            d = MessageToDict(from_radio.node_info, preserving_proto_field_name=True)
            node_num = from_radio.node_info.num
            d["node_id"] = f"!{node_num:08x}"
            long_name = ""
            if from_radio.node_info.HasField("user"):
                long_name = from_radio.node_info.user.long_name
            result["data"]    = d
            result["summary"] = f"{d['node_id']}  {long_name}".strip()

        elif variant == "config":
            d = MessageToDict(from_radio.config, preserving_proto_field_name=True)
            config_type = from_radio.config.WhichOneof("payload_variant") or "?"
            result["data"]    = d
            result["summary"] = f"config.{config_type}"

        elif variant == "channel":
            d = MessageToDict(from_radio.channel, preserving_proto_field_name=True)
            result["data"]    = d
            result["summary"] = f"channel[{from_radio.channel.index}]"

        elif variant == "moduleConfig":
            d = MessageToDict(from_radio.moduleConfig, preserving_proto_field_name=True)
            mod_type = from_radio.moduleConfig.WhichOneof("payload_variant") or "?"
            result["data"]    = d
            result["summary"] = f"moduleConfig.{mod_type}"

        elif variant == "config_complete_id":
            cid = from_radio.config_complete_id
            result["data"]    = {"config_complete_id": cid}
            result["summary"] = f"id={cid}"

        elif variant == "rebooted":
            result["data"]    = {"rebooted": from_radio.rebooted}
            result["summary"] = "设备重启"

        elif variant == "queueStatus":
            d = MessageToDict(from_radio.queueStatus, preserving_proto_field_name=True)
            result["data"] = d
            res      = from_radio.queueStatus.res
            res_name = _ROUTING_ERRORS.get(res, f"ERR_{res}")
            free     = d.get("free", "?")
            maxlen   = d.get("maxlen", "?")
            pkt_id   = d.get("mesh_packet_id", "?")
            result["summary"] = f"res={res}({res_name})  队列 {free}/{maxlen}  针对包 id={pkt_id}"

        elif variant == "metadata":
            d = MessageToDict(from_radio.metadata, preserving_proto_field_name=True)
            result["data"]    = d
            result["summary"] = f"firmware={d.get('firmware_version', '?')}"

        elif variant == "log_record":
            d = MessageToDict(from_radio.log_record, preserving_proto_field_name=True)
            result["data"]    = d
            result["summary"] = d.get("message", "")[:80]

        elif variant == "clientNotification":
            d = MessageToDict(
                from_radio.clientNotification, preserving_proto_field_name=True
            )
            result["data"]    = d
            result["summary"] = d.get("message", "")[:80]

        elif variant == "fileInfo":
            d = MessageToDict(from_radio.fileInfo, preserving_proto_field_name=True)
            fname = d.get("file_name", "?")
            fsize = d.get("size_bytes", 0)
            result["data"]    = d
            result["summary"] = f"fileinfo: {fname}  ({fsize} B)"

        else:
            result["data"]    = {}
            result["summary"] = variant

    except Exception as exc:
        logger.warning("parse_from_radio 出错 variant=%s: %s", variant, exc)
        result["data"]    = {"parse_error": str(exc)}
        result["summary"] = f"解析错误: {exc}"

    return result
