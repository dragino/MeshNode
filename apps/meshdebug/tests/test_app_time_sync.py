import unittest
from unittest.mock import patch

from meshtastic import mesh_pb2

from meshdebug.app import (
    CUSTOM_TIMESYNC_PORTNUM,
    TIME_SYNC_DRIFT_THRESHOLD_SEC,
    TIME_SYNC_HOP_LIMIT,
    MainWindow,
)


class _FakeCheckBox:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _FakeWorker:
    def __init__(self):
        self.sent = []

    def is_running(self):
        return True

    def send_packet(self, packet):
        self.sent.append(packet)
        return True, "94c30000"


class _FakeCapture:
    def __init__(self):
        self.records = []

    def record_sent_frame(self, packet_dict, frame_hex, *, summary=""):
        self.records.append((packet_dict, frame_hex, summary))


class _FakeSendPanel:
    def __init__(self):
        self.logs = []

    def log_result(self, success, msg):
        self.logs.append((success, msg))


class MainWindowAutoTimeSyncTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow.__new__(MainWindow)
        self.window.chk_auto_time_sync = _FakeCheckBox(True)
        self.window._worker = _FakeWorker()
        self.window._capture = _FakeCapture()
        self.window.send_panel = _FakeSendPanel()
        self.window._nodes = {}
        self.window._my_node_id = "!50070e1b"
        self.window._time_sync_last_sent_at = {}
        self.window._time_sync_last_status = "ready"
        self.window._capture_call = lambda action, *args, **kwargs: action(*args, **kwargs)
        self.window._update_time_sync_status_label = lambda: None

    def _telemetry_frame(self, node_time):
        return {
            "variant": "packet",
            "data": {
                "from_id": "!50063009",
                "decoded": {
                    "portnum": 67,
                    "portnum_name": "TELEMETRY_APP",
                    "payload_parsed": {"time": node_time},
                },
            },
        }

    def _business_frame(self, node_time):
        return {
            "variant": "packet",
            "data": {
                "from_id": "!50063009",
                "decoded": {
                    "portnum": 290,
                    "portnum_name": "DRAGINO_BUSINESS_DATA_APP",
                    "payload_parsed": {
                        "has_utc_time": True,
                        "utc_time": node_time,
                    },
                },
            },
        }

    def test_build_time_sync_packet_uses_private_position_port(self):
        packet = self.window._build_time_sync_packet(1_785_000_000)
        pos = mesh_pb2.Position()
        pos.ParseFromString(packet.decoded.payload)

        self.assertEqual(packet.to, 0xFFFF_FFFF)
        self.assertEqual(packet.channel, 0)
        self.assertEqual(packet.decoded.portnum, CUSTOM_TIMESYNC_PORTNUM)
        self.assertEqual(packet.hop_limit, TIME_SYNC_HOP_LIMIT)
        self.assertEqual(packet.hop_start, TIME_SYNC_HOP_LIMIT)
        self.assertFalse(packet.want_ack)
        self.assertEqual(packet.priority, mesh_pb2.MeshPacket.Priority.Value("MAX"))
        self.assertEqual(pos.time, 1_785_000_000)
        self.assertEqual(pos.timestamp, 1_785_000_000)
        self.assertEqual(pos.location_source, 2)
        self.assertEqual(pos.fix_quality, 9)

    def test_auto_time_sync_disabled_does_not_send(self):
        self.window.chk_auto_time_sync = _FakeCheckBox(False)

        self.window._handle_auto_time_sync(self._telemetry_frame(1_785_000_500))

        self.assertEqual([], self.window._worker.sent)

    def test_small_drift_does_not_send(self):
        with patch("time.time", return_value=1_785_000_000), patch("time.monotonic", return_value=100.0):
            self.window._handle_auto_time_sync(
                self._telemetry_frame(1_785_000_000 + TIME_SYNC_DRIFT_THRESHOLD_SEC - 1)
            )

        self.assertEqual([], self.window._worker.sent)
        self.assertIn("last_time_sync_observation", self.window._nodes["!50063009"])

    def test_business_packet_utc_time_does_not_trigger_auto_sync(self):
        with patch("time.time", return_value=1_785_000_000), patch("time.monotonic", return_value=100.0):
            self.window._handle_auto_time_sync(self._business_frame(1_785_000_600))

        self.assertEqual([], self.window._worker.sent)
        self.assertNotIn("!50063009", self.window._nodes)

    def test_large_drift_sends_once_then_cools_down(self):
        with patch("time.time", return_value=1_785_000_000), patch("time.monotonic", return_value=100.0):
            self.window._handle_auto_time_sync(self._telemetry_frame(1_785_000_600))

        self.assertEqual(1, len(self.window._worker.sent))
        packet = self.window._worker.sent[0]
        pos = mesh_pb2.Position()
        pos.ParseFromString(packet.decoded.payload)
        self.assertEqual(pos.time, 1_785_000_000)

        with patch("time.time", return_value=1_785_000_010), patch("time.monotonic", return_value=120.0):
            self.window._handle_auto_time_sync(self._telemetry_frame(1_785_000_610))

        self.assertEqual(1, len(self.window._worker.sent))


if __name__ == "__main__":
    unittest.main()
