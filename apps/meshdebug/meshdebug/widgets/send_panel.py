"""
meshdebug/widgets/send_panel.py
发送数据包面板（QDockWidget 内嵌 Widget）。

PortNum 与 payload 页面对应：
  TEXT 页  — TEXT_MESSAGE_APP(1): 文本输入
  POS  页  — POSITION_APP(3) / CUSTOM_POSITION_APP(286): mesh_pb2.Position 完整字段
  RAW  页  — 其他 / 自定义: 原始 Hex 输入

MeshPacket 字段默认值（未填时）：
  to        → 0xFFFFFFFF (broadcast)
  channel   → 0
  from      → 0 (设备自填)
  want_ack  → False
  hop_limit → 3
  id        → 0 (随机生成)
"""

import json
import logging
import os
import random
import re
import base64 as _base64
import binascii
import time as _time
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QSizePolicy
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from meshdebug.widgets.json_highlighter import JsonHighlighter
from meshdebug.i18n import add_combo_item, set_widget_text, tr
from meshtastic import mesh_pb2

logger = logging.getLogger(__name__)

# ─── PortNum 下拉选项：(显示名, int值, 页面索引) ─────────────────────────────
#   页面索引: 0=TEXT  1=POS  2=RAW  3=TELEMETRY  4=NODEINFO  5=ADMIN
#             6=PRIVATE_CONFIG  7=WAKEUP_COMM
_PORTNUM_OPTIONS: list[tuple[str, int, int]] = [
    ("TEXT_MESSAGE_APP  (1)",        1,   0),
    ("POSITION_APP  (3)",            3,   1),
    ("NODEINFO_APP  (4)",            4,   4),
    ("ROUTING_APP  (5)",             5,   2),
    ("ADMIN_APP  (6)",               6,   5),
    ("TELEMETRY_APP  (67)",          67,  3),
    ("TRACEROUTE_APP  (70)",         70,  2),
    ("NEIGHBORINFO_APP  (71)",       71,  2),
    ("CUSTOM_POSITION_APP  (286)",   286, 1),
    ("PRIVATE_CONFIG_APP  (287)",    287, 6),
    ("WAKEUP_COMM_APP  (288)",       288, 7),
    ("DRAGINO_BUSINESS_DATA_APP  (290)", 290, 2),
    ("PRIVATE_APP  (256)",           256, 2),
    ("RAW / 自定义 ...",             -1,  2),
]

# ─── AdminMessage 操作表 ──────────────────────────────────────────────────────
# (display_label, field_name, input_type, extra_label, max_len)
# field_name=None → 分隔符行（不可选）
# input_type: 0=NONE(bool) 1=UINT32 2=INT32 3=STRING 4=CFG_TYPE 5=MOD_TYPE
#             6=SET_OWNER 7=SET_CHANNEL 8=SET_CONFIG 9=SET_MODULE_CONFIG
#             10=HAM_MODE 11=FIXED_POS 12=ADD_CONTACT 13=KEY_VERIF
#             14=BACKUP_LOC 15=INPUT_EVT
_ADMIN_OPS: list[tuple] = [
    # ── GET 请求 ─────────────────────────────────────────────────────────────
    ("─── GET 请求 ─────────────────", None, -1, "", 0),
    ("Get Channel",                   "get_channel_request",                      1, "Channel Index+1 (1=主信道)", 0),
    ("Get Owner",                     "get_owner_request",                        0, "", 0),
    ("Get Config",                    "get_config_request",                       4, "", 0),
    ("Get Module Config",             "get_module_config_request",                5, "", 0),
    ("Get Canned Messages",           "get_canned_message_module_messages_request", 0, "", 0),
    ("Get Device Metadata",           "get_device_metadata_request",              0, "", 0),
    ("Get Ringtone",                  "get_ringtone_request",                     0, "", 0),
    ("Get Device Connection Status",  "get_device_connection_status_request",     0, "", 0),
    ("Get Node Remote HW Pins",       "get_node_remote_hardware_pins_request",    0, "", 0),
    ("Get UI Config",                 "get_ui_config_request",                    0, "", 0),
    # ── SET 操作 ─────────────────────────────────────────────────────────────
    ("─── SET 操作 ─────────────────", None, -1, "", 0),
    ("Set Owner",                     "set_owner",                                6, "", 0),
    ("Set Channel",                   "set_channel",                              7, "", 0),
    ("Set Config",                    "set_config",                               8, "", 0),
    ("Set Module Config",             "set_module_config",                        9, "", 0),
    ("Set Canned Messages",           "set_canned_message_module_messages",       3, "文本内容 (max 200)", 200),
    ("Set Ringtone",                  "set_ringtone_message",                     3, "铃声文本 (max 230)", 230),
    ("Set Ham Mode",                  "set_ham_mode",                             10, "", 0),
    ("Set Fixed Position",            "set_fixed_position",                       11, "", 0),
    ("Set Scale",                     "set_scale",                                1, "Scale 值 (uint32)", 0),
    ("Set Time Only",                 "set_time_only",                            1, "Unix 时间戳（秒）", 0),
    # ── 节点管理 ──────────────────────────────────────────────────────────────
    ("─── 节点管理 ─────────────────", None, -1, "", 0),
    ("Remove By Node Num",            "remove_by_nodenum",                        1, "节点 ID", 0),
    ("Set Favorite Node",             "set_favorite_node",                        1, "节点 ID", 0),
    ("Remove Favorite Node",          "remove_favorite_node",                     1, "节点 ID", 0),
    ("Set Ignored Node",              "set_ignored_node",                         1, "节点 ID", 0),
    ("Remove Ignored Node",           "remove_ignored_node",                      1, "节点 ID", 0),
    ("Remove Fixed Position",         "remove_fixed_position",                    0, "", 0),
    ("Add Contact",                   "add_contact",                              12, "", 0),
    ("Key Verification",              "key_verification",                         13, "", 0),
    # ── 设备控制 ──────────────────────────────────────────────────────────────
    ("─── 设备控制 ─────────────────", None, -1, "", 0),
    ("Reboot (seconds, -1=取消)",     "reboot_seconds",                           2, "重启倒计时（秒，-1=取消）", 0),
    ("Reboot OTA (seconds)",          "reboot_ota_seconds",                       2, "OTA重启倒计时（秒，-1=取消）", 0),
    ("Shutdown (seconds, -1=取消)",   "shutdown_seconds",                         2, "关机倒计时（秒，-1=取消）", 0),
    ("Factory Reset Config",          "factory_reset_config",                     2, "值 (通常填 1)", 0),
    ("Factory Reset Device",          "factory_reset_device",                     2, "值 (通常填 1)", 0),
    ("NodeDB Reset",                  "nodedb_reset",                             0, "", 0),
    ("Enter DFU Mode",                "enter_dfu_mode_request",                   0, "", 0),
    ("Delete File",                   "delete_file_request",                      3, "文件路径 (max 200)", 200),
    ("Exit Simulator",                "exit_simulator",                           0, "", 0),
    # ── 设置事务 ──────────────────────────────────────────────────────────────
    ("─── 设置事务 ─────────────────", None, -1, "", 0),
    ("Begin Edit Settings",           "begin_edit_settings",                      0, "", 0),
    ("Commit Edit Settings",          "commit_edit_settings",                     0, "", 0),
    ("Backup Preferences",            "backup_preferences",                       14, "", 0),
    ("Restore Preferences",           "restore_preferences",                      14, "", 0),
    ("Remove Backup Preferences",     "remove_backup_preferences",                14, "", 0),
    # ── 其他 ────────────────────────────────────────────────────────────────
    ("─── 其他 ──────────────────────", None, -1, "", 0),
    ("Send Input Event",              "send_input_event",                         15, "", 0),
]

# ─── Admin 相关枚举常量 ────────────────────────────────────────────────────────
_CONFIG_TYPES = [
    (0, "DEVICE_CONFIG (0)"),    (1, "POSITION_CONFIG (1)"), (2, "POWER_CONFIG (2)"),
    (3, "NETWORK_CONFIG (3)"),   (4, "DISPLAY_CONFIG (4)"),  (5, "LORA_CONFIG (5)"),
    (6, "BLUETOOTH_CONFIG (6)"), (7, "SECURITY_CONFIG (7)"),
    (8, "SESSIONKEY_CONFIG (8)"), (9, "DEVICEUI_CONFIG (9)"),
]
_MODULE_CONFIG_TYPES = [
    (0,  "MQTT_CONFIG (0)"),            (1,  "SERIAL_CONFIG (1)"),
    (2,  "EXTNOTIF_CONFIG (2)"),        (3,  "STOREFORWARD_CONFIG (3)"),
    (4,  "RANGETEST_CONFIG (4)"),       (5,  "TELEMETRY_CONFIG (5)"),
    (6,  "CANNEDMSG_CONFIG (6)"),       (7,  "AUDIO_CONFIG (7)"),
    (8,  "REMOTEHARDWARE_CONFIG (8)"),  (9,  "NEIGHBORINFO_CONFIG (9)"),
    (10, "AMBIENTLIGHTING_CONFIG (10)"),(11, "DETECTIONSENSOR_CONFIG (11)"),
    (12, "PAXCOUNTER_CONFIG (12)"),     (13, "STATUSMESSAGE_CONFIG (13)"),
    (14, "TRAFFICMANAGEMENT_CONFIG (14)"),
]
_BACKUP_LOCATIONS = [(0, "FLASH (0)"), (1, "SD (1)")]
_CHANNEL_ROLES    = [
    (0, "DISABLED (0)"),
    (1, "PRIMARY (1)"),
    (2, "SECONDARY (2)"),
]
_KV_MSG_TYPES     = [
    (0, "INITIATE_VERIFICATION (0)"), (1, "PROVIDE_SECURITY_NUMBER (1)"),
    (2, "DO_VERIFY (2)"), (3, "DO_NOT_VERIFY (3)"),
]
_ADMIN_NODE_ID_FIELDS = {
    "remove_by_nodenum",
    "set_favorite_node",
    "remove_favorite_node",
    "set_ignored_node",
    "remove_ignored_node",
}

_JOIN_V2_CHANNEL1_LABEL = "dragino-channel-1"
_JOIN_V2_CHANNEL2_LABEL = "dragino-channel-2"
_JOIN_V2_CHANNEL1_NAME = "dg-cfg"
_JOIN_V2_CHANNEL2_NAME = "dg-fn"


def _decode_optional_key_bytes(value: str, expected_len: int, field_label: str) -> bytes:
    raw = (value or "").strip()
    if not raw:
        return b""
    hex_raw = re.sub(r"[^0-9A-Fa-f]", "", raw)
    if len(hex_raw) == expected_len * 2 and re.fullmatch(r"[0-9A-Fa-f]+", hex_raw):
        return bytes.fromhex(hex_raw)
    try:
        decoded = _base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{field_label} 必须是 Base64 或 {expected_len * 2} 位 Hex") from exc
    if len(decoded) != expected_len:
        raise ValueError(f"{field_label} 解码后必须为{expected_len}字节，当前 {len(decoded)} 字节")
    return decoded


def _decode_required_key_bytes(value: str, expected_len: int, field_label: str) -> bytes:
    decoded = _decode_optional_key_bytes(value, expected_len, field_label)
    if not decoded:
        raise ValueError(f"Set Factory Identity 需要 {field_label}")
    return decoded


def _decode_network_seed_bytes(value: str, field_label: str = "network_seed") -> bytes:
    raw = (value or "").strip()
    if not raw:
        raise ValueError(f"{field_label} 必须填写")
    hex_raw = re.sub(r"[^0-9A-Fa-f]", "", raw)
    if 32 <= len(hex_raw) <= 64 and len(hex_raw) % 2 == 0 and re.fullmatch(r"[0-9A-Fa-f]+", hex_raw):
        decoded = bytes.fromhex(hex_raw)
    else:
        try:
            decoded = _base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"{field_label} 必须是 Base64 或 16-32字节 Hex") from exc
    if not 16 <= len(decoded) <= 32:
        raise ValueError(f"{field_label} 解码后必须为16-32字节，当前 {len(decoded)} 字节")
    return decoded


# ─── 样式常量 ─────────────────────────────────────────────────────────────────
_S_SEND = (
    "QPushButton { background:#1e4d2b; color:#6fcf97; border:1px solid #3d7a55; "
    "padding:5px 18px; border-radius:3px; font-weight:bold; font-size:13px; }"
    "QPushButton:hover { background:#2a6b3d; }"
    "QPushButton:disabled { background:#2d2d2d; color:#555; border-color:#444; }"
)
_S_SMALL = (
    "QPushButton { background:#2d2d2d; color:#ccc; border:1px solid #555; "
    "padding:3px 8px; border-radius:3px; }"
    "QPushButton:hover { background:#3d3d3d; }"
)
_S_NOW = (
    "QPushButton { background:#1a2d4a; color:#8cc8f0; border:1px solid #2a4a7a; "
    "padding:2px 8px; border-radius:3px; font-size:11px; }"
    "QPushButton:hover { background:#2a4a7a; }"
)
_S_INPUTS = """
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background:#252525; color:#dfe6e9; border:1px solid #555;
        padding:3px 6px; border-radius:3px;
    }
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus { border-color:#56ccf2; }
    QScrollArea { border: none; }
    QScrollBar:vertical { background:#1c1c1c; width:10px; }
    QScrollBar::handle:vertical { background:#444; border-radius:4px; min-height:20px; }
"""
_S_LOG = (
    "background:#111; color:#aaa; border:1px solid #333; "
    "font-family:Consolas,monospace; font-size:11px;"
)
_S_GROUP = (
    "QGroupBox { border:1px solid #3d3d3d; border-radius:4px; "
    "margin-top:6px; padding-top:8px; color:#aaa; }"
    "QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }"
)


# ─── SendPanel ────────────────────────────────────────────────────────────────

class SendPanel(QWidget):
    """
    发送数据包面板。

    Signals
    -------
    send_requested(MeshPacket)
        用户点击「发送」时发射，由 MainWindow 转给 SerialWorker.send_packet()。
    """

    send_requested = pyqtSignal(object)
    factory_profiles_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_S_INPUTS)

        self._known_nodes: dict[str, dict] = {}
        self._manual_nodes: dict[str, dict] = {}
        self._local_node_id: str = ""   # 本机节点 ID，my_info 后由 MainWindow 注入
        # 配置缓存：cfg_type(int) → (from_id: str, timestamp: float, cfg_dict: dict)
        self._config_cache: dict[int, tuple] = {}
        self._join_lock_cache: dict[str, dict] = {}
        self._factory_identity_profiles: dict[str, dict] = {}
        self._broadcast_private_config_ops = {
            "gateway_announce",
            "keep_awake",
            "set_sync_wakeup",
            "reset_network_config",
            "change_network_key",
            "trusted_gateway_config",
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)

        root.addWidget(self._build_routing_row())

        payload_group = self._build_payload_group()
        payload_group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(payload_group, stretch=1)

        root.addWidget(self._build_advanced_group())
        root.addLayout(self._build_send_row())
        root.addWidget(self._build_log_area())
        self._load_factory_identity_profiles()

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def update_nodes(self, nodes: dict):
        """更新「已知节点」下拉（由 MainWindow 调用）。"""
        merged_nodes = dict(self._manual_nodes)
        merged_nodes.update(nodes)
        self._known_nodes = merged_nodes
        # 保存当前选中的节点 ID，rebuild 后恢复
        current_nid = self.node_combo.currentData()
        if not current_nid:
            try:
                current_nid = self._normalize_node_id_text(self.node_combo.currentText())
            except Exception:
                current_nid = None
        was_blocked = self.node_combo.blockSignals(True)
        try:
            self.node_combo.clear()
            add_combo_item(self.node_combo, "— 从已知节点选择 —", None)
            restore_idx = 0
            for i, (nid, info) in enumerate(merged_nodes.items(), start=1):
                name  = info.get("long_name") or info.get("short_name") or ""
                label = f"{nid}  [{name}]" if name else nid
                add_combo_item(self.node_combo, label, nid)
                if nid == current_nid:
                    restore_idx = i
            self.node_combo.setCurrentIndex(restore_idx)
        finally:
            self.node_combo.blockSignals(was_blocked)

    def add_manual_node(self, node_id: str, select: bool = True) -> str:
        normalized = self._normalize_node_id_text(node_id)
        self._manual_nodes.setdefault(normalized, {
            "node_id": normalized,
            "long_name": "manual",
            "manual": True,
        })
        self.update_nodes(self._known_nodes)
        if select:
            self.select_node(normalized)
        return normalized

    def select_node(self, node_id: str, *, set_to: bool = True) -> bool:
        normalized = self._normalize_node_id_text(node_id)
        idx = self.node_combo.findData(normalized)
        if idx < 0:
            self.add_manual_node(normalized, select=False)
            idx = self.node_combo.findData(normalized)
        if idx >= 0:
            was_blocked = self.node_combo.blockSignals(True)
            try:
                self.node_combo.setCurrentIndex(idx)
            finally:
                self.node_combo.blockSignals(was_blocked)
        if set_to:
            self.to_edit.setText(normalized)
            self._sync_private_config_target_node_fields(normalized)
            self._select_join_lock_for_node(normalized, fill=False, set_to=True)
        return True

    def _normalize_node_id_text(self, text: str) -> str:
        token = (text or "").strip().split()[0] if (text or "").strip() else ""
        return f"!{_parse_required_node_id(token, 'node_id'):08x}"

    def _to_edit_matches_node(self, node_id: str) -> bool:
        try:
            return self._normalize_node_id_text(self.to_edit.text()) == self._normalize_node_id_text(node_id)
        except Exception:
            return False

    def _gateway_join_v2_target_node(self) -> str:
        candidates = (
            self._local_node_id,
            self.to_edit.text().strip() if hasattr(self, "to_edit") else "",
            self.pc_na_gwid_edit.text().strip() if hasattr(self, "pc_na_gwid_edit") else "",
        )
        for node_id in candidates:
            if not node_id:
                continue
            try:
                normalized = self._normalize_node_id_text(node_id)
            except Exception:
                continue
            if normalized != "!ffffffff":
                return normalized
        raise ValueError("Gateway JoinNetWorkV2 needs connected gateway my_info or a specific To node")

    def _set_pc_na_row_visible(self, field_widget: QWidget, visible: bool) -> None:
        form = getattr(self, "pc_na_form", None)
        if form is not None:
            label = form.labelForField(field_widget)
            if label is not None:
                label.setVisible(visible)
        field_widget.setVisible(visible)

    def _sync_private_config_target_node_fields(self, node_id: str | None = None) -> bool:
        if node_id is None:
            if not hasattr(self, "to_edit"):
                return False
            node_id = self.to_edit.text()
        try:
            normalized = self._normalize_node_id_text(node_id)
        except Exception:
            return False

        target_widgets = (
            "pc_dev_node_edit",
            "pc_reset_dev_node_edit",
            "pc_cck_dev_node_edit",
        )
        if normalized == "!ffffffff":
            for attr in target_widgets:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.clear()
            return True

        for attr in target_widgets:
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setText(normalized)
        return True

    def _on_to_text_changed(self, _text: str) -> None:
        self._sync_private_config_target_node_fields()

    def set_local_node(self, node_id: str):
        """MainWindow 收到 my_info 后调用，存储本机节点 ID。"""
        self._local_node_id = node_id
        if hasattr(self, "pc_fi_node_id_edit") and not self.pc_fi_node_id_edit.text().strip():
            self.pc_fi_node_id_edit.setText(node_id)
        if hasattr(self, "pc_ch12_node_id_edit") and not self.pc_ch12_node_id_edit.text().strip():
            self.pc_ch12_node_id_edit.setText(node_id)
        if (
            hasattr(self, "pc_op_combo")
            and self.pc_op_combo.currentData() == "join_network_v2_gateway"
            and node_id
        ):
            self.to_edit.setText(node_id)

    def update_sent_detail(self, packet_dict: dict, frame_hex: str):
        """发送成功后由 MainWindow 调用，更新 JSON/Hex 详情 Tab。"""
        import json as _json
        self.sent_json_edit.setPlainText(
            _json.dumps(packet_dict, ensure_ascii=False, indent=2)
        )
        # Hex：每行 16 字节，每 8 字节加空格
        groups = [frame_hex[i:i+2] for i in range(0, len(frame_hex), 2)]
        lines = []
        for i in range(0, len(groups), 16):
            chunk = groups[i:i+16]
            hex_part = " ".join(chunk[:8]) + "  " + " ".join(chunk[8:])
            lines.append(f"{i:04x}:  {hex_part}")
        self.sent_hex_edit.setPlainText("\n".join(lines))
        # 切到 JSON Tab 方便查看
        self._sent_tabs.setCurrentIndex(1)

    def log_result(self, success: bool, msg: str):
        """写入发送日志（由 MainWindow 调用）。"""
        ts    = datetime.now(timezone.utc).strftime("%H:%M:%S")
        sym   = "✓" if success else "✗"
        color = "#6fcf97" if success else "#ff8a80"
        msg = tr(msg)
        self.log_edit.append(
            f'<span style="color:{color}">[{ts}] {sym} {msg}</span>'
        )

    def log_response(self, req_summary: str, response_frame: dict):
        """收到对应响应时由 MainWindow 调用，在发送日志追加一条蓝色响应行。"""
        ts      = datetime.now(timezone.utc).strftime("%H:%M:%S")
        data    = response_frame.get("data") or {}
        decoded = data.get("decoded") or {}
        payload_parsed = decoded.get("payload_parsed") or {}
        # 取响应消息中以 _response 结尾的字段名作描述
        resp_variant = next(
            (k for k in payload_parsed if k.endswith("_response")),
            decoded.get("portnum_name", "ADMIN_APP"),
        )
        from_id = data.get("from_id", "?")
        req_label = tr("请求")
        self.log_edit.append(
            f'<span style="color:#a8d8ff">[{ts}] ↩ {resp_variant}'
            f'  from {from_id}'
            f'  <span style="color:#666">({req_label}: {tr(req_summary[:50])})</span></span>'
        )
        self._sent_tabs.setCurrentIndex(1)   # 切换到 JSON tab 显示响应内容

    def log_nak_warning(self, req_summary: str, err_code):
        """收到 ROUTING_APP NAK NO_RESPONSE 且请求为 Admin 时调用，显示托管模式诊断。"""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.log_edit.append(
            f'<span style="color:#ff8a80;font-weight:bold">[{ts}] ✕ NAK {err_code} — {tr("Admin 命令被设备拒绝")}</span><br>'
            f'<span style="color:#ffb347;font-size:10px;">{tr("请求")}: {tr(req_summary[:60])}</span><br>'
            f'<span style="color:#fc9c3a;font-size:10px;font-weight:bold">⚠ {tr("可能原因：设备处于托管模式 (config.security.is_managed=true)")}</span><br>'
            f'<span style="color:#bbb;font-size:10px;">'
            f'{tr("固件在 is_managed=true 时拒绝所有本地串口 Admin 命令，不返回任何响应。")}<br>'
            f'{tr("解决方法：在官方 App → Settings → Security → 关闭 Managed Mode 后重试。")}</span>'
        )
        self._sent_tabs.setCurrentIndex(0)   # 切换到日志 Tab 让用户看到警告

    def set_session_passkey_status(self, passkey: bytes, valid: bool, node_id: str = ""):
        """收到新 passkey 时由 MainWindow 调用，更新 Admin 页状态标签并自动填充输入框。"""
        if valid and passkey:
            hex_str = passkey.hex()
            node_tag = f" [{node_id}]" if node_id else ""
            set_widget_text(self.passkey_status_lbl, f"● 已自动存储{node_tag} {len(passkey)} 字节  (有效 ~270s)")
            self.passkey_status_lbl.setStyleSheet("color:#6fcf97; font-size:10px;")
            # 自动填入 adm_passkey_edit（只在为空或内容与当前节点对应时更新）
            self.adm_passkey_edit.setText(hex_str)
        else:
            set_widget_text(self.passkey_status_lbl, "○ 未获取（发送任意 GET 后自动存储）")
            self.passkey_status_lbl.setStyleSheet("color:#888; font-size:10px;")

    def fill_nodeinfo_from_virtual_identity(
        self,
        node_id: str,
        long_name: str,
        short_name: str,
        hw_model: int,
        role: int,
        pub_key_b64: str,
    ):
        """将虚拟身份信息填充到 NodeInfo 发送页面。"""
        import base64 as _base64
        self.ni_id_edit.setText(node_id)
        self.ni_long_edit.setText(long_name[:40])
        self.ni_short_edit.setText(short_name[:4])
        # 设置 hw_model 下拉
        for i in range(self.ni_hw_combo.count()):
            if self.ni_hw_combo.itemData(i) == hw_model:
                self.ni_hw_combo.setCurrentIndex(i)
                break
        # 设置 role 下拉
        for i in range(self.ni_role_combo.count()):
            if self.ni_role_combo.itemData(i) == role:
                self.ni_role_combo.setCurrentIndex(i)
                break
        self.ni_pubkey_edit.setText(pub_key_b64)
        # 同步发送页 From 字段（使虚拟ID为发送来源）
        self.to_edit.setText(node_id if node_id else "!ffffffff")

    def fill_global_from_vi(
        self,
        global_pub_b64: str,
        gw_pub_b64: str,
        gw_node_hex: str,
        network_seed_b64: str = "",
    ):
        """将 Network 身份信息填充到 Private Config 页的 JoinNetWorkV2 表单。"""
        self.pc_cpub_edit.setText(global_pub_b64)
        self.pc_gwpub_edit.setText(gw_pub_b64)
        self.pc_gwid_edit.setText(gw_node_hex)
        if hasattr(self, "pc_na_global_pub_edit"):
            self.pc_na_global_pub_edit.setText(global_pub_b64)
            self.pc_na_gwpub_edit.setText(gw_pub_b64)
            self.pc_na_gwid_edit.setText(gw_node_hex)
        if network_seed_b64 and hasattr(self, "pc_jv2_seed_edit"):
            self.pc_jv2_seed_edit.setText(network_seed_b64)
            try:
                seed = self._join_v2_seed_from_ui()
                node_id = self.pc_na_join_combo.currentData() if hasattr(self, "pc_na_join_combo") else ""
                self._fill_join_v2_derived_channel12(seed, node_id if node_id else None, save=bool(node_id))
            except Exception:
                pass
        # 切换到 Private Config 页并选中 JoinNetWorkV2 操作
        target_op = self.pc_op_combo.currentData()
        if target_op != "join_network_v2":
            target_op = "join_network_v2"
        for i in range(self.pc_op_combo.count()):
            if self.pc_op_combo.itemData(i) == target_op:
                self.pc_op_combo.setCurrentIndex(i)
                break

    def fill_enrollment_from_vi(
        self,
        company_pub_b64: str,
        gw_pub_b64: str,
        gw_node_hex: str,
    ):
        """Legacy wrapper."""
        self.fill_global_from_vi(company_pub_b64, gw_pub_b64, gw_node_hex)

    def update_join_lock_advertise(
        self,
        node_id: str,
        sn: str,
        dev_eui: str,
        join_challenge: bytes,
    ) -> None:
        import base64 as _b64
        import time as _t

        if not node_id or len(join_challenge) != 16:
            return

        self._join_lock_cache[node_id] = {
            "node_id": node_id,
            "sn": sn or "",
            "dev_eui": dev_eui or "",
            "join_challenge": bytes(join_challenge),
            "received_at": _t.time(),
            "source": "advertise",
        }
        prof = dict(self._factory_identity_profiles.get(node_id, {}))
        if prof:
            changed = False
            if sn and not prof.get("sn"):
                prof["sn"] = sn
                changed = True
            if dev_eui and not prof.get("dev_eui"):
                prof["dev_eui"] = dev_eui
                changed = True
            if changed:
                self._factory_identity_profiles[node_id] = prof
                self._save_factory_identity_profiles()
                self._refresh_factory_identity_profile_combo(select_node_id=node_id)
        self._refresh_join_lock_combo(select_node_id=node_id)

        if self.pc_op_combo.currentData() == "join_network_v2" and self._to_edit_matches_node(node_id):
            self.pc_na_challenge_edit.setText(_b64.b64encode(join_challenge).decode())
            self._fill_device_private_key_from_profile(node_id)
            self._fill_join_v2_seed_from_profile(node_id)
            self.pc_na_sig_edit.clear()
            self.pc_na_timestamp_edit.clear()
            if hasattr(self, "pc_ch12_node_id_edit"):
                self.pc_ch12_node_id_edit.setText(node_id)
            self._fill_channel12_from_profile(node_id, overwrite=False)

    def _refresh_join_lock_combo(self, select_node_id: str | None = None) -> None:
        if not hasattr(self, "pc_na_join_combo"):
            return

        current = select_node_id or self.pc_na_join_combo.currentData()
        was_blocked = self.pc_na_join_combo.blockSignals(True)
        try:
            self.pc_na_join_combo.clear()
            add_combo_item(self.pc_na_join_combo, "无缓存 JoinLockAdvertise", None)
            for node_id, item in self._join_lock_cache.items():
                sn = item.get("sn") or "-"
                dev_eui = item.get("dev_eui") or "-"
                source = item.get("source", "")
                suffix = (
                    f"  [{tr('本地档案，等待真实JoinLock')}]"
                    if source == "local_profile"
                    else f"  [{tr('真实JoinLock')}]"
                )
                add_combo_item(self.pc_na_join_combo, f"{node_id}  SN={sn}  EUI={dev_eui}{suffix}", node_id)
            if current:
                idx = self.pc_na_join_combo.findData(current)
                if idx >= 0:
                    self.pc_na_join_combo.setCurrentIndex(idx)
        finally:
            self.pc_na_join_combo.blockSignals(was_blocked)
        self.pc_na_fill_join_btn.setEnabled(bool(self.pc_na_join_combo.currentData()))

    def _on_join_lock_combo_changed(self, _idx: int) -> None:
        if hasattr(self, "pc_na_fill_join_btn"):
            self.pc_na_fill_join_btn.setEnabled(bool(self.pc_na_join_combo.currentData()))
        self._sync_join_lock_target_from_combo(fill=False)

    def _select_join_lock_for_node(self, node_id: str, fill: bool = False, *, set_to: bool = True) -> bool:
        if not node_id or not hasattr(self, "pc_na_join_combo"):
            return False
        try:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
        except Exception:
            normalized = node_id

        idx = self.pc_na_join_combo.findData(normalized)
        if idx < 0:
            self.pc_na_fill_join_btn.setEnabled(False)
            return False

        if self.pc_na_join_combo.currentIndex() != idx:
            was_blocked = self.pc_na_join_combo.blockSignals(True)
            try:
                self.pc_na_join_combo.setCurrentIndex(idx)
            finally:
                self.pc_na_join_combo.blockSignals(was_blocked)
        if set_to:
            self._sync_join_lock_target_from_combo(fill=False, set_to=True)
        if fill:
            self._on_fill_join_lock_clicked()
        return True

    def _sync_join_lock_target_from_combo(self, fill: bool = False, *, set_to: bool = True) -> bool:
        if not hasattr(self, "pc_na_join_combo"):
            return False
        node_id = self.pc_na_join_combo.currentData()
        if not node_id:
            return False

        if set_to:
            self.to_edit.setText(node_id)
        if hasattr(self, "pc_ch12_node_id_edit"):
            self.pc_ch12_node_id_edit.setText(node_id)
        self._fill_channel12_from_profile(node_id, overwrite=False)
        self._fill_join_v2_seed_from_profile(node_id)

        if fill:
            self._on_fill_join_lock_clicked()
        return True

    def _on_fill_join_lock_clicked(self) -> None:
        import base64 as _b64

        node_id = self.pc_na_join_combo.currentData()
        item = self._join_lock_cache.get(node_id or "")
        if not item:
            return
        if item.get("source") == "local_profile":
            self.log_result(False, "当前选中的是本地 FactoryIdentity 档案，不是真实 JoinLockAdvertise；请切到网关侧等待远端节点广播 JoinLock")
            return

        self.pc_na_challenge_edit.setText(_b64.b64encode(item["join_challenge"]).decode())
        self._fill_device_private_key_from_profile(item["node_id"])
        self._fill_join_v2_seed_from_profile(item["node_id"])
        self.pc_na_sig_edit.clear()
        self.pc_na_timestamp_edit.clear()
        self.to_edit.setText(item["node_id"])
        if hasattr(self, "pc_ch12_node_id_edit"):
            self.pc_ch12_node_id_edit.setText(item["node_id"])
        self._fill_channel12_from_profile(item["node_id"], overwrite=False)

    def _on_generate_factory_identity_keys(self) -> None:
        import base64 as _b64
        try:
            from meshdebug.pki_crypto import generate_keypair
            device_priv, device_pub = generate_keypair()
        except Exception as exc:
            self.log_result(False, f"生成 Meshtastic device key 失败: {exc}")
            return

        self.pc_fi_device_priv_edit.setText(_b64.b64encode(device_priv).decode())
        if not self.pc_fi_node_id_edit.text().strip() and self._local_node_id:
            self.pc_fi_node_id_edit.setText(self._local_node_id)
        self.log_result(
            True,
            "已生成 FactoryIdentity device_private_key。\n"
            "device_private_key 会写入工厂身份，并用于 Join/ChangeAdmin auth_code。\n"
            f"device_public_key: {_b64.b64encode(device_pub).decode()}"
        )

    def _cache_join_lock_from_profile(self, node_id: str, profile: dict, *, select: bool = True) -> bool:
        import base64 as _b64
        import time as _t

        try:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
            device_private_key = _b64.b64decode(profile.get("device_private_key", "") or profile.get("flash_private_key", ""))
        except Exception:
            return False
        if len(device_private_key) != 32:
            return False

        existing = self._join_lock_cache.get(normalized)
        if existing and existing.get("source") != "local_profile":
            self._refresh_join_lock_combo(select_node_id=normalized if select else None)
            if select:
                self._select_join_lock_for_node(normalized, fill=False)
            return True

        self._join_lock_cache[normalized] = {
            "node_id": normalized,
            "sn": profile.get("sn", ""),
            "dev_eui": profile.get("dev_eui", ""),
            "join_challenge": b"",
            "received_at": _t.time(),
            "source": "local_profile",
        }
        self._refresh_join_lock_combo(select_node_id=normalized if select else None)
        if select:
            self._select_join_lock_for_node(normalized, fill=False)
        return True

    def get_factory_identity_profile(self, node_id: str) -> dict | None:
        try:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
        except Exception:
            return None
        prof = self._factory_identity_profiles.get(normalized)
        return dict(prof) if prof else None

    def list_factory_identity_profiles(self) -> dict[str, dict]:
        return {node_id: dict(profile) for node_id, profile in self._factory_identity_profiles.items()}

    def load_factory_identity_profile_for_node(self, node_id: str) -> bool:
        try:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
        except Exception:
            return False
        prof = self._factory_identity_profiles.get(normalized)
        if not prof:
            return False
        self._refresh_factory_identity_profile_combo(select_node_id=normalized)
        self._apply_factory_identity_profile(prof)
        self._cache_join_lock_from_profile(normalized, prof, select=True)
        self.to_edit.setText(normalized)
        self._fill_join_v2_seed_from_profile(normalized)
        self._fill_channel12_from_profile(normalized, overwrite=True)
        self._select_join_lock_for_node(normalized, fill=False)
        return True

    def clear_factory_identity_profile_for_node(self, node_id: str) -> bool:
        try:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
        except Exception:
            return False
        if normalized not in self._factory_identity_profiles:
            return False

        self._factory_identity_profiles.pop(normalized, None)
        cached = self._join_lock_cache.get(normalized)
        if cached and cached.get("source") == "local_profile":
            self._join_lock_cache.pop(normalized, None)
        self._save_factory_identity_profiles()
        self._refresh_factory_identity_profile_combo()
        self._refresh_channel12_profile_combo()
        self._refresh_join_lock_combo()
        self.factory_profiles_changed.emit()

        current_to = ""
        try:
            current_to = self._normalize_profile_node_id(self.to_edit.text(), "node_id")
        except Exception:
            pass
        if current_to == normalized:
            self.pc_fi_node_id_edit.setText(normalized)
            self.pc_fi_sn_edit.clear()
            self.pc_fi_deveui_edit.clear()
            self.pc_fi_device_priv_edit.clear()
            if hasattr(self, "pc_fi_legacy_app_key_edit"):
                self.pc_fi_legacy_app_key_edit.clear()
            self.pc_fi_mfg_ts_edit.clear()
            self.pc_na_device_priv_edit.clear()
            if hasattr(self, "pc_na_challenge_edit"):
                self.pc_na_challenge_edit.clear()
            if hasattr(self, "pc_ch12_node_id_edit"):
                self.pc_ch12_node_id_edit.setText(normalized)
            self.pc_ch1_name_edit.clear()
            self.pc_ch1_psk_edit.clear()
            self.pc_ch2_name_edit.clear()
            self.pc_ch2_psk_edit.clear()

        self.log_result(True, f"已清除 FactoryIdentity 本地档案: {normalized}")
        return True

    def save_factory_identity_profile(self, profile: dict, *, select: bool = True, apply: bool = False) -> dict:
        normalized = self._normalize_profile_node_id(profile.get("node_id", ""), "node_id")
        merged = dict(self._factory_identity_profiles.get(normalized, {}))
        merged.update(profile)
        merged["node_id"] = normalized
        try:
            import base64 as _b64
            from meshdebug.pki_crypto import public_key_from_private

            device_private_key = _b64.b64decode(merged.get("device_private_key", "") or merged.get("flash_private_key", ""))
            if len(device_private_key) == 32:
                device_public_key_b64 = _b64.b64encode(public_key_from_private(device_private_key)).decode()
                merged["device_public_key"] = device_public_key_b64
                merged["flash_public_key"] = device_public_key_b64
        except Exception:
            pass
        try:
            legacy_app_key = _decode_optional_key_bytes(
                merged.get("legacy_app_key", "") or merged.get("legacy_app_key_hex", ""),
                16,
                "legacy_app_key",
            )
            if legacy_app_key:
                merged["legacy_app_key"] = _b64.b64encode(legacy_app_key).decode()
                merged["legacy_app_key_hex"] = legacy_app_key.hex().upper()
        except Exception:
            pass
        self._factory_identity_profiles[normalized] = merged
        self._save_factory_identity_profiles()
        self._refresh_factory_identity_profile_combo(select_node_id=normalized if select else None)
        self._refresh_channel12_profile_combo(select_node_id=normalized if select else None)
        self._cache_join_lock_from_profile(normalized, merged, select=apply)
        self._fill_join_v2_seed_from_profile(normalized)
        if apply:
            self._apply_factory_identity_profile(merged)
            self.to_edit.setText(normalized)
            self._select_join_lock_for_node(normalized, fill=False)
        self.factory_profiles_changed.emit()
        self.log_result(True, f"已保存 FactoryIdentity 档案: {normalized}")
        return dict(merged)

    def generate_factory_identity_profile_for_node(
        self,
        node_id: str,
        *,
        sn: str = "",
        dev_eui: str = "",
        network_seed_b64: str = "",
        overwrite: bool = True,
    ) -> dict:
        import base64 as _b64
        from meshdebug.pki_crypto import generate_keypair

        normalized = self._normalize_profile_node_id(node_id, "node_id")
        existing = dict(self._factory_identity_profiles.get(normalized, {}))
        if existing and not overwrite:
            self.load_factory_identity_profile_for_node(normalized)
            return existing

        device_priv, device_pub = generate_keypair()
        network_seed = _b64.b64decode(network_seed_b64) if network_seed_b64 else b""
        if network_seed and not 16 <= len(network_seed) <= 32:
            raise ValueError(f"network_seed must be 16-32 bytes, got {len(network_seed)}")
        dev_eui_hex = re.sub(r"[^0-9A-Fa-f]", "", dev_eui or existing.get("dev_eui", ""))

        seed_b64 = _b64.b64encode(network_seed).decode() if network_seed else existing.get("join_v2_network_seed", "")
        profile = dict(existing)
        profile.update({
            "node_id": normalized,
            "factory_version": int(existing.get("factory_version", 1) or 1),
            "sn": sn or existing.get("sn", ""),
            "dev_eui": dev_eui_hex.upper(),
            "device_private_key": _b64.b64encode(device_priv).decode(),
            "device_public_key": _b64.b64encode(device_pub).decode(),
            "manufacturing_timestamp": int(existing.get("manufacturing_timestamp") or _time.time()),
            "status": int(existing.get("status", 1) or 1),
        })
        if existing.get("legacy_app_key"):
            profile["legacy_app_key"] = existing.get("legacy_app_key", "")
        if existing.get("legacy_app_key_hex"):
            profile["legacy_app_key_hex"] = existing.get("legacy_app_key_hex", "")
        if seed_b64:
            profile["join_v2_network_seed"] = seed_b64
        if network_seed:
            self.pc_jv2_seed_edit.setText(seed_b64)
            channel12 = self._fill_join_v2_derived_channel12(network_seed, normalized, save=False)
            profile["channel12"] = channel12

        self._factory_identity_profiles[normalized] = profile
        self._save_factory_identity_profiles()
        self._refresh_factory_identity_profile_combo(select_node_id=normalized)
        self._refresh_channel12_profile_combo(select_node_id=normalized)
        self._apply_factory_identity_profile(profile)
        self.to_edit.setText(normalized)
        self._fill_join_v2_seed_from_profile(normalized)
        self._cache_join_lock_from_profile(normalized, profile, select=True)
        self._select_join_lock_for_node(normalized, fill=False)
        self.factory_profiles_changed.emit()
        self.log_result(True, f"已生成并绑定 FactoryIdentity 档案: {normalized}")
        return dict(profile)

    def _fill_network_access_flash_private_from_profile(self, node_id: str, flash_public_id: bytes = b"") -> bool:
        import base64 as _b64

        lookup_node_id = node_id or ""
        if lookup_node_id:
            try:
                lookup_node_id = f"!{_parse_required_node_id(lookup_node_id, 'node_id'):08x}"
            except Exception:
                pass
        profile = self._factory_identity_profiles.get(lookup_node_id)
        if not profile:
            return False
        try:
            private_key = _b64.b64decode(profile.get("device_private_key", "") or profile.get("flash_private_key", ""))
        except Exception:
            private_key = b""
        if len(private_key) != 32:
            if hasattr(self, "pc_na_flash_priv_edit"):
                self.pc_na_flash_priv_edit.clear()
            return False
        self.pc_na_flash_priv_edit.setText(_b64.b64encode(private_key).decode())
        return True

    def _fill_device_private_key_from_profile(self, node_id: str) -> bool:
        return self._fill_network_access_flash_private_from_profile(node_id, b"")

    def _join_v2_seed_from_ui(self, generate_if_empty: bool = False) -> bytes:
        import base64 as _b64
        import os as _os

        seed_b64 = self.pc_jv2_seed_edit.text().strip() if hasattr(self, "pc_jv2_seed_edit") else ""
        if not seed_b64 and generate_if_empty:
            seed = _os.urandom(16)
            self.pc_jv2_seed_edit.setText(_b64.b64encode(seed).decode())
            return seed
        if not seed_b64:
            raise ValueError("JoinNetWorkV2 needs network_seed")
        seed = _b64.b64decode(seed_b64)
        if not 16 <= len(seed) <= 32:
            raise ValueError(f"network_seed must be 16-32 bytes, got {len(seed)}")
        return seed

    def _fill_join_v2_seed_from_profile(self, node_id: str) -> bool:
        import base64 as _b64

        if not hasattr(self, "pc_jv2_seed_edit"):
            return False
        try:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
        except Exception:
            return False
        profile = self._factory_identity_profiles.get(normalized, {})
        seed_b64 = (profile.get("join_v2_network_seed") or profile.get("network_seed") or "").strip()
        if not seed_b64:
            return False
        try:
            seed = _b64.b64decode(seed_b64)
        except Exception:
            return False
        if not 16 <= len(seed) <= 32:
            return False
        self.pc_jv2_seed_edit.setText(seed_b64)
        try:
            self._fill_join_v2_derived_channel12(seed, normalized, save=False)
        except Exception:
            pass
        return True

    def _fill_join_v2_derived_channel12(
        self,
        network_seed: bytes,
        node_id: str | None = None,
        save: bool = False,
    ) -> dict:
        import base64 as _b64

        from meshdebug.pki_crypto import derive_join_network_v2_psk

        psk1 = derive_join_network_v2_psk(_JOIN_V2_CHANNEL1_LABEL, network_seed)
        psk2 = derive_join_network_v2_psk(_JOIN_V2_CHANNEL2_LABEL, network_seed)
        channel12 = {
            "send_channel": 0,
            "channel1_name": _JOIN_V2_CHANNEL1_NAME,
            "psk1": _b64.b64encode(psk1).decode(),
            "channel2_name": _JOIN_V2_CHANNEL2_NAME,
            "psk2": _b64.b64encode(psk2).decode(),
        }

        if hasattr(self, "pc_ch12_send_channel_spin"):
            self.pc_ch12_send_channel_spin.setValue(0)
        self.pc_ch1_name_edit.setText(channel12["channel1_name"])
        self.pc_ch1_psk_edit.setText(channel12["psk1"])
        self.pc_ch2_name_edit.setText(channel12["channel2_name"])
        self.pc_ch2_psk_edit.setText(channel12["psk2"])

        if node_id:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
            self.pc_ch12_node_id_edit.setText(normalized)
            if save:
                seed_b64 = _b64.b64encode(network_seed).decode()
                prof = dict(self._factory_identity_profiles.get(normalized, {}))
                prof["node_id"] = normalized
                prof["join_v2_network_seed"] = seed_b64
                prof["channel12"] = channel12
                self._factory_identity_profiles[normalized] = prof
                self._save_factory_identity_profiles()
                self._refresh_factory_identity_profile_combo(select_node_id=normalized)
                self._refresh_channel12_profile_combo(select_node_id=normalized)
                self.factory_profiles_changed.emit()
        return channel12

    def _on_generate_join_v2_seed_clicked(self, _checked: object = None) -> None:
        node_id = self.pc_na_join_combo.currentData() or self.to_edit.text().strip()
        try:
            seed = self._join_v2_seed_from_ui()
            self._fill_join_v2_derived_channel12(seed, node_id if node_id else None, save=bool(node_id))
            self.log_result(True, "已按当前 network_seed 派生 Channel 1/2")
        except Exception as exc:
            self.log_result(False, f"派生 Channel 1/2 失败，请先在 Global 界面生成并加载 network_seed: {exc}")

    def _on_generate_change_network_seed_clicked(self, _checked: object = None) -> None:
        import os as _os

        seed = _os.urandom(16)
        self.pc_new_seed_edit.setText(_base64.b64encode(seed).decode())
        self.log_result(True, "已生成 new_network_seed")

    def _on_fill_empty_reset_auth_clicked(self, _checked: object = None) -> None:
        self._pc_reset_timestamp = int(_time.time())
        self.pc_reset_sig_edit.setText(_base64.b64encode(bytes(32)).decode())
        self.log_result(True, "已填充 ResetNetworkConfig 空 auth_code")

    def _on_fill_empty_cck_auth_clicked(self, _checked: object = None) -> None:
        self._pc_cck_timestamp = int(_time.time())
        self.pc_cck_sig_edit.setText(_base64.b64encode(bytes(32)).decode())
        self.log_result(True, "已填充 ChangeNetworkKey 空 auth_code")

    def _on_gateway_announce_fill_from_join_v2_clicked(self, _checked: object = None) -> None:
        if hasattr(self, "pc_jv2_seed_edit"):
            self.pc_ga_seed_edit.setText(self.pc_jv2_seed_edit.text().strip())
        if hasattr(self, "pc_na_global_pub_edit") and self.pc_na_global_pub_edit.text().strip():
            self.pc_ga_pub_edit.setText(self.pc_na_global_pub_edit.text().strip())
        self.log_result(True, "已从 JoinV2 区域复制 network_seed/network_public_key")

    def _on_gateway_announce_auth_clicked(self, _checked: object = None) -> None:
        try:
            from meshdebug.pki_crypto import hmac_gateway_announce

            network_pub = _base64.b64decode(self.pc_ga_pub_edit.text().strip(), validate=True)
            network_seed = _decode_network_seed_bytes(self.pc_ga_seed_edit.text(), "network_seed")
            auth_code = hmac_gateway_announce(network_seed, network_pub)
            self.pc_ga_auth_edit.setText(_base64.b64encode(auth_code).decode())
            self.log_result(True, "已生成 GatewayAnnounce.auth_code")
        except Exception as exc:
            self.log_result(False, f"生成 GatewayAnnounce.auth_code 失败: {exc}")

    def _normalize_profile_node_id(self, node_id: str, field_label: str = "node_id") -> str:
        node_id = (node_id or "").strip()
        if not node_id:
            raise ValueError(f"请填写 {field_label}")
        return f"!{_parse_required_node_id(node_id, field_label):08x}"

    def _channel12_profile_node_id(self) -> str:
        node_id = self.pc_ch12_node_id_edit.text().strip() if hasattr(self, "pc_ch12_node_id_edit") else ""
        if not node_id:
            node_id = self.to_edit.text().strip()
        if not node_id or _parse_node_id(node_id) == 0xFFFFFFFF:
            node_id = self.pc_fi_node_id_edit.text().strip() if hasattr(self, "pc_fi_node_id_edit") else ""
        if not node_id:
            node_id = self.pc_ch12_profile_combo.currentData() if hasattr(self, "pc_ch12_profile_combo") else ""
        return self._normalize_profile_node_id(node_id, "Channel12 target node_id")

    def _refresh_channel12_profile_combo(self, select_node_id: str | None = None) -> None:
        if not hasattr(self, "pc_ch12_profile_combo"):
            return
        current = select_node_id or self.pc_ch12_profile_combo.currentData()
        was_blocked = self.pc_ch12_profile_combo.blockSignals(True)
        try:
            self.pc_ch12_profile_combo.clear()
            add_combo_item(self.pc_ch12_profile_combo, "无保存信道配置", None)
            for node_id in sorted(self._factory_identity_profiles):
                prof = self._factory_identity_profiles[node_id]
                ch = prof.get("channel12") or {}
                ch1 = ch.get("channel1_name") or "-"
                ch2 = ch.get("channel2_name") or "-"
                send_ch = ch.get("send_channel", "-")
                sn = prof.get("sn") or "-"
                add_combo_item(self.pc_ch12_profile_combo, f"{node_id}  SN={sn}  TXCH={send_ch}  CH={ch1}/{ch2}", node_id)
            if current:
                idx = self.pc_ch12_profile_combo.findData(current)
                if idx >= 0:
                    self.pc_ch12_profile_combo.setCurrentIndex(idx)
        finally:
            self.pc_ch12_profile_combo.blockSignals(was_blocked)

    def _channel12_send_channel_value(self) -> int:
        if hasattr(self, "pc_ch12_send_channel_spin"):
            value = self.pc_ch12_send_channel_spin.value()
        else:
            value = self.channel_spin.value()
        return max(0, min(7, int(value)))

    def _collect_channel12_profile(self) -> tuple[str, dict]:
        import base64 as _b64

        node_id = self._channel12_profile_node_id()
        self.pc_ch12_node_id_edit.setText(node_id)
        ch1 = self.pc_ch1_name_edit.text().strip()
        ch2 = self.pc_ch2_name_edit.text().strip()
        psk1_b64 = self.pc_ch1_psk_edit.text().strip()
        psk2_b64 = self.pc_ch2_psk_edit.text().strip()
        if not all([ch1, ch2, psk1_b64, psk2_b64]):
            raise ValueError("Channel12Config 需要 channel1/2 name 和 psk1/2")
        psk1 = _b64.b64decode(psk1_b64)
        psk2 = _b64.b64decode(psk2_b64)
        if len(psk1) < 16 or len(psk1) > 32:
            raise ValueError(f"psk1 解码后必须为16-32字节，当前 {len(psk1)} 字节")
        if len(psk2) < 16 or len(psk2) > 32:
            raise ValueError(f"psk2 解码后必须为16-32字节，当前 {len(psk2)} 字节")
        return node_id, {
            "send_channel": self._channel12_send_channel_value(),
            "channel1_name": ch1,
            "psk1": psk1_b64,
            "channel2_name": ch2,
            "psk2": psk2_b64,
        }

    def _apply_channel12_profile(self, prof: dict, overwrite: bool = True) -> bool:
        ch = prof.get("channel12") or {}
        if not ch:
            return False
        if not overwrite and any([
            self.pc_ch1_name_edit.text().strip(),
            self.pc_ch1_psk_edit.text().strip(),
            self.pc_ch2_name_edit.text().strip(),
            self.pc_ch2_psk_edit.text().strip(),
        ]):
            return False
        try:
            send_channel = max(0, min(7, int(ch.get("send_channel", self.channel_spin.value()))))
            if hasattr(self, "pc_ch12_send_channel_spin"):
                self.pc_ch12_send_channel_spin.setValue(send_channel)
            self.channel_spin.setValue(send_channel)
        except Exception:
            pass
        self.pc_ch1_name_edit.setText(ch.get("channel1_name", ""))
        self.pc_ch1_psk_edit.setText(ch.get("psk1", ""))
        self.pc_ch2_name_edit.setText(ch.get("channel2_name", ""))
        self.pc_ch2_psk_edit.setText(ch.get("psk2", ""))
        return True

    def _fill_channel12_from_profile(self, node_id: str, overwrite: bool = False) -> bool:
        try:
            normalized = self._normalize_profile_node_id(node_id, "node_id")
        except Exception:
            return False
        prof = self._factory_identity_profiles.get(normalized)
        if not prof:
            return False
        ok = self._apply_channel12_profile(prof, overwrite=overwrite)
        if ok:
            self.pc_ch12_node_id_edit.setText(normalized)
            self._refresh_channel12_profile_combo(select_node_id=normalized)
        return ok

    def _on_channel12_profile_load_clicked(self, _checked: object = None) -> None:
        node_id = self.pc_ch12_profile_combo.currentData()
        if not node_id:
            return
        prof = self._factory_identity_profiles.get(node_id)
        if not prof:
            return
        if self._apply_channel12_profile(prof, overwrite=True):
            self.to_edit.setText(node_id)
            self.pc_ch12_node_id_edit.setText(node_id)
        else:
            self.log_result(False, f"节点 {node_id} 没有保存 Channel12 配置")

    def _on_channel12_autofill_clicked(self, _checked: object = None) -> None:
        try:
            node_id = self._channel12_profile_node_id()
        except Exception as exc:
            self.log_result(False, f"自动填充 Channel12 失败: {exc}")
            return
        if self._fill_channel12_from_profile(node_id, overwrite=True):
            self.to_edit.setText(node_id)
            self.log_result(True, f"已从节点档案自动填充 Channel12: {node_id}")
        else:
            self.log_result(False, f"节点 {node_id} 没有保存 Channel12 配置")

    def _save_channel12_profile_from_ui(self, auto: bool = False) -> bool:
        try:
            node_id, channel12 = self._collect_channel12_profile()
            prof = dict(self._factory_identity_profiles.get(node_id, {}))
            prof["node_id"] = node_id
            prof["channel12"] = channel12
            self._factory_identity_profiles[node_id] = prof
            self._save_factory_identity_profiles()
            self._refresh_factory_identity_profile_combo(select_node_id=node_id)
            self._refresh_channel12_profile_combo(select_node_id=node_id)
            self.to_edit.setText(node_id)
            self.channel_spin.setValue(channel12["send_channel"])
            self.factory_profiles_changed.emit()
            if not auto:
                self.log_result(True, f"已保存 Channel12 配置: {node_id}")
            return True
        except Exception as exc:
            self.log_result(False, f"保存 Channel12 配置失败: {exc}")
            return False

    def _on_channel12_profile_save_clicked(self, _checked: object = None) -> None:
        self._save_channel12_profile_from_ui(auto=False)

    def _factory_identity_registry_path(self) -> str:
        base_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        return os.path.join(base_dir, "factory_identity_profiles.json")

    def _load_factory_identity_profiles(self) -> None:
        path = self._factory_identity_registry_path()
        if not os.path.exists(path):
            self._refresh_factory_identity_profile_combo()
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            self.log_result(False, f"加载 FactoryIdentity 档案失败: {exc}")
            self._refresh_factory_identity_profile_combo()
            return
        profiles = data.get("factory_identities", data if isinstance(data, dict) else {})
        normalized_profiles: dict[str, dict] = {}
        if isinstance(profiles, dict):
            for raw_node_id, raw_profile in profiles.items():
                if not isinstance(raw_profile, dict):
                    continue
                try:
                    node_id = self._normalize_profile_node_id(
                        raw_profile.get("node_id") or raw_node_id,
                        "node_id",
                    )
                except Exception:
                    continue
                prof = dict(raw_profile)
                prof["node_id"] = node_id
                normalized_profiles[node_id] = prof
        self._factory_identity_profiles = normalized_profiles
        self._refresh_factory_identity_profile_combo()
        for node_id, prof in self._factory_identity_profiles.items():
            self._cache_join_lock_from_profile(node_id, prof, select=False)
        self._refresh_join_lock_combo()

    def _save_factory_identity_profiles(self) -> None:
        path = self._factory_identity_registry_path()
        data = {"factory_identities": self._factory_identity_profiles}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _refresh_factory_identity_profile_combo(self, select_node_id: str | None = None) -> None:
        if not hasattr(self, "pc_fi_profile_combo"):
            return
        current = select_node_id or self.pc_fi_profile_combo.currentData()
        was_blocked = self.pc_fi_profile_combo.blockSignals(True)
        try:
            self.pc_fi_profile_combo.clear()
            add_combo_item(self.pc_fi_profile_combo, "无保存档案", None)
            for node_id in sorted(self._factory_identity_profiles):
                prof = self._factory_identity_profiles[node_id]
                sn = prof.get("sn") or "-"
                dev_eui = prof.get("dev_eui") or "-"
                add_combo_item(self.pc_fi_profile_combo, f"{node_id}  SN={sn}  EUI={dev_eui}", node_id)
            if current:
                idx = self.pc_fi_profile_combo.findData(current)
                if idx >= 0:
                    self.pc_fi_profile_combo.setCurrentIndex(idx)
        finally:
            self.pc_fi_profile_combo.blockSignals(was_blocked)
        self._refresh_channel12_profile_combo(select_node_id=select_node_id)

    def _collect_factory_identity_profile(self) -> dict:
        import base64 as _b64

        node_id = self.pc_fi_node_id_edit.text().strip() or self._local_node_id or ""
        if not node_id:
            raise ValueError("请填写 node_id，或先连接节点获取本机节点ID")
        node_id = f"!{_parse_required_node_id(node_id, 'node_id'):08x}"
        sn = self.pc_fi_sn_edit.text().strip()
        dev_eui_hex = re.sub(r"[^0-9A-Fa-f]", "", self.pc_fi_deveui_edit.text())
        flash_pub_b64 = self.pc_fi_flash_pub_edit.text().strip()
        flash_priv_b64 = self.pc_fi_flash_priv_edit.text().strip()
        flash_id_b64 = self.pc_fi_flash_id_edit.text().strip()
        legacy_app_key_text = self.pc_fi_legacy_app_key_edit.text().strip()
        mfg_ts_text = self.pc_fi_mfg_ts_edit.text().strip()
        if not sn:
            raise ValueError("Set Factory Identity 需要填写 SN")
        if len(sn.encode()) > 20:
            raise ValueError("SN 不能超过20字节")
        if len(dev_eui_hex) != 16:
            raise ValueError("DevEUI 必须是16位十六进制数，例如 A84041CC1F606353")
        if not flash_priv_b64:
            raise ValueError("Set Factory Identity 需要 device_private_key")
        flash_pub = _b64.b64decode(flash_pub_b64) if flash_pub_b64 else b""
        flash_id = _b64.b64decode(flash_id_b64) if flash_id_b64 else b""
        flash_priv = _b64.b64decode(flash_priv_b64) if flash_priv_b64 else b""
        legacy_app_key = _decode_required_key_bytes(legacy_app_key_text, 16, "legacy_app_key")
        if flash_pub and len(flash_pub) != 32:
            raise ValueError(f"legacy device_public_key 解码后必须为32字节，当前 {len(flash_pub)} 字节")
        if flash_id and len(flash_id) != 16:
            raise ValueError(f"legacy flash_public_id 解码后必须为16字节，当前 {len(flash_id)} 字节")
        if len(flash_priv) != 32:
            raise ValueError(f"device_private_key 解码后必须为32字节，当前 {len(flash_priv)} 字节")

        from meshdebug.pki_crypto import public_key_from_private

        device_public_key_b64 = _b64.b64encode(public_key_from_private(flash_priv)).decode()

        profile = {
            "node_id": node_id,
            "factory_version": self.pc_fi_version_spin.value(),
            "sn": sn,
            "dev_eui": dev_eui_hex.upper(),
            "flash_public_key": device_public_key_b64,
            "flash_public_id": flash_id_b64,
            "device_private_key": flash_priv_b64,
            "device_public_key": device_public_key_b64,
            "legacy_app_key": _b64.b64encode(legacy_app_key).decode(),
            "legacy_app_key_hex": legacy_app_key.hex().upper(),
            "manufacturing_timestamp": int(mfg_ts_text) if mfg_ts_text else int(_time.time()),
            "status": self.pc_fi_status_combo.currentData(),
        }
        if hasattr(self, "pc_jv2_seed_edit"):
            seed_b64 = self.pc_jv2_seed_edit.text().strip()
            if seed_b64:
                seed = _b64.b64decode(seed_b64)
                if not 16 <= len(seed) <= 32:
                    raise ValueError(f"Join V2 network_seed 解码后必须为16-32字节，当前 {len(seed)} 字节")
                profile["join_v2_network_seed"] = seed_b64
        return profile

    def _apply_factory_identity_profile(self, prof: dict) -> None:
        self.pc_fi_node_id_edit.setText(prof.get("node_id", ""))
        if hasattr(self, "pc_ch12_node_id_edit"):
            self.pc_ch12_node_id_edit.setText(prof.get("node_id", ""))
        self.pc_fi_version_spin.setValue(int(prof.get("factory_version", 1)))
        self.pc_fi_sn_edit.setText(prof.get("sn", ""))
        self.pc_fi_deveui_edit.setText(prof.get("dev_eui", ""))
        display_public_key = prof.get("device_public_key", "") or prof.get("flash_public_key", "")
        try:
            import base64 as _b64
            from meshdebug.pki_crypto import public_key_from_private

            device_private_key = _b64.b64decode(prof.get("device_private_key", "") or prof.get("flash_private_key", ""))
            if len(device_private_key) == 32:
                display_public_key = _b64.b64encode(public_key_from_private(device_private_key)).decode()
        except Exception:
            pass
        self.pc_fi_flash_pub_edit.setText(display_public_key)
        self.pc_fi_flash_id_edit.setText(prof.get("flash_public_id", ""))
        self.pc_fi_flash_priv_edit.setText(prof.get("device_private_key", "") or prof.get("flash_private_key", ""))
        self.pc_fi_legacy_app_key_edit.setText(prof.get("legacy_app_key", "") or prof.get("legacy_app_key_hex", ""))
        ts = prof.get("manufacturing_timestamp", "")
        self.pc_fi_mfg_ts_edit.setText(str(ts) if ts else "")
        status = int(prof.get("status", 1))
        for i in range(self.pc_fi_status_combo.count()):
            if self.pc_fi_status_combo.itemData(i) == status:
                self.pc_fi_status_combo.setCurrentIndex(i)
                break
        self._apply_channel12_profile(prof, overwrite=True)

    def _on_factory_profile_changed(self, _idx: int) -> None:
        pass

    def _on_factory_profile_load_clicked(self) -> None:
        node_id = self.pc_fi_profile_combo.currentData()
        if not node_id:
            return
        prof = self._factory_identity_profiles.get(node_id)
        if not prof:
            return
        self._apply_factory_identity_profile(prof)
        self._cache_join_lock_from_profile(node_id, prof, select=True)
        self.to_edit.setText(node_id)
        self._fill_join_v2_seed_from_profile(node_id)
        self.factory_profiles_changed.emit()

    def _on_factory_profile_save_clicked(self) -> None:
        try:
            prof = self._collect_factory_identity_profile()
            node_id = prof["node_id"]
            merged = dict(self._factory_identity_profiles.get(node_id, {}))
            merged.update(prof)
            self._factory_identity_profiles[node_id] = merged
            self._save_factory_identity_profiles()
            self._refresh_factory_identity_profile_combo(select_node_id=node_id)
            self._cache_join_lock_from_profile(node_id, merged, select=True)
            self._fill_join_v2_seed_from_profile(node_id)
            self.to_edit.setText(node_id)
            self.factory_profiles_changed.emit()
            self.log_result(True, f"已保存 FactoryIdentity 档案: {node_id}")
        except Exception as exc:
            self.log_result(False, f"保存 FactoryIdentity 档案失败: {exc}")

    def fill_change_admin_from_vi(
        self,
        new_gw_pub_b64: str,
        new_gw_node_hex: str,
    ):
        """将虚拟身份信息填充到 Private Config 页的 Change Admin 表单。"""
        self.pc_newgwpub_edit.setText(new_gw_pub_b64)
        self.pc_newgwid_edit.setText(new_gw_node_hex)
        self._sync_private_config_target_node_fields()
        # 切换到 change_admin 操作
        for i in range(self.pc_op_combo.count()):
            if self.pc_op_combo.itemData(i) == "change_admin":
                self.pc_op_combo.setCurrentIndex(i)
                break

    # ── Set Config 配置缓存填充 ───────────────────────────────────────────────

    def update_config_cache(self, cfg_type: int, from_id: str, cfg_dict: dict) -> None:
        """由 app.py 在收到 get_config_response 时调用，缓存并刷新填充按钮状态。"""
        import time as _t
        self._config_cache[cfg_type] = (from_id, _t.time(), cfg_dict)
        self._refresh_fill_btn_state()

    def _refresh_fill_btn_state(self) -> None:
        """根据当前选中的 ConfigType 更新填充按钮的启用状态和提示文字。"""
        if not hasattr(self, "scfg_fill_btn"):
            return
        import time as _t
        cfg_type = self.adm_scfg_type_combo.currentData()
        if cfg_type in self._config_cache:
            from_id, ts, _ = self._config_cache[cfg_type]
            age = int(_t.time() - ts)
            self.scfg_fill_btn.setEnabled(True)
            self.scfg_fill_btn.setToolTip(f"填充来自 {from_id} 的配置，{age} 秒前获取")
        else:
            self.scfg_fill_btn.setEnabled(False)
            self.scfg_fill_btn.setToolTip("请先发送 Get Config 获取该节点配置")

    def _on_scfg_fill_clicked(self) -> None:
        """用户点击"填充上次获取"按钮。"""
        cfg_type = self.adm_scfg_type_combo.currentData()
        self.fill_set_config_from_cache(cfg_type)

    def fill_set_config_from_cache(self, cfg_type: int) -> None:
        """从缓存填充 Set Config 表单（JSON 页直接写入，结构化页填充各 widget）。"""
        if cfg_type not in self._config_cache:
            return
        _, _, cfg_dict = self._config_cache[cfg_type]

        # JSON 类型（0,1,2,3,4,9）：直接填充 QTextEdit
        _json_widgets: dict = {}
        if hasattr(self, "scfg_dev_json"): _json_widgets[0] = self.scfg_dev_json
        if hasattr(self, "scfg_pos_json"): _json_widgets[1] = self.scfg_pos_json
        if hasattr(self, "scfg_pwr_json"): _json_widgets[2] = self.scfg_pwr_json
        if hasattr(self, "scfg_net_json"): _json_widgets[3] = self.scfg_net_json
        if hasattr(self, "scfg_dsp_json"): _json_widgets[4] = self.scfg_dsp_json
        if hasattr(self, "scfg_dui_json"): _json_widgets[9] = self.scfg_dui_json

        if cfg_type in _json_widgets:
            import json as _json
            _json_widgets[cfg_type].setPlainText(
                _json.dumps(cfg_dict, indent=2, ensure_ascii=False)
            )
            return

        # 结构化类型：填充各 widget
        def _set_combo(combo, val):
            for _i in range(combo.count()):
                if combo.itemData(_i) == val:
                    combo.setCurrentIndex(_i)
                    return

        if cfg_type == 5:  # LORA
            lora = cfg_dict.get("lora", {})
            self.scfg_lora_use_preset_chk.setChecked(bool(lora.get("use_preset", False)))
            _set_combo(self.scfg_lora_preset_combo, lora.get("modem_preset", 0))
            _set_combo(self.scfg_lora_region_combo, lora.get("region", 0))
            self.scfg_lora_hop_spin.setValue(lora.get("hop_limit", 3))
            self.scfg_lora_tx_enabled_chk.setChecked(bool(lora.get("tx_enabled", False)))
            self.scfg_lora_tx_power_spin.setValue(lora.get("tx_power", 0))
            self.scfg_lora_ch_num_spin.setValue(lora.get("channel_num", 0))
            self.scfg_lora_bw_spin.setValue(lora.get("bandwidth", 0))
            self.scfg_lora_sf_spin.setValue(lora.get("spread_factor", 0))
            self.scfg_lora_duty_chk.setChecked(bool(lora.get("override_duty_cycle", False)))
            self.scfg_lora_ok_mqtt_chk.setChecked(bool(lora.get("config_ok_to_mqtt", False)))

        elif cfg_type == 6:  # BLUETOOTH
            bt = cfg_dict.get("bluetooth", {})
            self.scfg_bt_enabled_chk.setChecked(bool(bt.get("enabled", False)))
            _set_combo(self.scfg_bt_mode_combo, bt.get("mode", 0))
            self.scfg_bt_pin_spin.setValue(bt.get("fixed_pin", 0))

        elif cfg_type == 7:  # SECURITY
            sec = cfg_dict.get("security", {})
            self.scfg_sec_pubkey_edit.setText(sec.get("public_key", ""))
            self.scfg_sec_privkey_edit.setText(sec.get("private_key", ""))
            ak_list = sec.get("admin_key", [])
            for _i, edit in enumerate([self.scfg_sec_ak0_edit,
                                       self.scfg_sec_ak1_edit,
                                       self.scfg_sec_ak2_edit]):
                edit.setText(ak_list[_i] if _i < len(ak_list) else "")
            self.scfg_sec_managed_chk.setChecked(bool(sec.get("is_managed", False)))
            self.scfg_sec_serial_chk.setChecked(bool(sec.get("serial_enabled", False)))
            self.scfg_sec_admin_ch_chk.setChecked(bool(sec.get("admin_channel_enabled", False)))

    # ── 构建 UI ───────────────────────────────────────────────────────────────

    def _build_routing_row(self) -> QWidget:
        """路由参数行：To / Channel / PortNum。"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        def _lbl(t):
            l = QLabel(t)
            l.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            return l

        h.addWidget(_lbl("To:"))
        self.to_edit = QLineEdit("!ffffffff")
        self.to_edit.setPlaceholderText("!xxxxxxxx")
        self.to_edit.setMinimumWidth(110)
        self.to_edit.textChanged.connect(self._on_to_text_changed)
        h.addWidget(self.to_edit)

        btn_bc = QPushButton("广播")
        btn_bc.setStyleSheet(_S_SMALL)
        btn_bc.setToolTip("填入 broadcast (!ffffffff)")
        btn_bc.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_bc.clicked.connect(lambda: self.to_edit.setText("!ffffffff"))
        h.addWidget(btn_bc)

        self.node_combo = QComboBox()
        self.node_combo.setEditable(False)
        self.node_combo.setMinimumWidth(150)
        self.node_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        add_combo_item(self.node_combo, "— 已知节点 —", None)
        self.node_combo.currentIndexChanged.connect(self._on_node_selected)
        h.addWidget(self.node_combo)

        h.addWidget(_lbl("  信道:"))
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(0, 7)
        self.channel_spin.setValue(0)
        self.channel_spin.setMinimumWidth(50)
        h.addWidget(self.channel_spin)

        h.addWidget(_lbl("  PortNum:"))
        self.portnum_combo = QComboBox()
        self.portnum_combo.setMinimumWidth(200)
        self.portnum_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        for label, val, _ in _PORTNUM_OPTIONS:
            add_combo_item(self.portnum_combo, label, val)
        self.portnum_combo.currentIndexChanged.connect(self._on_portnum_changed)
        h.addWidget(self.portnum_combo)

        return w

    def _build_payload_group(self) -> QGroupBox:
        """消息内容区（QStackedWidget，按 PortNum 切换页面）。"""
        group = QGroupBox("消息内容")
        group.setStyleSheet(_S_GROUP)
        v = QVBoxLayout(group)
        v.setContentsMargins(6, 4, 6, 4)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # ── 页 0：文本 ────────────────────────────────────────────────────────
        text_w = QWidget()
        tv = QVBoxLayout(text_w)
        tv.setContentsMargins(0, 0, 0, 0)
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("输入要发送的文本内容…")
        self.text_edit.setMinimumHeight(60)
        self.text_edit.setFont(QFont("Segoe UI", 10))
        tv.addWidget(self.text_edit)
        self.stack.addWidget(text_w)   # index 0

        # ── 页 1：Position（滚动区域，5 个分组）────────────────────────────
        self.stack.addWidget(self._build_pos_page())   # index 1

        # ── 页 2：Raw Hex ─────────────────────────────────────────────────────
        raw_w = QWidget()
        rv = QVBoxLayout(raw_w)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Payload Hex（空格分隔，如 0a 1b 2c…）:"))
        self.raw_edit = QLineEdit()
        self.raw_edit.setPlaceholderText("例: 0a 04 48 65 6c 6c 6f")
        self.raw_edit.setFont(QFont("Consolas", 10))
        self.raw_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        rv.addWidget(self.raw_edit)
        rv.addStretch()
        self.stack.addWidget(raw_w)    # index 2

        # ── 页 3：Telemetry / DeviceMetrics ──────────────────────────────────
        self.stack.addWidget(self._build_telemetry_page())   # index 3

        # ── 页 4：NodeInfo / User ─────────────────────────────────────────────
        self.stack.addWidget(self._build_nodeinfo_page())    # index 4

        # ── 页 5：Admin / AdminMessage ────────────────────────────────────────
        self.stack.addWidget(self._build_admin_page())       # index 5

        # ── 页 6：PRIVATE_CONFIG_APP (287) ───────────────────────────────────
        self.stack.addWidget(self._build_private_config_page())  # index 6

        # ── 页 7：WAKEUP_COMM_APP (288) ──────────────────────────────────────
        self.stack.addWidget(self._build_wakeup_comm_page())     # index 7

        v.addWidget(self.stack)
        return group

    def _build_pos_page(self) -> QScrollArea:
        """Position 完整字段页（QScrollArea 包裹，5 个分组 GroupBox）。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(4, 4, 4, 4)
        cv.setSpacing(6)

        # ── 分组 1：基本坐标 ──────────────────────────────────────────────────
        g1, f1 = _make_form_group("📍  基本坐标")

        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(7)
        self.lat_spin.setToolTip("度（×1e7 后存为 sfixed32）")
        f1.addRow("纬度 latitude_i:", _row(self.lat_spin, "°N"))

        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(7)
        f1.addRow("经度 longitude_i:", _row(self.lon_spin, "°E"))

        self.alt_spin = QSpinBox()
        self.alt_spin.setRange(-9999, 99999)
        self.alt_spin.setToolTip("海拔高度（MSL），单位 m")
        f1.addRow("海拔 altitude (MSL):", _row(self.alt_spin, "m"))

        self.alt_hae_spin = QSpinBox()
        self.alt_hae_spin.setRange(-9999, 99999)
        self.alt_hae_spin.setToolTip("HAE 椭球面高度，单位 m")
        f1.addRow("椭球高 altitude_hae:", _row(self.alt_hae_spin, "m"))

        self.ageo_spin = QSpinBox()
        self.ageo_spin.setRange(-9999, 9999)
        self.ageo_spin.setToolTip("大地水准面分离，单位 m")
        f1.addRow("大地分离 geoidal_sep:", _row(self.ageo_spin, "m"))

        cv.addWidget(g1)

        # ── 分组 2：时间 ──────────────────────────────────────────────────────
        g2, f2 = _make_form_group("🕐  时间")

        self.time_spin = QSpinBox()
        self.time_spin.setRange(0, 2_147_483_647)
        self.time_spin.setToolTip("Unix 时间戳（秒），通常来自手机同步")
        btn_now = QPushButton("填入当前时间")
        btn_now.setStyleSheet(_S_NOW)
        btn_now.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_now.clicked.connect(
            lambda: self.time_spin.setValue(int(_time.time()))
        )
        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.addWidget(self.time_spin)
        time_row.addWidget(btn_now)
        time_row.addStretch()
        f2.addRow("time (Unix s):", time_row)

        self.ts_spin = QSpinBox()
        self.ts_spin.setRange(0, 2_147_483_647)
        self.ts_spin.setToolTip("GPS 定位时刻的 Unix 时间戳（秒）")
        f2.addRow("timestamp (GPS fix s):", _row(self.ts_spin))

        self.ts_ms_spin = QSpinBox()
        self.ts_ms_spin.setRange(-999, 999)
        self.ts_ms_spin.setToolTip("时间戳毫秒修正量")
        f2.addRow("timestamp_millis_adjust:", _row(self.ts_ms_spin, "ms"))

        cv.addWidget(g2)

        # ── 分组 3：精度与卫星 ────────────────────────────────────────────────
        g3, f3 = _make_form_group("📡  精度与卫星")

        self.pdop_spin = QSpinBox()
        self.pdop_spin.setRange(0, 9999)
        self.pdop_spin.setToolTip("位置稀释度 PDOP，实际值 = 此值 × 0.01")
        f3.addRow("PDOP (×0.01):", _row(self.pdop_spin))

        self.hdop_spin = QSpinBox()
        self.hdop_spin.setRange(0, 9999)
        self.hdop_spin.setToolTip("水平稀释度 HDOP，实际值 = 此值 × 0.01")
        f3.addRow("HDOP (×0.01):", _row(self.hdop_spin))

        self.vdop_spin = QSpinBox()
        self.vdop_spin.setRange(0, 9999)
        self.vdop_spin.setToolTip("垂直稀释度 VDOP，实际值 = 此值 × 0.01")
        f3.addRow("VDOP (×0.01):", _row(self.vdop_spin))

        self.gps_acc_spin = QSpinBox()
        self.gps_acc_spin.setRange(0, 99999)
        self.gps_acc_spin.setToolTip("GPS 硬件精度常数，单位 mm")
        f3.addRow("gps_accuracy:", _row(self.gps_acc_spin, "mm"))

        self.fq_spin = QSpinBox()
        self.fq_spin.setRange(0, 9)
        self.fq_spin.setToolTip("GPS 定位质量（来自 GGA）")
        f3.addRow("fix_quality:", _row(self.fq_spin))

        self.ft_spin = QSpinBox()
        self.ft_spin.setRange(0, 9)
        self.ft_spin.setToolTip("定位维数：2=2D  3=3D（来自 GSA）")
        f3.addRow("fix_type (2=2D,3=3D):", _row(self.ft_spin))

        self.sats_spin = QSpinBox()
        self.sats_spin.setRange(0, 99)
        self.sats_spin.setToolTip("可见卫星数")
        f3.addRow("sats_in_view:", _row(self.sats_spin))

        cv.addWidget(g3)

        # ── 分组 4：运动数据 ──────────────────────────────────────────────────
        g4, f4 = _make_form_group("🚀  运动数据")

        self.gs_spin = QSpinBox()
        self.gs_spin.setRange(0, 999999)
        self.gs_spin.setToolTip("地速，单位 cm/s（即 m/s × 100）")
        f4.addRow("ground_speed:", _row(self.gs_spin, "cm/s"))

        self.gt_spin = QSpinBox()
        self.gt_spin.setRange(0, 35_999_999)
        self.gt_spin.setToolTip("真北航迹角，单位 1/100000°（即 度 × 100000）")
        f4.addRow("ground_track (×0.00001°):", _row(self.gt_spin))

        cv.addWidget(g4)

        # ── 分组 5：来源与其他 ────────────────────────────────────────────────
        g5, f5 = _make_form_group("⚙  来源与其他")

        self.loc_src_combo = QComboBox()
        self.loc_src_combo.addItems(
            ["LOC_UNSET (0)", "LOC_MANUAL (1)", "LOC_INTERNAL (2)", "LOC_EXTERNAL (3)"]
        )
        f5.addRow("location_source:", self.loc_src_combo)

        self.alt_src_combo = QComboBox()
        self.alt_src_combo.addItems([
            "ALT_UNSET (0)", "ALT_MANUAL (1)", "ALT_INTERNAL (2)",
            "ALT_EXTERNAL (3)", "ALT_BAROMETRIC (4)",
        ])
        f5.addRow("altitude_source:", self.alt_src_combo)

        self.sensor_spin = QSpinBox()
        self.sensor_spin.setRange(0, 255)
        self.sensor_spin.setToolTip("多定位传感器时用于区分来源")
        f5.addRow("sensor_id:", _row(self.sensor_spin))

        self.next_upd_spin = QSpinBox()
        self.next_upd_spin.setRange(0, 65535)
        self.next_upd_spin.setToolTip("预期的下次更新间隔（秒）")
        f5.addRow("next_update:", _row(self.next_upd_spin, "秒"))

        self.prec_spin = QSpinBox()
        self.prec_spin.setRange(0, 32)
        self.prec_spin.setValue(32)
        self.prec_spin.setToolTip("坐标精度位数，32 = 完整精度")
        f5.addRow("precision_bits:", _row(self.prec_spin))

        cv.addWidget(g5)
        cv.addStretch()

        scroll.setWidget(content)
        return scroll

    def _build_telemetry_page(self) -> QScrollArea:
        """Telemetry / DeviceMetrics 完整字段页。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(4, 4, 4, 4)
        cv.setSpacing(6)

        g1, f1 = _make_form_group("📊  Telemetry — DeviceMetrics")

        self.tel_time_spin = QSpinBox()
        self.tel_time_spin.setRange(0, 2_147_483_647)
        self.tel_time_spin.setToolTip("Unix 时间戳（秒）")
        btn_now = QPushButton("当前时间")
        btn_now.setStyleSheet(_S_NOW)
        btn_now.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_now.clicked.connect(lambda: self.tel_time_spin.setValue(int(_time.time())))
        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.addWidget(self.tel_time_spin)
        time_row.addWidget(btn_now)
        time_row.addStretch()
        f1.addRow("time (Unix s):", time_row)

        self.tel_batt_spin = QSpinBox()
        self.tel_batt_spin.setRange(0, 101)
        self.tel_batt_spin.setToolTip("0–100 = 电量百分比；101 = 已接外部供电")
        f1.addRow("battery_level (%):", _row(self.tel_batt_spin))

        self.tel_volt_spin = QDoubleSpinBox()
        self.tel_volt_spin.setRange(0.0, 30.0)
        self.tel_volt_spin.setDecimals(3)
        self.tel_volt_spin.setSingleStep(0.001)
        self.tel_volt_spin.setToolTip("实测电压（V）")
        f1.addRow("voltage (V):", _row(self.tel_volt_spin, "V"))

        self.tel_chutil_spin = QDoubleSpinBox()
        self.tel_chutil_spin.setRange(0.0, 100.0)
        self.tel_chutil_spin.setDecimals(2)
        self.tel_chutil_spin.setToolTip("当前信道占用率（%）")
        f1.addRow("channel_utilization (%):", _row(self.tel_chutil_spin, "%"))

        self.tel_airutil_spin = QDoubleSpinBox()
        self.tel_airutil_spin.setRange(0.0, 100.0)
        self.tel_airutil_spin.setDecimals(2)
        self.tel_airutil_spin.setToolTip("过去一小时 TX 空口占用率（%）")
        f1.addRow("air_util_tx (%):", _row(self.tel_airutil_spin, "%"))

        self.tel_uptime_spin = QSpinBox()
        self.tel_uptime_spin.setRange(0, 2_147_483_647)
        self.tel_uptime_spin.setToolTip("设备开机时长（秒）")
        f1.addRow("uptime_seconds (s):", _row(self.tel_uptime_spin, "s"))

        cv.addWidget(g1)
        cv.addStretch()
        scroll.setWidget(content)
        return scroll

    def _build_nodeinfo_page(self) -> QScrollArea:
        """NodeInfo / User 完整字段页。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(4, 4, 4, 4)
        cv.setSpacing(6)

        g1, f1 = _make_form_group("👤  NodeInfo — User")

        self.ni_id_edit = QLineEdit()
        self.ni_id_edit.setPlaceholderText("!aabbccdd")
        self.ni_id_edit.setToolTip("节点唯一 ID 字符串（格式 !xxxxxxxx）")
        f1.addRow("id:", self.ni_id_edit)

        self.ni_long_edit = QLineEdit()
        self.ni_long_edit.setMaxLength(40)
        self.ni_long_edit.setToolTip("长名（最多 40 字符）")
        f1.addRow("long_name:", self.ni_long_edit)

        self.ni_short_edit = QLineEdit()
        self.ni_short_edit.setMaxLength(4)
        self.ni_short_edit.setToolTip("短名（最多 4 字符）")
        f1.addRow("short_name:", self.ni_short_edit)

        self.ni_hw_combo = QComboBox()
        # 常用硬件型号（value → 名称，来自 mesh.pb.h HardwareModel enum）
        _HW_MODELS = [
            (0,   "UNSET (0)"),
            (1,   "TLORA_V2 (1)"),
            (4,   "TBEAM (4)"),
            (9,   "HELTEC_V2_0 (9)"),
            (10,  "TBEAM_V0P7 (10)"),
            (11,  "T_ECHO (11)"),
            (12,  "TLORA_V1_1P3 (12)"),
            (13,  "RAK4631 (13)"),
            (16,  "HELTEC_V2_1 (16)"),
            (17,  "HELTEC_V1 (17)"),
            (19,  "TBEAM_S3_CORE (19)"),
            (20,  "RAK11200 (20)"),
            (22,  "NANO_G1 (22)"),
            (24,  "TLORA_T3_S3 (24)"),
            (32,  "HELTEC_WIRELESS_TRACKER (32)"),
            (37,  "RAK11310 (37)"),
            (255, "PRIVATE_HW (255)"),
        ]
        for val, name in _HW_MODELS:
            self.ni_hw_combo.addItem(name, userData=val)
        self.ni_hw_combo.setToolTip("硬件型号")
        f1.addRow("hw_model:", self.ni_hw_combo)

        self.ni_lic_chk = QCheckBox("is_licensed（持证业余无线电运营）")
        f1.addRow("", self.ni_lic_chk)

        self.ni_role_combo = QComboBox()
        _ROLES = [
            (0, "CLIENT (0)"),
            (1, "CLIENT_MUTE (1)"),
            (2, "ROUTER (2)"),
            (3, "ROUTER_CLIENT (3)"),
            (4, "REPEATER (4)"),
            (5, "TRACKER (5)"),
            (6, "SENSOR (6)"),
            (7, "TAK (7)"),
            (8, "CLIENT_HIDDEN (8)"),
            (9, "LOST_AND_FOUND (9)"),
            (10, "TAK_TRACKER (10)"),
        ]
        for val, name in _ROLES:
            self.ni_role_combo.addItem(name, userData=val)
        self.ni_role_combo.setToolTip("节点角色")
        f1.addRow("role:", self.ni_role_combo)

        self.ni_pubkey_edit = QLineEdit()
        self.ni_pubkey_edit.setPlaceholderText("Base64 公钥（32字节），留空=不设置")
        self.ni_pubkey_edit.setFont(QFont("Consolas", 10))
        self.ni_pubkey_edit.setToolTip("Curve25519 公钥 Base64 编码（32字节），目标节点存入 NodeDB 后才能 PKI 加密通信")
        f1.addRow("public_key (Base64):", self.ni_pubkey_edit)

        cv.addWidget(g1)
        cv.addStretch()
        scroll.setWidget(content)
        return scroll

    def _build_admin_page(self) -> QScrollArea:
        """Admin / AdminMessage 全字段页（QScrollArea 包裹）。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(4, 4, 4, 4)
        cv.setSpacing(6)

        # ── 操作选择组 ────────────────────────────────────────────────────────
        op_group = QGroupBox("AdminMessage 操作")
        op_group.setStyleSheet(_S_GROUP)
        og_v = QVBoxLayout(op_group)
        og_v.setContentsMargins(6, 4, 6, 6)
        og_v.setSpacing(6)

        # 操作类型下拉
        op_row = QHBoxLayout()
        op_row.setContentsMargins(0, 0, 0, 0)
        op_row.addWidget(QLabel("操作类型:"))
        self.adm_op_combo = QComboBox()
        self.adm_op_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        for entry in _ADMIN_OPS:
            label, field_name, input_type, _, _ = entry
            self.adm_op_combo.addItem(label, userData=entry if field_name is not None else None)
            if field_name is None:
                # 分隔符行：禁用
                idx = self.adm_op_combo.count() - 1
                item = self.adm_op_combo.model().item(idx)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled
                              & ~Qt.ItemFlag.ItemIsSelectable)
        self.adm_op_combo.currentIndexChanged.connect(self._on_adm_op_changed)
        op_row.addWidget(self.adm_op_combo)
        og_v.addLayout(op_row)

        # 内层参数 stacked widget（16 个 input 页）
        self.adm_inner_stack = QStackedWidget()

        # page 0: NONE
        p0 = QWidget()
        p0v = QVBoxLayout(p0)
        p0v.addWidget(QLabel("✔  此操作无需额外参数（bool = True）"))
        p0v.addStretch()
        self.adm_inner_stack.addWidget(p0)   # 0

        # page 1: UINT32
        p1 = QWidget()
        p1f = QFormLayout(p1)
        self.adm_lbl_uint32 = QLabel("值 (uint32):")
        self.adm_uint32_stack = QStackedWidget()
        self.adm_uint32_stack.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.adm_uint32_stack.setFixedWidth(120)
        self.adm_uint32_spin = QSpinBox()
        self.adm_uint32_spin.setRange(0, 2_147_483_647)
        self.adm_uint32_spin.setMinimumWidth(120)
        self.adm_uint32_spin.setFixedWidth(120)
        self.adm_uint32_stack.addWidget(self.adm_uint32_spin)
        self.adm_uint32_node_edit = QLineEdit()
        self.adm_uint32_node_edit.setPlaceholderText("!aabbccdd / 0xaabbccdd / 2864434397")
        self.adm_uint32_node_edit.setFixedWidth(240)
        self.adm_uint32_node_edit.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.adm_uint32_node_edit.setToolTip("鑺傜偣 ID 鏀寔 !aabbccdd銆乤abbccdd銆?0xaabbccdd 鎴栧崄杩涘埗")
        self.adm_uint32_stack.addWidget(self.adm_uint32_node_edit)
        p1f.addRow(self.adm_lbl_uint32, self.adm_uint32_stack)
        self.adm_uint32_hint_lbl = QLabel("")
        self.adm_uint32_hint_lbl.setStyleSheet("color:#888; font-size:10px;")
        self.adm_uint32_hint_lbl.hide()
        p1f.addRow("", self.adm_uint32_hint_lbl)
        self.adm_inner_stack.addWidget(p1)   # 1

        # page 2: INT32
        p2 = QWidget()
        p2f = QFormLayout(p2)
        self.adm_lbl_int32 = QLabel("值 (int32):")
        self.adm_int32_spin = QSpinBox()
        self.adm_int32_spin.setRange(-2_147_483_648, 2_147_483_647)
        self.adm_int32_spin.setValue(0)
        self.adm_int32_spin.setMinimumWidth(120)
        p2f.addRow(self.adm_lbl_int32, self.adm_int32_spin)
        hint2 = QLabel("提示：reboot/shutdown 中 -1 表示取消")
        hint2.setStyleSheet("color:#888; font-size:10px;")
        p2f.addRow("", hint2)
        self.adm_inner_stack.addWidget(p2)   # 2

        # page 3: STRING
        p3 = QWidget()
        p3f = QFormLayout(p3)
        self.adm_lbl_str = QLabel("内容:")
        self.adm_str_edit = QLineEdit()
        self.adm_str_edit.setMaxLength(230)
        p3f.addRow(self.adm_lbl_str, self.adm_str_edit)
        self.adm_inner_stack.addWidget(p3)   # 3

        # page 4: CONFIG_TYPE
        p4 = QWidget()
        p4f = QFormLayout(p4)
        self.adm_cfg_type_combo = QComboBox()
        for val, name in _CONFIG_TYPES:
            self.adm_cfg_type_combo.addItem(name, userData=val)
        p4f.addRow("ConfigType:", self.adm_cfg_type_combo)
        self.adm_inner_stack.addWidget(p4)   # 4

        # page 5: MODULE_CONFIG_TYPE
        p5 = QWidget()
        p5f = QFormLayout(p5)
        self.adm_mod_type_combo = QComboBox()
        for val, name in _MODULE_CONFIG_TYPES:
            self.adm_mod_type_combo.addItem(name, userData=val)
        p5f.addRow("ModuleConfigType:", self.adm_mod_type_combo)
        self.adm_inner_stack.addWidget(p5)   # 5

        # page 6: SET_OWNER (User 表单)
        p6, f6 = _make_form_group("Set Owner — User 字段")
        self.adm_own_id_edit = QLineEdit()
        self.adm_own_id_edit.setPlaceholderText("!aabbccdd")
        self.adm_own_id_edit.setToolTip("节点唯一 ID 字符串（格式 !xxxxxxxx）")
        f6.addRow("id:", self.adm_own_id_edit)
        self.adm_own_long_edit = QLineEdit()
        self.adm_own_long_edit.setMaxLength(40)
        f6.addRow("long_name:", self.adm_own_long_edit)
        self.adm_own_short_edit = QLineEdit()
        self.adm_own_short_edit.setMaxLength(4)
        f6.addRow("short_name:", self.adm_own_short_edit)
        self.adm_own_hw_combo = QComboBox()
        for val, name in [
            (0,"UNSET(0)"),(4,"TBEAM(4)"),(9,"HELTEC_V2_0(9)"),(11,"T_ECHO(11)"),
            (13,"RAK4631(13)"),(16,"HELTEC_V2_1(16)"),(19,"TBEAM_S3_CORE(19)"),
            (24,"TLORA_T3_S3(24)"),(37,"RAK11310(37)"),(255,"PRIVATE(255)"),
        ]:
            self.adm_own_hw_combo.addItem(name, userData=val)
        f6.addRow("hw_model:", self.adm_own_hw_combo)
        self.adm_own_lic_chk = QCheckBox("is_licensed（持证业余无线电）")
        f6.addRow("", self.adm_own_lic_chk)
        self.adm_own_role_combo = QComboBox()
        for val, name in [
            (0,"CLIENT(0)"),(1,"CLIENT_MUTE(1)"),(2,"ROUTER(2)"),
            (3,"ROUTER_CLIENT(3)"),(4,"REPEATER(4)"),(5,"TRACKER(5)"),
            (6,"SENSOR(6)"),(7,"TAK(7)"),(8,"CLIENT_HIDDEN(8)"),
            (9,"LOST_AND_FOUND(9)"),(10,"TAK_TRACKER(10)"),
        ]:
            self.adm_own_role_combo.addItem(name, userData=val)
        f6.addRow("role:", self.adm_own_role_combo)
        self.adm_inner_stack.addWidget(p6)   # 6

        # page 7: SET_CHANNEL (Channel 表单)
        p7, f7 = _make_form_group("Set Channel — Channel 字段")
        self.adm_ch_idx_spin = QSpinBox()
        self.adm_ch_idx_spin.setRange(0, 7)
        self.adm_ch_idx_spin.setValue(1)
        self.adm_ch_idx_spin.setToolTip("信道索引 (0=主信道，不可修改；1-7=二级信道)")
        f7.addRow("index:", self.adm_ch_idx_spin)
        self.adm_ch_primary_warn = QLabel("⚠ 主信道(index=0)只读，请选择索引 1-7！")
        self.adm_ch_primary_warn.setStyleSheet("color:#e74c3c; font-size:11px;")
        self.adm_ch_primary_warn.hide()
        f7.addRow("", self.adm_ch_primary_warn)
        self.adm_ch_idx_spin.valueChanged.connect(
            lambda v: self.adm_ch_primary_warn.setVisible(v == 0)
        )
        self.adm_ch_role_combo = QComboBox()
        for val, name in _CHANNEL_ROLES:
            self.adm_ch_role_combo.addItem(name, userData=val)
        # 默认选中 SECONDARY (2)（适合新建次级信道）
        for _i in range(self.adm_ch_role_combo.count()):
            if self.adm_ch_role_combo.itemData(_i) == 2:
                self.adm_ch_role_combo.setCurrentIndex(_i)
                break
        f7.addRow("role:", self.adm_ch_role_combo)
        self.adm_ch_name_edit = QLineEdit()
        self.adm_ch_name_edit.setMaxLength(12)
        self.adm_ch_name_edit.setToolTip("信道名称（max 12 字符）")
        f7.addRow("settings.name:", self.adm_ch_name_edit)
        self.adm_ch_psk_edit = QLineEdit()
        self.adm_ch_psk_edit.setPlaceholderText("Base64 编码 PSK（16 or 32 字节），留空=使用默认 PSK")
        self.adm_ch_psk_edit.setFont(QFont("Consolas", 10))
        self.adm_ch_psk_edit.setToolTip("Base64 字符串，解码后须为 0/16/32 字节")
        f7.addRow("settings.psk (Base64):", self.adm_ch_psk_edit)
        self.adm_ch_uplink_chk = QCheckBox("uplink_enabled（上传 MQTT）")
        f7.addRow("", self.adm_ch_uplink_chk)
        self.adm_ch_downlink_chk = QCheckBox("downlink_enabled（下载 MQTT）")
        f7.addRow("", self.adm_ch_downlink_chk)
        self.adm_ch_pos_prec_spin = QSpinBox()
        self.adm_ch_pos_prec_spin.setRange(0, 32)
        self.adm_ch_pos_prec_spin.setToolTip("位置精度位数（0=不广播位置）")
        f7.addRow("module_settings.position_precision:", self.adm_ch_pos_prec_spin)
        self.adm_ch_is_muted_chk = QCheckBox("is_muted（静音该信道）")
        f7.addRow("", self.adm_ch_is_muted_chk)
        self.adm_inner_stack.addWidget(p7)   # 7

        # page 8: SET_CONFIG — 按 ConfigType 分页表单
        p8 = QScrollArea()
        p8.setWidgetResizable(True)
        p8.setStyleSheet("QScrollArea { border: none; }")
        p8_content = QWidget()
        p8_vbox = QVBoxLayout(p8_content)
        p8_vbox.setContentsMargins(4, 4, 4, 4)
        p8_vbox.setSpacing(6)

        scfg_top_grp = QGroupBox("Set Config — 选择配置类型")
        scfg_top_grp.setStyleSheet(_S_GROUP)
        scfg_top_f = QFormLayout(scfg_top_grp)
        scfg_top_f.setContentsMargins(8, 4, 8, 4)
        scfg_top_f.setSpacing(4)
        self.adm_scfg_type_combo = QComboBox()
        for val, name in _CONFIG_TYPES:
            self.adm_scfg_type_combo.addItem(name, userData=val)
        scfg_top_f.addRow("ConfigType:", self.adm_scfg_type_combo)
        self.scfg_fill_btn = QPushButton("📥 填充上次获取")
        self.scfg_fill_btn.setEnabled(False)
        self.scfg_fill_btn.setToolTip("请先发送 Get Config 获取该节点配置")
        self.scfg_fill_btn.setStyleSheet(_S_SMALL)
        self.scfg_fill_btn.clicked.connect(self._on_scfg_fill_clicked)
        scfg_top_f.addRow("", self.scfg_fill_btn)
        p8_vbox.addWidget(scfg_top_grp)

        # 各 ConfigType 的参数页
        self.adm_scfg_stack = QStackedWidget()

        # ── JSON TextEdit 通用页工厂 ──────────────────────────────────────────
        def _make_json_page(hint: str) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            lbl = QLabel(hint)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#888; font-size:10px;")
            v.addWidget(lbl)
            te = QTextEdit()
            te.setPlaceholderText('{"key": value, ...}  (protobuf JSON 格式)')
            te.setFont(QFont("Consolas", 10))
            te.setMinimumHeight(80)
            v.addWidget(te, stretch=1)
            return w, te

        # page 8-0: DEVICE_CONFIG (JSON)
        wp, self.scfg_dev_json = _make_json_page(
            "DEVICE_CONFIG — 先 Get Config(DEVICE) 读取当前值，修改后填入。"
        )
        self.adm_scfg_stack.addWidget(wp)   # idx 0

        # page 8-1: POSITION_CONFIG (JSON)
        wp, self.scfg_pos_json = _make_json_page(
            "POSITION_CONFIG — 先 Get Config(POSITION) 读取当前值，修改后填入。"
        )
        self.adm_scfg_stack.addWidget(wp)   # idx 1

        # page 8-2: POWER_CONFIG (JSON)
        wp, self.scfg_pwr_json = _make_json_page(
            "POWER_CONFIG — 先 Get Config(POWER) 读取当前值，修改后填入。"
        )
        self.adm_scfg_stack.addWidget(wp)   # idx 2

        # page 8-3: NETWORK_CONFIG (JSON)
        wp, self.scfg_net_json = _make_json_page(
            "NETWORK_CONFIG — 先 Get Config(NETWORK) 读取当前值，修改后填入。"
        )
        self.adm_scfg_stack.addWidget(wp)   # idx 3

        # page 8-4: DISPLAY_CONFIG (JSON)
        wp, self.scfg_dsp_json = _make_json_page(
            "DISPLAY_CONFIG — 先 Get Config(DISPLAY) 读取当前值，修改后填入。"
        )
        self.adm_scfg_stack.addWidget(wp)   # idx 4

        # page 8-5: LORA_CONFIG (完整表单)
        scfg_lora_grp = QGroupBox("LORA_CONFIG 字段")
        scfg_lora_grp.setStyleSheet(_S_GROUP)
        scfg_lora_f = QFormLayout(scfg_lora_grp)
        scfg_lora_f.setContentsMargins(8, 4, 8, 6)
        scfg_lora_f.setSpacing(5)
        self.scfg_lora_use_preset_chk = QCheckBox("use_preset（使用预设调制方案）")
        scfg_lora_f.addRow("", self.scfg_lora_use_preset_chk)
        self.scfg_lora_preset_combo = QComboBox()
        for val, name in [
            (0, "LONG_FAST (0)"), (1, "LONG_SLOW (1)"), (2, "VERY_LONG_SLOW (2)"),
            (3, "MEDIUM_SLOW (3)"), (4, "MEDIUM_FAST (4)"), (5, "SHORT_SLOW (5)"),
            (6, "SHORT_FAST (6)"), (7, "LONG_MODERATE (7)"), (8, "SHORT_TURBO (8)"),
        ]:
            self.scfg_lora_preset_combo.addItem(name, userData=val)
        scfg_lora_f.addRow("modem_preset:", self.scfg_lora_preset_combo)
        self.scfg_lora_region_combo = QComboBox()
        for val, name in [
            (0, "UNSET (0)"), (1, "US (1)"), (2, "EU_433 (2)"), (3, "EU_868 (3)"),
            (4, "CN (4)"), (5, "JP (5)"), (6, "ANZ (6)"), (7, "KR (7)"),
            (8, "TW (8)"), (9, "RU (9)"), (10, "IN (10)"), (11, "NZ_865 (11)"),
            (12, "TH (12)"), (13, "LORA_24 (13)"), (14, "UA_433 (14)"),
            (15, "UA_868 (15)"), (16, "MY_433 (16)"), (17, "MY_919 (17)"),
            (18, "SG_923 (18)"),
        ]:
            self.scfg_lora_region_combo.addItem(name, userData=val)
        scfg_lora_f.addRow("region:", self.scfg_lora_region_combo)
        self.scfg_lora_hop_spin = QSpinBox()
        self.scfg_lora_hop_spin.setRange(1, 7)
        self.scfg_lora_hop_spin.setValue(3)
        self.scfg_lora_hop_spin.setToolTip("最大跳数（1-7）")
        scfg_lora_f.addRow("hop_limit:", self.scfg_lora_hop_spin)
        self.scfg_lora_tx_enabled_chk = QCheckBox("tx_enabled（允许发射）")
        self.scfg_lora_tx_enabled_chk.setChecked(True)
        scfg_lora_f.addRow("", self.scfg_lora_tx_enabled_chk)
        self.scfg_lora_tx_power_spin = QSpinBox()
        self.scfg_lora_tx_power_spin.setRange(0, 30)
        self.scfg_lora_tx_power_spin.setToolTip("发射功率 dBm（0=最大值）")
        scfg_lora_f.addRow("tx_power (dBm):", self.scfg_lora_tx_power_spin)
        self.scfg_lora_ch_num_spin = QSpinBox()
        self.scfg_lora_ch_num_spin.setRange(0, 104)
        self.scfg_lora_ch_num_spin.setToolTip("LoRa 信道编号（0=根据地区自动计算）")
        scfg_lora_f.addRow("channel_num:", self.scfg_lora_ch_num_spin)
        self.scfg_lora_bw_spin = QSpinBox()
        self.scfg_lora_bw_spin.setRange(0, 812)
        self.scfg_lora_bw_spin.setToolTip("带宽 kHz（0=preset，常用：125/250/500）")
        scfg_lora_f.addRow("bandwidth (kHz):", self.scfg_lora_bw_spin)
        self.scfg_lora_sf_spin = QSpinBox()
        self.scfg_lora_sf_spin.setRange(0, 12)
        self.scfg_lora_sf_spin.setToolTip("扩频因子（0=preset，有效范围 7-12）")
        scfg_lora_f.addRow("spread_factor:", self.scfg_lora_sf_spin)
        self.scfg_lora_duty_chk = QCheckBox("override_duty_cycle（忽略占空比限制）")
        scfg_lora_f.addRow("", self.scfg_lora_duty_chk)
        self.scfg_lora_ok_mqtt_chk = QCheckBox("config_ok_to_mqtt（允许上传 MQTT）")
        scfg_lora_f.addRow("", self.scfg_lora_ok_mqtt_chk)
        self.adm_scfg_stack.addWidget(scfg_lora_grp)   # idx 5

        # page 8-6: BLUETOOTH_CONFIG (完整表单)
        scfg_bt_grp = QGroupBox("BLUETOOTH_CONFIG 字段")
        scfg_bt_grp.setStyleSheet(_S_GROUP)
        scfg_bt_f = QFormLayout(scfg_bt_grp)
        scfg_bt_f.setContentsMargins(8, 4, 8, 6)
        scfg_bt_f.setSpacing(5)
        self.scfg_bt_enabled_chk = QCheckBox("enabled（启用蓝牙）")
        scfg_bt_f.addRow("", self.scfg_bt_enabled_chk)
        self.scfg_bt_mode_combo = QComboBox()
        for val, name in [
            (0, "RANDOM_PIN (0)"), (1, "FIXED_PIN (1)"), (2, "NO_PIN (2)"),
        ]:
            self.scfg_bt_mode_combo.addItem(name, userData=val)
        scfg_bt_f.addRow("mode:", self.scfg_bt_mode_combo)
        self.scfg_bt_pin_spin = QSpinBox()
        self.scfg_bt_pin_spin.setRange(0, 999999)
        self.scfg_bt_pin_spin.setToolTip("固定 PIN（mode=FIXED_PIN 时使用，6位数）")
        scfg_bt_f.addRow("fixed_pin:", self.scfg_bt_pin_spin)
        self.adm_scfg_stack.addWidget(scfg_bt_grp)   # idx 6

        # page 8-7: SECURITY_CONFIG (完整表单)
        scfg_sec_grp = QGroupBox("SECURITY_CONFIG 字段")
        scfg_sec_grp.setStyleSheet(_S_GROUP)
        scfg_sec_f = QFormLayout(scfg_sec_grp)
        scfg_sec_f.setContentsMargins(8, 4, 8, 6)
        scfg_sec_f.setSpacing(5)
        self.scfg_sec_pubkey_edit = QLineEdit()
        self.scfg_sec_pubkey_edit.setPlaceholderText("Base64（32字节），留空=不修改")
        self.scfg_sec_pubkey_edit.setFont(QFont("Consolas", 10))
        scfg_sec_f.addRow("public_key (Base64):", self.scfg_sec_pubkey_edit)
        self.scfg_sec_privkey_edit = QLineEdit()
        self.scfg_sec_privkey_edit.setPlaceholderText("Base64（32字节），留空=不修改")
        self.scfg_sec_privkey_edit.setFont(QFont("Consolas", 10))
        self.scfg_sec_privkey_edit.setEchoMode(QLineEdit.EchoMode.Password)
        scfg_sec_f.addRow("private_key (Base64):", self.scfg_sec_privkey_edit)
        self.scfg_sec_ak0_edit = QLineEdit()
        self.scfg_sec_ak0_edit.setPlaceholderText("Base64（32字节），留空=不设置")
        self.scfg_sec_ak0_edit.setFont(QFont("Consolas", 10))
        scfg_sec_f.addRow("admin_key[0] (Base64):", self.scfg_sec_ak0_edit)
        self.scfg_sec_ak1_edit = QLineEdit()
        self.scfg_sec_ak1_edit.setPlaceholderText("Base64（32字节），留空=不设置")
        self.scfg_sec_ak1_edit.setFont(QFont("Consolas", 10))
        scfg_sec_f.addRow("admin_key[1] (Base64):", self.scfg_sec_ak1_edit)
        self.scfg_sec_ak2_edit = QLineEdit()
        self.scfg_sec_ak2_edit.setPlaceholderText("Base64（32字节），留空=不设置")
        self.scfg_sec_ak2_edit.setFont(QFont("Consolas", 10))
        scfg_sec_f.addRow("admin_key[2] (Base64):", self.scfg_sec_ak2_edit)
        self.scfg_sec_managed_chk = QCheckBox("is_managed（托管模式，远程管理员控制）")
        scfg_sec_f.addRow("", self.scfg_sec_managed_chk)
        self.scfg_sec_serial_chk = QCheckBox("serial_enabled（串口控制台）")
        self.scfg_sec_serial_chk.setChecked(True)
        scfg_sec_f.addRow("", self.scfg_sec_serial_chk)
        self.scfg_sec_admin_ch_chk = QCheckBox("admin_channel_enabled（允许通过信道管理）")
        scfg_sec_f.addRow("", self.scfg_sec_admin_ch_chk)
        self.adm_scfg_stack.addWidget(scfg_sec_grp)   # idx 7

        # page 8-8: SESSIONKEY_CONFIG (只读)
        p8_8 = QWidget()
        p8_8v = QVBoxLayout(p8_8)
        p8_8v.addWidget(QLabel("ℹ  SESSIONKEY_CONFIG 为只读，设备自动管理，无需手动设置。"))
        p8_8v.addStretch()
        self.adm_scfg_stack.addWidget(p8_8)   # idx 8

        # page 8-9: DEVICEUI_CONFIG (JSON)
        wp, self.scfg_dui_json = _make_json_page(
            "DEVICEUI_CONFIG — 先 Get Config(DEVICEUI) 读取当前值，修改后填入。"
        )
        self.adm_scfg_stack.addWidget(wp)   # idx 9

        # 绑定 ConfigType 下拉 → 切换参数页 + 更新填充按钮状态
        self.adm_scfg_type_combo.currentIndexChanged.connect(
            self.adm_scfg_stack.setCurrentIndex
        )
        self.adm_scfg_type_combo.currentIndexChanged.connect(
            lambda _: self._refresh_fill_btn_state()
        )
        self.adm_scfg_stack.setCurrentIndex(0)

        p8_vbox.addWidget(self.adm_scfg_stack, stretch=1)
        p8.setWidget(p8_content)
        self.adm_inner_stack.addWidget(p8)   # 8

        # page 9: SET_MODULE_CONFIG (ModuleConfigType + ModuleConfig bytes hex)
        p9, f9 = _make_form_group("Set Module Config — 模块配置类型 + proto bytes")
        self.adm_smcfg_type_combo = QComboBox()
        for val, name in _MODULE_CONFIG_TYPES:
            self.adm_smcfg_type_combo.addItem(name, userData=val)
        f9.addRow("ModuleConfigType (参考):", self.adm_smcfg_type_combo)
        self.adm_smcfg_raw_edit = QLineEdit()
        self.adm_smcfg_raw_edit.setPlaceholderText("完整 ModuleConfig protobuf bytes（hex，可为空）")
        self.adm_smcfg_raw_edit.setFont(QFont("Consolas", 10))
        f9.addRow("ModuleConfig bytes (hex):", self.adm_smcfg_raw_edit)
        self.adm_inner_stack.addWidget(p9)   # 9

        # page 10: HAM_MODE (HamParameters)
        p10, f10 = _make_form_group("Set Ham Mode — HamParameters")
        self.adm_ham_call_edit = QLineEdit()
        self.adm_ham_call_edit.setMaxLength(7)
        self.adm_ham_call_edit.setToolTip("业余无线电呼号（max 7 字符）")
        f10.addRow("call_sign:", self.adm_ham_call_edit)
        self.adm_ham_freq_spin = QDoubleSpinBox()
        self.adm_ham_freq_spin.setRange(0.0, 2_000_000_000.0)
        self.adm_ham_freq_spin.setDecimals(0)
        self.adm_ham_freq_spin.setSingleStep(1_000_000)
        self.adm_ham_freq_spin.setToolTip("LoRa 频率（Hz），如 915000000")
        f10.addRow("frequency (Hz):", _row(self.adm_ham_freq_spin, "Hz"))
        self.adm_ham_power_spin = QSpinBox()
        self.adm_ham_power_spin.setRange(-30, 30)
        self.adm_ham_power_spin.setToolTip("发射功率（dBm）")
        f10.addRow("tx_power (dBm):", _row(self.adm_ham_power_spin, "dBm"))
        self.adm_ham_short_edit = QLineEdit()
        self.adm_ham_short_edit.setMaxLength(4)
        self.adm_ham_short_edit.setToolTip("节点短名（max 4 字符，可留空）")
        f10.addRow("short_name:", self.adm_ham_short_edit)
        self.adm_inner_stack.addWidget(p10)  # 10

        # page 11: SET_FIXED_POSITION (简化 Position)
        p11, f11 = _make_form_group("Set Fixed Position — 简化坐标")
        self.adm_pos_lat_spin = QDoubleSpinBox()
        self.adm_pos_lat_spin.setRange(-90.0, 90.0)
        self.adm_pos_lat_spin.setDecimals(7)
        f11.addRow("latitude (°N):", _row(self.adm_pos_lat_spin, "°N"))
        self.adm_pos_lon_spin = QDoubleSpinBox()
        self.adm_pos_lon_spin.setRange(-180.0, 180.0)
        self.adm_pos_lon_spin.setDecimals(7)
        f11.addRow("longitude (°E):", _row(self.adm_pos_lon_spin, "°E"))
        self.adm_pos_alt_spin = QSpinBox()
        self.adm_pos_alt_spin.setRange(-9999, 99999)
        f11.addRow("altitude (m):", _row(self.adm_pos_alt_spin, "m"))
        self.adm_pos_time_spin = QSpinBox()
        self.adm_pos_time_spin.setRange(0, 2_147_483_647)
        btn_now11 = QPushButton("当前时间")
        btn_now11.setStyleSheet(_S_NOW)
        btn_now11.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_now11.clicked.connect(lambda: self.adm_pos_time_spin.setValue(int(_time.time())))
        time_row11 = QHBoxLayout()
        time_row11.setContentsMargins(0, 0, 0, 0)
        time_row11.addWidget(self.adm_pos_time_spin)
        time_row11.addWidget(btn_now11)
        time_row11.addStretch()
        f11.addRow("time (Unix s):", time_row11)
        self.adm_inner_stack.addWidget(p11)  # 11

        # page 12: ADD_CONTACT (SharedContact)
        p12, f12 = _make_form_group("Add Contact — SharedContact")
        self.adm_ct_node_edit = QLineEdit()
        self.adm_ct_node_edit.setPlaceholderText("!aabbccdd")
        self.adm_ct_node_edit.setToolTip("联系人节点号，支持 hex 或十进制")
        self.adm_ct_node_edit.setFixedWidth(240)
        self.adm_ct_node_edit.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        f12.addRow("node_num:", self.adm_ct_node_edit)
        self.adm_ct_ignore_chk = QCheckBox("should_ignore（加入屏蔽列表）")
        f12.addRow("", self.adm_ct_ignore_chk)
        self.adm_ct_verified_chk = QCheckBox("manually_verified（手动标记密钥已验证）")
        f12.addRow("", self.adm_ct_verified_chk)
        self.adm_inner_stack.addWidget(p12)  # 12

        # page 13: KEY_VERIFICATION (KeyVerificationAdmin)
        p13, f13 = _make_form_group("Key Verification — KeyVerificationAdmin")
        self.adm_kv_type_combo = QComboBox()
        for val, name in _KV_MSG_TYPES:
            self.adm_kv_type_combo.addItem(name, userData=val)
        f13.addRow("message_type:", self.adm_kv_type_combo)
        self.adm_kv_node_edit = QLineEdit()
        self.adm_kv_node_edit.setPlaceholderText("!aabbccdd")
        self.adm_kv_node_edit.setToolTip("远端节点号，支持 hex 或十进制")
        self.adm_kv_node_edit.setFixedWidth(240)
        self.adm_kv_node_edit.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        f13.addRow("remote_nodenum:", self.adm_kv_node_edit)
        self.adm_kv_nonce_spin = QSpinBox()
        self.adm_kv_nonce_spin.setRange(0, 2_147_483_647)
        self.adm_kv_nonce_spin.setToolTip("连接追踪 nonce (uint64，填低32位)")
        f13.addRow("nonce:", self.adm_kv_nonce_spin)
        self.adm_kv_secnum_spin = QSpinBox()
        self.adm_kv_secnum_spin.setRange(0, 9999)
        self.adm_kv_secnum_spin.setToolTip("4位安全码（0=不填）")
        f13.addRow("security_number (0=不填):", self.adm_kv_secnum_spin)
        self.adm_inner_stack.addWidget(p13)  # 13

        # page 14: BACKUP_LOCATION
        p14 = QWidget()
        p14f = QFormLayout(p14)
        self.adm_backup_loc_combo = QComboBox()
        for val, name in _BACKUP_LOCATIONS:
            self.adm_backup_loc_combo.addItem(name, userData=val)
        p14f.addRow("BackupLocation:", self.adm_backup_loc_combo)
        self.adm_inner_stack.addWidget(p14)  # 14

        # page 15: SEND_INPUT_EVENT (InputEvent)
        p15, f15 = _make_form_group("Send Input Event — InputEvent")
        self.adm_evt_code_spin = QSpinBox()
        self.adm_evt_code_spin.setRange(0, 255)
        self.adm_evt_code_spin.setToolTip("输入事件码 (uint8)")
        f15.addRow("event_code:", self.adm_evt_code_spin)
        self.adm_evt_kbchar_spin = QSpinBox()
        self.adm_evt_kbchar_spin.setRange(0, 255)
        self.adm_evt_kbchar_spin.setToolTip("键盘字符码 (uint8)")
        f15.addRow("kb_char:", self.adm_evt_kbchar_spin)
        self.adm_evt_tx_spin = QSpinBox()
        self.adm_evt_tx_spin.setRange(0, 65535)
        self.adm_evt_tx_spin.setToolTip("触摸 X 坐标 (uint16)")
        f15.addRow("touch_x:", self.adm_evt_tx_spin)
        self.adm_evt_ty_spin = QSpinBox()
        self.adm_evt_ty_spin.setRange(0, 65535)
        self.adm_evt_ty_spin.setToolTip("触摸 Y 坐标 (uint16)")
        f15.addRow("touch_y:", self.adm_evt_ty_spin)
        self.adm_inner_stack.addWidget(p15)  # 15

        og_v.addWidget(self.adm_inner_stack)
        cv.addWidget(op_group)

        # ── Session Passkey 组 ────────────────────────────────────────────────
        pk_group = QGroupBox("Session Passkey（防重放，可选）")
        pk_group.setStyleSheet(_S_GROUP)
        pk_h = QHBoxLayout(pk_group)
        pk_h.setContentsMargins(6, 4, 6, 6)
        self.adm_passkey_edit = QLineEdit()
        self.adm_passkey_edit.setMaxLength(16)
        self.adm_passkey_edit.setPlaceholderText("16 hex 字符 = 8 字节，留空=自动注入")
        self.adm_passkey_edit.setFont(QFont("Consolas", 10))
        self.adm_passkey_edit.setToolTip(
            "收到 GET 响应后自动存储并注入（无需手动填写）\n"
            "手动填写可覆盖自动值，SET 命令需要有效 passkey，300秒内有效"
        )
        pk_h.addWidget(self.adm_passkey_edit)
        btn_pk_clr = QPushButton("清空")
        btn_pk_clr.setStyleSheet(_S_SMALL)
        btn_pk_clr.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_pk_clr.clicked.connect(self.adm_passkey_edit.clear)
        pk_h.addWidget(btn_pk_clr)
        cv.addWidget(pk_group)
        # passkey 状态标签
        self.passkey_status_lbl = QLabel("○ 未获取（发送任意 GET 后自动存储）")
        self.passkey_status_lbl.setStyleSheet("color:#888; font-size:10px; padding-left:4px;")
        cv.addWidget(self.passkey_status_lbl)

        cv.addStretch()
        scroll.setWidget(content)
        return scroll

    def _build_advanced_group(self) -> QGroupBox:
        """高级选项（可勾选折叠的 GroupBox）。"""
        group = QGroupBox("高级选项（可选）")
        group.setCheckable(True)
        group.setChecked(False)
        group.setStyleSheet(_S_GROUP)

        outer = QVBoxLayout(group)
        outer.setContentsMargins(6, 2, 6, 4)

        # ── 第一行：MeshPacket 级选项 ─────────────────────────────────────────
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)

        self.want_ack_chk = QCheckBox("Want ACK")
        h.addWidget(self.want_ack_chk)

        h.addWidget(QLabel("跳数:"))
        self.hop_spin = QSpinBox()
        self.hop_spin.setRange(0, 7)
        self.hop_spin.setValue(3)
        self.hop_spin.setMinimumWidth(50)
        h.addWidget(self.hop_spin)

        h.addWidget(QLabel("Packet ID:"))
        self.pid_spin = QSpinBox()
        self.pid_spin.setRange(0, 2_147_483_647)
        self.pid_spin.setValue(0)
        self.pid_spin.setToolTip("0 = 自动随机生成")
        self.pid_spin.setMinimumWidth(90)
        h.addWidget(self.pid_spin)

        self.from_chk = QCheckBox("自定义 From:")
        h.addWidget(self.from_chk)
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText("!xxxxxxxx")
        self.from_edit.setMinimumWidth(110)
        self.from_edit.setEnabled(False)
        self.from_chk.toggled.connect(self.from_edit.setEnabled)
        h.addWidget(self.from_edit)
        h.addStretch()

        # ── 第二行：Data 子字段 ───────────────────────────────────────────────
        h2 = QHBoxLayout()
        h2.setContentsMargins(0, 0, 0, 0)
        h2.setSpacing(14)

        self.want_resp_chk = QCheckBox("Want Response")
        self.want_resp_chk.setToolTip("请求接收方回应（decoded.want_response）")
        h2.addWidget(self.want_resp_chk)

        h2.addWidget(QLabel("Reply-to ID:"))
        self.reply_id_spin = QSpinBox()
        self.reply_id_spin.setRange(0, 2_147_483_647)
        self.reply_id_spin.setValue(0)
        self.reply_id_spin.setToolTip("回复的原消息 Packet ID（0=不填）")
        self.reply_id_spin.setMinimumWidth(90)
        h2.addWidget(self.reply_id_spin)

        h2.addWidget(QLabel("Emoji:"))
        self.emoji_spin = QSpinBox()
        self.emoji_spin.setRange(0, 2_147_483_647)
        self.emoji_spin.setValue(0)
        self.emoji_spin.setToolTip("Emoji Unicode 码点（0=不填）")
        self.emoji_spin.setMinimumWidth(90)
        h2.addWidget(self.emoji_spin)
        h2.addStretch()

        self._adv_content = QWidget()
        adv_v = QVBoxLayout(self._adv_content)
        adv_v.setContentsMargins(0, 0, 0, 0)
        adv_v.setSpacing(4)
        row1_w = QWidget()
        row1_w.setLayout(h)
        adv_v.addWidget(row1_w)
        row2_w = QWidget()
        row2_w.setLayout(h2)
        adv_v.addWidget(row2_w)

        self._adv_content.setVisible(False)
        outer.addWidget(self._adv_content)

        # 勾选 → 显示内容
        group.toggled.connect(self._adv_content.setVisible)
        return group

    def _build_send_row(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(0, 2, 0, 2)
        self.lbl_hint = QLabel("串口连接后可发送")
        self.lbl_hint.setStyleSheet("color:#666; font-size:11px;")
        h.addWidget(self.lbl_hint)
        h.addStretch()

        btn_clr = QPushButton("清空日志")
        btn_clr.setStyleSheet(_S_SMALL)
        btn_clr.clicked.connect(self._clear_log)
        h.addWidget(btn_clr)

        self.btn_send = QPushButton("▶  发送")
        self.btn_send.setStyleSheet(_S_SEND)
        self.btn_send.clicked.connect(self._on_send_clicked)
        h.addWidget(self.btn_send)
        return h

    def _build_log_area(self) -> QTabWidget:
        """三 Tab 区域：发送日志 / JSON 详情 / Hex 详情。"""
        tabs = QTabWidget()
        tabs.setMinimumHeight(80)
        tabs.setMaximumHeight(220)
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #333; }"
            "QTabBar::tab { background: #252525; color: #aaa; padding: 3px 10px; }"
            "QTabBar::tab:selected { background: #2d2d2d; color: #fff; }"
        )

        mono = QFont("Consolas", 10)

        # ── Tab 0: 发送日志 ──────────────────────────────────────────────────
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(mono)
        self.log_edit.setStyleSheet(_S_LOG)
        self.log_edit.setPlaceholderText("发送日志…")

        # ── Tab 1: JSON 详情 ─────────────────────────────────────────────────
        self.sent_json_edit = QTextEdit()
        self.sent_json_edit.setReadOnly(True)
        self.sent_json_edit.setFont(mono)
        self.sent_json_edit.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; border:none;"
        )
        self.sent_json_edit.setPlaceholderText("发送后自动显示已发包的 JSON 结构…")
        self._sent_json_hl = JsonHighlighter(self.sent_json_edit.document())

        # ── Tab 2: Hex 详情 ──────────────────────────────────────────────────
        self.sent_hex_edit = QTextEdit()
        self.sent_hex_edit.setReadOnly(True)
        self.sent_hex_edit.setFont(mono)
        self.sent_hex_edit.setStyleSheet(
            "background:#1a1a2e; color:#a0c4ff; border:none;"
        )
        self.sent_hex_edit.setPlaceholderText("发送后自动显示帧原始字节…")

        tabs.addTab(self.log_edit,      "发送日志")
        tabs.addTab(self.sent_json_edit, "JSON")
        tabs.addTab(self.sent_hex_edit,  "Hex")

        self._sent_tabs = tabs
        return tabs

    # ── 槽函数 ────────────────────────────────────────────────────────────────

    def _private_config_op_needs_response(self, op: object) -> bool:
        if op in ("gateway_announce",):
            return False
        broadcast_ops = self.__dict__.get("_broadcast_private_config_ops", set())
        if op in broadcast_ops and hasattr(self, "to_edit"):
            try:
                if _parse_node_id(self.to_edit.text()) == 0xFFFFFFFF:
                    return False
            except Exception:
                pass
        return op in (
            "get_factory_identity",
            "get_network_config",
            "get_join_lock_advertise",
            "get_config",
            "get_sync_wakeup",
            "get_info_labels",
            "set_factory_identity",
            "set_sync_wakeup",
            "keep_awake",
            "join_network_v2",
            "join_network_v2_gateway",
            "channel12_config",
            "set_info_label",
            "enter_bootloader",
            "change_admin",
            "reset_network_config",
            "change_network_key",
            "trusted_gateway_config",
        )

    def _admin_op_needs_response(self) -> bool:
        if not hasattr(self, "adm_op_combo"):
            return False
        entry = self.adm_op_combo.currentData()
        if entry is None:
            return False
        _, field_name, *_ = entry
        return field_name is not None and field_name.startswith("get_")

    def _sync_want_response_default(self) -> None:
        if not hasattr(self, "want_resp_chk") or not hasattr(self, "portnum_combo"):
            return
        idx = self.portnum_combo.currentIndex()
        if idx < 0:
            return
        page = _PORTNUM_OPTIONS[idx][2]
        want_response = False
        if page == 5:
            want_response = self._admin_op_needs_response()
        elif page == 6 and hasattr(self, "pc_op_combo"):
            want_response = self._private_config_op_needs_response(self.pc_op_combo.currentData())
        self.want_resp_chk.setChecked(want_response)

    def _on_portnum_changed(self, idx: int):
        _, portnum_val, page = _PORTNUM_OPTIONS[idx]
        self.stack.setCurrentIndex(page)
        self.want_ack_chk.setChecked(portnum_val == 6)
        self._sync_want_response_default()

    def _on_adm_op_changed(self, _idx: int):
        """Admin 操作选择变更：切换内层参数页并更新动态标签。"""
        entry = self.adm_op_combo.currentData()
        if entry is None:
            return
        _, field_name, input_type, extra_lbl, max_len = entry
        if input_type < 0:
            return
        if extra_lbl:
            self.adm_lbl_uint32.setText(extra_lbl + ":")
            self.adm_lbl_int32.setText(extra_lbl + ":")
            self.adm_lbl_str.setText(extra_lbl + ":")
        else:
            self.adm_lbl_uint32.setText("值 (uint32):")
            self.adm_lbl_int32.setText("值 (int32):")
            self.adm_lbl_str.setText("内容:")
        if max_len:
            self.adm_str_edit.setMaxLength(max_len)
        if input_type == 1:
            if _is_admin_node_id_field(field_name):
                self.adm_uint32_stack.setCurrentWidget(self.adm_uint32_node_edit)
                self.adm_uint32_stack.setFixedWidth(240)
                self.adm_uint32_hint_lbl.setText(
                    "节点号支持 !aabbccdd / aabbccdd / 0xaabbccdd / 十进制"
                )
                self.adm_uint32_hint_lbl.show()
            else:
                self.adm_uint32_stack.setCurrentWidget(self.adm_uint32_spin)
                self.adm_uint32_stack.setFixedWidth(120)
                self.adm_uint32_hint_lbl.hide()
                # get_channel_request: 最小值必须为 1（protobuf 0=not present）
                if field_name == "get_channel_request":
                    self.adm_uint32_spin.setMinimum(1)
                    if self.adm_uint32_spin.value() == 0:
                        self.adm_uint32_spin.setValue(1)
                else:
                    self.adm_uint32_spin.setMinimum(0)
        # GET 操作固件只在 want_response=true 时才构造响应，自动联动勾选框
        self._sync_want_response_default()
        self.adm_inner_stack.setCurrentIndex(input_type)

    def _on_node_selected(self, idx: int):
        nid = self.node_combo.itemData(idx)
        if nid:
            self.to_edit.setText(nid)
            self._sync_private_config_target_node_fields(nid)
            self._select_join_lock_for_node(nid, fill=False)

    def _on_send_clicked(self):
        try:
            packet = self._build_packet()
            if self._is_join_network_v2_send():
                nodeinfo_packet = self._build_join_v2_nodeinfo_packet(packet)
                self.send_requested.emit(nodeinfo_packet)
                if hasattr(self, "btn_send"):
                    self.btn_send.setEnabled(False)
                    set_widget_text(self.btn_send, "3 秒后发送入网请求")
                self.log_result(True, tr("JoinNetWorkV2: 已先发送 NodeInfo，3 秒后发送入网请求"))
                QTimer.singleShot(
                    3000,
                    lambda packet=packet: self._send_delayed_join_network_v2(packet),
                )
                return
        except Exception as exc:
            msg = f"构造包失败: {exc}"
            self.log_result(False, msg)
            tabs = self.__dict__.get("_sent_tabs")
            if tabs is not None:
                tabs.setCurrentIndex(0)
            QMessageBox.warning(self, "发送失败", msg)
            return
        self.send_requested.emit(packet)

    def _is_join_network_v2_send(self) -> bool:
        if not hasattr(self, "portnum_combo") or not hasattr(self, "pc_op_combo"):
            return False
        idx = self.portnum_combo.currentIndex()
        if idx < 0 or idx >= len(_PORTNUM_OPTIONS):
            return False
        return _PORTNUM_OPTIONS[idx][2] == 6 and self.pc_op_combo.currentData() == "join_network_v2"

    def _join_v2_gateway_node_for_nodeinfo(self) -> str:
        candidates = (
            self.pc_na_gwid_edit.text().strip() if hasattr(self, "pc_na_gwid_edit") else "",
            self._local_node_id if hasattr(self, "_local_node_id") else "",
        )
        for node_id in candidates:
            if not node_id:
                continue
            try:
                normalized = self._normalize_node_id_text(node_id)
            except Exception:
                continue
            if normalized != "!ffffffff":
                return normalized
        raise ValueError("JoinNetWorkV2 前置 NodeInfo 需要填写网关节点 ID")

    def _build_join_v2_nodeinfo_packet(self, join_packet: mesh_pb2.MeshPacket) -> mesh_pb2.MeshPacket:
        packet = mesh_pb2.MeshPacket()
        packet.to = _parse_node_id(self._join_v2_gateway_node_for_nodeinfo())
        setattr(packet, "from", join_packet.to)
        packet.channel = 0
        packet.decoded.portnum = 4
        packet.decoded.payload = b""
        packet.want_ack = False
        packet.hop_limit = self.hop_spin.value()
        packet.hop_start = self.hop_spin.value()
        packet.id = random.randint(1, 2_147_483_647)
        return packet

    def _send_delayed_join_network_v2(self, packet: mesh_pb2.MeshPacket) -> None:
        if hasattr(self, "btn_send"):
            self.btn_send.setEnabled(True)
            set_widget_text(self.btn_send, "▶  发送")
        self.send_requested.emit(packet)

    def _clear_log(self):
        self.log_edit.clear()

    # ── 包构造 ────────────────────────────────────────────────────────────────

    def _build_packet(self) -> mesh_pb2.MeshPacket:
        packet = mesh_pb2.MeshPacket()
        packet.to      = _parse_node_id(self.to_edit.text())
        packet.channel = self.channel_spin.value()

        idx         = self.portnum_combo.currentIndex()
        portnum_val = _PORTNUM_OPTIONS[idx][1]
        page_idx    = _PORTNUM_OPTIONS[idx][2]
        if portnum_val == -1:
            portnum_val = 256

        self._autofill_custom_position_time(portnum_val, page_idx)
        packet.decoded.portnum = portnum_val
        packet.decoded.payload = self._build_payload(page_idx)

        force_want_response = False
        force_local_from = False
        if page_idx == 6 and getattr(self, "pc_op_combo", None) and self.pc_op_combo.currentData() == "join_network_v2":
            packet.to = _parse_node_id(self.to_edit.text())
            if packet.to == 0xFFFF_FFFF:
                raise ValueError("JoinNetWorkV2 must be sent to a specific node")
            packet.channel = 0
            packet.pki_encrypted = True
            force_want_response = True
            force_local_from = True
            self.want_ack_chk.setChecked(False)
        elif page_idx == 6 and getattr(self, "pc_op_combo", None) and self.pc_op_combo.currentData() == "join_network_v2_gateway":
            gateway_node = self._gateway_join_v2_target_node()
            self.to_edit.setText(gateway_node)
            packet.to = _parse_node_id(gateway_node)
            packet.channel = 0
            force_want_response = True
            force_local_from = True
            self.want_ack_chk.setChecked(False)
        elif page_idx == 6 and getattr(self, "pc_op_combo", None) and self.pc_op_combo.currentData() == "get_join_lock_advertise":
            packet.to = _parse_node_id(self.to_edit.text())
            if packet.to == 0xFFFF_FFFF:
                raise ValueError("Get JoinLockAdvertise must be sent to a specific node")
            packet.channel = 0
            force_want_response = True
        elif page_idx == 6 and getattr(self, "pc_op_combo", None):
            op = self.pc_op_combo.currentData()
            if op == "gateway_announce":
                self.to_edit.setText("!ffffffff")
                packet.to = 0xFFFF_FFFF
            if op in self._broadcast_private_config_ops and packet.to == 0xFFFF_FFFF:
                packet.channel = 1
                self.channel_spin.setValue(1)
                self.want_ack_chk.setChecked(False)
                self.want_resp_chk.setChecked(False)

        packet.want_ack  = self.want_ack_chk.isChecked()
        packet.hop_limit = self.hop_spin.value()
        packet.hop_start = self.hop_spin.value()

        pid = self.pid_spin.value()
        packet.id = pid if pid != 0 else random.randint(1, 2_147_483_647)

        if self.from_chk.isChecked() and self.from_edit.text().strip() and not force_local_from:
            setattr(packet, "from", _parse_node_id(self.from_edit.text()))

        # Data 子字段
        if force_want_response or self.want_resp_chk.isChecked():
            packet.decoded.want_response = True
        reply_id = self.reply_id_spin.value()
        if reply_id:
            packet.decoded.reply_id = reply_id
        emoji = self.emoji_spin.value()
        if emoji:
            packet.decoded.emoji = emoji

        return packet

    def _autofill_custom_position_time(self, portnum_val: int, page_idx: int) -> None:
        if portnum_val != 286 or page_idx != 1 or not hasattr(self, "time_spin"):
            return
        if self.time_spin.value() == 0:
            self.time_spin.setValue(int(_time.time()))

    def _build_payload(self, page_idx: int) -> bytes:
        if page_idx == 0:
            text = self.text_edit.toPlainText()
            if not text:
                raise ValueError("文本内容不能为空")
            return text.encode("utf-8")

        elif page_idx == 1:
            pos = mesh_pb2.Position()

            # 基本坐标
            pos.latitude_i  = int(self.lat_spin.value() * 1e7)
            pos.longitude_i = int(self.lon_spin.value() * 1e7)
            pos.altitude    = self.alt_spin.value()
            pos.altitude_hae               = self.alt_hae_spin.value()
            pos.altitude_geoidal_separation = self.ageo_spin.value()

            # 时间
            pos.time                    = self.time_spin.value()
            pos.timestamp               = self.ts_spin.value()
            pos.timestamp_millis_adjust = self.ts_ms_spin.value()

            # 精度与卫星
            pos.PDOP         = self.pdop_spin.value()
            pos.HDOP         = self.hdop_spin.value()
            pos.VDOP         = self.vdop_spin.value()
            pos.gps_accuracy = self.gps_acc_spin.value()
            pos.fix_quality  = self.fq_spin.value()
            pos.fix_type     = self.ft_spin.value()
            pos.sats_in_view = self.sats_spin.value()

            # 运动数据
            pos.ground_speed = self.gs_spin.value()
            pos.ground_track = self.gt_spin.value()

            # 来源与其他
            pos.location_source = self.loc_src_combo.currentIndex()
            pos.altitude_source = self.alt_src_combo.currentIndex()
            pos.sensor_id       = self.sensor_spin.value()
            pos.next_update     = self.next_upd_spin.value()
            pos.precision_bits  = self.prec_spin.value()

            return pos.SerializeToString()

        elif page_idx == 3:  # TELEMETRY_APP
            return self._build_payload_telemetry()

        elif page_idx == 4:  # NODEINFO_APP
            return self._build_payload_nodeinfo()

        elif page_idx == 5:  # ADMIN_APP
            return self._build_payload_admin()

        elif page_idx == 6:  # PRIVATE_CONFIG_APP (287)
            return self._build_payload_private_config()

        elif page_idx == 7:  # WAKEUP_COMM_APP (288)
            return self._build_payload_wakeup_comm()

        else:
            hex_str = self.raw_edit.text().strip().replace(" ", "")
            if not hex_str:
                return b""
            if not re.fullmatch(r"[0-9a-fA-F]*", hex_str):
                raise ValueError(f"Hex 包含非法字符: {hex_str!r}")
            if len(hex_str) % 2 != 0:
                raise ValueError("Hex 长度必须为偶数")
            return bytes.fromhex(hex_str)

    def _build_payload_telemetry(self) -> bytes:
        """构造 TELEMETRY_APP payload（DeviceMetrics）。"""
        from meshtastic import telemetry_pb2
        tel = telemetry_pb2.Telemetry()
        tel.time = self.tel_time_spin.value()
        tel.device_metrics.battery_level       = self.tel_batt_spin.value()
        tel.device_metrics.voltage             = self.tel_volt_spin.value()
        tel.device_metrics.channel_utilization = self.tel_chutil_spin.value()
        tel.device_metrics.air_util_tx         = self.tel_airutil_spin.value()
        tel.device_metrics.uptime_seconds      = self.tel_uptime_spin.value()
        return tel.SerializeToString()

    def _build_private_config_page(self) -> QScrollArea:
        """端口 287：PRIVATE_CONFIG_APP 配置页面。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(6, 6, 6, 6)
        cv.setSpacing(8)

        # ── 操作类型 ─────────────────────────────────────────────────────────
        g_op, f_op = _make_form_group("操作类型")
        self.pc_op_combo = QComboBox()
        add_combo_item(self.pc_op_combo, "Get Factory Identity（获取出厂身份）", "get_factory_identity")
        add_combo_item(self.pc_op_combo, "Set Factory Identity（写入出厂身份）", "set_factory_identity")
        add_combo_item(self.pc_op_combo, "Get Network Config（获取网络配置）", "get_network_config")
        add_combo_item(self.pc_op_combo, "Get JoinLockAdvertise", "get_join_lock_advertise")
        add_combo_item(self.pc_op_combo, "Join Network V2 - Gateway", "join_network_v2_gateway")
        add_combo_item(self.pc_op_combo, "Get Sync Wakeup（获取唤醒配置）", "get_sync_wakeup")
        add_combo_item(self.pc_op_combo, "Get Info Labels（获取标签列表）", "get_info_labels")
        add_combo_item(self.pc_op_combo, "Set Sync Wakeup Config（设置唤醒配置）", "set_sync_wakeup")
        add_combo_item(self.pc_op_combo, "Keep Awake（广播/定向长唤醒）", "keep_awake")
        add_combo_item(self.pc_op_combo, "Gateway Announce（广播第二网关）", "gateway_announce")
        add_combo_item(self.pc_op_combo, "Join Network V2（单包快速入网）", "join_network_v2")
        add_combo_item(self.pc_op_combo, "Channel 1/2 Config（信道表）", "channel12_config")
        add_combo_item(self.pc_op_combo, "Set Info Label（添加/修改/删除标签）", "set_info_label")
        add_combo_item(self.pc_op_combo, "Change Admin（更换管理员）", "change_admin")
        add_combo_item(self.pc_op_combo, "Reset Network Config（网络重置）", "reset_network_config")
        add_combo_item(self.pc_op_combo, "Change Network Key（更换网络公钥）", "change_network_key")
        add_combo_item(self.pc_op_combo, "Trusted Gateway Config（可信网关）", "trusted_gateway_config")
        add_combo_item(self.pc_op_combo, "Enter Bootloader（进入 Bootloader）", "enter_bootloader")
        f_op.addRow("操作:", self.pc_op_combo)
        cv.addWidget(g_op)

        # ── Set Sync Wakeup Config 参数表单 ──────────────────────────────────
        self.pc_set_group = QGroupBox("Set Sync Wakeup Config 参数")
        self.pc_set_group.setStyleSheet(_S_GROUP)
        sv = QVBoxLayout(self.pc_set_group)
        sv.setContentsMargins(6, 8, 6, 6)
        sv.setSpacing(6)

        sf = QFormLayout()
        sf.setContentsMargins(0, 0, 0, 0)

        self.pc_enabled_chk = QCheckBox("enabled（启用同步唤醒）")
        self.pc_enabled_chk.setChecked(True)
        sf.addRow("", self.pc_enabled_chk)

        self.pc_strategy_combo = QComboBox()
        add_combo_item(self.pc_strategy_combo, "STRATEGY_FIXED（固定间隔）", 0)
        add_combo_item(self.pc_strategy_combo, "STRATEGY_SCHEDULED（分时段）", 1)
        sf.addRow("strategy:", self.pc_strategy_combo)

        self.pc_sync_label_id_edit = QLineEdit()
        self.pc_sync_label_id_edit.setPlaceholderText("0 = no filter; decimal or 0xHEX")
        self.pc_sync_label_id_edit.setToolTip(
            "PrivateConfigPacket.label_id. Broadcast private config only applies when the node has this InfoLabel id; 0 applies to all."
        )
        sf.addRow("packet_label_id:", self.pc_sync_label_id_edit)

        sv.addLayout(sf)

        # Fixed Wakeup 子分组
        fw_group = QGroupBox("Fixed Wakeup 配置")
        fw_group.setStyleSheet(_S_GROUP)
        ff = QFormLayout(fw_group)
        ff.setContentsMargins(6, 8, 6, 6)

        self.pc_interval_spin = QSpinBox()
        self.pc_interval_spin.setRange(1, 1440)
        self.pc_interval_spin.setValue(30)
        self.pc_interval_spin.setToolTip("唤醒间隔（分钟，1-1440）")
        ff.addRow("interval_min:", _row(self.pc_interval_spin, "分钟"))

        self.pc_align_spin = QSpinBox()
        self.pc_align_spin.setRange(0, 59)
        self.pc_align_spin.setValue(0)
        self.pc_align_spin.setToolTip("对齐分钟（0-59），使唤醒时刻对齐到该分钟")
        ff.addRow("align_minute:", _row(self.pc_align_spin, "(0-59)"))

        self.pc_offset_spin = QSpinBox()
        self.pc_offset_spin.setRange(0, 3599)
        self.pc_offset_spin.setValue(0)
        self.pc_offset_spin.setToolTip("设备偏移秒数（0-3599），用于多设备错峰唤醒")
        ff.addRow("offset_sec:", _row(self.pc_offset_spin, "秒"))

        sv.addWidget(fw_group)

        sched_group = QGroupBox("Scheduled Wakeup 配置")
        sched_group.setStyleSheet(_S_GROUP)
        sched_layout = QVBoxLayout(sched_group)
        sched_layout.setContentsMargins(6, 8, 6, 6)
        sched_layout.setSpacing(4)
        sched_hint = QLabel("最多 4 个分时段；启用复选框的行会写入 scheduled_wakeup.time_slots。")
        sched_hint.setStyleSheet("color:#888; font-size:10px;")
        sched_hint.setWordWrap(True)
        sched_layout.addWidget(sched_hint)
        self.pc_sched_rows: list[tuple[QCheckBox, QSpinBox, QSpinBox, QSpinBox, QSpinBox]] = []
        for i in range(4):
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            enabled = QCheckBox(f"slot {i + 1}")
            start = QSpinBox()
            start.setRange(0, 23)
            start.setValue((i * 6) % 24)
            end = QSpinBox()
            end.setRange(0, 23)
            end.setValue(((i + 1) * 6) % 24)
            interval = QSpinBox()
            interval.setRange(1, 1440)
            interval.setValue(60)
            align = QSpinBox()
            align.setRange(0, 59)
            align.setValue(0)
            row_l.addWidget(enabled)
            row_l.addWidget(QLabel("start"))
            row_l.addWidget(start)
            row_l.addWidget(QLabel("end"))
            row_l.addWidget(end)
            row_l.addWidget(QLabel("interval"))
            row_l.addWidget(interval)
            row_l.addWidget(QLabel("align"))
            row_l.addWidget(align)
            row_l.addStretch()
            sched_layout.addWidget(row)
            self.pc_sched_rows.append((enabled, start, end, interval, align))
        sv.addWidget(sched_group)

        window_group = QGroupBox("Wakeup Window 配置")
        window_group.setStyleSheet(_S_GROUP)
        wf = QFormLayout(window_group)
        wf.setContentsMargins(6, 8, 6, 6)
        wf.setSpacing(5)

        self.pc_win_startup_spin = QSpinBox()
        self.pc_win_startup_spin.setRange(0, 3600)
        self.pc_win_startup_spin.setValue(0)
        wf.addRow("startup_delay_sec:", _row(self.pc_win_startup_spin, "秒"))

        self.pc_win_random_spin = QSpinBox()
        self.pc_win_random_spin.setRange(0, 3600)
        self.pc_win_random_spin.setValue(0)
        wf.addRow("random_delay_max_sec:", _row(self.pc_win_random_spin, "秒"))

        self.pc_win_gateway_spin = QSpinBox()
        self.pc_win_gateway_spin.setRange(0, 3600)
        self.pc_win_gateway_spin.setValue(0)
        wf.addRow("gateway_wait_sec:", _row(self.pc_win_gateway_spin, "秒"))

        self.pc_win_final_spin = QSpinBox()
        self.pc_win_final_spin.setRange(0, 3600)
        self.pc_win_final_spin.setValue(0)
        wf.addRow("final_wait_sec:", _row(self.pc_win_final_spin, "秒"))

        self.pc_win_degraded_spin = QSpinBox()
        self.pc_win_degraded_spin.setRange(0, 86400)
        self.pc_win_degraded_spin.setValue(0)
        wf.addRow("degraded_window_sec:", _row(self.pc_win_degraded_spin, "秒"))

        self.pc_win_factory_spin = QSpinBox()
        self.pc_win_factory_spin.setRange(0, 86400)
        self.pc_win_factory_spin.setValue(0)
        wf.addRow("factory_window_sec:", _row(self.pc_win_factory_spin, "秒"))

        window_note = QLabel("保持 0 表示不在下发包中覆盖该窗口字段，由固件沿用/补默认值。")
        window_note.setStyleSheet("color:#888; font-size:10px;")
        window_note.setWordWrap(True)
        wf.addRow("", window_note)
        sv.addWidget(window_group)

        # 下次唤醒时间显示
        self.pc_next_lbl = QLabel("—")
        self.pc_next_lbl.setStyleSheet("color:#8cc8f0; font-size:11px;")
        sv.addWidget(self.pc_next_lbl)

        cv.addWidget(self.pc_set_group)

        self.pc_fi_group = QGroupBox("Set Factory Identity 参数（工厂固件写入）")
        self.pc_fi_group.setStyleSheet(_S_GROUP)
        fif = QFormLayout(self.pc_fi_group)
        fif.setContentsMargins(8, 8, 8, 8)
        fif.setSpacing(5)

        self.pc_fi_version_spin = QSpinBox()
        self.pc_fi_version_spin.setRange(1, 0x7FFFFFFF)
        self.pc_fi_version_spin.setValue(1)
        fif.addRow("factory_version:", self.pc_fi_version_spin)

        self.pc_fi_node_id_edit = QLineEdit()
        self.pc_fi_node_id_edit.setPlaceholderText("!aabbccdd（档案索引，建议填写目标节点ID）")
        self.pc_fi_node_id_edit.setFont(QFont("Consolas", 9))
        fif.addRow("node_id:", self.pc_fi_node_id_edit)

        self.pc_fi_sn_edit = QLineEdit()
        self.pc_fi_sn_edit.setPlaceholderText("SN，最多20字节")
        fif.addRow("sn:", self.pc_fi_sn_edit)

        self.pc_fi_deveui_edit = QLineEdit()
        self.pc_fi_deveui_edit.setPlaceholderText("16位十六进制，例如 A84041CC1F606353")
        self.pc_fi_deveui_edit.setFont(QFont("Consolas", 9))
        fif.addRow("dev_eui:", self.pc_fi_deveui_edit)

        self.pc_fi_flash_pub_edit = QLineEdit()
        self.pc_fi_flash_pub_edit.setVisible(False)
        self.pc_fi_flash_id_edit = QLineEdit()
        self.pc_fi_flash_id_edit.setVisible(False)

        self.pc_fi_flash_priv_edit = QLineEdit()
        self.pc_fi_flash_priv_edit.setPlaceholderText("Base64 device_private_key（32字节，写入设备）")
        self.pc_fi_flash_priv_edit.setFont(QFont("Consolas", 9))
        fif.addRow("device_private_key:", self.pc_fi_flash_priv_edit)
        self.pc_fi_device_priv_edit = self.pc_fi_flash_priv_edit

        self.pc_fi_legacy_app_key_edit = QLineEdit()
        self.pc_fi_legacy_app_key_edit.setPlaceholderText("LoRaWAN AppKey，Base64 或 32位Hex（16字节，写入设备）")
        self.pc_fi_legacy_app_key_edit.setFont(QFont("Consolas", 9))
        fif.addRow("legacy_app_key:", self.pc_fi_legacy_app_key_edit)

        self.pc_fi_mfg_ts_edit = QLineEdit()
        self.pc_fi_mfg_ts_edit.setPlaceholderText("Unix timestamp；留空则使用当前时间")
        fif.addRow("manufacturing_timestamp:", self.pc_fi_mfg_ts_edit)

        self.pc_fi_status_combo = QComboBox()
        self.pc_fi_status_combo.addItem("VALID (1)", 1)
        self.pc_fi_status_combo.addItem("LOCKED (4)", 4)
        self.pc_fi_status_combo.setCurrentIndex(1)
        fif.addRow("status:", self.pc_fi_status_combo)

        profile_widget = QWidget()
        profile_row = QHBoxLayout(profile_widget)
        profile_row.setContentsMargins(0, 0, 0, 0)
        profile_row.setSpacing(5)
        self.pc_fi_profile_combo = QComboBox()
        add_combo_item(self.pc_fi_profile_combo, "无保存档案", None)
        self.pc_fi_profile_combo.currentIndexChanged.connect(self._on_factory_profile_changed)
        self.pc_fi_load_btn = QPushButton("加载档案")
        self.pc_fi_load_btn.setStyleSheet(_S_SMALL)
        self.pc_fi_load_btn.clicked.connect(self._on_factory_profile_load_clicked)
        self.pc_fi_save_btn = QPushButton("保存档案")
        self.pc_fi_save_btn.setStyleSheet(_S_SMALL)
        self.pc_fi_save_btn.clicked.connect(self._on_factory_profile_save_clicked)
        profile_row.addWidget(self.pc_fi_profile_combo, stretch=1)
        profile_row.addWidget(self.pc_fi_load_btn)
        profile_row.addWidget(self.pc_fi_save_btn)
        fif.addRow("profiles:", profile_widget)

        self.pc_fi_gen_keys_btn = QPushButton("生成 Device Key")
        self.pc_fi_gen_keys_btn.setStyleSheet(_S_SMALL)
        self.pc_fi_gen_keys_btn.setToolTip("生成 Meshtastic X25519 device_private_key，并显示派生 device_public_key")
        self.pc_fi_gen_keys_btn.clicked.connect(self._on_generate_factory_identity_keys)
        fif.addRow("", self.pc_fi_gen_keys_btn)

        fi_note = QLabel("注意：正式固件会拒绝写入；只有 DRAGINO_FACTORY_FIRMWARE 且来自串口/手机方向的包才会写入 Flash。")
        fi_note.setStyleSheet("color:#888; font-size:10px;")
        fi_note.setWordWrap(True)
        fif.addRow("", fi_note)

        cv.addWidget(self.pc_fi_group)

        self.pc_na_group = QGroupBox("Network Access 参数（入网邀请）")
        self.pc_na_group.setStyleSheet(_S_GROUP)
        naf = QFormLayout(self.pc_na_group)
        self.pc_na_form = naf
        naf.setContentsMargins(8, 8, 8, 8)
        naf.setSpacing(5)

        join_widget = QWidget()
        join_row = QHBoxLayout(join_widget)
        join_row.setContentsMargins(0, 0, 0, 0)
        join_row.setSpacing(5)
        self.pc_na_join_combo = QComboBox()
        add_combo_item(self.pc_na_join_combo, "无缓存 JoinLockAdvertise", None)
        self.pc_na_join_combo.setMinimumWidth(220)
        self.pc_na_fill_join_btn = QPushButton("填充 JoinLock")
        self.pc_na_fill_join_btn.setStyleSheet(_S_SMALL)
        self.pc_na_fill_join_btn.setEnabled(False)
        join_row.addWidget(self.pc_na_join_combo, stretch=1)
        join_row.addWidget(self.pc_na_fill_join_btn)
        naf.addRow("cached_join_lock:", join_widget)
        self.pc_na_join_combo.currentIndexChanged.connect(self._on_join_lock_combo_changed)
        self.pc_na_fill_join_btn.clicked.connect(self._on_fill_join_lock_clicked)

        self.pc_na_flash_priv_edit = QLineEdit()
        self.pc_na_flash_priv_edit.setPlaceholderText("Base64 device_private_key（32字节，用于生成 auth_code）")
        self.pc_na_flash_priv_edit.setFont(QFont("Consolas", 9))
        self.pc_na_flash_priv_edit.setEchoMode(QLineEdit.EchoMode.Password)
        naf.addRow("device_private_key:", self.pc_na_flash_priv_edit)
        self.pc_na_device_priv_edit = self.pc_na_flash_priv_edit

        self.pc_na_flash_id_edit = QLineEdit()
        self.pc_na_flash_id_edit.setVisible(False)

        self.pc_na_nonce_edit = QLineEdit()
        self.pc_na_nonce_edit.setPlaceholderText("Base64 join_challenge（16字节，来自 JoinLockAdvertise）")
        self.pc_na_nonce_edit.setFont(QFont("Consolas", 9))
        naf.addRow("join_challenge:", self.pc_na_nonce_edit)
        self.pc_na_challenge_edit = self.pc_na_nonce_edit

        self.pc_na_global_pub_edit = QLineEdit()
        self.pc_na_global_pub_edit.setPlaceholderText("Base64 network_public_key（32字节）")
        self.pc_na_global_pub_edit.setFont(QFont("Consolas", 9))
        naf.addRow("network_public_key:", self.pc_na_global_pub_edit)

        self.pc_na_gwpub_edit = QLineEdit()
        self.pc_na_gwpub_edit.setPlaceholderText("Base64 gateway_public_key（32字节）")
        self.pc_na_gwpub_edit.setFont(QFont("Consolas", 9))
        naf.addRow("gateway_public_key:", self.pc_na_gwpub_edit)

        self.pc_na_gwid_edit = QLineEdit()
        self.pc_na_gwid_edit.setPlaceholderText("!aabbccdd")
        naf.addRow("gateway_node_id:", self.pc_na_gwid_edit)

        self.pc_jv2_seed_widget = QWidget()
        jv2_seed_row = QHBoxLayout(self.pc_jv2_seed_widget)
        jv2_seed_row.setContentsMargins(0, 0, 0, 0)
        jv2_seed_row.setSpacing(5)
        self.pc_jv2_seed_edit = QLineEdit()
        self.pc_jv2_seed_edit.setPlaceholderText("Base64 network_seed（从 Network 界面加载，16-32字节）")
        self.pc_jv2_seed_edit.setFont(QFont("Consolas", 9))
        jv2_seed_row.addWidget(self.pc_jv2_seed_edit, stretch=1)
        self.pc_gen_jv2_seed_btn = QPushButton("派生信道")
        self.pc_gen_jv2_seed_btn.setStyleSheet(_S_SMALL)
        self.pc_gen_jv2_seed_btn.clicked.connect(self._on_generate_join_v2_seed_clicked)
        jv2_seed_row.addWidget(self.pc_gen_jv2_seed_btn)
        self.pc_jv2_seed_label = QLabel("network_seed:")
        naf.addRow(self.pc_jv2_seed_label, self.pc_jv2_seed_widget)

        self.pc_na_timestamp_edit = QLineEdit()
        self.pc_na_timestamp_edit.setPlaceholderText("Unix timestamp；生成 auth_code 时自动填当前时间")
        naf.addRow("timestamp:", self.pc_na_timestamp_edit)

        self.pc_na_sig_edit = QLineEdit()
        self.pc_na_sig_edit.setPlaceholderText("Base64 auth_code（32字节，点击生成）")
        self.pc_na_sig_edit.setFont(QFont("Consolas", 9))
        self.pc_na_sig_edit.setReadOnly(True)
        naf.addRow("auth_code:", self.pc_na_sig_edit)

        self.pc_gen_na_sig_btn = QPushButton("生成 JoinNetWorkV2 AuthCode")
        self.pc_gen_na_sig_btn.setStyleSheet(_S_SMALL)
        naf.addRow("", self.pc_gen_na_sig_btn)

        self.pc_na_gateway_note = QLabel("Gateway 模式不需要 SN/AuthCode；只需要 network_seed，发送时会自动使用空 auth_code。")
        self.pc_na_gateway_note.setStyleSheet("color:#ffb347; font-size:11px;")
        self.pc_na_gateway_note.setWordWrap(True)
        naf.addRow("", self.pc_na_gateway_note)

        cv.addWidget(self.pc_na_group)

        self.pc_ch12_group = QGroupBox("Channel 1/2 Config 参数")
        self.pc_ch12_group.setStyleSheet(_S_GROUP)
        ch12f = QFormLayout(self.pc_ch12_group)
        ch12f.setContentsMargins(8, 8, 8, 8)
        ch12f.setSpacing(5)

        self.pc_ch12_node_id_edit = QLineEdit()
        self.pc_ch12_node_id_edit.setPlaceholderText("!aabbccdd（保存档案索引）")
        self.pc_ch12_node_id_edit.setFont(QFont("Consolas", 9))
        ch12f.addRow("node_id:", self.pc_ch12_node_id_edit)

        self.pc_ch12_send_channel_spin = QSpinBox()
        self.pc_ch12_send_channel_spin.setRange(0, 7)
        self.pc_ch12_send_channel_spin.setValue(self.channel_spin.value())
        self.pc_ch12_send_channel_spin.setToolTip("Channel12Config 发送时使用的 MeshPacket.channel，会随节点档案持久化")
        ch12f.addRow("send_channel:", self.pc_ch12_send_channel_spin)

        ch12_profile_widget = QWidget()
        ch12_profile_row = QHBoxLayout(ch12_profile_widget)
        ch12_profile_row.setContentsMargins(0, 0, 0, 0)
        ch12_profile_row.setSpacing(5)
        self.pc_ch12_profile_combo = QComboBox()
        add_combo_item(self.pc_ch12_profile_combo, "无保存信道配置", None)
        self.pc_ch12_profile_combo.currentIndexChanged.connect(self._on_channel12_profile_load_clicked)
        self.pc_ch12_autofill_btn = QPushButton("自动填充")
        self.pc_ch12_autofill_btn.setStyleSheet(_S_SMALL)
        self.pc_ch12_autofill_btn.clicked.connect(self._on_channel12_autofill_clicked)
        self.pc_ch12_load_btn = QPushButton("加载档案")
        self.pc_ch12_load_btn.setStyleSheet(_S_SMALL)
        self.pc_ch12_load_btn.clicked.connect(self._on_channel12_profile_load_clicked)
        self.pc_ch12_save_btn = QPushButton("保存档案")
        self.pc_ch12_save_btn.setStyleSheet(_S_SMALL)
        self.pc_ch12_save_btn.clicked.connect(self._on_channel12_profile_save_clicked)
        ch12_profile_row.addWidget(self.pc_ch12_profile_combo, stretch=1)
        ch12_profile_row.addWidget(self.pc_ch12_autofill_btn)
        ch12_profile_row.addWidget(self.pc_ch12_load_btn)
        ch12_profile_row.addWidget(self.pc_ch12_save_btn)
        ch12f.addRow("profiles:", ch12_profile_widget)

        self.pc_ch1_name_edit = QLineEdit()
        self.pc_ch1_name_edit.setPlaceholderText("Channel 1 name（私有配置信道）")
        ch12f.addRow("channel1_name:", self.pc_ch1_name_edit)

        self.pc_ch1_psk_edit = QLineEdit()
        self.pc_ch1_psk_edit.setPlaceholderText("Base64 psk1（16-32字节）")
        self.pc_ch1_psk_edit.setFont(QFont("Consolas", 9))
        ch12f.addRow("psk1:", self.pc_ch1_psk_edit)

        self.pc_ch2_name_edit = QLineEdit()
        self.pc_ch2_name_edit.setPlaceholderText("Channel 2 name（业务/功能信道）")
        ch12f.addRow("channel2_name:", self.pc_ch2_name_edit)

        self.pc_ch2_psk_edit = QLineEdit()
        self.pc_ch2_psk_edit.setPlaceholderText("Base64 psk2（16-32字节）")
        self.pc_ch2_psk_edit.setFont(QFont("Consolas", 9))
        ch12f.addRow("psk2:", self.pc_ch2_psk_edit)

        cv.addWidget(self.pc_ch12_group)

        # ── Legacy Set Global Key 参数表单（已隐藏，仅保留兼容旧对象引用）──────────────────────
        self.pc_enroll_group = QGroupBox("Set Global Key 参数（首次入网）")
        self.pc_enroll_group.setStyleSheet(_S_GROUP)
        ef = QFormLayout(self.pc_enroll_group)
        ef.setContentsMargins(8, 8, 8, 8)
        ef.setSpacing(5)

        self.pc_cpub_edit = QLineEdit()
        self.pc_cpub_edit.setPlaceholderText("Base64 network_public_key（32字节，legacy hidden）")
        self.pc_cpub_edit.setFont(QFont("Consolas", 9))
        ef.addRow("global_public_key:", self.pc_cpub_edit)

        self.pc_gwpub_edit = QLineEdit()
        self.pc_gwpub_edit.setPlaceholderText("Base64 Gateway 公钥（32字节）")
        self.pc_gwpub_edit.setFont(QFont("Consolas", 9))
        ef.addRow("gateway_public_key:", self.pc_gwpub_edit)

        self.pc_gwid_edit = QLineEdit()
        self.pc_gwid_edit.setPlaceholderText("!aabbccdd")
        ef.addRow("gateway_node_id:", self.pc_gwid_edit)

        enroll_note = QLabel("时间戳自动取当前时间（无需填写）")
        enroll_note.setStyleSheet("color:#888; font-size:10px;")
        ef.addRow("", enroll_note)

        self.pc_fill_enroll_btn = QPushButton("从虚拟身份填充")
        self.pc_fill_enroll_btn.setStyleSheet(_S_SMALL)
        self.pc_fill_enroll_btn.setToolTip("从 Network 身份 Dock 自动填入 network_public_key、Gateway 公钥和节点ID")
        ef.addRow("", self.pc_fill_enroll_btn)

        cv.addWidget(self.pc_enroll_group)

        # ── Change Admin 参数表单（更换管理员）──────────────────────────────
        self.pc_change_group = QGroupBox("Change Admin 参数（更换管理员）")
        self.pc_change_group.setStyleSheet(_S_GROUP)
        chf = QFormLayout(self.pc_change_group)
        chf.setContentsMargins(8, 8, 8, 8)
        chf.setSpacing(5)

        self.pc_newgwpub_edit = QLineEdit()
        self.pc_newgwpub_edit.setPlaceholderText("Base64 新网关公钥（32字节）")
        self.pc_newgwpub_edit.setFont(QFont("Consolas", 9))
        chf.addRow("new_gateway_public_key:", self.pc_newgwpub_edit)

        self.pc_newgwid_edit = QLineEdit()
        self.pc_newgwid_edit.setPlaceholderText("!aabbccdd（新网关节点ID）")
        chf.addRow("new_gateway_node_id:", self.pc_newgwid_edit)

        self.pc_dev_node_edit = QLineEdit()
        self.pc_dev_node_edit.setPlaceholderText("!aabbccdd（目标设备节点ID，用于签名绑定）")
        chf.addRow("target_device_node_id:", self.pc_dev_node_edit)

        self.pc_sig_edit = QLineEdit()
        self.pc_sig_edit.setPlaceholderText("HMAC auth_code Base64（32字节，点击生成）")
        self.pc_sig_edit.setFont(QFont("Consolas", 9))
        self.pc_sig_edit.setReadOnly(True)
        chf.addRow("auth_code (Base64):", self.pc_sig_edit)

        change_note = QLabel("时间戳自动取当前时间（无需填写）")
        change_note.setStyleSheet("color:#888; font-size:10px;")
        chf.addRow("", change_note)

        ch_btn_row = QHBoxLayout()
        self.pc_fill_change_btn = QPushButton("从虚拟身份填充")
        self.pc_fill_change_btn.setStyleSheet(_S_SMALL)
        self.pc_fill_change_btn.setToolTip("将虚拟身份的公钥/节点ID填入新网关字段")
        ch_btn_row.addWidget(self.pc_fill_change_btn)

        self.pc_gen_sig_btn = QPushButton("生成 auth_code")
        self.pc_gen_sig_btn.setStyleSheet(_S_SMALL)
        self.pc_gen_sig_btn.setToolTip("使用目标节点 device_private_key 生成 ChangeAdmin.auth_code")
        ch_btn_row.addWidget(self.pc_gen_sig_btn)
        chf.addRow("", ch_btn_row)

        cv.addWidget(self.pc_change_group)

        # ── Reset Config 参数表单（远程清除）────────────────────────────────
        self.pc_reset_group = QGroupBox("Reset Network Config 参数（远程清除）")
        self.pc_reset_group.setStyleSheet(_S_GROUP)
        rcf = QFormLayout(self.pc_reset_group)
        rcf.setContentsMargins(8, 8, 8, 8)
        rcf.setSpacing(5)

        self.pc_reset_type_combo = QComboBox()
        add_combo_item(self.pc_reset_type_combo, "FACTORY（恢复出厂/默认配置）", 1)
        add_combo_item(self.pc_reset_type_combo, "NETWORK（清除网络配置）", 2)
        rcf.addRow("reset_type:", self.pc_reset_type_combo)

        self.pc_reset_dev_node_edit = QLineEdit()
        self.pc_reset_dev_node_edit.setPlaceholderText("!aabbccdd（目标设备节点ID，用于签名绑定）")
        rcf.addRow("target_device_node_id:", self.pc_reset_dev_node_edit)

        self.pc_reset_sig_edit = QLineEdit()
        self.pc_reset_sig_edit.setPlaceholderText("auth_code Base64（32字节；当前固件允许为空，空值自动补0）")
        self.pc_reset_sig_edit.setFont(QFont("Consolas", 9))
        self.pc_reset_sig_edit.setReadOnly(True)
        rcf.addRow("auth_code (Base64):", self.pc_reset_sig_edit)

        reset_note = QLabel("时间戳自动取当前时间（无需填写）")
        reset_note.setStyleSheet("color:#888; font-size:10px;")
        rcf.addRow("", reset_note)

        self.pc_gen_reset_sig_btn = QPushButton("填充空 auth_code")
        self.pc_gen_reset_sig_btn.setStyleSheet(_S_SMALL)
        self.pc_gen_reset_sig_btn.setToolTip("当前固件未校验 ResetNetworkConfig.auth_code；点击填充32字节0并记录时间戳")
        self.pc_gen_reset_sig_btn.clicked.connect(self._on_fill_empty_reset_auth_clicked)
        rcf.addRow("", self.pc_gen_reset_sig_btn)

        cv.addWidget(self.pc_reset_group)

        # ── Change Network Key 参数表单（更换网络公钥）──────────────────────
        self.pc_cck_group = QGroupBox("Change Network Key 参数（更换网络公钥）")
        self.pc_cck_group.setStyleSheet(_S_GROUP)
        cckf = QFormLayout(self.pc_cck_group)
        cckf.setContentsMargins(8, 8, 8, 8)
        cckf.setSpacing(5)

        self.pc_new_cpub_edit = QLineEdit()
        self.pc_new_cpub_edit.setPlaceholderText("Base64 新 network_public_key（32字节）")
        self.pc_new_cpub_edit.setFont(QFont("Consolas", 9))
        cckf.addRow("new_network_public_key:", self.pc_new_cpub_edit)

        seed_row = QWidget()
        seed_layout = QHBoxLayout(seed_row)
        seed_layout.setContentsMargins(0, 0, 0, 0)
        seed_layout.setSpacing(4)
        self.pc_new_seed_edit = QLineEdit()
        self.pc_new_seed_edit.setPlaceholderText("Base64 或 Hex new_network_seed（16-32字节）")
        self.pc_new_seed_edit.setFont(QFont("Consolas", 9))
        seed_layout.addWidget(self.pc_new_seed_edit, stretch=1)
        self.pc_gen_new_seed_btn = QPushButton("生成")
        self.pc_gen_new_seed_btn.setStyleSheet(_S_SMALL)
        self.pc_gen_new_seed_btn.setToolTip("生成 16 字节 new_network_seed")
        self.pc_gen_new_seed_btn.clicked.connect(self._on_generate_change_network_seed_clicked)
        seed_layout.addWidget(self.pc_gen_new_seed_btn)
        cckf.addRow("new_network_seed:", seed_row)

        self.pc_cck_dev_node_edit = QLineEdit()
        self.pc_cck_dev_node_edit.setPlaceholderText("!aabbccdd（目标设备节点ID，用于签名绑定）")
        cckf.addRow("target_device_node_id:", self.pc_cck_dev_node_edit)

        self.pc_cck_sig_edit = QLineEdit()
        self.pc_cck_sig_edit.setPlaceholderText("auth_code Base64（32字节；当前固件允许为空，空值自动补0）")
        self.pc_cck_sig_edit.setFont(QFont("Consolas", 9))
        self.pc_cck_sig_edit.setReadOnly(True)
        cckf.addRow("auth_code (Base64):", self.pc_cck_sig_edit)

        cck_note = QLabel("时间戳自动取当前时间；当前固件暂不校验 auth_code，留空会自动补 32 字节 0")
        cck_note.setStyleSheet("color:#888; font-size:10px;")
        cckf.addRow("", cck_note)

        self.pc_gen_cck_sig_btn = QPushButton("填充空 auth_code")
        self.pc_gen_cck_sig_btn.setStyleSheet(_S_SMALL)
        self.pc_gen_cck_sig_btn.setToolTip("当前固件未校验 ChangeNetworkKey.auth_code；点击填充32字节0并记录时间戳")
        self.pc_gen_cck_sig_btn.clicked.connect(self._on_fill_empty_cck_auth_clicked)
        cckf.addRow("", self.pc_gen_cck_sig_btn)

        cv.addWidget(self.pc_cck_group)

        self.pc_tgw_group = QGroupBox("Trusted Gateway Config 参数")
        self.pc_tgw_group.setStyleSheet(_S_GROUP)
        tgwf = QFormLayout(self.pc_tgw_group)
        tgwf.setContentsMargins(8, 8, 8, 8)
        tgwf.setSpacing(5)

        self.pc_tgw_action_combo = QComboBox()
        add_combo_item(self.pc_tgw_action_combo, "GET_LIST（读取可信网关列表）", "get")
        add_combo_item(self.pc_tgw_action_combo, "ADD（添加可信网关）", "add")
        add_combo_item(self.pc_tgw_action_combo, "REMOVE（移除可信网关）", "remove")
        tgwf.addRow("action:", self.pc_tgw_action_combo)

        self.pc_tgw_single_chk = QCheckBox("is_single_gateway")
        self.pc_tgw_single_chk.setChecked(True)
        tgwf.addRow("", self.pc_tgw_single_chk)

        self.pc_tgw_node_edit = QLineEdit()
        self.pc_tgw_node_edit.setPlaceholderText("!aabbccdd（ADD/REMOVE 时填写）")
        self.pc_tgw_node_edit.setFont(QFont("Consolas", 9))
        tgwf.addRow("trusted_gateway:", self.pc_tgw_node_edit)

        tgw_note = QLabel("GET_LIST 会返回 NetWorkConfig；ADD/REMOVE 需要设备已入网且发送方具备配置权限。")
        tgw_note.setStyleSheet("color:#888; font-size:10px;")
        tgw_note.setWordWrap(True)
        tgwf.addRow("", tgw_note)

        self.pc_tgw_group.setVisible(False)
        cv.addWidget(self.pc_tgw_group)

        self.pc_ga_group = QGroupBox("Gateway Announce 参数")
        self.pc_ga_group.setStyleSheet(_S_GROUP)
        gaf = QFormLayout(self.pc_ga_group)
        gaf.setContentsMargins(8, 8, 8, 8)
        gaf.setSpacing(5)

        self.pc_ga_pub_edit = QLineEdit()
        self.pc_ga_pub_edit.setPlaceholderText("Base64 network_public_key（32字节）")
        self.pc_ga_pub_edit.setFont(QFont("Consolas", 9))
        gaf.addRow("network_public_key:", self.pc_ga_pub_edit)

        self.pc_ga_seed_edit = QLineEdit()
        self.pc_ga_seed_edit.setPlaceholderText("Base64 或 Hex network_seed（16-32字节，仅用于生成 auth_code）")
        self.pc_ga_seed_edit.setFont(QFont("Consolas", 9))
        gaf.addRow("network_seed:", self.pc_ga_seed_edit)

        self.pc_ga_auth_edit = QLineEdit()
        self.pc_ga_auth_edit.setPlaceholderText("auth_code Base64；留空则按 network_seed 自动生成")
        self.pc_ga_auth_edit.setFont(QFont("Consolas", 9))
        gaf.addRow("auth_code:", self.pc_ga_auth_edit)

        ga_btn_row = QWidget()
        ga_btn_layout = QHBoxLayout(ga_btn_row)
        ga_btn_layout.setContentsMargins(0, 0, 0, 0)
        ga_btn_layout.setSpacing(4)
        self.pc_ga_fill_btn = QPushButton("从 JoinV2 复制 seed")
        self.pc_ga_fill_btn.setStyleSheet(_S_SMALL)
        self.pc_ga_fill_btn.setToolTip("把 Join Network V2 的 network_seed 复制到 GatewayAnnounce")
        self.pc_ga_fill_btn.clicked.connect(self._on_gateway_announce_fill_from_join_v2_clicked)
        ga_btn_layout.addWidget(self.pc_ga_fill_btn)
        self.pc_ga_auth_btn = QPushButton("生成 auth_code")
        self.pc_ga_auth_btn.setStyleSheet(_S_SMALL)
        self.pc_ga_auth_btn.clicked.connect(self._on_gateway_announce_auth_clicked)
        ga_btn_layout.addWidget(self.pc_ga_auth_btn)
        gaf.addRow("", ga_btn_row)

        ga_note = QLabel("GatewayAnnounce 必须以 broadcast 发送；meshdebug 会自动使用 !ffffffff、channel 1、无 ACK、无回包。")
        ga_note.setStyleSheet("color:#888; font-size:10px;")
        ga_note.setWordWrap(True)
        gaf.addRow("", ga_note)

        self.pc_ga_group.setVisible(False)
        cv.addWidget(self.pc_ga_group)

        self.pc_keep_group = QGroupBox("Keep Awake 参数")
        self.pc_keep_group.setStyleSheet(_S_GROUP)
        kaf = QFormLayout(self.pc_keep_group)
        kaf.setContentsMargins(8, 8, 8, 8)
        kaf.setSpacing(5)

        self.pc_keep_duration_spin = QSpinBox()
        self.pc_keep_duration_spin.setRange(0, 3600)
        self.pc_keep_duration_spin.setValue(300)
        self.pc_keep_duration_spin.setToolTip("0 表示取消当前长唤醒；常用 300 秒")
        kaf.addRow("duration_sec:", _row(self.pc_keep_duration_spin, "秒"))

        keep_note = QLabel("广播长唤醒走 channel 1 且不回包；定向发送可保留响应，用于调试单节点。")
        keep_note.setStyleSheet("color:#888; font-size:10px;")
        keep_note.setWordWrap(True)
        kaf.addRow("", keep_note)

        self.pc_keep_group.setVisible(False)
        cv.addWidget(self.pc_keep_group)

        self.pc_boot_group = QGroupBox("Enter Bootloader Parameters")
        self.pc_boot_group.setStyleSheet(_S_GROUP)
        bootf = QFormLayout(self.pc_boot_group)
        bootf.setContentsMargins(8, 8, 8, 8)
        bootf.setSpacing(5)

        self.pc_boot_reason_combo = QComboBox()
        self.pc_boot_reason_combo.addItem("UPPER_COMPUTER (3)", 3)
        self.pc_boot_reason_combo.addItem("BLUETOOTH (2)", 2)
        self.pc_boot_reason_combo.addItem("SERIAL (1)", 1)
        self.pc_boot_reason_combo.addItem("TEST (4)", 4)
        self.pc_boot_reason_combo.addItem("UNKNOWN (0)", 0)
        bootf.addRow("reason:", self.pc_boot_reason_combo)

        self.pc_boot_delay_spin = QSpinBox()
        self.pc_boot_delay_spin.setRange(0, 60000)
        self.pc_boot_delay_spin.setValue(0)
        self.pc_boot_delay_spin.setToolTip("0 lets firmware use its default reboot delay.")
        bootf.addRow("delay_ms:", _row(self.pc_boot_delay_spin, "ms"))

        self.pc_boot_auth_edit = QLineEdit()
        self.pc_boot_auth_edit.setPlaceholderText("optional Base64 auth_code, max 32 bytes")
        self.pc_boot_auth_edit.setFont(QFont("Consolas", 9))
        bootf.addRow("auth_code:", self.pc_boot_auth_edit)

        boot_note = QLabel("Direct meshdebug serial command is treated as upper-computer request by firmware.")
        boot_note.setStyleSheet("color:#888; font-size:10px;")
        boot_note.setWordWrap(True)
        bootf.addRow("", boot_note)

        self.pc_boot_group.setVisible(False)
        cv.addWidget(self.pc_boot_group)

        # auth_code 时间戳缓存：由 app.py 生成 auth_code 时写入，发送时使用同一时间戳
        self._pc_network_access_timestamp: int | None = None
        self._pc_change_admin_timestamp: int | None = None
        self._pc_reset_timestamp:        int | None = None
        self._pc_cck_timestamp:          int | None = None

        # ── Set Admin Key 参数表单 ────────────────────────────────────────────
        self.pc_ak_group = QGroupBox("Set Admin Key 参数")
        self.pc_ak_group.setStyleSheet(_S_GROUP)
        akv = QVBoxLayout(self.pc_ak_group)
        akv.setContentsMargins(6, 8, 6, 6)
        akf = QFormLayout()
        akf.setContentsMargins(0, 0, 0, 0)
        self.pc_ak_edit = QLineEdit()
        self.pc_ak_edit.setPlaceholderText("Base64 管理员公钥（任意字节数）")
        self.pc_ak_edit.setFont(QFont("Consolas", 9))
        akf.addRow("admin_key (Base64):", self.pc_ak_edit)
        ak_note = QLabel("需要设备已入网且在私有配置信道或 PKI 加密发送")
        ak_note.setStyleSheet("color:#888; font-size:10px;")
        akf.addRow("", ak_note)
        akv.addLayout(akf)
        self.pc_ak_group.setVisible(False)
        cv.addWidget(self.pc_ak_group)

        # ── Set Device Name 参数表单 ──────────────────────────────────────────
        self.pc_dn_group = QGroupBox("Set Device Name 参数")
        self.pc_dn_group.setStyleSheet(_S_GROUP)
        dnv = QVBoxLayout(self.pc_dn_group)
        dnv.setContentsMargins(6, 8, 6, 6)
        dnf = QFormLayout()
        dnf.setContentsMargins(0, 0, 0, 0)
        self.pc_dn_edit = QLineEdit()
        self.pc_dn_edit.setPlaceholderText("设备名（最多20字符）")
        dn_row = QHBoxLayout()
        dn_row.addWidget(self.pc_dn_edit)
        self.pc_dn_counter_lbl = QLabel("0/20")
        self.pc_dn_counter_lbl.setStyleSheet("color:#888; font-size:10px;")
        dn_row.addWidget(self.pc_dn_counter_lbl)
        dnf.addRow("device_name:", dn_row)
        self.pc_dn_edit.textChanged.connect(
            lambda t: self.pc_dn_counter_lbl.setText(f"{len(t.encode())}/20")
        )
        dnv.addLayout(dnf)
        self.pc_dn_group.setVisible(False)
        cv.addWidget(self.pc_dn_group)

        # ── Set Info Label 参数表单 ───────────────────────────────────────────
        self.pc_sil_group = QGroupBox("Set Info Label 参数")
        self.pc_sil_group.setStyleSheet(_S_GROUP)
        silv = QVBoxLayout(self.pc_sil_group)
        silv.setContentsMargins(6, 8, 6, 6)
        silf = QFormLayout()
        silf.setContentsMargins(0, 0, 0, 0)
        self.pc_sil_action_combo = QComboBox()
        add_combo_item(self.pc_sil_action_combo, "ADD（新增标签）", 0)
        add_combo_item(self.pc_sil_action_combo, "UPDATE（更新标签）", 1)
        add_combo_item(self.pc_sil_action_combo, "DELETE（删除标签）", 2)
        silf.addRow("action:", self.pc_sil_action_combo)
        self.pc_sil_id_spin = QSpinBox()
        self.pc_sil_id_spin.setRange(0, 65535)
        self.pc_sil_id_spin.setToolTip("标签 ID（ADD/UPDATE/DELETE 均需要）")
        silf.addRow("label_id:", self.pc_sil_id_spin)
        self.pc_sil_key_edit = QLineEdit()
        self.pc_sil_key_edit.setPlaceholderText("键名（max 20 chars）")
        silf.addRow("key:", self.pc_sil_key_edit)
        self.pc_sil_val_edit = QLineEdit()
        self.pc_sil_val_edit.setPlaceholderText("值（max 20 chars）")
        silf.addRow("value:", self.pc_sil_val_edit)
        sil_note = QLabel("DELETE 只需填写 label_id，key/value 忽略")
        sil_note.setStyleSheet("color:#888; font-size:10px;")
        silf.addRow("", sil_note)
        silv.addLayout(silf)
        self.pc_sil_action_combo.currentIndexChanged.connect(self._on_pc_sil_action_changed)
        self.pc_sil_group.setVisible(False)
        cv.addWidget(self.pc_sil_group)

        preset_group = QGroupBox("预设模板")
        preset_group.setStyleSheet(_S_GROUP)
        ph = QHBoxLayout(preset_group)
        ph.setContentsMargins(6, 8, 6, 6)
        ph.setSpacing(4)

        presets = [
            ("每30分钟",  30,  0, 0, True),
            ("每1小时",   60,  0, 0, True),
            ("每2小时",  120,  0, 0, True),
            ("每3小时",  180,  0, 0, True),
            ("关闭唤醒",  30,  0, 0, False),
        ]
        for label, interval, align, offset, enabled in presets:
            btn = QPushButton(label)
            btn.setStyleSheet(_S_SMALL)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(
                lambda _checked, i=interval, a=align, o=offset, e=enabled: (
                    self.pc_interval_spin.setValue(i),
                    self.pc_align_spin.setValue(a),
                    self.pc_offset_spin.setValue(o),
                    self.pc_enabled_chk.setChecked(e),
                    self._update_next_wakeup_label(),
                )
            )
            ph.addWidget(btn)

        cv.addWidget(preset_group)
        cv.addStretch()

        scroll.setWidget(content)

        # 连接信号更新「下次唤醒」标签
        self.pc_op_combo.currentIndexChanged.connect(self._on_pc_op_changed)
        self.pc_interval_spin.valueChanged.connect(self._update_next_wakeup_label)
        self.pc_align_spin.valueChanged.connect(self._update_next_wakeup_label)
        self.pc_offset_spin.valueChanged.connect(self._update_next_wakeup_label)

        # 初始状态
        self._on_pc_op_changed(0)
        self._update_next_wakeup_label()
        return scroll

    def _on_pc_op_changed(self, _idx: int):
        """切换操作类型时显示/隐藏参数表单。"""
        op = self.pc_op_combo.currentData()
        self.pc_set_group.setVisible(op == "set_sync_wakeup")
        self.pc_fi_group.setVisible(op == "set_factory_identity")
        self.pc_na_group.setVisible(op in ("join_network_v2", "join_network_v2_gateway"))
        if hasattr(self, "pc_jv2_seed_edit"):
            is_v2 = op in ("join_network_v2", "join_network_v2_gateway")
            is_gateway_v2 = op == "join_network_v2_gateway"
            self.pc_jv2_seed_label.setVisible(is_v2)
            self.pc_jv2_seed_widget.setVisible(is_v2)
            for widget in (
                self.pc_na_join_combo.parentWidget(),
                self.pc_na_flash_priv_edit,
                self.pc_na_nonce_edit,
                self.pc_na_global_pub_edit,
                self.pc_na_gwpub_edit,
                self.pc_na_gwid_edit,
                self.pc_na_timestamp_edit,
                self.pc_na_sig_edit,
            ):
                self._set_pc_na_row_visible(widget, is_v2 and not is_gateway_v2)
            set_widget_text(
                self.pc_gen_na_sig_btn,
                "Gateway 模式无需 AuthCode" if is_gateway_v2
                else ("生成 JoinNetWorkV2 AuthCode" if is_v2 else "NetworkAccess 已移除")
            )
            self.pc_gen_na_sig_btn.setVisible(is_v2 and not is_gateway_v2)
            self.pc_gen_na_sig_btn.setEnabled(is_v2 and not is_gateway_v2)
            self.pc_na_gateway_note.setVisible(is_gateway_v2)
            if is_gateway_v2 and self._local_node_id:
                self.to_edit.setText(self._local_node_id)
            self._sync_want_response_default()
            if is_v2 and hasattr(self, "want_ack_chk"):
                self.want_ack_chk.setChecked(False)
            if is_v2 and hasattr(self, "channel_spin"):
                self.channel_spin.setValue(0)
        self.pc_ch12_group.setVisible(op == "channel12_config")
        self.pc_enroll_group.setVisible(False)
        self.pc_change_group.setVisible(op == "change_admin")
        self.pc_reset_group.setVisible(op in ("reset_config", "reset_network_config"))
        self.pc_cck_group.setVisible(op == "change_network_key")
        if op in ("change_admin", "reset_config", "reset_network_config", "change_network_key"):
            self._sync_private_config_target_node_fields()
        self.pc_tgw_group.setVisible(op == "trusted_gateway_config")
        self.pc_ga_group.setVisible(op == "gateway_announce")
        self.pc_keep_group.setVisible(op == "keep_awake")
        if op in ("gateway_announce", "keep_awake"):
            self.to_edit.setText("!ffffffff")
            self.channel_spin.setValue(1)
            if hasattr(self, "want_ack_chk"):
                self.want_ack_chk.setChecked(False)
            if hasattr(self, "want_resp_chk"):
                self.want_resp_chk.setChecked(False)
        elif op in self._broadcast_private_config_ops:
            self._sync_want_response_default()
        self.pc_boot_group.setVisible(op == "enter_bootloader")
        if op == "enter_bootloader":
            self.channel_spin.setValue(0)
            if hasattr(self, "want_ack_chk"):
                self.want_ack_chk.setChecked(False)
            if hasattr(self, "want_resp_chk"):
                self.want_resp_chk.setChecked(True)
        self.pc_ak_group.setVisible(op == "set_admin_key")
        self.pc_dn_group.setVisible(op == "set_device_name")
        self.pc_sil_group.setVisible(op == "set_info_label")

    def _on_pc_sil_action_changed(self, _idx: int):
        """DELETE 操作时隐藏 key/value 输入框。"""
        action = self.pc_sil_action_combo.currentData()
        is_delete = (action == 2)
        self.pc_sil_key_edit.setVisible(not is_delete)
        self.pc_sil_val_edit.setVisible(not is_delete)

    def _update_next_wakeup_label(self):
        """实时计算并显示下次唤醒时间。"""
        if not self.pc_enabled_chk.isChecked():
            set_widget_text(self.pc_next_lbl, "（已禁用，不会唤醒）")
            return
        text = _calc_next_wakeup(
            self.pc_interval_spin.value(),
            self.pc_align_spin.value(),
            self.pc_offset_spin.value(),
        )
        set_widget_text(self.pc_next_lbl, text)

    def _build_wakeup_comm_page(self) -> QWidget:
        """端口 288：WAKEUP_COMM_APP 网关命令页面。"""
        w = QWidget()
        wv = QVBoxLayout(w)
        wv.setContentsMargins(6, 6, 6, 6)
        wv.setSpacing(8)

        g_cmd, f_cmd = _make_form_group("网关命令 (Port 288)")
        self.wc_cmd_combo = QComboBox()
        add_combo_item(self.wc_cmd_combo, "REQUEST_TELEMETRY (1) — 请求设备上报遥测", 1)
        add_combo_item(self.wc_cmd_combo, "SET_CONFIG (2) — 下发配置", 2)
        add_combo_item(self.wc_cmd_combo, "SYNC_TIME (3) — 时间同步", 3)
        add_combo_item(self.wc_cmd_combo, "REBOOT (4) — 重启设备", 4)
        f_cmd.addRow("命令类型:", self.wc_cmd_combo)

        wv.addWidget(g_cmd)

        info = QLabel(
            "说明：发送 1 字节命令至端口 288，设备在唤醒后监听此端口。\n"
            "REBOOT 命令会立即触发固件重启（NVIC_SystemReset）。"
        )
        info.setStyleSheet("color:#888; font-size:10px;")
        info.setWordWrap(True)
        wv.addWidget(info)
        wv.addStretch()
        return w

    def _build_payload_private_config(self) -> bytes:
        """构造 PRIVATE_CONFIG_APP (287) payload。"""
        import base64 as _b64
        try:
            from meshdebug.private_config_pb2 import (
                DeviceFactoryIdentity,
                encode_get_factory_identity,
                encode_set_factory_identity,
                encode_get_config,
                encode_get_network_config,
                encode_get_join_lock_advertise,
                encode_get_sync_wakeup,
                encode_get_info_labels,
                encode_join_network_v2,
                encode_gateway_announce,
                encode_channel12_config,
                encode_trusted_gateway_config,
                encode_set_sync_wakeup,
                encode_keep_awake,
                encode_set_admin_key,
                encode_set_device_name,
                encode_set_info_label,
                encode_set_company_key,
                encode_change_admin,
                encode_reset_config,
                encode_reset_network_config,
                encode_change_global_key,
                encode_change_company_key,
                encode_change_network_key,
                encode_enter_bootloader,
            )
        except Exception as exc:
            raise ValueError(f"private_config_pb2 未初始化: {exc}") from exc

        op = self.pc_op_combo.currentData()
        packet_label_id = _parse_optional_uint32(
            self.pc_sync_label_id_edit.text(),
            "PrivateConfigPacket.label_id",
        )
        if op in (
            "change_admin",
            "reset_config",
            "reset_network_config",
            "change_network_key",
            "change_company_key",
            "change_global_key",
        ):
            self._sync_private_config_target_node_fields()
        if op == "get_factory_identity":
            return encode_get_factory_identity()
        if op == "set_factory_identity":
            profile = self._collect_factory_identity_profile()
            self.to_edit.setText(profile["node_id"])
            try:
                merged = dict(self._factory_identity_profiles.get(profile["node_id"], {}))
                merged.update(profile)
                self._factory_identity_profiles[profile["node_id"]] = merged
                self._save_factory_identity_profiles()
                self._refresh_factory_identity_profile_combo(select_node_id=profile["node_id"])
                self._refresh_channel12_profile_combo(select_node_id=profile["node_id"])
                self._cache_join_lock_from_profile(profile["node_id"], merged, select=True)
                self._fill_join_v2_seed_from_profile(profile["node_id"])
                self.factory_profiles_changed.emit()
            except Exception as exc:
                self.log_result(False, f"自动保存 FactoryIdentity 档案失败: {exc}")
            identity = DeviceFactoryIdentity()
            identity.factory_version = profile["factory_version"]
            identity.sn = profile["sn"]
            dev_eui_hex = profile["dev_eui"]
            identity.dev_eui_hi = int(dev_eui_hex[:8], 16)
            identity.dev_eui_lo = int(dev_eui_hex[8:], 16)
            identity.device_private_key = _b64.b64decode(profile["device_private_key"])
            identity.legacy_app_key = _b64.b64decode(profile["legacy_app_key"])
            identity.manufacturing_timestamp = profile["manufacturing_timestamp"]
            identity.status = profile["status"]
            identity.identity_crc = 0
            return encode_set_factory_identity(identity)
        if op == "get_network_config":
            return encode_get_network_config()
        if op == "get_join_lock_advertise":
            return encode_get_join_lock_advertise()
        if op == "get_config":
            return encode_get_config()
        elif op == "get_sync_wakeup":
            return encode_get_sync_wakeup()
        elif op == "set_sync_wakeup":
            scheduled_slots = []
            if self.pc_strategy_combo.currentData() == 1:
                for enabled, start, end, interval, align in self.pc_sched_rows:
                    if enabled.isChecked():
                        scheduled_slots.append((
                            start.value(),
                            end.value(),
                            interval.value(),
                            align.value(),
                        ))
                if not scheduled_slots:
                    raise ValueError("STRATEGY_SCHEDULED 至少需要启用一个 time slot")
            return encode_set_sync_wakeup(
                enabled=self.pc_enabled_chk.isChecked(),
                interval_min=self.pc_interval_spin.value(),
                align_minute=self.pc_align_spin.value(),
                offset_sec=self.pc_offset_spin.value(),
                strategy=self.pc_strategy_combo.currentData(),
                scheduled_slots=scheduled_slots,
                scheduled_offset_sec=self.pc_offset_spin.value(),
                startup_delay_sec=self.pc_win_startup_spin.value(),
                random_delay_max_sec=self.pc_win_random_spin.value(),
                gateway_wait_sec=self.pc_win_gateway_spin.value(),
                final_wait_sec=self.pc_win_final_spin.value(),
                degraded_window_sec=self.pc_win_degraded_spin.value(),
                factory_window_sec=self.pc_win_factory_spin.value(),
                label_id=packet_label_id,
            )
        elif op == "keep_awake":
            return encode_keep_awake(
                duration_sec=self.pc_keep_duration_spin.value(),
                label_id=packet_label_id,
            )
        elif op == "network_access":
            raise ValueError("NetworkAccess 已删除，请使用 Join Network V2")
        elif op == "join_network_v2":
            node_id = self.pc_na_join_combo.currentData() or self.to_edit.text().strip()
            network_pub_b64 = self.pc_na_global_pub_edit.text().strip()
            seed_b64 = self.pc_jv2_seed_edit.text().strip()
            timestamp_str = self.pc_na_timestamp_edit.text().strip()
            auth_b64 = self.pc_na_sig_edit.text().strip()
            if not all([node_id, network_pub_b64, seed_b64, timestamp_str, auth_b64]):
                raise ValueError("JoinNetWorkV2 需要目标节点、network_public_key、network_seed、timestamp 和 auth_code；请先填充 JoinLock 并生成 AuthCode")
            target_node = f"!{_parse_required_node_id(node_id, 'JoinNetWorkV2 target node_id'):08x}"
            network_pub = _b64.b64decode(network_pub_b64)
            network_seed = _b64.b64decode(seed_b64)
            auth_code = _b64.b64decode(auth_b64)
            if len(network_pub) != 32:
                raise ValueError(f"network_public_key must be 32 bytes, got {len(network_pub)}")
            if not 16 <= len(network_seed) <= 32:
                raise ValueError(f"network_seed must be 16-32 bytes, got {len(network_seed)}")
            if len(auth_code) != 32:
                raise ValueError(f"auth_code must be 32 bytes, got {len(auth_code)}")
            self.to_edit.setText(target_node)
            self.channel_spin.setValue(0)
            self.want_ack_chk.setChecked(False)
            self._fill_join_v2_derived_channel12(network_seed, target_node, save=True)
            return encode_join_network_v2(
                network_public_key=network_pub,
                network_seed=network_seed,
                timestamp=int(timestamp_str),
                auth_code=auth_code,
            )
        elif op == "join_network_v2_gateway":
            seed_b64 = self.pc_jv2_seed_edit.text().strip()
            if not seed_b64:
                raise ValueError("Gateway JoinNetWorkV2 不需要 SN/AuthCode，只需要 network_seed；请先在 Network 密钥配置界面生成或加载 network_seed")
            network_seed = _b64.b64decode(seed_b64)
            if not 16 <= len(network_seed) <= 32:
                raise ValueError(f"network_seed must be 16-32 bytes, got {len(network_seed)}")
            gateway_node = self._gateway_join_v2_target_node()
            self.to_edit.setText(gateway_node)
            self.channel_spin.setValue(0)
            self.want_ack_chk.setChecked(False)
            self.want_resp_chk.setChecked(True)
            self._fill_join_v2_derived_channel12(network_seed, gateway_node, save=False)
            return encode_join_network_v2(
                network_public_key=bytes(32),
                network_seed=network_seed,
                timestamp=int(__import__("time").time()),
                auth_code=bytes(32),
            )
        elif op == "channel12_config":
            node_id, channel12 = self._collect_channel12_profile()
            self.to_edit.setText(node_id)
            self.channel_spin.setValue(channel12["send_channel"])
            self._save_channel12_profile_from_ui(auto=True)
            return encode_channel12_config(
                channel1_name=channel12["channel1_name"],
                psk1=_b64.b64decode(channel12["psk1"]),
                channel2_name=channel12["channel2_name"],
                psk2=_b64.b64decode(channel12["psk2"]),
            )
        elif op == "set_company_key":
            cpub_b64 = self.pc_cpub_edit.text().strip()
            gwpub_b64 = self.pc_gwpub_edit.text().strip()
            gwid_str = self.pc_gwid_edit.text().strip().lstrip("!")
            if not cpub_b64 or not gwpub_b64 or not gwid_str:
                raise ValueError("请填写 network_public_key、Gateway 公钥和 Gateway 节点ID")
            company_pub = _b64.b64decode(cpub_b64)
            gw_pub = _b64.b64decode(gwpub_b64)
            if len(company_pub) != 32:
                raise ValueError(f"network_public_key 解码后须为32字节，当前 {len(company_pub)} 字节")
            if len(gw_pub) != 32:
                raise ValueError(f"网关公钥解码后须为32字节，当前 {len(gw_pub)} 字节")
            return encode_set_company_key(
                company_pub=company_pub,
                gw_pub=gw_pub,
                gw_node_id=int(gwid_str, 16),
                timestamp=int(_time.time()),
            )
        elif op == "change_admin":
            newpub_b64 = self.pc_newgwpub_edit.text().strip()
            newid_str = self.pc_newgwid_edit.text().strip().lstrip("!")
            sig_b64 = self.pc_sig_edit.text().strip()
            if not newpub_b64 or not newid_str:
                raise ValueError("请填写新网关公钥和新网关节点ID")
            if not sig_b64:
                raise ValueError("请先点击[生成 auth_code]按钮生成 ChangeAdmin.auth_code")
            if self._pc_change_admin_timestamp is None:
                raise ValueError("请先点击[生成 auth_code]按钮（时间戳未记录）")
            new_gw_pub = _b64.b64decode(newpub_b64)
            if len(new_gw_pub) != 32:
                raise ValueError(f"新网关公钥解码后须为32字节，当前 {len(new_gw_pub)} 字节")
            sig = _b64.b64decode(sig_b64)
            if len(sig) != 32:
                raise ValueError(f"auth_code 须为32字节，当前 {len(sig)} 字节")
            return encode_change_admin(
                new_gw_pub=new_gw_pub,
                new_gw_node_id=int(newid_str, 16),
                timestamp=self._pc_change_admin_timestamp,
                auth_code=sig,
            )
        elif op in ("reset_config", "reset_network_config"):
            sig_b64 = self.pc_reset_sig_edit.text().strip()
            timestamp = self._pc_reset_timestamp or int(_time.time())
            sig = _b64.b64decode(sig_b64) if sig_b64 else b""
            if sig and len(sig) != 32:
                raise ValueError(f"auth_code 须为空或32字节，当前 {len(sig)} 字节")
            self._pc_reset_timestamp = timestamp
            return encode_reset_network_config(
                reset_type=self.pc_reset_type_combo.currentData(),
                timestamp=timestamp,
                auth_code=sig,
                label_id=packet_label_id,
            )
        elif op in ("change_network_key", "change_company_key", "change_global_key"):
            new_cpub_b64 = self.pc_new_cpub_edit.text().strip()
            new_seed_text = self.pc_new_seed_edit.text().strip()
            sig_b64 = self.pc_cck_sig_edit.text().strip()
            if not new_cpub_b64:
                raise ValueError("请填写新 network_public_key（Base64）")
            if not new_seed_text:
                raise ValueError("请填写 new_network_seed（Base64 或 Hex）")
            new_company_pub = _b64.b64decode(new_cpub_b64)
            new_network_seed = _decode_network_seed_bytes(new_seed_text, "new_network_seed")
            if len(new_company_pub) != 32:
                raise ValueError(f"新 network_public_key 解码后须为32字节，当前 {len(new_company_pub)} 字节")
            timestamp = self._pc_cck_timestamp or int(_time.time())
            sig = _b64.b64decode(sig_b64) if sig_b64 else b""
            if sig and len(sig) != 32:
                raise ValueError(f"auth_code 须为空或32字节，当前 {len(sig)} 字节")
            self._pc_cck_timestamp = timestamp
            return encode_change_network_key(
                new_network_public_key=new_company_pub,
                timestamp=timestamp,
                auth_code=sig,
                new_network_seed=new_network_seed,
                label_id=packet_label_id,
            )
        elif op == "trusted_gateway_config":
            action = self.pc_tgw_action_combo.currentData()
            kwargs = {
                "is_single_gateway": self.pc_tgw_single_chk.isChecked(),
                "get_list": action == "get",
            }
            if action in ("add", "remove"):
                node_text = self.pc_tgw_node_edit.text().strip()
                node_id = _parse_required_node_id(node_text, "trusted_gateway")
                if action == "add":
                    kwargs["add_gateway"] = node_id
                else:
                    kwargs["remove_gateway"] = node_id
            kwargs["label_id"] = packet_label_id
            return encode_trusted_gateway_config(**kwargs)
        elif op == "gateway_announce":
            network_pub_b64 = self.pc_ga_pub_edit.text().strip()
            network_seed_text = self.pc_ga_seed_edit.text().strip()
            auth_b64 = self.pc_ga_auth_edit.text().strip()
            if not network_pub_b64:
                raise ValueError("请填写 GatewayAnnounce network_public_key")
            network_pub = _b64.b64decode(network_pub_b64)
            if len(network_pub) != 32:
                raise ValueError(f"network_public_key must be 32 bytes, got {len(network_pub)}")
            auth_code = _b64.b64decode(auth_b64) if auth_b64 else b""
            if auth_code and len(auth_code) != 32:
                raise ValueError(f"auth_code must be 32 bytes, got {len(auth_code)}")
            network_seed = b"" if auth_code else _decode_network_seed_bytes(network_seed_text, "network_seed")
            self.to_edit.setText("!ffffffff")
            self.channel_spin.setValue(1)
            self.want_ack_chk.setChecked(False)
            self.want_resp_chk.setChecked(False)
            return encode_gateway_announce(
                network_public_key=network_pub,
                network_seed=network_seed,
                auth_code=auth_code,
                label_id=packet_label_id,
            )
        elif op == "enter_bootloader":
            auth_b64 = self.pc_boot_auth_edit.text().strip()
            auth_code = _b64.b64decode(auth_b64) if auth_b64 else b""
            if len(auth_code) > 32:
                raise ValueError(f"auth_code must be 0-32 bytes, got {len(auth_code)}")
            self.channel_spin.setValue(0)
            self.want_ack_chk.setChecked(False)
            self.want_resp_chk.setChecked(True)
            return encode_enter_bootloader(
                reason=self.pc_boot_reason_combo.currentData(),
                delay_ms=self.pc_boot_delay_spin.value(),
                auth_code=auth_code,
            )
        elif op == "get_info_labels":
            return encode_get_info_labels()
        elif op == "set_admin_key":
            ak_b64 = self.pc_ak_edit.text().strip()
            if not ak_b64:
                raise ValueError("请填写管理员公钥（Base64）")
            return encode_set_admin_key(admin_key=_b64.b64decode(ak_b64))
        elif op == "set_device_name":
            dn = self.pc_dn_edit.text().strip()
            if not dn:
                raise ValueError("请填写设备名")
            if len(dn.encode()) > 20:
                raise ValueError("设备名超过20字节限制")
            return encode_set_device_name(device_name=dn)
        elif op == "set_info_label":
            action = self.pc_sil_action_combo.currentData()
            lid = self.pc_sil_id_spin.value()
            key = self.pc_sil_key_edit.text().strip()
            val = self.pc_sil_val_edit.text().strip()
            if action != 2 and (not key or not val):
                raise ValueError("ADD/UPDATE 操作需要填写 key 和 value")
            if len(key.encode()) > 20 or len(val.encode()) > 20:
                raise ValueError("key/value 不能超过20字节")
            return encode_set_info_label(action=action, label_id=lid, key=key, value=val)
        raise ValueError(f"未知操作: {op}")

    def _build_payload_wakeup_comm(self) -> bytes:
        """构造 WAKEUP_COMM_APP (288) payload（1 字节命令）。"""
        cmd = self.wc_cmd_combo.currentData()
        return bytes([cmd])

    def _build_payload_nodeinfo(self) -> bytes:
        """构造 NODEINFO_APP payload（User）。"""
        import base64 as _base64
        user = mesh_pb2.User()
        user.id         = self.ni_id_edit.text().strip()
        user.long_name  = self.ni_long_edit.text()[:40]
        user.short_name = self.ni_short_edit.text()[:4]
        user.hw_model   = self.ni_hw_combo.currentData()
        user.is_licensed = self.ni_lic_chk.isChecked()
        user.role        = self.ni_role_combo.currentData()
        b64 = self.ni_pubkey_edit.text().strip()
        if b64:
            pk = _base64.b64decode(b64)
            if len(pk) != 32:
                raise ValueError(f"public_key 解码后须为 32 字节，当前 {len(pk)} 字节")
            user.public_key = pk
        return user.SerializeToString()

    def _build_payload_admin(self) -> bytes:
        """构造 ADMIN_APP payload（AdminMessage）。"""
        from meshtastic import admin_pb2
        entry = self.adm_op_combo.currentData()
        if entry is None:
            raise ValueError("请选择 AdminMessage 操作")
        _, field_name, input_type, _, _ = entry
        if field_name is None:
            raise ValueError("请选择具体操作（分隔符不可选）")

        msg = admin_pb2.AdminMessage()

        if input_type == 0:    # bool = True
            setattr(msg, field_name, True)
        elif input_type == 1:  # uint32
            if _is_admin_node_id_field(field_name):
                value = _parse_required_node_id(
                    self.adm_uint32_node_edit.text(),
                    "节点 ID",
                )
            else:
                value = self.adm_uint32_spin.value()
            setattr(msg, field_name, value)
        elif input_type == 2:  # int32
            setattr(msg, field_name, self.adm_int32_spin.value())
        elif input_type == 3:  # string
            setattr(msg, field_name, self.adm_str_edit.text())
        elif input_type == 4:  # ConfigType enum
            setattr(msg, field_name, self.adm_cfg_type_combo.currentData())
        elif input_type == 5:  # ModuleConfigType enum
            setattr(msg, field_name, self.adm_mod_type_combo.currentData())
        elif input_type == 6:  # set_owner → User
            user = mesh_pb2.User()
            user.id          = self.adm_own_id_edit.text().strip()
            user.long_name   = self.adm_own_long_edit.text()[:40]
            user.short_name  = self.adm_own_short_edit.text()[:4]
            user.hw_model    = self.adm_own_hw_combo.currentData()
            user.is_licensed = self.adm_own_lic_chk.isChecked()
            user.role        = self.adm_own_role_combo.currentData()
            msg.set_owner.CopyFrom(user)
        elif input_type == 7:  # set_channel → Channel
            import base64 as _base64
            from meshtastic import channel_pb2
            if self.adm_ch_idx_spin.value() == 0:
                raise ValueError("主信道(index=0)不可修改，请选择索引 1-7")
            ch = channel_pb2.Channel()
            ch.index = self.adm_ch_idx_spin.value()
            ch.role  = self.adm_ch_role_combo.currentData()
            ch.settings.name = self.adm_ch_name_edit.text()[:12]
            b64 = self.adm_ch_psk_edit.text().strip()
            if b64:
                psk_bytes = _base64.b64decode(b64)
                if len(psk_bytes) not in (0, 16, 32):
                    raise ValueError(f"PSK 解码后须为 0/16/32 字节，当前 {len(psk_bytes)} 字节")
                ch.settings.psk = psk_bytes
            ch.settings.uplink_enabled   = self.adm_ch_uplink_chk.isChecked()
            ch.settings.downlink_enabled = self.adm_ch_downlink_chk.isChecked()
            ch.settings.module_settings.position_precision = self.adm_ch_pos_prec_spin.value()
            ch.settings.module_settings.is_muted = self.adm_ch_is_muted_chk.isChecked()
            msg.set_channel.CopyFrom(ch)
        elif input_type == 8:  # set_config → 结构化表单
            import base64 as _base64
            from meshtastic import config_pb2
            from google.protobuf import json_format as _jf
            cfg = config_pb2.Config()
            cfg_type = self.adm_scfg_type_combo.currentData()
            if cfg_type == 5:  # LORA
                cfg.lora.use_preset    = self.scfg_lora_use_preset_chk.isChecked()
                cfg.lora.modem_preset  = self.scfg_lora_preset_combo.currentData()
                cfg.lora.region        = self.scfg_lora_region_combo.currentData()
                cfg.lora.hop_limit     = self.scfg_lora_hop_spin.value()
                cfg.lora.tx_enabled    = self.scfg_lora_tx_enabled_chk.isChecked()
                cfg.lora.tx_power      = self.scfg_lora_tx_power_spin.value()
                cfg.lora.channel_num   = self.scfg_lora_ch_num_spin.value()
                bw = self.scfg_lora_bw_spin.value()
                if bw:
                    cfg.lora.bandwidth = bw
                sf = self.scfg_lora_sf_spin.value()
                if sf:
                    cfg.lora.spread_factor = sf
                cfg.lora.override_duty_cycle = self.scfg_lora_duty_chk.isChecked()
                cfg.lora.config_ok_to_mqtt   = self.scfg_lora_ok_mqtt_chk.isChecked()
            elif cfg_type == 6:  # BLUETOOTH
                cfg.bluetooth.enabled   = self.scfg_bt_enabled_chk.isChecked()
                cfg.bluetooth.mode      = self.scfg_bt_mode_combo.currentData()
                cfg.bluetooth.fixed_pin = self.scfg_bt_pin_spin.value()
            elif cfg_type == 7:  # SECURITY
                b64 = self.scfg_sec_pubkey_edit.text().strip()
                if b64:
                    pk = _base64.b64decode(b64)
                    if len(pk) != 32:
                        raise ValueError(f"public_key 须为 32 字节，当前 {len(pk)}")
                    cfg.security.public_key = pk
                b64 = self.scfg_sec_privkey_edit.text().strip()
                if b64:
                    pk = _base64.b64decode(b64)
                    if len(pk) != 32:
                        raise ValueError(f"private_key 须为 32 字节，当前 {len(pk)}")
                    cfg.security.private_key = pk
                for edit in (self.scfg_sec_ak0_edit, self.scfg_sec_ak1_edit, self.scfg_sec_ak2_edit):
                    b64 = edit.text().strip()
                    if b64:
                        ak = _base64.b64decode(b64)
                        if len(ak) != 32:
                            raise ValueError(f"admin_key 须为 32 字节，当前 {len(ak)}")
                        cfg.security.admin_key.append(ak)
                cfg.security.is_managed            = self.scfg_sec_managed_chk.isChecked()
                cfg.security.serial_enabled        = self.scfg_sec_serial_chk.isChecked()
                cfg.security.admin_channel_enabled = self.scfg_sec_admin_ch_chk.isChecked()
            elif cfg_type == 8:  # SESSIONKEY — 只读
                raise ValueError("SESSIONKEY_CONFIG 为只读，无需手动设置")
            else:
                # JSON TextEdit 页（DEVICE/POSITION/POWER/NETWORK/DISPLAY/DEVICEUI）
                json_widgets = {
                    0: self.scfg_dev_json,
                    1: self.scfg_pos_json,
                    2: self.scfg_pwr_json,
                    3: self.scfg_net_json,
                    4: self.scfg_dsp_json,
                    9: self.scfg_dui_json,
                }
                te = json_widgets.get(cfg_type)
                txt = te.toPlainText().strip() if te else ""
                if txt:
                    _jf.Parse(txt, cfg)
            msg.set_config.CopyFrom(cfg)
        elif input_type == 9:  # set_module_config → ModuleConfig bytes hex
            from meshtastic import module_config_pb2
            raw = self.adm_smcfg_raw_edit.text().strip().replace(" ", "")
            mcfg = module_config_pb2.ModuleConfig()
            if raw:
                if len(raw) % 2 != 0:
                    raise ValueError("ModuleConfig hex 长度必须为偶数")
                mcfg.ParseFromString(bytes.fromhex(raw))
            msg.set_module_config.CopyFrom(mcfg)
        elif input_type == 10:  # set_ham_mode
            msg.set_ham_mode.call_sign  = self.adm_ham_call_edit.text()[:7]
            msg.set_ham_mode.frequency  = self.adm_ham_freq_spin.value()
            msg.set_ham_mode.tx_power   = self.adm_ham_power_spin.value()
            msg.set_ham_mode.short_name = self.adm_ham_short_edit.text()[:4]
        elif input_type == 11:  # set_fixed_position
            pos = mesh_pb2.Position()
            pos.latitude_i  = int(self.adm_pos_lat_spin.value() * 1e7)
            pos.longitude_i = int(self.adm_pos_lon_spin.value() * 1e7)
            pos.altitude    = self.adm_pos_alt_spin.value()
            pos.time        = self.adm_pos_time_spin.value()
            msg.set_fixed_position.CopyFrom(pos)
        elif input_type == 12:  # add_contact
            msg.add_contact.node_num          = _parse_required_node_id(
                self.adm_ct_node_edit.text(), "node_num"
            )
            msg.add_contact.should_ignore     = self.adm_ct_ignore_chk.isChecked()
            msg.add_contact.manually_verified = self.adm_ct_verified_chk.isChecked()
        elif input_type == 13:  # key_verification
            msg.key_verification.message_type   = self.adm_kv_type_combo.currentData()
            msg.key_verification.remote_nodenum = _parse_required_node_id(
                self.adm_kv_node_edit.text(), "remote_nodenum"
            )
            msg.key_verification.nonce          = self.adm_kv_nonce_spin.value()
            sec = self.adm_kv_secnum_spin.value()
            if sec:
                msg.key_verification.security_number = sec
        elif input_type == 14:  # BackupLocation
            setattr(msg, field_name, self.adm_backup_loc_combo.currentData())
        elif input_type == 15:  # send_input_event
            msg.send_input_event.event_code = self.adm_evt_code_spin.value()
            msg.send_input_event.kb_char    = self.adm_evt_kbchar_spin.value()
            msg.send_input_event.touch_x    = self.adm_evt_tx_spin.value()
            msg.send_input_event.touch_y    = self.adm_evt_ty_spin.value()

        # Session passkey（可选，8字节 = 16 hex字符）
        pk = self.adm_passkey_edit.text().strip().replace(" ", "")
        if pk:
            if len(pk) != 16:
                raise ValueError(f"Session Passkey 需 16 个 hex 字符（8字节），当前 {len(pk)} 个")
            msg.session_passkey = bytes.fromhex(pk)

        return msg.SerializeToString()

def _make_form_group(title: str) -> tuple[QGroupBox, QFormLayout]:
    """创建带 QFormLayout 的 GroupBox，返回 (group, form)。"""
    g = QGroupBox(title)
    g.setStyleSheet(_S_GROUP)
    f = QFormLayout(g)
    f.setContentsMargins(8, 4, 8, 6)
    f.setSpacing(5)
    f.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return g, f


def _row(widget: QWidget, suffix: str = "") -> QWidget:
    """将 widget + 可选单位标签包成一行 QWidget。"""
    if not suffix:
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return widget
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    h.addWidget(widget)
    lbl = QLabel(tr(suffix))
    lbl.setProperty("_i18n_source_text", suffix)
    lbl.setStyleSheet("color:#888; font-size:11px;")
    h.addWidget(lbl)
    h.addStretch()
    return w


def _parse_node_id(s: str) -> int:
    """
    节点 ID 字符串 → uint32。
    支持: !abcdef12 / abcdef12 / 4294967295 / 0xFFFFFFFF
    """
    s = s.strip().lstrip("!")
    if not s:
        return 0xFFFF_FFFF
    try:
        if s.lower().startswith("0x"):
            return int(s, 16) & 0xFFFF_FFFF
        if len(s) <= 8 and re.fullmatch(r"[0-9a-fA-F]+", s):
            return int(s, 16) & 0xFFFF_FFFF
        return int(s) & 0xFFFF_FFFF
    except ValueError:
        raise ValueError(f"无法解析节点 ID: {s!r}")


def _is_admin_node_id_field(field_name: Optional[str]) -> bool:
    """Whether an Admin uint32 field semantically carries a node ID."""
    return field_name in _ADMIN_NODE_ID_FIELDS


def _parse_required_node_id(s: str, field_label: str = "节点 ID") -> int:
    """Parse a required node ID field, rejecting empty or out-of-range input."""
    raw = s.strip()
    if not raw:
        raise ValueError(f"请填写 {field_label}")
    value_str = raw.lstrip("!")
    try:
        if value_str.lower().startswith("0x"):
            value = int(value_str, 16)
        elif len(value_str) <= 8 and re.fullmatch(r"[0-9a-fA-F]+", value_str):
            value = int(value_str, 16)
        else:
            value = int(value_str)
    except ValueError as exc:
        raise ValueError(f"无法解析 {field_label}: {raw!r}") from exc
    if not 0 <= value <= 0xFFFF_FFFF:
        raise ValueError(f"{field_label} 超出 uint32 范围: {raw}")
    return value


def _parse_optional_uint32(s: str, field_label: str) -> int:
    raw = s.strip()
    if not raw:
        return 0
    try:
        value = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 10)
    except ValueError as exc:
        raise ValueError(f"无法解析 {field_label}: {raw!r}") from exc
    if not 0 <= value <= 0xFFFF_FFFF:
        raise ValueError(f"{field_label} 超出 uint32 范围: {raw}")
    return value


def _calc_next_wakeup(interval_min: int, align_minute: int, offset_sec: int) -> str:
    """
    计算下次唤醒时间，算法与固件 TEWakeupScheduler::calcFixedWakeup() 一致。

    返回格式: "下次唤醒: HH:MM:SS（约 Xm Ys 后）"
    """
    from datetime import datetime as _dt
    now = _dt.now()
    today_sec = now.hour * 3600 + now.minute * 60 + now.second
    interval_sec = interval_min * 60
    align_sec = align_minute * 60

    next_align = align_sec
    while next_align <= today_sec:
        next_align += interval_sec

    sleep_sec = next_align - today_sec + offset_sec
    if sleep_sec < 1:
        sleep_sec += interval_sec

    import time as _t
    wake_ts = _t.time() + sleep_sec
    wake_dt = _dt.fromtimestamp(wake_ts)
    mins, secs = divmod(int(sleep_sec), 60)
    return f"下次唤醒: {wake_dt.strftime('%H:%M:%S')}（约 {mins}m {secs}s 后）"
