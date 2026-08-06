#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from amazon_export import create_amazon_workbook, _manifest_rows, _is_mixed_packing_row  # noqa: E402
from packing import PackingResult, PackingRow  # noqa: E402

TPL = APP_DIR / "templates" / (
    "ManifestFileUpload_Template_IncludeCasePack_IncludeExpirationDate_IncludeMLC_MPL2.xlsx"
)


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

    @unittest.skipUnless(TPL.is_file(), "template missing")
    def test_write_workbook(self):
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
            create_amazon_workbook(template_source=TPL, output_path=out, result=result)
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
            self.assertIn(ws.cell(header + 2, 5).value, (None, ""))
            self.assertIn(ws.cell(header + 2, 7).value, (None, ""))
            wb.close()


if __name__ == "__main__":
    unittest.main()
