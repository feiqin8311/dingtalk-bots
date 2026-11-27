from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"

from apps.track_notify.dedup_store import TrackStateStore  # noqa: E402
from apps.track_notify.dingtalk_table import TableRow  # noqa: E402
from apps.track_notify.excel_export import ReportItem  # noqa: E402
from apps.track_notify.pingyi_client import TrackEvent, TrackShipment  # noqa: E402
from apps.track_notify.runner import _retry_longzhou_query_errors, _retry_yinghe_query_errors  # noqa: E402


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

    def test_retry_does_not_duplicate_existing_milestone(self):
        log = logging.getLogger("test_retry")
        no = "AL0-RETRY-DUP"
        row = _row(logistics_no=no)
        bucket = [
            ReportItem(
                shipment_key=no,
                event_key="lz:pod",
                message=f"{no} 节点1条",
                user_ids=["17409662804279906"],
                logistics_no=no,
                carrier="龙舟",
                detail="2026-08-01 已到达卸货港",
                event_keys=["lz:pod"],
            ),
            ReportItem(
                shipment_key=no,
                event_key="query_error",
                message=f"{no} 查询失败",
                user_ids=["17331048354297047"],
                logistics_no=no,
                carrier="龙舟",
            ),
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
                _retry_longzhou_query_errors(
                    bucket,
                    [row],
                    gateway=gateway,
                    store=store,
                    logger=log,
                    pause_sec=0,
                )
                from apps.track_notify.runner import _checkpoint_bucket

                _checkpoint_bucket(store, bucket)
                self.assertEqual(store.pending_count(), 1)
            finally:
                store.close()

        self.assertFalse(any(it.event_key == "query_error" for it in bucket))
        self.assertEqual(sum(1 for it in bucket if it.event_key == "lz:pod"), 1)

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

    def test_retry_skipped_when_circuit_open(self):
        log = logging.getLogger("test_retry")
        no = "AL0-CIRCUIT"
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
        gateway.circuit_open = True

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

        self.assertEqual(stats["gateway_retry"], 0)
        gateway.query_longzhou.assert_not_called()
        self.assertEqual(bucket[0].event_key, "query_error")

    def test_retry_aborts_remaining_when_circuit_opens(self):
        log = logging.getLogger("test_retry")
        nos = ["AL0-A", "AL0-B", "AL0-C"]
        rows = [_row(logistics_no=no) for no in nos]
        bucket = [
            ReportItem(
                shipment_key=no,
                event_key="query_error",
                message="fail",
                user_ids=["u"],
                logistics_no=no,
            )
            for no in nos
        ]

        class FakeGw:
            circuit_open = False
            calls = 0

            def query_longzhou(self, *args, **kwargs):
                self.calls += 1
                self.circuit_open = True
                raise TimeoutError("timed out")

        gateway = FakeGw()
        with tempfile.TemporaryDirectory() as td:
            store = TrackStateStore(Path(td) / "t.sqlite3")
            try:
                stats = _retry_longzhou_query_errors(
                    bucket,
                    rows,
                    gateway=gateway,
                    store=store,
                    logger=log,
                    pause_sec=0,
                )
            finally:
                store.close()

        self.assertEqual(stats["gateway_retry"], 3)
        self.assertEqual(gateway.calls, 1)
        self.assertEqual(sum(1 for it in bucket if it.event_key == "query_error"), 3)


class YingheRetryTests(unittest.TestCase):
    def test_retry_recovers_yinghe_query_error(self):
        log = logging.getLogger("test_retry")
        no = "YH260717001"
        row = TableRow(
            record_id="r-yh",
            invoice_no="26YH001",
            brand="YPLUS",
            country="美国",
            carrier="盈和",
            fba_codes=["FBA1"],
            logistics_nos=[no],
            eta_date=None,
            delivered_at=None,
            owners=[{"unionId": "u1", "name": "柯鹏翔"}],
        )
        bucket = [
            ReportItem(
                shipment_key=no,
                event_key="query_error",
                message=f"{no} 查询失败",
                user_ids=["u1"],
                logistics_no=no,
                carrier="盈和",
                detail=f"{no} 查询失败：网关超时",
            )
        ]
        shipment = TrackShipment(
            reference_no=no,
            tracking_no=no,
            destination_country="",
            track_status="",
            track_status_name="已入仓",
            events=[
                TrackEvent(
                    occur_date="2026-08-06",
                    location="",
                    description="POD 已提供,当地时间【8月4日】已入仓，",
                    track_code="",
                    track_status="",
                    track_status_name="",
                )
            ],
        )
        gateway = MagicMock()
        gateway.query_yinghe.return_value = shipment

        with tempfile.TemporaryDirectory() as td:
            store = TrackStateStore(Path(td) / "t.sqlite3")
            try:
                stats = _retry_yinghe_query_errors(
                    bucket,
                    [row],
                    gateway=gateway,
                    store=store,
                    logger=log,
                    pause_sec=0,
                    platform="yinghe",
                )
            finally:
                store.close()

        self.assertEqual(stats["yinghe_retry"], 1)
        self.assertEqual(stats["yinghe_recovered"], 1)
        self.assertFalse(any(it.event_key == "query_error" for it in bucket))
        self.assertTrue(any(it.event_keys for it in bucket))
        gateway.query_yinghe.assert_called_once_with(no, platform="yinghe")


if __name__ == "__main__":
    unittest.main()
