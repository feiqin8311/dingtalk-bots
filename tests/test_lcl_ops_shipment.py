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


if __name__ == "__main__":
    unittest.main()
