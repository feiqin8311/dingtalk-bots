from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from dedup_store import TrackStateStore  # noqa: E402
from dingtalk_table import TableRow  # noqa: E402
from excel_export import ReportItem  # noqa: E402
from pingyi_client import TrackEvent, TrackShipment  # noqa: E402
from runner import _retry_longzhou_query_errors  # noqa: E402


def _row(*, logistics_no: str, brand: str = "EZARC") -> TableRow:
    return TableRow(
        record_id="r1",
        invoice_no="26EA001",
        brand=brand,
        country="美国",
        carrier="龙舟",
        fba_codes=["FBA1"],
        logistics_nos=[logistics_no],
        eta_date=None,
        delivered_at=None,
        owners=[{"unionId": "iiCcejLysla6iiFFOiPD53DFwiEiE", "name": "乔丹丹"}],
    )


class LongzhouRetryTests(unittest.TestCase):
    def test_retry_recovers_query_error(self):
        log = logging.getLogger("test_retry")
        no = "AL0-RETRY1"
        row = _row(logistics_no=no)
        bucket = [
            ReportItem(
                shipment_key=no,
                event_key="query_error",
                message=f"{no} 查询失败",
                user_ids=["17331048354297047"],
                logistics_no=no,
                carrier="龙舟",
                detail=f"{no} 查询失败：AGL 页面未加载",
            )
        ]
        shipment = TrackShipment(
            reference_no=no,
            tracking_no=no,
            destination_country="",
            track_status="",
            track_status_name="已到达卸货港",
            events=[
                TrackEvent(
                    occur_date="2026-08-01",
                    location="",
                    description="已到达卸货港",
                    track_code="",
                    track_status="",
                    track_status_name="",
                )
            ],
        )
        gateway = MagicMock()
        gateway.query_longzhou.return_value = shipment

        with tempfile.TemporaryDirectory() as td:
            store = TrackStateStore(Path(td) / "t.sqlite3")
            try:
                stats = _retry_longzhou_query_errors(
                    bucket,
                    [row],
                    gateway=gateway,
                    store=store,
                    logger=log,
                    pause_sec=0,
                )
            finally:
                store.close()

        self.assertEqual(stats["gateway_retry"], 1)
        self.assertEqual(stats["gateway_recovered"], 1)
        self.assertFalse(any(it.event_key == "query_error" for it in bucket))
        self.assertTrue(any(it.event_keys for it in bucket))
        gateway.query_longzhou.assert_called_once()

    def test_retry_still_fail_keeps_error(self):
        log = logging.getLogger("test_retry")
        no = "AL0-RETRY2"
        row = _row(logistics_no=no)
        bucket = [
            ReportItem(
                shipment_key=no,
                event_key="query_error",
                message="fail",
                user_ids=["u"],
                logistics_no=no,
            )
        ]
        gateway = MagicMock()
        gateway.query_longzhou.side_effect = RuntimeError("AGL 页面未加载")

        with tempfile.TemporaryDirectory() as td:
            store = TrackStateStore(Path(td) / "t.sqlite3")
            try:
                stats = _retry_longzhou_query_errors(
                    bucket,
                    [row],
                    gateway=gateway,
                    store=store,
                    logger=log,
                    pause_sec=0,
                )
            finally:
                store.close()

        self.assertEqual(stats["gateway_retry"], 1)
        self.assertEqual(stats["gateway_recovered"], 0)
        self.assertEqual(len(bucket), 1)
        self.assertEqual(bucket[0].event_key, "query_error")


if __name__ == "__main__":
    unittest.main()
