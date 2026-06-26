"""Local capture writer for meshdebug runtime data."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2


def default_capture_root() -> Path:
    return Path(__file__).resolve().parents[2] / "meshdebugdb"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_session_part(value: Any) -> str:
    text = str(value or "unknown").strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "unknown"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {"base64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)


def _raw_hex_to_blob(raw_hex: Any) -> bytes | None:
    text = str(raw_hex or "").strip()
    if not text:
        return None
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None


def _parsed_without_raw_hex(value: dict[str, Any]) -> dict[str, Any]:
    parsed = dict(value)
    parsed.pop("raw_hex", None)
    return parsed


def _node_snapshot_entry(node: dict[str, Any], *, local_node_id: str, updated_at: str) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "node_id": node.get("node_id", ""),
        "long_name": node.get("long_name", ""),
        "short_name": node.get("short_name", ""),
        "last_seen_at": node.get("last_seen_at") or updated_at,
        "source": node.get("source") or [],
        "is_local": bool(node.get("node_id") and node.get("node_id") == local_node_id),
    }

    public_key = node.get("public_key")
    if isinstance(public_key, (bytes, bytearray)) and public_key:
        entry["public_key_b64"] = base64.b64encode(bytes(public_key)).decode("ascii")
    elif isinstance(public_key, str) and public_key:
        entry["public_key_b64"] = public_key

    for key in (
        "user",
        "factory_identity",
        "factory_identity_status",
        "network_config",
        "join_lock",
        "join_lock_advertise",
        "operation_result",
        "last_operation_result",
    ):
        if key in node:
            entry[key] = _jsonable(node[key])

    return entry


class CaptureWriter:
    """SQLite-backed writer for meshdebug capture sessions."""

    def __init__(self, root_dir: str | Path | None = None):
        self.root_dir = Path(root_dir) if root_dir is not None else default_capture_root()
        self.sessions_dir = self.root_dir / "sessions"
        self.db_path = self.root_dir / "meshdebug_capture.db"
        self.enabled = False
        self.session_id = ""
        self.session_dir: Path | None = None
        self.port = ""
        self.baudrate: int | None = None
        self.started_at = ""
        self._frame_seq = 0
        self._text_seq = 0
        self._sent_seq = 0
        self._lock = threading.RLock()
        self.ensure_root()

    def ensure_root(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def set_enabled(self, enabled: bool, *, port: str = "", baudrate: int | None = None) -> None:
        with self._lock:
            if enabled:
                self.enabled = True
                if not self.session_dir:
                    self.start_session(port=port or self.port, baudrate=baudrate or self.baudrate)
            else:
                self.stop_session()
                self.enabled = False

    def start_session(self, *, port: str = "", baudrate: int | None = None) -> str:
        with self._lock:
            self.ensure_root()
            self.port = port or self.port or "unknown"
            self.baudrate = baudrate if baudrate is not None else self.baudrate
            self.started_at = utc_now_iso()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            self.session_id = f"{stamp}_{_safe_session_part(self.port)}_{_safe_session_part(self.baudrate)}"
            self.session_dir = self.sessions_dir / self.session_id
            suffix = 1
            while self.session_dir.exists():
                suffix += 1
                self.session_id = f"{stamp}_{_safe_session_part(self.port)}_{_safe_session_part(self.baudrate)}_{suffix}"
                self.session_dir = self.sessions_dir / self.session_id
            self.session_dir.mkdir(parents=True, exist_ok=False)
            self._frame_seq = 0
            self._text_seq = 0
            self._sent_seq = 0
            self.enabled = True
            self._write_session_metadata(status="active", ended_at=None)
            self._write_latest_session(status="active", ended_at=None)
            self.write_connection_state(connected=True)
            return self.session_id

    def stop_session(self) -> None:
        with self._lock:
            if not self.session_dir:
                return
            ended_at = utc_now_iso()
            self._write_session_metadata(status="ended", ended_at=ended_at)
            self._write_latest_session(status="ended", ended_at=ended_at)
            self.write_connection_state(connected=False, updated_at=ended_at)
            self.session_dir = None
            self.session_id = ""
            self.started_at = ""

    def update_connection(self, *, port: str = "", baudrate: int | None = None, connected: bool | None = None) -> None:
        with self._lock:
            if port:
                self.port = port
            if baudrate is not None:
                self.baudrate = baudrate
            if self.enabled and not self.session_dir and connected:
                self.start_session(port=self.port, baudrate=self.baudrate)
            elif self.session_dir and connected is not None:
                self.write_connection_state(connected=connected)

    def record_received_frame(self, frame: dict[str, Any]) -> None:
        with self._lock:
            if not self.enabled or not self.session_dir:
                return
            self._frame_seq += 1
            data = frame.get("data") if isinstance(frame, dict) else None
            parse_error = data.get("parse_error") if isinstance(data, dict) else None
            self._insert_record(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "from_radio_frame",
                    "session_id": self.session_id,
                    "seq": self._frame_seq,
                    "direction": "from_radio",
                    "received_at": frame.get("received_at") or utc_now_iso(),
                    "port": self.port,
                    "baudrate": self.baudrate,
                    "frame_id": frame.get("id"),
                    "variant": frame.get("variant", ""),
                    "summary": frame.get("summary", ""),
                    "raw_hex": frame.get("raw_hex", ""),
                    "parsed": _jsonable(_parsed_without_raw_hex(frame)),
                    "parse_error": parse_error,
                }
            )

    def record_serial_text(self, text: str) -> None:
        with self._lock:
            if not self.enabled or not self.session_dir or not str(text).strip():
                return
            self._text_seq += 1
            self._insert_record(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "serial_text",
                    "session_id": self.session_id,
                    "seq": self._text_seq,
                    "received_at": utc_now_iso(),
                    "port": self.port,
                    "baudrate": self.baudrate,
                    "text": str(text),
                }
            )

    def record_sent_frame(self, parsed: dict[str, Any], raw_hex: str, *, summary: str = "") -> None:
        with self._lock:
            if not self.enabled or not self.session_dir:
                return
            self._sent_seq += 1
            self._insert_record(
                {
                    "schema_version": SCHEMA_VERSION,
                    "record_type": "to_radio_frame",
                    "session_id": self.session_id,
                    "seq": self._sent_seq,
                    "direction": "to_radio",
                    "sent_at": utc_now_iso(),
                    "port": self.port,
                    "baudrate": self.baudrate,
                    "summary": summary or parsed.get("summary", ""),
                    "raw_hex": raw_hex,
                    "parsed": _jsonable(parsed),
                }
            )

    def write_nodes_snapshot(self, nodes: dict[str, dict[str, Any]], local_node_id: str = "") -> None:
        with self._lock:
            if not self.enabled or not self.session_dir:
                return
            updated_at = utc_now_iso()
            payload = {
                "schema_version": SCHEMA_VERSION,
                "session_id": self.session_id,
                "local_node_id": local_node_id,
                "updated_at": updated_at,
                "nodes": {
                    str(node_id): _node_snapshot_entry(node, local_node_id=local_node_id, updated_at=updated_at)
                    for node_id, node in sorted(nodes.items())
                },
            }
            self._replace_nodes(payload)
            self._write_json(self.session_dir / "nodes_snapshot.json", payload)
            self._write_json(self.root_dir / "current_nodes.json", payload)
            self.write_connection_state(connected=True, local_node_id=local_node_id, updated_at=updated_at)

    def write_connection_state(
        self,
        *,
        connected: bool,
        local_node_id: str = "",
        updated_at: str | None = None,
    ) -> None:
        if not self.enabled and not self.session_dir:
            return
        self._write_json(
            self.root_dir / "current_connection.json",
            {
                "schema_version": SCHEMA_VERSION,
                "connected": connected,
                "port": self.port,
                "baudrate": self.baudrate,
                "local_node_id": local_node_id,
                "session_id": self.session_id,
                "updated_at": updated_at or utc_now_iso(),
            },
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capture_sessions (
                    session_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    tool TEXT NOT NULL,
                    port TEXT,
                    baudrate INTEGER,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    save_enabled_by_user INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capture_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schema_version INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    direction TEXT,
                    event_time TEXT NOT NULL,
                    port TEXT,
                    baudrate INTEGER,
                    frame_id INTEGER,
                    variant TEXT,
                    summary TEXT,
                    raw_hex TEXT,
                    raw_frame BLOB,
                    text TEXT,
                    parsed_json TEXT,
                    parse_error TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, record_type, seq),
                    FOREIGN KEY(session_id) REFERENCES capture_sessions(session_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capture_nodes (
                    session_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_local INTEGER NOT NULL DEFAULT 0,
                    node_json TEXT NOT NULL,
                    PRIMARY KEY(session_id, node_id),
                    FOREIGN KEY(session_id) REFERENCES capture_sessions(session_id)
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_capture_records_session_id ON capture_records(session_id, id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_capture_records_type ON capture_records(record_type, id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_capture_records_variant ON capture_records(variant, id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_capture_records_parse_error ON capture_records(parse_error, id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_capture_records_event_time ON capture_records(event_time);")
            self._migrate_db(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")

    def _migrate_db(self, conn: sqlite3.Connection) -> None:
        record_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(capture_records);").fetchall()
        }
        if "raw_frame" not in record_columns:
            conn.execute("ALTER TABLE capture_records ADD COLUMN raw_frame BLOB;")

    def _write_session_metadata(self, *, status: str, ended_at: str | None) -> None:
        assert self.session_dir is not None
        payload = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "tool": "meshdebug",
            "port": self.port,
            "baudrate": self.baudrate,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "status": status,
            "save_enabled_by_user": True,
        }
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO capture_sessions (
                    session_id, schema_version, tool, port, baudrate,
                    started_at, ended_at, status, save_enabled_by_user
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    ended_at=excluded.ended_at,
                    status=excluded.status,
                    port=excluded.port,
                    baudrate=excluded.baudrate;
                """,
                (
                    self.session_id,
                    SCHEMA_VERSION,
                    "meshdebug",
                    self.port,
                    self.baudrate,
                    self.started_at,
                    ended_at,
                    status,
                    1,
                ),
            )
        self._write_json(self.session_dir / "session.json", payload)

    def _write_latest_session(self, *, status: str, ended_at: str | None) -> None:
        session_dir = f"sessions/{self.session_id}" if self.session_id else ""
        self._write_json(
            self.root_dir / "latest_session.json",
            {
                "schema_version": SCHEMA_VERSION,
                "session_id": self.session_id,
                "session_dir": session_dir,
                "started_at": self.started_at,
                "ended_at": ended_at,
                "status": status,
            },
        )

    def _insert_record(self, record: dict[str, Any]) -> None:
        event_time = record.get("received_at") or record.get("sent_at") or utc_now_iso()
        parsed = record.get("parsed")
        parse_error = record.get("parse_error")
        raw_hex = str(record.get("raw_hex") or "")
        raw_frame = _raw_hex_to_blob(raw_hex)
        raw_hex_for_db = None if raw_frame is not None else (raw_hex or None)
        record_envelope = {
            "schema_version": SCHEMA_VERSION,
            "session_id": record.get("session_id"),
            "record_type": record.get("record_type"),
            "seq": record.get("seq"),
            "direction": record.get("direction"),
            "event_time": event_time,
            "port": record.get("port"),
            "baudrate": record.get("baudrate"),
            "frame_id": record.get("frame_id"),
            "variant": record.get("variant"),
            "summary": record.get("summary"),
            "has_raw_frame": raw_frame is not None,
            "has_parsed_json": parsed is not None,
            "has_text": record.get("text") is not None,
            "parse_error": str(parse_error) if parse_error else None,
        }
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO capture_records (
                    schema_version, session_id, record_type, seq, direction,
                    event_time, port, baudrate, frame_id, variant, summary,
                    raw_hex, raw_frame, text, parsed_json, parse_error, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    SCHEMA_VERSION,
                    record.get("session_id"),
                    record.get("record_type"),
                    record.get("seq"),
                    record.get("direction"),
                    event_time,
                    record.get("port"),
                    record.get("baudrate"),
                    record.get("frame_id"),
                    record.get("variant"),
                    record.get("summary"),
                    raw_hex_for_db,
                    raw_frame,
                    record.get("text"),
                    _json_dumps(parsed) if parsed is not None else None,
                    str(parse_error) if parse_error else None,
                    _json_dumps(record_envelope),
                    utc_now_iso(),
                ),
            )

    def _replace_nodes(self, snapshot: dict[str, Any]) -> None:
        nodes = snapshot.get("nodes") or {}
        with self._transaction() as conn:
            conn.execute("DELETE FROM capture_nodes WHERE session_id = ?;", (self.session_id,))
            conn.executemany(
                """
                INSERT INTO capture_nodes (
                    session_id, node_id, updated_at, is_local, node_json
                ) VALUES (?, ?, ?, ?, ?);
                """,
                [
                    (
                        self.session_id,
                        node_id,
                        snapshot.get("updated_at"),
                        1 if node.get("is_local") else 0,
                        _json_dumps(node),
                    )
                    for node_id, node in nodes.items()
                ],
            )

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(_jsonable(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(path)
