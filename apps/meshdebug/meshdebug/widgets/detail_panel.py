"""
meshdebug/widgets/detail_panel.py
右侧帧详情面板：header + JSON / Raw Hex 两个 tab + 复制按钮。
"""

import json
from typing import Optional

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from meshdebug.widgets.json_highlighter import JsonHighlighter
from meshdebug.widgets.frame_table import VARIANT_STYLE, DEFAULT_STYLE
from meshdebug.i18n import set_widget_text, tr


class DetailPanel(QWidget):
    """帧详情面板：JSON 高亮显示 + 原始 Hex。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 标题行
        self.header_label = QLabel(tr("— 点击左侧列表查看帧详情 —"))
        self.header_label.setProperty("_i18n_source_text", "— 点击左侧列表查看帧详情 —")
        self.header_label.setStyleSheet(
            "color: #aaa; padding: 4px; font-size: 12px;"
        )
        layout.addWidget(self.header_label)

        # Tab：JSON / Hex
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #444; }"
            "QTabBar::tab { background: #2d2d2d; color: #ccc; padding: 4px 12px; }"
            "QTabBar::tab:selected { background: #3d3d3d; color: #fff; }"
        )

        mono = QFont("Consolas", 10)

        self.json_edit = QTextEdit()
        self.json_edit.setReadOnly(True)
        self.json_edit.setFont(mono)
        self.json_edit.setStyleSheet(
            "background: #1e1e1e; color: #d4d4d4; border: none;"
        )
        self._highlighter = JsonHighlighter(self.json_edit.document())

        self.hex_edit = QTextEdit()
        self.hex_edit.setReadOnly(True)
        self.hex_edit.setFont(mono)
        self.hex_edit.setStyleSheet(
            "background: #1a1a2e; color: #a0c4ff; border: none;"
        )

        self.tabs.addTab(self.json_edit, "JSON")
        self.tabs.addTab(self.hex_edit, "Raw Hex")
        layout.addWidget(self.tabs, stretch=1)

        # 复制按钮行
        btn_row = QHBoxLayout()
        self.btn_copy_json = QPushButton(tr("复制 JSON"))
        self.btn_copy_json.setProperty("_i18n_source_text", "复制 JSON")
        self.btn_copy_json.setStyleSheet(
            "QPushButton { background: #2d4a3e; color: #6fcf97; "
            "border: 1px solid #3d6b55; padding: 4px 12px; border-radius: 3px; }"
            "QPushButton:hover { background: #3d6b55; }"
        )
        self.btn_copy_hex = QPushButton(tr("复制 Hex"))
        self.btn_copy_hex.setProperty("_i18n_source_text", "复制 Hex")
        self.btn_copy_hex.setStyleSheet(
            "QPushButton { background: #1a2a4a; color: #8cc8f0; "
            "border: 1px solid #2a4a7a; padding: 4px 12px; border-radius: 3px; }"
            "QPushButton:hover { background: #2a4a7a; }"
        )
        btn_row.addWidget(self.btn_copy_json)
        btn_row.addWidget(self.btn_copy_hex)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.btn_copy_json.clicked.connect(self._copy_json)
        self.btn_copy_hex.clicked.connect(self._copy_hex)

        self._current_frame: Optional[dict] = None

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def show_frame(self, frame: dict):
        self._current_frame = frame
        variant = frame.get("variant", "")
        ts      = frame.get("received_at", "")
        summary = frame.get("summary", "")
        bg, fg  = VARIANT_STYLE.get(variant, DEFAULT_STYLE)

        set_widget_text(self.header_label, f"[{ts}]  {variant}  {summary}")
        self.header_label.setStyleSheet(
            f"background: {bg}; color: {fg}; padding: 6px; "
            f"font-size: 12px; border-radius: 3px;"
        )

        # JSON tab
        data = frame.get("data") or {}
        display = {
            "variant":     variant,
            "id":          frame.get("id"),
            "received_at": ts,
            **data,
        }
        self.json_edit.setPlainText(
            json.dumps(display, ensure_ascii=False, indent=2)
        )

        # Hex tab：每行 16 字节，每 8 字节加额外空格
        raw_hex = frame.get("raw_hex", "")
        groups  = [raw_hex[i:i+2] for i in range(0, len(raw_hex), 2)]
        lines   = []
        for i in range(0, len(groups), 16):
            chunk    = groups[i:i+16]
            hex_part = " ".join(chunk[:8]) + "  " + " ".join(chunk[8:])
            lines.append(f"{i:04x}:  {hex_part}")
        self.hex_edit.setPlainText("\n".join(lines))

    def clear(self):
        self._current_frame = None
        set_widget_text(self.header_label, "— 点击左侧列表查看帧详情 —")
        self.header_label.setStyleSheet("color: #aaa; padding: 4px; font-size: 12px;")
        self.json_edit.clear()
        self.hex_edit.clear()

    def retranslate(self):
        if self._current_frame:
            self.show_frame(self._current_frame)
        else:
            set_widget_text(self.header_label, "— 点击左侧列表查看帧详情 —")
        set_widget_text(self.btn_copy_json, "复制 JSON")
        set_widget_text(self.btn_copy_hex, "复制 Hex")

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _copy_json(self):
        if not self._current_frame:
            return
        data = self._current_frame.get("data") or {}
        display = {
            "variant":     self._current_frame.get("variant"),
            "id":          self._current_frame.get("id"),
            "received_at": self._current_frame.get("received_at"),
            **data,
        }
        QApplication.clipboard().setText(
            json.dumps(display, ensure_ascii=False, indent=2)
        )

    def _copy_hex(self):
        if self._current_frame:
            QApplication.clipboard().setText(
                self._current_frame.get("raw_hex", "")
            )
