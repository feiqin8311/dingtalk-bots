from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from dedup_store import TrackStateStore  # noqa: E402
from dingtalk_table import TableRow, _split_codes, _ts_to_date  # noqa: E402


class HelpersTests(unittest.TestCase):
    def test_split_codes(self):
        self.assertEqual(
            _split_codes("FBA1\nFBA2\nFBA1"),
            ["FBA1", "FBA2"],
        )

    def test_ts_to_date(self):
        # 2026-07-01 00:00:00 +08
        self.assertEqual(_ts_to_date(1782864000000), date(2026, 7, 1))
        # 表内「发货时间」样例：2026-05-18
        self.assertEqual(_ts_to_date(1779033600000), date(2026, 5, 18))
        # 2025-02-10
        self.assertEqual(_ts_to_date(1739116800000), date(2025, 2, 10))
        self.assertEqual(_ts_to_date(1739116800000).year, 2025)


class StoreTests(unittest.TestCase):
    def test_checked_record_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TrackStateStore(Path(tmp) / "t.sqlite3")
            self.assertFalse(store.is_checked("r1"))
            self.assertTrue(store.mark_checked("r1", carrier="平谊", invoice_no="1"))
            self.assertTrue(store.is_checked("r1"))
            self.assertFalse(store.mark_checked("r1"))
            store.close()


class CarrierKindTests(unittest.TestCase):
    def test_carrier_kind(self):
        from runner import _carrier_kind, _missing_key_line

        self.assertEqual(_carrier_kind("平谊物流"), "pingyi")
        self.assertEqual(_carrier_kind("龙舟AGL"), "longzhou")
        self.assertEqual(_carrier_kind("其他"), "unknown")

    def test_missing_fba_line(self):
        from runner import _missing_key_line, _no_track_line, _query_fail_line

        row = TableRow(
            record_id="r1",
            invoice_no="26LBA22",
            brand="",
            country="",
            carrier="平谊",
            fba_codes=[],
            logistics_nos=[],
            eta_date=None,
            delivered_at=None,
        )
        self.assertEqual(
            _missing_key_line(row, kind="pingyi"),
            "26LBA22 无FBA编码，无法查询平谊轨迹",
        )
        self.assertEqual(
            _no_track_line(row, "FBA19ABC"),
            "26LBA22 FBA19ABC 未查到轨迹",
        )
        self.assertEqual(
            _query_fail_line(row, "FBA19ABC", "timeout"),
            "26LBA22 FBA19ABC 查询失败：timeout",
        )


class NotifyRoutingTests(unittest.TestCase):
    def test_issue_only_kepengxiang(self):
        from owners import KEPENGXIANG_USER_ID, notify_user_ids

        owners = [{"unionId": "iiCcejLysla6iiFFOiPD53DFwiEiE", "name": "乔丹丹"}]
        self.assertEqual(
            notify_user_ids(owners, issue=True),
            [KEPENGXIANG_USER_ID],
        )

    def test_ok_owners_plus_kepengxiang(self):
        from owners import KEPENGXIANG_USER_ID, notify_user_ids

        owners = [{"unionId": "iiCcejLysla6iiFFOiPD53DFwiEiE", "name": "乔丹丹"}]
        uids = notify_user_ids(owners, issue=False)
        self.assertEqual(uids[0], "17409662804279906")  # 乔丹丹
        self.assertIn(KEPENGXIANG_USER_ID, uids)
        self.assertEqual(len(uids), 2)

    def test_ok_no_owner_still_kepengxiang(self):
        from owners import KEPENGXIANG_USER_ID, notify_user_ids

        self.assertEqual(
            notify_user_ids([], issue=False),
            [KEPENGXIANG_USER_ID],
        )


if __name__ == "__main__":
    unittest.main()

