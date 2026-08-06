from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CST = timezone(timedelta(hours=8))


def _utc_sqlite_to_cst_ymd(raw: str) -> str:
    """sqlite datetime('now') is UTC 'YYYY-MM-DD HH:MM:SS' → Asia/Shanghai calendar day."""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        utc_dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return utc_dt.astimezone(CST).strftime("%Y-%m-%d")
    except ValueError:
        return text[:10]


class TrackStateStore:
    """
    - notified_events: 指定业务节点去重（同一单号同一 milestone 只推一次）
    - pending_report_items: 本轮已查出、尚未推送/落盘成功的行（防进程被杀丢结果）
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
        # 查一行记一行：完整 ReportItem JSON，发送/落盘成功后再删
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_report_items (
                shipment_key TEXT NOT NULL,
                event_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (shipment_key, event_key)
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

    def sync_pending_items(self, items: list[dict[str, Any]]) -> None:
        """用当前 bucket 全量覆盖 pending（查一行后调用，崩溃可恢复）。"""
        with self._lock:
            self._conn.execute("DELETE FROM pending_report_items")
            for raw in items:
                sk = str(raw.get("shipment_key") or "")
                ek = str(raw.get("event_key") or "")
                if not sk or not ek:
                    continue
                self._conn.execute(
                    """
                    INSERT INTO pending_report_items (shipment_key, event_key, payload)
                    VALUES (?,?,?)
                    """,
                    (sk, ek, json.dumps(raw, ensure_ascii=False)),
                )
            self._conn.commit()

    def load_pending_items(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM pending_report_items ORDER BY updated_at, shipment_key, event_key"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for (payload,) in rows:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                out.append(data)
        return out

    def discard_pending_if_stale(self, today_ymd: str) -> int:
        """
        跨日丢弃 pending：仅同一业务日（Asia/Shanghai YYYY-MM-DD）可恢复。
        返回丢弃条数；0 表示无 pending 或仍属今日。
        """
        day = (today_ymd or "").strip()
        if not day:
            return 0
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), MAX(updated_at) FROM pending_report_items"
            ).fetchone()
            count = int(row[0] or 0) if row else 0
            if count <= 0:
                return 0
            pending_day = _utc_sqlite_to_cst_ymd(str(row[1] or ""))
            if pending_day == day:
                return 0
            self._conn.execute("DELETE FROM pending_report_items")
            self._conn.commit()
            return count

    def clear_pending_for(self, pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        with self._lock:
            for sk, ek in pairs:
                self._conn.execute(
                    "DELETE FROM pending_report_items WHERE shipment_key=? AND event_key=?",
                    (sk, ek),
                )
            self._conn.commit()

    def clear_all_pending(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pending_report_items")
            self._conn.commit()

    def pending_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM pending_report_items"
            ).fetchone()
            return int(row[0]) if row else 0

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
