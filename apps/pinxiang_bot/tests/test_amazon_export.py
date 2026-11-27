#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]

from apps.pinxiang_bot.amazon_export import (  # noqa: E402
    create_amazon_workbook,
    _manifest_rows,
    _is_mixed_packing_row,
    _use_imperial,
    CM_TO_INCH,
    KG_TO_LB,
)
from apps.pinxiang_bot.packing import PackingResult, PackingRow, Template1Row, process_shipment_file  # noqa: E402

import apps.pinxiang_bot.pinxiang_config as pinxiang_config  # noqa: E402

TPL = pinxiang_config.AMAZON_TEMPLATE_MPL
TPL2 = pinxiang_config.AMAZON_TEMPLATE_MPL2

from .workbook_samples import write_shipment


class AmazonExportTests(unittest.TestCase):
    def test_classify_original_vs_mixed(self):
        self.assertFalse(
            _is_mixed_packing_row(
                PackingRow("W", "A", "A", 288, 36, 8, 14.0, 49, 36, 27, "原箱-整数部分")
            )
        )
        self.assertTrue(
            _is_mixed_packing_row(
                PackingRow("W", "A", "A", 12, 12, 1, 4.8, 20, 20, 41, "余数改箱")
            )
        )

    def test_merge_mixed_sku_qty(self):
        rows = _manifest_rows(
            [
                PackingRow("W", "A", "A", 288, 36, 8, 14.0, 49, 36, 27, "原箱-整数部分"),
                PackingRow("W", "A", "A", 12, 12, 1, 4.8, 20, 20, 41, "余数改箱"),
                PackingRow("W", "A", "A", 6, 6, 1, 2.0, 20, 20, 20, "不足一箱改箱"),
                PackingRow("W", "B", "B", 20, 20, 1, 5.0, 20, 20, 20, "不足一箱改箱"),
            ]
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0].qty, 288)
        self.assertTrue(rows[0][1])
        self.assertEqual(rows[1][0].sku, "A")
        self.assertEqual(rows[1][0].qty, 18)
        self.assertFalse(rows[1][1])
        self.assertEqual(rows[2][0].sku, "B")
        self.assertFalse(rows[2][1])

    def test_write_workbook_fallback_amazon_rows(self):
        result = PackingResult(
            rows=[],
            all_rows=[
                PackingRow("W", "A", "A", 100, 50, 2, 10.0, 40, 30, 20, "原箱"),
                PackingRow("W", "B", "B", 10, 10, 1, 3.0, 20, 20, 20, "不足一箱改箱"),
                PackingRow("W", "B", "B", 5, 5, 1, 1.5, 20, 20, 20, "不足一箱改箱"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m.xlsx"
            create_amazon_workbook(template_source=TPL2, output_path=out, result=result)
            from openpyxl import load_workbook

            wb = load_workbook(out, data_only=True)
            ws = wb["Create workflow – template"]
            header = next(
                r for r in range(1, 15) if ws.cell(r, 1).value == "Merchant SKU"
            )
            # original A with dims
            self.assertEqual(ws.cell(header + 1, 1).value, "A")
            self.assertEqual(ws.cell(header + 1, 2).value, 100)
            self.assertEqual(ws.cell(header + 1, 5).value, 50)
            self.assertIsNotNone(ws.cell(header + 1, 7).value)
            # merged B no dims
            self.assertEqual(ws.cell(header + 2, 1).value, "B")
            self.assertEqual(ws.cell(header + 2, 2).value, 15)

    def test_use_imperial_by_country(self):
        self.assertTrue(_use_imperial("美国"))
        self.assertTrue(_use_imperial("US"))
        self.assertTrue(_use_imperial(""))
        self.assertFalse(_use_imperial("加拿大"))
        self.assertFalse(_use_imperial("Canada"))
        self.assertFalse(_use_imperial("CA"))

    def test_write_workbook_from_template1_sheet(self):
        result = PackingResult(
            country="美国",
            template1_rows=[
                Template1Row(
                    is_full_box=True,
                    country="美国",
                    sku="FULL",
                    qty=100,
                    msku="FULL-M",
                    units_per_box=50,
                    box_count=2,
                    box_weight_kg=10.0,
                    length_cm=40,
                    width_cm=30,
                    height_cm=20,
                ),
                Template1Row(
                    is_full_box=False,
                    country="美国",
                    sku="PART",
                    qty=15,
                    msku="PART-M",
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m.xlsx"
            create_amazon_workbook(template_source=TPL2, output_path=out, result=result)
            from openpyxl import load_workbook

            wb = load_workbook(out, data_only=True)
            ws = wb["Create workflow – template"]
            header = next(
                r for r in range(1, 15) if ws.cell(r, 1).value == "Merchant SKU"
            )
            self.assertEqual(ws.cell(header + 1, 1).value, "FULL-M")
            self.assertEqual(ws.cell(header + 1, 2).value, 100)
            self.assertEqual(ws.cell(header + 1, 5).value, 50)
            self.assertEqual(ws.cell(header + 1, 7).value, round(40 * CM_TO_INCH, 2))
            self.assertEqual(ws.cell(header + 1, 10).value, round(10 * KG_TO_LB, 2))
            self.assertEqual(ws.cell(header + 2, 1).value, "PART-M")
            self.assertEqual(ws.cell(header + 2, 2).value, 15)
            self.assertIn(ws.cell(header + 2, 5).value, (None, ""))

    def test_canada_keeps_metric_units(self):
        result = PackingResult(
            country="加拿大",
            template1_rows=[
                Template1Row(
                    is_full_box=True,
                    country="加拿大",
                    sku="FULL",
                    qty=100,
                    msku="FULL-M",
                    units_per_box=50,
                    box_count=2,
                    box_weight_kg=10.0,
                    length_cm=40,
                    width_cm=30,
                    height_cm=20,
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m.xlsx"
            create_amazon_workbook(template_source=TPL2, output_path=out, result=result)
            from openpyxl import load_workbook

            wb = load_workbook(out, data_only=True)
            ws = wb["Create workflow – template"]
            header = next(
                r for r in range(1, 15) if ws.cell(r, 1).value == "Merchant SKU"
            )
            self.assertEqual(ws.cell(header + 1, 7).value, 40)
            self.assertEqual(ws.cell(header + 1, 8).value, 30)
            self.assertEqual(ws.cell(header + 1, 9).value, 20)
            self.assertEqual(ws.cell(header + 1, 10).value, 10)

    def test_canada_picks_mpl3_shell(self):
        import apps.pinxiang_bot.pinxiang_config as pinxiang_config

        us = pinxiang_config.amazon_template_mpl("美国")
        ca = pinxiang_config.amazon_template_mpl("加拿大")
        self.assertTrue(str(us).endswith("MPL.xlsx"))
        self.assertTrue(str(ca).endswith("MPL3.xlsx"))
        self.assertTrue(pinxiang_config.AMAZON_TEMPLATE_MPL3.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ca.xlsx"
            result = PackingResult(
                country="加拿大",
                template1_rows=[
                    Template1Row(
                        is_full_box=True,
                        country="加拿大",
                        sku="A",
                        qty=50,
                        msku="A",
                        units_per_box=25,
                        box_count=2,
                        box_weight_kg=12.0,
                        length_cm=40,
                        width_cm=30,
                        height_cm=20,
                    )
                ],
            )
            create_amazon_workbook(template_source=ca, output_path=out, result=result)
            from openpyxl import load_workbook

            wb = load_workbook(out, data_only=True)
            ws = wb["Create workflow – template"]
            header = next(r for r in range(1, 15) if ws.cell(r, 1).value == "Merchant SKU")
            # 表头应为 cm/kg
            self.assertIn("(cm)", str(ws.cell(header, 7).value or ""))
            self.assertIn("(kg)", str(ws.cell(header, 10).value or ""))
            self.assertEqual(ws.cell(header + 1, 7).value, 40)
            self.assertEqual(ws.cell(header + 1, 10).value, 12)

    def test_manifest_exports_full_then_partial_from_shipment(self):
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            result = process_shipment_file(write_shipment(folder / "shipment.xlsx"))
            out = folder / "manifest.xlsx"
            create_amazon_workbook(template_source=TPL, output_path=out, result=result)
            wb = load_workbook(out, data_only=True)
            try:
                ws = wb["Create workflow – template"]
                header = next(r for r in range(1, 15) if ws.cell(r, 1).value == "Merchant SKU")
                cells = lambda row: tuple(ws.cell(row, col).value for col in (1, 2, 5, 6, 7, 8, 9, 10))
                self.assertEqual(cells(header + 1), ("M-FULL", 40, 20, 2, 15.75, 11.81, 7.87, 22.05))
                self.assertEqual(cells(header + 2), ("M-PART", 5, None, None, None, None, None, None))
                self.assertIsNone(ws.cell(header + 3, 1).value)
            finally:
                wb.close()


if __name__ == "__main__":
    unittest.main()
