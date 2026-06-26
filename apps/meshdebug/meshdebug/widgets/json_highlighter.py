"""
meshdebug/widgets/json_highlighter.py
QSyntaxHighlighter 实现的 JSON 语法着色器。
"""

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat


class JsonHighlighter(QSyntaxHighlighter):
    """为 QTextEdit 提供 JSON 语法着色。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        def _fmt(color: str, bold: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(700)
            return f

        # 规则顺序：key 在前（含冒号前缀），字符串值在后
        self._rules = [
            # JSON key（双引号字符串后跟冒号）
            (
                QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"\s*(?=:)'),
                _fmt("#56ccf2", bold=True),
            ),
            # 字符串值（不在 key 位置）
            (
                QRegularExpression(r':\s*"[^"\\]*(?:\\.[^"\\]*)*"'),
                _fmt("#6fcf97"),
            ),
            # 数字
            (
                QRegularExpression(r'\b-?\d+\.?\d*([eE][+-]?\d+)?\b'),
                _fmt("#f2994a"),
            ),
            # 布尔和 null
            (
                QRegularExpression(r'\b(true|false|null)\b'),
                _fmt("#bb87f7", bold=True),
            ),
            # 括号和逗号
            (
                QRegularExpression(r'[{}\[\],]'),
                _fmt("#778ca3"),
            ),
        ]

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
