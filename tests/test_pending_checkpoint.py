from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from dedup_store import CST, TrackStateStore, _utc_sqlite_to_cst_ymd  # noqa: E402
from excel_export import ReportItem  # noqa: E402
from runner import _checkpoint_bucket, _item_from_dict  # noqa: E402


class PendingCheckpointTests(unittest.TestCase):
    def test_checkpoint_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.sqlite3"
            store = TrackStateStore(db)
            items = [
                ReportItem(
                    shipment_key="AL0-1",
                    event_key="lz:pod",
                    message="m",
                    user_ids=["u1", "u2"],
                    detail="已到达卸货港",
                    event_keys=["lz:pod"],
                ),
                ReportItem(
                    shipment_key="AL0-2",
                    event_key="query_error",
                    message="fail",
                    user_ids=["u1"],
                ),
            ]
            _checkpoint_bucket(store, items)
            self.assertEqual(store.pending_count(), 2)
            store.close()

            store2 = TrackStateStore(db)
            loaded = store2.load_pending_items()
            self.assertEqual(len(loaded), 2)
            restored = [_item_from_dict(r) for r in loaded]
            self.assertEqual(restored[0].shipment_key, "AL0-1")
            self.assertEqual(restored[0].user_ids, ["u1", "u2"])
            self.assertEqual(restored[0].event_keys, ["lz:pod"])
            store2.clear_pending_for([("AL0-1", "lz:pod")])
            self.assertEqual(store2.pending_count(), 1)
            store2.clear_all_pending()
            self.assertEqual(store2.pending_count(), 0)
            store2.close()

    def test_discard_pending_if_stale_same_day_keeps(self):
        with tempfile.TemporaryDirectory() as td:
            store = TrackStateStore(Path(td) / "t.sqlite3")
            _checkpoint_bucket(
                store,
                [
                    ReportItem(
                        shipment_key="A",
                        event_key="k",
                        message="m",
                        user_ids=["u1"],
                    )
                ],
            )
            today = datetime.now(tz=CST).strftime("%Y-%m-%d")
            self.assertEqual(store.discard_pending_if_stale(today), 0)
            self.assertEqual(store.pending_count(), 1)
            store.close()

    def test_discard_pending_if_stale_cross_day_clears(self):
        with tempfile.TemporaryDirectory() as td:
            store = TrackStateStore(Path(td) / "t.sqlite3")
            _checkpoint_bucket(
                store,
                [
                    ReportItem(
                        shipment_key="A",
                        event_key="k",
                        message="m",
                        user_ids=["u1"],
                    )
                ],
            )
            # force updated_at to yesterday UTC so CST day != today
            yesterday_utc = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            store._conn.execute(
                "UPDATE pending_report_items SET updated_at=?",
                (yesterday_utc,),
            )
            store._conn.commit()
            today = datetime.now(tz=CST).strftime("%Y-%m-%d")
            self.assertEqual(store.discard_pending_if_stale(today), 1)
            self.assertEqual(store.pending_count(), 0)
            store.close()

    def test_utc_sqlite_to_cst_ymd_boundary(self):
        # 2026-08-05 16:00 UTC = 2026-08-06 00:00 CST
        self.assertEqual(_utc_sqlite_to_cst_ymd("2026-08-05 16:00:00"), "2026-08-06")
        self.assertEqual(_utc_sqlite_to_cst_ymd("2026-08-05 15:59:00"), "2026-08-05")


if __name__ == "__main__":
    unittest.main()
