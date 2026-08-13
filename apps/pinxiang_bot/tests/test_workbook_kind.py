from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from handler import PinxiangBotHandler  # noqa: E402


def _xlsx_with_sheets(*names: str) -> Path:
    wb = Workbook()
    first = True
    for name in names:
        if first:
            wb.active.title = name
            first = False
        else:
            wb.create_sheet(name)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    path = Path(tmp.name)
    wb.save(path)
    return path


class WorkbookKindTests(unittest.TestCase):
    def test_pinxiang_result_sheet(self):
        path = _xlsx_with_sheets("拼箱结果")
        self.addCleanup(path.unlink, missing_ok=True)
        self.assertTrue(PinxiangBotHandler._looks_like_packing_result(path))
        self.assertFalse(PinxiangBotHandler._looks_like_lcl_packing_result(path))

    def test_lcl_result_sheet_is_not_shipment(self):
        path = _xlsx_with_sheets("拼箱计算结果")
        self.addCleanup(path.unlink, missing_ok=True)
        self.assertFalse(PinxiangBotHandler._looks_like_packing_result(path))
        self.assertTrue(PinxiangBotHandler._looks_like_lcl_packing_result(path))


if __name__ == "__main__":
    unittest.main()
