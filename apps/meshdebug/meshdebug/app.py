"""
meshdebug/app.py
MainWindow：整合帧列表、详情面板、发送面板，管理串口连接生命周期。
"""

import base64
import logging
import json
import os
import random
import sys
import time
from collections import deque
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from meshdebug.serial_worker import SerialWorker, list_serial_ports
from meshdebug.capture_writer import CaptureWriter
from meshdebug.widgets.frame_table import FrameTable
from meshdebug.widgets.detail_panel import DetailPanel
from meshdebug.i18n import (
    LANG_EN,
    LANG_ZH,
    get_language,
    install_filedialog_i18n,
    install_messagebox_i18n,
    load_language,
    save_language,
    set_language,
    set_widget_text,
    tr,
    translate_widget_tree,
)
from meshdebug.widgets.send_panel import SendPanel
from meshdebug.widgets.serial_log_panel import SerialLogPanel
from meshtastic import mesh_pb2

logger = logging.getLogger(__name__)

BAUDRATES = ["115200", "9600", "57600", "230400", "460800", "921600"]
FILTER_OPTIONS = [
    ("全部", ""),
    ("packet", "packet"),
    ("node_info", "node_info"),
    ("my_info", "my_info"),
    ("config", "config"),
    ("channel", "channel"),
    ("moduleConfig", "moduleConfig"),
    ("rebooted", "rebooted"),
    ("config_complete_id", "config_complete_id"),
    ("log_record", "log_record"),
    ("queueStatus", "queueStatus"),
    ("metadata", "metadata"),
]

CUSTOM_TIMESYNC_PORTNUM = 286
TIME_SYNC_DRIFT_THRESHOLD_SEC = 180
TIME_SYNC_COOLDOWN_SEC = 10 * 60
TIME_SYNC_HOP_LIMIT = 7
TIME_SYNC_CHANNEL = 0


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MeshDebug — Meshtastic 串口调试工具")
        self.resize(1320, 800)

        self._apply_global_style()

        # 运行时状态
        self._worker: Optional[SerialWorker] = None
        self._nodes:  dict[str, dict]        = {}
        self._factory_identity_cache: dict[str, dict] = {}
        self._my_node_id: str                = ""   # 本机节点 hex，如 "!aabbccdd"
        self._frame_count = 0
        self._recent_ts: deque[float] = deque(maxlen=30)
        self._ni_suppress_send_sync = False
        self._capture = CaptureWriter()
        # 请求-响应追踪
        self._pending_requests: dict[int, dict] = {}  # packet.id → {summary, portnum}
        # Admin session passkey 表（按节点 ID 存储，支持多节点并行）
        # 格式：node_id → (passkey_bytes, monotonic_timestamp)
        self._admin_passkeys: dict = {}
        self._time_sync_last_sent_at: dict[str, float] = {}
        self._time_sync_last_status = "off"

        # Network 密钥配置（持久化到 virtual_identity.json）
        self._virtual_identity: dict = {
            "network_public_key":  b"",
            "network_private_key": b"",
            "network_seed":       b"",
        }

        self._build_toolbar()
        self._build_central()
        self._build_send_dock()
        self._build_serial_log_dock()
        self._build_virtual_identity_dock()
        self._build_node_info_dock()
        self._build_factory_profile_dock()
        self._build_statusbar()
        self._update_capture_status_label()

        # 每秒刷新帧速率显示
        self._rate_timer = QTimer(self)
        self._rate_timer.timeout.connect(self._update_rate)
        self._rate_timer.start(1000)

        # 串口心跳定时器（10分钟，防止固件 15 分钟超时断连）
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(10 * 60 * 1000)
        self._heartbeat_timer.timeout.connect(self._on_heartbeat)

        self._refresh_ports()
        # 自动加载虚拟身份（如果存在）
        self._load_virtual_identity(auto=True)
        # 连接 PKI 签名按钮
        self.send_panel.pc_gen_na_sig_btn.clicked.connect(self._on_gen_network_access_sig)
        self.send_panel.factory_profiles_changed.connect(self._on_factory_profiles_changed)
        self.send_panel.pc_gen_sig_btn.clicked.connect(self._on_gen_change_admin_sig)
        self.send_panel.pc_fill_enroll_btn.clicked.connect(self._vi_load_to_global)
        self.send_panel.pc_fill_change_btn.clicked.connect(self._vi_load_to_change_admin)
        self.send_panel.pc_gen_reset_sig_btn.clicked.connect(self._on_gen_reset_config_sig)
        self.send_panel.pc_gen_cck_sig_btn.clicked.connect(self._on_gen_change_global_key_sig)
        self._retranslate_ui()

    # ── 全局样式 ──────────────────────────────────────────────────────────────

    def _apply_global_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #1c1c1c; color: #dfe6e9;
            }
            QToolBar {
                background: #252525; border-bottom: 1px solid #3d3d3d;
                spacing: 6px; padding: 4px;
            }
            QComboBox {
                background: #2d2d2d; color: #dfe6e9;
                border: 1px solid #555; padding: 2px 6px;
                border-radius: 3px; min-width: 90px;
            }
            QComboBox QAbstractItemView {
                background: #2d2d2d; color: #dfe6e9;
            }
            QPushButton {
                background: #2d2d2d; color: #dfe6e9;
                border: 1px solid #555; padding: 4px 10px; border-radius: 3px;
            }
            QPushButton:hover  { background: #3d3d3d; }
            QPushButton:disabled { color: #555; }
            QStatusBar {
                background: #1c1c1c; color: #999;
                border-top: 1px solid #3d3d3d;
            }
            QDockWidget {
                titlebar-close-icon: none;
                color: #ccc; font-weight: bold;
            }
            QDockWidget::title {
                background: #252525; padding: 4px 8px;
                border-bottom: 1px solid #3d3d3d;
            }
            QGroupBox {
                border: 1px solid #3d3d3d; border-radius: 4px;
                margin-top: 6px; padding-top: 8px; color: #aaa;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 8px; padding: 0 4px;
            }
            QCheckBox { color: #aaa; }
            QLabel    { color: #ccc; }
        """)

    # ── 工具栏 ────────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        self.addToolBar(tb)

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet("color: #888; padding: 0 4px;")
            return l

        tb.addWidget(_lbl("串口:"))

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(130)
        tb.addWidget(self.port_combo)

        btn_refresh = QPushButton("↻")
        btn_refresh.setToolTip("刷新串口列表")
        btn_refresh.setFixedWidth(28)
        btn_refresh.clicked.connect(self._refresh_ports)
        tb.addWidget(btn_refresh)

        tb.addWidget(_lbl("波特率:"))

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUDRATES)
        self.baud_combo.setCurrentText("115200")
        tb.addWidget(self.baud_combo)

        tb.addSeparator()

        self.btn_connect = QPushButton("▶ 连接")
        self.btn_connect.setStyleSheet(
            "QPushButton { background:#1e4d2b; color:#6fcf97; border:1px solid #3d7a55; "
            "padding:4px 14px; border-radius:3px; font-weight:bold; }"
            "QPushButton:hover { background:#2a6b3d; }"
        )
        self.btn_connect.clicked.connect(self._on_connect)
        tb.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("■ 断开")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.setStyleSheet(
            "QPushButton { background:#4a1a1a; color:#ff8a80; border:1px solid #7a2a2a; "
            "padding:4px 14px; border-radius:3px; font-weight:bold; }"
            "QPushButton:hover { background:#6a2a2a; }"
            "QPushButton:disabled { background:#2d2d2d; color:#555; border-color:#444; }"
        )
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        tb.addWidget(self.btn_disconnect)

        tb.addSeparator()

        tb.addWidget(_lbl("过滤:"))
        self.filter_combo = QComboBox()
        for label, value in FILTER_OPTIONS:
            self.filter_combo.addItem(label, value)
        self.filter_combo.setMinimumWidth(140)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        tb.addWidget(self.filter_combo)

        tb.addSeparator()

        tb.addWidget(_lbl("语言:"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", LANG_ZH)
        self.language_combo.addItem("English", LANG_EN)
        self.language_combo.setMinimumWidth(105)
        lang_index = self.language_combo.findData(get_language())
        if lang_index >= 0:
            self.language_combo.setCurrentIndex(lang_index)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        tb.addWidget(self.language_combo)

        tb.addSeparator()

        btn_clear = QPushButton("🗑 清空")
        btn_clear.clicked.connect(self._clear_all)
        tb.addWidget(btn_clear)

        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        tb.addWidget(self.chk_autoscroll)

        self.chk_capture = QCheckBox("保存数据")
        self.chk_capture.setToolTip("开启后把串口帧、串口文本和节点快照写入 apps/meshdebugdb")
        self.chk_capture.toggled.connect(self._on_capture_toggled)
        tb.addWidget(self.chk_capture)

        self.chk_auto_time_sync = QCheckBox("自动时间同步")
        self.chk_auto_time_sync.setToolTip(
            "收到远程节点 TELEMETRY payload 内的节点 RTC 时间后，偏差超过 3 分钟时由网关广播 286 时间同步包"
        )
        self.chk_auto_time_sync.toggled.connect(self._on_auto_time_sync_toggled)
        tb.addWidget(self.chk_auto_time_sync)

        tb.addSeparator()

        self.btn_toggle_send = QPushButton("📤 发送面板")
        self.btn_toggle_send.setCheckable(True)
        self.btn_toggle_send.setChecked(False)
        self.btn_toggle_send.setStyleSheet(
            "QPushButton { background:#2d2d2d; color:#ffd580; border:1px solid #666; "
            "padding:4px 12px; border-radius:3px; }"
            "QPushButton:checked { background:#4a3200; border-color:#ffc940; }"
            "QPushButton:hover   { background:#3d3d3d; }"
        )
        self.btn_toggle_send.toggled.connect(self._toggle_send_dock)
        tb.addWidget(self.btn_toggle_send)

        self.btn_toggle_vi = QPushButton("🔑 Network 密钥")
        self.btn_toggle_vi.setCheckable(True)
        self.btn_toggle_vi.setChecked(False)
        self.btn_toggle_vi.setStyleSheet(
            "QPushButton { background:#2d2d2d; color:#a8d8ea; border:1px solid #666; "
            "padding:4px 12px; border-radius:3px; }"
            "QPushButton:checked { background:#1a3040; border-color:#56ccf2; }"
            "QPushButton:hover   { background:#3d3d3d; }"
        )
        self.btn_toggle_vi.toggled.connect(
            lambda checked: self._vi_dock.setVisible(checked) if hasattr(self, "_vi_dock") else None
        )
        tb.addWidget(self.btn_toggle_vi)

        self.btn_toggle_ni = QPushButton("📋 节点列表")
        self.btn_toggle_ni.setCheckable(True)
        self.btn_toggle_ni.setChecked(True)
        self.btn_toggle_ni.toggled.connect(
            lambda checked: self._ni_dock.setVisible(checked) if hasattr(self, "_ni_dock") else None
        )
        tb.addWidget(self.btn_toggle_ni)

        self.btn_toggle_fp = QPushButton("🗂 档案管理")
        self.btn_toggle_fp.setCheckable(True)
        self.btn_toggle_fp.setChecked(False)
        self.btn_toggle_fp.toggled.connect(
            lambda checked: self._fp_dock.setVisible(checked) if hasattr(self, "_fp_dock") else None
        )
        tb.addWidget(self.btn_toggle_fp)

    def _on_filter_changed(self, index: int):
        variant = self.filter_combo.itemData(index) or ""
        if hasattr(self, "frame_table"):
            self.frame_table.set_filter(variant)

    def _on_language_changed(self, index: int):
        lang = self.language_combo.itemData(index) or LANG_ZH
        set_language(lang)
        save_language(lang)
        self._retranslate_ui()

    def _retranslate_ui(self):
        self.setProperty("_i18n_source_window_title", "MeshDebug — Meshtastic 串口调试工具")
        self.setWindowTitle(tr("MeshDebug — Meshtastic 串口调试工具"))
        translate_widget_tree(self)
        self._update_capture_status_label()
        self._update_time_sync_status_label()
        self._refresh_nodes_status()
        if hasattr(self, "frame_table"):
            self.frame_table.retranslate()
        if hasattr(self, "detail_panel"):
            self.detail_panel.retranslate()
        if hasattr(self, "_refresh_node_info_dock"):
            self._refresh_node_info_dock()
        if hasattr(self, "_refresh_factory_profile_dock"):
            self._refresh_factory_profile_dock()
        self._update_rate()

    # ── 中央区域 ──────────────────────────────────────────────────────────────

    def _build_central(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #3d3d3d; width: 3px; }"
        )

        self.frame_table = FrameTable()
        self.detail_panel = DetailPanel()
        self.frame_table.frame_selected.connect(self.detail_panel.show_frame)

        splitter.addWidget(self.frame_table)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([700, 580])

        self.setCentralWidget(splitter)

    # ── 发送面板 Dock ──────────────────────────────────────────────────────────

    def _build_send_dock(self):
        self.send_panel = SendPanel()
        self.send_panel.send_requested.connect(self._on_send_requested)

        self._send_dock = QDockWidget("📤  发送数据包", self)
        self._send_dock.setWidget(self.send_panel)
        self._send_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self._send_dock.setMinimumHeight(220)
        self._send_dock.setVisible(False)
        self._send_dock.visibilityChanged.connect(
            lambda v: self.btn_toggle_send.setChecked(v)
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._send_dock)

    def _build_serial_log_dock(self):
        self._serial_log = SerialLogPanel()

        self._log_dock = QDockWidget("📋  串口日志", self)
        self._log_dock.setWidget(self._serial_log)
        self._log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._log_dock.setMinimumHeight(120)
        # 独立放置，不与发送面板 tabify（避免干扰发送面板的 visibilityChanged 信号）
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)


    # ── 虚拟管理员身份 Dock ────────────────────────────────────────────────────

    def _build_virtual_identity_dock(self):
        """创建虚拟管理员节点身份配置 Dock。"""
        _S_GRP = (
            "QGroupBox { border:1px solid #3d3d3d; border-radius:4px; "
            "margin-top:6px; padding-top:8px; color:#aaa; }"
            "QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }"
        )
        _S_INP = """
            QLineEdit, QComboBox {
                background:#252525; color:#dfe6e9; border:1px solid #555;
                padding:3px 6px; border-radius:3px;
            }
            QLineEdit:focus, QComboBox:focus { border-color:#56ccf2; }
        """
        _S_BTN = (
            "QPushButton { background:#2d2d2d; color:#ccc; border:1px solid #555; "
            "padding:4px 10px; border-radius:3px; }"
            "QPushButton:hover { background:#3d3d3d; }"
        )
        _S_SAVE = (
            "QPushButton { background:#1e4d2b; color:#6fcf97; border:1px solid #3d7a55; "
            "padding:4px 12px; border-radius:3px; font-weight:bold; }"
            "QPushButton:hover { background:#2a6b3d; }"
        )

        w = QWidget()
        w.setStyleSheet(_S_INP)
        root = QVBoxLayout(w)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        grp = QGroupBox("Network 密钥（Meshtastic X25519）")
        grp.setStyleSheet(_S_GRP)
        form = QFormLayout(grp)
        form.setContentsMargins(8, 4, 8, 8)
        form.setSpacing(5)

        from PyQt6.QtGui import QFont as _QFont
        self.vi_cpub_edit = QLineEdit()
        self.vi_cpub_edit.setPlaceholderText("Base64 network_public_key（32字节）")
        self.vi_cpub_edit.setFont(_QFont("Consolas", 9))
        form.addRow("network_pub (Base64):", self.vi_cpub_edit)

        self.vi_cpriv_edit = QLineEdit()
        self.vi_cpriv_edit.setPlaceholderText("Base64 network_private_key（32字节，仅本地保存）")
        self.vi_cpriv_edit.setFont(_QFont("Consolas", 9))
        self.vi_cpriv_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        form.addRow("network_priv (Base64):", self.vi_cpriv_edit)

        self.vi_network_seed_edit = QLineEdit()
        self.vi_network_seed_edit.setPlaceholderText("Base64 network_seed（16-32字节，网络级随机种子）")
        self.vi_network_seed_edit.setFont(_QFont("Consolas", 9))
        form.addRow("network_seed (Base64):", self.vi_network_seed_edit)

        root.addWidget(grp)

        # 当前网关节点信息（只读，来自串口连接节点）
        gw_grp = QGroupBox("当前网关节点（串口连接节点）")
        gw_grp.setStyleSheet(_S_GRP)
        gw_form = QFormLayout(gw_grp)
        gw_form.setContentsMargins(8, 4, 8, 8)
        gw_form.setSpacing(4)

        self.vi_gw_id_lbl = QLabel("—")
        self.vi_gw_id_lbl.setStyleSheet("color:#8cc8f0; font-family:Consolas; font-size:10px;")
        gw_form.addRow("node_id:", self.vi_gw_id_lbl)

        self.vi_gw_pub_lbl = QLabel("—")
        self.vi_gw_pub_lbl.setStyleSheet("color:#8cc8f0; font-family:Consolas; font-size:9px;")
        self.vi_gw_pub_lbl.setWordWrap(True)
        gw_form.addRow("public_key:", self.vi_gw_pub_lbl)

        gw_note = QLabel("连接串口后自动读取，作为入网/改管理员的网关凭证")
        gw_note.setStyleSheet("color:#666; font-size:10px;")
        gw_note.setWordWrap(True)
        gw_form.addRow(gw_note)

        root.addWidget(gw_grp)

        # 状态标签
        self.vi_status_lbl = QLabel("○ 未配置")
        self.vi_status_lbl.setStyleSheet("color:#888; font-size:10px;")
        root.addWidget(self.vi_status_lbl)

        # 按钮行 1：密钥生成
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_gen_company = QPushButton("生成 Network 密钥对")
        btn_gen_company.setStyleSheet(_S_BTN)
        btn_gen_company.setToolTip("自动生成 Meshtastic X25519 Network 密钥对")
        btn_gen_company.clicked.connect(self._vi_generate_global_keypair)
        btn_row.addWidget(btn_gen_company)

        btn_gen_seed = QPushButton("生成网络随机种子")
        btn_gen_seed.setStyleSheet(_S_BTN)
        btn_gen_seed.setToolTip("生成 JoinNetWorkV2 使用的网络级 network_seed；同一个网络只应使用一份")
        btn_gen_seed.clicked.connect(self._vi_generate_network_seed)
        btn_row.addWidget(btn_gen_seed)

        root.addLayout(btn_row)

        # 按钮行 2：加载到发送页
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(6)

        btn_load_enroll = QPushButton("加载到入网签名页")
        btn_load_enroll.setStyleSheet(_S_BTN)
        btn_load_enroll.setToolTip("将 network_public_key + 当前连接节点公钥填入 Private Config 入网表单")
        btn_load_enroll.clicked.connect(self._vi_load_to_global)
        btn_row2.addWidget(btn_load_enroll)

        btn_load_change = QPushButton("加载到改管理员页")
        btn_load_change.setStyleSheet(_S_BTN)
        btn_load_change.setToolTip("将当前连接节点公钥/节点ID填入 Private Config 更换管理员表单")
        btn_load_change.clicked.connect(self._vi_load_to_change_admin)
        btn_row2.addWidget(btn_load_change)

        root.addLayout(btn_row2)

        # 按钮行 3：保存
        btn_row3 = QHBoxLayout()
        btn_row3.setSpacing(6)
        btn_save = QPushButton("保存")
        btn_save.setStyleSheet(_S_SAVE)
        btn_save.clicked.connect(self._vi_save)
        btn_row3.addWidget(btn_save)

        btn_copy_global = QPushButton("复制 Network 全量信息")
        btn_copy_global.setStyleSheet(_S_BTN)
        btn_copy_global.setToolTip("复制 Network 公钥、私钥、network_seed 的 Base64/Hex，测试阶段用于共享给工程师")
        btn_copy_global.clicked.connect(self._copy_global_identity)
        btn_row3.addWidget(btn_copy_global)

        root.addLayout(btn_row3)
        root.addStretch()

        self._vi_dock = QDockWidget("Network 密钥配置", self)
        self._vi_dock.setWidget(w)
        self._vi_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._vi_dock.setMinimumWidth(280)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._vi_dock)
        self._vi_dock.hide()   # 默认隐藏，用户可从工具栏打开

    def _vi_generate_global_keypair(self):
        """生成 X25519 Network 密钥对并填入 UI 字段。"""
        import base64 as _base64
        try:
            from meshdebug.pki_crypto import generate_global_keypair
        except ImportError:
            QMessageBox.critical(
                self, "缺少依赖库",
                "缺少 cryptography 库，请在运行本程序的 Python 环境中执行：\n\n"
                "    pip install cryptography\n\n"
                f"当前 Python：{__import__('sys').executable}"
            )
            return
        try:
            priv, pub = generate_global_keypair()
            self.vi_cpub_edit.setText(_base64.b64encode(pub).decode())
            self.vi_cpriv_edit.setText(_base64.b64encode(priv).decode())
            set_widget_text(self.vi_status_lbl, "● 已生成 Network 密钥对（尚未保存）")
            self.vi_status_lbl.setStyleSheet("color:#f0c040; font-size:10px;")
        except Exception as e:
            QMessageBox.critical(self, "生成 Network 密钥对失败", str(e))

    def _vi_generate_company_keypair(self):
        """Legacy wrapper."""
        self._vi_generate_global_keypair()

    def _vi_generate_network_seed(self):
        """生成网络级 network_seed 并填入 Network UI。"""
        import base64 as _base64
        import os as _os

        seed = _os.urandom(16)
        self.vi_network_seed_edit.setText(_base64.b64encode(seed).decode())
        set_widget_text(self.vi_status_lbl, "● 已生成网络随机种子（尚未保存）")
        self.vi_status_lbl.setStyleSheet("color:#f0c040; font-size:10px;")

    def _vi_current_network_seed_b64(self) -> str:
        import base64 as _base64

        seed_b64 = self.vi_network_seed_edit.text().strip()
        if not seed_b64:
            return ""
        seed = _base64.b64decode(seed_b64)
        if not 16 <= len(seed) <= 32:
            raise ValueError(f"network_seed 必须为16-32字节，当前 {len(seed)} 字节")
        return seed_b64

    def _vi_load_to_global(self):
        """将 Network 公钥+网关公钥+节点ID填入 Private Config 入网表单。"""
        import base64 as _b64
        try:
            network_seed_b64 = self._vi_current_network_seed_b64()
        except Exception as exc:
            QMessageBox.warning(self, "network_seed 错误", str(exc))
            return
        global_pub_b64 = self.vi_cpub_edit.text().strip()
        # 网关公钥/节点ID 来自当前串口连接节点
        gw_node_hex = self._my_node_id
        gw_node_info = self._nodes.get(self._my_node_id, {})
        gw_pub_bytes = gw_node_info.get("public_key", b"")
        gw_pub_b64 = _b64.b64encode(gw_pub_bytes).decode() if gw_pub_bytes else ""
        if not gw_node_hex:
            QMessageBox.warning(self, "未连接", "请先连接串口，获取本机节点信息后再加载入网表单。")
            return
        self.send_panel.fill_global_from_vi(
            global_pub_b64=global_pub_b64,
            gw_pub_b64=gw_pub_b64,
            gw_node_hex=gw_node_hex,
            network_seed_b64=network_seed_b64,
        )
        # 切换到 Private Config 页
        for i in range(self.send_panel.portnum_combo.count()):
            if self.send_panel.portnum_combo.itemData(i) == 287:
                self.send_panel.portnum_combo.setCurrentIndex(i)
                break

    def _vi_load_to_enrollment(self):
        """Legacy wrapper."""
        self._vi_load_to_global()

    def _vi_load_to_change_admin(self):
        """将网关公钥/节点ID填入 Private Config 更换管理员表单。"""
        import base64 as _b64
        # 网关公钥/节点ID 来自当前串口连接节点
        gw_node_hex = self._my_node_id
        gw_node_info = self._nodes.get(self._my_node_id, {})
        gw_pub_bytes = gw_node_info.get("public_key", b"")
        gw_pub_b64 = _b64.b64encode(gw_pub_bytes).decode() if gw_pub_bytes else ""
        if not gw_node_hex:
            QMessageBox.warning(self, "未连接", "请先连接串口，获取本机节点信息后再加载改管理员表单。")
            return
        self.send_panel.fill_change_admin_from_vi(
            new_gw_pub_b64=gw_pub_b64,
            new_gw_node_hex=gw_node_hex,
        )
        # 切换到 Private Config 页
        for i in range(self.send_panel.portnum_combo.count()):
            if self.send_panel.portnum_combo.itemData(i) == 287:
                self.send_panel.portnum_combo.setCurrentIndex(i)
                break

    def _vi_save(self):
        """将当前 UI 中的 Network 密钥保存到 virtual_identity.json 并应用。"""
        cpub_b64  = self.vi_cpub_edit.text().strip()
        cpriv_b64 = self.vi_cpriv_edit.text().strip()
        try:
            network_seed_b64 = self._vi_current_network_seed_b64()
        except Exception as exc:
            QMessageBox.warning(self, "network_seed 错误", str(exc))
            return

        data = {
            "network_public_key":  cpub_b64,
            "network_private_key": cpriv_b64,
            "network_seed":        network_seed_b64,
        }
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "virtual_identity.json")
        path = os.path.normpath(path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return

        self._apply_virtual_identity(data)
        set_widget_text(self.vi_status_lbl, f"● 已保存到 {os.path.basename(path)}")
        self.vi_status_lbl.setStyleSheet("color:#6fcf97; font-size:10px;")

    def _load_virtual_identity(self, auto: bool = False):
        """从 virtual_identity.json 加载 Network 密钥配置。auto=True 时静默失败。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "virtual_identity.json")
        path = os.path.normpath(path)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            if not auto:
                QMessageBox.critical(self, "加载 Network 密钥失败", str(e))
            return
        # 填充 UI
        cpub_b64  = data.get("network_public_key", data.get("global_public_key", data.get("company_public_key", "")))
        cpriv_b64 = data.get("network_private_key", data.get("global_private_key", data.get("company_private_key", "")))
        network_seed_b64 = data.get("network_seed", "")
        self.vi_cpub_edit.setText(cpub_b64)
        self.vi_cpriv_edit.setText(cpriv_b64)
        self.vi_network_seed_edit.setText(network_seed_b64)
        self._apply_virtual_identity(data)
        set_widget_text(self.vi_status_lbl, f"● 已加载 {os.path.basename(path)}")
        self.vi_status_lbl.setStyleSheet("color:#6fcf97; font-size:10px;")

    def _apply_virtual_identity(self, data: dict):
        """将加载的 Network 密钥写入 _virtual_identity。"""
        import base64 as _base64
        cpub_b64  = data.get("network_public_key", data.get("global_public_key", data.get("company_public_key", ""))).strip()
        cpriv_b64 = data.get("network_private_key", data.get("global_private_key", data.get("company_private_key", ""))).strip()
        seed_b64 = data.get("network_seed", "").strip()
        try:
            cpub_bytes  = _base64.b64decode(cpub_b64)  if cpub_b64  else b""
            cpriv_bytes = _base64.b64decode(cpriv_b64) if cpriv_b64 else b""
            seed_bytes  = _base64.b64decode(seed_b64)  if seed_b64  else b""
        except Exception:
            cpub_bytes = cpriv_bytes = seed_bytes = b""

        self._virtual_identity = {
            "network_public_key":  cpub_bytes,
            "network_private_key": cpriv_bytes,
            "global_public_key":   cpub_bytes,
            "global_private_key":  cpriv_bytes,
            "network_seed":        seed_bytes,
        }

    @staticmethod
    def _bytes_formats(value) -> dict:
        if isinstance(value, str):
            raw = value.encode("utf-8")
        elif isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
        else:
            raw = b""
        return {
            "len": len(raw),
            "hex": raw.hex(),
            "base64": base64.b64encode(raw).decode() if raw else "",
        }

    def _collect_global_identity_for_share(self) -> dict:
        try:
            seed_b64 = self._vi_current_network_seed_b64()
        except Exception:
            seed_b64 = self.vi_network_seed_edit.text().strip()
        fields = {
            "network_public_key": self.vi_cpub_edit.text().strip(),
            "network_private_key": self.vi_cpriv_edit.text().strip(),
            "network_seed": seed_b64,
        }
        out: dict = {}
        for name, text in fields.items():
            raw = b""
            if text:
                try:
                    raw = base64.b64decode(text)
                except Exception:
                    raw = b""
            out[name] = {
                "base64": text,
                "hex": raw.hex(),
                "len": len(raw),
            }
        return out

    def _format_global_identity_for_share(self) -> str:
        ident = self._collect_global_identity_for_share()
        lines = [
            "Dragino Network Identity",
            f"generated_at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for name in ("network_public_key", "network_private_key", "network_seed"):
            item = ident.get(name, {})
            lines += [
                f"{name}_len: {item.get('len', 0)}",
                f"{name}_base64: {item.get('base64', '')}",
                f"{name}_hex: {item.get('hex', '')}",
                "",
            ]
        lines.append("note: 测试阶段共享用，正式客户交付时不要明文外发 network_private_key。")
        return "\n".join(lines)

    def _copy_global_identity(self):
        QApplication.clipboard().setText(self._format_global_identity_for_share())
        QMessageBox.information(self, "已复制", "已复制 Network 全量信息到剪贴板。")

    def _on_gen_network_access_sig(self):
        """Generate JoinNetWorkV2.auth_code from the node device_private_key."""
        import base64 as _b64
        import time as _t
        try:
            from meshdebug.pki_crypto import sign_join_network_v2
        except ImportError:
            QMessageBox.critical(
                self, "缺少依赖库",
                "缺少 cryptography 库，请在运行本程序的 Python 环境中执行：\n\n"
                "    pip install cryptography\n\n"
                f"当前 Python：{__import__('sys').executable}"
            )
            return

        try:
            op = self.send_panel.pc_op_combo.currentData()
            if op != "join_network_v2":
                raise ValueError("请切换到 Join Network V2")
            device_private_key = _b64.b64decode(self.send_panel.pc_na_device_priv_edit.text().strip())
            join_challenge = _b64.b64decode(self.send_panel.pc_na_challenge_edit.text().strip())
            network_pub = _b64.b64decode(self.send_panel.pc_na_global_pub_edit.text().strip())
            current_gw_pub = self._nodes.get(self._my_node_id, {}).get("public_key", b"") if self._my_node_id else b""
            if self._my_node_id and len(current_gw_pub) == 32:
                gw_pub = current_gw_pub
                gw_node_id = int(self._my_node_id.lstrip("!"), 16)
                self.send_panel.pc_na_gwpub_edit.setText(_b64.b64encode(gw_pub).decode())
                self.send_panel.pc_na_gwid_edit.setText(self._my_node_id)
            else:
                gw_pub = _b64.b64decode(self.send_panel.pc_na_gwpub_edit.text().strip())
                gw_node_id = int(self.send_panel.pc_na_gwid_edit.text().strip().lstrip("!"), 16)
            timestamp = int(_t.time())
            if op == "join_network_v2":
                node_id = self.send_panel.pc_na_join_combo.currentData() or self.send_panel.to_edit.text().strip()
                target_node = self.send_panel._normalize_profile_node_id(node_id, "JoinNetWorkV2 target node_id")
                item = self.send_panel._join_lock_cache.get(target_node) or self.send_panel._join_lock_cache.get(node_id or "")
                if not item:
                    self.send_panel._fill_join_v2_seed_from_profile(target_node)
                    raise ValueError(
                        "JoinNetWorkV2 需要先在网关侧收到远端节点真实 JoinLockAdvertise。\n"
                        "本地 FactoryIdentity 档案只保存 SN/EUI/私钥/network_seed，不能提供设备当前 join_challenge。\n"
                        "请确认远端节点未入网、已写入有效 FactoryIdentity，然后切到网关串口等待 JoinLock 广播。"
                    )
                if item.get("source") == "local_profile":
                    self.send_panel._fill_join_v2_seed_from_profile(target_node)
                    raise ValueError(
                        "当前选中的是本地 FactoryIdentity 档案，不是真实 JoinLockAdvertise。\n"
                        "JoinNetWorkV2 auth_code 必须使用远端节点运行时广播的 join_challenge；"
                        "请切到网关串口，等收到该节点 JoinLock 后再生成 auth_code。"
                    )
                cached_challenge = item.get("join_challenge", b"")
                if len(cached_challenge) != 16:
                    raise ValueError("缓存的 JoinLockAdvertise 不完整，请等待远端节点重新广播 JoinLock")
                if cached_challenge != join_challenge:
                    join_challenge = cached_challenge
                    self.send_panel.pc_na_challenge_edit.setText(_b64.b64encode(join_challenge).decode())
                if not self.send_panel._fill_device_private_key_from_profile(target_node):
                    raise ValueError(
                        f"本地档案缺少 {target_node} 的 device_private_key；"
                        "不能生成 JoinNetWorkV2 auth_code。请先 Get/保存 FactoryIdentity，"
                        "或在档案管理中为该节点补齐私钥。"
                    )
                device_private_key = _b64.b64decode(self.send_panel.pc_na_device_priv_edit.text().strip())
                if len(device_private_key) != 32:
                    raise ValueError(f"device_private_key 必须为32字节，当前 {len(device_private_key)} 字节")
                if len(network_pub) != 32:
                    raise ValueError(f"network_public_key 必须为32字节，当前 {len(network_pub)} 字节")
                if len(gw_pub) != 32:
                    raise ValueError(f"gateway_public_key 必须为32字节，当前 {len(gw_pub)} 字节")
                seed_b64 = self.send_panel.pc_jv2_seed_edit.text().strip()
                if not seed_b64:
                    self.send_panel._fill_join_v2_seed_from_profile(target_node)
                    seed_b64 = self.send_panel.pc_jv2_seed_edit.text().strip()
                if not seed_b64:
                    raise ValueError("JoinNetWorkV2 需要 network_seed，请先在 Network 密钥配置界面生成/保存，并加载到入网签名页")
                network_seed = _b64.b64decode(seed_b64)
                if not 16 <= len(network_seed) <= 32:
                    raise ValueError(f"network_seed 必须为16-32字节，当前 {len(network_seed)} 字节")
                sig = sign_join_network_v2(
                    join_authority_private_key=device_private_key,
                    sn=item.get("sn", ""),
                    dev_eui=item.get("dev_eui", ""),
                    join_challenge=join_challenge,
                    target_node_id=int(target_node.lstrip("!"), 16),
                    gateway_node_id=gw_node_id,
                    gateway_public_key=gw_pub,
                    network_public_key=network_pub,
                    network_seed=network_seed,
                    timestamp=timestamp,
                )
                self.send_panel.to_edit.setText(target_node)
                self.send_panel.channel_spin.setValue(0)
                self.send_panel.want_resp_chk.setChecked(True)
                self.send_panel.want_ack_chk.setChecked(False)
                self.send_panel._fill_join_v2_derived_channel12(network_seed, target_node, save=True)
            self.send_panel.pc_na_sig_edit.setText(_b64.b64encode(sig).decode())
            self.send_panel.pc_na_timestamp_edit.setText(str(timestamp))
            self.send_panel._pc_network_access_timestamp = timestamp
        except Exception as e:
            self.send_panel.log_result(False, f"JoinNetWorkV2 AuthCode 生成失败: {e}")
            QMessageBox.warning(self, "JoinNetWorkV2 auth_code 生成失败", str(e))

    def _on_gen_change_admin_sig(self):
        """用目标节点 device_private_key 为 ChangeAdmin 请求生成 auth_code。"""
        import base64 as _b64
        import time as _t
        self.send_panel._sync_private_config_target_node_fields()
        new_gw_pub_b64 = self.send_panel.pc_newgwpub_edit.text().strip()
        dev_node_str   = self.send_panel.pc_dev_node_edit.text().strip().lstrip("!")
        if not new_gw_pub_b64:
            QMessageBox.warning(self, "错误", "请先填入新网关公钥（Base64）")
            return
        if not dev_node_str:
            QMessageBox.warning(self, "错误", "请先填入目标设备节点ID（!xxxxxxxx）")
            return
        try:
            new_gw_pub     = _b64.b64decode(new_gw_pub_b64)
            device_node_id = int(dev_node_str, 16)
            timestamp      = int(_t.time())
            profile = self.send_panel.get_factory_identity_profile(f"!{device_node_id:08x}") or {}
            device_private_key = _b64.b64decode(profile.get("device_private_key", "") or profile.get("flash_private_key", ""))
            network_pub = self._virtual_identity.get("network_public_key", b"") or self._virtual_identity.get("global_public_key", b"")
            if len(device_private_key) != 32:
                raise ValueError("缺少目标节点 device_private_key 本地档案")
            if len(network_pub) != 32:
                raise ValueError("缺少当前 network_public_key")
            from meshdebug.pki_crypto import hmac_change_admin
            sig = hmac_change_admin(
                device_private_key=device_private_key,
                sn=profile.get("sn", ""),
                dev_eui=profile.get("dev_eui", ""),
                target_node_id=device_node_id,
                current_network_public_key=network_pub,
                new_gateway_node_id=int(self.send_panel.pc_newgwid_edit.text().strip().lstrip("!"), 16),
                new_gateway_public_key=new_gw_pub,
                timestamp=timestamp,
            )
            self.send_panel.pc_sig_edit.setText(_b64.b64encode(sig).decode())
            self.send_panel._pc_change_admin_timestamp = timestamp
        except Exception as e:
            QMessageBox.warning(self, "签名失败", str(e))

    def _on_gen_reset_config_sig(self):
        """Fill ResetNetworkConfig.auth_code for the current firmware protocol."""
        import base64 as _b64
        import time as _t
        self.send_panel._sync_private_config_target_node_fields()
        timestamp = int(_t.time())
        auth_code = b"\x00" * 32
        self.send_panel.pc_reset_sig_edit.setText(_b64.b64encode(auth_code).decode())
        self.send_panel._pc_reset_timestamp = timestamp

    def _on_gen_change_global_key_sig(self):
        """Fill ChangeNetworkKey.auth_code for the current firmware protocol."""
        import base64 as _b64
        import time as _t
        self.send_panel._sync_private_config_target_node_fields()
        new_cpub_b64 = self.send_panel.pc_new_cpub_edit.text().strip()
        if not new_cpub_b64:
            QMessageBox.warning(self, "错误", "请先填入新 network_public_key（Base64）")
            return
        try:
            new_company_pub = _b64.b64decode(new_cpub_b64)
            if len(new_company_pub) != 32:
                raise ValueError(f"新 network_public_key 解码后须为32字节，当前 {len(new_company_pub)} 字节")
            timestamp = int(_t.time())
            auth_code = b"\x00" * 32
            self.send_panel.pc_cck_sig_edit.setText(_b64.b64encode(auth_code).decode())
            self.send_panel._pc_cck_timestamp = timestamp
        except Exception as e:
            QMessageBox.warning(self, "auth_code 生成失败", str(e))

    def _on_gen_change_company_key_sig(self):
        """Legacy wrapper."""
        self._on_gen_change_global_key_sig()

    def _on_heartbeat(self):
        """每 10 分钟发送一次心跳，防止固件 15 分钟超时断连。"""
        if self._worker and self._worker.is_running():
            self._worker.send_heartbeat()

    # ── 状态栏 ────────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self.lbl_status = QLabel("○  未连接")
        self.lbl_status.setStyleSheet("color: #666; padding: 0 8px;")

        self.lbl_nodes = QLabel("节点: —")
        self.lbl_nodes.setStyleSheet("color: #8cc8f0; padding: 0 8px;")

        self.lbl_frames = QLabel("帧数: 0")
        self.lbl_frames.setStyleSheet("color: #aaa; padding: 0 8px;")

        self.lbl_capture = QLabel("保存: 关闭")
        self.lbl_capture.setStyleSheet("color: #666; padding: 0 8px;")

        self.lbl_time_sync = QLabel("校时: 关闭")
        self.lbl_time_sync.setStyleSheet("color: #666; padding: 0 8px;")

        def _sep():
            l = QLabel("|")
            l.setStyleSheet("color: #444;")
            return l

        sb.addWidget(self.lbl_status)
        sb.addWidget(_sep())
        sb.addWidget(self.lbl_nodes)
        sb.addWidget(_sep())
        sb.addWidget(self.lbl_frames)
        sb.addWidget(_sep())
        sb.addWidget(self.lbl_capture)
        sb.addWidget(_sep())
        sb.addWidget(self.lbl_time_sync)

    def _selected_serial_config(self) -> tuple[str, Optional[int]]:
        port = ""
        baudrate = None
        if hasattr(self, "port_combo"):
            idx = self.port_combo.currentIndex()
            if idx >= 0:
                port = self.port_combo.itemData(idx) or self.port_combo.currentText().split()[0]
        if hasattr(self, "baud_combo"):
            try:
                baudrate = int(self.baud_combo.currentText())
            except Exception:
                baudrate = None
        return port, baudrate

    def _capture_call(self, action, *args, **kwargs):
        try:
            return action(*args, **kwargs)
        except Exception as exc:
            logger.exception("capture write failed")
            self._set_status("error", f"保存失败: {exc}")
            return None

    def _on_capture_toggled(self, checked: bool):
        port, baudrate = self._selected_serial_config()
        self._capture_call(
            self._capture.set_enabled,
            bool(checked),
            port=port,
            baudrate=baudrate,
        )
        if checked and self._nodes:
            self._capture_call(self._capture.write_nodes_snapshot, self._nodes, self._my_node_id)
        self._update_capture_status_label()

    def _update_capture_status_label(self):
        if not hasattr(self, "lbl_capture"):
            return
        if self._capture.enabled and self._capture.session_id:
            set_widget_text(self.lbl_capture, f"保存: 开 {self._capture.session_id}")
            self.lbl_capture.setStyleSheet("color: #6fcf97; padding: 0 8px;")
        elif self._capture.enabled:
            set_widget_text(self.lbl_capture, "保存: 开")
            self.lbl_capture.setStyleSheet("color: #6fcf97; padding: 0 8px;")
        else:
            set_widget_text(self.lbl_capture, "保存: 关闭")
            self.lbl_capture.setStyleSheet("color: #666; padding: 0 8px;")

    def _on_auto_time_sync_toggled(self, checked: bool):
        if not hasattr(self, "_time_sync_last_status"):
            self._time_sync_last_status = "off"
        self._time_sync_last_status = "ready" if checked else "off"
        self._update_time_sync_status_label()

    def _update_time_sync_status_label(self):
        if not hasattr(self, "lbl_time_sync"):
            return
        enabled = self._auto_time_sync_enabled()
        status = getattr(self, "_time_sync_last_status", "off")
        if not enabled:
            set_widget_text(self.lbl_time_sync, "校时: 关闭")
            self.lbl_time_sync.setStyleSheet("color: #666; padding: 0 8px;")
            return
        if status == "ready":
            text = "校时: 待命"
            color = "#a8d8ea"
        elif status.startswith("sent:"):
            text = "校时: " + status.split(":", 1)[1]
            color = "#6fcf97"
        elif status.startswith("skip:"):
            text = "校时: " + status.split(":", 1)[1]
            color = "#ffd580"
        elif status.startswith("error:"):
            text = "校时: " + status.split(":", 1)[1]
            color = "#ff8a80"
        else:
            text = "校时: 待命"
            color = "#a8d8ea"
        set_widget_text(self.lbl_time_sync, text)
        self.lbl_time_sync.setStyleSheet(f"color: {color}; padding: 0 8px;")

    def _on_serial_text(self, text: str):
        self._serial_log.append_line(text)
        self._capture_call(self._capture.record_serial_text, text)

    # ── 串口操作 ──────────────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports   = list_serial_ports()
        current = self.port_combo.currentText()
        self.port_combo.clear()
        for p in ports:
            desc  = p["description"]
            label = (
                f"{p['device']}  ({desc})"
                if desc and desc != p["device"]
                else p["device"]
            )
            self.port_combo.addItem(label, userData=p["device"])
        idx = self.port_combo.findText(current, Qt.MatchFlag.MatchStartsWith)
        if idx >= 0:
            self.port_combo.setCurrentIndex(idx)

    def _on_connect(self):
        idx = self.port_combo.currentIndex()
        if idx < 0:
            self._set_status("error", "✕  请先选择串口")
            return
        port     = self.port_combo.itemData(idx) or self.port_combo.currentText().split()[0]
        baudrate = int(self.baud_combo.currentText())

        if self.chk_capture.isChecked():
            self._capture_call(self._capture.set_enabled, True, port=port, baudrate=baudrate)
            self._update_capture_status_label()

        self._worker = SerialWorker(port=port, baudrate=baudrate)
        self._worker.frame_received.connect(self._on_frame)
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.text_received.connect(self._on_serial_text)
        self._worker.start()

        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self._set_status("connecting", f"⏳  正在连接 {port}…")

    def _on_disconnect(self):
        if self._worker:
            self._worker.stop()
            self._worker.wait(3000)
            self._worker = None
        self._capture_call(self._capture.stop_session)
        self._update_capture_status_label()
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)

    # ── 信号槽 ────────────────────────────────────────────────────────────────

    def _on_status_changed(self, msg: str):
        if msg.startswith("connected:"):
            self._set_status("ok", f"●  已连接 {msg.split(':',1)[1]}")
            self._capture_call(self._capture.update_connection, connected=True)
            self._update_capture_status_label()
            self._heartbeat_timer.start()
        elif msg == "disconnected":
            self._set_status("off", "○  已断开")
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            self._heartbeat_timer.stop()
            self._capture_call(self._capture.stop_session)
            self._update_capture_status_label()
        elif msg.startswith("reconnecting:"):
            delay = msg.split(":")[-1]
            self._set_status("connecting", f"⏳  断线，{delay} 后重连…")
            self._heartbeat_timer.stop()
            # 保持断开按钮可用，让用户可以取消重连
        elif msg.startswith("error:"):
            self._set_status("error", f"✕  {msg.split(':',1)[1]}")
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            self._heartbeat_timer.stop()
            self._capture_call(self._capture.stop_session)
            self._update_capture_status_label()

    def _auto_time_sync_enabled(self) -> bool:
        chk = getattr(self, "chk_auto_time_sync", None)
        return bool(chk and chk.isChecked())

    @staticmethod
    def _to_int(value, default: int | None = None) -> int | None:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return default
            try:
                return int(text, 0)
            except ValueError:
                return default
        return default

    @staticmethod
    def _is_truthy_payload_flag(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)

    def _node_rtc_from_frame(self, frame: dict) -> tuple[int | None, str]:
        if frame.get("variant") != "packet":
            return None, ""

        data = frame.get("data") or {}
        decoded = data.get("decoded") or {}
        parsed = decoded.get("payload_parsed") or {}
        portnum = self._to_int(decoded.get("portnum"), -1)
        portname = str(decoded.get("portnum_name") or "")

        if portname == "TELEMETRY_APP":
            epoch = self._to_int(parsed.get("time"), 0)
            return (epoch, "telemetry.time") if epoch and epoch > 0 else (None, "")

        return None, ""

    def _is_wakeup_sync_trigger_frame(self, frame: dict) -> tuple[bool, str]:
        data = frame.get("data") or {}
        decoded = data.get("decoded") or {}
        portname = str(decoded.get("portnum_name") or "")
        if portname == "TELEMETRY_APP":
            return True, "telemetry"
        return False, ""

    def _is_expected_wakeup_window(self, node_id: str, system_epoch: int) -> tuple[bool, str]:
        node = getattr(self, "_nodes", {}).get(node_id, {}) if node_id else {}
        sync = node.get("sync_wakeup_config") if isinstance(node.get("sync_wakeup_config"), dict) else {}
        if not sync or not sync.get("enabled"):
            return True, "observed packet"

        window = sync.get("wakeup_window") if isinstance(sync.get("wakeup_window"), dict) else {}
        active_sec = (
            self._to_int(window.get("startup_delay_sec"), 20) or 20
        ) + (
            self._to_int(window.get("random_delay_max_sec"), 15) or 15
        ) + (
            self._to_int(window.get("gateway_wait_sec"), 90) or 90
        ) + (
            self._to_int(window.get("final_wait_sec"), 5) or 5
        ) + 30
        active_sec = max(60, min(active_sec, 15 * 60))

        tod = system_epoch % 86400
        strategy = self._to_int(sync.get("strategy"), 0) or 0
        if strategy == 1 and isinstance(sync.get("scheduled_wakeup"), dict):
            sched = sync.get("scheduled_wakeup") or {}
            offset = self._to_int(sched.get("offset_sec"), 0) or 0
            slots = sched.get("time_slots") if isinstance(sched.get("time_slots"), list) else []
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                start_hour = self._to_int(slot.get("start_hour"), 0) or 0
                end_hour = self._to_int(slot.get("end_hour"), 24) or 24
                interval = max(1, self._to_int(slot.get("interval_min"), 60) or 60)
                align = self._to_int(slot.get("align_minute"), 0) or 0
                start = max(0, min(23, start_hour)) * 3600
                end = max(1, min(24, end_hour)) * 3600
                if end <= start:
                    end = 24 * 3600
                wake = start + align * 60 + offset - 30
                while wake < end:
                    if 0 <= tod - wake <= active_sec:
                        return True, "scheduled window"
                    wake += interval * 60
            return False, "outside scheduled window"

        fixed = sync.get("fixed_wakeup") if isinstance(sync.get("fixed_wakeup"), dict) else {}
        interval = max(1, self._to_int(fixed.get("interval_min"), 30) or 30)
        align = self._to_int(fixed.get("align_minute"), 0) or 0
        offset = self._to_int(fixed.get("offset_sec"), 0) or 0
        wake = align * 60 + offset - 30
        interval_sec = interval * 60
        while wake < 24 * 3600:
            if 0 <= tod - wake <= active_sec:
                return True, "fixed window"
            wake += interval_sec
        return False, "outside fixed window"

    def _build_time_sync_packet(self, epoch_seconds: int) -> mesh_pb2.MeshPacket:
        packet = mesh_pb2.MeshPacket()
        packet.to = 0xFFFF_FFFF
        packet.channel = TIME_SYNC_CHANNEL
        packet.decoded.portnum = CUSTOM_TIMESYNC_PORTNUM
        packet.want_ack = False
        packet.hop_limit = TIME_SYNC_HOP_LIMIT
        packet.hop_start = TIME_SYNC_HOP_LIMIT
        packet.priority = mesh_pb2.MeshPacket.Priority.Value("MAX")
        packet.id = random.randint(1, 2_147_483_647)

        pos = mesh_pb2.Position()
        pos.time = epoch_seconds
        pos.timestamp = epoch_seconds
        pos.location_source = 2  # LOC_INTERNAL; TimeSyncModule rejects lower remote sources.
        pos.altitude_source = 2
        pos.fix_quality = 9
        pos.fix_type = 3
        pos.sats_in_view = 99
        pos.precision_bits = 32
        packet.decoded.payload = pos.SerializeToString()
        return packet

    def _send_auto_time_sync_packet(
        self,
        node_id: str,
        *,
        node_epoch: int,
        system_epoch: int,
        drift_sec: int,
        source: str,
        wakeup_reason: str,
    ) -> bool:
        worker = getattr(self, "_worker", None)
        if not worker or not worker.is_running():
            self._time_sync_last_status = "error:未连接"
            self._update_time_sync_status_label()
            return False

        packet = self._build_time_sync_packet(system_epoch)
        success, frame_hex = worker.send_packet(packet)
        summary = (
            f"AUTO_TIME_SYNC 286 local -> broadcast  node={node_id} "
            f"node_time={node_epoch} system_time={system_epoch} drift={drift_sec:+d}s "
            f"source={source} wakeup={wakeup_reason}"
        )
        if success:
            self._time_sync_last_sent_at[node_id] = time.monotonic()
            self._time_sync_last_sent_at["__broadcast__"] = time.monotonic()
            try:
                from meshdebug.proto_parser import parse_mesh_packet
                packet_dict = parse_mesh_packet(packet)
            except Exception:
                packet_dict = {}
            capture = getattr(self, "_capture", None)
            if capture is not None:
                self._capture_call(capture.record_sent_frame, packet_dict, frame_hex, summary=summary)
            if hasattr(self, "send_panel"):
                self.send_panel.log_result(True, summary)
            self._time_sync_last_status = f"sent:{node_id} {drift_sec:+d}s"
            self._update_time_sync_status_label()
            return True

        if hasattr(self, "send_panel"):
            self.send_panel.log_result(False, "AUTO_TIME_SYNC 写串口失败")
        self._time_sync_last_status = "error:发送失败"
        self._update_time_sync_status_label()
        return False

    def _handle_auto_time_sync(self, frame: dict):
        if not self._auto_time_sync_enabled():
            return
        is_wakeup, wakeup_reason = self._is_wakeup_sync_trigger_frame(frame)
        if not is_wakeup:
            return

        data = frame.get("data") or {}
        node_id = str(data.get("from_id") or "")
        if not node_id or node_id == "broadcast":
            return
        if node_id == getattr(self, "_my_node_id", ""):
            return

        node_epoch, source = self._node_rtc_from_frame(frame)
        if not node_epoch:
            return

        system_epoch = int(time.time())
        drift_sec = int(node_epoch - system_epoch)
        abs_drift = abs(drift_sec)
        node_info = self._nodes.setdefault(node_id, {"node_id": node_id})
        in_window, window_reason = self._is_expected_wakeup_window(node_id, system_epoch)
        node_info["last_time_sync_observation"] = {
            "node_epoch": node_epoch,
            "system_epoch": system_epoch,
            "drift_sec": drift_sec,
            "source": source,
            "wakeup_trigger": wakeup_reason,
            "expected_window": in_window,
            "window_reason": window_reason,
        }

        if abs_drift < TIME_SYNC_DRIFT_THRESHOLD_SEC:
            self._time_sync_last_status = f"skip:{node_id} {drift_sec:+d}s"
            self._update_time_sync_status_label()
            return

        now_mono = time.monotonic()
        last_for_node = self._time_sync_last_sent_at.get(node_id)
        if last_for_node is not None and now_mono - last_for_node < TIME_SYNC_COOLDOWN_SEC:
            self._time_sync_last_status = f"skip:{node_id} 冷却"
            self._update_time_sync_status_label()
            return
        last_broadcast = self._time_sync_last_sent_at.get("__broadcast__")
        if last_broadcast is not None and now_mono - last_broadcast < 30:
            self._time_sync_last_status = "skip:广播冷却"
            self._update_time_sync_status_label()
            return

        self._send_auto_time_sync_packet(
            node_id,
            node_epoch=node_epoch,
            system_epoch=system_epoch,
            drift_sec=drift_sec,
            source=source,
            wakeup_reason=window_reason if in_window else f"{wakeup_reason}; {window_reason}",
        )

    def _on_frame(self, frame: dict):
        self._frame_count += 1
        self._recent_ts.append(time.monotonic())

        self.frame_table.append_frame(frame)
        self._capture_call(self._capture.record_received_frame, frame)
        self._update_nodes(frame)
        self._handle_auto_time_sync(frame)
        set_widget_text(self.lbl_frames, f"帧数: {self._frame_count}")

        if self.chk_autoscroll.isChecked():
            self.frame_table.scroll_to_bottom()

        # ── 请求-响应追踪 + Session Passkey 提取 ─────────────────────────
        if frame.get("variant") == "packet":
            data    = frame.get("data") or {}
            decoded = data.get("decoded") or {}

            # 响应关联：检查 request_id 是否对应一条已发请求
            req_id = decoded.get("request_id")
            if req_id and req_id in self._pending_requests:
                req_info = self._pending_requests.pop(req_id)
                portnum_name = decoded.get("portnum_name", "")
                if portnum_name == "ROUTING_APP":
                    # ROUTING_APP 通常是 NAK —— 检查 error_reason
                    payload_parsed = decoded.get("payload_parsed") or {}
                    err_reason = payload_parsed.get("error_reason", "")
                    # NO_RESPONSE + Admin 请求 → is_managed 诊断警告
                    if err_reason in ("NO_RESPONSE", "8", 8) and req_info.get("portnum") == 6:
                        self.send_panel.log_nak_warning(req_info["summary"], err_reason)
                    else:
                        # 其他 NAK / Routing 响应 → 通用记录
                        self.send_panel.log_response(req_info["summary"], frame)
                else:
                    # 正常 Admin / 其他响应
                    self.send_panel.log_response(req_info["summary"], frame)
                    self.send_panel.update_sent_detail(data, "")

            # Admin 响应：提取 session_passkey + 全量响应解析
            if decoded.get("portnum") == 6:   # ADMIN_APP
                from_id_adm = data.get("from_id", "")
                payload_hex = decoded.get("payload_hex", "")
                if payload_hex:
                    try:
                        from meshtastic import admin_pb2
                        from google.protobuf.json_format import MessageToDict as _MsgToDict
                        adm = admin_pb2.AdminMessage()
                        adm.ParseFromString(bytes.fromhex(payload_hex))
                        # ① session_passkey：按来源节点存储
                        if adm.session_passkey:
                            pk = bytes(adm.session_passkey)
                            self._admin_passkeys[from_id_adm] = (pk, time.monotonic())
                            self.send_panel.set_session_passkey_status(
                                pk, valid=True, node_id=from_id_adm
                            )
                        # ② 响应类型分发
                        which = adm.WhichOneof("payload_variant")
                        _MD_KWARGS = dict(
                            preserving_proto_field_name=True,
                            use_integers_for_enums=True,
                            always_print_fields_with_no_presence=False,
                        )
                        if which == "get_config_response":
                            cfg = adm.get_config_response
                            cfg_variant = cfg.WhichOneof("payload_variant")
                            _name2type = {
                                "device": 0, "position": 1, "power": 2,
                                "network": 3, "display": 4, "lora": 5,
                                "bluetooth": 6, "security": 7,
                                "sessionkey": 8, "device_ui": 9,
                            }
                            cfg_type_int = _name2type.get(cfg_variant, -1)
                            cfg_dict = _MsgToDict(cfg, **_MD_KWARGS)
                            if from_id_adm:
                                self._nodes.setdefault(from_id_adm, {"node_id": from_id_adm}) \
                                           .setdefault("configs", {})[cfg_type_int] = cfg_dict
                            if cfg_type_int >= 0:
                                self.send_panel.update_config_cache(cfg_type_int, from_id_adm, cfg_dict)
                            self._refresh_node_info_dock()
                        elif which == "get_module_config_response":
                            mcfg = adm.get_module_config_response
                            mcfg_variant = mcfg.WhichOneof("payload_variant")
                            _mname2type = {
                                "mqtt": 0, "serial": 1, "external_notification": 2,
                                "store_forward": 3, "range_test": 4, "telemetry": 5,
                                "canned_message": 6, "audio": 7, "remote_hardware": 8,
                                "neighbor_info": 9, "ambient_lighting": 10,
                                "detection_sensor": 11, "pax_counter": 12,
                            }
                            mcfg_type_int = _mname2type.get(mcfg_variant, -1)
                            mcfg_dict = _MsgToDict(mcfg, **_MD_KWARGS)
                            if from_id_adm and mcfg_type_int >= 0:
                                self._nodes.setdefault(from_id_adm, {"node_id": from_id_adm}) \
                                           .setdefault("module_configs", {})[mcfg_type_int] = mcfg_dict
                            self._refresh_node_info_dock()
                        elif which == "get_channel_response":
                            ch = adm.get_channel_response
                            ch_dict = _MsgToDict(ch, **_MD_KWARGS)
                            if from_id_adm:
                                self._nodes.setdefault(from_id_adm, {"node_id": from_id_adm}) \
                                           .setdefault("channels", {})[ch.index] = ch_dict
                            self._refresh_node_info_dock()
                        elif which == "get_owner_response":
                            user_dict = _MsgToDict(adm.get_owner_response, **_MD_KWARGS)
                            if from_id_adm:
                                self._nodes.setdefault(from_id_adm, {"node_id": from_id_adm}) \
                                           ["owner"] = user_dict
                            self._refresh_node_info_dock()
                    except Exception:
                        pass

            # PRIVATE_CONFIG_APP (287) 响应解析
            if decoded.get("portnum") == 287:
                payload_hex_pc = decoded.get("payload_hex", "")
                if payload_hex_pc:
                    try:
                        from meshdebug.private_config_pb2 import PrivateConfigPacket
                        pkt_pc = PrivateConfigPacket()
                        pkt_pc.ParseFromString(bytes.fromhex(payload_hex_pc))
                        which_pkt = pkt_pc.WhichOneof("packet_type")
                        if which_pkt == "uplink_packet":
                            uplink = pkt_pc.uplink_packet
                            which_up = uplink.WhichOneof("payload")
                            if which_up == "join_lock_advertise":
                                adv = uplink.join_lock_advertise
                                from_id_pc = data.get("from_id", "")
                                dev_eui = f"{adv.dev_eui_hi:08X}{adv.dev_eui_lo:08X}"
                                join_challenge = bytes(adv.join_challenge)
                                self.send_panel.update_join_lock_advertise(
                                    from_id_pc,
                                    adv.sn,
                                    dev_eui,
                                    join_challenge,
                                )
                                if from_id_pc:
                                    node_info = self._nodes.setdefault(from_id_pc, {"node_id": from_id_pc})
                                    node_info["join_lock_advertise"] = {
                                        "sn": adv.sn,
                                        "dev_eui": dev_eui,
                                        "join_challenge": join_challenge.hex(),
                                    }
                                    self._refresh_nodes_status()
                                    self._refresh_node_info_dock()
                                    join_summary = self._node_join_summary(node_info)
                                else:
                                    join_summary = {"state": "not_joined", "reason": "join_lock_advertise"}
                                lines = [
                                    f"sn: {adv.sn}",
                                    f"dev_eui: {dev_eui}",
                                    f"join_challenge: {join_challenge.hex()}",
                                    f"join_state: {join_summary.get('state')} ({join_summary.get('reason')})",
                                ]
                                self.send_panel.log_result(
                                    True, "JoinLockAdvertise:\n" + "\n".join(lines))
                            elif which_up == "factory_identity":
                                identity = uplink.factory_identity
                                from_id_pc = data.get("from_id", "")
                                device_private_key = bytes(identity.device_private_key)
                                device_private_key_b64 = base64.b64encode(device_private_key).decode() if device_private_key else ""
                                legacy_app_key = bytes(identity.legacy_app_key)
                                legacy_app_key_b64 = base64.b64encode(legacy_app_key).decode() if legacy_app_key else ""
                                legacy_app_key_hex = legacy_app_key.hex().upper()
                                device_public_key_b64 = ""
                                if len(device_private_key) == 32:
                                    try:
                                        from meshdebug.pki_crypto import public_key_from_private
                                        device_public_key_b64 = base64.b64encode(public_key_from_private(device_private_key)).decode()
                                    except Exception:
                                        device_public_key_b64 = ""
                                identity_info = {
                                    "factory_version": identity.factory_version,
                                    "sn": identity.sn,
                                    "dev_eui": f"{identity.dev_eui_hi:08X}{identity.dev_eui_lo:08X}",
                                    "device_private_key": device_private_key_b64,
                                    "device_public_key": device_public_key_b64,
                                    "legacy_app_key": legacy_app_key_b64,
                                    "legacy_app_key_hex": legacy_app_key_hex,
                                    "manufacturing_timestamp": identity.manufacturing_timestamp,
                                    "status": identity.status,
                                    "identity_crc": f"0x{identity.identity_crc:08X}",
                                }
                                if from_id_pc:
                                    self._factory_identity_cache[from_id_pc] = identity_info
                                    self._nodes.setdefault(from_id_pc, {"node_id": from_id_pc})[
                                        "factory_identity_status"
                                    ] = self._device_factory_identity_status(identity_info)
                                    self._save_factory_identity_from_device(from_id_pc, identity_info, quiet=True)
                                    self._refresh_node_info_dock()
                                    self._refresh_factory_profile_dock()
                                lines = [
                                    f"factory_version: {identity.factory_version}",
                                    f"sn: {identity.sn}",
                                    f"dev_eui: {identity.dev_eui_hi:08X}{identity.dev_eui_lo:08X}",
                                    f"device_private_key: {device_private_key_b64}",
                                    f"device_public_key: {device_public_key_b64}",
                                    f"legacy_app_key: {legacy_app_key_b64}",
                                    f"legacy_app_key_hex: {legacy_app_key_hex}",
                                    f"manufacturing_timestamp: {identity.manufacturing_timestamp}",
                                    f"status: {identity.status}",
                                    f"identity_crc: 0x{identity.identity_crc:08X}",
                                ]
                                self.send_panel.log_result(
                                    True, "DeviceFactoryIdentity:\n" + "\n".join(lines))
                            elif which_up == "network_config":
                                cfg = uplink.network_config
                                gateways = [f"0x{x:08X}" for x in cfg.trusted_gateway_sources]
                                from_id_pc = data.get("from_id", "")
                                network_info = {
                                    "network_public_key": bytes(cfg.network_public_key).hex(),
                                    "network_seed": bytes(cfg.network_seed).hex(),
                                    "last_change_timestamp": cfg.last_change_timestamp,
                                    "is_single_gateway": cfg.is_single_gateway,
                                    "trusted_gateway_sources": [f"!{x:08x}" for x in cfg.trusted_gateway_sources],
                                }
                                if from_id_pc:
                                    node_info = self._nodes.setdefault(from_id_pc, {"node_id": from_id_pc})
                                    node_info["network_config"] = network_info
                                    self._refresh_nodes_status()
                                    self._refresh_node_info_dock()
                                    join_summary = self._node_join_summary(node_info)
                                    config_summary = self._node_network_config_summary(node_info)
                                else:
                                    join_summary = {"state": "joined", "reason": "network_config captured"}
                                    config_summary = self._node_network_config_summary({"network_config": network_info})
                                lines = [
                                    f"network_public_key: {bytes(cfg.network_public_key).hex()}",
                                    f"network_seed: {bytes(cfg.network_seed).hex()}",
                                    f"last_change_timestamp: {cfg.last_change_timestamp}",
                                    f"is_single_gateway: {cfg.is_single_gateway}",
                                    "trusted_gateway_sources: " + (", ".join(gateways) if gateways else "-"),
                                    f"network_public_key_len: {config_summary.get('network_public_key_len', 0)}",
                                    f"network_seed_len: {config_summary.get('network_seed_len', 0)}",
                                    f"join_state: {join_summary.get('state')} ({join_summary.get('reason')})",
                                ]
                                self.send_panel.log_result(
                                    True, "NetWorkConfig:\n" + "\n".join(lines))
                            elif which_up == "sync_wakeup_config":
                                wc = uplink.sync_wakeup_config
                                from_id_pc = data.get("from_id", "")
                                wakeup_info = {
                                    "enabled": wc.enabled,
                                    "strategy": wc.strategy,
                                    "fixed_wakeup": {
                                        "interval_min": wc.fixed_wakeup.interval_min,
                                        "align_minute": wc.fixed_wakeup.align_minute,
                                        "offset_sec": wc.fixed_wakeup.offset_sec,
                                    },
                                }
                                lines = [
                                    f"enabled: {wc.enabled}",
                                    f"strategy: {wc.strategy}",
                                    f"fixed.interval_min: {wc.fixed_wakeup.interval_min}",
                                    f"fixed.align_minute: {wc.fixed_wakeup.align_minute}",
                                    f"fixed.offset_sec: {wc.fixed_wakeup.offset_sec}",
                                ]
                                if wc.HasField("scheduled_wakeup"):
                                    lines.append(f"scheduled.offset_sec: {wc.scheduled_wakeup.offset_sec}")
                                    for i, slot in enumerate(wc.scheduled_wakeup.time_slots):
                                        lines.append(
                                            f"scheduled.slot[{i}]: {slot.start_hour}-{slot.end_hour}, "
                                            f"interval={slot.interval_min}, align={slot.align_minute}"
                                        )
                                    wakeup_info["scheduled_wakeup"] = {
                                        "offset_sec": wc.scheduled_wakeup.offset_sec,
                                        "time_slots": [
                                            {
                                                "start_hour": slot.start_hour,
                                                "end_hour": slot.end_hour,
                                                "interval_min": slot.interval_min,
                                                "align_minute": slot.align_minute,
                                            }
                                            for slot in wc.scheduled_wakeup.time_slots
                                        ],
                                    }
                                if wc.HasField("wakeup_window"):
                                    ww = wc.wakeup_window
                                    lines += [
                                        f"window.startup_delay_sec: {ww.startup_delay_sec}",
                                        f"window.random_delay_max_sec: {ww.random_delay_max_sec}",
                                        f"window.gateway_wait_sec: {ww.gateway_wait_sec}",
                                        f"window.final_wait_sec: {ww.final_wait_sec}",
                                        f"window.degraded_window_sec: {ww.degraded_window_sec}",
                                        f"window.factory_window_sec: {ww.factory_window_sec}",
                                    ]
                                    wakeup_info["wakeup_window"] = {
                                        "startup_delay_sec": ww.startup_delay_sec,
                                        "random_delay_max_sec": ww.random_delay_max_sec,
                                        "gateway_wait_sec": ww.gateway_wait_sec,
                                        "final_wait_sec": ww.final_wait_sec,
                                        "degraded_window_sec": ww.degraded_window_sec,
                                        "factory_window_sec": ww.factory_window_sec,
                                    }
                                if from_id_pc:
                                    self._nodes.setdefault(from_id_pc, {"node_id": from_id_pc})[
                                        "sync_wakeup_config"
                                    ] = wakeup_info
                                    self._refresh_node_info_dock()
                                self.send_panel.log_result(
                                    True, "SyncWakeupConfig:\n" + "\n".join(lines))
                            elif which_up == "device_labels":
                                labels = list(uplink.device_labels.info_labels)
                                from_id_pc = data.get("from_id", "")
                                label_info = [
                                    {"id": l.id, "key": l.key, "value": l.value}
                                    for l in labels
                                ]
                                if from_id_pc:
                                    self._nodes.setdefault(from_id_pc, {"node_id": from_id_pc})[
                                        "device_labels"
                                    ] = label_info
                                    self._refresh_node_info_dock()
                                if labels:
                                    rows = [f"  [{l.id}] {l.key} = {l.value}" for l in labels]
                                    self.send_panel.log_result(
                                        True, f"DeviceLabels ({len(labels)}):\n" + "\n".join(rows))
                                else:
                                    self.send_panel.log_result(True, "DeviceLabels: empty")
                            elif which_up == "operation_result":
                                result = uplink.operation_result
                                operation_names = {
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
                                status_names = {
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
                                lines = [
                                    f"operation: {operation_names.get(result.operation, result.operation)}",
                                    f"status: {status_names.get(result.status, result.status)}",
                                    f"request_id: 0x{result.request_id:08X}",
                                    f"target_node_id: !{result.target_node_id:08x}",
                                    f"source_node_id: !{result.source_node_id:08x}",
                                    f"gateway_node_id: !{result.gateway_node_id:08x}",
                                    f"operation_timestamp: {result.operation_timestamp}",
                                ]
                                if result.message:
                                    lines.append(f"message: {result.message}")
                                from_id_pc = data.get("from_id", "")
                                result_info = {
                                    "operation": operation_names.get(result.operation, result.operation),
                                    "status": status_names.get(result.status, result.status),
                                    "request_id": f"0x{result.request_id:08X}",
                                    "target_node_id": f"!{result.target_node_id:08x}",
                                    "source_node_id": f"!{result.source_node_id:08x}",
                                    "gateway_node_id": f"!{result.gateway_node_id:08x}",
                                    "operation_timestamp": result.operation_timestamp,
                                    "message": result.message,
                                }
                                result_node_ids = []
                                if from_id_pc:
                                    result_node_ids.append(from_id_pc)
                                if result.target_node_id:
                                    target_node_id = result_info["target_node_id"]
                                    if target_node_id not in result_node_ids:
                                        result_node_ids.append(target_node_id)
                                for result_node_id in result_node_ids:
                                    self._nodes.setdefault(result_node_id, {"node_id": result_node_id})[
                                        "last_operation_result"
                                    ] = dict(result_info)
                                if result_node_ids:
                                    target_info = self._nodes.get(result_info["target_node_id"]) or self._nodes.get(result_node_ids[0], {})
                                    join_summary = self._node_join_summary(target_info)
                                    lines.append(
                                        f"join_state: {join_summary.get('state')} ({join_summary.get('reason')})"
                                    )
                                    self._refresh_nodes_status()
                                    self._refresh_node_info_dock()
                                ok_status = result.status in (1, 2, 3, 4)
                                self.send_panel.log_result(
                                    ok_status, "OperationResult:\n" + "\n".join(lines))
                        if which_pkt == "response":
                            resp = pkt_pc.response
                            which_resp = resp.WhichOneof("payload")
                            if which_resp == "private_config":
                                cfg = resp.private_config
                                lines = [f"deviceName: {cfg.deviceName}",
                                         f"isAdminKeySet: {cfg.isAdminKeySet}",
                                         f"privateVersion: 0x{cfg.privateVersion:08X}"]
                                if cfg.HasField("company_config"):
                                    cc = cfg.company_config
                                    lines += [
                                        f"is_enrolled: {cc.is_enrolled}",
                                        f"legacy_global_pub: {bytes(cc.company_public_key).hex()}",
                                        f"last_change_ts: {cc.last_change_timestamp}",
                                    ]
                                if cfg.HasField("sync_wakeup"):
                                    wc = cfg.sync_wakeup
                                    lines.append(
                                        f"sync_wakeup: enabled={wc.enabled}, "
                                        f"interval={wc.fixed_wakeup.interval_min}min"
                                    )
                                self.send_panel.log_result(
                                    True, "PrivateConfig 响应:\n" + "\n".join(lines))
                            elif which_resp == "device_labels":
                                labels = list(resp.device_labels.info_labels)
                                if labels:
                                    rows = [f"  [{l.id}] {l.key} = {l.value}" for l in labels]
                                    self.send_panel.log_result(
                                        True, f"DeviceLabels ({len(labels)}条):\n" + "\n".join(rows))
                                else:
                                    self.send_panel.log_result(True, "DeviceLabels: 暂无标签")
                            elif which_resp == "sync_wakeup_config":
                                wc = resp.sync_wakeup_config
                                self.send_panel.log_result(
                                    True,
                                    f"SyncWakeupConfig: enabled={wc.enabled}, "
                                    f"strategy={wc.strategy}, "
                                    f"interval={wc.fixed_wakeup.interval_min}min, "
                                    f"align={wc.fixed_wakeup.align_minute}min, "
                                    f"offset={wc.fixed_wakeup.offset_sec}s")
                            elif which_resp == "company_config":
                                cc = resp.company_config
                                self.send_panel.log_result(
                                    True,
                                    f"LegacyGlobalConfig: enrolled={cc.is_enrolled}, "
                                    f"legacy_pub={bytes(cc.company_public_key).hex()}, "
                                    f"last_change_ts={cc.last_change_timestamp}")
                    except Exception as _exc_pc:
                        self.send_panel.log_result(False, f"解析 PRIVATE_CONFIG 响应失败: {_exc_pc}")

        if self._nodes:
            self._capture_call(self._capture.write_nodes_snapshot, self._nodes, self._my_node_id)

    def _on_send_requested(self, packet):
        if not self._worker or not self._worker.is_running():
            self.send_panel.log_result(False, "串口未连接")
            return

        # ── Admin 自动化（参考官方 node.py _sendAdmin）─────────────────────
        if packet.decoded.portnum == 6:   # ADMIN_APP
            # want_ack 由 UI 勾选框决定，此处不强制覆盖
            # 自动注入目标节点的 session_passkey（有效期 270s，留 30s 余量）
            to_nid_str = f"!{packet.to:08x}"
            pk_entry = self._admin_passkeys.get(to_nid_str)
            if pk_entry:
                pk_bytes, pk_ts = pk_entry
                if time.monotonic() - pk_ts < 270:
                    try:
                        from meshtastic import admin_pb2
                        adm = admin_pb2.AdminMessage()
                        adm.ParseFromString(packet.decoded.payload)
                        if not adm.session_passkey:   # 用户未手动填写时才注入
                            adm.session_passkey = pk_bytes
                            packet.decoded.payload = adm.SerializeToString()
                    except Exception:
                        pass

        success, frame_hex = self._worker.send_packet(packet)

        from_id = f"!{getattr(packet, 'from'):08x}" if getattr(packet, 'from', 0) else "本机"
        to_id   = "broadcast" if packet.to == 0xFFFF_FFFF else f"!{packet.to:08x}"
        try:
            from meshdebug.proto_parser import portnum_to_name
            pname = portnum_to_name(packet.decoded.portnum)
        except Exception:
            pname = str(packet.decoded.portnum)

        summary = f"{pname}  {from_id} → {to_id}  ch={packet.channel}  id={packet.id}"

        # ── 记录待响应请求（want_response=True 时追踪）──────────────────────
        if success and packet.decoded.want_response:
            self._pending_requests[packet.id] = {
                "summary": summary,
                "portnum": packet.decoded.portnum,
            }

        # 帧 hex 按每行 16 字节分组显示
        hex_lines = [frame_hex[i:i+32] for i in range(0, len(frame_hex), 32)]
        hex_display = "<br>".join(
            " ".join(ln[j:j+2] for j in range(0, len(ln), 2))
            for ln in hex_lines
        )

        # AdminMessage payload hex（portnum=6 时附加）
        admin_hex = ""
        if packet.decoded.portnum == 6:
            admin_hex = (
                f"<br><span style='color:#888;font-size:10px;'>"
                f"AdminMessage: {packet.decoded.payload.hex()}</span>"
            )

        if success:
            from meshdebug.proto_parser import parse_mesh_packet
            try:
                packet_dict = parse_mesh_packet(packet)
            except Exception:
                packet_dict = {}
            self._capture_call(self._capture.record_sent_frame, packet_dict, frame_hex, summary=summary)
            self.send_panel.update_sent_detail(packet_dict, frame_hex)
            self.send_panel.log_result(
                True,
                f"{summary}"
                f"<br><span style='color:#555;font-family:Consolas;font-size:10px;'>"
                f"Frame: {hex_display}</span>"
                f"{admin_hex}"
            )
        else:
            self.send_panel.log_result(False, "写串口失败，请检查连接")

    def _toggle_send_dock(self, checked: bool):
        self._send_dock.setVisible(checked)

    # ── 节点维护 ──────────────────────────────────────────────────────────────

    def _update_nodes(self, frame: dict):
        variant = frame.get("variant", "")
        data    = frame.get("data") or {}

        if variant == "my_info":
            nid = data.get("node_id", "")
            if nid:
                self._nodes.setdefault(nid, {}).update({"node_id": nid, "long_name": "本机"})
                self._my_node_id = nid
                self.send_panel.set_local_node(nid)
                self.vi_gw_id_lbl.setText(nid)
                self._refresh_nodes_status()
                self._refresh_node_info_dock()

        elif variant == "node_info":
            nid = data.get("node_id", "")
            if nid:
                user = data.get("user", {}) or {}
                pk_raw = user.get("public_key", "")
                if isinstance(pk_raw, str) and pk_raw:
                    try:
                        import base64 as _b64
                        pub_key = _b64.b64decode(pk_raw)
                    except Exception:
                        pub_key = b""
                elif isinstance(pk_raw, (bytes, bytearray)):
                    pub_key = bytes(pk_raw)
                else:
                    pub_key = b""
                self._nodes.setdefault(nid, {}).update({
                    "node_id":    nid,
                    "long_name":  user.get("long_name", ""),
                    "short_name": user.get("short_name", ""),
                    "public_key": pub_key,
                    "user":       user,
                })
                # 如果是本机节点，同步更新网关公钥显示
                if nid == self._my_node_id and pub_key:
                    import base64 as _b64
                    self.vi_gw_pub_lbl.setText(_b64.b64encode(pub_key).decode())
                self._refresh_nodes_status()
                self._refresh_node_info_dock()
                self.send_panel.update_nodes(self._nodes)

    # ── 节点信息 Dock ─────────────────────────────────────────────────────────

    def _build_node_info_dock(self):
        """创建节点列表/详情 Dock。"""
        self._ni_dock = QDockWidget("📋  节点列表", self)
        self._ni_dock.setObjectName("ni_dock")
        self._ni_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(4)
        # 工具栏行
        hbar = QHBoxLayout()
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setFixedHeight(24)
        btn_refresh.clicked.connect(self._refresh_node_info_dock)
        self._ni_copy_btn = QPushButton("📋 复制ID")
        self._ni_copy_btn.setFixedHeight(24)
        self._ni_copy_btn.setEnabled(False)
        self._ni_copy_btn.clicked.connect(self._on_ni_copy_id)
        self._ni_copy_summary_btn = QPushButton("复制汇总")
        self._ni_copy_summary_btn.setFixedHeight(24)
        self._ni_copy_summary_btn.setEnabled(False)
        self._ni_copy_summary_btn.setToolTip("复制当前节点的 Meshtastic、Dragino、Network 和网关信息")
        self._ni_copy_summary_btn.clicked.connect(self._on_ni_copy_summary)
        self._ni_export_summary_btn = QPushButton("导出汇总")
        self._ni_export_summary_btn.setFixedHeight(24)
        self._ni_export_summary_btn.setEnabled(False)
        self._ni_export_summary_btn.setToolTip("把当前节点汇总导出为 Markdown 文件")
        self._ni_export_summary_btn.clicked.connect(self._on_ni_export_summary)
        self._ni_profile_btn = QPushButton("生成/绑定Key")
        self._ni_profile_btn.setFixedHeight(24)
        self._ni_profile_btn.setEnabled(False)
        self._ni_profile_btn.setToolTip("为当前选中节点生成并保存 FactoryIdentity device_private_key 和 Join V2 seed")
        self._ni_profile_btn.clicked.connect(self._on_ni_generate_profile)
        self._ni_save_device_identity_btn = QPushButton("保存设备身份")
        self._ni_save_device_identity_btn.setFixedHeight(24)
        self._ni_save_device_identity_btn.setEnabled(False)
        self._ni_save_device_identity_btn.setToolTip("把 Get Factory Identity 回来的 SN/DevEUI/device_private_key 保存到本地档案")
        self._ni_save_device_identity_btn.clicked.connect(self._on_ni_save_device_identity_profile)
        self._ni_clear_profile_btn = QPushButton("清除Key")
        self._ni_clear_profile_btn.setFixedHeight(24)
        self._ni_clear_profile_btn.setEnabled(False)
        self._ni_clear_profile_btn.setToolTip("清除当前选中节点的本地 FactoryIdentity 档案")
        self._ni_clear_profile_btn.clicked.connect(self._on_ni_clear_profile)
        hbar.addWidget(btn_refresh)
        hbar.addWidget(self._ni_copy_btn)
        hbar.addWidget(self._ni_copy_summary_btn)
        hbar.addWidget(self._ni_export_summary_btn)
        hbar.addWidget(self._ni_profile_btn)
        hbar.addWidget(self._ni_save_device_identity_btn)
        hbar.addWidget(self._ni_clear_profile_btn)
        hbar.addStretch()
        vbox.addLayout(hbar)
        # 左列表 + 右详情
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._ni_list = QListWidget()
        self._ni_list.setMinimumWidth(150)
        self._ni_list.currentRowChanged.connect(self._on_ni_select)
        splitter.addWidget(self._ni_list)
        self._ni_detail = QTextEdit()
        self._ni_detail.setReadOnly(True)
        self._ni_detail.setPlaceholderText("点击节点查看详情")
        self._ni_detail.setMinimumWidth(240)
        self._ni_detail.setFont(QFont("Consolas", 10))
        splitter.addWidget(self._ni_detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        vbox.addWidget(splitter)
        self._ni_dock.setWidget(container)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._ni_dock)

    # ── FactoryIdentity 档案管理 Dock ────────────────────────────────────────

    def _build_factory_profile_dock(self):
        self._fp_dock = QDockWidget("🗂  FactoryIdentity 档案管理", self)
        self._fp_dock.setObjectName("fp_dock")
        self._fp_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(4)

        hbar = QHBoxLayout()
        self._fp_refresh_btn = QPushButton("刷新")
        self._fp_refresh_btn.setFixedHeight(24)
        self._fp_refresh_btn.clicked.connect(self._refresh_factory_profile_dock)
        self._fp_load_btn = QPushButton("加载到发送")
        self._fp_load_btn.setFixedHeight(24)
        self._fp_load_btn.setEnabled(False)
        self._fp_load_btn.clicked.connect(self._on_fp_load_profile)
        self._fp_copy_btn = QPushButton("复制档案")
        self._fp_copy_btn.setFixedHeight(24)
        self._fp_copy_btn.setEnabled(False)
        self._fp_copy_btn.clicked.connect(self._on_fp_copy_profile)
        self._fp_export_btn = QPushButton("导出档案")
        self._fp_export_btn.setFixedHeight(24)
        self._fp_export_btn.setEnabled(False)
        self._fp_export_btn.clicked.connect(self._on_fp_export_profile)
        self._fp_delete_btn = QPushButton("删除档案")
        self._fp_delete_btn.setFixedHeight(24)
        self._fp_delete_btn.setEnabled(False)
        self._fp_delete_btn.clicked.connect(self._on_fp_delete_profile)
        self._fp_delete_all_btn = QPushButton("清空全部")
        self._fp_delete_all_btn.setFixedHeight(24)
        self._fp_delete_all_btn.clicked.connect(self._on_fp_delete_all_profiles)

        for btn in (
            self._fp_refresh_btn,
            self._fp_load_btn,
            self._fp_copy_btn,
            self._fp_export_btn,
            self._fp_delete_btn,
            self._fp_delete_all_btn,
        ):
            hbar.addWidget(btn)
        hbar.addStretch()
        vbox.addLayout(hbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._fp_list = QListWidget()
        self._fp_list.setMinimumWidth(260)
        self._fp_list.currentRowChanged.connect(self._on_fp_select)
        splitter.addWidget(self._fp_list)

        self._fp_detail = QTextEdit()
        self._fp_detail.setReadOnly(True)
        self._fp_detail.setPlaceholderText("选择一个本地档案查看详情")
        self._fp_detail.setMinimumWidth(360)
        self._fp_detail.setFont(QFont("Consolas", 10))
        splitter.addWidget(self._fp_detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        vbox.addWidget(splitter)

        self._fp_dock.setWidget(container)
        self._fp_dock.setVisible(False)
        self._fp_dock.visibilityChanged.connect(
            lambda v: self.btn_toggle_fp.setChecked(v) if hasattr(self, "btn_toggle_fp") else None
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._fp_dock)
        self._refresh_factory_profile_dock()

    def _refresh_node_info_dock(self):
        """重建节点列表（节点更新或 Admin 响应到达后调用）。"""
        if not hasattr(self, "_ni_list"):
            return
        prev_nid = None
        cur = self._ni_list.currentItem()
        if cur:
            prev_nid = cur.data(Qt.ItemDataRole.UserRole)
        self._ni_list.blockSignals(True)
        self._ni_list.clear()
        for nid, info in self._nodes.items():
            has_profile = bool(
                hasattr(self, "send_panel") and
                self.send_panel.get_factory_identity_profile(nid)
            )
            short = info.get("short_name", "")
            long_ = info.get("long_name", "")
            join_state = self._node_join_summary(info).get("state", "unknown")
            label = f"{nid}  [{short or long_ or '?'}]  <{join_state}>"
            if nid == self._my_node_id:
                label = "★ " + label
            if has_profile:
                label += f"  [{tr('档案')}]"
            item = QListWidgetItem(tr(label))
            item.setData(Qt.ItemDataRole.UserRole, nid)
            self._ni_list.addItem(item)
        self._ni_list.blockSignals(False)
        if prev_nid:
            for i in range(self._ni_list.count()):
                if self._ni_list.item(i).data(Qt.ItemDataRole.UserRole) == prev_nid:
                    self._ni_suppress_send_sync = True
                    try:
                        self._ni_list.setCurrentRow(i)
                    finally:
                        self._ni_suppress_send_sync = False
                    break

    def _current_factory_profile_id(self) -> str:
        if not hasattr(self, "_fp_list"):
            return ""
        cur = self._fp_list.currentItem()
        return cur.data(Qt.ItemDataRole.UserRole) if cur else ""

    def _profile_display_dict(self, profile: dict) -> dict:
        return self._node_factory_profile_summary(profile)

    def _profile_export_dict(self, profile: dict) -> dict:
        return dict(profile)

    def _refresh_factory_profile_dock(self):
        if not hasattr(self, "_fp_list"):
            return
        prev_nid = self._current_factory_profile_id()
        profiles = self.send_panel.list_factory_identity_profiles() if hasattr(self, "send_panel") else {}

        self._fp_list.blockSignals(True)
        self._fp_list.clear()
        for node_id in sorted(profiles):
            profile = profiles[node_id]
            sn = profile.get("sn") or "-"
            dev_eui = profile.get("dev_eui") or "-"
            has_seed_label = "seed" if profile.get("join_v2_network_seed") or profile.get("network_seed") else "no-seed"
            has_ch_label = "ch12" if profile.get("channel12") else "no-ch12"
            label = f"{node_id}  SN={sn}  EUI={dev_eui}  [{has_seed_label}/{has_ch_label}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, node_id)
            self._fp_list.addItem(item)
        self._fp_list.blockSignals(False)

        selected = False
        if prev_nid:
            for i in range(self._fp_list.count()):
                if self._fp_list.item(i).data(Qt.ItemDataRole.UserRole) == prev_nid:
                    self._fp_list.setCurrentRow(i)
                    selected = True
                    break
        if not selected:
            self._on_fp_select(-1)

    def _on_fp_select(self, row: int):
        for btn_name in ("_fp_load_btn", "_fp_copy_btn", "_fp_export_btn", "_fp_delete_btn"):
            if hasattr(self, btn_name):
                getattr(self, btn_name).setEnabled(False)
        if row < 0:
            if hasattr(self, "_fp_detail"):
                self._fp_detail.clear()
            return
        item = self._fp_list.item(row)
        if not item:
            return
        node_id = item.data(Qt.ItemDataRole.UserRole)
        profile = self.send_panel.get_factory_identity_profile(node_id) if hasattr(self, "send_panel") else None
        if not profile:
            self._fp_detail.clear()
            return
        self._fp_detail.setPlainText(json.dumps(self._profile_display_dict(profile), indent=2, ensure_ascii=False))
        self._fp_load_btn.setEnabled(True)
        self._fp_copy_btn.setEnabled(True)
        self._fp_export_btn.setEnabled(True)
        self._fp_delete_btn.setEnabled(True)

    def _on_fp_load_profile(self):
        node_id = self._current_factory_profile_id()
        if not node_id:
            return
        if self.send_panel.load_factory_identity_profile_for_node(node_id):
            self.send_panel.select_node(node_id, set_to=True)
            self.send_panel.update_nodes(self._nodes)
            self._select_node_info_item(node_id)
            QMessageBox.information(self, "已加载", f"已加载 {node_id} 的档案到发送面板。")

    def _on_fp_copy_profile(self):
        node_id = self._current_factory_profile_id()
        if not node_id:
            return
        profile = self.send_panel.get_factory_identity_profile(node_id)
        if not profile:
            return
        QApplication.clipboard().setText(json.dumps(self._profile_export_dict(profile), indent=2, ensure_ascii=False))
        QMessageBox.information(self, "已复制", f"已复制 {node_id} 的本地档案。")

    def _on_fp_export_profile(self):
        node_id = self._current_factory_profile_id()
        if not node_id:
            return
        profile = self.send_panel.get_factory_identity_profile(node_id)
        if not profile:
            return
        default_name = f"Dragino_FactoryIdentity_{node_id.lstrip('!')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 FactoryIdentity 档案",
            default_name,
            "JSON (*.json);;Text (*.txt);;All Files (*)",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._profile_export_dict(profile), f, indent=2, ensure_ascii=False)
        QMessageBox.information(self, "已导出", f"已导出 {node_id} 的本地档案。")

    def _delete_factory_profile(self, node_id: str, *, ask: bool = True) -> bool:
        if not node_id:
            return False
        if ask:
            ret = QMessageBox.question(
                self,
                "确认删除",
                f"确定删除 {node_id} 的本地 FactoryIdentity 档案吗？\n\n不会修改节点设备 Flash。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return False
        if not self.send_panel.clear_factory_identity_profile_for_node(node_id):
            return False
        self._refresh_node_info_dock()
        self._select_node_info_item(node_id)
        self._refresh_factory_profile_dock()
        return True

    def _on_fp_delete_profile(self):
        node_id = self._current_factory_profile_id()
        if self._delete_factory_profile(node_id, ask=True):
            QMessageBox.information(self, "已删除", f"已删除 {node_id} 的本地档案。")

    def _on_fp_delete_all_profiles(self):
        profiles = self.send_panel.list_factory_identity_profiles() if hasattr(self, "send_panel") else {}
        if not profiles:
            QMessageBox.information(self, "无档案", "当前没有保存的 FactoryIdentity 档案。")
            return
        ret = QMessageBox.question(
            self,
            "确认清空",
            f"确定删除全部 {len(profiles)} 个本地 FactoryIdentity 档案吗？\n\n不会修改任何节点设备 Flash。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        for node_id in list(profiles):
            self.send_panel.clear_factory_identity_profile_for_node(node_id)
        self._refresh_node_info_dock()
        self._refresh_factory_profile_dock()
        QMessageBox.information(self, "已清空", "已删除全部本地 FactoryIdentity 档案。")

    def _on_factory_profiles_changed(self):
        self._refresh_node_info_dock()
        self._refresh_factory_profile_dock()

    def _on_ni_select(self, row: int):
        """点击节点列表项，更新右侧详情。"""
        self._ni_copy_btn.setEnabled(False)
        self._ni_copy_summary_btn.setEnabled(False)
        self._ni_export_summary_btn.setEnabled(False)
        self._ni_profile_btn.setEnabled(False)
        self._ni_save_device_identity_btn.setEnabled(False)
        self._ni_clear_profile_btn.setEnabled(False)
        if row < 0:
            self._ni_detail.clear()
            return
        item = self._ni_list.item(row)
        if not item:
            return
        nid = item.data(Qt.ItemDataRole.UserRole)
        info = self._nodes.get(nid, {})
        profile_summary = {}
        if hasattr(self, "send_panel"):
            profile = self.send_panel.get_factory_identity_profile(nid)
            if profile:
                profile_summary = self._node_factory_profile_summary(profile)
        import base64 as _b64
        display: dict = {}
        for k, v in info.items():
            if k == "factory_identity_profile":
                continue
            if k == "factory_identity":
                display["factory_identity_status"] = self._device_factory_identity_status(v)
                continue
            if isinstance(v, (bytes, bytearray)):
                display[k] = _b64.b64encode(v).decode()
            elif isinstance(v, dict):
                if k == "user":
                    nested = dict(v)
                    nested.pop("public_key", None)
                    display[k] = nested
                else:
                    display[k] = v
            else:
                display[k] = v
        display["join_state_summary"] = self._node_join_summary(info)
        display["network_config_summary"] = self._node_network_config_summary(info)
        if profile_summary:
            display["local_factory_profile_status"] = profile_summary
        self._ni_detail.setPlainText(
            json.dumps(display, indent=2, ensure_ascii=False)
        )
        self._ni_copy_btn.setEnabled(True)
        self._ni_copy_summary_btn.setEnabled(True)
        self._ni_export_summary_btn.setEnabled(True)
        self._ni_profile_btn.setEnabled(True)
        self._ni_save_device_identity_btn.setEnabled(
            bool(self._factory_identity_cache.get(nid) or info.get("factory_identity"))
        )
        self._ni_clear_profile_btn.setEnabled(bool(profile_summary))
        if hasattr(self, "send_panel"):
            self.send_panel.select_node(nid, set_to=not self._ni_suppress_send_sync)

    def _current_node_info_id(self) -> str:
        if not hasattr(self, "_ni_list"):
            return ""
        cur = self._ni_list.currentItem()
        return cur.data(Qt.ItemDataRole.UserRole) if cur else ""

    def _node_factory_profile_summary(self, profile: dict) -> dict:
        device_private_key_b64 = profile.get("device_private_key", "") or profile.get("flash_private_key", "")
        device_public_key_b64 = profile.get("device_public_key", "") or profile.get("flash_public_key", "")
        if device_private_key_b64:
            try:
                from meshdebug.pki_crypto import public_key_from_private

                device_private_key = base64.b64decode(device_private_key_b64)
                if len(device_private_key) == 32:
                    device_public_key_b64 = base64.b64encode(public_key_from_private(device_private_key)).decode()
            except Exception:
                pass
        seed_b64 = profile.get("join_v2_network_seed", "") or profile.get("network_seed", "")
        channel12 = profile.get("channel12") or {}
        out = {
            "node_id": profile.get("node_id", ""),
            "sn": profile.get("sn", ""),
            "dev_eui": profile.get("dev_eui", ""),
        }
        if device_private_key_b64:
            out["device_private_key"] = device_private_key_b64
        if device_public_key_b64:
            out["device_public_key"] = device_public_key_b64
        if profile.get("legacy_app_key"):
            out["legacy_app_key"] = profile.get("legacy_app_key", "")
        if profile.get("legacy_app_key_hex"):
            out["legacy_app_key_hex"] = profile.get("legacy_app_key_hex", "")
        if seed_b64:
            out["join_v2_network_seed"] = seed_b64
        if channel12:
            out["channel12"] = channel12
        return out

    def _device_factory_identity_status(self, identity_info: dict) -> dict:
        if not identity_info:
            return {}
        out = {
            "factory_version": identity_info.get("factory_version", 0),
            "sn": identity_info.get("sn", ""),
            "dev_eui": identity_info.get("dev_eui", ""),
            "manufacturing_timestamp": identity_info.get("manufacturing_timestamp", 0),
            "status": identity_info.get("status", 0),
            "identity_crc": identity_info.get("identity_crc", ""),
        }
        if identity_info.get("device_private_key"):
            out["device_private_key"] = identity_info.get("device_private_key")
        if identity_info.get("device_public_key"):
            out["device_public_key"] = identity_info.get("device_public_key")
        if identity_info.get("legacy_app_key"):
            out["legacy_app_key"] = identity_info.get("legacy_app_key")
        if identity_info.get("legacy_app_key_hex"):
            out["legacy_app_key_hex"] = identity_info.get("legacy_app_key_hex")
        return out

    def _node_join_summary(self, info: dict) -> dict:
        if not isinstance(info, dict):
            info = {}

        op = info.get("last_operation_result") if isinstance(info.get("last_operation_result"), dict) else {}
        operation = str(op.get("operation", "")).upper()
        status = str(op.get("status", "")).upper()
        if operation == "JOIN_NETWORK_V2":
            if status in {"OK", "NO_CHANGE", "ALREADY_ENROLLED"}:
                return {"state": "joined", "reason": f"JOIN_NETWORK_V2/{status}"}
            if status == "PENDING_CHANNEL12":
                return {"state": "pending_join", "reason": f"JOIN_NETWORK_V2/{status}"}
            if status:
                return {"state": "not_joined", "reason": f"JOIN_NETWORK_V2/{status}"}

        network_config = info.get("network_config") if isinstance(info.get("network_config"), dict) else {}
        if network_config and (
            network_config.get("network_public_key")
            or network_config.get("network_seed")
            or network_config.get("trusted_gateway_sources")
        ):
            return {"state": "joined", "reason": "network_config captured"}

        join_lock = info.get("join_lock_advertise") if isinstance(info.get("join_lock_advertise"), dict) else {}
        if join_lock:
            return {"state": "not_joined", "reason": "join_lock_advertise"}

        return {"state": "unknown", "reason": "no join evidence"}

    def _node_network_config_summary(self, info: dict) -> dict:
        network_config = info.get("network_config") if isinstance(info.get("network_config"), dict) else {}
        if not network_config:
            return {"captured": False}

        network_public_key = str(network_config.get("network_public_key") or "")
        network_seed = str(network_config.get("network_seed") or "")
        return {
            "captured": True,
            "network_public_key_len": len(network_public_key) // 2 if network_public_key else 0,
            "network_seed_len": len(network_seed) // 2 if network_seed else 0,
            "last_change_timestamp": network_config.get("last_change_timestamp", 0),
            "is_single_gateway": bool(network_config.get("is_single_gateway")),
            "trusted_gateway_sources": list(network_config.get("trusted_gateway_sources") or []),
        }

    def _profile_from_device_identity_info(self, nid: str, identity_info: dict) -> dict:
        if not identity_info:
            raise ValueError("当前节点没有 Get Factory Identity 回包")
        device_private_key_b64 = identity_info.get("device_private_key", "")
        if not device_private_key_b64:
            raise ValueError("设备回包没有 device_private_key，不能保存成可用于入网的档案")
        profile = {
            "node_id": nid,
            "factory_version": int(identity_info.get("factory_version", 1) or 1),
            "sn": identity_info.get("sn", ""),
            "dev_eui": identity_info.get("dev_eui", ""),
            "device_private_key": device_private_key_b64,
            "device_public_key": identity_info.get("device_public_key", ""),
            "legacy_app_key": identity_info.get("legacy_app_key", ""),
            "legacy_app_key_hex": identity_info.get("legacy_app_key_hex", ""),
            "manufacturing_timestamp": int(identity_info.get("manufacturing_timestamp", 0) or time.time()),
            "status": int(identity_info.get("status", 1) or 1),
        }
        try:
            from meshdebug.pki_crypto import public_key_from_private

            device_private_key = base64.b64decode(device_private_key_b64)
            if len(device_private_key) == 32:
                profile["device_public_key"] = base64.b64encode(public_key_from_private(device_private_key)).decode()
        except Exception:
            pass
        existing = self.send_panel.get_factory_identity_profile(nid) if hasattr(self, "send_panel") else None
        if existing:
            for key in ("join_v2_network_seed", "network_seed", "channel12"):
                if key in existing:
                    profile[key] = existing[key]
        return profile

    def _save_factory_identity_from_device(self, nid: str, identity_info: dict, *, quiet: bool = False) -> dict | None:
        try:
            profile = self._profile_from_device_identity_info(nid, identity_info)
            saved = self.send_panel.save_factory_identity_profile(profile, select=True, apply=False)
            if not quiet:
                QMessageBox.information(self, "已保存", f"已把 {nid} 的设备 FactoryIdentity 保存到本地档案。")
            return saved
        except Exception as exc:
            if not quiet:
                QMessageBox.warning(self, "保存失败", str(exc))
            else:
                self.send_panel.log_result(False, f"保存设备 FactoryIdentity 档案失败: {exc}")
            return None

    def _json_ready(self, value):
        if isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
            return {
                "base64": base64.b64encode(raw).decode() if raw else "",
                "hex": raw.hex(),
                "len": len(raw),
            }
        if isinstance(value, dict):
            return {str(k): self._json_ready(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json_ready(v) for v in value]
        return value

    def _node_summary_dict(self, nid: str) -> dict:
        info = dict(self._nodes.get(nid, {}))
        profile_summary = {}
        if hasattr(self, "send_panel"):
            profile = self.send_panel.get_factory_identity_profile(nid)
            if profile:
                profile_summary = self._node_factory_profile_summary(profile)
        network_config = info.get("network_config") if isinstance(info.get("network_config"), dict) else {}
        join_lock = info.get("join_lock_advertise") if isinstance(info.get("join_lock_advertise"), dict) else {}
        join_summary = self._node_join_summary(info)
        network_config_summary = self._node_network_config_summary(info)
        direct_gateways = []
        if isinstance(network_config, dict):
            direct_gateways.extend(network_config.get("trusted_gateway_sources") or [])
        if not direct_gateways and hasattr(self, "send_panel"):
            gw_text = getattr(self.send_panel, "pc_na_gwid_edit", None)
            if gw_text:
                value = gw_text.text().strip()
                if value:
                    direct_gateways.append(value)
        if not direct_gateways and self._my_node_id:
            direct_gateways.append(self._my_node_id)

        return {
            "node_id": nid,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "meshtastic": {
                "node_id": info.get("node_id", nid),
                "long_name": info.get("long_name", ""),
                "short_name": info.get("short_name", ""),
                "public_key": self._json_ready(info.get("public_key", b"")),
                "user": self._json_ready({
                    k: v for k, v in (info.get("user", {}) or {}).items()
                    if k != "public_key"
                }),
                "owner": self._json_ready(info.get("owner", {})),
                "configs": self._json_ready(info.get("configs", {})),
                "module_configs": self._json_ready(info.get("module_configs", {})),
                "channels": self._json_ready(info.get("channels", {})),
            },
            "dragino": {
                "join_state_summary": self._json_ready(join_summary),
                "join_lock_advertise": self._json_ready(join_lock),
                "factory_identity_from_device": self._json_ready(
                    info.get("factory_identity_status")
                    or self._device_factory_identity_status(info.get("factory_identity", {}))
                ),
                "factory_identity_local_profile": self._json_ready(profile_summary),
                "network_config_summary": self._json_ready(network_config_summary),
                "network_config": self._json_ready(network_config),
                "sync_wakeup_config": self._json_ready(info.get("sync_wakeup_config", {})),
                "device_labels": self._json_ready(info.get("device_labels", [])),
                "last_operation_result": self._json_ready(info.get("last_operation_result", {})),
            },
            "network_identity": self._collect_global_identity_for_share(),
            "gateway": {
                "current_connected_gateway_node_id": self._my_node_id,
                "current_connected_gateway_public_key": self._json_ready(
                    self._nodes.get(self._my_node_id, {}).get("public_key", b"")
                ),
                "direct_gateways": direct_gateways,
            },
        }

    def _format_node_summary_markdown(self, nid: str) -> str:
        summary = self._node_summary_dict(nid)
        safe_json = json.dumps(summary, indent=2, ensure_ascii=False)
        node = summary["meshtastic"]
        join_lock = summary["dragino"].get("join_lock_advertise", {})
        profile = summary["dragino"].get("factory_identity_local_profile", {})
        netcfg = summary["dragino"].get("network_config", {})
        join_state = summary["dragino"].get("join_state_summary", {})
        netcfg_summary = summary["dragino"].get("network_config_summary", {})
        gateway = summary["gateway"]
        lines = [
            f"# Dragino Node Summary {nid}",
            "",
            "## Quick Info",
            f"- node_id: {nid}",
            f"- long_name: {node.get('long_name', '')}",
            f"- short_name: {node.get('short_name', '')}",
            f"- SN: {profile.get('sn') or join_lock.get('sn', '')}",
            f"- DevEUI: {profile.get('dev_eui') or join_lock.get('dev_eui', '')}",
            f"- join_state: {join_state.get('state', 'unknown')}",
            f"- join_reason: {join_state.get('reason', '-')}",
            f"- direct_gateways: {', '.join(gateway.get('direct_gateways') or []) or '-'}",
            f"- current_connected_gateway: {gateway.get('current_connected_gateway_node_id') or '-'}",
            "",
            "## Network Identity",
        ]
        network_info = summary["network_identity"]
        for name in ("network_public_key", "network_private_key", "network_seed"):
            item = network_info.get(name, {})
            lines += [
                f"- {name}_len: {item.get('len', 0)}",
                f"- {name}_base64: `{item.get('base64', '')}`",
                f"- {name}_hex: `{item.get('hex', '')}`",
            ]
        lines += [
            "",
            "## Dragino Join / Factory",
            f"- local_profile: {bool(profile)}",
            f"- device_public_key: `{profile.get('device_public_key', '')}`",
            f"- device_private_key: `{profile.get('device_private_key', '')}`",
            f"- legacy_app_key: `{profile.get('legacy_app_key', '')}`",
            f"- legacy_app_key_hex: `{profile.get('legacy_app_key_hex', '')}`",
            f"- join_challenge: `{join_lock.get('join_challenge', '')}`",
            f"- join_v2_network_seed: `{profile.get('join_v2_network_seed', '')}`",
            "",
            "## Channel / Network",
            f"- network_public_key: `{netcfg.get('network_public_key', '')}`",
            f"- network_public_key_len: {netcfg_summary.get('network_public_key_len', 0)}",
            f"- network_seed_len: {netcfg_summary.get('network_seed_len', 0)}",
            f"- last_change_timestamp: {netcfg_summary.get('last_change_timestamp', 0)}",
            f"- trusted_gateway_sources: {', '.join(netcfg.get('trusted_gateway_sources') or []) or '-'}",
            f"- is_single_gateway: {netcfg.get('is_single_gateway', '')}",
            f"- channel12: `{json.dumps(profile.get('channel12', {}), ensure_ascii=False)}`",
            "",
            "## Full JSON",
            "```json",
            safe_json,
            "```",
            "",
            "note: 测试阶段共享用，正式客户交付时不要明文外发 network_private_key / device_private_key / legacy_app_key。",
        ]
        return "\n".join(lines)

    def _on_ni_generate_profile(self):
        nid = self._current_node_info_id()
        if not nid:
            QMessageBox.warning(self, "未选择节点", "请先在节点列表中选择一个节点。")
            return

        existing = self.send_panel.get_factory_identity_profile(nid)
        overwrite = True
        if existing and (existing.get("device_private_key") or existing.get("flash_private_key")):
            ret = QMessageBox.question(
                self,
                "已有本地档案",
                f"{nid} 已有 FactoryIdentity 本地档案。\n\n"
                "选择“是”会重新生成并覆盖该节点的 device_private_key 和 Join V2 seed。\n"
                "选择“否”只加载已有档案到发送面板。",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Cancel:
                return
            if ret == QMessageBox.StandardButton.No:
                if self.send_panel.load_factory_identity_profile_for_node(nid):
                    self._refresh_node_info_dock()
                    self._select_node_info_item(nid)
                    QMessageBox.information(self, "已加载", f"已加载 {nid} 的本地档案到发送面板。")
                return
            overwrite = True

        try:
            network_seed_b64 = self._vi_current_network_seed_b64()
        except Exception as exc:
            QMessageBox.warning(self, "network_seed 错误", str(exc))
            return
        if not network_seed_b64:
            QMessageBox.warning(
                self,
                "缺少 network_seed",
                "请先在 Network 密钥配置界面生成网络随机种子并保存，然后再为节点生成/绑定 Key。",
            )
            return

        info = self._nodes.get(nid, {})
        join_lock = info.get("join_lock_advertise", {}) if isinstance(info.get("join_lock_advertise"), dict) else {}
        try:
            profile = self.send_panel.generate_factory_identity_profile_for_node(
                nid,
                sn=join_lock.get("sn", ""),
                dev_eui=join_lock.get("dev_eui", ""),
                network_seed_b64=network_seed_b64,
                overwrite=overwrite,
            )
        except Exception as exc:
            QMessageBox.warning(self, "生成失败", str(exc))
            return

        self._refresh_node_info_dock()
        self._select_node_info_item(nid)
        self.send_panel.update_nodes(self._nodes)
        self.send_panel.select_node(nid)
        QMessageBox.information(
            self,
            "已生成",
            f"已为 {nid} 生成并绑定 FactoryIdentity 本地档案。\n"
            "切到发送面板后，收到该节点 JoinLock 时可直接使用“填充 JoinLock”。",
        )

    def _on_ni_save_device_identity_profile(self):
        nid = self._current_node_info_id()
        if not nid:
            QMessageBox.warning(self, "未选择节点", "请先在节点列表中选择一个节点。")
            return
        info = self._nodes.get(nid, {})
        identity_info = self._factory_identity_cache.get(nid)
        if not identity_info and isinstance(info.get("factory_identity"), dict):
            identity_info = info.get("factory_identity")
        saved = self._save_factory_identity_from_device(nid, identity_info, quiet=False)
        if saved:
            self._refresh_node_info_dock()
            self._select_node_info_item(nid)
            self._refresh_factory_profile_dock()

    def _on_ni_clear_profile(self):
        nid = self._current_node_info_id()
        if not nid:
            QMessageBox.warning(self, "未选择节点", "请先在节点列表中选择一个节点。")
            return

        existing = self.send_panel.get_factory_identity_profile(nid)
        if not existing:
            self._refresh_node_info_dock()
            self._select_node_info_item(nid)
            QMessageBox.information(self, "无本地档案", f"{nid} 当前没有保存的 FactoryIdentity 本地档案。")
            return

        ret = QMessageBox.question(
            self,
            "确认清除",
            f"确定清除 {nid} 的本地 FactoryIdentity 档案吗？\n\n"
            "会删除 Debug 程序本地保存的 device_private_key、Join V2 seed 和 Channel1/2 派生配置。\n"
            "不会修改节点设备 Flash，也不会删除节点列表中的 NodeInfo。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        if not self._delete_factory_profile(nid, ask=False):
            QMessageBox.warning(self, "清除失败", f"没有找到 {nid} 的本地档案。")
            return
        QMessageBox.information(self, "已清除", f"已清除 {nid} 的本地 FactoryIdentity 档案。")

    def _select_node_info_item(self, nid: str) -> bool:
        if not hasattr(self, "_ni_list"):
            return False
        for i in range(self._ni_list.count()):
            if self._ni_list.item(i).data(Qt.ItemDataRole.UserRole) == nid:
                self._ni_list.setCurrentRow(i)
                return True
        return False

    def _on_ni_copy_id(self):
        """复制当前选中节点的 ID 到剪贴板。"""
        cur = self._ni_list.currentItem()
        if cur:
            nid = cur.data(Qt.ItemDataRole.UserRole)
            QApplication.clipboard().setText(nid)

    def _on_ni_copy_summary(self):
        nid = self._current_node_info_id()
        if not nid:
            return
        QApplication.clipboard().setText(self._format_node_summary_markdown(nid))
        QMessageBox.information(self, "已复制", f"已复制 {nid} 的节点汇总到剪贴板。")

    def _on_ni_export_summary(self):
        nid = self._current_node_info_id()
        if not nid:
            return
        default_name = f"Dragino_Node_{nid.lstrip('!')}_summary.md"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出节点汇总",
            default_name,
            "Markdown (*.md);;Text (*.txt);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._format_node_summary_markdown(nid))
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "已导出", f"节点汇总已导出到：\n{path}")

    def _refresh_nodes_status(self):
        if not self._nodes:
            set_widget_text(self.lbl_nodes, "节点: —")
            return
        parts = []
        joined = 0
        pending = 0
        not_joined = 0
        unknown = 0
        for n in list(self._nodes.values())[:5]:
            name = n.get("long_name") or n.get("short_name") or ""
            nid  = n.get("node_id", "")
            parts.append(f"{nid} [{name}]" if name else nid)
        for node in self._nodes.values():
            state = self._node_join_summary(node).get("state", "unknown")
            if state == "joined":
                joined += 1
            elif state == "pending_join":
                pending += 1
            elif state == "not_joined":
                not_joined += 1
            else:
                unknown += 1
        text = f"节点: {joined}已入网 / {not_joined}未入网 / {pending}等待中 / {unknown}未知"
        if parts:
            text += "  |  " + "  |  ".join(parts)
        if len(self._nodes) > 5:
            text += f"  +{len(self._nodes)-5}…"
        set_widget_text(self.lbl_nodes, text)

    # ── 清空 & 速率 ───────────────────────────────────────────────────────────

    def _clear_all(self):
        self.frame_table.clear_all()
        self.detail_panel.clear()
        self._frame_count = 0
        self._recent_ts.clear()
        self._nodes.clear()
        self._factory_identity_cache.clear()
        set_widget_text(self.lbl_frames, "帧数: 0")
        set_widget_text(self.lbl_nodes, "节点: —")
        self.send_panel.update_nodes({})

    def _update_rate(self):
        now    = time.monotonic()
        recent = [t for t in self._recent_ts if now - t <= 5.0]
        if len(recent) >= 2:
            rate = len(recent) / (recent[-1] - recent[0] + 0.001)
        else:
            rate = 0.0
        set_widget_text(self.lbl_frames, f"帧数: {self._frame_count}  |  {rate:.1f} 帧/秒")

    # ── 状态栏辅助 ────────────────────────────────────────────────────────────

    def _set_status(self, level: str, text: str):
        color = {
            "ok":         "#6fcf97",
            "off":        "#666",
            "connecting": "#ffd580",
            "error":      "#ff8a80",
        }.get(level, "#aaa")
        set_widget_text(self.lbl_status, text)
        self.lbl_status.setStyleSheet(f"color: {color}; padding: 0 8px;")

    # ── 关闭 ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop()
            self._worker.wait(3000)
        self._capture_call(self._capture.stop_session)
        event.accept()


# ─── 入口函数 ─────────────────────────────────────────────────────────────────

def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("MeshDebug")
    app.setFont(QFont("Segoe UI", 10))
    load_language()
    install_messagebox_i18n()
    install_filedialog_i18n()

    win = MainWindow()
    win.show()
    sys.exit(app.exec())
