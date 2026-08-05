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

from excel_export import (  # noqa: E402
    HEADERS,
    ReportItem,
    export_filename,
    format_shipped_at,
    write_report_xlsx,
)
from openpyxl import load_workbook  # noqa: E402
from datetime import datetime  # noqa: E402


class ExcelExportTests(unittest.TestCase):
    def test_export_filename_cn_name_date(self):
        when = datetime(2026, 8, 5, 11, 43, 36)
        self.assertEqual(
            export_filename(user_id="17409662804279906", when=when),
            "乔丹丹_轨迹回传_20260805.xlsx",
        )
        self.assertEqual(
            export_filename(user_id="17331048354297047", when=when),
            "柯鹏翔_轨迹回传_20260805.xlsx",
        )
        self.assertEqual(
            export_filename(user_id="no_owner", when=when),
            "无负责人_轨迹回传_20260805.xlsx",
        )

    def test_headers_order(self):
        self.assertEqual(
            HEADERS,
            (
                "发票号",
                "品牌",
                "国家",
                "FBA编码",
                "物流编号",
                "货代公司",
                "发货时间",
                "预计船期",
                "实际送仓时间",
                "负责人",
                "物流详情",
            ),
        )

    def test_format_shipped_at(self):
        self.assertEqual(format_shipped_at(date(2026, 7, 21)), "2026-07-21")
        self.assertEqual(format_shipped_at(None), "")

    def test_write_report_xlsx(self):
        items = [
            ReportItem(
                shipment_key="FBA1",
                event_key="k1",
                message="FBA1 2026-07-01 离港",
                user_ids=["u1"],
                invoice_no="26YP075",
                brand="YPLUS",
                country="美国",
                fba_code="FBA1",
                logistics_no="",
                carrier="平谊",
                shipped_at="2026-07-21",
                eta_date="2026-08-01",
                delivered_at="",
                owners="芋圆",
                detail="2026-07-01 离港",
            ),
            ReportItem(
                shipment_key="r1",
                event_key="missing_fba",
                message="26LBA22 无FBA编码，无法查询平谊轨迹",
                user_ids=["u1"],
                invoice_no="26LBA22",
                brand="LIBRATON",
                country="美国",
                fba_code="",
                logistics_no="",
                carrier="平谊",
                shipped_at="2026-07-21",
                eta_date="2026-07-30",
                delivered_at="2026-08-02",
                owners="芋圆",
                detail="26LBA22 无FBA编码，无法查询平谊轨迹",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report_xlsx(items, Path(tmp) / "t.xlsx")
            self.assertTrue(path.is_file())
            wb = load_workbook(path)
            ws = wb.active
            self.assertEqual([c.value for c in ws[1]], list(HEADERS))
            self.assertEqual(ws.max_row, 3)
            self.assertEqual(ws["A2"].value, "26YP075")
            self.assertEqual(ws["C2"].value, "美国")
            self.assertEqual(ws["D2"].value, "FBA1")
            self.assertEqual(ws["G2"].value, "2026-07-21")
            self.assertEqual(ws["H2"].value, "2026-08-01")
            self.assertEqual(ws["I2"].value, None)  # openpyxl empty → None
            self.assertEqual(ws["J2"].value, "芋圆")
            self.assertEqual(ws["K2"].value, "2026-07-01 离港")
            self.assertEqual(ws["H3"].value, "2026-07-30")
            self.assertEqual(ws["I3"].value, "2026-08-02")
            self.assertEqual(ws["K3"].value, "26LBA22 无FBA编码，无法查询平谊轨迹")

    def test_multiline_detail_one_cell(self):
        detail = "2026-07-01 离港\n2026-07-10 清关\n2026-07-15 派送中"
        items = [
            ReportItem(
                shipment_key="FBA1",
                event_key="k1",
                message="FBA1 轨迹3条",
                user_ids=["u1"],
                invoice_no="26YP075",
                brand="YPLUS",
                country="美国",
                fba_code="FBA1",
                logistics_no="",
                carrier="平谊",
                shipped_at="2026-07-21",
                owners="乔丹-Joyce",
                detail=detail,
                event_keys=["k1", "k2", "k3"],
            ),
        ]
        self.assertEqual(items[0].keys_to_mark(), ["k1", "k2", "k3"])
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report_xlsx(items, Path(tmp) / "m.xlsx")
            wb = load_workbook(path)
            ws = wb.active
            self.assertEqual(ws.max_row, 2)
            self.assertEqual(ws["K2"].value, detail)
            self.assertTrue(ws["K2"].alignment.wrap_text)


if __name__ == "__main__":
    unittest.main()
