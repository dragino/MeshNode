"""
meshdebug/widgets/frame_table.py
帧列表 Widget，封装 QTableWidget 的颜色、行插入、过滤等逻辑。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

from meshdebug.i18n import tr

# variant → (背景色, 前景色)
VARIANT_STYLE: dict[str, tuple[str, str]] = {
    "packet":             ("#1e4d2b", "#a8e6b8"),
    "node_info":          ("#1a3a5c", "#8cc8f0"),
    "my_info":            ("#1a3a5c", "#8cc8f0"),
    "config":             ("#4a3200", "#ffd580"),
    "channel":            ("#3d2f00", "#ffc940"),
    "moduleConfig":       ("#3d2800", "#ffb74d"),
    "rebooted":           ("#5c1a1a", "#ff8a80"),
    "config_complete_id": ("#2d2d2d", "#aaaaaa"),
    "log_record":         ("#1a1a1a", "#999999"),
    "queueStatus":        ("#2d3436", "#b2bec3"),
    "metadata":           ("#1e3040", "#81d4fa"),
}
DEFAULT_STYLE = ("#2d3436", "#dfe6e9")

MAX_ROWS = 2000   # 保留帧上限


class FrameTable(QTableWidget):
    """
    帧列表表格。

    Signals
    -------
    frame_selected(dict) : 用户点击某行时发射，携带该帧 dict
    """

    frame_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["#", tr("时间"), tr("类型"), "PortNum", tr("摘要")])
        self.horizontalHeader().setStretchLastSection(True)
        self.setColumnWidth(0, 55)
        self.setColumnWidth(1, 105)
        self.setColumnWidth(2, 100)
        self.setColumnWidth(3, 155)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setShowGrid(True)
        self.setStyleSheet(
            "QTableWidget { background: #1a1a1a; color: #dfe6e9; "
            "               gridline-color: #333; border: none; }"
            "QTableWidget::item:selected { background: #2a4a7a; }"
            "QHeaderView::section { background: #252525; color: #aaa; "
            "                       border: none; border-right: 1px solid #3d3d3d; "
            "                       padding: 4px 8px; }"
        )
        self.currentItemChanged.connect(self._on_item_changed)

        # 全量帧列表（用于过滤重建）
        self._all_frames: list[dict] = []
        self._current_filter = ""
        self._row_count = 0    # 全局帧序号

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def retranslate(self):
        self.setHorizontalHeaderLabels(["#", tr("时间"), tr("类型"), "PortNum", tr("摘要")])
        self._rebuild()

    def append_frame(self, frame: dict):
        """追加一帧到全量列表，若通过过滤则插入表格行。"""
        self._row_count += 1
        frame["_seq"] = self._row_count   # 注入序号
        self._all_frames.append(frame)

        if self._passes_filter(frame):
            self._insert_row(frame, self.rowCount() + 1)

        # 超出上限时裁剪
        if len(self._all_frames) > MAX_ROWS:
            self._all_frames.pop(0)
            # 删除表格最旧行（若在过滤范围内）
            if self.rowCount() > 0:
                self.removeRow(0)

    def set_filter(self, variant: str):
        """切换过滤器，重建表格。"""
        self._current_filter = variant
        self._rebuild()

    def clear_all(self):
        """清空所有帧和节点数据。"""
        self.setRowCount(0)
        self._all_frames.clear()
        self._row_count = 0

    def scroll_to_bottom(self):
        self.scrollToBottom()

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _passes_filter(self, frame: dict) -> bool:
        if not self._current_filter:
            return True
        return frame.get("variant", "") == self._current_filter

    def _insert_row(self, frame: dict, display_seq: int):
        variant  = frame.get("variant", "")
        ts_full  = frame.get("received_at", "")
        ts_short = ts_full[11:23] if len(ts_full) >= 23 else ts_full

        bg_hex, fg_hex = VARIANT_STYLE.get(variant, DEFAULT_STYLE)
        bg = QColor(bg_hex)
        fg = QColor(fg_hex)

        row = self.rowCount()
        self.insertRow(row)

        def _cell(text: str) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            item.setBackground(bg)
            item.setForeground(fg)
            return item

        # 提取 PortNum 显示文本（只对 packet 变体有意义）
        portnum_text = ""
        if variant == "packet":
            decoded = (frame.get("data") or {}).get("decoded", {})
            if decoded:
                portnum_text = decoded.get("portnum_name", "encrypted")
            else:
                portnum_text = "encrypted"

        num_item = _cell(str(frame.get("_seq", display_seq)))
        num_item.setData(Qt.ItemDataRole.UserRole, frame)   # 帧 dict 存在第0列
        self.setItem(row, 0, num_item)
        self.setItem(row, 1, _cell(ts_short))
        self.setItem(row, 2, _cell(variant))
        self.setItem(row, 3, _cell(portnum_text))
        self.setItem(row, 4, _cell(tr(frame.get("summary", ""))))
        self.setRowHeight(row, 22)

    def _rebuild(self):
        """按当前过滤器重建表格。"""
        self.setRowCount(0)
        seq = 0
        for frame in self._all_frames:
            if self._passes_filter(frame):
                seq += 1
                self._insert_row(frame, seq)
        self.scrollToBottom()

    def _on_item_changed(self, current, _previous):
        if current is None:
            return
        frame = self.item(current.row(), 0)
        if frame:
            data = frame.data(Qt.ItemDataRole.UserRole)
            if data:
                self.frame_selected.emit(data)
