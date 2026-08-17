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


class ScheduleAndDeliverTests(unittest.TestCase):
    def test_next_run_at_mon_wed_0700_and_catchup(self):
        from main import SCHEDULE_HOUR, _next_run_at

        self.assertEqual(SCHEDULE_HOUR, 7)
        mon_before = datetime(2026, 8, 3, 6, 59, 0, tzinfo=CST)
        self.assertEqual(
            _next_run_at(mon_before, last_run_ymd=None),
            datetime(2026, 8, 3, 7, 0, 0, tzinfo=CST),
        )
        mon_late = datetime(2026, 8, 3, 7, 5, 0, tzinfo=CST)
        self.assertEqual(_next_run_at(mon_late, last_run_ymd=None), mon_late)
        self.assertEqual(
            _next_run_at(mon_late, last_run_ymd="2026-08-03"),
            datetime(2026, 8, 5, 7, 0, 0, tzinfo=CST),
        )

    def test_deliver_defers_mark_until_all_recipients_ok(self):
        from unittest.mock import MagicMock

        from runner import _deliver_excel_reports
        from settings import TrackNotifyConfig

        def _cfg(state_dir: Path) -> TrackNotifyConfig:
            return TrackNotifyConfig(
                pingyi_base_url="",
                pingyi_app_token="",
                pingyi_app_key="",
                pingyi_timeout_sec=60.0,
                pingyi_retries=1,
                meitong_base_url="",
                meitong_username="",
                meitong_password="",
                meitong_timeout_sec=30.0,
                meitong_retries=1,
                gateway_base_url="",
                gateway_api_key="",
                gateway_timeout_sec=60.0,
                gateway_max_concurrent=1,
                gateway_min_interval_sec=0.0,
                dingtalk_doc_key="x",
                dingtalk_sheet_id="x",
                dingtalk_view_id="x",
                operator_union_id="x",
                ding_client_id="k",
                ding_client_secret="s",
                ding_robot_code="r",
                carrier_keywords=("平谊", "龙舟"),
                ship_year=2026,
                state_dir=state_dir,
                query_workers=1,
                send_excel=True,
            )

        def _install_notifier(notifier: MagicMock) -> None:
            fake_mod = MagicMock()
            fake_mod.DingTalkNotifier = MagicMock(return_value=notifier)
            sys.modules["api"] = type(sys)("api")
            sys.modules["api.dingtalk_client"] = fake_mod

        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            store = TrackStateStore(state_dir / "t.sqlite3")
            item = ReportItem(
                shipment_key="AL0-1",
                event_key="lz:pod",
                message="m",
                user_ids=["u1", "u2"],
                detail="2026-08-01 已到达卸货港",
                event_keys=["lz:pod"],
            )
            config = _cfg(state_dir)

            notifier = MagicMock()
            notifier.send_user_file.side_effect = lambda uid, _p: (
                (_ for _ in ()).throw(RuntimeError("send fail")) if uid == "u2" else None
            )
            _install_notifier(notifier)
            stats = _deliver_excel_reports(
                [item], config=config, store=store, dry_run=False, logger=MagicMock()
            )
            self.assertGreaterEqual(stats["excel_failed"], 1)
            self.assertEqual(stats["excel_mark_deferred"], 1)
            self.assertFalse(store.has_event("AL0-1", "lz:pod"))

            _install_notifier(MagicMock())
            stats2 = _deliver_excel_reports(
                [item], config=config, store=store, dry_run=False, logger=MagicMock()
            )
            self.assertEqual(stats2["excel_sent"], 2)
            self.assertEqual(stats2["excel_mark_deferred"], 0)
            self.assertTrue(store.has_event("AL0-1", "lz:pod"))
            store.close()


if __name__ == "__main__":
    unittest.main()
