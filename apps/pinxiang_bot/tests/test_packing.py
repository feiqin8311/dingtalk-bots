#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拼箱算法单测（独立于 dingtalk-lcl-bot）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from amazon_export import create_amazon_workbook  # noqa: E402
from packing import LineItem, compute_packing, process_shipment_file, write_packing_workbook  # noqa: E402

SAMPLE_SHIPMENT = Path("/Users/kerden/Desktop/不分仓拼箱/参考表格/发货单-938438362569883648.xlsx")
TEMPLATE = APP_DIR / "templates" / (
    "ManifestFileUpload_Template_IncludeCasePack_IncludeExpirationDate_IncludeMLC_MPL2.xlsx"
)


class PackingLogicTests(unittest.TestCase):
    def test_partial_under_one_box(self):
        item = LineItem(
            shipment_sn="SP1",
            warehouse="青山湖仓库",
            sku="801905N",
            msku="801905",
            product_name="x",
            qty=20,
            units_per_box=40,
            box_weight_kg=17.5,
            length_cm=44,
            width_cm=33.5,
            height_cm=24,
        )
        result = compute_packing([item])
        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(row.qty, 20)
        self.assertEqual(row.units_per_box, 20)
        self.assertEqual(row.box_count, 1)
        self.assertAlmostEqual(row.box_weight_kg, 8.75, places=2)

    def test_non_integer_split_full_and_remainder(self):
        item = LineItem(
            shipment_sn="SP1",
            warehouse="青山湖仓库",
            sku="80376351F1",
            msku="80376351F1",
            product_name="x",
            qty=235,
            units_per_box=60,
            box_weight_kg=17.5,
            length_cm=54,
            width_cm=31,
            height_cm=18,
        )
        result = compute_packing([item])
        by_remark = {r.remark: r for r in result.rows}
        self.assertIn("原箱-整数部分", by_remark)
        self.assertIn("余数改箱", by_remark)
        full = by_remark["原箱-整数部分"]
        rem = by_remark["余数改箱"]
        self.assertEqual(full.qty, 180)
        self.assertEqual(full.units_per_box, 60)
        self.assertEqual(full.box_count, 3)
        self.assertEqual(rem.qty, 55)
        self.assertEqual(rem.units_per_box, 55)
        self.assertEqual(rem.box_count, 1)

    def test_integer_boxes_excluded_from_packing_sheet(self):
        item = LineItem(
            shipment_sn="SP1",
            warehouse="WH",
            sku="A",
            msku="A",
            product_name="",
            qty=100,
            units_per_box=20,
            box_weight_kg=10,
            length_cm=30,
            width_cm=20,
            height_cm=15,
        )
        result = compute_packing([item])
        # 整箱不进拼箱结果表，只进 all_rows（亚马逊）
        self.assertEqual(len(result.rows), 0)
        self.assertEqual(len(result.all_rows), 1)
        self.assertEqual(result.all_rows[0].remark, "原箱")
        self.assertEqual(result.all_rows[0].box_count, 5)

    @unittest.skipUnless(SAMPLE_SHIPMENT.is_file(), "sample shipment not on this machine")
    def test_sample_shipment_file(self):
        result = process_shipment_file(SAMPLE_SHIPMENT)
        # 拼箱结果仅非整箱相关行（参考表只有 3 行量级）
        self.assertEqual(len(result.rows), 3)
        skus = {r.sku for r in result.rows}
        self.assertEqual(skus, {"801905N", "80376351F1"})
        partial = [r for r in result.rows if r.sku == "801905N"]
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial[0].units_per_box, 20)
        rem_rows = [r for r in result.rows if r.sku == "80376351F1" and r.remark == "余数改箱"]
        full_rows = [r for r in result.rows if r.sku == "80376351F1" and "整数" in r.remark]
        self.assertEqual(len(full_rows), 1)
        self.assertEqual(full_rows[0].qty, 180)
        self.assertEqual(len(rem_rows), 1)
        self.assertEqual(rem_rows[0].qty, 55)
        # 全量含原箱，多于结果表
        self.assertGreater(len(result.all_rows), len(result.rows))

        with tempfile.TemporaryDirectory() as tmp:
            out = write_packing_workbook(result, Path(tmp) / "out.xlsx")
            self.assertTrue(out.is_file())
            if TEMPLATE.is_file():
                amazon = create_amazon_workbook(
                    template_source=TEMPLATE,
                    output_path=Path(tmp) / "amazon.xlsx",
                    result=result,
                )
                self.assertTrue(amazon.is_file())


if __name__ == "__main__":
    unittest.main()
