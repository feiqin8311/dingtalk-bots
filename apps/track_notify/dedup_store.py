from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class TrackStateStore:
    """
    - notified_events: 指定业务节点去重（同一单号同一 milestone 只推一次）
    - checked_records: 遗留表（方案 A 整行跳过已废弃，仍可手工查）
    Thread-safe for concurrent row queries (AGL is slow; we parallelize).
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # check_same_thread=False: workers share one conn under self._lock
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notified_events (
                shipment_key TEXT NOT NULL,
                event_key TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (shipment_key, event_key)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checked_records (
                record_id TEXT PRIMARY KEY,
                carrier TEXT,
                invoice_no TEXT,
                checked_at TEXT NOT NULL DEFAULT (datetime('now')),
                note TEXT
            )
            """
        )
        self._conn.commit()

    def is_checked(self, record_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM checked_records WHERE record_id=? LIMIT 1",
                (record_id,),
            ).fetchone()
            return row is not None

    def mark_checked(
        self,
        record_id: str,
        *,
        carrier: str = "",
        invoice_no: str = "",
        note: str = "",
    ) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO checked_records (record_id, carrier, invoice_no, note)
                    VALUES (?,?,?,?)
                    """,
                    (record_id, carrier, invoice_no, note),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def has_event(self, shipment_key: str, event_key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM notified_events WHERE shipment_key=? AND event_key=? LIMIT 1",
                (shipment_key, event_key),
            ).fetchone()
            return row is not None

    def mark_event(self, shipment_key: str, event_key: str, message: str) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO notified_events (shipment_key, event_key, message) VALUES (?,?,?)",
                    (shipment_key, event_key, message),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    # 兼容旧名
    def has(self, shipment_key: str, event_key: str) -> bool:
        return self.has_event(shipment_key, event_key)

    def mark(self, shipment_key: str, event_key: str, message: str) -> bool:
        return self.mark_event(shipment_key, event_key, message)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# 旧 import 兼容
NotifiedEventStore = TrackStateStore
