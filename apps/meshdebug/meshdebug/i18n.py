"""Lightweight runtime internationalization helpers for the PyQt UI."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QTableWidget,
    QTextEdit,
    QWidget,
)

LANG_ZH = "zh_CN"
LANG_EN = "en_US"
SUPPORTED_LANGUAGES = (LANG_ZH, LANG_EN)

_CURRENT_LANGUAGE = LANG_ZH
_SETTINGS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "meshdebug_settings.json")
)

_ORIGINAL_TEXT_ROLE = int(Qt.ItemDataRole.UserRole) + 1000
_ORIGINAL_PROPS = {
    "text": "_i18n_source_text",
    "title": "_i18n_source_title",
    "window_title": "_i18n_source_window_title",
    "placeholder": "_i18n_source_placeholder",
    "tooltip": "_i18n_source_tooltip",
    "status_tip": "_i18n_source_status_tip",
    "whats_this": "_i18n_source_whats_this",
}

_EXACT_EN: dict[str, str] = {
    "全部": "All",
    "时间": "Time",
    "类型": "Type",
    "摘要": "Summary",
    "串口:": "Port:",
    "波特率:": "Baud:",
    "过滤:": "Filter:",
    "语言:": "Language:",
    "中文": "Chinese",
    "自动滚动": "Auto scroll",
    "保存数据": "Save data",
    "自动时间同步": "Auto time sync",
    "刷新": "Refresh",
    "清空": "Clear",
    "清空日志": "Clear log",
    "保存": "Save",
    "复制 JSON": "Copy JSON",
    "复制 Hex": "Copy Hex",
    "复制ID": "Copy ID",
    "复制汇总": "Copy Summary",
    "导出汇总": "Export Summary",
    "生成/绑定Key": "Generate/Bind Key",
    "保存设备身份": "Save Device Identity",
    "清除Key": "Clear Key",
    "加载到发送": "Load to Send",
    "复制档案": "Copy Profile",
    "导出档案": "Export Profile",
    "删除档案": "Delete Profile",
    "清空全部": "Clear All",
    "节点: —": "Nodes: -",
    "帧数: 0": "Frames: 0",
    "保存: 关闭": "Capture: Off",
    "校时: 关闭": "Time Sync: Off",
    "校时: 待命": "Time Sync: Ready",
    "○  未连接": "○  Disconnected",
    "○  已断开": "○  Disconnected",
    "○ 未配置": "○ Not configured",
    "○ 未获取（发送任意 GET 后自动存储）": "○ Not captured (stored automatically after any GET response)",
    "— 点击左侧列表查看帧详情 —": "- Click a frame on the left to view details -",
    "串口文本日志": "Serial Text Log",
    "时间戳": "Timestamp",
    "发送日志": "Send Log",
    "发送日志…": "Send log...",
    "发送后自动显示已发包的 JSON 结构…": "The sent packet JSON structure appears here after sending...",
    "发送后自动显示帧原始字节…": "The raw sent frame bytes appear here after sending...",
    "串口连接后可发送": "Available after serial connection",
    "▶  发送": "▶  Send",
    "3 秒后发送入网请求": "Sending join request in 3 s",
    "▶ 连接": "▶ Connect",
    "■ 断开": "■ Disconnect",
    "📤 发送面板": "📤 Send Panel",
    "📋 节点列表": "📋 Node List",
    "🗂 档案管理": "🗂 Profile Manager",
    "🔑 Network 密钥": "🔑 Network Keys",
    "📋  串口日志": "📋  Serial Log",
    "📤  发送数据包": "📤  Send Packet",
    "Network 密钥配置": "Network Key Configuration",
    "Network 密钥（Meshtastic X25519）": "Network Keys (Meshtastic X25519)",
    "当前网关节点（串口连接节点）": "Current Gateway Node (serial-connected node)",
    "连接串口后自动读取，作为入网/改管理员的网关凭证": (
        "Read automatically after serial connection and used as gateway credentials for join/admin changes"
    ),
    "生成 Network 密钥对": "Generate Network Key Pair",
    "生成网络随机种子": "Generate Network Seed",
    "加载到入网签名页": "Load to Join Signing",
    "加载到改管理员页": "Load to Change Admin",
    "复制 Network 全量信息": "Copy Full Network Info",
    "主工具栏": "Main Toolbar",
    "串口日志": "Serial Log",
    "发送数据包": "Send Packet",
    "点击节点查看详情": "Click a node to view details",
    "选择一个本地档案查看详情": "Select a local profile to view details",
    "无保存档案": "No saved profile",
    "无保存信道配置": "No saved channel config",
    "无缓存 JoinLockAdvertise": "No cached JoinLockAdvertise",
    "操作类型": "Operation Type",
    "操作:": "Operation:",
    "高级选项（可选）": "Advanced Options (optional)",
    "跳数:": "Hops:",
    "自定义 From:": "Custom From:",
    "请求接收方回应（decoded.want_response）": "Ask receiver to respond (decoded.want_response)",
    "回复的原消息 Packet ID（0=不填）": "Original packet ID to reply to (0=unset)",
    "Emoji Unicode 码点（0=不填）": "Emoji Unicode code point (0=unset)",
    "构造包失败": "Packet build failed",
    "发送失败": "Send Failed",
    "错误": "Error",
    "未连接": "Not Connected",
    "未选择节点": "No Node Selected",
    "保存失败": "Save Failed",
    "加载失败": "Load Failed",
    "生成失败": "Generate Failed",
    "签名失败": "Signing Failed",
    "导出失败": "Export Failed",
    "已复制": "Copied",
    "已保存": "Saved",
    "已加载": "Loaded",
    "已生成": "Generated",
    "已导出": "Exported",
    "已删除": "Deleted",
    "已清空": "Cleared",
    "已清除": "Cleared",
    "确认删除": "Confirm Delete",
    "确认清除": "Confirm Clear",
    "确认清空": "Confirm Clear",
    "已有本地档案": "Existing Local Profile",
    "无档案": "No Profiles",
    "无本地档案": "No Local Profile",
    "缺少依赖库": "Missing Dependency",
    "缺少 network_seed": "Missing network_seed",
    "network_seed 错误": "network_seed Error",
    "导出 FactoryIdentity 档案": "Export FactoryIdentity Profile",
    "导出节点汇总": "Export Node Summary",
    "JSON (*.json);;Text (*.txt);;All Files (*)": "JSON (*.json);;Text (*.txt);;All Files (*)",
    "Markdown (*.md);;Text (*.txt);;All Files (*)": "Markdown (*.md);;Text (*.txt);;All Files (*)",
}

_EXACT_EN.update(
    {
        "🗑 清空": "🗑 Clear",
        "广播": "Broadcast",
        "填入 broadcast (!ffffffff)": "Fill broadcast (!ffffffff)",
        "— 已知节点 —": "- Known nodes -",
        "— 从已知节点选择 —": "- Select from known nodes -",
        "信道:": "Channel:",
        "RAW / 自定义 ...": "RAW / Custom ...",
        "消息内容": "Message Content",
        "网关命令 (Port 288)": "Gateway Command (Port 288)",
        "命令类型:": "Command Type:",
        "REQUEST_TELEMETRY (1) — 请求设备上报遥测": "REQUEST_TELEMETRY (1) - Request telemetry upload",
        "SET_CONFIG (2) — 下发配置": "SET_CONFIG (2) - Send config",
        "SYNC_TIME (3) — 时间同步": "SYNC_TIME (3) - Time sync",
        "REBOOT (4) — 重启设备": "REBOOT (4) - Reboot device",
        "说明：发送 1 字节命令至端口 288，设备在唤醒后监听此端口。\nREBOOT 命令会立即触发固件重启（NVIC_SystemReset）。": (
            "Sends a 1-byte command to port 288. The device listens on this port after wakeup.\n"
            "The REBOOT command immediately triggers firmware reboot (NVIC_SystemReset)."
        ),
        "Get Factory Identity（获取出厂身份）": "Get Factory Identity",
        "Set Factory Identity（写入出厂身份）": "Set Factory Identity",
        "Get Network Config（获取网络配置）": "Get Network Config",
        "Get Sync Wakeup（获取唤醒配置）": "Get Sync Wakeup",
        "Get Info Labels（获取标签列表）": "Get Info Labels",
        "Set Sync Wakeup Config（设置唤醒配置）": "Set Sync Wakeup Config",
        "Keep Awake（广播/定向长唤醒）": "Keep Awake",
        "Gateway Announce（广播第二网关）": "Gateway Announce",
        "Join Network V2（单包快速入网）": "Join Network V2",
        "Channel 1/2 Config（信道表）": "Channel 1/2 Config",
        "Set Info Label（添加/修改/删除标签）": "Set Info Label",
        "Change Admin（更换管理员）": "Change Admin",
        "Reset Network Config（网络重置）": "Reset Network Config",
        "Change Network Key（更换网络公钥）": "Change Network Key",
        "Trusted Gateway Config（可信网关）": "Trusted Gateway Config",
        "Enter Bootloader（进入 Bootloader）": "Enter Bootloader",
        "Set Sync Wakeup Config 参数": "Set Sync Wakeup Config Parameters",
        "enabled（启用同步唤醒）": "enabled (enable sync wakeup)",
        "STRATEGY_FIXED（固定间隔）": "STRATEGY_FIXED (fixed interval)",
        "STRATEGY_SCHEDULED（分时段）": "STRATEGY_SCHEDULED (scheduled slots)",
        "Fixed Wakeup 配置": "Fixed Wakeup Config",
        "唤醒间隔（分钟，1-1440）": "Wakeup interval (minutes, 1-1440)",
        "分钟": "min",
        "对齐分钟（0-59），使唤醒时刻对齐到该分钟": "Align minute (0-59), aligning wakeup time to that minute",
        "设备偏移秒数（0-3599），用于多设备错峰唤醒": "Device offset seconds (0-3599), for staggering multiple devices",
        "秒": "s",
        "Scheduled Wakeup 配置": "Scheduled Wakeup Config",
        "最多 4 个分时段；启用复选框的行会写入 scheduled_wakeup.time_slots。": (
            "Up to 4 time slots; rows with enabled checked are written to scheduled_wakeup.time_slots."
        ),
        "Wakeup Window 配置": "Wakeup Window Config",
        "保持 0 表示不在下发包中覆盖该窗口字段，由固件沿用/补默认值。": (
            "Keep 0 to avoid overriding that wakeup-window field; firmware keeps or fills defaults."
        ),
        "Set Factory Identity 参数（工厂固件写入）": "Set Factory Identity Parameters (factory firmware write)",
        "!aabbccdd（档案索引，建议填写目标节点ID）": "!aabbccdd (profile index; use target node ID)",
        "SN，最多20字节": "SN, up to 20 bytes",
        "16位十六进制，例如 A84041CC1F606353": "16 hex digits, for example A84041CC1F606353",
        "Base64 device_private_key（32字节，写入设备）": "Base64 device_private_key (32 bytes, written to device)",
        "LoRaWAN AppKey，Base64 或 32位Hex（16字节，写入设备）": "LoRaWAN AppKey, Base64 or 32 hex digits (16 bytes, written to device)",
        "Unix timestamp；留空则使用当前时间": "Unix timestamp; leave blank to use current time",
        "生成 Meshtastic X25519 device_private_key，并显示派生 device_public_key": (
            "Generate a Meshtastic X25519 device_private_key and show the derived device_public_key"
        ),
        "注意：正式固件会拒绝写入；只有 DRAGINO_FACTORY_FIRMWARE 且来自串口/手机方向的包才会写入 Flash。": (
            "Note: production firmware rejects writes; only DRAGINO_FACTORY_FIRMWARE writes Flash, "
            "and only for packets from serial/mobile direction."
        ),
        "Network Access 参数（入网邀请）": "Network Access Parameters (join invitation)",
        "Base64 device_private_key（32字节，用于生成 auth_code）": "Base64 device_private_key (32 bytes, used to generate auth_code)",
        "Base64 join_challenge（16字节，来自 JoinLockAdvertise）": "Base64 join_challenge (16 bytes, from JoinLockAdvertise)",
        "Base64 network_public_key（32字节）": "Base64 network_public_key (32 bytes)",
        "Base64 gateway_public_key（32字节）": "Base64 gateway_public_key (32 bytes)",
        "Base64 network_seed（从 Network 界面加载，16-32字节）": "Base64 network_seed (loaded from Network panel, 16-32 bytes)",
        "Unix timestamp；生成 auth_code 时自动填当前时间": "Unix timestamp; filled with current time when generating auth_code",
        "Base64 auth_code（32字节，点击生成）": "Base64 auth_code (32 bytes; click Generate)",
        "NetworkAccess 已移除": "NetworkAccess removed",
        "Gateway 模式不需要 SN/AuthCode；只需要 network_seed，发送时会自动使用空 auth_code。": (
            "Gateway mode does not need SN/AuthCode; only network_seed is required. "
            "An empty auth_code is used automatically when sending."
        ),
        "Channel 1/2 Config 参数": "Channel 1/2 Config Parameters",
        "!aabbccdd（保存档案索引）": "!aabbccdd (saved profile index)",
        "Channel12Config 发送时使用的 MeshPacket.channel，会随节点档案持久化": (
            "MeshPacket.channel used when sending Channel12Config; persisted with the node profile"
        ),
        "Channel 1 name（私有配置信道）": "Channel 1 name (private config channel)",
        "Base64 psk1（16-32字节）": "Base64 psk1 (16-32 bytes)",
        "Channel 2 name（业务/功能信道）": "Channel 2 name (business/function channel)",
        "Base64 psk2（16-32字节）": "Base64 psk2 (16-32 bytes)",
        "Set Global Key 参数（首次入网）": "Set Global Key Parameters (first join)",
        "Base64 network_public_key（32字节，legacy hidden）": "Base64 network_public_key (32 bytes, legacy hidden)",
        "Base64 Gateway 公钥（32字节）": "Base64 Gateway public key (32 bytes)",
        "时间戳自动取当前时间（无需填写）": "Timestamp uses current time automatically (no manual input needed)",
        "从 Network 身份 Dock 自动填入 network_public_key、Gateway 公钥和节点ID": (
            "Auto-fill network_public_key, Gateway public key and node ID from the Network Identity dock"
        ),
        "Change Admin 参数（更换管理员）": "Change Admin Parameters",
        "Base64 新网关公钥（32字节）": "Base64 new gateway public key (32 bytes)",
        "!aabbccdd（新网关节点ID）": "!aabbccdd (new gateway node ID)",
        "!aabbccdd（目标设备节点ID，用于签名绑定）": "!aabbccdd (target device node ID, used for signature binding)",
        "HMAC auth_code Base64（32字节，点击生成）": "HMAC auth_code Base64 (32 bytes; click Generate)",
        "将虚拟身份的公钥/节点ID填入新网关字段": "Fill virtual identity public key/node ID into the new gateway fields",
        "使用目标节点 device_private_key 生成 ChangeAdmin.auth_code": "Generate ChangeAdmin.auth_code using target node device_private_key",
        "Reset Network Config 参数（远程清除）": "Reset Network Config Parameters (remote clear)",
        "FACTORY（恢复出厂/默认配置）": "FACTORY (restore factory/default config)",
        "NETWORK（清除网络配置）": "NETWORK (clear network config)",
        "auth_code Base64（32字节；当前固件允许为空，空值自动补0）": (
            "auth_code Base64 (32 bytes; current firmware allows blank, blank auto-fills zeros)"
        ),
        "当前固件未校验 ResetNetworkConfig.auth_code；点击填充32字节0并记录时间戳": (
            "Current firmware does not verify ResetNetworkConfig.auth_code; click to fill 32 zero bytes and record timestamp"
        ),
        "Change Network Key 参数（更换网络公钥）": "Change Network Key Parameters",
        "Base64 新 network_public_key（32字节）": "Base64 new network_public_key (32 bytes)",
        "Base64 或 Hex new_network_seed（16-32字节）": "Base64 or Hex new_network_seed (16-32 bytes)",
        "生成 16 字节 new_network_seed": "Generate a 16-byte new_network_seed",
        "时间戳自动取当前时间；当前固件暂不校验 auth_code，留空会自动补 32 字节 0": (
            "Timestamp uses current time automatically; current firmware does not verify auth_code yet, "
            "and blank auto-fills 32 zero bytes"
        ),
        "当前固件未校验 ChangeNetworkKey.auth_code；点击填充32字节0并记录时间戳": (
            "Current firmware does not verify ChangeNetworkKey.auth_code; click to fill 32 zero bytes and record timestamp"
        ),
        "Trusted Gateway Config 参数": "Trusted Gateway Config Parameters",
        "GET_LIST（读取可信网关列表）": "GET_LIST (read trusted gateway list)",
        "ADD（添加可信网关）": "ADD (add trusted gateway)",
        "REMOVE（移除可信网关）": "REMOVE (remove trusted gateway)",
        "!aabbccdd（ADD/REMOVE 时填写）": "!aabbccdd (required for ADD/REMOVE)",
        "GET_LIST 会返回 NetWorkConfig；ADD/REMOVE 需要设备已入网且发送方具备配置权限。": (
            "GET_LIST returns NetWorkConfig; ADD/REMOVE requires the device to be joined and the sender to have config permission."
        ),
        "Gateway Announce 参数": "Gateway Announce Parameters",
        "Base64 或 Hex network_seed（16-32字节，仅用于生成 auth_code）": (
            "Base64 or Hex network_seed (16-32 bytes, only used to generate auth_code)"
        ),
        "auth_code Base64；留空则按 network_seed 自动生成": "auth_code Base64; leave blank to generate from network_seed automatically",
        "把 Join Network V2 的 network_seed 复制到 GatewayAnnounce": "Copy Join Network V2 network_seed into GatewayAnnounce",
        "GatewayAnnounce 必须以 broadcast 发送；meshdebug 会自动使用 !ffffffff、channel 1、无 ACK、无回包。": (
            "GatewayAnnounce must be sent as broadcast; meshdebug automatically uses !ffffffff, channel 1, no ACK and no response."
        ),
        "Keep Awake 参数": "Keep Awake Parameters",
        "0 表示取消当前长唤醒；常用 300 秒": "0 cancels the current keep-awake period; 300 seconds is commonly used",
        "广播长唤醒走 channel 1 且不回包；定向发送可保留响应，用于调试单节点。": (
            "Broadcast keep-awake uses channel 1 and returns no response; directed send can keep response for single-node debugging."
        ),
        "Set Admin Key 参数": "Set Admin Key Parameters",
        "Base64 管理员公钥（任意字节数）": "Base64 admin public key (any byte length)",
        "需要设备已入网且在私有配置信道或 PKI 加密发送": "Requires the device to be joined and sent on the private config channel or with PKI encryption",
        "Set Device Name 参数": "Set Device Name Parameters",
        "设备名（最多20字符）": "Device name (up to 20 chars)",
        "Set Info Label 参数": "Set Info Label Parameters",
        "ADD（新增标签）": "ADD (add label)",
        "UPDATE（更新标签）": "UPDATE (update label)",
        "DELETE（删除标签）": "DELETE (delete label)",
        "标签 ID（ADD/UPDATE/DELETE 均需要）": "Label ID (required for ADD/UPDATE/DELETE)",
        "键名（max 20 chars）": "Key (max 20 chars)",
        "值（max 20 chars）": "Value (max 20 chars)",
        "DELETE 只需填写 label_id，key/value 忽略": "DELETE only needs label_id; key/value are ignored",
        "每30分钟": "Every 30 min",
        "每1小时": "Every 1 hour",
        "每2小时": "Every 2 hours",
        "每3小时": "Every 3 hours",
        "AdminMessage 操作": "AdminMessage Operation",
        "操作类型:": "Operation Type:",
        "─── GET 请求 ─────────────────": "--- GET Requests ----------------",
        "─── SET 操作 ─────────────────": "--- SET Operations --------------",
        "─── 节点管理 ─────────────────": "--- Node Management -------------",
        "─── 设备控制 ─────────────────": "--- Device Control --------------",
        "Reboot (seconds, -1=取消)": "Reboot (seconds, -1=cancel)",
        "Shutdown (seconds, -1=取消)": "Shutdown (seconds, -1=cancel)",
        "─── 设置事务 ─────────────────": "--- Settings Transaction --------",
        "─── 其他 ──────────────────────": "--- Other -----------------------",
        "输入事件码 (uint8)": "Input event code (uint8)",
        "键盘字符码 (uint8)": "Keyboard character code (uint8)",
        "触摸 X 坐标 (uint16)": "Touch X coordinate (uint16)",
        "触摸 Y 坐标 (uint16)": "Touch Y coordinate (uint16)",
        "远端节点号，支持 hex 或十进制": "Remote node number, hex or decimal",
        "连接追踪 nonce (uint64，填低32位)": "Connection trace nonce (uint64; fill low 32 bits)",
        "security_number (0=不填):": "security_number (0=unset):",
        "4位安全码（0=不填）": "4-digit security code (0=unset)",
        "联系人节点号，支持 hex 或十进制": "Contact node number, hex or decimal",
        "should_ignore（加入屏蔽列表）": "should_ignore (add to ignored list)",
        "manually_verified（手动标记密钥已验证）": "manually_verified (mark key as verified)",
        "Set Fixed Position — 简化坐标": "Set Fixed Position - Simple Coordinates",
        "当前时间": "Current Time",
        "业余无线电呼号（max 7 字符）": "Amateur radio callsign (max 7 chars)",
        "LoRa 频率（Hz），如 915000000": "LoRa frequency (Hz), for example 915000000",
        "发射功率（dBm）": "TX power (dBm)",
        "节点短名（max 4 字符，可留空）": "Node short name (max 4 chars, optional)",
        "Set Module Config — 模块配置类型 + proto bytes": "Set Module Config - Module Config Type + proto bytes",
        "ModuleConfigType (参考):": "ModuleConfigType (reference):",
        "完整 ModuleConfig protobuf bytes（hex，可为空）": "Full ModuleConfig protobuf bytes (hex, optional)",
        "Set Config — 选择配置类型": "Set Config - Select Config Type",
        "📥 填充上次获取": "📥 Fill Last GET",
        "请先发送 Get Config 获取该节点配置": "Please send Get Config first to read this node's config",
        "DEVICEUI_CONFIG — 先 Get Config(DEVICEUI) 读取当前值，修改后填入。": (
            "DEVICEUI_CONFIG - Send Get Config(DEVICEUI) first, then edit and fill the current value."
        ),
        "DISPLAY_CONFIG — 先 Get Config(DISPLAY) 读取当前值，修改后填入。": (
            "DISPLAY_CONFIG - Send Get Config(DISPLAY) first, then edit and fill the current value."
        ),
        "NETWORK_CONFIG — 先 Get Config(NETWORK) 读取当前值，修改后填入。": (
            "NETWORK_CONFIG - Send Get Config(NETWORK) first, then edit and fill the current value."
        ),
        "POWER_CONFIG — 先 Get Config(POWER) 读取当前值，修改后填入。": (
            "POWER_CONFIG - Send Get Config(POWER) first, then edit and fill the current value."
        ),
        "POSITION_CONFIG — 先 Get Config(POSITION) 读取当前值，修改后填入。": (
            "POSITION_CONFIG - Send Get Config(POSITION) first, then edit and fill the current value."
        ),
        "DEVICE_CONFIG — 先 Get Config(DEVICE) 读取当前值，修改后填入。": (
            "DEVICE_CONFIG - Send Get Config(DEVICE) first, then edit and fill the current value."
        ),
        '{"key": value, ...}  (protobuf JSON 格式)': '{"key": value, ...} (protobuf JSON format)',
        "ℹ  SESSIONKEY_CONFIG 为只读，设备自动管理，无需手动设置。": (
            "ℹ SESSIONKEY_CONFIG is read-only and managed by the device; no manual setting is needed."
        ),
        "SECURITY_CONFIG 字段": "SECURITY_CONFIG Fields",
        "Base64（32字节），留空=不修改": "Base64 (32 bytes), blank = no change",
        "Base64（32字节），留空=不设置": "Base64 (32 bytes), blank = unset",
        "is_managed（托管模式，远程管理员控制）": "is_managed (managed mode, remote administrator control)",
        "serial_enabled（串口控制台）": "serial_enabled (serial console)",
        "admin_channel_enabled（允许通过信道管理）": "admin_channel_enabled (allow channel administration)",
        "BLUETOOTH_CONFIG 字段": "BLUETOOTH_CONFIG Fields",
        "enabled（启用蓝牙）": "enabled (enable Bluetooth)",
        "固定 PIN（mode=FIXED_PIN 时使用，6位数）": "Fixed PIN (used when mode=FIXED_PIN, 6 digits)",
        "LORA_CONFIG 字段": "LORA_CONFIG Fields",
        "use_preset（使用预设调制方案）": "use_preset (use preset modem settings)",
        "最大跳数（1-7）": "Max hops (1-7)",
        "tx_enabled（允许发射）": "tx_enabled (allow transmit)",
        "发射功率 dBm（0=最大值）": "TX power dBm (0=max)",
        "LoRa 信道编号（0=根据地区自动计算）": "LoRa channel number (0=auto by region)",
        "带宽 kHz（0=preset，常用：125/250/500）": "Bandwidth kHz (0=preset, common: 125/250/500)",
        "扩频因子（0=preset，有效范围 7-12）": "Spread factor (0=preset, valid range 7-12)",
        "override_duty_cycle（忽略占空比限制）": "override_duty_cycle (ignore duty-cycle limits)",
        "config_ok_to_mqtt（允许上传 MQTT）": "config_ok_to_mqtt (allow MQTT upload)",
        "Set Channel — Channel 字段": "Set Channel - Channel Fields",
        "信道索引 (0=主信道，不可修改；1-7=二级信道)": "Channel index (0=primary, read-only; 1-7=secondary channel)",
        "⚠ 主信道(index=0)只读，请选择索引 1-7！": "⚠ Primary channel (index=0) is read-only; select index 1-7.",
        "信道名称（max 12 字符）": "Channel name (max 12 chars)",
        "Base64 编码 PSK（16 or 32 字节），留空=使用默认 PSK": "Base64 PSK (16 or 32 bytes), blank = use default PSK",
        "Base64 字符串，解码后须为 0/16/32 字节": "Base64 string; after decoding must be 0/16/32 bytes",
        "uplink_enabled（上传 MQTT）": "uplink_enabled (upload to MQTT)",
        "downlink_enabled（下载 MQTT）": "downlink_enabled (download from MQTT)",
        "位置精度位数（0=不广播位置）": "Position precision bits (0=do not broadcast position)",
        "is_muted（静音该信道）": "is_muted (mute this channel)",
        "Set Owner — User 字段": "Set Owner - User Fields",
        "节点唯一 ID 字符串（格式 !xxxxxxxx）": "Unique node ID string (format !xxxxxxxx)",
        "is_licensed（持证业余无线电）": "is_licensed (licensed amateur radio)",
        "内容:": "Content:",
        "值 (int32):": "Value (int32):",
        "提示：reboot/shutdown 中 -1 表示取消": "Hint: -1 in reboot/shutdown means cancel",
        "值 (uint32):": "Value (uint32):",
        "✔  此操作无需额外参数（bool = True）": "✔ This operation needs no extra parameters (bool = True)",
        "Session Passkey（防重放，可选）": "Session Passkey (anti-replay, optional)",
        "16 hex 字符 = 8 字节，留空=自动注入": "16 hex chars = 8 bytes, blank = auto-inject",
        "收到 GET 响应后自动存储并注入（无需手动填写）\n手动填写可覆盖自动值，SET 命令需要有效 passkey，300秒内有效": (
            "Stored and injected automatically after a GET response (no manual input needed).\n"
            "Manual input overrides the automatic value. SET commands need a valid passkey, valid for 300 s."
        ),
        "长名（最多 40 字符）": "Long name (up to 40 chars)",
        "短名（最多 4 字符）": "Short name (up to 4 chars)",
        "硬件型号": "Hardware model",
        "is_licensed（持证业余无线电运营）": "is_licensed (licensed amateur radio operator)",
        "节点角色": "Node role",
        "Base64 公钥（32字节），留空=不设置": "Base64 public key (32 bytes), blank = unset",
        "Curve25519 公钥 Base64 编码（32字节），目标节点存入 NodeDB 后才能 PKI 加密通信": (
            "Curve25519 public key, Base64 encoded (32 bytes). The target node must store it in NodeDB before PKI encrypted communication works."
        ),
        "Unix 时间戳（秒）": "Unix timestamp (seconds)",
        "0–100 = 电量百分比；101 = 已接外部供电": "0-100 = battery percentage; 101 = external power connected",
        "实测电压（V）": "Measured voltage (V)",
        "当前信道占用率（%）": "Current channel utilization (%)",
        "过去一小时 TX 空口占用率（%）": "TX airtime utilization over the last hour (%)",
        "设备开机时长（秒）": "Device uptime (seconds)",
        "Payload Hex（空格分隔，如 0a 1b 2c…）:": "Payload Hex (space-separated, e.g. 0a 1b 2c...):",
        "例: 0a 04 48 65 6c 6c 6f": "Example: 0a 04 48 65 6c 6c 6f",
        "📍  基本坐标": "📍 Basic Coordinates",
        "纬度 latitude_i:": "Latitude latitude_i:",
        "度（×1e7 后存为 sfixed32）": "Degrees (stored as sfixed32 after x1e7)",
        "经度 longitude_i:": "Longitude longitude_i:",
        "海拔 altitude (MSL):": "Altitude altitude (MSL):",
        "海拔高度（MSL），单位 m": "Altitude (MSL), unit m",
        "椭球高 altitude_hae:": "Ellipsoid height altitude_hae:",
        "HAE 椭球面高度，单位 m": "HAE ellipsoid height, unit m",
        "大地分离 geoidal_sep:": "Geoidal separation geoidal_sep:",
        "大地水准面分离，单位 m": "Geoidal separation, unit m",
        "🕐  时间": "🕐 Time",
        "Unix 时间戳（秒），通常来自手机同步": "Unix timestamp (seconds), usually synchronized from phone",
        "填入当前时间": "Fill Current Time",
        "GPS 定位时刻的 Unix 时间戳（秒）": "Unix timestamp of GPS fix time (seconds)",
        "时间戳毫秒修正量": "Timestamp millisecond adjustment",
        "📡  精度与卫星": "📡 Accuracy and Satellites",
        "位置稀释度 PDOP，实际值 = 此值 × 0.01": "Position dilution PDOP, actual value = this value x 0.01",
        "水平稀释度 HDOP，实际值 = 此值 × 0.01": "Horizontal dilution HDOP, actual value = this value x 0.01",
        "垂直稀释度 VDOP，实际值 = 此值 × 0.01": "Vertical dilution VDOP, actual value = this value x 0.01",
        "GPS 硬件精度常数，单位 mm": "GPS hardware accuracy constant, unit mm",
        "GPS 定位质量（来自 GGA）": "GPS fix quality (from GGA)",
        "定位维数：2=2D  3=3D（来自 GSA）": "Fix dimensions: 2=2D 3=3D (from GSA)",
        "可见卫星数": "Satellites in view",
        "🚀  运动数据": "🚀 Motion Data",
        "地速，单位 cm/s（即 m/s × 100）": "Ground speed, unit cm/s (m/s x 100)",
        "真北航迹角，单位 1/100000°（即 度 × 100000）": "True-north track angle, unit 1/100000 degrees (degrees x 100000)",
        "⚙  来源与其他": "⚙ Source and Other",
        "多定位传感器时用于区分来源": "Used to distinguish sources when multiple positioning sensors exist",
        "预期的下次更新间隔（秒）": "Expected next update interval (seconds)",
        "坐标精度位数，32 = 完整精度": "Coordinate precision bits, 32 = full precision",
        "输入要发送的文本内容…": "Enter text content to send...",
        "0 = 自动随机生成": "0 = generate randomly",
        "在每行前面加上接收时间戳（设备日志自带时间时可关闭）": (
            "Prefix each line with receive timestamp (disable if device logs already include timestamps)"
        ),
        "Base64 network_private_key（32字节，仅本地保存）": "Base64 network_private_key (32 bytes, saved locally only)",
        "Base64 network_seed（16-32字节，网络级随机种子）": "Base64 network_seed (16-32 bytes, network-level random seed)",
        "● 已加载 virtual_identity.json": "● Loaded virtual_identity.json",
        "🔄 刷新": "🔄 Refresh",
        "📋 复制ID": "📋 Copy ID",
        "复制当前节点的 Meshtastic、Dragino、Network 和网关信息": "Copy Meshtastic, Dragino, Network and gateway info for the current node",
        "把当前节点汇总导出为 Markdown 文件": "Export the current node summary as a Markdown file",
        "为当前选中节点生成并保存 FactoryIdentity device_private_key 和 Join V2 seed": (
            "Generate and save FactoryIdentity device_private_key and Join V2 seed for the selected node"
        ),
        "把 Get Factory Identity 回来的 SN/DevEUI/device_private_key 保存到本地档案": (
            "Save SN/DevEUI/device_private_key returned by Get Factory Identity to a local profile"
        ),
        "清除当前选中节点的本地 FactoryIdentity 档案": "Clear the local FactoryIdentity profile for the selected node",
        "🗂  FactoryIdentity 档案管理": "🗂 FactoryIdentity Profile Manager",
        "选择一个本地档案查看详情": "Select a local profile to view details",
        "帧数: 0  |  0.0 帧/秒": "Frames: 0 | 0.0 fps",
        "📋 node列表": "📋 Node List",
        "收到远程node TELEMETRY payload 内的node RTC 时间later, 偏差超过 3 min时由gateway广播 286 time sync包": (
            "When a remote node RTC time is found in TELEMETRY payload, the gateway broadcasts port 286 time sync if drift exceeds 3 minutes"
        ),
        "鑺傜偣 ID 鏀寔 !aabbccdd銆乤abbccdd銆?0xaabbccdd 鎴栧崄杩涘埗": (
            "Node ID supports !aabbccdd, aabbccdd, 0xaabbccdd, or decimal"
        ),
    }
)

_PHRASE_EN: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            "MeshDebug — Meshtastic 串口调试工具": "MeshDebug - Meshtastic Serial Debug Tool",
            "刷新串口列表": "Refresh serial port list",
            "开启后把串口帧、串口文本和节点快照写入 apps/meshdebugdb": (
                "When enabled, serial frames, serial text and node snapshots are written to apps/meshdebugdb"
            ),
            "收到远程节点 TELEMETRY payload 内的节点 RTC 时间后，偏差超过 3 分钟时由网关广播 286 时间同步包": (
                "When a remote node RTC time is found in TELEMETRY payload, the gateway broadcasts port 286 time sync if drift exceeds 3 minutes"
            ),
            "自动生成 Meshtastic X25519 Network 密钥对": "Automatically generate a Meshtastic X25519 Network key pair",
            "生成 JoinNetWorkV2 使用的网络级 network_seed；同一个网络只应使用一份": (
                "Generate the network-level network_seed used by JoinNetWorkV2; use one seed per network"
            ),
            "将 network_public_key + 当前连接节点公钥填入 Private Config 入网表单": (
                "Fill network_public_key and the connected node public key into the Private Config join form"
            ),
            "将当前连接节点公钥/节点ID填入 Private Config 更换管理员表单": (
                "Fill the connected node public key/node ID into the Private Config Change Admin form"
            ),
            "复制 Network 公钥、私钥、network_seed 的 Base64/Hex，测试阶段用于共享给工程师": (
                "Copy Network public key, private key and network_seed as Base64/Hex for engineering-stage sharing"
            ),
            "发送任意 GET 后自动存储": "stored automatically after any GET response",
            "串口连接后可发送": "Available after serial connection",
            "JoinNetWorkV2: 已先发送 NodeInfo，3 秒后发送入网请求": (
                "JoinNetWorkV2: NodeInfo sent first; join request will be sent in 3 s"
            ),
            "本地档案，等待真实JoinLock": "local profile, waiting for real JoinLock",
            "真实JoinLock": "real JoinLock",
            "请先选择串口": "Please select a serial port",
            "保存失败": "Save failed",
            "写串口失败": "serial write failed",
            "发送失败": "send failed",
            "未连接": "not connected",
            "广播冷却": "broadcast cooldown",
            "冷却": "cooldown",
            "从已知节点选择": "Select from known nodes",
            "当前选中的是本地 FactoryIdentity 档案，不是真实 JoinLockAdvertise；请切到网关侧等待远端节点广播 JoinLock": (
                "The current selection is a local FactoryIdentity profile, not a real JoinLockAdvertise; switch to the gateway side and wait for the remote node to broadcast JoinLock"
            ),
            "设置唤醒配置": "set wakeup config",
            "获取唤醒配置": "get wakeup config",
            "广播/定向长唤醒": "broadcast/directed keep-awake",
            "广播第二网关": "broadcast secondary gateway",
            "单包快速入网": "single-packet fast join",
            "信道表": "channel table",
            "添加/修改/删除标签": "add/update/delete labels",
            "更换管理员": "change admin",
            "网络重置": "network reset",
            "更换网络公钥": "change network public key",
            "可信网关": "trusted gateway",
            "进入 Bootloader": "enter Bootloader",
            "获取出厂身份": "get factory identity",
            "写入出厂身份": "write factory identity",
            "获取网络配置": "get network config",
            "获取标签列表": "get label list",
            "出厂身份": "factory identity",
            "工厂固件写入": "factory firmware write",
            "远程清除": "remote clear",
            "首次入网": "first join",
            "入网邀请": "join invitation",
            "获取可信网关列表": "read trusted gateway list",
            "添加可信网关": "add trusted gateway",
            "移除可信网关": "remove trusted gateway",
            "请求设备上报遥测": "request telemetry upload",
            "下发配置": "send config",
            "时间同步": "time sync",
            "重启设备": "reboot device",
            "恢复出厂/默认配置": "factory/default config",
            "清除网络配置": "clear network config",
            "本地保存": "saved locally",
            "网络级随机种子": "network-level random seed",
            "串口连接节点": "serial-connected node",
            "网关凭证": "gateway credentials",
            "目标设备节点ID": "target device node ID",
            "新网关节点ID": "new gateway node ID",
            "新网关公钥": "new gateway public key",
            "管理员公钥": "admin public key",
            "设备名": "device name",
            "新增标签": "add label",
            "更新标签": "update label",
            "删除标签": "delete label",
            "标签 ID": "label ID",
            "键名": "key",
            "值": "value",
            "预设模板": "Presets",
            "关闭唤醒": "Disable Wakeup",
            "每30分钟": "Every 30 min",
            "每1小时": "Every 1 hour",
            "每2小时": "Every 2 hours",
            "每3小时": "Every 3 hours",
            "已禁用，不会唤醒": "disabled; no wakeup",
            "下次唤醒": "Next wakeup",
            "约": "about",
            "后": "later",
            "最多": "up to",
            "启用": "enable",
            "禁用": "disable",
            "自动填充": "Auto Fill",
            "加载档案": "Load Profile",
            "保存档案": "Save Profile",
            "生成 Device Key": "Generate Device Key",
            "填充 JoinLock": "Fill JoinLock",
            "派生信道": "Derive Channels",
            "生成 auth_code": "Generate auth_code",
            "生成 JoinNetWorkV2 AuthCode": "Generate JoinNetWorkV2 AuthCode",
            "填充空 auth_code": "Fill empty auth_code",
            "从虚拟身份填充": "Fill from virtual identity",
            "从 JoinV2 复制 seed": "Copy seed from JoinV2",
            "保留响应": "keep response",
            "用于调试单节点": "for single-node debugging",
            "正式固件会拒绝写入": "production firmware rejects writes",
            "点击生成": "click to generate",
            "自动取当前时间": "uses current time automatically",
            "无需填写": "no manual input needed",
            "留空": "leave blank",
            "自动补": "auto-fill",
            "不能为空": "cannot be empty",
            "不能超过": "must not exceed",
            "必须是": "must be",
            "必须为": "must be",
            "必须填写": "is required",
            "请填写": "Please enter",
            "请先": "Please",
            "请选择": "Please select",
            "解码后": "after decoding",
            "当前": "current",
            "字节": "bytes",
            "十六进制": "hex",
            "十进制": "decimal",
            "发送失败": "Send failed",
            "构造包失败": "Packet build failed",
            "解析错误": "Parse error",
            "解析失败": "parse failed",
            "导入失败": "import failed",
            "串口打开失败": "serial open failed",
            "串口异常断开": "serial disconnected unexpectedly",
            "串口未连接": "serial port is not connected",
            "串口已连接": "serial connected",
            "等待": "wait",
            "重连": "reconnect",
            "断线": "disconnected",
            "正在连接": "connecting to",
            "已连接": "connected",
            "已断开": "disconnected",
            "本机节点": "local node",
            "设备重启": "device rebooted",
            "队列": "queue",
            "针对包": "for packet",
            "自定义": "custom",
            "主信道": "primary channel",
            "文本内容": "text content",
            "铃声文本": "ringtone text",
            "节点管理": "node management",
            "设备控制": "device control",
            "设置事务": "settings transaction",
            "其他": "other",
            "请求": "request",
            "操作": "operation",
            "参数": "parameters",
            "配置": "config",
            "信道": "channel",
            "节点": "node",
            "帧": "frame",
            "日志": "log",
            "详情": "details",
            "密钥": "key",
            "公钥": "public key",
            "私钥": "private key",
            "网关": "gateway",
            "网络": "network",
            "档案": "profile",
            "发送": "send",
            "获取": "get",
            "写入": "write",
            "更换": "change",
            "清除": "clear",
            "删除": "delete",
            "加载": "load",
            "导出": "export",
            "复制": "copy",
            "生成": "generate",
            "保存": "save",
            "失败": "failed",
            "成功": "succeeded",
            "错误": "error",
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

_MESSAGEBOX_INSTALLED = False
_MESSAGEBOX_ORIGINALS: dict[str, Any] = {}
_FILEDIALOG_INSTALLED = False
_FILEDIALOG_ORIGINALS: dict[str, Any] = {}

_REGEX_EN: tuple[tuple[str, str], ...] = (
    (r"● 已生成 Network 密钥对（尚未保存）", "● Generated Network key pair (not saved)"),
    (r"● 已生成网络随机种子（尚未保存）", "● Generated network seed (not saved)"),
    (r"● 已保存到\s*(.+)", r"● Saved to \1"),
    (r"● 已加载\s*(.+)", r"● Loaded \1"),
    (r"节点:\s*(\d+)已入网\s*/\s*(\d+)未入网\s*/\s*(\d+)等待中\s*/\s*(\d+)未知\s*\|\s*(.*)", (
        r"Nodes: \1 joined / \2 not joined / \3 pending / \4 unknown | \5"
    )),
    (r"节点:\s*(\d+)已入网 / (\d+)未入网 / (\d+)等待中 / (\d+)未知(.*)", (
        r"Nodes: \1 joined / \2 not joined / \3 pending / \4 unknown\5"
    )),
    (r"帧数:\s*(\d+)\s*\|\s*([0-9.]+)\s*帧/秒", r"Frames: \1 | \2 fps"),
    (r"帧数:\s*(\d+)", r"Frames: \1"),
    (r"校时:\s*(.+)", r"Time Sync: \1"),
    (r"保存:\s*开\s*(.*)", r"Capture: On \1"),
    (r"已复制 Network 全量信息到剪贴板。", "Copied full Network info to clipboard."),
    (r"note: 测试阶段共享用，正式客户交付时不要明文外发 network_private_key。", (
        "note: for engineering-stage sharing only; do not send network_private_key in plaintext "
        "in customer releases."
    )),
    (r"note: 测试阶段共享用，正式客户交付时不要明文外发 network_private_key / device_private_key / legacy_app_key。", (
        "note: for engineering-stage sharing only; do not send network_private_key, "
        "device_private_key, or legacy_app_key in plaintext in customer releases."
    )),
    (r"本机节点\s*(![0-9A-Fa-f]{8})", r"local node \1"),
    (r"res=(.+?)\s+队列\s+(.+?)\s+针对包 id=(.+)", r"res=\1 queue \2 for packet id=\3"),
    (r"DeviceLabels \((\d+)条\):", r"DeviceLabels (\1):"),
    (r"DeviceLabels: 暂无标签", "DeviceLabels: no labels"),
    (r"PrivateConfig 响应:", "PrivateConfig response:"),
    (r"解析 PRIVATE_CONFIG 响应失败:\s*(.+)", r"Failed to parse PRIVATE_CONFIG response: \1"),
    (r"节点汇总已导出到:\s*(.+)", r"Node summary exported to:\n\1"),
    (r"节点汇总已导出到：\s*(.+)", r"Node summary exported to:\n\1"),
    (r"已复制\s+(.+?)\s+的节点汇总到剪贴板。", r"Copied node summary for \1 to the clipboard."),
    (r"已复制\s+(.+?)\s+的本地档案。", r"Copied local profile for \1."),
    (r"已加载\s+(.+?)\s+的档案到发送面板。", r"Loaded profile for \1 into the Send panel."),
    (r"已加载\s+(.+?)\s+的本地档案到发送面板。", r"Loaded local profile for \1 into the Send panel."),
    (r"已导出\s+(.+?)\s+的本地档案。", r"Exported local profile for \1."),
    (r"已删除\s+(.+?)\s+的本地档案。", r"Deleted local profile for \1."),
    (r"已清除\s+(.+?)\s+的本地 FactoryIdentity 档案。", r"Cleared local FactoryIdentity profile for \1."),
    (r"已把\s+(.+?)\s+的设备 FactoryIdentity 保存到本地档案。", (
        r"Saved device FactoryIdentity for \1 to the local profile."
    )),
    (r"没有找到\s+(.+?)\s+的本地档案。", r"No local profile was found for \1."),
    (r"(.+?)\s+当前没有保存的 FactoryIdentity 本地档案。", (
        r"\1 does not currently have a saved local FactoryIdentity profile."
    )),
    (r"确定删除\s+(.+?)\s+的本地 FactoryIdentity 档案吗\?\s*不会修改节点设备 Flash。", (
        r"Delete the local FactoryIdentity profile for \1?\n\nThis will not modify node Flash."
    )),
    (r"确定删除\s+(.+?)\s+的本地 FactoryIdentity 档案吗？\s*不会修改节点设备 Flash。", (
        r"Delete the local FactoryIdentity profile for \1?\n\nThis will not modify node Flash."
    )),
    (r"确定删除全部\s+(\d+)\s+个本地 FactoryIdentity 档案吗\?\s*不会修改任何节点设备 Flash。", (
        r"Delete all \1 local FactoryIdentity profiles?\n\nThis will not modify any node Flash."
    )),
    (r"确定删除全部\s+(\d+)\s+个本地 FactoryIdentity 档案吗？\s*不会修改任何节点设备 Flash。", (
        r"Delete all \1 local FactoryIdentity profiles?\n\nThis will not modify any node Flash."
    )),
    (r"确定清除\s+(.+?)\s+的本地 FactoryIdentity 档案吗\?\s*会删除 Debug 程序本地保存的 device_private_key、Join V2 seed 和 Channel1/2 派生配置。\s*不会修改节点设备 Flash，也不会删除节点列表中的 NodeInfo。", (
        r"Clear the local FactoryIdentity profile for \1?\n\nThis will delete the device_private_key, "
        r"Join V2 seed, and derived Channel1/2 config saved by this debug tool.\n"
        r"It will not modify node Flash or remove NodeInfo from the node list."
    )),
    (r"确定清除\s+(.+?)\s+的本地 FactoryIdentity 档案吗？\s*会删除 Debug 程序本地保存的 device_private_key、Join V2 seed 和 Channel1/2 派生配置。\s*不会修改节点设备 Flash，也不会删除节点列表中的 NodeInfo。", (
        r"Clear the local FactoryIdentity profile for \1?\n\nThis will delete the device_private_key, "
        r"Join V2 seed, and derived Channel1/2 config saved by this debug tool.\n"
        r"It will not modify node Flash or remove NodeInfo from the node list."
    )),
    (r"(.+?)\s+已有 FactoryIdentity 本地档案。\s*选择“是”会重新生成并覆盖该节点的 device_private_key 和 Join V2 seed。\s*选择“否”只加载已有档案到发送面板。", (
        r"\1 already has a local FactoryIdentity profile.\n\n"
        r"Choose Yes to regenerate and overwrite this node's device_private_key and Join V2 seed.\n"
        r"Choose No to only load the existing profile into the Send panel."
    )),
    (r"已为\s+(.+?)\s+生成并绑定 FactoryIdentity 本地档案。\s*切到发送面板后，收到该节点 JoinLock 时可直接使用“填充 JoinLock”。", (
        r"Generated and bound a local FactoryIdentity profile for \1.\n"
        r"After switching to the Send panel, Fill JoinLock can be used directly when this node's JoinLock is received."
    )),
    (r"请先在节点列表中选择一个节点。", "Select a node in the node list first."),
    (r"请先连接串口，获取本机节点信息后再加载入网表单。", (
        "Connect the serial port and read the local node info before loading the join form."
    )),
    (r"请先连接串口，获取本机节点信息后再加载改管理员表单。", (
        "Connect the serial port and read the local node info before loading the Change Admin form."
    )),
    (r"请先填入新网关公钥（Base64）", "Enter the new gateway public key (Base64) first."),
    (r"请先填入目标设备节点ID（!xxxxxxxx）", "Enter the target device node ID (!xxxxxxxx) first."),
    (r"请先填入新 network_public_key（Base64）", "Enter the new network_public_key (Base64) first."),
    (r"缺少目标节点 device_private_key 本地档案", "Missing local device_private_key profile for the target node"),
    (r"缺少当前 network_public_key", "Missing current network_public_key"),
    (r"请切换到 Join Network V2", "Switch to Join Network V2"),
    (r"缓存的 JoinLockAdvertise 不完整，请等待远端节点重新广播 JoinLock", (
        "Cached JoinLockAdvertise is incomplete; wait for the remote node to broadcast JoinLock again"
    )),
    (r"当前节点没有 Get Factory Identity 回包", "The current node has no Get Factory Identity response"),
    (r"设备回包没有 device_private_key，不能保存成可用于入网的档案", (
        "The device response has no device_private_key, so it cannot be saved as a profile usable for joining"
    )),
    (r"当前没有保存的 FactoryIdentity 档案。", "There are no saved FactoryIdentity profiles."),
    (r"已删除全部本地 FactoryIdentity 档案。", "Deleted all local FactoryIdentity profiles."),
    (r"已保存\s*", "Saved"),
    (r"已加载\s*", "Loaded"),
    (r"已复制\s*", "Copied"),
    (r"已导出\s*", "Exported"),
    (r"已删除\s*", "Deleted"),
    (r"已清除\s*", "Cleared"),
    (r"已生成\s*", "Generated"),
    (r"缺少 cryptography 库，请在运行本程序的 Python 环境中执行:\s*pip install cryptography\s*当前 Python:\s*(.+)", (
        r"Missing the cryptography package. Run this in the Python environment used by this program:\n\n"
        r"    pip install cryptography\n\nCurrent Python: \1"
    )),
    (r"缺少 cryptography 库，请在运行本程序的 Python 环境中执行：\s*pip install cryptography\s*当前 Python：\s*(.+)", (
        r"Missing the cryptography package. Run this in the Python environment used by this program:\n\n"
        r"    pip install cryptography\n\nCurrent Python: \1"
    )),
    (r"JoinNetWorkV2 需要先在网关侧收到远端节点真实 JoinLockAdvertise。\s*本地 FactoryIdentity 档案只保存 SN/EUI/私钥/network_seed，不能提供设备当前 join_challenge。\s*请确认远端节点未入网、已写入有效 FactoryIdentity，然后切到网关串口等待 JoinLock 广播。", (
        "JoinNetWorkV2 needs a real JoinLockAdvertise from the remote node on the gateway side.\n"
        "A local FactoryIdentity profile only stores SN/EUI/private key/network_seed and cannot provide the device's current join_challenge.\n"
        "Confirm the remote node is not joined and has a valid FactoryIdentity written, then switch to the gateway serial port and wait for the JoinLock broadcast."
    )),
    (r"当前选中的是本地 FactoryIdentity 档案，不是真实 JoinLockAdvertise。\s*JoinNetWorkV2 auth_code 必须使用远端节点运行时广播的 join_challenge；请切到网关串口，等收到该节点 JoinLock 后再生成 auth_code。", (
        "The current selection is a local FactoryIdentity profile, not a real JoinLockAdvertise.\n"
        "JoinNetWorkV2 auth_code must use the join_challenge broadcast by the remote node at runtime; switch to the gateway serial port and generate auth_code after this node's JoinLock is received."
    )),
    (r"本地档案缺少\s+(.+?)\s+的 device_private_key；不能生成 JoinNetWorkV2 auth_code。请先 Get/保存 FactoryIdentity，或在档案管理中为该节点补齐私钥。", (
        r"The local profile for \1 has no device_private_key, so JoinNetWorkV2 auth_code cannot be generated. "
        r"Get/save FactoryIdentity first, or fill the private key for this node in Profile Manager."
    )),
    (r"JoinNetWorkV2 需要 network_seed，请先在 Network 密钥配置界面生成/保存，并加载到入网签名页", (
        "JoinNetWorkV2 needs network_seed; generate/save it in Network Key Configuration and load it into the join signing page"
    )),
    (r"network_seed 必须为16-32字节，当前\s*(\d+)\s*字节", r"network_seed must be 16-32 bytes, got \1 bytes"),
    (r"device_private_key 必须为32字节，当前\s*(\d+)\s*字节", r"device_private_key must be 32 bytes, got \1 bytes"),
    (r"network_public_key 必须为32字节，当前\s*(\d+)\s*字节", r"network_public_key must be 32 bytes, got \1 bytes"),
    (r"gateway_public_key 必须为32字节，当前\s*(\d+)\s*字节", r"gateway_public_key must be 32 bytes, got \1 bytes"),
    (r"(.+?) 解码后必须为(\d+)-(\d+)字节，当前\s*(\d+)\s*字节", r"\1 must decode to \2-\3 bytes, got \4 bytes"),
    (r"(.+?) 解码后必须为(\d+)字节，当前\s*(\d+)\s*字节", r"\1 must decode to \2 bytes, got \3 bytes"),
    (r"(.+?) 解码后须为\s*(\d+)\s*字节，当前\s*(\d+)\s*字节", r"\1 must decode to \2 bytes, got \3 bytes"),
    (r"(.+?) 须为\s*(\d+)\s*字节，当前\s*(\d+)", r"\1 must be \2 bytes, got \3"),
    (r"(.+?) 须为空或(\d+)字节，当前\s*(\d+)\s*字节", r"\1 must be blank or \2 bytes, got \3 bytes"),
    (r"(.+?) 超出 uint32 范围:\s*(.+)", r"\1 is out of uint32 range: \2"),
    (r"无法解析节点 ID:\s*(.+)", r"Cannot parse node ID: \1"),
    (r"无法解析\s+(.+?):\s*(.+)", r"Cannot parse \1: \2"),
    (r"请填写\s+(.+)", r"Enter \1"),
    (r"请选择具体操作（分隔符不可选）", "Select a specific operation; separators cannot be selected"),
    (r"Set Factory Identity 需要\s+(.+)", r"Set Factory Identity requires \1"),
    (r"SN 不能超过20字节", "SN must not exceed 20 bytes"),
    (r"DevEUI 必须是16位十六进制数，例如 A84041CC1F606353", (
        "DevEUI must be 16 hex digits, for example A84041CC1F606353"
    )),
    (r"Channel12Config 需要 channel1/2 name 和 psk1/2", "Channel12Config needs channel1/2 name and psk1/2"),
    (r"节点\s+(.+?)\s+没有保存 Channel12 配置", r"Node \1 has no saved Channel12 config"),
    (r"已从节点档案自动填充 Channel12:\s*(.+)", r"Auto-filled Channel12 from node profile: \1"),
    (r"已保存 Channel12 配置:\s*(.+)", r"Saved Channel12 config: \1"),
    (r"保存 Channel12 配置失败:\s*(.+)", r"Failed to save Channel12 config: \1"),
    (r"自动填充 Channel12 失败:\s*(.+)", r"Failed to auto-fill Channel12: \1"),
    (r"已清除 FactoryIdentity 本地档案:\s*(.+)", r"Cleared local FactoryIdentity profile: \1"),
    (r"已保存 FactoryIdentity 档案:\s*(.+)", r"Saved FactoryIdentity profile: \1"),
    (r"保存 FactoryIdentity 档案失败:\s*(.+)", r"Failed to save FactoryIdentity profile: \1"),
    (r"加载 FactoryIdentity 档案失败:\s*(.+)", r"Failed to load FactoryIdentity profiles: \1"),
    (r"生成 Meshtastic device key 失败:\s*(.+)", r"Failed to generate Meshtastic device key: \1"),
    (r"已生成并绑定 FactoryIdentity 档案:\s*(.+)", r"Generated and bound FactoryIdentity profile: \1"),
    (r"已按当前 network_seed 派生 Channel 1/2", "Derived Channel 1/2 from the current network_seed"),
    (r"派生 Channel 1/2 失败，请先在 Global 界面生成并加载 network_seed:\s*(.+)", (
        r"Failed to derive Channel 1/2. Generate and load network_seed in the Global panel first: \1"
    )),
    (r"已生成 new_network_seed", "Generated new_network_seed"),
    (r"已填充 ResetNetworkConfig 空 auth_code", "Filled empty ResetNetworkConfig auth_code"),
    (r"已填充 ChangeNetworkKey 空 auth_code", "Filled empty ChangeNetworkKey auth_code"),
    (r"已从 JoinV2 区域复制 network_seed/network_public_key", "Copied network_seed/network_public_key from the JoinV2 section"),
    (r"已生成 GatewayAnnounce.auth_code", "Generated GatewayAnnounce.auth_code"),
    (r"生成 GatewayAnnounce.auth_code 失败:\s*(.+)", r"Failed to generate GatewayAnnounce.auth_code: \1"),
    (r"填充来自\s+(.+?)\s+的配置，(\d+)\s+秒前获取", r"Fill config from \1, captured \2 s ago"),
    (r"Gateway 模式无需 AuthCode", "Gateway mode does not need AuthCode"),
    (r"JoinNetWorkV2: 已先发送 NodeInfo，3 秒后发送入网请求", (
        "JoinNetWorkV2: NodeInfo sent first; join request will be sent in 3 s"
    )),
    (r"JoinNetWorkV2 前置 NodeInfo 需要填写网关节点 ID", "JoinNetWorkV2 preflight NodeInfo requires a gateway node ID"),
    (r"NetworkAccess 已删除，请使用 Join Network V2", "NetworkAccess has been removed; use Join Network V2"),
    (r"STRATEGY_SCHEDULED 至少需要启用一个 time slot", "STRATEGY_SCHEDULED needs at least one enabled time slot"),
    (r"Hex 长度必须为偶数", "Hex length must be even"),
    (r"Hex 包含非法字符:\s*(.+)", r"Hex contains invalid characters: \1"),
    (r"ModuleConfig hex 长度必须为偶数", "ModuleConfig hex length must be even"),
    (r"SESSIONKEY_CONFIG 为只读，无需手动设置", "SESSIONKEY_CONFIG is read-only; manual setting is not needed"),
    (r"设备名超过20字节限制", "Device name exceeds the 20-byte limit"),
    (r"ADD/UPDATE 操作需要填写 key 和 value", "ADD/UPDATE needs key and value"),
    (r"key/value 不能超过20字节", "key/value must not exceed 20 bytes"),
    (r"未知操作:\s*(.+)", r"Unknown operation: \1"),
    (r"public_key 须为 32 字节，当前\s*(\d+)", r"public_key must be 32 bytes, got \1"),
    (r"private_key 须为 32 字节，当前\s*(\d+)", r"private_key must be 32 bytes, got \1"),
    (r"admin_key 须为 32 字节，当前\s*(\d+)", r"admin_key must be 32 bytes, got \1"),
    (r"auth_code 须为32字节，当前\s*(\d+)\s*字节", r"auth_code must be 32 bytes, got \1 bytes"),
    (r"auth_code 须为空或32字节，当前\s*(\d+)\s*字节", r"auth_code must be blank or 32 bytes, got \1 bytes"),
    (r"PSK 解码后须为 0/16/32 字节，当前\s*(\d+)\s*字节", r"PSK must decode to 0/16/32 bytes, got \1 bytes"),
    (r"新网关公钥解码后须为32字节，当前\s*(\d+)\s*字节", r"new gateway public key must decode to 32 bytes, got \1 bytes"),
    (r"网关公钥解码后须为32字节，当前\s*(\d+)\s*字节", r"gateway public key must decode to 32 bytes, got \1 bytes"),
    (r"新 network_public_key 解码后须为32字节，当前\s*(\d+)\s*字节", r"new network_public_key must decode to 32 bytes, got \1 bytes"),
    (r"请填写 network_public_key、Gateway 公钥和 Gateway 节点ID", "Enter network_public_key, Gateway public key, and Gateway node ID"),
    (r"请填写新网关公钥和新网关节点ID", "Enter the new gateway public key and new gateway node ID"),
    (r"请先点击\[生成 auth_code\]按钮生成 ChangeAdmin.auth_code", "Click Generate auth_code first to generate ChangeAdmin.auth_code"),
    (r"请先点击\[生成 auth_code\]按钮（时间戳未记录）", "Click Generate auth_code first (timestamp not recorded)"),
    (r"请填写新 network_public_key（Base64）", "Enter the new network_public_key (Base64)"),
    (r"请填写 new_network_seed（Base64 或 Hex）", "Enter new_network_seed (Base64 or Hex)"),
    (r"请填写 GatewayAnnounce network_public_key", "Enter GatewayAnnounce network_public_key"),
    (r"请填写管理员公钥（Base64）", "Enter admin public key (Base64)"),
    (r"请填写设备名", "Enter device name"),
    (r"JoinNetWorkV2 需要目标节点、network_public_key、network_seed、timestamp 和 auth_code；请先填充 JoinLock 并生成 AuthCode", (
        "JoinNetWorkV2 needs target node, network_public_key, network_seed, timestamp, and auth_code; fill JoinLock and generate AuthCode first"
    )),
    (r"Gateway JoinNetWorkV2 不需要 SN/AuthCode，只需要 network_seed；请先在 Network 密钥配置界面生成或加载 network_seed", (
        "Gateway JoinNetWorkV2 does not need SN/AuthCode, only network_seed; generate or load network_seed in Network Key Configuration first"
    )),
    (r"private_config_pb2 未初始化:\s*(.+)", r"private_config_pb2 is not initialized: \1"),
    (r"自动保存 FactoryIdentity 档案失败:\s*(.+)", r"Failed to auto-save FactoryIdentity profile: \1"),
    (r"Session Passkey 需 16 个 hex 字符（8字节），当前\s*(\d+)\s*个", (
        r"Session Passkey needs 16 hex characters (8 bytes), got \1"
    )),
    (r"● 已自动存储(\s+\[[^\]]+\])?\s+(\d+)\s+字节\s+\(有效 ~270s\)", (
        r"● Automatically stored\1 \2 bytes (valid ~270s)"
    )),
    (r"Admin 命令被设备拒绝", "Admin command rejected by device"),
    (r"可能原因：设备处于托管模式 \(config\.security\.is_managed=true\)", (
        "Possible cause: device is in managed mode (config.security.is_managed=true)"
    )),
    (r"固件在 is_managed=true 时拒绝所有本地串口 Admin 命令，不返回任何响应。", (
        "When is_managed=true, firmware rejects all local serial Admin commands and returns no response."
    )),
    (r"解决方法：在官方 App → Settings → Security → 关闭 Managed Mode 后重试。", (
        "Fix: in the official app, go to Settings -> Security, disable Managed Mode, then retry."
    )),
    (r"下次唤醒:\s*(.+?)（约\s*(\d+)m\s*(\d+)s\s*后）", r"Next wakeup: \1 (about \2m \3s later)"),
    (r"写串口失败，请检查连接", "Serial write failed; check the connection"),
    (r"串口未连接", "Serial port is not connected"),
    (r"AUTO_TIME_SYNC 写串口失败", "AUTO_TIME_SYNC serial write failed"),
)


def get_language() -> str:
    return _CURRENT_LANGUAGE


def set_language(language: str) -> str:
    global _CURRENT_LANGUAGE
    _CURRENT_LANGUAGE = language if language in SUPPORTED_LANGUAGES else LANG_ZH
    return _CURRENT_LANGUAGE


def load_language(default: str = LANG_ZH) -> str:
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set_language(str(data.get("language") or default))
    except Exception:
        return set_language(default)


def save_language(language: str | None = None) -> None:
    lang = set_language(language or _CURRENT_LANGUAGE)
    data: dict[str, Any] = {}
    try:
        if os.path.exists(_SETTINGS_FILE):
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)
    except Exception:
        data = {}
    data["language"] = lang
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def tr(text: Any, language: str | None = None) -> Any:
    if not isinstance(text, str):
        return text
    lang = language or _CURRENT_LANGUAGE
    if lang == LANG_ZH or not text:
        return text
    return _to_english(text)


def _to_english(text: str) -> str:
    if text in _EXACT_EN:
        return _EXACT_EN[text]
    if not has_cjk(text):
        return text

    out = _translate_common_patterns(text)
    if out in _EXACT_EN:
        return _EXACT_EN[out]
    regex_out = _translate_regex_patterns(text)
    if regex_out != text:
        return regex_out
    for src, dst in _PHRASE_EN:
        out = out.replace(src, dst)
        if out in _EXACT_EN:
            return _EXACT_EN[out]

    out = _normalize_punctuation(out)
    regex_out = _translate_regex_patterns(out)
    if regex_out != out:
        return regex_out
    if out in _EXACT_EN:
        return _EXACT_EN[out]
    return out


def _translate_regex_patterns(text: str) -> str:
    normalized = _normalize_punctuation(text)
    candidates = (text, normalized) if normalized != text else (text,)
    for candidate in candidates:
        for pattern, repl in _REGEX_EN:
            if re.fullmatch(pattern, candidate, flags=re.DOTALL):
                return re.sub(pattern, repl, candidate, flags=re.DOTALL)
    return text


def _translate_common_patterns(text: str) -> str:
    replacements = [
        (r"(\d+)\s*行", r"\1 lines"),
        (r"(\d+)\s*秒", r"\1 s"),
        (r"(\d+)\s*分钟", r"\1 min"),
        (r"(\d+)\s*小时", r"\1 h"),
        (r"(\d+)\s*字节", r"\1 bytes"),
        (r"帧数:\s*(\d+)", r"Frames: \1"),
        (r"Frames:\s*(\d+)\s*\|\s*([0-9.]+)\s*帧/秒", r"Frames: \1 | \2 fps"),
        (r"帧数:\s*(\d+)\s*\|\s*([0-9.]+)\s*帧/秒", r"Frames: \1 | \2 fps"),
        (r"节点:\s*—", "Nodes: -"),
        (
            r"节点:\s*(\d+)已入网\s*/\s*(\d+)未入网\s*/\s*(\d+)等待中\s*/\s*(\d+)未知",
            r"Nodes: \1 joined / \2 not joined / \3 pending / \4 unknown",
        ),
        (r"保存:\s*开", "Capture: On"),
        (r"保存:\s*关闭", "Capture: Off"),
        (r"校时:\s*关闭", "Time Sync: Off"),
        (r"校时:\s*待命", "Time Sync: Ready"),
        (r"校时:\s*未连接", "Time Sync: Not connected"),
        (r"校时:\s*发送失败", "Time Sync: Send failed"),
        (r"校时:\s*广播冷却", "Time Sync: Broadcast cooldown"),
        (r"校时:\s*(.+?)\s*冷却", r"Time Sync: \1 cooldown"),
        (r"⏳\s*正在连接\s+(.+?)…?$", r"⏳ Connecting to \1..."),
        (r"●\s*已连接\s+(.+)$", r"● Connected \1"),
        (r"⏳\s*断线，(.+?)\s*后重连…?$", r"⏳ Disconnected, reconnecting in \1..."),
    ]
    out = text
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out)
    return out


def _normalize_punctuation(text: str) -> str:
    out = text
    out = out.replace("（", " (").replace("）", ")")
    out = out.replace("：", ": ")
    out = out.replace("，", ", ")
    out = out.replace("；", "; ")
    out = out.replace("。", ".")
    out = out.replace("、", "/")
    out = out.replace("→", "->")
    out = out.replace("—", "-")
    out = out.replace("…", "...")
    out = re.sub(r"\s+", " ", out)
    out = out.replace(" :", ":")
    return out.strip()


def _source_prop(widget: QWidget, key: str, current: str) -> str:
    prop_name = _ORIGINAL_PROPS[key]
    stored = widget.property(prop_name)
    if isinstance(stored, str):
        return stored
    widget.setProperty(prop_name, current)
    return current


def set_widget_text(widget: QWidget | None, text: str, language: str | None = None) -> None:
    if widget is None:
        return
    widget.setProperty(_ORIGINAL_PROPS["text"], text)
    setter = getattr(widget, "setText", None)
    if callable(setter):
        setter(tr(text, language))


def add_combo_item(combo: QComboBox, text: str, user_data: Any = None, language: str | None = None) -> None:
    combo.addItem(tr(text, language), user_data)
    combo.setItemData(combo.count() - 1, text, _ORIGINAL_TEXT_ROLE)


def set_combo_item_text(combo: QComboBox, index: int, text: str, language: str | None = None) -> None:
    if index < 0 or index >= combo.count():
        return
    combo.setItemData(index, text, _ORIGINAL_TEXT_ROLE)
    combo.setItemText(index, tr(text, language))


def translate_widget_tree(root: QWidget | None, language: str | None = None) -> None:
    if root is None:
        return
    lang = language or _CURRENT_LANGUAGE
    _translate_widget(root, lang)
    for child in root.findChildren(QWidget):
        _translate_widget(child, lang)


def _translate_widget(widget: QWidget, language: str) -> None:
    if bool(widget.property("_i18n_skip")):
        return

    tooltip = widget.toolTip()
    if tooltip:
        source = _source_prop(widget, "tooltip", tooltip)
        widget.setToolTip(tr(source, language))

    status_tip = widget.statusTip()
    if status_tip:
        source = _source_prop(widget, "status_tip", status_tip)
        widget.setStatusTip(tr(source, language))

    whats_this = widget.whatsThis()
    if whats_this:
        source = _source_prop(widget, "whats_this", whats_this)
        widget.setWhatsThis(tr(source, language))

    title = widget.windowTitle()
    if title:
        source = _source_prop(widget, "window_title", title)
        widget.setWindowTitle(tr(source, language))

    if isinstance(widget, QGroupBox):
        source = _source_prop(widget, "title", widget.title())
        widget.setTitle(tr(source, language))

    if isinstance(widget, QAbstractButton):
        source = _source_prop(widget, "text", widget.text())
        widget.setText(tr(source, language))
    elif isinstance(widget, QLabel):
        source = _source_prop(widget, "text", widget.text())
        widget.setText(tr(source, language))

    if isinstance(widget, QLineEdit):
        placeholder = widget.placeholderText()
        if placeholder:
            source = _source_prop(widget, "placeholder", placeholder)
            widget.setPlaceholderText(tr(source, language))
    elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
        placeholder = widget.placeholderText()
        if placeholder:
            source = _source_prop(widget, "placeholder", placeholder)
            widget.setPlaceholderText(tr(source, language))

    if isinstance(widget, QComboBox) and not bool(widget.property("_i18n_skip_items")):
        _translate_combo_items(widget, language)

    if isinstance(widget, QTabWidget):
        _translate_tabs(widget, language)

    if isinstance(widget, QTableWidget):
        _translate_table_headers(widget, language)


def _translate_combo_items(combo: QComboBox, language: str) -> None:
    current = combo.currentIndex()
    was_blocked = combo.blockSignals(True)
    try:
        for i in range(combo.count()):
            source = combo.itemData(i, _ORIGINAL_TEXT_ROLE)
            if not isinstance(source, str):
                source = combo.itemText(i)
                combo.setItemData(i, source, _ORIGINAL_TEXT_ROLE)
            combo.setItemText(i, tr(source, language))
    finally:
        combo.setCurrentIndex(current)
        combo.blockSignals(was_blocked)


def _translate_tabs(tabs: QTabWidget, language: str) -> None:
    for i in range(tabs.count()):
        page = tabs.widget(i)
        prop_name = f"_i18n_tab_text_{id(tabs)}"
        source = page.property(prop_name) if page is not None else None
        if not isinstance(source, str):
            source = tabs.tabText(i)
            if page is not None:
                page.setProperty(prop_name, source)
        tabs.setTabText(i, tr(source, language))


def _translate_table_headers(table: QTableWidget, language: str) -> None:
    for col in range(table.columnCount()):
        item = table.horizontalHeaderItem(col)
        if item is None:
            continue
        source = item.data(_ORIGINAL_TEXT_ROLE)
        if not isinstance(source, str):
            source = item.text()
            item.setData(_ORIGINAL_TEXT_ROLE, source)
        item.setText(tr(source, language))


def install_messagebox_i18n() -> None:
    global _MESSAGEBOX_INSTALLED
    if _MESSAGEBOX_INSTALLED:
        return

    def _wrap(name: str):
        original = getattr(QMessageBox, name)
        _MESSAGEBOX_ORIGINALS[name] = original

        def wrapped(parent, title, text, *args, **kwargs):
            for key in ("informativeText", "detailedText"):
                if key in kwargs:
                    kwargs[key] = tr(kwargs[key])
            return original(parent, tr(title), tr(text), *args, **kwargs)

        setattr(QMessageBox, name, wrapped)

    for method in ("information", "warning", "critical", "question"):
        _wrap(method)
    _MESSAGEBOX_INSTALLED = True


def install_filedialog_i18n() -> None:
    global _FILEDIALOG_INSTALLED
    if _FILEDIALOG_INSTALLED:
        return

    def _wrap(name: str):
        original = getattr(QFileDialog, name)
        _FILEDIALOG_ORIGINALS[name] = original

        def wrapped(parent, caption="", directory="", filter="", *args, **kwargs):
            return original(parent, tr(caption), directory, tr(filter), *args, **kwargs)

        setattr(QFileDialog, name, wrapped)

    for method in ("getSaveFileName", "getOpenFileName"):
        _wrap(method)
    _FILEDIALOG_INSTALLED = True
