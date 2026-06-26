"""
meshdebug/widgets/serial_log_panel.py
串口文本日志面板 —— 显示设备输出的非 protobuf 纯文本内容（如 Serial.println 日志）。

与帧列表/详情面板完全独立，以 QDockWidget 形式嵌入 MainWindow 底部。
"""

from datetime import datetime, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from meshdebug.i18n import set_widget_text

_MAX_LINES  = 2000   # 超过此行数时裁剪
_TRIM_LINES = 500    # 每次裁剪时删除的最旧行数

_S_CLEAR = (
    "QPushButton { background:#2d2d2d; color:#ccc; border:1px solid #555; "
    "padding:2px 10px; border-radius:3px; font-size:11px; }"
    "QPushButton:hover { background:#3d3d3d; }"
)

_S_LOG = (
    "QPlainTextEdit {"
    "  background:#111111; color:#b0c4b1;"
    "  border:none;"
    "  font-family: Consolas, 'Courier New', monospace;"
    "  font-size: 11px;"
    "  selection-background-color: #2a4a7a;"
    "}"
)


class SerialLogPanel(QWidget):
    """
    串口文本日志面板。

    公开接口
    --------
    append_line(text: str)
        追加一行文本（由 SerialWorker.text_received 信号直接连接）。
    clear()
        清空面板。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._line_count = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 2)
        root.setSpacing(3)

        # ── 工具行 ────────────────────────────────────────────────────────────
        toolbar = QWidget()
        th = QHBoxLayout(toolbar)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(6)

        self._lbl_count = QLabel("0 行")
        self._lbl_count.setStyleSheet("color:#666; font-size:10px;")

        self._chk_timestamp = QCheckBox("时间戳")
        self._chk_timestamp.setChecked(False)
        self._chk_timestamp.setToolTip("在每行前面加上接收时间戳（设备日志自带时间时可关闭）")
        self._chk_timestamp.setStyleSheet("color:#aaa; font-size:11px;")

        self._chk_autoscroll = QCheckBox("自动滚动")
        self._chk_autoscroll.setChecked(True)
        self._chk_autoscroll.setStyleSheet("color:#aaa; font-size:11px;")

        btn_clear = QPushButton("清空")
        btn_clear.setStyleSheet(_S_CLEAR)
        btn_clear.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_clear.clicked.connect(self.clear)

        th.addWidget(QLabel("串口文本日志") )
        th.addStretch()
        th.addWidget(self._lbl_count)
        th.addWidget(self._chk_timestamp)
        th.addWidget(self._chk_autoscroll)
        th.addWidget(btn_clear)
        root.addWidget(toolbar)

        # 分隔线
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#2d2d2d;")
        root.addWidget(sep)

        # ── 日志文本区 ────────────────────────────────────────────────────────
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(_S_LOG)
        self._log.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._log.setMaximumBlockCount(0)   # 手动管理行数上限
        root.addWidget(self._log, stretch=1)

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def append_line(self, text: str):
        """追加一行，若时间戳开关启用则加前缀，超限时裁剪旧行。"""
        if self._chk_timestamp.isChecked():
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
            line = f"[{ts}]  {text}"
        else:
            line = text

        self._log.appendPlainText(line)
        self._line_count += 1

        # 超限裁剪（从顶部删除旧行）
        if self._line_count > _MAX_LINES:
            cursor = self._log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(_TRIM_LINES):
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()  # 删除行尾 \n
            self._line_count -= _TRIM_LINES

        set_widget_text(self._lbl_count, f"{self._line_count} 行")

        if self._chk_autoscroll.isChecked():
            self._log.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self):
        """清空日志。"""
        self._log.clear()
        self._line_count = 0
        set_widget_text(self._lbl_count, "0 行")
