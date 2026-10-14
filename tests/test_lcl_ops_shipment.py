from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "apps") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps"))

from lcl_bot.handlers import WorkflowBotHandler  # noqa: E402


class LclOpsShipmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.h = WorkflowBotHandler.__new__(WorkflowBotHandler)

    def test_shipment_workbook_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "发货单.xlsx"
            with pd.ExcelWriter(path) as writer:
                pd.DataFrame({"SKU": [1]}).to_excel(writer, sheet_name="发货单详情", index=False)
                pd.DataFrame({"SKU": [1]}).to_excel(writer, sheet_name="装箱信息", index=False)
            self.assertTrue(self.h._looks_like_shipment_workbook(str(path)))
            self.assertFalse(self.h._looks_like_lcl_packing_result(str(path)))

    def test_packing_result_is_not_shipment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "拼箱.xlsx"
            with pd.ExcelWriter(path) as writer:
                pd.DataFrame({"SKU": [1]}).to_excel(writer, sheet_name="拼箱计算结果", index=False)
            self.assertFalse(self.h._looks_like_shipment_workbook(str(path)))
            self.assertTrue(self.h._looks_like_lcl_packing_result(str(path)))

    def test_ops_who_uploaded_shipment_acts_as_logistics(self):
        self.h.state_manager = SimpleNamespace(get_logistics_user_id=lambda: "ops1")
        msg = SimpleNamespace(sender_id="ops1", sender_user_id="ops1", sender_staff_id="ops1")
        self.assertTrue(self.h._acting_as_logistics(msg, "operation"))
        other = SimpleNamespace(sender_id="x", sender_user_id="x", sender_staff_id="x")
        self.assertFalse(self.h._acting_as_logistics(other, "operation"))
        self.assertTrue(self.h._acting_as_logistics(other, "logistics"))

    def _write_packing_result(self, path: Path, rows: dict) -> None:
        pd.DataFrame(rows).to_excel(path, sheet_name="拼箱计算结果", index=False)

    def test_modified_packing_result_fills_merged_actual_box_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "拼箱数据.xlsx"
            self._write_packing_result(
                path,
                {
                    "SKU": ["804020", "804011", "804016", "80BHS016"],
                    "发货仓库（单据）": ["杭州虚拟仓"] * 4,
                    "发货数量": [400, 150, 700, 300],
                    "是否拼箱": ["拼箱", "拼箱", "拼箱", "不拼箱"],
                    "单份数量": [80, 30, 100, 6],
                    "小组名称": ["杭州虚拟仓-第1组", None, "杭州虚拟仓-第3组", "杭州虚拟仓-单独装箱"],
                    "实际箱数": [5, None, None, 50],
                    "单箱重量": [17975.28, None, 12640, 12400],
                    "单箱理论长": [32, None, 29, 41.5],
                    "单箱理论宽": [25, None, 38, 30],
                    "单箱理论高": [54.94, None, 31, 27.8],
                },
            )
            out = self.h._load_modified_packing_result(str(path))

        by_sku = out.set_index("SKU")
        self.assertEqual(by_sku.loc["804011", "实际箱数"], 5)
        self.assertEqual(by_sku.loc["804016", "实际箱数"], 7)
        self.assertEqual(by_sku.loc["80BHS016", "实际箱数"], 50)
        self.assertEqual(by_sku.loc["804011", "小组名称"], "杭州虚拟仓-第1组")
        self.assertEqual(by_sku.loc["804016", "小组名称"], "杭州虚拟仓-第3组")


if __name__ == "__main__":
    unittest.main()
