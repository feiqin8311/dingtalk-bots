from __future__ import annotations

import re
import threading
from typing import Any, Optional

try:
    import pymysql
except ModuleNotFoundError:  # pragma: no cover - allows router unit tests without DB dependency installed
    pymysql = None  # type: ignore[assignment]


REQUIRED_COLUMNS = {
    "id",
    "created_at",
    "bot_module",
    "event_type",
    "request_id",
    "message_id",
    "user_id",
    "user_name",
    "ack_status",
    "shipment_sns",
    "message_text",
}


class ProjectCallLogStore:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        table: str,
        connect_timeout_sec: int = 5,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.table = _validate_identifier(table, name="table")
        self.connect_timeout_sec = connect_timeout_sec
        self._lock = threading.Lock()
        self._conn: Optional[Any] = None
        self._connect()
        self.assert_schema_ready()

    def _connect(self) -> None:
        if pymysql is None:
            raise RuntimeError("Missing Python dependency: pymysql. Install requirements before enabling MySQL call logging.")
        self._conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=self.connect_timeout_sec,
            read_timeout=30,
            write_timeout=30,
        )

    def _ensure_conn(self) -> Any:
        if self._conn is None:
            self._connect()
            assert self._conn is not None
            return self._conn
        try:
            self._conn.ping(reconnect=True)
        except Exception:
            self._connect()
        assert self._conn is not None
        return self._conn

    def assert_schema_ready(self) -> None:
        conn = self._ensure_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                """,
                (self.database, self.table),
            )
            rows = cur.fetchall()
        existing = {str(row[0]) for row in rows}
        if not existing:
            raise RuntimeError(f"MySQL call log table missing: {self.table}. Please create it before starting the bot.")
        missing = sorted(REQUIRED_COLUMNS - existing)
        if missing:
            raise RuntimeError(
                f"MySQL call log table {self.table} missing columns: {', '.join(missing)}. "
                "Please apply the project call log schema."
            )

    def log_event(
        self,
        *,
        bot_module: str,
        event_type: str,
        request_id: Optional[str] = None,
        message_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        ack_status: Optional[str] = None,
        shipment_sns: Optional[str] = None,
        message_text: Optional[str] = None,
    ) -> None:
        safe_bot_module = (str(bot_module or "").strip() or "unknown")[:32]
        safe_event_type = (str(event_type or "").strip().upper() or "UNKNOWN")[:64]
        safe_user_id = (str(user_id or "").strip() or "UNKNOWN")[:64]
        safe_user_name = (str(user_name or "").strip() or None)
        if safe_user_name:
            safe_user_name = safe_user_name[:128]
        with self._lock:
            conn = self._ensure_conn()
            with conn.cursor() as cur:
                try:
                    conn.begin()
                    cur.execute(
                        f"""
                        INSERT INTO `{self.table}`
                        (bot_module, event_type, request_id, message_id, user_id, user_name, ack_status, shipment_sns, message_text)
                        VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            safe_bot_module,
                            safe_event_type,
                            _truncate(request_id, 128),
                            _truncate(message_id, 128),
                            safe_user_id,
                            safe_user_name,
                            _truncate(ack_status, 64),
                            shipment_sns or None,
                            message_text or None,
                        ),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None



def _validate_identifier(value: str, *, name: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", text):
        raise RuntimeError(f"Invalid MySQL {name} identifier: {text!r}")
    return text
