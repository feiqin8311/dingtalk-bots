from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from dedup_store import TrackStateStore  # noqa: E402
from dingtalk_table import TableRow  # noqa: E402
from milestones import filter_new_milestones, match_milestone, milestone_label  # noqa: E402
from pingyi_client import TrackEvent, TrackShipment  # noqa: E402
from runner import _emit_events  # noqa: E402


def _ev(desc: str, *, code: str = "", when: str = "2026-07-01") -> TrackEvent:
    return TrackEvent(
        occur_date=when,
        location="",
        description=desc,
        track_code=code,
        track_status="",
        track_status_name="",
    )


class MatchMilestoneTests(unittest.TestCase):
    def test_pingyi_by_code_and_desc(self):
        self.assertEqual(match_milestone(_ev("x", code="KC"), "pingyi"), "py:KC")
        self.assertEqual(match_milestone(_ev("x", code="DG"), "pingyi"), "py:DG")
        self.assertEqual(match_milestone(_ev("x", code="SC"), "pingyi"), "py:SC")
        self.assertEqual(
            match_milestone(_ev("船只从始发港离港/KC"), "pingyi"),
            "py:KC",
        )
        self.assertEqual(
            match_milestone(_ev("船只到达目的港"), "pingyi"),
            "py:DG",
        )
        self.assertEqual(
            match_milestone(_ev("货件已被完整配送至亚马逊仓库"), "pingyi"),
            "py:SC",
        )
        self.assertIsNone(match_milestone(_ev("货件在国内完成出口报关", code="BG"), "pingyi"))

    def test_longzhou_keywords_flexible_space(self):
        self.assertEqual(
            match_milestone(_ev("出发地 中国宁波"), "longzhou"),
            "lz:ningbo",
        )
        self.assertEqual(
            match_milestone(_ev("出发地：中国宁波"), "longzhou"),
            "lz:ningbo",
        )
        self.assertEqual(match_milestone(_ev("已到达卸货港"), "longzhou"), "lz:pod")
        self.assertEqual(match_milestone(_ev("已提柜"), "longzhou"), "lz:pickup")
        self.assertEqual(
            match_milestone(_ev("货物已送达 FC 场地"), "longzhou"),
            "lz:fc",
        )
        self.assertEqual(
            match_milestone(_ev("货物已送达FC场地"), "longzhou"),
            "lz:fc",
        )
        self.assertIsNone(match_milestone(_ev("海关查验中"), "longzhou"))

    def test_longzhou_bilingual_api_text_still_matches(self):
        # 龙舟 API 常带英文后缀，匹配仍按关键字
        self.assertEqual(
            match_milestone(
                _ev("出发地 中国宁波Departed from 中国宁波"),
                "longzhou",
            ),
            "lz:ningbo",
        )
        self.assertEqual(
            match_milestone(
                _ev("已到达卸货港Arrived at Port of Discharge"),
                "longzhou",
            ),
            "lz:pod",
        )
        self.assertEqual(
            match_milestone(_ev("已提柜Full out-gate"), "longzhou"),
            "lz:pickup",
        )
        self.assertEqual(
            match_milestone(
                _ev("货物已送达 FC 场地Cargo delivered to FC yard"),
                "longzhou",
            ),
            "lz:fc",
        )

    def test_milestone_label_is_chinese_only(self):
        self.assertEqual(milestone_label("lz:ningbo"), "出发地 中国宁波")
        self.assertEqual(milestone_label("lz:pod"), "已到达卸货港")
        self.assertEqual(milestone_label("lz:pickup"), "已提柜")
        self.assertEqual(milestone_label("lz:fc"), "货物已送达 FC 场地")
        self.assertEqual(milestone_label("py:KC"), "船只从始发港离港")

    def test_filter_multiple_and_dedupe_key(self):
        events = [
            _ev("快件电子信息已经收到", code="IR", when="2026-06-01"),
            _ev("船只从始发港离港", code="KC", when="2026-06-10"),
            _ev("船只到达目的港", code="DG", when="2026-07-01"),
            _ev("再次离港文案", code="KC", when="2026-07-02"),  # 同 key 只取首次
        ]
        pairs = filter_new_milestones(events, kind="pingyi")
        self.assertEqual([k for k, _ in pairs], ["py:KC", "py:DG"])
        pairs2 = filter_new_milestones(events, kind="pingyi", already={"py:KC"})
        self.assertEqual([k for k, _ in pairs2], ["py:DG"])


class EmitIncrementalTests(unittest.TestCase):
    def test_emit_only_new_milestones(self):
        logger = logging.getLogger("test_emit")
        row = TableRow(
            record_id="r1",
            invoice_no="26X",
            brand="Y",
            country="美国",
            carrier="龙舟AGL",
            fba_codes=["FBA1"],
            logistics_nos=["AL0"],
            eta_date=None,
            delivered_at=None,
            owners=[{"name": "乔丹丹", "unionId": "u"}],
        )
        shipment = TrackShipment(
            reference_no="AL0",
            tracking_no="AL0",
            destination_country="",
            track_status="",
            track_status_name="",
            events=[
                _ev("出发地 中国宁波Departed from 中国宁波", when="2026-05-01"),
                _ev("已到达卸货港Arrived at Port of Discharge", when="2026-06-01"),
                _ev("海关查验", when="2026-06-10"),
                _ev("已提柜Full out-gate", when="2026-07-01"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = TrackStateStore(Path(tmp) / "s.sqlite3")
            # 模拟周一已推 ningbo + pod
            store.mark_event("AL0", "lz:ningbo", "old")
            store.mark_event("AL0", "lz:pod", "old")
            bucket: list = []
            n = _emit_events(
                row=row,
                shipment=shipment,
                shipment_key="AL0",
                display_code="AL0",
                kind="longzhou",
                user_ids=["uid1"],
                store=store,
                bucket=bucket,
                logger=logger,
            )
            self.assertEqual(n, 1)
            self.assertEqual(len(bucket), 1)
            self.assertEqual(bucket[0].event_keys, ["lz:pickup"])
            self.assertEqual(bucket[0].detail, "2026-07-01 已提柜")
            self.assertNotIn("Full out-gate", bucket[0].detail)
            self.assertNotIn("已到达卸货港", bucket[0].detail)

            # 周三再跑无新节点
            bucket2: list = []
            store.mark_event("AL0", "lz:pickup", "sent")
            n2 = _emit_events(
                row=row,
                shipment=shipment,
                shipment_key="AL0",
                display_code="AL0",
                kind="longzhou",
                user_ids=["uid1"],
                store=store,
                bucket=bucket2,
                logger=logger,
            )
            self.assertEqual(n2, 0)
            self.assertEqual(bucket2, [])
            store.close()

    def test_emit_multiple_new_in_one_cell(self):
        logger = logging.getLogger("test_emit")
        row = TableRow(
            record_id="r2",
            invoice_no="26Y",
            brand="Y",
            country="美国",
            carrier="平谊",
            fba_codes=["FBA9"],
            logistics_nos=[],
            eta_date=None,
            delivered_at=None,
        )
        shipment = TrackShipment(
            reference_no="FBA9",
            tracking_no="PY1",
            destination_country="US",
            track_status="",
            track_status_name="",
            events=[
                _ev("船只从始发港离港", code="KC", when="2026-06-01 10:00:00"),
                _ev("船只到达目的港", code="DG", when="2026-07-01 10:00:00"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = TrackStateStore(Path(tmp) / "s.sqlite3")
            bucket: list = []
            n = _emit_events(
                row=row,
                shipment=shipment,
                shipment_key="FBA9",
                display_code="FBA9",
                kind="pingyi",
                user_ids=["u1"],
                store=store,
                bucket=bucket,
                logger=logger,
            )
            self.assertEqual(n, 1)
            self.assertEqual(bucket[0].event_keys, ["py:KC", "py:DG"])
            self.assertEqual(
                bucket[0].detail,
                "2026-06-01 船只从始发港离港\n2026-07-01 船只到达目的港",
            )
            store.close()


if __name__ == "__main__":
    unittest.main()
