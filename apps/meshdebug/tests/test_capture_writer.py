import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from meshdebug.capture_writer import CaptureWriter


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _db_rows(root: str, query: str, params=()):
    conn = sqlite3.connect(str(Path(root) / "meshdebug_capture.db"))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def _db_value(root: str, query: str, params=()):
    rows = _db_rows(root, query, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


class CaptureWriterTests(unittest.TestCase):
    def test_disabled_writer_creates_root_but_does_not_write_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = CaptureWriter(tmp)

            writer.record_received_frame({"id": 1, "variant": "packet", "raw_hex": "abcd"})

            self.assertTrue((Path(tmp) / "sessions").exists())
            self.assertTrue((Path(tmp) / "meshdebug_capture.db").exists())
            self.assertFalse(list((Path(tmp) / "sessions").iterdir()))
            self.assertEqual(_db_value(tmp, "SELECT COUNT(*) FROM capture_sessions;"), 0)
            self.assertEqual(_db_value(tmp, "SELECT COUNT(*) FROM capture_records;"), 0)

    def test_enabled_writer_records_session_frame_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = CaptureWriter(tmp)
            writer.set_enabled(True, port="COM7", baudrate=115200)

            writer.record_received_frame(
                {
                    "id": 11,
                    "variant": "packet",
                    "received_at": "2026-06-22T00:00:00.000Z",
                    "summary": "hello",
                    "raw_hex": "94c30001aa",
                    "data": {"decoded": {"payload": b"abc"}},
                }
            )
            writer.record_serial_text("boot ok")

            session_dirs = list((Path(tmp) / "sessions").iterdir())
            self.assertEqual(len(session_dirs), 1)
            session_dir = session_dirs[0]

            self.assertEqual(_read_json(session_dir / "session.json")["tool"], "meshdebug")
            self.assertEqual(_read_json(Path(tmp) / "latest_session.json")["status"], "active")

            sessions = _db_rows(tmp, "SELECT * FROM capture_sessions;")
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["port"], "COM7")
            self.assertEqual(sessions[0]["baudrate"], 115200)
            self.assertEqual(sessions[0]["status"], "active")

            records = _db_rows(tmp, "SELECT * FROM capture_records ORDER BY id;")
            self.assertEqual([row["record_type"] for row in records], ["from_radio_frame", "serial_text"])

            frame = records[0]
            self.assertEqual(frame["seq"], 1)
            self.assertEqual(frame["raw_frame"].hex(), "94c30001aa")
            self.assertIsNone(frame["raw_hex"])
            parsed = json.loads(frame["parsed_json"])
            self.assertNotIn("raw_hex", parsed)
            self.assertEqual(parsed["data"]["decoded"]["payload"]["base64"], "YWJj")

            text = records[1]
            self.assertEqual(text["text"], "boot ok")
            self.assertIsNone(text["raw_frame"])

    def test_writer_records_sent_frame_and_nodes_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = CaptureWriter(tmp)
            writer.start_session(port="COM8", baudrate=921600)

            writer.record_sent_frame({"variant": "packet", "summary": "send"}, "94c3", summary="packet out")
            writer.write_nodes_snapshot(
                {
                    "!12345678": {
                        "node_id": "!12345678",
                        "long_name": "Gateway",
                        "short_name": "GW",
                        "public_key": b"\x01" * 32,
                        "user": {"long_name": "Gateway"},
                        "join_lock_advertise": {"sn": "SN001"},
                        "last_operation_result": {
                            "operation": "JOIN_NETWORK_V2",
                            "status": "OK",
                            "target_node_id": "!12345678",
                        },
                    }
                },
                local_node_id="!12345678",
            )

            session_dir = next((Path(tmp) / "sessions").iterdir())

            sent = _db_rows(tmp, "SELECT * FROM capture_records WHERE record_type = 'to_radio_frame';")
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["summary"], "packet out")
            self.assertEqual(sent[0]["raw_frame"].hex(), "94c3")

            snapshot = _read_json(session_dir / "nodes_snapshot.json")
            node = snapshot["nodes"]["!12345678"]
            self.assertTrue(node["is_local"])
            self.assertEqual(node["public_key_b64"], "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=")
            self.assertEqual(node["join_lock_advertise"]["sn"], "SN001")
            self.assertEqual(node["last_operation_result"]["operation"], "JOIN_NETWORK_V2")
            self.assertEqual(_read_json(Path(tmp) / "current_nodes.json")["local_node_id"], "!12345678")

            nodes = _db_rows(tmp, "SELECT * FROM capture_nodes;")
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0]["node_id"], "!12345678")
            self.assertEqual(nodes[0]["is_local"], 1)
            db_node = json.loads(nodes[0]["node_json"])
            self.assertEqual(db_node["long_name"], "Gateway")
            self.assertEqual(db_node["last_operation_result"]["status"], "OK")

    def test_stop_session_marks_latest_session_ended(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = CaptureWriter(tmp)
            writer.start_session(port="COM9", baudrate=115200)
            session_id = writer.session_id

            writer.stop_session()

            latest = _read_json(Path(tmp) / "latest_session.json")
            self.assertEqual(latest["session_id"], session_id)
            self.assertEqual(latest["status"], "ended")
            self.assertIsNotNone(latest["ended_at"])
            self.assertFalse(_read_json(Path(tmp) / "current_connection.json")["connected"])

            sessions = _db_rows(tmp, "SELECT * FROM capture_sessions WHERE session_id = ?;", (session_id,))
            self.assertEqual(sessions[0]["status"], "ended")
            self.assertIsNotNone(sessions[0]["ended_at"])


if __name__ == "__main__":
    unittest.main()
