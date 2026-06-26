import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from meshdebug import i18n
from meshdebug.widgets.frame_table import FrameTable

_QT_APP = QApplication.instance() or QApplication([])


class MeshDebugI18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.LANG_ZH)

    def test_exact_translation_to_english(self):
        self.assertEqual(i18n.tr("全部", i18n.LANG_EN), "All")
        self.assertEqual(i18n.tr("▶  发送", i18n.LANG_EN), "▶  Send")

    def test_dynamic_status_translation_to_english(self):
        self.assertEqual(
            i18n.tr("帧数: 12  |  2.5 帧/秒", i18n.LANG_EN),
            "Frames: 12 | 2.5 fps",
        )
        self.assertEqual(
            i18n.tr("节点: 1已入网 / 2未入网 / 3等待中 / 4未知", i18n.LANG_EN),
            "Nodes: 1 joined / 2 not joined / 3 pending / 4 unknown",
        )
        self.assertEqual(
            i18n.tr("⏳  正在连接 COM3…", i18n.LANG_EN),
            "⏳ Connecting to COM3...",
        )

    def test_language_preference_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "meshdebug_settings.json"
            with patch.object(i18n, "_SETTINGS_FILE", str(settings_path)):
                i18n.save_language(i18n.LANG_EN)
                i18n.set_language(i18n.LANG_ZH)

                self.assertEqual(i18n.load_language(), i18n.LANG_EN)

    def test_frame_table_filter_uses_stable_empty_all_value(self):
        table = type("FakeFrameTable", (), {})()

        table._current_filter = ""
        self.assertTrue(FrameTable._passes_filter(table, {"variant": "packet"}))
        self.assertTrue(FrameTable._passes_filter(table, {"variant": "node_info"}))

        table._current_filter = "packet"
        self.assertTrue(FrameTable._passes_filter(table, {"variant": "packet"}))
        self.assertFalse(FrameTable._passes_filter(table, {"variant": "node_info"}))

    def test_dynamic_widget_text_uses_current_language(self):
        label = QLabel()
        i18n.set_language(i18n.LANG_EN)

        i18n.set_widget_text(label, "帧数: 12  |  2.5 帧/秒")

        self.assertEqual(label.text(), "Frames: 12 | 2.5 fps")
        self.assertEqual(label.property("_i18n_source_text"), "帧数: 12  |  2.5 帧/秒")

    def test_remaining_send_panel_phrases_translate_to_english(self):
        samples = {
            "广播": "Broadcast",
            "填入 broadcast (!ffffffff)": "Fill broadcast (!ffffffff)",
            "本地档案，等待真实JoinLock": "local profile, waiting for real JoinLock",
            "真实JoinLock": "real JoinLock",
            "Gateway 模式不需要 SN/AuthCode；只需要 network_seed，发送时会自动使用空 auth_code。": (
                "Gateway mode does not need SN/AuthCode; only network_seed is required. "
                "An empty auth_code is used automatically when sending."
            ),
            "⚠ 主信道(index=0)只读，请选择索引 1-7！": (
                "⚠ Primary channel (index=0) is read-only; select index 1-7."
            ),
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(i18n.tr(source, i18n.LANG_EN), expected)

    def test_runtime_messages_translate_to_english(self):
        samples = {
            "节点: 1已入网 / 2未入网 / 3等待中 / 4未知  |  !aabbccdd [gw]": (
                "Nodes: 1 joined / 2 not joined / 3 pending / 4 unknown | !aabbccdd [gw]"
            ),
            "已复制 !aabbccdd 的节点汇总到剪贴板。": (
                "Copied node summary for !aabbccdd to the clipboard."
            ),
            "确定删除 !aabbccdd 的本地 FactoryIdentity 档案吗？\n\n不会修改节点设备 Flash。": (
                "Delete the local FactoryIdentity profile for !aabbccdd?\n\nThis will not modify node Flash."
            ),
            "写串口失败，请检查连接": "Serial write failed; check the connection",
            "DeviceLabels (2条):": "DeviceLabels (2):",
            "PrivateConfig 响应:": "PrivateConfig response:",
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(i18n.tr(source, i18n.LANG_EN), expected)


if __name__ == "__main__":
    unittest.main()
