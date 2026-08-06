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
from runner import _drop_transient_issues, _retry_pingyi_query_errors  # noqa: E402


def _row(*, fba: str) -> TableRow:
    return TableRow(
        record_id="r1",
        invoice_no="26PM012",
        brand="EZARC",
        country="加拿大",
        carrier="平谊",
        fba_codes=[fba],
        logistics_nos=[],
        eta_date=None,
        delivered_at=None,
        owners=[{"unionId": "u1", "name": "柯鹏翔"}],
    )


class PingyiRetryTests(unittest.TestCase):
    def test_drop_transient_issues(self):
        bucket = [
            ReportItem(
                shipment_key="FBA1",
                event_key="query_error",
                message="fail",
                user_ids=["x"],
            ),
            ReportItem(
                shipment_key="FBA1",
                event_key="py:KC",
                message="ok node",
                user_ids=["x"],
            ),
            ReportItem(
                shipment_key="FBA2",
                event_key="query_error",
                message="other",
                user_ids=["x"],
            ),
        ]
        n = _drop_transient_issues(bucket, "FBA1")
        self.assertEqual(n, 1)
        self.assertEqual([it.event_key for it in bucket], ["py:KC", "query_error"])

    def test_retry_recovers_query_error(self):
        log = logging.getLogger("test_pingyi_retry")
        code = "FBA19FDLLNCM"
        row = _row(fba=code)
        bucket = [
            ReportItem(
                shipment_key=code,
                event_key="query_error",
                message=f"{code} 查询失败",
                user_ids=["17331048354297047"],
                fba_code=code,
                carrier="平谊",
                detail=f"{code} 查询失败：timed out",
            )
        ]
        shipment = TrackShipment(
            reference_no=code,
            tracking_no=code,
            destination_country="",
            track_status="",
            track_status_name="转运中",
            events=[
                TrackEvent(
                    occur_date="2026-07-16",
                    location="",
                    description="船只从始发港离港",
                    track_code="KC",
                    track_status="",
                    track_status_name="",
                )
            ],
        )
        client = MagicMock()
        client.get_track.return_value = shipment

        with tempfile.TemporaryDirectory() as td:
            store = TrackStateStore(Path(td) / "t.sqlite3")
            try:
                stats = _retry_pingyi_query_errors(
                    bucket,
                    [row],
                    pingyi=client,
                    store=store,
                    logger=log,
                    pause_sec=0,
                )
            finally:
                store.close()

        self.assertEqual(stats["pingyi_retry"], 1)
        self.assertEqual(stats["pingyi_recovered"], 1)
        self.assertFalse(any(it.event_key == "query_error" for it in bucket))
        self.assertTrue(any(it.event_key == "py:KC" or "py:KC" in (it.event_keys or []) for it in bucket))
        client.get_track.assert_called_once_with(code)


if __name__ == "__main__":
    unittest.main()
